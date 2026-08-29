# Pre-DXP compile-fx stage map

Source basis: `torch-spyre/torch-spyre @ 3855d11` (upstream/main at
time of writing).

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
        │                       │     │     ├── deadcode_elimination
        │                       │     │     ├── propagate_named_dims
        │                       │     │     ├── validate_named_dims
        │                       │     │     ├── assign_dim_hints
        │                       │     │     ├── _maybe_reorder_unhinted_interlopers
        │                       │     │     ├── _maybe_coarse_tile_hints
        │                       │     │     ├── split_multi_ops
        │                       │     │     ├── propagate_spyre_tensor_layouts
        │                       │     │     ├── validate_ops
        │                       │     │     ├── optimize_restickify_locations
        │                       │     │     ├── finalize_layouts
        │                       │     │     ├── insert_restickify
        │                       │     │     ├── validate_no_restickify_on_mutation_targets
        │                       │     │     ├── enforce_indirect_access_layout
        │                       │     │     ├── insert_post_mutation_restickify
        │                       │     │     ├── insert_restickify_padding
        │                       │     │     ├── insert_bmm_padding
        │                       │     │     ├── dedup_and_promote_constants
        │                       │     │     ├── _maybe_coarse_tile_span_overflow
        │                       │     │     ├── span_reduction
        │                       │     │     ├── _distribute_work
        │                       │     │     ├── _maybe_scratchpad_planning
        │                       │     │     └── elide_proven_read_copies
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
- `torch_spyre/_inductor/passes.py:446-492` — `CustomPreSchedulingPasses.__init__`: 22-pass list, in order:
  `deadcode_elimination`, `propagate_named_dims`, `validate_named_dims`, `assign_dim_hints`, `_maybe_reorder_unhinted_interlopers`, `_maybe_coarse_tile_hints`, `split_multi_ops`, `propagate_spyre_tensor_layouts`, `validate_ops`, `optimize_restickify_locations`, `finalize_layouts`, `insert_restickify`, `validate_no_restickify_on_mutation_targets`, `enforce_indirect_access_layout`, `insert_post_mutation_restickify`, `insert_restickify_padding`, `insert_bmm_padding`, `dedup_and_promote_constants`, `_maybe_coarse_tile_span_overflow`, `span_reduction`, `_distribute_work`, `_maybe_scratchpad_planning`, `elide_proven_read_copies`.
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

## Non-obvious things to watch during timing

1. **`_pre_fusion_custom_pass` and `_post_fusion_custom_pass` fire inside `Scheduler`**, not inside `_pre_scheduling_pass`. Time attributed to "CustomPreSchedulingPasses" excludes them. They belong in the Scheduler bucket.
2. **`recover_spyre_hints`** runs once per compile at `_spyre_update_scheduler` entry, before `_pre_scheduling_pass`. It is not accounted for in the per-pass `elapsed_ms` loop, and it is inside the CustomPreSchedulingPasses bucket by the boundary above but not observable through the existing `elapsed_ms` INFO log.
3. **The `_update_scheduler` monkey-patch fires from upstream `Scheduler` construction inside `codegen`.** Anything Inductor does after `_update_scheduler` returns (fusion, per-node codegen, wrapper codegen) is *scheduling/codegen/backend-input preparation* and belongs in that bucket, not `CustomPreSchedulingPasses`.
4. **First-call vs compile-time split.** The pre-scheduling passes run once during `compile_fx_wrapper`; SDSC bundle generation and `dxp_standalone` invocation run on first invocation of the compiled wrapper. Reconciling to a single "pre-DXP" total means summing `compile_fx_wrapper` + the interval inside `first_call_wall` up to `subprocess.run`.
5. **CustomPreSchedulingPasses is a module-level singleton** (`_pre_scheduling_pass = CustomPreSchedulingPasses()` at `patches.py:111`). Multiple compiles share the pass instance but each `__call__` operates on a fresh `GraphLowering`.
6. **PR #4113's dedup fix already merged** — `dedup_and_promote_constants` should not appear as a scaling defect in current data (verify anyway).
7. The `CustomPreSchedulingPasses.__call__` early-returns if `_operations_have_spyre_device(graph.operations)` is false (`passes.py:495`). A no-op run is possible on non-Spyre subgraphs; the harness must confirm the run is Spyre-active.

## What Phase 2 needs to know

- The safe pre-DXP stop point is **immediately before `subprocess.run(["dxp_standalone", ...])` at `async_compile.py:155`**. `generate_bundle` and `build_kernel_provenance_descriptor` are torch-side; they must run to reach a state that a normal DXP compile would see. Skipping the subprocess and everything after (`SpyreSDSCKernelRunner`) is safe as long as the caller does not attempt to execute the returned kernel.
- The harness should therefore patch `subprocess.run` in `torch_spyre.execution.async_compile` (or intercept the call site) to raise a sentinel exception after generation, catch it in the outer test loop, and record the "pre-DXP" total wall-clock.
- Verify that the artifacts produced by `generate_bundle` (the SDSC bundle files) match what a normal run produces at a baseline point. This is the fidelity check.
