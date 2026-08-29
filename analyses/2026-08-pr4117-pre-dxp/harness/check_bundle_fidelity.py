"""Rescoped harness-fidelity check for the pre-DXP stop harness.

We separate two concepts explicitly:

  A. **Harness-path fidelity** — the stop harness must not perturb
     the pre-DXP compiler path. Verified by comparing identity
     signals captured at the sdsc() boundary across runs.

  B. **Bundle reproducibility** — torch-spyre's ``generate_bundle``
     is not byte-deterministic across independent cold compiles on
     the frozen tree. Documented as an incidental finding.

Runs the same workload three times at one baseline shape:

  - observe A (real DXP)
  - observe B (real DXP)
  - stop (sentinel)

Compares three pairs (A vs B, A vs stop, B vs stop) on:

  - kernel identity (kernel_name)
  - n_specs
  - spec_type_run_length_signature (ordered type run-lengths)
  - provenance_key from KernelProvenanceDescriptor
  - debug_handle_ids from KernelProvenanceDescriptor
  - aten_ops set
  - bundle file inventory (structural, informational)
  - bundle content SHA-256 (informational)

Harness-fidelity verdict: **stop does not introduce a new class of
divergence not already seen between observe A and observe B**.
Byte-equality is NOT part of the verdict — the A vs B control
already shows byte divergence for identical normal runs.

Exit codes:
  0 — harness fidelity passes (with known bundle nondeterminism)
  2 — argparse / environment
  3 — one of the runs failed to produce a catalog
  4 — stop introduced a divergence class not seen in A vs B
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run_harness(
    cache_dir: Path,
    out_json: Path,
    catalog_json: Path,
    *,
    mode: str,
    workload: str,
    Lq: int | None,
    Lk: int | None,
    N_in: int | None,
    N_hidden: int | None,
    layers: int | None,
) -> int:
    env = os.environ.copy()
    env["TORCHINDUCTOR_CACHE_DIR"] = str(cache_dir)
    env["TORCH_SPYRE_TIMING"] = "1"
    env["SPYRE_TIMING_OUT"] = str(out_json)
    env["SPYRE_PRE_DXP_CATALOG"] = str(catalog_json)
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("pre_dxp_stop.py")),
        "--workload", workload,
        "--mode", mode,
        "--out", str(out_json),
        "--catalog", str(catalog_json),
    ]
    if workload == "flash":
        cmd += ["--Lq", str(Lq), "--Lk", str(Lk)]
    else:
        cmd += ["--N-in", str(N_in), "--N-hidden", str(N_hidden),
                "--layers", str(layers)]
    print(f"    $ TORCHINDUCTOR_CACHE_DIR={cache_dir} --mode {mode}", flush=True)
    return subprocess.run(cmd, env=env).returncode


def _identity_signals(captured_kernel: dict) -> dict:
    """Extract identity-only fields from a captured record (exclude
    the potentially-nondeterministic bundle catalog).
    """
    return {
        k: captured_kernel.get(k)
        for k in (
            "kernel_name",
            "n_specs",
            "spec_type_run_length_signature",
            "spec_type_total_signature",
            "provenance_key",
            "debug_handle_ids",
            "aten_ops",
            "cmd",
        )
        if captured_kernel.get(k) is not None
    }


def _compare_two(name_a: str, cat_a: dict, name_b: str, cat_b: dict) -> dict:
    """Pair by kernel_name and compare identity + bundle contents.

    Returns a structured dict; caller decides whether divergence counts.
    """
    caps_a = cat_a.get("captured", {})
    caps_b = cat_b.get("captured", {})

    def by_kernel(caps):
        # Records were saved keyed by kernel_name already (identity path)
        # OR by output_dir basename (fallback). Prefer kernel_name when
        # present.
        out = {}
        for key, rec in caps.items():
            kn = rec.get("kernel_name") or key
            out[kn] = rec
        return out

    ka = by_kernel(caps_a)
    kb = by_kernel(caps_b)

    common = sorted(set(ka) & set(kb))
    only_a = sorted(set(ka) - set(kb))
    only_b = sorted(set(kb) - set(ka))

    pairs = []
    for k in common:
        id_a = _identity_signals(ka[k])
        id_b = _identity_signals(kb[k])
        # Identity divergences (list keys where the two disagree).
        id_diverges = sorted(
            key for key in set(id_a) | set(id_b)
            if id_a.get(key) != id_b.get(key)
        )
        # Bundle content comparison (informational).
        cat_files_a = ka[k].get("catalog", {})
        cat_files_b = kb[k].get("catalog", {})
        only_files_a = sorted(set(cat_files_a) - set(cat_files_b))
        only_files_b = sorted(set(cat_files_b) - set(cat_files_a))
        content_diverges = []
        for rel in sorted(set(cat_files_a) & set(cat_files_b)):
            fa = cat_files_a[rel]
            fb = cat_files_b[rel]
            if (fa.get("sha256") != fb.get("sha256")
                    or fa.get("size") != fb.get("size")):
                content_diverges.append(rel)
        pairs.append({
            "kernel": k,
            "identity_diverges": id_diverges,
            "n_files_a": len(cat_files_a),
            "n_files_b": len(cat_files_b),
            "only_files_a": only_files_a,
            "only_files_b": only_files_b,
            "n_content_diverges": len(content_diverges),
            "content_diverges_sample": content_diverges[:10],
        })

    return {
        "name_a": name_a,
        "name_b": name_b,
        "only_a_kernels": only_a,
        "only_b_kernels": only_b,
        "pairs": pairs,
    }


def _print_summary(diff: dict) -> None:
    a = diff["name_a"]; b = diff["name_b"]
    print(f"\n{a} vs {b}:")
    print(f"  only {a}: {len(diff['only_a_kernels'])} kernels")
    print(f"  only {b}: {len(diff['only_b_kernels'])} kernels")
    for p in diff["pairs"]:
        marker = "OK" if not p["identity_diverges"] else "!!"
        print(f"  [{marker}] {p['kernel']}: identity_diverges={p['identity_diverges']}")
        print(f"       n_files={p['n_files_a']}/{p['n_files_b']}   "
              f"only_a={len(p['only_files_a'])}   only_b={len(p['only_files_b'])}   "
              f"content_diverges={p['n_content_diverges']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", choices=["flash", "mlp"], default="flash")
    ap.add_argument("--Lq", type=int, default=512)
    ap.add_argument("--Lk", type=int, default=1024)
    ap.add_argument("--N-in", type=int, dest="N_in", default=1024)
    ap.add_argument("--N-hidden", type=int, dest="N_hidden", default=2048)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument(
        "--out-dir", type=str, required=True,
        help="Directory for per-run caches, catalogs, and the report.",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = [
        ("observeA", "observe"),
        ("observeB", "observe"),
        ("stop", "stop"),
    ]
    catalogs: dict[str, dict] = {}
    for label, mode in runs:
        cache = out_dir / f"cache_{label}"
        if cache.exists():
            shutil.rmtree(cache)
        cache.mkdir()
        catalog_path = out_dir / f"catalog_{label}.json"
        print(f"\n[run {label}] mode={mode}")
        rc = _run_harness(
            cache, out_dir / f"timing_{label}.json", catalog_path,
            mode=mode, workload=args.workload,
            Lq=args.Lq, Lk=args.Lk,
            N_in=args.N_in, N_hidden=args.N_hidden, layers=args.layers,
        )
        if rc != 0:
            print(f"FATAL: {label} exited {rc}", file=sys.stderr)
            return 3
        if not catalog_path.exists():
            print(f"FATAL: {label} produced no catalog", file=sys.stderr)
            return 3
        catalogs[label] = json.loads(catalog_path.read_text())

    # Three-way comparisons.
    aa = _compare_two("observeA", catalogs["observeA"],
                      "observeB", catalogs["observeB"])
    as_ = _compare_two("observeA", catalogs["observeA"],
                       "stop", catalogs["stop"])
    bs = _compare_two("observeB", catalogs["observeB"],
                      "stop", catalogs["stop"])

    report = {
        "workload": args.workload,
        "Lq": args.Lq, "Lk": args.Lk,
        "N_in": args.N_in, "N_hidden": args.N_hidden, "layers": args.layers,
        "observeA_vs_observeB": aa,
        "observeA_vs_stop": as_,
        "observeB_vs_stop": bs,
    }

    report_path = out_dir / "fidelity_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nwrote {report_path}")

    for d in (aa, as_, bs):
        _print_summary(d)

    # Harness-fidelity verdict.
    #
    # PASS when:
    #   * every pair (observe A vs stop, observe B vs stop) has no identity
    #     divergences that observe A vs observe B does not also exhibit.
    #   * no kernel appears only on the stop side (or only on one observe
    #     side but not the other).
    def _pair_identity_set(diff):
        s = set()
        for p in diff["pairs"]:
            for id_key in p["identity_diverges"]:
                s.add(id_key)
        return s

    aa_ids = _pair_identity_set(aa)
    as_ids = _pair_identity_set(as_)
    bs_ids = _pair_identity_set(bs)
    new_in_stop = (as_ids | bs_ids) - aa_ids

    kernel_set_a = {p["kernel"] for p in aa["pairs"]} | set(aa["only_a_kernels"])
    kernel_set_b = {p["kernel"] for p in aa["pairs"]} | set(aa["only_b_kernels"])
    kernel_set_stop = {p["kernel"] for p in as_["pairs"]} | set(as_["only_b_kernels"])
    stop_only_kernels = kernel_set_stop - kernel_set_a - kernel_set_b

    stop_new_class = bool(new_in_stop or stop_only_kernels
                          or as_["only_a_kernels"] or as_["only_b_kernels"]
                          or bs["only_a_kernels"] or bs["only_b_kernels"])

    print("\n----")
    print("observe-A/observe-B identity divergences:", sorted(aa_ids))
    print("observe-A/stop identity divergences:", sorted(as_ids))
    print("observe-B/stop identity divergences:", sorted(bs_ids))
    print("new-in-stop identity keys:", sorted(new_in_stop))
    print("kernels only in stop:", sorted(stop_only_kernels))
    if stop_new_class:
        print("\nHARNESS FIDELITY: FAIL — stop introduces divergence not "
              "already present in observe-A vs observe-B")
        return 4
    print("\nHARNESS FIDELITY: PASS WITH KNOWN CROSS-RUN BUNDLE NONDETERMINISM")
    print("  Bundle content divergence is present between two independent "
          "observe runs (unattributed bundle-generation nondeterminism),")
    print("  and stop exhibits the same class of divergence — not new. "
          "Byte-equality is not a fidelity oracle for this build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
