#!/usr/bin/env python3
"""Fallback-case validation for the certified greedy seed.

Loads the captured flash-512x8192 planner-buffer set at 25% of its
shipped LX capacity and runs it through the rebased/current-main
``CpSatLayoutSolver`` implementation. Proves:

* the seed's greedy probe leaves objective above the forced-spill
  floor (so the certificate rejects);
* the full CP-SAT solve then runs;
* ``hybrid_objective == standalone_cpsat_objective``.

Emits a small JSON with the numbers.
"""

from __future__ import annotations

import argparse
import copy
import json
import pickle
import sys
import time
from dataclasses import replace


def _obj_units(buffers, alignment, _hbm_spill_cost, ceil_div):
    return sum(
        _hbm_spill_cost(replace(b, size=ceil_div(b.size, alignment)))
        for b in buffers
        if b.address is None
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--capacity-scale", type=float, default=0.25)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import torch  # noqa: F401
    import torch_spyre  # noqa: F401
    from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
        CpSatLayoutSolver, _hbm_spill_cost, ceil_div,
    )
    from torch_spyre._inductor.scratchpad.greedy_solver import (
        GreedyLayoutSolver,
    )

    with open(args.capture, "rb") as fh:
        cap = pickle.load(fh)
    buffers = cap["buffers"]
    base_limit = cap["limit"]
    alignment = cap["alignment"]
    scaled_limit = int(base_limit * args.capacity_scale)

    print(
        f"capture: {args.capture}",
        f"n_buffers: {len(buffers)}",
        f"base_limit: {base_limit}",
        f"alignment: {alignment}",
        f"scaled_limit: {scaled_limit}",
        sep="\n",
    )

    # 1) Greedy alone
    greedy_bufs = copy.deepcopy(buffers)
    t0 = time.perf_counter()
    greedy_plan = list(
        GreedyLayoutSolver(greedy_bufs, scaled_limit, alignment).plan_layout()
    )
    greedy_wall = time.perf_counter() - t0
    greedy_obj = _obj_units(
        greedy_plan, alignment, _hbm_spill_cost, ceil_div,
    )

    # 2) Forced-spill floor
    solver_for_floor = CpSatLayoutSolver(
        copy.deepcopy(buffers), scaled_limit, alignment,
    )
    forced = dict(solver_for_floor.record_exclusions())
    lb_units = sum(
        _hbm_spill_cost(replace(b, size=ceil_div(b.size, alignment)))
        for b in buffers
        if b.name in forced
    )

    # 3) Try the seed alone -- expect None (reject)
    seed_probe_solver = CpSatLayoutSolver(
        copy.deepcopy(buffers), scaled_limit, alignment,
    )
    t1 = time.perf_counter()
    seed_result = seed_probe_solver._try_certified_greedy_seed()
    seed_wall = time.perf_counter() - t1

    # 4) Standalone CP-SAT bypassing the seed
    std_solver = CpSatLayoutSolver(
        copy.deepcopy(buffers), scaled_limit, alignment,
    )
    t2 = time.perf_counter()
    std_plan = list(std_solver._plan_layout_generic())
    std_wall = time.perf_counter() - t2
    std_obj = _obj_units(std_plan, alignment, _hbm_spill_cost, ceil_div)

    # 5) Hybrid via the public path
    hybrid_solver = CpSatLayoutSolver(
        copy.deepcopy(buffers), scaled_limit, alignment,
    )
    t3 = time.perf_counter()
    hybrid_plan = list(hybrid_solver.plan_layout())
    hybrid_wall = time.perf_counter() - t3
    hybrid_obj = _obj_units(
        hybrid_plan, alignment, _hbm_spill_cost, ceil_div,
    )

    result = {
        "capture": args.capture,
        "n_buffers": len(buffers),
        "base_limit": base_limit,
        "scaled_limit": scaled_limit,
        "alignment": alignment,
        "capacity_units_at_scaled_limit": scaled_limit // alignment,
        "greedy_alone": {
            "objective_units": greedy_obj,
            "wall_s": greedy_wall,
        },
        "forced_spill_floor_units": lb_units,
        "greedy_above_floor": greedy_obj > lb_units,
        "seed_alone": {
            "returned_None": seed_result is None,
            "wall_s": seed_wall,
        },
        "standalone_cpsat": {
            "objective_units": std_obj,
            "wall_s": std_wall,
        },
        "hybrid_public": {
            "objective_units": hybrid_obj,
            "wall_s": hybrid_wall,
        },
        "objectives_match": hybrid_obj == std_obj,
    }
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2, default=str)

    print(json.dumps({
        "greedy_obj": greedy_obj,
        "lb_units": lb_units,
        "greedy_above_floor": greedy_obj > lb_units,
        "seed_rejects": seed_result is None,
        "standalone_cpsat_obj": std_obj,
        "hybrid_obj": hybrid_obj,
        "objectives_match": hybrid_obj == std_obj,
        "greedy_ms": round(greedy_wall * 1000, 2),
        "seed_probe_ms": round(seed_wall * 1000, 2),
        "standalone_cpsat_ms": round(std_wall * 1000, 2),
        "hybrid_ms": round(hybrid_wall * 1000, 2),
    }, indent=2))

    ok = (
        seed_result is None
        and greedy_obj > lb_units
        and hybrid_obj == std_obj
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
