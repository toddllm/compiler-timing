# Pre-DXP frontend investigation (epic #4117)

Read `notes/summary.md` for the framing. This README is the layout key.

**Frozen torch-spyre baseline:**
`3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f`
(upstream/main at study start; PR #4113 merge
`c073d69cceaac91d34b01dea6545048d0d645c2c` verified as ancestor).

## Layout

    notes/
      pre-dxp-stage-map.md     Phase 1 — source-level stages, file:line
      pre-dxp-attribution.md   Phase 5 — bucket-by-bucket ms + %
      next-opportunities.md    Phase 6 — ranking judgment (no AND-gate)
      summary.md               concise summary (Todd/Will/Olivier)
      tables/
        scaling.md             log-log slopes + per-unit drift per bucket
        pass-detail.md         top-K passes inside CustomPreSched
        reconciliation.md      per-run residual + validity
    harness/
      pre_dxp_stop.py          cold compile with --mode {stop,observe,passthrough}
      check_bundle_fidelity.py paired observe+stop — pre-DXP catalog diff
      pilot_driver.sh          5 shapes × 1 sample — run first
      sweep_driver.sh          9 flash + 6 layer-scaled MLP × 3 samples
      analyze_sweep.py         sweep → notes/*, tables/*
      README.md                harness usage
    patches/
      timing_recorder.py       vendored — writes JSON dumps
      extra_timers.py          vendored — brackets Scheduler/codegen/etc.
      instrumentation.patch    for the frozen SHA only
      apply_instrumentation.sh refuses to apply on drifted / dirty tree
    data/
      pilot/                   filled by pilot_driver.sh
      sweep/                   filled by sweep_driver.sh
      fidelity_check/          filled by check_bundle_fidelity.py

## Pod runbook

    # Frozen SHA + apply instrumentation (one-time per pod).
    export TORCH_SPYRE_REPO=$HOME/pr4117/torch-spyre
    git -C "$TORCH_SPYRE_REPO" checkout 3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f
    bash patches/apply_instrumentation.sh

    # 1. Bundle fidelity at one baseline shape.
    python3 harness/check_bundle_fidelity.py --out-dir data/fidelity_check

    # 2. Pilot — 5 shapes × 1 sample. Inspect event trees manually.
    bash harness/pilot_driver.sh
    python3 harness/analyze_sweep.py --sweep-dir data/pilot \
        --out-notes /tmp/pilot-notes --out-tables /tmp/pilot-tables --strict

    # 3. Only after pilot passes: full 3-sample sweep.
    bash harness/sweep_driver.sh
    python3 harness/analyze_sweep.py --sweep-dir data/sweep \
        --out-notes notes --out-tables notes/tables --strict
