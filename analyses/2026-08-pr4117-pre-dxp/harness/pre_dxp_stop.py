"""Frontend-only measurement harness for epic #4117.

Runs the normal cold-compile path through backend-input generation and
stops immediately before ``subprocess.run(["dxp_standalone", ...])`` in
``torch_spyre.execution.async_compile.SpyreAsyncCompile.sdsc``.

The stop is implemented by monkey-patching ``subprocess.run`` at the
call site: when ``TORCH_SPYRE_PRE_DXP_STOP=1`` is set, the patched
``run`` records the arguments it would have passed to DXP, raises a
dedicated sentinel exception ``_PreDxpBoundary``, and lets the outer
harness catch it as the "pre-DXP done" signal.

Design constraints (per epic #4117 methodology):

  * Preserve normal frontend path — the harness does not stub out
    ``generate_bundle`` or ``build_kernel_provenance_descriptor``.
    Everything that runs before ``subprocess.run`` in a production
    cold compile also runs here.
  * Do not replace DXP with a fake implementation that could make
    upstream code take a different branch. The interception is at the
    subprocess call itself, after every torch-side step.
  * Verify SDSC bundle fidelity by re-running under a normal (no-stop)
    mode at one baseline point and comparing the produced bundle
    directory listing against the pre-DXP-stop run.

Interception mechanism
----------------------

``_install_pre_dxp_stop()`` replaces
``torch_spyre.execution.async_compile.subprocess.run`` with a function
that:

  1. captures ``args`` and ``kwargs`` on ``self._captured_dxp_calls``
     (a class-level attribute on the recorder for the run).
  2. calls ``timing_recorder.stage("pre_dxp_boundary_marker")`` briefly
     so the boundary is a queryable event ordinal in the JSON.
  3. raises ``_PreDxpBoundary``, which the harness in ``main()``
     catches at the compile-driver level.

The sentinel exception carries the captured call so a caller can
verify that the process really reached the DXP boundary. This
distinguishes "stopped as intended" from "compile bailed for some
other reason."

Environment
-----------

``TORCH_SPYRE_PRE_DXP_STOP=1``
    Enable pre-DXP interception. When unset, the harness runs a
    normal cold compile.

``TORCH_SPYRE_TIMING=1``
    Also record hierarchical timing into ``$SPYRE_TIMING_OUT``. This
    is orthogonal to the stop switch; enable both for a full
    instrumented pre-DXP-only run.

``SPYRE_TIMING_OUT``
    Path to write the timing JSON. Required when TIMING is on.

Fidelity
--------

Under ``TORCH_SPYRE_PRE_DXP_STOP=1``:

  * ``generate_bundle`` runs to completion. The SDSC bundle exists on
    disk in ``$TORCHINDUCTOR_CACHE_DIR/.../<kernel_name>/`` at the
    normal location.
  * ``build_kernel_provenance_descriptor`` runs (or is caught by its
    own try/except; identical to normal).
  * ``subprocess.run`` is not invoked; no DXP output artifacts appear.
  * ``SpyreSDSCKernelRunner`` is never constructed. The wrapper's first
    call raises ``_PreDxpBoundary`` from inside ``sdsc()``.

Anything the wrapper's first call would have done after the compiled
kernel returned (post-DXP path: allocations, runtime kernel launch)
does not run. The harness is therefore analysis-only.
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
from typing import Any


class _PreDxpBoundary(Exception):
    """Sentinel raised at the subprocess.run(dxp_standalone) call
    site when TORCH_SPYRE_PRE_DXP_STOP=1.

    Carries the captured (args, kwargs) so callers can prove the
    interception fired at the intended point.
    """

    def __init__(self, dxp_args: tuple[Any, ...], dxp_kwargs: dict[str, Any]) -> None:
        super().__init__("pre-DXP stop boundary reached")
        self.dxp_args = dxp_args
        self.dxp_kwargs = dxp_kwargs


def _install_pre_dxp_stop() -> None:
    """Monkey-patch subprocess.run inside torch_spyre.execution.async_compile
    to record + raise _PreDxpBoundary. Idempotent.
    """
    from torch_spyre.execution import async_compile as _ac

    if getattr(_ac, "_pre_dxp_stop_installed", False):
        return

    orig_run = _ac.subprocess.run

    def _stub_run(*args, **kwargs):
        # Sanity: only intercept the DXP subprocess. Any other call
        # (unlikely from this module, but safe) passes through.
        cmd = args[0] if args else kwargs.get("args") or []
        if not (isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "dxp_standalone"):
            return orig_run(*args, **kwargs)
        # Emit a boundary marker into the timing record so the
        # analyzer has an unambiguous event ordinal to align at.
        # The recorder module is whichever one main() already imported
        # (upstream torch_spyre one, or the compiler-timing fallback).
        try:
            _tr = sys.modules.get("torch_spyre._inductor.timing_recorder") \
                or sys.modules.get("timing_recorder")
            if _tr is not None:
                with _tr.stage("pre_dxp_boundary_marker", cmd=list(cmd)):
                    pass
        except Exception:
            pass
        raise _PreDxpBoundary(args, kwargs)

    _ac.subprocess.run = _stub_run  # type: ignore[attr-defined]
    _ac._pre_dxp_stop_installed = True  # type: ignore[attr-defined]


def _flash_workload(Lq: int, Lk: int):
    """Same flash-attention closure the study used, so results are
    directly comparable across analyses.
    """
    import math

    import torch

    B, H, D = 1, 8, 128
    b_block_size, h_block_size = 1, 4
    q_block_size, kv_block_size = 256, 512

    def flash(queries, keys, values, mask):
        scale = 1.0 / math.sqrt(math.sqrt(D))
        output = torch.zeros_like(queries)
        real_max = torch.full(
            (B, H, Lq, 64), float("-inf"), device=queries.device, dtype=torch.float16
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
                        exp_scores = torch.exp(scores - running_max.unsqueeze(-1))
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

    queries = torch.randn(B, H, Lq, D, device="spyre", dtype=torch.float16)
    keys = torch.randn(B, H, Lk, D, device="spyre", dtype=torch.float16)
    values = torch.randn(B, H, Lk, D, device="spyre", dtype=torch.float16)
    causal = torch.tril(torch.ones(Lq, Lk, dtype=torch.bool))
    mask_cpu = torch.zeros(1, 1, Lq, Lk, dtype=torch.float16)
    mask_cpu.masked_fill_(~causal, float("-inf"))
    mask = mask_cpu.to("spyre")
    return flash, (queries, keys, values, mask), {
        "B": B,
        "H": H,
        "D": D,
        "Lq": Lq,
        "Lk": Lk,
        "b_block_size": b_block_size,
        "h_block_size": h_block_size,
        "q_block_size": q_block_size,
        "kv_block_size": kv_block_size,
    }


def _mlp_workload(N_in: int, N_hidden: int, layers: int):
    """A stack of ``layers`` matmul-plus-bias-plus-gelu blocks. Simple
    non-flash workload for the epic's "structurally different" ask.
    """
    import torch

    def mlp(x, weights, biases):
        for w, b in zip(weights, biases):
            x = torch.nn.functional.gelu(torch.matmul(x, w) + b)
        return x

    x = torch.randn(1, N_in, device="spyre", dtype=torch.float16)
    weights = [
        torch.randn(
            N_in if i == 0 else N_hidden,
            N_hidden if i < layers - 1 else N_in,
            device="spyre",
            dtype=torch.float16,
        )
        for i in range(layers)
    ]
    biases = [
        torch.randn(
            N_hidden if i < layers - 1 else N_in,
            device="spyre",
            dtype=torch.float16,
        )
        for i in range(layers)
    ]
    return mlp, (x, weights, biases), {
        "N_in": N_in,
        "N_hidden": N_hidden,
        "layers": layers,
    }


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"FATAL: {name} required", file=sys.stderr)
        sys.exit(2)
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", choices=["flash", "mlp"], required=True)
    ap.add_argument("--Lq", type=int)
    ap.add_argument("--Lk", type=int)
    ap.add_argument("--N-in", type=int, dest="N_in", default=1024)
    ap.add_argument("--N-hidden", type=int, dest="N_hidden", default=4096)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--out", type=str, required=True, help="timing JSON path")
    ap.add_argument(
        "--allow-full-dxp",
        action="store_true",
        help=(
            "For fidelity runs only. Do NOT install the pre-DXP stop; "
            "let the full compile run to completion (including DXP)."
        ),
    )
    args = ap.parse_args()

    _require_env("TORCHINDUCTOR_CACHE_DIR")
    if os.environ.get("TORCH_SPYRE_TIMING") != "1":
        print("FATAL: TORCH_SPYRE_TIMING=1 required.", file=sys.stderr)
        return 2

    import torch
    import torch_spyre  # noqa: F401
    try:
        # Preferred: recorder is installed inside torch-spyre (Phase 3+).
        from torch_spyre._inductor import timing_recorder as _tr
    except ImportError:
        # Phase 2 fallback: the recorder lives in the compiler-timing study
        # tree. Add its patches/ dir to sys.path and import from there so
        # the harness runs even before the recorder is upstreamed into
        # torch_spyre.
        _study_patches = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "2026-08-pr3806-frontend-timing", "patches",
        )
        sys.path.insert(0, os.path.normpath(_study_patches))
        import timing_recorder as _tr  # type: ignore[no-redef]

    # Meta lines the timing recorder will embed in the JSON.
    _tr.set_run_meta(
        workload=args.workload,
        allow_full_dxp=bool(args.allow_full_dxp),
        Lq=args.Lq,
        Lk=args.Lk,
        N_in=args.N_in,
        N_hidden=args.N_hidden,
        layers=args.layers,
        TORCHINDUCTOR_CACHE_DIR=os.environ["TORCHINDUCTOR_CACHE_DIR"],
        SENCORES=os.environ.get("SENCORES", "<unset>"),
        pod=os.environ.get("HOSTNAME", "<unknown>"),
        torch_version=torch.__version__,
        python_version=sys.version.split()[0],
        pre_dxp_stop=bool(not args.allow_full_dxp),
    )

    torch.manual_seed(0xAFFE)

    if args.workload == "flash":
        if args.Lq is None or args.Lk is None:
            print("FATAL: --Lq and --Lk required for --workload=flash", file=sys.stderr)
            return 2
        fn, inputs, meta = _flash_workload(args.Lq, args.Lk)
    elif args.workload == "mlp":
        fn, inputs, meta = _mlp_workload(args.N_in, args.N_hidden, args.layers)
    else:
        raise AssertionError(args.workload)
    _tr.set_run_meta(**meta)

    # Move inputs to device outside timing.
    with _tr.stage("device_init_and_transfer"):
        # inputs may include a list of tensors (mlp weights); ensure everything
        # is already on device. The workload builders above already .to()'d
        # anything they needed to, so this is a no-op unless the inputs are
        # nested. Left as an explicit event to bracket lazy device init.
        pass

    gc.collect()

    if not args.allow_full_dxp:
        _install_pre_dxp_stop()

    compiled = torch.compile(fn)

    hit_boundary = False
    boundary_info: dict[str, Any] = {}
    try:
        with _tr.stage("first_call_wall"):
            compiled(*inputs)
    except _PreDxpBoundary as e:
        hit_boundary = True
        cmd = e.dxp_args[0] if e.dxp_args else e.dxp_kwargs.get("args")
        boundary_info = {"dxp_cmd_captured": list(cmd) if cmd else None}
    except Exception as e:  # noqa: BLE001
        # Unwrap InductorError-style wrappings so we still recognize the
        # sentinel when dynamo wraps.
        cur: BaseException | None = e
        while cur is not None:
            if isinstance(cur, _PreDxpBoundary):
                hit_boundary = True
                cmd = cur.dxp_args[0] if cur.dxp_args else cur.dxp_kwargs.get("args")
                boundary_info = {"dxp_cmd_captured": list(cmd) if cmd else None}
                break
            cur = cur.__cause__ or cur.__context__
        if not hit_boundary:
            # Real error — record it in meta and re-raise after dump.
            _tr.set_run_meta(unexpected_error=repr(e)[:2000])
            _tr.dump_and_finalize(args.out)
            raise

    _tr.set_run_meta(
        pre_dxp_boundary_reached=hit_boundary,
        boundary_info=boundary_info,
    )
    _tr.dump_and_finalize(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
