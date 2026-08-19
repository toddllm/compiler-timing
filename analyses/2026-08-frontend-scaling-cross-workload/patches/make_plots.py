#!/usr/bin/env python3
"""Generate the two headline plots for the cross-workload SUMMARY."""
from __future__ import annotations

import glob
import json
import os
import statistics
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(STUDY))
DATA_A = f"{ROOT}/analyses/2026-08-pr3806-frontend-timing/data"
DATA_B_POST = f"{STUDY}/data/workload-B-post-fix"
OUT = f"{STUDY}/plots"

os.makedirs(OUT, exist_ok=True)


def med(vs): return statistics.median(vs) if vs else float("nan")


def ev(d, name):
    hits = [e for e in d["events"] if e["name"] == name]
    return sum(e["inclusive_ns"] for e in hits) / 1e6 if hits else 0.0


TOP_PASSES = [
    ("_maybe_coarse_tile_hints", "coarse_tile_hints", "#c0392b"),
    ("dedup_and_promote_constants", "dedup", "#e67e22"),
    ("optimize_restickify_locations", "optimize_restickify", "#f1c40f"),
    ("_maybe_scratchpad_planning", "scratchpad_planning", "#27ae60"),
    ("propagate_spyre_tensor_layouts", "propagate_layouts", "#2980b9"),
]
OTHER_PASSES = [
    "_distribute_work",
    "_maybe_reorder_unhinted_interlopers",
    "enforce_indirect_access_layout",
    "span_reduction",
    "deadcode_elimination",
    "validate_ops",
    "split_multi_ops",
    "_maybe_coarse_tile_span_overflow",
]


def load_workload_B_post_fix():
    by = defaultdict(list)
    for p in sorted(glob.glob(f"{DATA_B_POST}/*.json")):
        d = json.load(open(p))
        n = d["meta"]["n_chunks"]
        by[n].append(d)
    return by


def plot_1_workload_B_composition():
    by = load_workload_B_post_fix()
    ns = sorted(by.keys())

    stacks = []
    for n in ns:
        runs = by[n]
        row = {}
        for pass_name, label, _color in TOP_PASSES:
            row[label] = med([ev(r, f"pass:CustomPreSchedulingPasses:{pass_name}") for r in runs]) / 1000
        other_ms = med([sum(ev(r, f"pass:CustomPreSchedulingPasses:{p}") for p in OTHER_PASSES) for r in runs])
        row["other"] = other_ms / 1000
        stacks.append(row)

    labels = [label for _, label, _ in TOP_PASSES] + ["other"]
    colors = [color for _, _, color in TOP_PASSES] + ["#7f8c8d"]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = list(range(len(ns)))
    bottoms = [0.0] * len(ns)
    for label, color in zip(labels, colors):
        heights = [row[label] for row in stacks]
        ax.bar(x, heights, bottom=bottoms, label=label, color=color, edgecolor="white", linewidth=0.5)
        bottoms = [b + h for b, h in zip(bottoms, heights)]

    for i, total in enumerate(bottoms):
        ax.text(i, total + 1, f"{total:.1f} s", ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([f"n_chunks={n}" for n in ns])
    ax.set_ylabel("Spyre custom pass time (seconds)")
    ax.set_title("Workload B — Spyre-owned frontend composition (post-fix)")
    ax.set_ylim(0, max(bottoms) * 1.15)
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()
    p = f"{OUT}/workload-B-frontend-composition.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    print(f"wrote {p}")


def plot_2_mechanism_matrix():
    """Cross-workload mechanism/scaling comparison."""
    # Rows = passes / mechanisms. Cols = (workload A, workload B).
    # Cell content: qualitative scaling label + a numeric "measured slope" if available.
    rows = [
        ("dedup_and_promote_constants",  "ops × dups (quadratic-like)", "ops × dups (quadratic-like)"),
        ("_maybe_coarse_tile_hints",     "inactive (~0)",                "~4× per 2× chunks (quadratic-like)"),
        ("optimize_restickify_locations", "sublinear",                    "2.2–2.4× per 2× chunks (post-fix)"),
        ("_maybe_scratchpad_planning",   "n^1.45 (superlinear)",         "linear"),
        ("propagate_spyre_tensor_layouts", "sublinear",                   "linear"),
        ("dxp_standalone (backend)",     "dominant, superlinear",         "dominant, superlinear"),
    ]

    # Numeric intensity for coloring: 0=absent, 1=linear-or-below, 2=mildly superlinear, 3=quadratic-like, 4=dominant
    intensity = {
        ("dedup_and_promote_constants",  "A"): 3, ("dedup_and_promote_constants",  "B"): 3,
        ("_maybe_coarse_tile_hints",     "A"): 0, ("_maybe_coarse_tile_hints",     "B"): 3,
        ("optimize_restickify_locations", "A"): 1, ("optimize_restickify_locations", "B"): 2,
        ("_maybe_scratchpad_planning",   "A"): 3, ("_maybe_scratchpad_planning",   "B"): 1,
        ("propagate_spyre_tensor_layouts", "A"): 1, ("propagate_spyre_tensor_layouts", "B"): 1,
        ("dxp_standalone (backend)",     "A"): 4, ("dxp_standalone (backend)",     "B"): 4,
    }

    cmap = {
        0: "#ecf0f1",  # inactive
        1: "#d5f5e3",  # linear-or-below
        2: "#fdebd0",  # mildly superlinear
        3: "#f5b7b1",  # quadratic-like
        4: "#78281f",  # backend dominant (dark)
    }
    text_color = {
        0: "#7f8c8d", 1: "#1e6f4c", 2: "#8a5a1a", 3: "#7c1f19", 4: "#fefefe",
    }

    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.set_xlim(0, 3)
    ax.set_ylim(0, len(rows) + 1)
    ax.invert_yaxis()

    # Header
    ax.text(0.5, 0.35, "Pass / mechanism", ha="center", va="center",
            fontsize=11, fontweight="bold")
    ax.text(1.5, 0.35, "Workload A\n(OpSpec/static tiled FA)",
            ha="center", va="center", fontsize=10, fontweight="bold")
    ax.text(2.5, 0.35, "Workload B\n(WSR/KV-chunked FA, controlled base)",
            ha="center", va="center", fontsize=10, fontweight="bold")

    for i, (name, a_desc, b_desc) in enumerate(rows):
        y = i + 1
        # Label cell
        ax.add_patch(Rectangle((0, y), 1, 1, facecolor="#ffffff",
                               edgecolor="#bdc3c7", linewidth=0.7))
        ax.text(0.05, y + 0.5, name, ha="left", va="center", fontsize=10, fontfamily="monospace")

        # Workload A cell
        ia = intensity[(name, "A")]
        ax.add_patch(Rectangle((1, y), 1, 1, facecolor=cmap[ia],
                               edgecolor="#bdc3c7", linewidth=0.7))
        ax.text(1.5, y + 0.5, a_desc, ha="center", va="center",
                fontsize=9.5, color=text_color[ia])

        # Workload B cell
        ib = intensity[(name, "B")]
        ax.add_patch(Rectangle((2, y), 1, 1, facecolor=cmap[ib],
                               edgecolor="#bdc3c7", linewidth=0.7))
        ax.text(2.5, y + 0.5, b_desc, ha="center", va="center",
                fontsize=9.5, color=text_color[ib])

    # Legend
    legend_items = [
        ("inactive / negligible", cmap[0], text_color[0]),
        ("linear or sublinear",   cmap[1], text_color[1]),
        ("mildly superlinear",    cmap[2], text_color[2]),
        ("quadratic-like",        cmap[3], text_color[3]),
        ("backend, dominant",     cmap[4], text_color[4]),
    ]
    for i, (label, fc, tc) in enumerate(legend_items):
        y0 = len(rows) + 1.15
        x0 = 0.05 + i * 0.6
        ax.add_patch(Rectangle((x0, y0), 0.06, 0.32, facecolor=fc,
                               edgecolor="#bdc3c7", linewidth=0.5))
        ax.text(x0 + 0.08, y0 + 0.16, label, ha="left", va="center",
                fontsize=8.5, color="#2c3e50")

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title("Cross-workload frontend scaling mechanisms",
                 fontsize=13, fontweight="bold", pad=12)

    fig.tight_layout()
    p = f"{OUT}/cross-workload-mechanism-matrix.png"
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {p}")


if __name__ == "__main__":
    plot_1_workload_B_composition()
    plot_2_mechanism_matrix()
