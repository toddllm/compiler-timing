# PR #4113 — review response record

Will's review:
[torch-spyre#4113 review 5052707164](https://github.com/torch-spyre/torch-spyre/pull/4113#pullrequestreview-5052707164)

Response commit + PR comment:
- head: `659f4f256e67f214cc5f6a3f838fda480815623f`
- previous head: `ce34227eb162d5a622cb3946c1dcbdce97b6766a`
- reply comment: https://github.com/torch-spyre/torch-spyre/pull/4113#issuecomment-5455343591

## Independent reproduction

Will independently reproduced the optimization against
torch-spyre `main@faff191` (newer than the PR's base `813a298`):

| N ops | D | pristine calls | PR calls | ratio |
|------:|--:|---------------:|---------:|------:|
| 17    | 2 |             28 |       14 |   2.0 |
| 29    | 4 |             96 |       24 |   4.0 |
| 53    | 8 |            352 |       44 |   8.0 |
| 101   |16 |          1,344 |       84 |  16.0 |

Ratio exactly equals D at every point, and post-dedup state
matches across all eight fields the PR body claims. 9/9 new
tests pass; 5 existing dedup tests and `test_padding_constants_deduped`
pass with the PR pass in the pipeline.

## Blockers addressed

### B1 — regression guard for the optimization

Added `TestDedupConstantsPassLevel::test_reverse_index_scales_with_N_not_D`.

Builds a duplicate-bearing graph (three unaligned bmms → dedup
group of ≥3 → D≥2), counts `ComputedBuffer.get_read_writes` calls
during `dedup_and_promote_constants` via
`patch.object(ComputedBuffer, "get_read_writes", counted_grw)`,
and asserts:

- `calls <= n_ops_at_entry`
- `calls > 0`

A regression that rebuilds the reverse index inside the
per-duplicate loop would raise the count to ~N×D.

**Verified locally** that the guard catches the regression:
applied a synthetic "rebuild reverse index inside the
per-duplicate loop" patch on the pod, ran only this test, and it
failed with:

```
28 not less than or equal to 17 : regression guard: dedup called
ComputedBuffer.get_read_writes 28 times on a graph with 17 ops at
pass entry. A single-sweep reverse-index build should make at most
one call per op. A count materially larger than N suggests the
index is being rebuilt per duplicate (regression).
```

Then restored the good file and it passes.

### B2 — same-group multi-duplicate behavioral test with real IR

Added
`TestDedupConstantsPassLevel::test_one_consumer_reads_two_duplicates_same_group`.

Runs three unaligned bmms to produce a dedup group of size 3
(canonical + dup1 + dup2). In the callback finds a live
`ComputedBuffer` that reads `dup1` and wraps its `inner_fn` with
a real `NameSwapHandler({C: dup2})` so its live
`get_read_writes` reports both `{dup1, dup2}` before dedup. Runs
`dedup_and_promote_constants` and asserts that after dedup:

- `dup1` absent from the consumer's live reads
- `dup2` absent from the consumer's live reads
- canonical `C` present
- both `dup1` and `dup2` removed from `graph.operations`
- canonical survives

No mocks. Real `ComputedBuffer`, real `NameSwapHandler`, real
`_patch_inner_fn`, real `dedup_and_promote_constants`.

This is the case Will identified where a live-rescan
implementation would still find and patch the consumer for `dup2`
after the `dup1` rewrite. The snapshot approach used in this PR
patches the consumer twice from a single pre-redirect scan and
the two `NameSwapHandler` layers compose (each translates its
own key at codegen). Semantically indistinguishable from
live-rescan on this case, matching Will's independent
reproduction.

## Suggestions applied (all)

1. **`defaultdict` → `dict` return.**
   `_build_reverse_consumer_index` now returns `dict(idx)`.
   Added `test_returned_mapping_is_plain_dict_not_defaultdict`
   which asserts:
   - the returned mapping is not a `defaultdict`
   - `idx["absent"]` raises `KeyError`
   - `idx.get("absent")` does not install the key

2. **Output-name filter at index construction.**
   `dedup_and_promote_constants` now excludes duplicates whose
   name is in `V.graph.get_output_names()` from `duplicate_names`
   before building the reverse index.
   Behavior-preserving: pristine `_redirect_consumers` already
   skipped such duplicates; indexing consumers for them was work
   the pass never performed. `_drop_constant` continues to run
   on output-name duplicates in Step 2 exactly as before. The
   separately-known
   `_redirect_consumers`-skip-but-`_drop_constant`-still-runs
   question is intentionally not touched in this PR.

3. **Index-freshness contract in docstring.**
   Rewrote `_redirect_consumers`' docstring to state the
   freshness precondition in terms of "the reverse index built
   by `_build_reverse_consumer_index` from a single sweep of
   `graph.operations` taken immediately before this pass's
   redirect loop begins," not in terms of a caller-local
   variable name. Explicitly describes the multi-duplicate
   composed-`NameSwapHandler` case.

4. **Test-harness sentinel exception.**
   Added `_TestStopSignal(Exception)`. Each pass-level callback
   raises it after its assertions. `_DedupTestBase._drive`
   catches only that sentinel (walking `__cause__`/`__context__`
   since dynamo/inductor wraps user exceptions in
   `InductorError`); any other exception propagates. No more
   broad exception swallowing; `assertions_ran["ok"]` is gone.

5. **Fixture-shape assertion messages.**
   Every incidental
   `assertGreaterEqual(len(constants), N)` /
   `assertTrue(multi)` / `assertFalse(multi)` now uses
   `"PRECONDITION: ... Not a dedup failure — fixture shape
   changed."` in the failure message. Still hard-fails; no
   `skipTest` added, so coverage stays honest.

6. **File merged.**
   `test_dedup_constants_more.py` folded into
   `test_dedup_constants.py`. Removed
   `test_dedup_constants_more_config.yaml`. Structure:
     - `_DedupTestBase` — shared config patches +
       `_constants`/`_non_constants` helpers
     - `_CapturingPasses` — hook for full-pipeline tests
     - `_StopBeforeDedupPasses` — hook for pass-level tests
     - `_TestStopSignal` — sentinel
     - `TestDedupConstants` — 5 existing full-pipeline tests
     - `TestDedupConstantsPassLevel` — 7 pass-level tests
       (5 previous + B1 + B2)
     - `TestBuildReverseConsumerIndex` — 5 unit tests
       (4 previous + the plain-dict guard)
   17 tests in one file, one startup, one CI job. Ran in
   10.98 s on the pod, matching Will's timing point about
   startup dominating the previous split.

## Suggestions declined

None.

## Pod-side validation

Same environment as prior phases (torch-spyre `a9316b381` tree
with the `NameSwapHandler` `pass_utils` / `insert_restickify`
dual-import shim; body-equivalent to the PR file):

```
tests/inductor/test_dedup_constants.py                              17 pass
tests/inductor/test_padding.py::test_padding_constants_deduped       1 pass
tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash   1 pass
                                                          Total: 19 pass, 0 skipped
```

## CI on push

Workflow-level: all five workflows `success`:
`tests`, `upstream-pytorch-tests`, `linters`,
`Enforce Test CI Coverage`, `oot-config-checker-tool`. Plus DCO
success.

One initial sub-job (`run-tests / Inductor / Test Inductor Ops
Misc Shape B`, unrelated to dedup) hit a
`RAS::CBRB::ResponseTimeout` Spyre-card hardware fault. The
`tests` workflow's built-in pod-level retry re-ran the same
suite on a different pod at 16:46 UTC and it succeeded. Same
retry-covered infra-flake pattern as the first push (which had
`Test Scratchpad Solver` fail then retry-pass). `statusCheckRollup`
in the PR view still surfaces the initial FAILURE check-run by
design; workflow-level SUCCESS is what branch protection
evaluates.
