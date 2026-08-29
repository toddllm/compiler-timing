# Bucket scaling

For each bucket, we fit a log-log slope against the natural per-bucket independent variable when available, else against `fx_nodes_at_entry`. Slope > 1 is a super-linear warning, not a gate. Per-unit drift (ms per natural unit) is reported alongside so linear buckets that dominate absolutely are still visible.

## flash (n=9 shapes)

| bucket | unit | slope | ms/unit at max | ms at min | ms at max | ratio |
|---|---|---|---|---|---|---|
| pre_dxp_total | fx_nodes | 1.14 | 152.7347 | 11176.1 | 515021.3 | 46.1× |
| pre_compile_fx | fx_nodes | 0.45 | 1.1794 | 1021.6 | 3976.9 | 3.9× |
| compile_fx_wrapper | fx_nodes | 1.17 | 151.4668 | 10158.4 | 510745.9 | 50.3× |
| compile_fx_outer_other | fx_nodes | 0.31 | 4.0961 | 5561.7 | 13811.9 | 2.5× |
| spyre_inner_compile | fx_nodes | 1.39 | 147.4654 | 4671.1 | 497253.2 | 106.5× |
| inner_compile_other | fx_nodes | 1.03 | 1.7337 | 181.1 | 5845.9 | 32.3× |
| graphlowering_run | fx_nodes | 1.02 | 1.7234 | 197.7 | 5811.2 | 29.4× |
| graphlowering_compile_to_module | fx_nodes | 1.41 | 144.0186 | 4260.4 | 485630.6 | 114.0× |
| custompresched_total | presched_ops | 1.48 | 95.7139 | 1949.3 | 392426.9 | 201.3× |
| presched_pass_loop | presched_ops | 1.48 | 95.4556 | 1916.9 | 391368.1 | 204.2× |
| presched_cost_model | fx_nodes | 0.26 | 0.0000 | 0.0 | 0.0 | 2.4× |
| presched_finalize_work_division | fx_nodes | 1.03 | 0.3140 | 33.0 | 1058.7 | 32.1× |
| upstream_update_scheduler | fx_nodes | 1.22 | 4.9968 | 300.9 | 16849.4 | 56.0× |
| scheduler_init | sched_nodes | 1.13 | 4.1095 | 300.8 | 16849.0 | 56.0× |
| scheduler_codegen | sched_nodes | 1.00 | 3.5040 | 369.3 | 14366.3 | 38.9× |
| spyre_kernel_codegen_total | fx_nodes | 1.04 | 1.0427 | 107.6 | 3516.0 | 32.7× |
| wrapper_codegen | fx_nodes | 1.05 | 0.0654 | 6.5 | 220.7 | 33.8× |
| wrapper_module_exec | fx_nodes | 1.09 | 18.1372 | 1607.3 | 61158.7 | 38.1× |
| sdsc_total | fx_nodes | 1.10 | 12.1886 | 1028.4 | 41099.9 | 40.0× |
| sdsc_bundle_gen_total | n_specs | 1.02 | 8.7050 | 877.9 | 35664.3 | 40.6× |
| kernel_provenance_total | n_specs | 1.01 | 1.2996 | 140.8 | 5324.3 | 37.8× |
| scratchpad_plan_allocation | planner_buffers | 1.84 | 52.4175 | 389.6 | 215121.3 | 552.2× |
| scratchpad_solve | planner_buffers | 2.11 | 49.3364 | 178.8 | 202476.5 | 1132.5× |
| scratchpad_prepare_buffers | planner_buffers | 1.14 | 3.0587 | 210.2 | 12552.9 | 59.7× |
| scratchpad_build_solver | planner_buffers | 0.54 | 0.0000 | 0.0 | 0.2 | 7.0× |

## mlp (n=6 shapes)

| bucket | unit | slope | ms/unit at max | ms at min | ms at max | ratio |
|---|---|---|---|---|---|---|
| pre_dxp_total | fx_nodes | 0.23 | 26.3419 | 3754.1 | 8482.1 | 2.3× |
| pre_compile_fx | fx_nodes | 0.03 | 2.2448 | 636.7 | 722.8 | 1.1× |
| compile_fx_wrapper | fx_nodes | 0.26 | 24.1053 | 3119.4 | 7761.9 | 2.5× |
| compile_fx_outer_other | fx_nodes | -0.01 | 8.4637 | 2802.3 | 2725.3 | 1.0× |
| spyre_inner_compile | fx_nodes | 0.84 | 15.5215 | 317.0 | 4997.9 | 15.8× |
| inner_compile_other | fx_nodes | 0.34 | 0.4334 | 44.8 | 139.6 | 3.1× |
| graphlowering_run | fx_nodes | 0.50 | 0.8128 | 48.0 | 261.7 | 5.4× |
| graphlowering_compile_to_module | fx_nodes | 0.91 | 14.2822 | 227.0 | 4598.9 | 20.3× |
| custompresched_total | presched_ops | 0.91 | 9.5460 | 78.3 | 1832.8 | 23.4× |
| presched_pass_loop | presched_ops | 0.91 | 9.5158 | 77.9 | 1827.0 | 23.5× |
| presched_cost_model | fx_nodes | 0.09 | 0.0000 | 0.0 | 0.0 | 1.5× |
| presched_finalize_work_division | fx_nodes | 0.80 | 0.0178 | 0.4 | 5.7 | 14.1× |
| upstream_update_scheduler | fx_nodes | 0.87 | 1.2935 | 24.1 | 416.5 | 17.3× |
| scheduler_init | sched_nodes | 0.82 | 2.1688 | 24.0 | 416.4 | 17.3× |
| scheduler_codegen | sched_nodes | 0.82 | 3.4464 | 36.3 | 661.7 | 18.2× |
| spyre_kernel_codegen_total | fx_nodes | 0.85 | 1.1370 | 19.0 | 366.1 | 19.3× |
| wrapper_codegen | fx_nodes | 0.86 | 0.0348 | 0.7 | 11.2 | 16.4× |
| wrapper_module_exec | fx_nodes | 0.93 | 5.1595 | 78.0 | 1661.4 | 21.3× |
| sdsc_total | fx_nodes | 1.00 | 3.2790 | 39.6 | 1055.8 | 26.7× |
| sdsc_bundle_gen_total | n_specs | 0.96 | 4.6919 | 32.9 | 900.9 | 27.4× |
| kernel_provenance_total | n_specs | 1.01 | 0.7487 | 4.4 | 143.8 | 32.9× |
| scratchpad_plan_allocation | planner_buffers | 0.84 | 0.9923 | 19.1 | 318.5 | 16.7× |
| scratchpad_solve | planner_buffers | 0.64 | 0.3364 | 12.3 | 108.0 | 8.8× |
| scratchpad_prepare_buffers | planner_buffers | 1.03 | 0.6449 | 6.4 | 207.0 | 32.4× |
| scratchpad_build_solver | planner_buffers | 0.24 | 0.0001 | 0.0 | 0.0 | 2.4× |

