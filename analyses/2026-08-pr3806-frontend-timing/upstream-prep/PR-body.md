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
PR #3806 `test_flash` workload. Verified via a normalized post-
dedup state comparison across `graph.operations`, surviving
constants, `removed_buffers`, `name_to_buffer`, `name_to_op`,
`name_to_users`, per-consumer live reads, and provenance
history.

## Mechanism

Old:
```python
for group in groups.values():
    if len(group) <= 1: continue
    canonical = group[0]
    for dup in group[1:]:
        for op in graph.operations:            # O(N)
            if op is dup or op is canonical: continue
            rw = op.get_read_writes()           # not cached; walks inner_fn
            if any(dep.name == D for dep in rw.reads):
                _patch_inner_fn(op, {D: C})
        graph.operations.remove(dup)            # O(N)
```

New:
```python
duplicate_names = {dup.get_name() for group in groups.values() if len(group) > 1
                                   for dup in group[1:]}

if duplicate_names:
    consumers_by_name = _build_reverse_consumer_index(   # single O(N) sweep
        graph.operations, duplicate_names,
    )
    for group in groups.values():
        if len(group) <= 1: continue
        canonical = group[0]
        for dup in group[1:]:
            for op in consumers_by_name.get(dup.get_name(), []):
                if op is dup or op is canonical: continue
                _patch_inner_fn(op, {D: C})
            graph.operations.remove(dup)                  # unchanged
```

The reverse-index builder uses a per-op `set` of matched buffer
names, so an op whose reads contain two distinct `MemoryDep`
objects sharing a name still appears at most once in
`consumers_by_name[name]` — matching the pristine algorithm's
"patch once per (op, dup)" behavior.

`_drop_constant`'s `operations.remove(dup)` is deliberately
preserved. It runs D times, each an O(N) list scan. In the
pristine pass, it accounted for 0.02–0.03% of dedup wall-clock
(measured); the remaining O(N × D) tail is not worth batching
in this change. If we later want to eliminate that tail, it can
land as a separate one-file cleanup (details in the phase-3
evidence linked below).

## Complexity claim (precise)

- **Consumer-discovery term** (the dominant cost) changes from D
  full scans of `graph.operations` (each calling `get_read_writes`
  on every op) to a single scan. `get_read_writes()` calls fall
  from approximately `N × D` to `N`.
- **Per-duplicate `operations.remove(dup)`** stays O(N × D)
  overall. Measured at ~0.02% of pristine pass time; intentionally
  unchanged.
- Grouping and Step-3 front-loading remain O(N).
- No-duplicate fast path preserved: when no group has more than
  one entry, no `get_read_writes()` calls are made at all.

## Measured impact (pass-local, DIAG-OFF)

`test_flash` from `tests/inductor/test_opspec_tiling.py`, three cold
samples per point:

| point   | pristine dedup | new dedup  | pass-local speedup |
|---------|---------------:|-----------:|-------------------:|
| 512×1024|        0.87 s  |    0.060 s |              14×   |
| 512×4096|       14.11 s  |    0.250 s |              57×   |
| 512×8192|       54.65 s  |    0.492 s |             111×   |

Work-count collapse (DIAG-ON diagnostic):

| point   | N    | D   | pristine `get_read_writes` calls | new calls | reduction |
|---------|-----:|----:|---------------------------------:|----------:|----------:|
| 512×1024|  276 |  16 |                            4,416 |       276 |       16× |
| 512×4096| 1092 |  64 |                           69,888 |     1,092 |       64× |
| 512×8192| 2180 | 128 |                          279,040 |     2,180 |      128× |

## Absolute impact (whole compile)

The pass-local win is huge but the end-to-end win is small
because DXP dominates cold compile at scale:

| point   | pristine `compile_fx_wrapper` | E-only compile_fx (est.) | savings | % of compile_fx |
|---------|------------------------------:|-------------------------:|--------:|----------------:|
| 512×1024|                       99.4 s |                    98.6 s|   0.8 s |            0.8% |
| 512×4096|                      568.0 s |                   554.2 s|  13.9 s |            2.4% |
| 512×8192|                     2379.7 s |                  2325.5 s|  54.2 s |            2.3% |

The value of this change is removing a scaling pathology in the
frontend, not fixing total cold-compile latency. `dxp_standalone`
is 80–92% of `compile_fx` across these workloads, and it stays
the dominant absolute cost. After this change the next frontend
bottlenecks — `optimize_restickify_locations` and
`_maybe_scratchpad_planning` — become the largest surviving
frontend passes and easier to see for future work.

## Tests

Adds `tests/inductor/test_dedup_constants_more.py` with 9 new
tests (5 pass-level + 4 unit tests), all deterministic (no
`skipTest`):

Pass-level tests (each runs the real pre-scheduling pipeline
through `insert_bmm_padding`, then invokes
`dedup_and_promote_constants` by hand):

- `test_zero_consumer_duplicate` — a duplicate with no live
  consumers still gets cleanly removed and its bookkeeping
  cleaned.
- `test_one_duplicate_many_consumers` — two distinct live
  `ComputedBuffer`s reading the same duplicate name D are both
  redirected to the canonical.
- `test_name_to_users_fold_exact` — post-dedup
  `name_to_users[canonical]` is exactly the identity-preserving
  concatenation of pre-dedup canonical + all duplicate entries;
  each duplicate key is absent.
- `test_provenance_transform_appended` — canonical carries
  `n_dups_in_group` new `ProvenanceTransform` entries with
  `pass_name == "dedup_and_promote_constants"`,
  `kind == "fusion"`, `reason == "duplicate constant"`.
- `test_no_duplicates_fast_path` — a workload with no
  multi-constant group triggers ZERO `ComputedBuffer.get_read_writes`
  calls inside dedup. Guards the fast-path invariant.

Unit tests (against `_build_reverse_consumer_index` directly, no
Spyre device required):

- `test_op_with_two_deps_same_name_appears_once` — the critical
  behavior-preservation check: an op whose reads contain two
  distinct dep objects with the same name D appears exactly once
  in `consumers_by_name[D]`.
- `test_op_with_two_deps_different_names` — an op that reads D1
  and D2 appears once in each of `consumers_by_name[D1]` and
  `consumers_by_name[D2]`.
- `test_op_with_no_duplicate_reads_absent_from_index` — non-
  duplicate names don't populate the index.
- `test_multiple_ops_deterministic_order` — ops appear in
  `graph.operations` order.

Full test suite result on `a9316b381` with the equivalent code
change (dual-import shim for `NameSwapHandler` since it moved to
`pass_utils` after that SHA):

```
tests/inductor/test_dedup_constants.py           (5 pristine)   5 pass
tests/inductor/test_dedup_constants_more.py      (5 pass-level) 5 pass
tests/inductor/test_dedup_constants_more.py      (4 unit)       4 pass
tests/inductor/test_padding.py::test_padding_constants_deduped  1 pass
tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash 1 pass
======= 16 passed, 0 skipped =======
```

Full pytest output preserved with the evidence trail linked
below.

## Semantic equivalence

Captured a normalized post-dedup state at `Lq=512, Lk=1024` under
both pristine `a9316b381` and this change. Compared:

- ordered `graph.operations` (types + canonical positions)
- surviving-constant identity keys `(value, dtype, device)`
- `removed_buffers` set
- `name_to_buffer` keys
- `name_to_op` keys
- `name_to_users` entries by type + canonical inner-name
- per-consumer live reads for every surviving `ComputedBuffer`
- `_spyre_prov_history` per surviving canonical

Result: **EQUIVALENT — no semantic differences detected**.

## Not in this PR

- Batch removal (`operations.remove` → filter/partition
  rebuild). Measured within-noise on this workload
  (~1.5% of dedup at Lk=8192). Ships as a separate change if
  desired.
- Any upstream Inductor change (e.g. teaching
  `register_users_of` to walk decomposed lowerings). Would let
  us use `V.graph.name_to_users` directly, but it's an upstream-
  Inductor scope change; this PR stays in torch-spyre.
- The known behavior in `_redirect_consumers` where an output-name
  duplicate is skipped for redirect but still dropped: unchanged.
  Tracked separately.

## Evidence trail

External evidence repository:
`toddllm/compiler-timing` (private).

Study of pristine performance:
`analyses/2026-08-pr3806-frontend-timing/notes/findings.md`

Source-level analysis and cost model:
`analyses/2026-08-pr3806-frontend-timing/notes/dedup-phase2-plan.md`

Final decision + measured evidence:
`analyses/2026-08-pr3806-frontend-timing/notes/dedup-phase3-conclusion.md`

Raw JSONs, semantic-equivalence diffs, and full pytest output:
`analyses/2026-08-pr3806-frontend-timing/data-E-only/`
`analyses/2026-08-pr3806-frontend-timing/data-semantic/`
`analyses/2026-08-pr3806-frontend-timing/data-semantic-prod/`

## Environment

Pod `tdeshane-compiler-timing-dev-v2` (RHEL 9.6, kernel 5.14.0),
Python 3.12.13, torch 2.13.0+cpu, torch-spyre baseline
`a9316b381` for the empirical validation. Diff is minimal against
current `torch-spyre/main` (`813a298`); the only functional
change between `a9316b381` and current main in `dedup_constants.py`
is the `NameSwapHandler` import location (`insert_restickify` →
`pass_utils`), and this PR uses the current-main import path.
