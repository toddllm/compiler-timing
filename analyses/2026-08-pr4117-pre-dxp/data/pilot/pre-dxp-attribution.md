# Pre-DXP time attribution

Median-of-N cold samples, milliseconds. `pre_dxp_total` is derived directly from timestamps as `pre_dxp_boundary_marker.t_start − first_call_wall.t_start`; nothing is subtracted from `compile_fx_wrapper` or `graphlowering_compile_to_module`.

| shape | N | fx_nodes | presched_ops | n_kernels | n_specs | pre_dxp_total | pre_compile_fx | compile_fx_wrapper_pre_dxp |
|---|---|---|---|---|---|---|---|---|
| flash-1024x8192 | 1 | 3372 | 4100 | 1 | 4097 | 516824.8 | 1918.6 | 514906.3 |
| flash-512x1024 | 1 | 236 | 260 | 1 | 257 | 27704.5 | 334.5 | 27370.0 |
| flash-512x8192 | 1 | 1692 | 2052 | 1 | 2049 | 193574.9 | 1205.2 | 192369.6 |
| mlp-L2-w2048 | 1 | 12 | 6 | 1 | 6 | 10574.7 | 182.3 | 10392.4 |
| mlp-L32-w2048 | 1 | 162 | 96 | 1 | 96 | 6981.7 | 144.0 | 6837.7 |

## Percent of pre-DXP total

| shape | pre_compile_fx | compile_fx_wrapper_pre_dxp |
|---|---|---|
| flash-1024x8192 | 0.4% | 99.6% |
| flash-512x1024 | 1.2% | 98.8% |
| flash-512x8192 | 0.6% | 99.4% |
| mlp-L2-w2048 | 1.7% | 98.3% |
| mlp-L32-w2048 | 2.1% | 97.9% |

## Full bucket detail

Every measured bucket, including derived residuals. `sentinel_unwind` should be small (< 20 ms typically) — if it grows, that is stack-unwind overhead contaminating first_call_wall's inclusive time, and the primary `pre_dxp_total` column above already excludes it.

| shape | pre_compile_fx | compile_fx_wrapper | compile_fx_wrapper_pre_dxp | compile_fx_outer_other | spyre_inner_compile | inner_compile_other | graphlowering_run | graphlowering_compile_to_module | compile_to_module_other | graphlowering_codegen | graphlowering_codegen_other | spyre_update_scheduler | spyre_update_scheduler_other | recover_spyre_hints | custompresched_total | presched_pass_loop | presched_cost_model | presched_cost_dump | presched_finalize_work_division | upstream_update_scheduler | scheduler_init | custompref_fusion | custompost_fusion | scheduler_codegen | scheduler_codegen_other | spyre_kernel_codegen_total | wrapper_codegen | wrapper_module_exec | async_compile_wait | async_compile_wait_other | sdsc_total | sdsc_bundle_gen_total | kernel_provenance_total | dxp_standalone_total | sentinel_unwind |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| flash-1024x8192 | 1918.6 | 514909.8 | 514906.3 | 12920.4 | 501989.4 | 5249.2 | 6198.5 | 490541.7 | 0.1 | 426720.8 | 237.9 | 410681.4 | 0.1 | 16.6 | 391794.2 | 390637.8 | 0.0 | 0.0 | 1156.3 | 18870.5 | 18870.2 | 1380.3 | 1602.2 | 15801.5 | 11072.7 | 4728.8 | 222.3 | 63820.8 | 0.0 | 0.0 | 40849.7 | 35375.2 | 5364.9 | 108.8 | 260.9 |
| flash-512x1024 | 334.5 | 27375.8 | 27370.0 | 12191.4 | 15184.4 | 526.8 | 591.9 | 14065.7 | 0.1 | 10127.7 | 34.5 | 9178.3 | 0.1 | 0.2 | 8321.6 | 8246.7 | 0.0 | 0.0 | 74.8 | 856.5 | 856.4 | 88.4 | 248.8 | 914.8 | 604.7 | 310.1 | 15.2 | 3937.8 | 0.0 | 0.0 | 2460.9 | 2108.7 | 340.4 | 11.2 | 143.6 |
| flash-512x8192 | 1205.2 | 192375.5 | 192369.6 | 21099.7 | 171275.7 | 2720.9 | 3208.8 | 165346.1 | 0.2 | 133859.7 | 140.4 | 126065.8 | 0.1 | 4.6 | 117983.3 | 117416.4 | 0.0 | 0.0 | 566.9 | 8077.8 | 8077.6 | 694.2 | 775.7 | 7653.4 | 5286.2 | 2367.2 | 113.7 | 31486.2 | 0.0 | 0.0 | 20013.4 | 17277.3 | 2692.5 | 42.8 | 203.2 |
| mlp-L2-w2048 | 182.3 | 10394.8 | 10392.4 | 7867.4 | 2527.4 | 41.8 | 118.6 | 2367.0 | 0.1 | 2283.3 | 16.3 | 2223.6 | 0.0 | 0.0 | 2197.8 | 2197.4 | 0.0 | 0.0 | 0.4 | 25.7 | 25.6 | 3.2 | 4.0 | 43.5 | 22.3 | 21.2 | 0.7 | 83.6 | 0.0 | 0.0 | 42.5 | 32.4 | 4.3 | 5.5 | 38.2 |
| mlp-L32-w2048 | 144.0 | 6841.1 | 6837.7 | 3666.5 | 3174.6 | 84.0 | 147.8 | 2942.8 | 0.1 | 2117.1 | 17.5 | 1828.0 | 0.1 | 0.0 | 1625.2 | 1623.1 | 0.0 | 0.0 | 2.1 | 202.7 | 202.6 | 37.1 | 26.4 | 271.6 | 159.5 | 112.1 | 5.5 | 825.7 | 0.0 | 0.0 | 538.5 | 460.2 | 71.6 | 6.4 | 42.5 |
