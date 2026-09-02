# Final Torch-Spyre Frontend Performance Handoff

**Author.** Todd Deshane, 2026-09-02.

**Purpose.** Supersede the earlier Torch-Spyre frontend performance
handoff (`will-continuation-plan.md`, `frontend-roadmap-handoff.md`) for
prioritization. Written after tracing the current default planning path
on upstream `main` and reviewing the joint-CP-SAT PRs actively in flight
(#4018, #4203, and adjacent).

**Scope.** What the next engineer should work on to make frontend
compilation acceptable once the joint CP-SAT co-optimizing path
(`co_optimizing_lx_planning=True`) is the shipped default. Investigation
and this document are the deliverable; no production code changes.

**Standards used in this document.**

- **VERIFIED.** Read directly from upstream `main`
  (`3919da175dc1f42c6be636468dff8e38ef7ef101`) or a specific PR head.
  Cited by file and line.
- **INFERRED.** Follows from what is verified plus a stated assumption.
- **RECOMMEND.** A judgment call. Kept separate from evidence.

Earlier Todd recommendations that this document supersedes are called
out explicitly at the section that supersedes them.

---

## 1. Executive conclusion

**Where the architecture is going.** `layout_solver="cpsat"` is already
the shipped default on upstream `main` (set by #3978, merged
2026-08-26). `co_optimizing_lx_planning` is still `False` on upstream
`main` (`torch_spyre/_inductor/config.py:23-25`); the switch to `True`
lives in **#4018 "Enable default cooptimization"** (draft, actively
being iterated as of 2026-09-02). The pending stack that determines the
shape of the default compile is:

- **#4018** (draft) — flips `co_optimizing_lx_planning` to `True` by
  default, lowers `time_limit_seconds` from 120 s to 30 s, adds seven
  "pin to fixed division" guards to `CoOptimizingAllocator._division_map`
  for classes of op the joint solver would otherwise re-slice into
  silently wrong code, currently disables the `prune` knob on the
  candidate-enumeration path.
- **#4203** (draft) — adds solver-decided LX relayouts on
  producer/consumer edges (a real feature expansion of the joint model),
  raises `time_limit_seconds` from 120 s to 600 s, enabled by default
  within the joint config.
- **#3810** (merged 2026-08-30) — cost-model objective (`cost_expr`)
  wired into the joint CP-SAT `plan_layout_and_core_divisions` call.
- **#4196** (Ready) — closes a `PYTHONHASHSEED`-dependent nondeterminism
  hole in the LX planner itself; unblocks any A/B measurement on the
  joint path.

Two of the drafts above disagree on the CP-SAT time limit by 20x
(#4018: 30 s, #4203: 600 s). Whichever lands first will materially
change the compile-time worst case.

**What that does to the previous performance priorities.**

- **#4139 (certified greedy seed) and #4141 (lazy OR-Tools) accelerate
  the placement-only CP-SAT path only** — see the module docstring at
  `torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py:15-82` and the
  test on `plan_layout` (not `plan_layout_and_core_divisions`) at
  `ilp_solver_ortools.py:659`. Neither reaches the joint solver. If
  #4018 lands as intended, both PRs stop affecting the default compile.
  Prior handoff (`will-continuation-plan.md`) called out this coupling;
  this document supersedes its prioritization: **placement-only compile
  cost is no longer the central lane**.
- **`optimize_restickify_locations`** (Will's earlier lane) still has
  the historical largest-flash pre-DXP bucket (~138 s at
  flash-1024x8192). Unchanged by any of the joint-path work. Prior
  handoff called this out as `LIKELY_WILL_LANE` — still the correct
  reading, but decoupled from the joint-solver work below.
- **SDSC per-spec / bundle generation** — still an independent lane;
  historical ~35.7 s / ~4097 specs. Its win is coupled to the
  `sdsc_cache` miss rate, and the double-compile path on cache misses
  is still in the code (`bundle.py:515`, `bundle.py:536` per the prior
  handoff). Also unchanged by the joint-solver work.

**Where the next owner should focus (ordered).**

1. **Instrument the joint CP-SAT solver at production scale.** Two
   things: (a) internal breakdown of `plan_layout_and_core_divisions`
   into deterministic sub-phases (see §5), (b) a machine-readable
   per-compile timing record (this is #4156, still fully unclaimed —
   see §9). Nothing else on this list is decidable without this data.
2. **Characterize the joint model's growth on production-shaped
   graphs.** How many candidate divisions per op, how many
   producer-consumer edges, how many `cd_parent_matches` pairs, how
   many `cd_parent_relayouts` triples (once #4203 lands), how many
   CP-SAT decision variables and constraints. Answer #3934 with real
   numbers before recommending a heuristic. See §4 and §5.
3. **Decide the timeout-and-fallback policy from evidence.** Today, a
   CP-SAT timeout under `co_optimizing_lx_planning=True` degrades via
   `SolveError` to a **placement-only greedy fallback**
   (`allocator.py:2415-2425`). That is the pre-#2062 unsafe path, gated
   only by `demote_incoherent_lx_buffers`. Any shipped default needs a
   timeout policy that does not silently reintroduce the very failure
   mode joint co-optimization exists to prevent. See §7.
4. **Look at whether the joint solver can be given a cheap feasible
   incumbent** (warm start / solution hint / seeded plan). Today it
   receives none (verified: zero occurrences of `add_hint`, `AddHint`,
   or `SetSolutionHint` across `ilp_solver_ortools.py` on upstream
   `main`, #4018, and #4203). This is Todd's most transferable
   intuition from the #4139 work: greedy often finds an excellent
   placement quickly. But greedy alone carries no core-division choice
   and does not know the joint objective's parallelism/balance/relayout
   axes, so the transfer is not mechanical. See §6.

---

## 2. Current default-path architecture

This section explains what actually executes on a torch-spyre compile
under the anticipated new defaults (`layout_solver="cpsat"` +
`co_optimizing_lx_planning=True`), reading from upstream `main` at
`3919da1` and the #4018/#4203 diffs.

**Entry point.**
`CustomPreSchedulingPasses` (`passes.py:421`, ordered pipeline
including `_maybe_scratchpad_planning`) runs each pass, timing it with
`time.perf_counter()` and logging `elapsed %5dms  <pass_name>` at INFO
on `spyre.inductor.passes` (`passes.py:511-526`).
`_maybe_scratchpad_planning` (`passes.py:412-418`) is a thin wrapper on
`scratchpad_planning(graph)` (`allocator.py:2399`), which calls
`select_allocator()` (`allocator.py:2333`), then
`allocator.plan_allocation(graph)`.

**Allocator selection under the new defaults.**
`select_allocator` (`allocator.py:2333-2396`):

- `co_optimizing_lx_planning=True` and `layout_solver="cpsat"` →
  `CoOptimizingAllocator(layout_planning=_make_cpsat_solver, ...)`.
- `co_optimizing_lx_planning=True` and `layout_solver` is a non-cpsat
  placement-only solver (greedy/firstfit/bestfit) → the placement-only
  factory is wrapped in `ExhaustiveSearchSolver`, which does a
  cross-product DFS over candidate divisions × placement solves. See §7
  under "OR-Tools missing"; this is the s390x default today per #3932.
- `co_optimizing_lx_planning=False` (today's default on upstream) →
  `ScratchpadAllocator(layout_planning=solver_cls, ...)`.

**Under the joint default: what actually runs.**

1. **Candidate core-division enumeration.**
   `CoOptimizingAllocator._division_map`
   (`allocator.py:1722+`, extended by #4018) walks
   `graph.operations` and produces a `divisions: dict[str,
   list[CoreDivision]]` per op. Each op falls into one of three cases:

   - **Pinned to its committed division.** #4018 broadens the "pinned"
     class from just `ops_in_offset_mutation_component` to include
     CPU/host buffers, windowed pools, keep_by_index layout groups,
     fp8-matmul layout groups, indirect-access ops, and offset-slice
     reads. Each guard corresponds to a documented wrong-code failure
     the joint solver would otherwise cause; see
     `_is_windowed_pool`/`_is_coarse_tiled`/`_is_indirect_access_op`/
     `_reads_offset_slice`/`_fused_layout_group_ops` in the #4018
     diff. **Pinning ~single-candidate ops shrinks the effective
     search space substantially** (see §4).
   - **`prune=True`.** Deduplicated `_legal_split_options` set built
     from `_enum_split_options` (matmul roles, matmul-driven
     tilings). Falls back to a single fixed division if the pruned set
     is empty (added late in #4018 iteration).
   - **`prune=False`.** Full
     `_enumerate_core_divisions(op, max_cores=config.sencores)` via
     `enumerate_work_division_candidates` (`work_division.py:799`) —
     the cross-product of per-axis factors filtered by
     `MAX_SPAN_BYTES`, at-most-one-K-split, blocked dims, and
     `allowed_splits`. The most recent #4018 head disables `prune`
     ("Lower time limit and undo pruning"), so this is the enumeration
     that ships if #4018 merges as-is.

2. **Buffer wrapping.** `CoOptimizingAllocator._prepare_buffers` (via
   the base `ScratchpadAllocator.plan_allocation` at
   `allocator.py:264`) produces one `CoreDivisionBuffer` per op with:
   `core_divisions` (the list above), `parents` (producer names),
   `cd_parent_matches[parent]` (division-index pairs whose per-core
   views are equal — precomputed by `_cd_parent_matches`),
   `residency_reason` (pre-computed from allocator-declared bars).
   Under #4203, also `cd_parent_relayouts[parent]` = list of
   `(P_div_idx, C_div_idx, cost_ns)` triples for edges where a shuffle
   is priced by the fitted `relayout_ns` law.

3. **CP-SAT model construction** — `CpSatLayoutSolver._plan_layout_generic`
   (`ilp_solver_ortools.py:712-755`) then `_run` (`ilp_solver_ortools.py:798`):

   - Each buffer wrapped by `_wrap` (`ilp_solver_ortools.py:688-710`).
     A buffer with `core_divisions` gets the joint wrapper
     (`_CoreDivisionBufferWithCpVars.__post_init__`,
     `ilp_solver_ortools.py:279-332`); everything else gets the
     placement-only wrapper. The joint wrapper creates: `division` int
     var over `[0, len(core_divisions)-1]`, `eff_size` var over
     `[0, max(per_core)]`, `core_cost` int var, `cores` int var,
     per-axis `sym_core_divs` int vars (one per output/reduction
     symbol, domain `[1, config.sencores]`), and
     `AddElement`s tying them to `division`. Under #4203, also one
     BoolVar per relayout-eligible edge in
     `_CoreDivisionBufferWithCpVars.__post_init__` and,
     inside `constrain_residency`, pair literals plus the
     match/relayout gate.

   - Common terms: `in_buffer` bool, `offset` int var, `merge_vars`
     bool per in-place parent, plus the base `_add_no_overlap_2d`
     over optional rectangles (`allocator.py`+`ilp_solver_ortools.py`
     around `_add_inplace_relaxation` at line 916). Under #4203, one
     extra optional rectangle per relayout-eligible edge with the
     edge's decision literal as presence.

4. **Objective.** Two entry paths (`ilp_solver_ortools.py:822-882`):

   - `cost_expr` **is** provided (the #3810 path,
     `CoOptimizingAllocator._solve` at `allocator.py:1659-1687`, always
     provides one when bundle scoring succeeded): a single
     `model.minimize(cp_cost)` where `cp_cost` is
     `_SympyExprToCpSat(model, sym_map).convert(cost_expr)`. The
     linearization does sympy rewrites (`floor`, `log(min)`, `Pow` to
     `inv_` symbol, `Mul` distribution), each of which can call back
     into `model.AddMultiplicationEquality` and `AddMinEquality` /
     `AddMaxEquality` (`ilp_solver_ortools.py:611-627`). Symbolic size
     is not bounded by the number of variables and constraints —
     several rewrite paths can create new intermediate int vars.
   - `cost_expr` **is not** provided or the linearization threw
     (`_minimize_cost_expr` returns `None`,
     `ilp_solver_ortools.py:792-796`): fallback lexicographic solve —
     level 1 residency (HBM traffic `sum spill_cost * (1 - in_buffer)`),
     level 2 parallelism (`sum cores`), level 3 balance
     (`sum core_cost`). Each level pins the prior optimum as a
     constraint and re-solves. Under #4203 the fallback pins every
     relayout literal to 0 (an unpriced shuffle would look free).

5. **Solve.** `cp_model.CpSolver()` with
   `parameters.max_time_in_seconds = self._time_limit_seconds`
   (`ilp_solver_ortools.py:809-816`). `num_search_workers = 1` under
   deterministic mode, else `os.cpu_count()`. `random_seed = 0`. On
   upstream `main` the constructor sets `time_limit_seconds=120.0`
   (`ilp_solver_ortools.py:643`). #4018 lowers it to 30 s; #4203 raises
   it to 600 s. **Status handling is the same at every level: only
   `OPTIMAL` and `FEASIBLE` are accepted; every other status raises
   `SolveError`.** Timeout with no feasible solution
   → `UNKNOWN` → `SolveError` → propagates up.

6. **Extraction and commit.** `_extract` reads back per-buffer chosen
   division and offset. `_justify` (`ilp_solver_ortools.py:64-68` doc)
   slides each merged unit to the lowest free address. Under #4203,
   `_finalize_lx_relayout_allocation` (extended in the diff) rebuilds
   the two `PerCoreView`s under the chosen divisions and returns
   `LXRelayoutPlan`s that `materialize_lx_relayouts` inserts as real
   copies.

7. **Fallback path.** `scratchpad_planning` at `allocator.py:2415-2425`
   catches `SolveError` and re-runs with `GreedyLayoutSolver` — the
   placement-only greedy allocator. **This is important:** under
   `co_optimizing_lx_planning=True`, a timeout is caught by the same
   `except SolveError` and falls back to plain greedy placement, not
   to the ExhaustiveSearchSolver or SA co-optimizer. That is the
   pre-#2062 unsafe path, still relying on `demote_incoherent_lx_buffers`
   to patch up any producer/consumer core-division disagreement.

**Simplified flow (the real code above is authoritative):**

```
graph.operations (topological)
  → CoOptimizingAllocator._division_map(graph)          (§ enumeration)
     → for each op:
          if op matches a pin guard → [committed division]
          elif prune=True           → _legal_split_options(op, ...)
          else                       → enumerate_work_division_candidates
  → CoreDivisionBuffer per op with:
       core_divisions, parents, cd_parent_matches,
       cd_parent_relayouts (only under #4203),
       residency_reason
  → CpSatLayoutSolver.plan_layout_and_core_divisions(cost_expr)
     → _wrap each buffer (vars, AddElement to per_core sizes)
     → _add_inplace_relaxation + _add_no_overlap_2d + relayout dest rects
     → residency gate (slicing-match OR relayout, per edge, per buffer)
     → objective: cost_expr (single minimize) OR lex triple
     → cp_model.CpSolver().Solve(model)  [time-limited]
     → status ∈ {OPTIMAL, FEASIBLE} → extract; else raise SolveError
  → scratchpad_planning fallback on SolveError:
       ScratchpadAllocator(GreedyLayoutSolver).plan_allocation(graph)
```

---

## 3. What changed since the earlier handoff

The earlier Todd handoff was oriented around the placement-only CP-SAT
path (`plan_layout`), which is what #4139/#4141 accelerate. Between
2026-08-30 and 2026-09-02, three pieces of the joint path shifted:

- **#3810 merged 2026-08-30** — the joint solver's default objective
  path now goes through `cost_expr` when the allocator can build a bundle
  cost. This changes the CP-SAT model materially: instead of the
  lexicographic triple (residency, parallelism, balance) the solve is a
  single `model.minimize(cp_cost)` where `cp_cost` came out of
  `_SympyExprToCpSat.convert`. That linearization is the largest new
  chunk of Python-side model-construction work, and it's mostly opaque
  to instrumentation today.

- **#4018 (draft, in active iteration)** — flips
  `co_optimizing_lx_planning` default to `True` and lowers the CP-SAT
  time limit to 30 s, adds seven pin-guard classes to the division map
  (see §2 step 1), currently disables the `prune` knob but adds a
  fallback for empty pruned sets. The commit log shows real churn on
  correctness ("Fixed scatter and gather", "Fixed matmul error", "Fixed
  numerical error", "Fixed pre-commit", "Fixed missing function") — the
  joint path is not merely a flag flip; it needs behavior guards that
  the placement-only path did not.

- **#4203 (draft)** — adds LX relayout as a *solver-chosen decision*.
  This is a genuine feature expansion of the joint model: per eligible
  producer→consumer edge, one edge BoolVar + N pair literals + one
  optional destination rectangle. Enumeration builds a table of
  `(P_div_idx, C_div_idx, cost_ns)` triples per edge via the fitted
  `relayout_ns` law. Raises `time_limit_seconds` from 120 s to 600 s —
  a 5x-vs-#4018 disagreement that will need resolution before either
  ships as the default.

**Why placement-only optimization is no longer the central frontend
performance target.** Two independent reasons:

- **Correctness first, not compile time.** #3932's motivation is that
  the greedy/placement-only path had 11 value-corruption failures from
  producer/consumer core-mapping disagreement (#2062). The joint path
  is the only cell in the 2x2 that gets all 11 right *structurally*.
  That decides the default independent of compile time.
- **Sunk cost is not a reason.** The #4139 certificate proves greedy
  is objective-optimal for a specific placement-only scalar; that
  argument does not extend to the joint objective (parallelism,
  balance, `cost_expr`, plus #4203's per-edge relayout costs). The
  prior handoff (`pr4139-pr4141-coopt-transition.md`) called out this
  scope mismatch; the same argument still holds after the current
  investigation.

Earlier `will-continuation-plan.md` "Priority-zero after the
joint-CP-SAT default switch" section said the first task is to profile
the joint path at production graph scale. **This document keeps that
recommendation and makes it concrete: §5 and §10.**

Earlier `frontend-roadmap-handoff.md` Cards 3-6 (scheduler, wrapper,
device init, shared analysis context) remain other-owner or speculative
lanes. This document does not change their disposition.

---

## 4. Where compile time can grow

Size variables in this table are natural to the specific stage. Priority
uses this document's judgment scale: **P1** = must be measured before
any heuristic can be chosen; **P2** = likely to matter once P1 evidence
lands; **P3** = hedge against known unknowns.

| # | Stage | Natural size variables | Scaling mechanism | Current evidence | Instrumentation needed | Priority |
|---|---|---|---|---|---|---|
| 1 | Candidate division enumeration per op (`enumerate_work_division_candidates`, `work_division.py:799`) | per-axis factor lists × #axes; `MAX_SPAN_BYTES` filter; at-most-one-K-split rule | Cross-product of `factors(v)` over `it_space_adjusted.keys()` (line 885-889); rejected by `valid_split`. Filter is per-candidate `get_per_core_span` computed for every tensor dep. | None current on the joint path. #4018 turned pruning on then off in the last three days. | **Per-op**: `n_axes`, `n_factors_per_axis`, `n_generated_pre_filter`, `n_legal_post_filter`, `time_ms`. | **P1** |
| 2 | Pin-guard evaluation (`_division_map` in #4018) | `n_ops`; `_fused_layout_group_ops` rescan | Loop-invariant group sets built once; per-op guard chain runs top-down. `_reads_offset_slice` calls `op_read_writes(op)` (memoized). | The #4018 diff's inline comment explicitly notes the "loop-invariant group sets" hoist to `_division_map` header. Not yet measured. | Guard-hit counters (which guard pinned which op), per-guard `time_ms`. | **P2** |
| 3 | `cd_parent_matches` construction (`CoOptimizingAllocator._cd_parent_matches`, allocator.py) | `n_edges` × `mean(candidates_per_op)^2` (per-edge cross product of division indices, filtered by view equality) | Per edge, prepares up to two `PerCoreView`s per candidate pair via `_views_for_divs`; deduped through `prep_cache`. Real work is `n_edges * mean_pair_count`. | Not measured. `prep_cache` hits/misses are inspectable but not surfaced. | Per-edge: `n_producer_divs`, `n_consumer_divs`, `n_matched_pairs`, `prep_cache_hits`. | **P1** |
| 4 | `cd_parent_relayouts` construction (#4203, `CoOptimizingAllocator._cd_parent_relayouts`) | `n_edges` × `mean(candidates_per_op)^2`; `solver_relayout_pair_cost` per pair | Sibling of match; runs when `config.lx_solver_relayout=True` (default under #4203). Each pair calls `solver_relayout_edge_context` then `solver_relayout_pair_cost` (fitted law + gates). | Not measured. Only in #4203 branch. | Per-edge: `n_priced_pairs`, `time_ms`. | **P1** (once #4203 lands) |
| 5 | CP-SAT model construction (`_LifetimeBufferWithCpVars`/`_CoreDivisionBufferWithCpVars.__post_init__`, `_add_inplace_relaxation`, `_add_no_overlap_2d`) | `n_buffers`; per-buffer: `len(core_divisions)`, `n_axes`, `n_in_place_parents`. Under #4203: `n_relayout_pair_lits` per edge. | Per-buffer int/bool var creation + `AddElement`s. #4203 adds a BoolVar per edge + a BoolVar per pair + one optional rectangle per edge. | None on the joint path. `CpModel.Proto().variables` / `.constraints` are inspectable post-construction. | Deterministic: `n_int_vars`, `n_bool_vars`, `n_constraints`, `n_add_element_calls`, `n_optional_intervals`. Wall: `model_build_ms`. | **P1** |
| 6 | `cost_expr` linearization (`_SympyExprToCpSat.convert`, `ilp_solver_ortools.py:391-548`) | Size of the sympy expression tree at entry; `#relayout_edges` (adds an additive term per edge under #4203) | Sympy rewrites (floor, log(min), Pow, Mul), each with `expr.replace` traversal. `_print_Mul` can call `AddMultiplicationEquality` and create new int vars. `_print_Max`/`_print_Min` call `AddMaxEquality` / `AddMinEquality`. | None. This is where #3810's cost model lives; the linearization is not directly benchmarked. | `sympy_expr_pre_expand_len`, `sympy_expr_post_len`, `add_multiplication_equality_count`, `linearize_ms`. | **P1** |
| 7 | CP-SAT solve (`solver.Solve(model)`, one call per objective level) | Model size (rectangles for no-overlap-2D, div/eff_size vars, residency lits, relayout lits). Search worker count. | OR-Tools CP-SAT internal. Not something we control directly; we can measure wall and status. Under lex-fallback, three solves; under `cost_expr`, one. Under #4203, one extra edge/pair layer per relayout-eligible edge. | Only the DEBUG log line at `ilp_solver_ortools.py:893-903` reports `walltime` and `status`. | Per-level: `solve_ms`, `status`, `objective_value`, `best_bound`, `num_conflicts`, `num_branches`, `num_search_workers` — all live on `cp_model.CpSolver` after the solve. | **P1** |
| 8 | Extraction + `_justify` | `n_buffers`; per-buffer in-place chain length | Solved-value reads + one downward slide per merge unit. Historically not a hot spot. | Not measured on the joint path. | `extract_ms`, `justify_ms`. | P3 |
| 9 | Fallback: `SolveError` → `GreedyLayoutSolver.plan_allocation` | `n_buffers`; greedy is single-pass. | The joint search is discarded; a placement-only plan runs on the same buffers. **Correctness concern is higher than compile-time concern** (see §7). | Silent today: only the `logger.debug("solve error detected. falling back to greedy solver.")` line. | Fallback event + reason (which solver, which level raised) as a structured record, not a debug log. | **P1** (correctness observability, not perf) |
| 10 | `ExhaustiveSearchSolver` (s390x / no-ortools with joint on) | `n_variable_buffers` and `mean(candidates_per_op)` → `K^N` DFS leaves; each leaf is one full placement solve. | Explicit DFS in `exhaustive_search.py:165-181`. Log line at 190-195 reports `n_paths` per solve. #3932 called this "a likely-unintended, expensive default" on s390x. | Log message exists but not aggregated. | `n_paths`, `t_search_ms` — already emitted, just needs collection. | **P2** (only if s390x runs joint) |
| 11 | Restickify passes | Graph size; restickify candidate count per op | Independent of joint switch. Historical largest bucket at flash-1024x8192 (~138 s). | Prior handoff documents it. | Not new here; see `will-continuation-plan.md`. | P2 (Will's lane, independent) |
| 12 | SDSC bundle generation | `n_specs`; `sdsc_cache` miss rate | Independent of joint switch. Historical ~35.7 s / ~4097 specs. Double-compile on cache miss. | Prior handoff documents it. | Not new here. | P2 (independent lane) |

**Why the Big-O-shaped rows don't get Big-O labels.** Row 1's
enumeration is a cross-product; the *cardinality* is a product of
per-axis factor list lengths, filtered by `MAX_SPAN_BYTES` and the
K-split rule. That product can be small (matmul with 2 free axes, few
factors) or large (many-axis pointwise on a big tensor with a factor
list of `{1,2,4,8,16,32}`); the count is the natural work metric, not
"O(N^k)". Rows 3 and 4 are `n_edges × candidates²` in the worst case
but each pair's evaluation is a `PerCoreView` construction (bounded by
its own concrete-domain evaluation), so pair count alone doesn't
predict wall — instrument both. Row 5 counts what CP-SAT sees; row 6 is
sympy overhead the CP-SAT search doesn't see; row 7 is the CP-SAT
search itself.

---

## 5. Joint CP-SAT measurement plan

**Concrete counters to add.** Every counter here is deterministic
(reproducible across runs on the same graph and config, given #4196's
`PYTHONHASHSEED` fix), unless flagged as **wall**.

Instrumentation surface: a small structured record emitted by
`CpSatLayoutSolver._plan_layout_generic` (and its callees) plus one
record emitted by `CoOptimizingAllocator._solve`. Every field below
serializes to a value that survives across runs — no free-form
strings for objective values, no absolute filesystem paths.

**Per compile, once.**

| Field | Source | Deterministic? |
|---|---|---|
| `n_ops` | `len(graph.operations)` | Yes |
| `n_buffers` | `len(solver.buffers)` in `CpSatLayoutSolver` | Yes |
| `n_core_division_buffers` | count of buffers with `len(core_divisions) > 0` | Yes |
| `n_variable_buffers` | count of buffers with `len(core_divisions) > 1` | Yes |
| `n_pinned_by_guard[guard_name]` | one counter per guard in `_division_map` (#4018) | Yes |
| `sum_candidates_over_buffers` | sum of `len(b.core_divisions)` | Yes |
| `sum_edges` | `sum(len(b.parents) for b in buffers)` | Yes |
| `sum_match_pairs` | `sum(len(b.cd_parent_matches[p]) for b, p ...)` | Yes |
| `sum_relayout_triples` | `sum(len(b.cd_parent_relayouts[p]) for b, p ...)` (#4203 only) | Yes |
| `n_forced_reasons` | `len(record_exclusions())` | Yes |
| `n_cp_int_vars` | `len(model.Proto().variables)` filtered for int | Yes |
| `n_cp_bool_vars` | same filtered for bool | Yes |
| `n_cp_constraints` | `len(model.Proto().constraints)` | Yes |
| `used_cost_expr` | 1 if `cost_expr is not None` and linearization returned non-None | Yes |
| `cost_expr_linearize_status` | `ok` / `linearization_failed` / `not_provided` | Yes |
| `n_solves` | 1 for `cost_expr`, 1–3 for lex triple | Yes |
| `time_limit_seconds` | `self._time_limit_seconds` | Yes (config-dependent) |
| `layout_solver` | `config.layout_solver` | Yes |
| `co_optimizing_lx_planning` | `config.co_optimizing_lx_planning` | Yes |
| `torch_spyre_sha` | HEAD SHA | Yes |
| `pythonhashseed` | `os.environ.get("PYTHONHASHSEED", "unset")` | Yes |

**Per solve (once for `cost_expr` path, up to 3 times for lex).**

| Field | Source | Deterministic? |
|---|---|---|
| `solve_level` | `residency` / `parallelism` / `balance` / `cost_expr` | Yes |
| `status` | `solver.StatusName(status)` | Yes |
| `objective_value` | `solver.ObjectiveValue()` (round when integer-lex) | Yes |
| `best_bound` | `solver.BestObjectiveBound()` | Yes |
| `walltime_ms` | `solver.WallTime() * 1e3` | **Wall** (already logged at line 902) |
| `num_conflicts` | `solver.NumConflicts()` | Yes |
| `num_branches` | `solver.NumBranches()` | Yes |
| `num_booleans` | `solver.NumBooleans()` | Yes |
| `num_search_workers` | `solver.parameters.num_search_workers` | Yes |

**Sub-phase timers.** These are wall-clock, kept out of unit tests.

| Timer | Bracket |
|---|---|
| `division_map_ms` | `CoOptimizingAllocator._division_map(graph)` |
| `cd_parent_matches_ms` | `_cd_parent_matches` |
| `cd_parent_relayouts_ms` | `_cd_parent_relayouts` (#4203) |
| `feature_extraction_ms` | the `predict_by_bundle` call chain in `_solve` (`allocator.py:1657-1678`) |
| `cost_expr_build_ms` | `_solve` around the `predict_by_bundle → sympify` (`allocator.py:1659-1665`) |
| `sympy_linearize_ms` | inside `_SympyExprToCpSat.convert` |
| `model_build_ms` | `CpSatLayoutSolver._plan_layout_generic` from `cp_model.CpModel()` to first `solver.Solve` |
| `solve_ms[level]` | one per `solver.Solve()` call |
| `extract_ms` | `_extract` + `_justify` |
| `total_planning_ms` | `_maybe_scratchpad_planning` (already exists as the pass-level `elapsed_ms`) |

**Distinguishing "Python is slow" vs "search is slow" vs "model is too
big."** The three signals map to:

- **Python/model construction slow** → high `model_build_ms` and/or
  `sympy_linearize_ms` and/or `division_map_ms`, low `solve_ms`.
  Fixable in our code without touching OR-Tools.
- **CP-SAT search slow** → low `model_build_ms`, high `solve_ms`, small
  gap between `objective_value` and `best_bound`, high `num_branches`.
  Requires a warm start, tighter bounds, or a different search
  strategy.
- **Model is too big** → high `n_cp_int_vars` / `n_cp_bool_vars` /
  `n_cp_constraints` and high `solve_ms` from the start, weak
  `best_bound`. Requires reducing what we hand CP-SAT (candidate
  dominance, edge pruning, chunking).

**Correlate to natural size.** For every counter above, plot against
`n_buffers`, `sum_candidates_over_buffers`, and `sum_edges` on a
production workload sweep (see §10). Log-log axes so superlinear
behavior is visible.

---

## 6. Highest-value optimization hypotheses

Ranked. Each includes: **why it might matter**, **evidence that would
confirm/refute**, **correctness risk**, **likely implementation
surface**. Do not implement any of these without §5 measurements first.

**H1 — Cheap feasible incumbent for the joint CP-SAT solve.**

- **Why it might matter.** VERIFIED (grep across upstream `main`,
  #4018, #4203): the joint solver receives no warm start, no
  `AddHint`, no seeded incumbent. The #4139 study demonstrated greedy
  reaches the placement-only optimum on 39 of 40 measured
  capacity-pressure points; even if that ratio does not transfer,
  greedy is very likely to find *a* feasible plan quickly. A feasible
  incumbent turns `SolveError` on timeout into
  "return the best feasible plan we had", which is worth measuring
  independently of any warm-start-improves-time claim.
- **Evidence to gather.** Instrument `_solve[level].status` and
  `_solve[level].objective_value` on production graphs. If a
  substantial fraction of joint solves currently exit `FEASIBLE` (not
  `OPTIMAL`) with a small remaining `best_bound` gap, hinting helps
  little on optimality but a lot on optimality-gap policy. If a
  fraction exit `UNKNOWN`, a feasible-incumbent-preserving fallback is
  the more urgent fix.
- **Correctness risk.** *Low* on the hinting itself (CP-SAT's hint is
  advisory), *high* on any change to the fallback that reuses the
  hinted plan. A hinted incumbent that the search discarded must not
  reappear on timeout unless it was structurally validated
  (slicing-match on every resident edge, capacity, in-place rules).
- **Implementation surface.** `CpSatLayoutSolver._plan_layout_generic`.
  A cheap seed candidate: everyone's committed division (like
  `ExhaustiveSearchSolver`'s initial state), with placement from
  `GreedyLayoutSolver`. That's already a *coherent* plan (every op at
  its committed division means producer/consumer divisions agree
  trivially), so hinting it is safe. Whether it wins search time is
  what §5 evidence would answer.
- **Do not extend the #4139 certificate here.** The forced-spill lower
  bound is a placement-only proof; the joint objective has extra axes
  the proof does not cover.

**H2 — Redundant candidate/model construction between passes.**

- **Why it might matter.** #4018's `_division_map` extension hoists
  `_fused_layout_group_ops` results out of the per-op loop with an
  explicit comment about the hoist. That is a specific case where a
  loop-invariant scan was previously re-run. Similar scans in
  `cd_parent_matches` and `cd_parent_relayouts` (§4 rows 3, 4) may or
  may not exhibit repeat work. #4203 introduces a `prep_cache` for
  view construction (see `_finalize_lx_relayout_allocation` in the
  diff), suggesting the author already found repeat work.
- **Evidence.** `prep_cache_hits` vs `prep_cache_misses` per edge (add
  as a counter). If misses dominate at production scale, caching is
  either miskeyed or not the win.
- **Correctness risk.** *Very low* on pure memoization if the cache key
  is complete (op name + dep + buf name is already how `prep_cache` is
  keyed). *Medium* if the cache leaks across graph mutations —
  `graph_editor.py`'s invalidation contract already handles the
  `op_read_writes` case; the joint-path caches are separate.
- **Implementation surface.** `CoOptimizingAllocator._cd_parent_matches`
  and `_cd_parent_relayouts` in `allocator.py`; `_prepare_per_core_view`
  and `_per_core_view_from_prep` if they show up as hot.

**H3 — Dominated candidate pruning.**

- **Why it might matter.** #4018's most recent commit undid the earlier
  `prune=True` default ("Lower time limit and undo pruning"). Under
  no pruning, `_enumerate_core_divisions` returns the full legal
  cross-product for every non-pinned op. That is exactly the size
  variable at row 1 of §4. A safe dominance rule (candidate A
  dominates B iff A is legal, A's per-core span ≤ B's on every
  tensor, A uses ≥ B cores, and A is compatible with the same or
  strictly more pairs on every incident edge) could remove candidates
  from the model without changing the reachable optimum.
- **Evidence.** `sum_candidates_over_buffers` before/after a
  dominance filter, on the same graph. `solve_ms` and
  `objective_value` before/after — if the optimum ever moves, the
  dominance rule is wrong.
- **Correctness risk.** *High.* This is a real proof obligation, not a
  heuristic. #4018's history of turning pruning on then off suggests
  the earlier `_enum_split_options` pruning was not safe under all
  ops. Any new pruning must survive the full test matrix, not just a
  showcase graph.
- **Implementation surface.**
  `CoOptimizingAllocator._enumerate_core_divisions` and any
  dominance predicate; must run *after* the pin-guard chain so the
  pinned ops are unaffected.
- **Read #4018's commit history before proposing this.** The removed
  pruning is not documented in the PR body yet, but the sequence
  ("Removed infeasible ops", "Trying to dedup logic", "Removed extra
  tests", "Proceed with pruning as default", "Lower time limit and
  undo pruning") tells you the author has already been burned once.

**H4 — Optimality-gap-based bounded solve policy.**

- **Why it might matter.** CP-SAT's `best_bound` is available after
  any solve. A policy that stops when `(obj - best_bound) / obj ≤ eps`
  or when a wall-clock budget is exhausted — whichever comes first —
  gives a predictable worst-case compile time. Today the only
  bounding is `max_time_in_seconds`, and its behavior at expiry is a
  hard `SolveError` (§7).
- **Evidence.** The full status/objective/bound distribution across
  the production sweep (§5 fields). If `best_bound` closes to within
  1% of `objective_value` before the time limit on most graphs, an
  early-exit policy costs nothing on those graphs and helps the tail.
  If it doesn't close, the policy still bounds the wall but at some
  objective cost that has to be characterized.
- **Correctness risk.** *Low* on the policy itself — early-exit
  returns a feasible plan CP-SAT already verified. The interaction
  with the lex-triple objective is subtle: an early exit on level 1
  can't run levels 2 and 3, so the plan won't be balance-optimized.
  That's usually fine but should be an explicit fallback path, not a
  silent behavior change.
- **Implementation surface.** `CpSatLayoutSolver._run`.
  `CpSolverSolutionCallback` gives per-solution progress if wanted.

**H5 — Cost expression size reduction (dominance / factoring).**

- **Why it might matter.** Under #3810 the objective is a single
  sympy expression built from `predict_by_bundle`. Under #4203, it's
  that expression plus one `relayout_symbol` term per relayout-eligible
  edge. `_SympyExprToCpSat.convert` does multiple `expr.replace`
  passes each of which walks the tree; `_print_Mul` can create fresh
  intermediate int vars (`AddMultiplicationEquality`). If the sympy
  expression has structural redundancy the linearizer doesn't factor
  out, we pay for it as extra CP-SAT variables and constraints.
- **Evidence.** `sympy_expr_pre_expand_len` / `sympy_expr_post_len` /
  `add_multiplication_equality_count`. If they grow non-linearly with
  graph size, there's a factoring opportunity.
- **Correctness risk.** *Medium.* Rewrites of sympy expressions have
  been the source of subtle bugs before. Any rewrite must preserve
  the numeric value of the expression under all bindings, not just
  the ones that happen on the current test corpus.
- **Implementation surface.** `_SympyExprToCpSat.convert` and its
  rewrites (`_log_min`, `_log_split`, `_inv_sym`, `_min_expand`,
  `_truncate_floats_min`).

**H6 — Model formulation improvements (e.g., channeling redundancies).**

- **Why it might matter.** The joint model uses `AddElement` heavily
  to tie `division` to per-axis vars, per-core sizes, and core counts.
  For a division menu of length K, that's K constants per array. CP-SAT
  handles this well up to a point; large K on many buffers may cost
  search time. Also, some symmetry may exist across identical
  candidate menus that a symmetry-breaking constraint could eliminate.
- **Evidence.** Distribution of `len(core_divisions)` across buffers,
  and whether many buffers share identical menus.
- **Correctness risk.** *High.* Symmetry breaking is easy to get
  wrong. Skip until §5 evidence proves it's on a bottleneck path.
- **Implementation surface.** `_CoreDivisionBufferWithCpVars.__post_init__`.

---

## 7. Timeout and fallback policy

**Current state on upstream `main`.**

- CP-SAT time limit = 120 s (`ilp_solver_ortools.py:643`). #4018 →
  30 s. #4203 → 600 s.
- Any status other than `OPTIMAL` or `FEASIBLE` raises `SolveError`.
  Under time-limited runs that typically means: **`FEASIBLE` (a plan
  was found before the limit) is accepted**; **`UNKNOWN` (no feasible
  plan yet at the limit) raises**. This is important — the code does
  preserve a feasible incumbent when one exists.
- `SolveError` is caught in `scratchpad_planning` at
  `allocator.py:2415-2425` and re-runs with
  `ScratchpadAllocator(GreedyLayoutSolver)` — the placement-only
  greedy path. **Under `co_optimizing_lx_planning=True`, this
  fallback discards every core-division decision the joint solver
  was about to make and reverts to the pre-#2062 unsafe path**, gated
  only by `demote_incoherent_lx_buffers` for producer/consumer
  disagreement.

**What needs to be measured before choosing a shipped policy.**

1. **Distribution of solver status across a production workload sweep.**
   How often does the solver finish `OPTIMAL` vs `FEASIBLE` vs
   `UNKNOWN` under 30 s, 120 s, 600 s time limits? #5 records this.
2. **`best_bound` on `FEASIBLE` exits.** If most `FEASIBLE` exits are
   already close to `objective_value`, longer time limits buy little.
3. **`UNKNOWN` frequency.** This is the failure mode of interest. If
   `UNKNOWN` is rare (< 1% of production compiles), the fallback path
   matters less. If it's not rare, a fallback strategy that preserves
   correctness properties is the priority.

**What a safe shipped policy needs to guarantee.**

- **Producer/consumer core-division coherence.** #3932 lists this as
  the correctness driver for the joint switch. A fallback that
  discards the joint solve and reverts to greedy placement without
  `demote_incoherent_lx_buffers` is unsafe. A fallback that reverts
  and then runs `demote_incoherent_lx_buffers` is safe but gives up
  the joint objective's residency wins.
- **Bounded worst-case compile time.** The policy that produces this
  guarantee is a wall-clock budget, not a solver-internal parameter.
  `max_time_in_seconds` on CP-SAT bounds only the CP-SAT search;
  `_division_map`, `cd_parent_matches`, `cd_parent_relayouts`,
  feature extraction, and `sympy_linearize` are all pre-solve wall
  that is not bounded by `time_limit_seconds`.
- **Feasible-plan preservation.** A `FEASIBLE` status with a coherent
  plan is strictly better than falling back to greedy. That is
  already what the code does; the risk is only around `UNKNOWN`.

**Not a recommendation, but options that §5 evidence would let you
choose between:**

- **Feasible-incumbent-preserving fallback.** Hand the joint solver a
  seed of "everyone at committed division + greedy placement" via
  `AddHint`. On `UNKNOWN`, treat the hinted plan as the fallback
  rather than dropping to placement-only greedy. Correctness: the
  hinted plan is coherent by construction. Cost: the hint machinery
  itself.
- **Two-stage timeout.** A short first solve (say 5 s) to establish an
  incumbent; if `UNKNOWN`, revert to greedy-with-demote; if `FEASIBLE`
  or `OPTIMAL`, either accept immediately or continue solving up to a
  longer budget. Cost: two solve calls in the worst case; one in the
  common case.
- **Optimality-gap early exit.** Accept the current incumbent as soon
  as `(obj - best_bound) / obj ≤ eps`. Cost: none; the incumbent was
  already feasible.

**Do not** pick a specific numeric time-limit recommendation without
sweep evidence. #4018 (30 s) and #4203 (600 s) disagree by 20x; the
right number is a function of what a production graph actually looks
like on the shipped code, not of the tail behavior on any specific
demonstration workload.

**Also: OR-Tools missing.**

- `_make_cpsat_solver` (`allocator.py:2298-2321`) catches
  `ImportError` from `CpSatLayoutSolver.__init__` and returns a
  `GreedyLayoutSolver` factory. So `layout_solver="cpsat"` +
  ortools-absent → placement-only greedy on the non-joint path.
- Under `co_optimizing_lx_planning=True` + ortools-absent,
  `select_allocator` wraps the placement-only greedy factory in
  `ExhaustiveSearchSolver` — a `K^N` DFS with one full placement
  solve per leaf (`exhaustive_search.py:165-181`). **This is the
  s390x default #3932 explicitly flagged as "a likely-unintended,
  expensive default."** Any measurement plan should include an
  s390x-shaped run (small K, moderate N to bound `K^N`).

---

## 8. Disposition of #4139 and #4141

Both PRs remain live on GitHub as of 2026-09-02. No maintainer response
since Todd's reply to Dave on 2026-08-31T22:12:13Z. Head SHAs unchanged
from prior report (2016887 / 1fa1f56).

**#4139 — certified greedy seed for placement-only CP-SAT.**

- **Classification: useful but secondary; do not close without a
  maintainer response, but do not extend into the joint path.**
- **Why.** The certificate proves greedy is objective-optimal for the
  placement-only scalar residency objective. That result stands as
  research evidence for #3932 whether or not the PR merges. The joint
  objective has axes (parallelism, balance, `cost_expr`, plus #4203's
  per-edge relayout costs) the forced-spill lower bound does not
  cover. Trying to lift the proof into `plan_layout_and_core_divisions`
  is a new research task, not a rewrite.
- **Do.** Reference the greedy+committed-division idea from H1 (§6)
  as a *seed for a warm start*, not as a certificate. A seed's plan
  does not need to be provably optimal to be a useful hint.
- **Do not.** Try to prove joint optimality from a placement-only
  lower bound.

**#4141 — lazy OR-Tools loading.**

- **Classification: leave available for the placement-only /
  no-ortools configuration; residual hygiene value only if joint is
  the default.**
- **Why.** If joint CP-SAT becomes the shipped default, OR-Tools is
  needed on the first default compile, and #4141's -1 to -2 s startup
  benefit disappears from the default path. Residual value: cleaner
  module-loading, thread-safe first-load, preserved absent-package
  fallback for s390x — all independent of the switch. Whether that
  residual is worth merging is a maintainer judgment.
- **Do.** Leave the PR Ready; the technical work is done.
- **Do not.** Try to widen its scope to the joint path.

**Neither PR is dead.** Both are held awaiting a maintainer response on
#4139's architectural question. If Dave or another scratchpad
maintainer answers that placement-only CP-SAT is deprecated as a
supported path, both PRs can be closed as research evidence and this
document's §6 is where the work continues.

---

## 9. Relationship to #4117 / #4156 / #3934

**Ownership map as I read it:**

- **#4117 (Compiler frontend performance)** is the umbrella epic.
  Scope covers the whole frontend, not just scratchpad planning.
  Owner not obviously named on the issue itself.
- **#4156 (Frontend baseline suite)** is the measurement lane under
  #4117. **No implementation and no assignees or comments as of
  2026-09-02.** Fully unclaimed.
- **#3934 (Compile-time and scalability bounds for the CP-SAT
  co-optimizing path)** is Track B of the #3932 epic. **Depends on
  #3810 (now merged).** Owner not obviously named.

**Recommendation on how they should fit together.**

- **#3934 becomes the central performance implementation lane for the
  joint path.** Tasks from that issue: "Determine whether SDPA's
  slowness is solver blowup or model-construction overhead", "Design
  and implement a bail-out/timeout policy", "Document the expected
  compile-time envelope". Every one of these depends on §5's
  instrumentation; none should be answered by guess.
- **#4156 becomes the general measurement/regression infrastructure**
  that #3934 (and this document's §5) consume. #4156's spec —
  timing_recorder, machine-readable per-compile record, cold-compile
  protocol, log-log plots — is close to what §5 wants. The joint-path
  fields in §5 fit inside its framework.
- **#4117** stays the epic. #3934 and #4156 should both link back.
- **This document** is the joint-path prioritization insert under
  #4117. It supersedes the earlier `will-continuation-plan.md` for
  what the next engineer works on; the earlier document is still
  correct on restickify, SDSC, and lanes independent of the joint
  switch.

**Do not spawn a new issue for this document's contents.** #3934 is
the right home for the joint-path performance work; extend or link it
rather than fragmenting.

---

## 10. Concrete next steps

Five steps. Each has a specific question, files/functions, output, and a
go/no-go for the next step. Do them in order — later steps depend on
data earlier steps produce.

### Step 1. Add joint-path counters and sub-phase timers (§5)

- **Question.** What does one production-scale joint compile actually
  look like in terms of `n_buffers`, `sum_candidates_over_buffers`,
  `sum_edges`, `n_cp_int_vars`, `n_cp_constraints`, `solve_ms`,
  `status`, `objective_value`, `best_bound`?
- **Files.** `torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py`
  (`_plan_layout_generic`, `_run`, `_extract`, existing DEBUG log at
  line 893), `torch_spyre/_inductor/scratchpad/allocator.py`
  (`CoOptimizingAllocator._solve`, `_division_map`,
  `_cd_parent_matches`, `_cd_parent_relayouts`).
- **Output.** A structured record (JSON) per compile with §5 fields.
  Off by default; enabled by an env var (candidate:
  `TORCH_SPYRE_TIMING=1`, aligned with #4156). Overhead measured on a
  small workload before enabling by default.
- **Stop/go.** Green if a single joint compile on a small workload
  produces a well-formed record and pre-existing tests still pass.
  Red if instrumentation overhead exceeds, say, 5% wall on the small
  workload — dial down what's collected or move to conditional
  instrumentation.

### Step 2. Sweep 4-6 production-shaped workloads across the three time-limit points

- **Question.** On real (not stand-alone) graphs, what is the
  status/objective/bound distribution at 30 s (#4018 value), 120 s
  (upstream `main` value), and 600 s (#4203 value)?
- **Files.** Reuse `analyses/2026-08-pr4117-pre-dxp/harness/frontend_reconnaissance.py`
  as the DXP-intercept harness; add a config axis over
  `CpSatLayoutSolver.__init__`'s `time_limit_seconds`. Workloads:
  flash, MLP, sdpa, transformer_block at production shapes (production
  graph captures, not stand-alone closures — the stand-alone ones
  underrepresent by design).
- **Output.** `data/joint_sweep_2026_09/` with one Step-1 record per
  (workload × time_limit) pair. Three cold samples per point, median
  as primary. Include #4196 in the base to avoid `PYTHONHASHSEED`
  noise.
- **Stop/go.** Green if the record set answers "how often does
  `UNKNOWN` happen at 30 s?" and "is `FEASIBLE` on most compiles
  close to `OPTIMAL`?". Red if the sweep can't be made deterministic
  — investigate whether #4196 landed and whether any other
  hash-seeded state remains.

### Step 3. Read Step 2 results and pick a fallback policy

- **Question.** Given the observed status/`best_bound` distribution,
  which of the three §7 policy options (feasible-incumbent hint /
  two-stage / optimality-gap) removes the pre-#2062 unsafe fallback
  without a compile-time regression?
- **Files.** `torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py`
  (`_run`), `torch_spyre/_inductor/scratchpad/allocator.py`
  (`scratchpad_planning` fallback block).
- **Output.** A design memo (paragraph, not a full PR) picking one
  option, with the specific §5 counters that justify it.
- **Stop/go.** Green if you can name a policy that the data supports.
  Red if the data is ambiguous — that itself is a finding; report to
  #3934 and either widen Step 2's sweep or ship the current 120 s
  limit as a documented worst-case envelope until better evidence
  arrives.

### Step 4. Prototype the fallback policy and re-measure

- **Question.** Does the chosen policy actually preserve joint
  correctness properties while bounding worst-case wall?
- **Files.** Same as Step 3, plus tests. Existing correctness suite
  under `tests/inductor/test_scratchpad_use.py` and the joint-path
  additions from #4018 must still pass; new tests should exercise
  the timeout path directly (a small graph with an artificially low
  time limit).
- **Output.** A branch (not necessarily a PR) with the policy behind
  a config flag, and a repeat of Step 2's sweep with the flag on.
- **Stop/go.** Green if joint tests pass and Step 2's sweep shows the
  expected worst-case bound. Red if a correctness test fails —
  investigate before touching the flag default.

### Step 5. Warm start / seeded incumbent — measure separately from Step 4

- **Question.** Does hinting `AddHint` with everyone-at-committed-
  division + greedy placement measurably reduce `solve_ms` on the
  same production sweep? Does it change `status` distributions?
- **Files.** Same as Step 3.
- **Output.** A/B on the Step 2 sweep with hinting on/off, all other
  config held.
- **Stop/go.** Green if hinting is measurably neutral or better on the
  sweep and the search never converges to a strictly worse objective
  (CP-SAT's hint is advisory but a bug in how we set it up could
  bias search). Red if hinting is neutral — that's a legitimate
  finding; document and move on.

---

## 11. Things NOT to spend time on

- **Do not try to extend #4139's placement-only certificate into
  `plan_layout_and_core_divisions`.** The forced-spill lower bound is
  a placement-only proof; the joint objective has extra axes that no
  amount of case analysis will convert into a joint lower bound.
- **Do not restore #4018's earlier heuristic pruning without
  understanding why it was removed.** The commit history shows
  "Proceed with pruning as default" followed by "Lower time limit and
  undo pruning". If §5 evidence later argues for a *provably safe*
  dominance rule, that's H3, and it has to survive the whole test
  matrix, not just a demonstration graph.
- **Do not add features to #4139 or #4141.** Their scope is settled.
  If a maintainer response arrives, act on it exactly; if not, they
  remain research evidence.
- **Do not re-derive baselines the earlier handoff already covers.**
  Restickify (~138 s at flash-1024x8192), SDSC (~35.7 s / ~4097
  specs), scheduler/codegen — measurements exist under
  `data/frontend_recon_2026_08/`. Rerun on production graphs if
  needed; do not restart the recon on stand-alone closures.
- **Do not put wall-clock assertions in unit tests.** #4117's
  methodology already says deterministic work-count metrics belong in
  tests; wall-clock belongs in regression runs. #4156 formalizes the
  split.
- **Do not treat `SPYRE_LOG_PASSES` as a timing switch.** It gates a
  DEBUG-level IR dump; the elapsed_ms line is gated on
  `spyre.inductor.passes` INFO. #4156 documents this.
- **Do not spawn a new tracking issue for this handoff.** #3934 is
  the right home; extend it.

---

## 12. Open questions / decisions needed from maintainers

Only genuinely unresolved architectural/product questions. Not
implementation questions.

**Q1. Is placement-only CP-SAT (`plan_layout`,
`co_optimizing_lx_planning=False`) a supported configuration after
#4018 lands, or is it deprecated?** This gates the disposition of
#4139 and #4141. Todd asked Dave Grove this question on
2026-08-31T22:12:13Z; no maintainer response yet.

**Q2. Which time limit is the intended default?** #4018 lowers to
30 s; #4203 raises to 600 s. Both are draft. Whichever lands second
overrides the other silently unless the maintainers reconcile
explicitly. §7 argues the number should be evidence-driven and
policy-bounded, not hard-coded — but a default number ships either way
when #4018 or #4203 merges.

**Q3. On `SolveError` under `co_optimizing_lx_planning=True`, is
"placement-only greedy with `demote_incoherent_lx_buffers`" an
acceptable production fallback?** §7 lays out the options; the choice
is a correctness/UX trade-off, not a performance one.

**Q4. Is s390x expected to run joint CP-SAT via `ExhaustiveSearchSolver`
in production, or should the s390x default remain
`co_optimizing_lx_planning=False`?** #3932 flagged the current
behavior as "likely unintended." No visible decision since.

**Q5. If joint CP-SAT is the default, does #3934 become the
performance implementation lane, with #4117 as the umbrella? If so,
who owns #3934?** #3934 has no visible owner as of 2026-09-02.

---

## Evidence appendix

**Repository state at the time of writing.**

- Upstream `main` = `3919da175dc1f42c6be636468dff8e38ef7ef101`
  ("Synchronize docs with implementation (#4195)"), 2026-09-02.
- `torch_spyre/_inductor/config.py:23-25` on upstream `main`:
  `co_optimizing_lx_planning` defaults to `False` via
  `os.environ.get("CO_OPTIMIZING_LX_PLANNING", "0") == "1"`.
- `torch_spyre/_inductor/config.py:180-182` on upstream `main`:
  `layout_solver` defaults to `"cpsat"` via
  `os.environ.get("LAYOUT_SOLVER", "cpsat")`.
- `torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py:643` on
  upstream `main`: `time_limit_seconds: float = 120.0`.

**Live PRs.**

- **#4018** "Enable default cooptimization" — draft, head
  `b55f73f`, updated 2026-09-02T16:05:46Z, author `spectre-ns`.
  Files: `tests/inductor/test_scratchpad_use.py`,
  `tests/inductor/test_work_division.py`,
  `tests/inductor/test_work_division_hint.py`,
  `torch_spyre/_inductor/config.py`,
  `torch_spyre/_inductor/scratchpad/allocator.py`,
  `torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py`,
  `torch_spyre/_inductor/scratchpad/utils.py`,
  `torch_spyre/_inductor/work_division_constraints.py`. Recent
  commit trail includes "Lower time limit and undo pruning".
- **#4203** "Let the CP-SAT solver decide LX relayouts" — draft,
  head `ee418b9`, updated 2026-09-01T18:23:17Z, author `tardieu`.
  Files include `torch_spyre/_inductor/scratchpad/lx_relayout.py`,
  `torch_spyre/_inductor/cost_model.py`, and three dedicated test
  files: `test_solver_relayout_candidates.py`,
  `test_solver_relayout_decision.py`, `test_solver_relayout_e2e.py`.
  Uses `SPYRE_LX_SOLVER_RELAYOUT=0` as kill switch.
- **#3810** "Integrate cost model with ILP solver" — MERGED
  2026-08-30T19:27:57Z. Provides the `cost_expr` parameter reached
  through `plan_layout_and_core_divisions` only.
- **#4196** "Fix a gap in making LX planning independent of
  `PYTHONHASHSEED`" — Ready, updated 2026-09-02T16:17:10Z, author
  `dgrove-oss`. Referenced from Step 2 in §10 because the sweep
  needs determinism.

**Live issues.**

- **#3932** "[Epic] Default enable CP-SAT co-optimizer for
  lx_planning and core division" — Open, updated 2026-08-24.
  Tracks A/B/C/D. Motivates the switch on correctness grounds
  (#2062, 11 value-corruption failures).
- **#3934** "Track B: Compile-time and scalability bounds for the
  cpsat co-optimizing path" — Open, updated 2026-08-21. Depends on
  #3810. Named home for the joint-path performance work; no visible
  owner as of 2026-09-02.
- **#4117** "Compiler frontend performance" — Open, updated
  2026-08-28. Umbrella epic. Contains the methodology section §10
  quotes.
- **#4156** "Frontend baseline suite: structured per-compile timing
  records" — Open, updated 2026-09-02. No comments and no
  implementation yet. Fully unclaimed lane; §5 fields fit here.

**Live PRs left as Ready by Todd.**

- **#4139** "inductor: certified greedy seed for placement-only
  CP-SAT" — Open, Ready, head `2016887`, unchanged since Todd's
  reply on 2026-08-31T22:12:13Z. No maintainer response since.
- **#4141** "inductor: lazily load OR-Tools for CP-SAT fallback" —
  Open, Ready, head `1fa1f56`, unchanged. No reviews.

**Prior Todd analyses cited (still valid on their own terms):**

- `notes/pr4139-pr4141-coopt-transition.md` — the fork this
  document is opening onto.
- `notes/will-continuation-plan.md` — the earlier prioritization,
  now superseded for joint-path work.
- `notes/frontend-roadmap-handoff.md` — the 6-card roadmap. Cards
  1 (this document's §5 supersedes) and Card 2 (restickify — Will's
  lane, unchanged) are relevant.
- `notes/certified-greedy-seed.md`, `notes/pr4139-hardening-report.md`,
  `notes/pr4141-body.md`, `notes/pr4139-body-draft.md` — durable
  research artifacts for #4139/#4141.
- `data/frontend_recon_2026_08/*.json` — small-workload residual
  attribution baseline (not to be re-run on stand-alone closures).
- `data/hybrid_certified_corpus_v2/`,
  `data/capacity_pressure_sweep_v2/` — #4139 evidence.
- `data/lazy_ortools_ab_v2/` — #4141 A/B.

**Sanity check on VERIFIED claims about the solver.** Grep across
upstream `main`, PR #4018 head, and PR #4203 head for
`add_hint|AddHint|SetSolutionHint`: zero occurrences in
`torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py`. The joint
CP-SAT solver receives no warm start today. This is the load-bearing
factual claim behind H1 in §6.
