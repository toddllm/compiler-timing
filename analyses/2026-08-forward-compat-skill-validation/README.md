# Torch-spyre-forward-compat skill — empirical validation

Empirical evaluation of the `.claude/skills/torch-spyre-forward-compat/`
Claude Code skill against one real compatibility experiment: current
torch-spyre main against current pytorch main.

**Status: SKILL AUTHORED, EMPIRICAL VALIDATION PENDING.** The skill
under evaluation is checked in at v0.1.0. The pod run that drives
this study end-to-end has not executed yet. Sections in
[`SUMMARY.md`](SUMMARY.md) and
[`cases/current-main/README.md`](cases/current-main/README.md) that
depend on measured data are marked `TODO: pod run 2026-08-21`.

**Start with [`SUMMARY.md`](SUMMARY.md)** — 2-minute overview of
what the skill is being tested to do and (once the pod run lands)
the measured outcome.

## What this study is

This is a validation study of the SKILL itself, not of any
particular torch bump. The single primary case (torch-spyre@`a3128985`
against pytorch main HEAD as of 2026-08-21,
`73961011bf64f1c04b3291bf90ac1dbbe197c2ca`) measures whether the
skill, run by a fresh Claude session on a fresh pod, produces:

- A green **SUPPORTED_CONTROL** at torch-spyre's declared pin
  (currently `torch~=2.13.0`, parsed from `pyproject.toml` at
  runtime — never hard-coded).
- An honest **FORWARD_BEFORE_FIX** result — either `NO_BREAK` or a
  categorised first break at the earliest failing stage under the
  unpatched torch-spyre + forward-torch combination.
- For each break: a hypothesis-first minimum patch, applied to a
  clean checkout, verified in **FORWARD_AFTER_FIX**.
- A `case.json` per break that validates against the skill's
  `references/case-schema.json`.
- Verbatim citations (`torch-spyre@<short-sha>:<path>:<line>` for
  the private torch-spyre repo; canonical
  `https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>` for
  the public pytorch repo).

## Three-state control

Every case in this study runs three builds on the same pod, same
base image digest, same fresh `.venv`, differing only in torch
source and whether torch-spyre carries the case's patch:

| control state | torch | torch-spyre |
|---|---|---|
| `SUPPORTED_CONTROL` | pinned per `pyproject.toml` (currently declares `torch~=2.13.0`) | `a31289852145a59099edccc3e506cf5336e8e2e0`, unpatched |
| `FORWARD_BEFORE_FIX` | pytorch main HEAD (`73961011bf64f1c04b3291bf90ac1dbbe197c2ca` as of 2026-08-21) | `a31289852145a59099edccc3e506cf5336e8e2e0`, unpatched |
| `FORWARD_AFTER_FIX` | pytorch main HEAD (same SHA as above) | `a31289852145a59099edccc3e506cf5336e8e2e0` + this case's minimum patch |

`SUPPORTED_CONTROL` green is a prerequisite: without it, any
Stage-N failure under `FORWARD_BEFORE_FIX` could be pod- or
environment-caused rather than forward-torch-caused. See
`.claude/skills/torch-spyre-forward-compat/references/three-state-protocol.md`.

## Structure

```
SUMMARY.md                          — 2-minute overview (placeholders
                                      until pod run 2026-08-21 lands)
README.md                           — this file
notes/
    methodology.md                  — hypothesis-before-fix discipline,
                                      staging, alignment rules
cases/
    current-main/
        README.md                   — primary case description
        environment/
            .gitkeep
            note.md                 — pointer to
                                      scripts/capture_environment.py
        failures/
            .gitkeep                — one subdir per Stage-N break,
                                      populated by the pod run
        patches/
            .gitkeep                — one patch per case, minimum-diff
data/
    .gitkeep                        — resolved-HEAD snapshots, base-image
                                      digest, other raw run artifacts
```

## Related work

- `.claude/skills/torch-spyre-forward-compat/SKILL.md` — the skill
  under evaluation.
- `.claude/skills/torch-spyre-forward-compat/references/` —
  validation ladder, three-state protocol, failure taxonomy, patch
  policy, verification policy, upstream investigation, environment
  policy, case-schema.
- `.claude/skills/torch-spyre-forward-compat/scripts/` — pod
  provisioning, environment capture, three-state runners, patch
  verification, resolve-versions helper.
- `analyses/2026-08-frontend-impact-skill-validation/` — the
  precedent skill-validation study for `frontend-compiler-impact`;
  same house style, different skill.

## Reference facts (frozen at study start)

- **torch-spyre main HEAD**: `a31289852145a59099edccc3e506cf5336e8e2e0`
  (2026-08-21).
- **pytorch main HEAD**: `73961011bf64f1c04b3291bf90ac1dbbe197c2ca`
  (2026-08-21).
- **Fresh pod for the primary case**: `tdeshane-forward-compat-2026-08-21`
  in namespace `a5-deepview`.
- **Base image (mutable tag; digest recorded at pod creation)**:
  `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest`.
- **Torch pin declared by torch-spyre**: currently `torch~=2.13.0`
  in `pyproject.toml`; scripts re-read this at runtime and never
  hard-code it, so a pin bump before the pod run does not
  invalidate the study.

## Bottom line

**SKILL AUTHORED, EMPIRICAL VALIDATION PENDING.** The scaffold is
in place. The pod run of 2026-08-21 will fill
[`SUMMARY.md`](SUMMARY.md), populate
[`cases/current-main/environment/`](cases/current-main/environment/)
with `00-environment.json` under all three control states,
[`cases/current-main/failures/`](cases/current-main/failures/) with
one subdirectory per Stage-N break, and
[`cases/current-main/patches/`](cases/current-main/patches/) with
each break's minimum patch, and produce the case's `case.json` at
the top of `cases/current-main/`.
