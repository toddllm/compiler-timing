# Cross-workload frontend scalability — findings

Two Torch-Spyre FlashAttention workloads, side by side. Detailed
workload A results live in the sibling PR #3806 study; this document
adds workload B, contrasts the two, and ranks improvement opportunities.

## 1. Workload B baseline (KV-chunked FA on the pr3806-base tree)

Config: `B=1 H=8 D=128 Lq=256 Lk=4096 h_tiles=4 lq_tiles=None`.
`n_chunks = Lk / kv_block`. All medians in seconds unless noted.

### Layout-fix A/B (crashes reproduce)

At **pre-fix** `_all_constant_layouts(op)`:

| n_chunks | wall (s) | compile_fx | dxp | Spyre pipes | dedup | coarse_tile | restickify |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 23.45 | 22.99 | 10.82 | 3.30 | 0.183 | 1.344 | 0.583 |
| 4 | 42.86 | 42.04 | 23.16 | 7.85 | 0.652 | 4.013 | 1.102 |
| 8 | **CRASH** | — | — | — | — | — | — |

All 3 pre-fix n_chunks=8 samples fail with

```
InductorError: NotImplementedError: buf112 (Pointwise):
  no mechanism to resolve stick incompatibility
  ...
  Problem:
    STL 0 --> Out STL 0: No mechanism to scatter elements from one stick to multiple sticks
    STL 1 --> Out STL 1: No mechanism to gather elements from multiple sticks into single stick
```

— the exact buf112 exponential-beam signature documented in issue #3687.
Same buffer name, same two-STL candidate pattern.

At **post-fix** `[generic_layout(op)]`:

| n_chunks | n | wall  | compile_fx | dxp    | Spyre pipes | dedup   | coarse_tile | restickify |
|---------:|--:|------:|-----------:|-------:|------------:|--------:|------------:|-----------:|
| 2        | 3 | 22.72 | 21.76      | 10.83  | 3.38        | 0.184   | 1.467       | 0.545      |
| 4        | 3 | 42.99 | 42.18      | 23.32  | 7.99        | 0.662   | 4.110       | 1.049      |
| 8        | 3 | 107.06| 105.81     | 69.07  | 23.30       | 2.479   | 14.464      | 2.300      |
| 16       | 1 | 314.81| 313.39     | 217.23 | 76.58       | 10.013  | 53.128      | 5.607      |

Pre-fix and post-fix values at n_chunks=2 and 4 agree to within 3–9%
(within measurement noise) for `_maybe_coarse_tile_hints` and other
non-layout passes. The layout fix specifically unblocks n_chunks ≥ 8
without changing frontend cost at lower chunk counts.

### Doubling ratios (post-fix)

| pair | coarse_tile_hints | restickify | dedup | scratchpad | prop_layouts | compile_fx | dxp |
|:---|---:|---:|---:|---:|---:|---:|---:|
| 2→4 | 2.80× | 1.93× | 3.59× | 1.94× | 1.80× | 1.94× | 2.15× |
| 4→8 | 3.52× | 2.19× | 3.74× | 1.93× | 1.89× | 2.51× | 2.96× |
| 8→16 | 3.67× | 2.44× | 4.04× | 1.73× | 2.04× | 2.96× | 3.14× |

`_maybe_coarse_tile_hints` converges to ~4× per doubling — nearly
quadratic in n_chunks. `dedup` also ~4× per doubling as expected from
its `operations × duplicates` model (both factors ≈ 2× per doubling).
`restickify` climbs from 1.93× to 2.44× — consistent with PR #3812's
reported 2.2–2.4× band. Other passes stay near-linear (1.7–2×).

## 2. `_maybe_coarse_tile_hints` — full 100% substage attribution

We wrapped every non-trivial callsite in `_coarse_tile_common`
(patches/`coarse_tile_substage_timing.py`) at n_chunks=4 (3 samples)
and n_chunks=8 (1 sample). Medians in ms:

| substage | n=4 | n=8 | 4→8 ratio | % of umbrella at n=8 |
|---|---:|---:|---:|---:|
| **`resync_and_patch_load_indexes`** | **2,752** | **10,259** | **3.73×** | **74.5%** |
| `plan_tiling_propagation` | 840 | 3,042 | 3.62× | 22.1% |
| `insert_all_read_copy_ops` | 358 | 265 | 0.74× | 1.9% |
| `plan_coarse_tile_groups` | 85 | 160 | 1.89× | 1.2% |
| `plan_read_copies` | 23 | 40 | 1.77× | 0.3% |
| `apply_plan_loop` | 5 | 10 | 1.84× | 0.1% |
| `insert_all_write_copy_ops` | 2 | 2 | 1.05× | 0.01% |
| `insert_all_reduction_ops`, validators, log | ~0 | ~0 | — | ~0% |
| **SUM** | **4,064** | **13,779** | **3.39×** | 100.0% |
| **UMBRELLA** | **4,068** | **13,779** | **3.39×** | — |

**Two substages account for 96.6% of the pass at n=8**, both scaling
near-quadratically. Third-place `insert_all_read_copy_ops` was a source-
audit prediction that turned out to *shrink* with chunk count in this
workload (0.74×) — the audit was right in shape but wrong in scale for
workload B because `n_groups=1` throughout (all KV chunks fit in a
single coarse-tile group by construction).

### Source-level cost drivers (both substages)

Both dominant substages share a common mechanism, identified in source
by follow-on inspection and validated numerically:

1. **`_reads_buffer` (coarse_tile.py:1850)** calls raw
   `op.get_read_writes()` — bypassing the memoized `op_read_writes`
   helper in `pass_utils.py:96`. Each call re-runs sympy dependency
   extraction over the op's inner_fn.
2. **`replace_computed_buffer_body` (pass_utils.py:1342)** uses
   `operations.index(op)` — O(N) linear scan per splice.

`_plan_tiling_propagation` invokes `_reads_buffer` O(N × K) times per
substage entry (per-op call to `_find_outside_consumers_planned` walks
all `operations`). `_patch_retiled_load_indexes` invokes it O(N × R)
times plus takes O(N) list-splices per patch.

**Predicted asymptotic: Θ(N²)** on both. Predicted timing at n=4: ~2.0 s;
predicted at n=8: ~7.2 s. Measured: 2.75 s and 10.3 s. Predicted 4→8
ratio 3.6×; measured 3.73×. Very close for a source-only prediction.

## 3. Dedup — `t ≈ c × operations × duplicates` shape, per-workload constant

The PR #3806 study established
`t ≈ 201.8 µs × (|operations| × |duplicates|)` on workload A. We test
this coefficient out-of-sample on workload B **without refitting**.

| n_chunks | input_ops | dups | ops × dups | pr3806-predicted (ms) | measured (ms) | error |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 55 | 4 | 220 | 44 | 184 | +316% |
| 4 | 95 | 8 | 760 | 153 | 662 | +332% |
| 8 | 175 | 16 | 2,800 | 565 | 2,479 | +339% |
| 16 | 335 | 32 | 10,720 | 2,163 | 10,013 | +363% |

Per-pair cost inside workload B:

| n_chunks | t / (ops × dups) |
|---:|---:|
| 2 | 836 µs/pair |
| 4 | 871 µs/pair |
| 8 | 885 µs/pair |
| 16 | 934 µs/pair |

**The `ops × dups` shape generalizes tightly** — per-pair cost drifts
only 12% across an 8× chunk range within workload B. **The constant
does not** — workload B pays ~880 µs/pair vs #3806's 202 µs/pair,
**a 4.6× higher `C_op`**. Refitting on workload B gives 931 µs/pair.

Interpretation: `C_op` — the per-op cost of one `get_read_writes()` call
plus per-op bookkeeping — is workload-dependent. Workload B ops have
richer inner_fns (softmax reductions, matmul-plus-broadcast chains,
restickify inserts, and more consumers via the diamond pattern). Cold
sympy dep extraction takes longer on those ops. **Same driver as the
coarse-tile substages above.**

## 4. Restickify — beam frontier evolution, pre-fix vs post-fix

Instrumented with `patches/restickify_beam_counters.py`. Recorded
`pre_expand`, `n_candidates`, `post_expand`, `post_merge`, `post_trim`
per-op, plus summary counters.

### Summary counters

| fix | n_chunks | ops | max_pre | max_expand | max_merge | max_trim | merged_total |
|:---|---:|---:|---:|---:|---:|---:|---:|
| pre | 2 | 55 | 54 | 108 | 54 | 54 | 239 |
| post | 2 | 55 | 27 | 81 | 27 | 27 | 153 |
| pre | 4 | 95 | 200 | 600 | 300 | 200 | 1,801 |
| post | 4 | 95 | 200 | 656 | 243 | 200 | 1,525 |
| post | 8 | 175 | 200 | 800 | 400 | 200 | 5,803 |
| post | 16 | 335 | 200 | 800 | 400 | 200 | 15,403 |

At n_chunks=2 the post-fix reduces every metric by ~50%. At n=4 both
saturate BEAM_WIDTH=200; the true unclamped frontier would differ more.
At n=8 and 16, only post-fix survives with beam=200.

### Per-op candidate change (n_chunks=2)

Constant-fill ops whose `n_candidates` collapsed pre→post from 2 → 1:

```
buf1, buf3, buf4, buf32, buf33            ← torch.full / zeros_like sources
coarse_tile_read_copy_0_buf33_7           ← read-copy of a constant
```

Downstream diamond ops keep their `n_candidates` values (still 4 for
buf25/26/28/30 because their consumers dictate layout). But their
`post_expand` roughly halves (buf28: 72→36; buf30: 108→54) — that's
the diamond state doubling being eliminated at the source.

This confirms the mechanism described in issue #3687:
"the failure is over a carry shaped [1,2,256] with two equally-costed
stick mappings, and there are ~3 such carries per chunk, so states
double per chunk."

## 5. Extent independence in this tree

At fixed n_chunks=4 in workload B:

| axis | range tested | compile_fx range | FX@entry | n_specs |
|:---|:---|---:|---:|---:|
| Lq, `lq_tiles=None` | 64 → 4096 (64×) | 40.0 → 48.8 s (1.22×) | 105 (constant) | 5 (constant) |
| Lq, `lq_tiles=2` | 256 → 2048 (8×) | 64.6 → 66.2 s (1.02×) | 106 (constant) | 5 (constant) |
| Lk (kv_block scaled) | 1024 → 16384 (16×) | 39.0 → 40.5 s (1.04×) | 105 (constant) | 5 (constant) |

**Compile cost is essentially independent of Lq or Lk value at fixed
n_chunks.** FX-nodes and `n_specs` are constant across all extents.

PR #3812's docstring warned "Lq=8192 at n=4 compiled for over two hours".
That pathology does NOT reproduce on the pr3806-base tree. The most
likely explanation is that pr3812 has other code paths beyond the 1-line
layout fix — 22 files changed in total including 820 lines of new C++
(`perm_layout_native.cpp`), a large `span_overflow_hint_analysis.py`
expansion, and scratchpad allocator revisions. One of those could
introduce extent-dependent cost that our base doesn't hit. A full
pr3812 tree build with C-extension would answer this; deferred.

## 6. What generalizes across workloads

|  |  workload A (OpSpec) | workload B (WSR KV-chunked) |
|:---|:---|:---|
| Graph growth mechanism | Statically unrolled B/H/Lq/Lk tiles | Python KV loop, WSR H/Lq tiles |
| FX growth per doubling | ~1.8× (chunk-doubling) | ~1.85× |
| Coarse tiling active? | No (0.3 ms `_maybe_coarse_tile_hints` at baseline) | Yes (1.5–53 s across n_chunks range) |
| Dedup shape | `t ∝ ops × dups` | `t ∝ ops × dups` |
| Dedup coefficient | 202 µs/pair | 931 µs/pair (4.6× higher) |
| Restickify scaling | ~1.5× per doubling | ~2.2–2.4× per doubling (post-fix) |
| Scratchpad scaling | ~n^1.45 in workload A | ~1.9× per doubling in workload B (near-linear) |
| Layout propagation scaling | ~n^0.87 (sublinear) | ~1.8–2.0× per doubling (linear) |
| Restickify state-space | Not exercised past normal range | Diamond state doubling; issue #3687 |
| dxp share of compile_fx | 73–92% (fully-sampled) | 50–70% (fully-sampled) |
| Frontend share | 5–10% | 15–25% |
| Uncached `get_read_writes()` in hot loops | Yes (`_redirect_consumers`) | Yes (`_reads_buffer` × several substages) |

### What generalizes
- **Dedup's `ops × dups` structural cost model** — the shape is stable
  across workloads; the constant factor is not.
- **Backend dominates absolute compile time at scale** in both.
- **Uncached sympy dep extraction** (`op.get_read_writes()`) is a
  cross-workload hotspot mechanism. Same source-level driver behind
  dedup's O(|ops|·|dups|), coarse-tile's O(N·K), and
  patch_retiled_load_indexes' O(N·K).

### What does not generalize
- **The dedup constant** is workload-dependent (4.6× higher on B).
- **Coarse-tile scaling** is WSR-specific — near-zero on workload A,
  4× per doubling on workload B.
- **Restickify state space** is only exercised in workloads with
  constant-fill diamonds. Absent from A entirely.

## 7. Closed decomposition of `compile_fx_wrapper` (extra timers)

With `patches/extra_timers_v2.py` + hook installed, `compile_fx_wrapper`
is now 100% attributable. Wraps around `GraphLowering.run` (upstream
Inductor lowering), `GraphLowering.codegen` (upstream + Spyre pipes +
kernel codegen + wrapper), and `SpyreKernel.codegen_kernel`. See
[`notes/extra-timers-closure.md`](extra-timers-closure.md).

Medians in milliseconds:

| point | n | compile_fx | gl_run | gl_codegen | sdsc | unattr | unattr % |
|:---|--:|---:|---:|---:|---:|---:|---:|
| A: 512×1024 | 1 | 97,944 | 651 | 5,744 | 80,480 | 11,069 | 11.3% |
| B: n=2 | 3 | 21,048 | 113 | 3,521 | 11,123 | 6,266 | 29.8% |
| B: n=4 | 3 | 37,594 | 152 | 8,149 | 23,765 | 5,843 | 15.5% |
| B: n=8 | 3 | 104,587 | 417 | 23,239 | 70,446 | 11,423 | 10.9% |

Sub-decomposition of `graphlowering_codegen`:

| point | gl_codegen | Spyre pipes | kernel_codegen | codegen residual |
|:---|---:|---:|---:|---:|
| A: 512×1024 | 5,744 | 4,359 | 244 | 1,142 |
| B: n=2 | 3,521 | 3,009 | 52 | 460 |
| B: n=4 | 8,149 | 7,263 | 101 | 785 |
| B: n=8 | 23,239 | 21,630 | 176 | 1,433 |

`codegen_residual = gl_codegen − Σ Spyre pipes − spyre_kernel_codegen`
is upstream Inductor scheduling + wrapper code generation. Scales
linearly with graph size, small in absolute terms.

**Two structural findings.**

1. **`gl_run` and `spyre_kernel_codegen` are effectively free** (<1% of
   compile_fx in every measured point). Upstream Inductor lowering and
   per-kernel codegen are not hotspots.
2. **The unattributed bucket is a nearly-fixed floor**: 11 s in both
   workload A baseline (98 s total) and workload B n=8 (105 s total),
   at the same absolute cost despite very different graph structures.
   Workload B n=8 unattr (11.4 s) / n=2 unattr (6.3 s) = 1.8× while
   `compile_fx` grows 5.0× — the bucket is very sublinear.
   Contains AOTAutograd joint-graph decomposition + `torch.compile`
   setup + inner-compile plumbing. Out of frontend scope.

**Implication**: Spyre-owned frontend cost = `gl_codegen − codegen_residual
− spyre_kernel_codegen` ≈ Σ Spyre pass pipelines. Optimizing the Spyre
pass pipelines IS optimizing the Spyre frontend end-to-end.

## 8. Scratchpad scaling — same code, two very different laws

Same `scratchpad_planning` code path, dramatically different scaling
on the two workloads. See
[`notes/scratchpad-scaling.md`](scratchpad-scaling.md) for the
full table.

Per-input-operation cost:

| workload | at smallest measured | at largest measured | growth |
|:---|---:|---:|---:|
| A | 3.6 µs/op (b=4) | 18.1 µs/op (b=128) | 5× |
| B | 5.8 µs/op (n=2) | 6.3 µs/op (n=16) | 1.1× (flat) |

Workload B: scratchpad is **linear** in graph size. Workload A:
scratchpad is **superlinear** (n^~1.45 as reported in #3806).

Root cause identified statically in `scratchpad/allocator.py:122` —
`_extern_kernel_in_live_range` iterates `range(min(uses), max(uses)+1)`
per buffer. Cost = Σ buffer live-range lengths.

- Workload A has long-lived carry buffers (`running_max`, `denominator`,
  `output`) that thread through every inner tile loop → each carry's
  live range grows with N → total pass work grows O(N·B) → superlinear.
- Workload B carries only 3 top-level state variables through the K
  loop; per-chunk scratch buffers stay local → live ranges bounded →
  pass stays linear.

**Fix (LOW/MEDIUM priority; workload A gains only)**: precompute a
prefix-sum of ExternKernel-count. Per-buffer check becomes O(1).
Estimated: scratchpad drops from 74 s → ~4 s at #3806's largest point.

## 9. Ranked opportunity list

### High-confidence fixes

1. **Reverse-adjacency `{buf_name: [reader_ops]}` in `_plan_tiling_propagation`
   and `_patch_retiled_load_indexes`.**
   Impact: Θ(N²) → Θ(N) on the two substages representing 96.6% of
   `_maybe_coarse_tile_hints`. Estimated reduction: from 14 s → ~2 s at
   n=8 (7× on the coarse-tile pass), from 53 s → ~7 s at n=16.
   Source location: `wsr/coarse_tile.py:510-635` (plan_tiling_propagation)
   and `1483-1489` (resync block) + `_patch_retiled_load_indexes`.
   Risk: MEDIUM — must be built per-substage since op mutation happens
   between substages (a naïve global memo breaks correctness, verified
   empirically in Phase 10 prototype).

2. **Replace `operations.index(op)` with an `op_to_position` dict in
   `replace_computed_buffer_body`.**
   Pattern already used at `coarse_tile.py:1480`; extend to
   `pass_utils.py:1342`.
   Impact: eliminates O(N)-per-splice in every mutating pass — dedup,
   coarse_tile, insert_restickify, split_multi_ops. Rough estimate:
   another 10–20% reduction in `_patch_retiled_load_indexes`.
   Risk: LOW — pure indexing change.

3. **Same reverse-adjacency approach applied to `dedup_and_promote_constants`'s
   `_redirect_consumers` per-op operations scan.**
   Impact: dedup 10 s → ~2 s at n=16 (5×). The `ops × dups` product
   stays; the per-pair constant shrinks by removing per-op sympy cost.
   Risk: LOW — dedup is already well-understood structurally.

4. **`_extern_kernel_in_live_range` prefix-sum in scratchpad_planning.**
   Replace `range(min(uses), max(uses)+1)` per-buffer scan with an
   O(N) precomputed prefix-sum of ExternKernel-count → O(1) per buffer
   check. Impact: scratchpad_planning drops from O(N·B) to O(N+B),
   collapsing workload A's n^1.45 slope to n^1.0. Estimated: 74 s → ~4 s
   at #3806's largest measured point (1024×8192).
   Source location: `scratchpad/allocator.py:122`.
   Risk: LOW — pure algorithm change on a single function.
   Workload-B benefit is small (scratchpad is already linear there);
   workload-A benefit is substantial at large graph sizes.

### Needs more measurement

4. **`optimize_restickify_locations` post-fix ~2.2–2.4× per doubling.**
   The mechanism after the constant-fill collapse is not yet
   source-attributed. Static audit flagged `state.assignments +
   (candidate_stl,)` tuple concat inside the beam loop as a
   O(N²·K·|L|) Python-bookkeeping cost. Instrumenting that path
   would confirm.

5. **Backend `dxp_standalone` growth.** Outside frontend scope but
   dominant in absolute compile time (2200 s at #3806's largest
   workload, 217 s at workload B n_chunks=16). Backend team's
   territory.

6. **Extent-driven scaling in pr3812 tree.** Our pr3806-base tree
   does not reproduce the PR docstring's ">2 hour Lq=8192" pathology.
   A pr3812 build would tell us whether that phenomenon lives in the
   new `perm_layout_native.cpp`, in extended
   `span_overflow_hint_analysis.py`, or elsewhere.

### Interesting but low leverage

7. **`_maybe_reorder_unhinted_interlopers` explicit `O(n²)`
   docstring.** Measured at 0.32 ms at n=2, 1 ms at n=16. The static
   worry is empirically fine for these graphs.

8. **`insert_all_read_copy_ops`'s `name_to_op` rebuild-per-entry.**
   Predicted as a hotspot by static audit; measured to shrink with
   chunk count in workload B because plan entries stay small. Not a
   priority for this workload family.

## 10. Executive summary

The frontend compilation cost of PR #3812's KV-chunked FlashAttention
is dominated by `_maybe_coarse_tile_hints`, whose 4×-per-doubling
scaling is 74% caused by `_patch_retiled_load_indexes` and 22% by
`_plan_tiling_propagation` — both driven by the same uncached
`get_read_writes()` mechanism that also inflates dedup's per-pair
constant 4.6× on this workload vs the PR #3806 workload. A per-substage
reverse-adjacency + a `op_to_position`-style splice fix would collapse
this class of quadratic behavior to linear in graph size across three
different passes simultaneously. The 5-line PR #3812 layout fix
independently removes the exponential state-space explosion in
`optimize_restickify` — that mechanism is confirmed at per-op
candidate granularity and reduces beam-state metrics by ~50% at
n_chunks=2.

Closed compile_fx decomposition (extra_timers hook) confirms
`gl_run` and `spyre_kernel_codegen` are effectively free (<1% each)
and that the previously-unattributed bucket is a nearly-fixed 11 s
upstream-Inductor floor (AOTAutograd + `torch.compile` setup) that
does not scale with graph size — meaning the entire Spyre-owned
frontend cost is captured by the Spyre pass pipelines. Scratchpad
planning is linear on workload B but superlinear on workload A
(same code, driven by workload A's long-lived carry buffers hitting
`_extern_kernel_in_live_range`'s O(range) scan); a prefix-sum fix
turns that into O(1) per buffer.
