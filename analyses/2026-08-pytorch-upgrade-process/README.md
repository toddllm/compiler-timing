# 2026-08 — PyTorch upgrade process archaeology (Track B)

Reconstruction of how the torch-spyre team actually moves from one
supported PyTorch minor to the next, based on the real history of
the 2.11, 2.12, and 2.13 upgrades.

## Layout

- `SUMMARY.md` — Track B findings.
- `historical/`
  - `pt-2.11/{timeline.md, consequences.json}` — PR #1930 reconstruction.
  - `pt-2.12/{timeline.md, consequences.json}` — PR #2218 reconstruction.
  - `pt-2.13/{timeline.md, consequences.json}` — PR #3374 reconstruction.
- `skill-replay/`
  - `SKILL.md.snapshot` — the checked-in `upgrade-pytorch-version` skill.
  - `upgrade-skill-2.11-to-2.12.md` — replay coverage.
  - `upgrade-skill-2.12-to-2.13.md` — replay coverage.
  - `coverage.json` — machine-readable coverage summary.
- `notes/`
  - `existing-upgrade-skill-assessment.md` — what the skill covers.
  - `consequence-taxonomy.md` — the vocabulary a readiness model needs.
  - `actual-team-process.md` — the recurring patterns across upgrades.
  - `downstream-dependencies.md` — vLLM / kineto / spyre-inference /
    hf-adapters coupling.
  - `upgrade-readiness-model.md` — six dimensions with fill-in checks.
- `compatibility-ledger.{json,md}` — 14-entry ledger merging
  historical + open forward-compat cases.

## Snapshot metadata

- torch-spyre main: `613b259aacbee507c34ccba1e3e25280a6bc55cb`
- PT 2.11 PR base: `a84df55fa31be1b71cc211e599c2f50e044b0eca`
- PT 2.12 PR base: `dd95ef44ee298217c8764117ef58665520794bf5`
