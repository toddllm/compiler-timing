# Patch policy

Discipline for producing fixes when torch-spyre breaks against a
newer PyTorch. The point of this document is to keep the fixes
minimal, hypothesis-driven, and auditable — so that a reviewer can
reconstruct why each line changed, and so that the resulting patches
are candidates for upstream landing (in torch-spyre or in PyTorch)
rather than local monkey-patches that rot.

Violations of this policy invalidate the fix — record what happened
and start over.

## One logically isolated fix at a time

A "break" is a single failure mode with a single root cause. One
traceback that decomposes into three unrelated `AttributeError`s
against three unrelated PyTorch surfaces is three breaks, not one.
Each break gets its own per-break directory (see below) and its own
patch.

Rules:

- Never bundle two independent fixes into one patch, even when they
  are trivially small. If the second fix regresses later, the git
  archaeology is impossible.
- Never fix a break "on the way" to fixing another. Note it, park
  it, and address it as its own break with its own hypothesis chain.
- One patch touches the minimum set of files needed for that fix.
  If a patch spans five files, the diagnosis had better explain why
  five files were required. "I noticed a nearby cleanup" is not a
  reason.
- If two breaks share a root cause (e.g. one PyTorch symbol was
  renamed, and two torch-spyre call sites reference it), the
  observations remain separate but the diagnosis and remediation
  can reference a shared root cause. The single patch touches both
  call sites; the record shows two observations converging into one
  diagnosis. Do not manufacture a "single break" by hand-waving the
  two observations together.

## Six-file per-break record

Every break gets its own directory
`per-break/<NN>-<short-slug>/` containing exactly six files, in
this order:

```
01-observation.md
02-diagnosis-hypothesis.md
03-remediation-plan.md
04-patch.diff             (or 04-patch/ with multiple hunks)
05-verification.md
06-retrospective.md
```

**The first three files MUST land before the fix is applied.**
Hypothesis before fix. This is not a formality — a diagnosis
written after the patch is a rationalization, not a diagnosis. If
you find yourself patching first and documenting after, stop, throw
away the working-tree change, and start the record properly.

### 01-observation.md — what actually broke

Written directly from the run that produced the failure. Contents:

- Exact command that produced the failure (copy-pasted, not
  paraphrased).
- Full traceback (or complete failing output for non-Python failures
  — link errors, compile errors, hangs).
- Environment at the time of failure: PyTorch git SHA, torch-spyre
  git SHA, Python version, pod name, base image digest. Cite
  torch-spyre as `torch-spyre@<short-sha>:<path>:<line>` (private
  repo — no permalink); cite PyTorch as
  `https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>`.
- Whether the failure is deterministic. If it isn't, say so and
  say what fraction of runs reproduce it.

No hypothesis in this file. Observation only. If you catch
yourself writing "this is probably because…", stop — that belongs
in `02-diagnosis-hypothesis.md`.

### 02-diagnosis-hypothesis.md — why it broke

Written before `04-patch.diff` exists on disk. Contents:

- The specific PyTorch commit or PR that introduced the change
  torch-spyre is now incompatible with. Cite by SHA and file:line.
  If you cannot locate it, say so and record what you searched.
- The specific torch-spyre call site(s) that the change breaks.
  Cite each as `torch-spyre@<short-sha>:<path>:<line>`.
- The mechanism: what did PyTorch used to expose that torch-spyre
  relied on? What does PyTorch expose now? What is the smallest
  change that would make torch-spyre compatible again?
- A falsifiable prediction: "if this diagnosis is correct, then
  <observable X> will hold after the patch". `05-verification.md`
  is graded against this prediction.
- Confidence and unknowns. If the diagnosis is a guess, say so —
  the retrospective in `06-` will grade it.

### 03-remediation-plan.md — the shape of the fix, before the fix

Also written before `04-patch.diff` exists. Contents:

- Which of the three fix classes this is (see below):
  LATEST_ONLY_FIX, DUAL_COMPAT_FIX, or SUPPORTED_VERSION_NO_LONGER_PRACTICAL.
- The one to three lines of code that will change, described in
  words (not the diff itself). "Rename `torch._foo` → `torch._bar`
  at `<file>:<line>`" is sufficient. "Refactor the layout module
  to use the new API" is not — that is a design, not a plan.
- Files touched, and why each is required. If a helper or import
  moves, name it.
- Explicitly: **what this fix does NOT change**. Adjacent code
  that a reader might expect to be touched but which the
  hypothesis says should not be. This is the anti-scope-creep
  clause.
- Whether the fix should also be sent upstream (to torch-spyre, or
  to PyTorch if the change was accidental) and if so what form
  that upstream change would take. This is the reason to keep the
  local patch minimal — an upstream candidate must look nothing
  like a hotfix.

### 04-patch.diff — the fix itself

Produced with `git diff` against the exact torch-spyre SHA cited
in `01-observation.md`. Contents:

- Applies cleanly to that SHA. If the tree has drifted, rebase and
  regenerate; do not commit a patch that no longer applies.
- No unrelated hunks (see "Minimal changes" below).
- Matches the plan in `03-remediation-plan.md`. If the patch as
  actually written differs from the plan, either the plan or the
  patch is wrong — update the plan file first, then adjust the
  patch to match, then land both together.

### 05-verification.md — proof it works, and proof it did not break the world

Written after the patch is applied. Contents:

- The same command from `01-observation.md`, re-run against the
  patched tree, with its output. This is the primary check — the
  failure mode from `01-observation.md` must be gone.
- The prediction from `02-diagnosis-hypothesis.md`, evaluated
  against the observed behavior. Explicit "prediction held" or
  "prediction did not hold, here is what happened".
- The declared-supported control (torch-spyre @ its declared
  PyTorch version) still passes. This is the collateral-damage
  check — the fix must not break the supported configuration.
- If this repo's compiler-timing sentinel workloads are runnable
  on the pod, at least one is run to confirm no compile-time
  regression on the supported configuration. If they are not
  runnable, say so; do not skip silently.

### 06-retrospective.md — what the record teaches

Written last. Contents:

- Prediction vs. outcome: did `02-diagnosis-hypothesis.md`
  correctly explain the break? If not, what was actually wrong?
- Was the fix class in `03-remediation-plan.md` the right one, or
  did the patch turn out to require a different class? (E.g. a
  planned LATEST_ONLY_FIX that had to become DUAL_COMPAT_FIX to
  avoid breaking the supported configuration.)
- Upstream-ability: is this patch a candidate for landing in
  torch-spyre or in PyTorch? What would need to change to make it
  upstream-quality?
- What the next similar break should look for. A one-sentence
  lesson the next Claude Code session should pick up.

## Minimal changes

The patch touches only what the diagnosis requires. In particular:

- **No unrelated cleanup.** A drive-by whitespace fix, a docstring
  polish, a rename of an unrelated variable, a `TODO` deletion —
  all forbidden inside a break patch. If you spot something worth
  fixing, note it in `06-retrospective.md` and open a separate
  break (or a plain follow-up task) for it.
- **No reformatting entire files.** Even if the project's formatter
  disagrees with the file, do not run it across the whole file as
  part of this patch. If the fix requires a formatter change,
  contain the reformat to the lines the fix actually modifies.
- **No refactoring on the way to the fix.** If the diagnosis is
  "PyTorch renamed `_foo` to `_bar`", the patch renames the call
  site. It does not also extract a helper function, adjust an
  import order, or convert a `dict` to a `dataclass`.
- **No opportunistic feature adds.** If while reading the code you
  realize a nearby function would benefit from a new argument, that
  is a separate change with its own justification. Never bundle.

The rule of thumb: a reviewer skimming the patch should see only
lines whose necessity is explained by `02-diagnosis-hypothesis.md`.
If a hunk is not explained by the hypothesis, it does not belong
in this patch.

## Fix classes — LATEST_ONLY_FIX vs DUAL_COMPAT_FIX vs SUPPORTED_VERSION_NO_LONGER_PRACTICAL

Every fix is one of exactly three classes. The class is declared
in `03-remediation-plan.md` and re-evaluated in `06-retrospective.md`.

Torch-spyre currently declares its supported PyTorch version in
`pyproject.toml` (currently `torch~=2.13.0`, but re-read the
declaration at runtime — do not hard-code). "Supported" means that
version; "latest" means whatever PyTorch main resolves to when the
experiment runs. The two may or may not overlap.

### LATEST_ONLY_FIX — patch only needs to work against latest PyTorch

Use when:

- The break involves a PyTorch API that changed in a way where the
  new form is strictly better, and there is no good reason for
  torch-spyre to continue calling the old form.
- The patch can naturally use the new API in a way that also works
  on the supported version — either because the new API existed on
  both, or because the supported version already had a compatible
  code path.
- Or: the supported version is close enough to being retired that
  breaking it deliberately would be an acceptable next step (this
  should be a rare judgment call and must be flagged for the
  torch-spyre maintainers, not decided unilaterally in a patch).

The verification step still runs the declared-supported control.
If the LATEST_ONLY_FIX broke it, either escalate to DUAL_COMPAT_FIX
or reclassify as SUPPORTED_VERSION_NO_LONGER_PRACTICAL and get
explicit sign-off.

### DUAL_COMPAT_FIX — patch works against both supported and latest

The default class for most breaks. Use when:

- Torch-spyre's `pyproject.toml` declares a supported PyTorch
  version, and shipping a fix that only works against latest would
  break users on the declared version.
- A common implementation exists that works on both. Prefer this
  strongly over version-conditional code (see below).

A DUAL_COMPAT_FIX may still use version-conditional code as a last
resort, when a common implementation demonstrably will not work.
The `03-remediation-plan.md` must explain what the common
implementation would look like and why it does not work — an
assertion is not enough.

### SUPPORTED_VERSION_NO_LONGER_PRACTICAL — the declared version cannot be preserved

Use when:

- PyTorch has removed a surface torch-spyre requires, and no
  compatibility shim is reasonable within torch-spyre.
- Or: preserving the declared-supported behavior would require
  substantial new machinery (a compat layer, a shim module, a
  parallel code path) whose maintenance cost exceeds the cost of
  bumping the declared version.

This class is **not** a license to skip the fix. It is a signal
that the correct action is to bump torch-spyre's declared PyTorch
version (in `pyproject.toml`), and the patch's `03-remediation-plan.md`
must call out that bump as part of the plan. The patch may be
LATEST_ONLY_FIX in structure but is classified as
SUPPORTED_VERSION_NO_LONGER_PRACTICAL because the version bump is
the load-bearing change.

Never silently classify a break as SUPPORTED_VERSION_NO_LONGER_PRACTICAL
to avoid writing the compat code. The retrospective must show that
the DUAL_COMPAT_FIX path was considered and rejected on evidence.

## Version-conditional code

Acceptable only when a common implementation demonstrably will not
work. Prefer, in order:

1. **Code that naturally works on both versions.** Use the newer
   API if it exists on both, or the older API if it still exists
   on both. The best DUAL_COMPAT_FIX is invisible.
2. **Feature detection via `hasattr` / `getattr` / import
   try/except.** Prefer this to version checks — it survives
   forks, patched builds, and future renames better than a numeric
   comparison.
3. **Version-guarded branches**, last resort. If you must, use
   `torch.__version__` parsed via `packaging.version.Version` (not
   string compare), guard the branch with a comment naming the
   PyTorch PR/commit that introduced the change, and put the branch
   as close as possible to the divergence point.

For any version-conditional code, `03-remediation-plan.md` must
show the common-implementation attempt and why it failed. A patch
that lands version-conditional code without a documented failed
attempt at a common implementation is rejected.

## Not acceptable — the "did not fix it" list

The following are not fixes. If you find yourself doing any of
them, stop and reclassify the break as unresolved.

- **Pin PyTorch back to an older SHA.** This is not a fix; it is
  hiding the problem. The whole point of forward-compat testing is
  to detect the break early. Pinning erases the signal. (If the
  supported PyTorch version genuinely does not need bumping yet
  and the break is on latest-only, the correct move is to record
  the break and defer the fix — with a dated note — not to silently
  pin.)
- **Loosen the experiment.** Reducing the workload, dropping a
  compile flag, or turning off a feature so the failing path is
  not exercised does not fix the underlying incompatibility. The
  next real workload that hits that path will fail again.
- **Skip the failing path.** Adding an early return, a
  `if not <condition>: return`, or a code path that avoids the
  broken call, in order to make the traceback go away, is not a
  fix — it is silent behavior deletion.
- **Broad `except`.** Catching `Exception` (or worse, bare `except:`)
  around the failing call to swallow the error is worse than a
  skip — it also hides future, unrelated failures on that call
  site.
- **Disable the feature.** Setting the feature flag or config
  default to off, so the failing code path is never hit, is not a
  fix. It may be an acceptable temporary mitigation if flagged as
  such — but only alongside a real fix, not instead of one.
- **`xfail` without root cause.** Marking a test as expected-fail
  in order to make CI green is only acceptable when the
  `02-diagnosis-hypothesis.md` has identified the root cause and
  the xfail is a placeholder while the fix is landing elsewhere.
  An xfail without an identified root cause is admitting the break
  is unresolved.
- **Monkey-patch.** Rewriting PyTorch symbols at torch-spyre
  import time — replacing `torch._foo` with a torch-spyre-defined
  function — is not acceptable **unless monkey-patching IS the
  production design** for that surface (some torch-spyre
  integration points genuinely install into torch namespaces at
  import; those are declared as such in the repo). A monkey-patch
  introduced as a hotfix, to work around a break, is forbidden —
  it will collide with future PyTorch changes and it will make the
  next forward-compat run harder, not easier.

If the only fix you can find is on this list, the correct next
step is to write it up as `INSUFFICIENT_FIX_AVAILABLE` in
`06-retrospective.md` and hand the break back to the torch-spyre
maintainers with the full observation + diagnosis, unpatched.
That is a better outcome than a bad fix.
