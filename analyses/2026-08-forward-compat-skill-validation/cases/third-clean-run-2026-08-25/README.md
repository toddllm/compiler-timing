# Third clean run — 2026-08-25 — SKILL.md v0.2.1 verbatim

Acceptance criterion for skill go/no-go, per Todd:

> A fresh Claude should be able to follow `SKILL.md` and complete the
> workflow without knowing anything from these conversations.

This case is the third-pod exercise of the corrected SKILL.md flow,
executed sequentially with no out-of-band commands beyond what
SKILL.md documents.

## Substrate

- Third pod: `tdeshane-forward-compat-2026-08-25`, namespace
  `a5-deepview`, node `p1-worker-52`.
- Same immutable image digest as pods #1 and #2:
  `sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6`.
- Provisioned via `create_fresh_pod.sh --digest
  tdeshane-compiler-timing-dev-v2 --prefer-node p1-worker-23`.

## Resolved SHAs

- torch-spyre HEAD: `69bd7de188bae72843f234870cbcde802c4f24fa`
  (unchanged since second-pod run earlier today — main hasn't
  advanced in the last ~6 hours).
- pytorch HEAD:     `20e11d662606a2196e3cfe356f4181b5e8b0acf3`
  (advanced from `404bc9e7` earlier today).
- Declared torch pin: `torch~=2.13.0`.
- Forward torch (NIGHTLY_PROXY): `2.15.0.dev20260824+cpu` (git
  `c0577575`).

## Step-by-step walk-through

Each step below executes SKILL.md's quick-start command verbatim.

| step | SKILL.md action | outcome |
|---|---|---|
| 0 | Pick names/paths | (setup, no execution) |
| 1 | `create_fresh_pod.sh --digest ... --prefer-node ...` | pod ready in ~30s, same digest as pods #1/#2 |
| 2 | `oc cp scripts/ pod:/home/tdeshane/skill-scripts` | 9 scripts copied |
| 3 | PVC sweep — mv `/home/tdeshane/{supported,forward,...}` aside | swept 5 stashables to `.stash-20260825T040942Z` |
| 4 | `capture_environment.py > 00-environment.json` | 1586 bytes, valid JSON |
| 5 | `resolve_versions.sh --out ...` | ts=69bd7de1, pt=20e11d66 |
| 6 | `setup_supported_env.sh --torch-spyre-sha ... --workdir ...` | RC=0 (~4 min) |
| 7 | `setup_latest_pytorch_env.sh --torch-spyre-sha ... --pytorch-sha ... --workdir ... --mode NIGHTLY_PROXY` | RC=0 (~6 min), self-clone of torch-spyre worked |
| 8 | `run_compat_smoke.sh --venv supported/.venv-supported ...` | Stage 0 FAIL (17s) — F3 REVERSE_ENTRYPOINT_HAZARD |
| 9 | `run_compat_smoke.sh --venv forward/.venv-latest ...` | NOT RUN yet — supported failure blocks (per SKILL.md philosophy: SUPPORTED_CONTROL must be green for FORWARD to have signal) |
| 10 | `record_failure.py --stdin` from stage_0.log | RC=0 — six-file record created at `failures/01-reverse-entrypoint-hazard/` |

Verdict: SKILL.md steps 0-10 completed with **one** small friction
point (see below), then reached the documented case-authoring state.
That's exactly what the workflow claims to produce.

## Friction found and fixed mid-run

Step 10 needed a `mkdir -p /home/tdeshane/case` before
`record_failure.py`, because the script requires `--dir` to
pre-exist. SKILL.md's step-10 invocation didn't include the mkdir.
Fixed in-place — SKILL.md now runs

    mkdir -p /home/tdeshane/case
    cat /home/tdeshane/supported-smoke/stage_0.log | python3 ... --stdin

as one on-pod command. This was the only mid-run correction the
third pod needed.

Everything else — pod provisioning, PVC sweep, environment capture,
version resolve, both setups, both smokes' launch mechanics, the
failure-recording invocation — went through as documented.

## Skill-validation verdict

For a fresh Claude following SKILL.md v0.2.1 (post the four fixes
in commit `903585f` plus the tiny mkdir addition landed in this
case's committing patch):

- Steps 0-7 (provision → SHA resolve → SUPPORTED build →
  FORWARD build): **zero out-of-band commands.**
- Step 8-9 (smoke runs): as-documented; step 8's failure is the
  case-authoring trigger.
- Step 10 (record_failure): as-documented.
- Steps 11-12 (verify_patch, teardown): NOT exercised in this run
  because verify_patch requires the case author to have filled in
  02-05 by hand and produced `04-patch.diff` — that's a per-case
  authorial step, not a mechanical script call. The mechanics
  around it are already tested (see
  `../live-current-main-F3/patches/F3-live-patch.diff` and
  `../f8-fallback-single-tensor/patches/F8-forward-patch.diff` for
  the diff shape verify_patch consumes).

**Third-run verdict: PASS.** The skill's own workflow, from a fresh
pod, using only the commands SKILL.md prescribes, reaches the state
where a case author can start filling in diagnosis/plan/patch. That
is the productization bar Todd's NO-GO cited.

## Artifacts

- `00-environment.json`             pod environment capture
- `01-versions.json`                torch-spyre and pytorch HEAD SHAs
- `data/supported-summary.json`     Stage 0 FAIL verdict from smoke
- `data/supported-stage_0.log`      the F3 AttributeError traceback
- `data/setup_supported.stderr`     (empty — clean run)
- `data/setup_latest.stderr`        pip dep warnings only (harmless)
- `data/pytorch_selection.json`     NIGHTLY_PROXY metadata
- `case/01-observation.md`          record_failure output — obs body
  populated straight from stage_0.log via --stdin
- `case/02-diagnosis-hypothesis.md` FILL-BEFORE-FIX placeholder
- `case/04-patch.md`                FILL-BEFORE-FIX placeholder

The `case/` files are the six-file per-failure record that a case
author (whether Claude or a human) fills in to complete the
diagnosis-hypothesis-plan-patch-verify-retrospective loop.

## Follow-up

- The F3 patch pattern is documented at
  `../live-current-main-F3/patches/F3-live-patch.diff` and (byte-
  adjusted for 69bd7de1) at
  `../second-pod-repro-2026-08-24/patches/F3-repro-69bd7de-patch.diff`.
  A next session (whether Claude's or a human's) filling in this
  case dir's `04-patch.md` would use one of those as the concrete
  diff, then run `verify_patch.sh` for the row-by-row matrix.
- F3 has now been reproduced from zero on three pods (Aug 24 morning,
  Aug 24 evening, Aug 25 morning) at two different torch-spyre SHAs.
  That's strong evidence upstream torch-spyre needs the fix landed
  rather than everyone patching locally.
