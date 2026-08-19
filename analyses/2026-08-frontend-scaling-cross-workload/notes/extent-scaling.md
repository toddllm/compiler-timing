# Tensor-extent scaling at fixed n_chunks

Fixed workload params: `B=1 H=8 D=128 Lk=4096 kv_block=1024 h_tiles=4 lq_tiles=None`
→ `n_chunks=4`. Vary Lq only. Post-fix layout state.

## Small-Lq points (initial sweep)

| Lq | wall (s) | compile_fx | dxp | coarse_tile | restickify | dedup | scratchpad | FX@entry | n_specs |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 64 | 44.34 | 42.99 | 21.50 | 4.008 | 1.033 | 0.655 | 0.570 | 105 | 5 |
| 128 | 44.80 | 43.36 | 21.80 | 3.819 | 1.028 | 0.643 | 0.552 | 105 | 5 |
| 256 | 47.08 | 46.02 | 23.57 | 3.778 | 1.043 | 0.657 | 0.624 | 105 | 5 |
| 512 | 40.94 | 40.03 | 22.76 | 3.873 | 1.056 | 0.659 | 0.642 | 105 | 5 |

**Every value within measurement noise.** Lq ∈ {64, 128, 256, 512} at
fixed n_chunks=4 produces:

- **Identical FX-nodes-at-entry (105)** — graph structure is a function
  of chunk count, not Lq value.
- **Identical `n_specs` (5)** — bundle content stable.
- **Compile cost flat within ~15%** — 40.94 → 47.08 s, no monotonic trend.

## Interpretation so far

The PR docstring's warning ("Lq=8192 at n=4 took over 2 hours") is
**NOT** smooth-extent scaling. Compile cost is stable across a 4×
Lq range (64 → 512) with all pass times matching to within a few
percent. Any dramatic slowdown must come from a **threshold effect** at
large Lq — not a smooth O(Lq^k) scaling law.

Candidate mechanisms for a threshold:
1. Some pass has a code path that only triggers when `Lq × D > some_bound`
   (memory or stick-count limit).
2. Sympy simplification cost grows sharply when Lq exceeds a range the
   library handles trivially (large-integer arithmetic).
3. A per-op cost model iterates `range(0, Lq, step)` for some `step`,
   producing O(Lq) work in one loop even though graph structure is
   Lq-independent.
4. Search/beam/DP over "possible tile decompositions" whose state space
   grows in Lq / kv_block combinations.

## Extended sweep

Second run at Lq ∈ {2048, 4096} succeeded fast; Lq=1024 hit a **hardware
fault** (PCIe bus fence RAS::PCI::BusFence — unrelated to compile).
Retry pending.

## Combined observations (lq_tiles=None throughout)

| Lq | wall | compile_fx | dxp | coarse_tile | restickify | dedup | scratchpad | prop_layout | FX@entry | n_specs |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 64 | 44.34 | 42.99 | 21.50 | 4.008 | 1.033 | 0.655 | 0.570 | 0.490 | 105 | 5 |
| 128 | 44.80 | 43.36 | 21.80 | 3.819 | 1.028 | 0.643 | 0.552 | 0.482 | 105 | 5 |
| 256 | 47.08 | 46.02 | 23.57 | 3.778 | 1.043 | 0.657 | 0.624 | 0.498 | 105 | 5 |
| 512 | 40.94 | 40.03 | 22.76 | 3.873 | 1.056 | 0.659 | 0.642 | 0.504 | 105 | 5 |
| 2048 | 44.04 | 43.28 | 26.04 | 4.302 | 1.051 | 0.663 | 0.575 | 0.499 | 105 | 5 |
| 4096 | 49.75 | 48.76 | 28.39 | 4.210 | 1.040 | 0.661 | 0.568 | 0.497 | 105 | 5 |

**Across a 64× Lq range compile cost is flat within ~15%.**

- `compile_fx` range: 40.0 → 48.8 s → 1.22× max/min
- `_maybe_coarse_tile_hints`: 3.78 → 4.30 s → 1.14× max/min
- `optimize_restickify_locations`: 1.03 → 1.06 s → 1.03× max/min
- `dedup`: 0.64 → 0.66 s → 1.03× max/min
- `dxp_standalone` shows a mild upward drift (21.5 → 28.4 s → 1.32×) —
  backend does process tensor extents so this is expected.

**FX@entry = 105 for all 6 Lq values. n_specs = 5 for all.** Graph
structure at compile_fx entry is independent of Lq at fixed n_chunks
when Lq is not tiled.

## The PR's Lq=8192 slow case likely requires Lq tiling

Looking again at the PR's `test_hint_flash_attention_kv_chunked_prefill_8k`
setup that produced the "over 2 hours" observation:

```python
h_tiles=4, lq_tiles=2, B=1, H=8, Lq=512, Lk=8192, D=128, kv_block=2048
```

Notice **`lq_tiles=2`**. The prohibitive-Lq case in the docstring comment
must be `lq_tiles=2` too — otherwise the graph has no Lq-tile structure to
process. My sweep above uses `lq_tiles=None` (no Lq tiling), so Lq flows
through as an opaque range with no per-tile machinery. That's why Lq is
flat here.

The threshold effect is likely triggered when Lq × lq_tiles machinery
enters the compile graph, and one of the pass loops iterates something
like `range(0, Lq, kv_block)` or does per-Lq-tile symbolic work.

## Lq × lq_tiles=2 sweep (WSR Lq tiling enabled)

Same Lk=4096, n_chunks=4 config as above but with `lq_tiles=2`:

| Lq | lq_tiles | compile_fx | dxp | coarse_tile | restickify | dedup | scratchpad | prop_layout | FX@entry | n_specs |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 256 | 2 | 65.22 | 46.51 | 4.070 | 1.048 | 0.656 | 0.571 | 0.513 | 106 | 5 |
| 512 | 2 | 66.23 | 50.26 | 4.063 | 1.056 | 0.658 | 0.571 | 0.503 | 106 | 5 |
| 1024 | 2 | 66.11 | 48.20 | 4.027 | 1.051 | 0.668 | 0.575 | 0.501 | 106 | 5 |
| 2048 | 2 | 64.60 | 48.87 | 4.100 | 1.034 | 0.656 | 0.573 | 0.499 | 106 | 5 |

**Also flat across an 8× Lq range with lq_tiles=2.**

The only effect of enabling `lq_tiles=2` is a fixed additive cost of
about **+21 s** — 65 s vs 43 s at Lq=256. Almost all of that lives in
`dxp` (46-50 s vs 21-28 s). Frontend Spyre passes are within measurement
noise between tiled and untiled.

## Interpretation

**Lq extent alone does NOT drive compile cost in workload B.** Neither
with `lq_tiles=0` nor `lq_tiles=2`. FX-node count and `n_specs` are
independent of Lq.

The PR docstring's ">2 hour" Lq=8192 case at n=4 must involve
`Lk=8192`, not `Lq=8192` in isolation. Recall the PR's actual test that
observed the long compile:

```python
h_tiles=4, lq_tiles=2, B=1, H=8, Lq=512, Lk=8192, D=128, kv_block=2048
```

The prohibitive setup was `Lk=8192` at `kv_block=2048` (still n_chunks=4)
combined with `Lq=8192` (hypothetical). We should test `Lk` variation at
fixed n_chunks separately.

## Lk extent sweep at fixed n_chunks=4

Sweep `Lk` from 1024 to 16384 (16×) while keeping n_chunks fixed by
scaling kv_block. `lq_tiles=None`, all other params fixed.

| Lk | kv_block | compile_fx | dxp | coarse_tile | restickify | dedup | scratchpad | FX@entry | n_specs |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1024 | 256 | 39.03 | 19.12 | 4.012 | 1.052 | 0.654 | 0.500 | 105 | 5 |
| 2048 | 512 | 41.87 | 25.34 | 3.931 | 1.041 | 0.655 | 0.586 | 105 | 5 |
| 4096 | 1024 | 39.39 | 23.01 | 3.828 | 1.035 | 0.655 | 0.571 | 105 | 5 |
| 8192 | 2048 | 39.48 | 22.51 | 4.181 | 1.048 | 0.661 | 0.530 | 105 | 5 |
| 16384 | 4096 | 40.47 | 23.96 | 4.305 | 1.051 | 0.663 | 0.529 | 105 | 5 |

**Lk × 16 has no effect on compile cost.** Every frontend pass within
noise. FX@entry constant at 105, n_specs constant at 5.

## Phase 4 conclusion

Compile cost in workload B on the **pr3806-base tree** is a function
of `n_chunks` alone (the loop-unroll factor that determines graph size).
It is **INDEPENDENT** of:
- `Lq` value at fixed n_chunks (tested 64 → 4096, 64× range)
- `Lk` value at fixed n_chunks (tested 1024 → 16384, 16× range)
- `lq_tiles ∈ {None, 2}` (fixed additive dxp cost only)

The PR #3812 docstring claim that Lq=8192 at n_chunks=4 compiled for
>2 hours does NOT reproduce on our tree. Two candidate explanations:

1. **Different code path**: pr3812's branch has meaningful changes beyond
   the 1-line layout fix in `propagate_layouts.py:1910`. Its `perm_layout_native.cpp`
   (820 lines new C++), `span_overflow_hint_analysis.py` (+468 lines),
   and revisions to `scratchpad/allocator.py` may enable an extent-
   dependent code path that our older base doesn't hit.

2. **Different C-extension**: our tree uses the pr3806 `_C.so`. If the
   pathological Lq behavior involves the C-extension, we'd never see it.

The Phase 4 extent-scaling question is answered "no" for our tree.
Distinguishing (1) from (2) would require building the pr3812 tree —
significant investment for a follow-up finding that doesn't change the
Phase 3/6 conclusions.

Recommendation: document this as a **null result specific to our tree**
and move on. The extent-dependent phenomenon is worth flagging in the
synthesis but should be qualified: "PR #3812 reports it; we could not
reproduce on pr3806-base main snapshot."



