# Frontend-compiler-impact skill — validation summary

## What was validated (v0.2)

The `.claude/skills/frontend-compiler-impact/` skill (see
[`SKILL.md`](../../.claude/skills/frontend-compiler-impact/SKILL.md))
was applied to six cases. The current inventory is:

- Negative control (test-only): **PR #3871**.
- Activation-specific (gated feature): **PR #3873**.
- Ambiguous (validation on hot subsystem): **PR #3849**.
- Frontend-relevant (hot-path correctness fix): **PR #3890**.
- **Known-positive control** (end-to-end measurement flow on a
  change whose direction was already established by the primary
  study): `local-revadj-prototype`. This exercised the full
  predict→measure→verdict pipeline on data the skill's authors
  already knew the answer to, so it validates the machinery but is
  not a test of predicting a novel change.
- **Novel-change empirical validation attempt**: **PR #3868**. This
  is the case that would test the skill on a change the authors did
  NOT know the answer to. The initial marginal-patch measurement was
  RETRACTED after the alignment-gate policy was tightened; the Tier 3
  isolated-checkout retry was blocked by pod system-lib age; final
  verdict `INSUFFICIENT_EVIDENCE`.

## Cross-case results

| PR | Rank at scan | Level chosen | Verdict | Device time used |
|---:|:---|---:|:---|---:|
| #3871 | NONE | 0 | NO_RUN (correct) | 0 s |
| #3873 | MEDIUM | 1 | ACTIVATION_SPECIFIC_IMPACT (static-only, corroborated by 3-way apply) | 0 s |
| #3849 | MEDIUM | 1 | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift + C-extension absence) | 0 s |
| #3890 | HIGH | 3 → reduced to WB_scaling_pair | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift + system-lib versions) | 100 s (shared reference) |
| local-revadj-prototype | — | 1 | FRONTEND_IMPROVEMENT — **known-positive control**, not a novel test (measured 2.93× @ n=4, 3.68× @ n=8) | ~18 min (reused primary study) |
| #3868 | MEDIUM | 1 → attempted Tier 2 → escalated Tier 3 → blocked | **INSUFFICIENT_EVIDENCE**; marginal-patch data retained but not authoritative | ~24 min (marginal-patch attempt, retracted) |

**Total device time**: ~42 minutes across six cases.

**Novel-change empirical validation is not yet complete.** The v0.2
skill design, prediction discipline, isolated-checkout tooling, and
tightened alignment policy are all in place. What remains is running
`PR #3868` — or another currently-open non-coarse-tile frontend PR
— on a pod substrate that is new enough to build the PR's `_C.so`
against its actual base.

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
5. **`local-revadj-prototype` as a known-positive control** — the
   full flow (prediction → sentinel selection → measurement →
   verdict → retrospective) ran end-to-end on a change whose
   direction was already established in the primary study. This
   validates the machinery (the shim, the paired sweep, the
   verdict decision tree) but does not test the skill's ability to
   predict a change it did not already know the answer to.
6. **PR #3868 caught its own alignment error and was retracted**.
   The initial marginal-patch measurement produced a plausible
   `BACKEND_IMPACT_ONLY` classification. Investigation showed the
   pod's `bundle.py` differs from the PR's actual base
   (`c93d3ba5d7...` at PR base vs `314e022307...` at pod), and the
   pod predates a pool-allocation refactor that the PR base
   already carries. The alignment policy was tightened to require
   per-touched-file blob equality (see
   `references/measurement-policy.md` Tier 2). The Tier 3 retry
   at the exact PR base/head SHAs was blocked by pod system-lib
   age — rebuilding `_C.so` fails on missing
   `spyrecode-host-functions/fast_process_hcm.h`. Final verdict:
   `INSUFFICIENT_EVIDENCE`. The prediction is preserved verbatim;
   the marginal-patch data is preserved as an exploratory
   supplementary finding, clearly labeled.

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
   `references/measurement-policy.md` — three tiers, checked
   BEFORE scheduling device work. Tier 2 now requires
   **per-touched-file blob equality** with the PR's actual base,
   not just "diff applies cleanly". This is the fix motivated by
   the #3868 retraction.
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
   added to `references/interpretation-guide.md`.
5. **[DONE]** SKILL.md version bumped to 0.2.0; documents the
   isolated-checkout workflow and points at the six-case
   validation.

## What's still needed for a full GO

A **clean isolated-checkout base/head measurement of a currently-open
frontend PR** requires a pod with system libraries new enough to
build `_C.so` at the PR's base SHA. The current pod
(`tdeshane-compiler-timing-dev`) is not new enough: `_C.so` rebuild
fails on a missing `spyrecode-host-functions/fast_process_hcm.h`
header. Options:

1. Refresh the compiler-timing dev pod's base image to a newer
   `vllm-spyre-dev` snapshot that includes the newer deeptools
   headers.
2. Find a currently-open frontend PR whose base SHA is close enough
   to the pod SHA (`a9316b3`) that Tier 2 alignment holds
   byte-for-byte on every touched file. Given the age gap (pod
   dated 2026-08-17, PRs typically branch from `main` at more
   recent SHAs), this may not be possible without a pod refresh.

## Improvements still open for v0.3

1. Add `_monkey_patch.py` rule → `compile_fx_wrapper_setup`.
2. Add a "correctness-fix" signal reader: parse the PR body for
   words like "bug", "fix", "correctness", and lower the default
   level cap by one when found on a coarse_tile/scratchpad/
   restickify change (this would have downgraded #3890 from
   Level 3 to Level 1).
3. Automate the tightened pod-tree alignment gate as a script step
   that fetches each PR-touched file's base blob and cmps.

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
identify the affected compiler surface, select the right sentinel,
and run the alignment gate. When the pod substrate can build the
PR's `_C.so`, it will produce a valid A/B verdict. When the pod
substrate cannot, it will halt at `INSUFFICIENT_EVIDENCE` — the
correct answer, not a fabricated verdict. This was demonstrated
end-to-end on PR #3868: the skill caught its own alignment error,
tightened the policy, and reported `INSUFFICIENT_EVIDENCE` when
the Tier 3 retry was blocked.

**What's still needed for full GO**: a compiler-timing dev pod on
a newer base image (or a currently-open PR whose base SHA aligns
byte-for-byte with the pod on every touched file). Either
condition would let the same skill run to a verdict on a novel
change. The skill logic and tooling are in place.
