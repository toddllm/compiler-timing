#!/usr/bin/env python3
"""Sanity checks for a `timing_recorder` JSON sample.

Verifies the invariants documented in `references/interpretation-guide.md`:

  1. For each event `e` with nested children `c1..cn`,
     `sum(c.inclusive_ns for c in children) <= e.inclusive_ns`.
  2. For each event, `self_ns == inclusive_ns - sum(children.inclusive_ns)`
     (allowing 1 ms of measurement noise).
  3. For each leaf event (no children), `self_ns == inclusive_ns`.
  4. `parent_ordinal` of each child is the `ordinal` of some earlier
     event, and the child event's start/end times are contained in the
     parent's.

Usage:
    check_timing_json.py <file.json> [<file.json> ...]

Exit codes:
    0 — all files pass every invariant.
    1 — at least one invariant failed.
    2 — usage / IO error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

NOISE_NS = 1_000_000  # 1 ms slack — recorder overhead


def check_one(path: Path) -> list[str]:
    with open(path) as f:
        data = json.load(f)
    events = data.get("events", [])
    by_ord = {e["ordinal"]: e for e in events}
    children_of: dict[int, list[dict]] = {}
    for e in events:
        p = e.get("parent_ordinal")
        if p is not None:
            children_of.setdefault(p, []).append(e)

    errors: list[str] = []

    for e in events:
        name = e["name"]
        ord_ = e["ordinal"]
        incl = e["inclusive_ns"]
        selfns = e["self_ns"]
        p = e.get("parent_ordinal")
        children = children_of.get(ord_, [])
        children_incl = sum(c["inclusive_ns"] for c in children)

        # 1. children_incl <= incl (allow noise)
        if children_incl > incl + NOISE_NS:
            errors.append(
                f"{path.name}: event #{ord_} {name!r} children_incl={children_incl}ns "
                f"exceeds inclusive_ns={incl}ns by {children_incl - incl}ns"
            )

        # 2. self == inclusive - children_incl (approx)
        derived_self = incl - children_incl
        if abs(derived_self - selfns) > NOISE_NS:
            errors.append(
                f"{path.name}: event #{ord_} {name!r} self_ns={selfns}ns "
                f"does not match inclusive - Σchildren = {derived_self}ns "
                f"(diff {selfns - derived_self}ns)"
            )

        # 3. leaves: self == inclusive
        if not children:
            if abs(selfns - incl) > NOISE_NS:
                errors.append(
                    f"{path.name}: leaf event #{ord_} {name!r} self_ns={selfns}ns "
                    f"!= inclusive_ns={incl}ns"
                )

        # 4. parent-ordinal + time containment
        if p is not None:
            if p not in by_ord:
                errors.append(
                    f"{path.name}: event #{ord_} {name!r} has parent_ordinal={p} "
                    f"which does not exist"
                )
            else:
                parent = by_ord[p]
                if not (parent["t_start_ns"] <= e["t_start_ns"] and
                        e["t_end_ns"] <= parent["t_end_ns"]):
                    errors.append(
                        f"{path.name}: event #{ord_} {name!r} times "
                        f"[{e['t_start_ns']}, {e['t_end_ns']}] are not within "
                        f"parent #{p} {parent['name']!r} times "
                        f"[{parent['t_start_ns']}, {parent['t_end_ns']}]"
                    )

    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    total_files = 0
    files_with_errors = 0
    all_errors: list[str] = []
    for arg in argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"FATAL: no such file: {arg}", file=sys.stderr)
            return 2
        total_files += 1
        errs = check_one(p)
        if errs:
            files_with_errors += 1
            all_errors.extend(errs)

    if all_errors:
        for e in all_errors:
            print(e)
        print()
        print(f"# {files_with_errors}/{total_files} file(s) failed at least one invariant")
        return 1
    print(f"# {total_files} file(s) OK — all invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
