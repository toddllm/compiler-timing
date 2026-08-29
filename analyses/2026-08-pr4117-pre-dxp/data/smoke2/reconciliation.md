# Per-run reconciliation

One row per sample. `residual_pct` is the share of `pre_dxp_total` that the top-level partition (pre_compile_fx + compile_fx_wrapper_pre_dxp) does not account for. Target: <1%. `sdsc_parent` shows the event that timestamp-contains `sdsc_total` on this run — a topology discovery, not a hard-coded assumption. `invalid` runs are excluded from the aggregate tables.

| shape | run | valid | pre_dxp_ms | residual_ms | residual_pct | sdsc_parent | reason |
|---|---|---|---|---|---|---|---|
| flash-512x1024 | flash-512x1024-run1 | yes | 22085.4 | 0.00 | 0.00% | wrapper_module_exec | - |
