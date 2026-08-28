# E+batch measurement results

**Same environment as E-only run.**
`torch_spyre/_inductor/dedup_constants.py` swapped to E+batch
variant (`patches/dedup_constants_E_plus_batch.py`).

## Headline (DIAG-OFF)

| point   | E-only median | **E+batch median** | delta vs E-only | vs pristine speedup |
|---------|--------------:|-------------------:|----------------:|--------------------:|
| 512×1024|      59.95 ms |     **61.29 ms**   |         +2.23% |    **15.9×**        |
| 512×4096|     249.66 ms |    **254.07 ms**   |         +1.77% |    **61.8×**        |
| 512×8192|     492.49 ms |    **494.81 ms**   |         +0.47% |   **125.7×**        |

E+batch is statistically indistinguishable from E-only. Within-noise
delta at every point (±2%, consistent with the ~1% run-to-run
variation this pod exhibits in the perturbation-check data).

## Mechanism (DIAG-ON)

| point | run | N | D | n_calls | n_scanned | n_hits | n_operations_remove_calls | total (ms) | get_read_writes (ms) | operations_remove (ms) | front_load (ms) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 512×1024 | 1 |  276 |  16 |  276 | 0 |  16 | **0** |  61.93 |  60.99 | **0.000** | 0.120 |
| 512×1024 | 2 |  276 |  16 |  276 | 0 |  16 | **0** |  62.58 |  61.79 | **0.000** | 0.118 |
| 512×1024 | 3 |  276 |  16 |  276 | 0 |  16 | **0** |  61.67 |  60.90 | **0.000** | 0.121 |
| 512×4096 | 1 | 1092 |  64 | 1092 | 0 |  64 | **0** | 251.85 | 248.56 | **0.000** | 0.461 |
| 512×4096 | 2 | 1092 |  64 | 1092 | 0 |  64 | **0** | 250.92 | 247.71 | **0.000** | 0.462 |
| 512×4096 | 3 | 1092 |  64 | 1092 | 0 |  64 | **0** | 257.38 | 253.86 | **0.000** | 0.502 |
| 512×8192 | 1 | 2180 | 128 | 2180 | 0 | 128 | **0** | 492.47 | 485.71 | **0.000** | 0.889 |
| 512×8192 | 2 | 2180 | 128 | 2180 | 0 | 128 | **0** | 491.41 | 484.43 | **0.000** | 0.882 |
| 512×8192 | 3 | 2180 | 128 | 2180 | 0 | 128 | **0** | 499.01 | 491.65 | **0.000** | 0.885 |

- `n_operations_remove_calls = 0` at every sample — per-duplicate
  `operations.remove(dup)` is gone, replaced by the single Step-3
  `operations[:] = ...` rebuild.
- `operations_remove_ns = 0` at every sample — no time attributed
  to per-dup list removal.
- `front_load_ns` slightly higher than E-only's front-load (adds
  the `id(op) not in dead_ids` check per op), by ~40-200 µs.

## Incremental value of batch removal

| point | E-only rm | E-only fl | E+batch rm | E+batch fl | net saving |
|---|---:|---:|---:|---:|---:|
| 512×1024 | 0.173 ms | ~0.08 ms | 0.000 ms | 0.120 ms | ~+0.13 ms |
| 512×4096 | 2.091 ms | ~0.34 ms | 0.000 ms | 0.462 ms | −1.97 ms |
| 512×8192 | 8.192 ms | ~0.94 ms | 0.000 ms | 0.885 ms | −8.25 ms |

Batch removal saves roughly the E-only `rm_ms` amount (as expected;
that's the D calls to `operations.remove(dup)` becoming free). It
adds a small amount to the final rebuild (the `id(op) not in
dead_ids` check adds ~40 µs at N=276, ~200 µs at N=2180). Net:
E+batch saves ~1.5% of dedup at Lk=8192 vs E-only.

**Attribution**: this is the actual incremental value of the
batch-removal change. Not the headline speedup — that came from
E's reverse index in Commit B. Batch removal is a modest constant-
factor cleanup that eliminates the last O(N·D) list operation and
its cost.

## Semantic equivalence

Captured normalized post-dedup state under E+batch at Lq=512,
Lk=1024 via `patches/semantic_equiv_harness.py`. Diffed against
both pristine and E-only states.

```
$ python3 patches/diff_semantic_state.py \
    data-semantic/state-pristine-512x1024.json \
    data-semantic/state-E-plus-batch-512x1024.json
EQUIVALENT — no semantic differences detected.

$ python3 patches/diff_semantic_state.py \
    data-semantic/state-E-only-512x1024.json \
    data-semantic/state-E-plus-batch-512x1024.json
EQUIVALENT — no semantic differences detected.
```

State dump preserved at
`data-semantic/state-E-plus-batch-512x1024.json`.

## Test execution against E+batch

Same eleven tests that pass against pristine and E-only also pass
against E+batch. Zero skips.

```
tests/inductor/test_dedup_constants.py                        5 pass
tests/inductor/test_dedup_constants_more.py                   5 pass
tests/inductor/test_padding.py::test_padding_constants_deduped 1 pass

======================= 11 passed, 11 warnings in 14.86s =======================
```

Full pytest output in `data-E-batch/test-execution-E-plus-batch.txt`.
