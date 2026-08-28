# `dedup_and_promote_constants` — Phase 4: upstream PR preparation

**Status: preparation complete; PR NOT yet opened. All artifacts
ready for review at `upstream-prep/`.**

Companion to `notes/dedup-phase3-conclusion.md`. Phase 3 established
that shipping E-only is the right call. Phase 4 addresses the three
things that had to be tightened before the change becomes an
upstream PR: the semantic discrepancy in the reverse-index builder,
rebasing onto current torch-spyre `main`, and precision of the
complexity claim.

## What changed since Phase 3

### 1. Reverse-index de-duplication within an op's read set

**Discrepancy identified.** The pristine algorithm patches an op
at most once per duplicate:

```python
rw = op.get_read_writes()
if not any(dep.name == D for dep in rw.reads):
    continue
_patch_inner_fn(op, {D: C})
```

The Phase 3 reverse-index builder appended `op` for every matching
dep in `op.get_read_writes().reads`. If a single ComputedBuffer's
inner_fn happens to `ops.load(D, ...)` at two different indices,
`rw.reads` contains two distinct MemoryDep objects with the same
`.name` and the op would appear TWICE in `consumers_by_name[D]`.
`_redirect_consumers` would then patch that op twice with the same
name-map — semantically harmless (the second NameSwapHandler stacks
on the first and translates the same key the same way) but not
exact preservation.

**Fix**: use a per-op set of matched names.

```python
matched_names: set[str] = set()
for dep in op.get_read_writes().reads:
    if dep.name in duplicate_names:
        matched_names.add(dep.name)
for name in matched_names:
    idx[name].append(op)
```

Now each op appears at most once in `consumers_by_name[name]`
regardless of how many distinct dep objects share a name.

**Regression coverage.** Four new unit tests in
`tests/inductor/test_dedup_constants_more.py::TestBuildReverseConsumerIndex`:

- `test_op_with_two_deps_same_name_appears_once` — the exact
  case above. Constructs a fake op whose `get_read_writes()`
  returns two dep objects with the same `.name`; asserts the
  reverse index lists that op once.
- `test_op_with_two_deps_different_names` — reads to D1 and D2
  from same op → single entry in each of `consumers_by_name[D1]`
  and `consumers_by_name[D2]`.
- `test_op_with_no_duplicate_reads_absent_from_index` — non-
  duplicate names don't leak into the index.
- `test_multiple_ops_deterministic_order` — ops appear in
  `graph.operations` order.

All four pass.

### 2. Rebased onto current torch-spyre `main` (`813a298`)

Current main SHA at time of prep:
`813a2980dbd9d2e84f5006b9cde2f305e679fc71`
(commit "fix(ci): pass --allow-escape-sequences when downloading
GHA job logs (#4091)", 2026-XX-XX).

Between the Phase 3 baseline `a9316b381` (PR #3806 head) and
current main, `dedup_constants.py`'s only functional change is
the `NameSwapHandler` import location: it moved from
`torch_spyre._inductor.insert_restickify` to
`torch_spyre._inductor.pass_utils`. All the surrounding pass
mechanics are unchanged. Verified by `git diff a9316b381..813a298
-- torch_spyre/_inductor/dedup_constants.py` — the only lines
different are those two import lines.

The production file at `upstream-prep/dedup_constants.py`
targets current main (imports from `pass_utils`). For
validation on the pod's `a9316b381` tree we used a dual-import
shim; the resulting behavior is identical.

### 3. Complexity language corrected

Not claimed:
> "E-only makes the pass O(N)."

Claimed instead:
> The dominant consumer-discovery term changes from ~D full
> scans of `graph.operations` (each calling `op.get_read_writes()`
> on every op) to a single scan. `get_read_writes()` calls fall
> from approximately N×D to N. The per-duplicate
> `operations.remove(dup)` remains and is still O(N×D) overall;
> its measured cost is 0.02–0.03% of pristine pass time and is
> intentionally not batched in this change.

Applied in `notes/dedup-phase2-plan.md` (Section D
"Option E delivers…" and the F "Goal" block), and the phase-3
conclusion + the PR body + the commit message all use this
narrower phrasing.

**Test count** in the phase-3 conclusion "Content: exactly the
E-only diff plus the deterministic new tests" line was corrected
to include both the five pass-level tests AND the four unit
tests over `_build_reverse_consumer_index`.

## Validation summary

All against the pod's `a9316b381` torch-spyre tree with the
production `dedup_constants.py` (dual-import shim for
`NameSwapHandler`).

### Test execution — 16/16 pass, zero skips

- `tests/inductor/test_dedup_constants.py`: 5 tests pass
  (pristine coverage, unchanged).
- `tests/inductor/test_dedup_constants_more.py`: 9 tests pass
  (5 pass-level + 4 unit).
- `tests/inductor/test_padding.py::test_padding_constants_deduped`:
  1 test pass (end-to-end correctness vs CPU).
- `tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash`:
  1 test pass (the actual PR #3806 workload; 104.17s cold).

Full output at `data-prod-perf/pytest-output.txt`.

### Semantic equivalence — EQUIVALENT

Fresh Lq=512, Lk=1024 capture on the production tree
(`data-semantic-prod/state-E-prod-512x1024.json`) vs pristine
`a9316b381` (`data-semantic-prod/state-pristine-a9316b3-512x1024.json`)
using the same normalized-state comparison as Phase 3:

```
$ python3 patches/diff_semantic_state.py \
    data-semantic-prod/state-pristine-a9316b3-512x1024.json \
    data-semantic-prod/state-E-prod-512x1024.json
EQUIVALENT — no semantic differences detected.
```

### Cheap perf reconfirm — passes

3 cold DIAG-OFF samples at Lq=512, Lk=1024 with the production
tree:

  run1  run2  run3  median
  55.06 56.06 56.43 **56.06 ms**

Consistent with the Phase 3 E-only measurement (60.0 ms
median). About 7% faster than Phase 3, within normal day-to-day
pod variation; the production version drops the `_diag_record`
kwarg-threading present in Phase 3's instrumented version, so a
tiny improvement is plausible.

A 512×8192 sample was attempted but the Spyre device threw a
hardware `RAS::PCI::BusFence` unrelated to the code change.
Phase 3's 3-sample Lk=8192 measurement (492.5 ms median) already
covered that point; no reason to rerun. Documented in
`data-prod-perf/results.md`.

## Upstream PR artifacts

`upstream-prep/` contains everything needed to open the PR:

- `dedup_constants.py` — production file targeting current main
  (imports from `pass_utils`).
- `dedup_constants.diff` — the diff against pristine
  `dedup_constants.py` at `813a298`. 148 lines. Reads cleanly.
- `PR-title.txt` — one-line title.
- `PR-body.md` — full PR body, mechanism-first, then measured
  numbers and evidence pointers.
- `commit-message.txt` — full commit message (subject + body).
- `whole-compile-perspective.md` — end-to-end framing so the PR
  doesn't oversell the pass-local ratio.
- `branch-prep.sh` — the exact script to create the branch,
  copy the three files (dedup_constants.py, tests, test config),
  and commit. Does NOT push. Does NOT open a PR.

The PR is deliberately NOT opened yet. When you're ready:

1. On a machine with a torch-spyre fork remote, run
   `upstream-prep/branch-prep.sh`.
2. Review `git log --oneline -3` and `git show HEAD`.
3. Push to your fork: `git push <fork> tdeshane/dedup-reverse-consumer-index`.
4. Open the PR via `gh pr create` with title from PR-title.txt
   and body from PR-body.md.

## What is NOT in the upstream PR

Deliberately excluded:

- **Batch removal.** Phase 3 measured within-noise; ships as a
  separate change if desired. Sketch preserved in
  `patches/dedup_constants_E_plus_batch.py`.
- **Diagnostic instrumentation.** The reference E-only file at
  `patches/dedup_constants_E_only.py` carries the diagnostic
  wiring for measurement; the production file at
  `upstream-prep/dedup_constants.py` has it stripped.
- **Any upstream Inductor change.** Notably, no attempt to teach
  `register_users_of` to walk decomposed lowerings.
- **The output-name skip behavior** in `_redirect_consumers` where
  an output-name duplicate is skipped for redirect but its
  bookkeeping still runs. Preserved verbatim; worth a separate
  investigation.
- **`tests/inductor/test_dedup_constants.py`** existing tests:
  unchanged.

## Remaining hypotheses

Same list as Phase 3 §5, unchanged by this phase:

1. `f_grw` per-call cost on other workloads.
2. `_maybe_scratchpad_planning` sensitivity to
   `name_to_users` state.
3. Downstream noise (`optimize_restickify_locations` −15.5% in
   the Phase 3 comparison; almost certainly pod-state).
4. Output-name latent behavior.
5. Upstream `register_users_of` scope.
6. Non-`test_flash` workloads.

None block landing the PR; each is a separate potential
follow-up.
