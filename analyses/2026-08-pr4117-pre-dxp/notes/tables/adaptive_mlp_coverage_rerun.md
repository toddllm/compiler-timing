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
| mlp-L128-w2048 | 384 | 23679.2 | 18260.6 | -5418.6 | -22.9% | 694.0 | 700.0 | 242.1 | 251.8 |
| mlp-L192-w2048 | 576 | 26807.6 | 24128.0 | -2679.6 | -10.0% | 1129.9 | 763.4 | 405.2 | 42.7 |
| mlp-L384-w2048 | 1152 | 42384.0 | 38266.0 | -4118.0 | -9.7% | 2896.6 | 2063.2 | 1013.7 | 171.3 |

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
| mlp-L128-w2048 | baseline | 39324.2 | 23679.2 | 17046.0 | 23679.2 |
| mlp-L128-w2048 | adaptive | 19713.5 | 17462.6 | 18260.6 | 18260.6 |
| mlp-L192-w2048 | baseline | 25600.9 | 26807.6 | 29011.7 | 26807.6 |
| mlp-L192-w2048 | adaptive | 22469.7 | 25728.4 | 24128.0 | 24128.0 |
| mlp-L384-w2048 | baseline | 40514.0 | 45654.1 | 42384.0 | 42384.0 |
| mlp-L384-w2048 | adaptive | 38190.5 | 38266.0 | 40341.0 | 38266.0 |

