### Time-to-first-pass (from raw event timestamps)

Interval from `first_call_wall` t=0 to the start of the named event, computed per run from raw ``t_start_ns`` and medianed. The first Spyre custom pipeline entered is ``CustomPrePasses``; the main pre-scheduling pipeline is ``CustomPreSchedulingPasses``. These are two distinct boundaries — the first Spyre pipeline typically begins about a second before pre-scheduling.

| H | Lq | Lk | t → compile_fx (s) | t → first Spyre pipeline (s) | t → pre-scheduling pipeline (s) |
|---:|---:|---:|---:|---:|---:|
| 8 | 256 | 1024 | 0.28 | 7.64 | 8.00 |
| 8 | 512 | 512 | 0.40 | 11.35 | 11.82 |
| 8 | 512 | 1024 | 0.41 | 9.59 | 10.51 |
| 8 | 512 | 2048 | 0.55 | 11.11 | 12.51 |
| 8 | 512 | 4096 | 0.75 | 12.42 | 15.02 |
| 8 | 512 | 8192 | 1.25 | 15.69 | 20.86 |
| 8 | 1024 | 1024 | 0.62 | 12.65 | 14.03 |
| 8 | 1024 | 8192 | 1.90 | 15.42 | 25.58 |
| 8 | 2048 | 1024 | 0.85 | 12.24 | 14.93 |
| 16 | 512 | 1024 | 0.54 | 9.06 | 10.46 |
| 32 | 512 | 1024 | 0.92 | 12.81 | 15.53 |

The gap between `t → compile_fx` and `t → first Spyre pipeline` is upstream Inductor work (AOTAutograd, decomposition, `GraphLowering` construction). The gap between the first Spyre pipeline and `t → pre-scheduling` is upstream Inductor lowering, scheduling, and Spyre-specific graph-level FX passes.

Dynamo capture is not inside `compile_fx_wrapper`: `compile_fx` receives an already-captured `gm` and `example_inputs`. Dynamo runs upstream of this boundary, before the compiled call reaches `compile_fx`.
