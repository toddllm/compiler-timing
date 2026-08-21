#!/usr/bin/env python3
"""Pod-side environment capture for the torch-spyre forward-compat study.

Runs INSIDE the fresh pod (tdeshane-forward-compat-2026-08-21 in
namespace a5-deepview, or whatever fresh pod the case is running on).
Emits a single JSON document on stdout — the caller is expected to
redirect it into ``environment.json`` in the case's artifact directory.

Design rules:

- Stdlib only. The pod's base image may or may not have any extras;
  this script must run on a bare interpreter.
- Every probe is wrapped so a failure records ``{"error": "..."}``
  in place of the value rather than aborting the whole capture. A
  partial run that only tells us the Python version is more useful
  than no run at all.
- Nothing is written until the entire dict is assembled — the final
  ``json.dumps`` is the only output. A crash mid-capture leaves stdout
  empty, which the caller can detect, rather than a half-written file
  that later readers assume is complete.
- ``schema_version`` is bumped whenever a field is renamed or removed;
  additive fields do not require a bump.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from typing import Any, Optional

SCHEMA_VERSION = 1

# Env-var prefixes and exact names that are load-bearing for the compile
# path or the runtime backend. Kept small on purpose — a wide capture
# leaks tokens (HF_TOKEN, IBM_*) into artifacts.
ENV_PREFIXES = (
    "TORCH_",
    "LX_",
    "FLEX_",
    "AIU_",
    "TORCHINDUCTOR_",
)
ENV_EXACT = (
    "SENCORES",
    "TORCH_LOGS",
)


def _safe(fn):
    """Run ``fn()`` and return its value, or a stringified error dict."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — capture is best-effort
        return {"error": f"{type(e).__name__}: {e}"}


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return None


def _run(cmd: list[str]) -> Optional[str]:
    """Run a subprocess, return its first line of stdout, or None."""
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        out = (p.stdout or "").strip()
        if not out:
            return None
        return out.splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------------------
# Probes

def probe_pod() -> dict[str, Any]:
    name = os.environ.get("HOSTNAME") or "unknown"
    ns = _read_file("/var/run/secrets/kubernetes.io/serviceaccount/namespace") or "unknown"
    # NODE_NAME is only set if the downward API is wired into the pod spec;
    # the fresh-pod manifest for this study is expected to include it.
    node = os.environ.get("NODE_NAME") or "unknown"
    return {"name": name, "namespace": ns, "node": node}


def probe_image() -> dict[str, Any]:
    # The container has no direct way to know its own image name/digest
    # from inside — the kubelet holds that information. The fresh-pod
    # bootstrap (create_fresh_pod.sh) is expected to write the digest
    # to /tmp/image_digest and, optionally, the human-readable image
    # reference to /tmp/image_name so this probe can pick them up.
    digest = _read_file("/tmp/image_digest") or "unknown"
    name = _read_file("/tmp/image_name") or os.environ.get("IMAGE_NAME") or "unknown"
    return {"name": name, "digest": digest}


def probe_python() -> dict[str, Any]:
    return {
        "version": sys.version.split()[0],
        "executable": sys.executable,
    }


def probe_torch() -> dict[str, Any]:
    try:
        import torch  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    d: dict[str, Any] = {
        "version": _safe(lambda: torch.__version__),
        "git_version": _safe(lambda: getattr(torch.version, "git_version", None)),
        "__file__": _safe(lambda: torch.__file__),
        "cuda_available": _safe(lambda: bool(torch.cuda.is_available())),
        "spyre_available": _safe(lambda: getattr(torch, "spyre", None) is not None),
    }
    return d


def probe_torch_spyre() -> dict[str, Any]:
    try:
        import torch_spyre  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    version: Any = None
    try:
        from importlib.metadata import PackageNotFoundError, version as _v
        try:
            version = _v("torch_spyre")
        except PackageNotFoundError:
            try:
                version = _v("torch-spyre")
            except PackageNotFoundError:
                version = None
    except Exception as e:  # noqa: BLE001
        version = {"error": f"{type(e).__name__}: {e}"}

    file_attr = _safe(lambda: torch_spyre.__file__)

    # If installed editable, the working tree's .git may be reachable
    # from the package file. Walk up until we find a .git directory.
    sha: Any = None
    try:
        if isinstance(file_attr, str):
            here = os.path.dirname(os.path.abspath(file_attr))
            for _ in range(8):
                git_dir = os.path.join(here, ".git")
                if os.path.isdir(git_dir) or os.path.isfile(git_dir):
                    sha = _run(["git", "-C", here, "rev-parse", "HEAD"])
                    break
                parent = os.path.dirname(here)
                if parent == here:
                    break
                here = parent
    except Exception as e:  # noqa: BLE001
        sha = {"error": f"{type(e).__name__}: {e}"}

    return {
        "version": version,
        "__file__": file_attr,
        "sha": sha,
    }


def probe_deeptools() -> Any:
    try:
        import deeptools  # type: ignore
    except Exception:
        return None
    try:
        from importlib.metadata import PackageNotFoundError, version as _v
        try:
            return {"version": _v("deeptools")}
        except PackageNotFoundError:
            return {"version": getattr(deeptools, "__version__", None)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def probe_toolchain() -> dict[str, Any]:
    return {
        "gcc": _run(["gcc", "--version"]),
        "clang": _run(["clang", "--version"]),
        "cmake": _run(["cmake", "--version"]),
        "ninja": _run(["ninja", "--version"]),
        "ccache": _run(["ccache", "--version"]),
    }


def probe_device() -> dict[str, Any]:
    try:
        import torch  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    spyre = getattr(torch, "spyre", None)
    if spyre is None:
        return {"device_count": 0, "is_available": False}
    return {
        "device_count": _safe(lambda: int(spyre.device_count())) if hasattr(spyre, "device_count") else 0,
        "is_available": _safe(lambda: bool(spyre.is_available())) if hasattr(spyre, "is_available") else False,
    }


def probe_env_vars() -> dict[str, str]:
    picked: dict[str, str] = {}
    for k, v in os.environ.items():
        if k in ENV_EXACT or k.startswith(ENV_PREFIXES):
            picked[k] = v
    # Sort for stable diffs across captures.
    return dict(sorted(picked.items()))


# ---------------------------------------------------------------------------
# Main — assemble the full dict, then emit exactly once.

def main() -> None:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "pod": _safe(probe_pod),
        "image": _safe(probe_image),
        "python": _safe(probe_python),
        "torch": _safe(probe_torch),
        "torch_spyre": _safe(probe_torch_spyre),
        "deeptools": _safe(probe_deeptools),
        "toolchain": _safe(probe_toolchain),
        "device": _safe(probe_device),
        "env_vars": _safe(probe_env_vars),
    }
    # Single write. If any probe blew past _safe and raised, we'd rather
    # print nothing than a truncated document — so keep dumps at the end.
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=False))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
