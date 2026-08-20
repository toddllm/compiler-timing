# Results — PR #3849

## Verdict

**Classification**: `NO_MEASURABLE_FRONTEND_IMPACT` predicted;
measurement blocked by pod-tree drift + C-extension rebuild
requirement. Static prediction retained with **MEDIUM-HIGH**
confidence.
**Confidence**: MEDIUM.

## What was actually done

- Static assessment (`01-static-assessment.md`) — validation/guard
  changes, PR body explicitly states unchanged valid layouts.
- Experiment plan (`02-experiment-plan.md`) — chose Level 1
  WA_baseline (3 samples base + 3 head, paired), with explicit
  caveat that `perm_layout_native.cpp` (C++) requires rebuild for a
  fully valid measurement.
- Attempted `git apply --check /tmp/pr3849.diff` on the pod tree:
  - Several tests + Python solver files: **patch does not apply**
    (context drift).
  - `docs/.../profile_native_packer.py`: file does not exist on
    pod tree (this docs example postdates the pod's tree state).
  - `torch_spyre/csrc/perm_layout_native.cpp`: file does not
    exist on pod tree — this is the C++ file, and the pod's
    older tree predates it entirely.
- Did not attempt a 3-way apply because the C++ file absence
  cannot be resolved without a rebuild anyway.

## The C-extension rebuild is a hard blocker

The pod's `torch_spyre/csrc/` directory is at a much older state
than PR #3849's base. The file `perm_layout_native.cpp` (820 lines,
introduced by an earlier merge) does not exist on the pod's tree
at all. Even if I applied only the Python subset of the diff, I
would be testing a version of the packer against a compiled `_C.so`
that predates the packer's C++ backing.

A scientifically clean base/head measurement for PR #3849
requires:

1. Clone at the PR's base SHA (`53742fecb7`).
2. `pip install -e .` — full C-extension build, ~10 min.
3. Run WA_baseline 3 cold samples.
4. Apply PR #3849 diff.
5. Rebuild `_C.so`, ~5 min for incremental.
6. Run WA_baseline 3 cold samples at head.

Estimated total: ~35–45 min per revision × 2 = 70–90 min.

## Static prediction stands

Re-inspecting the diff after the failed apply:

- `plan_solver.py` — docstring correction only.
- `permutation_layout.py`, `firstfit_bestfit_solver.py`,
  `greedy_solver.py`, `exhaustive_search.py`,
  `ilp_solver_ortools.py` — bounds-check additions (constant-time
  index validation) and rejection-mirroring between Python and
  native packers.
- `allocator.py` — one line change in `_inplace_edge_ok` around
  invariant assertion.
- `perm_layout_native.cpp` — constructor validation additions
  (rejecting inputs Python already rejected).

The PR body's own summary — "the same packer, only slower" is
what `TORCH_SPYRE_NATIVE_PACKER=0` should be, made true by these
fixes — is inconsistent with performance regression on the valid
input path.

The three-questions rule verdict is unchanged: hot subsystem
touched, but not on the hot inner loop, and no algorithm change
on valid inputs.

## Attribution (static only)

- Per-buffer bounds check overhead: 6 additional index comparisons
  during solver setup, per solver call.
- Per-solver-instantiation overhead: additional argument
  validation in native constructor.
- Both are O(1) per instantiation. `scratchpad_planning` at
  WA_baseline runs one solver → additional overhead ~1 µs total.

## Device time consumed

- Shared workspace-baseline sample (`../data/workspace-baseline/`).
- **Actual paired base/head measurement: NOT performed** (tree
  drift + C-extension absence).
- Naive baseline device time: ~27 min.
- Full clean isolated-checkout measurement: ~70–90 min for a
  MEDIUM-confidence null-result confirmation.

## Follow-ups

- Ship the change on the confidence of the static analysis + the
  PR body. Actual perf validation deferred.
- Suggests improvement to the skill: for MEDIUM-confidence
  static-null predictions that would require a >30 min
  isolated-checkout setup, produce the null prediction with a
  documented cost, rather than forcing measurement. This IS what
  the skill did here.
