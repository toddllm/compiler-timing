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
- **Novel-change empirical validation** (the case that tests the
  skill on a change whose direction was NOT already known): **PR
  #3868**. Three attempts:
  1. Marginal-patch on old pod tree — RETRACTED after tightened
     Tier 2 caught the pod-tree `bundle.py` drift.
  2. Tier 3 on old pod (isolated checkouts at exact SHAs) — BLOCKED
     by pod system-lib age; correct `INSUFFICIENT_EVIDENCE`.
  3. Tier 3 on new pod `tdeshane-compiler-timing-dev-v2` (fresh
     `:latest` pull with newer deeptools) — **SUCCESS**. `_C.so`
     built at PR base and head, timing shim instrumented both,
     3+3 paired samples at WB_n4 and WB_n8. Verdict:
     **BACKEND_IMPACT_ONLY** with a documented `sdsc_bundle_gen`
     sub-stage regression. HIGH confidence.

## Cross-case results

| PR | Rank at scan | Level chosen | Verdict | Device time used |
|---:|:---|---:|:---|---:|
| #3871 | NONE | 0 | NO_RUN (correct) | 0 s |
| #3873 | MEDIUM | 1 | ACTIVATION_SPECIFIC_IMPACT (static-only, corroborated by 3-way apply) | 0 s |
| #3849 | MEDIUM | 1 | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift + C-extension absence) | 0 s |
| #3890 | HIGH | 3 → reduced to WB_scaling_pair | INSUFFICIENT_EVIDENCE (measurement blocked by tree drift + system-lib versions) | 100 s (shared reference) |
| local-revadj-prototype | — | 1 | FRONTEND_IMPROVEMENT — **known-positive control**, not a novel test (measured 2.93× @ n=4, 3.68× @ n=8) | ~18 min (reused primary study) |
| #3868 (attempts 1+2) | MEDIUM | 1 → Tier 3 (blocked) | INSUFFICIENT_EVIDENCE (marginal-patch retracted, old-pod Tier 3 blocked by system libs) | ~24 min (retracted) |
| **#3868 (attempt 3, validated)** | MEDIUM | Tier 3 on new pod | **BACKEND_IMPACT_ONLY** — sdsc_bundle_gen +65% / +46%, dxp_standalone −40% / −45% at n=4 / n=8; every Spyre pipeline flat; n_specs unchanged. Net wall clock (`first_call_wall` inclusive) −11% / −24%. HIGH confidence. | ~15 min |

**Total device time**: ~57 minutes across six cases (including one
retracted attempt and one successful Tier 3 rerun).

**Novel-change empirical validation is complete.** PR #3868's clean
base/head A/B was executed against the exact PR SHAs on a substrate
new enough to build `_C.so` at the PR base. The prediction
(`FRONTEND_IMPROVEMENT` via cache hits) was refuted by the
measurement (BACKEND_IMPACT_ONLY via bundle-representation shift).
Both are preserved in the case documents.

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
6. **PR #3868 executed the whole predict→measure→learn loop with
   a validated verdict on a novel change.** Three attempts:
   1. Marginal-patch on old pod tree caught its own alignment error
      when the tightened Tier 2 was applied — pod `bundle.py`
      (`314e022307...`) is not the PR's base `bundle.py`
      (`c93d3ba5d7...`).
   2. Tier 3 retry on old pod correctly failed with
      `INSUFFICIENT_EVIDENCE` when pod system libs were too old to
      rebuild `_C.so` at the PR base.
   3. Tier 3 on a new pod (`tdeshane-compiler-timing-dev-v2` built
      from fresh `:latest` pull) succeeded. `_C.so` rebuilt at PR
      base `2e935f...` and head `a7786ac...` (both 82 MB, both
      import cleanly with `NativePermutationLayoutSolver`). Timing
      shim instrumented both trees without tree modification. 3+3
      paired cold samples at WB_n4 and WB_n8 produced the verdict:
      **BACKEND_IMPACT_ONLY** with a documented `sdsc_bundle_gen`
      sub-stage regression (+65% / +46%), `dxp_standalone`
      improvement (−40% / −45%), `n_specs` unchanged, all Spyre
      pipelines flat. Net wall clock (`first_call_wall` inclusive)
      improves −11% at n=4 and −24% at n=8.
   The prediction (`FRONTEND_IMPROVEMENT` via cache hits, MEDIUM
   confidence) is preserved verbatim in `prediction.json` and
   `01-static-assessment.md`. The measurement disagreed with the
   prediction — cache never populated because OpSpecs are distinct
   across chunks — but the PR still improves wall clock via a
   backend representation shift. Both preserved.
7. **Reduction bug caught and fixed**: the first pass of the
   validated case reported `first_call_wall` and `compile_fx_wrapper`
   from `self_ns`, which excludes nested children. Those columns
   read 1.3 s / 12.6 s at n=4 (the residual after subtracting every
   pass + sdsc + dxp), not the actual wall time (47.8 s / 46.4 s
   inclusive). Fixed in this revision with a new interpretation-guide
   rule "Inclusive vs self" and a sanity-check script
   (`scripts/check_timing_json.py`) that validates every sample JSON
   before reduction. Raw data was unchanged; only the reduction and
   the docs were rewritten.

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
2. **[DONE]** `scripts/check_alignment.sh` — implements the Tier 2
   check: fetches each PR-touched file's base blob from GitHub via
   `gh api` and byte-for-byte compares against the pod's copy.
   Exits 0/1/3 per policy (Tier 2 passes / Tier 2 fails / pod
   missing a touched file).
3. **[DONE]** Isolated-checkout scripts:
   - `scripts/setup_isolated_checkout.sh` — clone at SHA,
     symlink `_C.so`, smoke-test import.
   - `scripts/timing_shim.py` + `scripts/timing_recorder.py` —
     runtime instrumentation for an isolated tree without
     tree modification. Now also (a) defends against missing
     `_has_spyre_device` on newer trees, (b) aliases into
     `torch_spyre._inductor.timing_recorder` so unmodified
     harnesses work, (c) instruments `bundle.generate_bundle`
     (for `sdsc_bundle_gen`) and subprocess `dxp_standalone`
     invocation (for the backend split).
   - `scripts/shim_runner.py` — shim-first harness runner.
   - `scripts/run_isolated_sample.sh` — end-to-end orchestrator.
4. **[DONE]** `codegen/bundle.py` rule added to
   `references/compiler-stage-map.md`: file sits at the
   frontend/backend boundary and can move `sdsc_bundle_gen`
   independently of every Spyre pass. Verify `n_specs` before
   trusting cache-hit predictions.
5. **[DONE]** `sdsc_bundle_gen`-moved-but-no-pass-did clause
   added to `references/interpretation-guide.md`.
6. **[DONE]** Inclusive-vs-self rule added to
   `references/interpretation-guide.md`: enclosing wall-clock
   stages reduce with `inclusive_ns`; `self_ns` is only reported
   when the column name ends in `_self`.
   `scripts/check_timing_json.py` validates the invariants
   (parent-child containment; `self == inclusive − Σchildren`;
   leaves have `self == inclusive`) on every sample JSON before
   reduction.
7. **[DONE]** SKILL.md version bumped to 0.2.0; documents the
   isolated-checkout workflow and points at the six-case
   validation. Invocation section now includes the alignment gate
   check as an explicit step before device work.

## Pod substrate story

The pod tree that ran the original primary study
(`tdeshane-compiler-timing-dev`) uses
`us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest`
pulled on 2026-08-17. Its deeptools install is
`ibm-deeptools 2238.654a8d5`, missing
`spyrecode-host-functions/fast_process_hcm.h`, which PR #3868's
base (2e935f, 2026-08-19) needs to rebuild `_C.so`.

The fix was to stand up a second pod,
`tdeshane-compiler-timing-dev-v2`, from the same image reference
but with `imagePullPolicy: Always` on a fresh spec, which pulled
the newer daily rebuild of `:latest` (deeptools
`2245.85f9432`, dated 2026-08-19, containing the missing header).
The v2 pod scheduled on a different `spyre_pf` node
(`p1-worker-23`) and shares the same PVC-backed `/home/tdeshane`
as the original pod, so all pr3806 primary-study state was
directly accessible. `_C.so` rebuilt cleanly in the isolated
checkouts at both PR base and PR head.

Both pods remain in the cluster. The v2 pod is where the validated
Tier 3 measurement ran. The original pod is preserved with its
primary-study baseline data. Snapshots of the original pod's
scripts + data + iso trees are archived at `.pod-snapshots/`
(gitignored).

## Improvements still open for v0.3

1. Add `_monkey_patch.py` rule → `compile_fx_wrapper_setup`.
2. Add a "correctness-fix" signal reader: parse the PR body for
   words like "bug", "fix", "correctness", and lower the default
   level cap by one when found on a coarse_tile/scratchpad/
   restickify change (this would have downgraded #3890 from
   Level 3 to Level 1).
3. Automate the "refresh pod image" step — a helper that spins up
   a v2 pod from a fresh `:latest` pull, verifies newer deeptools,
   and returns the pod name. Manual today; scripted for v0.3.

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

**Yes**, for hot-path changes: the skill correctly identifies the
affected compiler surface, selects the right sentinel, runs the
alignment gate, and either (a) executes an in-place patch-swap
A/B when Tier 2 blob equality passes, (b) executes Tier 3
isolated-checkout with per-revision `_C.so` rebuild when
Tier 2 fails and the pod substrate is new enough, or (c) reports
`INSUFFICIENT_EVIDENCE` when the substrate cannot support Tier 3.
Demonstrated end-to-end on PR #3868 across three attempts: the
retracted marginal-patch, the old-pod Tier 3 that correctly
reported `INSUFFICIENT_EVIDENCE`, and the new-pod Tier 3 that
produced the validated `BACKEND_IMPACT_ONLY` verdict with HIGH
confidence.

**The skill is validated end-to-end.** Prediction discipline
preserved the pre-measurement `FRONTEND_IMPROVEMENT` hypothesis;
measurement disagreed; the retrospective preserved both and
documented the mechanism (canonical bundle representation shift
rather than spec dedup).
