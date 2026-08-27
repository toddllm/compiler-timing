# Test execution evidence — Commit A

Executed on pod `tdeshane-compiler-timing-dev-v2` (RHEL 9.6, Python
3.12.13, torch 2.13.0+cpu, torch-spyre @ `a9316b381`).

`dedup_constants.py` in the pod tree is the diagnostic-patched
version from earlier, but `TORCH_SPYRE_DEDUP_DIAG` is UNSET for
this run, so the diag paths are inert and the semantics are
identical to pristine `a9316b381`.

```
$ python -m pytest tests/inductor/test_dedup_constants.py \
                   tests/inductor/test_dedup_constants_more.py \
                   tests/inductor/test_padding.py::TestInsertPaddingIR::test_padding_constants_deduped \
                   -v -p no:logging

============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/tdeshane/pr3806/torch-spyre
configfile: pyproject.toml
plugins: xdist-3.8.0, anyio-4.14.0
collected 11 items

tests/inductor/test_dedup_constants.py::TestDedupConstants::test_constants_at_front PASSED [  9%]
tests/inductor/test_dedup_constants.py::TestDedupConstants::test_dedup_across_same_dtype_pad_sequences PASSED [ 18%]
tests/inductor/test_dedup_constants.py::TestDedupConstants::test_different_dtype_constants_not_merged PASSED [ 27%]
tests/inductor/test_dedup_constants.py::TestDedupConstants::test_no_orphans_in_name_to_buffer PASSED [ 36%]
tests/inductor/test_dedup_constants.py::TestDedupConstants::test_surviving_constant_at_index_zero PASSED [ 45%]
tests/inductor/test_dedup_constants_more.py::TestDedupConstantsPassLevel::test_name_to_users_fold_exact PASSED [ 54%]
tests/inductor/test_dedup_constants_more.py::TestDedupConstantsPassLevel::test_no_duplicates_fast_path PASSED [ 63%]
tests/inductor/test_dedup_constants_more.py::TestDedupConstantsPassLevel::test_one_duplicate_many_consumers PASSED [ 72%]
tests/inductor/test_dedup_constants_more.py::TestDedupConstantsPassLevel::test_provenance_transform_appended PASSED [ 81%]
tests/inductor/test_dedup_constants_more.py::TestDedupConstantsPassLevel::test_zero_consumer_duplicate PASSED [ 90%]
tests/inductor/test_padding.py::TestInsertPaddingIR::test_padding_constants_deduped PASSED [100%]

======================= 11 passed, 11 warnings in 16.42s =======================
```

## Counts

| suite                                  | passed | failed | skipped |
|----------------------------------------|-------:|-------:|--------:|
| test_dedup_constants.py (pristine)     |      5 |      0 |       0 |
| test_dedup_constants_more.py (new)     |      5 |      0 |       0 |
| test_padding.py::test_padding_constants_deduped (E2E) | 1 | 0 | 0 |

## New tests — what each locks in

`test_zero_consumer_duplicate` — a duplicate whose live readers have
been artificially removed from `graph.operations` is still cleanly
removed by dedup: absent from operations, its buffer name is in
`removed_buffers`, absent from `name_to_buffer`, its operation
name is absent from `name_to_op`, and its buffer name is absent
from `name_to_users`. Canonical survives.

`test_one_duplicate_many_consumers` — we artificially attach a
second live `ComputedBuffer` reader to the same duplicate name D
(by wrapping its inner_fn with a `NameSwapHandler({C: D})`), so
BOTH reader ops have live reads that include D. After dedup neither
reads D and both read the canonical C.

`test_name_to_users_fold_exact` — pre-dedup `name_to_users[C]` and
`name_to_users[D_i]` are captured by object identity. After dedup:
`name_to_users[C]` equals the exact identity-preserving
concatenation `pre_C + [entry for D in dups for entry in pre_D_entries[D]]`,
and every `D_i` key is absent from `name_to_users`.

`test_provenance_transform_appended` — the canonical constant's
`_spyre_prov_history` gains exactly (n_dups_in_group)
`ProvenanceTransform` entries with `kind="fusion"`,
`pass_name="dedup_and_promote_constants"`,
`reason="duplicate constant"`.

`test_no_duplicates_fast_path` — with a workload that produces NO
multi-constant group, `dedup_and_promote_constants` makes ZERO
`ComputedBuffer.get_read_writes` calls. This test locks in the
fast-path invariant that must survive the E-only refactor.

## How determinism is enforced

Rather than relying on Dynamo/Inductor producing a particular
incidental graph shape, each test:

  1. Uses a `_StopBeforeDedupPasses` subclass of
     `CustomPreSchedulingPasses` that runs the real pipeline up to
     (but not including) `dedup_and_promote_constants`, then hands
     control to the test callback.
  2. The callback identifies the actual duplicate group produced by
     the real pipeline (asserting `len(multi) >= 1`), then, where
     necessary, mutates state to construct the exact condition each
     test needs (dropping consumers to make a zero-consumer dup,
     re-wiring an existing consumer to add a second reader of D).
  3. The callback then invokes `dedup_and_promote_constants(graph)`
     directly, snapshots the resulting state, and asserts.
  4. Downstream passes are NOT run (the callback returns `False`
     to short-circuit the pipeline); the harness catches the
     compile-time `InductorError` this eventually produces and only
     re-raises if the test's own assertions never ran.
