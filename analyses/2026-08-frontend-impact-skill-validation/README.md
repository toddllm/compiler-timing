# Frontend-compiler-impact skill — empirical validation

Empirical evaluation of the `.claude/skills/frontend-compiler-impact/`
Claude Code skill against four currently-open torch-spyre PRs.

**Start with [`SUMMARY.md`](SUMMARY.md)** — 2-minute overview of the
skill and its measured strengths and weaknesses.

## What this study is

This is a validation study of the SKILL itself, not of any
particular PR. Each case measures:

- Did the skill's static triage correctly classify the PR's
  compiler surface?
- Did it choose the right measurement level (Level 0–4)?
- Was its prediction (written before any measurement) correct?
- How much device time did it consume vs a naive "run everything"
  baseline?
- What did the skill learn from any prediction that missed?

## Structure

```
SUMMARY.md                      — 2-minute overview
README.md                       — this file
notes/
    corpus.md                   — validation PR selection rationale
    case-study-summary.md       — cross-case comparison + grades
cases/
    pr-XXXX/
        target.json             — resolved base/head SHAs + changed files
        triage.json             — static_triage.py output
        prediction.json         — prediction written BEFORE measurement
        01-static-assessment.md — narrative static assessment
        02-experiment-plan.md   — measurement plan before run
        03-results.md           — measurement results (or "no run")
        04-retrospective.md     — prediction vs measurement
        impact.json             — machine-readable summary
data/
    scan-2026-08-20.{md,json}   — open-PR scan at validation time
    workspace-baseline/         — reference sample for cross-case sanity
```

## Cases

| PR | Category | Level | Verdict |
|---:|:---|---:|:---|
| **#3871** | negative control (tests-only) | 0 | NO_RUN |
| **#3873** | activation-specific feature (torch.full layout) | 1 | ACTIVATION_SPECIFIC_IMPACT |
| **#3849** | ambiguous (scratchpad validation/guard changes + csrc) | 1 | INSUFFICIENT_EVIDENCE (pod substrate) |
| **#3890** | frontend-relevant (coarse_tile correctness fix) | 3 | INSUFFICIENT_EVIDENCE (pod substrate) |

## Reproduction

```bash
# Refresh the open-PR list
.claude/skills/frontend-compiler-impact/scripts/scan_open_prs.sh \
    torch-spyre/torch-spyre --limit 40

# Per-PR triage
.claude/skills/frontend-compiler-impact/scripts/resolve_target.sh 3890 \
    | .claude/skills/frontend-compiler-impact/scripts/static_triage.py

# Emit machine-readable impact report
python3 .claude/skills/frontend-compiler-impact/scripts/emit_impact_report.py \
    --target cases/pr-3890/target.json \
    --triage cases/pr-3890/triage.json \
    --prediction cases/pr-3890/prediction.json \
    --classification INSUFFICIENT_EVIDENCE \
    --confidence medium \
    --device-used-seconds 100 \
    --device-avoided-seconds 1520
```

## Related work

- `.claude/skills/frontend-compiler-impact/SKILL.md` — the skill
  under evaluation.
- `analyses/2026-08-pr3806-frontend-timing/` — workload A study
  (source of dedup, scratchpad, restickify measurements).
- `analyses/2026-08-frontend-scaling-cross-workload/` — workload
  B study (source of coarse-tile substage attribution,
  activation-specific/scratchpad-null discipline).
