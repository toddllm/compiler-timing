# Torch-spyre-forward-compat skill — validation summary

**Status: v0.1.0 authored, first empirical case landed with material findings.**
The primary case ran end-to-end on a fresh Spyre-capable pod on
`2026-08-21`. Neither `SUPPORTED_CONTROL` nor `FORWARD_BEFORE_FIX`
produced a clean green ladder — but the failures they produced are
exactly the kind of substrate/declared-version signal the skill exists to
surface. See the "Findings" section for the specifics.

## The primary case

| axis | value |
|---|---|
| Case id | `current-main` |
| torch-spyre SHA | `a31289852145a59099edccc3e506cf5336e8e2e0` (main @ 2026-08-21) |
| pytorch SHA (forward, requested) | `73961011bf64f1c04b3291bf90ac1dbbe197c2ca` (main @ 2026-08-21) |
| pytorch (forward, actual) | `torch 2.15.0.dev20260821+cpu`, git `cef373b344057d8ed91bcf05d7921b2ca1d0d13c` — NIGHTLY_PROXY |
| Declared torch pin (parsed at runtime) | `torch~=2.13.0` |
| Pod name | `tdeshane-forward-compat-2026-08-21` |
| Namespace | `a5-deepview` |
| Node landed on | `p1-worker-48` |
| Base image (tag) | `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest` |
| Base image digest (immutable) | `sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6` |
| System torch shipped in image | `torch 2.11.0+cpu` at `/usr/local/lib64/python3.12/site-packages/torch/` |
| Compiler | `gcc/c++ 14.3.1 20251022 (Red Hat 14.3.1-4)` — GCC 14, not `/opt/rh/gcc-toolset-*` |
| SENDNN / DEEPTOOLS | present at `/opt/sentient/{runtime,deeptools}` |

The pod resolved `:latest` to the same digest a co-located working pod
uses, and we pinned to that digest to eliminate `:latest` drift as a
variable.

## Ladder results (Stages 0-2 completed; 3-6 deferred by both failures)

### SUPPORTED_CONTROL — torch-spyre@a3128985 + `pip install torch~=2.13.0 --index-url .../whl/cpu`

| stage | rc | outcome |
|---:|:---|:---|
| build (venv .venv-supported) | 0 | canonical `pip install -e . --no-deps --no-build-isolation` succeeds; editable wheel installed |
| Stage 0 — env / device enum | 1 | `_autoload` fails at `torch_spyre.ops.eager` import: **`ImportError: torch_spyre/_C.so: undefined symbol: _ZNK4c10d7Backend15incref_pyobjectEv`** (`c10d::Backend::incref_pyobject() const`) |
| Stage 1 — module imports | 139 | subsequent module imports crash with `RuntimeError: Only a single TORCH_LIBRARY can be used to register the namespace triton` (harness re-import artifact after Stage 0 partial failure) |
| Stage 2 — trivial CPU inductor compile | 1 | same |

### FORWARD_BEFORE_FIX — torch-spyre@a3128985 + torch nightly `2.15.0.dev20260821+cpu`

| stage | rc | outcome |
|---:|:---|:---|
| build (venv .venv-latest) | 0 | canonical build succeeds against nightly torch |
| Stage 0 — env / device enum | **0** | `import torch_spyre` works, `torch.spyre.device_count() == 1`, eager tensor sum works |
| Stage 1 — module imports | 139 | same `TORCH_LIBRARY(triton)` double-registration on module re-import |
| Stage 2 — trivial CPU inductor compile | 0 | trivial pointwise compile against Inductor backend succeeds (this is CPU-only Inductor, not Spyre codegen) |

## Findings

### F1 — SUPPORTED_CONTROL undefined symbol (highest-value finding)

torch-spyre@a3128985 builds cleanly against upstream `torch==2.13.0+cpu`
(the version its own `pyproject.toml` declares via `torch~=2.13.0`) but
its `_C.so` at runtime references `c10d::Backend::incref_pyobject()` — a
symbol **not present in the upstream torch 2.13.0 CPU wheel** and not
present in `Backend.hpp` on either `v2.13.0` or `main` (verified by
fetching both from `raw.githubusercontent.com`).

This means torch-spyre@main is being built and tested internally against
a torch that carries an out-of-tree/staged patch adding
`incref_pyobject` — most likely the torch shipped in newer
`torch-aiu-runtime-dev` image layers. The pyproject pin `torch~=2.13.0`
is therefore **not a self-sufficient install specification**: `pip
install torch~=2.13.0` from the standard CPU index produces a torch that
cannot resolve one of torch-spyre's C-symbol dependencies.

Failure taxonomy: **`C_EXTENSION_ABI_BREAK`** — the module builds and
links but does not autoload because a runtime-referenced symbol is
undefined. Category rules require classification before patching; no
patch was applied.

The three plausible root causes, in decreasing likelihood:

1. **The declared pin is stale.** torch-spyre@main should declare its
   dependency on a specific PyTorch build/lineage, not the vanilla
   `torch~=2.13.0` CPU wheel. Fixing pyproject to point at the correct
   internal wheel index (or documenting the assumed image torch) would
   close this.
2. **`_C.so` references a symbol via an accidental include path.** The
   compile succeeded despite the pyproject pin because system-site
   torch (2.11.0) headers are on the include path and one of them
   references `incref_pyobject` unconditionally, producing an undefined
   symbol at link time that only shows on import.
3. **`incref_pyobject` was in a torch release candidate branch that
   torch-spyre’s build environment tracks but the public wheel does
   not.** Would require internal torch-aiu-runtime-dev sources to
   confirm.

Reproducible artifact: `data/supported_stage0.log` shows the full
traceback and the `_C.so` symbol.

### F2 — FORWARD_BEFORE_FIX Stage 0 actually works on nightly

The forward-compat test at `torch 2.15.0.dev20260821+cpu` produced a
working `torch_spyre` import, real `torch.spyre.device_count() == 1`,
and successful eager tensor operations. This is the more surprising
outcome: torch-spyre@main survives its own future-torch better than its
own supposedly-supported torch. Under the failure taxonomy this alone
would count as **`NO_BREAK`** on Stage 0.

### F3 — Stage 1 harness bug (`TORCH_LIBRARY(triton)` double registration)

Both configurations fail Stage 1 with `RuntimeError: Only a single
TORCH_LIBRARY can be used to register the namespace triton`. The
mechanism is that Stage 0's `import torch_spyre` autoloads and registers
`triton` via torch's own `torch/__init__.py:3350` (nightly) / `:2899`
(2.13.0), and then Stage 1 launches a fresh `python3 -c` where a
subsequent `__import__("torch_spyre._inductor.lowering")` re-triggers a
registration path that duplicates the entry. This is **not** a
compatibility break — the current ladder harness serialises stage
transitions across process boundaries incorrectly. It is a **v0.2
harness fix**, tracked at Task #30.

Reproducible artifacts: `data/forward_stage1.log`,
`data/supported_stage1.log`.

### F4 — Substrate: `/opt/rh/gcc-toolset-*` no longer present

`torch-spyre-docs/scripts/build-torch-spyre.sh` exports
`CXX="ccache $(ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ | tail -1)"`.
The current `torch-aiu-runtime-dev:latest` image
(`sha256:81c352...`) does not have `/opt/rh/gcc-toolset-*`; it ships
GCC 14.3.1 as the system compiler with ccache already on PATH at
`/usr/lib64/ccache/*`. `CXX=c++` produces the correct behaviour.

The skill's `references/canonical-dev-flow.md` and the pipeline handle
both cases (gcc-toolset-when-present, system-c++-otherwise). The docs
themselves need updating; not in scope for this skill.

### F5 — PVC contamination hazard characterised

The user's persistent home directory contains an editable
`torch_spyre-0.0.1.pth` under `.local/lib/python3.12/site-packages/`
pointing at an older build with a *different* flex-ABI symbol mismatch
(`_ZN4flex12RuntimeEntry10toPriorityEi`). Any pipeline that uses
`python3` outside a fresh venv autoloads this stale build and produces
misleading errors. The skill's pipeline mitigates via `PYTHONNOUSERSITE=1`
top-level and never invokes `python3` outside its venvs. Documented in
`references/environment-policy.md`.

## Where the skill worked

- **Three-state discipline preserved through the collected data.** The
  pod, image digest, both venvs, and both ladder outcomes are recorded
  from the same run. `FORWARD_AFTER_FIX` was not reached — but that is
  the correct outcome, because the skill's own patch-policy forbids
  applying a fix until the SUPPORTED_CONTROL is either green or its
  failure has been root-caused. Applying a nightly-only patch on top of
  a broken SUPPORTED_CONTROL would have hidden F1.
- **Canonical build flow re-encoded from `torch-spyre-docs` was correct.**
  Both builds succeeded via `pip install -e . --no-deps
  --no-build-isolation -vvv --verbose` with the observed compiler
  (GCC 14.3, ccache-wrapped `c++`). The `--no-deps` flag is what allowed
  the venv-installed torch (2.13.0 or nightly) to survive the
  torch-spyre install rather than being evicted.
- **Failure taxonomy discriminated real from spurious.** F1 is
  `C_EXTENSION_ABI_BREAK`. F3 is a harness bug (`NOT_TORCH_SPYRE`
  in the taxonomy). Without the category structure, both would have
  been mistaken for compatibility breaks and produced bogus patches.
- **Environment provenance sufficient for reproduction.** Pod name,
  namespace, node, resolved image digest, python version, GCC version,
  and both torch versions are all in `environment/environment.json`.
  A fresh Claude session can re-create the pod at the same digest.

## Where the skill fell short

- **Pipeline had a `{ } vs ( )` bug that killed itself on first success.**
  The initial canonical_build helper wrapped a block command in `{ ...;
  exit $rc; }` — `{ }` is not a subshell, so `exit` inside killed the
  parent pipeline immediately after the SUPPORTED build succeeded. Fixed
  in the re-run; documented in `notes/methodology.md`.
- **`:latest` image tag drift risk was not initially guarded against.**
  The first pod attempt on `p1-worker-35` hung for 66 minutes on a
  `:latest` pull with no cached layers, no useful events, and no error.
  The fix was to pin to the exact image digest observed on a working
  pod and prefer the same node via `nodeAffinity`. `create_fresh_pod.sh`
  should default to `--image us.icr.io/...:@sha256:<digest>` recording
  form when a digest is available.
- **Stage 1 harness re-imports across process boundaries incorrectly.**
  Yields the F3 signal for every case even when there is no
  compatibility break. Needs a v0.2 rewrite that either drops the
  Stage 1 module-list check (Stage 0 already exercises autoload) or
  runs the module walk inside the same python process as Stage 0.
- **The declared torch pin is not diagnosed as suspicious.** The skill
  correctly runs SUPPORTED_CONTROL with the pyproject pin but does not
  cross-check that the pin actually lives up to its promise (compare
  observed C-symbols against what the wheel exports). A v0.2 addition
  to `references/upstream-investigation.md` should include an
  `nm -D $(python -c 'import torch; ...')` step that would have flagged
  F1 as `PIN_LIES` rather than a mysterious ABI break.
- **`create_fresh_pod.sh` was not actually used.** It was authored per
  spec but the empirical run applied a hand-written pod manifest to
  incorporate the digest-pin + node-affinity fixes above. The script
  needs those same fixes back-ported.

## Improvements delivered in v0.1

1. Three-state protocol described in `SKILL.md`.
2. Validation ladder Stages 0-6 in `references/validation-ladder.md`
   (841 lines).
3. Failure taxonomy in `references/failure-taxonomy.md` — used
   successfully to categorize F1 vs F3.
4. Patch policy — one break per patch, hypothesis before fix, revert-
   clean, minimum-diff, shim-first — in `references/patch-policy.md`.
5. Environment policy including PVC-contamination-mitigation in
   `references/environment-policy.md`.
6. Verification policy defining strict-stage-advancement acceptance in
   `references/verification-policy.md`.
7. Upstream investigation policy in
   `references/upstream-investigation.md`.
8. `case-schema.json` + `case-schema-example.json`.
9. Nine scripts under `scripts/` (create_fresh_pod, capture_environment,
   resolve_versions, setup_supported_env, setup_latest_pytorch_env,
   run_compat_smoke, record_failure, verify_patch,
   canonical-dev-flow reference).
10. `references/canonical-dev-flow.md` — encodes torch-spyre-docs'
    `basic_install.md` canonical build form (`--no-deps
    --no-build-isolation`), the GCC-14/gcc-toolset dual path, and the
    PYTHONNOUSERSITE/`.local` hazard.

## Improvements open for v0.2

1. Digest-pinning + node-affinity in `create_fresh_pod.sh`.
2. Fix the pipeline's `{ } vs ( )` subshell bug in
   `scripts/run_compat_smoke.sh` (currently only in the ad-hoc pipeline
   used for this run; the skill script structure is correct).
3. Rewrite Stage 1 harness to avoid the `TORCH_LIBRARY(triton)`
   double-registration artifact.
4. Add an `nm -D` symbol-vs-wheel cross-check to
   `references/upstream-investigation.md` — would have flagged F1 as
   `PIN_LIES` before Stage 0 ran.
5. Add a `SUPPORTED_CONTROL_PROBE` sub-stage that runs *before*
   `SUPPORTED_CONTROL` proper: `nm -uD torch_spyre/_C.so` intersected
   with `nm -D <torch installed>/lib/libtorch*.so` should produce zero
   undefined symbols. If not, escalate immediately without running the
   full ladder — F1 would have surfaced in seconds instead of minutes.

## Bottom-line answer

> **If a torch bump lands tomorrow and someone asks whether torch-spyre
> survives it, can a fresh Claude session use this repository plus the
> skill to answer with a categorised first break, a verbatim citation,
> a hypothesis-first minimum patch, and a verified
> `FORWARD_AFTER_FIX`?**

**Partially.** The skill correctly categorised the observed breaks,
grounded them in reproducible artifacts (build/stage logs, image digest,
resolved torch git SHAs), and refused to apply a preemptive patch
because SUPPORTED_CONTROL was itself broken. It did NOT reach
`FORWARD_AFTER_FIX` because the discovered failure lies upstream of the
skill's remit — torch-spyre's own pyproject-declared torch pin does not
satisfy its C-extension symbol requirements. That finding is the
correct output of the first empirical case, not a failure of the skill.

The v0.2 escalations listed above would convert this from a partially-
answered case to a fully-diagnosed one within the first minute of a
future run.

## Files

- Primary case: `cases/current-main/`
  - `environment/environment.json` — captured on the pod at run start.
  - `data/case.json` — machine-readable case output.
  - `data/*.log` — full pipeline log, build logs, per-stage logs.
  - `failures/` — populated by follow-up work (Tasks #29, #30 for the
    F1 root-cause and F3 harness fix respectively).
  - `patches/` — none applied; F1 blocks all patching per skill policy.
- Methodology: `notes/methodology.md`.
