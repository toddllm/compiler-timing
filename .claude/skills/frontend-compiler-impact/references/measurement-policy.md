# Measurement policy

Non-negotiable rules for any timed measurement. Violation of any
rule invalidates the result.

## Pod-tree alignment gate — check BEFORE scheduling device work

Before you consume any device time, decide whether the pod tree can
serve as the base for this PR. Three tiers, checked in order — each
tier gated by a strictly stronger check than the last.

### Tier 1 — Cleanest: pod == PR base

The pod's `HEAD` matches the PR's `base_sha` exactly. In-place patch
swap between `.base` and `.head` snapshots of the changed files is
fine (pure-Python changes only).

### Tier 2 — Adequate: per-touched-file blob equality

**"Diff applies cleanly" is not sufficient.** `git apply --check`
only checks whether the patch's context lines match the file's
context — it says nothing about the rest of the file. A PR-touched
file can have drifted heavily around the patched hunks and still
apply cleanly. That drift means the "base" you measure against is
not the PR's actual base.

The correct check is **per-touched-file blob equality**:

```
# For each file the PR touches, fetch the base blob and compare
# byte-for-byte against the pod's copy.
for f in $(gh pr diff <pr> --name-only); do
    gh api "repos/<owner>/<repo>/contents/$f?ref=$BASE_SHA" \
        -q .content | base64 -d > /tmp/base_blob
    if ! cmp -s /tmp/base_blob "$POD_TREE/$f"; then
        echo "DRIFT: $f — pod copy is not the PR base"
        # Tier 2 fails — must escalate to Tier 3
    fi
done
```

Tier 2 is only satisfied when EVERY touched file's pod copy matches
the PR-base blob byte-for-byte. Otherwise the measurement would be
"effect of applying the diff to a differently-drifted substrate",
not "PR base vs PR head". Escalate to Tier 3.

Record the verification in `02-experiment-plan.md` under
`## Pod-tree alignment`: which SHAs, which files, blob md5s at
pod-copy and at PR-base blob, and the cmp exit codes.

### Tier 3 — Isolated checkout at exact SHAs

Required when:

- Tier 2 fails (any PR-touched file has drifted at the pod).
- The PR touches C-extension sources (in-place patching cannot
  swap `_C.so` symbols).
- The PR's base needs newer torch/AIupti/deeptools than the pod
  has.

Run:

```
.claude/skills/frontend-compiler-impact/scripts/setup_isolated_checkout.sh \
    <base_sha> <base-dir>
.claude/skills/frontend-compiler-impact/scripts/setup_isolated_checkout.sh \
    <head_sha> <head-dir>
```

Then use the timing shim
(`.claude/skills/frontend-compiler-impact/scripts/timing_shim.py`)
to instrument each tree. The shim is idempotent and requires no
tree modification.

If the isolated `_C.so` cannot be symlinked from a shared pod build
(ABI mismatch — new C++ symbols like `NativePermutationLayoutSolver`
appear in newer torch-spyre revisions), rebuild `_C.so` from source
in each isolated tree with `python setup.py build_ext --inplace`.
This takes ~10–20 minutes per tree on the pod but produces an ABI
match. Only fall back to `INSUFFICIENT_EVIDENCE` when even the
fresh build fails (system libs too old for the PR's base).

Never symlink an older `_C.so` into a newer tree hoping the missing
symbol is not exercised — the Spyre pass pipeline transitively
imports scratchpad code that top-level imports newer C symbols, so
the failure will surface at compile time, not at import.

### Where the tier goes in the experiment plan

The alignment tier belongs in `02-experiment-plan.md` in a
`## Pod-tree alignment` section, with:

- The Tier 1 / Tier 2 / Tier 3 decision.
- For Tier 2: the touched-file blob-cmp evidence.
- For Tier 3: the isolated-checkout paths, whether `_C.so` was
  symlinked or rebuilt, and the smoke-test import result.
- The exact base and head SHAs.

This step comes BEFORE cache-dir setup, BEFORE sentinel selection —
it decides whether device time can usefully happen at all.

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
