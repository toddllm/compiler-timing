# Pre-DXP time attribution

Median-of-N cold samples, milliseconds. `pre_dxp_total` is derived directly from timestamps as `pre_dxp_boundary_marker.t_start − first_call_wall.t_start`; nothing is subtracted from `compile_fx_wrapper` or `graphlowering_compile_to_module`.

| shape | N | fx_nodes | presched_ops | n_kernels | n_specs | pre_dxp_total | pre_compile_fx | compile_fx_wrapper_pre_dxp |
|---|---|---|---|---|---|---|---|---|
| flash-512x1024 | 1 | 236 | 260 | 1 | 257 | 22085.4 | 343.9 | 21741.5 |

## Percent of pre-DXP total

| shape | pre_compile_fx | compile_fx_wrapper_pre_dxp |
|---|---|---|
| flash-512x1024 | 1.6% | 98.4% |

## Full bucket detail

Every measured bucket, including derived residuals. `sentinel_unwind` should be small (< 20 ms typically) — if it grows, that is stack-unwind overhead contaminating first_call_wall's inclusive time, and the primary `pre_dxp_total` column above already excludes it.

| shape | pre_compile_fx | compile_fx_wrapper | compile_fx_wrapper_pre_dxp | compile_fx_wrapper_other | graphlowering_run | graphlowering_compile_to_module | compile_to_module_other | graphlowering_codegen | graphlowering_codegen_other | spyre_update_scheduler | spyre_update_scheduler_other | recover_spyre_hints | custompresched_total | presched_pass_loop | presched_cost_model | presched_cost_dump | presched_finalize_work_division | upstream_update_scheduler | scheduler_init | custompref_fusion | custompost_fusion | scheduler_codegen | scheduler_codegen_other | spyre_kernel_codegen_total | wrapper_codegen | wrapper_module_exec | async_compile_wait | async_compile_wait_other | sdsc_total | sdsc_bundle_gen_total | kernel_provenance_total | dxp_standalone_total | sentinel_unwind |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| flash-512x1024 | 343.9 | 21746.9 | 21741.5 | 9070.6 | 498.6 | 12177.7 | 0.1 | 8660.9 | 36.3 | 7541.0 | 0.1 | 0.2 | 6829.7 | 6753.3 | 0.0 | 0.0 | 76.4 | 711.0 | 710.9 | 84.1 | 96.5 | 1083.7 | 776.3 | 307.3 | 14.7 | 3516.7 | 0.0 | 0.0 | 2472.1 | 2114.8 | 347.0 | 9.8 | 61.6 |
