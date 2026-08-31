# Torch-Spyre #4117 frontend performance — continuation plan for Will

**Author.** Todd Deshane, 2026-08-31, on his way out of IBM.

**Purpose.** One page you can read cold. Tells you what's done, what
you're expected to own next, and exactly which script to run first.
For deeper context, follow the links; nothing here assumes access to
Slack, IBM internal wikis, or PR-comment threads.

---

## What is already done

| # | Status | What it is |
|---|---|---|
| #4113 | merged | dedup fix. Baseline for everything below. |
| #4139 | Ready for Review; **awaiting maintainer response** | **Certified greedy seed for placement-only CP-SAT.** Accelerates only `CpSatLayoutSolver.plan_layout` (`co_optimizing_lx_planning=False`); does NOT accelerate `plan_layout_and_core_divisions`. On 28 corpus scenarios: 20 certified, 8 fallback, 0 objective mismatches vs standalone CP-SAT. On 40 captured-buffer capacity-pressure points: 39 certified, 1 fallback (flash-512x8192 at 25% capacity). See `notes/certified-greedy-seed.md`. **Status update 2026-08-31**: Dave Grove (`dgrove-oss`, author of #3932 epic) indicated joint CP-SAT co-optimization is expected to become the shipped default imminently. Todd asked on-thread whether placement-only remains supported or whether #4139 should close as #3932 evidence; **awaiting Dave's answer**. See `notes/pr4139-pr4141-coopt-transition.md`. |
| #4141 | Ready for Review; **strategic value coupled to #4139** | **Lazy OR-Tools loading.** Certified compiles no longer trigger the ~1.4 s SWIG bootstrap of `ortools.sat.python.cp_model`. Compounds #4139. A/B fresh-process median: 3.04 s → 1.93 s first useful compile (-1.11 s, -36%); a second session under higher pod contention reproduced -2.06 s. Rebased onto upstream `7c1d5b6` (post-#4084 `elem_arr_1` ceiling fix). All 5 required top-level workflows green on head `1fa1f56`. **If joint CP-SAT becomes the shipped default, #4141's measured startup win no longer applies to the default compile path** — the joint solver needs OR-Tools, so the lazy import fires immediately on first joint compile. Residual value (module-loading hygiene, thread-safe first-load, absent-package fallback preservation) is a maintainer judgment. Held with #4139 pending Dave's answer. See `notes/pr4141-body.md`, `data/lazy_ortools_ab_v2/`, and `notes/pr4139-pr4141-coopt-transition.md`. |

Baseline instrumentation harness (all in
`analyses/2026-08-pr4117-pre-dxp/harness/`):

- `frontend_reconnaissance.py` — DXP-intercepted probe over any
  standalone workload; captures per-pass `elapsed <ms>ms` from
  `spyre.inductor.passes`, coarse phase spies, and analysis call
  counts.
- `tb_probe.py` — transformer-block workload for a bigger stand-alone
  graph.
- `scratchpad_subtime_probe.py` — breaks `plan_allocation` into its
  8 sub-steps.
- `fixed_startup_probe.py` — fixed per-compile cost on a trivial
  closure. This is the harness that produced the #4141 A/B.
- `sdsc_subtime_probe.py` — decomposes `generate_bundle` into pass 1
  (`_compile_specs`, ~9 ms/spec) and pass 2 (bundle.mlir emission).
- `ortools_import_chain_probe.py` — subprocess-isolated import-chain
  audit; snapshots `sys.modules` at each stage of a compile.
- `lazy_ortools_ab.sh` — driver for A/B on the OR-Tools import path.
- `seed_endtoend_probe.py` / `seed_fallback_probe.py` — instrument
  `plan_layout` on real workloads (used for #4139 evidence).

Known measurement caveats:

- Stand-alone closures (flash / MLP / sdpa / transformer_block) hit
  the compiler with tiny subgraphs (13–31 pre-scheduling ops). They
  bound fixed-cost measurements well but do NOT stress the passes
  that historically dominated at production graph sizes.
- Pod wall-time noise: `first_call_wall` on the trivial-compile
  fixture varied 3.7-15.8 s between BASELINE runs on the same probe
  session. Deltas were stable; absolutes are not.
- `torch` import (~5-9 s cold) and first Spyre-tensor allocation
  (~5.7 s) are separate from any compile-time optimisation.
- **Previously-recurring `keep_by_index_4d_dim3` CI failure was
  fixed by #4084**:
  `test_inductor_ops__oot_wrapper.py::TestOpsPRIVATEUSE1::test_keep_by_index_4d_dim3_spyre`
  with `AssertionError: Tensor-likes are not close!` at
  `test_inductor_ops.py:6354` (max absolute diff ~99 at tol 0.1 —
  a real wrong-output signature, not a small tolerance flake).
  Seen on multiple #4139 and #4141 pushes onto pre-#4084 upstream.
  #4084 (`Round up elem_arr_1 factor for index tensors`) fixed
  `compute_ops.gen_coord_info_value` to use ceiling division for
  index-tensor coordinate factors; after rebasing #4141 onto
  `7c1d5b6` (post-#4084 upstream), the failure did not reappear.
  If you see it again on future #4117 PRs, first confirm the base
  contains #4084; if it does, treat as a new regression, not a
  return of this one.
- **CI infrastructure stall watchdog**: individual sub-tests can
  be `SIGKILL`ed by the pod-level stall-watcher after ~6.5 min,
  producing `exit=137`. The killed attempt's VFIO fd doesn't
  release synchronously, so the immediate retry hits
  `RAS::VFIO::DeviceOpenFail: Device or resource busy` and
  reports a spurious setup error. Not a code failure; the parent
  workflow's aggregation logic treats it as recoverable.
  Observed on the `Test Inductor Ops Reduction Scalar` sub-check
  after the #4141 rebase-onto-`7c1d5b6` push (the parent `tests`
  workflow still concluded `success`).

---

## Priority-zero after the joint-CP-SAT default switch

Once `co_optimizing_lx_planning` becomes the shipped default (per
Dave Grove's 2026-08-31 note on #4139; see
`notes/pr4139-pr4141-coopt-transition.md`), the first performance
task is:

**Profile the joint CP-SAT path at production graph scale. Do not
assume it scales like placement-only CP-SAT did.**

Reuse the `harness/frontend_reconnaissance.py` DXP-intercept
methodology. Measure model-building time and solve time separately;
capture n_buffers, n_core_division_buffers, and where possible the
`cp_model.CpModel` decision-variable and constraint counts.
Production-shaped workloads (flash, MLP, sdpa) with captured
planner-buffer sets. Full experiment plan in the coopt-transition
note.

**Do NOT extend #4139's placement-only certificate into
`plan_layout_and_core_divisions`.** The joint objective has axes
(parallelism, balance, optional `cost_expr`) that the placement-
only forced-spill lower bound does not cover. A joint-objective
lower-bound proof would be a real research task, not a mechanical
extension. The certificate methodology from #4139 remains useful
as evidence for the #3932 compile-time/scalability track even if
neither PR merges.

---

## What you are already expected to own

### Restickify lane (LIKELY_WILL_LANE)

Historical largest-flash pre-DXP cost: **`optimize_restickify_locations` ~138 s at flash-1024x8192**. Second-largest bucket after scratchpad in the frozen-tree study. On the small stand-alone workloads I re-measured post-#4139/#4141 it's 15-97 ms — but production graph size has always been where this scales.

Files:

- `torch_spyre/_inductor/optimize_restickify.py` (~866 lines).
- `torch_spyre/_inductor/insert_restickify.py`.
- `torch_spyre/_inductor/padding.py`
  (`insert_restickify_padding` and `insert_bmm_padding`).

You already have prior investigation in this area; I did not
re-analyse it in the reconnaissance pass, so nothing here duplicates
your existing thinking.

**Exact next useful experiment:**

```bash
# On a real production graph you already have handy (not the stand-
# alone flash closure), rerun frontend_reconnaissance.py with the
# analysis-call-count list extended to include per-op restickify
# candidate counts. The current list already captures
# spyre.optimize_restickify_locations.entry and
# spyre.insert_restickify_padding.entry as bare entry counts, but
# not their per-op fanout.
SPYRE_INDUCTOR_LOG=1 SPYRE_INDUCTOR_LOG_LEVEL=INFO \
  python3 analyses/2026-08-pr4117-pre-dxp/harness/frontend_reconnaissance.py \
    --workload <your bigger workload> --out /tmp/restick.json
```

Then look at:
- per-pass `elapsed_ms` for the restickify passes on a large graph;
- number of restickify insertions and their per-op cost;
- whether the pass's inner loops scale with graph size or with
  restickify-candidate count.

**What NOT to redo:**

- Don't re-derive `op_read_writes` memoisation. It's already in-tree
  at `torch_spyre/_inductor/pass_utils.py:122` (key
  `_ts_cached_read_writes`, invalidated in `graph_editor.py`).
- Don't re-run the full frontend residual attribution on stand-alone
  closures; my `data/frontend_recon_2026_08/` already covers that
  and shows the scratchpad bucket is now dominated by OR-Tools
  import time (removed by #4141).

---

## Strong next lane after restickify

### SDSC per-spec / bundle generation

Historical: **`sdsc_bundle_gen_total` ~35.7 s at flash-1024x8192,
~4097 specs, ~8-9 ms/spec** (`notes/certified-greedy-seed.md` and the
prior study).

I reproduced the per-spec relationship on a modest workload:
transformer_block seq=512 emb=1024, 19 specs, `_compile_specs`
Pass 1 took 176 ms → **~9.3 ms/spec** — matches history.

Files:

- `torch_spyre/_inductor/execution/async_compile.py`
  (`SpyreAsyncCompile.sdsc` — outer entry).
- `torch_spyre/_inductor/codegen/bundle.py`
  (`generate_bundle`, `_compile_specs`, `_emit_specs`).
- `torch_spyre/_inductor/codegen/superdsc.py`
  (`compile_op_spec` — the per-spec worker, ~2284 lines).
- `torch_spyre/_inductor/kernel_provenance.py`.

**What evidence is strong:**

- Per-spec cost of ~9 ms is reproducible; scales linearly with
  `n_specs`.
- With `sdsc_cache` enabled, `_compile_specs` calls `compile_op_spec`
  **twice per spec on a cache MISS**: once at `bundle.py:515` for
  canonical cache-key generation, again at `bundle.py:536` for the
  real emission. On a cache **hit** the second call is elided, so
  the extra compile only runs on misses.
- Each spec writes an `sdsc_N.json` file to disk in the hot loop.

**What still needs large-graph confirmation:**

- Ratio of pass-1 to pass-2 (`bundle.mlir` emission) at scale. On my
  small workloads pass 2 was below the noise floor.
- **Actual `sdsc_cache` miss rate on production graphs.** The
  double-compile matters *more* when many specs are unique
  (high miss rate → the canonical-compile-then-real-compile path
  runs for most specs). It matters *less* when many specs are
  duplicates (high hit rate → most specs skip the second compile
  anyway). Without the miss-rate measurement first, you don't
  know whether halving the miss-path saves 40% of SDSC wall or
  4%.
- Whether disk-write is CPU-bound (JSON serialization dominates) or
  I/O-bound (`json.dump` fsync latency). Different fixes.

**First 2–3 experiments:**

1. **Measure the production cache miss rate first.** In
   `_compile_specs`, add throwaway counters for cache hits and
   misses (the code already threads `_sdsc_cache_counts` for
   this — just log the tuple at end of compilation on real graphs).
   Do NOT change the cache key before you know what fraction of
   specs are actually on the miss path.
2. **Confirm ratio at scale.** Run
   `harness/sdsc_subtime_probe.py` on a captured production
   compile (or a bigger stand-alone workload) with hundreds of
   specs. Compare `_compile_specs` (Pass 1) vs bundle.mlir emit
   (Pass 2) wall.
3. **Ablate JSON write.** Comment out the `json.dump` in
   `_compile_specs` (skip the file write) and re-measure per-spec
   cost. If per-spec drops meaningfully, the win is in batching
   disk writes; if not, the win is in `compile_op_spec` itself.

**Where the harness/data already live:**

- Harness: `harness/sdsc_subtime_probe.py`.
- Data: `data/frontend_recon_2026_08/*.json` under
  `spyre.SpyreAsyncCompile.sdsc` phase time.

---

## Conditional lane

### Shared frontend analysis context

**Currently speculative.** Do NOT build a generalised analysis cache
until a large production graph proves the repeated work exists.

What's already known:

- `op_read_writes` is already memoised (see above).
- On small stand-alone workloads I did not see other repeated
  analysis at suspicious counts. The reconnaissance
  `analysis_call_counts` field captured
  `spyre.pass_utils.op_read_writes` (127-366 calls per workload)
  and a handful of pass-entry counters; nothing else stood out.
- If a big graph shows an inner loop that rebuilds e.g. consumer
  discovery, symbolic simplification, or per-core view construction
  per pass, THAT is where a shared context earns its keep.

**Exact instrumentation to rerun first:**

Extend
`frontend_reconnaissance._install_pass_counters()` to wrap
additional candidates before deciding whether to build anything:

```python
# Suggested additions (pseudocode; wire them the same way the
# existing counters are wired):
_wrap_method(Operation,          "get_read_writes",       ...)
_wrap_method(ReadWrites,         "from_body_expr",        ...)
_wrap_free_fn(pass_utils,        "get_op_users",          ...)
_wrap_free_fn(pass_utils,        "iter_operations",       ...)
# and any sympy hot-spot you observe on a real graph
```

Only if a call at very high count with a non-trivial per-call cost
appears does a shared analysis context become justified. Cache
invalidation across graph-mutating passes is subtle — the
invalidation-boundary discussion is in the roadmap Card 6.

---

## Likely other-owner lanes

**Scheduler init / codegen** (Card 3 of the roadmap): 44-211 ms on
my small workloads; historical 16.8+14.4 s at flash-1024x8192.
Owned by upstream Inductor with a thin Spyre wrapper. Unless a
production-scale rerun shows Torch-Spyre substantially amplifies
upstream cost, this is a PyTorch-team problem, not a #4117
frontend problem.

**Spyre device first-tensor init** (~5.7 s in the fixed-startup
probe): runtime/device-team lane. RAS `ContextNotCreated` fires
here. Not a compile-scaling problem.

**Broad `torch_spyre` import restructuring** (~8.85 s combined with
`import torch`): mostly upstream torch. Some Torch-Spyre-side
deferrable, but a separate product from large-model compile
scaling.

Don't touch these under #4117.

---

## Reproduction entry points

**Run this first (one command, ~10 minutes):**

```bash
cd toddllm/compiler-timing
# On any pod that has torch-spyre installed with layout_solver=cpsat:
SPYRE_INDUCTOR_LOG=1 SPYRE_INDUCTOR_LOG_LEVEL=INFO \
  python3 analyses/2026-08-pr4117-pre-dxp/harness/frontend_reconnaissance.py \
    --workload flash --Lq 512 --Lk 8192 \
    --out /tmp/recon.json
```

Compare against my baseline in
`analyses/2026-08-pr4117-pre-dxp/data/frontend_recon_2026_08/flash_512x8192.json`.

**Look at these counters first** (all interpretation is
same-machine / same-session relative to a comparison run — absolute
wall values on this pod vary run-to-run under contention):

- Ranked top of `passes[].elapsed_ms`. Pre-#4141 the top was
  `_maybe_scratchpad_planning` at 500-1200 ms; post-#4141 it should
  no longer be in the top of the list. If it is, something in
  #4141 regressed.
- Ranked top of `phases[].elapsed_ms`. Compare shape against my
  baseline JSON alongside your run; a new phase near the top that
  wasn't in the baseline points at where to look.
- `analysis_call_counts["Operation.get_read_writes"]` — should
  scale with `n_ops`, not `n_ops^2`. Super-linear against graph
  size across two runs is a regression signal.
- `first_call_wall_s` — useful only for A/B against another fresh-
  process run on the same machine within the same session. Do not
  treat any absolute threshold as correctness-like; the same-pod
  session showed BASELINE median wander from 3.04 s to 5.12 s
  under contention.

**Decision tree** (based on rankings, not absolute wall):

- **If `_maybe_scratchpad_planning` reappears in the top of the pass
  list on the rebased branch**: something in #4141 regressed. Check
  that `_load_ortools` isn't being called before the certificate
  rejects.
- **If a restickify pass dominates on a big production graph**:
  restickify lane (yours already).
- **If SDSC bundle-gen dominates at production scale**: SDSC lane
  (see above). Confirm with `sdsc_subtime_probe.py` and the
  miss-rate measurement.
- **If a new pass appears in the top of the list that wasn't there
  before**: new regression, investigate its own inner loop before
  generalising.
- **If none of the above and total wall is stable**: nothing #4117-
  scoped to do; the interactive-latency floor is dominated by
  `import torch` and Spyre device init, both other-team lanes.

---

## Cross-reference

- `notes/frontend-roadmap-handoff.md` — the full 6-card roadmap
  with Chosen / Rejected control for Card 1 (this file's short
  version).
- `notes/certified-greedy-seed.md` — #4139 design, corpus, and
  capacity-pressure sweep.
- `notes/pr4139-hardening-report.md` — full #4139 hardening history.
- `notes/pr4139-body-draft.md` — final #4139 PR body.
- `notes/pr4141-body.md` — final #4141 PR body.
- `data/hybrid_certified_corpus_v2/summary.json` — #4139 corpus.
- `data/capacity_pressure_sweep_v2/summary.json` — #4139 sweep.
- `data/e2e_validation/*.json` — #4139 real-compile validation.
- `data/frontend_recon_2026_08/*.json` — post-#4139 residual
  attribution on 8 workloads.
- `data/lazy_ortools_ab_v2/{BASELINE,HARDENED_LAZY}/sample_*.txt`
  — #4141 A/B evidence.

If PR discussion is hard to find later, all the substantive
evidence you need is in this repo.
