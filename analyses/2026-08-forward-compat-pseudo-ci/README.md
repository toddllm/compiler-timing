# 2026-08 — Forward-compat pseudo-CI (Track A)

Shadow / on-demand compatibility lane over open torch-spyre PRs.

Do NOT modify or comment on active PRs. Do NOT wire this into
production CI. Do NOT make status checks required. This is
observational Claude-operated shadow work; posts nothing back to
the PRs or upstream repos.

## Layout

- `SUMMARY.md` — Track A findings.
- `notes/synthesis.md` — cross-track synthesis with Track B.
- `inventory/`
  - `open-prs.json` — 216 open PRs at snapshot 2026-08-25.
  - `ci-infrastructure.md` — existing CI workflows and what they
    can do out of the box.
  - `wf-*.yaml` — snapshots of the key GH Actions workflows.
- `triage/`
  - `triage.json` — every open PR, augmented with `file_categories`,
    `triage_class`, `priority_score`.
  - `triage.md` — rendered distribution + top-30 by priority.
- `cases/pr-3404/` — the one empirical case run. `PR_STALE_AGAINST_MAIN`
  detected in 7 min of device time.

## Snapshot metadata

- torch-spyre main: `613b259aacbee507c34ccba1e3e25280a6bc55cb`
- pytorch main: `26b9ddd7f8a46a15067a7cdc789623f3cdee2cb1`
- torch pin: `torch~=2.13.0`
- forward torch under test: NIGHTLY_PROXY
  `2.15.0.dev20260824+cpu` (git `c0577575`)
- open PRs: 216 (129 non-draft, 87 draft)
