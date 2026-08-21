# `environment/` — capture directory

This directory holds the per-state, per-stage environment capture
JSON emitted by the pod run of 2026-08-21. It is empty at scaffold
time. `.gitkeep` reserves the directory in git; this note records
what will be here after the run and how it is produced.

## Runner

`.claude/skills/torch-spyre-forward-compat/scripts/capture_environment.py`
is the authoritative capture script. It re-reads
`torch-spyre/pyproject.toml` at runtime to recover the currently
declared torch pin (currently `torch~=2.13.0`); it never hard-codes
the pin. It resolves pytorch main HEAD and torch-spyre main HEAD
via `git ls-remote` at run time and records both SHAs. It resolves
the base image tag
`us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest`
to its immutable `@sha256:...` digest at pod-creation time and
records that digest.

## Filenames

The naming convention is `<stage>-<what>.<state>.json`, where:

- `<stage>` is `00` through `06` per the validation ladder.
- `<what>` names the stage's check (`environment`, `torch-install`,
  `torch-spyre-install`, `import`, `device`, `ops`, `compile`).
- `<state>` is `supported`, `forward`, or `after`.

Under each control state, Stage 0 (`00-environment.<state>.json`)
is always present. Stages 1-6 under `FORWARD_BEFORE_FIX` are
present only up to the first failing stage inclusive: the ladder
halts on failure and does not run subsequent stages under that
state. `FORWARD_AFTER_FIX` runs the same stages the successful
`SUPPORTED_CONTROL` walk ran, so `01`-`06` all appear once the
patch loop closes.

## What each JSON records

Every capture records at least:

- `state`: `supported` | `forward` | `after`.
- `stage`: `0` through `6`.
- `pod`: pod name (`tdeshane-forward-compat-2026-08-21`) and
  namespace (`a5-deepview`).
- `image`: tag as configured plus the resolved
  `@sha256:...` digest.
- `pytorch_sha`: for `supported`, the SHA that the pinned wheel
  resolves to at run time; for `forward` and `after`, the resolved
  pytorch main HEAD (`73961011bf64f1c04b3291bf90ac1dbbe197c2ca` as
  of 2026-08-21).
- `torch_spyre_sha`: `a31289852145a59099edccc3e506cf5336e8e2e0`
  (main HEAD as of 2026-08-21), or the same SHA plus a
  patch identifier under `after`.
- `torch_declared_pin`: the pin as parsed from
  `torch-spyre/pyproject.toml` at run time (currently
  `torch~=2.13.0`).
- Stage-specific fields per the validation ladder: exit code,
  stdout tail, stderr tail, traceback if any, timing.

Stage 0's JSON additionally records kernel, glibc, python, pip
version, `NIXL_PLUGIN_DIR` (when set), and any environment
variables the runner explicitly considers load-bearing.

## Why the note lives here

The capture directory needs to exist in git before the pod run so
that the file layout is fixed and reproducible from the scaffold.
Placing this note alongside `.gitkeep` gives a fresh Claude
session the exact runner path and the file-name convention without
requiring a search across the skill's `scripts/` and `references/`
directories.
