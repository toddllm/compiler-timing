### H-dimension correctness

For each `H ∈ {16, 32}` at `Lq=512, Lk=1024`, the compiled Spyre
output is compared against the CPU reference by
`patches/run_h_correctness.sh`. The CPU reference runs strictly
outside the timed region (`--compare-cpu`), and correctness is
performed in a separate process from the timed sweep so the timing
dataset is not perturbed.

Raw evidence is committed alongside the timing dataset in
[`../../data-correctness/`](../../data-correctness/); each file's
`meta.cpu_reference_ok` field records the pass/fail decision from
`torch.testing.assert_close(atol=0.1, rtol=0.1)`.

| H | Lq | Lk | tolerance | `cpu_reference_ok` | evidence |
|---:|---:|---:|:---|:---:|:---|
| 16 | 512 | 1024 | `atol=0.1, rtol=0.1` | pass | [`data-correctness/h16-correctness.json`](../../data-correctness/h16-correctness.json) |
| 32 | 512 | 1024 | `atol=0.1, rtol=0.1` | pass | [`data-correctness/h32-correctness.json`](../../data-correctness/h32-correctness.json) |
