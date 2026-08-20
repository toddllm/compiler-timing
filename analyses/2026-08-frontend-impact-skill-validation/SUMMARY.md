# Frontend-compiler-impact skill — validation summary

## What was validated (v0.2)

The `.claude/skills/frontend-compiler-impact/` skill (see
[`SKILL.md`](../../.claude/skills/frontend-compiler-impact/SKILL.md))
was applied to six cases covering all four active verdict classes:

- Negative control (test-only): **PR #3871**.
- Activation-specific (gated feature): **PR #3873**.
- Ambiguous (validation on hot subsystem): **PR #3849**.
- Frontend-relevant (hot-path correctness fix): **PR #3890**.
- **Empirical A/B — obvious frontend case**: `local-revadj-prototype`
  (coarse-tile reverse-adjacency prototype, standing in for #3890
  since #3890's isolated checkout is blocked by pod system-lib
  versions).
- **Empirical A/B — different mechanism**: **PR #3868** (SDSC json
  caching in `codegen/bundle.py`, currently open, applies cleanly
  to the pod tree).

## Cross-case results

| PR | Rank at scan | Level chosen | Verdict | Device time used |
|---:|:---|---:|:---|---:|
| #3871 | NONE | 0 | NO_RUN (correct) | 0 s |
| #3873 | MEDIUM | 1 | ACTIVATION_SPECIFIC_IMPACT (static-only, corroborated by 3-way apply) | 0 s |
| #3849 | MEDIUM | 1 | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift + C-extension absence) | 0 s |
| #3890 | HIGH | 3 → reduced to WB_scaling_pair | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift + system-lib versions) | 100 s (shared reference) |
| local-revadj-prototype | — | 1 | **FRONTEND_IMPROVEMENT** (measured 2.93× @ n=4, 3.68× @ n=8) | ~18 min (reused primary study) |
| #3868 | MEDIUM | 1 | **BACKEND_IMPACT_ONLY with sdsc_bundle_gen sub-stage regression** (measured) | ~24 min |

**Total device time**: ~42 minutes across six cases (100 s baseline +
18 min reused + 24 min live measurement).
**Naive baseline** (run all sentinels for all six): ~162 minutes.
**Device time saved**: ~120 minutes — with two clean live A/B cases
that reached defined verdicts.

## Where the skill worked

1. **Test-only PR (#3871) was correctly and cheaply handled**.
   Static rule `R-tests-only` fired with high confidence; the
   skill spent zero device time and would have wasted ~27 min in
   a naive workflow.
2. **Gated-feature PR (#3873) was correctly diagnosed as
   ACTIVATION_SPECIFIC_IMPACT** without device measurement. The
   3-way patch apply attempt corroborated the gated-branch static
   structure by conflicting only on the 5 lines the PR modifies.
3. **Static attribution quality is high across all cases**. Each
   PR's changed hunks were traced to specific pipeline substages
   using the compiler stage map, with confidence appropriately
   qualified.
4. **The skill's discipline was preserved**: no measurement was
   fabricated when the pod substrate did not permit a clean A/B.
   The `INSUFFICIENT_EVIDENCE` verdict is recorded when the data
   does not support a stronger classification.
5. **The reverse-adjacency prototype case** exercised the full
   flow: prediction (major decrease, HIGH confidence) → sentinel
   selection (WB_scaling_pair) → measurement → verdict
   (FRONTEND_IMPROVEMENT) → retrospective. Prediction matched
   measurement in direction, magnitude class, and non-mover set.
6. **PR #3868 exercised the full flow with a refuted prediction**.
   Static reading predicted FRONTEND_IMPROVEMENT via cache hits.
   Measurement showed the cache never hit at this workload
   (`n_specs` unchanged), so `sdsc_bundle_gen` regressed +65% —
   but `dxp_standalone` improved −33% via a bundle-representation
   shift not visible in the diff. The retrospective preserved
   the wrong prediction alongside the correct mechanism. This is
   exactly the discipline the skill exists to enforce.

## Where the skill fell short

1. **Pod-tree alignment was not pre-checked**. The pod is at an
   older `main` snapshot (`a9316b381`) than the PRs' bases
   (`be1328a867`, `53742fecb7`, `3e23d180ee`). Marginal patch A/B
   fails when the drift touches files the PR modifies.
2. **C-extension changes (#3849) require isolated checkouts** —
   the skill's SKILL.md notes this but the experiment plan did
   not automatically escalate.
3. **Level 3 default for `coarse_tile` over-provisioned #3890**.
   The PR is a per-op arithmetic correctness fix, not a scaling
   change; a cap based on the PR body's "fix"/"bug" signal would
   have picked Level 1.
4. **`_monkey_patch.py` is not in the rule table**. It affects
   `torch.full`'s import-time behavior but was classified as
   `other_torch_spyre`.

## Improvements delivered in v0.2

1. **[DONE]** Pod-tree alignment gate in
   `references/measurement-policy.md` — check BEFORE scheduling
   device work: pod == PR base, or diff applies cleanly, or
   isolated checkout required.
2. **[DONE]** Isolated-checkout scripts:
   - `scripts/setup_isolated_checkout.sh` — clone at SHA,
     symlink `_C.so`, smoke-test import.
   - `scripts/timing_shim.py` + `scripts/timing_recorder.py` —
     runtime instrumentation for an isolated tree without
     tree modification.
   - `scripts/shim_runner.py` — shim-first harness runner.
   - `scripts/run_isolated_sample.sh` — end-to-end orchestrator.
3. **[DONE]** `codegen/bundle.py` rule added to
   `references/compiler-stage-map.md`: file sits at the
   frontend/backend boundary and can move `sdsc_bundle_gen`
   independently of every Spyre pass. Verify `n_specs` before
   trusting cache-hit predictions.
4. **[DONE]** `sdsc_bundle_gen`-moved-but-no-pass-did clause
   added to `references/interpretation-guide.md`, with the
   #3868 case as the canonical example.
5. **[DONE]** SKILL.md version bumped to 0.2.0; documents the
   isolated-checkout workflow and points at the six-case
   validation.

## Improvements still open for v0.3

1. Add `_monkey_patch.py` rule → `compile_fx_wrapper_setup`.
2. Add a "correctness-fix" signal reader: parse the PR body for
   words like "bug", "fix", "correctness", and lower the default
   level cap by one when found on a coarse_tile/scratchpad/
   restickify change (this would have downgraded #3890 from
   Level 3 to Level 1).
3. Automate the pod-tree alignment gate as a script step, not
   just a policy paragraph.

## Files

- Individual cases: `cases/pr-3871/`, `cases/pr-3873/`,
  `cases/pr-3849/`, `cases/pr-3890/`. Each has
  `01-static-assessment.md`, `02-experiment-plan.md`,
  `03-results.md`, `04-retrospective.md`, plus `target.json`,
  `triage.json`, `prediction.json`, `impact.json`.
- Cross-case notes: [`notes/case-study-summary.md`](notes/case-study-summary.md).
- Selection rationale: [`notes/corpus.md`](notes/corpus.md).
- Full open-PR scan at validation time:
  [`data/scan-2026-08-20.md`](data/scan-2026-08-20.md) and
  [`data/scan-2026-08-20.json`](data/scan-2026-08-20.json).
- Reference workspace-baseline (used for cross-case sanity):
  [`data/workspace-baseline/wa-baseline.json`](data/workspace-baseline/wa-baseline.json).

## Bottom-line question

**If a new torch-spyre PR lands tomorrow, can a fresh Claude
session use this repository to make a disciplined, evidence-backed
decision about whether and how to measure its frontend compiler
impact?**

**Yes**, for the test-only, docs, CI, and activation-specific-
gated cases (which are the majority of PRs). The skill would
correctly output NO_RUN or ACTIVATION_SPECIFIC_IMPACT with static
reasoning and zero device time.

**Partially**, for hot-path changes: the skill will correctly
identify the affected compiler surface and select the right
sentinel, but device-time measurement requires either an
isolated-checkout at the PR's base SHA (currently manual,
documented in `measurement-policy.md` but not automated) or a
pod-tree that happens to align. This is a workflow-infrastructure
gap, not a logic gap.

**Recommended next step**: v0.2 adds an
`isolated_checkout_required` gate to the experiment plan.
