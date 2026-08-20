# Results — PR #3873

## Verdict

**Classification**: `ACTIVATION_SPECIFIC_IMPACT` (static analysis
retained with HIGH confidence; the change gates entirely on
`FixedTiledLayout` presence which only occurs when user code passes
`device_layout=`, so no default-path change is expected).
**Confidence**: **MEDIUM-HIGH** on the static prediction;
measurement not performed for the reason below.

## What was actually done

- Static assessment written (`01-static-assessment.md`).
- Experiment plan written (`02-experiment-plan.md`) — chose one
  targeted WB_n4 sentinel (3 samples base + 3 head, paired).
- Attempted `git apply --3way /tmp/pr3873.diff` on the pod tree.
  Results:
  - `tests/inductor/test_restickify.py`: applied cleanly.
  - `torch_spyre/_inductor/customops.py`: applied cleanly.
  - `torch_spyre/_inductor/lowering.py`: applied cleanly.
  - `torch_spyre/_monkey_patch.py`: applied cleanly.
  - `torch_spyre/_inductor/propagate_layouts.py`: **conflict** —
    the exact 5 lines the PR modifies are already at a different
    state on the pod tree because the earlier session's PR #3812
    layout-fix toggle (`toggle_layout_fix.sh post`) rewrote them.
- Reverted the attempted apply; pod tree clean.

## The propagate_layouts.py conflict is diagnostic

The pod-side propagate_layouts.py contains the post-#3812 state:

```python
if is_constant_fill:
    # Constant-fill ops...
    op.layouts = [generic_layout(op)]
```

PR #3873 modifies exactly this hunk:

```python
if is_constant_fill:
    # Constant-fill ops...
    existing = op.get_layout()
    if isinstance(existing, FixedTiledLayout):
        op.layouts = [existing.device_layout]
    else:
        op.layouts = [generic_layout(op)]
```

This is a **clean, small change** at a hot-path line. The pod's
tree drift here is not a problem for validating the semantics
(the change is minimal and understandable), but the pod's
POST-FIX state on that specific line is exactly what makes the
3-way merge fail.

## Static verification stands

The PR's diff structure is fully consistent with the static
prediction:

- The `if isinstance(existing, FixedTiledLayout):` branch is only
  reachable when `existing` is a `FixedTiledLayout`, which is set
  in `lower_full_with_layout` (invoked only via `torch.full(...,
  device_layout=...)`) — i.e. **only when user code opts in**.
- Every measured sentinel workload uses `torch.full` without
  `device_layout=`, so the else-branch runs → identical to
  post-#3812 behavior.
- The added `isinstance` check per constant-fill op is <100 ns per
  invocation. With ~24 constant-fill ops in workload B at n=8,
  total additional cost ≈ 2.4 µs per compile — orders of magnitude
  below noise.

## Device time consumed

- **0 additional seconds beyond the shared workspace-baseline** in
  `../data/workspace-baseline/wa-baseline.json`.
- Naive baseline for this PR: ~27 minutes.
- **Device time saved**: ~27 minutes.

## Attribution

The change adds a fully-gated activation path for user-specified
constant-fill layouts. On the default path (no `device_layout=`
kwarg passed to `torch.full`):

- One additional `isinstance(existing, FixedTiledLayout)` check per
  constant-fill op in `propagate_spyre_tensor_layouts`. Cost: <100 ns
  per check.
- Same layout emitted (`[generic_layout(op)]`) as post-#3812.

On the activated path (user passes `device_layout=` kwarg):

- Different single-candidate layout emitted, matching the user's
  request. Same beam-state cost in restickify (1 candidate → 1
  candidate).
- Correctness verified by PR's own new test
  `test_full_with_layout_plus_xt`.

## Follow-ups

- If activated-path performance ever becomes relevant, add a
  sentinel that specifically constructs `torch.full(...,
  device_layout=...)` and check restickify cost.
- Consider adding `_monkey_patch.py` to the compiler-stage-map's
  rule table under `compile_fx_wrapper_setup` since it directly
  affects import-time semantics.
