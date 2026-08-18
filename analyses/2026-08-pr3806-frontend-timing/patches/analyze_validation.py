#!/usr/bin/env python3
"""Decompose ``unattributed_compile_fx`` using the ``extra_timers`` events.

Reads validation runs from ``data-validation/*.json`` (produced by
``run_validation.sh`` on a pod with ``extra_timers.py`` active) and
writes ``notes/tables/unattributed-decomposition.md``.

The extra_timers module records three boundaries inside
``compile_fx_wrapper`` that are not otherwise instrumented:
``graphlowering_run``, ``graphlowering_compile_to_fn``, and
``spyre_kernel_codegen``. ``compile_to_fn`` nests ``sdsc_total`` and
``spyre_kernel_codegen`` inside itself, so the wrapper/scheduler/fusion
share is ``compile_to_fn − sdsc_total − spyre_kernel_codegen``.
"""

from __future__ import annotations

import glob
import json
import os
import statistics
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
VAL_DATA = os.path.join(STUDY, "data-validation")
TABLES = os.path.join(STUDY, "notes", "tables")


def load_runs() -> dict[tuple[int, int], list[dict]]:
    by = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(VAL_DATA, "*.json"))):
        base = os.path.basename(path)
        if "-run" not in base or not base.endswith(".json"):
            continue
        stem = base[:-len(".json")]
        try:
            lqxlk, _ = stem.split("-run")
            lq, lk = (int(x) for x in lqxlk.split("x"))
        except ValueError:
            continue
        with open(path) as f:
            by[(lq, lk)].append(json.load(f))
    return by


def event(run: dict, name: str) -> dict | None:
    for e in run["events"]:
        if e["name"] == name:
            return e
    return None


def sum_ms(run: dict, name: str) -> float:
    return sum(e["inclusive_ns"]
               for e in run["events"] if e["name"] == name) / 1e6


def med(vs: list[float]) -> float:
    return statistics.median(vs) if vs else float("nan")


SPYRE_PIPES = [
    "pipeline:CustomPreGradPasses",
    "pipeline:CustomPrePasses",
    "pipeline:CustomPostPasses",
    "pipeline:CustomPreFusionPasses",
    "pipeline:CustomPostFusionPasses",
    "pipeline:CustomPreSchedulingPasses",
]


def spyre_pass_total_ms(run: dict) -> float:
    return sum(sum_ms(run, n) for n in SPYRE_PIPES)


def main() -> None:
    by = load_runs()
    if not by:
        print("no validation runs found in data-validation/")
        return
    lines = []
    lines.append("### Decomposition of `unattributed_compile_fx`")
    lines.append("")
    lines.append(
        "Derived from validation runs (`data-validation/`) captured with "
        "the `extra_timers` hook enabled. Adds three boundaries inside "
        "`compile_fx_wrapper`:"
    )
    lines.append("")
    lines.append("- `graphlowering_run` — upstream Inductor lowering (FX → IR).")
    lines.append("- `graphlowering_compile_to_fn` — upstream Inductor codegen.")
    lines.append("- `spyre_kernel_codegen` — Spyre-specific `SpyreKernel.codegen_kernel`.")
    lines.append("")
    lines.append(
        "`graphlowering_compile_to_fn` nests `sdsc_total` (already timed) "
        "and each `spyre_kernel_codegen` call, so the "
        "wrapper/scheduler/fusion cost is "
        "`compile_to_fn − sdsc_total − spyre_kernel_codegen`."
    )
    lines.append("")
    lines.append(
        "| Lq | Lk | n | compile_fx (s) | graphlowering_run (s) | "
        "graphlowering_compile_to_fn (s) | spyre_kernel_codegen (s) | "
        "sdsc_total (s) | compile_to_fn_self (s) | residual (s) |"
    )
    lines.append(
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for (lq, lk), runs in sorted(by.items()):
        cfx = med([event(r, "compile_fx_wrapper")["inclusive_ns"]/1e6 for r in runs]) / 1000
        gl_run = med([sum_ms(r, "graphlowering_run") for r in runs]) / 1000
        gl_ctf = med([sum_ms(r, "graphlowering_compile_to_fn") for r in runs]) / 1000
        skc = med([sum_ms(r, "spyre_kernel_codegen") for r in runs]) / 1000
        sdsc = med([sum_ms(r, "sdsc_total") for r in runs]) / 1000
        ctf_self = gl_ctf - sdsc - skc
        pipes = med([spyre_pass_total_ms(r) for r in runs]) / 1000
        residual = cfx - gl_run - gl_ctf - pipes
        lines.append(
            f"| {lq} | {lk} | {len(runs)} | {cfx:.2f} | {gl_run:.2f} | "
            f"{gl_ctf:.2f} | {skc:.2f} | {sdsc:.2f} | "
            f"{ctf_self:.2f} | {residual:.2f} |"
        )
    lines.append("")
    lines.append("Reading the columns:")
    lines.append("")
    lines.append(
        "- `graphlowering_run` measures upstream Inductor FX-to-IR "
        "lowering. If this is a large share of what was previously "
        "`unattributed_compile_fx`, upstream Inductor lowering is the "
        "next candidate for finer instrumentation."
    )
    lines.append(
        "- `compile_to_fn_self` (the derived column) captures wrapper "
        "codegen and upstream scheduler/fusion work."
    )
    lines.append(
        "- `residual` is everything inside `compile_fx_wrapper` that "
        "runs outside `GraphLowering.run` and outside the Spyre pass "
        "pipelines: AOTAutograd joint-graph decomposition, pre-grad "
        "pass barrier, config wiring."
    )
    lines.append("")

    os.makedirs(TABLES, exist_ok=True)
    path = os.path.join(TABLES, "unattributed-decomposition.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
