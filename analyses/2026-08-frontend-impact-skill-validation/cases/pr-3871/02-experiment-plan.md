# Experiment plan — PR #3871

**Written BEFORE any measurement.**

## Level decision

- **Chosen level**: **0** (NO_RUN)
- **Rationale**: both changed files are under `tests/`. Rule
  `R-tests-only` fires with high confidence for each. No hot-path
  activation is possible in the compiled path. The three-questions
  rule fails at question 1: the changed code does not execute
  during a compile on any sentinel workload.

## Sentinels selected

None.

## Metrics expected to move

None.

## Metrics expected NOT to move

All compile-time metrics on any sentinel workload.

## C-extension rebuild required?

No.

## Estimated device time

- **Actual plan**: 0 seconds.
- **Naive baseline** (WA_baseline + WB_scaling_pair, 3 samples each,
  base+head): ≈ 3 × (90 + 90) + 3 × (60 + 60) + 3 × (125 + 125)
  = 540 + 360 + 750 = 1650 seconds base+head ≈ 27.5 minutes.
- **Device time saved by targeted selection**: ~27 minutes.
