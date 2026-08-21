---
name: torch-spyre-forward-compat
description: "Answer the empirical question of whether torch-spyre still builds and imports against a forward (newer) PyTorch main than the version torch-spyre currently pins, driving a fresh Spyre pod through a staged validation ladder — install → import → device presence → op registration → one small compile — and treating every deviation from a supported-torch control as a distinct, hypothesis-first case. Use when the user asks 'does torch-spyre work on pytorch main?', 'what breaks when we bump torch?', 'can we get ahead of the next torch bump?', 'characterize torch-spyre-vs-pytorch-main breakage', or 'produce a forward-compat matrix'. This skill does NOT chase compile-time regressions (see frontend-compiler-impact for that) — it answers the prior question of whether the stack survives the forward step at all."
version: 0.1.0
---

# Torch-Spyre Forward-Compat Skill

**Mission.** The prompt this skill answers is verbatim: *"Does
torch-spyre still build and import against a forward (newer) PyTorch
main than the version torch-spyre currently pins, and if not, what
exactly breaks, why, and what is the minimum patch that unbreaks it?"*
`frontend-compiler-impact` answers "did this torch-spyre change move
compile time?" — assuming torch-spyre works. This skill answers the
prior question: does torch-spyre work at all against a torch newer
than the pinned range?

The primary output of a case is not a benchmark — it is a **case
document** that records what torch we tried, what torch-spyre we
tried, what supported-torch control we established, what broke first,
what the minimum hypothesis-first patch was, and where the next break
would surface if the current break were papered over.

## Distinct from `frontend-compiler-impact`

| axis | `frontend-compiler-impact` | this skill |
|---|---|---|
| question | did compile time move? | does the stack import/run? |
| assumes | torch-spyre works | torch-spyre may not work |
| target of change | a torch-spyre PR | a bumped pytorch commit |
| primary artifact | `impact.json` + timing tables | `case.json` per break + patches |
| device time | required at Level ≥1 | Stages 5-6 only |
| verdict space | 7 timing verdicts | 6 failure categories + `NO_BREAK` |

The two skills will compose eventually — a torch bump that survives
all six stages here becomes the input to a `frontend-compiler-impact`
scaling comparison — but for v0.1 they are run independently. See the
final section for the deferred integration.

## Three-state control philosophy

Every empirical case in this skill compares **three** builds, not two.
Two builds cannot distinguish "torch-spyre is fundamentally broken" from
"the newer torch broke it." Three builds can.

```
SUPPORTED_CONTROL     — torch pinned per torch-spyre's pyproject.toml
                         (currently declares torch~=2.13.0; scripts
                         re-read this at runtime, not hard-coded)
                         Must be GREEN through Stage 6 for the case
                         to have signal. If SUPPORTED_CONTROL is red,
                         the pod or the pin itself is broken and the
                         forward-compat question cannot be answered.

FORWARD_BEFORE_FIX    — torch installed from pytorch main HEAD (e.g.
                         73961011bf64f1c04b3291bf90ac1dbbe197c2ca as
                         of 2026-08-21; scripts resolve HEAD at run
                         time), torch-spyre UNPATCHED. This is the
                         "does it break?" run and the honest baseline
                         that later fixes are compared to.

FORWARD_AFTER_FIX     — same forward torch, torch-spyre with the
                         minimum patch applied. This is the "did the
                         hypothesis-first fix work?" run.
```

All three states are required. Without SUPPORTED_CONTROL, a Stage-N
failure could be an environmental fluke (bad pod, missing NIXL, cache
poisoning) rather than a forward-torch issue; green control rules
that out. Without FORWARD_BEFORE_FIX, the FORWARD_AFTER_FIX result is
unanchored — you cannot prove the patch was necessary if you never
saw the unpatched break, and this is the most common shortcut the
skill refuses. Without FORWARD_AFTER_FIX, a break is described but
not addressed; the case is incomplete.

The three states MUST use the same pod, same base image digest, and
the same fresh `.venv`, differing only in (torch source, patched?).
See `references/three-state-protocol.md`.

## Validation ladder — Stages 0-6

Progression is ordered and terminates on the first stage that fails
under FORWARD_BEFORE_FIX. Do not skip.

- **Stage 0 — Environment capture.** Record pod name (e.g.
  `tdeshane-forward-compat-2026-08-21`), namespace (`a5-deepview`),
  base image digest (resolve `us.icr.io/wxpe-cicd-internal/amd64/
  torch-aiu-runtime-dev:latest` to its immutable `@sha256:...` digest
  at pod-creation time), kernel, glibc, python, pip, pytorch commit
  SHA, torch-spyre commit SHA (currently `a3128985...` on main), the
  `torch~=X.Y` declaration parsed from `pyproject.toml` at runtime
  (never hard-coded), and NIXL plugin dir. Produces
  `00-environment.json`. Runs for all three control states.

- **Stage 1 — Torch install.** Under FORWARD state, install torch
  from the current pytorch main HEAD. Success = `pip install` exits 0
  AND `python -c 'import torch; print(torch.__version__,
  torch.version.git_version)'` prints a version matching the requested
  SHA. Failure taxonomy: `WHEEL_UNAVAILABLE`, `BUILD_FAILURE`,
  `TORCH_ONLY_IMPORT_FAILURE`.

- **Stage 2 — Torch-spyre install.** With forward torch already
  present, run `pip install -e .` (or the equivalent editable install)
  from the torch-spyre tree. Success = install exits 0. Common
  failure: `PIN_CONFLICT` (pip refuses because torch-spyre's
  `torch~=2.13.0` declaration excludes the forward wheel).

- **Stage 3 — Import.** `python -c 'import torch_spyre'` in a fresh
  process. Success = exit 0 with no ImportError, no AttributeError, no
  C-extension symbol errors. Failure categories: `PYTHON_API_BREAK`
  (Python-level symbol torch removed/renamed),
  `C_EXTENSION_ABI_BREAK` (`_C.so` cannot resolve a torch symbol),
  `SIDE_EFFECT_BREAK` (something at import time — a decorator, a
  registration call — raises).

- **Stage 4 — Device presence.** Verify the spyre device is
  registered and enumerable — `torch.device('spyre')` constructs
  without error and `torch_spyre` reports at least one device (or
  reports the expected "no hardware present" state matching
  SUPPORTED_CONTROL). This exercises the PrivateUse1 backend
  registration path and catches a class of breaks that Stage 3 misses.

- **Stage 5 — Op registration / dispatcher sanity.** Enumerate the
  ops that torch-spyre registers against the torch dispatcher and
  verify they resolve. Do not compile anything yet; this stage is
  cheap and separates dispatcher-level breaks from graph-level ones.

- **Stage 6 — Smoke compile.** ONE small `torch.compile(...)` of a
  minimal function on the spyre device (or, if the pod has no
  hardware, on CPU with the spyre backend selected as far as it can
  be exercised). This is the last stage and the only one that costs
  meaningful device time. A green Stage 6 across
  SUPPORTED_CONTROL / FORWARD_AFTER_FIX is the acceptance criterion
  for "forward-compat restored for this bump."

At every stage: run under all three control states in order
(SUPPORTED_CONTROL first, so a broken pod is caught before any
forward-torch work); on failure DO NOT advance to the next stage
under that control state (record the failure and enter the patching
loop); record `stage_N.json` per state capturing exit code, stdout
tail, stderr tail, traceback if any, and timing. Detailed stage
recipes in `references/validation-ladder.md`.

## Failure taxonomy

See `references/failure-taxonomy.md` for the authoritative form
(each category includes a diagnostic recipe and a canonical example).
Summary:

| category | stage that first surfaces it | example signature |
|---|---|---|
| `WHEEL_UNAVAILABLE` | 1 | no wheel for python/platform/CUDA combo at requested SHA |
| `BUILD_FAILURE` | 1 | source build of torch main fails (usually C++ toolchain) |
| `PIN_CONFLICT` | 2 | `torch-spyre` refuses to install because `torch~=2.13.0` excludes the forward version |
| `PYTHON_API_BREAK` | 3 | `AttributeError`/`ImportError` on a torch Python symbol torch-spyre imports |
| `C_EXTENSION_ABI_BREAK` | 3 | `_C.so` fails to resolve a torch C++ symbol (undefined symbol, ABI drift) |
| `SIDE_EFFECT_BREAK` | 3 | import-time registration/decorator call raises against the newer torch |
| `DEVICE_REGISTRATION_BREAK` | 4 | PrivateUse1 / backend registration API drift |
| `DISPATCHER_BREAK` | 5 | op schema or dispatcher registration API changed |
| `GRAPH_LEVEL_BREAK` | 6 | dynamo/inductor API drift; graph capture fails |
| `NO_BREAK` | n/a | all six stages green under FORWARD_BEFORE_FIX; the case is "clean forward bump" |

`NO_BREAK` is a valid, valuable verdict — it means the current torch
main is safe to point torch-spyre at with no code changes and only a
pin bump.

## Patching policy

Full policy in `references/patch-policy.md`. Non-negotiable rules:

- **One break at a time.** When Stage N fails, patch ONLY that break.
  Do not preemptively patch things you suspect might fail at Stage
  N+1. Preemptive patches muddle attribution and make it impossible
  to count how many independent breaks a torch bump introduces.
- **Hypothesis before fix.** Every patch is preceded by a written
  hypothesis: "The break is X because Y; the minimum change is Z; I
  expect Z to unblock Stage N and leave Stages N+1..6 untouched." The
  hypothesis is written to the case document BEFORE the patch is
  authored.
- **Minimum patch.** Prefer a shim (`hasattr` fallback, try/except
  import) over a rewrite. Prefer a rewrite of one call site over a
  rewrite of a module. Never bundle unrelated cleanups into a
  forward-compat patch.
- **Revert-clean.** Every patch is applied to a clean checkout of
  torch-spyre at the recorded SHA (`a31289985...` in the current
  example), never onto a tree that already has unrelated changes.
- **Cite verbatim.** Every claim about torch-spyre or pytorch source
  cites the actual line. Torch-spyre is PRIVATE, so citations take
  the form `torch-spyre@<short-sha>:<path>:<line>`. PyTorch is
  public, so citations take the form
  `https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>`.

If a patch's FORWARD_AFTER_FIX run passes Stage N but reveals a
DIFFERENT break at Stage N+1, that is a **new case**, not a
continuation of the current one. Close the current case with the
Stage-N patch as its remediation and open the next case for Stage
N+1.

## What NOT to do

The following are explicitly not acceptable as remediation, from the
prompt:

- **Pinning around the break.** Editing torch-spyre's `pyproject.toml`
  to declare `torch<2.14` so pip refuses the install is not a fix; it
  is a re-statement of the pin and hides the question the skill
  exists to answer.
- **Skipping stages.** Jumping from Stage 3 to Stage 6 because "the
  interesting break is at compile time" abandons the discipline; the
  earlier stages are cheap and their state matters for attribution.
- **Bundling patches.** One patch per break; never a forward-compat
  patch alongside a refactor.
- **Skipping FORWARD_BEFORE_FIX.** Going straight from
  SUPPORTED_CONTROL to FORWARD_AFTER_FIX because "we know the patch
  works" — the failure signature at FORWARD_BEFORE_FIX is the primary
  evidence the case exists to record.
- **Simulating on a stale pod.** Reusing a pod whose base image
  digest predates the recorded environment, or whose `.venv` has been
  mutated across cases. Every case gets a fresh `.venv`.
- **Guessing torch's HEAD.** Every case resolves pytorch and
  torch-spyre HEADs at runtime via `git ls-remote` and records the
  resolved SHA. Never hard-code a SHA into a script.
- **Declaring `NO_BREAK` from CI green.** `NO_BREAK` requires all six
  stages green in this skill's ladder, on the recorded pod, with the
  recorded environment. CI passing is not evidence.

## How to invoke — quick start

Fresh compatibility experiment against current pytorch main and
current torch-spyre main:

```
# 0. Environment capture (records pod, image digest, resolves both
#    HEADs from GitHub, parses torch-spyre's pyproject.toml pin at
#    runtime — nothing hard-coded).
scripts/00_capture_env.sh tdeshane-forward-compat-2026-08-21 a5-deepview

# 1. Establish SUPPORTED_CONTROL at torch-spyre's declared pin.
#    Must reach Stage 6 green or the experiment is void.
scripts/01_run_supported_control.sh

# 2. FORWARD_BEFORE_FIX — reinstall torch from pytorch main HEAD,
#    keep torch-spyre unpatched, walk the ladder until it breaks.
scripts/02_run_forward_before_fix.sh

# 3. Author the hypothesis-first patch under patches/case-NNNN/ and
#    write the case document. (Manual — no script writes patches.)

# 4. FORWARD_AFTER_FIX — patched torch-spyre against the same
#    forward torch. Expected to advance at least one stage past
#    the FORWARD_BEFORE_FIX break.
scripts/03_run_forward_after_fix.sh patches/case-NNNN/

# 5. Emit machine-readable case record.
scripts/04_emit_case_json.py cases/case-NNNN/ > cases/case-NNNN/case.json
```

Every script re-reads `torch-spyre/pyproject.toml` at runtime to
recover the currently-declared torch pin. Do not hard-code the pin.

## Machine-readable case format

Each case emits a `case.json` conforming to
`references/case-schema.json`. It records pod name, namespace, base
image digest; pytorch and torch-spyre SHAs at the time of the case;
the parsed pin from `pyproject.toml`; per-stage results under all
three control states; the first-break stage under FORWARD_BEFORE_FIX
and its failure-taxonomy category; the patch (or `null` if
`NO_BREAK`); the FORWARD_AFTER_FIX outcome; and verbatim citations
for every source claim. `case.json` is the durable artifact —
Markdown case documents may paraphrase, but `case.json` is the
primary record.

## Empirical validation

This skill is **v0.1** and its correctness has not yet been
validated by a real case. The acceptance test is
`analyses/2026-08-forward-compat-skill-validation/`, which drives
one real compatibility experiment against pytorch main
`7396101...` and torch-spyre main `a3128985...` end-to-end and
checks whether all six stages are exercised in order under all
three control states, the first FORWARD_BEFORE_FIX break is
categorised via the taxonomy and cited to specific torch-spyre and
pytorch lines, the hypothesis-first patching policy produces a
small revert-clean patch (shim-first where possible),
FORWARD_AFTER_FIX advances at least one stage past
FORWARD_BEFORE_FIX, and `case.json` validates against
`references/case-schema.json`. Failures encountered during the
validation study drive the v0.2 revision. No claim in this
SKILL.md should be read as validated until the validation study
lands.

## Future composition with `frontend-compiler-impact` (deferred)

Once this skill produces a `NO_BREAK` verdict for a given
(pytorch_sha, torch_spyre_sha) pair, that pair becomes a candidate
input to `frontend-compiler-impact`: measure whether the forward
torch bump moves compile time, using the same three-state
philosophy adapted to timing (SUPPORTED_CONTROL / FORWARD (no
change to torch-spyre) / FORWARD_WITH_TORCH_SPYRE_UPGRADE). The
composed skill would answer both "does it work?" and "does it
still perform?" in one workflow.

**For v0.1 this composition is NOT integrated.** The two skills are
invoked independently. `case.json` from this skill will be
readable by a future `frontend-compiler-impact` extension, but
that extension is not written and no script in this skill imports
from `frontend-compiler-impact`. Getting v0.1 correct in isolation
matters more than a premature contract between the two.

## Files under this skill

```
.claude/skills/torch-spyre-forward-compat/
    SKILL.md                          — this file
    references/
        three-state-protocol.md       — SUPPORTED / FORWARD_BEFORE /
                                        FORWARD_AFTER discipline
        validation-ladder.md          — Stages 0-6 detailed recipes
        failure-taxonomy.md           — categories, diagnostics
        patch-policy.md               — one-break, hypothesis-first,
                                        minimum-patch, revert-clean
        case-schema.json              — machine-readable case format
        case-templates/               — per-stage case doc templates
    scripts/
        00_capture_env.sh             — record pod, image digest,
                                        resolve both HEADs, parse pin
        01_run_supported_control.sh   — ladder under SUPPORTED_CONTROL
        02_run_forward_before_fix.sh  — ladder under FORWARD_BEFORE_FIX
        03_run_forward_after_fix.sh   — ladder under FORWARD_AFTER_FIX
        04_emit_case_json.py          — assemble case.json
        resolve_pytorch_head.sh       — git ls-remote pytorch main
        resolve_torch_spyre_head.sh   — git ls-remote torch-spyre main
        parse_torch_pin.py            — read pyproject.toml at runtime
        ladder_runner.py              — Stage-0..6 harness
```

## What this skill is NOT

- **Not a torch bumper.** It answers whether a bump is safe; it does
  not land pin changes in `pyproject.toml`.
- **Not a performance tool.** Stage 6 is a smoke compile, not a
  benchmark. Compile-time regression is `frontend-compiler-impact`.
- **Not authoritative on pytorch internals.** When a failure
  implicates a pytorch commit, the skill cites the commit and reports
  the diagnosis; it does not propose changes to pytorch.
- **Not a substitute for CI.** The skill runs one pod, one time, per
  case. CI can and should run this ladder on schedule; this skill's
  discipline is what a CI job should encode, not what it replaces.
