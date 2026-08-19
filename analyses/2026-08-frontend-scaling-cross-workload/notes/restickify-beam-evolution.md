# Restickify beam frontier evolution, pre-fix vs post-fix

Instrumentation: `patches/restickify_beam_counters.py` adds counters per-op
in `beam_global_min_cost` (`optimize_restickify.py`): `pre_expand`,
`n_candidates`, `post_expand`, `post_merge`, `post_trim`. Also summary
`max_*` and `merged_total` recorded on a `restickify_beam_trace` event.

## Pre-fix beam counters

### n_chunks=2 (compiles OK)

| metric | value |
|---|---:|
| ops_processed | 55 |
| BEAM_WIDTH | 200 |
| max_pre_expand | 54 |
| max_post_expand | 108 |
| max_post_merge | 54 |
| max_post_trim | 54 |
| merged_total (across all ops) | 239 |

Interesting expansions (post_expand > post_merge):
```
buf26  pre=18 cand=4 exp= 36 merge=12 trim=12
buf28  pre=24 cand=4 exp= 72 merge=36 trim=36
buf30  pre=36 cand=4 exp=108 merge=54 trim=54  ← peak
buf35  pre=27 cand=4 exp= 81 merge=18 trim=18
buf38  pre= 9 cand=4 exp= 27 merge= 6 trim= 6
```

Peak is 108 states — well under BEAM_WIDTH=200. Compile succeeds.

### n_chunks=4 (compiles OK, beam saturated)

| metric | value |
|---|---:|
| ops_processed | 95 |
| BEAM_WIDTH | 200 |
| max_pre_expand | **200** |
| max_post_expand | **600** |
| max_post_merge | 300 |
| max_post_trim | 200 |
| merged_total | 1,801 |

Interesting expansions:
```
buf56  pre=200 cand=4 exp=600 merge=300 trim=200  ← peak, BEAM SATURATED
buf61  pre= 96 cand=4 exp=384 merge= 96 trim= 96
buf64  pre= 48 cand=4 exp=168 merge= 40 trim= 40
```

Beam **hits the BEAM_WIDTH=200 cap at buf56**. Trim discards states from
300 → 200. Still finds a feasible layout at n=4.

### n_chunks=8 (CRASH)

Fails at buf112 with the exact issue #3687 signature. Beam trace is
lost because the exception fires inside `beam_global_min_cost` before
our `_tr.stage` emission. This matches issue #3687's law:
`min_beam ≈ 400 × 2^(n − 7)`, so at n=8 default 200 is 4× too small.

## Doubling the pre-fix pre-expand cap

n_chunks=2: max_pre_expand=54
n_chunks=4: max_pre_expand=200 (saturated)

Between n=2 and n=4, without trim the beam would grow ≥ 200/54 ≈ 3.7×.
That's consistent with the 2× per additional chunk state-doubling law
(3 additional chunks × 2× each = 8× naive; trim & liveness merge
suppress it to 3.7×).

## Structural observation

`n_candidates=4` on the offending ops (buf26/28/30 pre-fix). These are
**buffers fed by constant-fill ops whose layout is undetermined** —
exactly the state PR #3812's fix collapses. Each candidate doubles beam
states through subsequent liveness merges when the down-stream consumer
locks in an orientation.

## Post-fix beam counters

| n_chunks | ops | max_pre | max_expand | max_merge | max_trim | merged_total | compile time |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 55 | 27 | 81 | 27 | 27 | 153 | 49 s |
| 4 | 95 | 200 | 656 | 243 | 200 | 1,525 | 56 s |
| 8 | 175 | 200 | 800 | 400 | 200 | 5,803 | 127 s |
| 16 | 335 | 200 | 800 | 400 | 200 | 15,403 | 329 s |

## Pre-vs-post comparison

| metric | pre n=2 | post n=2 | reduction |
|---|---:|---:|---:|
| max_pre_expand | 54 | 27 | −50% |
| max_post_expand | 108 | 81 | −25% |
| max_post_merge | 54 | 27 | −50% |
| max_post_trim | 54 | 27 | −50% |
| merged_total | 239 | 153 | −36% |

At n=4 both hit BEAM_WIDTH=200 (trim cap); the true unclamped
frontier would differ more.

## Per-op candidate change (n_chunks=2)

Ops with `n_candidates` collapsed pre→post from 2 to 1:
```
buf1, buf3, buf4, buf32, buf33            ← constant-fill sources
coarse_tile_read_copy_0_buf33_7           ← read-copy of a constant
```

These are exactly the `torch.full()` / `torch.zeros_like()` / `.amax(-1)`
constant-fill ops in the KV-chunked FA closure — the sources the
`_all_constant_layouts` → `[generic_layout(op)]` fix targets.

Downstream ops keep their `n_candidates` values (4 candidates in most
cases) because their own consumers dictate layout — but `post_expand`
halves for ops in the diamond immediately downstream of the collapsed
constants (buf25: 18→9, buf28: 72→36, buf30: 108→54). That's the
diamond-pattern state doubling being eliminated.

## Cross-fix scaling stability under BEAM_WIDTH=200 (post-fix)

| n_chunks | pre-fix behavior | post-fix max_post_expand | post-fix max_post_trim |
|---:|:---|---:|---:|
| 2 | OK, peak 108 | 81 | 27 |
| 4 | OK, BEAM saturated | 656 | 200 |
| 8 | **CRASH** (needs beam ≥ 800) | 800 | 200 |
| 16 | (would need beam ≥ 3,200) | 800 | 200 |

Post-fix `max_post_expand=800` at both n=8 AND n=16. Note that BEAM
_expansion_ still doubles per chunk (since each op has up to 4 candidates
× 200 states = 800 next_states), but liveness merge + trim quickly bring
it back to 200 or below. The trim is finding a feasible state without
needing a wider beam, so the compile continues.

## Mechanism confirmation

Pre-fix: `_all_constant_layouts(op)` produced up to 4 candidates for each
of the three carry-init constant-fill ops (running_max, denom, acc). Each
per-chunk diamond branches once at the constants and once again through
downstream ops that inherit those choices. The state space doubles per
chunk.

Post-fix: `[generic_layout(op)]` gives each constant-fill ONE candidate.
The per-chunk state doubling is removed. Diamond-downstream ops still
have multiple candidates but their expansion is capped because the
upstream chain has only ONE upstream state to expand from.

This matches issue #3687's mechanism exactly (from the issue body):
"the failure is over a carry shaped [1,2,256] with two equally-costed
stick mappings, and there are ~3 such carries per chunk, so states
double per chunk."

## Timing correlation with beam trace

Restickify pass timings from the substage sweep:

| n_chunks | pre-fix restickify (ms) | post-fix restickify (ms) |
|---:|---:|---:|
| 2 | 583 | 545 |
| 4 | 1,102 | 1,049 |
| 8 | (CRASH) | 2,300 |
| 16 | (CRASH) | 5,607 |

Pre-fix restickify at n_chunks=2 and 4 is slightly slower (~5-7%) than
post-fix, consistent with the beam doing more state expansion + more
liveness merges. But the difference is small at these chunk counts —
the exponential blowup only bites past n=6, and by then the pre-fix
just fails.

