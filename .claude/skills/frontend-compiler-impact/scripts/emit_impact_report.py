#!/usr/bin/env python3
"""Construct the machine-readable `impact.json` for one case.

Usage:
    emit_impact_report.py \
        --target target.json \
        --triage triage.json \
        --prediction prediction.json \
        [--base-data 'sentinel:point:path/*.json'] ... \
        [--head-data 'sentinel:point:path/*.json'] ... \
        --classification NO_MEASURABLE_FRONTEND_IMPACT \
        --confidence high \
        --device-used-seconds 720 \
        --device-avoided-seconds 3600 \
        --notes "..."

Emits the JSON validating against
`references/impact-report.schema.json`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import statistics
import sys
from collections import defaultdict


SPYRE_PIPES = [
    "pipeline:CustomPreGradPasses",
    "pipeline:CustomPrePasses",
    "pipeline:CustomPostPasses",
    "pipeline:CustomPreFusionPasses",
    "pipeline:CustomPostFusionPasses",
    "pipeline:CustomPreSchedulingPasses",
]
KEY_METRICS = [
    "compile_fx_wrapper",
    "sdsc_total",
    "sdsc_bundle_gen",
    "dxp_standalone",
    "async_compile_wait",
] + SPYRE_PIPES + [
    "pass:CustomPreSchedulingPasses:_maybe_coarse_tile_hints",
    "pass:CustomPreSchedulingPasses:dedup_and_promote_constants",
    "pass:CustomPreSchedulingPasses:optimize_restickify_locations",
    "pass:CustomPreSchedulingPasses:_maybe_scratchpad_planning",
    "pass:CustomPreSchedulingPasses:propagate_spyre_tensor_layouts",
    "pass:CustomPreSchedulingPasses:_distribute_work",
]


def load_files(patterns: list[str]) -> dict[str, list[dict]]:
    """patterns: 'sentinel:point:glob' — return dict[(sentinel,point)] -> [runs]."""
    result: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for pat in patterns or []:
        sentinel, point, path = pat.split(":", 2)
        for p in sorted(glob.glob(path)):
            result[(sentinel, point)].append(json.load(open(p)))
    return result


def ev(d: dict, name: str) -> float:
    hits = [e for e in d["events"] if e["name"] == name]
    return sum(e["inclusive_ns"] for e in hits) / 1e6 if hits else float("nan")


def med(vs: list[float]) -> float:
    return statistics.median(vs) if vs else float("nan")


def summarize(runs: list[dict], metric: str) -> dict:
    vs = [ev(r, metric) for r in runs]
    vs = [v for v in vs if v == v]
    if not vs:
        return {}
    return {"median_ms": med(vs), "min_ms": min(vs), "max_ms": max(vs), "n": len(vs)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--triage", required=True)
    ap.add_argument("--prediction", required=False)
    ap.add_argument("--base-data", action="append", default=[])
    ap.add_argument("--head-data", action="append", default=[])
    ap.add_argument("--classification", required=True)
    ap.add_argument("--confidence", required=True)
    ap.add_argument("--device-used-seconds", type=float, default=0.0)
    ap.add_argument("--device-avoided-seconds", type=float, default=0.0)
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    target = json.load(open(args.target))
    triage = json.load(open(args.triage))
    prediction = json.load(open(args.prediction)) if args.prediction else None

    base_runs = load_files(args.base_data)
    head_runs = load_files(args.head_data)

    # Combine measurements. Key format: "<sentinel>:<point>:<metric>"
    measurements = {}
    for key in set(list(base_runs.keys()) + list(head_runs.keys())):
        sentinel, point = key
        for metric in KEY_METRICS:
            base_summary = summarize(base_runs.get(key, []), metric)
            head_summary = summarize(head_runs.get(key, []), metric)
            if not base_summary and not head_summary:
                continue
            entry = {
                "base_median_ms": base_summary.get("median_ms"),
                "base_min_ms": base_summary.get("min_ms"),
                "base_max_ms": base_summary.get("max_ms"),
                "base_n": base_summary.get("n", 0),
                "head_median_ms": head_summary.get("median_ms"),
                "head_min_ms": head_summary.get("min_ms"),
                "head_max_ms": head_summary.get("max_ms"),
                "head_n": head_summary.get("n", 0),
            }
            bm = entry.get("base_median_ms")
            hm = entry.get("head_median_ms")
            if bm and hm and bm == bm and hm == hm:
                entry["delta_ms"] = hm - bm
                entry["delta_pct"] = 100 * (hm - bm) / bm
            measurements[f"{sentinel}:{point}:{metric}"] = entry

    # Structural deltas
    structural_deltas = {}
    for key in set(list(base_runs.keys()) + list(head_runs.keys())):
        sentinel, point = key
        for r_list, revision in ((base_runs.get(key, []), "base"), (head_runs.get(key, []), "head")):
            if not r_list:
                continue
            for r in r_list[:1]:
                for e in r["events"]:
                    m = e.get("meta", {})
                    if e["name"] == "compile_fx_wrapper" and "fx_nodes_at_entry" in m:
                        structural_deltas.setdefault(f"{sentinel}:{point}:fx_nodes_at_entry", {})[revision] = m["fx_nodes_at_entry"]
                    if e["name"] == "sdsc_bundle_gen" and "n_specs" in m:
                        structural_deltas.setdefault(f"{sentinel}:{point}:n_specs", {})[revision] = m["n_specs"]
                    if e["name"] == "pass:CustomPreSchedulingPasses:dedup_and_promote_constants":
                        if "input_operations" in m:
                            structural_deltas.setdefault(f"{sentinel}:{point}:dedup_input_operations", {})[revision] = m["input_operations"]
                        if "ops_delta" in m:
                            structural_deltas.setdefault(f"{sentinel}:{point}:dedup_ops_delta", {})[revision] = m["ops_delta"]
                break
    for k, v in structural_deltas.items():
        v["changed"] = ("base" in v and "head" in v and v["base"] != v["head"])

    report = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target": {k: target.get(k) for k in ("kind", "repo", "pr_number", "pr_url", "url",
                                              "base_ref", "head_ref", "commit_range", "branch") if target.get(k) is not None},
        "base_sha": target.get("base_sha", ""),
        "head_sha": target.get("head_sha", ""),
        "diff_summary": {
            "files_changed": len(target.get("changed_files", [])),
            "changed_files": target.get("changed_files", []),
        },
        "static_impact": triage.get("static_impact", []),
        "level_decision": triage.get("level_decision", {}),
        "measurements": measurements,
        "structural_deltas": structural_deltas,
        "classification": args.classification,
        "confidence": args.confidence,
        "device_time_used_seconds": args.device_used_seconds,
        "device_time_avoided_seconds": args.device_avoided_seconds,
        "notes": args.notes,
    }
    if prediction:
        report["prediction"] = prediction

    # Normalize target.pr_url
    if "pr_url" not in report["target"] and target.get("url"):
        report["target"]["pr_url"] = target["url"]

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
