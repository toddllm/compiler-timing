# Pre-DXP frontend investigation (epic #4117)

Read `notes/summary.md` for the one-page framing. This README is the
layout key.

## Layout

    notes/
      pre-dxp-stage-map.md     Phase 1 — source-level stages, file:line
      pre-dxp-attribution.md   Phase 5 — bucket-by-bucket ms + %
      next-opportunities.md    Phase 6 — ranking + methodology
      summary.md               concise summary (Todd/Will/Olivier)
      tables/
        scaling.md             log-log slopes per bucket per workload
        pass-detail.md         top-K passes inside CustomPreSched
    harness/
      pre_dxp_stop.py          Phase 2 — cold compile w/ pre-DXP sentinel
      check_bundle_fidelity.py Phase 2 — bundle fidelity at Lq=512/Lk=1024
      sweep_driver.sh          Phase 4 — flash + MLP sweep
      analyze_sweep.py         Phase 5 — sweep -> notes/*
      README.md                harness usage
    patches/
      timing_recorder.py       vendored — writes JSON dumps
      extra_timers.py          vendored — brackets upstream Inductor methods
      instrumentation.patch    Phase 3 — apply to torch-spyre
      apply_instrumentation.sh Phase 3 — apply script
    data/
      sweep/                   filled by sweep_driver.sh
      fidelity_check/          filled by check_bundle_fidelity.py

## Pod runbook

    export TORCH_SPYRE_REPO=$HOME/pr4117/torch-spyre
    bash patches/apply_instrumentation.sh

    export TORCH_SPYRE_TIMING=1
    python3 harness/check_bundle_fidelity.py \
        --out-dir data/fidelity_check

    bash harness/sweep_driver.sh
    python3 harness/analyze_sweep.py \
        --sweep-dir data/sweep \
        --out-notes notes \
        --out-tables notes/tables
