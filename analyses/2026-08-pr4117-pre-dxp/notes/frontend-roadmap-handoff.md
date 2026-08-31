# Torch-Spyre frontend performance — roadmap and handoff (#4117)

Written by Todd Deshane 2026-08-31 as a wide-first reconnaissance
after PR #4139 (certified greedy seed for placement-only CP-SAT) went
Ready for Review. This note is intended to survive Todd's departure
so Will (and other engineers) can pick up remaining lanes without
re-discovering the problem.

Data collected in this pass lives under
`analyses/2026-08-pr4117-pre-dxp/data/frontend_recon_2026_08/`. All
measurements are on the rebased branch (upstream `main` `ae9b88d`
plus the PR #4139 seed), single cold sample per workload except
where noted. **These are stand-alone-closure compiles** — the
measured graphs are small (13-31 pre-scheduling ops); production
transformer runs will amplify the passes that scale with graph size.
The 2056-buffer captured flash-512x8192 planner set already
established that fallback CP-SAT still runs and matches standalone.

## Completed / underway lanes

- **Baseline framework** — pre-DXP timing/attribution methodology
  in `analyses/2026-08-pr4117-pre-dxp/harness/` (see
  `pre_dxp_stop.py`, `frontend_reconnaissance.py`,
  `scratchpad_subtime_probe.py`, `fixed_startup_probe.py`,
  `build_solver_probe.py`, `sdsc_subtime_probe.py`).
- **PR #4113** dedup fix — merged upstream.
- **CP-SAT investigation / PR #4139** — certified greedy seed inside
  placement-only `CpSatLayoutSolver.plan_layout`. On accepted plans
  greedy replaces CP-SAT entirely (previously several tens of ms
  to tens of seconds); on rejected plans the standalone CP-SAT solve
  runs unchanged. Ready-for-Review at 2026-08-31.
- **`op_read_writes` memoization** — already in-tree on the rebased
  branch (`pass_utils.op_read_writes`, key `_ts_cached_read_writes`
  on the op instance, invalidated via `invalidate_op_read_writes`
  after inner-fn swaps in `graph_editor.py`). The prior study
  identified per-pass `get_read_writes` as a hot repeated call;
  this cache already fixes it. Any candidate that claims "cache
  op_read_writes" is redundant — check this first.
- **Will's likely lane** — `optimize_restickify_locations` and
  earlier restickify work. Kept measured in the tables below;
  classified `LIKELY_WILL_LANE`. See §4 of the numbered candidate
  cards.

## Refreshed residual attribution (2026-08-31)

Rebased branch, DXP intercepted at the subprocess boundary, seed
active. Cold single-sample per workload.

| workload | first_call_wall | dominant pass | 2nd pass | 3rd pass | 4th | 5th |
|----------|-----:|---|---|---|---|---|
| flash 512x4096 | 3.98 s | `_maybe_scratchpad_planning` 622 ms | `optimize_restickify_locations` 33 | `propagate_spyre_tensor_layouts` 28 | `span_reduction` 28 | `_distribute_work` 23 |
| flash 512x8192 | 4.23 s | `_maybe_scratchpad_planning` 518 ms | `optimize_restickify_locations` 34 | `_distribute_work` 30 | `propagate_spyre_tensor_layouts` 28 | `span_reduction` 28 |
| flash 1024x8192 | 4.25 s | `_maybe_scratchpad_planning` 647 ms | `optimize_restickify_locations` 35 | `_distribute_work` 30 | `propagate_spyre_tensor_layouts` 29 | `span_reduction` 28 |
| MLP L=8 (1024→4096) | 4.77 s | `_maybe_scratchpad_planning` 721 ms | `span_reduction` 62 | `_distribute_work` 54 | `propagate_spyre_tensor_layouts` 34 | `optimize_restickify_locations` 15 |
| sdpa S=512 | 4.49 s | `_maybe_scratchpad_planning` 737 ms | `optimize_restickify_locations` 97 | `span_reduction` 80 | `propagate_spyre_tensor_layouts` 70 | `_distribute_work` 56 |
| transformer_block seq=512 emb=1024 ffn=4096 | 6.58 s | `_maybe_scratchpad_planning` 1122 ms | `_distribute_work` 125 | `span_reduction` 80 | `propagate_spyre_tensor_layouts` 65 | `optimize_restickify_locations` 59 |

Cross-workload phase totals (wall):

| phase | flash 4096 | flash 8192 | flash 1024x8192 | MLP L8 | sdpa S512 | tb-1024 |
|-------|-----------:|-----------:|----------------:|-------:|----------:|-------:|
| `graphlowering.compile_to_module` | 1154 ms | 1064 | 1188 | 1319 | 1746 | 2199 |
| `spyre.pre_scheduling_pipeline` | 759 | 661 | 794 | 920 | 1098 | 1490 |
| `inductor.Scheduler.__init__` | 44 | 44 | 44 | 61 | 99 | 211 |
| `inductor.Scheduler.codegen` | 204 | 217 | 207 | 105 | 150 | 170 |
| `spyre.SpyreAsyncCompile.sdsc` | 97 | 98 | 97 | 164 | 282 | 249 |

## The new dominant cost: `_maybe_scratchpad_planning` still >500 ms

Even with the seed active, `_maybe_scratchpad_planning` accounts for
500-1200 ms — the largest pre-scheduling bucket by a factor of 5-20
on every workload measured. On investigation
(`scratchpad_subtime_probe.py`) the breakdown inside
`plan_allocation` on seq=512 emb=1024 transformer_block is:

```
step     0.00 ms  pre_optimization_passes
step    45.10 ms  _prepare_buffers
step  1202.66 ms  _build_solver            <-- 96% of scratchpad-planning
step     0.93 ms  _solve                   <-- seed skipped CP-SAT
step  <1.00 ms  each  _finalize_lx_relayout_allocation .. post_optimization_passes
```

**`_build_solver` is a lazy first-time OR-Tools import.**
`build_solver_probe.py` confirms:

- `ortools.sat.python` import first call: **1435 ms**
- `ortools.sat.python` import second call (cached): **0.00 ms**
- `ilp_solver_ortools` module import (once OR-Tools is warm): 8.5 ms
- `_make_cpsat_solver(bufs, size)` call after warm-up: 0.01 ms
- `plan_allocation` after warm-up on a fresh 30-buffer set: 25 ms

So the 500-1200 ms cost is **not solver work** and it's not
`_generate_buffers`. It's the first-time SWIG bootstrap of
OR-Tools' C++ bindings, happening lazily inside
`allocator._make_cpsat_solver` on line 2310 (`from
torch_spyre._inductor.scratchpad.ilp_solver_ortools import
CpSatLayoutSolver`), which in turn imports `ortools.sat.python`.

## Fixed startup

`fixed_startup_probe.py` on a trivial `torch.relu(x)` closure with a
1-element input, freshly-launched process:

```
[ 0.000s] starting
[ 0.009s] frontend_reconnaissance imported
[ 0.012s] DXP stop installed
[ 8.851s] torch imported
[ 8.851s] torch_spyre imported
[ 8.851s] torch._inductor imported
[ 8.851s] GraphLowering imported
[ 8.903s] scratchpad.allocator imported
[ 8.943s] wrappers installed
[14.638s] input allocated               <-- first spyre tensor: +5.7 s
[14.651s] torch.compile wrapper created
[20.638s] first compiled call done      <-- +5.99 s
[20.709s] second call (71.0 ms)         <-- cache-hit second call
```

The 5.99 s first-compile on a *trivial* graph decomposes to:
- ~1.3 s inside `GraphLowering.compile_to_module` (measured).
- ~4.7 s inside Dynamo tracing / lowering, outside our wrappers.
- ~1.4 s of that 4.7 s is the lazy OR-Tools import happening the
  first time `_make_cpsat_solver` is called.

So the **fixed compile-latency floor** on a warm Python process is
approximately 6 s, of which ~1.4 s can be removed by preloading
OR-Tools during process init. The 8.85 s `torch + torch_spyre`
import is separate and belongs to the process launch, not the
compile.

## SDSC decomposition (small graphs)

`sdsc_subtime_probe.py` on transformer_block seq=512 emb=1024
(19 specs, one SDSC call):

```
find_unimplemented        0.00 ms
_compile_specs (Pass 1) 176.18 ms   -> ~9.3 ms/spec
```

- Per-spec cost is ~9 ms — matches historical 8-9 ms/spec.
- `_compile_specs` walks `specs` depth-first (via `LoopSpec.body`
  recursion) and calls `compile_op_spec` once (or twice with
  `sdsc_cache` enabled, since the canonical-form key requires a
  parallel compile). Each `OpSpec` also writes a `sdsc_N.json`
  file to disk.
- Pass 2 (`bundle.mlir` emission) walks compiled entries, does
  dedup across `symbol_kinds`, dedup across `dim_syms`, dedup
  across affine maps, then writes `bundle.mlir` as one open file.
- On these small graphs Pass 2 was too small to measure separately
  (< a couple ms). On the historic 35.7 s bundle-generation at
  flash-1024x8192 with hundreds/thousands of specs, Pass 1 wall
  is expected to dominate (per-spec × n_specs).

## Scheduler init + codegen

- `Scheduler.__init__`: **44-99 ms** on our workloads (211 ms on
  the transformer_block). Historical largest-flash was 16.8 s.
  Scaling unit is scheduler nodes / dependency edges. Owned by
  upstream Inductor; Torch-Spyre only registers node-level passes
  via `patches._spyre_update_scheduler`.
- `Scheduler.codegen`: 105-217 ms on our workloads. Historical
  largest-flash was 14.4 s. Owned by upstream Inductor with a
  Spyre wrapper-codegen hook.

## Wrapper / module-exec accounting

`GraphLowering.compile_to_module` = 1.06-2.20 s across our
workloads. It calls, in order: our custom
`_pre_scheduling_pass` (`spyre.pre_scheduling_pipeline`,
0.66-1.49 s), Scheduler init, Scheduler codegen (which emits
wrapper Python source), then imports/executes the wrapper module.
The generated wrapper module contains `async_compile.sdsc(...)`
calls that fire during import. So:

```
compile_to_module
├── _update_scheduler (Spyre monkey-patch, patches.py:126)
│   └── _pre_scheduling_pass (CustomPreSchedulingPasses)
│       ├── deadcode_elimination
│       ├── propagate_named_dims / validate_named_dims / assign_dim_hints
│       ├── coarse-tile-hints
│       ├── split_multi_ops
│       ├── propagate_spyre_tensor_layouts
│       ├── validate_ops
│       ├── optimize_restickify_locations   <-- LIKELY_WILL_LANE
│       ├── finalize_layouts / insert_restickify / …
│       ├── insert_restickify_padding
│       ├── insert_bmm_padding
│       ├── dedup_and_promote_constants
│       ├── coarse-tile-span-overflow
│       ├── span_reduction
│       ├── _distribute_work
│       ├── _maybe_scratchpad_planning         <-- includes lazy ortools import
│       └── elide_proven_read_copies
├── Scheduler.__init__
├── Scheduler.codegen
│   └── emits wrapper Python source
├── import + exec the generated wrapper module
│   └── SpyreAsyncCompile.sdsc(kernel_name, specs, pool_size)
│       ├── find_unimplemented
│       ├── generate_bundle
│       │   ├── _compile_specs (Pass 1 - per-spec, ~9 ms/spec)
│       │   └── bundle.mlir emission (Pass 2)
│       ├── build_kernel_provenance_descriptor
│       └── subprocess.run(["dxp_standalone", …])  <-- INTERCEPTED
└── return compiled module
```

On our workloads `spyre.SpyreAsyncCompile.sdsc` measured 97-282 ms
(inclusive of `find_unimplemented`, `generate_bundle`, and
`build_kernel_provenance_descriptor`). The remaining
`compile_to_module` wall — after subtracting pre-scheduling and
SDSC — is Python source generation, module import, Scheduler
init/codegen, and wrapper execution: ~200-700 ms on our tests.

## Remaining opportunity map

Not all of the below are worth doing. §7 rankings state which are
worth prioritizing.

### Candidate cards (3-6 independent workstreams)

---

### Card 1 — OR-Tools eager preload

**Name.** Eager-import OR-Tools during Spyre backend init to remove
the ~1.4 s first-compile lazy-import spike.

**Current cost.** 500-1200 ms on **every first compile** in a
process. On our data this is the single largest pre-scheduling
bucket. Amortizes to zero after the first compile.

**Scaling / natural unit.** Fixed, one-shot per process.

**Source ownership.** Torch-Spyre. Locus:
`torch_spyre/_inductor/scratchpad/allocator.py:2310` (lazy import
inside `_make_cpsat_solver`).

**What appears expensive.** SWIG-wrapped C++ ortools binding
initialization. Verified in `build_solver_probe.py`: first
`from ortools.sat.python import cp_model` takes ~1.4 s; every
subsequent import is 0 ms.

**Current hypothesis.** Move the `from ortools.sat.python import
cp_model, cp_model_helper` up into `torch_spyre/__init__.py` (or
a lazy-loader gated on `config.layout_solver in {"cpsat"}` that
fires when torch_spyre is imported, not when the first compile
runs). This shifts cost to import-time where users already pay
`torch_spyre` import cost.

**Confidence.** HIGH. Fully diagnosed and reproducible.

**Expected upside.** 500-1200 ms shaved off every first compile;
zero on subsequent compiles. This IS the small-graph interactive
speedup — no other change in this list is as clean.

**Risk.** LOW. OR-Tools is already a hard dependency (no fallback
path exists when `ilp_solver_ortools` is missing except the greedy
solver, which is what our fallback already does). Import ordering
in `torch_spyre.__init__.py` may interact with autoload gating —
worth a small test.

**Independence.** YES. Independent of Will's restickify lane and
of the CP-SAT certificate work.

**First next experiment.** Move the import to
`torch_spyre.__init__`, gate on
`config.layout_solver == "cpsat"`, re-run
`fixed_startup_probe.py`. Should collapse the first-compile spike.

**Likely fix shape.** Local import ordering change (~10 lines).

**Ownership tag.** `GOOD_INDEPENDENT_TASK`. Trivial to hand off.

---

### Card 2 — Torch-Spyre / torch import cost (~8.9 s process launch)

**Name.** Reduce or defer torch_spyre import-time cost.

**Current cost.** ~8.85 s from process start to `torch_spyre`
imported. This is process launch, not compile — it hits every
python process that touches the backend.

**Scaling / natural unit.** Fixed, one per process. Grows only
when new eager submodules are added on the import path.

**Source ownership.** Mixed. Some is upstream `torch` (~7 s of
`import torch` alone is typical on Python 3.12 with recent
pytorch). Torch-Spyre's own `__init__` adds another chunk
(need to measure — the probe times both together).

**What appears expensive.** Not decomposed further in this pass;
`fixed_startup_probe.py` shows `torch` and `torch_spyre` complete
together at 8.851 s but does not separate them.

**Current hypothesis.** Most is upstream torch; some fraction is
Spyre-side eager submodule imports and PrivateUse1 device
registration.

**Confidence.** MEDIUM. Total confirmed; per-owner attribution not
yet done.

**Expected upside.** UNKNOWN. If we can shave 500 ms of Spyre-side
imports, small graphs benefit; multi-second wins likely require
upstream torch changes.

**Risk.** MEDIUM. Lazy-loading device backends can break the
PrivateUse1 autoload contract.

**Independence.** YES.

**First next experiment.** Add per-module `time.perf_counter()`
around every top-level `import` in `torch_spyre/__init__.py` and
around the PrivateUse1 device-registration path.

**Likely fix shape.** Lazy imports of heavy submodules, no
architectural change.

**Ownership tag.** `GOOD_INDEPENDENT_TASK`.

---

### Card 3 — Spyre-device first-tensor init (~5.7 s)

**Name.** Reduce first-tensor-on-spyre initialization cost.

**Current cost.** 5.70 s between "torch_spyre imported" and "first
`torch.randn(1, device='spyre')` returned" in `fixed_startup_probe.py`.

**Scaling / natural unit.** Fixed, one per process.

**Source ownership.** Torch-Spyre / Spyre runtime C++ bindings.

**What appears expensive.** Not decomposed further. Likely
includes Spyre driver / runtime handshake, device topology query,
`_C.so` initialization.

**Current hypothesis.** UNKNOWN — the RAS log line
`ContextNotCreated` fires here (see any workload stdout), which
suggests the runtime is checking device availability
synchronously. This may not be reducible on the dev pod but might
be reducible on target hardware.

**Confidence.** LOW without deeper probe.

**Expected upside.** UNKNOWN. Possibly 1-5 s off first tensor.
Small-graph latency-sensitive.

**Risk.** MEDIUM — touching device init requires the runtime
owner's input.

**Independence.** YES from #4139.

**First next experiment.** Instrument
`torch_spyre._C._device_init()` (or whichever C-side entrypoint
runs first) with a timer.

**Likely fix shape.** Runtime team investigation. Not a Torch-Spyre
Python fix.

**Ownership tag.** `NEEDS_ARCHITECTURAL_DISCUSSION` /
`NEEDS_SDSC_OWNER`-style (Spyre runtime team).

---

### Card 4 — `optimize_restickify_locations` and restickify pipeline (LIKELY_WILL_LANE)

**Name.** Continue Will's restickify investigation.

**Current cost.** Measured 15-97 ms across our tiny workloads (higher
for sdpa; lower for MLP). Historical largest-flash was 138 s. This
lane's cost scales strongly with graph size and restickify-candidate
count.

**Scaling / natural unit.** Number of stickify boundaries; number of
restickify candidates; number of consumer edges per producer.

**Source ownership.** Torch-Spyre. `optimize_restickify.py` (~866
lines).

**What appears expensive.** Not re-analyzed in this pass — this is
already Will's lane and re-analysis would duplicate his work.

**Current hypothesis.** Not stated here — Will's investigation.

**Confidence.** HIGH that this remains an important lane at
production graph sizes; unclear from small-graph data alone.

**Expected upside.** Historically the second-largest bucket (138 s
at flash-1024x8192, ~27% of pre-DXP). If the previously-observed
scaling continues, tens of seconds are recoverable at production
sizes.

**Risk.** MEDIUM — restickify insertion is on the correctness path.

**Independence.** Independent of #4139; overlaps completely with
Will's active work — do not duplicate.

**First next experiment.** Coordinate with Will; don't start.

**Likely fix shape.** Local algorithm change and/or shared
analysis context.

**Ownership tag.** `LIKELY_WILL_LANE`.

---

### Card 5 — SDSC per-spec cost + bundle-generation Pass 1 batching

**Name.** Batch or amortize per-spec `_compile_specs` work.

**Current cost.** ~9 ms/spec × n_specs. Small graphs: 97-282 ms
total. Historical largest-flash: 35.7 s / ~9 ms per spec × ~4000
specs. **On any graph with many hundreds of specs, this is the
biggest single lane after scratchpad and restickify.**

**Scaling / natural unit.** `n_specs`.

**Source ownership.** Torch-Spyre. `_inductor/codegen/bundle.py`
`_compile_specs` + `_inductor/codegen/superdsc.py` `compile_op_spec`.

**What appears expensive.** Per-spec: `compile_op_spec` builds a
JSON dict + symbol resolution + affine map extraction, then writes
one `sdsc_N.json` per spec. With `sdsc_cache` enabled, each spec
runs `compile_op_spec` **twice** (once for canonical cache-key
generation, once for the real emission — bundle.py:515 vs 536).

**Current hypothesis.** Three plausible sub-opportunities:

1. `sdsc_cache` double-compilation: canonical `compile_op_spec(0,
   entry, [], 0)` runs the full spec compile just to compute the
   cache key, then does it again. Deriving a lighter cache key
   from `entry` structure alone would halve per-spec cost when
   the cache is on.
2. Per-spec `json.dump` to disk in a hot loop — n_specs file
   writes. Batching to one JSONL / a single archive file might
   reduce I/O.
3. Sympy work inside `compile_op_spec` (affine strides, symbol
   registration) may reduce with better sympy caching. Not
   inspected in this pass.

**Confidence.** MEDIUM. Per-spec cost measured; sub-decomposition
of `compile_op_spec` not done in this pass.

**Expected upside.** At production sizes ~35 s historic → maybe
15-25 s recoverable if per-spec halves. Tiny on small graphs.

**Risk.** MEDIUM — `bundle.mlir` bytes are consumed by DXP; any
change must preserve identical output.

**Independence.** YES.

**First next experiment.** Instrument `_compile_specs` inner loop
to attribute per-spec cost to `compile_op_spec` vs `json.dump`
vs cache-key work. Measure with `sdsc_cache=1` vs `sdsc_cache=0`
on a large-spec workload.

**Likely fix shape.** Cache-key light-touch + optional batched
disk write.

**Ownership tag.** `GOOD_FOR_WILL` (adjacent to his existing work)
or `GOOD_INDEPENDENT_TASK`.

---

### Card 6 — Cross-pass shared analysis context (speculative)

**Name.** Introduce a phase-local analysis cache shared between
propagate_spyre_tensor_layouts, span_reduction, _distribute_work,
insert_restickify_padding (and the working-set-reduction passes).

**Current cost.** On our small graphs each of these 4 passes runs
in 5-80 ms. Historic largest-flash: 33.5 s combined.

**Scaling / natural unit.** Graph ops × per-op analysis fanout.

**Source ownership.** Torch-Spyre.

**What appears expensive.** Not yet demonstrated in this pass.
`op_read_writes` is already cached (see Completed). Other
candidates that MIGHT be repeated across passes:

- dependency-edge extraction / consumer discovery (each pass rebuilds
  its own graph-walk state).
- symbolic simplification of index expressions
  (`find_reduction_var`, `broadcast_batch_vars`, and the
  layout-propagation matmul path all touch sympy `free_symbols` /
  `.subs()`).
- device-layout extraction (`SpyreTensorLayout` object
  reconstruction).
- per-core view construction.

**Current hypothesis.** The rebased tree's `op_read_writes` memo is
the biggest win of that shape. Others might not exist at the
scale worth building an analysis context for — need per-call
counters across a larger real workload to justify.

**Confidence.** LOW. Under-motivated on this small-graph data. A
production-graph rerun of `frontend_reconnaissance.py` with more
`analysis_call_counts` keys wired up is needed before proposing
a shared context.

**Expected upside.** UNKNOWN.

**Risk.** HIGH if built prematurely. Analysis-cache correctness
across graph-mutating passes needs sharp invalidation boundaries.

**Independence.** YES.

**First next experiment.** Extend `frontend_reconnaissance.py`
counter list to include `get_op_users`, `iter_operations`,
`compute_layouts`, `MemoryDep.__init__`, and sympy `free_symbols` /
`.subs` hotspots. Run on a large real graph (e.g. the captured
production transformer, not our stand-alone flash). Only then
decide whether the shared context is worth building.

**Likely fix shape.** New `AnalysisContext` object passed through
`CustomPreSchedulingPasses.__call__`, invalidated at boundaries
where the graph mutates. NOT to build in one pass.

**Ownership tag.** `NEEDS_ARCHITECTURAL_DISCUSSION`.

---

## Rankings

### Large-model compile-time ranking

For "seconds saved on the largest realistic frontend workloads":

1. **Card 4** — `optimize_restickify_locations` / restickify pipeline
   (Will's lane). Historical 138 s. Highest absolute upside.
2. **Card 5** — SDSC per-spec Pass 1 batching. Historical 35.7 s;
   scales linearly with `n_specs`.
3. **Card 6** — shared analysis context, IF and only if a
   large-graph rerun shows repeated expensive analysis beyond
   the already-memoized `op_read_writes`.

`_maybe_scratchpad_planning`'s residency solve is now removed on
the certified path (PR #4139). What remains is the OR-Tools
first-import (Card 1), which does NOT scale with graph size — it's
a fixed startup cost regardless of workload.

### Interactive / small-model ranking

For "fixed compile latency; first useful compile":

1. **Card 1** — OR-Tools eager preload. Removes 500-1200 ms from
   every first compile in a process. Trivial local fix.
2. **Card 3** — Spyre device first-tensor init (~5.7 s). Requires
   runtime-team input.
3. **Card 2** — torch_spyre import cost (~8.85 s combined with
   torch). Mostly upstream torch; some Spyre-side deferrable.

## Suggested sequencing

Derived from the data above:

**Phase 1 — remove known dominant pathologies.**
- Card 1 (OR-Tools eager preload): the single-highest-leverage
  change for interactive latency, low risk, easy hand-off.
- Continue Card 4 (Will).

**Phase 2 — attack repeated linear work / per-spec constants.**
- Card 5 (SDSC per-spec halving via lighter cache key).
- Extend `frontend_reconnaissance.py` for the large-graph rerun
  that motivates or kills Card 6.

**Phase 3 — reduce fixed startup for the interactive latency
budget.**
- Card 2 (torch_spyre import decomposition + lazy loading).
- Card 3 (Spyre-runtime first-tensor init).

**Phase 4 — install trend / regression gates.**
See §9 below.

## Ownership suggestions

- Card 1 → `GOOD_INDEPENDENT_TASK`. Non-Will engineer. ~1 day of
  work + testing.
- Card 2 → `GOOD_INDEPENDENT_TASK` or `LIKELY_UPSTREAM_PYTORCH`
  depending on where the cost lands after per-module timing.
- Card 3 → `NEEDS_ARCHITECTURAL_DISCUSSION` with the Spyre-runtime
  team (`NEEDS_SDSC_OWNER`).
- Card 4 → `LIKELY_WILL_LANE`. Do not duplicate.
- Card 5 → `GOOD_FOR_WILL` (adjacent to his existing work in the
  bundle-generation side) OR `GOOD_INDEPENDENT_TASK` — either can
  own it. Recommend confirming with Will first.
- Card 6 → `NEEDS_ARCHITECTURAL_DISCUSSION` after the large-graph
  rerun.

## Regression / trend infrastructure

Not yet built; recommend the following minimal persistent perf-gate
suite (§9):

**Deterministic unit-test-friendly metrics (safe to gate on):**

- `analysis_call_counts["Operation.get_read_writes"]` per pass —
  guards the `op_read_writes` memo against regression.
- `n_specs` per SDSC call — guards against future bundle-gen
  regressions that inflate spec counts.
- Number of `sdsc_N.json` files emitted per compile.
- Deterministic pass names and count observed in
  `spyre.inductor.passes` log.

**Noisy wall-clock CI/benchmark metrics (report only, don't gate):**

- `first_call_wall_s` per representative workload (flash 512x4096,
  MLP L4, sdpa S512).
- Per-pass `elapsed_ms` for the top 8 pre-scheduling passes.
- `spyre.SpyreAsyncCompile.sdsc` per-call wall.
- `_maybe_scratchpad_planning` wall (should drop dramatically
  after Card 1 lands).
- `plan_layout` chosen path (`greedy-certified` vs
  `cpsat-fallback`) count per compile.

Suggested cadence: run a small suite (5 workloads × 1 sample) on
each merge to `main`; alert on wall-clock >2× median-of-last-N.
Gate on the deterministic metrics.

## Handoff: exact paths

Data:
- `analyses/2026-08-pr4117-pre-dxp/data/frontend_recon_2026_08/*.json`
- `analyses/2026-08-pr4117-pre-dxp/data/hybrid_certified_corpus_v2/summary.json`
- `analyses/2026-08-pr4117-pre-dxp/data/capacity_pressure_sweep_v2/summary.json`
- `analyses/2026-08-pr4117-pre-dxp/data/e2e_validation/*.json`

Harness:
- `analyses/2026-08-pr4117-pre-dxp/harness/frontend_reconnaissance.py`
- `analyses/2026-08-pr4117-pre-dxp/harness/tb_probe.py`
- `analyses/2026-08-pr4117-pre-dxp/harness/scratchpad_subtime_probe.py`
- `analyses/2026-08-pr4117-pre-dxp/harness/build_solver_probe.py`
- `analyses/2026-08-pr4117-pre-dxp/harness/fixed_startup_probe.py`
- `analyses/2026-08-pr4117-pre-dxp/harness/sdsc_subtime_probe.py`
- `analyses/2026-08-pr4117-pre-dxp/harness/seed_endtoend_probe.py`
- `analyses/2026-08-pr4117-pre-dxp/harness/seed_fallback_probe.py`
- Prior harness (parent study): existing files in the same directory.

Notes:
- This file.
- `analyses/2026-08-pr4117-pre-dxp/notes/certified-greedy-seed.md`
- `analyses/2026-08-pr4117-pre-dxp/notes/pr4139-hardening-report.md`
- `analyses/2026-08-pr4117-pre-dxp/notes/pr4139-body-draft.md`

## Continuation checkpoint

If Todd stopped working on #4117 today, the durable evidence is:

- Baseline pre-DXP attribution methodology and harnesses (working
  on the rebased branch — validated 2026-08-31).
- Per-pass per-workload timing data on 8 stand-alone workloads.
- Diagnosed root cause of the remaining `_maybe_scratchpad_planning`
  bucket: lazy OR-Tools SWIG import. Reproducer:
  `build_solver_probe.py`.
- Fixed-startup decomposition on a trivial closure. Reproducer:
  `fixed_startup_probe.py`.
- SDSC per-spec cost model (~9 ms/spec, historical corroboration).
  Reproducer: `sdsc_subtime_probe.py`.
- Six candidate cards above with independent-ownership tags.
- Two rankings (large-model / interactive).
- A regression-suite proposal.

Missing / weak:

- No large-graph rerun on the rebased branch — the stand-alone
  closures used here don't stress the passes that historically
  dominated (restickify, SDSC bundle-gen). Card 6 depends on a
  large-graph rerun.
- SDSC Pass 2 (bundle.mlir emission) was under-measured (below
  the noise floor on small graphs).
- `build_kernel_provenance_descriptor` was not decomposed
  (measured ~zero cost on our small graphs).
- `torch` vs `torch_spyre` import cost is not separated.
- No decomposition inside `Scheduler.__init__` or `Scheduler.codegen`
  — treated as upstream Inductor black boxes.
- Card 3 (device init) has no source-level attribution yet.

**Overall answer: YES — enough documented evidence is in the
handoff for Will (or another engineer) to continue systematically
rather than rediscover the problem, with the caveat that Card 6 in
particular needs a large-graph rerun before deciding whether to
build a shared analysis context.**
