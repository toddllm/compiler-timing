"""Frontend-only measurement harness for epic #4117.

Runs the normal cold-compile path through backend-input generation.

Interception modes (via ``--mode``):

  stop
      Reach the ``subprocess.run(["dxp_standalone", ...])`` call site,
      hash and catalog the bundle *before* subprocess.run, emit a
      ``pre_dxp_boundary_marker`` timing stage, and raise the
      ``_PreDxpBoundary`` sentinel. `generate_bundle` and
      `build_kernel_provenance_descriptor` have already completed.
      DXP itself does not run. Sentinel unwinds through the compile
      stack; the outer harness catches it and dumps timing JSON.
      Analysis-only.

  observe
      Reach the same call site, hash and catalog the bundle *before*
      subprocess.run, emit ``pre_dxp_boundary_marker``, THEN delegate
      to the original ``subprocess.run`` so DXP runs to completion.
      The compiled artifact fully materializes. Used only for
      fidelity checks: this run and a paired ``stop`` run produce
      identical pre-DXP catalogs when the interception did not alter
      what DXP sees.

  passthrough
      No interception. Baseline compare — used for sanity/timing
      comparison against production behavior.

The catalog dumped by ``stop`` and ``observe`` at the boundary is
written to ``$SPYRE_PRE_DXP_CATALOG`` (JSON), keyed by output_dir. It
records every file the bundle contains, with SHA-256, size, and mode,
so paired runs can be compared for byte-for-byte identity of the
INPUT to DXP — not what DXP wrote afterwards.

Environment
-----------

``TORCH_SPYRE_TIMING=1``            required
``SPYRE_TIMING_OUT``                 path for timing JSON dump
``SPYRE_PRE_DXP_CATALOG``            path for pre-DXP catalog JSON (optional)
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import stat
import sys
from typing import Any


# ---- catalog helpers -------------------------------------------------------

def _hash_file(path: str, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while buf := fh.read(chunk):
            h.update(buf)
    return h.hexdigest()


def _catalog_dir(root: str) -> dict[str, dict]:
    """Return {relpath: {"size", "sha256", "mode"}} for every regular
    file under ``root``. Symlinks are NOT followed.
    """
    out: dict[str, dict] = {}
    if not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            abs_ = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_, root)
            try:
                st = os.lstat(abs_)
                if not stat.S_ISREG(st.st_mode):
                    out[rel] = {"kind": "non-regular", "mode": st.st_mode}
                    continue
                out[rel] = {
                    "size": st.st_size,
                    "sha256": _hash_file(abs_),
                    "mode": stat.S_IMODE(st.st_mode),
                }
            except OSError as e:
                out[rel] = {"error": repr(e)}
    return out


# ---- interception ----------------------------------------------------------

class _PreDxpBoundary(Exception):
    """Sentinel raised at the DXP call site in ``stop`` mode.

    Carries the captured (args, kwargs) so the outer harness can prove
    interception fired at the intended point.
    """

    def __init__(self, dxp_args: tuple[Any, ...], dxp_kwargs: dict[str, Any]) -> None:
        super().__init__("pre-DXP stop boundary reached")
        self.dxp_args = dxp_args
        self.dxp_kwargs = dxp_kwargs


class _Interception:
    """Records identity signals for each SDSC call, then either raises
    the sentinel (``stop``) or delegates to the real subprocess
    (``observe``). ``passthrough`` installs nothing.

    Both modes take EXACTLY the same code path up to the final
    delegate-vs-raise decision. The recorded identity signals per
    kernel are:

      * kernel_name — from the ``sdsc()`` positional argument
      * n_specs — from the specs argument
      * spec_type_signature — ordered ``(type_name, count)`` tuples,
        so two runs producing the same tree structure agree even
        when python object identities differ
      * provenance_key — ``KernelProvenanceDescriptor.key`` computed
        from the finalized specs. Deterministic and canonical (per
        ``torch_spyre._inductor.kernel_provenance``).
      * debug_handle_ids — same descriptor's ordered handle-id
        tuple
      * output_dir — from the DXP subprocess command line
      * catalog — SHA-256 catalog of the bundle directory at the DXP
        call site (informational; not used for the fidelity verdict)
    """

    def __init__(self, mode: str, catalog_path: str | None) -> None:
        assert mode in ("stop", "observe", "passthrough")
        self.mode = mode
        self.catalog_path = catalog_path
        # kernel_name → identity + catalog dict
        self.captured: dict[str, dict] = {}
        self._pending_by_thread: dict[int, dict] = {}
        self.orig_run = None
        self.orig_sdsc = None

    def install(self) -> None:
        if self.mode == "passthrough":
            return
        from torch_spyre.execution import async_compile as _ac
        from torch_spyre.execution.async_compile import SpyreAsyncCompile

        if getattr(_ac, "_pre_dxp_intercept_installed", False):
            return

        # ---- Wrap SpyreAsyncCompile.sdsc to record identity signals
        # from the (kernel_name, specs) arguments BEFORE subprocess.run
        # is called. The identity survives even when the intercept later
        # raises the sentinel.
        self.orig_sdsc = SpyreAsyncCompile.sdsc

        def _identity_from_specs(kernel_name: str, specs) -> dict:
            import threading
            info: dict = {
                "kernel_name": kernel_name,
                "n_specs": len(specs),
            }
            try:
                sig = []
                for s in specs:
                    sig.append(type(s).__name__)
                # ordered counts (preserves order)
                counts: list[tuple[str, int]] = []
                for name in sig:
                    if counts and counts[-1][0] == name:
                        counts[-1] = (name, counts[-1][1] + 1)
                    else:
                        counts.append((name, 1))
                info["spec_type_run_length_signature"] = counts
                info["spec_type_total_signature"] = sorted(
                    {n: sig.count(n) for n in set(sig)}.items()
                )
            except Exception as e:
                info["spec_signature_error"] = repr(e)[:200]
            try:
                from torch_spyre._inductor.kernel_provenance import (
                    build_kernel_provenance_descriptor,
                )
                descriptor = build_kernel_provenance_descriptor(specs)
                info["provenance_key"] = descriptor.key
                info["debug_handle_ids"] = list(descriptor.debug_handle_ids)
                info["aten_ops"] = sorted(descriptor.aten_ops)
            except Exception as e:
                info["provenance_error"] = repr(e)[:200]
            info["thread_id"] = threading.get_ident()
            return info

        outer_self = self

        def _wrapped_sdsc(self, kernel_name, specs, *args, **kwargs):
            import threading
            tid = threading.get_ident()
            outer_self._pending_by_thread[tid] = _identity_from_specs(
                kernel_name, specs
            )
            try:
                return outer_self.orig_sdsc(self, kernel_name, specs, *args, **kwargs)
            finally:
                # observe mode: the sdsc call completed; move the
                # pending record into the captured map keyed by kernel.
                # stop mode: subprocess.run raised _PreDxpBoundary,
                # which propagates through here, so the finally block
                # still fires and we still record the identity.
                pending = outer_self._pending_by_thread.pop(tid, None)
                if pending is not None:
                    kn = pending["kernel_name"]
                    # If subprocess.run's wrapper already stashed the
                    # output_dir + catalog under this kernel, merge in.
                    existing = outer_self.captured.get(kn, {})
                    existing.update(pending)
                    outer_self.captured[kn] = existing

        SpyreAsyncCompile.sdsc = _wrapped_sdsc

        # ---- Wrap subprocess.run for the actual boundary behavior.
        self.orig_run = _ac.subprocess.run

        def _wrapped_run(*args, **kwargs):
            import threading
            cmd = args[0] if args else kwargs.get("args") or []
            if not (isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "dxp_standalone"):
                return outer_self.orig_run(*args, **kwargs)

            output_dir = None
            for i in range(len(cmd) - 1):
                if cmd[i] == "-d":
                    output_dir = cmd[i + 1]
                    break
            catalog = _catalog_dir(output_dir) if output_dir else {}

            # Find the pending identity record for this thread.
            tid = threading.get_ident()
            pending = outer_self._pending_by_thread.get(tid)
            kn = (pending or {}).get("kernel_name") \
                or (os.path.basename(output_dir) if output_dir else f"cmd{len(outer_self.captured)}")
            record = outer_self.captured.setdefault(kn, {})
            record.update({
                "cmd": list(cmd),
                "output_dir": output_dir,
                "catalog": catalog,
                "n_bundle_files": len(catalog),
            })
            if pending is not None:
                record.update({k: v for k, v in pending.items() if k not in record})

            try:
                _tr = sys.modules.get("torch_spyre._inductor.timing_recorder") \
                    or sys.modules.get("timing_recorder")
                if _tr is not None:
                    with _tr.stage(
                        "pre_dxp_boundary_marker",
                        cmd=list(cmd),
                        output_dir=output_dir,
                        n_files=len(catalog),
                    ):
                        pass
            except Exception:
                pass

            if outer_self.mode == "stop":
                raise _PreDxpBoundary(args, kwargs)
            # observe mode: identity + catalog recorded, DXP runs.
            return outer_self.orig_run(*args, **kwargs)

        _ac.subprocess.run = _wrapped_run  # type: ignore[attr-defined]
        _ac._pre_dxp_intercept_installed = True  # type: ignore[attr-defined]

    def dump_catalog(self) -> None:
        if self.catalog_path is None:
            return
        payload = {
            "mode": self.mode,
            "captured": self.captured,
        }
        tmp = self.catalog_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        os.replace(tmp, self.catalog_path)


# ---- workloads -------------------------------------------------------------

def _flash_workload(Lq: int, Lk: int):
    """Same flash-attention closure the prior study used, so results
    are directly comparable across analyses.
    """
    import math

    import torch

    B, H, D = 1, 8, 128
    b_block_size, h_block_size = 1, 4
    q_block_size, kv_block_size = 256, 512

    def flash(queries, keys, values, mask):
        scale = 1.0 / math.sqrt(math.sqrt(D))
        output = torch.zeros_like(queries)
        real_max = torch.full(
            (B, H, Lq, 64), float("-inf"), device=queries.device, dtype=torch.float16
        ).amax(-1)
        denominator = torch.zeros(
            (B, H, Lq, 64), device=queries.device, dtype=torch.float16
        ).amax(-1)
        for b_start in range(0, B, b_block_size):
            b_end = b_start + b_block_size
            for h_start in range(0, H, h_block_size):
                h_end = h_start + h_block_size
                for lq_start in range(0, Lq, q_block_size):
                    lq_end = lq_start + q_block_size
                    queries_tile = queries[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]
                    real_max_tile = real_max[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]
                    denominator_tile = denominator[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]
                    output_tile = output[
                        b_start:b_end, h_start:h_end, lq_start:lq_end
                    ]
                    for lk_start in range(0, Lk, kv_block_size):
                        lk_end = lk_start + kv_block_size
                        mask_tile = mask[:, :, lq_start:lq_end, lk_start:lk_end]
                        keys_tile = keys[
                            b_start:b_end, h_start:h_end, lk_start:lk_end
                        ]
                        values_tile = values[
                            b_start:b_end, h_start:h_end, lk_start:lk_end
                        ]
                        keys_tile_T = keys_tile.transpose(-1, -2).contiguous()
                        scores = torch.matmul(
                            queries_tile * scale, keys_tile_T * scale
                        )
                        scores = scores + mask_tile
                        block_max = torch.amax(scores, dim=-1)
                        running_max = torch.maximum(real_max_tile, block_max)
                        exp_scores = torch.exp(scores - running_max.unsqueeze(-1))
                        correction = torch.exp(real_max_tile - running_max)
                        denominator_tile.copy_(
                            denominator_tile * correction + exp_scores.sum(dim=-1)
                        )
                        output_tile.copy_(
                            output_tile * correction.unsqueeze(-1)
                            + torch.matmul(exp_scores, values_tile)
                        )
                        real_max_tile.copy_(running_max)
        return output / denominator.unsqueeze(-1)

    queries = torch.randn(B, H, Lq, D, device="spyre", dtype=torch.float16)
    keys = torch.randn(B, H, Lk, D, device="spyre", dtype=torch.float16)
    values = torch.randn(B, H, Lk, D, device="spyre", dtype=torch.float16)
    causal = torch.tril(torch.ones(Lq, Lk, dtype=torch.bool))
    mask_cpu = torch.zeros(1, 1, Lq, Lk, dtype=torch.float16)
    mask_cpu.masked_fill_(~causal, float("-inf"))
    mask = mask_cpu.to("spyre")
    return flash, (queries, keys, values, mask), {
        "B": B, "H": H, "D": D, "Lq": Lq, "Lk": Lk,
        "b_block_size": b_block_size, "h_block_size": h_block_size,
        "q_block_size": q_block_size, "kv_block_size": kv_block_size,
    }


def _mlp_workload(N_in: int, N_hidden: int, layers: int):
    """Layer-scaled MLP: hold width moderate, sweep depth. Produces
    proportional graph growth in FX node count.
    """
    import torch

    def mlp(x, weights, biases):
        for w, b in zip(weights, biases):
            x = torch.nn.functional.gelu(torch.matmul(x, w) + b)
        return x

    x = torch.randn(1, N_in, device="spyre", dtype=torch.float16)
    weights = [
        torch.randn(
            N_in if i == 0 else N_hidden,
            N_hidden if i < layers - 1 else N_in,
            device="spyre", dtype=torch.float16,
        )
        for i in range(layers)
    ]
    biases = [
        torch.randn(
            N_hidden if i < layers - 1 else N_in,
            device="spyre", dtype=torch.float16,
        )
        for i in range(layers)
    ]
    return mlp, (x, weights, biases), {
        "N_in": N_in, "N_hidden": N_hidden, "layers": layers,
    }


# ---- main ------------------------------------------------------------------

def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"FATAL: {name} required", file=sys.stderr)
        sys.exit(2)
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", choices=["flash", "mlp"], required=True)
    ap.add_argument("--Lq", type=int)
    ap.add_argument("--Lk", type=int)
    ap.add_argument("--N-in", type=int, dest="N_in", default=1024)
    ap.add_argument("--N-hidden", type=int, dest="N_hidden", default=4096)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--out", type=str, required=True, help="timing JSON path")
    ap.add_argument(
        "--mode", choices=["stop", "observe", "passthrough"], default="stop",
        help=(
            "stop = raise sentinel at DXP boundary (analysis-only); "
            "observe = catalog then let DXP run (fidelity check paired with stop); "
            "passthrough = no interception (baseline)."
        ),
    )
    ap.add_argument(
        "--catalog", type=str, default=None,
        help="Path for the pre-DXP catalog JSON. Also read from "
             "$SPYRE_PRE_DXP_CATALOG if unset.",
    )
    args = ap.parse_args()

    _require_env("TORCHINDUCTOR_CACHE_DIR")
    if os.environ.get("TORCH_SPYRE_TIMING") != "1":
        print("FATAL: TORCH_SPYRE_TIMING=1 required.", file=sys.stderr)
        return 2

    catalog_path = args.catalog or os.environ.get("SPYRE_PRE_DXP_CATALOG")

    import torch
    import torch_spyre  # noqa: F401
    from torch_spyre._inductor import timing_recorder as _tr
    from torch_spyre._inductor import config as _spyre_config

    # Resolved runtime values from torch_spyre._inductor.config (NOT env
    # strings). Any env override has already fired by the time we import
    # this module; the values below are what the compiler actually saw.
    _RECORDED_CONFIG_KEYS = [
        "layout_solver",
        "co_optimizing_lx_planning",
        "lx_planning",
        "lx_planner_relayout",
        "allow_all_ops_in_lx_planning",
        "sencores",
        "dxp_lx_frac_avail",
        "hbm_pool_planning",
        "frontend_pool_allocation",
        "global_stick_optimizer",
        "ignore_wsr_hints",
        "ignore_span_overflow_hints",
        "ignore_work_division_hints",
        "max_buckets",
        "min_default_granularity",
        "validate_op_specs",
        "native_layout_packer",
        "cost_model",
        "log_passes",
    ]
    resolved_config = {}
    for key in _RECORDED_CONFIG_KEYS:
        try:
            resolved_config[key] = getattr(_spyre_config, key)
        except AttributeError:
            resolved_config[key] = "<missing>"

    # Env strings recorded separately so we can see which values came
    # from an explicit override vs the source default.
    _RECORDED_ENV_KEYS = [
        "LAYOUT_SOLVER",
        "CO_OPTIMIZING_LX_PLANNING",
        "LX_PLANNING",
        "SPYRE_LX_PLANNER_RELAYOUT",
        "SENCORES",
        "DXP_LX_FRAC_AVAIL",
        "HBM_POOL_PLANNING",
        "FRONTEND_POOL_ALLOCATION",
        "GLOBAL_STICK_OPTIMIZER",
        "SPYRE_INDUCTOR_IGNORE_HINTS",
        "SPYRE_VALIDATE_OP_SPECS",
        "TORCH_SPYRE_NATIVE_PACKER",
        "USE_SPYRE_CCL",
        "TORCH_SPYRE_TIMING",
        "TORCH_LOGS",
    ]
    env_snapshot = {
        k: os.environ.get(k, "<unset>") for k in _RECORDED_ENV_KEYS
    }

    _tr.set_run_meta(
        workload=args.workload,
        mode=args.mode,
        Lq=args.Lq, Lk=args.Lk,
        N_in=args.N_in, N_hidden=args.N_hidden, layers=args.layers,
        TORCHINDUCTOR_CACHE_DIR=os.environ["TORCHINDUCTOR_CACHE_DIR"],
        SENCORES=os.environ.get("SENCORES", "<unset>"),
        pod=os.environ.get("HOSTNAME", "<unknown>"),
        torch_version=torch.__version__,
        python_version=sys.version.split()[0],
        pre_dxp_catalog_path=catalog_path,
        resolved_spyre_config=resolved_config,
        env_snapshot=env_snapshot,
    )

    torch.manual_seed(0xAFFE)

    if args.workload == "flash":
        if args.Lq is None or args.Lk is None:
            print("FATAL: --Lq and --Lk required for --workload=flash",
                  file=sys.stderr)
            return 2
        fn, inputs, meta = _flash_workload(args.Lq, args.Lk)
    elif args.workload == "mlp":
        fn, inputs, meta = _mlp_workload(args.N_in, args.N_hidden, args.layers)
    else:
        raise AssertionError(args.workload)
    _tr.set_run_meta(**meta)

    with _tr.stage("device_init_and_transfer"):
        pass

    gc.collect()

    intercept = _Interception(args.mode, catalog_path)
    intercept.install()

    compiled = torch.compile(fn)

    hit_boundary = False
    boundary_info: dict[str, Any] = {}
    try:
        with _tr.stage("first_call_wall"):
            compiled(*inputs)
        # observe / passthrough: no exception expected.
        if args.mode == "observe":
            hit_boundary = True
            # captured[*].cmd shows we reached the boundary.
            for key, rec in intercept.captured.items():
                boundary_info = {"dxp_cmd_captured": rec["cmd"]}
                break
    except _PreDxpBoundary as e:
        hit_boundary = True
        cmd = e.dxp_args[0] if e.dxp_args else e.dxp_kwargs.get("args")
        boundary_info = {"dxp_cmd_captured": list(cmd) if cmd else None}
    except Exception as e:  # noqa: BLE001
        cur: BaseException | None = e
        while cur is not None:
            if isinstance(cur, _PreDxpBoundary):
                hit_boundary = True
                cmd = cur.dxp_args[0] if cur.dxp_args else cur.dxp_kwargs.get("args")
                boundary_info = {"dxp_cmd_captured": list(cmd) if cmd else None}
                break
            cur = cur.__cause__ or cur.__context__
        if not hit_boundary:
            _tr.set_run_meta(unexpected_error=repr(e)[:2000])
            _tr.dump_and_finalize(args.out)
            raise

    _tr.set_run_meta(
        pre_dxp_boundary_reached=hit_boundary,
        boundary_info=boundary_info,
        n_captured_kernels=len(intercept.captured),
    )
    _tr.dump_and_finalize(args.out)
    intercept.dump_catalog()
    return 0


if __name__ == "__main__":
    sys.exit(main())
