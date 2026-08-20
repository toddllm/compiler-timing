# Measurement policy

Non-negotiable rules for any timed measurement. Violation of any
rule invalidates the result.

## Isolation

- The Spyre device is exclusive per process. Runs are strictly
  serial. Never launch two Spyre compiles concurrently.
- Fresh Python process per timed sample. Same-process warm cache is
  not a compile-time measurement.
- Base and head must use **isolated checkouts**, not the same
  checkout with a patch swap, when C-extension changes are in play.
  For pure-Python changes, in-place patch swap is acceptable but
  each sample must still be a fresh process with a fresh cache.

## Cache

- Every timed sample gets a **unique** `TORCHINDUCTOR_CACHE_DIR`.
- Each driver `rm -rf`s that path before use.
- The exact string is preserved in `meta.TORCHINDUCTOR_CACHE_DIR` on
  the recorded JSON, and reproduced in every embedded backend
  `output_dir` field.

## Environment quietness

- No `TORCH_COMPILE_DEBUG=1`, `TORCH_LOGS=+dynamo`, `TORCH_SPYRE_DEBUG=1`
  during timed samples.
- No profilers, no verbose logging, no extra_timers hook unless the
  study explicitly needs it (it adds ~5% overhead; note that in the
  results).
- Diagnostic (cProfile, TORCH_LOGS) runs are labeled "diagnostic" and
  kept separate from timing runs.

## Correctness

- CPU reference (`--compare-cpu`) runs OUTSIDE the timed region.
- Correctness is required for any prototype/optimization prototype.
  Passes → record `meta.cpu_reference_ok=true` in the JSON.
- For a plain compile-time comparison without code behavior change,
  correctness comparison against base is sufficient (i.e. the same
  program compiles on both).

## Sample counts and pairing

- Default: **3 cold samples per point per revision**.
- Acceptable: n=1 for expensive points (>10 min per sample) if
  clearly labeled as "preliminary" or "validation stress point".
- Report median AND spread: min–max or per-sample dump. Never
  claim significance from n=3 without reporting variance.
- **Paired/interleaved execution** — do not run all base samples
  first then all head samples. Alternate:
  ```
  base1 head1 base2 head2 base3 head3
  ```
  This reduces machine/time drift.

## C-extension rebuild

For any change under `torch_spyre/csrc/`:

- The `_C.so` extension differs between revisions. In-process patch
  swap does not work.
- Build the head revision from scratch in an isolated checkout:
  ```
  git clone <repo> /path/to/head
  cd /path/to/head
  git checkout <head_sha>
  python -m venv .venv
  source .venv/bin/activate
  pip install -e .
  ```
- Same for base. Note in `02-experiment-plan.md` that both
  revisions were rebuilt.
- If the pod already has a working editable install for one
  revision, using it is acceptable — do not accidentally load one
  revision's `_C.so` into another revision's Python source.

## Recording metadata

Every JSON dump must carry:

- `meta.workload` (harness name).
- All workload dims (`B`, `H`, `Lq`, `Lk`, `D`, `kv_block`,
  `h_tiles`, `lq_tiles`).
- `meta.n_chunks` where applicable.
- `meta.TORCHINDUCTOR_CACHE_DIR` — the exact per-sample path.
- `meta.pod` — sanitized to `<sanitized>` before commit.
- `meta.SENCORES` and other resolved compiler-config env vars if
  they differ from the primary study's baseline (see
  `analyses/2026-08-pr3806-frontend-timing/data/resolved-config.json`).

The impact.json emitted by this skill also carries:

- `target.pr_number` or `target.commit_range` or `target.branch`.
- `base_sha` and `head_sha` (both exact, resolved at experiment
  time — never assume `main`).
- `base_ref` and `head_ref` names.
- Files touched, per-file static triage classification.

## Statistical hygiene

- Compare effect size to observed spread, not to a fixed threshold.
- 20 ms shift in a 50 s pass is measurement noise even if percent
  arithmetic looks impressive.
- 10 s shift matters even if `compile_fx` is backend-dominated.
- Report absolute delta (ms/s) AND relative delta (%).
- If effect size is within run-to-run spread, classify as **NO
  MEASURABLE FRONTEND IMPACT** and say so explicitly — do not report
  a suggestive percentage without noting the spread.

## When to escalate to Level 4

Only when Level ≤3 measurement showed a real movement OR a
contradiction of the static prediction. Then:

- Enable substage instrumentation if the pass has a decomposition
  patch available (e.g. `coarse_tile_substage_timing.py`).
- Run cProfile on ONE diagnostic sample — never mix cProfile output
  with timing samples.
- Emit per-op counters if the affected pass instrumentation supports
  them (dedup emits `input_operations`/`ops_delta`; restickify emits
  beam counters with the beam-counter patch).

## Recording no-run verdicts

Level 0 verdicts still produce `03-results.md` with:

- The static classification that led to no-run.
- Explicit statement: "no device time consumed".
- The device-time budget that was avoided (e.g. "avoided ~3× 60 s
  WB_n4 samples for base and head = 6 min, plus the paired-run
  overhead").

This lets the skill's efficiency be evaluated after the fact.
