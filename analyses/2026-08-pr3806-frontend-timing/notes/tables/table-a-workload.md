### Table A — workload scaling

Times are medians across `n` cold-compile samples per point, in seconds. `compile_fx_wrapper` is exhaustively partitioned into four buckets that sum to it (up to a negligible `async_compile_wait`):

- `dxp_standalone` — external backend compiler subprocess.
- `sdsc_prep` — torch-side SDSC/backend-input preparation (`sdsc_total − dxp_standalone`; includes `sdsc_bundle_gen` and kernel-provenance bookkeeping).
- `Spyre pass pipelines` — the six Spyre custom pass pipelines (`CustomPreGrad`, `CustomPre`, `CustomPost`, `CustomPreFusion`, `CustomPostFusion`, `CustomPreScheduling`).
- `unattributed_compile_fx` — the remaining time inside `compile_fx_wrapper` that this instrumentation does not yet bracket individually (upstream Inductor lowering, AOTAutograd, codegen, wrapper generation).

Bucket subtraction is performed **per run** and then medianed; medians are not composed algebraically.

| H | Lq | Lk | inner_bodies | FX nodes | n_specs | wall (s) | compile_fx (s) | dxp_standalone (s) | sdsc_prep (s) | Spyre pass pipelines (s) | unattributed compile_fx (s) | n |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 256 | 1024 | 4 | 124 | 115 | 43.81 | 42.78 | 31.17 | 0.67 | 2.19 | 8.78 | 3 |
| 8 | 512 | 512 | 4 | 132 | 137 | 53.03 | 51.98 | 36.09 | 0.80 | 2.42 | 12.67 | 3 |
| 8 | 512 | 1024 | 8 | 236 | 273 | 100.52 | 99.36 | 79.60 | 1.74 | 5.28 | 12.45 | 3 |
| 8 | 512 | 2048 | 16 | 444 | 545 | 220.69 | 219.50 | 186.58 | 3.38 | 13.84 | 16.81 | 3 |
| 8 | 1024 | 1024 | 16 | 460 | 545 | 234.19 | 232.70 | 195.97 | 3.36 | 13.79 | 17.98 | 3 |
| 16 | 512 | 1024 | 16 | 460 | 545 | 222.19 | 220.91 | 188.00 | 3.35 | 13.89 | 14.64 | 3 |
| 8 | 512 | 4096 | 32 | 860 | 1089 | 569.48 | 568.03 | 497.70 | 6.53 | 40.71 | 24.09 | 3 |
| 8 | 2048 | 1024 | 32 | 908 | 1089 | 611.04 | 609.53 | 538.53 | 6.58 | 40.67 | 23.91 | 3 |
| 32 | 512 | 1024 | 32 | 908 | 1089 | 581.55 | 580.10 | 509.65 | 6.57 | 40.39 | 24.36 | 3 |
| 8 | 512 | 8192 | 64 | 1692 | 2177 | 2381.31 | 2379.66 | 2198.93 | 13.29 | 128.90 | 40.20 | 3 |
| 8 | 1024 | 8192 | 128 | 3372 | 4353 | 13958.26 | 13955.57 | 13401.01 | 26.73 | 460.56 | 67.27 | 1 |

### Growth relative to baseline (H=8, Lq=512, Lk=1024)

| H | Lq | Lk | inner_bodies × | FX nodes × | n_specs × | compile_fx × | dxp × | sdsc_prep × | Spyre passes × | unattributed × |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 256 | 1024 | 0.50 | 0.53 | 0.42 | 0.43 | 0.39 | 0.38 | 0.41 | 0.70 |
| 8 | 512 | 512 | 0.50 | 0.56 | 0.50 | 0.52 | 0.45 | 0.46 | 0.46 | 1.02 |
| 8 | 512 | 1024 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 8 | 512 | 2048 | 2.00 | 1.88 | 2.00 | 2.21 | 2.34 | 1.94 | 2.62 | 1.35 |
| 8 | 1024 | 1024 | 2.00 | 1.95 | 2.00 | 2.34 | 2.46 | 1.92 | 2.61 | 1.44 |
| 16 | 512 | 1024 | 2.00 | 1.95 | 2.00 | 2.22 | 2.36 | 1.92 | 2.63 | 1.18 |
| 8 | 512 | 4096 | 4.00 | 3.64 | 3.99 | 5.72 | 6.25 | 3.75 | 7.71 | 1.94 |
| 8 | 2048 | 1024 | 4.00 | 3.85 | 3.99 | 6.13 | 6.77 | 3.77 | 7.71 | 1.92 |
| 32 | 512 | 1024 | 4.00 | 3.85 | 3.99 | 5.84 | 6.40 | 3.77 | 7.65 | 1.96 |
| 8 | 512 | 8192 | 8.00 | 7.17 | 7.97 | 23.95 | 27.62 | 7.62 | 24.42 | 3.23 |
| 8 | 1024 | 8192 | 16.00 | 14.29 | 15.95 | 140.45 | 168.35 | 15.33 | 87.27 | 5.40 |

