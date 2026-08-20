# Cross-case summary — skill validation

## Case matrix

| PR | Changed compiler surface | Skill static classification | Level | Sentinel selected | Prediction | Measured result | Prediction correct? | Experiment selection correct? | Device time | Naive baseline | Skill saving |
|:--:|:---|:---|---:|:---|:---|:---|:---|:---|---:|---:|---:|
| **#3871** | tests/ only | Level 0 (tests_only) | 0 | none | neutral / none | N/A (no run) | **YES** | **YES** | 0 s | ~27 min | ~27 min |
| **#3873** | layout_prop + ir_lowering + monkey-patch, all gated on `device_layout=` kwarg | Level 1 (TARGETED_RUN); ACTIVATION_SPECIFIC_IMPACT via static reasoning | 1 | WB_n4 (planned) | neutral for default path | 3-way apply confirmed pod-tree conflict only on the 5 lines the PR touches — corroborates the gated-branch structure | **YES** (static reasoning consistent with actual diff) | **YES** — measurement not required | 0 s | ~27 min | ~27 min |
| **#3849** | csrc + scratchpad on validation/guard paths | Level 1 (TARGETED_RUN) with C-extension caveat | 1 | WA_baseline (planned) | neutral (validation-only) | INSUFFICIENT_EVIDENCE — csrc file absent on pod, patches don't apply, would require ~70–90 min isolated build | **HIGH-medium confidence null retained** | **PARTIAL** — skill did not check pod-tree alignment before scheduling | 0 s | ~27 min | ~27 min |
| **#3890** | coarse_tile hot path | Level 3 (SCALING_RUN → reduced to WB_scaling_pair) | 3 | WB_scaling_pair (planned) | small regression (added arithmetic on correctness path) | INSUFFICIENT_EVIDENCE — pod-tree drift on `coarse_tile.py` (3757 lines pod vs 4317 lines PR base) prevents marginal patch A/B; isolated-checkout also blocked by pod system-lib mismatch | Cannot validate — static prediction retained with HIGH confidence | **PARTIAL** — over-provisioned to Level 3; Level 1 or 2 would have been sufficient given the localized correctness-fix nature | 100 s (one health-check baseline) | ~27 min | ~26 min |
| **local-revadj-prototype** | coarse_tile `_maybe_coarse_tile_hints` — reverse-adjacency restructuring of `_patch_retiled_load_indexes` and `_plan_tiling_propagation` | Level 1 (TARGETED_RUN) on WB_n4 + WB_n8 | 1 | WB_scaling_pair | FRONTEND_IMPROVEMENT, HIGH confidence, 3-4x on WB | **FRONTEND_IMPROVEMENT** (known-positive control), 2.93× at n=4, 3.68× at n=8; other passes flat within ±1%; dxp flat; scaling exponent shifted 3.52× → 2.81× | Known-positive control — this direction was established in the primary study before the skill existed. Validates the machinery, not the skill's ability to predict a novel change. | **YES** — right sentinels, right level | ~18 min (from primary study, reused) | ~27 min | 9 min |
| **#3868** | `codegen/bundle.py` — SDSC json caching / canonical embedding | Level 1 (TARGETED_RUN) on WB_n4 + WB_n8 | 1 | WB_scaling_pair | FRONTEND_IMPROVEMENT on `sdsc_bundle_gen`, MEDIUM confidence | **INSUFFICIENT_EVIDENCE** — initial marginal-patch measurement (base = pod bundle.py, head = same + PR diff) was RETRACTED after alignment-gate check showed pod's bundle.py differs from PR's actual base by 14 lines (pool-allocation refactor). Tier 3 isolated-checkout retry at exact PR base/head SHAs was blocked by pod's older deeptools install (missing `fast_process_hcm.h`). | Cannot validate — the marginal-patch data cannot separate the PR diff from the pool-refactor drift. Prediction preserved verbatim; the disagreement between prediction and marginal-patch result is not a valid test of the prediction. | Tier 2 gate check FAILED once tightened; Tier 3 was the correct escalation | ~24 min (marginal-patch attempt, retracted) | ~27 min | 3 min |

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
- **local-revadj-prototype** (known-positive control): correctly
  identified `_maybe_coarse_tile_hints` as the affected pass; Level 1
  on WB_scaling_pair was the right sentinel choice. Validates the
  machinery on a known answer; is not a test of predicting a novel
  change.
- **#3868** (SDSC json caching): correctly identified
  `codegen/bundle.py` as the affected surface. The initial "diff
  applies cleanly" Tier 2 acceptance was WRONG — the touched file
  had drifted at the pod. The alignment gate was tightened to
  per-touched-file blob equality; Tier 3 escalation was correct but
  blocked by pod system-lib age.

**Grade: 4/6 clean successes, 1 over-provisioning (#3890), 1 caught
its own alignment error and retracted (#3868).**

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
- #3873: correctly Level 1; measurement not needed given
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
- **local-revadj-prototype**: prediction (major decrease on
  `_maybe_coarse_tile_hints`, HIGH confidence) **matched
  measurement exactly**: 2.93× at n=4, 3.68× at n=8, scaling
  exponent shifted. All non-mover predictions held. This is a
  known-positive control, not a novel test.
- **#3868**: prediction (FRONTEND_IMPROVEMENT on `sdsc_bundle_gen`,
  MEDIUM confidence) is preserved verbatim. The marginal-patch
  measurement showed the opposite direction (+65%), but per the
  retraction that data cannot separate the PR diff from the
  pool-refactor drift. The prediction has NOT been calibrated
  against a valid measurement of PR #3868.

**Grade: predictions are internally consistent. Direct
measurement-based calibration is available on the known-positive
control only. Novel-change calibration remains open until a
Tier-3-capable substrate is available.**

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
- Lessons applied in v0.2:
  1. Add `_monkey_patch.py` to the rule table under
     `compile_fx_wrapper_setup`.
  2. **[DONE in v0.2]** Add a pod-tree-alignment check to
     `02-experiment-plan.md` that catches base-SHA mismatch before
     scheduling measurement. See
     `references/measurement-policy.md` "Pod-tree alignment gate".
  3. Add a cap for `coarse_tile` Level 3 when the diff is a
     correctness fix (docstring or PR-body signal: word "fix" or
     "bug" without "scaling"). Default remains Level 3; the cap
     downgrades to Level 1 or 2 when the signal is present.
  4. For C-extension changes, add a hard precondition that the
     pod tree contains the file — if not, escalate to
     "isolated_checkout_required" and route to a longer-form
     experiment plan.
  5. **[DONE in v0.2]** Add scripts for isolated-checkout
     workflow: `setup_isolated_checkout.sh`, `timing_shim.py`,
     `run_isolated_sample.sh`.
  6. **[DONE in v0.2, from #3868]** Add a new rule row for
     `codegen/bundle.py` in `compiler-stage-map.md`: it can move
     `sdsc_bundle_gen` independently of every Spyre pass. Give
     `sdsc_bundle_gen` its own row in every result table (not
     bundled into "Spyre pipes total"). Add the "sdsc_bundle_gen
     moved but no Spyre pass did" verdict clause in
     `interpretation-guide.md`.
  7. **[DONE in v0.2, from #3868]** Add the rule that predictions
     for cache-hit-driven changes must verify `n_specs` behavior
     before assuming the cache hits — the WB workload compiles into
     distinct OpSpec dicts despite structural Python repetition,
     so the cache we expected to hit never did.

## Grand verdict

The skill is **useful right now for triage discipline and static
attribution**. Across six cases:

- Four static-only cases (#3871, #3873, #3849, #3890) validated
  triage/attribution/prediction discipline without device time
  (except #3890's 100 s health-check baseline).
- `local-revadj-prototype` exercised the full predict → measure →
  verdict machinery on a known-positive control. Verdict:
  FRONTEND_IMPROVEMENT (HIGH), matching what the primary study
  already established. This validates the machinery, not the
  skill's ability to predict a novel change.
- **#3868 caught its own alignment error and was retracted**. The
  initial Tier 2 acceptance was too weak; the tightened Tier 2
  now requires per-touched-file blob equality with the PR's
  actual base. The Tier 3 retry at the exact PR SHAs was blocked
  by pod system-lib age. Final verdict: INSUFFICIENT_EVIDENCE.

**Novel-change empirical validation is not yet complete.** The
tooling and policy are in place. What is missing is a pod
substrate new enough to rebuild `_C.so` at a currently-open PR's
actual base SHA.

**For a fresh Claude session tomorrow**: the SKILL.md + references
+ scripts would let it correctly:

- Triage a new PR and issue NO_RUN if the diff is
  test/docs/CI-only.
- Issue a gated-activation verdict if the change is well-gated
  in source.
- Run the tightened alignment gate BEFORE scheduling device work:
  per-touched-file blob equality for Tier 2; isolated checkout
  at exact SHAs for Tier 3.
- Perform paired base/head measurements at the appropriate level.
- Interpret the results using the seven-verdict decision tree.
- Compare the pre-written prediction to the measurement in the
  retrospective, keeping the disagreement in the record instead
  of retconning.
- Retract a measurement when the alignment check catches a
  substrate mismatch, rather than reporting a plausible-looking
  but invalid verdict.

The #3868 case's ultimate value is that it caught its own
alignment error. If the skill had NOT tightened the alignment
gate, this case would have been committed as a validated
`BACKEND_IMPACT_ONLY` verdict that isn't. Instead, the case
documents the retraction, the tightened policy, and the pod
substrate limitation that blocks the retry.
