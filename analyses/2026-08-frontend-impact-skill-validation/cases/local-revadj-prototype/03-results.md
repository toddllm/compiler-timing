# Results — coarse-tile reverse-adjacency prototype

**Written AFTER measurement.**

## Data

- 3 base samples: `data/workload-B-post-fix/kv{1024,512}-nchunks{4,8}-run{1,2,3}-post.json`.
- 3 head samples: `data/workload-B-revadj/kv{1024,512}-nchunks{4,8}-run{1,2,3}-revadj.json`.
- All under `analyses/2026-08-frontend-scaling-cross-workload/data/`.

## WB_n4 (kv_block=1024, n_chunks=4)

| Stage | base_med (s) | head_med (s) | Δ (s) | ratio |
|---|---:|---:|---:|---:|
| **pass:_maybe_coarse_tile_hints** | 4.1097 | 1.4032 | **−2.71** | **0.341 (2.93× faster)** |
| **compile_fx_wrapper** | 10.7864 | 7.0992 | **−3.69** | 0.658 |
| first_call_wall | 0.8945 | 0.4512 | −0.44 | 0.504 |
| sdsc_bundle_gen | 0.4780 | 0.4771 | −0.001 | 0.998 |
| sdsc_total | 0.0583 | 0.0586 | +0.0003 | 1.006 |
| dxp_standalone | 23.3153 | 23.0146 | −0.30 | 0.987 |
| every other pass:* | flat within ±1% | | | |

## WB_n8 (kv_block=512, n_chunks=8)

| Stage | base_med (s) | head_med (s) | Δ (s) | ratio |
|---|---:|---:|---:|---:|
| **pass:_maybe_coarse_tile_hints** | 14.4637 | 3.9331 | **−10.53** | **0.272 (3.68× faster)** |
| **compile_fx_wrapper** | 12.2500 | 8.4394 | **−3.81** | 0.689 |
| first_call_wall | 1.2522 | 0.8956 | −0.36 | 0.715 |
| sdsc_bundle_gen | 1.0707 | 1.0820 | +0.011 | 1.011 |
| sdsc_total | 0.1146 | 0.1140 | −0.001 | 0.995 |
| dxp_standalone | 69.0736 | 69.0687 | −0.005 | 1.000 |
| every other pass:* | flat within ±1% | | | |

## Scaling law check

- Base `_maybe_coarse_tile_hints` grows 4.11 → 14.46 s from n=4 to n=8 (**3.52×**).
- Head `_maybe_coarse_tile_hints` grows 1.40 → 3.93 s (**2.81×**).
- Not just a constant-factor win — the scaling exponent has also
  improved on this pass. This is exactly what we would expect from
  replacing an O(k²) pairwise scan with a single-pass forward-adjacency
  traversal.

## Backend / structural sanity

- `dxp_standalone` is flat at both points (0.987× at n=4, 1.000× at n=8),
  confirming the backend received an equivalent bundle. Purely a
  frontend win — no downstream cost.

## Verdict

**FRONTEND_IMPROVEMENT**, HIGH confidence.
