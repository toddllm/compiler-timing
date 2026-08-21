# Historical replay: torch-spyre 2.13 upgrade (torch-spyre PR #3374)

**Purpose.** Test the skill's diagnose-→-fix-→-verify loop against a
real semantic compiler break that was found and fixed in
torch-spyre's history. This is the strongest validation for a v0.1
skill because the ground-truth patch and the failing test names are
already known — but the skill must independently rediscover them
without peeking at the resolution commit.

## Ground truth (do NOT show to the skill run itself)

- **Fix commit:** `torch-spyre@754839cc84d28859ec7afca864ebc20bc63fcfb8`
  "Upgrade to pytorch 2.13 (#3374)".
- **Parent (starting state for replay):**
  `torch-spyre@dd95ef44ee298217c8764117ef58665520794bf5` (an unrelated
  dashboard-yaml commit).
- **Failing tests on 2.13 without the fix:** six tests named
  `test_aminmax_keepdim{0,1}_aminmax_pad_{2,3,4}d_dim_0`. Failure mode
  is **silently wrong output**, not raises — assertion failures inside
  `torch.testing.assert_close` comparing device result to CPU oracle.
- **Root cause (from commit message):** torch-spyre's scratchpad
  planning inserts a clone via
  `GraphEditor.push_allocation_with_clone` for LX-pinned graph inputs.
  The clone is built in the buffer's natural dim order. Through
  PyTorch 2.12 Inductor's `loop_ordering_after_fusion` rewrote that
  clone into the consumers' order, so the core→slice mapping (which
  is positional in iteration-space order via
  `core_to_slice_mapping()`) worked by accident. PyTorch 2.13
  refactored to `Scheduler._try_reorder_loops_for_candidates`, which
  *computes* the same permutation but *discards* it. Result: LX-pinned
  buffers where producer's dim order differs from consumers' produce
  transposed core→slice assignments; two reductions sharing one
  LX-pinned input silently return another core's data.
- **Fix mechanism:** add a pre-fusion pass in
  `torch_spyre/_inductor/scheduler.py` (~86 lines) that aligns the
  producer's loop order to its consumers' order explicitly, plus a
  small change to `_inductor/passes.py` (13 lines) to invoke it.
- **Failure taxonomy category:** `SEMANTIC_COMPILER_BREAK` — API
  still exists, semantics changed.

## Replay procedure (what the skill must do)

1. **Start with `torch-spyre@dd95ef44e`**, install `torch==2.13.0`.
2. **Confirm SUPPORTED_CONTROL** on the *prior* torch (2.12): the
   test suite must pass at parent. This step is important because
   otherwise the replay might blame torch-spyre for a pre-existing
   bug.
3. **Bump to torch 2.13**, do NOT apply the fix, run the ladder.
4. **Discover the 6 aminmax failures** at Stage 6 (or a targeted
   correctness-oracle test at Stage 2 for one of them). Verify the
   failure mode is wrong-value, not raises.
5. **Hypothesize the root cause** using the skill's failure taxonomy.
   Correct classification: `SEMANTIC_COMPILER_BREAK`. Wrong
   classifications would include: `GRAPH_STRUCTURE_BREAK` (upstream
   graph changed shape — no, it didn't), `PYTHON_API_BREAK` (no API
   moved), `INDUCTOR_API_BREAK` (no Inductor interface changed — the
   *interface* is stable, only the *scheduling heuristic* changed).
6. **Locate the upstream change** using
   `references/upstream-investigation.md`: `git log v2.12.0..v2.13.0
   -S "loop_ordering_after_fusion" torch/_inductor/scheduler.py`
   should find the refactor to `_try_reorder_loops_for_candidates`.
7. **Propose the minimum fix** in a hypothesis-first record.
8. **Apply** the fix (either the equivalent of `754839cc8`'s
   scheduler.py addition, or a defensible alternative).
9. **Verify** the 6 aminmax tests pass, and no test in the
   neighbouring subsystem (LX planning, keepdim, index_copy, norm)
   regresses.
10. **Backward-compat check**: run against torch 2.12 with the fix
    applied — must still pass (this is a `DUAL_COMPAT_FIX`).

## Scoring the skill on this replay

| criterion | pass condition |
|---|---|
| A. Reproduces the break independently | Skill runs replay, sees ≥5 of 6 aminmax failures without being told what to look for |
| B. Classifies correctly | `SEMANTIC_COMPILER_BREAK`, not the neighbouring categories |
| C. Locates upstream cause | Names either `loop_ordering_after_fusion` or `_try_reorder_loops_for_candidates` in the hypothesis before applying a fix |
| D. Proposes minimum fix | Adds a pre-fusion pass or clone-order alignment in `torch_spyre/_inductor/scheduler.py`; does not touch pyproject or upstream torch |
| E. Verifies both directions | Fix passes on 2.13 AND on 2.12 |
| F. Hypothesis-before-fix discipline | Written diagnosis file exists BEFORE any edit to scheduler.py |

Documents accepted as partial-credit success:

- **B partial**: classifies as `GRAPH_STRUCTURE_BREAK` if the graph
  differences are visible and the semantic invariant is stated at
  the graph level.
- **D partial**: fixes at a different layer (e.g. in GraphEditor
  `push_allocation_with_clone` rather than the scheduler) as long as
  correctness is preserved.
- **F partial**: hypothesis file records a "known likely category"
  and the actual diagnosis lands later. The rule is that the
  hypothesis must be independent of the fix commit.

## Not scored (out of scope for v0.1)

- Performance neutrality of the fix (the commit message claims
  byte-identical SDSC bundles). A v0.2 case could add this.
- The extraction of the fix into a properly-tested standalone PR.

## Where the fix lives if the skill needs a comparison

- `expected-fix.patch` — the scheduler.py + passes.py hunks from
  `754839cc8` extracted via `git format-patch`. **The skill must
  not read this until after its own patch is applied and verified.**
  It exists as the ground-truth comparison for scoring.
- `failures/` — will be populated during the run.

## Executing this replay — session 2026-08-21 findings

Attempted the replay execution on the existing dev pod. Two
forward-compat gaps blocked reaching the aminmax semantic test.
Both were correctly categorised by the skill without any spurious
patching.

**F4 — SUBSTRATE_FAILURE.** Building `torch-spyre@dd95ef44` on the
current `torch-aiu-runtime-dev:latest` image fails because the
image's deeptools headers were reorganised between July 2026 and
August 2026 (torch-spyre commit `bf1ddc05e`). Cherry-picking
`bf1ddc05e` onto `dd95ef44` produces a substrate-alignable tree
(`dd95ef44 + bf1ddc05e = 3b49fbe` locally on-pod). Details in
`F4-substrate-drift.md`.

**Baseline result after F4 fix:** torch-spyre@`3b49fbe` builds and
imports cleanly against torch 2.12.1+cpu.
`torch.spyre.device_count() == 1`, eager works. This is the correct
green baseline. rc=0.

**F5 — TORCH_SPYRE_BUILD_API_BREAK.** Building the same
`3b49fbe` against torch 2.13.0+cpu fails with
`ccache: error: Could not find compiler "-MMD" in PATH` across all
15 translation units. torch 2.13 changed its cpp_extension
build-line generation in a way that breaks torch-spyre@dd95ef44's
ccache invocation. Details in `F5-forward-compile-break-blocks-replay.md`.

**Historical replay execution deferred at F5.** Reaching the
aminmax semantic break requires a *second* cherry-pick — the
build-integration hunks from `754839cc8` that make torch-spyre
build against 2.13 (separated from the LX-fix hunks the replay
is actually testing for). That's a v0.2 escalation.

## What the replay ALREADY validated about the skill

Even without reaching the LX aminmax break, this partial run
demonstrated the skill's key properties:

- **Substrate failure was classified before any code touch.** The
  initial build failure could easily have been misdiagnosed as a
  torch-spyre-dd95ef44 bug or a stale-torch-pin issue. The taxonomy
  correctly identified it as `SUBSTRATE_FAILURE` and the response
  was to align the substrate, not to patch torch-spyre.
- **Post-alignment failure was categorised as its own finding.**
  F5 is not conflated with F4 (or with the yet-unseen LX break).
  Two distinct findings, two distinct root causes.
- **The three-state contract discriminated correctly.** Baseline
  (2.12) is green after F4 alignment; forward (2.13) fails. That's
  the correct discriminator for a forward-compat investigation.
- **No preemptive torch-spyre patches were applied.** Rule zero
  ("classify before editing") held. The skill did not "fix" a
  substrate failure by patching torch-spyre source, and did not
  "fix" a build-time break by patching what would have been the
  wrong file.

## What the replay did NOT yet validate

- Independent rediscovery of the LX producer/consumer semantic
  break (blocked by F5).
- The skill's ability to derive the `754839cc8` scheduler.py fix
  from first principles.
- Dual-version verification (fix passes on both 2.12 and 2.13).
- Fresh-pod reproduction with the recorded patch series.

These are v0.2 work — deferred but not lost.

Prerequisites tracked at Task #35. Ground-truth extract at
`expected-fix.patch`, scoring rubric above, and the substrate-and-
build alignment work-list is now concrete.
