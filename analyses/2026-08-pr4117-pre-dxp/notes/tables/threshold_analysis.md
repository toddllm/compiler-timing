# Threshold-prototype analysis (§3 + §4)

Reads baseline CP-SAT primary data (3 cold samples per shape) and greedy-arm-A / greedy-arm-B data (1 sample per shape). Simulates the adaptive policy `if n_operations > T then greedy else cpsat` at several thresholds.

## Per-shape summary

| shape | n_ops | cpsat_pre_dxp | greedyA_pre_dxp | greedyB_pre_dxp | cpsat_scratch | greedyA_scratch | greedyB_scratch | cpsat_n_specs | greedyA_n_specs | greedyB_n_specs | placed A vs cpsat | placed B vs cpsat |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| flash-1024x1024 | 516 | 31544.2 | 30616.2 | 32225.9 | 2815.2 | 1771.7 | 1184.4 | 513 | 545 | 513 | only_c=0 only_g=64 agreed=225 | only_c=0 only_g=0 agreed=225 |
| flash-1024x8192 | 4100 | 515021.3 | 333348.9 | 315350.3 | 215121.5 | 20550.7 | 13902.1 | 4097 | 4353 | 4097 | only_c=0 only_g=512 agreed=1793 | only_c=0 only_g=0 agreed=1793 |
| flash-2048x1024 | 1028 | 71107.1 | 63604.6 | 59239.4 | 11004.1 | 3572.0 | 2161.2 | 1025 | 1089 | 1025 | only_c=0 only_g=128 agreed=449 | only_c=0 only_g=0 agreed=449 |
| flash-256x1024 | 110 | 11176.1 | 14932.5 | 11924.1 | 389.6 | 370.4 | 218.8 | 107 | 115 | 107 | only_c=0 only_g=16 agreed=57 | only_c=0 only_g=0 agreed=57 |
| flash-512x1024 | 260 | 17806.8 | 16079.0 | 25252.4 | 798.5 | 776.0 | 473.4 | 257 | 273 | 257 | only_c=0 only_g=32 agreed=113 | only_c=0 only_g=0 agreed=113 |
| flash-512x2048 | 516 | 31189.5 | 29118.7 | 42285.7 | 2718.9 | 1791.3 | 1145.0 | 513 | 545 | 513 | only_c=0 only_g=64 agreed=225 | only_c=0 only_g=0 agreed=225 |
| flash-512x4096 | 1028 | 65580.9 | 61383.7 | 58245.0 | 11187.5 | 3520.4 | 2178.0 | 1025 | 1089 | 1025 | only_c=0 only_g=128 agreed=449 | only_c=0 only_g=0 agreed=449 |
| flash-512x512 | 132 | 11317.1 | 12009.9 | 12812.8 | 391.9 | 399.6 | 233.1 | 129 | 137 | 129 | only_c=0 only_g=16 agreed=57 | only_c=0 only_g=0 agreed=57 |
| flash-512x8192 | 2052 | 200334.8 | 137204.1 | 125330.0 | 75696.2 | 8447.3 | 5398.4 | 2049 | 2177 | 2049 | only_c=0 only_g=256 agreed=897 | only_c=0 only_g=0 agreed=897 |
| mlp-L16-w2048 | 48 | 4978.8 | 8980.7 | 7108.1 | 82.1 | 128.2 | 60.4 | 48 | 48 | 48 | only_c=0 only_g=0 agreed=31 | only_c=0 only_g=0 agreed=31 |
| mlp-L2-w2048 | 6 | 3754.1 | 11817.6 | 11966.0 | 19.1 | 8.7 | 6.5 | 6 | 6 | 6 | only_c=0 only_g=0 agreed=3 | only_c=0 only_g=0 agreed=3 |
| mlp-L32-w2048 | 96 | 6039.6 | 8765.9 | 8590.8 | 154.1 | 274.3 | 142.4 | 96 | 96 | 96 | only_c=0 only_g=0 agreed=63 | only_c=0 only_g=0 agreed=63 |
| mlp-L4-w2048 | 12 | 4068.9 | 8080.3 | 6846.8 | 27.4 | 25.4 | 13.4 | 12 | 12 | 12 | only_c=0 only_g=0 agreed=7 | only_c=0 only_g=0 agreed=7 |
| mlp-L64-w2048 | 192 | 8482.1 | 11734.9 | 11727.6 | 318.6 | 640.3 | 370.2 | 192 | 192 | 192 | only_c=0 only_g=0 agreed=127 | only_c=0 only_g=0 agreed=127 |
| mlp-L8-w2048 | 24 | 4721.1 | 7946.2 | 7479.5 | 45.7 | 57.1 | 27.7 | 24 | 24 | 24 | only_c=0 only_g=0 agreed=15 | only_c=0 only_g=0 agreed=15 |

## Threshold sweep — simulated total compile time

Simulates the prototype policy `if config.layout_solver == 'cpsat' and n_operations > T, use greedy fallback; else keep cpsat`.

Two fallback flavors: **A** = greedy at pod-default SPYRE_LX_PLANNER_RELAYOUT=1 (greedy's normal behavior, includes LX-relayout paired-buffer expansion), **B** = SPYRE_LX_PLANNER_RELAYOUT=0 (solver-only fallback).

| threshold_n_ops | baseline_total_s | armA_total_s | armA_savings_s | armA_savings_% | armA_switched | armB_total_s | armB_savings_s | armB_savings_% | armB_switched |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 987.1 | 755.6 | 231.5 | 23.5% | 15/15 | 736.4 | 250.7 | 25.4% | 15/15 |
| 100 | 987.1 | 733.6 | 253.5 | 25.7% | 10/15 | 718.0 | 269.2 | 27.3% | 10/15 |
| 200 | 987.1 | 725.9 | 261.2 | 26.5% | 7/15 | 712.5 | 274.7 | 27.8% | 7/15 |
| 300 | 987.1 | 727.6 | 259.5 | 26.3% | 6/15 | 705.0 | 282.1 | 28.6% | 6/15 |
| 500 | 987.1 | 727.6 | 259.5 | 26.3% | 6/15 | 705.0 | 282.1 | 28.6% | 6/15 |
| 800 | 987.1 | 730.6 | 256.5 | 26.0% | 4/15 | 693.2 | 293.9 | 29.8% | 4/15 |
| 1200 | 987.1 | 742.3 | 244.8 | 24.8% | 2/15 | 712.4 | 274.7 | 27.8% | 2/15 |
| 2000 | 987.1 | 742.3 | 244.8 | 24.8% | 2/15 | 712.4 | 274.7 | 27.8% | 2/15 |
| 3000 | 987.1 | 805.5 | 181.7 | 18.4% | 1/15 | 787.5 | 199.7 | 20.2% | 1/15 |
| 1000000000 | 987.1 | 987.1 | 0.0 | 0.0% | 0/15 | 987.1 | 0.0 | 0.0% | 0/15 |

## Downstream difference between arms

Same as the per-shape summary but focused on downstream differences that would ship: n_specs (kernels' spec count fed into SDSC) and placed-set overlap.

| shape | cpsat_n_specs | greedyA_n_specs | greedyB_n_specs | specs_delta_A | specs_delta_B | placed_agree_A | placed_agree_B |
|---|---:|---:|---:|---:|---:|---|---|
| flash-1024x1024 | 513 | 545 | 513 | +32 | +0 | only_cpsat=0 only_greedy=64 agreed=225 | only_cpsat=0 only_greedy=0 agreed=225 |
| flash-1024x8192 | 4097 | 4353 | 4097 | +256 | +0 | only_cpsat=0 only_greedy=512 agreed=1793 | only_cpsat=0 only_greedy=0 agreed=1793 |
| flash-2048x1024 | 1025 | 1089 | 1025 | +64 | +0 | only_cpsat=0 only_greedy=128 agreed=449 | only_cpsat=0 only_greedy=0 agreed=449 |
| flash-256x1024 | 107 | 115 | 107 | +8 | +0 | only_cpsat=0 only_greedy=16 agreed=57 | only_cpsat=0 only_greedy=0 agreed=57 |
| flash-512x1024 | 257 | 273 | 257 | +16 | +0 | only_cpsat=0 only_greedy=32 agreed=113 | only_cpsat=0 only_greedy=0 agreed=113 |
| flash-512x2048 | 513 | 545 | 513 | +32 | +0 | only_cpsat=0 only_greedy=64 agreed=225 | only_cpsat=0 only_greedy=0 agreed=225 |
| flash-512x4096 | 1025 | 1089 | 1025 | +64 | +0 | only_cpsat=0 only_greedy=128 agreed=449 | only_cpsat=0 only_greedy=0 agreed=449 |
| flash-512x512 | 129 | 137 | 129 | +8 | +0 | only_cpsat=0 only_greedy=16 agreed=57 | only_cpsat=0 only_greedy=0 agreed=57 |
| flash-512x8192 | 2049 | 2177 | 2049 | +128 | +0 | only_cpsat=0 only_greedy=256 agreed=897 | only_cpsat=0 only_greedy=0 agreed=897 |
| mlp-L16-w2048 | 48 | 48 | 48 | +0 | +0 | only_cpsat=0 only_greedy=0 agreed=31 | only_cpsat=0 only_greedy=0 agreed=31 |
| mlp-L2-w2048 | 6 | 6 | 6 | +0 | +0 | only_cpsat=0 only_greedy=0 agreed=3 | only_cpsat=0 only_greedy=0 agreed=3 |
| mlp-L32-w2048 | 96 | 96 | 96 | +0 | +0 | only_cpsat=0 only_greedy=0 agreed=63 | only_cpsat=0 only_greedy=0 agreed=63 |
| mlp-L4-w2048 | 12 | 12 | 12 | +0 | +0 | only_cpsat=0 only_greedy=0 agreed=7 | only_cpsat=0 only_greedy=0 agreed=7 |
| mlp-L64-w2048 | 192 | 192 | 192 | +0 | +0 | only_cpsat=0 only_greedy=0 agreed=127 | only_cpsat=0 only_greedy=0 agreed=127 |
| mlp-L8-w2048 | 24 | 24 | 24 | +0 | +0 | only_cpsat=0 only_greedy=0 agreed=15 | only_cpsat=0 only_greedy=0 agreed=15 |

