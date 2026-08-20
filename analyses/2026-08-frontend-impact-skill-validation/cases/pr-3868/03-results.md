# Results — PR #3868

**Written AFTER measurement.**

## Data

- 3 base + 3 head paired cold-compile samples at WB_n4 (kv_block=1024).
- 3 base + 3 head paired cold-compile samples at WB_n8 (kv_block=512).
- Interleaved base1/head1/base2/head2/base3/head3 within each point.
- Fresh `TORCHINDUCTOR_CACHE_DIR` per sample.
- Timing captured via primary-study in-tree instrumentation (pod tree
  already carries the shim compiled in from `pr3806`).
- Base = pod tree's `bundle.py` (md5 `314e022307...`).
- Head = pod tree's `bundle.py` + PR #3868 diff applied
  (md5 `9f867fc18ca6...`).
- Pod-tree alignment: `git apply --check /tmp/pr3868.diff` returned
  0 on the pod tree — safe for in-place patch swap.

## WB_n4 (kv_block=1024, n_chunks=4)

| Stage | base_med (s) | head_med (s) | Δ (s) | ratio | spread |
|---|---:|---:|---:|---:|---|
| **sdsc_bundle_gen** | 0.4791 | 0.7901 | **+0.311** | **1.649** | 0.473–0.485 vs 0.790–0.792 |
| sdsc_total (self) | 0.0580 | 0.0617 | +0.004 | 1.063 | tight |
| **dxp_standalone** | 23.0845 | 15.3883 | **−7.70** | **0.667** | 22.91–23.21 vs 15.33–15.44 |
| compile_fx_wrapper | 14.37 | 17.07 | +2.70 | 1.188 | wide (12.4–16.8 vs 14.6–18.6) |
| first_call_wall | 1.43 | 1.20 | −0.24 | 0.835 | — |
| every Spyre pipeline: | flat within ±1.5% | | | | |

### Bundle-level breakdown

Two SDSC bundles per compile:

| Bundle | n_specs | base bundle_gen (s) | head bundle_gen (s) | Δ | base dxp (s) | head dxp (s) | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|
| `sdsc_fused_amax_full_zeros_like_0` | 5 → 5 | 0.028 | 0.048 | +0.020 | 1.14 | 0.78 | −0.36 |
| `sdsc_fused_add_amax_..._unsqueeze_1` | 1 → 1 | 0.457 | 0.743 | +0.286 | 22.07 | 14.55 | −7.52 |

**`n_specs` unchanged** on both bundles. The cache did not hit —
every op-spec was distinct — so no spec de-duplication occurred.

## WB_n8 (kv_block=512, n_chunks=8)

| Stage | base_med (s) | head_med (s) | Δ (s) | ratio | spread |
|---|---:|---:|---:|---:|---|
| **sdsc_bundle_gen** | 1.0679 | 1.6519 | **+0.584** | **1.547** | 1.062–1.073 vs 1.642–1.656 |
| sdsc_total (self) | 0.1149 | 0.1150 | +0.000 | 1.001 | tight |
| **dxp_standalone** | 67.9713 | 45.6980 | **−22.27** | **0.672** | 65.91–69.32 vs 43.77–46.48 |
| compile_fx_wrapper | 12.69 | 13.44 | +0.75 | 1.059 | wide |
| first_call_wall | 1.26 | 1.78 | +0.52 | 1.410 | — |
| every Spyre pipeline / pass: | flat within ±1.5% | | | | |

Pattern is identical at n=8: pipelines flat, `sdsc_bundle_gen` up 55%,
`dxp_standalone` down 33%.

## Prediction vs measurement

| Item | Predicted | Measured | Match? |
|---|---|---|:---:|
| Direction on `sdsc_bundle_gen` | decrease | **INCREASE +55–65%** | no |
| Direction on `sdsc_total` (self) | decrease | ±1% (within noise) | no (predicted mover, didn't) |
| Direction on `dxp_standalone` | maybe decrease | **decrease −33%** at both points | yes (larger than expected) |
| `n_specs` | may decrease | UNCHANGED at both points, both bundles | wrong (predicted uncertainty) |
| Every Spyre pass | flat | flat ±1.5% | yes |
| Verdict class | FRONTEND_IMPROVEMENT | BACKEND_IMPACT_ONLY with sdsc_bundle_gen regression | wrong |
| Confidence | MEDIUM | HIGH (data very clean, tight spreads, matches at 2 points) | — |

## What the data shows

The static reading correctly identified that the PR adds per-OpSpec
canonical-compile + `json.dumps(sort_keys=True)` work. What it MISSED:

- On this workload the compiler never sees repeated OpSpecs to dedupe
  — even though the Python source loops over chunks with identical
  structure, the resulting OpSpec dicts are distinct. `n_specs` is
  unchanged on both bundles at both points.
- The emitted bundle format changes even without cache hits, and the
  backend (`dxp_standalone`) processes that reshaped bundle
  substantially faster.

Net wall-clock is head−base = −7.7 s at n=4, −22.3 s at n=8. The PR
is a net improvement, but the mechanism is not the frontend-side
cache — it is a backend-side benefit of the canonicalized
representation.

## Verdict

**BACKEND_IMPACT_ONLY** with a documented `sdsc_bundle_gen` sub-stage
regression.

Under the seven-verdict scheme:
- Every Spyre `pipeline:*` is flat within ±1.5%, at BOTH points.
- `sdsc_bundle_gen` (frontend/backend boundary) regressed +65% at
  n=4 and +55% at n=8. Same-direction, similar-magnitude at both
  points — this is not noise.
- `dxp_standalone` (backend) improved −33% at BOTH points.

The frontend passes did not move. The only frontend surface that
moved is bundle emission, at a scale (~0.3–0.6 s) that is small
compared to the backend win. Confidence: **HIGH** on the classification.

Structural verification: `n_specs` unchanged on both bundles at
both points — this is not a spec-dedup effect. The mechanism is
whatever the backend does differently with a canonicalized bundle.
