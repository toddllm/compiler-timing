#!/usr/bin/env python3
"""Consume a target record (from resolve_target.sh) and emit per-file
static impact classification.

Reads the target record from stdin OR from a filename argument.

The mapping rules are the "operational" version of
`references/compiler-stage-map.md`. When rules change there, update
this file too — the mapping is intentionally duplicated because
tests + human review use the markdown file while the script uses
this table.

Output: JSON list on stdout, one entry per changed file.

Usage:
    resolve_target.sh 3890 | static_triage.py
    static_triage.py /tmp/target.json
"""
from __future__ import annotations

import json
import re
import sys

# Rule table. Order matters — first match wins.
#
# Each entry: (path_regex, stage, hot_path, confidence, rule_id)
#
# hot_path:
#   yes       — change is on a timed compile path
#   gated     — activates only under a feature flag / argument
#   no        — validation/setup/error/test/runtime
#   uncertain — needs Level-1 assessment to decide
RULES = [
    # ------------------------------------------------------------------ Level 0 categorical
    (r"^tests/",                            "test_only",       "no",         "high",   "R-tests-only"),
    (r"^docs/",                             "docs",            "no",         "high",   "R-docs-only"),
    (r"^\.github/",                         "ci_only",         "no",         "high",   "R-ci-only"),
    (r"\.gitignore$",                       "meta",            "no",         "high",   "R-meta"),
    (r"^\.pre-commit",                      "ci_only",         "no",         "high",   "R-ci-only"),
    (r"^README(\.[^/]+)?$",                 "docs",            "no",         "high",   "R-docs-only"),
    (r"^LICENSE$",                          "meta",            "no",         "high",   "R-meta"),
    (r"^CHANGELOG(\.[^/]+)?$",              "docs",            "no",         "high",   "R-docs-only"),
    (r"\.md$",                              "docs",            "no",         "medium", "R-md-file"),
    (r"^requirements(\.[^/]+)?$",           "build",           "no",         "medium", "R-build-config"),
    (r"^pyproject\.toml$",                  "build",           "no",         "medium", "R-build-config"),
    (r"^setup\.(py|cfg)$",                  "build",           "no",         "medium", "R-build-config"),
    # ------------------------------------------------------------------ measured hot spots
    (r"torch_spyre/_inductor/dedup_constants\.py",
     "dedup", "yes", "high", "R-dedup"),
    (r"torch_spyre/_inductor/wsr/coarse_tile\.py",
     "coarse_tile", "yes", "high", "R-coarse-tile"),
    (r"torch_spyre/_inductor/wsr/coarse_tile_hints\.py",
     "coarse_tile_hints", "uncertain", "medium", "R-coarse-tile-hints"),
    (r"torch_spyre/_inductor/optimize_restickify\.py",
     "restickify", "yes", "high", "R-restickify"),
    (r"torch_spyre/_inductor/propagate_layouts\.py",
     "layout_prop", "yes", "high", "R-layout-prop"),
    (r"torch_spyre/_inductor/propagate_hints\.py",
     "hint_prop", "yes", "medium", "R-hint-prop"),
    (r"torch_spyre/_inductor/wsr/propagate_named_dims\.py",
     "named_dim_prop", "yes", "medium", "R-named-dim"),
    (r"torch_spyre/_inductor/insert_restickify\.py",
     "insert_restickify", "yes", "medium", "R-insert-restickify"),
    (r"torch_spyre/_inductor/scratchpad/",
     "scratchpad", "uncertain", "medium", "R-scratchpad"),
    (r"torch_spyre/_inductor/fusion\.py",
     "fusion", "yes", "medium", "R-fusion"),
    (r"torch_spyre/_inductor/scheduler\.py",
     "scheduler", "yes", "medium", "R-scheduler"),
    (r"torch_spyre/_inductor/work_division",
     "work_division", "yes", "medium", "R-work-division"),
    (r"torch_spyre/_inductor/spyre_kernel\.py",
     "kernel_codegen", "no", "medium", "R-kernel-codegen"),
    (r"torch_spyre/_inductor/lowering\.py",
     "ir_lowering", "yes", "medium", "R-lowering"),
    (r"torch_spyre/_inductor/decompositions\.py",
     "decompositions", "yes", "medium", "R-decompositions"),
    (r"torch_spyre/_inductor/__init__\.py",
     "compile_fx_wrapper_setup", "yes", "medium", "R-compile-fx-init"),
    (r"torch_spyre/_inductor/patches\.py",
     "compile_fx_wrapper_setup", "yes", "medium", "R-patches"),
    (r"torch_spyre/_inductor/enforce_indirect_access_layout\.py",
     "enforce_indirect_access", "yes", "medium", "R-enforce-indirect"),
    (r"torch_spyre/_inductor/split_multi_ops\.py",
     "split_multi_ops", "yes", "medium", "R-split-multi-ops"),
    (r"torch_spyre/_inductor/deadcode_elimination\.py",
     "dce", "yes", "medium", "R-dce"),
    (r"torch_spyre/_inductor/hbm_pool_planning\.py",
     "hbm_planning", "yes", "medium", "R-hbm-planning"),
    (r"torch_spyre/_inductor/pass_utils\.py",
     "pass_utils", "yes", "medium", "R-pass-utils"),
    # ------------------------------------------------------------------ C-extension
    (r"torch_spyre/csrc/", "csrc", "uncertain", "medium", "R-csrc"),
    # ------------------------------------------------------------------ backend / runtime / codegen dir
    (r"torch_spyre/execution/async_compile\.py",
     "backend_handoff", "yes", "medium", "R-backend-handoff"),
    (r"torch_spyre/execution/",
     "runtime_exec", "no", "medium", "R-runtime-exec"),
    (r"torch_spyre/_inductor/codegen/",
     "codegen_subdir", "yes", "medium", "R-codegen-subdir"),
    (r"torch_spyre/runtime/", "runtime", "no", "medium", "R-runtime"),
    # ------------------------------------------------------------------ everything else under torch_spyre/
    (r"torch_spyre/", "other_torch_spyre", "uncertain", "low", "R-other-torch-spyre"),
]


def classify_path(path: str) -> dict:
    for pattern, stage, hot_path, conf, rule_id in RULES:
        if re.search(pattern, path):
            return {
                "path": path,
                "stage": stage,
                "hot_path_probability": hot_path,
                "confidence": conf,
                "rule": rule_id,
            }
    return {
        "path": path,
        "stage": "unknown",
        "hot_path_probability": "uncertain",
        "confidence": "low",
        "rule": "R-unclassified",
    }


LEVEL_MAP = {
    # stage → (default level, rationale)
    "dedup":                        (1, "known measured hotspot; ops×dups scaling"),
    "coarse_tile":                  (3, "known dominant WSR/KV pass; scaling law is the interesting axis"),
    "coarse_tile_hints":            (1, "coarse-tile-hints helpers; measure once"),
    "restickify":                   (1, "beam-search; state-space sensitive"),
    "layout_prop":                  (1, "may alter candidate set feeding restickify"),
    "hint_prop":                    (1, ""),
    "named_dim_prop":               (1, ""),
    "insert_restickify":            (1, ""),
    "scratchpad":                   (1, "root cause of workload-A slope unresolved; measure the actual path"),
    "fusion":                       (1, ""),
    "scheduler":                    (1, ""),
    "work_division":                (1, ""),
    "kernel_codegen":               (0, "<1% of compile_fx at every measured point"),
    "ir_lowering":                  (1, ""),
    "decompositions":               (1, "may move work into downstream passes"),
    "compile_fx_wrapper_setup":     (1, "affects compile_fx wrapper wiring"),
    "enforce_indirect_access":      (1, ""),
    "split_multi_ops":              (1, ""),
    "dce":                          (1, ""),
    "hbm_planning":                 (1, ""),
    "pass_utils":                   (1, "shared helpers; may affect multiple passes"),
    "csrc":                         (1, "C-extension; requires rebuild per revision"),
    "backend_handoff":              (1, "may be BACKEND_IMPACT_ONLY; still measure once"),
    "runtime_exec":                 (0, "runtime code, no compile path"),
    "codegen_subdir":               (1, ""),
    "runtime":                      (0, "runtime; not compile-time"),
    "other_torch_spyre":            (1, "unclassified torch_spyre change; measure once conservatively"),
    "test_only":                    (0, "tests only"),
    "docs":                         (0, "docs only"),
    "ci_only":                      (0, "CI only"),
    "meta":                         (0, "metadata only"),
    "build":                        (0, "build config"),
    "unknown":                      (1, "unclassified path; conservative default"),
}


def choose_level(entries: list[dict]) -> tuple[int, str]:
    """Pick the highest applicable level across all entries."""
    highest = 0
    reasons = []
    for e in entries:
        stage = e["stage"]
        level, rationale = LEVEL_MAP.get(stage, (1, "conservative default"))
        # Hot path modifier: if the stage rule says "no", cap at 0.
        if e["hot_path_probability"] == "no":
            level = 0
        if level > highest:
            highest = level
            reasons = [f"{e['path']} → {stage} → Level {level} ({rationale})"]
        elif level == highest:
            reasons.append(f"{e['path']} → {stage} → Level {level} ({rationale})")
    return highest, "; ".join(reasons) if reasons else "no changed files"


def main() -> None:
    if len(sys.argv) == 2:
        payload = json.load(open(sys.argv[1]))
    else:
        payload = json.load(sys.stdin)
    files = payload.get("changed_files", [])
    entries = [classify_path(p) for p in files]
    level, rationale = choose_level(entries)
    out = {
        "target": {k: v for k, v in payload.items() if k != "changed_files"},
        "changed_files": files,
        "static_impact": entries,
        "level_decision": {
            "level": level,
            "rationale": rationale,
        },
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
