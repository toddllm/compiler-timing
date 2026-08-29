# Pre-DXP frontend investigation — summary

**Epic:** torch-spyre #4117 — investigate remaining pre-DXP compile
time outside `CustomPreSchedulingPasses`.

**Frozen torch-spyre baseline:**
`3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f`
(upstream/main at study start; verified to contain PR #4113 merge
`c073d69cceaac91d34b01dea6545048d0d645c2c` as an ancestor via
`git merge-base --is-ancestor`).

**Scope:** cold `torch.compile()` path through generation of backend
input, stopping immediately before `subprocess.run(["dxp_standalone",
...])` in `torch_spyre/execution/async_compile.py:155`. DXP itself is
out of scope.

## Question

> Once known pass-level costs are accounted for, where does the rest
> of pre-DXP compile time go, how does each bucket scale with graph
> size, and which remaining bucket is the next material optimization
> target?

## Framework corrections applied (pre-data)

The framework was corrected before any data was collected. The
correction commit landed as a separate signed commit; nothing about
the pilot or full sweep has yet been executed on a pod.

- **Source basis frozen.** The instrumentation applier refuses to
  operate on any tree that is not exactly the frozen SHA and clean.
  `git apply --check` is required before any file is written.
- **CustomPreSchedulingPasses is 23 passes**, not 20 or 22 as the
  earlier draft claimed. The `__call__` also runs
  `cost_model_pass`, `dump_cost_model`, and
  `finalize_work_division_for_scheduler` after the loop; the whole
  method is now bracketed and the four sub-regions are timed
  separately.
- **SDSC is NOT nested inside `compile_fx_wrapper` or
  `compile_to_fn`.** It fires during first invocation of the compiled
  wrapper. The analyzer never subtracts `sdsc_total` from those
  parents.
- **Primary `pre_dxp_total`** is `pre_dxp_boundary_marker.t_start −
  first_call_wall.t_start`. The sentinel unwind is reported
  separately.
- **Neutral bucket names.** `pre_compile_fx`,
  `compile_to_fn_other`, `spyre_update_scheduler_other`, etc. No
  "dynamo_aot_prelude" and no directly-named Scheduler bucket unless
  it is directly bracketed.
- **Direct timers.** `Scheduler.__init__`, `Scheduler.codegen`,
  `PythonWrapperCodegen.generate`, `GraphLowering.codegen`, plus
  `recover_spyre_hints` and the pre-scheduling sub-regions — all
  measured, not derived.
- **Hard reconciliation validation.** Every run is asserted to have
  reached the boundary with the correct captured cmd, all required
  events present, children ≤ parent inclusive. Derived buckets that
  come out negative fail the run rather than being silently clamped.
  Runs with |residual| > 1% of `pre_dxp_total` are marked invalid
  and excluded from aggregates.
- **Fidelity check** compares PRE-DXP catalogs from paired
  `--mode=observe` and `--mode=stop` runs, catalogued at the exact
  DXP call site before subprocess.run. Kernels paired by output_dir
  basename, not sorted index.
- **Layer-scaled MLP.** Fixed moderate width (`N_hidden=2048`),
  sweep layers ∈ {2, 4, 8, 16, 32, 64}. Independent variable is
  graph-node growth, not tensor dimension.
- **Opportunity ranking is judgment**, not an AND-gate. Absolute
  ms, share, per-natural-unit drift, future work-unit growth,
  attribution confidence, lever availability, and correctness risk
  all weigh. Slope > 1 is a warning, not a gate.

## What we built (on laptop, ready for pod)

- **Stage map** (`notes/pre-dxp-stage-map.md`) — every source-level
  stage between `torch.compile()` and `dxp_standalone`, with
  file:line at the frozen SHA. Explicitly enumerates 23 passes and
  the three post-loop calls.
- **Frontend-only harness** (`harness/pre_dxp_stop.py`) — modes
  `stop`, `observe`, `passthrough`. Catalogs the bundle at the DXP
  call site; raises `_PreDxpBoundary` sentinel in stop mode.
- **Bundle fidelity check** (`harness/check_bundle_fidelity.py`) —
  paired observe+stop, byte-for-byte diff of pre-DXP catalogs.
- **Hierarchical instrumentation** (`patches/instrumentation.patch`,
  `patches/timing_recorder.py`, `patches/extra_timers.py`) —
  bracketed directly at 25+ points including the three
  post-loop pre-scheduling stages and the upstream Scheduler
  boundaries.
- **Applier** (`patches/apply_instrumentation.sh`) — refuses on
  wrong SHA, dirty tree, or fuzzy patch application.
- **Pilot driver** (`harness/pilot_driver.sh`) — 5 shapes × 1 sample.
- **Sweep driver** (`harness/sweep_driver.sh`) — 9 flash points + 6
  layer-scaled MLP points × 3 samples, serial.
- **Analyzer** (`harness/analyze_sweep.py`) — hierarchical event-tree
  based accounting, reconciliation validation, natural-unit
  scaling.

## Preflight status

- Applier: dry-run pass, dirty-tree/wrong-SHA rejection tested.
- Analyzer: synthetic-run smoke-test with realistic hierarchy —
  reconciliation 0.00% residual, all 23 passes visible in top-K,
  bucket accounting closed by construction.
- Instrumentation patch: `git apply --check` passes at the frozen
  SHA; every instrumented file py_compiles.
- Fidelity check: rewritten to compare PRE-DXP catalogs, not
  POST-DXP directory listings.

**Not yet executed:** the pilot or full sweep on a pod.

## Runbook (see `README.md`)

1. Freeze torch-spyre at the SHA above.
2. `bash patches/apply_instrumentation.sh`.
3. Fidelity check at `flash 512x1024`.
4. Pilot: 5 shapes × 1 sample. Inspect event tree, confirm nesting.
5. Full sweep: 9 flash + 6 MLP × 3 samples.
6. Analyzer regenerates all deliverables.

## Findings

*(To be filled in from real data after §10 pilot + §11 sweep pass on
the pod. The current commit contains framework corrections only.)*
