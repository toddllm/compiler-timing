"""Post-build sanity check: USE_SPYRE_CCL=0 does not perturb the
compiler frontend path for the epic #4117 workloads.

Runs flash 512x1024 once through the pre-DXP-stop harness's stage()
recorder and prints, from the resulting event tree:

  - FX node count at compile_fx entry (compile_fx_wrapper meta)
  - pre-scheduling input operation count (pipeline event meta)
  - emitted kernel count (count of spyre_kernel_codegen events)
  - number of specs handed to sdsc (sdsc_bundle_gen meta)
  - relevant Inductor config values that affect the frontend

Also confirms that ``torch_spyre._C`` was built without
``USE_SPYRE_CCL`` (i.e. no distributed bindings) by trying to import
the distributed submodule and reporting the outcome.

Justification (§5 of the review-1 corrections plus §5 of the CCL=0
instruction): distributed collectives are out of scope for this
study; disabling CCL removes a cross-repo build dependency without
touching any frontend path our workloads exercise. This script makes
that claim inspectable.
"""

from __future__ import annotations

import json
import os
import sys


def _report_binding_status() -> dict:
    """Confirm the distributed C++ symbols are absent when
    USE_SPYRE_CCL=0. Torch-Spyre's distributed Python module imports
    from torch_spyre._C only when compiled with USE_SPYRE_CCL.
    """
    # torch first: importing torch_spyre triggers torch's device-backend
    # autoload which will re-enter torch_spyre; import torch first so
    # that path has completed before we ask for torch_spyre directly.
    import torch  # noqa: F401
    import torch_spyre
    import torch_spyre._C as _C

    # Distributed init symbols are compiled in only under
    # USE_SPYRE_CCL. Their absence proves the CCL=0 build lever fired.
    ccl_symbols = [name for name in dir(_C) if "ccl" in name.lower() or "spyre_comms" in name.lower()]

    # Also try to import the Python-side distributed module; expect
    # this to be absent-or-empty when CCL=0.
    dist_imported = False
    dist_err = None
    try:
        from torch_spyre import distributed  # noqa: F401
        dist_imported = True
    except Exception as e:
        dist_err = f"{type(e).__name__}: {e}"

    return {
        "USE_SPYRE_CCL_env": os.environ.get("USE_SPYRE_CCL", "<unset>"),
        "torch_spyre_from": torch_spyre.__file__,
        "torch_spyre__C_ccl_symbols": ccl_symbols,
        "torch_spyre.distributed_imported": dist_imported,
        "torch_spyre.distributed_import_error": dist_err,
    }


def _inductor_config_snapshot() -> dict:
    """Snapshot Inductor config values that touch the compiler frontend
    for this study. Used to prove that CCL=0 does not perturb the
    pass pipeline configuration.
    """
    import torch  # noqa: F401
    import torch._inductor.config as ic
    return {
        # Post-review §5 direct-timer surface: these are the values we
        # rely on for pass-pipeline behaviour. Any drift with CCL flag
        # would show up as a difference between builds; recording lets
        # future readers cross-check.
        "split_reductions": ic.split_reductions,
        "benchmark_harness": ic.benchmark_harness,
        "permute_fusion": ic.permute_fusion,
        "allow_buffer_reuse": ic.allow_buffer_reuse,
        "unroll_reductions_threshold": ic.unroll_reductions_threshold,
    }


def _stats_from_events(path: str) -> dict:
    with open(path) as fh:
        doc = json.load(fh)
    events = doc.get("events") or []

    def first(name):
        for e in events:
            if e.get("name") == name:
                return e
        return None

    def count(name):
        return sum(1 for e in events if e.get("name") == name)

    cfw = first("compile_fx_wrapper")
    pipeline = first("pipeline:CustomPreSchedulingPasses")
    bundle = first("sdsc_bundle_gen")
    sched_init = first("scheduler_init")

    return {
        "fx_nodes_at_entry": (cfw or {}).get("meta", {}).get("fx_nodes_at_entry"),
        "presched_input_operations": (pipeline or {}).get("meta", {}).get("input_operations"),
        "presched_passes_in_pipeline": (pipeline or {}).get("meta", {}).get("passes"),
        "scheduler_init_input_nodes": (sched_init or {}).get("meta", {}).get("input_nodes"),
        "n_kernels_emitted": count("spyre_kernel_codegen"),
        "n_specs_to_sdsc": (bundle or {}).get("meta", {}).get("n_specs"),
        "meta_from_run": doc.get("meta", {}),
    }


def main() -> int:
    # The harness populates $SPYRE_TIMING_OUT; we pick the JSON from there.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--timing-json", required=True,
                    help="Path to timing JSON from one flash 512x1024 stop run.")
    ap.add_argument("--out", required=True,
                    help="Path to write the invariants JSON.")
    args = ap.parse_args()

    result = {
        "binding_status": _report_binding_status(),
        "inductor_config": _inductor_config_snapshot(),
        "run_stats": _stats_from_events(args.timing_json),
    }
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
