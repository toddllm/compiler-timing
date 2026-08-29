# Per-run reconciliation

One row per sample. `residual_pct` is the share of `pre_dxp_total` that the top-level partition (pre_compile_fx + compile_fx_wrapper_pre_dxp) does not account for. Target: <1%. `sdsc_parent` shows the event that timestamp-contains `sdsc_total` on this run — a topology discovery, not a hard-coded assumption. `invalid` runs are excluded from the aggregate tables.

| shape | run | valid | pre_dxp_ms | residual_ms | residual_pct | sdsc_parent | reason |
|---|---|---|---|---|---|---|---|
| flash-1024x1024 | flash-1024x1024-run1 | yes | 30147.5 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-1024x1024 | flash-1024x1024-run2 | yes | 31544.2 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-1024x1024 | flash-1024x1024-run3 | yes | 32987.9 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-1024x8192 | flash-1024x8192-run1 | yes | 515021.3 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-1024x8192 | flash-1024x8192-run2 | yes | 512883.4 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-1024x8192 | flash-1024x8192-run3 | yes | 520322.0 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-2048x1024 | flash-2048x1024-run1 | yes | 71126.9 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-2048x1024 | flash-2048x1024-run2 | yes | 70275.6 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-2048x1024 | flash-2048x1024-run3 | yes | 71107.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-256x1024 | flash-256x1024-run1 | yes | 15922.7 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-256x1024 | flash-256x1024-run2 | yes | 10413.5 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-256x1024 | flash-256x1024-run3 | yes | 11176.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x1024 | flash-512x1024-run1 | yes | 17130.6 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x1024 | flash-512x1024-run2 | yes | 17806.8 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x1024 | flash-512x1024-run3 | yes | 20184.2 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x2048 | flash-512x2048-run1 | yes | 30575.6 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x2048 | flash-512x2048-run2 | yes | 33622.8 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x2048 | flash-512x2048-run3 | yes | 31189.5 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x4096 | flash-512x4096-run1 | yes | 64874.4 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x4096 | flash-512x4096-run2 | yes | 65580.9 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x4096 | flash-512x4096-run3 | yes | 70474.4 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x512 | flash-512x512-run1 | yes | 11552.5 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x512 | flash-512x512-run2 | yes | 11317.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x512 | flash-512x512-run3 | yes | 9735.2 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x8192 | flash-512x8192-run1 | yes | 200334.8 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x8192 | flash-512x8192-run2 | yes | 181358.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| flash-512x8192 | flash-512x8192-run3 | yes | 201348.2 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L16-w2048 | mlp-L16-w2048-run1 | yes | 5392.0 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L16-w2048 | mlp-L16-w2048-run2 | yes | 4978.8 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L16-w2048 | mlp-L16-w2048-run3 | yes | 4507.3 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L2-w2048 | mlp-L2-w2048-run1 | yes | 10483.7 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L2-w2048 | mlp-L2-w2048-run2 | yes | 3754.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L2-w2048 | mlp-L2-w2048-run3 | yes | 3123.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L32-w2048 | mlp-L32-w2048-run1 | yes | 5954.9 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L32-w2048 | mlp-L32-w2048-run2 | yes | 6570.0 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L32-w2048 | mlp-L32-w2048-run3 | yes | 6039.6 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L4-w2048 | mlp-L4-w2048-run1 | yes | 4817.5 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L4-w2048 | mlp-L4-w2048-run2 | yes | 4068.9 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L4-w2048 | mlp-L4-w2048-run3 | yes | 3834.9 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L64-w2048 | mlp-L64-w2048-run1 | yes | 8482.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L64-w2048 | mlp-L64-w2048-run2 | yes | 8634.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L64-w2048 | mlp-L64-w2048-run3 | yes | 8103.6 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L8-w2048 | mlp-L8-w2048-run1 | yes | 4210.1 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L8-w2048 | mlp-L8-w2048-run2 | yes | 4728.4 | 0.00 | 0.00% | wrapper_module_exec | - |
| mlp-L8-w2048 | mlp-L8-w2048-run3 | yes | 4721.1 | 0.00 | 0.00% | wrapper_module_exec | - |
