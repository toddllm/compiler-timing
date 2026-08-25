---
name: torch-spyre-forward-compat
description: "Answer the empirical question of whether torch-spyre still builds and imports against a forward (newer) PyTorch than the version torch-spyre currently pins, driving a fresh Spyre pod through a staged validation ladder — install → import → device presence → op registration → one small compile — and treating every deviation from a supported-torch control as a distinct, hypothesis-first case. Use when the user asks 'does torch-spyre work on pytorch main?', 'what breaks when we bump torch?', 'can we get ahead of the next torch bump?', 'characterize torch-spyre-vs-pytorch-main breakage', or 'produce a forward-compat matrix'. This skill does NOT chase compile-time regressions (see frontend-compiler-impact for that) — it answers the prior question of whether the stack survives the forward step at all."
version: 0.2.0
---

# Torch-Spyre Forward-Compat Skill

**Mission.** *"Does torch-spyre still build and import against a
forward (newer) PyTorch than the version torch-spyre currently pins,
and if not, what exactly breaks, why, and what is the minimum patch
that unbreaks it?"* `frontend-compiler-impact` answers "did this
torch-spyre change move compile time?" — assuming torch-spyre works.
This skill answers the prior question: does torch-spyre work at all
against a torch newer than the pinned range?

The primary output of a case is not a benchmark — it is a **case
document** that records what torch was tried, what torch-spyre was
tried, what supported-torch control was established, what broke first,
what the minimum hypothesis-first patch was, and where the next break
would surface if the current break were papered over.

## Status — v0.2 with two validated remediations

- **F6** (`cases/historical-replay-pt213/`) — historical replay of the
  torch 2.13 upgrade. The skill independently derived a
  byte-identical fix for a real upstream C++ API break
  (`c10::impl::PyObjectSlot::load_pyobj_interpreter` removed in torch
  2.13; replaced with `c10::impl::getGlobalPyInterpreter()`). Verified
  as `DUAL_COMPAT_FIX` — the same one-line change works cleanly on
  both torch 2.12 and torch 2.13. See
  `cases/historical-replay-pt213/F6-pyobj-slot-api-rename-independently-derived.md`.
- **F3 live current-main** (`cases/live-current-main-F3/`) — the skill
  diagnosed and fixed a **currently-live** re-entrancy bug in
  `torch_spyre/__init__.py` at torch-spyre `main` (`8aba5bc...`, one
  day old at time of run). All 7 import-matrix cases pass post-fix;
  Stage 2 real `torch.compile(backend="inductor")` with Spyre-device
  tensors produces correct output. See
  `cases/live-current-main-F3/README.md`.

Both cases followed rule zero (classify before editing), the
hypothesis-first patch policy, and the three-state protocol. The
skill has not yet reproduced a `SEMANTIC_COMPILER_BREAK` end-to-end
(see F7 in the historical-replay case for the partial attempt and
what a full reproduction would require).

## Distinct from `frontend-compiler-impact`

| axis | `frontend-compiler-impact` | this skill |
|---|---|---|
| question | did compile time move? | does the stack import/run? |
| assumes | torch-spyre works | torch-spyre may not work |
| target of change | a torch-spyre PR | a bumped pytorch commit |
| primary artifact | `impact.json` + timing tables | `case.json` per break + patches |
| device time | required at Level ≥1 | Stages 5-6 only |
| verdict space | 7 timing verdicts | 12+ failure categories + `NO_BREAK` |

The two skills compose eventually — a torch bump that survives all
six stages here becomes the input to a `frontend-compiler-impact`
scaling comparison — but for v0.2 they are still run independently.
See the final section for the deferred integration.

## Three-state control philosophy

Every empirical case in this skill compares **three** builds, not two.
Two builds cannot distinguish "torch-spyre is fundamentally broken"
from "the newer torch broke it." Three builds can.

```
SUPPORTED_CONTROL     — torch pinned per torch-spyre's pyproject.toml
                         (currently declares torch~=2.13.0; scripts
                         re-read this at runtime, not hard-coded).
                         Must be GREEN through every stage the case
                         wants to reach — at minimum Stages 0-3 (the
                         automated ladder). If SUPPORTED_CONTROL is red,
                         the pod, the pin, or the pipeline itself is
                         broken and the forward-compat question
                         cannot be answered.

FORWARD_BEFORE_FIX    — forward torch, torch-spyre UNPATCHED. This is
                         the "does it break?" run and the honest
                         baseline that later fixes are compared to.
                         Forward torch is one of two modes, recorded
                         per-case:
                           * EXACT_UPSTREAM_MAIN — torch built from a
                             recorded pytorch main SHA (3h build; use
                             when precision matters).
                           * NIGHTLY_PROXY — torch from
                             pytorch.org/whl/nightly at the run start.
                             Records the embedded git SHA. Faster;
                             used for the F6/F3 v0.2 runs. Both modes
                             are legitimate; the mode is a required
                             field in case.json.

FORWARD_AFTER_FIX     — same forward torch, torch-spyre with the
                         minimum patch applied. This is the "did the
                         hypothesis-first fix work?" run.
```

All three states are required. Without SUPPORTED_CONTROL, a Stage-N
failure could be an environmental fluke; green control rules that
out. Without FORWARD_BEFORE_FIX, the FORWARD_AFTER_FIX result is
unanchored — you cannot prove the patch was necessary if you never
saw the unpatched break. Without FORWARD_AFTER_FIX, a break is
described but not addressed; the case is incomplete.

The three states MUST use the same pod, same base image digest, and
the same fresh `.venv`, differing only in (torch source, patched?).
See `references/environment-policy.md` for the enforcement details.

## Validation ladder — Stages 0-6

Progression is ordered and terminates on the first stage that fails
under FORWARD_BEFORE_FIX. Do not skip. Detailed recipes live in
`references/validation-ladder.md` — this is the summary.

- **Stage 0 — ENVIRONMENT.** Runtime smoke: `import torch`, `import
  torch_spyre`, `torch.spyre.device_count() >= 1`, and one trivial
  eager op on the spyre device. A failure here is a substrate /
  ABI / import problem, not a compiler problem.
- **Stage 1 — BUILD / IMPORT.** Primary-module import matrix under
  the current torch — confirms every `torch_spyre.*` package that
  the compiler will later touch imports cleanly, and the private-
  use-1 backend has been registered on the `torch` singleton.
- **Stage 2 — MINIMAL COMPILE.** ONE `torch.compile(..., backend=
  "inductor")` call on a two-op program (e.g. `add`) with a CPU
  correctness oracle. Cheapest actual compile; catches lowering /
  code-emission API breaks before the harder ones surface.
- **Stage 3 — COMPILER-SURFACE SMOKES.** A hand-picked cheap subset
  of `tests/inductor/` — building_blocks, dedup_constants, logging,
  overwrite, inductor_scalar, copy_back_elision. Covers the
  lowering-pipeline entry points that upstream torch changes tend
  to break first.
- **Stage 4 — FOCUSED FAILURE-DRIVEN TESTING.** Per-case, manual.
  Once a Stage 0-3 failure is triaged and hypothesized, the case
  author writes targeted tests that would have caught the failure
  and passes them against SUPPORTED_CONTROL + FORWARD_AFTER_FIX.
- **Stage 5 — REGRESSION VERIFICATION.** Per-case, manual. Wider
  regression sweep on FORWARD_AFTER_FIX — the broader test grid the
  case's diagnosis calls for (fp16, bool, distributed, etc.), not
  the full torch-spyre suite.
- **Stage 6 — BROADER CONFIDENCE.** Per-case, manual. Model-level
  smoke: at least one small end-to-end model (e.g. one Granite
  block) compiled and run under FORWARD_AFTER_FIX. Green Stage 6
  across SUPPORTED_CONTROL and FORWARD_AFTER_FIX is the acceptance
  criterion for "forward-compat restored for this bump."

**Automation boundary.** `run_compat_smoke.sh --stage-through 3` is
the automated runner. It implements Stages 0-3 above verbatim (each
stage maps 1:1 to a `stage_N.log` and `stage_N.result` on disk).
Stages 4-6 are per-case manual work driven by `record_failure.py`
(to open the six-file record) and `verify_patch.sh` (to enforce the
verification matrix). Extending the runner to `--stage-through 6` is
v0.3 backlog.

Detailed stage recipes in `references/validation-ladder.md`.

## Failure taxonomy

See `references/failure-taxonomy.md` for the authoritative list. v0.2
expanded the taxonomy with categories learned from the v0.1 → v0.2
transition:

- **`PIPELINE_MISCONFIGURATION`** (from F5 retraction). When the
  compile error involves an unusual toolchain invocation
  (double-ccache, wrong-arg-to-compiler, missing include path),
  suspect the pipeline env before suspecting torch. Diagnostic:
  `env | grep -E "^(CXX|CC|CFLAGS)="` and inspect the actual
  compile command line before assuming any torch-side responsibility.
- **`REVERSE_ENTRYPOINT_HAZARD`** (from F3). A backend registered via
  a `pyproject.toml` entry point can be invoked *while its own
  `__init__.py` is still executing* — the resolving code path calls
  `getattr(module, "_autoload")` before the module has finished
  binding names. Diagnostic: run the 5-case import matrix in
  `references/failure-taxonomy.md` under §REVERSE_ENTRYPOINT_HAZARD.
- **`SEMANTIC_COMPILER_BREAK`** (from F7 attempt). A silent
  wrong-output regression — code compiles and runs, but produces
  incorrect values. Reproduction is harder than API breaks:
  neutralising just the fix invocation may not be enough because
  test-harness safeguards can mask the bad output. Full reproduction
  requires a revert against the prior substrate.
- **`PIPELINE_DEFECT`** (from F1). Two builds against different torch
  versions cannot share a single torch-spyre source tree — editable
  `.pth` installs point at the same on-disk `_C.so`, so the second
  build overwrites the first and the first venv now points at a
  wrong-torch-linked `_C.so`.

The `NO_BREAK` verdict remains valid and valuable — it means the
current forward torch is safe to point torch-spyre at with only a pin
bump.

## Patching policy

Full policy in `references/patch-policy.md`. Non-negotiable rules:

- **One break at a time.** When Stage N fails, patch ONLY that
  break. Do not preemptively patch things you suspect might fail at
  Stage N+1.
- **Hypothesis before fix.** Every patch is preceded by a written
  hypothesis in `NN-hypothesis.md`. The hypothesis names the
  mechanism, the minimum change, and the expected outcome.
- **Minimum patch.** Prefer a shim over a rewrite. Never bundle
  unrelated cleanups into a forward-compat patch. For F3 the correct
  form is the **defer-and-invoke-at-end** pattern: define the
  entry-point target early so the early call succeeds cleanly (as a
  no-op if state isn't ready), and invoke at the end of the module
  once state is ready.
- **Revert-clean.** Every patch is applied to a clean checkout at
  the recorded SHA.
- **Cite verbatim.** Torch-spyre is PRIVATE — citations take the
  form `torch-spyre@<short-sha>:<path>:<line>`. PyTorch is public —
  citations take the form
  `https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>`.

If a patch's FORWARD_AFTER_FIX run passes Stage N but reveals a
DIFFERENT break at Stage N+1, that is a **new case**, not a
continuation of the current one.

## Learned rules from v0.1 → v0.2

Codified from the F1/F3/F4/F5/F6/F7 investigation:

- **F1 — separate build trees per venv.** Editable installs and
  shared source trees do not compose across two different torch
  versions. The `setup_supported_env.sh` and
  `setup_latest_pytorch_env.sh` scripts must produce independent
  torch-spyre working trees, not two venvs pointing at one tree.
  Details: `cases/current-main/failures/F1-*/03-root-cause.md`.
- **F4 — substrate-fitness probe before Stage 0.** Before running the
  ladder, confirm that the code under test can build against the
  current substrate at its own declared torch pin. If it cannot, the
  case is either a stale-substrate problem or a stale-code problem;
  either way the ladder proper has no signal. Details:
  `cases/historical-replay-pt213/F4-substrate-drift.md`.
- **F5 — check `CXX`/`CC` before assuming torch break.** Toolchain
  env vars from an outer shell can silently corrupt an inner build
  (double-ccache is the concrete case; `CXX="ccache c++"` with
  `/usr/lib64/ccache` already on `PATH` produces `ccache 'ccache c++'
  -MMD`). Diagnostic: `env | grep -E "^(CXX|CC|CFLAGS)="` before
  assuming any torch-side responsibility. Details:
  `cases/historical-replay-pt213/F5-forward-compile-break-blocks-replay.md`.
- **F6 — `nm -uD` symbol-vs-wheel cross-check.** When Stage 3 (import)
  fails with an undefined symbol from `_C.so`, run `nm -uD` on the
  built `.so` and cross-reference against the target libtorch. This
  identifies whether the missing symbol is a torch internal that was
  renamed. Then locate the replacement in the newer libtorch's
  headers. Details:
  `cases/historical-replay-pt213/F6-pyobj-slot-api-rename-independently-derived.md`.
- **F3 — 5-case import matrix diagnostic.** For any suspected
  `REVERSE_ENTRYPOINT_HAZARD`, run the canonical 5-case matrix (A:
  `import torch`; B: `+ torch._inductor`; C: `import torch_spyre`
  alone with autoload ON; D: `import torch_spyre` alone with autoload
  OFF; E: `import torch; import torch_spyre`; F: `torch_spyre +
  torch_spyre._inductor.lowering`; H: full canonical order). If C and
  F fail while A/B/D/E/H pass, the diagnosis is confirmed. Details:
  `cases/current-main/failures/F3-*/02-import-matrix.md` and
  `cases/live-current-main-F3/README.md`.

## How to invoke — quick start

Every command below matches the exact `--help` of the checked-in
script it invokes. `bash <script> --help` will show the same
argument shape.

Prerequisites:

- `KUBECONFIG` set to the dev-cluster kubeconfig (e.g.
  `export KUBECONFIG=$HOME/kubeconfig`).
- `oc` on PATH, logged in (`oc whoami` must succeed).
- Local checkout of this repo. All commands assume the working
  directory contains this skill (or use absolute paths).

Fresh compatibility experiment against current pytorch main and
current torch-spyre main:

```bash
# 0. Pick names / paths for this run. YYYY-MM-DD is the date of the
#    experiment; POD_NAME must be unique in the namespace.
export POD_NAME="tdeshane-forward-compat-$(date +%Y-%m-%d)"
export NS="a5-deepview"

# Local artifacts land under one CASE dir per experiment.
export CASE_DIR="$PWD/case-$(date +%Y-%m-%d)"
mkdir -p "$CASE_DIR"

# 1. Provision a fresh Spyre-capable pod. --digest byte-exact-pins
#    the image to an existing pod's imageID (recommended, avoids
#    :latest drift and 60-min uncached-pull hangs). --prefer-node is
#    a soft affinity hint.
bash .claude/skills/torch-spyre-forward-compat/scripts/create_fresh_pod.sh \
     --name "$POD_NAME" \
     --namespace "$NS" \
     --digest tdeshane-compiler-timing-dev-v2 \
     --prefer-node p1-worker-23

# 2. Copy scripts to the pod once, then invoke on-pod.
oc cp .claude/skills/torch-spyre-forward-compat/scripts \
      "$NS/$POD_NAME:/home/tdeshane/skill-scripts"

# 3. Sweep PVC contamination aside. The dev-cluster PVC (a5-deepview)
#    is shared across all pods, so /home/tdeshane may already contain
#    /supported, /forward, /torch-spyre-work, etc. from prior sessions.
#    setup_supported_env.sh and setup_latest_pytorch_env.sh both refuse
#    a non-empty WORKDIR — for good reason: a partial old state would
#    silently poison the run. Move any pre-existing state ASIDE (not
#    delete) so it can be inspected if the run surfaces something.
#    Timestamp-suffixed so multiple stashings never collide.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
oc exec "$POD_NAME" -n "$NS" -- bash -c '
    STAMP="'"$STAMP"'"
    for d in supported forward torch-spyre-work manual-repro fresh-validate skill-runs; do
        if [ -e "/home/tdeshane/$d" ]; then
            mv "/home/tdeshane/$d" "/home/tdeshane/${d}.stash-${STAMP}"
        fi
    done
    echo "# PVC swept; anything under /home/tdeshane/*.stash-'"$STAMP"' is prior state"
'

# 4. Capture environment (pod, image, python, toolchain, PVC hazards).
oc exec "$POD_NAME" -n "$NS" -- \
   python3 /home/tdeshane/skill-scripts/capture_environment.py \
   > "$CASE_DIR/00-environment.json"

# 5. Resolve current torch-spyre and pytorch HEAD SHAs plus the
#    pyproject-declared torch pin. Anonymous fetch; falls back to
#    GITHUB_TOKEN if the network policy requires it.
oc exec "$POD_NAME" -n "$NS" -- \
   bash /home/tdeshane/skill-scripts/resolve_versions.sh \
        --out /home/tdeshane/versions.json
oc cp "$NS/$POD_NAME:/home/tdeshane/versions.json" \
      "$CASE_DIR/01-versions.json"

# Read back the resolved SHAs for the next two steps.
TS_SHA=$(python3 -c 'import json; print(json.load(open("'$CASE_DIR'/01-versions.json"))["torch_spyre"]["sha"])')
PT_SHA=$(python3 -c 'import json; print(json.load(open("'$CASE_DIR'/01-versions.json"))["pytorch"]["sha"])')

# --- Device-serialization boundary ------------------------------------
# The a5-deepview pod has ONE Spyre AIU device and the device runtime
# is exclusive: once started (e.g. by a `capture_environment.py` call
# or by a smoke stage running an on-device op), it holds state that a
# concurrent workload can wedge into a DMA timeout / SIGABRT. Steps
# 6-9 below must run SERIALLY. Do NOT background any of them.
# ---------------------------------------------------------------------

# 6. SUPPORTED_CONTROL — install torch at the pyproject-declared pin
#    (parsed at runtime; scripts do NOT hard-code). --workdir must
#    NOT yet exist; the script creates it and refuses to overwrite
#    (that's why step 3 swept the PVC).
oc exec "$POD_NAME" -n "$NS" -- \
   bash /home/tdeshane/skill-scripts/setup_supported_env.sh \
        --torch-spyre-sha "$TS_SHA" \
        --workdir /home/tdeshane/supported

# 7. FORWARD_BEFORE_FIX — a SEPARATE workdir (F1 rule: never share
#    source trees between builds against different torches). This
#    script clones its own torch-spyre tree into $WORKDIR/torch-spyre
#    at $TS_SHA, so there is no shared-tree hazard with step 6.
#    Choose mode:
#      EXACT_UPSTREAM_MAIN builds torch from source (~3h ceiling);
#      NIGHTLY_PROXY installs a nightly wheel and reports the embedded
#      git SHA for provenance.
oc exec "$POD_NAME" -n "$NS" -- \
   bash /home/tdeshane/skill-scripts/setup_latest_pytorch_env.sh \
        --torch-spyre-sha "$TS_SHA" \
        --pytorch-sha "$PT_SHA" \
        --workdir /home/tdeshane/forward \
        --mode NIGHTLY_PROXY

# 8. Run the compat smoke on the SUPPORTED venv. This walks Stages
#    0-3 (env, import, minimal compile, targeted smoke). Stages 4-6
#    from references/validation-ladder.md are per-case manual work
#    driven by record_failure.py + verify_patch.sh. The
#    TORCH_SPYRE_TREE env pins Stage 3's test-tree locator to the
#    supported tree.
oc exec "$POD_NAME" -n "$NS" -- \
   env TORCH_SPYRE_TREE=/home/tdeshane/supported/torch-spyre \
   bash /home/tdeshane/skill-scripts/run_compat_smoke.sh \
        --venv /home/tdeshane/supported/.venv-supported \
        --out-dir /home/tdeshane/supported-smoke \
        --stage-through 3

# 9. Run the compat smoke on the FORWARD venv. Failures here are
#    the interesting result. First FORWARD failure blocks the ladder.
oc exec "$POD_NAME" -n "$NS" -- \
   env TORCH_SPYRE_TREE=/home/tdeshane/forward/torch-spyre \
   bash /home/tdeshane/skill-scripts/run_compat_smoke.sh \
        --venv /home/tdeshane/forward/.venv-latest \
        --out-dir /home/tdeshane/forward-smoke \
        --stage-through 3

# 10. For each FORWARD failure (or supported failure at F3-live):
#     author a hypothesis-first record. record_failure.py creates the
#     six-file per-failure directory (01-observation.md through
#     06-retrospective.md). 04-patch.md must reference a concrete
#     diff before verify_patch.sh will run.
#
#     The observation body is piped directly from the failing stage's
#     log — no out-of-band file authoring — so the record is
#     reproducibly tied to what actually happened.
#
#     Example below is for the F3 REVERSE_ENTRYPOINT_HAZARD case
#     (still live on torch-spyre main at time of writing); swap the
#     classification and citation for whatever the actual failure is.
oc exec "$POD_NAME" -n "$NS" -- bash -c '
    mkdir -p /home/tdeshane/case
    cat /home/tdeshane/supported-smoke/stage_0.log \
      | python3 /home/tdeshane/skill-scripts/record_failure.py \
        --dir /home/tdeshane/case \
        --index 1 \
        --classification REVERSE_ENTRYPOINT_HAZARD \
        --torch-spyre-loc torch_spyre/__init__.py:20 \
        --stdin
'

# 11. Verify the patch: assert it moves the ladder at least one
#     stage past the FORWARD failure AND does not regress
#     SUPPORTED_CONTROL. Seven-row matrix; refuses if any row fails.
#
#     Pass the exact failure-dir slug — record_failure.py named it
#     from the classification you gave it in step 10 (in this example,
#     REVERSE_ENTRYPOINT_HAZARD → 01-reverse-entrypoint-hazard).
#     Do NOT use a wildcard: oc exec ships the arg through un-globbed
#     and verify_patch rejects a literal "01-*".
#
#     Trees must be explicit arguments (F14 lesson, 2026-08-25):
#     they sit as siblings of the venvs, not ancestors — the previous
#     walk-up heuristic silently failed on the documented layout.
oc exec "$POD_NAME" -n "$NS" -- \
   bash /home/tdeshane/skill-scripts/verify_patch.sh \
        --failure-dir    /home/tdeshane/case/failures/01-reverse-entrypoint-hazard \
        --venv-supported /home/tdeshane/supported/.venv-supported \
        --venv-latest    /home/tdeshane/forward/.venv-latest \
        --tree-supported /home/tdeshane/supported/torch-spyre \
        --tree-latest    /home/tdeshane/forward/torch-spyre

# 12. When done, pull the case directory back and tear down the pod.
oc cp "$NS/$POD_NAME:/home/tdeshane/case" "$CASE_DIR/case"
oc delete pod "$POD_NAME" -n "$NS"
```

Every script re-reads `torch-spyre/pyproject.toml` at runtime to
recover the currently-declared torch pin. Do not hard-code the pin
in scripts or cases.

Stage 0-3 vs Stage 0-6

`run_compat_smoke.sh --stage-through 3` is the automation limit of
this v0.2 skill. It runs Stages 0-3 (environment, import, minimal
compile, targeted smoke) which are cheap and universal. Stages 4-6
from `references/validation-ladder.md` (focused failure-driven
testing, regression verification, broader confidence) are per-case
manual work that the case author drives via `record_failure.py`
and `verify_patch.sh`. Extending `run_compat_smoke.sh` to a
`--stage-through 6` mode is v0.3 backlog.

## Machine-readable case format

Each case emits a `case.json` conforming to
`references/case-schema.json`. It records pod name, namespace, base
image digest; pytorch and torch-spyre SHAs at the time of the case;
the parsed pin from `pyproject.toml`; per-stage results under all
three control states; the first-break stage under FORWARD_BEFORE_FIX
and its failure-taxonomy category; the patch (or `null` if
`NO_BREAK`); the FORWARD_AFTER_FIX outcome; verbatim citations for
every source claim; and the FORWARD torch mode (EXACT_UPSTREAM_MAIN or
NIGHTLY_PROXY). See `references/case-schema-example.json` for a
filled example.

## Empirical validation status — v0.2

Two full cases validated:

**F6 — Historical replay of torch 2.13 upgrade**
(`analyses/2026-08-forward-compat-skill-validation/cases/historical-replay-pt213/`)

- Target: torch-spyre@`dd95ef44` (parent of the maintainer's 2.13 fix
  `754839cc8`) forward-compat against torch 2.13.0+cpu.
- Skill independently derived the exact one-line fix
  (`pyobj_slot_.load_pyobj_interpreter()` →
  `(*c10::impl::getGlobalPyInterpreter())`). Byte-identical to the
  maintainer's fix.
- Verified as `DUAL_COMPAT_FIX`: the same patch works cleanly on
  torch 2.12.1+cpu and torch 2.13.0+cpu with no version-conditional
  code needed.
- Real Spyre `torch.compile(backend="inductor")`: pointwise 0.023,
  reduction 0.031, aminmax 0.002 (all fp16-noise deltas).

**F3 — Live current-main remediation**
(`analyses/2026-08-forward-compat-skill-validation/cases/live-current-main-F3/`)

- Target: torch-spyre@`8aba5bc` (Aug 2026 main tip) — a currently-live
  bug, not a historical replay.
- Skill diagnosed via 5-case import matrix; classified as
  `REVERSE_ENTRYPOINT_HAZARD`; produced the defer-and-invoke-at-end
  fix in `torch_spyre/__init__.py`.
- Post-fix: 7/7 import-matrix cases pass; Stage 0 device enum
  (`spyre.device_count() == 1`) works; Stage 2 real Spyre compile
  produces correct output within fp16 tolerance.

**Not yet validated in v0.2:**

- End-to-end `SEMANTIC_COMPILER_BREAK` reproduction. F7 (LX aminmax
  replay) attempted this and reached partial success — the exact
  historical test collects and runs under `LX_PLANNING=1`, but
  neutralising `align_lx_producer_loop_order` alone did not
  reproduce wrong values on current main. See
  `cases/historical-replay-pt213/F7-lx-aminmax-replay-attempt.md`.
  Full reproduction is a v0.3 target.
- Fresh-pod-only run using solely the skill scripts (no hand
  intervention). The current cases used a mix of scripts and manual
  steps.

## Future composition with `frontend-compiler-impact` (deferred)

Once this skill produces a `NO_BREAK` verdict — or a green
`FORWARD_AFTER_FIX` — for a given (pytorch_sha, torch_spyre_sha)
pair, that pair becomes a candidate input to
`frontend-compiler-impact`: measure whether the forward torch bump
moves compile time, using the same three-state philosophy adapted to
timing (SUPPORTED_CONTROL / FORWARD (no torch-spyre change) /
FORWARD_WITH_TORCH_SPYRE_UPGRADE). The composed skill would answer
both "does it work?" and "does it still perform?" in one workflow.

**For v0.2 this composition is NOT integrated.** The two skills are
invoked independently. `case.json` from this skill will be readable
by a future `frontend-compiler-impact` extension, but that extension
is not written and no script in this skill imports from
`frontend-compiler-impact`.

## Files under this skill

```
.claude/skills/torch-spyre-forward-compat/
    SKILL.md                          — this file
    references/
        validation-ladder.md          — Stages 0-6 detailed recipes
        failure-taxonomy.md           — categories + diagnostic recipes
                                        (includes v0.2 additions:
                                        PIPELINE_MISCONFIGURATION,
                                        REVERSE_ENTRYPOINT_HAZARD,
                                        SEMANTIC_COMPILER_BREAK,
                                        PIPELINE_DEFECT)
        patch-policy.md               — one-break, hypothesis-first,
                                        minimum-patch, revert-clean
        environment-policy.md         — three-state enforcement
        canonical-dev-flow.md         — torch-spyre install flow
                                        (--no-deps --no-build-isolation,
                                        CXX guidance, F5 rule)
        upstream-investigation.md     — how to find upstream cause
        verification-policy.md        — FORWARD_AFTER_FIX acceptance
        case-schema.json              — machine-readable case format
        case-schema-example.json      — filled example
    scripts/
        create_fresh_pod.sh           — provision Spyre-capable pod,
                                        record image digest
        capture_environment.py        — emit 00-environment.json
        resolve_versions.sh           — git ls-remote pytorch + torch-spyre
        setup_supported_env.sh        — SUPPORTED_CONTROL venv+build
        setup_latest_pytorch_env.sh   — FORWARD venv+build (separate tree)
        run_compat_smoke.sh           — Stages 0-3 harness
                                        (Stages 4-6 are per-case
                                        manual work via
                                        record_failure.py +
                                        verify_patch.sh)
        record_failure.py             — case scaffolding
        verify_patch.sh               — FORWARD_AFTER_FIX acceptance
```

## What this skill is NOT

- **Not a torch bumper.** It answers whether a bump is safe; it does
  not land pin changes in `pyproject.toml`.
- **Not a performance tool.** Stage 2 is a minimum-viable compile
  and Stage 6 is a small-model smoke — neither is a benchmark.
  Compile-time regression is `frontend-compiler-impact`.
- **Not authoritative on pytorch internals.** When a failure
  implicates a pytorch commit, the skill cites the commit and
  reports the diagnosis; it does not propose changes to pytorch.
- **Not a substitute for CI.** The skill runs one pod, one time,
  per case. CI can and should run this ladder on schedule; this
  skill's discipline is what a CI job should encode, not what it
  replaces.
