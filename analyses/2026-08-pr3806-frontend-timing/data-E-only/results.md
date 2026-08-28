# E-only measurement results

**All results computed on `tdeshane-compiler-timing-dev-v2`
(RHEL 9.6, Python 3.12.13, torch 2.13.0+cpu, torch-spyre baseline
`a9316b381`). E-only variant swapped in for
`torch_spyre/_inductor/dedup_constants.py`.**

Per-sample raw JSONs under this directory. `timing-*.json` files
are the standard timing-recorder outputs (headline dedup
wall-clock via `pass:CustomPreSchedulingPasses:dedup_and_promote_constants`).
`dedup-*.json` files are the diagnostic recorder outputs
(sub-timers + counts).

## E-only headline (DIAG-OFF)

Direct wall-clock comparison against Phase 2's pristine numbers.

| point | pristine (Phase 2 median) | E-only median | speedup |
|---|---:|---:|---:|
| 512×1024 |    976.9 ms |  **60.0 ms** | **16.3×** |
| 512×4096 | 15,697.1 ms | **249.7 ms** | **62.9×** |
| 512×8192 | 62,189.4 ms | **492.5 ms** | **126.3×** |

## Mechanism (DIAG-ON)

| point | run | N | D | n_get_read_writes_calls | n_ops_scanned | n_consumer_hits | dedup_total (ms) | get_read_writes (ms) | operations_remove (ms) | merge_provenance (ms) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 512×1024 | 1 |  276 |  16 |   276 | 0 |  16 |  61.54 |  60.46 | 0.176 | 0.271 |
| 512×1024 | 2 |  276 |  16 |   276 | 0 |  16 |  60.78 |  59.86 | 0.171 | 0.107 |
| 512×1024 | 3 |  276 |  16 |   276 | 0 |  16 |  60.77 |  59.88 | 0.173 | 0.106 |
| 512×4096 | 1 | 1092 |  64 |  1092 | 0 |  64 | 256.40 | 250.57 | 2.135 | 0.721 |
| 512×4096 | 2 | 1092 |  64 |  1092 | 0 |  64 | 243.37 | 238.20 | 2.082 | 0.655 |
| 512×4096 | 3 | 1092 |  64 |  1092 | 0 |  64 | 253.99 | 248.54 | 2.091 | 0.657 |
| 512×8192 | 1 | 2180 | 128 |  2180 | 0 | 128 | 491.11 | 476.45 | 8.192 | 1.926 |
| 512×8192 | 2 | 2180 | 128 |  2180 | 0 | 128 | 488.75 | 474.09 | 8.203 | 1.837 |
| 512×8192 | 3 | 2180 | 128 |  2180 | 0 | 128 | 473.11 | 458.65 | 8.030 | 1.919 |

Consistency checks:
- `n_ops_scanned = 0` at every sample — the per-duplicate scan
  loop is gone, replaced by the single reverse-index build inside
  `_build_reverse_consumer_index`.
- `n_get_read_writes_calls = N` at every sample — exactly one
  `get_read_writes()` per op in `graph.operations`, invoked during
  index construction.
- `n_consumer_hits = D` at every sample — every duplicate found
  its (single) live consumer via the local reverse index.
- `n_operations_remove_calls = D` at every sample (unchanged from
  pristine — E-only preserves per-dup `operations.remove`; batch
  removal is a separate change).

## Work-count collapse

| point | N | D | pristine calls (N×D) | E-only calls (N) | reduction |
|---|---:|---:|---:|---:|---:|
| 512×1024 |  276 |  16 |     4,416 |   276 | **16×**  |
| 512×4096 | 1092 |  64 |    69,888 | 1,092 | **64×**  |
| 512×8192 | 2180 | 128 |   279,040 | 2,180 | **128×** |

## Diagnostic perturbation, within E-only

| point | DIAG-OFF median (ms) | DIAG-ON median (ms) | delta |
|---|---:|---:|---:|
| 512×1024 |  59.95 |  60.81 | +1.43% |
| 512×4096 | 249.66 | 254.07 | +1.77% |
| 512×8192 | 492.49 | 488.80 | −0.75% |

Same order of magnitude as the pristine perturbation delta
(+1.23%). Diagnostic overhead is small in either baseline.

## Model comparison

Predicted (§Section-E of `notes/dedup-phase2-plan.md`):

    N · f_grw + D · (patch + bookkeeping) + O(N)
    f_grw ≈ 228 µs per ComputedBuffer.get_read_writes call

At Lk=8192 (N=2180, D=128):

    2180 × 228 µs + 128 × 40 µs + O(2180) ≈ 497 ms + 5.1 ms + ~1 ms ≈ 503 ms

Measured: **492.49 ms** (median). Within 2% of the pre-run prediction.

At Lk=4096: predicted **~252 ms**; measured **249.7 ms** (median).
At Lk=1024: predicted **~64 ms**; measured **60.0 ms** (median).

The measured `f_grw` per call (`get_read_writes_ns /
n_get_read_writes_calls`) is:

| point | get_read_writes_ns per call |
|---|---:|
| 512×1024 | 219,057 ns median |
| 512×4096 | 227,647 ns median |
| 512×8192 | 217,451 ns median |

Consistent with the pristine measurement (~228 µs); slightly
lower at Lk=8192 could be cache effects or noise but is not
material for the model.

## Semantic equivalence (Lq=512, Lk=1024)

Captured normalized post-dedup state via
`patches/semantic_equiv_harness.py` under both dedup implementations
(pristine and E-only) on the same workload and same pod. Compared
via `patches/diff_semantic_state.py`:

Compared:
  - `graph.operations` (ordered list of type/canonical-position)
  - surviving-constant identity keys (`_constant_key` output)
  - `removed_buffers`
  - `name_to_buffer` keys
  - `name_to_op` keys
  - `name_to_users` entries (types + canonical inner-name index)
  - per-consumer live reads for every surviving ComputedBuffer
  - provenance history length + pass_names per surviving canonical

Result:

    $ python3 patches/diff_semantic_state.py \
        data-semantic/state-pristine-512x1024.json \
        data-semantic/state-E-only-512x1024.json
    EQUIVALENT — no semantic differences detected.

Raw state dumps preserved at
`data-semantic/state-{pristine,E-only}-512x1024.json`.

## Test execution against E-only

Same eleven tests that pass against pristine also pass against
E-only. Full pytest output preserved in
`data-E-only/test-execution-E-only.txt`.

    11 passed, 11 warnings in 15.36s

No skips. No downstream-pass regressions.
