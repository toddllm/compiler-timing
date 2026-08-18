# Timing boundary map

Boundaries measured by `patches/timing_recorder.py` and installed by
the diff in `patches/instrumentation.patch`. Every event in the JSON
under `data/` corresponds to one entry below. Nesting is expressed as
indentation: an inner event's inclusive time is fully contained in
its parent's inclusive time.

## Compile call structure

```
first_call_wall                                    (outermost, from harness)
└── compile_fx_wrapper                             (torch-spyre wraps compile_fx)
    ├── pipeline:CustomPreGradPasses
    ├── pipeline:CustomPrePasses
    ├── pipeline:CustomPostPasses
    ├── pipeline:CustomPreFusionPasses
    ├── pipeline:CustomPostFusionPasses
    ├── pipeline:CustomPreSchedulingPasses          (main pre-scheduling loop)
    │   └── pass:CustomPreSchedulingPasses:<name>   (one per pass, with meta)
    ├── sdsc_total                                  (per kernel; this workload emits one)
    │   ├── sdsc_bundle_gen                         (torch-side SDSC generation)
    │   └── dxp_standalone                          (external backend subprocess)
    └── async_compile_wait                          (essentially zero here)
```

Events outside `compile_fx_wrapper`:

```
device_init_and_transfer   input tensor .to("spyre") + Spyre runtime init
```

Recorded on each `pass:CustomPreSchedulingPasses:<name>` event:
`input_operations` (`len(graph.operations)` at pass entry),
`output_operations`, and `ops_delta = output_operations - input_operations`.

Recorded on `compile_fx_wrapper`: `fx_nodes_at_entry` (the FX node
count at the boundary where torch-spyre wraps `compile_fx`).

Recorded on `sdsc_bundle_gen`: `n_specs` (number of op specs handed
to the backend).

## What is NOT inside `compile_fx_wrapper`

- **Dynamo capture.** `compile_fx` receives an already-captured `gm`
  and `example_inputs`; Dynamo runs upstream.
- **First runtime execution.** The compiled artifact is executed
  after `compile_fx_wrapper` returns; `first_call_wall` covers that
  execution but `compile_fx_wrapper` does not.

## What each pipeline contains

The six Spyre custom-pass pipelines are documented in
`torch_spyre/_inductor/passes.py`. Their pass lists in the version
under test:

- `CustomPreGradPasses` — empty (extension point).
- `CustomPrePasses` — `[collect_spyre_hints]`.
- `CustomPostPasses` — `[recover_spyre_hints, decompose_addmm,
  mm_to_bmm_pass.apply, mark_direct_unit_bmm_pass,
  bmm_unflatten_pass.apply]`.
- `CustomPreFusionPasses` — `[propagate_mutation_layouts,
  align_lx_producer_loop_order, build_loop_scheduler_nodes]`.
- `CustomPostFusionPasses` — `[demote_incoherent_lx_buffers,
  spyre_fuse_nodes, hbm_pool_planning]`.
- `CustomPreSchedulingPasses` — 20 pass entries in order:
  `deadcode_elimination`, `propagate_named_dims`,
  `validate_named_dims`, `assign_dim_hints`,
  `_maybe_reorder_unhinted_interlopers`,
  `_maybe_coarse_tile_hints`, `split_multi_ops`,
  `propagate_spyre_tensor_layouts`, `validate_ops`,
  `optimize_restickify_locations`, `finalize_layouts`,
  `insert_restickify`, `enforce_indirect_access_layout`,
  `insert_post_mutation_restickify`, `insert_bmm_padding`,
  `dedup_and_promote_constants`, `_maybe_coarse_tile_span_overflow`,
  `span_reduction`, `_distribute_work`, `_maybe_scratchpad_planning`.
  `cost_model_pass` and `dump_cost_model` run after the timed loop
  and are not measured per-pass (cost model is disabled anyway; see
  `notes/resolved-config.md`).

## Boundaries staged but not measured in the current dataset

`patches/extra_timers.py` defines three additional class-level wraps
that are **not** applied to the runs under `data/`. They are:

- `torch._inductor.graph.GraphLowering.run` — upstream Inductor
  FX → IR lowering (records `n_fx_nodes`).
- `torch._inductor.graph.GraphLowering.compile_to_fn` — upstream
  Inductor codegen phase (records `n_operations`).
- `torch_spyre._inductor.spyre_kernel.SpyreKernel.codegen_kernel` —
  Spyre-specific per-kernel codegen invoked from `compile_to_fn`.

`patches/extra_timers-hook.patch` shows the two-line edit to
`torch_spyre/_inductor/__init__.py` that arms these wraps. Enabling
this hook produces validation runs (`data-validation/`) that
`patches/analyze_validation.py` uses to decompose the
`unattributed_compile_fx` bucket in Table A.

## Reconciliation identity

For every run, `compile_fx_wrapper.inclusive_ns` reconciles to the
sum of its direct children plus `self_ns`. The four Table A buckets
are computed from that identity:

```
compile_fx_wrapper
  = dxp_standalone                                        (external backend)
  + (sdsc_total - dxp_standalone)                         (sdsc_prep)
  + sum(pipeline:CustomPre*Passes, pipeline:CustomPost*Passes)  (Spyre pipelines)
  + async_compile_wait                                    (~0 for this workload)
  + unattributed_compile_fx                               (upstream Inductor / codegen / AOTAutograd)
```

`unattributed_compile_fx` is computed per run and then medianed.
