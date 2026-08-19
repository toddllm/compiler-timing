# Frontend compilation scaling — 2-minute summary

## What we investigated

Two Torch-Spyre FlashAttention workload families, controlled on the
same base tree:

- **Workload A — OpSpec/static tiled FlashAttention** (from the earlier
  PR #3806 timing study).
- **Workload B — WSR/coarse-tiled KV-chunked FlashAttention derived
  from PR #3812**, measured on the pr3806-base tree with the relevant
  constant-fill layout behavior toggled between the pre-fix and post-fix
  variants. This is not the full PR #3812 tree.

Reference numbers reported in PR #3812 itself are cited alongside our
own measurements where they overlap; they were made on that PR's full
branch and used a different pod.

## Main conclusion

**There is not one frontend scaling problem.** We identified several
independent mechanisms whose importance depends on workload topology.

### 1. Repeated dependency/graph scanning

Both `dedup_and_promote_constants` and WSR coarse tiling repeatedly
recompute dependency information over the operation list. In our
workload B this shows up as `_maybe_coarse_tile_hints` growing
approximately quadratically with chunk count, and dedup growing as
`operations × duplicates`.

The `operations × duplicates` shape for dedup **generalizes** across
both workloads. The per-pair constant does not — it is ~4.6× larger on
workload B because individual dependency extractions are more expensive
on richer inner_fns.

Coarse-tile hints scaling in workload B, from 3-sample medians:

| n_chunks | `_maybe_coarse_tile_hints` (s) | 2× growth |
|:---:|:---:|:---:|
| 2 | 1.5 | — |
| 4 | 4.1 | 2.80× |
| 8 | 14.5 | 3.52× |
| 16 | 53.1 | 3.67× |

At 8 chunks, two substages account for **96.6%** of that pass, both
driven by the same uncached `op.get_read_writes()` pattern:

- `_patch_retiled_load_indexes` — 74.5%
- `_plan_tiling_propagation` — 22.1%

### 2. Restickify search-state explosion

Distinct from mechanism 1. Constant-fill layout ambiguity multiplies
beam-search state through the per-chunk diamond pattern. Issue #3687
independently observed `min_beam ≈ 400 × 2^(n − 7)` — a doubling per
chunk. PR #3812's one-line change (`_all_constant_layouts(op)` →
`[generic_layout(op)]`) collapses the diamond source. Our beam-frontier
instrumentation directly confirms the candidate reduction: on the same
graph, constant-fill ops go from 2 candidates each to 1, and immediate
downstream `post_expand` metrics halve.

### 3. Workload-topology-dependent scratchpad scaling

Same `scratchpad_planning` code:

- **Workload A**: superlinear (~n^1.45 across the 32× range measured).
- **Workload B**: linear.

Root cause: `_extern_kernel_in_live_range` walks `range(min(uses),
max(uses)+1)` per buffer. Workload A has long-lived carry buffers
(`running_max`, `denominator`, `output`) threading through every inner
tile, so per-buffer scan lengths grow with graph size. Workload B's
per-chunk scratch buffers stay local, so scan lengths are bounded.

### 4. What is not a hidden frontend problem

With extra timers wrapping upstream `GraphLowering.run`, `.codegen`, and
`SpyreKernel.codegen_kernel`, we can close the `compile_fx_wrapper`
attribution to 100%:

- Upstream `GraphLowering.run` (Inductor lowering): <1% of `compile_fx`
  everywhere measured.
- `SpyreKernel.codegen_kernel` (per-kernel): <1% everywhere.
- Wrapper/upstream scheduling residual inside `codegen`: small.
- The **Spyre custom pass pipelines** contain essentially the entire
  Spyre-owned frontend work worth optimizing.
- A roughly **6–11 s comparatively sublinear upstream/setup component**
  (AOTAutograd joint-graph decomposition + `torch.compile` plumbing)
  remains over the measured points. It does not scale nearly as fast
  as the Spyre pass pipelines and is not Spyre-owned.

The external backend, `dxp_standalone`, dominates absolute compile time
at scale (69 s at workload B n=8; 217 s at n=16; larger still on the
biggest workload A points). That is a separate ownership area outside
the primary frontend scope.

## Biggest current frontend opportunities

_See [`notes/engineering-opportunities.md`](notes/engineering-opportunities.md)
for the ranked map with confidence levels._

1. **Per-substage reverse adjacency in coarse-tile hints**
   (**MEASURED**). Replace the two dominant
   O(N × K) `_reads_buffer` scan patterns in `_plan_tiling_propagation`
   and `_patch_retiled_load_indexes` with a single per-substage
   `readers_by_buffer` / `reads_by_op` index. Root cause measured;
   prototype impact **measured**: coarse-tile pass 2.93× faster at n=4,
   3.68× faster at n=8; scaling-law growth 4→8 shifts from 3.52× down
   to 2.80× (approaching linear). Total Spyre pass pipelines at n=8:
   23.3 s → 12.8 s.

2. **`_extern_kernel_in_live_range` prefix-sum in scratchpad_planning**
   (**MEASURED NULL — hypothesis refuted**). The prototype changed
   `_maybe_scratchpad_planning` by only 1–2% (128 ms saved at 512×4096,
   204 ms saved at 512×8192 — within measurement noise). The source
   audit correctly identified an O(N·B) code pattern, but
   `isinstance(op, ExternKernel)` is empirically not the dominant term.
   The real driver of workload A's n^1.45 scratchpad scaling is still
   unattributed. **Needs substage instrumentation inside
   `plan_allocation` before another prototype.**

3. **Dedup reverse-adjacency / consumer index** (estimated). The same
   uncached-`get_read_writes` mechanism that drives coarse-tile hints
   also inflates dedup's per-pair constant 4.6× on workload B. Root
   cause **measured**; no prototype yet — awaiting prototype.

4. **Restickify's post-fix ~2.2–2.4× per doubling** (needs further
   investigation). The exponential mechanism is closed by PR #3812.
   The remaining post-fix scaling has not yet been source-attributed;
   `state.assignments + (candidate_stl,)` tuple concatenation inside
   the beam loop is a static-audit candidate.

## Open questions

- **The controlled base tree does not reproduce PR #3812's reported
  ">2 hour" Lq=8192 pathology at n_chunks=4.** Our sweep across
  Lq ∈ {64…4096} at fixed n_chunks=4, both untiled and with
  `lq_tiles=2`, shows compile cost varying by less than 15%. FX@entry
  and n_specs are constant. The mechanism causing that pathology
  either lives in PR #3812's additional changes (820 lines of new
  `perm_layout_native.cpp`, an expanded `span_overflow_hint_analysis.py`,
  scratchpad allocator revisions) or in extent-dependent code paths
  our base does not exercise. Distinguishing these requires a full
  pr3812 build.

- **The 6–11 s upstream/setup component is not further decomposed.**
  It is upstream Inductor and `torch.compile` wiring, not Spyre-owned,
  but if pushed lower it would benefit every workload.

## Two figures worth 20 seconds each

- [`plots/workload-B-frontend-composition.png`](plots/workload-B-frontend-composition.png)
  — stacked Spyre-frontend bars at n_chunks 2/4/8/16 in workload B;
  makes the coarse-tile dominance visually obvious.
- [`plots/cross-workload-mechanism-matrix.png`](plots/cross-workload-mechanism-matrix.png)
  — cross-workload comparison of which frontend scaling mechanisms
  apply to which workload family.

## Where to go next

- Full technical synthesis: [`notes/findings.md`](notes/findings.md).
- Prioritized action list: [`notes/engineering-opportunities.md`](notes/engineering-opportunities.md).
- The two prototype measurement writeups:
  [`notes/coarse-tile-prototype.md`](notes/coarse-tile-prototype.md),
  [`notes/scratchpad-prototype.md`](notes/scratchpad-prototype.md).
