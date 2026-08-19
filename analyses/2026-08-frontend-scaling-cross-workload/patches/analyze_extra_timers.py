#!/usr/bin/env python3
"""Consume workload timing JSONs with extra_timers events and report
the closed decomposition of compile_fx_wrapper.

Buckets:
  - graphlowering_run          (upstream Inductor: FX → IR lowering)
  - graphlowering_codegen      (upstream + Spyre pass pipelines + kernel codegen)
  - sdsc_total                 (SDSC prep + dxp_standalone)
  - async_compile_wait
  - unattributed_compile_fx    (residual)

If graphlowering_codegen is present, it wraps `pipeline:CustomPre*`
events plus `spyre_kernel_codegen` — so we can further split:
  - Spyre pass pipelines (already timed)
  - spyre_kernel_codegen (per-kernel)
  - "codegen residual" = graphlowering_codegen − spyre_pipes − spyre_kernel_codegen
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


def med(vs): return statistics.median(vs) if vs else float("nan")

def ev(d, name):
    hits = [e for e in d["events"] if e["name"] == name]
    return sum(e["inclusive_ns"] for e in hits) / 1e6 if hits else float("nan")

def spyre_pipes_ms(d):
    total = 0.0
    for n in SPYRE_PIPES:
        e = ev(d, n)
        if e == e:
            total += e
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    args = ap.parse_args()

    by = defaultdict(list)
    for pat in args.dirs:
        for p in sorted(glob.glob(os.path.join(pat, "*.json"))):
            d = json.load(open(p))
            m = d.get("meta", {})
            n = m.get("n_chunks")
            if n is None:
                # Workload A JSON: key on Lq×Lk
                lq, lk = m.get("Lq"), m.get("Lk")
                if lq is None or lk is None:
                    continue
                key = ("A", f"{lq}x{lk}")
            else:
                key = ("B", f"n{n}")
            by[key].append(d)

    print(f"Loaded {sum(len(v) for v in by.values())} runs across {len(by)} points\n")

    print("### Extra-timers closed decomposition (medians, ms)\n")
    print(f"{'point':>10} {'n':>3} {'compile_fx':>12} {'gl_run':>9} {'gl_codegen':>11} "
          f"{'sdsc':>8} {'async_wait':>10} {'unattr':>9} {'unattr %':>10}")
    print("-" * 96)
    for key in sorted(by.keys()):
        runs = by[key]
        cfx = med([ev(r, "compile_fx_wrapper") for r in runs])
        gr = med([ev(r, "graphlowering_run") for r in runs])
        gc = med([ev(r, "graphlowering_codegen") for r in runs])
        sdsc = med([ev(r, "sdsc_total") for r in runs])
        aw = med([ev(r, "async_compile_wait") for r in runs])
        aw = 0.0 if aw != aw else aw
        # per-run unattributed
        unattr_per_run = []
        for r in runs:
            _cfx = ev(r, "compile_fx_wrapper")
            _gr = ev(r, "graphlowering_run"); _gr = 0 if _gr != _gr else _gr
            _gc = ev(r, "graphlowering_codegen"); _gc = 0 if _gc != _gc else _gc
            _sdsc = ev(r, "sdsc_total"); _sdsc = 0 if _sdsc != _sdsc else _sdsc
            _aw = ev(r, "async_compile_wait"); _aw = 0 if _aw != _aw else _aw
            unattr_per_run.append(_cfx - _gr - _gc - _sdsc - _aw)
        unattr = med(unattr_per_run)
        pct = 100 * unattr / cfx if cfx else float("nan")
        wl, tag = key
        print(f"{wl+':'+tag:>10} {len(runs):>3} {cfx:>12.0f} {gr:>9.0f} {gc:>11.0f} "
              f"{sdsc:>8.0f} {aw:>10.0f} {unattr:>9.0f} {pct:>9.1f}%")
    print()

    # Detailed codegen split for workload B
    print("### graphlowering_codegen sub-decomposition (medians, ms)\n")
    print(f"{'point':>10} {'gl_codegen':>11} {'Spyre pipes':>11} {'kernel_codegen':>15} {'codegen residual':>17}")
    for key in sorted(by.keys()):
        runs = by[key]
        gc = med([ev(r, "graphlowering_codegen") for r in runs])
        sp = med([spyre_pipes_ms(r) for r in runs])
        sk = med([ev(r, "spyre_kernel_codegen") for r in runs])
        sk = 0.0 if sk != sk else sk
        residual = gc - sp - sk if gc == gc else float("nan")
        wl, tag = key
        print(f"{wl+':'+tag:>10} {gc:>11.0f} {sp:>11.0f} {sk:>15.0f} {residual:>17.0f}")


if __name__ == "__main__":
    main()
