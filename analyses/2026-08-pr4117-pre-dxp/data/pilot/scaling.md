# Bucket scaling

For each bucket, we fit a log-log slope against the natural per-bucket independent variable when available, else against `fx_nodes_at_entry`. Slope > 1 is a super-linear warning, not a gate. Per-unit drift (ms per natural unit) is reported alongside so linear buckets that dominate absolutely are still visible.

## flash (n=3 shapes)

| bucket | unit | slope | ms/unit at max | ms at min | ms at max | ratio |
|---|---|---|---|---|---|---|
| pre_dxp_total | fx_nodes | 1.08 | 153.2695 | 27704.5 | 516824.8 | 18.7× |
| pre_compile_fx | fx_nodes | 0.66 | 0.5690 | 334.5 | 1918.6 | 5.7× |
| compile_fx_wrapper | fx_nodes | 1.08 | 152.7016 | 27375.8 | 514909.8 | 18.8× |
| compile_fx_outer_other | fx_nodes | 0.08 | 3.8317 | 12191.4 | 12920.4 | 1.1× |
| spyre_inner_compile | fx_nodes | 1.30 | 148.8699 | 15184.4 | 501989.4 | 33.1× |
| inner_compile_other | fx_nodes | 0.86 | 1.5567 | 526.8 | 5249.2 | 10.0× |
| graphlowering_run | fx_nodes | 0.88 | 1.8382 | 591.9 | 6198.5 | 10.5× |
| graphlowering_compile_to_module | fx_nodes | 1.32 | 145.4750 | 14065.7 | 490541.7 | 34.9× |
| custompresched_total | presched_ops | 1.37 | 95.5596 | 8321.6 | 391794.2 | 47.1× |
| presched_pass_loop | presched_ops | 1.37 | 95.2775 | 8246.7 | 390637.8 | 47.4× |
| presched_cost_model | fx_nodes | 0.17 | 0.0000 | 0.0 | 0.0 | 1.8× |
| presched_finalize_work_division | fx_nodes | 1.03 | 0.3429 | 74.8 | 1156.3 | 15.5× |
| upstream_update_scheduler | fx_nodes | 1.16 | 5.5962 | 856.5 | 18870.5 | 22.0× |
| scheduler_init | sched_nodes | 1.11 | 4.6025 | 856.4 | 18870.2 | 22.0× |
| scheduler_codegen | sched_nodes | 1.03 | 3.8540 | 914.8 | 15801.5 | 17.3× |
| spyre_kernel_codegen_total | fx_nodes | 1.03 | 1.4024 | 310.1 | 4728.8 | 15.2× |
| wrapper_codegen | fx_nodes | 1.01 | 0.0659 | 15.2 | 222.3 | 14.6× |
| wrapper_module_exec | fx_nodes | 1.05 | 18.9267 | 3937.8 | 63820.8 | 16.2× |
| sdsc_total | fx_nodes | 1.06 | 12.1144 | 2460.9 | 40849.7 | 16.6× |
| sdsc_bundle_gen_total | n_specs | 1.02 | 8.6344 | 2108.7 | 35375.2 | 16.8× |
| kernel_provenance_total | n_specs | 1.00 | 1.3095 | 340.4 | 5364.9 | 15.8× |

## mlp (n=2 shapes)

| bucket | unit | slope | ms/unit at max | ms at min | ms at max | ratio |
|---|---|---|---|---|---|---|
| pre_dxp_total | fx_nodes | -0.16 | 43.0972 | 10574.7 | 6981.7 | 0.7× |
| pre_compile_fx | fx_nodes | -0.09 | 0.8890 | 182.3 | 144.0 | 0.8× |
| compile_fx_wrapper | fx_nodes | -0.16 | 42.2288 | 10394.8 | 6841.1 | 0.7× |
| compile_fx_outer_other | fx_nodes | -0.29 | 22.6327 | 7867.4 | 3666.5 | 0.5× |
| spyre_inner_compile | fx_nodes | 0.09 | 19.5961 | 2527.4 | 3174.6 | 1.3× |
| inner_compile_other | fx_nodes | 0.27 | 0.5184 | 41.8 | 84.0 | 2.0× |
| graphlowering_run | fx_nodes | 0.08 | 0.9121 | 118.6 | 147.8 | 1.2× |
| graphlowering_compile_to_module | fx_nodes | 0.08 | 18.1656 | 2367.0 | 2942.8 | 1.2× |
| custompresched_total | presched_ops | -0.11 | 16.9296 | 2197.8 | 1625.2 | 0.7× |
| presched_pass_loop | presched_ops | -0.11 | 16.9073 | 2197.4 | 1623.1 | 0.7× |
| presched_cost_model | fx_nodes | 0.01 | 0.0001 | 0.0 | 0.0 | 1.0× |
| presched_finalize_work_division | fx_nodes | 0.64 | 0.0130 | 0.4 | 2.1 | 5.3× |
| upstream_update_scheduler | fx_nodes | 0.79 | 1.2511 | 25.7 | 202.7 | 7.9× |
| scheduler_init | sched_nodes | 0.75 | 2.1105 | 25.6 | 202.6 | 7.9× |
| scheduler_codegen | sched_nodes | 0.66 | 2.8287 | 43.5 | 271.6 | 6.2× |
| spyre_kernel_codegen_total | fx_nodes | 0.64 | 0.6917 | 21.2 | 112.1 | 5.3× |
| wrapper_codegen | fx_nodes | 0.79 | 0.0339 | 0.7 | 5.5 | 7.9× |
| wrapper_module_exec | fx_nodes | 0.88 | 5.0968 | 83.6 | 825.7 | 9.9× |
| sdsc_total | fx_nodes | 0.98 | 3.3239 | 42.5 | 538.5 | 12.7× |
| sdsc_bundle_gen_total | n_specs | 0.96 | 4.7936 | 32.4 | 460.2 | 14.2× |
| kernel_provenance_total | n_specs | 1.01 | 0.7457 | 4.3 | 71.6 | 16.6× |

