# Retrospective — coarse-tile reverse-adjacency prototype

## Prediction vs measurement

| Item | Predicted | Measured | Match? |
|---|---|---|:---:|
| Direction on `_maybe_coarse_tile_hints` | major decrease | 2.93× @ n=4, 3.68× @ n=8 | yes |
| Direction on `compile_fx_wrapper` | decrease by pass delta | -3.69s (n=4), -3.81s (n=8) — matches pass delta | yes |
| Other passes | flat within noise | flat within ±1% | yes |
| `dxp_standalone` | unchanged | -1.3% @ n=4, 0.0% @ n=8 | yes |
| `sdsc_*` | unchanged | ±1% | yes |
| Verdict class | FRONTEND_IMPROVEMENT | FRONTEND_IMPROVEMENT | yes |
| Confidence | HIGH | HIGH | yes |

## Interpretation

The three-questions rule and the primary study's profiler traces
localized the hot substages ahead of measurement. Both substages were
inside a pass whose k² behavior on WB was already documented. The
patch targeted exactly those code paths, and the measurement confirmed
the predicted direction, magnitude, and non-mover set.

## What this case validates about the skill

- **Static triage** correctly identified this as a Level 1 case with a
  named `pass:*` and a clear expected mover.
- **Prediction discipline** — the direction (major decrease),
  magnitude class (major), and verdict class (FRONTEND_IMPROVEMENT)
  were written before measurement and match the results.
- **Structural counters** were sanity-checked via `dxp_standalone`
  flatness; no backend-only impact hidden here.
- **Scaling-law shift** — the pass's growth ratio between n=4 and n=8
  changed from 3.52× to 2.81×, so the skill's per-point measurement
  policy (two workload sizes, not one) is what let us see the exponent
  change instead of only the constant-factor shift.

## Lessons carried forward into v0.2

- The base/head triples were NOT interleaved. Deltas were large enough
  that this did not matter, but the skill's default policy is now to
  interleave in-place patch-swap runs whenever possible. See
  `.claude/skills/frontend-compiler-impact/references/measurement-policy.md`.
- The `dxp_standalone` flatness check is now called out in the
  interpretation guide as the canonical "backend was handed the same
  bundle" evidence for a pure frontend win.
