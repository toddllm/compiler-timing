# Structural predictor study (#4139)

Same planner-buffer universe both arms (`SPYRE_LX_PLANNER_RELAYOUT=0`). Structural metrics are pure functions of that shared buffer set; greedy work counters and CP-SAT model geometry are recorded per-solver.

## Solve time — which solver wins

| shape | family | cpsat_solve_ms | greedy_solve_ms | winner | ratio (greedy/cpsat) |
|---|---|---:|---:|:---:|---:|
| sdpa-B1H8S1024D128 | other | 25.2 | 0.2 | greedy | 0.009 |
| sdpa-B1H8S2048D128 | other | 17.5 | 0.2 | greedy | 0.011 |
| sdpa-B1H8S512D128 | other | 24.2 | 0.2 | greedy | 0.009 |
| tblock-S1024E1024 | other | 0.0 | 0.0 | cpsat | inf |
| tblock-S512E1024 | other | 0.0 | 0.0 | cpsat | inf |
| tblock-S512E2048 | other | 0.0 | 0.0 | cpsat | inf |

## Structural metrics (from the shared buffer universe)

| shape | planner_buffers | placeable_buffers | barred_buffers_prep | n_transition_points | max_live_count | mean_live_count | live_set_area | max_live_bytes | mean_live_bytes | n_overlap_pairs | overlap_density | in_place_edges | size_median | size_p90 | size_max | transition_x_placeable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sdpa-B1H8S1024D128 | 34 | 17 | 17 | 32 | 7 | 4.938 | 158 | 1245184 | 484352.0 | 176 | 0.314 | 9 | 32768 | 65536 | 524288 | 544 |
| sdpa-B1H8S2048D128 | 34 | 17 | 17 | 32 | 7 | 4.938 | 158 | 4587520 | 1665024.0 | 176 | 0.314 | 9 | 65536 | 131072 | 2097152 | 544 |
| sdpa-B1H8S512D128 | 34 | 17 | 17 | 32 | 7 | 4.938 | 158 | 360448 | 156160.0 | 176 | 0.314 | 9 | 16384 | 32768 | 131072 | 544 |
| tblock-S1024E1024 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| tblock-S512E1024 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| tblock-S512E2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |

## Greedy internal work counters

| shape | n_find_free_block_calls | sum_live_set_size_entering_find | max_live_set_size_entering_find | n_try_allocate_one_calls | n_in_place_parent_probes | n_in_place_reuses | n_try_deallocate_calls | n_occupied_spans_calls | sum_usage_entering_occupied_spans | n_transition_times | n_alloc_transition_iterations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sdpa-B1H8S1024D128 | 10 | 13 | 3 | 17 | 9 | 7 | 17 | 0 | 0 | 21 | 357 |
| sdpa-B1H8S2048D128 | 9 | 7 | 2 | 14 | 7 | 5 | 14 | 0 | 0 | 21 | 357 |
| sdpa-B1H8S512D128 | 10 | 13 | 3 | 17 | 9 | 7 | 17 | 0 | 0 | 21 | 357 |
| tblock-S1024E1024 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| tblock-S512E1024 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| tblock-S512E2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |

## CP-SAT model geometry

| shape | num_variables | num_constraints | num_no_overlap_2d | num_no_overlap | num_interval | proto_bytes | num_tensors | num_forced_reasons | walltime_s | num_branches | num_conflicts | num_booleans |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sdpa-B1H8S1024D128 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| sdpa-B1H8S2048D128 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| sdpa-B1H8S512D128 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| tblock-S1024E1024 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| tblock-S512E1024 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| tblock-S512E2048 | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |

## Simple predictor candidates

Predictors evaluated: pick a structural quantity that separates flash-wins-greedy from mlp-wins-cpsat. For each shape, compute the predictor and its sign relative to the actual solver-cost sign (`greedy_solve < cpsat_solve`).

For each candidate: show shape values and check whether **a single threshold** on that candidate correctly labels flash-wins-greedy vs mlp-wins-cpsat on this measured set.

| candidate | sdpa-B1H8S1024D128 | sdpa-B1H8S2048D128 | sdpa-B1H8S512D128 | tblock-S1024E1024 | tblock-S512E1024 | tblock-S512E2048 | threshold splits? |
|---|---:|---:|---:|---:|---:|---:|:---:|
| planner_buffers | 34 | 34 | 34 | 0 | 0 | 0 | YES |
| placeable_buffers | 17 | 17 | 17 | 0 | 0 | 0 | YES |
| live_set_area | 158 | 158 | 158 | 0 | 0 | 0 | YES |
| overlap_density | 0.314 | 0.314 | 0.314 | 0 | 0 | 0 | YES |
| n_overlap_pairs | 176 | 176 | 176 | 0 | 0 | 0 | YES |
| max_live_count | 7 | 7 | 7 | 0 | 0 | 0 | YES |
| mean_live_count | 4.94 | 4.94 | 4.94 | 0 | 0 | 0 | YES |
| in_place_edges | 9 | 9 | 9 | 0 | 0 | 0 | YES |
| transition_x_placeable | 544 | 544 | 544 | 0 | 0 | 0 | YES |
| greedy_find_free_calls | 10 | 9 | 10 | 0 | 0 | 0 | YES |
| greedy_alloc_iterations | 357 | 357 | 357 | 0 | 0 | 0 | YES |
| greedy_occupied_span_calls | 0 | 0 | 0 | 0 | 0 | 0 | YES |
| cpsat_num_variables | 0 | 0 | 0 | 0 | 0 | 0 | YES |
| greedy_alloc_iter / cpsat_vars^2 | 357 | 357 | 357 | 0 | 0 | 0 | YES |
| overlap_density x placeable_buffers | 5.33 | 5.33 | 5.33 | 0 | 0 | 0 | YES |
| live_set_area / planner_buffers | 4.65 | 4.65 | 4.65 | 0 | 0 | 0 | YES |
| n_overlap_pairs / n_transition_points | 5.5 | 5.5 | 5.5 | 0 | 0 | 0 | YES |

