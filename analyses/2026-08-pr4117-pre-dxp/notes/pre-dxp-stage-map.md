# Pre-DXP compile-fx stage map

Source basis (**frozen**): `torch-spyre/torch-spyre @
3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f` (upstream/main at study
start, verified to contain PR #4113 merge
`c073d69cceaac91d34b01dea6545048d0d645c2c` as ancestor).

Purpose: enumerate every source-level stage between the user's
`torch.compile(...)` call and the `dxp_standalone` subprocess
invocation, with file:line citations, so the timing harness in
Phase 2/3 can reconcile hierarchically. This document does **not**
attribute time — that is Phase 5.

## Nesting

```
first_call_wall                                 (harness-observable)
  └── compile_fx_wrapper                        (torch-spyre wraps torch._inductor.compile_fx)
        ├── dynamo / AOTAutograd                (upstream; produces post-grad FX graph)
        │       └── pre_grad_custom_pass = CustomPreGradPasses
        │       └── post_grad_custom_pre_pass = CustomPrePasses
        │       └── post_grad_custom_post_pass = CustomPostPasses
        ├── inner_compile (= _spyre_inner_compile)
        │     └── compile_fx_inner
        │           └── GraphLowering.__init__ + graph lowering (Inductor)
        │           │   └── per-FX-node run_node / lowering registrations
        │           └── GraphLowering.compile_to_module
        │                 └── GraphLowering.codegen
        │                       ├── GraphLowering._update_scheduler
        │                       │     ├── recover_spyre_hints (once per compile)
        │                       │     ├── CustomPreSchedulingPasses.__call__
        │                       │     │     ├── presched_pass_loop  (23 passes)
        │                       │     │     │     ├── deadcode_elimination
        │                       │     │     │     ├── propagate_named_dims
        │                       │     │     │     ├── validate_named_dims
        │                       │     │     │     ├── assign_dim_hints
        │                       │     │     │     ├── _maybe_reorder_unhinted_interlopers
        │                       │     │     │     ├── _maybe_coarse_tile_hints
        │                       │     │     │     ├── split_multi_ops
        │                       │     │     │     ├── propagate_spyre_tensor_layouts
        │                       │     │     │     ├── validate_ops
        │                       │     │     │     ├── optimize_restickify_locations
        │                       │     │     │     ├── finalize_layouts
        │                       │     │     │     ├── insert_restickify
        │                       │     │     │     ├── validate_no_restickify_on_mutation_targets
        │                       │     │     │     ├── enforce_indirect_access_layout
        │                       │     │     │     ├── insert_post_mutation_restickify
        │                       │     │     │     ├── insert_restickify_padding
        │                       │     │     │     ├── insert_bmm_padding
        │                       │     │     │     ├── dedup_and_promote_constants
        │                       │     │     │     ├── _maybe_coarse_tile_span_overflow
        │                       │     │     │     ├── span_reduction
        │                       │     │     │     ├── _distribute_work
        │                       │     │     │     ├── _maybe_scratchpad_planning
        │                       │     │     │     └── elide_proven_read_copies
        │                       │     │     ├── presched_cost_model
        │                       │     │     ├── presched_cost_dump
        │                       │     │     └── presched_finalize_work_division
        │                       │     ├── _pre_fusion_custom_pass = CustomPreFusionPasses
        │                       │     │     (invoked via Scheduler; upstream ordering)
        │                       │     └── Scheduler(self.operations)
        │                       │           └── _post_fusion_custom_pass = CustomPostFusionPasses
        │                       └── Scheduler.codegen()
        │                             ├── per SpyreKernel.codegen_kernel
        │                             │     └── SDSC OpSpec generation (torch-side)
        │                             └── PythonWrapperCodegen (SpyrePythonWrapperCodegen)
        │                                   └── wrapper module compiled and returned
        └── first-call execution (compiled module invoked)
              └── SpyreAsyncCompile.sdsc(kernel_name, specs, ...)
                    ├── generate_bundle(kernel_name, output_dir, specs, pool_size)
                    │     — writes SDSC bundle artifacts under output_dir
                    ├── build_kernel_provenance_descriptor(finalized_specs)
                    └── subprocess.run(["dxp_standalone", "-d", output_dir])
                          ─────────── PRE-DXP BOUNDARY ───────────
                    ← everything after this line is DXP + kernel-load
```

## Buckets aligned with epic #4117

| bucket                                | starts at                                                        | ends at                                                        | notes |
|---------------------------------------|------------------------------------------------------------------|----------------------------------------------------------------|-------|
| Dynamo / AOT / upstream Inductor      | `torch.compile(...)` returns callable; first invocation triggers | end of `compile_fx_inner`'s upstream lowering, before per-Spyre passes fire | Torch-Spyre's `enable_spyre_context` and pre/post-grad custom passes execute inside this bucket |
| Torch-Spyre lowering                  | Inductor calls `run_node` per FX node                            | `GraphLowering` fully populated                                | Registered via `torch_spyre._inductor.lowering` + `_inductor.customops` |
| CustomPreSchedulingPasses (20 passes) | `_spyre_update_scheduler` calls `_pre_scheduling_pass(self)` (`patches.py:126`) | Last pass in the list returns                    | Instrumented per-pass with `elapsed_ms` at INFO level in the pipeline itself (`passes.py:513-521`) |
| Scheduler + node-pass pipelines       | `Scheduler(self.operations)` inside `_update_scheduler`          | `Scheduler.codegen()` returns                                  | Invokes `CustomPreFusionPasses` and `CustomPostFusionPasses` around fusion |
| SDSC / backend-input generation       | `SpyrePythonWrapperCodegen` emits the wrapper module             | `SpyreAsyncCompile.sdsc()` returns just before subprocess call | Includes `generate_bundle` and `build_kernel_provenance_descriptor` |
| DXP invocation boundary               | `subprocess.run(["dxp_standalone", ...])`                        | subprocess exits                                                | **Out of scope for this investigation.** |

## Key file:line anchors (upstream `3855d11`)

- `torch_spyre/_inductor/__init__.py:76-196` — `enable_spyre_compile_fx_wrapper`: monkey-patches `torch._inductor.compile_fx` with `_wrapper`. `_wrapper` calls `torch.spyre._impl._lazy_init()`, sets `kwargs["decompositions"]`, `kwargs["inner_compile"] = _spyre_inner_compile`, wraps the call in `enable_spyre_context`, then calls the original `compile_fx`.
- `torch_spyre/_inductor/__init__.py:33-73` — `_spyre_inner_compile`: rebinds `get_decomp_fn` to a picklable module-level callable, then delegates to `compile_fx_inner`.
- `torch_spyre/_inductor/patches.py:41-95` — `enable_spyre_context`: applies Torch-Spyre-specific Inductor config (`split_reductions=False`, `pre_grad_custom_pass=CustomPreGradPasses()`, `post_grad_custom_pre_pass=CustomPrePasses()`, `post_grad_custom_post_pass=CustomPostPasses()`, `_pre_fusion_custom_pass=CustomPreFusionPasses()`, `_post_fusion_custom_pass=CustomPostFusionPasses()`, `unroll_reductions_threshold=1`, `permute_fusion=False`, `allow_buffer_reuse=False`) via `torch._inductor.config.patch(new_config)`.
- `torch_spyre/_inductor/patches.py:109-130` — `_spyre_update_scheduler`: monkey-patched onto `GraphLowering._update_scheduler`. First per-compile call runs `recover_spyre_hints` (once) then `_pre_scheduling_pass(self)` (a module-level `CustomPreSchedulingPasses` instance). Then delegates to the upstream `_update_scheduler` which builds the `Scheduler`.
- `torch_spyre/_inductor/passes.py:452-498` — `CustomPreSchedulingPasses.__init__`: **23**-pass list, in order:
  1. `deadcode_elimination` 2. `propagate_named_dims` 3. `validate_named_dims`
  4. `assign_dim_hints` 5. `_maybe_reorder_unhinted_interlopers`
  6. `_maybe_coarse_tile_hints` 7. `split_multi_ops`
  8. `propagate_spyre_tensor_layouts` 9. `validate_ops`
  10. `optimize_restickify_locations` 11. `finalize_layouts`
  12. `insert_restickify` 13. `validate_no_restickify_on_mutation_targets`
  14. `enforce_indirect_access_layout` 15. `insert_post_mutation_restickify`
  16. `insert_restickify_padding` 17. `insert_bmm_padding`
  18. `dedup_and_promote_constants` 19. `_maybe_coarse_tile_span_overflow`
  20. `span_reduction` 21. `_distribute_work` 22. `_maybe_scratchpad_planning`
  23. `elide_proven_read_copies`.
- `torch_spyre/_inductor/passes.py:500-553` — `CustomPreSchedulingPasses.__call__`: runs the 23-pass loop and then, **outside the loop but INSIDE this method**, invokes `cost_model_pass(graph)`, `dump_cost_model(graph.operations)`, and `finalize_work_division_for_scheduler(graph)`. The pipeline instrumentation MUST bracket the whole `__call__`; the pass loop is a nested sub-region called `presched_pass_loop`, and the three post-loop calls are directly-measured sub-regions (`presched_cost_model`, `presched_cost_dump`, `presched_finalize_work_division`).
- `torch_spyre/_inductor/patches.py:113-128` — `_spyre_update_scheduler`: brackets `recover_spyre_hints` (only when `__spyre_dim_hints` is present in module meta), then `_pre_scheduling_pass(self)`, then the upstream `_update_scheduler` (which builds the `Scheduler` and fires `CustomPreFusionPasses` + upstream fusion + `CustomPostFusionPasses`). Timed as `spyre_update_scheduler` around the whole body, with nested `recover_spyre_hints` and `upstream_update_scheduler` stages.
- `torch_spyre/_inductor/passes.py:492-540` — `CustomPreSchedulingPasses.__call__`: loops over passes, wraps each in `SpyreGraphTransformObserver`, times each with `time.perf_counter`. Records to INFO log as `elapsed %5dms  %s`.
- `torch/_inductor/graph.py:2245-2254` (upstream 2.13) — `_update_scheduler`: `self.scheduler = Scheduler(self.operations)`. Note that upstream Inductor internally calls `_pre_fusion_custom_pass` inside the `Scheduler` construction and `_post_fusion_custom_pass` after fusion.
- `torch/_inductor/graph.py:2256-2274` (upstream 2.13) — `codegen`: calls `_update_scheduler()`, then `scheduler.codegen()`.
- `torch/_inductor/graph.py:2312-2338` (upstream 2.13) — `compile_to_module`: calls `codegen_with_cpp_wrapper()` (if cpp) or `codegen()`. Returns the compiled Python wrapper module.
- `torch_spyre/execution/async_compile.py:112-173` — `SpyreAsyncCompile.sdsc`: called at first invocation of the compiled wrapper. Runs `find_unimplemented`, `generate_bundle` (writes the SDSC bundle to disk), `build_kernel_provenance_descriptor`, then `subprocess.run(["dxp_standalone", "-d", output_dir])`.
- `torch_spyre/execution/async_compile.py:152-158` — **the DXP boundary**. `subprocess.run(...)`.

## What is NOT inside `compile_fx_wrapper`

- **Dynamo tracing before `compile_fx`.** `torch.compile` is a Dynamo decorator; Dynamo captures the frame, produces an FX graph, and only then invokes the backend (Inductor via `compile_fx_wrapper`). Time spent in Dynamo bytecode analysis, guard evaluation, graph capture is upstream of `compile_fx_wrapper`.
- **First runtime execution of the compiled artifact.** `SpyreAsyncCompile.sdsc()` and thus `dxp_standalone` fire when the compiled wrapper is *called*, not when `compile_fx_wrapper` returns. The PR #3806 study captured this by wrapping the first call in `first_call_wall`. If `dxp_standalone` is deferred to first-call, the "pre-DXP" boundary spans two intervals — `compile_fx_wrapper` proper, plus everything inside `first_call_wall` up to the subprocess.

## Existing observability

The pass pipeline already emits per-pass `elapsed_ms` at INFO level (see `passes.py:517-522`). The dedup timing study
(`analyses/2026-08-pr3806-frontend-timing/`) built a `timing_recorder` module that hierarchically bracketed:

- `first_call_wall`
- `compile_fx_wrapper` (via the `_wrapper` in `_inductor/__init__.py`)
- one `pipeline:CustomPre*Passes` event per pipeline instance
- one `pass:CustomPreSchedulingPasses:<name>` event per pass
- `sdsc_total` (around `SpyreAsyncCompile.sdsc`)
- `sdsc_bundle_gen` (around `generate_bundle`)
- `dxp_standalone` (around the subprocess itself — not part of pre-DXP but bracketed to give it a clean boundary)
- `async_compile_wait`

That module is the natural reuse target for Phase 3 instrumentation — extend rather than rewrite.

## Direct `_spyre_inner_compile` bracket

Torch-Spyre's ``_spyre_inner_compile`` is the picklable-wrapper that
Inductor calls as ``inner_compile`` — it delegates to the upstream
``torch._inductor.compile_fx.compile_fx_inner``. Everything inside
Inductor's inner compile fires within this call.

On flash 512×1024 the outer ``compile_fx_wrapper`` interval is
~20 s; only ~13.6 s of that is inside ``_spyre_inner_compile``. The
outer ~6.5 s runs AOTAutograd's joint-graph preparation before the
inner compile fires. Timing ``_spyre_inner_compile`` directly gives:

* ``compile_fx_outer_other`` — the pre-inner path (AOTAutograd
  prep, pre/post-grad passes, dynamo-side bookkeeping).
* ``spyre_inner_compile`` — the inner compile itself.

Both are timestamp-partitioned from ``compile_fx_wrapper.inclusive``
with zero subtraction of un-verified children.

## Discovered timeline (pilot smoke, flash 512×1024)

The pre-pilot draft of this document assumed that
``SpyreAsyncCompile.sdsc()`` would fire during a separate
first-invocation phase, i.e. under ``async_compile.wait(globals())``
called from the generated wrapper on first call. Empirical smoke on
the frozen build showed a different topology:

* ``torch.compile(fn)`` returns immediately; Dynamo does not trace
  the function until ``fn`` is actually called.
* On first call, Dynamo traces + AOTAutograd runs (~318 ms), then
  invokes the backend (``compile_fx_wrapper``).
* Inside ``compile_fx_wrapper``, Inductor runs
  ``GraphLowering.run`` and then ``GraphLowering.compile_to_module``.
* ``compile_to_module → _compile_to_module_lines`` loads the
  generated Python wrapper module via ``PyCodeCache.load_by_key_path``.
* Loading a Python module **executes its top-level statements**.
  The generated wrapper's module body contains one
  ``async_compile.sdsc('<kernel_name>', ...)`` call per kernel,
  followed by ``async_compile.wait(globals())``.
* ``SpyreAsyncCompile.sdsc()`` runs the SDSC bundle generator +
  ``dxp_standalone`` **synchronously**, then returns a fully-loaded
  runner. So ``async_compile.wait(globals())`` becomes a no-op — but
  the sentinel never reaches it in ``--mode=stop`` because
  ``sdsc()`` raises ``_PreDxpBoundary`` first.

Consequence: ``sdsc_total``, ``sdsc_bundle_gen``,
``kernel_provenance``, and ``dxp_standalone`` are all nested inside
``compile_fx_wrapper`` on this build — specifically under
``wrapper_module_exec`` (a directly-timed bracket on
``GraphLowering._compile_to_module_lines``). The analyzer verifies
this via timestamp containment on every run rather than assuming it.

## Non-obvious things the framework accounts for

1. **`_pre_fusion_custom_pass` and `_post_fusion_custom_pass` fire inside `Scheduler.__init__`**, not inside `_pre_scheduling_pass`. Timed as separate `pipeline:CustomPreFusionPasses` and `pipeline:CustomPostFusionPasses` events under `scheduler_init`.
2. **`recover_spyre_hints`** runs once per compile at `_spyre_update_scheduler` entry, before `_pre_scheduling_pass`. Timed as its own `recover_spyre_hints` stage.
3. **`cost_model_pass`, `dump_cost_model`, and `finalize_work_division_for_scheduler`** run inside `CustomPreSchedulingPasses.__call__` but **outside** the 23-pass loop. The pipeline event brackets ALL of them; nested stages `presched_pass_loop`, `presched_cost_model`, `presched_cost_dump`, `presched_finalize_work_division` isolate each.
4. **`compile_fx_wrapper` and `async_compile_wait` are TIME-DISJOINT SIBLINGS** under `first_call_wall`. The compile produces a compiled artifact; `async_compile.wait()` fires when the wrapper module initializes at first invocation, INSIDE `first_call_wall` but AFTER `compile_fx_wrapper` has returned. **Never subtract `sdsc_total` from `compile_fx_wrapper` or `compile_to_module`.**
5. **CustomPreSchedulingPasses is a module-level singleton** (`_pre_scheduling_pass = CustomPreSchedulingPasses()` in `patches.py`). Multiple compiles share the pass instance but each `__call__` operates on a fresh `GraphLowering`.
6. **PR #4113's dedup fix is upstream** at the frozen SHA — `dedup_and_promote_constants` should not appear as a scaling defect. `tables/pass-detail.md` verifies this.
7. `CustomPreSchedulingPasses.__call__` early-returns if `_operations_have_spyre_device(graph.operations)` is false. The harness confirms the run is Spyre-active via the boundary marker capture and the `input_operations` metadata on the pipeline event.

## Pre-DXP boundary and primary total

- The safe pre-DXP stop point is **immediately before `subprocess.run(["dxp_standalone", ...])` at `async_compile.py:155`**. `generate_bundle` and `build_kernel_provenance_descriptor` are torch-side; they run to reach the exact state a normal DXP compile would see. Skipping the subprocess and everything after (`SpyreSDSCKernelRunner`) is safe as long as the caller does not attempt to execute the returned kernel.
- The harness patches `subprocess.run` in `torch_spyre.execution.async_compile` with an `_Interception` that has three modes: `stop` (catalog, boundary marker, raise sentinel), `observe` (catalog, boundary marker, delegate to real subprocess), and `passthrough` (no interception). `stop` mode is analysis-only; `observe` is the paired-run fidelity check.
- **Primary `pre_dxp_total`** is derived directly from timestamps as `pre_dxp_boundary_marker.t_start_ns − first_call_wall.t_start_ns`, NOT from `first_call_wall.inclusive_ns`. This excludes the sentinel-unwind cost. The unwind is reported separately as `sentinel_unwind` and expected to be small.
- **Fidelity** is proven by a paired `observe` + `stop` run at a baseline shape: both catalog the bundle at the exact same call site (before subprocess.run), and the two catalogs must be byte-identical. See `harness/check_bundle_fidelity.py`.
