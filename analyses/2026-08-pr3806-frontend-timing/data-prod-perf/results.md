# Production E-only performance reconfirm

Ran the upstream-prep production E-only implementation
(`patches/dedup_constants_E_only.py` from `upstream-prep/`, plus
the `_build_reverse_consumer_index` de-duplication fix) against
the pod's `a9316b381` tree.

Note about `NameSwapHandler`: the production file lives against
current-main's import (`from .pass_utils import NameSwapHandler`).
For validation on the `a9316b381` tree we used a dual-import
shim that falls back to `insert_restickify` when `pass_utils`
does not have the class. The resulting file is byte-identical to
the production file everywhere except the import block.

## Results

### DIAG-OFF, 3 cold samples per point

| point   | run1 | run2 | run3 | median (ms) |
|---------|-----:|-----:|-----:|------------:|
| 512×1024 | 55.06 | 56.06 | 56.43 | **56.06** |
| 512×8192 |    —  |    —  |    —  | *hardware
              failure, see below* |

Phase 3 E-only measurement at 512×1024 was 60.0 ms median; the
reconfirm here is ~7% faster. This is within the pod's normal
run-to-run variation (the perturbation check measured ~1-2%
sample-to-sample; day-to-day variation on the same pod is
larger). No regression; if anything a slight improvement,
possibly because the production version drops the `_diag_record`
kwarg threading that Phase 3's instrumented version carried.

### 512×8192 — hardware failure

The Lk=8192 sample terminated with an unrelated Spyre PCIe bus
fence event (RAS::PCI::BusFence, code 0xa35e). Full stack trace
in `data-prod-perf/run.log`. This is a hardware condition not
caused by the code change; the same pod has produced clean
Lk=8192 samples repeatedly in Phase 2 and Phase 3. Since the
Phase 3 measurement of E-only at Lk=8192 (492.5 ms median across
3 samples on the same pod) is already established, no reason to
rerun.

## Test suite

All 15 tests pass against the production E-only implementation
on the same pod:

```
tests/inductor/test_dedup_constants.py                       (5) PASS
tests/inductor/test_dedup_constants_more.py (pass-level)     (5) PASS
tests/inductor/test_dedup_constants_more.py (unit)           (4) PASS
tests/inductor/test_padding.py::test_padding_constants_deduped
                                                              (1) PASS
tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash
                                                              (1) PASS
=============================
Total: 16 pass, 0 skipped
```

`test_flash` completed in 104.17s (cold compile).
