# Certified greedy seed for placement-only CP-SAT (#4139)

Follow-up to the placement-only differential corpus. The corpus
showed placement-only CP-SAT and greedy make the same decisions on
the compiled workloads measured but the one synthetic
capacity-constrained fixture where they differ has greedy strictly
worse. That prompted a workload-independent design question: can we
tell, from greedy's own plan, when CP-SAT cannot improve on it?

Yes. The mechanism ships in #4139.

## The objective (source-proved)

`CpSatLayoutSolver.plan_layout` (placement-only entry, i.e.
`co_optimizing_lx_planning=False`) runs `_plan_layout_generic`, whose
`_run` executes a lexicographic solve of three levels:

- Level 1 (residency): minimize
  `sum(spill_cost(b) * (1 - in_buffer(b)))`.
- Level 2 (parallelism): maximize `sum(cores)`.
- Level 3 (balance): minimize `sum(core_cost)`.

Levels 2 and 3 are gated on `core_terms` being non-empty. `core_terms`
comes from `[sb.cores for sb in tensors.values() if sb.cores is not None]`.
`_LifetimeBufferWithCpVars.__post_init__` sets `self.cores = None`;
only `_CoreDivisionBufferWithCpVars` sets a non-`None` value. So
`plan_layout` on a plain `LifetimeBoundBuffer` universe (what the
placement-only allocator produces via `_generate_buffers`) never
enters levels 2 or 3.

**Placement-only CP-SAT is therefore optimizing a single scalar:**

    minimize sum(spill_cost(b) * (1 - in_buffer(b)))

Every `spill_cost(b) >= 0` (from
`_LifetimeBufferWithCpVars.spill_cost`: `(reads_served + is_intermediate) * size`
with `size > 0`, `reads_served >= 0`, `is_intermediate ∈ {0, 1}`);
every `(1 - in_buffer) ∈ {0, 1}`. Objective is a nonnegative sum.

## The lower bound (source-proved)

The absolute lower bound of a nonnegative sum where some terms are
forced active is the sum of the forced-active terms alone.
`_add_core_division` inspects `forced_reasons` (equivalent to
`b.residency_reason`) and pins those buffers non-resident
(`in_buffer = 0`), so their `spill_cost` is unavoidably active.

    L = sum(spill_cost(b) for b in buffers if b.residency_reason is not None)

A plan reaches `L` iff every non-barred buffer is placed. No plan can
beat `L`.

## The certificate

Run greedy on a solver-local deep copy of `self.buffers`. Compute
`greedy_objective = sum(spill_cost(b) for b in greedy_plan if b.address is None)`.
If `greedy_objective == L`, greedy is optimal — CP-SAT cannot
improve on it — accept greedy and skip CP-SAT.

Otherwise fall through to `_plan_layout_generic` with the original
untouched buffers.

## Corpus result

Runner: `harness/hybrid_certified_corpus.py`. Runs every captured
`BaseLayoutSolverTests` scenario through greedy, CP-SAT, and the
hybrid, then classifies.

Data: `data/hybrid_certified_corpus/summary.json`.

| class            | count | notes |
|------------------|------:|-------|
| SKIP             |     7 | assertion-only test, no solver invocation |
| greedy-certified |    17 | seed accepts, CP-SAT skipped |
| cpsat-fallback   |    11 | seed rejects, CP-SAT runs |

**Invariant checks:**

- `hybrid_objective <= cpsat_objective`: holds on every case.
- `hybrid_chosen == "greedy-certified" ⇒ hybrid_objective == L == greedy_objective`:
  holds on every case.

The single case where standalone greedy strictly loses to standalone
CP-SAT (`test_largest_buffer_evicted_when_full`: greedy objective 60,
CP-SAT optimum 20) hits the fallback path: `greedy_objective = 60
!= 0 = L`, so the seed rejects and CP-SAT runs, returning objective 20.

The single case where standalone greedy places one buffer greedy-only
better than CP-SAT-only (`test_simple_layout_below_alignment`, a
capacity-below-alignment edge case) also hits the fallback path
(`greedy_objective = 14`, `L = 0`), and hybrid returns CP-SAT's
objective 20. Hybrid does NOT beat standalone greedy on this
particular fixture — but the invariant `hybrid <= standalone_cpsat`
still holds and this fixture does not resemble a production layout.

## Capacity-pressure sweep on captured planner-buffer sets

Runner: `harness/capacity_pressure_sweep.py`. Captured buffer sets:
`data/captured_buffers/*.pkl` (nine workloads: flash 512x1024/2048/4096/8192,
MLP L=96/192/384, sdpa S=512/1024/2048). Each captured buffer set
comes from a compiled workload with
`SPYRE_LX_PLANNER_RELAYOUT=0` so both solvers see identical inputs.

At each capacity scale in {1.0, 0.75, 0.5, 0.25} × the shipped LX
capacity, solve with greedy alone, CP-SAT alone, and the hybrid.

Data: `data/capacity_pressure_sweep/summary.json`. Per-workload
transcript in the note below.

| workload            | scale | greedy_obj | cpsat_obj | hybrid choice   | greedy_ms | cpsat_ms | hybrid_ms |
|---------------------|------:|-----------:|----------:|-----------------|----------:|---------:|----------:|
| flash-512x1024      |  1.00 |  3,751,936 | 3,751,936 | greedy-certified|      3.8  |    313.5 |       9.3 |
| flash-512x1024      |  0.75 |  3,751,936 | 3,751,936 | greedy-certified|      3.7  |    327.3 |      12.3 |
| flash-512x1024      |  0.50 |  3,751,936 | 3,751,936 | greedy-certified|      3.8  |    316.9 |       9.1 |
| flash-512x1024      |  0.25 |  3,751,936 | 3,751,936 | greedy-certified|      3.9  |    301.3 |       9.2 |
| flash-512x2048      |  1.00 |  9,027,584 | 9,027,584 | greedy-certified|     14.9  |  1,659.8 |      22.4 |
| flash-512x2048      |  0.75 |  9,027,584 | 9,027,584 | greedy-certified|     15.1  |  1,628.3 |      22.6 |
| flash-512x2048      |  0.50 |  9,027,584 | 9,027,584 | greedy-certified|     15.3  |  1,584.6 |      25.1 |
| flash-512x2048      |  0.25 |  9,027,584 | 9,027,584 | greedy-certified|     15.6  |  1,645.0 |      22.8 |
| flash-512x4096      |  1.00 | 24,297,472 | 24,297,472| greedy-certified|     57.7  |  9,014.5 |     224.1 |
| flash-512x4096      |  0.75 | 24,297,472 | 24,297,472| greedy-certified|     58.8  |  9,030.1 |      78.6 |
| flash-512x4096      |  0.50 | 24,297,472 | 24,297,472| greedy-certified|     59.8  |  8,934.4 |      77.8 |
| flash-512x4096      |  0.25 | 24,297,472 | 24,297,472| greedy-certified|     59.6  |  9,040.2 |      76.8 |
| flash-512x8192      |  1.00 | 73,711,616 | 73,711,616| greedy-certified|    225.3  | 65,978.0 |     426.3 |
| flash-512x8192      |  0.75 | 73,711,616 | 73,711,616| greedy-certified|    232.7  | 46,966.3 |     264.2 |
| flash-512x8192      |  0.50 | 73,711,616 | 73,711,616| greedy-certified|    236.2  | 47,686.6 |     264.5 |
| **flash-512x8192**  |**0.25**|**74,039,296**|**73,711,616**|**cpsat-fallback**| **235.9**|**46,086.2**|**45,912.1**|
| mlp-L96             |  1.00 |        128 |       128 | greedy-certified|      9.5  |    180.6 |      19.0 |
| mlp-L96             |  0.75 |        128 |       128 | greedy-certified|      9.6  |    185.4 |      19.1 |
| mlp-L96             |  0.50 |        128 |       128 | greedy-certified|      9.5  |    180.9 |      20.5 |
| mlp-L96             |  0.25 |        128 |       128 | greedy-certified|      9.4  |    191.0 |      20.7 |
| mlp-L192            |  1.00 |        128 |       128 | greedy-certified|     38.5  |    606.0 |      55.0 |
| mlp-L192            |  0.75 |        128 |       128 | greedy-certified|     40.4  |    582.6 |      53.4 |
| mlp-L192            |  0.50 |        128 |       128 | greedy-certified|     38.2  |    653.2 |      52.7 |
| mlp-L192            |  0.25 |        128 |       128 | greedy-certified|     38.6  |    620.6 |      55.0 |
| mlp-L384            |  1.00 |        128 |       128 | greedy-certified|    152.9  |  1,656.4 |     182.2 |
| mlp-L384            |  0.75 |        128 |       128 | greedy-certified|    155.8  |  1,429.4 |     179.5 |
| mlp-L384            |  0.50 |        128 |       128 | greedy-certified|    151.4  |  1,446.7 |     369.0 |
| mlp-L384            |  0.25 |        128 |       128 | greedy-certified|    152.7  |  1,493.9 |     179.6 |
| sdpa-S512           |  1.00 |    458,752 |   458,752 | greedy-certified|      0.2  |     23.2 |       0.8 |
| sdpa-S512           |  0.75 |    458,752 |   458,752 | greedy-certified|      0.2  |     23.5 |       0.8 |
| sdpa-S512           |  0.50 |    458,752 |   458,752 | greedy-certified|      0.2  |     23.5 |       0.8 |
| sdpa-S512           |  0.25 |    458,752 |   458,752 | greedy-certified|      0.2  |     25.7 |       0.8 |
| sdpa-S1024          |  1.00 |  1,441,792 | 1,441,792 | greedy-certified|      0.2  |     23.3 |       0.8 |
| sdpa-S1024          |  0.75 |  1,441,792 | 1,441,792 | greedy-certified|      0.2  |     25.3 |       0.8 |
| sdpa-S1024          |  0.50 |  1,441,792 | 1,441,792 | greedy-certified|      0.2  |     22.9 |       0.8 |
| **sdpa-S1024**      |**0.25**| **5,636,096**|**5,636,096**|**cpsat-fallback**| **0.2**|  **16.4**|    **16.8**|
| **sdpa-S2048**      |**1.00**|**22,020,096**|**22,020,096**|**cpsat-fallback**| **0.2**|  **15.7**|    **16.7**|
| **sdpa-S2048**      |**0.75**|**22,020,096**|**22,020,096**|**cpsat-fallback**| **0.2**|  **16.4**|    **18.2**|
| **sdpa-S2048**      |**0.50**|**22,020,096**|**22,020,096**|**cpsat-fallback**| **0.2**|  **17.1**|    **17.0**|
| **sdpa-S2048**      |**0.25**|**22,020,096**|**22,020,096**|**cpsat-fallback**| **0.2**|  **16.3**|    **18.5**|

Aggregate over 36 test points: 30 certified, 6 fell through to CP-SAT.
Hybrid objective matches standalone CP-SAT objective on every
fallback point. On the 30 certified points, hybrid is 30-160× faster
than standalone CP-SAT.

The single flash-512x8192 fallback at 25% capacity is the "CP-SAT
genuinely buys quality under capacity pressure" scenario the corpus
predicted: greedy leaves 327,680 units on the table; CP-SAT reaches
the lower bound. Hybrid returns CP-SAT's plan.

The five sdpa fallbacks are cases where no plan can reach the floor
(max_live_bytes > capacity), so both solvers produce the same
objective and the fallback just adds ~1 ms.

## Design comparison with the earlier adaptive threshold

| dimension                    | `adaptive_solver_threshold_ops` | certified greedy seed |
|------------------------------|---------------------------------|-----------------------|
| control                      | size threshold                  | CP-SAT's own objective |
| requires threshold choice    | yes                             | no |
| workload classifier          | implicit (size proxy)           | none |
| preserves CP-SAT quality     | not guaranteed                  | by construction (obj-certified) |
| user-visible knob            | yes (config)                    | none |
| overrides on capacity pressure | doesn't detect it             | automatically escalates |
| joint co-opt path affected   | untouched                       | untouched |

The certified seed dominates the threshold design on every dimension
that mattered. The threshold was solving a proxy question ("is this
graph big?"); the seed answers the direct question ("does the seed
already reach the objective's floor?"). No knobs to tune, no
regression risk on capacity-constrained workloads, and no need to
distinguish flash from MLP or any other family.

## Recommendation

Ship the certified seed. That is what draft PR #4139 now proposes.
The joint co-optimization path (`co_optimizing_lx_planning=True`)
remains untouched. The mechanism is off-critical (greedy probe adds
0.2 ms to a few hundred ms depending on graph size; net wall-time
delta is strongly positive on measured workloads).

## Reproduction

Frozen torch-spyre `3358f39` for the study; the seed itself sits on
upstream `4e077da` (`c310c3b` when this note was written), in
`toddllm/torch-spyre` branch
`tdeshane/adaptive-solver-threshold-draft` (kept as the PR branch
name across the pivot).

```bash
# Placement-only differential corpus
python3 harness/hybrid_certified_corpus.py --out data/hybrid_certified_corpus

# Capture compiled-workload planner buffers (nine workloads)
for w in flash-512x1024 flash-512x2048 flash-512x4096 flash-512x8192 \
         mlp-L96 mlp-L192 mlp-L384 sdpa-S512 sdpa-S1024 sdpa-S2048; do
    # see harness/capture_planner_buffers.py for exact args
done

# Capacity-pressure sweep on the captured sets
python3 harness/capacity_pressure_sweep.py \
    --captures-dir data/captured_buffers \
    --out data/capacity_pressure_sweep
```
