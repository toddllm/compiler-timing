# Compiler stage / change-surface map

For each source area of `torch-spyre`, this file lists:

- **Stage**: which compiler stage/pass the code implements.
- **Measured role**: how much of the timed frontend it represented
  in the two committed studies.
- **Triage rule**: how a change touching this area should be
  classified.
- **Default level**: recommended device-time level.

`t_pass @ (workload, point)` cites medians from the primary studies.

## Boundaries and stages

```
compile_fx_wrapper (100% by definition of the timed region)
├── GraphLowering.run                  (upstream Inductor: FX → IR)
├── GraphLowering.codegen              (upstream + Spyre pass pipelines + kernel codegen + wrapper)
│   ├── pipeline:CustomPreGradPasses
│   ├── pipeline:CustomPrePasses
│   ├── pipeline:CustomPostPasses
│   ├── pipeline:CustomPreFusionPasses
│   ├── pipeline:CustomPostFusionPasses
│   └── pipeline:CustomPreSchedulingPasses  ← 20 ordered passes; dominant
├── SpyreKernel.codegen_kernel         (per-kernel; <1% measured)
├── sdsc_total  = sdsc_bundle_gen + dxp_standalone
└── async_compile_wait                 (~0)
```

Anything not enclosed by the above but inside `compile_fx_wrapper`
counts as **upstream/setup component** (AOTAutograd, `torch.compile`
plumbing). Measured 6–11 s at all four points sampled — sublinear.

## Per-file / per-directory rules

### `torch_spyre/_inductor/dedup_constants.py`

- **Stage**: pre-scheduling pass — `dedup_and_promote_constants`.
- **Measured role**:
  - Workload A: `t ≈ 202 µs × (ops × dups)`. At 1024×8192 (b=128,
    preliminary n=1) = 225 s.
  - Workload B: `t ≈ 931 µs × (ops × dups)` — same shape, 4.6× larger
    constant. At n=16 = 10 s.
- **Triage rule**: any change to `_redirect_consumers`, `_drop_constant`,
  or the outer loop over duplicate groups → Level ≥1. Structural
  refactors that don't touch the loop body → Level 1.
- **Reverse-adjacency prototype** for the same class of mechanism
  was measured on coarse tiling (not dedup) and moved 4→8 growth ratio
  from 3.52× to 2.80×. Estimated dedup gain: similar shape.

### `torch_spyre/_inductor/wsr/coarse_tile.py`

- **Stage**: `_maybe_coarse_tile_hints` and its downstream substages
  (`plan_coarse_tile_groups`, `_plan_tiling_propagation`,
  `_apply_plan`, `_plan_read_copies`, `_insert_all_read_copy_ops`,
  `_insert_all_reduction_ops`, `_insert_all_write_copy_ops`, the
  resync-and-patch tail with `_patch_retiled_load_indexes`,
  `_log_propagation_self_check`, `validate_writer/reader_tile_advance`).
- **Measured role** (workload B, `_maybe_coarse_tile_hints`):
  - n=2: 1.47 s.
  - n=4: 4.11 s (2.80× per doubling from n=2).
  - n=8: 14.46 s (3.52×).
  - n=16: 53.13 s (3.67×).
  - At n=8, `resync_and_patch_load_indexes` = 74.5%,
    `_plan_tiling_propagation` = 22.1%.
- **Triage rule**:
  - Change to `_find_outside_consumers_planned`, `_reads_buffer`,
    `_patch_retiled_load_indexes`, `_should_patch_retiled_load_indexes`,
    or `_plan_tiling_propagation` → Level ≥1 on WB_scaling_pair.
    Level 3 if the change claims to alter complexity.
  - Change to `hints_to_coarse_tile_groups`, `validate_coarse_tile_groups`,
    or `_apply_plan` → Level 1 on WB_n4 (these substages are cheap).
  - Change to insert_all_* substages → Level 1; measured to shrink
    with chunk count in workload B, so unlikely to be a hotspot.
- **The reverse-adjacency prototype is committed** at
  `analyses/2026-08-frontend-scaling-cross-workload/patches/coarse_tile_reverse_adj.py`.
  For any change here, run the sweep both with and without the
  prototype to see if the new work stacks or conflicts.

### `torch_spyre/_inductor/wsr/coarse_tile_hints.py`

- **Stage**: `_maybe_reorder_unhinted_interlopers`,
  `hints_to_coarse_tile_groups`, plus the coarse-tile hint utilities.
- **Measured role**: `_maybe_reorder_unhinted_interlopers` = 0–1 ms
  at every measured point despite its explicit `O(n²)` docstring.
- **Triage rule**: Level 0 by default — measured negligible. Escalate
  to Level 1 only if the change is claimed to add a new pass in this
  file that runs on the hot path.

### `torch_spyre/_inductor/optimize_restickify.py`

- **Stage**: `optimize_restickify_locations` — global beam-search
  layout selection.
- **Measured role**:
  - Pre-#3812 workload B at n_chunks≥7: **crashes** with `buf112 no
    mechanism` (issue #3687), needs `BEAM_WIDTH ≥ 400×2^(n−7)`.
    Post-#3812: 2.3 s at n=8, 5.6 s at n=16, 2.2–2.4× per doubling.
  - Workload A: sublinear.
- **Triage rule**:
  - Any change to `BEAM_WIDTH`, `Frontier`, `BeamState`,
    liveness merge, or the per-op state expansion → Level ≥1 on
    WB_n4 or WB_n8 (state-space sensitive workload).
  - Any change to candidate-generation (`op.layouts` list contents)
    is a state-space multiplier — Level 2 with the beam-counter
    patch to record `n_candidates` per op.
  - Any change that removes/adds candidates for constant-fill ops is
    subject to the diamond-multiplication mechanism identified by
    issue #3687; verify pre-fix reproduces buf112 before and
    post-change does not.

### `torch_spyre/_inductor/propagate_layouts.py`

- **Stage**: `propagate_spyre_tensor_layouts` (pre-scheduling pass).
- **Measured role**: sublinear on both workloads. Workload A:
  0.29 → 10.1 s across 32× graph range. Workload B: 0.29 s at n=2
  to 1.93 s at n=16.
- **Triage rule**: Level 1 targeted. If change alters `op.layouts`
  content (candidate set), promote to Level 2 with beam counters
  because restickify may be sensitive.

### `torch_spyre/_inductor/propagate_hints.py` and `wsr/propagate_named_dims.py`

- **Stage**: named-dim/hint propagation.
- **Measured role**: `span_reduction` and named-dim propagation are
  in the near-linear "other passes" bucket. Small.
- **Triage rule**: Level 1.

### `torch_spyre/_inductor/insert_restickify.py`

- **Stage**: `insert_restickify` pass — inserts restickify ops based
  on the layout decisions from `optimize_restickify_locations`.
- **Measured role**: bundled in "other Spyre passes" — small.
- **Triage rule**: Level 1. Static-audit flagged
  `operations.index(op)` in this file as an O(N)-per-splice pattern;
  changes that alter the splice count are relevant.

### `torch_spyre/_inductor/scratchpad/allocator.py` and siblings

- **Stage**: `_maybe_scratchpad_planning` — LX scratchpad address
  assignment.
- **Measured role**:
  - Workload B: 0.3 → 1.9 s across n=2 to n=16. Approximately linear.
  - Workload A: 0.4 s → 74 s across 32× graph range (b=4 to b=128).
    Superlinear (`n^~1.45`).
- **Triage rule**:
  - **The root cause of the workload-A superlinear behavior is
    UNRESOLVED.** The `_extern_kernel_in_live_range` prefix-sum
    hypothesis was prototyped and measured null (1–2% within noise).
    Do NOT reason from source structure alone here.
  - Level 0 for changes to validation/guard paths, docstrings,
    assertions.
  - Level 1 targeted for changes on the plausible hot path (e.g.
    `plan_allocation` main loop, `LifetimeBoundBuffer` construction).
  - Level 3 only if the change claims to alter the solver algorithm.
  - Solver-file changes (`greedy_solver.py`, `firstfit_bestfit_solver.py`,
    `simulated_annealing.py`, `ilp_solver_ortools.py`,
    `exhaustive_search.py`, `plan_solver.py`) affect only their own
    code path; determine which solver the current default `cost_model=""`
    config selects before assigning workload impact.

### `torch_spyre/_inductor/fusion.py`, `scheduler.py`, `work_division.py`

- **Stage**: `spyre_fuse_nodes`, scheduler nodes, `_distribute_work`.
- **Measured role**: `_distribute_work` at 0.14 → 0.88 s in workload B
  (near-linear). Small share.
- **Triage rule**: Level 1 targeted.

### `torch_spyre/_inductor/enforce_indirect_access_layout.py`, `split_multi_ops.py`, `deadcode_elimination.py`

- **Stage**: pre-scheduling passes, "other" bucket.
- **Measured role**: linear, small.
- **Triage rule**: Level 1 targeted.

### `torch_spyre/_inductor/spyre_kernel.py`

- **Stage**: `SpyreKernel.codegen_kernel`.
- **Measured role**: <1% of `compile_fx` at every measured point.
- **Triage rule**: Level 0 for local kernel-code emission changes.
  Level 1 if the change plausibly alters kernel count.

### `torch_spyre/_inductor/lowering.py`, `decompositions.py`

- **Stage**: AOTAutograd-facing decomposition table, IR lowering.
  This runs INSIDE the `GraphLowering.run` timer we added.
- **Measured role**: `GraphLowering.run` = 100–650 ms across all
  measured points. Small.
- **Triage rule**: Level 1 targeted. Note that decomposition changes
  can shift work into passes downstream — check pre-scheduling times
  as well as `graphlowering_run`.

### `torch_spyre/_inductor/__init__.py` and `patches.py`

- **Stage**: compile_fx wrapper wiring, decomp-table hook.
- **Measured role**: encompasses part of the 6–11 s upstream/setup
  component, but this bucket is upstream Inductor + `torch.compile`
  overhead, not Spyre-owned.
- **Triage rule**: Level 1 for wrapper changes; do not conflate with
  Spyre-owned frontend movement.

### `torch_spyre/csrc/**` (C++ extension)

- **Stage**: `_C.so` — device metadata, layout math, kernel binding.
- **Measured role**: not separately timed. Some `compile_fx` cost is
  paid here via C++ calls the Spyre passes make.
- **Triage rule**: Level ≥1 with a **rebuild per revision**.
  In-process patching does not work for C-extension changes. Note
  explicitly in `02-experiment-plan.md` that both `base` and `head`
  checkouts must be rebuilt with `pip install -e .` before timing.

### `torch_spyre/execution/async_compile.py`

- **Stage**: `sdsc()` and the `dxp_standalone` subprocess handoff.
- **Measured role**: `sdsc_total` = 11 s at workload B n=2, up to
  2400 s at largest workload A points. Backend-dominated.
- **Triage rule**: Frontend impact only if the change alters the
  bundle content, SDSC prep, or the handoff itself. If it only
  changes `dxp_standalone` subprocess management, classify as
  **backend impact only**.

### `torch_spyre/_inductor/codegen/bundle.py`

- **Stage**: SDSC bundle emission (`sdsc_bundle_gen`).
- **Measured role**: 0.5 s at WB_n4, 1.1 s at WB_n8. Small in
  absolute terms compared to `dxp_standalone`, but on the timed
  path for every compile.
- **Triage rule**: Level ≥1. This file sits at the frontend/backend
  boundary — changes here can move `sdsc_bundle_gen` independently
  of every Spyre `pipeline:*`. Two mechanisms to check:
  1. **Bundle-emission time** — added per-op work will show up in
     `sdsc_bundle_gen` even without any pass moving. PR #3868's
     canonical-compile + `json.dumps(sort_keys=True)` added +65% at
     WB_n4 with no Spyre pass changed.
  2. **Bundle content** — a change to what the bundle carries can
     shift `dxp_standalone` substantially. Verify by comparing
     head vs base `n_specs` at `sdsc_bundle_gen.meta`. If
     `n_specs` unchanged and `dxp_standalone` moves, the bundle
     representation (not the count) changed.
- **Verdict guidance**: when `sdsc_bundle_gen` moves but Spyre passes
  don't, use the "sdsc_bundle_gen moved but no Spyre pass did"
  clause in `interpretation-guide.md`.

### `torch_spyre/runtime/` and other execution-time code

- **Stage**: runtime (post-compile).
- **Triage rule**: Level 0 for compile-time impact. May be Level ≥1
  for runtime, which is out of this skill's scope.

### `tests/**`

- **Triage rule**: Level 0 unless the change modifies a helper that
  is imported by non-test code.

### `docs/**`, `.github/**`, `.pre-commit-config*`, `.gitignore`, `README*`, `*.md`

- **Triage rule**: Level 0.

## The three questions rule

For a change to escalate above Level 1 targeted, all three must be YES:

1. **Does the changed code execute on the timed compile path** in a
   sentinel workload? (If gated: what activates the gate?)
2. **Is the change on the hot inner loop** of the pass, or on
   setup/validation/error paths?
3. **Does the change alter the collections/constants** that made the
   pattern superlinear, or is it a local edit that preserves the
   algorithm?

If any answer is NO, cap at Level 1.

## Known refuted hypotheses

Record these to avoid re-litigating:

- **`_extern_kernel_in_live_range` prefix-sum** is not the driver of
  workload A's n^1.45 scratchpad scaling. Measured 1–2% within
  noise. Preserved as a low-leverage micro-optimization only.
- **Naïve global `op_read_writes` memoization** for `_reads_buffer`
  breaks correctness (`buf31` not found) because the cache crosses
  mutation boundaries in the coarse-tile pipeline. The correct
  approach is per-substage indexes; the prototype at
  `patches/coarse_tile_reverse_adj.py` implements this safely.
- **`_maybe_reorder_unhinted_interlopers`'s explicit O(n²)** is
  empirically negligible (0.3–1 ms) at every measured point.
- **`insert_all_read_copy_ops`'s `name_to_op` rebuild-per-entry**
  was flagged by static audit but measured to shrink with chunk
  count on workload B — not a hotspot.
