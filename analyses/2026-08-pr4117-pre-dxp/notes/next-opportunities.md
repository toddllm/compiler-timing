# Pre-DXP frontend — ranked opportunities under #4117

Baseline data from the final #4117 sweep (see `data/final_sweep/`,
`notes/pre-dxp-attribution.md`, `notes/tables/scaling.md`,
`notes/tables/pass-detail.md`). Frozen torch-spyre
`3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f` with `USE_SPYRE_CCL=0`
and `SPYRE_DUMP_COST` unset (cost model OFF for the primary
baseline).

## Ranking philosophy (unchanged from earlier)

Judgment across:

* absolute milliseconds at the largest measured shape
* share of pre-DXP time
* scaling in natural units (empirical scaling over this measured
  range; not algorithmic Big-O)
* future work-unit growth expectations
* attribution confidence (directly measured vs derived)
* practical lever availability
* correctness / review risk

Slope > 1 is a super-linear warning. Not a gate.

## Top absolute buckets at the three flash reference shapes

Small (`flash-256x1024`, `pre_dxp_total = 11 176 ms`)

* `compile_fx_outer_other` 5 562 ms (AOT / dynamo-side prelude — fixed cost)
* `spyre_inner_compile - graphlowering_compile_to_module` residual ≈ 411 ms
* `wrapper_module_exec` 1 607 ms (contains `sdsc_bundle_gen` 878 ms + `kernel_provenance` 141 ms)
* `custompresched_total` 1 949 ms (biggest passes: `optimize_restickify_locations` 500 ms, `_maybe_scratchpad_planning` 390 ms)

Middle (`flash-512x4096`, `pre_dxp_total = 65 581 ms`)

* `custompresched_total` 32 461 ms (49.5% of pre_dxp_total)
  * `_maybe_scratchpad_planning` **11 187 ms** (34.5% of custompresched, 17.1% of pre_dxp)
  * `optimize_restickify_locations` **11 691 ms** — Will's track
  * `span_reduction` 3 153 ms
* `wrapper_module_exec` 15 121 ms (`sdsc_bundle_gen` 8 568 ms, `kernel_provenance` 1 617 ms)
* `scheduler_codegen` 3 251 ms

Largest (`flash-1024x8192`, `pre_dxp_total = 515 021 ms`)

* `custompresched_total` **392 427 ms (76.2% of pre_dxp_total)**
  * `_maybe_scratchpad_planning` **215 121 ms (41.8% of pre_dxp_total)**
    * `scratchpad_solve` **202 477 ms** (94.1% of scratchpad_plan_allocation)
  * `optimize_restickify_locations` 138 354 ms (26.9%) — Will's track
  * `span_reduction` 12 709 ms
  * `_distribute_work` 9 193 ms
* `wrapper_module_exec` 61 159 ms (`sdsc_bundle_gen` 35 664 ms)
* `scheduler_codegen` 14 366 ms

## Empirical scaling over the flash range (n=9 shapes, log-log)

| bucket | slope | growth ratio |
|---|---:|---:|
| `pre_dxp_total` | 1.14 | 46× |
| `custompresched_total` | 1.48 | 201× |
| `_maybe_scratchpad_planning` (via `scratchpad_plan_allocation`) | 1.84 | 552× |
| `scratchpad_solve` (CP-SAT solver wall) | **2.11** | **1132×** |
| `optimize_restickify_locations` (via `custompresched_total` share) | ~1.5 | 277× (500 → 138 354 ms) |
| `sdsc_bundle_gen_total` | 1.02 | 41× |
| `scheduler_codegen` | 1.00 | 39× |
| `compile_fx_outer_other` | 0.31 | 2.5× (~fixed) |
| `pre_compile_fx` | 0.45 | 3.9× |
| `graphlowering_run` | 1.02 | 29× |
| `spyre_kernel_codegen_total` | 1.04 | 33× |
| `kernel_provenance_total` | 1.01 | 38× |

Read the slope column as an **empirical two-endpoint-plus-fit
exponent over this measured range**, not as an algorithmic Big-O
statement.

## Ranked opportunities

### 1. Current-default CP-SAT scratchpad solver cost

The dominant absolute cost at the largest flash shape:
`_maybe_scratchpad_planning = 215 121 ms = 41.8% of pre_dxp_total`,
of which `scratchpad_solve = 202 477 ms` is OR-Tools solver wall.

At `flash-512x8192` the CP-SAT solver reached `OPTIMAL` in
70.51 s wall (192 workers, 600 s time limit); at the largest shape
it took ~202 s wall. Empirical scaling exponent over the range
**2.11 on `scratchpad_solve` against planner buffers**. The CP-SAT
compile-time cost is real, super-linear over the measured range, and
already the largest single frontend bucket at scale.

**In scope for #4117** (per your correction):

* model-construction cost
* propagation cost
* work-count scaling
* avoiding unnecessary expensive solves
* size thresholds / small-graph fast paths
* fallback policies (e.g. switch to greedy when CP-SAT expected
  cost exceeds a threshold)
* solver configuration that reduces compile latency

**Separate solver-quality concern** (out of scope for #4117):

* residency objective redesign
* solution-quality optimization

Confidence: high (direct measurement, 9-shape trend, OR-Tools stats
already captured). Lever: yes (config-level fallback rule and/or
threshold-based fast path both look tractable). Risk: moderate;
changing the default solver would touch a lot of graphs, so a
threshold-and-fallback approach is likely safer than removing
CP-SAT.

**First concrete follow-up under #4117** — completed. See
`notes/adaptive-solver-followup.md` for the full write-up. Result:
apples-to-apples solver A/B with `SPYRE_LX_PLANNER_RELAYOUT=0`
shows CP-SAT and greedy produce byte-identical placement on the
measured shapes; CP-SAT's cost is 99% in `Solve()` with empirical
exponent ~2.45 in `planner_buffers`. A `n_operations > 800`
threshold with a `lx_planner_relayout=False` greedy fallback saves
29.8% of pre-DXP total on this 15-shape sweep (293.9 s of 987.1 s)
while keeping the emitted spec set identical to CP-SAT. No
torch-spyre source change yet — the prototype is an out-of-tree
monkey patch (`patches/adaptive_solver_prototype.py`).

### 2. `optimize_restickify_locations` (Will's track)

Second-largest absolute bucket at every large flash shape. At
`flash-1024x8192`: 138 354 ms = **26.9% of pre_dxp_total**.
Included here as context; Will owns.

### 3. `sdsc_bundle_gen`

`sdsc_bundle_gen_total` at `flash-1024x8192`: **35 664 ms (6.9% of
pre_dxp_total)**. Slope 1.02 vs `n_specs` — near-linear at
~8.7 ms/spec at the max shape. Not super-linear; not the highest
priority; but the absolute cost is material and any fixed per-spec
cost is worth checking (canonicalization / JSON emission /
copy paths).

Confidence: medium (linear scaling; per-spec cost is directly
readable). Lever: possibly small (per-spec cost reduction).

### 4. `span_reduction` inside CustomPreSchedulingPasses

At `flash-1024x8192`: 12 709 ms. Slope inferred from
`custompresched_total` minus scratchpad/restickify — grows near-
linearly. Non-restickify, non-solver bucket that would deserve
attention after (1) and (3) are addressed.

### 5. `scheduler_codegen` (upstream Inductor)

At `flash-1024x8192`: 14 366 ms. Slope 1.00 vs `sched_nodes`;
essentially linear at 3.5 ms per scheduler-node. Upstream
territory; a Spyre-side hook is not obvious.

### 6. `pre_compile_fx` and `compile_fx_outer_other` (fixed prelude)

Together `pre_compile_fx + compile_fx_outer_other ≈ 5 500 – 18 000 ms`
across the sweep. Slopes 0.45 and 0.31 — mostly fixed. Their
relative importance shrinks at scale but at small shapes
(`flash-256x1024`) `compile_fx_outer_other` is 5 562 ms ≈ 50% of
pre_dxp_total. Fixed startup cost, low urgency for large workloads.

## Explicit exclusions

* Anything past `dxp_standalone` — DXP itself is separate work.
* Restickify (`optimize_restickify_locations`,
  `insert_restickify_padding`, etc.) — Will's track.
* CP-SAT residency-objective redesign or solution-quality tuning —
  separate concern from the compile-time work in scope here.

## Incidental finding — bundle-generation nondeterminism

`generate_bundle` output is not byte-deterministic across
independent cold compiles on the frozen tree. Two identical
unmodified normal compiles at flash 512×1024 differ in
`bundle.mlir` bytes and several `sdsc_*.json` bytes; the
`KernelProvenanceDescriptor.key` also is not stable across runs.
Because the same divergence occurs between two unmodified observe
runs, byte equality cannot distinguish harness perturbation from
normal production variation. The mechanism is unattributed —
this study explicitly did NOT investigate it. Possible follow-up
as a separate torch-spyre issue.
