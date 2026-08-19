"""
Sweep harness for the PR #3812 KV-chunked FlashAttention workload.

Reproduces the compile path of ``_run_kv_chunked_flash`` from
``tests/inductor/test_coarse_tile_e2e.py`` (added in PR #3812) but as a
standalone harness so we can drive it under `TORCH_SPYRE_TIMING=1` and
record the full timing JSON schema our study already understands.

Contract with callers:

- One point per invocation. Fresh process per invocation is what makes it
  a cold compile.
- ``TORCH_SPYRE_TIMING=1`` and a per-run ``TORCHINDUCTOR_CACHE_DIR`` must
  be set by the caller.
- Writes ``$SPYRE_TIMING_OUT`` at the end containing the full JSON timing
  dump plus graph-size metrics.

Four load-bearing details from the PR's test docstring; each one produced
a wrong answer or hard error while the test was being written:

1. K loop must sit inside a single H/Lq scope — one WSR scope for the whole
   sweep. Per-chunk scopes cause validate_coarse_tile_groups to reject the
   layout with "hint_id=N appears in both group X and group Y".
2. K/V chunks must be sliced by the CALLER and passed in as named tensors.
   Slicing inside the graph silently fails to name the results.
3. Carry inits use the sparse idiom ``torch.full((B,H,Lq,64), val).amax(-1)``.
   A plain 3-D ``full((B,H,Lq))`` raises "no mechanism to resolve stick
   incompatibility".
4. Final divide must be inside the innermost scope (#3429); read past the
   loop group it becomes a full buffer plus a copy op whose target a second
   consumer also reads, and finalize_layouts overwrites it.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
from typing import Any

import torch  # module-scope for the closure below


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"FATAL: {name} must be set (cold-compile hygiene). Aborting.",
              file=sys.stderr)
        sys.exit(2)
    return v


def build_kvchunk_flash(
    B: int,
    H: int,
    D: int,
    Lq: int,
    kv_block: int,
    n_chunks: int,
    h_tiles: int,
    lq_tiles: int | None,
):
    """Return a ``flash(queries, k_chunks, v_chunks)`` closure that Dynamo
    will unroll into an n_chunks-body KV-sweep graph with a single H/Lq
    WSR scope wrapping the whole sweep."""

    from torch_spyre._inductor import spyre_hint

    scale = 1.0 / math.sqrt(math.sqrt(D))

    def flash(queries, k_chunks, v_chunks):
        with spyre_hint(named_dims=["B", "H", "Lq"]):
            running_max = torch.full(
                (B, H, Lq, 64), float("-inf"),
                device=queries.device, dtype=torch.float16,
            ).amax(dim=-1)
        with spyre_hint(named_dims=["B", "H", "Lq"]):
            denom = torch.full(
                (B, H, Lq, 64), 0.0,
                device=queries.device, dtype=torch.float16,
            ).amax(dim=-1)
        with spyre_hint(named_dims=["B", "H", "Lq", "D"]):
            acc = torch.zeros_like(queries)

        def sweep(running_max, denom, acc):
            out = None
            for kb in range(n_chunks):
                k_c, v_c = k_chunks[kb], v_chunks[kb]
                keys_T = (k_c * scale).transpose(-1, -2).contiguous()
                with spyre_hint(named_dims=["B", "H", "Lq", "Lkc"]):
                    scores = torch.matmul(queries * scale, keys_T)
                block_max = torch.amax(scores, dim=-1)
                new_max = torch.maximum(running_max, block_max)
                correction = torch.exp(running_max - new_max)
                exp_scores = torch.exp(scores - new_max.unsqueeze(-1))
                new_denom = denom * correction + exp_scores.sum(dim=-1)
                with spyre_hint(named_dims=["B", "H", "Lq", "D"]):
                    weighted = torch.matmul(exp_scores, v_c)
                new_acc = acc * correction.unsqueeze(-1) + weighted
                if kb == n_chunks - 1:
                    out = new_acc / new_denom.unsqueeze(-1)
                else:
                    running_max, denom, acc = new_max, new_denom, new_acc
            return out

        with spyre_hint(num_tiles_per_dim={"H": h_tiles}):
            if lq_tiles:
                with spyre_hint(num_tiles_per_dim={"Lq": lq_tiles}):
                    return sweep(running_max, denom, acc)
            return sweep(running_max, denom, acc)

    return flash


def chunk_kv(t: torch.Tensor, kv_block: int, n_chunks: int):
    return [
        t[..., i * kv_block : (i + 1) * kv_block, :].contiguous()
        for i in range(n_chunks)
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--B", type=int, default=1)
    ap.add_argument("--H", type=int, default=8)
    ap.add_argument("--D", type=int, default=128)
    ap.add_argument("--Lq", type=int, default=256)
    ap.add_argument("--Lk", type=int, default=4096)
    ap.add_argument("--kv-block", type=int, default=512,
                    help="n_chunks = Lk // kv_block")
    ap.add_argument("--h-tiles", type=int, default=4)
    ap.add_argument("--lq-tiles", type=int, default=0,
                    help="0 → no Lq tiling")
    ap.add_argument("--out", type=str, required=True,
                    help="Path to write the timing JSON dump.")
    ap.add_argument("--compare-cpu", action="store_true",
                    help="Also run CPU reference. NEVER inside timed region.")
    args = ap.parse_args()

    _require_env("TORCHINDUCTOR_CACHE_DIR")
    if os.environ.get("TORCH_SPYRE_TIMING") != "1":
        print("FATAL: TORCH_SPYRE_TIMING=1 required.", file=sys.stderr)
        sys.exit(2)

    if args.Lk % args.kv_block != 0:
        print(f"FATAL: kv_block ({args.kv_block}) must divide Lk ({args.Lk}).",
              file=sys.stderr)
        sys.exit(2)
    n_chunks = args.Lk // args.kv_block

    import torch_spyre  # noqa: F401
    from torch_spyre._inductor import timing_recorder  # type: ignore

    # Test-file helpers for WSR named-dim declaration are private to the
    # test module. Re-declare them here since we can't import them without
    # dragging in pytest infra.
    from torch_spyre._inductor.wsr.propagate_named_dims import (
        declare_tensor_dim as _declare_tensor_dim,
        name_tensor_dims as _name_tensor_dims,
    )

    lq_tiles = args.lq_tiles if args.lq_tiles > 0 else None

    timing_recorder.set_run_meta(
        workload="pr3812_kvchunk_flash",
        B=args.B, H=args.H, D=args.D, Lq=args.Lq, Lk=args.Lk,
        kv_block=args.kv_block,
        n_chunks=n_chunks,
        h_tiles=args.h_tiles,
        lq_tiles=lq_tiles if lq_tiles is not None else 0,
        TORCHINDUCTOR_CACHE_DIR=os.environ["TORCHINDUCTOR_CACHE_DIR"],
        SENCORES=os.environ.get("SENCORES", "<unset>"),
        pod=os.environ.get("HOSTNAME", "<unknown>"),
    )

    torch.manual_seed(42)
    queries_t = torch.randn(args.B, args.H, args.Lq, args.D, dtype=torch.float16)
    keys_t = torch.randn(args.B, args.H, args.Lk, args.D, dtype=torch.float16)
    values_t = torch.randn(args.B, args.H, args.Lk, args.D, dtype=torch.float16)

    k_chunks_t = chunk_kv(keys_t, args.kv_block, n_chunks)
    v_chunks_t = chunk_kv(values_t, args.kv_block, n_chunks)

    # CPU reference is computed BEFORE we move to Spyre so no Spyre state
    # is touched during the reference computation.
    if args.compare_cpu:
        flash_cpu = build_kvchunk_flash(
            args.B, args.H, args.D, args.Lq,
            args.kv_block, n_chunks, args.h_tiles, lq_tiles,
        )
        # Compile-time named-dim declarations are for the Spyre device only;
        # the CPU reference can run the plain closure directly.
        ref = flash_cpu(queries_t, k_chunks_t, v_chunks_t)

    with timing_recorder.stage("device_init_and_transfer"):
        queries_s = queries_t.to("spyre")
        k_chunks_s = [t.to("spyre") for t in k_chunks_t]
        v_chunks_s = [t.to("spyre") for t in v_chunks_t]

    # Declare named dims for WSR tiling (mirror the PR #3812 test).
    _declare_tensor_dim("B", args.B)
    _declare_tensor_dim("H", args.H)
    _declare_tensor_dim("Lq", args.Lq)
    _declare_tensor_dim("D", args.D)
    _declare_tensor_dim("Lkc", args.kv_block)
    _name_tensor_dims(queries_s, ["B", "H", "Lq", "D"])
    for t in k_chunks_s + v_chunks_s:
        _name_tensor_dims(t, ["B", "H", "Lkc", "D"])

    gc.collect()

    flash = build_kvchunk_flash(
        args.B, args.H, args.D, args.Lq,
        args.kv_block, n_chunks, args.h_tiles, lq_tiles,
    )
    flash_spyre = torch.compile(flash)
    with timing_recorder.stage("first_call_wall"):
        out_s = flash_spyre(queries_s, k_chunks_s, v_chunks_s)

    if args.compare_cpu:
        torch.testing.assert_close(
            out_s.cpu(), ref,
            equal_nan=True, atol=0.01, rtol=0.1,
        )
        timing_recorder.set_run_meta(cpu_reference_ok=True)

    timing_recorder.dump_and_finalize(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
