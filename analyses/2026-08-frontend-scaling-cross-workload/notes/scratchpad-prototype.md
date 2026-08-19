# Scratchpad ExternKernel prefix-sum prototype

Prototype patch: [`patches/scratchpad_prefix_sum.py`](../patches/scratchpad_prefix_sum.py).

Replaces the O(range) per-buffer scan in
`torch_spyre/_inductor/scratchpad/allocator.py:_extern_kernel_in_live_range`
with an O(N)-once prefix-sum built and cached on the GraphLowering
instance, and an O(1) range query per buffer.

Correctness pass smoke: `torch.testing.assert_close(atol=0.01, rtol=0.1)`
passes on workload A baseline (Lq=512, Lk=1024).

## Status

**Measurement in progress.** Baseline vs patched sweep at:

- Workload A `Lq=512, Lk=4096` (b=32) — 3 cold samples each.
- Workload A `Lq=512, Lk=8192` (b=64) — 1 cold validation sample.

The larger `1024×8192` (b=128) point is preliminary (n=1) in the
primary study and is not the right validation target for a scaling-law
comparison; the pair 4096 → 8192 doubles graph size cleanly.

Results section will be filled in once the sweep completes.
