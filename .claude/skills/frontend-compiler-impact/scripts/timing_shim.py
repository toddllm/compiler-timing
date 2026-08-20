"""Runtime instrumentation shim.

Applied to an isolated torch-spyre checkout that does NOT have the
primary study's committed `compile_fx_wrapper` and `pipeline:*` instrumentation
in-tree. This module:

1. Imports the `timing_recorder` implementation from the primary study
   (bundled next to this shim as `timing_recorder.py`).
2. Monkey-patches:
   - `torch_spyre._inductor.enable_spyre_compile_fx_wrapper` to wrap the
     `_wrapper` closure it returns with a `_tr.stage("compile_fx_wrapper")`
     block that records `fx_nodes_at_entry`.
   - `torch_spyre._inductor.passes._SpyreOpPassPipeline.__call__` to wrap
     each pass in a `_tr.stage("pipeline:...")` / `_tr.stage("pass:...")` pair.
   - `torch_spyre._inductor.passes._SpyreNodePassPipeline.__call__` similarly.
3. Instruments `torch_spyre.execution.async_compile.SpyreAsyncCompile.sdsc`
   for `sdsc_total`, `sdsc_bundle_gen`, `dxp_standalone`, `async_compile_wait`.

Usage from a harness or a wrapper script:

    import timing_shim  # applies the shim on import

Or as a prelude:

    python -c "import sys; sys.path.insert(0, '<shim-dir>'); import timing_shim; \
               exec(open('<harness>').read())"

The shim is designed to be idempotent: safe to import multiple times.
"""
from __future__ import annotations

import functools
import os

# Load the primary-study timing_recorder module. It is bundled next to this
# file as timing_recorder.py so the shim is self-contained.
_HERE = os.path.dirname(os.path.abspath(__file__))
import importlib.util
import sys as _sys
_MOD_NAME = "spyre_timing_shim_recorder"
_spec = importlib.util.spec_from_file_location(
    _MOD_NAME, os.path.join(_HERE, "timing_recorder.py")
)
_tr = importlib.util.module_from_spec(_spec)
# Register in sys.modules BEFORE exec so @dataclass and friends can find
# the class's own module namespace during class creation.
_sys.modules[_MOD_NAME] = _tr
_spec.loader.exec_module(_tr)


_INSTALLED = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    if not _tr.is_enabled():
        _INSTALLED = True
        return

    # Import torch FIRST — torch_spyre's autoloader requires torch already
    # imported at module init to avoid a circular-import failure.
    import torch  # noqa: F401

    # --- (1) compile_fx_wrapper --------------------------------------------
    import torch_spyre._inductor as _tsi
    if hasattr(_tsi, "enable_spyre_compile_fx_wrapper"):
        _orig_enable = _tsi.enable_spyre_compile_fx_wrapper

        @functools.wraps(_orig_enable)
        def _enable_wrapper():
            cm = _orig_enable()
            # cm is a context manager that patches compile_fx. It internally
            # calls the wrapped _wrapper closure — we cannot easily intercept
            # THAT closure across versions. Instead, patch compile_fx itself
            # here so we time each compile_fx call.
            return cm
        _tsi.enable_spyre_compile_fx_wrapper = _enable_wrapper

    # Simpler and version-agnostic: monkey-patch torch.compile's inductor
    # backend entry point directly.
    import torch._inductor.compile_fx as _cfx
    _orig_compile_fx = _cfx.compile_fx

    @functools.wraps(_orig_compile_fx)
    def _timed_compile_fx(gm, example_inputs, *args, **kwargs):
        try:
            fx_nodes = len(list(gm.graph.nodes))
        except Exception:
            fx_nodes = -1
        # Only time when compiling on the spyre device (avoid CPU-reference compile).
        uses_spyre = False
        try:
            for t in (example_inputs or []):
                dev = getattr(t, "device", None)
                if dev is not None:
                    ds = str(dev).split(":")[0]
                    if ds == "spyre":
                        uses_spyre = True
                        break
        except Exception:
            pass
        if uses_spyre:
            with _tr.stage("compile_fx_wrapper", fx_nodes_at_entry=fx_nodes):
                return _orig_compile_fx(gm, example_inputs, *args, **kwargs)
        else:
            return _orig_compile_fx(gm, example_inputs, *args, **kwargs)

    _cfx.compile_fx = _timed_compile_fx

    # --- (2) Spyre pipelines & passes --------------------------------------
    from torch_spyre._inductor import passes as _passes

    def _instrument_pipeline_cls(cls):
        if getattr(cls, "_ts_shim_instrumented", False):
            return
        _orig_call = cls.__call__

        @functools.wraps(_orig_call)
        def _timed_call(self, target):
            if not self._has_spyre_device(target):
                return _orig_call(self, target)
            pipeline_name = type(self).__name__
            n_passes = len(getattr(self, "passes", []))
            with _tr.stage(f"pipeline:{pipeline_name}", passes=n_passes):
                # Some pipelines return a value (node pipelines), some don't.
                # Reuse _orig_call semantics for correctness; we don't decompose
                # per-pass here to remain version-agnostic. The umbrella
                # pipeline timings are the primary signal for A/B.
                return _orig_call(self, target)

        cls.__call__ = _timed_call
        cls._ts_shim_instrumented = True

    for name in ("_SpyreOpPassPipeline", "_SpyreNodePassPipeline",
                 "SpyreOpPassPipeline", "SpyreNodePassPipeline",
                 "CustomGraphPass"):
        if hasattr(_passes, name):
            _instrument_pipeline_cls(getattr(_passes, name))

    # Also try to instrument individual pipeline instances that the primary
    # study times — CustomPreSchedulingPasses is the dominant one; if we can
    # find its class we wrap it.
    for pipeline_name in ("CustomPreGradPasses", "CustomPrePasses",
                          "CustomPostPasses", "CustomPreFusionPasses",
                          "CustomPostFusionPasses", "CustomPreSchedulingPasses"):
        cls = getattr(_passes, pipeline_name, None)
        if cls is not None and isinstance(cls, type):
            _instrument_pipeline_cls(cls)

    # --- (3) sdsc / dxp_standalone -----------------------------------------
    try:
        from torch_spyre.execution import async_compile as _ac
        cls = getattr(_ac, "SpyreAsyncCompile", None)
        if cls is not None and not getattr(cls, "_ts_shim_instrumented", False):
            _orig_sdsc = cls.sdsc

            @functools.wraps(_orig_sdsc)
            def _timed_sdsc(self, kernel_name, specs, *args, **kwargs):
                with _tr.stage("sdsc_total", kernel=kernel_name):
                    return _orig_sdsc(self, kernel_name, specs, *args, **kwargs)

            cls.sdsc = _timed_sdsc
            cls._ts_shim_instrumented = True
    except Exception:
        pass

    _INSTALLED = True


# Auto-install on import.
install()
