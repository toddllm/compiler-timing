# Adaptive-solver REAL validation

3 cold samples per shape/arm. Both arms have configured `LAYOUT_SOLVER=cpsat`; the adaptive arm has `ADAPTIVE_SOLVER_THRESHOLD_OPS=500` set, so `scratchpad_planning` chooses the greedy fallback (with per-instance `enable_lx_relayout=False`) at every shape above threshold. Baseline is the exact existing CP-SAT-only behavior.

## Chosen solver per arm

| shape | n_ops | baseline configured | baseline chosen | adaptive configured | adaptive chosen |
|---|---:|---|---|---|---|
| mlp-L128-w2048 | 384 | cpsat | CpSatLayoutSolver | cpsat | CpSatLayoutSolver |
| mlp-L192-w2048 | 576 | cpsat | CpSatLayoutSolver | cpsat | GreedyLayoutSolver |
| mlp-L384-w2048 | 1152 | cpsat | CpSatLayoutSolver | cpsat | GreedyLayoutSolver |

## Per-shape median pre-DXP (ms)

| shape | n_ops | baseline_pre_dxp | adaptive_pre_dxp | delta_ms | delta_% | baseline_scratch | adaptive_scratch | baseline_solve | adaptive_solve |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mlp-L128-w2048 | 384 | 17171.2 | 15432.2 | -1739.0 | -10.1% | 684.9 | 686.8 | 241.1 | 244.7 |
| mlp-L192-w2048 | 576 | 21108.2 | 23427.9 | +2319.8 | +11.0% | 1154.8 | 2095.2 | 435.5 | 1381.5 |
| mlp-L384-w2048 | 1152 | 39036.9 | 44233.7 | +5196.8 | +13.3% | 3113.2 | 7641.5 | 1043.3 | 5573.9 |

## Signature equivalence (baseline vs adaptive)

Best-of-9 pairing (3 baseline samples × 3 adaptive samples). Cross-run bundle nondeterminism is documented in `notes/next-opportunities.md` — a nonzero delta here reflects either that or a real divergence.

| shape | planner_buffers ok | placed (name,size) diff | placed (name,size,address) diff | spilled (name,size) diff | baseline n_specs | adaptive n_specs | specs_delta |
|---|:---:|---|---|---|---:|---:|---:|
| mlp-L128-w2048 | YES | MATCH (agree=255) | MATCH (agree=255) | MATCH (agree=386) | 384 | 384 | +0 |
| mlp-L192-w2048 | YES | MATCH (agree=383) | only_baseline=191 only_adaptive=191 agreed=192 | MATCH (agree=578) | 576 | 576 | +0 |
| mlp-L384-w2048 | YES | MATCH (agree=767) | only_baseline=383 only_adaptive=383 agreed=384 | MATCH (agree=1154) | 1152 | 1152 | +0 |

## Per-sample pre-DXP (for variance visibility)

| shape | arm | run1 | run2 | run3 | median |
|---|---|---:|---:|---:|---:|
| mlp-L128-w2048 | baseline | 30761.7 | 17171.2 | 16673.1 | 17171.2 |
| mlp-L128-w2048 | adaptive | 15432.2 | 17222.7 | 13736.7 | 15432.2 |
| mlp-L192-w2048 | baseline | 19943.9 | 21138.9 | 21108.2 | 21108.2 |
| mlp-L192-w2048 | adaptive | 23761.6 | 23247.8 | 23427.9 | 23427.9 |
| mlp-L384-w2048 | baseline | 37524.6 | 41137.5 | 39036.9 | 39036.9 |
| mlp-L384-w2048 | adaptive | 44233.7 | 45519.4 | 42840.3 | 44233.7 |

