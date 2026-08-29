"""Bundle-fidelity check for the pre-DXP stop harness.

Runs the same workload twice against a fresh Inductor cache:

  1. ``allow_full_dxp=True`` — normal compile, DXP subprocess runs
  2. ``allow_full_dxp=False`` — pre-DXP stop (subprocess.run replaced
     with a sentinel raise)

Compares the ``inductor-spyre/<digest>_<kernel>_*/`` directories that
``generate_bundle`` produced under ``$TORCHINDUCTOR_CACHE_DIR`` (see
``get_output_dir`` in ``torch_spyre/execution/async_compile.py``).

The pre-DXP tree should contain the same set of pre-subprocess files
with byte-for-byte identical contents (the SDSC bundle
``generate_bundle`` writes). Files that ``dxp_standalone`` produces —
typically ``spyreCodeDir/`` — appear only in the normal run. Reports
the diff so a human can eyeball what DXP added and confirm no other
divergence.

Runs one baseline point (Lq=512, Lk=1024) unless overridden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _hash_file(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while buf := fh.read(chunk):
            h.update(buf)
    return h.hexdigest()


def _catalog(root: Path) -> dict[str, dict]:
    """Return {relpath: {"size": int, "sha256": hex}} for every regular
    file under ``root``.
    """
    out: dict[str, dict] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        try:
            size = p.stat().st_size
            digest = _hash_file(p)
        except OSError as e:
            out[rel] = {"error": repr(e)}
            continue
        out[rel] = {"size": size, "sha256": digest}
    return out


def _find_spyre_kernel_dirs(cache_root: Path) -> list[Path]:
    """The bundle lands at
    ``$TORCHINDUCTOR_CACHE_DIR/inductor-spyre/<digest>_<kernel>_<xxxx>/``.
    Return every such dir found, sorted.
    """
    root = cache_root / "inductor-spyre"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _run_harness(cache_dir: Path, out_json: Path, *, allow_full_dxp: bool,
                 Lq: int, Lk: int) -> int:
    env = os.environ.copy()
    env["TORCHINDUCTOR_CACHE_DIR"] = str(cache_dir)
    env["TORCH_SPYRE_TIMING"] = "1"
    env["SPYRE_TIMING_OUT"] = str(out_json)
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("pre_dxp_stop.py")),
        "--workload", "flash",
        "--Lq", str(Lq),
        "--Lk", str(Lk),
        "--out", str(out_json),
    ]
    if allow_full_dxp:
        cmd.append("--allow-full-dxp")
    print(f"    $ TORCHINDUCTOR_CACHE_DIR={cache_dir} {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, env=env)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--Lq", type=int, default=512)
    ap.add_argument("--Lk", type=int, default=1024)
    ap.add_argument(
        "--out-dir", type=str, required=True,
        help="Directory to place per-run cache dirs and the fidelity report."
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    full_cache = out_dir / "cache_full_dxp"
    stop_cache = out_dir / "cache_pre_dxp"
    if full_cache.exists():
        shutil.rmtree(full_cache)
    if stop_cache.exists():
        shutil.rmtree(stop_cache)
    full_cache.mkdir()
    stop_cache.mkdir()

    print(f"[1/2] normal compile, allow_full_dxp=True, Lq={args.Lq} Lk={args.Lk}")
    rc = _run_harness(
        full_cache, out_dir / "timing_full_dxp.json",
        allow_full_dxp=True, Lq=args.Lq, Lk=args.Lk,
    )
    if rc != 0:
        print(f"FATAL: normal compile exited {rc}", file=sys.stderr)
        return rc

    print(f"[2/2] pre-DXP stop, allow_full_dxp=False, Lq={args.Lq} Lk={args.Lk}")
    rc = _run_harness(
        stop_cache, out_dir / "timing_pre_dxp.json",
        allow_full_dxp=False, Lq=args.Lq, Lk=args.Lk,
    )
    if rc != 0:
        print(f"FATAL: pre-DXP stop exited {rc}", file=sys.stderr)
        return rc

    full_kernels = _find_spyre_kernel_dirs(full_cache)
    stop_kernels = _find_spyre_kernel_dirs(stop_cache)
    if not full_kernels or not stop_kernels:
        print(
            f"FATAL: expected inductor-spyre/<kernel>/ under both caches; "
            f"got full={full_kernels}, stop={stop_kernels}",
            file=sys.stderr,
        )
        return 3

    # For a single-kernel workload we expect exactly one dir on each side.
    # If a compile emits multiple kernels the check pairs them by index
    # after sort — good enough for a fidelity smoke check; the full sweep
    # keeps only the first pairing.
    report = {
        "Lq": args.Lq,
        "Lk": args.Lk,
        "full_kernel_dirs": [str(p) for p in full_kernels],
        "stop_kernel_dirs": [str(p) for p in stop_kernels],
        "pairs": [],
    }
    for i, (fd, sd) in enumerate(zip(full_kernels, stop_kernels)):
        full_cat = _catalog(fd)
        stop_cat = _catalog(sd)

        only_full = sorted(set(full_cat) - set(stop_cat))
        only_stop = sorted(set(stop_cat) - set(full_cat))
        both = sorted(set(full_cat) & set(stop_cat))
        mismatched = []
        for rel in both:
            a, b = full_cat[rel], stop_cat[rel]
            if a.get("sha256") != b.get("sha256") or a.get("size") != b.get("size"):
                mismatched.append({"path": rel, "full": a, "stop": b})

        report["pairs"].append({
            "index": i,
            "full_dir": str(fd),
            "stop_dir": str(sd),
            "n_common": len(both),
            "n_only_full": len(only_full),
            "n_only_stop": len(only_stop),
            "only_full": only_full,
            "only_stop": only_stop,
            "mismatched_common": mismatched,
        })

    report_path = out_dir / "fidelity_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nwrote {report_path}")

    # Summary.
    for pair in report["pairs"]:
        print(
            f"  pair {pair['index']}: "
            f"common={pair['n_common']} "
            f"only_full={pair['n_only_full']} "
            f"only_stop={pair['n_only_stop']} "
            f"mismatched_common={len(pair['mismatched_common'])}"
        )
        for rel in pair["only_stop"]:
            print(f"    only in pre-DXP stop: {rel}  (should be empty)")
        for m in pair["mismatched_common"]:
            print(f"    diverged content: {m['path']}")

    # Fidelity is "pass" when: no files exist only in the stop run, and
    # every common file is byte-identical. Files only in the full run are
    # DXP output and are expected.
    bad = any(
        pair["only_stop"] or pair["mismatched_common"]
        for pair in report["pairs"]
    )
    if bad:
        print("\nFIDELITY: FAIL (see report)")
        return 4
    print("\nFIDELITY: OK — bundle contents identical up to DXP output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
