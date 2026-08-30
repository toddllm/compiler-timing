# Adaptive-solver REAL validation

3 cold samples per shape/arm. Both arms have configured `LAYOUT_SOLVER=cpsat`; the adaptive arm has `ADAPTIVE_SOLVER_THRESHOLD_OPS=500` set, so `scratchpad_planning` chooses the greedy fallback (with per-instance `enable_lx_relayout=False`) at every shape above threshold. Baseline is the exact existing CP-SAT-only behavior.

## Chosen solver per arm

| shape | n_ops | baseline configured | baseline chosen | adaptive configured | adaptive chosen |
|---|---:|---|---|---|---|
| flash-1024x1024 | 516 | cpsat | CpSatLayoutSolver | cpsat | GreedyLayoutSolver |
| flash-1024x8192 | 4100 | cpsat | CpSatLayoutSolver | cpsat | GreedyLayoutSolver |
| flash-2048x1024 | 1028 | cpsat | CpSatLayoutSolver | cpsat | GreedyLayoutSolver |
| flash-512x8192 | 2052 | cpsat | CpSatLayoutSolver | cpsat | GreedyLayoutSolver |

## Per-shape median pre-DXP (ms)

| shape | n_ops | baseline_pre_dxp | adaptive_pre_dxp | delta_ms | delta_% | baseline_scratch | adaptive_scratch | baseline_solve | adaptive_solve |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| flash-1024x1024 | 516 | 33791.4 | 28039.2 | -5752.2 | -17.0% | 2697.9 | 1122.2 | 1639.5 | 17.2 |
| flash-1024x8192 | 4100 | 510931.1 | 313529.5 | -197401.5 | -38.6% | 212566.7 | 13683.6 | 199926.7 | 1021.4 |
| flash-2048x1024 | 1028 | 69917.9 | 56496.7 | -13421.2 | -19.2% | 11107.7 | 2156.2 | 8948.3 | 65.3 |
| flash-512x8192 | 2052 | 176977.9 | 124104.5 | -52873.4 | -29.9% | 55569.4 | 5201.9 | 50566.5 | 258.0 |

## Signature equivalence (baseline vs adaptive)

Best-of-9 pairing (3 baseline samples × 3 adaptive samples). Cross-run bundle nondeterminism is documented in `notes/next-opportunities.md` — a nonzero delta here reflects either that or a real divergence.

| shape | planner_buffers ok | placed (name,size) diff | placed (name,size,address) diff | spilled (name,size) diff | baseline n_specs | adaptive n_specs | specs_delta |
|---|:---:|---|---|---|---:|---:|---:|
| flash-1024x1024 | YES | MATCH (agree=225) | only_baseline=187 only_adaptive=187 agreed=38 | MATCH (agree=295) | 513 | 513 | +0 |
| flash-1024x8192 | YES | MATCH (agree=1793) | only_baseline=1142 only_adaptive=1142 agreed=651 | MATCH (agree=2311) | 4097 | 4097 | +0 |
| flash-2048x1024 | YES | MATCH (agree=449) | only_baseline=381 only_adaptive=381 agreed=68 | MATCH (agree=583) | 1025 | 1025 | +0 |
| flash-512x8192 | YES | MATCH (agree=897) | only_baseline=566 only_adaptive=566 agreed=331 | MATCH (agree=1159) | 2049 | 2049 | +0 |

## Per-sample pre-DXP (for variance visibility)

| shape | arm | run1 | run2 | run3 | median |
|---|---|---:|---:|---:|---:|
| flash-1024x1024 | baseline | 47951.5 | 33791.4 | 30628.0 | 33791.4 |
| flash-1024x1024 | adaptive | 34394.7 | 26580.4 | 28039.2 | 28039.2 |
| flash-1024x8192 | baseline | 504631.2 | 601650.6 | 510931.1 | 510931.1 |
| flash-1024x8192 | adaptive | 313529.5 | 318512.6 | 310801.2 | 313529.5 |
| flash-2048x1024 | baseline | 70895.1 | 69917.9 | 69687.9 | 69917.9 |
| flash-2048x1024 | adaptive | 54720.3 | 57828.1 | 56496.7 | 56496.7 |
| flash-512x8192 | baseline | 176977.9 | 177888.0 | 175469.9 | 176977.9 |
| flash-512x8192 | adaptive | 122987.0 | 124104.5 | 124757.4 | 124104.5 |

