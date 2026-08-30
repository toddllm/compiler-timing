#!/usr/bin/env python3
"""Placement-only solver differential corpus.

For every ``BaseLayoutSolverTests`` scenario in
``tests/inductor/test_scratchpad_solver.py``, build the same
``LifetimeBoundBuffer`` set twice, hand it to ``GreedyLayoutSolver``
and to ``CpSatLayoutSolver`` (placement-only,
``co_optimizing_lx_planning=False``), and record:

* resident set (buffer names placed)
* spilled set (buffer names not placed)
* address map
* feasibility (both produced a legal layout)
* CP-SAT spill objective evaluated on cpsat's plan
* CP-SAT spill objective evaluated on greedy's plan
* whether the plans agree on placement decisions

The CP-SAT spill objective is ``sum(spill_cost(b))`` over the buffers
that the plan does NOT place (address is None). ``spill_cost`` is a
pure function of the buffer, so evaluating it on either arm's plan is
just: sum over spilled buffers.

Every case is classified as A/B/C/D/E:

* A: same resident set, same objective, same addresses.
* B: same resident set, same objective, different addresses.
* C: greedy strictly worse objective than cpsat.
* D: greedy strictly better objective than cpsat.
* E: one solver fails / produces invalid layout.

C/D fixtures are saved as reproducible artifacts in
``$out_dir/fixtures/``.
"""

from __future__ import annotations

import argparse
import copy
import inspect
import json
import os
import sys
import traceback
from typing import Any


def _spill_cost(b) -> int:
    """Same formula as
    torch_spyre._inductor.scratchpad.ilp_solver_ortools._LifetimeBufferWithCpVars.spill_cost,
    evaluated directly on a LifetimeBoundBuffer.
    """
    boundary = getattr(b, "boundary", None)
    if boundary is not None:
        # Import lazily so this module can be introspected without
        # torch_spyre installed.
        from torch_spyre._inductor.scratchpad.plan_solver import BufferType
        is_intermediate = boundary == BufferType.Intermediate
    else:
        is_intermediate = not b.first_use_is_read
    reads_served = b.read_count - (1 if b.first_use_is_read else 0)
    return (reads_served + (1 if is_intermediate else 0)) * b.size


def _objective(buffers) -> int:
    return sum(_spill_cost(b) for b in buffers if b.address is None)


def _legal(buffers, size, alignment) -> tuple[bool, str]:
    """Check the plan for capacity + alignment + no-overlap."""
    # Grouped by address, since an in-place handoff keeps two entries
    # at the same address for one shared tick; that is the only allowed
    # form of overlap (the child covers only the low buffer.size bytes
    # of the parent's slot at the handoff).
    placed = [b for b in buffers if b.address is not None]
    for b in placed:
        if b.address < 0 or b.address + b.size > size:
            return False, f"out-of-capacity: {b.name}@{b.address}+{b.size}>{size}"
        if b.address % alignment != 0:
            return False, f"misaligned: {b.name}@{b.address}%{alignment}!=0"
    # No live overlap at any tick, per-address (in-place shared slot OK).
    # Compute liveness ticks.
    if placed:
        ticks = set()
        for b in placed:
            if b.uses:
                ticks.add(b.start_time)
                ticks.add(b.end_time)
        for t in sorted(ticks):
            live_at_t = [b for b in placed if b.uses and b.start_time <= t < b.end_time]
            # For each address, only two buffers may share (in-place),
            # and one must list the other as an in_place_parent.
            by_addr: dict[int, list] = {}
            for b in live_at_t:
                by_addr.setdefault(b.address, []).append(b)
            for addr, group in by_addr.items():
                if len(group) > 2:
                    return False, f"tick {t}: {len(group)} buffers at addr={addr}"
                if len(group) == 2:
                    a, c = group
                    parent, child = (a, c) if a.size >= c.size else (c, a)
                    if parent.name not in child.in_place_parents:
                        return False, (
                            f"tick {t}: unauthorized shared addr={addr} "
                            f"between {a.name}, {c.name}"
                        )
    return True, ""


def _run_one_solver(solver_cls, buffers_in, size, alignment):
    """Run one solver against a fresh deep-copy of the buffers."""
    bufs = copy.deepcopy(buffers_in)
    try:
        solver = solver_cls(bufs, size, alignment)
        result = solver.plan_layout()
    except Exception as e:
        return {
            "error": f"{type(e).__name__}: {e}",
            "buffers": None,
        }
    ok, why = _legal(result, size, alignment)
    return {
        "error": None,
        "buffers": list(result),
        "legal": ok,
        "legal_error": why,
    }


def _classify(greedy_run, cpsat_run) -> str:
    if greedy_run["error"] or cpsat_run["error"]:
        return "E"
    if not greedy_run["legal"] or not cpsat_run["legal"]:
        return "E"
    g_bufs = greedy_run["buffers"]
    c_bufs = cpsat_run["buffers"]
    g_placed = {b.name for b in g_bufs if b.address is not None}
    c_placed = {b.name for b in c_bufs if b.address is not None}
    g_obj = _objective(g_bufs)
    c_obj = _objective(c_bufs)
    same_resident = g_placed == c_placed
    same_obj = g_obj == c_obj
    if same_resident and same_obj:
        # A: identical addresses; B: same objective different addresses.
        g_addr = {b.name: b.address for b in g_bufs}
        c_addr = {b.name: b.address for b in c_bufs}
        return "A" if g_addr == c_addr else "B"
    if g_obj > c_obj:
        return "C"
    if g_obj < c_obj:
        return "D"
    # Same objective but different resident set — treat as B.
    return "B"


def _buffer_to_json(b) -> dict:
    return {
        "name": b.name,
        "size": b.size,
        "uses": list(b.uses),
        "first_use_is_read": b.first_use_is_read,
        "in_place_parents": list(b.in_place_parents),
        "residency_reason": b.residency_reason,
        "lifetime_end_override": b.lifetime_end_override,
        "address": b.address,
    }


def _collect_fixtures():
    """Introspect BaseLayoutSolverTests. Each test method that calls
    self.solve(buffers, size, alignment) or self.verify_layout(buffers,
    ...) exposes a scenario. We stub self.solve/verify_layout to just
    capture (buffers, size, alignment) and return dummy addresses; then
    invoke each test method to get the fixture.

    We use TestGreedyLayoutSolver as the concrete host (it inherits
    BaseLayoutSolverTests). Once the fixture is captured we can
    replay the same buffers into any solver.
    """
    # Ensure torch is imported before torch_spyre (spyre backend autoload).
    import torch  # noqa: F401
    import torch_spyre  # noqa: F401

    # Import the base test class.
    sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
    # test_scratchpad_solver imports torch too; we already did that.
    from tests.inductor import test_scratchpad_solver as tss  # noqa: E402
    Base = tss.BaseLayoutSolverTests
    Host = tss.TestGreedyLayoutSolver  # concrete subclass

    from torch_spyre._inductor.scratchpad.plan_solver import LifetimeBoundBuffer

    fixtures = []
    # Discover test methods declared on Base itself (not inherited).
    method_names = [
        n for n in dir(Base)
        if n.startswith("test_")
        and callable(getattr(Base, n))
        # Only methods actually declared on Base:
        and n in Base.__dict__
    ]
    for name in sorted(method_names):
        # Fresh host per case with captured state.
        host = Host(name)
        host.last_solver = None
        captured: dict[str, Any] = {}

        def _cap_solve(buffers, size=None, alignment=1, _host=host, _cap=captured):
            _cap["buffers"] = copy.deepcopy(buffers)
            _cap["size"] = size if size is not None else tss.LARGE_SIZE
            _cap["alignment"] = alignment
            # Return the buffers unchanged (some tests inspect returned
            # addresses but with alignment=1 the addresses can stay None
            # for our capture-only pass).
            for b in buffers:
                b.address = None
            return list(buffers)

        def _cap_verify(buffers, expected_addresses,
                        size=tss.SMALL_SIZE, alignment=1,
                        _cap=captured):
            _cap["buffers"] = copy.deepcopy(buffers)
            _cap["size"] = size
            _cap["alignment"] = alignment
            for b in buffers:
                b.address = None
            return None

        host.solve = _cap_solve   # type: ignore[method-assign]
        host.verify_layout = _cap_verify  # type: ignore[method-assign]

        # A number of tests call self.assertEqual/assertRaises against
        # our captured object; those assertions may fail on our stubs.
        # Catch and record what we could capture anyway.
        skip_reason = None
        try:
            getattr(host, name)()
        except Exception as e:
            skip_reason = f"host raised: {type(e).__name__}: {e}"

        if "buffers" not in captured:
            fixtures.append({
                "name": name,
                "captured": False,
                "skip_reason": skip_reason or "no solve/verify_layout call",
                "buffers": None,
                "size": None,
                "alignment": None,
            })
            continue

        fixtures.append({
            "name": name,
            "captured": True,
            "skip_reason": skip_reason,
            "buffers": captured["buffers"],
            "size": captured["size"],
            "alignment": captured["alignment"],
        })
    return fixtures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True,
                    help="output directory (JSON summary + C/D fixtures)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(os.path.join(args.out, "fixtures"), exist_ok=True)

    fixtures = _collect_fixtures()

    from torch_spyre._inductor.scratchpad.greedy_solver import (
        GreedyLayoutSolver,
    )
    from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
        CpSatLayoutSolver,
    )

    results = []
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "SKIP": 0}
    for fx in fixtures:
        entry: dict[str, Any] = {"name": fx["name"], "captured": fx["captured"]}
        if not fx["captured"]:
            entry.update(class_="SKIP", skip_reason=fx["skip_reason"])
            counts["SKIP"] += 1
            results.append(entry)
            continue

        buffers_in = fx["buffers"]
        size = fx["size"]
        alignment = fx["alignment"]

        # Placement-only CP-SAT means we call plan_layout() on the same
        # LifetimeBoundBuffer set greedy sees.
        greedy_run = _run_one_solver(
            GreedyLayoutSolver, buffers_in, size, alignment,
        )
        cpsat_run = _run_one_solver(
            CpSatLayoutSolver, buffers_in, size, alignment,
        )

        cls_ = _classify(greedy_run, cpsat_run)
        counts[cls_] += 1

        g_bufs = greedy_run.get("buffers") or []
        c_bufs = cpsat_run.get("buffers") or []
        g_placed = [b.name for b in g_bufs if b.address is not None]
        c_placed = [b.name for b in c_bufs if b.address is not None]
        g_obj = _objective(g_bufs) if g_bufs else None
        c_obj = _objective(c_bufs) if c_bufs else None

        entry.update(
            class_=cls_,
            size=size, alignment=alignment,
            n_buffers=len(buffers_in),
            greedy_error=greedy_run.get("error"),
            cpsat_error=cpsat_run.get("error"),
            greedy_legal=greedy_run.get("legal"),
            cpsat_legal=cpsat_run.get("legal"),
            greedy_legal_error=greedy_run.get("legal_error"),
            cpsat_legal_error=cpsat_run.get("legal_error"),
            n_placed_greedy=len(g_placed),
            n_placed_cpsat=len(c_placed),
            greedy_objective=g_obj,
            cpsat_objective=c_obj,
        )

        if cls_ in ("C", "D"):
            # Save reproducible fixture.
            fx_path = os.path.join(
                args.out, "fixtures", f"{fx['name']}.json",
            )
            with open(fx_path, "w") as fh:
                json.dump(
                    {
                        "name": fx["name"],
                        "size": size,
                        "alignment": alignment,
                        "input_buffers": [
                            _buffer_to_json(b) for b in buffers_in
                        ],
                        "greedy_result": [
                            _buffer_to_json(b) for b in g_bufs
                        ],
                        "cpsat_result": [
                            _buffer_to_json(b) for b in c_bufs
                        ],
                        "greedy_objective": g_obj,
                        "cpsat_objective": c_obj,
                        "objective_delta_greedy_minus_cpsat": (
                            g_obj - c_obj
                            if g_obj is not None and c_obj is not None
                            else None
                        ),
                    },
                    fh, indent=2, default=str,
                )
            entry["fixture_path"] = fx_path

        results.append(entry)

    summary = {
        "n_total": len(results),
        "n_captured": sum(1 for r in results if r.get("captured")),
        "counts": counts,
        "cases": results,
    }
    with open(os.path.join(args.out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2, default=str)

    print(f"total {summary['n_total']} cases, "
          f"captured {summary['n_captured']}")
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
