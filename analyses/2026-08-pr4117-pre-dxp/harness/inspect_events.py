#!/usr/bin/env python3
"""Print the event tree of one timing_recorder JSON dump.

Usage:  python3 harness/inspect_events.py <run.json> [--ms-min MS]

Renders the hierarchical event tree with inclusive ms, self ms (via
child-inclusive subtraction), and per-event metadata. Used to
manually validate nesting on the pilot samples per §10.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict


def _load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _children_index(events: list[dict]) -> dict[int, list[int]]:
    idx: dict[int, list[int]] = defaultdict(list)
    for i, e in enumerate(events):
        parent = e.get("parent_ordinal")
        if parent is not None:
            idx[parent].append(i)
    return idx


def _self_ns(ev: dict, events: list[dict], child_idx: dict) -> int:
    children_inc = sum(
        events[i].get("inclusive_ns", 0)
        for i in child_idx.get(ev.get("ordinal"), [])
    )
    return ev.get("inclusive_ns", 0) - children_inc


def _fmt_meta(meta: dict) -> str:
    if not meta:
        return ""
    # Keep the interesting fields on one line.
    parts = []
    for k in ("fx_nodes_at_entry", "n_fx_nodes", "input_operations",
              "output_operations", "ops_delta", "input_nodes",
              "scheduler_nodes", "n_specs", "n_files", "kernel",
              "wrapper_cls", "passes", "cmd"):
        if k in meta:
            v = meta[k]
            if isinstance(v, list):
                v = f"[{len(v)}]"
            parts.append(f"{k}={v}")
    return " ".join(parts)


def _walk(events: list[dict], child_idx: dict, parent_ordinal, ms_min: float,
          depth: int, out: list[str]) -> None:
    # Find events whose parent_ordinal matches
    for i, ev in enumerate(events):
        if ev.get("parent_ordinal") != parent_ordinal:
            continue
        inc_ms = ev.get("inclusive_ns", 0) / 1e6
        if inc_ms < ms_min:
            continue
        self_ms = _self_ns(ev, events, child_idx) / 1e6
        indent = "  " * depth
        meta = _fmt_meta(ev.get("meta") or {})
        line = (
            f"{indent}{ev.get('name'):<48}  "
            f"inc={inc_ms:>9.2f}ms  self={self_ms:>7.2f}ms  {meta}"
        )
        out.append(line)
        _walk(events, child_idx, ev.get("ordinal"), ms_min, depth + 1, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument(
        "--ms-min", type=float, default=0.0,
        help="Hide events with inclusive_ms below this threshold.",
    )
    args = ap.parse_args()

    doc = _load(args.path)
    meta = doc.get("meta") or {}
    events = doc.get("events") or []
    if not events:
        print("no events", file=sys.stderr)
        return 2

    child_idx = _children_index(events)

    print(f"# {args.path}")
    for k in ("workload", "mode", "Lq", "Lk", "N_in", "N_hidden", "layers",
              "pre_dxp_boundary_reached", "boundary_info",
              "n_captured_kernels", "unexpected_error"):
        if k in meta:
            print(f"  {k}: {meta[k]}")
    print()

    lines: list[str] = []
    _walk(events, child_idx, None, args.ms_min, 0, lines)
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
