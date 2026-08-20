# Retrospective — PR #3868

## Prediction vs measurement

The static assessment predicted `FRONTEND_IMPROVEMENT` on `sdsc_bundle_gen`
via cache hits on repeated op-specs, based on the WB workload's
KV-chunked structural repetition.

The measurement disagreed **at both WB_n4 and WB_n8**:

| | WB_n4 | WB_n8 |
|---|---|---|
| `n_specs` (bundle 1 / bundle 2) | 5→5 / 1→1 | 5→5 / 1→1 |
| `sdsc_bundle_gen` delta | +65% (+0.31 s) | +55% (+0.58 s) |
| `dxp_standalone` delta | −33% (−7.7 s) | −33% (−22.3 s) |
| Spyre passes | flat ±1.5% | flat ±1.5% |

The pattern is identical in direction and near-identical in ratio at
both points — this is not noise, it is a mechanism operating at
scale. The head does more work in `sdsc_bundle_gen` (canonical
compile + `json.dumps` per op) and enables the backend to do
substantially less work.

## What went wrong in the prediction

The static reading correctly identified:

- The exact hot inner loop the PR touches.
- The direction on cache hits when they occur.
- The overhead on cache misses.

The static reading MISSED:

- That the emitted-bundle representation changes even on cache misses.
  Canonical json embedding, not just spec dedup, is what shrinks the
  backend's work.
- That KV-chunked repetition at the Python level does not necessarily
  produce identical `OpSpec` dicts after compile. The `n_specs=5`
  bundle has 5 distinct specs from what looked like structurally
  identical chunk operations.

## What this means for the seven-verdict scheme

The clean interpretation is:

- Spyre custom-pass pipelines: flat → NOT a FRONTEND_REGRESSION or
  IMPROVEMENT in the pass-time sense.
- `sdsc_bundle_gen` regressed within its slice, but that slice is
  bundle emission, not a custom pass.
- `dxp_standalone` moved substantially.

Two verdicts fit at the same time — the frontend `sdsc_bundle_gen`
regressed while the backend improved. In the seven-verdict scheme, the
best classification is **BACKEND_IMPACT_ONLY** (Spyre pipelines
unchanged, `dxp_standalone` moved), with a documented `sdsc_bundle_gen`
regression note. Alternatively, since `n_specs` and pass counts are
unchanged, `STRUCTURAL_CHANGE_NEUTRAL` also applies to describe the
bundle-representation shift.

For the v0.2 skill update: the interpretation guide should note that
`sdsc_bundle_gen` sits at the frontend/backend boundary and can move
without any pass-time change. It should be extracted as its own
line in the results table and treated as a boundary metric.

## What this case validates about the skill

- **Prediction discipline works**: the prediction was written, the
  measurement was independent, the two disagreed, and the case
  documented the disagreement instead of retconning either.
- **Static-only reasoning is not sufficient**. The static reading
  correctly bounded the affected surface, but the measurement
  revealed a mechanism that static reading could not see (backend
  benefit from canonical-form embedding).
- **`n_specs` structural counter is critical.** Without it, we would
  have assumed the cache "hit" (bundle emission time went UP,
  therefore extra work happened — but was that because the cache
  missed, or because canonical-compile was slow? `n_specs`
  unchanged tells us: no dedupe happened.)

## Lessons carried forward to v0.2

1. `sdsc_bundle_gen` gets its own line in every result table. Do not
   collapse it into "Spyre pipes" — it can move without any pass
   moving.
2. The interpretation guide's "BACKEND_IMPACT_ONLY" clause should
   allow for a coincident frontend sub-stage regression (like
   `sdsc_bundle_gen` here) as long as no Spyre pass moved.
3. Static predictions on cache-hit-driven changes should always
   verify `n_specs` behavior BEFORE trusting the direction. On
   workloads where the compile produces distinct OpSpec dicts
   despite structural Python repetition, the cache never hits.
4. The skill's `references/compiler-stage-map.md` should add a note
   that `bundle.py:_compile_specs` can move `sdsc_bundle_gen`
   independently of Spyre passes — new rule row.
