#!/usr/bin/env python3
"""Certified greedy fast-path hybrid, evaluated on the same
placement-only differential corpus used by ``differential_corpus.py``.

Rationale (from source review of
``torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py``):

- Placement-only ``CpSatLayoutSolver.plan_layout()`` runs only level 1 of the
  lexicographic solve. Levels 2 (parallelism) and 3 (shape balance) are gated
  on ``core_terms`` being non-empty, which requires at least one buffer to be
  a ``CoreDivisionBuffer`` with non-empty ``core_divisions``.
- ``_LifetimeBufferWithCpVars`` (the placement-only wrapper) sets
  ``cores = None``, so a plain ``LifetimeBoundBuffer`` universe produces
  ``core_terms == []`` and levels 2/3 are skipped entirely.
- Level 1 objective is ``sum(spill_cost(b) * (1 - in_buffer(b)))``. Every
  ``spill_cost(b) >= 0`` and ``(1 - in_buffer) in {0, 1}``, so the objective
  is a nonnegative sum. Its absolute lower bound is 0.

Certificate rule: if a greedy plan on the identical buffer set produces
``sum(spill_cost(b) for b in plan if b.address is None) == 0``, greedy is
already at the objective's absolute floor and CP-SAT cannot improve it.
Otherwise the greedy plan may be suboptimal and CP-SAT must run to be safe.

This hybrid is entirely at the solver/buffer level. It never mutates the
graph and it never runs greedy inside ``ScratchpadAllocator.plan_allocation``
(which would commit greedy's addresses to the graph and prevent a later
CP-SAT fallback). Buffers passed to the greedy probe are deep-copied so the
originals are untouched; a fallback CP-SAT run receives the original list.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from collections import defaultdict


def _spill_cost(b) -> int:
    """Mirror of
    ``_LifetimeBufferWithCpVars.spill_cost`` for a raw
    ``LifetimeBoundBuffer``. Pure function of the buffer.
    """
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


def _lower_bound_objective(buffers, size, alignment) -> int:
    """The absolute floor of the placement-only CP-SAT objective.

    The objective is ``sum(spill_cost(b) * (1 - in_buffer(b)))``.
    ``MemoryPlanSolver.record_exclusions`` pins to ``in_buffer = 0`` every
    buffer with ``residency_reason is not None`` OR
    ``min_footprint > limit`` (a size-only forced exclusion). Their
    ``spill_cost`` terms are always active, so the objective's floor is
    the sum over exactly that set.

    Matches the shipped ``_try_certified_greedy_seed`` semantics: the
    audit invariant only holds if the harness's floor uses the same
    exclusion set as the shipped code.
    """
    def _min_footprint(b) -> int:
        return getattr(b, "min_footprint", b.size)
    forced = [
        b for b in buffers
        if b.residency_reason is not None or _min_footprint(b) > size
    ]
    return sum(_spill_cost(b) for b in forced)


def _legal(buffers, size, alignment) -> tuple[bool, str]:
    placed = [b for b in buffers if b.address is not None]
    for b in placed:
        if b.address < 0 or b.address + b.size > size:
            return False, f"out-of-capacity: {b.name}@{b.address}+{b.size}>{size}"
        if b.address % alignment != 0:
            return False, f"misaligned: {b.name}@{b.address}%{alignment}"
    if placed:
        ticks = set()
        for b in placed:
            if b.uses:
                ticks.add(b.start_time)
                ticks.add(b.end_time)
        for t in sorted(ticks):
            live = [b for b in placed if b.uses and b.start_time <= t < b.end_time]
            by_addr: dict[int, list] = {}
            for b in live:
                by_addr.setdefault(b.address, []).append(b)
            for addr, group in by_addr.items():
                if len(group) > 2:
                    return False, f"tick {t}: {len(group)} at addr={addr}"
                if len(group) == 2:
                    a, c = group
                    parent, child = (a, c) if a.size >= c.size else (c, a)
                    if parent.name not in child.in_place_parents:
                        return False, (
                            f"tick {t}: unauthorized share addr={addr} "
                            f"between {a.name}, {c.name}"
                        )
    return True, ""


def _run_solver(solver_cls, buffers_in, size, alignment):
    """Run one solver against a fresh deep-copy of the buffers."""
    bufs = copy.deepcopy(buffers_in)
    t0 = time.perf_counter()
    err = None
    try:
        result = solver_cls(bufs, size, alignment).plan_layout()
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        result = None
    dur = time.perf_counter() - t0
    legal_ok, legal_why = (False, "no result") if result is None else _legal(result, size, alignment)
    return {
        "error": err,
        "buffers": list(result) if result is not None else None,
        "wall_s": dur,
        "legal": legal_ok,
        "legal_error": legal_why,
    }


def _run_standalone_cpsat(CpSatLayoutSolver, buffers_in, size, alignment):
    """Standalone CP-SAT bypassing the shipped seed. Calls
    ``_plan_layout_generic()`` directly so the harness measures raw
    CP-SAT time and objective — the same thing pre-#4139 ``plan_layout``
    would have returned. Never uses the seed."""
    bufs = copy.deepcopy(buffers_in)
    t0 = time.perf_counter()
    err = None
    result: list | None = None
    try:
        solver = CpSatLayoutSolver(bufs, size, alignment)
        result = list(solver._plan_layout_generic())
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    dur = time.perf_counter() - t0
    legal_ok, legal_why = (False, "no result") if result is None else _legal(result, size, alignment)
    return {
        "error": err,
        "buffers": result,
        "wall_s": dur,
        "legal": legal_ok,
        "legal_error": legal_why,
    }


def _run_hybrid(GreedyLayoutSolver, CpSatLayoutSolver, buffers_in,
                size, alignment):
    """Exercise the shipped hybrid on this input.

    ``CpSatLayoutSolver.plan_layout()`` is the shipped hybrid: it now
    calls ``_try_certified_greedy_seed`` first and only falls through to
    ``_plan_layout_generic`` if the certificate rejects. The harness
    infers which branch ran by checking whether the *shipped* seed would
    have accepted this input (same certificate the shipped code uses),
    so it can attribute the wall time correctly for reporting.
    """
    from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
        _hbm_spill_cost as shipped_spill_cost,
    )

    # Re-run the shipped certificate on a solver-local deep-copy to
    # classify this input as certified or fallback — we do this outside
    # the timed section so the reported ``hybrid_wall_s`` matches what
    # a real ``plan_layout()`` call takes end-to-end.
    _ = shipped_spill_cost  # binding proves the import exists

    t0 = time.perf_counter()
    err = None
    result: list | None = None
    try:
        solver = CpSatLayoutSolver(copy.deepcopy(buffers_in), size, alignment)
        result = list(solver.plan_layout())
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    dur = time.perf_counter() - t0

    # Classify: separately run just the seed on another copy to see if
    # it would have certified. This is duplicated work for the harness,
    # not for the shipped code.
    try:
        probe = CpSatLayoutSolver(
            copy.deepcopy(buffers_in), size, alignment,
        )
        seed_result = probe._try_certified_greedy_seed()
        chosen = "greedy-certified" if seed_result is not None else "cpsat-fallback"
    except Exception:
        chosen = "cpsat-fallback"

    if err is not None:
        # If the shipped call raised, still report as fallback (the
        # error will be caught at the summary level).
        return {
            "chosen": "cpsat-fallback",
            "greedy_probe_wall_s": 0.0,
            "cpsat_wall_s": dur,
            "cpsat_run": True,
            "error": err,
            "buffers": None,
            "greedy_objective_on_probe": None,
        }

    if chosen == "greedy-certified":
        return {
            "chosen": "greedy-certified",
            "greedy_probe_wall_s": dur,
            "cpsat_wall_s": 0.0,
            "cpsat_run": False,
            "error": None,
            "buffers": result,
            "greedy_objective_on_probe": _objective(result) if result else 0,
            "lower_bound_objective": _lower_bound_objective(
                buffers_in, size, alignment,
            ),
        }
    # Fallback: shipped code ran ``_plan_layout_generic`` after the
    # seed's own probe cost. Attribute the whole wall to CP-SAT to
    # match the pre-#4139 comparison shape.
    return {
        "chosen": "cpsat-fallback",
        "greedy_probe_wall_s": 0.0,
        "cpsat_wall_s": dur,
        "cpsat_run": True,
        "error": None,
        "buffers": result,
        "greedy_objective_on_probe": None,
    }


def _fixtures():
    """Introspect ``BaseLayoutSolverTests``; capture each test's buffer set.
    Same technique as ``differential_corpus.py``."""
    import torch  # noqa: F401
    import torch_spyre  # noqa: F401

    sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
    from tests.inductor import test_scratchpad_solver as tss  # noqa: E402
    Base = tss.BaseLayoutSolverTests
    Host = tss.TestGreedyLayoutSolver

    out = []
    method_names = [
        n for n in dir(Base)
        if n.startswith("test_") and n in Base.__dict__
        and callable(getattr(Base, n))
    ]
    for name in sorted(method_names):
        host = Host(name)
        captured: dict = {}

        def _cap_solve(buffers, size=None, alignment=1, _cap=captured):
            _cap["buffers"] = copy.deepcopy(buffers)
            _cap["size"] = size if size is not None else tss.LARGE_SIZE
            _cap["alignment"] = alignment
            for b in buffers:
                b.address = None
            return list(buffers)

        def _cap_verify(buffers, expected_addresses,
                        size=tss.SMALL_SIZE, alignment=1, _cap=captured):
            _cap["buffers"] = copy.deepcopy(buffers)
            _cap["size"] = size
            _cap["alignment"] = alignment
            for b in buffers:
                b.address = None
            return None

        host.solve = _cap_solve
        host.verify_layout = _cap_verify

        skip_reason = None
        try:
            getattr(host, name)()
        except Exception as e:
            skip_reason = f"host: {type(e).__name__}: {e}"

        if "buffers" not in captured:
            out.append({"name": name, "captured": False,
                        "skip_reason": skip_reason})
            continue
        out.append({
            "name": name, "captured": True,
            "skip_reason": skip_reason,
            "buffers": captured["buffers"],
            "size": captured["size"],
            "alignment": captured["alignment"],
        })
    return out


def _buf_dict(b):
    return {
        "name": b.name, "size": b.size, "uses": list(b.uses),
        "first_use_is_read": b.first_use_is_read,
        "in_place_parents": list(b.in_place_parents),
        "residency_reason": b.residency_reason,
        "lifetime_end_override": b.lifetime_end_override,
        "address": b.address,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(os.path.join(args.out, "divergences"), exist_ok=True)

    # torch imported before torch_spyre — the spyre-device backend
    # autoload machinery walks torch's registration to find _autoload,
    # and torch_spyre.__init__ ``import torch`` triggers the autoload
    # attempt.
    import torch  # noqa: F401
    import torch_spyre  # noqa: F401

    from torch_spyre._inductor.scratchpad.greedy_solver import (
        GreedyLayoutSolver,
    )
    from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
        CpSatLayoutSolver,
    )

    fixtures = _fixtures()

    results = []
    counts = defaultdict(int)
    for fx in fixtures:
        entry = {"name": fx["name"], "captured": fx["captured"]}
        if not fx["captured"]:
            counts["SKIP"] += 1
            entry["outcome"] = "SKIP"
            entry["skip_reason"] = fx["skip_reason"]
            results.append(entry)
            continue

        buffers_in = fx["buffers"]
        size = fx["size"]
        alignment = fx["alignment"]

        greedy = _run_solver(GreedyLayoutSolver, buffers_in, size, alignment)
        cpsat = _run_standalone_cpsat(
            CpSatLayoutSolver, buffers_in, size, alignment,
        )
        hybrid = _run_hybrid(
            GreedyLayoutSolver, CpSatLayoutSolver,
            buffers_in, size, alignment,
        )

        # A None ``buffers`` means the solver raised (invalid input rejected
        # or a genuine failure). ``buffers == []`` is the empty-input case
        # (well-defined objective = 0). Distinguish those.
        g_obj = _objective(greedy["buffers"]) if greedy["buffers"] is not None else None
        c_obj = _objective(cpsat["buffers"]) if cpsat["buffers"] is not None else None
        h_obj = _objective(hybrid["buffers"]) if hybrid["buffers"] is not None else None

        # Both solvers failed identically: no invariant applies, both
        # correctly rejected invalid input.
        both_failed = greedy["error"] is not None and cpsat["error"] is not None

        # Correctness invariants:
        # 1. hybrid objective is never worse than standalone cpsat objective;
        # 2. if hybrid chose greedy-certified, hybrid objective == lower
        #    bound == greedy objective (i.e. greedy left NO value on the
        #    table on placeable buffers).
        lb = _lower_bound_objective(buffers_in, size, alignment)
        if both_failed:
            invariant_1 = True
            invariant_2 = True
        else:
            invariant_1 = (
                g_obj is not None and c_obj is not None and h_obj is not None
                and h_obj <= c_obj
            )
            invariant_2 = (
                hybrid["chosen"] != "greedy-certified"
                or (h_obj == lb and g_obj == lb)
            )

        counts[hybrid["chosen"]] += 1
        entry.update(
            n_buffers=len(buffers_in), size=size, alignment=alignment,
            n_barred=sum(
                1 for b in buffers_in if b.residency_reason is not None
            ),
            lower_bound_objective=lb,
            greedy_error=greedy["error"], cpsat_error=cpsat["error"],
            hybrid_error=hybrid["error"],
            greedy_objective=g_obj,
            cpsat_objective=c_obj,
            hybrid_objective=h_obj,
            greedy_reaches_lower_bound=(g_obj == lb) if g_obj is not None else None,
            cpsat_reaches_lower_bound=(c_obj == lb) if c_obj is not None else None,
            hybrid_chosen=hybrid["chosen"],
            hybrid_cpsat_run=hybrid["cpsat_run"],
            greedy_wall_s=greedy["wall_s"],
            cpsat_wall_s=cpsat["wall_s"],
            hybrid_wall_s=(
                hybrid["greedy_probe_wall_s"] + hybrid["cpsat_wall_s"]
            ),
            hybrid_greedy_probe_wall_s=hybrid["greedy_probe_wall_s"],
            hybrid_cpsat_wall_s=hybrid["cpsat_wall_s"],
            invariant_1_hybrid_le_cpsat=bool(invariant_1),
            invariant_2_certified_iff_zero=bool(invariant_2),
        )

        if not (invariant_1 and invariant_2):
            counts["INVARIANT_VIOLATION"] += 1
            # Save divergent case for offline inspection.
            div_path = os.path.join(
                args.out, "divergences", f"{fx['name']}.json",
            )
            with open(div_path, "w") as fh:
                json.dump({
                    "name": fx["name"],
                    "size": size, "alignment": alignment,
                    "input_buffers": [_buf_dict(b) for b in buffers_in],
                    "greedy": [_buf_dict(b) for b in (greedy["buffers"] or [])],
                    "cpsat": [_buf_dict(b) for b in (cpsat["buffers"] or [])],
                    "hybrid": [_buf_dict(b) for b in (hybrid["buffers"] or [])],
                    "objectives": {
                        "greedy": g_obj, "cpsat": c_obj, "hybrid": h_obj,
                    },
                    "hybrid_chosen": hybrid["chosen"],
                    "invariants": {
                        "hybrid_le_cpsat": invariant_1,
                        "certified_iff_zero": invariant_2,
                    },
                }, fh, indent=2, default=str)
            entry["divergence_path"] = div_path

        results.append(entry)

    summary = {
        "n_total": len(results),
        "counts": dict(counts),
        "cases": results,
    }
    with open(os.path.join(args.out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2, default=str)
    print(f"total {summary['n_total']}")
    print(json.dumps(dict(counts), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
