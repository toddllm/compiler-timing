### Unattributed compile_fx

Time inside `compile_fx_wrapper` that this instrumentation does not yet bracket individually. Computed per run and then medianed rather than by subtracting bucket-wise medians (medians do not compose algebraically).

Contains, in decreasing order of expected weight:

- AOTAutograd joint-graph decomposition
- Upstream Inductor decomposition and lowering (`GraphLowering.run`)
- Upstream Inductor fusion and scheduling
- `SpyreKernel` per-kernel codegen
- `SpyrePythonWrapperCodegen` (host-side wrapper generation)
- Any Spyre pass work outside a `pipeline:*` event

Does not contain:

- Dynamo capture (runs outside `compile_fx`)
- `dxp_standalone` (its own bucket)
- `sdsc_bundle_gen` (part of `sdsc_total`)

| H | Lq | Lk | compile_fx (s) | Spyre pipelines (s) | sdsc_total (s) | unattributed (s) | unattributed % of compile_fx |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 256 | 1024 | 42.78 | 2.19 | 31.84 | 8.78 | 20.5% |
| 8 | 512 | 512 | 51.98 | 2.42 | 36.89 | 12.67 | 24.4% |
| 8 | 512 | 1024 | 99.36 | 5.28 | 81.36 | 12.45 | 12.5% |
| 8 | 512 | 2048 | 219.50 | 13.84 | 189.93 | 16.81 | 7.7% |
| 8 | 512 | 4096 | 568.03 | 40.71 | 504.23 | 24.09 | 4.2% |
| 8 | 512 | 8192 | 2379.66 | 128.90 | 2212.19 | 40.20 | 1.7% |
| 8 | 1024 | 1024 | 232.70 | 13.79 | 199.34 | 17.98 | 7.7% |
| 8 | 1024 | 8192 | 13955.57 | 460.56 | 13427.74 | 67.27 | 0.5% |
| 8 | 2048 | 1024 | 609.53 | 40.67 | 545.12 | 23.91 | 3.9% |
| 16 | 512 | 1024 | 220.91 | 13.89 | 191.38 | 14.64 | 6.6% |
| 32 | 512 | 1024 | 580.10 | 40.39 | 516.25 | 24.36 | 4.2% |

The bucket grows more slowly than `dxp_standalone` and the Spyre pass pipelines over the measured range, but its internal components cannot be characterized individually until the additional boundaries in `patches/extra_timers.py` are enabled.

