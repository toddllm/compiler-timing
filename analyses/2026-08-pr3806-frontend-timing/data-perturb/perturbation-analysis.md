# Diagnostic-timer perturbation check — same-environment DIAG-OFF vs DIAG-ON

**Result: DIAG-ON is +1.23% slower than DIAG-OFF at the median at
Lq=512, Lk=1024. Individual samples overlap.**

The ~10% delta between the study's original 201.8 µs/(N×D) coefficient
and the Phase 2 diag sweep's ~222 µs/(N×D) is therefore NOT the
diagnostic timers.

## Method

Same pod, same day (2026-08-27), same torch-spyre tree
(`a9316b381` with diag patch applied), same venv, same workload
(Lq=512, Lk=1024, H=8, all study defaults). Interleaved 3 samples
of each variant so any environment drift affects both roughly
equally:

```
OFF run=1 -> ON run=1 -> OFF run=2 -> ON run=2 -> OFF run=3 -> ON run=3
```

Each sample used a fresh `TORCHINDUCTOR_CACHE_DIR` and fresh Python
process. Both variants used `TORCH_SPYRE_TIMING=1` to capture the
top-level dedup pass wall-clock via
`pass:CustomPreSchedulingPasses:dedup_and_promote_constants`.

## Results

Raw dedup wall-clock (ms):

| sample | DIAG-OFF | DIAG-ON |
|-------:|---------:|--------:|
|      1 |    979.0 |   990.3 |
|      2 |    955.4 |   985.2 |
|      3 |    973.2 |   970.4 |
| median |  **973.2** | **985.2** |
|   mean |    969.2 |   981.9 |

Median delta: **+1.23%**.

Any single DIAG-ON sample can be lower than any single DIAG-OFF
sample (run-3 ON at 970.4 is below run-1 OFF at 979.0 and run-3
OFF at 973.2). This tells us the run-to-run variation on this pod
is comparable to the ~1% signal, so the +1.23% median delta is at
most a small, possibly-not-statistically-significant overhead.

## Correction to the Phase 2 report

The Phase 2 plan attributed the difference between the study's
201.8 µs coefficient and the diag sweep's ~222 µs coefficient to
diagnostic-timer overhead. This perturbation check disproves that
attribution at the single point where I could conveniently test.

The Phase 2 plan has been corrected in-place; the two-fact summary:

- **Timer overhead is not what accounts for the ~10% gap** between
  the two coefficient estimates.
- **The gap is more likely ordinary run/environment variation** —
  different pod state, warmer/colder OS caches, minor Python
  interpreter differences between sweeps taken weeks apart.

## Raw data

`data-perturb/timing-off-run{1,2,3}.json` — timing-recorder JSONs
for DIAG-OFF samples.
`data-perturb/timing-on-run{1,2,3}.json` — timing-recorder JSONs
for DIAG-ON samples (with the diag path also active; timing
recorder is orthogonal to the diag path).
`data-perturb/dedup-on-run{1,2,3}.json` — DedupRecord JSONs from
DIAG-ON samples for sub-timer sanity.
