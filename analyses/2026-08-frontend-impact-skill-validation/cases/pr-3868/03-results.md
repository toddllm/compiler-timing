# Results — PR #3868

**Written AFTER measurement. This is the Tier 3 clean base/head A/B
against the PR's exact SHAs, executed on a newer pod
(`tdeshane-compiler-timing-dev-v2`) whose deeptools install is new
enough to build `_C.so` at the PR base. All timings below use
`inclusive_ns` (wall-clock cost of the stage, including nested
children). `self_ns` reductions are only reported where the column
name ends in `_self`. See `references/interpretation-guide.md`
"Inclusive vs self".**

## Setup

- Isolated checkouts at:
  - base: `torch-spyre` @ `2e935febe58bcf275accfaa4c960d972d7e6ce49`
    (`bundle.py` md5 `c93d3ba5d7...`)
  - head: `torch-spyre` @ `a7786ac8a6934645821b3698a9eb33ae2d3b590b`
    (`bundle.py` md5 `e13273ee01...`)
- `_C.so` built from source in each isolated tree
  (`python setup.py build_ext --inplace`) against the v2 pod's
  `ibm-deeptools-2.0.0-0.main.1+2245.85f9432` install. Both `_C.so`
  binaries import cleanly with the newer `NativePermutationLayoutSolver`
  symbol.
- Instrumentation via runtime shim
  (`.claude/skills/frontend-compiler-impact/scripts/timing_shim.py`) —
  no tree modification. Shim registers itself as
  `torch_spyre._inductor.timing_recorder` so the primary study's
  harness (`workload_harness_kvchunk.py`) works unchanged.
- 3 paired cold samples per point per revision at WB_n4 (kv_block=1024,
  n_chunks=4) and WB_n8 (kv_block=512, n_chunks=8). Interleaved
  base1/head1/base2/head2/base3/head3 within each point.
- Fresh `TORCHINDUCTOR_CACHE_DIR` per sample, `rm -rf`'d before use.
- All 12 sample JSONs pass `scripts/check_timing_json.py` invariants
  (parent-child containment, `self_ns == inclusive_ns − Σchildren`,
  leaves have `self == inclusive`).

## Verdict

**BACKEND_IMPACT_ONLY** with a documented `sdsc_bundle_gen` sub-stage
regression. Confidence: **HIGH**. Net wall-clock improvement at
both workload points.

Both points show the same pattern:

- Every Spyre `pipeline:*` is flat within run-to-run noise (main
  pre-scheduling pipeline is +9% / -2%, other pipelines within ±3%).
- `sdsc_bundle_gen` regresses by roughly the same fraction at both
  points (+65% at n=4, +46% at n=8).
- `dxp_standalone` improves substantially at both points (−40% at
  n=4, −45% at n=8).
- `n_specs` on both SDSC bundles is unchanged (5→5 and 1→1), so
  this is not a spec-dedupe effect. The mechanism is a
  bundle-representation shift that the backend processes faster.

## WB_n4 (kv_block=1024, n_chunks=4) — TRUE base vs TRUE head

Reduced with `inclusive_ns` for enclosing stages; `sdsc_total_self`
is a `self_ns` reduction (kept only because it isolates the recorder
overhead of the `sdsc` wrapper from its two children).

| Stage | reduction | base_med (s) | head_med (s) | Δ (s) | ratio | spread (base / head) |
|---|:---:|---:|---:|---:|---:|---|
| **first_call_wall** (whole workload wall) | inclusive | 47.8007 | 42.3879 | **−5.413** | **0.887** | 46.20–48.64 / 39.77–43.14 |
| **compile_fx_wrapper** (inductor compile) | inclusive | 46.4335 | 41.3751 | **−5.058** | **0.891** | 45.17–47.29 / 38.16–41.88 |
| **sdsc_total** (bundle_gen + dxp per kernel, both bundles) | inclusive | 22.6449 | 14.1685 | **−8.476** | **0.626** | tight |
| sdsc_total_self (recorder overhead only) | self | 0.1137 | 0.1198 | +0.006 | 1.053 | tight |
| **sdsc_bundle_gen** (both bundles, front-end emit) | inclusive | 0.4891 | 0.8050 | **+0.316** | **1.646** | 0.489–0.498 / 0.796–0.864 |
| **dxp_standalone** (both bundles, back-end call) | inclusive | 22.0426 | 13.2526 | **−8.790** | **0.601** | 21.92–22.13 / 12.91–13.83 |
| pipeline:CustomPreSchedulingPasses | inclusive | 10.4719 | 11.3855 | +0.914 | 1.087 | 10.24–11.02 / 10.17–11.51 |
| pipeline:CustomPreFusionPasses | inclusive | 0.0382 | 0.0381 | 0 | 0.998 | tight |
| pipeline:CustomPostFusionPasses | inclusive | 0.0192 | 0.0195 | 0 | 1.015 | tight |
| device_init_and_transfer | inclusive | 0.0879 | 0.0879 | 0 | 1.000 | tight |

## WB_n8 (kv_block=512, n_chunks=8) — TRUE base vs TRUE head

| Stage | reduction | base_med (s) | head_med (s) | Δ (s) | ratio | spread (base / head) |
|---|:---:|---:|---:|---:|---:|---|
| **first_call_wall** (whole workload wall) | inclusive | 101.5549 | 76.9702 | **−24.585** | **0.758** | 99.94–105.92 / 75.21–84.06 |
| **compile_fx_wrapper** (inductor compile) | inclusive | 100.1676 | 75.2971 | **−24.871** | **0.752** | 98.42–103.88 / 73.96–82.78 |
| **sdsc_total** (bundle_gen + dxp per kernel, both bundles) | inclusive | 48.1205 | 27.8522 | **−20.268** | **0.579** | tight |
| sdsc_total_self (recorder overhead only) | self | 0.2920 | 0.3085 | +0.017 | 1.057 | tight |
| **sdsc_bundle_gen** (both bundles, front-end emit) | inclusive | 1.1292 | 1.6441 | **+0.515** | **1.456** | 1.079–1.146 / 1.641–1.689 |
| **dxp_standalone** (both bundles, back-end call) | inclusive | 46.6790 | 25.8991 | **−20.780** | **0.555** | 46.30–54.51 / 25.78–26.39 |
| pipeline:CustomPreSchedulingPasses | inclusive | 32.4508 | 31.7998 | −0.651 | 0.980 | 31.42–33.56 / 31.69–32.82 |
| pipeline:CustomPreFusionPasses | inclusive | 0.0631 | 0.0617 | −0.001 | 0.978 | tight |
| pipeline:CustomPostFusionPasses | inclusive | 0.0308 | 0.0306 | 0 | 0.992 | tight |
| device_init_and_transfer | inclusive | 0.0814 | 0.0839 | +0.003 | 1.030 | tight |

## Comparison to the retracted marginal-patch study

The earlier marginal-patch measurement (pod tree's older `bundle.py`
as "base", pod bundle.py + PR diff as "head") is preserved in
`data/` and was called `INSUFFICIENT_EVIDENCE` because pod
`bundle.py` did not match PR base `bundle.py` byte-for-byte.

The TRUE base/head A/B here confirms — and now, with the correct
inclusive-time reduction, sharpens — the direction:

| Metric | Retracted marginal-patch | TRUE base/head | Notes |
|---|---|---|---|
| n=4 `sdsc_bundle_gen` Δ | +65% | **+65%** | direction + magnitude match |
| n=4 `dxp_standalone` Δ | −33% | **−40%** | true delta larger; retracted study understated because pod's older bundle.py made dxp slower to begin with |
| n=8 `sdsc_bundle_gen` Δ | +55% | **+46%** | direction matches |
| n=8 `dxp_standalone` Δ | −33% | **−45%** | true delta larger |
| n=4 `first_call_wall` Δ | not correctly reported previously (self_ns bug) | **−11% (−5.4 s)** | corrected here |
| n=8 `first_call_wall` Δ | not correctly reported previously (self_ns bug) | **−24% (−24.6 s)** | corrected here |
| n_specs (both bundles, both points) | 5→5, 1→1 | 5→5, 1→1 | matches |
| Spyre pipelines | flat ±1.5% | flat ±1.5–9% | matches |

## Interpretation

`n_specs` did not change on either SDSC bundle at either point.
The op-specs the compiler emits are structurally distinct across
chunks even though the Python source loops over structurally
similar chunk operations, so PR #3868's cache never populated with
duplicates. The head paid the added per-op canonical-compile +
`json.dumps(..., sort_keys=True)` cost (+0.32 s at n=4, +0.51 s at
n=8) without recouping any of it via cache hits.

Yet the backend (`dxp_standalone`) is substantially faster at head
(−8.8 s at n=4, −20.8 s at n=8, both roughly a 40% reduction). The
mechanism is a bundle-representation shift — the canonical JSON
that ends up embedded in the emitted bundle allows `dxp_standalone`
to process it more efficiently, even without any spec dedup at
this workload.

Every Spyre custom-pass pipeline is flat, so this is not a
frontend-pass movement. Under the seven-verdict scheme this
classifies as **BACKEND_IMPACT_ONLY**, with a documented
`sdsc_bundle_gen` sub-stage regression that is small compared to the
backend win.

Net wall-clock (`first_call_wall`, inclusive) improves by −5.4 s
(−11%) at n=4 and by −24.6 s (−24%) at n=8. The PR is a substantial
net win at both points; the value is on the backend side.

## Prediction vs measurement

- **Predicted verdict**: `FRONTEND_IMPROVEMENT` on `sdsc_bundle_gen`
  via cache hits.
- **Measured verdict**: `BACKEND_IMPACT_ONLY` — `sdsc_bundle_gen`
  regressed, `dxp_standalone` improved, `n_specs` unchanged.
- **Prediction correct?** No. The direction on `sdsc_bundle_gen`
  was wrong (predicted decrease, actual increase). The static
  reading assumed the WB workload's structural Python repetition
  would produce repeated OpSpec dicts. Measurement shows OpSpecs
  are distinct across chunks despite Python-source similarity, so
  the cache never populated.
- **Prediction preserved verbatim** in `01-static-assessment.md`
  and `prediction.json`. The disagreement is documented, not
  retconned.
