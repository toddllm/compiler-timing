"""
Sweep harness for the PR #3806 OpSpec-tiling test_flash workload.

Reproduces the compile path of
``tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash``
but parameterized on ``Lq`` and ``Lk`` for the scaling study.

Contract for callers (usually ``run_sweep.py``):

- One point per invocation. Fresh process per invocation is what makes it
  a cold compile — do NOT loop across points inside one process.
- ``TORCH_SPYRE_TIMING=1`` and a per-run ``TORCHINDUCTOR_CACHE_DIR``
  must be set by the caller before invoking this. This module refuses
  to run if either is missing so we can never accidentally publish a
  warm-cache number.
- Writes ``$SPYRE_TIMING_OUT`` at the end containing the full JSON
  timing dump plus graph-size metrics.

Correctness: retains the exact ``flash`` closure body from the test file,
so the compiled path is the same one exercised by pytest. CPU-reference
comparison is optional (``COMPARE_CPU=1``) and NEVER runs inside the
timed region.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
import time
from typing import Any

import torch  # noqa: E402  — needed at module scope for the closure below


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"FATAL: {name} must be set (cold-compile hygiene). Aborting.",
              file=sys.stderr)
        sys.exit(2)
    return v


def build_flash_closure(B: int, H: int, D: int, Lq: int, Lk: int,
                        b_block_size: int, h_block_size: int,
                        q_block_size: int, kv_block_size: int):
    """Verbatim copy of the flash function in test_opspec_tiling.py, with
    the tiling constants captured in a closure so the compiler sees the
    same statically unrolled loop structure."""

    def flash(queries, keys, values, mask):
        scale = 1.0 / math.sqrt(math.sqrt(D))

        output = torch.zeros_like(queries)

        real_max = torch.full(
            (B, H, Lq, 64),
            float("-inf"),
            device=queries.device,
            dtype=torch.float16,
        ).amax(-1)

        denominator = torch.zeros(
            (B, H, Lq, 64), device=queries.device, dtype=torch.float16
        ).amax(-1)

        for b_start in range(0, B, b_block_size):
            b_end = b_start + b_block_size
            for h_start in range(0, H, h_block_size):
                h_end = h_start + h_block_size

                for lq_start in range(0, Lq, q_block_size):
                    lq_end = lq_start + q_block_size
                    queries_tile = queries[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]
                    real_max_tile = real_max[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]
                    denominator_tile = denominator[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]
                    output_tile = output[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]

                    for lk_start in range(0, Lk, kv_block_size):
                        lk_end = lk_start + kv_block_size
                        mask_tile = mask[:, :, lq_start:lq_end, lk_start:lk_end]
                        keys_tile = keys[
                            b_start:b_end, h_start:h_end, lk_start:lk_end
                        ]
                        values_tile = values[
                            b_start:b_end, h_start:h_end, lk_start:lk_end
                        ]
                        keys_tile_T = keys_tile.transpose(-1, -2).contiguous()

                        scores = torch.matmul(
                            queries_tile * scale, keys_tile_T * scale
                        )
                        scores = scores + mask_tile
                        block_max = torch.amax(scores, dim=-1)
                        running_max = torch.maximum(real_max_tile, block_max)

                        exp_scores = torch.exp(
                            scores - running_max.unsqueeze(-1)
                        )
                        correction = torch.exp(real_max_tile - running_max)

                        denominator_tile.copy_(
                            denominator_tile * correction + exp_scores.sum(dim=-1)
                        )
                        output_tile.copy_(
                            output_tile * correction.unsqueeze(-1)
                            + torch.matmul(exp_scores, values_tile)
                        )
                        real_max_tile.copy_(running_max)

        return output / denominator.unsqueeze(-1)

    return flash


def predicted_inner_bodies(B: int, H: int, Lq: int, Lk: int,
                           b_block_size: int, h_block_size: int,
                           q_block_size: int, kv_block_size: int) -> int:
    return ((B // b_block_size)
            * (H // h_block_size)
            * (Lq // q_block_size)
            * (Lk // kv_block_size))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--Lq", type=int, required=True)
    ap.add_argument("--Lk", type=int, required=True)
    ap.add_argument("--B", type=int, default=1)
    ap.add_argument("--H", type=int, default=8)
    ap.add_argument("--D", type=int, default=128)
    ap.add_argument("--b-block-size", type=int, default=1)
    ap.add_argument("--h-block-size", type=int, default=4)
    ap.add_argument("--q-block-size", type=int, default=256)
    ap.add_argument("--kv-block-size", type=int, default=512)
    ap.add_argument("--out", type=str, required=True,
                    help="Path to write the timing JSON dump.")
    ap.add_argument("--compare-cpu", action="store_true",
                    help="Also run CPU reference for correctness check "
                         "(happens OUTSIDE the timed region).")
    args = ap.parse_args()

    # Cold-cache hygiene.
    _require_env("TORCHINDUCTOR_CACHE_DIR")
    if os.environ.get("TORCH_SPYRE_TIMING") != "1":
        # Instrumentation is opt-in; we require it here so we never publish an
        # un-instrumented number by mistake.
        print("FATAL: TORCH_SPYRE_TIMING=1 required.", file=sys.stderr)
        sys.exit(2)

    # torch already imported at module top for the flash() closure. Now register
    # the "spyre" device by importing torch_spyre.
    import torch_spyre  # noqa: F401
    from torch_spyre._inductor import timing_recorder  # type: ignore

    # ---- meta ----
    timing_recorder.set_run_meta(
        workload="pr3806_test_flash",
        Lq=args.Lq, Lk=args.Lk,
        B=args.B, H=args.H, D=args.D,
        b_block_size=args.b_block_size,
        h_block_size=args.h_block_size,
        q_block_size=args.q_block_size,
        kv_block_size=args.kv_block_size,
        predicted_inner_bodies=predicted_inner_bodies(
            args.B, args.H, args.Lq, args.Lk,
            args.b_block_size, args.h_block_size,
            args.q_block_size, args.kv_block_size,
        ),
        TORCHINDUCTOR_CACHE_DIR=os.environ["TORCHINDUCTOR_CACHE_DIR"],
        SENCORES=os.environ.get("SENCORES", "<unset>"),
        pod=os.environ.get("HOSTNAME", "<unknown>"),
    )

    # ---- build the workload ----
    torch.manual_seed(0xAFFE)
    flash = build_flash_closure(
        args.B, args.H, args.D, args.Lq, args.Lk,
        args.b_block_size, args.h_block_size,
        args.q_block_size, args.kv_block_size,
    )

    queries_t = torch.randn(args.B, args.H, args.Lq, args.D, dtype=torch.float16)
    keys_t = torch.randn(args.B, args.H, args.Lk, args.D, dtype=torch.float16)
    values_t = torch.randn(args.B, args.H, args.Lk, args.D, dtype=torch.float16)
    causal = torch.tril(torch.ones(args.Lq, args.Lk, dtype=torch.bool))
    mask_t = torch.zeros(1, 1, args.Lq, args.Lk, dtype=torch.float16)
    mask_t.masked_fill_(~causal, float("-inf"))

    # ---- device warmup (before starting the compile timer) ----
    # First `.to("spyre")` triggers lazy runtime init; we do NOT want that in
    # the compile-time measurement.
    with timing_recorder.stage("device_init_and_transfer"):
        queries_s = queries_t.to("spyre")
        keys_s = keys_t.to("spyre")
        values_s = values_t.to("spyre")
        mask_s = mask_t.to(device="spyre")

    # Encourage a clean starting state before the compile timer.
    gc.collect()

    # ---- the cold compile itself ----
    flash_spyre = torch.compile(flash)
    with timing_recorder.stage("first_call_wall"):
        attn_s = flash_spyre(queries_s, keys_s, values_s, mask_s)

    # ---- optional CPU reference (outside timing) ----
    if args.compare_cpu:
        attn_cpu = flash(queries_t, keys_t, values_t, mask_t)
        torch.testing.assert_close(attn_cpu, attn_s.cpu(), atol=0.1, rtol=0.1)
        timing_recorder.set_run_meta(cpu_reference_ok=True)

    # ---- finalize ----
    timing_recorder.dump_and_finalize(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
