# Bucket scaling

For each bucket, we fit a log-log slope against the natural per-bucket independent variable when available, else against `fx_nodes_at_entry`. Slope > 1 is a super-linear warning, not a gate. Per-unit drift (ms per natural unit) is reported alongside so linear buckets that dominate absolutely are still visible.

## flash (n=3 shapes)

| bucket | unit | slope | ms/unit at max | ms at min | ms at max | ratio |
|---|---|---|---|---|---|---|
| pre_dxp_total | fx_nodes | 1.09 | 79.9659 | 15532.0 | 135302.3 | 8.7× |
| pre_compile_fx | fx_nodes | 0.69 | 1.9041 | 776.6 | 3221.8 | 4.1× |
| compile_fx_wrapper | fx_nodes | 1.10 | 77.8724 | 14760.0 | 131760.0 | 8.9× |
| compile_fx_outer_other | fx_nodes | 0.56 | 6.8505 | 3607.0 | 11591.0 | 3.2× |
| spyre_inner_compile | fx_nodes | 1.20 | 71.0219 | 11153.0 | 120169.0 | 10.8× |
| inner_compile_other | fx_nodes | 1.01 | 1.7407 | 399.3 | 2945.3 | 7.4× |
| graphlowering_run | fx_nodes | 1.04 | 1.8045 | 398.7 | 3053.2 | 7.7× |
| graphlowering_compile_to_module | fx_nodes | 1.21 | 67.4426 | 10364.7 | 114112.9 | 11.0× |
| custompresched_total | presched_ops | 1.28 | 32.2066 | 4568.1 | 66088.0 | 14.5× |
| presched_pass_loop | presched_ops | 1.29 | 31.9070 | 4489.4 | 65473.2 | 14.6× |
| presched_cost_model | fx_nodes | -0.19 | 0.0000 | 0.0 | 0.0 | 0.6× |
| presched_finalize_work_division | fx_nodes | 1.04 | 0.3616 | 78.6 | 611.8 | 7.8× |
| upstream_update_scheduler | fx_nodes | 1.22 | 4.5265 | 697.5 | 7658.9 | 11.0× |
| scheduler_init | sched_nodes | 1.16 | 3.5132 | 697.4 | 7658.8 | 11.0× |
| scheduler_codegen | sched_nodes | 0.91 | 3.3745 | 1105.5 | 7356.3 | 6.7× |
| spyre_kernel_codegen_total | fx_nodes | 1.01 | 1.3441 | 313.5 | 2274.3 | 7.3× |
| wrapper_codegen | fx_nodes | 1.05 | 0.0692 | 14.8 | 117.0 | 7.9× |
| wrapper_module_exec | fx_nodes | 1.08 | 19.3442 | 3954.8 | 32730.4 | 8.3× |
| sdsc_total | fx_nodes | 1.08 | 12.9310 | 2644.4 | 21879.3 | 8.3× |
| sdsc_bundle_gen_total | n_specs | 1.02 | 8.7772 | 2293.1 | 19108.0 | 8.3× |
| kernel_provenance_total | n_specs | 1.00 | 1.2323 | 335.2 | 2682.7 | 8.0× |
| scratchpad_plan_allocation | planner_buffers | 1.13 | 3.7490 | 788.1 | 8187.9 | 10.4× |
| scratchpad_solve | planner_buffers | 1.98 | 0.2294 | 8.5 | 501.0 | 59.0× |
| scratchpad_prepare_buffers | planner_buffers | 1.10 | 3.4129 | 765.3 | 7453.7 | 9.7× |
| scratchpad_build_solver | planner_buffers | 0.18 | 0.0000 | 0.0 | 0.0 | 1.3× |

