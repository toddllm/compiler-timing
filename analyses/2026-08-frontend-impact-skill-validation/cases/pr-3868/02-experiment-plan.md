# Experiment plan — PR #3868

**Written BEFORE any measurement. Updated to reflect the tightened
Tier 2 alignment policy that this case itself motivated.**

## Level decision

- **Chosen level**: **1** (TARGETED_RUN), possibly extended to
  Level 2 if WB and WA disagree.
- **Rationale**: `codegen/bundle.py` is a single file, on the hot
  path (called for every compile), with a clear semantic change.
  A single sentinel at moderate size should reveal the direction
  of impact.

## Pod-tree alignment (Tier 2 check)

**Tier 2 check on the pod at pod SHA `a9316b3` failed.** PR base
`bundle.py` md5 is `c93d3ba5d7...`; pod `bundle.py` md5 is
`314e022307...`. The pod's copy predates PR base by 14 lines (a
pool-allocation refactor already at PR base). "Diff applies cleanly"
via `git apply --check` returns 0, but that only checks the patch
context — Tier 2 blob equality fails.

→ **Escalate to Tier 3** (isolated checkout at exact PR SHAs).

The initial marginal-patch attempt (which pre-dated the tightened
Tier 2) is retained in `data/` as an exploratory finding, clearly
labeled.

## Tier 3 execution

- **Isolated base checkout**: `torch-spyre` @
  `2e935febe58bcf275accfaa4c960d972d7e6ce49` at
  `~/pr3868-iso/torch-spyre-base` (v2 pod).
- **Isolated head checkout**: `torch-spyre` @
  `a7786ac8a6934645821b3698a9eb33ae2d3b590b` at
  `~/pr3868-iso/torch-spyre-head` (v2 pod).
- **`_C.so`**: rebuilt from source in each isolated tree via
  `python setup.py build_ext --inplace`. Both build cleanly against
  the v2 pod's `ibm-deeptools 2245.85f9432`. The old pod's
  deeptools install (`2238.654a8d5`) lacks `fast_process_hcm.h`
  and blocked this step; the new pod unblocks it.
- **Instrumentation**: `timing_shim.py` monkey-patches
  `torch._inductor.compile_fx.compile_fx`, all Spyre pipeline
  classes, `bundle.generate_bundle`, and the subprocess call for
  `dxp_standalone`. Registered as `torch_spyre._inductor.timing_recorder`
  so unmodified harnesses import it directly.
- **Correctness**: Both isolated trees smoke-tested to import
  `NativePermutationLayoutSolver` and `scratchpad.allocator` cleanly.
- **PATH discipline**: `PYTHONPATH="$tree:/tmp/shim-dir"` before
  running the harness. `.venv` is the pod's shared torch install.

## Sentinels selected

| Sentinel | Point | Samples | Paired | Rationale |
|---|---|---:|:---:|---|
| WB_n4 | n_chunks=4 | 3 base, 3 head | yes | KV-chunked baseline; expected cache hits if the mechanism holds |
| WB_n8 | n_chunks=8 | 3 base, 3 head | yes | Doubled n; more repetitive ops give more expected cache hits |

## Metrics expected to move

- `sdsc_bundle_gen` — decrease (fewer distinct sdsc_<idx>.json).
- `sdsc_total` — decrease.
- `dxp_standalone` — maybe decrease (backend sees smaller bundle).
- Possibly `compile_fx_wrapper` — since `sdsc_*` is inside it.

## Metrics expected NOT to move

- All pre-scheduling passes (`_maybe_coarse_tile_hints`, etc).
- `fx_nodes_at_entry`.

## Structural counters to record

- `n_specs` at `sdsc_bundle_gen.meta` — MAY change (fewer distinct
  specs). If it decreases at head, verdict is
  `STRUCTURAL_CHANGE_NEUTRAL` (fewer specs means less backend
  work, not the same work faster).

## C-extension rebuild required?

Yes — Tier 3 path uses per-revision `_C.so` builds. The isolated
head tree also contains `_inductor.scratchpad.permutation_layout`
which top-level imports `NativePermutationLayoutSolver` from `_C`,
so the pod's older `_C.so` cannot be symlinked. Both builds
succeeded on the v2 pod.

## Estimated device time

- WB_n4: 3 base + 3 head, ~75 s each = ~7.5 min.
- WB_n8: 3 base + 3 head, ~130 s each = ~13 min.
- Total: ~20 min (actual: ~15 min).
- `_C.so` build time (one-time setup): ~3 min per tree = ~6 min.
