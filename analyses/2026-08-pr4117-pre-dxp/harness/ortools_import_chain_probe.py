"""Prove exactly when OR-Tools enters sys.modules during a torch-spyre
compile session.

Runs as a subprocess for reproducibility. Records sys.modules
membership at each named boundary. Does NOT modify production code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


ORTOOLS_KEYS = [
    "ortools",
    "ortools.sat",
    "ortools.sat.python",
    "ortools.sat.python.cp_model",
    "ortools.sat.python.cp_model_helper",
    "ortools.sat.python.swig_helper",
    "ortools.sat.python.cp_model_pb2",
]


def snapshot(label: str, records: list) -> None:
    present = {k: (k in sys.modules) for k in ORTOOLS_KEYS}
    records.append({"label": label, "t": time.perf_counter(), "present": present})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--force-fallback", action="store_true",
                    help="Configure the input so the seed rejects")
    ap.add_argument("--joint-path", action="store_true",
                    help="Also exercise plan_layout_and_core_divisions")
    args = ap.parse_args()

    records: list = []
    snapshot("process_start", records)
    t0_wall = records[-1]["t"]

    import torch  # noqa: E402
    snapshot("after_import_torch", records)

    import torch_spyre  # noqa: F401,E402
    snapshot("after_import_torch_spyre", records)

    # Just importing the scratchpad allocator module — this is what
    # runs when torch-spyre lowers a graph.
    from torch_spyre._inductor.scratchpad import allocator as _alloc  # noqa: F401,E402
    snapshot("after_import_allocator", records)

    # Try select_allocator — this only sets up a factory, does NOT
    # touch _make_cpsat_solver.
    from torch_spyre._inductor.scratchpad.allocator import select_allocator  # noqa: E402
    allocator_obj = select_allocator()
    snapshot("after_select_allocator", records)

    # Construct a fresh CP-SAT solver via the factory (this DOES
    # import ilp_solver_ortools).
    from torch_spyre._inductor.scratchpad.allocator import _make_cpsat_solver  # noqa: E402
    from torch_spyre._inductor.scratchpad.plan_solver import (  # noqa: E402
        LifetimeBoundBuffer,
    )
    small_buffers = [
        LifetimeBoundBuffer(f"b{i}", 100, [i, i + 2])
        for i in range(6)
    ]
    solver = _make_cpsat_solver(small_buffers, 100_000)
    snapshot("after_make_cpsat_solver", records)

    # Certified greedy seed on a large-capacity input (should certify).
    plan = solver.plan_layout()
    snapshot("after_certified_plan_layout", records)

    if args.force_fallback:
        # Force the seed to reject by constructing an input with
        # capacity < aligned-size for at least one non-excluded buffer.
        # Simple trick: two size-60 buffers with capacity 100, same
        # lifetime -> total live footprint 120 > 100, and neither has
        # residency_reason, so greedy places one and leaves the other
        # spilled with nonzero cost. Certificate rejects, CP-SAT runs.
        forced_buffers = [
            LifetimeBoundBuffer("a", 60, [0, 5]),
            LifetimeBoundBuffer("b", 60, [0, 5]),
        ]
        forced_solver = _make_cpsat_solver(forced_buffers, 100)
        forced_plan = forced_solver.plan_layout()
        snapshot("after_forced_fallback_plan_layout", records)
        # Sanity: what got placed?
        placed = sorted(b.name for b in forced_plan if b.address is not None)
        records[-1]["placed"] = placed
        records[-1]["forced_objective_units"] = sum(
            b.size for b in forced_plan if b.address is None
        )

    if args.joint_path:
        from torch_spyre._inductor.scratchpad.plan_solver import (  # noqa: E402
            CoreDivision, CoreDivisionBuffer,
        )
        from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (  # noqa: E402
            CpSatLayoutSolver,
        )
        whole = [CoreDivision()]
        joint_buffers = [
            CoreDivisionBuffer(f"c{i}", 100, [i, i + 2], core_divisions=whole)
            for i in range(3)
        ]
        joint_solver = CpSatLayoutSolver(joint_buffers, 100_000)
        _ = joint_solver.plan_layout_and_core_divisions()
        snapshot("after_joint_plan_layout_and_core_divisions", records)

    # Emit JSON.
    for r in records:
        r["t_rel_s"] = r["t"] - t0_wall
    result = {
        "records": records,
        "python_version": sys.version.split()[0],
    }
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2, default=str)

    # Compact stdout summary.
    prev_present = {k: False for k in ORTOOLS_KEYS}
    for r in records:
        newly = [
            k for k in ORTOOLS_KEYS
            if r["present"][k] and not prev_present[k]
        ]
        print(f"[{r['t_rel_s']:6.3f}s] {r['label']}")
        for k in newly:
            print(f"          + {k}")
        prev_present = dict(r["present"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
