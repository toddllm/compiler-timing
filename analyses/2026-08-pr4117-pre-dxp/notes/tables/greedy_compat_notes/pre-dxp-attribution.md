# Pre-DXP time attribution

Median-of-N cold samples, milliseconds. `pre_dxp_total` is derived directly from timestamps as `pre_dxp_boundary_marker.t_start − first_call_wall.t_start`; nothing is subtracted from `compile_fx_wrapper` or `graphlowering_compile_to_module`.

| shape | N | fx_nodes | presched_ops | n_kernels | n_specs | pre_dxp_total | pre_compile_fx | compile_fx_wrapper_pre_dxp |
|---|---|---|---|---|---|---|---|---|
| flash-512x1024 | 3 | 236 | 260 | 1 | 273 | 15532.0 | 776.6 | 14755.4 |
| flash-512x4096 | 3 | 860 | 1028 | 1 | 1089 | 57661.0 | 1414.6 | 56246.4 |
| flash-512x8192 | 3 | 1692 | 2052 | 1 | 2177 | 135302.3 | 3221.8 | 131757.2 |

## Percent of pre-DXP total

| shape | pre_compile_fx | compile_fx_wrapper_pre_dxp |
|---|---|---|
| flash-512x1024 | 5.0% | 95.0% |
| flash-512x4096 | 2.5% | 97.5% |
| flash-512x8192 | 2.4% | 97.4% |

## Full bucket detail

Every measured bucket, including derived residuals. `sentinel_unwind` should be small (< 20 ms typically) — if it grows, that is stack-unwind overhead contaminating first_call_wall's inclusive time, and the primary `pre_dxp_total` column above already excludes it.

| shape | pre_compile_fx | compile_fx_wrapper | compile_fx_wrapper_pre_dxp | compile_fx_outer_other | spyre_inner_compile | inner_compile_other | graphlowering_run | graphlowering_compile_to_module | compile_to_module_other | graphlowering_codegen | graphlowering_codegen_other | spyre_update_scheduler | spyre_update_scheduler_other | recover_spyre_hints | custompresched_total | presched_pass_loop | presched_cost_model | presched_cost_dump | presched_finalize_work_division | upstream_update_scheduler | scheduler_init | custompref_fusion | custompost_fusion | scheduler_codegen | scheduler_codegen_other | spyre_kernel_codegen_total | wrapper_codegen | wrapper_module_exec | async_compile_wait | async_compile_wait_other | sdsc_total | sdsc_bundle_gen_total | kernel_provenance_total | dxp_standalone_total | sentinel_unwind | scratchpad_plan_allocation | scratchpad_prepare_buffers | scratchpad_build_solver | scratchpad_solve | scratchpad_post_solve |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| flash-512x1024 | 776.6 | 14760.0 | 14755.4 | 3607.0 | 11153.0 | 399.3 | 398.7 | 10364.7 | 0.1 | 6389.8 | 22.6 | 5265.8 | 0.0 | 0.2 | 4568.1 | 4489.4 | 0.0 | 0.0 | 78.6 | 697.5 | 697.4 | 66.4 | 114.6 | 1105.5 | 792.0 | 313.5 | 14.8 | 3954.8 | 0.0 | 0.0 | 2644.4 | 2293.1 | 335.2 | 10.9 | 56.4 | 788.1 | 765.3 | 0.0 | 8.5 | 0.0 |
| flash-512x4096 | 1414.6 | 56249.6 | 56246.4 | 5525.2 | 51149.6 | 1431.6 | 1554.5 | 48163.5 | 0.1 | 31919.1 | 69.0 | 28224.0 | 0.1 | 1.5 | 24784.5 | 24478.4 | 0.0 | 0.0 | 306.1 | 3438.0 | 3437.8 | 426.2 | 450.0 | 3623.8 | 2469.4 | 1145.8 | 59.5 | 16244.3 | 0.0 | 0.0 | 11063.2 | 9684.3 | 1341.0 | 38.1 | 120.8 | 3456.7 | 3251.6 | 0.0 | 126.8 | 0.0 |
| flash-512x8192 | 3221.8 | 131760.0 | 131757.2 | 11591.0 | 120169.0 | 2945.3 | 3053.2 | 114112.9 | 0.1 | 81312.0 | 132.9 | 73809.0 | 0.1 | 4.5 | 66088.0 | 65473.2 | 0.0 | 0.0 | 611.8 | 7658.9 | 7658.8 | 804.6 | 912.7 | 7356.3 | 5082.0 | 2274.3 | 117.0 | 32730.4 | 0.0 | 0.0 | 21879.3 | 19108.0 | 2682.7 | 73.6 | 215.6 | 8187.9 | 7453.7 | 0.0 | 501.0 | 0.0 |
