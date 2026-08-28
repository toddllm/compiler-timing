# E-only whole-compile perspective

Two views. Both matter. Do not oversell the pass-local ratio.

## Pass-local (dedup_and_promote_constants wall-clock)

Comparing the study's own pristine timing recorder data
(`data/*.json`, 3 samples per point, no dedup diagnostics) with the
production E-only measurements (`data-E-only/timing-off-*.json`, 3
samples per point, DIAG-OFF).

| point   | pristine dedup | E-only dedup | pass-local speedup |
|---------|---------------:|-------------:|-------------------:|
| 512×1024|       0.87 s   |     0.060 s  |            **14×** |
| 512×4096|      14.11 s   |     0.250 s  |            **57×** |
| 512×8192|      54.65 s   |     0.492 s  |           **111×** |

(The 16× / 63× / 126× ratios elsewhere in the report use the
Phase 2 diagnostic-on pristine numbers as the baseline, which
run ~10% slower on this pod than the study's own timing recorder
alone. The 14× / 57× / 111× ratios here are apples-to-apples
against the study's own baseline.)

## Whole-compile

The pass-local win is enormous. The end-to-end win is much smaller
because the external DXP backend subprocess dominates cold-compile
cost.

Compile-fx decomposition at the three points (pristine, study data):

| point | first_call_wall | compile_fx_wrapper | dxp_standalone | dxp share of compile_fx |
|-------|----------------:|-------------------:|---------------:|------------------------:|
| 512×1024|     100.52 s |          99.36 s   |       79.60 s  |                80.1%    |
| 512×4096|     569.48 s |         568.03 s   |      497.70 s  |                87.6%    |
| 512×8192|    2381.31 s |        2379.66 s   |     2198.93 s  |                92.4%    |

E-only savings vs pristine (assuming other passes unchanged, which
matches the downstream-pass check that showed ±5% at every
non-dedup pass):

| point | pipeline sum (pristine → est. E-only) | compile_fx (pristine → est. E-only) | savings as % of compile_fx |
|-------|--------------------------------------:|------------------------------------:|---------------------------:|
| 512×1024|     5.22 s → ~4.41 s               |    99.36 s → ~98.55 s               |                     **0.8%** |
| 512×4096|    40.47 s → ~26.61 s               |   568.03 s → ~554.17 s              |                     **2.4%** |
| 512×8192|   128.42 s → ~74.26 s               |  2379.66 s → ~2325.50 s             |                     **2.3%** |

## How to frame this in the PR

- **What we fixed**: a near-quadratic frontend-pass scaling defect
  in `dedup_and_promote_constants`. The pass previously invoked
  `op.get_read_writes()` `N × D` times; it now invokes it `N`
  times. On this workload duplicate count `D` grows with graph
  size, so pass wall-clock was near-quadratic in program size.

- **What we did NOT fix**: absolute cold-compile time. DXP backend
  is ~92% of `compile_fx` at Lk=8192; even a 111× pass-local win
  is only ~2.3% off the total. The change is worth doing because
  (a) it removes a genuine scaling pathology from the frontend
  and (b) it makes the next frontend bottlenecks
  (`optimize_restickify_locations`, `_maybe_scratchpad_planning`,
  each near-linear at 15–20% of pipeline time now) visible for
  future work.

- **Absolute wall-clock savings by point**:
  - 512×1024: saves ~0.8 s of ~99 s compile_fx (~0.8%).
  - 512×4096: saves ~14 s of ~568 s compile_fx (~2.4%).
  - 512×8192: saves ~54 s of ~2380 s compile_fx (~2.3%).

The framing "pass-local scaling defect removed" is stronger and
more accurate than any wall-clock end-to-end claim.
