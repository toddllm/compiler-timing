#!/usr/bin/env python3
"""Capture the exact ``LifetimeBoundBuffer`` universe a real compiled
workload feeds to placement-only CP-SAT, and pickle it for offline
capacity-pressure and hybrid-solver studies.

Usage (inside the pod's torch-spyre .venv):

    python3 capture_planner_buffers.py \\
        --workload flash --Lq 512 --Lk 4096 \\
        --out data/captured_buffers/flash-512x4096.pkl

Runs the harness's normal ``--mode stop`` path but monkey-patches
``CpSatLayoutSolver.plan_layout`` to snapshot ``self.buffers`` and
``self.limit`` before invoking the real solver, pickle the snapshot,
and then let the compile continue as usual (the compile itself is
still stopped at the pre-DXP boundary by the existing harness).

Runs with ``SPYRE_LX_PLANNER_RELAYOUT=0`` so the captured universe is
the one the hybrid study needs to reason about.
"""

from __future__ import annotations

import argparse
import copy
import os
import pickle
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", required=True,
                    choices=["flash", "mlp", "sdpa"])
    ap.add_argument("--Lq", type=int)
    ap.add_argument("--Lk", type=int)
    ap.add_argument("--N-in", type=int, dest="N_in", default=1024)
    ap.add_argument("--N-hidden", type=int, dest="N_hidden", default=2048)
    ap.add_argument("--layers", type=int, default=8)
    ap.add_argument("--S", type=int, default=512)
    ap.add_argument("--B", type=int, default=1)
    ap.add_argument("--H", type=int, default=8)
    ap.add_argument("--D", type=int, default=128)
    ap.add_argument("--out", required=True)
    ap.add_argument("--layout-solver", default="cpsat",
                    choices=["cpsat", "greedy"])
    args = ap.parse_args()

    os.environ.setdefault("TORCH_SPYRE_TIMING", "1")
    os.environ.setdefault("USE_SPYRE_CCL", "0")
    os.environ.setdefault("CO_OPTIMIZING_LX_PLANNING", "0")
    os.environ.setdefault("LX_PLANNING", "1")
    os.environ.setdefault("SENCORES", "32")
    # THE key config: identical universe both solvers.
    os.environ["SPYRE_LX_PLANNER_RELAYOUT"] = "0"
    os.environ["LAYOUT_SOLVER"] = args.layout_solver
    os.environ.pop("ADAPTIVE_SOLVER_THRESHOLD_OPS", None)
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = (
        f"/tmp/tsc-capture-{args.workload}-{args.layout_solver}"
    )
    import shutil
    shutil.rmtree(os.environ["TORCHINDUCTOR_CACHE_DIR"], ignore_errors=True)

    import torch  # noqa: F401
    import torch_spyre  # noqa: F401
    from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
        CpSatLayoutSolver,
    )
    from torch_spyre._inductor.scratchpad.greedy_solver import (
        GreedyLayoutSolver,
    )

    captured: dict = {}

    def _install_capture(cls, key):
        orig = cls.plan_layout

        def wrapped(self, log_lx_usage=False):
            # Snapshot BEFORE solver runs so buffers have address=None.
            captured[f"{key}_buffers"] = copy.deepcopy(self.buffers)
            captured[f"{key}_limit"] = self.limit
            captured[f"{key}_alignment"] = self.alignment
            return orig(self, log_lx_usage=log_lx_usage)

        cls.plan_layout = wrapped

    _install_capture(CpSatLayoutSolver, "cpsat")
    _install_capture(GreedyLayoutSolver, "greedy")

    # Reach into the harness for its workload builders and compile
    # driver. Only Lq/Lk (or N-in/etc) parameters matter here — mode
    # is fixed to ``stop``.
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    from pre_dxp_stop import (  # noqa: E402
        _flash_workload,
        _mlp_workload,
        _sdpa_workload,
    )

    torch.manual_seed(0xAFFE)
    if args.workload == "flash":
        assert args.Lq is not None and args.Lk is not None
        fn, inputs, _meta = _flash_workload(args.Lq, args.Lk)
    elif args.workload == "mlp":
        fn, inputs, _meta = _mlp_workload(args.N_in, args.N_hidden, args.layers)
    elif args.workload == "sdpa":
        fn, inputs, _meta = _sdpa_workload(args.B, args.H, args.S, args.D)
    else:
        raise ValueError(args.workload)

    compiled = torch.compile(fn)
    try:
        compiled(*inputs)
    except Exception as e:
        # Any post-scratchpad error is fine — we already captured the
        # buffers we need.
        print(f"compile stopped: {type(e).__name__}", file=sys.stderr)

    key = "cpsat" if args.layout_solver == "cpsat" else "greedy"
    if f"{key}_buffers" not in captured:
        print(f"FATAL: {args.layout_solver} plan_layout never fired",
              file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        pickle.dump(
            {
                "workload": args.workload,
                "shape_params": {
                    "Lq": args.Lq, "Lk": args.Lk,
                    "N_in": args.N_in, "N_hidden": args.N_hidden,
                    "layers": args.layers,
                    "B": args.B, "H": args.H, "S": args.S, "D": args.D,
                },
                "layout_solver": args.layout_solver,
                "buffers": captured[f"{key}_buffers"],
                "limit": captured[f"{key}_limit"],
                "alignment": captured[f"{key}_alignment"],
            },
            fh,
        )
    print(f"wrote {args.out}: {len(captured[f'{key}_buffers'])} buffers, "
          f"limit={captured[f'{key}_limit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
