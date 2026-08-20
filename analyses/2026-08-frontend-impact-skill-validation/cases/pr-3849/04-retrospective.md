# Retrospective — PR #3849

## Prediction correctness

- **Predicted direction**: neutral (validation/guard changes; PR
  body explicitly says unchanged valid layouts).
- **Predicted magnitude**: none, possibly small from added
  O(1)-per-instantiation bounds checks.
- **Predicted verdict class**: `NO_MEASURABLE_FRONTEND_IMPACT`.

- **Actual outcome**: measurement blocked by tree drift +
  C-extension file absence on pod. Static prediction cannot be
  directly confirmed on the pod substrate.

**Verdict**: prediction is well-supported by the diff structure
and PR body, but the measurement infrastructure was not aligned to
test it. This is a **skill gap around C-extension changes on a
stale pod tree**, not a prediction failure.

## Experiment selection

- Chose Level 1 (TARGETED_RUN) with explicit C-extension caveat.
- Correctly noted the rebuild cost in `02-experiment-plan.md`.
- Underweighted the tree-drift risk when scheduling.

## Skill lessons

1. **The C-extension rule needs to escalate to isolated-checkout
   requirement**. Currently the rule says "rebuild per revision";
   in practice this means the whole test cannot use a shared pod
   tree at all if the PR post-dates the tree's `torch_spyre/csrc/`.
   Update `compiler-stage-map.md` accordingly.
2. **Non-existence of a changed file on the pod tree is a hard
   signal**. `git apply` errored `No such file or directory` for
   the new `.cpp` file. The skill should detect this
   automatically and route to isolated-checkout.
3. **PR body claims like "unchanged valid layouts" are useful
   priors** but should never be the sole basis for a
   NO_MEASURABLE_FRONTEND_IMPACT verdict on a scratchpad-adjacent
   change, given scratchpad's history of surprise measurements
   (see `notes/scratchpad-prototype.md` from the cross-workload
   study).

## Efficiency

- Device time used: 0 s (shared workspace baseline).
- Naive baseline device time: ~27 min.
- **Device time saved: ~27 min.**
- Full clean measurement would have cost ~70–90 min (rebuild + 2×
  sweep). Skipped for the reasons above.
- This is a **defensible skip**, not a false negative, because the
  prediction is a null and the PR body corroborates it.
