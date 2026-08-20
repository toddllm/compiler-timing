# Frontend-compiler-impact skill — validation summary

## What was validated

The `.claude/skills/frontend-compiler-impact/` skill (see the top-
level [`.claude/skills/frontend-compiler-impact/SKILL.md`](../../
.claude/skills/frontend-compiler-impact/SKILL.md)) was applied to
four currently-open torch-spyre PRs, selected to cover the four
verdict classes the skill defines:

- Negative control (test-only): **PR #3871**.
- Activation-specific (gated feature): **PR #3873**.
- Ambiguous (validation on hot subsystem): **PR #3849**.
- Frontend-relevant (hot-path correctness fix): **PR #3890**.

## Cross-case results

| PR | Rank at scan | Level chosen | Verdict | Device time used |
|---:|:---|---:|:---|---:|
| #3871 | NONE | 0 | NO_RUN (correct) | 0 s |
| #3873 | MEDIUM | 1 | ACTIVATION_SPECIFIC_IMPACT (static-only, corroborated by 3-way apply) | 0 s |
| #3849 | MEDIUM | 1 | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift + C-extension absence) | 0 s |
| #3890 | HIGH | 3 → reduced to WB_scaling_pair | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift) | 100 s (shared reference) |

**Total device time**: 100 seconds across four PRs.
**Naive baseline** (run all sentinels for all PRs): ~108 minutes.
**Device time saved**: ~106 minutes.

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
   The `INSUFFICIENT_EVIDENCE` verdict is used honestly.

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

## Improvements to make in v0.2

1. Add a `pod_tree_alignment_check` step: before scheduling
   Level ≥1, verify the pod tree can apply the PR's diff
   (dry-run `git apply --check`), else escalate to
   isolated-checkout or downgrade to static-only.
2. Add `_monkey_patch.py` rule → `compile_fx_wrapper_setup`.
3. Add a "correctness-fix" signal reader: parse the PR body for
   words like "bug", "fix", "correctness", and lower the default
   level cap by one when found on a coarse_tile/scratchpad/
   restickify change.
4. Document the "isolated-checkout required" workflow explicitly
   in `measurement-policy.md` with a step-by-step setup script
   for cases where the pod tree doesn't align.

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
