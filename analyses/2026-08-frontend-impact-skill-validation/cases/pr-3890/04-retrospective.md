# Retrospective — PR #3890

## Prediction correctness

- **Predicted direction**: mild regression on
  `_maybe_coarse_tile_hints` (added dict-building + heavier
  `active_full_sizes` computation).
- **Predicted magnitude**: small (~1–5 ms per compile at WB n=4);
  below WB n=4 spread.
- **Predicted verdict class**: `NO_MEASURABLE_FRONTEND_IMPACT` at
  WB n=4; possibly `NO_MEASURABLE_FRONTEND_IMPACT` at WB n=8 too.

- **Actual outcome**: `INSUFFICIENT_EVIDENCE` — measurement blocked
  by tree drift. Static prediction cannot be directly confirmed
  without a fresh isolated-checkout base at the PR's actual base
  SHA.

**Verdict**: unable to test the prediction directly. The
underlying static analysis still stands with HIGH confidence
because the diff is small and localized to per-op arithmetic on
paths not exercised by sentinel workloads at the shape level that
triggers the bugs.

## Experiment selection

- Chose Level 3 (SCALING_RUN reduced to WB_scaling_pair). This
  was correct for the static-triage classification (coarse_tile
  hot path → Level 3 default).
- However, executing this plan required pod-tree alignment. The
  skill did not check that alignment before committing to the
  plan.

## Skill lessons

1. **Add a "pod-tree alignment check" step to `02-experiment-plan.md`**.
   Before selecting Level ≥1, verify that the target PR's base SHA
   is close enough to the pod's checkout state that a marginal
   patch can apply. Options when they don't:
   - Set up an isolated fresh checkout at the PR's base SHA.
   - Downgrade to static-only assessment with an explicit
     limitation note.
   - Skip and request user intervention.
2. **The three-questions rule was applied correctly** — the answer
   at question 1 was "yes (touches hot path)" but at question 2 was
   "hot inner loop is touched with per-op arithmetic that scales
   O(N)", not "algorithm change". The right level was probably 2 or
   even 1 rather than 3.
3. **Reference-only measurement is useful as a health check** —
   the workspace-baseline sample confirmed the pod substrate is
   valid, which will speed future validation cycles that CAN align
   trees.

## Efficiency

- Device time used: ~100 s (one reference sample).
- Device time planned but not used: ~18 min (blocked by tree drift).
- Naive baseline device time: ~27 min.
- **Net saving in this run**: ~26 min (only spent the health-check
  sample, avoided both the mispiloted plan AND the naive baseline).
- **Cost of the drift limitation**: the definitive answer for PR
  #3890 requires setting up an isolated ~10-min checkout before
  the actual measurement. That is a real infrastructure gap for
  the skill.
