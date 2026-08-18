# Findings — PR #3806 front-end compiler timing

Cold-compile scaling of `test_flash` from PR #3806. Nine
`(Lq, Lk)` points, three samples per point except the largest which
is preliminary at `n=1`. All timings are medians in seconds unless
otherwise noted. Detailed tables and plots are cross-referenced
throughout.

## 1. Compile-time decomposition

Every measured stage lives inside `compile_fx_wrapper`. That total
partitions exhaustively into four buckets summing to it, up to a
negligible `async_compile_wait`:

- **`dxp_standalone`** — external backend compiler subprocess.
- **`sdsc_prep`** — torch-side SDSC/backend-input preparation, i.e.
  `sdsc_total − dxp_standalone`. Contains `sdsc_bundle_gen` and
  kernel-provenance bookkeeping.
- **Spyre pass pipelines** — the six Spyre custom pass pipelines.
- **`unattributed_compile_fx`** — the remaining time inside
  `compile_fx_wrapper` that this instrumentation does not yet
  bracket individually. Contains AOTAutograd joint-graph
  decomposition, upstream Inductor lowering
  (`GraphLowering.run`) and codegen (`GraphLowering.compile_to_fn`),
  upstream fusion + scheduling, `SpyreKernel` per-kernel codegen,
  and Spyre wrapper codegen. Does **not** contain Dynamo capture,
  which runs before `compile_fx` receives the FX graph.

At the baseline point (Lq=512, Lk=1024, 8 inner bodies, 236 FX nodes
at compile_fx entry, 273 SDSC specs), one cold compile takes:

| bucket | seconds | % of `compile_fx` |
|---|---:|---:|
| `compile_fx_wrapper` | 99.4 | 100 % |
| `dxp_standalone` | 79.6 | 80.1 % |
| `sdsc_prep` | 1.7 | 1.8 % |
| Spyre pass pipelines | 5.3 | 5.3 % |
| `unattributed_compile_fx` | 12.5 | 12.5 % |

At every workload point measured, external `dxp_standalone` accounts
for 73–96 % of `compile_fx_wrapper`. The Spyre pass pipelines account
for 5–5.5 % across the whole range. `unattributed_compile_fx` starts
at ~13 % at baseline and shrinks in relative share as tile count grows
because `dxp_standalone` and the Spyre pipelines both grow much
faster than it does. See
[`tables/table-a-workload.md`](tables/table-a-workload.md) and
[`../plots/compile-stages.png`](../plots/compile-stages.png).

## 2. Time to first front-end pass

From raw event timestamps
([`tables/time-to-first-pass.md`](tables/time-to-first-pass.md)),
measured relative to the start of `first_call_wall`:

| Lq | Lk | t → `compile_fx` (s) | t → first Spyre pipeline (s) | t → pre-scheduling (s) |
|---:|---:|---:|---:|---:|
| 512 | 1024 | 0.41 | 9.59 | 10.51 |
| 512 | 8192 | 1.25 | 15.69 | 20.86 |
| 1024 | 8192 | 1.90 | 15.42 | 25.58 |

The first Spyre custom pipeline (`CustomPrePasses`) begins about
9.6 s after the compiled call starts at baseline;
`CustomPreSchedulingPasses` — the pipeline that carries most of the
Spyre pass time — begins about 10.5 s in. The two boundaries are
distinct and about a second apart at baseline. The gap between
`t → compile_fx` (≈ 0.4 s) and `t → first Spyre pipeline` (≈ 9.6 s)
is upstream Inductor work: AOTAutograd joint-graph decomposition,
upstream FX passes, `GraphLowering` construction. It grows to
~15–16 s at the largest workloads.

## 3. Per-pass scaling in `CustomPreSchedulingPasses`

The pre-scheduling pipeline runs 20 ordered passes over
`graph.operations` and dominates measured Spyre pass time. Each pass
records `input_operations` at entry; the log-log slope of pass time
against that size across the measured range describes how the pass
scales.

Endpoint-to-endpoint slope, 1.0 ≈ linear, 2.0 ≈ quadratic
(from [`tables/table-b-passes.md`](tables/table-b-passes.md);
plot [`../plots/pass-scaling.png`](../plots/pass-scaling.png)):

| pass | slope | interpretation |
|---|---:|---|
| `dedup_and_promote_constants` | 1.96 | near-quadratic |
| `optimize_restickify_locations` | 1.46 | strongly superlinear |
| `_maybe_scratchpad_planning` | 1.45 | strongly superlinear |
| `propagate_spyre_tensor_layouts` | 0.87 | slightly sublinear |
| `span_reduction` | 1.00 | linear |
| `_distribute_work` | 1.02 | linear |
| `enforce_indirect_access_layout` | 1.00 | linear |
| `deadcode_elimination` | 0.98 | linear |
| `validate_ops` | 1.01 | linear |
| `split_multi_ops` | 1.13 | approximately linear |

Two of the top three passes are strongly superlinear;
`dedup_and_promote_constants` is close to quadratic in `input_operations`.

## 4. Cost model for `dedup_and_promote_constants`

The pass in `torch_spyre/_inductor/dedup_constants.py` groups
`SpyreConstantFallback` ops by value/dtype/device, then per duplicate:

```python
for dup in group[1:]:
    _redirect_consumers(operations, dup, canonical)  # walks all operations
    _drop_constant(operations, dup, canonical)       # operations.remove(dup)
```

`_redirect_consumers` iterates every operation and calls
`op.get_read_writes()`. `_drop_constant` calls
`operations.remove(dup)`, which is O(|operations|) on a Python list.
Both are executed once per duplicate. Source inspection therefore
predicts work proportional to `|operations| × |duplicates|`.

Directly measured (from [`tables/dedup-mechanism.md`](tables/dedup-mechanism.md)):

| Lq | Lk | input_ops | duplicates | ops × dups | measured (ms) | ops × dups × baseline | t × baseline |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 256 | 1024 | 118 | 8 | 944 | 193 | 0.21 | 0.22 |
| 512 | 512 | 140 | 8 | 1,120 | 230 | 0.25 | 0.26 |
| 512 | 1024 | 276 | 16 | 4,416 | 870 | 1.00 | 1.00 |
| 512 | 2048 | 548 | 32 | 17,536 | 3,486 | 3.97 | 4.01 |
| 512 | 4096 | 1,092 | 64 | 69,888 | 14,110 | 15.83 | 16.23 |
| 512 | 8192 | 2,180 | 128 | 279,040 | 54,646 | 63.19 | 62.84 |
| 1024 | 1024 | 548 | 32 | 17,536 | 3,464 | 3.97 | 3.98 |
| 1024 | 8192 | 4,356 | 256 | 1,115,136 | 225,474 | 252.52 | 259.27 |
| 2048 | 1024 | 1,092 | 64 | 69,888 | 14,106 | 15.83 | 16.22 |

The `ops × dups × baseline` and `t × baseline` columns agree to
within a few percent across the entire range. A single-parameter
linear fit through the origin ([`../plots/dedup-model-fit.png`](../plots/dedup-model-fit.png))
gives:

`t ≈ 200.9 µs × (|operations| × |duplicates|)`

For this workload, `|duplicates|` scales approximately proportionally
with `|operations|`, which is why the pass appears near-quadratic in
program size. The underlying cost model is the product, not a
universal `O(n²)` in graph size.

## 5. Backend scaling per SDSC spec

`sdsc_bundle_gen` emits a bundle of `n_specs` op specs to
`dxp_standalone`. If the external backend were linear in the size
of the bundle it receives, `dxp / n_specs` would be constant. It is
not.

From [`tables/backend-per-spec.md`](tables/backend-per-spec.md)
and [`../plots/backend-per-spec.png`](../plots/backend-per-spec.png):

| Lq | Lk | n_specs | `sdsc_bundle_gen`/spec (ms) | `dxp_standalone`/spec (ms) |
|---:|---:|---:|---:|---:|
| 256 | 1024 | 115 | 5.4 | 271 |
| 512 | 1024 | 273 | 6.0 | 292 |
| 512 | 4096 | 1,089 | 5.6 | 457 |
| 512 | 8192 | 2,177 | 5.7 | 1,010 |
| 1024 | 8192 | 4,353 | 5.8 | 3,079 |

Torch-side bundle generation cost is approximately constant per
spec: SDSC bundle generation is linear in `n_specs`. External
backend cost per spec grows about 11× across the measured range,
consistent with strongly superlinear scaling of the backend in the
size of the bundle it receives. The external backend is outside the
scope of this study and is reported here only for context.

## 6. What the `unattributed_compile_fx` bucket does and does not say

The bucket grows more slowly than either the backend or the Spyre
pass pipelines over the measured range
([`tables/residual-decomposition.md`](tables/residual-decomposition.md)):
5.4× at the largest measured workload vs 168× for `dxp_standalone`
and 87× for the Spyre pass pipelines. That is a statement about the
aggregate; the mixture inside — AOTAutograd, upstream Inductor
lowering, upstream fusion + scheduling, per-kernel codegen, wrapper
codegen — cannot be characterized individually until the additional
class-level wraps in `patches/extra_timers.py` are enabled. The
validation-run infrastructure to make that measurement is in place
(see `patches/run_validation.sh` and `patches/analyze_validation.py`).

## 7. Limitations

- Three samples per point support median comparisons but do not
  support tight asymptotic complexity claims.
- The largest workload point (Lq=1024, Lk=8192) currently has one
  committed sample. It is not given equal statistical weight in
  fitted slopes; the endpoint slopes in §3 use the fully-sampled
  Lq=512, Lk=8192 point as the upper endpoint.
- `SENCORES=32` throughout. `_distribute_work` and
  `_maybe_scratchpad_planning` scale with core count; other
  `SENCORES` values are not measured here.
- `LX_PLANNING=1` by default. Under `LX_PLANNING=0`,
  `_maybe_scratchpad_planning` becomes a no-op and its share of the
  Spyre pipeline evaporates. This does not change the dominant
  conclusions but does change the per-pass table.

## 8. Next investigations

Ranked by evidence:

1. Rework `dedup_and_promote_constants` so its cost is no longer
   `|operations| × |duplicates|`. The source and the fit both
   already identify the mechanism. Two candidate changes: replace
   `operations.remove(dup)` with a rebuild after the dedup loop, and
   use the graph's `name_to_users` index to skip
   `_redirect_consumers` when the duplicate has no consumers.
2. Instrument `optimize_restickify_locations` and
   `_maybe_scratchpad_planning`. Both show endpoint slopes near 1.45
   and together dominate the pre-scheduling pipeline's time. Their
   source-level cost models are not yet derived.
3. Enable `extra_timers.py` and take validation runs at baseline
   and one medium point to decompose `unattributed_compile_fx`
   ([`analyze_validation.py`](../patches/analyze_validation.py)
   emits [`tables/unattributed-decomposition.md`](tables/unattributed-decomposition.md)
   from those). Rerun the full sweep only if the decomposition
   materially changes interpretation.
4. Communicate the backend-per-spec growth (§5) to whoever owns
   `dxp_standalone`. Outside this study's scope but the dominant
   contributor to absolute compile time at scale.
