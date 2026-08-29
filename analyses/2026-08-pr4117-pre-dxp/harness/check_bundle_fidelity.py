"""Bundle-fidelity check for the pre-DXP stop harness.

Runs the workload twice at one baseline point:

  1. ``--mode=observe`` — reaches the DXP call site, catalogs the
     bundle immediately *before* subprocess.run, then delegates to
     the real DXP so the compile finishes.
  2. ``--mode=stop`` — reaches the same call site, catalogs the
     bundle immediately *before* the sentinel raise, then aborts.

Both runs emit a pre-DXP catalog JSON (see ``pre_dxp_stop.py``
``_Interception.dump_catalog``). This script diffs those two catalogs
and PROVES the interception did not alter what DXP sees: the input to
DXP is byte-identical whether we stopped or continued.

Comparison rules:

- Kernels are paired by output_dir basename (which includes the
  kernel_name), NOT by sorted directory index — an emitted graph may
  create N kernels in an order that differs across runs.
- File presence, size, SHA-256, and mode must match. Any file that
  appears in only one side of a paired kernel is a divergence.
- Extra kernels on only one side is a divergence.

Exit codes:

  0 — pre-DXP catalogs identical (fidelity holds)
  2 — argparse / environment
  3 — one of the runs failed to produce a catalog
  4 — divergence found
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
    print(f"    $ TORCHINDUCTOR_CACHE_DIR={cache_dir} {' '.join(cmd)}",
          flush=True)
    return subprocess.run(cmd, env=env).returncode


def _diff_catalogs(obs: dict, stop: dict) -> dict:
    """Compare pre-DXP catalogs. Both are the payloads dumped by
    pre_dxp_stop._Interception.dump_catalog: {"mode": ..., "captured": {key: {catalog, ...}, ...}}
    """
    obs_caps = obs.get("captured", {})
    stop_caps = stop.get("captured", {})

    result: dict = {
        "observe_kernels": sorted(obs_caps),
        "stop_kernels": sorted(stop_caps),
        "only_observe": sorted(set(obs_caps) - set(stop_caps)),
        "only_stop": sorted(set(stop_caps) - set(obs_caps)),
        "paired": [],
        "divergences": [],
    }

    common = sorted(set(obs_caps) & set(stop_caps))
    for key in common:
        obs_cat = obs_caps[key]["catalog"]
        stop_cat = stop_caps[key]["catalog"]

        only_obs = sorted(set(obs_cat) - set(stop_cat))
        only_stop = sorted(set(stop_cat) - set(obs_cat))
        mismatched = []
        for rel in sorted(set(obs_cat) & set(stop_cat)):
            a, b = obs_cat[rel], stop_cat[rel]
            if (a.get("sha256") != b.get("sha256")
                    or a.get("size") != b.get("size")
                    or a.get("mode") != b.get("mode")):
                mismatched.append({"path": rel, "observe": a, "stop": b})

        pair = {
            "key": key,
            "n_common": len(set(obs_cat) & set(stop_cat)),
            "only_observe": only_obs,
            "only_stop": only_stop,
            "mismatched": mismatched,
        }
        result["paired"].append(pair)
        if only_obs or only_stop or mismatched:
            result["divergences"].append(key)

    return result


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
        help="Directory to place per-run cache dirs, catalogs, and report.",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    obs_cache = out_dir / "cache_observe"
    stop_cache = out_dir / "cache_stop"
    for p in (obs_cache, stop_cache):
        if p.exists():
            shutil.rmtree(p)
        p.mkdir()

    obs_catalog = out_dir / "catalog_observe.json"
    stop_catalog = out_dir / "catalog_stop.json"

    print("[1/2] observe (real DXP runs; catalog captured pre-DXP)")
    rc = _run_harness(
        obs_cache, out_dir / "timing_observe.json", obs_catalog,
        mode="observe", workload=args.workload,
        Lq=args.Lq, Lk=args.Lk,
        N_in=args.N_in, N_hidden=args.N_hidden, layers=args.layers,
    )
    if rc != 0:
        print(f"FATAL: observe run exited {rc}", file=sys.stderr)
        return 3

    print("[2/2] stop (DXP skipped; catalog captured pre-DXP)")
    rc = _run_harness(
        stop_cache, out_dir / "timing_stop.json", stop_catalog,
        mode="stop", workload=args.workload,
        Lq=args.Lq, Lk=args.Lk,
        N_in=args.N_in, N_hidden=args.N_hidden, layers=args.layers,
    )
    if rc != 0:
        print(f"FATAL: stop run exited {rc}", file=sys.stderr)
        return 3

    if not obs_catalog.exists() or not stop_catalog.exists():
        print("FATAL: one or both catalogs missing", file=sys.stderr)
        return 3

    obs = json.loads(obs_catalog.read_text())
    stop = json.loads(stop_catalog.read_text())
    diff = _diff_catalogs(obs, stop)

    report_path = out_dir / "fidelity_report.json"
    report_path.write_text(json.dumps(diff, indent=2, sort_keys=True))
    print(f"\nwrote {report_path}")

    print(
        f"  observe kernels: {len(diff['observe_kernels'])}   "
        f"stop kernels: {len(diff['stop_kernels'])}   "
        f"paired: {len(diff['paired'])}   "
        f"divergent: {len(diff['divergences'])}"
    )
    for pair in diff["paired"]:
        marker = "OK" if not (pair["only_observe"] or pair["only_stop"] or pair["mismatched"]) else "!!"
        print(f"  [{marker}] {pair['key']}: n_common={pair['n_common']} "
              f"only_observe={len(pair['only_observe'])} "
              f"only_stop={len(pair['only_stop'])} "
              f"mismatched={len(pair['mismatched'])}")
        for rel in pair["only_stop"]:
            print(f"     only in stop:    {rel}  (should not exist)")
        for rel in pair["only_observe"]:
            print(f"     only in observe: {rel}  (should not exist — pre-DXP)")
        for m in pair["mismatched"]:
            print(f"     diverged: {m['path']}  "
                  f"obs={m['observe'].get('sha256', '?')[:12]} "
                  f"stop={m['stop'].get('sha256', '?')[:12]}")

    bad = bool(diff["divergences"] or diff["only_observe"] or diff["only_stop"])
    if bad:
        print("\nFIDELITY: FAIL — pre-DXP inputs differ between observe and stop")
        return 4
    print("\nFIDELITY: OK — pre-DXP inputs are byte-identical between observe and stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
