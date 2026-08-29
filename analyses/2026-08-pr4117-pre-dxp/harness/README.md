# Pre-DXP frontend harness — epic #4117

Runs the normal cold-compile path through backend-input generation
against a **frozen torch-spyre SHA**
(`3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f`, contains PR #4113).
The harness patches `subprocess.run(["dxp_standalone", ...])` and can
either stop the compile at that boundary (`--mode=stop`) or catalog
the bundle and delegate to the real DXP (`--mode=observe`).

## Files

- `pre_dxp_stop.py` — cold-compile driver. Loads torch_spyre, builds a
  workload, installs an interception on
  `torch_spyre.execution.async_compile.subprocess.run`, invokes
  `torch.compile(fn)`. In `stop` mode the interception catalogs the
  bundle then raises `_PreDxpBoundary`; in `observe` mode it catalogs
  then delegates to the real subprocess; in `passthrough` mode it
  installs nothing. Writes timing JSON to `--out` and (if configured)
  a pre-DXP catalog JSON to `--catalog` / `$SPYRE_PRE_DXP_CATALOG`.
- `check_bundle_fidelity.py` — pairs one `observe` run against one
  `stop` run at a baseline shape (default `flash` Lq=512 Lk=1024)
  and diffs the two pre-DXP catalogs. Passes when they are
  byte-identical up to file mode.
- `sweep_driver.sh` — full 3-cold-sample sweep across 9 flash points
  and 6 layer-scaled MLP points. Runs serially; the Spyre device is
  exclusive per process.
- `pilot_driver.sh` — one-sample pilot across 5 representative shapes
  (see §10 of the corrections review). Run this **before** the full
  sweep to validate the framework end-to-end.
- `analyze_sweep.py` — reads sweep or pilot JSON, produces
  `pre-dxp-attribution.md`, `tables/scaling.md`,
  `tables/pass-detail.md`, `tables/reconciliation.md`. Runs that fail
  hard reconciliation are marked invalid and excluded.

## Environment

| Variable | Where read | Purpose |
|---|---|---|
| `TORCHINDUCTOR_CACHE_DIR` | required | Fresh dir per cold-compile sample. |
| `TORCH_SPYRE_TIMING` | required (`=1`) | Turns on the timing recorder. |
| `SPYRE_TIMING_OUT` | timing JSON path | Passed through by drivers; harness also writes `--out`. |
| `SPYRE_PRE_DXP_CATALOG` | catalog JSON path | Written by stop and observe modes. |
| `TORCH_SPYRE_REPO` | drivers | Path to the instrumented torch-spyre checkout. |

## Pod runbook

```bash
# Frozen SHA + apply instrumentation (one-time per pod).
export TORCH_SPYRE_REPO=$HOME/pr4117/torch-spyre
git -C "$TORCH_SPYRE_REPO" checkout 3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f
bash patches/apply_instrumentation.sh

# Fidelity check first (one paired run at flash 512x1024).
python3 harness/check_bundle_fidelity.py --out-dir data/fidelity_check

# Pilot: 5 shapes × 1 sample. Inspect event trees manually.
bash harness/pilot_driver.sh
python3 harness/analyze_sweep.py \
    --sweep-dir data/pilot \
    --out-notes /tmp/pilot-notes \
    --out-tables /tmp/pilot-tables \
    --strict

# Only after pilot passes: full 3-sample sweep.
bash harness/sweep_driver.sh
python3 harness/analyze_sweep.py \
    --sweep-dir data/sweep \
    --out-notes notes \
    --out-tables notes/tables \
    --strict
```
