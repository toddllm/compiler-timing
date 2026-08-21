# Methodology — hypothesis-before-fix discipline

This note is the local expression of the discipline documented in
`.claude/skills/torch-spyre-forward-compat/references/patch-policy.md`
and applies to every case under this validation study. The skill
document is authoritative; this note mirrors it so a fresh Claude
session can walk the study without loading the whole skill first.

## Order of operations

For every case in this study, in this order:

1. **Environment capture — all three states.** Run Stage 0 under
   `SUPPORTED_CONTROL`, `FORWARD_BEFORE_FIX`, and (once a patch
   exists) `FORWARD_AFTER_FIX`. Same pod, same base-image digest,
   fresh `.venv` each state. The three `00-environment.*.json`
   files must agree on pod, image digest, kernel, glibc, and
   python; they must differ only in `pytorch_sha` and (for
   `after`) in the patch identifier.
2. **SUPPORTED_CONTROL walks all six stages.** If any stage fails
   under `SUPPORTED_CONTROL`, the case is void — the pod, image,
   or the pinned torch itself is broken. Refresh the pod and
   retry; do NOT interpret any `FORWARD_BEFORE_FIX` result until
   `SUPPORTED_CONTROL` is green through Stage 6.
3. **FORWARD_BEFORE_FIX walks until it breaks.** The moment
   Stage N fails, HALT the ladder under this state. Do not
   optimistically continue "to see whether Stage N+1 would
   also fail" — that muddles attribution and is explicitly
   forbidden by the skill's `patch-policy.md`.
4. **Write the hypothesis BEFORE the patch.** The hypothesis is a
   file — `failures/stage-N-<slug>/hypothesis.md` — dated,
   containing at least:
   - The verbatim traceback tail from Stage N.
   - A verbatim citation to the torch-spyre line implicated
     (`torch-spyre@a3128985:<path>:<line>`).
   - A verbatim citation to the pytorch line that the torch-spyre
     line depends on
     (`https://github.com/pytorch/pytorch/blob/73961011.../<path>#L<line>`).
   - A named failure-taxonomy category (from
     `references/failure-taxonomy.md`).
   - A one-sentence mechanism claim: *"The break is X because Y."*
   - A named minimum change: *"The minimum patch is Z."*
   - A prediction about the next stage: *"I expect Z to unblock
     Stage N and leave Stages N+1..6 in whichever state they were
     in under SUPPORTED_CONTROL."*
5. **Author the minimum patch.** Only after the hypothesis file is
   committed. The patch:
   - Modifies only files implicated by the first break.
   - Prefers a shim (`hasattr` fallback, try/except import) to a
     rewrite.
   - Is applied against a clean checkout of torch-spyre at
     `a31289852...`, never against a tree that already carries
     unrelated changes.
   - Contains no cleanups, formatting fixes, or "while I'm here"
     changes.
   - Lands as `patches/case-<N>.patch`.
6. **FORWARD_AFTER_FIX walks the ladder.** Under the patched
   torch-spyre + same forward torch. The acceptance criterion is
   strict stage advancement: `FORWARD_AFTER_FIX` must reach at
   least Stage N+1, meaning the recorded Stage-N break is
   resolved. Whether N+1 itself passes or fails is a separate
   question.
7. **If Stage N+1 fails under FORWARD_AFTER_FIX, open a new
   case.** Do not extend the current patch to cover it. Close
   the current case with its Stage-N patch as remediation; open
   a new case for the Stage-N+1 break with its own hypothesis
   file, own minimum patch, and own three-state walk.
8. **`NO_BREAK` is a valid verdict.** If `FORWARD_BEFORE_FIX`
   reaches Stage 6 green, the case's verdict is `NO_BREAK`. No
   patch is authored, no `FORWARD_AFTER_FIX` state is run (there
   is nothing to fix), and the case's `case.json` records
   `no_break: true` with per-stage evidence pointers.

## Prohibited shortcuts

Verbatim from the skill's `patch-policy.md` and
`SKILL.md` — reproduced here because they are the shortcuts
this validation study will be judged on:

- **Pinning around the break.** Editing torch-spyre's
  `pyproject.toml` to declare `torch<2.14` so `pip` refuses the
  install is not a fix; it re-states the pin and hides the
  question this skill exists to answer.
- **Skipping stages.** Jumping from Stage 3 to Stage 6 because
  "the interesting break is at compile time" abandons the
  discipline; the earlier stages are cheap and their state
  matters for attribution.
- **Bundling patches.** One patch per break; never a
  forward-compat patch alongside a refactor.
- **Skipping FORWARD_BEFORE_FIX.** Going straight from
  `SUPPORTED_CONTROL` to `FORWARD_AFTER_FIX` because "we know the
  patch works" — the failure signature at `FORWARD_BEFORE_FIX` is
  the primary evidence the case exists to record.
- **Simulating on a stale pod.** Reusing a pod whose base-image
  digest predates the recorded environment, or whose `.venv` has
  been mutated across cases. Every case gets a fresh `.venv`.
- **Guessing HEADs.** Every case resolves pytorch and torch-spyre
  HEADs at run time via `git ls-remote` and records the resolved
  SHAs. Nothing is hard-coded.
- **Declaring `NO_BREAK` from CI green.** `NO_BREAK` requires
  all six stages green under `FORWARD_BEFORE_FIX` on the
  recorded pod with the recorded environment. CI is not
  evidence.
- **Filling `TODO: pod run 2026-08-21` from prior belief.** The
  scaffold's placeholders are populated only by the pod run's
  own JSON outputs. If a placeholder is filled from a previous
  study, from memory, or from what "should" happen, the
  validation is void.

## Discipline checklist per case

Before marking a case complete:

- [ ] `SUPPORTED_CONTROL` is green through Stage 6, JSON on disk.
- [ ] `FORWARD_BEFORE_FIX` halted at the first failure and its
      per-stage JSON is on disk up to and including that stage.
- [ ] `failures/stage-N-<slug>/hypothesis.md` was committed
      BEFORE `patches/case-<N>.patch`.
- [ ] The patch cites both a torch-spyre line and a pytorch line
      verbatim in the required forms.
- [ ] `FORWARD_AFTER_FIX` reached at least Stage N+1.
- [ ] `case.json` validates against
      `.claude/skills/torch-spyre-forward-compat/references/case-schema.json`.
- [ ] Any subsequent-stage failure is filed as a NEW case, not
      folded into this one.
