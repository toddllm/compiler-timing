# Structural predictor study (#4139)

Same planner-buffer universe both arms (`SPYRE_LX_PLANNER_RELAYOUT=0`). Structural metrics are pure functions of that shared buffer set; greedy work counters and CP-SAT model geometry are recorded per-solver.

## Solve time — which solver wins

| shape | family | cpsat_solve_ms | greedy_solve_ms | winner | ratio (greedy/cpsat) |
|---|---|---:|---:|:---:|---:|
| flash-512x1024 | flash | 383.1 | 4.4 | greedy | 0.012 |
| flash-512x2048 | flash | 1624.2 | 17.0 | greedy | 0.010 |
| flash-512x4096 | flash | 6996.5 | 65.6 | greedy | 0.009 |
| flash-512x8192 | flash | 62745.0 | 258.0 | greedy | 0.004 |
| mlp-L128-w2048 | mlp | 253.1 | 19.0 | greedy | 0.075 |
| mlp-L192-w2048 | mlp | 408.3 | 42.4 | greedy | 0.104 |
| mlp-L384-w2048 | mlp | 1060.8 | 169.1 | greedy | 0.159 |
| mlp-L96-w2048 | mlp | 176.4 | 10.8 | greedy | 0.061 |

## Structural metrics (from the shared buffer universe)

| shape | planner_buffers | placeable_buffers | barred_buffers_prep | n_transition_points | max_live_count | mean_live_count | live_set_area | max_live_bytes | mean_live_bytes | n_overlap_pairs | overlap_density | in_place_edges | size_median | size_p90 | size_max | transition_x_placeable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| flash-512x1024 | 264 | 113 | 151 | 261 | 26 | 16.088 | 4199 | 286720 | 169678.0 | 4232 | 0.122 | 71 | 4096 | 32768 | 65536 | 29493 |
| flash-512x2048 | 520 | 225 | 295 | 517 | 42 | 24.416 | 12623 | 417792 | 262365.8 | 12656 | 0.094 | 143 | 4096 | 32768 | 131072 | 116325 |
| flash-512x4096 | 1032 | 449 | 583 | 1029 | 74 | 40.582 | 41759 | 679936 | 443896.5 | 41792 | 0.079 | 287 | 4096 | 16384 | 262144 | 462021 |
| flash-512x8192 | 2056 | 897 | 1159 | 2053 | 138 | 72.666 | 149183 | 1204224 | 805002.7 | 149216 | 0.071 | 575 | 4096 | 16384 | 524288 | 1841541 |
| mlp-L128-w2048 | 641 | 255 | 386 | 385 | 3 | 2.660 | 1024 | 262272 | 86686.1 | 1918 | 0.009 | 127 | 128 | 262144 | 262144 | 98175 |
| mlp-L192-w2048 | 961 | 383 | 578 | 577 | 3 | 2.662 | 1536 | 262272 | 86988.4 | 2878 | 0.006 | 191 | 128 | 262144 | 262144 | 220991 |
| mlp-L384-w2048 | 1921 | 767 | 1154 | 1153 | 3 | 2.664 | 3072 | 262272 | 87291.3 | 5758 | 0.003 | 383 | 128 | 262144 | 262144 | 884351 |
| mlp-L96-w2048 | 481 | 191 | 290 | 289 | 3 | 2.657 | 768 | 262272 | 86384.3 | 1438 | 0.012 | 95 | 128 | 262144 | 262144 | 55199 |

## Greedy internal work counters

| shape | n_find_free_block_calls | sum_live_set_size_entering_find | max_live_set_size_entering_find | n_try_allocate_one_calls | n_in_place_parent_probes | n_in_place_reuses | n_try_deallocate_calls | n_occupied_spans_calls | sum_usage_entering_occupied_spans | n_transition_times | n_alloc_transition_iterations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| flash-512x1024 | 50 | 255 | 10 | 113 | 71 | 63 | 113 | 0 | 0 | 176 | 19888 |
| flash-512x2048 | 98 | 895 | 18 | 225 | 143 | 127 | 225 | 0 | 0 | 352 | 79200 |
| flash-512x4096 | 194 | 3327 | 34 | 449 | 287 | 255 | 449 | 0 | 0 | 704 | 316096 |
| flash-512x8192 | 386 | 12799 | 66 | 897 | 575 | 511 | 897 | 0 | 0 | 1408 | 1262976 |
| mlp-L128-w2048 | 128 | 0 | 0 | 255 | 127 | 127 | 255 | 0 | 0 | 384 | 97920 |
| mlp-L192-w2048 | 192 | 0 | 0 | 383 | 191 | 191 | 383 | 0 | 0 | 576 | 220608 |
| mlp-L384-w2048 | 384 | 0 | 0 | 767 | 383 | 383 | 767 | 0 | 0 | 1152 | 883584 |
| mlp-L96-w2048 | 96 | 0 | 0 | 191 | 95 | 95 | 191 | 0 | 0 | 288 | 55008 |

## CP-SAT model geometry

| shape | num_variables | num_constraints | num_no_overlap_2d | num_no_overlap | num_interval | proto_bytes | num_tensors | num_forced_reasons | walltime_s | num_branches | num_conflicts | num_booleans |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| flash-512x1024 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| flash-512x2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| flash-512x4096 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| flash-512x8192 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| mlp-L128-w2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| mlp-L192-w2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| mlp-L384-w2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| mlp-L96-w2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |

## Simple predictor candidates

Predictors evaluated: pick a structural quantity that separates flash-wins-greedy from mlp-wins-cpsat. For each shape, compute the predictor and its sign relative to the actual solver-cost sign (`greedy_solve < cpsat_solve`).

For each candidate: show shape values and check whether **a single threshold** on that candidate correctly labels flash-wins-greedy vs mlp-wins-cpsat on this measured set.

| candidate | flash-512x1024 | flash-512x2048 | flash-512x4096 | flash-512x8192 | mlp-L128-w2048 | mlp-L192-w2048 | mlp-L384-w2048 | mlp-L96-w2048 | threshold splits? |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| planner_buffers | 264 | 520 | 1032 | 2056 | 641 | 961 | 1921 | 481 | NO |
| placeable_buffers | 113 | 225 | 449 | 897 | 255 | 383 | 767 | 191 | NO |
| live_set_area | 4199 | 12623 | 41759 | 149183 | 1024 | 1536 | 3072 | 768 | NO |
| overlap_density | 0.122 | 0.0938 | 0.0786 | 0.0706 | 0.00935 | 0.00624 | 0.00312 | 0.0125 | NO |
| n_overlap_pairs | 4232 | 12656 | 41792 | 149216 | 1918 | 2878 | 5758 | 1438 | NO |
| max_live_count | 26 | 42 | 74 | 138 | 3 | 3 | 3 | 3 | NO |
| mean_live_count | 16.1 | 24.4 | 40.6 | 72.7 | 2.66 | 2.66 | 2.66 | 2.66 | NO |
| in_place_edges | 71 | 143 | 287 | 575 | 127 | 191 | 383 | 95 | NO |
| transition_x_placeable | 29493 | 116325 | 462021 | 1841541 | 98175 | 220991 | 884351 | 55199 | NO |
| greedy_find_free_calls | 50 | 98 | 194 | 386 | 128 | 192 | 384 | 96 | NO |
| greedy_alloc_iterations | 19888 | 79200 | 316096 | 1262976 | 97920 | 220608 | 883584 | 55008 | NO |
| greedy_occupied_span_calls | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NO |
| cpsat_num_variables | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NO |
| greedy_alloc_iter / cpsat_vars^2 | 1.99e+04 | 7.92e+04 | 3.16e+05 | 1.26e+06 | 9.79e+04 | 2.21e+05 | 8.84e+05 | 5.5e+04 | NO |
| overlap_density x placeable_buffers | 13.8 | 21.1 | 35.3 | 63.4 | 2.38 | 2.39 | 2.39 | 2.38 | NO |
| live_set_area / planner_buffers | 15.9 | 24.3 | 40.5 | 72.6 | 1.6 | 1.6 | 1.6 | 1.6 | NO |
| n_overlap_pairs / n_transition_points | 16.2 | 24.5 | 40.6 | 72.7 | 4.98 | 4.99 | 4.99 | 4.98 | NO |

