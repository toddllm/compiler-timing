# Results — PR #3890

## Verdict

**Classification**: `INSUFFICIENT_EVIDENCE` (measurement blocked by
tree drift; static analysis alone stands with the confidence stated
in `01-static-assessment.md`).
**Confidence**: N/A for measurement; the static prediction retains
**HIGH** confidence.

## What was actually done

- Static assessment written (`01-static-assessment.md`).
- Experiment plan written (`02-experiment-plan.md`) — chose
  WB_scaling_pair (n=4 and n=8), 3 samples each.
- Attempted to apply the PR's diff to the pod's `torch-spyre`
  checkout as a marginal patch for A/B measurement:
  - `git apply --check /tmp/pr3890.diff` → fails
    (`patch failed: torch_spyre/_inductor/wsr/coarse_tile.py:1953`).
  - `git apply --3way /tmp/pr3890.diff` → applies with conflicts
    (`UU torch_spyre/_inductor/wsr/coarse_tile.py`, 6 conflict
    markers left).
- Reverted attempted patch state; the pod tree is clean.
- Took **one reference workspace-baseline sample** at WA_baseline
  configuration to confirm the pod tree still compiles cleanly.
  See `../data/workspace-baseline/wa-baseline.json`.

Workspace-baseline reference:

| metric | value |
|---|---:|
| compile_fx_wrapper | 100.4 s |
| dxp_standalone | 79.0 s |
| pipeline:CustomPreSchedulingPasses | 4.9 s |
| pass:_maybe_scratchpad_planning | 974 ms |
| pass:dedup_and_promote_constants | 888 ms |
| pass:optimize_restickify_locations | 1,432 ms |

These are consistent with the primary study's baseline
(compile_fx ≈ 99.4 s at 512×1024, dedup ≈ 870 ms, restickify ≈
1,700 ms), so the pod state is a valid substrate — just not the
right base for PR #3890.

## Why marginal patching fails

The pod's `torch_spyre/_inductor/wsr/coarse_tile.py` is derived
from the PR #3806 branch state (`a9316b381`, a Merge that includes
an older `main`). PR #3890 targets a newer `main` (`be1328a867`).
The `coarse_tile.py` file has drifted enough between those two
`main` snapshots that the PR's context hunks do not match the
pod's file.

Specifically:
- PR base's `coarse_tile.py`: 4,317 lines.
- Pod's `coarse_tile.py`: 3,757 lines.
- Hunks around `_tiled_dims_for_dep` and `_insert_one_read_copy`
  don't apply cleanly.

A scientifically clean A/B would require an **isolated checkout at
`be1328a867`** with a fresh `pip install -e .` in a new venv,
followed by measuring base (that SHA) then applying the PR diff for
head. Cost: ~10–20 min setup + ~18 min sweep = ~30–40 min for
this one PR.

## Attribution (static only)

From the diff analysis in `01-static-assessment.md`:

- The change adds `_raw_to_squeezed_pos(ir_node)` as a helper
  called inside `_tiled_dims_for_dep`, which itself is called
  inside `_plan_tiling_propagation` (measured as 22.1% of
  `_maybe_coarse_tile_hints` at WB n=8).
- The change also rewrites `active_full_sizes` computation inside
  `_insert_one_read_copy`, called inside `_insert_all_read_copy_ops`
  (measured as ~2% of `_maybe_coarse_tile_hints` at WB n=8).
- Both changes add per-op arithmetic on a correctness path.
  Rough estimate: ~5–20 µs per op per pass, totaling ~1–5 ms per
  compile at WB n=4. Below measurement noise.
- Neither change alters the collections that made the pattern
  quadratic (the `for op in operations` scans are unchanged).

## Device time consumed

- Reference baseline sample: ~100 seconds (one WA_baseline sample).
- **Actual paired base/head measurement: NOT performed** (tree
  drift blocked marginal patch).
- Naive baseline for this PR: ~27 min.
- Full clean isolated-checkout measurement: would cost ~30–40 min.

## Follow-ups

- If a definitive measurement is needed, set up a fresh venv at
  the PR's base SHA `be1328a867` and repeat the WB_scaling_pair
  sweep at head. Not blocking anything unless a regression is
  suspected in production.
- Suggests improvement to the skill: add a "pod-side tree state"
  precondition to the experiment plan. If the pod tree is not
  aligned to the PR's actual base, the skill should either request
  a fresh checkout or classify as INSUFFICIENT_EVIDENCE (as here).
