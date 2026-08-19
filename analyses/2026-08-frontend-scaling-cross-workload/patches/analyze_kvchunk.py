#!/usr/bin/env python3
"""Consume workload-B JSON dumps and emit a decomposition table.

Groups runs by (fix_state, n_chunks) and reports per-pass medians with
compile-fx bucketing consistent with the existing #3806 study.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
from collections import defaultdict


SPYRE_PIPES = [
    "pipeline:CustomPreGradPasses",
    "pipeline:CustomPrePasses",
    "pipeline:CustomPostPasses",
    "pipeline:CustomPreFusionPasses",
    "pipeline:CustomPostFusionPasses",
    "pipeline:CustomPreSchedulingPasses",
]

TOP_PASSES = [
    "_maybe_coarse_tile_hints",
    "optimize_restickify_locations",
    "dedup_and_promote_constants",
    "_maybe_scratchpad_planning",
    "propagate_spyre_tensor_layouts",
    "_distribute_work",
    "_maybe_reorder_unhinted_interlopers",
    "enforce_indirect_access_layout",
    "span_reduction",
    "deadcode_elimination",
    "validate_ops",
    "split_multi_ops",
]


def med(vs):
    return statistics.median(vs) if vs else float("nan")


def event(d, name):
    hits = [e for e in d["events"] if e["name"] == name]
    return sum(e["inclusive_ns"] for e in hits) / 1e6 if hits else float("nan")


def spyre_pipes_ms(d):
    return sum(event(d, n) for n in SPYRE_PIPES if event(d, n) == event(d, n))


def unattributed_compile_fx_ms(d):
    cfx = event(d, "compile_fx_wrapper")
    if cfx != cfx:
        return float("nan")
    return cfx - spyre_pipes_ms(d) - event(d, "sdsc_total") - (event(d, "async_compile_wait") or 0)


def load_all(dirs):
    by = defaultdict(list)
    for pat in dirs:
        for p in sorted(glob.glob(os.path.join(pat, "*.json"))):
            base = os.path.basename(p)
            fix = "post" if "-post" in base else "pre"
            d = json.load(open(p))
            n = d.get("meta", {}).get("n_chunks")
            if n is None:
                continue
            by[(fix, int(n))].append(d)
    return by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+",
                    help="Directories containing workload-B JSONs")
    args = ap.parse_args()

    by = load_all(args.dirs)
    if not by:
        print("no runs loaded")
        return

    print(f"loaded {sum(len(v) for v in by.values())} runs "
          f"across {len(by)} (fix_state, n_chunks) points\n")

    # Table 1: high-level decomposition
    print("### Workload B — high-level decomposition (medians in seconds)\n")
    print("| fix | n_chunks | n | wall | compile_fx | dxp | Spyre pipes | sdsc_prep | unattr |")
    print("|:---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for (fix, n), runs in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        wall = med([event(r, "first_call_wall") for r in runs]) / 1000
        cfx = med([event(r, "compile_fx_wrapper") for r in runs]) / 1000
        dxp = med([event(r, "dxp_standalone") for r in runs]) / 1000
        sp = med([spyre_pipes_ms(r) for r in runs]) / 1000
        sdsc = med([event(r, "sdsc_total") for r in runs]) / 1000
        sdsc_prep = sdsc - dxp
        unattr = med([unattributed_compile_fx_ms(r) for r in runs]) / 1000
        print(f"| {fix} | {n} | {len(runs)} | {wall:.2f} | {cfx:.2f} | "
              f"{dxp:.2f} | {sp:.2f} | {sdsc_prep:.2f} | {unattr:.2f} |")
    print()

    # Table 2: per-pass medians (ms)
    print("### Per-pass medians (ms)\n")
    cols = sorted(by.keys(), key=lambda k: (k[1], k[0]))
    hdr = "| pass | " + " | ".join(f"{fix} n={n}" for fix, n in cols) + " |"
    print(hdr)
    print("|---" * (1 + len(cols)) + "|")
    for name in TOP_PASSES:
        cells = []
        for k in cols:
            vals = [event(r, f"pass:CustomPreSchedulingPasses:{name}")
                    for r in by[k]]
            vals = [v for v in vals if v == v]
            cells.append(f"{med(vals):.0f}" if vals else "-")
        print(f"| `{name}` | " + " | ".join(cells) + " |")
    print()

    # Table 3: doubling ratios (per n_chunks doubling, per fix_state)
    print("### Doubling ratios (n_chunks × 2, same fix_state)\n")
    print("| fix | pair | " + " | ".join(f"`{p}`" for p in TOP_PASSES) + " | compile_fx | dxp |")
    print("|:---|:---|" + "---:|" * (len(TOP_PASSES) + 2))
    for fix in ("pre", "post"):
        chunks = sorted(n for (f, n) in by if f == fix)
        for i in range(len(chunks) - 1):
            a, b = chunks[i], chunks[i + 1]
            if b != 2 * a:
                continue
            cells = []
            for name in TOP_PASSES:
                ta = med([event(r, f"pass:CustomPreSchedulingPasses:{name}") for r in by[(fix, a)]])
                tb = med([event(r, f"pass:CustomPreSchedulingPasses:{name}") for r in by[(fix, b)]])
                if ta != ta or tb != tb or ta == 0:
                    cells.append("-")
                else:
                    cells.append(f"{tb/ta:.2f}×")
            cfx_a = med([event(r, "compile_fx_wrapper") for r in by[(fix, a)]])
            cfx_b = med([event(r, "compile_fx_wrapper") for r in by[(fix, b)]])
            dxp_a = med([event(r, "dxp_standalone") for r in by[(fix, a)]])
            dxp_b = med([event(r, "dxp_standalone") for r in by[(fix, b)]])
            cells.append(f"{cfx_b/cfx_a:.2f}×")
            cells.append(f"{dxp_b/dxp_a:.2f}×")
            print(f"| {fix} | {a}→{b} | " + " | ".join(cells) + " |")
    print()

    # Structural counters
    print("### Structural counters (medians)\n")
    print("| fix | n_chunks | n | FX@entry | n_specs | dedup input_ops | dedup dups |")
    print("|:---|---:|---:|---:|---:|---:|---:|")
    for k, runs in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        fix, n = k
        fx = med([next((e["meta"]["fx_nodes_at_entry"] for e in r["events"]
                        if e["name"] == "compile_fx_wrapper" and "fx_nodes_at_entry" in e.get("meta", {})),
                       float("nan")) for r in runs])
        nsp = med([next((e["meta"].get("n_specs") for e in r["events"]
                         if e["name"] == "sdsc_bundle_gen"),
                        float("nan")) for r in runs])
        d_iop = med([next((e["meta"].get("input_operations")
                           for e in r["events"]
                           if e["name"] == "pass:CustomPreSchedulingPasses:dedup_and_promote_constants"),
                          float("nan")) for r in runs])
        d_dups = med([-next((e["meta"].get("ops_delta") or 0
                             for e in r["events"]
                             if e["name"] == "pass:CustomPreSchedulingPasses:dedup_and_promote_constants"),
                            0) for r in runs])
        print(f"| {fix} | {n} | {len(runs)} | {int(fx)} | {int(nsp)} | {int(d_iop)} | {int(d_dups)} |")


if __name__ == "__main__":
    main()
