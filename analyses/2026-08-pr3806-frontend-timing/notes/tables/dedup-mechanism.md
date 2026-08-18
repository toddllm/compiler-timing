### `dedup_and_promote_constants` — source-level cost model

From `torch_spyre/_inductor/dedup_constants.py`: the pass loops `for dup in group[1:]:` and calls two O(|operations|) routines per duplicate:

- `_redirect_consumers(operations, dup, canonical)` iterates every
  operation and calls `op.get_read_writes()`.
- `_drop_constant(...)` calls `operations.remove(dup)`, which is
  O(|operations|) on a Python list.

Predicted work is therefore `c · |operations| · |duplicates|`.

| H | Lq | Lk | input_operations | duplicates | operations × duplicates | measured t (ms) | product × baseline | t × baseline |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 256 | 1024 | 118 | 8 | 944 | 193 | 0.21 | 0.22 |
| 8 | 512 | 512 | 140 | 8 | 1,120 | 230 | 0.25 | 0.26 |
| 8 | 512 | 1024 | 276 | 16 | 4,416 | 870 | 1.00 | 1.00 |
| 8 | 512 | 2048 | 548 | 32 | 17,536 | 3486 | 3.97 | 4.01 |
| 8 | 512 | 4096 | 1092 | 64 | 69,888 | 14110 | 15.83 | 16.23 |
| 8 | 512 | 8192 | 2180 | 128 | 279,040 | 54646 | 63.19 | 62.84 |
| 8 | 1024 | 1024 | 548 | 32 | 17,536 | 3464 | 3.97 | 3.98 |
| 8 | 1024 | 8192 | 4356 | 256 | 1,115,136 | 225474 | 252.52 | 259.27 |
| 8 | 2048 | 1024 | 1092 | 64 | 69,888 | 14106 | 15.83 | 16.22 |
| 16 | 512 | 1024 | 548 | 32 | 17,536 | 3505 | 3.97 | 4.03 |
| 32 | 512 | 1024 | 1092 | 64 | 69,888 | 13787 | 15.83 | 15.85 |

Source inspection predicts work proportional to `|operations| × |duplicates|`; measured pass time agrees with that prediction to within a few percent across the measured workload range. Because duplicate count grows approximately proportionally with operation count for this workload, the pass appears near-quadratic in program size — but the underlying cost model is the product, not a universal `O(n²)` in graph size.

