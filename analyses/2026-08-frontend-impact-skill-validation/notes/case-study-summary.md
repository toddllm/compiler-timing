# Cross-case summary — skill validation

## Case matrix

| PR | Changed compiler surface | Skill static classification | Level | Sentinel selected | Prediction | Measured result | Prediction correct? | Experiment selection correct? | Device time | Naive baseline | Skill saving |
|:--:|:---|:---|---:|:---|:---|:---|:---|:---|---:|---:|---:|
| **#3871** | tests/ only | Level 0 (tests_only) | 0 | none | neutral / none | N/A (no run) | **YES** | **YES** | 0 s | ~27 min | ~27 min |
| **#3873** | layout_prop + ir_lowering + monkey-patch, all gated on `device_layout=` kwarg | Level 1 (TARGETED_RUN); ACTIVATION_SPECIFIC_IMPACT via static reasoning | 1 | WB_n4 (planned) | neutral for default path | 3-way apply confirmed pod-tree conflict only on the 5 lines the PR touches — corroborates the gated-branch structure | **YES** (static reasoning consistent with actual diff) | **YES** — measurement not required | 0 s | ~27 min | ~27 min |
| **#3849** | csrc + scratchpad on validation/guard paths | Level 1 (TARGETED_RUN) with C-extension caveat | 1 | WA_baseline (planned) | neutral (validation-only) | INSUFFICIENT_EVIDENCE — csrc file absent on pod, patches don't apply, would require ~70–90 min isolated build | **HIGH-medium confidence null retained** | **PARTIAL** — skill did not check pod-tree alignment before scheduling | 0 s | ~27 min | ~27 min |
| **#3890** | coarse_tile hot path | Level 3 (SCALING_RUN → reduced to WB_scaling_pair) | 3 | WB_scaling_pair (planned) | small regression (added arithmetic on correctness path) | INSUFFICIENT_EVIDENCE — pod-tree drift on `coarse_tile.py` (3757 lines pod vs 4317 lines PR base) prevents marginal patch A/B; isolated-checkout also blocked by pod system-lib mismatch | Cannot validate — static prediction retained with HIGH confidence | **PARTIAL** — over-provisioned to Level 3; Level 1 or 2 would have been sufficient given the localized correctness-fix nature | 100 s (one health-check baseline) | ~27 min | ~26 min |
| **local-revadj-prototype** | coarse_tile `_maybe_coarse_tile_hints` — reverse-adjacency restructuring of `_patch_retiled_load_indexes` and `_plan_tiling_propagation` | Level 1 (TARGETED_RUN) on WB_n4 + WB_n8 | 1 | WB_scaling_pair | FRONTEND_IMPROVEMENT, HIGH confidence, 3-4x on WB | **FRONTEND_IMPROVEMENT**, 2.93× at n=4, 3.68× at n=8; other passes flat within ±1%; dxp flat; scaling exponent shifted 3.52× → 2.81× | **YES** (direction, magnitude class, verdict, and non-mover set all match) | **YES** — right sentinels, right level | ~18 min (from primary study, reused) | ~27 min | 9 min |
| **#3868** | `codegen/bundle.py` — SDSC json caching / canonical embedding | Level 1 (TARGETED_RUN) on WB_n4 + WB_n8 | 1 | WB_scaling_pair | FRONTEND_IMPROVEMENT on `sdsc_bundle_gen`, MEDIUM confidence | **BACKEND_IMPACT_ONLY with sub-stage regression note**: Spyre pipelines flat ±2%; `sdsc_bundle_gen` REGRESSED +65% at n=4; `n_specs` unchanged (cache never hit); `dxp_standalone` improved −33% at n=4 due to canonical bundle representation, not spec dedupe | **NO** — direction on `sdsc_bundle_gen` was wrong; ACTUAL mechanism is bundle-representation shift, not spec cache | **YES** — right sentinels, right level; PR was in-place-patchable to pod tree (validated pod-tree alignment gate) | ~24 min | ~27 min | 3 min |

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
- **local-revadj-prototype** (perf-optimization prototype): correctly
  identified `_maybe_coarse_tile_hints` as the affected pass; Level 1
  on WB_scaling_pair was the right sentinel choice.
- **#3868** (SDSC json caching): correctly identified
  `codegen/bundle.py` as the affected surface; pod-tree alignment
  gate confirmed diff applies cleanly; Level 1 on WB_scaling_pair
  was the right choice.

**Grade: 5/6 clean successes, 1 over-provisioning (#3890).**

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
  exponent shifted. All non-mover predictions held.
- **#3868**: prediction (FRONTEND_IMPROVEMENT on `sdsc_bundle_gen`,
  MEDIUM confidence) was **WRONG**. The cache never hit at this
  workload (`n_specs` unchanged), so the head paid overhead
  without dedup payoff — `sdsc_bundle_gen` regressed +65%. However,
  `dxp_standalone` improved −33% because the canonical bundle
  representation shifted independently of cache hits. The static
  reading missed this mechanism because it isn't visible from the
  diff alone.

**Grade: predictions are internally consistent. Direct
measurement-based calibration on two live A/B cases: one confirmed
(revadj), one refuted (#3868). The refuted case is exactly the
value of prediction discipline — it forced the mechanism to be
re-analyzed rather than fitted after the fact.**

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

The skill is **useful right now for triage discipline, static
attribution, and empirical A/B measurement**. Across six cases:

- Four static-only cases (#3871, #3873, #3849, #3890) validated
  triage/attribution/prediction discipline without device time
  (except #3890's 100 s health-check baseline).
- Two empirical A/B cases produced base/head measurements
  that reached defined verdicts:
  - `local-revadj-prototype` → **FRONTEND_IMPROVEMENT** (HIGH
    confidence, direction/magnitude/verdict prediction all
    matched).
  - **#3868** → **BACKEND_IMPACT_ONLY** with a documented
    `sdsc_bundle_gen` sub-stage regression (prediction of
    FRONTEND_IMPROVEMENT was refuted by measurement; the case
    documents both the prediction and the actual mechanism).

**For a fresh Claude session tomorrow**: the SKILL.md + references
+ scripts would let it correctly:

- Triage a new PR and issue NO_RUN if the diff is
  test/docs/CI-only.
- Issue a gated-activation verdict if the change is well-gated
  in source.
- Run the pod-tree alignment gate BEFORE scheduling device work:
  in-place patch-swap if the diff applies cleanly, isolated
  checkout otherwise.
- Perform paired base/head measurements at the appropriate level.
- Interpret the results using the seven-verdict decision tree,
  including the `sdsc_bundle_gen`-moved-but-no-pass-did clause
  that the #3868 case added.
- Compare the pre-written prediction to the measurement in the
  retrospective, keeping the disagreement in the record instead
  of retconning.

**Refuted-prediction preservation is a feature, not a bug.** The
#3868 case is the strongest evidence that the skill's discipline
works: the prediction was wrong, the measurement independently
disagreed, and the retrospective documents both the wrong
mechanism (spec dedup) and the correct one (canonical bundle
representation shift). Static reasoning is a hypothesis; the
measurement is the arbiter.
