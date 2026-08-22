# F7 — LX aminmax semantic replay attempt (Todd's §7 target, partial)

**Recorded 2026-08-22.** Todd's post-F6 review asked for a stricter
reproduction of the LX aminmax semantic break: exact historical test
`test_aminmax_keepdim0_aminmax_pad_2d_dim_0`, `LX_PLANNING=1`, prove
wrong values on unpatched 2.13 before deriving a fix. This attempt got
close but did not surface the wrong-values state.

## What actually ran

Using the F3-patched live current-main setup
(`/home/tdeshane/f3-live-remediation`, torch-spyre@8aba5bc + F3 patch,
torch 2.13.0+cpu):

1. Located the test: `tests/inductor/test_inductor_ops.py::TestOps::test_aminmax_keepdim0_aminmax_pad_2d_dim_0`.
   Verified it collects via `pytest --co`. The param set is
   `INDEX_REDUCTION_KEEPDIM_PARAM_SETS["aminmax_pad_2d_dim_0"]`,
   which uses `cached_randn((63, 129), scale=0.1)` and reduces `dim=0`.
2. Installed missing test deps (pyyaml, hypothesis, numpy).
3. **Test PASSES on current main** with all its fixes intact — 41
   seconds, exit rc=0. That is the expected outcome; the LX-fix is
   part of the main tree.
4. Attempted to reproduce the semantic bug by neutralising
   `align_lx_producer_loop_order` — commented out its invocation in
   `torch_spyre/_inductor/passes.py:274`.
5. Reran the test with `LX_PLANNING=1` on the neutralised passes.py.
   **Test still passes.**

## Why the neutralisation didn't reproduce the bug

Two plausible reasons the neutralisation was insufficient:

1. **The test itself may have been hardened.** The suite may now
   include additional invariants or a different oracle that the LX
   bug still produces wrong data but the test wouldn't catch it. Or
   the test file's helper machinery may include shape-sanity checks
   that catch the wrong output before the numerical assertion runs.
2. **The specific shape `(63, 129)` may not pin the input into LX on
   this pod's configuration.** LX-pinning depends on allocator
   decisions that consider core count, tile size, and memory
   budget. `LX_PLANNING=1` enables the machinery but doesn't force
   every input into LX. If the allocator decides `(63, 129)` fits in
   HBM (or in LX in a single core's slice), the transposition
   hazard the fix guards against never fires.

The stronger reproduction would require:

- Reverting the *full* 754839cc8 (all three subcommits: pyproject
  bump, test-suite adjustments, LX fix). The pyproject bump is
  incidental; the test-suite adjustments may be the piece that
  actually detects the bad output.
- Or running an older torch-spyre SHA (pre-754839cc8) directly,
  which produces the same problem we hit as F4 (substrate drift —
  header layout has changed since then). That's why the full
  historical replay was originally deferred: it requires either an
  older image or a two-cherry-pick scaffold to make the older
  source buildable on today's substrate.
- Or explicitly force-pinning the input to LX via a helper the test
  suite has, if one exists.

## What the attempt DID validate

- The **exact test the commit message names** exists in current main
  at `tests/inductor/test_inductor_ops.py::TestOps::test_aminmax_keepdim0_aminmax_pad_2d_dim_0`.
- The test **passes on current main** (torch-spyre@8aba5bc + F3 patch,
  torch 2.13.0+cpu, `LX_PLANNING=1`) — the LX fix from 754839cc8 is
  in the tree and effective.
- **`LX_PLANNING=1` is the default** (per `torch_spyre/_inductor/config.py:22`
  which reads `os.environ.get("LX_PLANNING", "1") == "1"`). So the
  LX-planning code path is exercised even without setting the env var.
- **41-second test wall-clock** is the honest cost of running one
  aminmax reduction test through the full lowering + Spyre codegen +
  device execution pipeline on this substrate.

## Skill implication

The full historical-replay-until-wrong-values loop is beyond what
this session can reach without a stronger revert of 754839cc8. The
F6 result (byte-identical fix for the API rename) remains the
strongest single-turn demonstration of the skill's diagnose→fix→
verify loop for a real historical break.

A v0.3 or later session could pick this up by:

1. Building torch-spyre@dd95ef44 with F4+F6 patches (already scaffolded
   in `historical-replay-pt213/`).
2. Cherry-picking only the test-suite portion of 754839cc8 onto that
   tree (so the tests exist to run).
3. Running the aminmax tests without the scheduler.py hunks. Expect
   FAIL with wrong values.
4. Adding the scheduler.py `align_lx_producer_loop_order` function
   independently. Expect PASS.

## Files

- `data/aminmax_test_current_main_lx_planning.log` — pytest output
  for the current-main + F3-patched + LX_PLANNING=1 run: PASSED.
- `data/aminmax_test_neutered_alignment.log` — pytest output after
  commenting out `align_lx_producer_loop_order` in passes.py: still
  PASSED (which is why F7 is only partial).

## Rule for v0.2 taxonomy

**`SEMANTIC_COMPILER_BREAK` reproduction requires more than
neutralising the fix invocation.** The v0.2 taxonomy should note
that a semantic bug that depends on a scoring heuristic (Inductor's
`loop_ordering_after_fusion`) can be masked by other machinery even
when the load-bearing fix is disabled. To confidently reproduce a
semantic-break case, revert the entire fix commit, run against the
*prior* substrate that shipped with it, and expect specific test
failures. Otherwise the "reproduction" may silently pass.
