# Adaptive solver — first follow-up to #4117

**Frozen torch-spyre:**
`3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f` (same as the #4117
pre-DXP baseline; PR #4113 merge
`c073d69cceaac91d34b01dea6545048d0d645c2c` is an ancestor).

**Scope of this note:** the first concrete follow-up called for in
`notes/next-opportunities.md`: an adaptive `layout_solver` policy
that keeps CP-SAT for small graphs and falls back to greedy for
graphs where CP-SAT's cost dominates pre-DXP compile time. The four
in-scope questions are:

1. Apples-to-apples solver A/B under a matched planner-buffer
   universe (no relayout-induced asymmetry).
2. Where inside CP-SAT is the cost — build vs solve?
3. A prototype threshold policy and simulated per-shape effect.
4. Correctness of the two fallback flavors (relayout enabled vs
   disabled) at the shapes this study measured.

**Explicit exclusions:** DXP-side work; CP-SAT residency-objective
redesign; solution-quality tuning; any change beyond the frontend
allocator selection path.

**Data locations:**
- `data/cpsat_investigation/` — §1 + §2 evidence (4 flash shapes,
  cpsat and greedy each with `SPYRE_LX_PLANNER_RELAYOUT=0`).
- `data/threshold_data/arm_A_relayout_on/` — greedy at 15 shapes
  with `SPYRE_LX_PLANNER_RELAYOUT=1` (pod default).
- `data/threshold_data/arm_B_relayout_off/` — greedy at 15 shapes
  with `SPYRE_LX_PLANNER_RELAYOUT=0`.
- `data/final_sweep/primary/` — CP-SAT baseline, 15 shapes × 3
  cold samples each (from the #4117 study).
- `harness/compare_cpsat_investigation.py`, `harness/threshold_analysis.py`
  — analysis scripts.
- `patches/extra_timers.py` — the torch-spyre-side instrumentation
  used for CP-SAT phase decomposition and canonical planner-buffer
  signatures.
- `patches/adaptive_solver_prototype.py` — the out-of-tree adaptive
  policy monkey-patch (not a torch-spyre source change).

## §1 — Apples-to-apples solver A/B under RELAYOUT=0

The previous cpsat-vs-greedy A/B (`notes/tables/solver_comparison.md`)
ran with `SPYRE_LX_PLANNER_RELAYOUT=1`. Under that config
`_prepare_buffers` calls `collect_lx_relayout_plans(...)` for
solvers that advertise `supports_paired_buffers=True`.
`GreedyLayoutSolver.supports_paired_buffers = True`,
`CpSatLayoutSolver` inherits the base default `False`, so greedy
was actually seeing more `PlannerBuffer` entries (paired
LX-relayout buffers) than CP-SAT. The two solvers were not solving
the same problem.

Under `SPYRE_LX_PLANNER_RELAYOUT=0`, `collect_lx_relayout_plans`
returns `[]`, so the paired-buffer expansion drops out and both
solvers walk the same `_generate_buffers(graph)` path. This is the
only config under which "cpsat vs greedy" compares two solvers on
identical inputs.

I ran cpsat and greedy at flash 512×1024 / 2048 / 4096 / 8192 with
`SPYRE_LX_PLANNER_RELAYOUT=0`, `CO_OPTIMIZING_LX_PLANNING=0`,
`LX_PLANNING=1`, `SENCORES=32`, cold TORCHINDUCTOR cache. Each run
captured a canonical planner-buffer signature (name, size, uses,
`first_use_is_read`, `residency_reason`, `in_place_parents`,
`lifetime_end_override`, paired-with count, lx-relayout-plans count)
plus the final `placed_signature` and `spilled_signature`.
Signature hashes are sha256 over the buffer list sorted by name.

Result (from `data/cpsat_investigation/report.md`):

- Planner-buffer signature hashes are byte-identical between the
  cpsat and greedy arms at every shape:
    - flash-512x1024:  `3c25d56686e666a9`
    - flash-512x2048:  `df5997edb35c4774`
    - flash-512x4096:  `4a6c8184f7a25459`
    - flash-512x8192:  `3c45992b2a4e8d8a`
- Placement outcomes are byte-identical: same `placed_in_lx` count,
  same bytes, same `placed_signature`. Symmetric difference of the
  placed sets is `only_cpsat=0, only_greedy=0` at every shape.

**Conclusion:** on this workload family and range, once the paired-
buffer asymmetry is removed, CP-SAT and greedy pick the same
placement — every buffer, byte for byte. The previous
solver_ab_v2 differences (`n_specs 257 vs 273`, different
`bytes_placed_in_lx`) were caused entirely by the LX-relayout
paired-buffer expansion, not by solver decisions.

Wall-clock cost under RELAYOUT=0 (single cold sample each; only
CP-SAT's cost matters here — greedy solve is under 260 ms even at
flash-512x8192):

| shape           | cpsat scratchpad | greedy scratchpad | cpsat solve | greedy solve |
|-----------------|-----------------:|------------------:|------------:|-------------:|
| flash-512x1024  |          803 ms  |            464 ms |      344 ms |       4.2 ms |
| flash-512x2048  |         2693 ms  |           1138 ms |     1566 ms |      16.7 ms |
| flash-512x4096  |        10988 ms  |           2181 ms |     8903 ms |      64.6 ms |
| flash-512x8192  |        55250 ms  |           5444 ms |    50270 ms |     255.9 ms |

The whole scratchpad-planning cost differential between CP-SAT and
greedy is in `scratchpad_solve`. `_prepare_buffers` and
`_post_solve` are within 5% wall-clock between arms.

## §2 — CP-SAT internal cost decomposition

I instrumented `CpSatLayoutSolver._plan_layout_generic`,
`_add_inplace_relaxation`, `_add_core_division`,
`_add_no_overlap_2d`, `_run`, and `_extract` individually, and
wrapped every `cp_model.CpSolver.Solve()` call with its own timer
plus an `ortools_all_solves` record (status, wall time,
`num_branches`, `num_conflicts`, `num_booleans`,
`num_binary_propagations`, `num_integer_propagations`,
`num_restarts`, `num_workers`, `max_time_in_seconds`). I also
sampled deterministic model-size metrics after `_run` finishes
(`num_variables`, `num_constraints`, and — where available — the
extra `NoOverlap2D`/interval/proto-size counters). One sample per
shape at flash 512×1024/2048/4096/8192.

Result:

| shape          | plan_layout_generic | add_inplace | add_core_div | add_no_overlap_2d | solve[1] | extract |
|----------------|--------------------:|------------:|-------------:|------------------:|---------:|--------:|
| flash-512x1024 |             343.9   |         3.0 |          0.3 |               1.8 |    334.6 |     1.2 |
| flash-512x2048 |            1566.1   |         5.6 |          0.5 |               3.3 |   1548.0 |     3.5 |
| flash-512x4096 |            8902.3   |        11.2 |          1.1 |               6.7 |   8866.6 |     6.7 |
| flash-512x8192 |           50269.6   |        24.7 |          2.3 |              15.0 |  49952.0 |    20.3 |

Only one `Solve()` is invoked per plan (the initial optimization
succeeds); the two later `Solve()` calls hooked in `_run` never
fire in this scenario, so `solve[2]` and `solve[3]` are 0 ms.

`plan_layout_generic` is 99.4–99.9% the single `Solve()` call.
Every other measured phase (all `_add_*` model construction and
`_extract`) is <0.1% of the total at the largest shape.

Per-`Solve()` OR-Tools stats:

| shape          | status  | wall_s | branches | conflicts | booleans | bin_prop | int_prop | restarts |
|----------------|---------|-------:|---------:|----------:|---------:|---------:|---------:|---------:|
| flash-512x1024 | OPTIMAL |   0.33 |      134 |         0 |      303 |        0 |        0 |        0 |
| flash-512x2048 | OPTIMAL |   1.55 |       24 |         0 |      607 |        0 |        0 |        0 |
| flash-512x4096 | OPTIMAL |   8.86 |       30 |         0 |     1215 |        0 |        0 |        0 |
| flash-512x8192 | OPTIMAL |  49.95 |        6 |         0 |     2431 |        0 |        0 |        0 |

Notable: `num_conflicts=0` everywhere, `num_branches` decreases as
`planner_buffers` grows (134 → 24 → 30 → 6), `num_booleans` grows
linearly (0.15 booleans per planner-buffer). Search is doing very
little work; the cost is inside CP-SAT's presolve and propagation.
`bin_prop` and `int_prop` are 0 in these outputs — OR-Tools
counters are known to not always populate under all
`log_search_progress` combinations. The `NumBooleans` and
`NumBranches` counters are populated and consistent.

Model-size progression across the four shapes:

| shape          | planner_buffers | num_variables | num_constraints |
|----------------|----------------:|--------------:|----------------:|
| flash-512x1024 |             264 |           926 |            1229 |
| flash-512x2048 |             520 |          1830 |            2429 |
| flash-512x4096 |            1032 |          3638 |            4829 |
| flash-512x8192 |            2056 |          7254 |            9629 |

Empirical log-log slopes (over these four shapes only; not
extrapolatable):

| phase                            | slope vs planner_buffers |
|----------------------------------|-------------------------:|
| plan_layout_generic (whole thing)|                     2.44 |
| solve[1]                         |                     2.45 |
| add_inplace                      |                     1.02 |
| add_core_div                     |                     1.03 |
| add_no_overlap_2d                |                     1.03 |
| extract                          |                     1.33 |
| num_variables                    |                     1.00 |
| num_constraints                  |                     1.00 |

**Conclusion:** the CP-SAT cost is 99% in `Solve()`. Model
construction and extraction scale linearly with
buffer count. `Solve()` grows with empirical exponent ~2.45 in
buffer count on this shape family. The branch counts are small and
declining; the conflict counter is 0. That means the cost lives in
presolve + constraint propagation, not branch-and-bound search.

## §3 — Prototype threshold policy

The prototype is an out-of-tree monkey patch installed by the
harness (`patches/adaptive_solver_prototype.py`), NOT a torch-spyre
source change. Env-controlled: `ADAPTIVE_SOLVER_ENABLE=1`,
`ADAPTIVE_SOLVER_THRESHOLD_OPS` (default 512),
`ADAPTIVE_SOLVER_FALLBACK_RELAYOUT` (`0`, `1`, or `as-is`).

Policy shape:

```
if configured layout_solver != 'cpsat':      keep configured solver
elif n_ops <= threshold:                     use cpsat
else:                                        use greedy fallback
```

Solver-independent pre-solve size metric is `len(graph.operations)`
at the entry to `scratchpad_planning`. That value is available
before any solver-specific `_prepare_buffers` runs, and it is
recorded in `scratchpad_planning_entry` for downstream analysis.
Planner-buffer count is not used — CP-SAT and greedy would build
different `planner_buffers` counts if paired-buffer support
diverged, and picking a solver based on a solver-dependent metric
would be circular.

The fallback greedy allocator is built via the existing
`select_allocator()` path with `config.layout_solver` temporarily
pinned to `greedy`; if `ADAPTIVE_SOLVER_FALLBACK_RELAYOUT=0`,
`config.lx_planner_relayout` is also pinned `False` for the
duration.

## §4 — Threshold sweep

Per-shape effect (from `notes/tables/threshold_analysis.md`):

| shape          | n_ops | cpsat pre_dxp | greedyA pre_dxp | greedyB pre_dxp |
|----------------|------:|--------------:|----------------:|----------------:|
| mlp-L2-w2048   |     6 |          3.8s |           11.8s |           12.0s |
| mlp-L4-w2048   |    12 |          4.1s |            8.1s |            6.8s |
| mlp-L8-w2048   |    24 |          4.7s |            7.9s |            7.5s |
| mlp-L16-w2048  |    48 |          5.0s |            9.0s |            7.1s |
| mlp-L32-w2048  |    96 |          6.0s |            8.8s |            8.6s |
| flash-256x1024 |   110 |         11.2s |           14.9s |           11.9s |
| flash-512x512  |   132 |         11.3s |           12.0s |           12.8s |
| mlp-L64-w2048  |   192 |          8.5s |           11.7s |           11.7s |
| flash-512x1024 |   260 |         17.8s |           16.1s |           25.3s |
| flash-1024x1024|   516 |         31.5s |           30.6s |           32.2s |
| flash-512x2048 |   516 |         31.2s |           29.1s |           42.3s |
| flash-2048x1024|  1028 |         71.1s |           63.6s |           59.2s |
| flash-512x4096 |  1028 |         65.6s |           61.4s |           58.2s |
| flash-512x8192 |  2052 |        200.3s |          137.2s |          125.3s |
| flash-1024x8192|  4100 |        515.0s |          333.3s |          315.4s |

Simulated total compile time under the policy `use greedy fallback
when n_ops > T` across all 15 shapes:

| threshold_n_ops | baseline_total | armA_total | armA_savings | armA_switched | armB_total | armB_savings | armB_switched |
|----------------:|---------------:|-----------:|-------------:|--------------:|-----------:|-------------:|--------------:|
|               0 |         987.1s |     755.6s |  231.5 (23.5%)|         15/15 |     736.4s |  250.7 (25.4%)|         15/15 |
|             100 |         987.1s |     733.6s |  253.5 (25.7%)|         10/15 |     718.0s |  269.2 (27.3%)|         10/15 |
|             200 |         987.1s |     725.9s |  261.2 (26.5%)|          7/15 |     712.5s |  274.7 (27.8%)|          7/15 |
|             300 |         987.1s |     727.6s |  259.5 (26.3%)|          6/15 |     705.0s |  282.1 (28.6%)|          6/15 |
|             500 |         987.1s |     727.6s |  259.5 (26.3%)|          6/15 |     705.0s |  282.1 (28.6%)|          6/15 |
|             800 |         987.1s |     730.6s |  256.5 (26.0%)|          4/15 |     693.2s |  293.9 (29.8%)|          4/15 |
|            1200 |         987.1s |     742.3s |  244.8 (24.8%)|          2/15 |     712.4s |  274.7 (27.8%)|          2/15 |
|            2000 |         987.1s |     742.3s |  244.8 (24.8%)|          2/15 |     712.4s |  274.7 (27.8%)|          2/15 |
|            3000 |         987.1s |     805.5s |  181.7 (18.4%)|          1/15 |     787.5s |  199.7 (20.2%)|          1/15 |

## §5 — Fallback flavor: A vs B

Same greedy solver, only difference is
`SPYRE_LX_PLANNER_RELAYOUT` during the fallback compile.

**Arm A (`RELAYOUT=1` — greedy's normal behavior).**
Since greedy declares `supports_paired_buffers=True` and
`config.lx_planner_relayout=True`, the greedy fallback sees an
expanded `PlannerBuffer` universe (paired LX-relayout buffers).
Downstream effects at every flash shape:
`n_specs` grows by 8/16/32/64/128/256 depending on shape, and the
placed set grows by the same count (16/shape family) versus what
CP-SAT produced. Placed-set symmetric difference is
`only_cpsat=0, only_greedy=<multiple-of-16>, agreed=<baseline>`
for every flash shape. Falling back to arm A therefore changes
the compile output — it's semantically not the same result the
CP-SAT arm would have produced; it's what greedy always would
have produced. MLP shapes have `n_specs` identical between arms
(no LX-relayout on those graphs).

**Arm B (`RELAYOUT=0` — solver-only fallback).**
Greedy sees the exact same `PlannerBuffer` universe as CP-SAT
would have seen. `n_specs` matches CP-SAT byte-for-byte on every
shape. Placed-set symmetric difference is `only_cpsat=0,
only_greedy=0, agreed=<baseline>` on every shape. The compile
output is the same one CP-SAT would have produced, just cheaper
to derive.

**Recommendation on flavor:** arm B. Arm A doesn't just cost more
than arm B in wall-clock at the largest shapes (315s vs 333s at
flash-1024x8192) — it also alters the emitted spec set. Arm B is
the fallback flavor that keeps downstream identical to CP-SAT.

At small shapes, greedy pre-DXP is often *longer* than CP-SAT (see
`mlp-L2-w2048` — 3.8s cpsat vs 12.0s greedy). This is not a
scratchpad-planning cost — the scratchpad pass itself is a few
tens of ms — it's other fixed startup varying between the runs.
It disappears at any threshold that keeps small shapes on CP-SAT
(T ≥ ~100).

**Recommended threshold and metric.**
Metric: `len(graph.operations)` at the entry to `scratchpad_planning`.
Range: **200–800** operations. Threshold=800 arm B gives the
largest total savings on this workload family (29.8% of pre-DXP,
293.9 s absolute over 15 shapes); threshold=300–500 arm B is
within 1.2 percentage points and switches slightly more shapes.
On its own this workload set does not decide 300 vs 500 vs 800;
all four flash shapes ≥ 1028 ops are switched by any threshold
in that range and account for 289 s of the 294 s savings.

## Estimated pre-DXP improvement on the #4117 baseline

Using arm B and threshold=800, per the simulation:
- Total pre-DXP across the 15-shape sweep: 987.1s → 693.2s.
- Absolute savings: **293.9s (~29.8%)**.
- Shapes switched: 4 of 15 (flash-2048x1024, flash-512x4096,
  flash-512x8192, flash-1024x8192).
- Largest per-shape saving: flash-1024x8192, 515.0s → 315.4s,
  199.6s absolute (–38.8% pre-DXP for that shape).

The comparable arm A number is 26.0% savings but with the
`n_specs` drift documented above, which is why arm B is the
recommended flavor.

## Correctness and behavior risks

- **Solver quality on flash shapes ≥ 512 ops.** §1 shows cpsat
  and greedy produce byte-identical placement (and byte-identical
  emitted spec sets under arm B) at every measured shape. This is
  strong evidence for the specific shape ranges here, but this
  study measured 15 shapes: 9 flash points and 6 MLP depths. It
  is not a proof over all workloads. The prototype is
  env-guarded and defaults off; any production wiring would need
  to reproduce a similar signature-match check on the target
  workload family, or hold a small tail of large-shape regression
  cases.
- **CP-SAT residency objective is not exercised here.** The
  objective for these problems is dominated by "everything fits";
  every CP-SAT run in this study terminated `OPTIMAL` in a single
  `Solve()`. Workloads that stress the residency objective or
  spill decisions could see greedy make different (worse)
  choices. This study does not evaluate that.
- **`num_conflicts=0` is a workload observation, not a guarantee.**
  Other CP-SAT problems in the same code path may be harder;
  their absolute cost could still be worse than greedy's, but the
  ratio may differ.
- **Fallback config toggle changes global state briefly.** The
  prototype temporarily flips `_c.layout_solver` and
  `_c.lx_planner_relayout` around `select_allocator()`, restoring
  in `finally`. That's safe within one thread of compilation; if
  the code path grows concurrency later, this would need
  revisiting.
- **`scratchpad_planning_entry` timing event.** Introduces a
  thin wrapper around `scratchpad_planning`. In the prototype
  it's out-of-tree; in production wiring the equivalent
  attribution point already exists as `select_allocator` /
  `pipeline:CustomPreSchedulingPasses`.
- **Bundle-generation nondeterminism (incidental).** `n_specs`
  and placed sets match byte-for-byte between arm B and CP-SAT in
  these numbers, but two independent cold compiles of the same
  configuration produce `bundle.mlir` byte differences at every
  shape (documented in `notes/next-opportunities.md`). Byte
  equality of `bundle.mlir` cannot be used as a regression gate;
  the correct gates are structural (`n_specs`, placed_signature,
  placed bytes).

## Recommendation on next steps

- Do not open a torch-spyre production PR from this study.
- Re-run the arm-B signature match on additional workloads
  (e.g. inference graphs for a target model family) before
  wiring this into torch-spyre `select_allocator`. Same
  methodology: `SPYRE_LX_PLANNER_RELAYOUT=0`, canonical
  planner-buffer signature match, placed-set equality.
- If those pass, a minimal production wiring would be:
  - `config.adaptive_solver_threshold_ops: int | None = None`
    (None = off, existing behavior).
  - In `scratchpad_planning`, when the configured solver is
    cpsat and the threshold is a positive int and
    `len(graph.operations) > threshold`, temporarily construct a
    greedy allocator with `lx_planner_relayout=False` for that
    plan. Restore config in `finally`.
  - Log the decision (configured / chosen / n_operations /
    threshold) at INFO for observability.
  - Default remains off; enable it explicitly in the CI /
    production configuration once a broader workload sweep
    replicates the signature match.

## Out-of-scope items (unchanged)

- DXP itself and anything after `subprocess.run(["dxp_standalone",
  ...])`.
- CP-SAT residency-objective redesign.
- Solution-quality tuning of the greedy solver.
- Restickify passes (Will's track).
- `sdsc_bundle_gen` per-spec cost (separate follow-up in
  `next-opportunities.md`).

## Reproduction

Frozen torch-spyre `3358f39` on
`tdeshane-compiler-timing-dev-v2`. From this directory:

```bash
# §1 + §2: apples-to-apples solver A/B and CP-SAT phase decomposition
bash harness/cpsat_investigation.sh
python3 harness/compare_cpsat_investigation.py \
    --data-dir data/cpsat_investigation \
    --out data/cpsat_investigation/report.md

# §3 + §4 + §5: threshold prototype data collection and analysis
bash harness/threshold_data_collection.sh
python3 harness/threshold_analysis.py \
    --baseline-dir data/final_sweep/primary \
    --greedy-a-dir data/threshold_data/arm_A_relayout_on \
    --greedy-b-dir data/threshold_data/arm_B_relayout_off \
    --out notes/tables/threshold_analysis.md
```

Cache directory (`TORCHINDUCTOR_CACHE_DIR`) is set per-run in each
script to force cold compiles.
