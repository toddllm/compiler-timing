# Pre-DXP frontend investigation — summary (final)

**Epic:** torch-spyre #4117 — investigate remaining pre-DXP compile
time outside `CustomPreSchedulingPasses`.

**Frozen torch-spyre baseline:**
`3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f`
(upstream/main at study start; PR #4113 merge
`c073d69cceaac91d34b01dea6545048d0d645c2c` verified as ancestor).

**Scope:** cold `torch.compile()` path through generation of backend
input, stopping immediately before `subprocess.run(["dxp_standalone",
...])` in `torch_spyre/execution/async_compile.py:155`. DXP itself is
out of scope.

## Question

> Once known pass-level costs are accounted for, where does the rest
> of pre-DXP compile time go, how does each bucket scale with graph
> size, and which remaining bucket is the next material optimization
> target?

## Answer

Under the current-main defaults (`LAYOUT_SOLVER=cpsat`) on flash
workloads, the pre-DXP frontend at scale is dominated by
`CustomPreSchedulingPasses`, which in turn is dominated by two
passes with roughly comparable absolute cost:

* `_maybe_scratchpad_planning` (CP-SAT solver-bound) — largest at
  `flash-1024x8192` (**215 121 ms = 41.8% of pre_dxp_total**),
  empirical scaling exponent ~2.11 on `scratchpad_solve` over the
  measured range.
* `optimize_restickify_locations` (Will's track) — second largest
  (138 354 ms = 26.9%).

The **largest remaining non-restickify bucket at every measured
flash shape is `_maybe_scratchpad_planning`**, and its cost is
solver-specific: greedy at the same source SHA takes ~8 s where
CP-SAT takes ~76 s at `flash-512x8192` (see
`notes/tables/solver_comparison.md`). The historical greedy path is
comparatively inexpensive and its costs remain near-linear.

## Baseline configuration

Same in every primary run; recorded from
`torch_spyre._inductor.config` per run:

| key | value |
|---|---|
| `layout_solver` | `cpsat` (frozen-main default) |
| `co_optimizing_lx_planning` | `False` |
| `lx_planning` | `True` |
| `lx_planner_relayout` | `True` |
| `sencores` | `32` |
| `dxp_lx_frac_avail` | `0.2` |
| `hbm_pool_planning` | `True` |
| `native_layout_packer` | `True` |
| `cost_model` | OFF (`SPYRE_DUMP_COST` unset) |
| `USE_SPYRE_CCL` | `0` |

CP-SAT reproducibility: OR-Tools 9.11+ (installed by `uv sync`;
version recorded in each run's meta), `num_search_workers = 192` on
this pod, `max_time_in_seconds = 600` s. On the largest flash shape
CP-SAT terminated `OPTIMAL` well inside that budget (~202 s wall in
`scratchpad_solve`).

## Deliverables in this commit

* `notes/pre-dxp-attribution.md` — bucket-by-bucket median-of-3 ms
  and % of pre_dxp_total for all 15 primary shapes.
* `notes/tables/scaling.md` — empirical scaling slope + per-unit
  drift for every bucket, per workload family, on the primary arm.
  Historical greedy arm reported separately in
  `notes/tables/greedy_compat/`.
* `notes/tables/pass-detail.md` — top passes inside
  `CustomPreSchedulingPasses` at every primary shape.
* `notes/tables/solver_comparison.md` — CP-SAT vs greedy on the
  three shared flash shapes (512×1024, 512×4096, 512×8192).
* `notes/tables/reconciliation.md` — 0.00% residual on every primary
  and every greedy compat run (54/54 valid).
* `notes/next-opportunities.md` — ranked follow-up work.

## Solver comparison — historical PR #3806 / Will / current-main

PR #3806 study and Will's scratchpad measurements ran under
`LAYOUT_SOLVER=greedy` (the `faff191`-era default). Current
frozen-main (`3358f39`) changed the default to `cpsat` (see
`torch_spyre/_inductor/config.py:183`
`= os.environ.get("LAYOUT_SOLVER", "cpsat")`). All other LX / co-opt
/ relayout / sencores knobs already match `faff191`.

On the three shared flash shapes:

| shape | solver | scratchpad_pass_ms | scratchpad_solve_ms | pre_dxp_ms |
|---|---|---:|---:|---:|
| flash-512×1024 | cpsat  | 798.5   | 330.4   | 17 806.8 |
| flash-512×1024 | greedy | 788.2   |   8.5   | 15 532.0 |
| flash-512×4096 | cpsat  | 11 187.5 | 9 090.0  | 65 580.9 |
| flash-512×4096 | greedy | 3 456.8  |   126.8 | 57 661.0 |
| flash-512×8192 | cpsat  | 75 696.2 | 70 589.5 | 200 334.8 |
| flash-512×8192 | greedy | 8 188.0  |   501.0 | 135 302.3 |

* Historical greedy scratchpad behavior **remains comparatively
  inexpensive**.
* Current-main changed the default to CP-SAT, making solver time a
  major frontend compile-time component at scale.
* **Not a regression in the greedy implementation.**

Do not merge CP-SAT and greedy points into a single scaling curve
(see `notes/tables/scaling.md` and its `greedy_compat/` companion).

## PR #4113 dedup confirmation

`dedup_and_promote_constants` per shape:

| shape | dedup_ms |
|---|---:|
| flash-256×1024   | 22.1 |
| flash-512×512    | 26.2 |
| flash-512×1024   | 51.0 |
| flash-1024×1024  | 103.1 |
| flash-512×2048   | 105.0 |
| flash-2048×1024  | 205.8 |
| flash-512×4096   | 205.7 |
| flash-512×8192   | 418.0 |
| flash-1024×8192  | 853.5 |

Growth: 22 → 853 ms over `presched_ops` 110 → 4100 (37×) — empirical
exponent ≈ 1.0 in `presched_ops`. **Linear scaling; PR #4113's fix
is holding.** Dedup is never the top pass at any measured shape.

## MLP results

Layers scale FX / presched-op count as expected:

| shape | fx_nodes | presched_ops | n_specs | pre_dxp_total_ms |
|---|---:|---:|---:|---:|
| mlp-L2  | 12  | 6   | 6   | 3 754  |
| mlp-L4  | 22  | 12  | 12  | 4 069  |
| mlp-L8  | 42  | 24  | 24  | 4 721  |
| mlp-L16 | 82  | 48  | 48  | 4 979  |
| mlp-L32 | 162 | 96  | 96  | 6 040  |
| mlp-L64 | 322 | 192 | 192 | 8 482  |

L=2's slight elevation above L=4 (3754 vs 4069) is cold-start
overhead of the first MLP compile in the sweep-driver process
sequence; not a scaling pathology. Not warmed away because this is a
cold-compile study.

`pre_compile_fx + compile_fx_outer_other ≈ 3300–3600 ms` at every
MLP shape — MLP results are dominated by fixed startup at these
small graph sizes.

## Harness fidelity

`HARNESS FIDELITY: PASS WITH KNOWN CROSS-RUN BUNDLE NONDETERMINISM`
(established prior to this sweep; see `data/fidelity_rescoped/`).
Not reopened.

## Sweep validity

* Frozen SHA asserted per run via the applier + driver-side
  `git rev-parse HEAD` check.
* Cost-model OFF guard (harness refuses `--allow-cost-model`
  unset with `SPYRE_DUMP_COST` set or `config.cost_model` on).
* `--expect-solver` guard on every sample (refuses mismatch,
  exit 5).
* Strict reconciliation 0.00% on 54/54 valid runs.
* Fresh `TORCHINDUCTOR_CACHE_DIR` per sample. Fresh process per
  sample.

## Recommended first concrete follow-up under #4117

Prototype a **size-threshold + greedy-fallback rule** in
`torch_spyre/_inductor/scratchpad/allocator.select_allocator`:
run greedy first, escalate to CP-SAT only when the graph's
`planner_buffer` count is below a caller-tunable ceiling and a
cheap quality heuristic suggests CP-SAT will help. Measure the
compile-time delta on the same 9-flash + 6-MLP sweep. Solver
quality changes are explicitly out of scope for #4117; solver
compile cost is in scope.

See `notes/next-opportunities.md` for the full ranked list.
