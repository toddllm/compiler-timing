# Per-run reconciliation

One row per sample. `residual_pct` is the share of `pre_dxp_total` that the top-level partition (pre_compile_fx + compile_fx_wrapper_pre_dxp) does not account for. Target: <1%. `sdsc_parent` shows the event that timestamp-contains `sdsc_total` on this run — a topology discovery, not a hard-coded assumption. `invalid` runs are excluded from the aggregate tables.

| shape | run | valid | pre_dxp_ms | residual_ms | residual_pct | sdsc_parent | reason |
|---|---|---|---|---|---|---|---|
| flash-1024x8192 | flash-1024x8192-run1 | yes | 516824.8 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x1024 | flash-512x1024-run1 | yes | 27704.5 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x8192 | flash-512x8192-run1 | yes | 193574.9 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L2-w2048 | mlp-L2-w2048-run1 | yes | 10574.7 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L32-w2048 | mlp-L32-w2048-run1 | yes | 6981.7 | 0.00 | 0.00% | wrapper_module_exec | - |
