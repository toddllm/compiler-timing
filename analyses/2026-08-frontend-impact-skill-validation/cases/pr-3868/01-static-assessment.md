# Static assessment — PR #3868

**Written BEFORE any measurement.**

## Target

- PR #3868 — "Cache and reuse sdsc json files during codegen"
- Base: main @ (verify at run time)
- URL: https://github.com/torch-spyre/torch-spyre/pull/3868
- 1 file changed: `torch_spyre/_inductor/codegen/bundle.py`

## What the PR does

Caches canonical SDSC JSON per unique op-spec in `_compile_specs`.
On repeated identical op specs, reuses the compiled entry and
avoids re-emitting the sdsc_<idx>.json file. Widens `_CompiledEntry`
tuple from 4-tuple to 5-tuple to carry the cached JSON.

## Applying the three-questions rule

1. **Executes on timed compile path in sentinel workload?** — YES.
   `_compile_specs` is called from `generate_bundle` which is called
   from `sdsc()`. Every SDSC bundle generation goes through this.
2. **Hot inner loop or setup?** — the hot inner loop of
   `_compile_specs` (per-OpSpec). The added cache check runs
   per-OpSpec.
3. **Alters collections/constants?** — YES: on cache hits, the
   canonical json is re-used and the per-OpSpec file emission is
   skipped. On cache misses, we do EXTRA work: an extra
   `compile_op_spec(0, ..., [], 0)` call to produce the canonical
   version, plus a `json.dumps(..., sort_keys=True)` for the key,
   plus a dict lookup.

## Expected direction

- On workloads with **many repeated op specs** (e.g. KV-chunked FA
  where each chunk contains structurally identical scores/exp/
  weighted computations), **improvement** in `sdsc_bundle_gen`
  from skipped duplicate emissions.
- On workloads with **all-unique op specs**, **small regression**
  from the added canonical compile + dict-key work per op.
- `dxp_standalone` should shrink slightly on workloads that hit
  the cache because the SDSC bundle handed to the backend is
  smaller (fewer distinct sdsc_<idx>.json files).

## Prediction

- **Direction**: improvement in `sdsc_bundle_gen` on workload B
  (KV-chunked with structural repetition); neutral or tiny
  improvement on workload A (OpSpec-tiled) since it has more
  varied ops but still some repetition.
- **Magnitude class**: moderate — the KV loop unrolls into
  many identical `keys_T = (k_c * scale).transpose...` and
  `torch.matmul(...)` patterns, so cache hits should be numerous.
- **Verdict class expected**: `FRONTEND_IMPROVEMENT` on `sdsc_*`;
  neutral on Spyre custom pass pipelines (they run before
  `_compile_specs`).
- **Confidence**: MEDIUM. The cache key is
  `json.dumps(canonical_json, sort_keys=True)` — for large op
  specs this string can be substantial, and the sort-keys work
  might partially offset gains on cache misses.

## Metrics expected to move

- `sdsc_bundle_gen` — should decrease with cache hits.
- `sdsc_total` (bundle_gen + dxp) — should decrease slightly.
- Possibly `dxp_standalone` if the emitted bundle is smaller.

## Metrics expected NOT to move

- `_maybe_coarse_tile_hints`, `dedup_and_promote_constants`,
  `optimize_restickify_locations`, all pre-scheduling passes.
- `compile_fx_wrapper` upper bound remains same, but should
  decrease by the `sdsc_*` savings.
- Structural counters: `fx_nodes_at_entry` unchanged. `n_specs`
  reported in `sdsc_bundle_gen.meta` MAY decrease (fewer distinct
  specs after dedup) — this is a **structural counter change**
  and would classify the result as `STRUCTURAL_CHANGE_NEUTRAL`
  in the frontend if it accompanies the timing improvement.

## Confidence

**MEDIUM**. Static reading of the diff is clear, but the
magnitude depends on how many cache hits the workload produces.
