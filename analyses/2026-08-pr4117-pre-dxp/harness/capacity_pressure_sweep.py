#!/usr/bin/env python3
"""Capacity-pressure sweep on captured real planner-buffer sets.

Reads the pickled buffer captures under ``data/captured_buffers/``,
each of which holds the exact ``LifetimeBoundBuffer`` list and
LX capacity a real compiled workload fed to placement-only
``CpSatLayoutSolver.plan_layout()`` under
``SPYRE_LX_PLANNER_RELAYOUT=0``.

For each capture and each capacity-scale factor in the sweep,
build a fresh solver-local deep copy of the buffers, run
greedy and CP-SAT independently at the scaled capacity, plus
run the hybrid (certified greedy fast path):

    if greedy achieves CP-SAT placement-objective 0:
        accept greedy;
        skip CP-SAT.
    else:
        run CP-SAT on the original untouched buffers.

Emit a per-capacity comparison so we can see whether the hybrid
automatically escalates exactly where CP-SAT begins buying quality.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import pickle
import sys
import time


def _spill_cost(b) -> int:
    boundary = getattr(b, "boundary", None)
    if boundary is not None:
        from torch_spyre._inductor.scratchpad.plan_solver import BufferType
        is_intermediate = boundary == BufferType.Intermediate
    else:
        is_intermediate = not b.first_use_is_read
    reads_served = b.read_count - (1 if b.first_use_is_read else 0)
    return (reads_served + (1 if is_intermediate else 0)) * b.size


def _objective(buffers) -> int:
    return sum(_spill_cost(b) for b in buffers if b.address is None)


def _lower_bound_objective(buffers, size) -> int:
    """Absolute floor of the placement-only CP-SAT objective.
    ``MemoryPlanSolver.record_exclusions`` pins to ``in_buffer = 0``
    every buffer with ``residency_reason is not None`` OR
    ``min_footprint > limit`` (size-only forced exclusion). Their
    ``spill_cost`` is unavoidably active in the objective. The floor
    equals the sum over exactly that set.
    """
    def _min_footprint(b) -> int:
        return getattr(b, "min_footprint", b.size)
    forced = [
        b for b in buffers
        if b.residency_reason is not None or _min_footprint(b) > size
    ]
    return sum(_spill_cost(b) for b in forced)


def _run(solver_cls, buffers_in, size, alignment, cpsat_time_limit_s=None,
         standalone_cpsat=False):
    """Run one solver against a fresh deep-copy of the buffers.

    ``standalone_cpsat=True`` drives ``_plan_layout_generic`` directly on
    ``CpSatLayoutSolver`` -- so the harness measures raw CP-SAT time and
    objective bypassing the shipped ``_try_certified_greedy_seed``. The
    hybrid path is measured separately by ``_run_hybrid``.
    """
    bufs = copy.deepcopy(buffers_in)
    t0 = time.perf_counter()
    try:
        # CP-SAT constructor takes an optional time_limit_seconds; greedy
        # ignores it. Passing only when the solver accepts it keeps the
        # call site simple.
        import inspect
        params = inspect.signature(solver_cls).parameters
        kwargs = {}
        if "time_limit_seconds" in params and cpsat_time_limit_s is not None:
            kwargs["time_limit_seconds"] = cpsat_time_limit_s
        solver = solver_cls(bufs, size, alignment, **kwargs)
        if standalone_cpsat:
            result = list(solver._plan_layout_generic())
        else:
            result = solver.plan_layout()
        err = None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        result = None
    return {
        "wall_s": time.perf_counter() - t0,
        "buffers": result,
        "error": err,
        "objective": _objective(result) if result is not None else None,
        "n_placed": (
            sum(1 for b in result if b.address is not None)
            if result is not None else None
        ),
        "n_spilled": (
            sum(1 for b in result if b.address is None)
            if result is not None else None
        ),
    }


def _run_hybrid(GreedyLayoutSolver, CpSatLayoutSolver,
                buffers_in, size, alignment):
    """Certified greedy fast path over CP-SAT (same as differential
    corpus)."""
    t_start = time.perf_counter()
    greedy_probe = _run(GreedyLayoutSolver, buffers_in, size, alignment)
    t_probe = time.perf_counter() - t_start
    if greedy_probe["error"] is not None:
        cpsat = _run(
            CpSatLayoutSolver, buffers_in, size, alignment,
            cpsat_time_limit_s=60.0,
        )
        return {
            "chosen": "cpsat-fallback-after-greedy-error",
            "hybrid_wall_s": t_probe + cpsat["wall_s"],
            "cpsat_wall_s": cpsat["wall_s"],
            "greedy_probe_wall_s": t_probe,
            "cpsat_run": True,
            "objective": cpsat["objective"],
            "buffers": cpsat["buffers"],
            "n_placed": cpsat["n_placed"],
            "n_spilled": cpsat["n_spilled"],
            "greedy_objective_on_probe": None,
        }
    lb = _lower_bound_objective(buffers_in, size)
    if greedy_probe["objective"] == lb:
        return {
            "chosen": "greedy-certified",
            "hybrid_wall_s": t_probe,
            "cpsat_wall_s": 0.0,
            "greedy_probe_wall_s": t_probe,
            "cpsat_run": False,
            "objective": greedy_probe["objective"],
            "buffers": greedy_probe["buffers"],
            "n_placed": greedy_probe["n_placed"],
            "n_spilled": greedy_probe["n_spilled"],
            "greedy_objective_on_probe": greedy_probe["objective"],
            "lower_bound_objective": lb,
        }
    # greedy left value on the table for placeable buffers; fall through
    # to CP-SAT.
    cpsat = _run(
        CpSatLayoutSolver, buffers_in, size, alignment,
        cpsat_time_limit_s=60.0,
    )
    return {
        "chosen": "cpsat-fallback",
        "hybrid_wall_s": t_probe + cpsat["wall_s"],
        "cpsat_wall_s": cpsat["wall_s"],
        "greedy_probe_wall_s": t_probe,
        "cpsat_run": True,
        "objective": cpsat["objective"],
        "buffers": cpsat["buffers"],
        "n_placed": cpsat["n_placed"],
        "n_spilled": cpsat["n_spilled"],
        "greedy_objective_on_probe": greedy_probe["objective"],
    }


def _round_capacity(scale, base):
    from torch_spyre._inductor.scratchpad.allocator import (
        _LX_ALLOCATION_GRANULARITY_BYTES,
    )
    g = _LX_ALLOCATION_GRANULARITY_BYTES
    # Round down to a multiple of the granularity so capacity_units is a
    # non-negative int.
    return int(scale * base) // g * g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures-dir", required=True,
                    help="dir with .pkl LifetimeBoundBuffer captures")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--capacity-scales",
        default="1.0,0.75,0.5,0.25",
    )
    args = ap.parse_args()

    import torch  # noqa: F401
    import torch_spyre  # noqa: F401
    from torch_spyre._inductor.scratchpad.greedy_solver import (
        GreedyLayoutSolver,
    )
    from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
        CpSatLayoutSolver,
    )

    os.makedirs(args.out, exist_ok=True)
    scales = [float(x) for x in args.capacity_scales.split(",")]

    all_results = []
    for fn in sorted(os.listdir(args.captures_dir)):
        if not fn.endswith(".pkl"):
            continue
        path = os.path.join(args.captures_dir, fn)
        with open(path, "rb") as fh:
            cap = pickle.load(fh)
        buffers = cap["buffers"]
        base_limit = cap["limit"]
        alignment = cap["alignment"]
        n_buf = len(buffers)
        # Total bytes that would spill if capacity were 0 (upper bound
        # on the residency objective for the sweep).
        total_spill_cost = sum(_spill_cost(b) for b in buffers)
        max_live_bytes = 0
        try:
            ticks = set()
            for b in buffers:
                if b.uses:
                    ticks.add(b.start_time)
                    ticks.add(b.end_time)
            for t in sorted(ticks):
                live = sum(
                    b.size for b in buffers
                    if b.uses and b.start_time <= t < b.end_time
                    and b.residency_reason is None
                )
                if live > max_live_bytes:
                    max_live_bytes = live
        except Exception:
            pass

        cap_results = []
        for scale in scales:
            size = _round_capacity(scale, base_limit)
            greedy = _run(GreedyLayoutSolver, buffers, size, alignment)
            cpsat = _run(
                CpSatLayoutSolver, buffers, size, alignment,
                cpsat_time_limit_s=60.0, standalone_cpsat=True,
            )
            hybrid = _run_hybrid(
                GreedyLayoutSolver, CpSatLayoutSolver,
                buffers, size, alignment,
            )
            # Resident-set difference between greedy and cpsat at this
            # capacity.
            g_res = (
                {b.name for b in greedy["buffers"] if b.address is not None}
                if greedy["buffers"] is not None else None
            )
            c_res = (
                {b.name for b in cpsat["buffers"] if b.address is not None}
                if cpsat["buffers"] is not None else None
            )
            diff = None
            if g_res is not None and c_res is not None:
                diff = {
                    "only_greedy": sorted(g_res - c_res)[:5],
                    "only_cpsat": sorted(c_res - g_res)[:5],
                    "agree": len(g_res & c_res),
                    "sym_diff": len(g_res ^ c_res),
                }
            lb = _lower_bound_objective(buffers, size)
            cap_results.append({
                "scale": scale,
                "size_bytes": size,
                "lower_bound_objective": lb,
                "greedy_objective": greedy["objective"],
                "cpsat_objective": cpsat["objective"],
                "hybrid_objective": hybrid["objective"],
                "greedy_reaches_lower_bound": (
                    greedy["objective"] == lb
                    if greedy["objective"] is not None else None
                ),
                "cpsat_reaches_lower_bound": (
                    cpsat["objective"] == lb
                    if cpsat["objective"] is not None else None
                ),
                "hybrid_chosen": hybrid["chosen"],
                "greedy_wall_s": greedy["wall_s"],
                "cpsat_wall_s": cpsat["wall_s"],
                "hybrid_wall_s": hybrid["hybrid_wall_s"],
                "hybrid_cpsat_run": hybrid["cpsat_run"],
                "greedy_n_placed": greedy["n_placed"],
                "greedy_n_spilled": greedy["n_spilled"],
                "cpsat_n_placed": cpsat["n_placed"],
                "cpsat_n_spilled": cpsat["n_spilled"],
                "resident_set_diff": diff,
            })
        all_results.append({
            "capture": fn,
            "workload": cap.get("workload"),
            "shape_params": cap.get("shape_params"),
            "n_buffers": n_buf,
            "base_limit_bytes": base_limit,
            "alignment": alignment,
            "max_live_bytes": max_live_bytes,
            "total_spill_cost_if_none_placed": total_spill_cost,
            "per_capacity": cap_results,
        })
        print(f"{fn}: n_buf={n_buf} base_limit={base_limit} "
              f"max_live={max_live_bytes}", flush=True)
        for r in cap_results:
            print(f"  scale={r['scale']:.2f} "
                  f"size={r['size_bytes']:>8d} "
                  f"g_obj={r['greedy_objective']} "
                  f"c_obj={r['cpsat_objective']} "
                  f"h={r['hybrid_chosen']:<20s} "
                  f"h_obj={r['hybrid_objective']} "
                  f"g_ms={r['greedy_wall_s']*1e3:.1f} "
                  f"c_ms={r['cpsat_wall_s']*1e3:.1f} "
                  f"h_ms={r['hybrid_wall_s']*1e3:.1f}",
                  flush=True)

    with open(os.path.join(args.out, "summary.json"), "w") as fh:
        json.dump({"captures": all_results}, fh, indent=2, default=str)
    print(f"wrote {args.out}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
