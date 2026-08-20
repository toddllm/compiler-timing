# Validation corpus — selected 2026-08-20

Selection criteria (from SKILL.md Part 5):

- At least 2 frontend-relevant PRs
- 1 ambiguous / likely-neutral PR
- 1 negative control

All PRs verified currently open at time of validation.

## Selected PRs

| PR | Title | Rank | Category | Level |
|---|:---|:---|:---|:---|
| **#3890** | Fix 2 bugs in coarse_tile related to dimensions of size 1 | HIGH | frontend-relevant, coarse_tile hot path | 3 |
| **#3873** | feat(inductor): allow specifying STL on `torch.full` | MEDIUM | frontend-relevant, layout_prop + ir_lowering | 1 |
| **#3849** | fix(scratchpad): follow-up review fixes for the native packer | MEDIUM | ambiguous, csrc + scratchpad on validation/guard paths | 1 |
| **#3871** | fix(tests): repair two Gemma op-test helpers | NONE | **negative control**, test-only | 0 |

## Why these

- **#3890** is a strong positive control for the coarse-tile hot-path
  reasoning. Fixing bugs in `coarse_tile.py` could touch performance
  or not; if the change is in a rare-shape guard, the skill should
  say "hot subsystem changed, but this path probably does not execute
  in the sentinel workload".
- **#3873** exercises the skill's layout/restickify reasoning.
  Adding `device_layout=` on `torch.full` may only activate under
  specific arguments. Good stress test of the "activation-specific
  impact" verdict.
- **#3849** is a scratchpad follow-up whose description emphasizes
  validation/guard behavior and unchanged valid layouts. Perfect
  test of the "hot subsystem changed but hot path unchanged" rule.
  Also a C-extension change (rebuild required).
- **#3871** is a clean negative control. A well-behaved skill must
  spend zero device time on it.

## Diff sizes

| PR | Files | + | − |
|---|---:|---:|---:|
| #3890 | 2 | 222 | 21 |
| #3873 | 5 | 191 | 4 |
| #3849 | 12 | 434 | 145 |
| #3871 | 2 | 17 | 1 |

## Base/head SHAs at time of validation

| PR | Base SHA | Head SHA |
|---|---|---|
| #3890 | be1328a867… | 148de44b93… |
| #3873 | be1328a867… | 8c5f911373… |
| #3849 | 53742fecb7… | a4281dce49… |
| #3871 | 3e23d180ee… | cdd9cf915a… |

PRs may be force-pushed after this validation. The case files record
the exact SHA measured at each stage.
