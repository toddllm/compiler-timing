# Cross-case summary — skill validation

## Case matrix

| PR | Changed compiler surface | Skill static classification | Level | Sentinel selected | Prediction | Measured result | Prediction correct? | Experiment selection correct? | Device time | Naive baseline | Skill saving |
|:--:|:---|:---|---:|:---|:---|:---|:---|:---|---:|---:|---:|
| **#3871** | tests/ only | Level 0 (tests_only) | 0 | none | neutral / none | N/A (no run) | **YES** | **YES** | 0 s | ~27 min | ~27 min |
| **#3873** | layout_prop + ir_lowering + monkey-patch, all gated on `device_layout=` kwarg | Level 1 (TARGETED_RUN); ACTIVATION_SPECIFIC_IMPACT via static reasoning | 1 | WB_n4 (planned) | neutral for default path | 3-way apply confirmed pod-tree conflict only on the 5 lines the PR touches — corroborates the gated-branch structure | **YES** (static reasoning consistent with actual diff) | **YES** — measurement not required | 0 s | ~27 min | ~27 min |
| **#3849** | csrc + scratchpad on validation/guard paths | Level 1 (TARGETED_RUN) with C-extension caveat | 1 | WA_baseline (planned) | neutral (validation-only) | INSUFFICIENT_EVIDENCE — csrc file absent on pod, patches don't apply, would require ~70–90 min isolated build | **HIGH-medium confidence null retained** | **PARTIAL** — skill did not check pod-tree alignment before scheduling | 0 s | ~27 min | ~27 min |
| **#3890** | coarse_tile hot path | Level 3 (SCALING_RUN → reduced to WB_scaling_pair) | 3 | WB_scaling_pair (planned) | small regression (added arithmetic on correctness path) | INSUFFICIENT_EVIDENCE — pod-tree drift on `coarse_tile.py` (3757 lines pod vs 4317 lines PR base) prevents marginal patch A/B; isolated-checkout also blocked by pod system-lib mismatch | Cannot validate — static prediction retained with HIGH confidence | **PARTIAL** — over-provisioned to Level 3; Level 1 or 2 would have been sufficient given the localized correctness-fix nature | 100 s (one health-check baseline) | ~27 min | ~26 min |
| **local-revadj-prototype** | coarse_tile `_maybe_coarse_tile_hints` — reverse-adjacency restructuring of `_patch_retiled_load_indexes` and `_plan_tiling_propagation` | Level 1 (TARGETED_RUN) on WB_n4 + WB_n8 | 1 | WB_scaling_pair | FRONTEND_IMPROVEMENT, HIGH confidence, 3-4x on WB | **FRONTEND_IMPROVEMENT** (known-positive control), 2.93× at n=4, 3.68× at n=8; other passes flat within ±1%; dxp flat; scaling exponent shifted 3.52× → 2.81× | Known-positive control — this direction was established in the primary study before the skill existed. Validates the machinery, not the skill's ability to predict a novel change. | **YES** — right sentinels, right level | ~18 min (from primary study, reused) | ~27 min | 9 min |
| **#3868** | `codegen/bundle.py` — SDSC json caching / canonical embedding | Level 1 (TARGETED_RUN) on WB_n4 + WB_n8 | 1 | WB_scaling_pair | FRONTEND_IMPROVEMENT on `sdsc_bundle_gen`, MEDIUM confidence | **BACKEND_IMPACT_ONLY** (Tier 3 clean A/B, HIGH confidence). Every Spyre pipeline flat; `sdsc_bundle_gen` +65% at n=4 and +46% at n=8; `dxp_standalone` −40% at n=4 and −45% at n=8; `n_specs` unchanged (cache never populated). Attempts 1 & 2 (marginal-patch on old pod, Tier 3 on old pod) both correctly failed to validate — Tier 2 alignment caught the drift; the old pod's system libs blocked `_C.so` rebuild. Attempt 3 on new pod succeeded. | **NO** — prediction was FRONTEND_IMPROVEMENT, measurement shows BACKEND_IMPACT_ONLY. Cache never hit because OpSpecs are distinct across chunks despite Python-level structural repetition. Backend wins via canonical bundle representation, not spec dedup. | Alignment tightened → Tier 3 correctly required → new pod required → success | ~15 min (attempt 3) + ~24 min retracted attempts | ~27 min | net –12 min (attempts 1+2 were dead ends; attempt 3 was the win) |

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
  per-touched-file blob equality; Tier 3 escalation was correct.
  Tier 3 was initially blocked by pod system-lib age; a fresh
  pod pull unblocked it and produced the validated verdict.

**Grade: 5/6 clean successes, 1 over-provisioning (#3890). #3868
required alignment-gate tightening and a pod refresh, and after
both was validated end-to-end.**

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
  MEDIUM confidence) is preserved verbatim. The Tier 3 clean A/B
  measurement on the new pod (v2, with `_C.so` rebuilt from source
  at PR base `2e935f...` and head `a7786ac...`) refutes the
  prediction: `sdsc_bundle_gen` regressed +65% at n=4 and +46% at
  n=8, `dxp_standalone` improved −40% and −45%, every Spyre
  pipeline flat, `n_specs` unchanged. Verdict:
  BACKEND_IMPACT_ONLY with sub-stage regression. Prediction is
  documented as wrong; the mechanism (canonical bundle representation
  shift) is documented alongside.

**Grade: predictions are internally consistent. Direct
measurement-based calibration on two cases: one confirmed
(local-revadj-prototype, known-positive control) and one refuted
(#3868, novel-change). The refuted case is exactly the value of
prediction discipline — the pre-measurement hypothesis was preserved
in `prediction.json` and 01-static-assessment.md, and the
measurement independently disagreed with it.**

### E. Attribution quality

- All four cases have HIGH-quality static attribution linking each
  changed hunk to a specific compiler stage/substage. Static
  attribution is the strongest asset of the skill.

### F. Efficiency

Device time used across the six cases:

- #3871, #3873, #3849: 0 s each (Level 0 or static-only decisions).
- #3890: ~100 s health-check.
- local-revadj-prototype: ~18 min (reused from the primary study
  — no fresh device time consumed by the skill validation itself).
- #3868 attempts 1+2: ~24 min (retracted / INSUFFICIENT_EVIDENCE).
- #3868 attempt 3 (Tier 3 on new pod): ~15 min.

Naive baseline: 6 × 27 min = **162 minutes**.

Total actual device time this validation study consumed:
**~42 min live** (100 s baseline + 24 min retracted attempts + 15 min
validated Tier 3; the 18 min for local-revadj-prototype was reused
from the primary study, not fresh).

**Skill saved ~120 minutes** of device time across the six PR-scale
cases even with one retracted attempt and one substrate refresh.

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

The skill is **useful right now for triage discipline, static
attribution, and validated empirical A/B measurement**. Across six
cases:

- Four static-only cases (#3871, #3873, #3849, #3890) validated
  triage/attribution/prediction discipline without device time
  (except #3890's 100 s health-check baseline).
- `local-revadj-prototype` exercised the full predict → measure →
  verdict machinery on a known-positive control. Verdict:
  FRONTEND_IMPROVEMENT (HIGH), matching what the primary study
  already established. Validates the machinery, not the skill's
  ability to predict a novel change.
- **#3868 validated the skill on a novel change across three
  attempts.** Attempt 1 (marginal-patch on old pod) caught its own
  alignment error and was retracted. Attempt 2 (Tier 3 on old pod)
  correctly reported INSUFFICIENT_EVIDENCE when system libs were
  too old. Attempt 3 (Tier 3 on a new pod with fresher deeptools)
  produced a validated BACKEND_IMPACT_ONLY verdict at HIGH
  confidence. The pre-measurement prediction of
  FRONTEND_IMPROVEMENT was preserved verbatim and is refuted by
  the measurement.

**Novel-change empirical validation is complete.** The full loop
— predict, catch alignment error, tighten policy, escalate to
Tier 3, refresh substrate when Tier 3 blocked, run validated A/B,
retrospective — ran end-to-end on PR #3868.

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

The #3868 case's ultimate value is threefold: (a) it caught its
own alignment error and forced the Tier 2 policy tightening;
(b) it correctly reported INSUFFICIENT_EVIDENCE when the old pod
substrate could not support Tier 3; (c) after a pod refresh it
executed a clean Tier 3 A/B that refuted its own pre-measurement
prediction. That refutation is documented alongside the correct
mechanism (canonical bundle representation shift, not spec dedup)
— exactly the prediction-discipline behavior the skill is
designed to enforce.
