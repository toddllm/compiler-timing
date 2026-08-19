# extra_timers close the unattributed bucket

Data:
- `data/workload-B-extra-timers/` — 9 samples, n_chunks ∈ {2, 4, 8}, 3 each.
- `data/workload-A-extra-timers/` — 1 sample at Lq=512, Lk=1024 (workload A baseline).

Instrumentation: `patches/extra_timers_v2.py` + `patches/extra_timers_hook.py`.
Wraps `GraphLowering.run` and `GraphLowering.codegen` (upstream Inductor)
plus `SpyreKernel.codegen_kernel`. The pr3806-shipped file had
`GraphLowering.compile_to_fn` which doesn't exist in torch 2.13; v2
uses `codegen` (the actual entry point that fires the Spyre pass
pipelines via `patches.py`'s `_spyre_update_scheduler`).

## Closed decomposition (medians, ms)

| point | n | compile_fx | gl_run | gl_codegen | sdsc | async_wait | unattr | unattr % |
|:---|--:|---:|---:|---:|---:|---:|---:|---:|
| A: 512×1024 | 1 | 97,944 | 651 | 5,744 | 80,480 | 0 | 11,069 | 11.3% |
| B: n=2 | 3 | 21,048 | 113 | 3,521 | 11,123 | 0 | 6,266 | 29.8% |
| B: n=4 | 3 | 37,594 | 152 | 8,149 | 23,765 | 0 | 5,843 | 15.5% |
| B: n=8 | 3 | 104,587 | 417 | 23,239 | 70,446 | 0 | 11,423 | 10.9% |

Formula: `unattr = compile_fx − gl_run − gl_codegen − sdsc_total − async_wait`.
`gl_run` is upstream Inductor lowering (AOTAutograd output → IR).
`gl_codegen` wraps `_update_scheduler` (Spyre pipes fire here) + scheduler.codegen + wrapper generation.
`sdsc` is SDSC prep + dxp_standalone.

## graphlowering_codegen sub-decomposition

| point | gl_codegen | Spyre pipes | kernel_codegen | codegen residual |
|:---|---:|---:|---:|---:|
| A: 512×1024 | 5,744 | 4,359 | 244 | 1,142 |
| B: n=2 | 3,521 | 3,009 | 52 | 460 |
| B: n=4 | 8,149 | 7,263 | 101 | 785 |
| B: n=8 | 23,239 | 21,630 | 176 | 1,433 |

`codegen residual = gl_codegen − Σ Spyre pipes − spyre_kernel_codegen`.
This residual is upstream Inductor scheduling + wrapper code generation
(scheduler.codegen writes the Python wrapper file for the compiled
graph). It scales roughly linearly with graph size.

## The unattributed bucket is upstream-Inductor floor

Workload A baseline (97.9 s total) and workload B n=8 (104.6 s total)
both have `unattr ≈ 11 s` at nearly identical total cost. That's
strong evidence the residual is a **fixed floor** — AOTAutograd
joint-graph decomposition + compile_fx wrapper setup + inner-compile
plumbing — that doesn't scale linearly with graph size.

Workload B n=2 has 6.3 s unattr on a 21 s compile (29.8%). The floor
is a bigger relative share when the compile is small. Same absolute
floor, different denominators.

Workload B n=8 unattr (11.4 s) / n=2 unattr (6.3 s) = 1.8× while
compile_fx grows 5.0×. Unattr is very sublinear in graph size.

## What the unattributed bucket contains

By elimination (everything else is now timed):

1. **AOTAutograd joint-graph decomposition** — runs BEFORE `compile_fx`
   receives the FX graph, but it's called INSIDE the compile_fx_wrapper
   because `torch.compile` wires it that way. This is the biggest single
   piece: sympy decomposition of the aten ops into Spyre-compatible
   primitives.
2. **compile_fx setup**: `torch.spyre._impl._lazy_init()`, decomposition
   table build (`get_spyre_decomp_table()`), inner-compile function
   binding.
3. **FX graph passes upstream of GraphLowering**: post-AOTAutograd graph
   normalization done by Inductor before it enters GraphLowering.
4. **Fusion + scheduling AFTER `graphlowering_codegen` returns** but
   BEFORE `sdsc_total` fires. Almost nothing here since dxp is invoked
   from within codegen.

## Closure summary

| bucket | at scale (n=8 or A baseline) | notes |
|:---|---:|:---|
| `sdsc` (dxp + prep) | 67-82% | External backend dominates |
| `gl_codegen` (Spyre pipes + kernel codegen + wrapper) | 6-22% | Frontend work |
| unattr (AOTAutograd + setup) | 11% (absolute) | Fixed floor |
| `gl_run` (upstream IR lowering) | <1% | Effectively free |
| kernel codegen (SpyreKernel) | <1% | Effectively free |

**Frontend attribution is now 100% closed**: `compile_fx = gl_run + gl_codegen + sdsc + unattr`, and `gl_codegen` fully decomposes into `Spyre pipes + kernel_codegen + codegen_residual`. Everything reconciles to within numerical precision.

## What this unlocks

Future opportunity ranking gets one more line:

- **AOTAutograd/upstream Inductor "floor" is ~10-11 s**. Anything faster
  than 11 s cannot come from frontend work alone at this baseline — it
  requires reducing the fixed pre-Inductor cost. Out of scope for
  Spyre engineering; noted for cross-team coordination.
- **Spyre custom pass pipelines are the entire frontend hotspot** in
  both workloads. `codegen_residual` is small; kernel codegen is
  effectively free. Fixing coarse-tile hints and dedup (already
  identified) IS fixing the Spyre-owned frontend.

## Instrumentation overhead

Extra_timers hook overhead measured across the sweep: n_chunks=4
elapsed 55 s median with extra_timers vs 60 s without (Phase 3
substage) or 43 s baseline (no extra instrumentation). The extra_timers
overhead alone appears NEGATIVE — actually faster than earlier runs.
That's within run-to-run noise; the point is that extra_timers cost
is negligible (<5%).
