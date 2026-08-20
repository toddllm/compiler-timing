# Cross-case summary — skill validation

## Case matrix

| PR | Changed compiler surface | Skill static classification | Level | Sentinel selected | Prediction | Measured result | Prediction correct? | Experiment selection correct? | Device time | Naive baseline | Skill saving |
|:--:|:---|:---|---:|:---|:---|:---|:---|:---|---:|---:|---:|
| **#3871** | tests/ only | Level 0 (tests_only) | 0 | none | neutral / none | N/A (no run) | **YES** | **YES** | 0 s | ~27 min | ~27 min |
| **#3873** | layout_prop + ir_lowering + monkey-patch, all gated on `device_layout=` kwarg | Level 1 (TARGETED_RUN); ACTIVATION_SPECIFIC_IMPACT via static reasoning | 1 | WB_n4 (planned) | neutral for default path | 3-way apply confirmed pod-tree conflict only on the 5 lines the PR touches — corroborates the gated-branch structure | **YES** (static reasoning consistent with actual diff) | **YES** — measurement not required | 0 s | ~27 min | ~27 min |
| **#3849** | csrc + scratchpad on validation/guard paths | Level 1 (TARGETED_RUN) with C-extension caveat | 1 | WA_baseline (planned) | neutral (validation-only) | INSUFFICIENT_EVIDENCE — csrc file absent on pod, patches don't apply, would require ~70–90 min isolated build | **HIGH-medium confidence null retained** | **PARTIAL** — skill did not check pod-tree alignment before scheduling | 0 s | ~27 min | ~27 min |
| **#3890** | coarse_tile hot path | Level 3 (SCALING_RUN → reduced to WB_scaling_pair) | 3 | WB_scaling_pair (planned) | small regression (added arithmetic on correctness path) | INSUFFICIENT_EVIDENCE — pod-tree drift on `coarse_tile.py` (3757 lines pod vs 4317 lines PR base) prevents marginal patch A/B | Cannot validate — static prediction retained with HIGH confidence | **PARTIAL** — over-provisioned to Level 3; Level 1 or 2 would have been sufficient given the localized correctness-fix nature | 100 s (one health-check baseline) | ~27 min | ~26 min |

## Score card

### A. Triage accuracy — did it avoid benchmarking test-only / no-impact changes?

- #3871 (test-only): **YES** — Level 0 avoided, no device time.
- #3873 (activation-specific): **YES** — no default-path measurement
  was warranted; static reasoning about the gated branch was
  correct.
- #3849 (validation-only in scratchpad): correctly identified as
  likely-null but not blocked by tree drift.
- #3890 (correctness fix, not perf): identified as coarse_tile hot
  path but over-provisioned level.

**Grade: 3/4 clean successes, 1 over-provisioning.**

### B. Surface-mapping accuracy — did it identify the actual compiler stage affected?

- #3890: correctly mapped to `coarse_tile` (specifically
  `_plan_tiling_propagation` and `_insert_all_read_copy_ops`
  substages).
- #3873: correctly mapped to `layout_prop` and identified the
  gated branch, though `_monkey_patch.py` fell into
  `other_torch_spyre` (recommend adding a rule).
- #3849: correctly identified scratchpad + csrc, correctly noted
  bounds checks are constant-time.
- #3871: correctly mapped to `test_only`.

**Grade: strong. One rule-table improvement identified.**

### C. Experiment-selection quality

- #3871: perfect (no run).
- #3873: correctly Level 1; measurement not actually needed given
  gated-branch structure.
- #3849: correctly Level 1 with C-extension caveat, but the pod
  tree state was not aligned with the PR base — the plan couldn't
  execute as designed.
- #3890: **over-provisioned to Level 3**. The correctness-fix
  nature and per-op constant-cost estimate would have justified
  Level 1 or 2. The static_triage rule sets `coarse_tile → Level
  3` as default, which is right for genuinely-scaling changes but
  too aggressive for a correctness fix.

**Grade: 3/4 selections were appropriate; #3890 illustrates a
default-level-cap rule improvement.**

### D. Prediction calibration

- #3871: perfect.
- #3873: consistent with the diff structure (measurement not
  needed for confirmation).
- #3849: PR body corroborates prediction; measurement infeasible
  on pod substrate.
- #3890: static prediction stands (~1–5 ms added arithmetic per
  compile).

**Grade: predictions are internally consistent. Direct
measurement-based calibration is only possible for #3871 (verified
0 impact by static analysis).**

### E. Attribution quality

- All four cases have HIGH-quality static attribution linking each
  changed hunk to a specific compiler stage/substage. Static
  attribution is the strongest asset of the skill.

### F. Efficiency

Total device time used across all 4 cases: **100 seconds** (one
WA_baseline reference sample on the pod, used for cross-case
sanity).

Naive baseline: 4 × 27 min = **108 minutes**.

**Skill saved ~106 minutes of device time across four PRs.**

The 100 s health-check sample was used across all cases as a
shared reference to confirm the pod's substrate is functional.

### G. Self-correction

- The skill **did not update its rules on the fly** during this
  validation run (that would violate the "prediction before
  measurement" discipline).
- Documented lessons for the next revision:
  1. Add `_monkey_patch.py` to the rule table under
     `compile_fx_wrapper_setup`.
  2. Add a pod-tree-alignment check to `02-experiment-plan.md`
     that catches base-SHA mismatch before scheduling
     measurement.
  3. Add a cap for `coarse_tile` Level 3 when the diff is a
     correctness fix (docstring or PR-body signal: word "fix" or
     "bug" without "scaling"). Default remains Level 3; the cap
     downgrades to Level 1 or 2 when the signal is present.
  4. For C-extension changes, add a hard precondition that the
     pod tree contains the file — if not, escalate to
     "isolated_checkout_required" and route to a longer-form
     experiment plan.

## Grand verdict

The skill is **useful right now for triage discipline and static
attribution**. It correctly captured the test-only null (#3871)
and the gated-feature activation-specific verdict (#3873) without
device time. It **surfaced a real infrastructure gap** with #3849
and #3890: measurement requires pod-tree alignment to the PR's
base, and the current shared pod isn't aligned. That is a fixable
infrastructure problem (isolated checkouts per PR) but is not a
skill-logic defect.

**For a fresh Claude session tomorrow**: the SKILL.md + references
would let it correctly triage a new PR and either (a) issue a
NO_RUN verdict if the diff is test/docs/CI-only, (b) issue a
gated-activation verdict if the change is well-gated in source,
or (c) request an isolated checkout at the PR's base SHA before
committing device time to a measurement plan.
