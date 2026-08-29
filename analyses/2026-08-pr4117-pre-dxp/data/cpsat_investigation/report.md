# CP-SAT investigation report

Frozen torch-spyre `3358f39` with **SPYRE_LX_PLANNER_RELAYOUT=0**. Under this config both cpsat and greedy call the same `_generate_buffers(graph)` path in `_prepare_buffers`, so the planner-buffer universe is identical between arms.

## Canonical planner-buffer signature (RELAYOUT=0)

| shape | cpsat_sig_hash | greedy_sig_hash | match? | diff details |
|---|---|---|---|---|
| flash-512x1024 | 3c25d56686e666a9 | 3c25d56686e666a9 | YES | — |
| flash-512x2048 | df5997edb35c4774 | df5997edb35c4774 | YES | — |
| flash-512x4096 | 4a6c8184f7a25459 | 4a6c8184f7a25459 | YES | — |
| flash-512x8192 | 3c45992b2a4e8d8a | 3c45992b2a4e8d8a | YES | — |

**Invariant confirmed**: cpsat and greedy see the same planner-buffer input universe under RELAYOUT=0.

## Placement outcome comparison

| shape | solver | planner_buffers | eligible | placed | spilled | bytes_placed | bytes_spilled | scratchpad_pass_ms | solve_ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| flash-512x1024 | cpsat | 264 | 113 | 113 | 151 | 1044480 | 991232 | 803.2 | 344.0 |
| flash-512x1024 | greedy | 264 | 113 | 113 | 151 | 1044480 | 991232 | 463.8 | 4.2 |
| flash-512x2048 | cpsat | 520 | 225 | 225 | 295 | 2060288 | 1875968 | 2692.9 | 1566.2 |
| flash-512x2048 | greedy | 520 | 225 | 225 | 295 | 2060288 | 1875968 | 1137.9 | 16.7 |
| flash-512x4096 | cpsat | 1032 | 449 | 449 | 583 | 4091904 | 3645440 | 10988.2 | 8902.5 |
| flash-512x4096 | greedy | 1032 | 449 | 449 | 583 | 4091904 | 3645440 | 2181.2 | 64.6 |
| flash-512x8192 | cpsat | 2056 | 897 | 897 | 1159 | 8155136 | 7184384 | 55250.1 | 50270.1 |
| flash-512x8192 | greedy | 2056 | 897 | 897 | 1159 | 8155136 | 7184384 | 5444.2 | 255.9 |

## Placed-set symmetric difference (cpsat vs greedy)

| shape | in cpsat only | in greedy only | agreed |
|---|---:|---:|---:|
| flash-512x1024 | 0 | 0 | 113 |
| flash-512x2048 | 0 | 0 | 225 |
| flash-512x4096 | 0 | 0 | 449 |
| flash-512x8192 | 0 | 0 | 897 |

## CP-SAT phase decomposition (ms)

Per phase inside `CpSatLayoutSolver._plan_layout_generic → _run`. One sample per shape.

| shape | plan_layout_generic | add_inplace | add_core_div | add_no_overlap_2d | solve[1] | solve[2] | solve[3] | extract |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| flash-512x1024 | 343.9 | 3.0 | 0.3 | 1.8 | 334.6 | 0.0 | 0.0 | 1.2 |
| flash-512x2048 | 1566.1 | 5.6 | 0.5 | 3.3 | 1548.0 | 0.0 | 0.0 | 3.5 |
| flash-512x4096 | 8902.3 | 11.2 | 1.1 | 6.7 | 8866.6 | 0.0 | 0.0 | 6.7 |
| flash-512x8192 | 50269.6 | 24.7 | 2.3 | 15.0 | 49952.0 | 0.0 | 0.0 | 20.3 |

## CP-SAT per-Solve() OR-Tools stats

| shape | solve# | status | wall_s | branches | conflicts | booleans | bin_prop | int_prop | restarts |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| flash-512x1024 | 1 | OPTIMAL | 0.33 | 134 | 0 | 303 | 0 | 0 | 0 |
| flash-512x2048 | 1 | OPTIMAL | 1.55 | 24 | 0 | 607 | 0 | 0 | 0 |
| flash-512x4096 | 1 | OPTIMAL | 8.86 | 30 | 0 | 1215 | 0 | 0 | 0 |
| flash-512x8192 | 1 | OPTIMAL | 49.95 | 6 | 0 | 2431 | 0 | 0 | 0 |

## CP-SAT model size (post-build, single model for all Solve() calls)

| shape | planner_buffers | num_variables | num_constraints | num_no_overlap_2d | num_no_overlap | num_interval | proto_bytes | num_tensors | num_forced_reasons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| flash-512x1024 | 264 | 926 | 1229 | None | None | None | None | None | None |
| flash-512x2048 | 520 | 1830 | 2429 | None | None | None | None | None | None |
| flash-512x4096 | 1032 | 3638 | 4829 | None | None | None | None | None | None |
| flash-512x8192 | 2056 | 7254 | 9629 | None | None | None | None | None | None |

## Empirical scaling exponents across the 4 measured shapes

Log-log fit against planner_buffers. Only the shapes measured here; not extrapolatable.

| CP-SAT phase | slope (log-log vs planner_buffers) |
|---|---:|
| cpsat_plan_layout_generic_ms | 2.44 |
| cpsat_add_inplace_relaxation_ms | 1.02 |
| cpsat_add_core_division_ms | 1.03 |
| cpsat_add_no_overlap_2d_ms | 1.03 |
| cpsat_solve_1_ms | 2.45 |
| cpsat_solve_2_ms | nan |
| cpsat_solve_3_ms | nan |
| cpsat_extract_ms | 1.33 |

