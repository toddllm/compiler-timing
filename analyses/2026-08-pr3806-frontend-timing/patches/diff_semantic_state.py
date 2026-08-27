#!/usr/bin/env python3
"""Compare two normalized post-dedup state snapshots produced by
semantic_equiv_harness.py.

Usage: diff_semantic_state.py STATE_A STATE_B

Prints a summary of any semantic differences. Exits 0 on equivalence,
1 on divergence.
"""

from __future__ import annotations

import json
import sys


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def compare(a: dict, b: dict, label_a: str, label_b: str) -> int:
    diffs: list[str] = []

    for k in [
        "n_operations", "n_surviving_constants",
        "removed_buffers_count",
    ]:
        if a.get(k) != b.get(k):
            diffs.append(f"{k}: {label_a}={a.get(k)} vs {label_b}={b.get(k)}")

    if sorted(a.get("removed_buffers", [])) != sorted(b.get("removed_buffers", [])):
        aa = set(a.get("removed_buffers", []))
        bb = set(b.get("removed_buffers", []))
        only_a = sorted(aa - bb)
        only_b = sorted(bb - aa)
        diffs.append(
            f"removed_buffers differ: only-{label_a}={only_a[:6]} "
            f"(total {len(only_a)}), only-{label_b}={only_b[:6]} "
            f"(total {len(only_b)})"
        )

    # Operations: compare types + canonical positions
    ops_a = [(o["type"], o["canonical"]) for o in a.get("operations", [])]
    ops_b = [(o["type"], o["canonical"]) for o in b.get("operations", [])]
    if ops_a != ops_b:
        # find first diverging index
        first = next(
            (i for i, (x, y) in enumerate(zip(ops_a, ops_b)) if x != y),
            min(len(ops_a), len(ops_b)),
        )
        diffs.append(
            f"operations diverge starting at index {first}: "
            f"{label_a}={ops_a[first:first+3]} vs {label_b}={ops_b[first:first+3]}"
        )

    # Surviving constants keys
    keys_a = [tuple(c["key"]) for c in a.get("constants", [])]
    keys_b = [tuple(c["key"]) for c in b.get("constants", [])]
    if keys_a != keys_b:
        diffs.append(
            f"surviving-constant keys differ: {label_a}={keys_a[:5]} "
            f"vs {label_b}={keys_b[:5]}"
        )

    # Provenance: total ProvenanceTransform count summed across canonicals
    total_prov_a = sum(c.get("provenance_history_len", 0) for c in a.get("constants", []))
    total_prov_b = sum(c.get("provenance_history_len", 0) for c in b.get("constants", []))
    if total_prov_a != total_prov_b:
        diffs.append(
            f"total provenance-history len: {label_a}={total_prov_a} "
            f"vs {label_b}={total_prov_b}"
        )
    pass_names_a = sorted(
        n for c in a.get("constants", [])
        for n in (c.get("provenance_pass_names") or []) if n
    )
    pass_names_b = sorted(
        n for c in b.get("constants", [])
        for n in (c.get("provenance_pass_names") or []) if n
    )
    if pass_names_a != pass_names_b:
        diffs.append(
            f"provenance pass_names differ: {label_a}={pass_names_a[:6]} "
            f"vs {label_b}={pass_names_b[:6]}"
        )

    # name_to_users keys
    kua = sorted(a.get("name_to_users", {}).keys())
    kub = sorted(b.get("name_to_users", {}).keys())
    if kua != kub:
        diffs.append(
            f"name_to_users key sets differ: only-{label_a}={sorted(set(kua)-set(kub))[:6]} "
            f"only-{label_b}={sorted(set(kub)-set(kua))[:6]}"
        )
    else:
        for key in kua:
            ea = a["name_to_users"][key]
            eb = b["name_to_users"][key]
            # Compare types + inner_name_canonical order (identity-preserving fold)
            sig_a = [(e.get("type"), e.get("inner_name_canonical")) for e in ea]
            sig_b = [(e.get("type"), e.get("inner_name_canonical")) for e in eb]
            if sig_a != sig_b:
                diffs.append(
                    f"name_to_users[{key}] entries differ: "
                    f"{label_a}={sig_a[:4]} vs {label_b}={sig_b[:4]}"
                )
                break  # one is enough

    # live_reads: for each canonicalized position, compare read sets
    live_a = a.get("live_reads", {})
    live_b = b.get("live_reads", {})
    if set(live_a.keys()) != set(live_b.keys()):
        diffs.append(
            f"live_reads key sets differ: only-{label_a}={sorted(set(live_a)-set(live_b))[:6]} "
            f"only-{label_b}={sorted(set(live_b)-set(live_a))[:6]}"
        )
    else:
        for key in sorted(live_a):
            ra = live_a[key].get("reads", [])
            rb = live_b[key].get("reads", [])
            if ra != rb:
                diffs.append(
                    f"live_reads[{key}] differ: {label_a}={ra} vs {label_b}={rb}"
                )
                # keep going; report multiple mismatches
    if diffs:
        print(f"DIFFERENCES ({len(diffs)}):")
        for d in diffs:
            print(f"  - {d}")
        return 1
    print("EQUIVALENT — no semantic differences detected.")
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: diff_semantic_state.py STATE_A STATE_B", file=sys.stderr)
        return 2
    a = load(sys.argv[1])
    b = load(sys.argv[2])
    return compare(a, b, sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
