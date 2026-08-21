# Case: current-main

**Ran 2026-08-21.** See `../../SUMMARY.md` for the full narrative.

torch-spyre@a3128985 + PyTorch main @ 73961011 (resolved to nightly
proxy `torch 2.15.0.dev20260821+cpu`), plus a SUPPORTED_CONTROL of
`torch~=2.13.0` (pyproject-declared).

## Outcomes

- SUPPORTED_CONTROL: Stage 0 fails with `C_EXTENSION_ABI_BREAK`
  (undefined `c10d::Backend::incref_pyobject`). See
  `failures/F1-supported-control-undefined-symbol/`.
- FORWARD_BEFORE_FIX: Stage 0 succeeds against torch nightly (device
  visible, eager works). Stage 1 fails with a ladder harness bug
  (`NOT_TORCH_SPYRE`). See
  `failures/F3-harness-triton-double-registration/`.
- FORWARD_AFTER_FIX: not attempted. Skill policy forbids applying a
  patch while SUPPORTED_CONTROL is broken.

## Files

- `environment/environment.json` — pod, python, toolchain, image
  paths, env vars captured at run start.
- `environment/versions.json` — live SHAs of pytorch/main and
  torch-spyre/main resolved via `git ls-remote` at run start, plus the
  fixed SHAs used for the experiment.
- `data/case.json` — machine-readable ladder outcomes.
- `data/pipeline.log` — full pipeline trace, one line per STEP.
- `data/build_supported.log` — canonical build against torch 2.13.0.
- `data/build_latest.log` — canonical build against torch nightly.
- `data/supported_stage[0-2].log` — SUPPORTED_CONTROL ladder outputs.
- `data/forward_stage[0-2].log` — FORWARD_BEFORE_FIX ladder outputs.
- `data/declared_torch.txt` — the raw pyproject torch dep string
  parsed at runtime (`torch~=2.13.0`).
- `failures/F1-supported-control-undefined-symbol/` — hypothesis-first
  record for the primary finding.
- `failures/F3-harness-triton-double-registration/` — harness-bug
  record; not a compatibility break.
- `patches/` — empty. See F1's `02-diagnosis-hypothesis.md` for why no
  patch was applied.

## Pod cleanup

`tdeshane-forward-compat-2026-08-21` on `p1-worker-48` (namespace
`a5-deepview`) was deleted after artifact collection. The image
digest `sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6`
is recorded in `environment/environment.json` and would allow a
byte-identical re-provisioning.
