# CP-SAT vs greedy — same-tree same-config comparison

Frozen torch-spyre `3358f39` with `USE_SPYRE_CCL=0` and all other config identical between arms. Cost model OFF for these primary runs (`SPYRE_DUMP_COST` unset; `config.cost_model` unset).

See `data/solver_ab_v2/report.md` for the earlier diagnostic A/B where the cost model was enabled and predicted ~16% lower runtime for greedy plans. Those A/B numbers are NOT combined with the timing baseline below.

## Shared flash shapes

| shape | solver | fx_nodes | presched_ops | planner_buffers | n_specs | pre_dxp_ms | scratchpad_pass_ms | scratchpad_solve_ms | solver_status | ortools_walltime_s | ortools_workers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| flash-512x1024 | cpsat | 236 | 260 | 264 | 257 | 17806.8 | 798.5 | 330.4 | OPTIMAL | 0.32 | 192 |
| flash-512x1024 | greedy | 236 | 260 | 280 | 273 | 15532.0 | 788.2 | 8.5 | — | — | — |
| flash-512x4096 | cpsat | 860 | 1028 | 1032 | 1025 | 65580.9 | 11187.5 | 9090.0 | OPTIMAL | 9.05 | 192 |
| flash-512x4096 | greedy | 860 | 1028 | 1096 | 1089 | 57661.0 | 3456.8 | 126.8 | — | — | — |
| flash-512x8192 | cpsat | 1692 | 2052 | 2056 | 2049 | 200334.8 | 75696.2 | 70589.5 | OPTIMAL | 70.51 | 192 |
| flash-512x8192 | greedy | 1692 | 2052 | 2184 | 2177 | 135302.3 | 8188.0 | 501.0 | — | — | — |

## Notes

- Cost model is OFF for these primary runs, so `pre_dxp_ms` here differs from A/B v2 timing (which had cost model ON).
- The historical greedy scratchpad path remains comparatively inexpensive. Current-main changed the default to CP-SAT, making solver time a major frontend compile-time component at scale.
- Not a regression in the greedy implementation.
