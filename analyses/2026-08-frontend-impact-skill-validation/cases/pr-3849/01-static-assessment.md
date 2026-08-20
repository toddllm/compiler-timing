# Static assessment — PR #3849

**Written BEFORE any measurement.**

## Target

- Kind: pr
- Repo: torch-spyre/torch-spyre
- PR: #3849
- Base ref → head ref: main → a4281dce49
- URL: https://github.com/torch-spyre/torch-spyre/pull/3849
- Title: fix(scratchpad): follow-up review fixes for the native packer

## Diff summary

- Files changed: 12
- +434 / −145

## Per-path static triage

| Path | Stage | Hot-path? | Confidence |
|---|---|---|---|
| docs/source/user_guide/examples/scratchpad/profile_native_packer.py | docs | no | high |
| tests/inductor/test_perm_layout_solver.py | test_only | no | high |
| tests/inductor/test_scratchpad_solver.py | test_only | no | high |
| tests/inductor/test_simulated_annealing.py | test_only | no | high |
| torch_spyre/_inductor/scratchpad/allocator.py | scratchpad | uncertain | medium |
| torch_spyre/_inductor/scratchpad/exhaustive_search.py | scratchpad | uncertain | medium |
| torch_spyre/_inductor/scratchpad/firstfit_bestfit_solver.py | scratchpad | uncertain | medium |
| torch_spyre/_inductor/scratchpad/greedy_solver.py | scratchpad | uncertain | medium |
| torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py | scratchpad | uncertain | medium |
| torch_spyre/_inductor/scratchpad/permutation_layout.py | scratchpad | uncertain | medium |
| torch_spyre/_inductor/scratchpad/plan_solver.py | scratchpad | uncertain | medium |
| torch_spyre/csrc/perm_layout_native.cpp | csrc | uncertain | medium |

## What the PR actually does

PR body explicitly describes four commits, all of which:

1. Correct a contradicted docstring in `plan_solver.py`
   `assert_in_place_parent_is_read`.
2. Mirror the Python packer's in-place rejections in the native
   packer's constructor (validation only).
3. Bounds-check the Python packer's `resize` / `set_eligible` /
   `top_or_inf` (previously silent on `idx=-1`; now raise `ValueError`).
4. Bounds-check `swap` and `rotate` too.
5. Cover the native constructor's `eligible=` argument with a test.

**Key phrase from PR body**: "so `TORCH_SPYRE_NATIVE_PACKER=0` was
not the 'same packer, only slower' the docs promise." → the change
is about **rejecting inputs Python already rejected**, not altering
valid-layout behavior.

## Applying the three-questions rule

1. **Does the changed code execute on the timed compile path?**
   Partially: `_inplace_edge_ok`, `_valid_inplace_parents`, the
   solver constructors, and `perm_layout_native.cpp` constructor
   validation all run during `scratchpad_planning`. But the
   modified branches are **rejection paths that only fire on invalid
   inputs**; on valid inputs (the sentinel workloads) they are `if
   ...: raise` guards.
2. **Hot inner loop or validation?**
   The changes are strictly validation. The bounds checks precede
   the unchanged data-flow.
3. **Does the change alter the collections/constants?**
   No. `swap`/`rotate` semantics on valid indices are unchanged.
   In-place edge admission is unchanged for admissible pairs.

Also relevant: our own scratchpad prototype (see
`analyses/2026-08-frontend-scaling-cross-workload/notes/scratchpad-prototype.md`)
demonstrated that the workload-A n^1.45 scratchpad driver is
**unattributed**, and that source-level intuition about scratchpad
has already been wrong once. Do not upgrade this PR to Level 3 on
the strength of "it's in `scratchpad/`".

## Predicted affected compiler surface

- Passes/stages expected to move: **none for valid inputs**.
- If a regression appears, it would be in the additional bounds-check
  overhead per allocation call. Bounds checks are constant-time and
  called O(B) times per plan_allocation; on n=64-body workloads that's
  hundreds to low thousands of calls — unlikely to be measurable.

## Prediction

- **Direction**: neutral.
- **Magnitude class**: none (or possibly small — <100 ms — from
  additional bounds-check overhead).
- **Reasoning**: PR is documented as validation/guard fixes with
  unchanged valid-layout behavior. The three-questions rule
  answers no on questions 2 and 3.

**Verdict class expected**: `NO_MEASURABLE_FRONTEND_IMPACT`.

## Failure modes for this prediction

- If the change accidentally rejected a valid case that used to
  work, we would see compilation FAILURE, not slowdown. The skill
  would classify as INSUFFICIENT_EVIDENCE (compile did not
  complete).
- If new validation is O(B²) per call rather than O(1), it could
  become visible at large B. Verified by inspecting the diff: all
  new checks are O(1) index comparisons.

## Confidence

**MEDIUM–HIGH**. The static analysis is well-supported by the PR
body itself, but scratchpad has a demonstrated history of surprising
measurements (see `analyses/2026-08-frontend-scaling-cross-workload/notes/scratchpad-prototype.md`).
The scratchpad-prefix-sum null result is a recent reminder to
measure, not assume — so we should target one cheap sentinel to
confirm.
