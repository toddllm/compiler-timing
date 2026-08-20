# Retrospective — PR #3873

## Prediction correctness

- **Predicted direction**: neutral (default path); functional
  activation-specific for opted-in path.
- **Predicted magnitude**: none for default path.
- **Predicted verdict class**: `ACTIVATION_SPECIFIC_IMPACT`.

- **Actual outcome**: consistent with prediction — static analysis
  of the diff confirms the change is fully gated on
  `FixedTiledLayout` presence, which is only set by opt-in through
  `torch.full(..., device_layout=...)`. The 3-way apply attempt
  produced a conflict only on the exact 5 lines the PR modifies,
  because the pod's tree is at post-#3812 state on that hunk.
  Everything else applied cleanly.

**Verdict**: correct. This is exactly the kind of PR the
`ACTIVATION_SPECIFIC_IMPACT` verdict was designed for.

## Experiment selection

- Chose Level 1 (TARGETED_RUN). Correct for a gated change.
- The 3-way apply attempt is a useful signal that the change is
  small and localized (only one file conflicted, and only on the
  exact 5 lines the PR modifies).

## Skill lessons

- **Gated-branch detection is important**. The static triage
  correctly identified layout_prop as a hot-path stage but the
  three-questions rule (specifically the "hot inner loop or
  setup?" and "alter collections/constants?" checks) correctly
  downgraded the assessment to Level 1.
- **The `_monkey_patch.py` file should have a rule**. Currently
  classified as `other_torch_spyre` with `uncertain` hot-path.
  Real classification: `compile_fx_wrapper_setup` because it
  monkey-patches `torch.full` globally at import time.
  → Add rule `R-monkey-patch` in the next iteration of
  `static_triage.py`.

## Efficiency

- Device time used: 0 s (shared with the workspace-baseline
  reference in ../data/workspace-baseline/).
- Naive baseline device time: ~27 min.
- **Device time saved: ~27 min.**
- This case shows the skill handling a MEDIUM-triage feature PR
  correctly with no measurement — because the static reasoning
  was decisive on gating.
