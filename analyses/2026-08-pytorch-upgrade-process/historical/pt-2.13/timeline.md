# PT 2.13 upgrade — timeline

- **PR:** [`torch-spyre/torch-spyre#3374`](https://github.com/torch-spyre/torch-spyre/pull/3374)  
  "Upgrade to pytorch 2.13", author `ani300`.
- **Merged:** 2026-07-29T17:32:57Z (one day after 2.12).
- **Head branch:** `2.13-upgrade`.
- **Diff shape:** 13 files, +788 / −556.
- **Commits (linearized):**
  - "Upgrade to pytorch 2.13"
  - "Update tests based on PT 2.13 changes for inplace ops and profiler"
  - "fix(lx): align an LX buffer's producer loop order to its consumers'"
  - "update deps to latest"
  - "Merge branch 'main' into 2.13-upgrade"

## Files touched

```
.claude/skills/project-overview/SKILL.md
docs/source/getting_started/installation.md
pyproject.toml
requirements/{build,dev,lint,run}.txt
tests/configs/upstream_tests/test_profiler_config.yaml
tests/inductor/test_inductor_ops.py
torch_spyre/_inductor/passes.py
torch_spyre/_inductor/scheduler.py
torch_spyre/csrc/spyre_tensor_impl.cpp
uv.lock
```

Only three non-mechanical files: `passes.py`, `scheduler.py`, and one
C++ file. Interesting: the 2.13 upgrade was SMALLER than 2.12 despite
carrying two substantial semantic changes.

## What triggered

Team practice + follow-through from 2.12 (@joerunde on this PR:
"torch 2.12 is dead, long live torch 2.13 😉!"). Merged one day after
2.12.

## Consequences that surfaced in the PR

### VERSION_BOOKKEEPING + LOCKFILE_REGENERATION (mechanical)

Same shape as 2.12.

### CXX_ABI_BREAK — `pyobj_slot_.load_pyobj_interpreter()` removed

**Delta.** PT 2.13 removed `c10::impl::PyObjectSlot::load_pyobj_interpreter()`
and replaced it with `c10::impl::getGlobalPyInterpreter()`.

**Impact.** `torch_spyre/csrc/spyre_tensor_impl.cpp:253` broke at build
time.

**Fix (one line, byte-identical to what our F6 case independently
derived):**

```diff
-    auto r = pyobj_slot_.load_pyobj_interpreter()->detach(this);
+    auto r = (*c10::impl::getGlobalPyInterpreter())->detach(this);
```

Category: `CXX_ABI_BREAK` — specifically a C++ API rename with no
transitional shim.

**Independent-derivation datum for `torch-spyre-forward-compat`.**  
Our historical-replay case
`cases/historical-replay-pt213/F6-pyobj-slot-api-rename-independently-derived.md`
recorded this in advance: given only the pre-upgrade tree and torch
2.13.0, the forward-compat skill produced this exact one-line diff by
inspecting the missing symbol. That's a full "the skill would have
saved this manual step" datapoint.

### INDUCTOR_SEMANTIC_BREAK — LX producer loop-order (SILENT WRONG RESULTS)

**Delta.** PT 2.13's `Scheduler._try_reorder_loops_for_candidates`
computes a loop reorder for candidate fusions and then DISCARDS it.
Through 2.12 the reorder was applied — so an LX-pinned buffer whose
producer walked the buffer in a different dim order than its
consumers read it got its clone silently re-ordered into the
consumers' order.

**Impact.** Under 2.13, that accidental correctness disappears. Two
reductions sharing one LX-pinned buffer read a different core's data
than what the producer wrote. `core_to_slice_mapping` hands out
`core_id` strides in iteration-space order, so the split factors
still multiply to the same core count — nothing downstream complains
— each core just returns the wrong data. **Silent wrong result.**

**Fix.** New `align_lx_producer_loop_order` pass in
`torch_spyre/_inductor/scheduler.py`, added to `CustomPreFusionPasses`
in `passes.py` BEFORE `build_loop_scheduler_nodes` (needs plain
SchedulerNodes, not `CountedLoopSchedulerNode` wrappers).

@ani300 in review response, when @thoangtrvn asked "Is this required
for PT 2.13 update, or it should be in a proper PR?": **"required for
PT 2.13, otherwise CI is not green."**

Category: `INDUCTOR_SEMANTIC_BREAK` +
`SILENT_CORRECTNESS_CHANGE`. Discovered via failing tests (with the
existing test coverage), not via a warning or exception. The commit
message body explicitly names this as an accidental-correctness case
that had held since forever and only surfaced in 2.13.

This is the exemplar case the taxonomy needs: no API changed shape,
no signature drifted, no warning fired — the upstream INTERNAL rewrite
of loop orders was doing invisible work for us.

### PROFILER_CHANGE — inplace-op / profiler test updates

Commit "Update tests based on PT 2.13 changes for inplace ops and
profiler" — updated `tests/inductor/test_inductor_ops.py` and
`tests/configs/upstream_tests/test_profiler_config.yaml`. Detail scope
is 2.13's profiler API polish, follow-on from 2.12's PrivateUse1
profiler introduction.

Category: `PROFILER_CHANGE` +
`TEST_EXPECTATION_CHANGE`.

### CI_INFRASTRUCTURE_CHANGE — upstream tests enablement

@ashokponkumar: "@seshapad Can we use Supraja's help to get pytorch
2.13 upstream tests enabled? cc: @kmehant" — the upstream-test
configuration for a new PT version is NOT automatic; the team
explicitly requested infrastructure work to add 2.13 to the upstream
suite.

Category: `CI_INFRASTRUCTURE_CHANGE`.

### DOWNSTREAM_DEPENDENCY (implicit) — vLLM path already unblocked

No blocking discussion this time; spyre-inference#357 (from the 2.12
timeline) had already removed the vLLM CPU-wheel dependency. Path
stays clear because a prior architectural change removed the coupling.

## Bundled work

- `.claude/skills/project-overview/SKILL.md` — version reference update.
- "update deps to latest" commit — the dependency-pass excuse pattern
  repeats.

## Criteria used to say "ready to merge"

@thoangtrvn: "any blockers other than this code changes?"  
@ani300: "at this point it's ready to merge!"

- CI green requirement was NOT waived — the LX loop-order fix was
  admitted specifically because "CI is not green" without it.
- Merged 1 day after 2.12. Very fast cadence.
- No explicit gate on downstream projects (already unblocked).

## Extra evidence

- **F3 was NOT introduced in this PR.** F3 (the REVERSE_ENTRYPOINT_HAZARD
  in `torch_spyre/__init__.py`) exists on 2.11, 2.12, and 2.13 —
  we tested that in earlier third-clean-run work. It's not a
  PyTorch-version consequence at all.
- **F8 was NOT introduced in this PR.** F8 (FallbackKernel single-tensor
  direct-output layout) is a torch 2.15-nightly future change that
  torch-spyre's `propagate_layouts.py` doesn't yet handle. Not a PT 2.13
  concern; it's the NEXT torch's problem.

## Time from PR open to merge

Order of days. Fastest of the three upgrades (2.11 spent weeks waiting
on multi-arch infra; 2.12 was a large PR with heavy review; 2.13 came
right on 2.12's heels with a much cleaner story).
