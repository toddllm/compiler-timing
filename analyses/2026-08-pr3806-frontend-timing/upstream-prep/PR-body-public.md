# Summary

`dedup_and_promote_constants` in `torch_spyre/_inductor/dedup_constants.py`
currently invokes `op.get_read_writes()` for every operation in
`graph.operations` **once per duplicate constant** it needs to
merge. On graphs where duplicate count grows with graph size —
which is the case for `insert_bmm_padding`'s `constant_pad_nd`
decomposition — this creates near-quadratic frontend compile
behavior in program size.

This change builds a live reverse consumer index once per pass
invocation, scoped to duplicate buffer names, and reuses it for
all duplicates. The `get_read_writes()` calls the pristine pass
made inside its per-duplicate scan happen only once per op now,
in a single sweep, and consumer discovery becomes a dictionary
lookup.

Semantically identical to the pristine algorithm on the
`tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash`
workload — verified via a normalized post-dedup state comparison
across `graph.operations`, surviving constants, `removed_buffers`,
`name_to_buffer`, `name_to_op`, `name_to_users`, per-consumer live
reads, and provenance history.

## Old vs new algorithm

Old (roughly):

```python
for group in groups.values():
    if len(group) <= 1:
        continue
    canonical = group[0]
    for dup in group[1:]:
        for op in graph.operations:            # O(N)
            if op is dup or op is canonical:
                continue
            rw = op.get_read_writes()           # not cached; walks inner_fn
            if any(dep.name == D for dep in rw.reads):
                _patch_inner_fn(op, {D: C})
        graph.operations.remove(dup)            # O(N)
```

New:

```python
# Whether Step 2 runs depends only on "does any duplicate exist?".
has_duplicates = any(len(group) > 1 for group in groups.values())

# Which duplicate names need consumer indexing. Filters out graph
# outputs -- pristine _redirect_consumers already skips those --
# so we don't widen the index for work the pass never performs.
duplicate_names = {
    dup.get_name()
    for group in groups.values() if len(group) > 1
    for dup in group[1:]
    if dup.get_name() not in V.graph.get_output_names()
}

if has_duplicates:
    # Build the reverse index only when there's a non-output
    # duplicate to redirect for; when every duplicate is a graph
    # output the index build (one get_read_writes call per op) is
    # skipped entirely -- but Step 2 still iterates so
    # _drop_constant runs for those output-name duplicates.
    consumers_by_name = (
        _build_reverse_consumer_index(graph.operations, duplicate_names)
        if duplicate_names
        else {}
    )
    for group in groups.values():
        if len(group) <= 1:
            continue
        canonical = group[0]
        for dup in group[1:]:
            _redirect_consumers(               # skips for output-name dups
                consumers_by_name.get(dup.get_name(), []),
                dup, canonical,
            )
            _drop_constant(graph.operations, dup, canonical)  # unchanged
```

The reverse-index builder de-duplicates matched buffer names
within each op's read set (using a per-op `set`), so an op whose
`.reads` contains two distinct `MemoryDep` objects sharing a name
still appears at most once in `consumers_by_name[name]`. That
matches the pristine algorithm's "patch once per (op, dup)"
behavior.

`_drop_constant`'s per-duplicate `operations.remove(dup)` is
deliberately preserved.

## Precise complexity claim

- **Consumer-discovery term** (the dominant cost) changes from
  D full scans of `graph.operations`, each calling
  `get_read_writes()` on every op, to a single scan.
- **`get_read_writes()` calls** fall from approximately `N × D`
  to `N`.
- **Per-duplicate `operations.remove(dup)`** remains, so the pass
  still has an `O(N × D)` tail from Python list removals. That
  tail was measured at ~0.02–0.03% of pristine dedup time and is
  intentionally not batched in this change.
- **Grouping** and **Step-3 front-loading** remain `O(N)`.
- **No-duplicate fast path** preserved: when no group has more
  than one entry, `has_duplicates == False` and no
  `get_read_writes()` calls are made at all.
- **All-output-duplicates path** preserved: when every duplicate
  is a graph output, `duplicate_names` is empty and the index
  build is skipped, but `has_duplicates == True` so Step 2 still
  runs `_drop_constant` on those duplicates exactly as pristine.

This is **not** a claim that the whole pass is `O(N)`.

## Work-count collapse

Measured on `TestOpSpecTiling::test_flash` at H=8, three cold
samples per point:

| point   | N    | D   | pristine `get_read_writes` calls | new calls | reduction |
|---------|-----:|----:|---------------------------------:|----------:|----------:|
| 512×1024|  276 |  16 |                            4,416 |       276 |       16× |
| 512×4096| 1092 |  64 |                           69,888 |     1,092 |       64× |
| 512×8192| 2180 | 128 |                          279,040 |     2,180 |      128× |

## Pass-local timing

Same three points, three cold samples per point:

| point   | pristine dedup | new dedup  | pass-local speedup |
|---------|---------------:|-----------:|-------------------:|
| 512×1024|        0.87 s  |    0.060 s |            **~14×** |
| 512×4096|       14.11 s  |    0.250 s |            **~57×** |
| 512×8192|       54.65 s  |    0.492 s |           **~111×** |

## Whole-compile impact

Because DXP backend compilation dominates cold-compile cost at
scale, the whole-compile effect of this change is small in
percentage terms even though the pass-local win is large:

| point   | pristine `compile_fx` | new `compile_fx` (est.) | savings | % of compile_fx |
|---------|----------------------:|------------------------:|--------:|----------------:|
| 512×1024|                 99.4 s|                  98.6 s |   0.8 s |            0.8% |
| 512×4096|                568.0 s|                 554.2 s |  13.9 s |            2.4% |
| 512×8192|               2379.7 s|                2325.5 s |  54.2 s |            2.3% |

`dxp_standalone` is 80–92% of `compile_fx` across these points.
The value of this change is removing a near-quadratic frontend
scaling pathology, not fixing total cold-compile latency.

## Correctness / semantic equivalence

Captured a normalized post-dedup state under both the pristine
algorithm and this change at `Lq=512, Lk=1024`. Compared:

- ordered `graph.operations` (types + canonical positions)
- surviving-constant identity keys `(value, dtype, device)`
- `removed_buffers` set
- `name_to_buffer` keys
- `name_to_op` keys
- `name_to_users` entries by type + canonical inner-name
- per-consumer live reads for every surviving `ComputedBuffer`
- `_spyre_prov_history` per surviving canonical

Result: **EQUIVALENT — no semantic differences detected**.

## Files changed

Two files:

- `torch_spyre/_inductor/dedup_constants.py` — the pass change.
- `tests/inductor/test_dedup_constants.py` — the five existing
  dedup tests plus the new deterministic tests added by this PR.

## Tests

The existing `tests/inductor/test_dedup_constants.py` gains two
new test classes alongside `TestDedupConstants` (its five
existing tests are unchanged):

**`TestDedupConstantsPassLevel`** — pass-level tests. Each runs
the real pre-scheduling pipeline through `insert_bmm_padding`,
then invokes `dedup_and_promote_constants` by hand and asserts on
the resulting state. Terminates the compile with a dedicated
`_TestStopSignal` sentinel so any other exception (including a
real `AssertionError` inside the callback) surfaces normally.

- `test_zero_consumer_duplicate` — a duplicate with no live
  consumers is still cleanly removed and its bookkeeping cleaned.
- `test_one_duplicate_many_consumers` — two distinct live
  `ComputedBuffer`s reading the same duplicate name D are both
  redirected to the canonical.
- `test_one_consumer_reads_two_duplicates_same_group` — one live
  `ComputedBuffer` reads two duplicates from the same dedup group.
  Uses real `NameSwapHandler` composition; verifies both
  duplicates absent from the consumer's live reads after dedup
  and only the canonical present. This is the case where the
  snapshot approach and a live-rescan implementation could
  plausibly diverge.
- `test_all_output_name_duplicates_still_dropped` — when every
  duplicate is a graph output, the reverse-index scope collapses
  to empty (zero `get_read_writes` calls) but every duplicate is
  still passed through `_drop_constant`; every duplicate op is
  removed, every duplicate buffer name is in `removed_buffers`,
  absent from `name_to_buffer` and `name_to_op`, canonical
  survives. Guards against re-gating Step 2 on the output-filtered
  set.
- `test_name_to_users_fold_exact` — post-dedup
  `name_to_users[canonical]` is exactly the identity-preserving
  concatenation of pre-dedup canonical + all duplicate entries;
  each duplicate key is absent.
- `test_provenance_transform_appended` — canonical carries
  `n_dups_in_group` new `ProvenanceTransform` entries with
  `pass_name == "dedup_and_promote_constants"`, `kind == "fusion"`,
  `reason == "duplicate constant"`.
- `test_no_duplicates_fast_path` — a workload with no
  multi-constant group triggers zero
  `ComputedBuffer.get_read_writes` calls inside dedup. Guards
  the D=0 fast-path invariant.
- `test_reverse_index_scales_with_N_not_D` — patches
  `ComputedBuffer.get_read_writes` to count calls and asserts
  `calls <= n_ops_at_entry` on a duplicate-bearing graph (D>=2).
  Verified locally that a synthetic "rebuild index inside
  per-duplicate loop" regression fails this guard (28 calls on a
  17-op graph). This is the guardrail for the optimization
  itself.

**`TestBuildReverseConsumerIndex`** — standalone unit tests over
`_build_reverse_consumer_index` using lightweight `SimpleNamespace`
mocks. No Spyre device required.

- `test_op_with_two_deps_same_name_appears_once` — an op with two
  distinct dep objects sharing a name appears exactly once in the
  index (behavior-preservation for the pristine "patch once per
  (op, dup)" rule).
- `test_op_with_two_deps_different_names` — an op reading D1 and
  D2 appears once in each of `consumers_by_name[D1]` and
  `consumers_by_name[D2]`.
- `test_op_with_no_duplicate_reads_absent_from_index` —
  non-duplicate names don't leak into the index.
- `test_multiple_ops_deterministic_order` — ops appear in
  `graph.operations` order.
- `test_returned_mapping_is_plain_dict_not_defaultdict` — the
  returned mapping is a plain `dict`; `idx["absent"]` raises
  `KeyError`; `idx.get("absent")` does not install the key.

## Test results

Full run in a Spyre PF test environment (Python 3.12, torch
2.13.0+cpu):

```
tests/inductor/test_dedup_constants.py                       18 pass
   (TestDedupConstants: 5, TestDedupConstantsPassLevel: 8,
    TestBuildReverseConsumerIndex: 5)
tests/inductor/test_padding.py::test_padding_constants_deduped   1 pass
tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash 1 pass
                                                       Total: 20 pass, 0 skipped
```

## Not in this PR

- **Batch removal.** Replacing per-duplicate
  `operations.remove(dup)` with a single Step-3
  filter/partition rebuild via a `dead_ids: set[int]`. Measured
  within-noise on this workload (~1.5% of dedup at Lk=8192, or
  ~8 ms of ~492 ms). Correct and semantically equivalent, but
  not worth combining with this change; can ship separately.
- **Any upstream Inductor change.** In particular, this change
  does not attempt to teach `register_users_of` to walk
  decomposed lowerings, which would let the pass use
  `V.graph.name_to_users` directly. That's an upstream-Inductor
  scope change; this PR stays in torch-spyre.
- **The known output-name behavior in `_redirect_consumers`**
  where a duplicate whose name is in `V.graph.get_output_names()`
  is skipped for redirect but `_drop_constant` still runs.
  Preserved verbatim by this PR; not addressed here.

Additional raw measurement artifacts and diagnostic traces are
retained separately.
