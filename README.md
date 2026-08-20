# compiler-timing

Empirical compiler-performance investigations — primarily Torch-Spyre
and upstream `torch.compile` / Inductor, but scoped broadly so any
future compiler-timing study can live here without renaming the repo.

Each study is self-contained under `analyses/<yyyy-mm>-<slug>/` and
carries its own README, instrumentation patches, raw data, and plots.

## Current analyses

- [`analyses/2026-08-pr3806-frontend-timing/`](analyses/2026-08-pr3806-frontend-timing/)
  — Torch-Spyre front-end compiler timing study for the OpSpec-tiling
  flash-attention test introduced in `torch-spyre` PR #3806
  (`tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash`).
  Cold-compile scaling sweep across `Lq` and `Lk`, controlled
  `H`-dimension sweep, exhaustive compile-stage decomposition, ranking
  of the pre-scheduling passes that dominate. Central result:
  `dedup_and_promote_constants` scales as `|operations| × |duplicates|`
  derived directly from source, with measured pass time agreeing with
  the model within a few percent across a 250× workload range and
  generalizing out-of-sample across an independent `H`-growth axis.
  Start with
  [`analyses/2026-08-pr3806-frontend-timing/notes/findings.md`](analyses/2026-08-pr3806-frontend-timing/notes/findings.md).

- [`analyses/2026-08-frontend-scaling-cross-workload/`](analyses/2026-08-frontend-scaling-cross-workload/)
  — Cross-workload frontend compiler scalability investigation
  extending the PR #3806 dataset with a second workload family: WSR/
  coarse-tiled KV-chunked FlashAttention derived from torch-spyre
  PR #3812. Identifies three distinct frontend scaling mechanisms
  (repeated dependency work, restickify search-state explosion,
  workload-topology-dependent scratchpad scaling) plus the backend as
  a separate concern. Includes measured optimization prototypes for
  the top opportunities.

  **Start with the 2-minute summary:
  [`analyses/2026-08-frontend-scaling-cross-workload/SUMMARY.md`](analyses/2026-08-frontend-scaling-cross-workload/SUMMARY.md).**
  Then the ranked opportunity list
  [`notes/engineering-opportunities.md`](analyses/2026-08-frontend-scaling-cross-workload/notes/engineering-opportunities.md)
  and the full technical synthesis
  [`notes/findings.md`](analyses/2026-08-frontend-scaling-cross-workload/notes/findings.md).

## Frontend compiler impact skill

The repository ships a Claude Code skill at
[`.claude/skills/frontend-compiler-impact/`](.claude/skills/frontend-compiler-impact/)
that encodes the compiler-performance understanding from the two
studies above into a reusable decision process.

**What it does**: given a torch-spyre PR, commit range, or local
branch, it (1) statically triages the diff onto compiler stages,
(2) picks the smallest experiment that could confirm or refute the
static hypothesis (Level 0/1/2/3/4), (3) commits its prediction
BEFORE any measurement, (4) if warranted, runs a paired base/head
sample, (5) classifies the result into one of seven verdicts.

**How to invoke**:

```bash
# One-line static triage:
.claude/skills/frontend-compiler-impact/scripts/resolve_target.sh 3890 \
  | .claude/skills/frontend-compiler-impact/scripts/static_triage.py

# Fast open-PR scan (no device time):
.claude/skills/frontend-compiler-impact/scripts/scan_open_prs.sh \
    torch-spyre/torch-spyre --limit 40
```

The skill's decision process, references, and scripts are
self-contained; a fresh Claude Code session with no prior context
can use it directly from this repo.

**Empirical validation**:
[`analyses/2026-08-frontend-impact-skill-validation/`](analyses/2026-08-frontend-impact-skill-validation/)
applies the skill to four currently-open torch-spyre PRs and
scores its triage accuracy, prediction calibration, and device-time
efficiency. Start with
[`SUMMARY.md`](analyses/2026-08-frontend-impact-skill-validation/SUMMARY.md).

## Layout of a study directory

```
analyses/<yyyy-mm>-<slug>/
  README.md            # methodology and reproduction
  data/                # raw JSON dumps, one per cold-compile sample
  plots/               # PNG plots produced from data/
  patches/             # instrumentation patches and analysis scripts
  notes/               # findings, boundary map, resolved config, tables
```

## Ground rules

- Cold compilation only. Warm runs are labeled as such and used only
  as sanity checks.
- Heavyweight diagnostics (`TORCH_COMPILE_DEBUG=1`, `TORCH_SPYRE_DEBUG=1`,
  verbose logs) are kept out of the timing dataset; diagnostic runs
  are performed separately.
- Every measurement carries the git SHA it was taken against, an
  environment probe, the resolved compiler configuration, and a
  documented cache methodology.
- Instrumentation must reconcile to the enclosing wall-clock stage;
  any residual is reported explicitly rather than absorbed.
- Spyre tests run strictly serially: the device is exclusive per
  process.
