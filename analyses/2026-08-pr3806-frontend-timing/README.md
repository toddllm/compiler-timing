# PR #3806 — Torch-Spyre front-end compiler timing

Cold-compile scaling study of the OpSpec-tiling flash-attention test
introduced in [`torch-spyre` PR #3806](https://github.com/torch-spyre/torch-spyre/pull/3806),
`tests/inductor/test_opspec_tiling.py::TestOpSpecTiling::test_flash`.

## Questions

1. How long does a cold compile of this workload take, end to end?
2. Of that total, how much is Torch-Spyre front-end vs external
   backend compilation?
3. How much time elapses before the first Torch-Spyre front-end pass
   begins?
4. How long does each individual front-end pass take?
5. How do those components scale as `Lq` and `Lk` grow?

The primary artifact answering these questions is
[`notes/findings.md`](notes/findings.md). This README is the study's
methodology and reproduction record.

## Workload

The `test_flash` test builds a flash-attention closure that iterates
over four tile axes (`B`, `H`, `Lq`, `Lk`) with Python `for` loops
and passes the closure to `torch.compile`. Because the loops are
unrolled at trace time, the compiler-visible program grows with the
product of tile counts.

Baseline configuration (unchanged from the PR):

| param          | value |
|----------------|-------|
| `B`            | 1     |
| `H`            | 8     |
| `D`            | 128   |
| `Lq`           | 512   |
| `Lk`           | 1024  |
| `b_block_size` | 1     |
| `h_block_size` | 4     |
| `q_block_size` | 256   |
| `kv_block_size`| 512   |

Predicted `inner_bodies = (B/b_block_size) × (H/h_block_size) ×
(Lq/q_block_size) × (Lk/kv_block_size)` = 8 at baseline. The FX node
count at `compile_fx` entry is measured directly on every run rather
than inferred from tile count.

## Environment

- Torch-Spyre @ PR #3806 head (`a9316b3`), Torch 2.13.0 CPU wheel,
  Python 3.12.
- Spyre PF device, single-tier, `SENCORES` defaulted to 32.
- No debug env vars set (`TORCH_COMPILE_DEBUG`, `TORCH_LOGS`,
  `TORCH_SPYRE_DEBUG` unset). Diagnostic runs were separated from
  timed runs so heavyweight logging does not affect the measurements.
- The resolved compiler configuration is captured in
  [`data/resolved-config.json`](data/resolved-config.json) and
  described in [`notes/resolved-config.md`](notes/resolved-config.md).
  Non-obvious defaults: `sencores=32`, `lx_planning=True`,
  `hbm_pool_planning=True`, `ignore_span_overflow_hints=True`,
  `cost_model=""`.
- The exact environment probe on the machine that ran the sweep is
  captured in [`data/env-probe.json`](data/env-probe.json).

## Measurement boundaries

Instrumentation is patched into torch-spyre via
[`patches/instrumentation.patch`](patches/instrumentation.patch)
and gated on `TORCH_SPYRE_TIMING=1`. Recorded stages nest as follows:

```
first_call_wall
└── compile_fx_wrapper
    ├── pipeline:CustomPre[Grad|Pre|Post|PreFusion|PostFusion|PreScheduling]Passes
    │   └── pass:CustomPreSchedulingPasses:<name>  (each pass, with input/output ops)
    ├── sdsc_total
    │   ├── sdsc_bundle_gen
    │   └── dxp_standalone     (external backend subprocess)
    └── async_compile_wait
```

See [`notes/timing-boundary-map.md`](notes/timing-boundary-map.md)
for the complete map, including three additional class-level wraps
(`GraphLowering.run`, `GraphLowering.compile_to_fn`,
`SpyreKernel.codegen_kernel`) defined in
[`patches/extra_timers.py`](patches/extra_timers.py) and intended for
validation runs.

The recorder itself is [`patches/timing_recorder.py`](patches/timing_recorder.py):
`time.perf_counter_ns`, `try`/`finally` around every stage, ordered
events with inclusive and self time, structured JSON output.

## Cold-compile methodology

Every measurement is a cold compile:

- Fresh Python process per sample.
- Fresh `TORCHINDUCTOR_CACHE_DIR` per sample. This wipes both the
  fxgraph cache and the compiled-wrapper `.py` cache layer, which
  survives `FxGraphCache.clear()`.
- Device init and input `.to("spyre")` transfer happen before the
  timed region and are reported separately as
  `device_init_and_transfer`.
- Spyre acquires the device exclusively per process; samples run
  strictly serially.

The workload harness [`patches/workload_harness.py`](patches/workload_harness.py)
reproduces the flash-attention closure from the test verbatim, so
the compiled path exercised is the same one the test exercises.
The CPU reference computation is available under `--compare-cpu` but
never included in timed runs; correctness was validated separately.

## Workload sweep

`Lq` and `Lk` are varied around the baseline; all other parameters
are held fixed. Three cold-compile samples per point, executed
serially, with the driver in
[`patches/sweep-driver.sh`](patches/sweep-driver.sh).

Primary sweep points (9 in total; 25 samples):

| H | Lq | Lk | inner_bodies | samples |
|---:|---:|---:|---:|---:|
| 8 | 256 | 1024 | 4 | 3 |
| 8 | 512 | 512 | 4 | 3 |
| 8 | 512 | 1024 | 8 | 3 |
| 8 | 512 | 2048 | 16 | 3 |
| 8 | 1024 | 1024 | 16 | 3 |
| 8 | 512 | 4096 | 32 | 3 |
| 8 | 2048 | 1024 | 32 | 3 |
| 8 | 512 | 8192 | 64 | 3 |
| 8 | 1024 | 8192 | 128 | 1 (preliminary) |

The 128-body point is marked preliminary until three samples are
present. It is included with `n=1` for completeness but is not given
equal statistical weight in fitted trends.

### H-dimension controlled sweep

A separate sweep varies `H ∈ {16, 32}` at fixed `Lq=512, Lk=1024` and
otherwise identical block sizes, driven by
[`patches/run_h_sweep.sh`](patches/run_h_sweep.sh). Three cold samples
per point.

| H | Lq | Lk | inner_bodies | samples |
|---:|---:|---:|---:|---:|
| 16 | 512 | 1024 | 16 | 3 |
| 32 | 512 | 1024 | 32 | 3 |

By construction these match the predicted inner-body counts of the
existing `H=8, 512×2048` and `H=8, 512×4096` points, enabling a
controlled H-vs-Lk comparison at equal graph size.
Correctness for each H value is validated separately from the timed
samples by running the harness with `--compare-cpu`, driven by
[`patches/run_h_correctness.sh`](patches/run_h_correctness.sh). CPU
reference time is never included in timed runs.

## Results

- Headline finding, compile-time decomposition, per-pass scaling,
  and next investigations: **[`notes/findings.md`](notes/findings.md)**.
- Table A (workload-level buckets): [`notes/tables/table-a-workload.md`](notes/tables/table-a-workload.md).
- Table B (per-pass scaling against each pass's own `input_operations`):
  [`notes/tables/table-b-passes.md`](notes/tables/table-b-passes.md).
- `dedup_and_promote_constants` cost model:
  [`notes/tables/dedup-mechanism.md`](notes/tables/dedup-mechanism.md).
- Time-to-first-pass, from raw event timestamps:
  [`notes/tables/time-to-first-pass.md`](notes/tables/time-to-first-pass.md).
- Backend scaling per SDSC spec:
  [`notes/tables/backend-per-spec.md`](notes/tables/backend-per-spec.md).
- Unattributed-bucket table:
  [`notes/tables/residual-decomposition.md`](notes/tables/residual-decomposition.md).
- H-dimension controlled scaling and equal-inner-body H-vs-Lk
  comparison: [`notes/tables/h-scaling.md`](notes/tables/h-scaling.md).
- Out-of-sample dedup cost-model check across H:
  [`notes/tables/dedup-oos.md`](notes/tables/dedup-oos.md).
- Plots: [`plots/compile-stages.png`](plots/compile-stages.png),
  [`plots/pass-scaling.png`](plots/pass-scaling.png),
  [`plots/dedup-model-fit.png`](plots/dedup-model-fit.png),
  [`plots/backend-per-spec.png`](plots/backend-per-spec.png).

## Limitations

- Three samples per point support median comparisons but do not
  support tight asymptotic complexity claims.
- The largest point (Lq=1024, Lk=8192) has one committed sample as
  of this snapshot and is treated as preliminary.
- `SENCORES` is fixed at 32; `_distribute_work` and
  `_maybe_scratchpad_planning` scale with core count. Scaling
  behavior at other core counts is out of scope.
- `LX_PLANNING=1` (default) enables `_maybe_scratchpad_planning`;
  under `LX_PLANNING=0` that pass becomes a no-op and its time
  disappears without changing the dominant conclusions.
- `unattributed_compile_fx` is a mixture of AOTAutograd, upstream
  Inductor lowering, upstream fusion + scheduling, and per-kernel
  and wrapper codegen. Its components cannot be characterized
  individually until the additional boundaries in
  `patches/extra_timers.py` are enabled.
- The external backend (`dxp_standalone`) is timed but not
  investigated; the sharp per-spec growth described in the results
  is a signal for the backend team, not a claim about a specific
  cause.

## Reproduction

Prerequisites: a working torch-spyre checkout at the PR #3806 head
with its usual venv (`torch~=2.13`, `torch_spyre` in editable install,
matching flex/deeptools/senlib/spyre-comms), and a Spyre device.

1. Apply the instrumentation patch to torch-spyre:

   ```bash
   patch -p1 < patches/instrumentation.patch
   ```

2. Place the timing recorder next to `torch_spyre/_inductor/`:

   ```bash
   cp patches/timing_recorder.py <checkout>/torch_spyre/_inductor/
   ```

3. Run the sweep (writes JSON dumps into `$DATA_DIR`, one per sample):

   ```bash
   TORCH_SPYRE_TIMING=1 \
     TORCH_SPYRE_CHECKOUT=<checkout> \
     DATA_DIR=./data \
     bash patches/sweep-driver.sh
   ```

4. Run the controlled H-dimension sweep and correctness checks:

   ```bash
   TORCH_SPYRE_TIMING=1 \
     TORCH_SPYRE_CHECKOUT=<checkout> \
     DATA_DIR=./data \
     bash patches/run_h_sweep.sh
   bash patches/run_h_correctness.sh
   ```

5. Regenerate tables and plots from the collected data:

   ```bash
   python3 patches/assemble_analysis.py
   ```

To also capture the additional upstream-Inductor boundaries in a
validation run:

```bash
patch -p1 < patches/extra_timers-hook.patch
cp patches/extra_timers.py <checkout>/torch_spyre/_inductor/
TORCH_SPYRE_TIMING=1 bash patches/run_validation.sh
python3 patches/analyze_validation.py
```

## Next investigations

- Reduce the observed `|operations| × |duplicates|` cost of
  `dedup_and_promote_constants`. The source model is stated in
  `notes/tables/dedup-mechanism.md`.
- Instrument `optimize_restickify_locations` and
  `_maybe_scratchpad_planning` — both show strong superlinear
  scaling and together account for most of the pre-scheduling
  pipeline time.
- Enable `extra_timers.py` and take validation runs at baseline and
  one medium point. If `graphlowering_run` dominates
  `unattributed_compile_fx`, instrument upstream Inductor lowering
  more finely. Only rerun the primary sweep if the added boundaries
  materially change interpretation.
- Surface the backend per-spec growth to the backend team; it is
  outside this study's scope but dominates absolute compile time at
  the largest workloads.
