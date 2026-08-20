# Static assessment — PR #3873

**Written BEFORE any measurement.**

## Target

- Kind: pr
- Repo: torch-spyre/torch-spyre
- PR: #3873
- Base ref → head ref: main → 8c5f911373
- URL: https://github.com/torch-spyre/torch-spyre/pull/3873
- Title: feat(inductor): allow specifying STL on `torch.full`

## Diff summary

- Files changed: 5
- +191 / −4
- Changed paths:
  - `tests/inductor/test_restickify.py`
  - `torch_spyre/_inductor/customops.py`
  - `torch_spyre/_inductor/lowering.py`
  - `torch_spyre/_inductor/propagate_layouts.py`
  - `torch_spyre/_monkey_patch.py`

## Per-path static triage

| Path | Stage | Hot-path? | Confidence |
|---|---|---|---|
| tests/inductor/test_restickify.py | test_only | no | high |
| torch_spyre/_inductor/customops.py | (unclassified — new custom op) | gated | medium |
| torch_spyre/_inductor/lowering.py | ir_lowering | yes | medium |
| torch_spyre/_inductor/propagate_layouts.py | layout_prop | yes | high |
| torch_spyre/_monkey_patch.py | (unclassified — monkey-patch layer) | gated | medium |

## What the PR actually does

Adds a new kwarg `device_layout=(device_size, stride_map, device_dtype)`
to `torch.full`. Implementation:

1. `customops.py`: registers `spyre::full_with_layout` custom op.
2. `lowering.py`: `lower_full_with_layout` calls `lower_full` to
   produce the standard `SpyreConstantFallback` + `Pointwise` IR,
   then stamps a `FixedTiledLayout` on the resulting
   `ComputedBuffer`.
3. `propagate_layouts.py`: in the `is_constant_fill` branch, check
   if the buffer already carries `FixedTiledLayout`; if so use its
   `device_layout` as the single candidate, else fall back to
   `[generic_layout(op)]`.
4. `_monkey_patch.py`: patches `torch.full` to route through
   `spyre::full_with_layout` when `device_layout=` is present.

## Applying the three-questions rule

The critical change is `propagate_layouts.py`, in a gated branch:

```python
if is_constant_fill:
    existing = op.get_layout()
    if isinstance(existing, FixedTiledLayout):
        op.layouts = [existing.device_layout]    # NEW (requires device_layout=)
    else:
        op.layouts = [generic_layout(op)]        # UNCHANGED default path
```

The new branch fires **only if the buffer has been stamped with
`FixedTiledLayout`**, which happens only through
`lower_full_with_layout` invoked from the new custom op. That is
reached only when user code passes `device_layout=` to `torch.full`.

1. **Does the changed code execute on the timed compile path in a
   sentinel workload?**
   - `WA_baseline`, `WB_n4`, `WB_scaling_pair` — none use
     `device_layout=`. On the default path the else-branch runs (was
     before, is after). **No.**
   - Only the PR's own new test `test_full_with_layout_plus_xt`
     activates the new path.
2. **Hot inner loop or setup?** — the changed line is inside
   `propagate_spyre_tensor_layouts`'s main loop, but adds one
   `isinstance` check per constant-fill op. Cheap.
3. **Does the change alter the collections/constants that made a
   pattern superlinear?** No.

## Predicted affected compiler surface

For default-path (no kwarg): **NONE**. Only the constant-fill
branch adds one `isinstance` check; that's O(n_constants) additional
work, dominated by measurement noise.

For activation-specific path (with kwarg): the constant now has 1
candidate matching the specific STL rather than 1 generic candidate.
Restickify would decide differently but at the same beam-state cost
(1 vs 1 candidate). The PR's own test asserts this changes the
restickify cost from non-zero to zero on the tested pattern.

## Prediction

- **Direction**: neutral (default path); functional for
  activation-specific path.
- **Magnitude class**: none for default; measured by the PR's own
  test for activated path.
- **Verdict class expected**: `ACTIVATION_SPECIFIC_IMPACT` — no
  default-path movement; new feature activated by kwarg.
- **Confidence**: HIGH.

## Failure modes for this prediction

- The `isinstance(existing, FixedTiledLayout)` check runs on every
  constant-fill op even on the default path. If some sentinel
  workload has hundreds of constant-fill ops (workload B has ~3
  per chunk = 24 at n=8), the extra isinstance work is:
  24 × ~50ns = ~1.2µs total. Utterly negligible.
- The `customops.py` and `lowering.py` code paths run
  unconditionally during import, adding an operator registration.
  Import overhead is not in `compile_fx_wrapper`.
- `_monkey_patch.py` patches `torch.full` globally. If the patch
  is expensive per call to `torch.full`, it would show up. Check by
  reading the diff.

## Confidence

**HIGH**. The gated-path structure is transparent in the diff.
Default-path change is a single `isinstance` check per constant-fill
op.
