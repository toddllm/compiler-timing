# Interpretation guide

How to read a base/head measurement and pick one of the seven
verdicts.

## Metrics to collect

For every timed sample, extract from the JSON at least:

- `first_call_wall`
- `compile_fx_wrapper`
- `pipeline:CustomPreGradPasses` … `pipeline:CustomPreSchedulingPasses`
  (six pipelines; sum them for `Spyre pipes total`)
- `pass:CustomPreSchedulingPasses:_maybe_coarse_tile_hints`
- `pass:CustomPreSchedulingPasses:dedup_and_promote_constants`
- `pass:CustomPreSchedulingPasses:optimize_restickify_locations`
- `pass:CustomPreSchedulingPasses:_maybe_scratchpad_planning`
- `pass:CustomPreSchedulingPasses:propagate_spyre_tensor_layouts`
- `pass:CustomPreSchedulingPasses:_distribute_work`
- `sdsc_total`, `sdsc_bundle_gen`, `dxp_standalone`
- `async_compile_wait` (usually ≈ 0)
- Individual passes touched by the change (if any)

### Boundary metrics — treat separately from Spyre pipelines

`sdsc_bundle_gen` sits at the frontend/backend boundary. It emits the
compiled bundle that gets handed to `dxp_standalone`. It can move
independently of every Spyre pass pipeline — the PR #3868 validation
case saw `sdsc_bundle_gen` regress +65% while every `pipeline:*` was
flat within ±2%. Keep `sdsc_bundle_gen` on its own row in every
result table. Never bucket it under "Spyre pipes total".

Similarly, `dxp_standalone` is not a frontend pass — but a change to
what `sdsc_bundle_gen` emits can shift `dxp_standalone` substantially
without any pass moving. Record both, and interpret their joint
movement using the `n_specs` and bundle-representation checks
described below.

Also structural counters:

- `event['compile_fx_wrapper'].meta.fx_nodes_at_entry`
- `event['sdsc_bundle_gen'].meta.n_specs`
- `event['pass:...:dedup_and_promote_constants'].meta.input_operations`
- `event['pass:...:dedup_and_promote_constants'].meta.ops_delta`
- Any per-pass `input_operations` field

Extra_timers events (if enabled):

- `graphlowering_run`, `graphlowering_codegen`,
  `spyre_kernel_codegen`

## Compute per-point summaries

For each `(revision, point)` pair:

- Median of the samples for each metric.
- Min/max spread.
- Per-run compile_fx breakdown so buckets sum:
  `compile_fx = graphlowering_run + graphlowering_codegen + sdsc + unattr`
  where `unattr = compile_fx − Σ(the others)`.

## Deltas

For each metric:

- `Δ_absolute = head_median − base_median` (positive = head slower)
- `Δ_relative = 100 × Δ_absolute / base_median`
- Spread band: `[head_min - base_max, head_max - base_min]` is a
  loose worst-case; report `head_max − base_min` (worst-case
  regression) and `base_max − head_min` (worst-case improvement)
  separately.

## Verdict decision tree

```
Are per-sample spreads bigger than the delta on every timed metric?
├── YES → NO MEASURABLE FRONTEND IMPACT
└── NO
    │
    Did compile_fx move?
    ├── NO → check whether individual Spyre passes moved anyway
    │       ├── YES → one pass got faster and another slower → likely
    │       │        STRUCTURAL CHANGE, PERFORMANCE NEUTRAL IN TESTED REGIME
    │       └── NO → NO MEASURABLE FRONTEND IMPACT
    │
    Did only dxp_standalone move (Spyre pipes stable)?
    ├── YES → BACKEND IMPACT ONLY
    └── NO
        │
        Did Spyre pipes move and structural counters change too?
        ├── YES → STRUCTURAL CHANGE ...
        │        (measure the per-op cost too: same-per-op with fewer
        │        ops is NEUTRAL; different per-op cost is IMPROVEMENT
        │        or REGRESSION depending on direction)
        └── NO → clean pass-time delta
                 ├── head < base → FRONTEND IMPROVEMENT
                 └── head > base → FRONTEND REGRESSION

Are results contradictory across sentinels or samples?
└── INSUFFICIENT EVIDENCE

Is the change gated (feature flag, argument, layout state) and
default-path is unchanged but the gated path moved?
└── ACTIVATION-SPECIFIC IMPACT
```

### `sdsc_bundle_gen` moved but no Spyre pass did

If `sdsc_bundle_gen` moved AND all Spyre `pipeline:*` are flat:

- If `n_specs` also moved → STRUCTURAL_CHANGE_NEUTRAL
  (bundle emission changed because there's less/more to emit).
- If `n_specs` unchanged AND `dxp_standalone` moved → the bundle
  representation changed. Verdict: **BACKEND_IMPACT_ONLY** with a
  documented `sdsc_bundle_gen` sub-stage delta note. This is what
  PR #3868 looked like at WB_n4: `sdsc_bundle_gen` +65%, every
  Spyre pass flat, `n_specs` unchanged, `dxp_standalone` −33%.
- If `n_specs` unchanged AND `dxp_standalone` unchanged → the change
  is doing extra bundle-emission work for no benefit at this
  workload. Note the regression; test on a different sentinel
  before generalizing.

## Structural change vs performance change

**The rule that separates them**: same graph, different pass time
= performance change. Different graph = structural change.

For dedup specifically:
- `input_operations` and `ops_delta` are recorded on every event.
- Compute per-run `t / (input_ops × dups)` at head and base.
- If per-pair cost is unchanged and total time moved because
  `input_ops × dups` moved → structural.
- If per-pair cost moved → performance.

For coarse-tile-hints specifically:
- `n_ops` and `n_groups` are recorded on substage events (when the
  substage instrumentation is on).
- Compute per-run `t / (n_ops × n_grouped_ops)`.
- Same test as above.

For n_specs / FX@entry:
- If a change caused fewer specs or fewer FX nodes → the compile
  necessarily ran less work; note that.
- Same specs / same FX → the pass is more or less efficient on the
  same input.

## Reporting effect size

Always include:

- Absolute delta in ms or s.
- Relative delta in %.
- Sample spread on both revisions.
- Structural counters at both revisions.

Example:

> `_maybe_coarse_tile_hints` head 3.93 s (min 3.87, max 4.02) vs
> base 14.46 s (min 14.19, max 14.71); Δ = −10.53 s (−73%). Well
> outside sample spread on either side. `n_ops` at
> `plan_tiling_propagation` unchanged (137 → 137), so this is a
> pass-efficiency improvement, not a structural change.
> Verdict: **FRONTEND IMPROVEMENT**.

Contrast with a poorly reported result:

> "Coarse-tile hints ran ~70% faster." — missing spread, missing
> structural check, missing base value.

## Growth-ratio comparison

For Level 3 (scaling pair):

- Baseline growth `t_base(2n) / t_base(n)`.
- Head growth `t_head(2n) / t_head(n)`.
- Compare the ratios, not just the absolute times.

A change that reduces absolute time by 20% at both points is a
constant-factor improvement, not a scaling-law change.

A change that leaves `t(n)` unchanged but reduces `t(2n) / t(n)`
from 3.7× to 2.8× IS a scaling-law shift — even if the smaller point
is untouched.

## What NOT to say

- "Compile time regressed" when only `dxp_standalone` moved.
- "Frontend improved" when only structural counters shrank.
- "Not significant" from n=3 with a t-test — small-sample stats
  disagree with what tiny n actually tells you. Report the spread.
- "Root cause identified" from source structure only. Say
  "hypothesized" until measurement agrees.
- Percentages without absolute numbers.

## Confidence labels

Use these consistently:

- **HIGH** — n≥3 both sides, effect exceeds spread on both, structural
  counters checked, at least one sentinel confirmed.
- **MEDIUM** — n=3 both sides but effect is at the edge of spread,
  OR n=1 with a clear direction.
- **LOW** — n=1 both sides, or spread and effect are comparable.
- **NONE** — the measurement did not run (Level 0 verdict) or
  produced INSUFFICIENT EVIDENCE.
