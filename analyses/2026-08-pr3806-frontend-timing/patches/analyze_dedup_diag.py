#!/usr/bin/env python3
"""Analyze dedup_diagnostics JSON dumps produced by run_dedup_diag.sh.

Reads all ``dedup-*.json`` files matching a glob, computes medians per
(Lq, Lk) point, and prints the tables required by the phase-2 decision
report:

  * Cost decomposition: per-point wall-clock split of dedup total into
    grouping / redirect (with get_read_writes subtracted) /
    get_read_writes / list-remove / provenance / bookkeeping /
    front-load / other.
  * Consumer-index evidence: per-point aggregates of gold vs
    name_to_users comparison. Reports TP, FP, FN, unwrap failures,
    consumer-type distribution.

Usage:

    python analyze_dedup_diag.py 'data-diag/dedup-*.json'

Prints Markdown tables to stdout. Copy into the phase-2 report.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from collections import defaultdict
from typing import Any


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else float("nan")


def _load(paths: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in paths:
        try:
            with open(p) as f:
                d = json.load(f)
            d["_path"] = p
            out.append(d)
        except Exception as e:
            print(f"warn: {p}: {e}", file=sys.stderr)
    return out


def _point_from_path(path: str) -> str:
    # dedup-<Lq>x<Lk>-runN.json
    base = path.rsplit("/", 1)[-1]
    if base.startswith("dedup-"):
        base = base[len("dedup-"):]
    if base.endswith(".json"):
        base = base[:-len(".json")]
    return base.split("-run")[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("glob_pattern")
    ap.add_argument("--which-invocation", type=int, default=-1,
                    help="Which dedup invocation ordinal to analyze (default -1 "
                         "= the last one, which is the compile-fx main pass). "
                         "Use 0 to see the first, or specify a positive value "
                         "if there are multiple compiles per run.")
    args = ap.parse_args()

    paths = sorted(glob.glob(args.glob_pattern))
    if not paths:
        print(f"error: no files match {args.glob_pattern!r}", file=sys.stderr)
        sys.exit(2)

    runs = _load(paths)
    by_point: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        pt = _point_from_path(r["_path"])
        records = r.get("records", [])
        if not records:
            continue
        idx = args.which_invocation
        if idx < 0:
            idx = len(records) + idx
        if idx < 0 or idx >= len(records):
            continue
        rec = records[idx]
        by_point[pt].append(rec)

    # -------- cost decomposition --------
    print("### Cost decomposition (median ms per point)")
    print()
    print("| point (Lq×Lk) | samples | total | grouping | redirect(scan) | "
          "get_read_writes | list_remove | merge_provenance | bookkeeping | "
          "front_load | other |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for pt in sorted(by_point):
        recs = by_point[pt]
        totals: list[float] = []
        rows = []
        for r in recs:
            t = r.get("timings_ns", {})
            total = t.get("dedup_total", 0)
            g = t.get("grouping", 0)
            redirect = t.get("redirect", 0)
            grw = t.get("get_read_writes", 0)
            probe = t.get("reads_probe", 0)
            patch_ = t.get("patch_inner_fn", 0)
            drop = t.get("drop", 0)
            mp = t.get("merge_provenance", 0)
            rm = t.get("operations_remove", 0)
            bk = t.get("bookkeeping", 0)
            fl = t.get("front_load", 0)
            # redirect(scan) is the outer-loop wall-clock in redirect
            # MINUS the time attributed to get_read_writes and probe
            # and patch_inner_fn (which live inside redirect).
            redirect_scan = redirect - grw - probe - patch_
            other = total - (g + redirect + drop + fl)
            rows.append({
                "total": total, "g": g, "redirect_scan": redirect_scan,
                "grw": grw, "rm": rm, "mp": mp, "bk": bk, "fl": fl,
                "other": other,
            })
            totals.append(total)

        def m(key: str) -> float:
            return _median([r[key] for r in rows]) / 1e6  # ns -> ms

        print(f"| {pt} | {len(recs)} | {_median(totals)/1e6:.2f} | "
              f"{m('g'):.3f} | {m('redirect_scan'):.3f} | {m('grw'):.3f} | "
              f"{m('rm'):.3f} | {m('mp'):.3f} | {m('bk'):.3f} | "
              f"{m('fl'):.3f} | {m('other'):.3f} |")

    # -------- percentages --------
    print()
    print("### Cost decomposition (percent of dedup total, median)")
    print()
    print("| point | grouping | redirect(scan) | get_read_writes | list_remove | "
          "merge_provenance | bookkeeping | front_load | other |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for pt in sorted(by_point):
        recs = by_point[pt]
        pcts = {k: [] for k in [
            "g", "redirect_scan", "grw", "rm", "mp", "bk", "fl", "other",
        ]}
        for r in recs:
            t = r.get("timings_ns", {})
            total = max(1, t.get("dedup_total", 1))
            grw = t.get("get_read_writes", 0)
            probe = t.get("reads_probe", 0)
            patch_ = t.get("patch_inner_fn", 0)
            redirect = t.get("redirect", 0)
            redirect_scan = redirect - grw - probe - patch_
            drop = t.get("drop", 0)
            g = t.get("grouping", 0)
            fl = t.get("front_load", 0)
            other = t.get("dedup_total", 0) - (g + redirect + drop + fl)
            pcts["g"].append(100 * g / total)
            pcts["redirect_scan"].append(100 * redirect_scan / total)
            pcts["grw"].append(100 * grw / total)
            pcts["rm"].append(100 * t.get("operations_remove", 0) / total)
            pcts["mp"].append(100 * t.get("merge_provenance", 0) / total)
            pcts["bk"].append(100 * t.get("bookkeeping", 0) / total)
            pcts["fl"].append(100 * fl / total)
            pcts["other"].append(100 * other / total)
        row = " | ".join(f"{_median(pcts[k]):.1f}%" for k in [
            "g", "redirect_scan", "grw", "rm", "mp", "bk", "fl", "other",
        ])
        print(f"| {pt} | {row} |")

    # -------- consumer-index evidence --------
    print()
    print("### Consumer-index evidence (name_to_users vs gold scan)")
    print()
    print("| point | dups | median gold consumers/dup | median NU raw/dup | "
          "median NU unique/dup | Σ TP | Σ FP | Σ FN | Σ unwrap fail | "
          "consumer types (count) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for pt in sorted(by_point):
        recs = by_point[pt]
        dups_total = 0
        gold_counts: list[int] = []
        nu_raw_counts: list[int] = []
        nu_unique_counts: list[int] = []
        tp = fp = fn = unwrap = 0
        types_agg: dict[str, int] = defaultdict(int)
        for r in recs:
            counts = r.get("counts", {})
            dups_total += counts.get("n_duplicates", 0)
            for d in r.get("per_duplicate", []):
                gold_counts.append(d.get("gold_consumer_count", 0))
                nu_raw_counts.append(d.get("nu_raw_entry_count", 0))
                nu_unique_counts.append(d.get("nu_unique_op_count", 0))
                tp += d.get("nu_true_positives", 0)
                fp += d.get("nu_false_positives", 0)
                fn += d.get("nu_false_negatives", 0)
                unwrap += d.get("nu_unwrap_failures", 0)
                for k, v in d.get("nu_consumer_types", {}).items():
                    types_agg[k] += v
        types_str = ", ".join(
            f"{k}={v}" for k, v in sorted(types_agg.items(), key=lambda kv: -kv[1])
        ) or "(none)"
        print(f"| {pt} | {dups_total} | "
              f"{_median(gold_counts) if gold_counts else 0:.0f} | "
              f"{_median(nu_raw_counts) if nu_raw_counts else 0:.0f} | "
              f"{_median(nu_unique_counts) if nu_unique_counts else 0:.0f} | "
              f"{tp} | {fp} | {fn} | {unwrap} | {types_str} |")

    # -------- headline verdict --------
    total_fn = 0
    for pt, recs in by_point.items():
        for r in recs:
            for d in r.get("per_duplicate", []):
                total_fn += d.get("nu_false_negatives", 0)
    print()
    print(f"### Verdict")
    print()
    if total_fn == 0:
        print(f"- name_to_users has **zero false negatives** across the sweep. "
              f"Option A is viable.")
    else:
        print(f"- name_to_users has **{total_fn} false negatives** across the "
              f"sweep. Option A requires a `get_read_writes` filter over the "
              f"union of the candidate set and the full-scan gold set, or "
              f"Option E should be preferred.")


if __name__ == "__main__":
    main()
