# Experiment plan — PR #3849

**Written BEFORE any measurement.**

## Level decision

- **Chosen level**: **1** (TARGETED_RUN, but with important caveat)
- **Rationale**: the static analysis is strong (validation-only
  changes on valid-input path, per PR body), but the scratchpad
  subsystem has a demonstrated history of counter-intuitive
  measurement outcomes on this codebase (see
  `analyses/2026-08-frontend-scaling-cross-workload/notes/scratchpad-prototype.md`).
  One cheap sentinel is warranted to confirm the null prediction.

### Cost caveat: C-extension rebuild

PR touches `torch_spyre/csrc/perm_layout_native.cpp`. Correct
measurement requires **rebuilding `_C.so` at both base and head**;
in-process patching would silently mix ABIs. Estimated rebuild
cost: 5-10 min per revision.

**For this validation exercise we treat the rebuild cost as a
skill decision point.** A production usage of the skill would
rebuild. For this validation, we note the cost and prefer to
measure via the pure-Python paths in the diff (5 of the changed
files are pure-Python; only `perm_layout_native.cpp` requires a
rebuild). The pure-Python changes are the bulk of the diff and
exercise the same guard-path semantics.

**Decision**: apply the pure-Python subset of the diff onto the
pod-side `torch-spyre/` checkout as a local patch and run
`WA_baseline` at head vs a fresh baseline. If the pure-Python
subset moves nothing, the C++ constructor-validation addition is
extremely unlikely to move anything either (it is a constructor
argument check that runs once per solver instantiation).

## Sentinels selected

| Sentinel | Point | Samples | Paired? | Rationale |
|---|---|---:|:---:|---|
| WA_baseline | Lq=512, Lk=1024 | 3 base, 3 head | yes (interleaved) | Cheapest scratchpad-active sentinel; workload A has non-negligible scratchpad_planning (~1 s). |

## Metrics expected to move

None. (This is the prediction.)

## Metrics expected NOT to move

- `_maybe_scratchpad_planning`
- `compile_fx_wrapper`
- All Spyre custom pass pipelines
- `dxp_standalone`
- All structural counters

## Structural counters to record

- `fx_nodes_at_entry`
- `n_specs`

## C-extension rebuild required?

- Fully validating the `perm_layout_native.cpp` change requires
  rebuild. For this validation exercise we deliberately test the
  pure-Python subset and note the C++ change was NOT rebuilt. If
  the pure-Python subset moves, the C++ change would require its
  own rebuild + sweep.

## Estimated device time

- Actual plan: 6 × 90 s = 540 s = 9 minutes (paired base/head).
- Naive baseline (WA_baseline + WB_scaling_pair, 3+3 each): 27
  minutes.
- Device time saved by targeted selection: ~18 minutes.
