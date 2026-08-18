### Table B — pre-scheduling pass scaling

Per-pass median times (ms), 3 samples per point. **The x-axis for each pass is its own `input_operations` (`graph.operations` size at pass entry), recorded on every event.** Passes further down the pipeline see a slightly smaller operation list than the initial FX-node count, so this is the meaningful scaling variable — not global FX nodes.

**Absolute time (ms):**

| pass | 256×1024 | 512×512 | 512×1024 | 512×2048 | 512×4096 | 512×8192 | 1024×1024 | 1024×8192 | 2048×1024 | H16 512×1024 | H32 512×1024 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `dedup_and_promote_constants` | 193 | 230 | 870 | 3486 | 14110 | 54646 | 3464 | 225474 | 14106 | 3505 | 13787 |
| `optimize_restickify_locations` | 680 | 724 | 1700 | 4478 | 12729 | 39475 | 4466 | 132671 | 12658 | 4456 | 12740 |
| `_maybe_scratchpad_planning` | 395 | 434 | 959 | 2403 | 6722 | 21037 | 2390 | 74033 | 6738 | 2436 | 6761 |
| `propagate_spyre_tensor_layouts` | 439 | 476 | 653 | 1270 | 2688 | 4982 | 1273 | 10145 | 2736 | 1281 | 2723 |
| `span_reduction` | 190 | 226 | 446 | 888 | 1775 | 3506 | 885 | 7136 | 1791 | 894 | 1804 |
| `_distribute_work` | 134 | 157 | 312 | 627 | 1257 | 2536 | 623 | 5326 | 1270 | 630 | 1275 |
| `enforce_indirect_access_layout` | 26 | 32 | 61 | 123 | 253 | 490 | 125 | 984 | 253 | 124 | 247 |
| `deadcode_elimination` | 26 | 28 | 56 | 109 | 217 | 430 | 109 | 885 | 219 | 112 | 218 |
| `validate_ops` | 22 | 26 | 52 | 103 | 208 | 412 | 103 | 839 | 207 | 104 | 208 |
| `split_multi_ops` | 11 | 11 | 21 | 43 | 93 | 229 | 43 | 641 | 97 | 43 | 96 |

**Input operations at pass entry:**

| pass | 256×1024 | 512×512 | 512×1024 | 512×2048 | 512×4096 | 512×8192 | 1024×1024 | 1024×8192 | 2048×1024 | H16 512×1024 | H32 512×1024 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `dedup_and_promote_constants` | 118 | 140 | 276 | 548 | 1092 | 2180 | 548 | 4356 | 1092 | 548 | 1092 |
| `optimize_restickify_locations` | 118 | 140 | 276 | 548 | 1092 | 2180 | 548 | 4356 | 1092 | 548 | 1092 |
| `_maybe_scratchpad_planning` | 110 | 132 | 260 | 516 | 1028 | 2052 | 516 | 4100 | 1028 | 516 | 1028 |
| `propagate_spyre_tensor_layouts` | 118 | 140 | 276 | 548 | 1092 | 2180 | 548 | 4356 | 1092 | 548 | 1092 |
| `span_reduction` | 110 | 132 | 260 | 516 | 1028 | 2052 | 516 | 4100 | 1028 | 516 | 1028 |
| `_distribute_work` | 110 | 132 | 260 | 516 | 1028 | 2052 | 516 | 4100 | 1028 | 516 | 1028 |
| `enforce_indirect_access_layout` | 118 | 140 | 276 | 548 | 1092 | 2180 | 548 | 4356 | 1092 | 548 | 1092 |
| `deadcode_elimination` | 110 | 132 | 260 | 516 | 1028 | 2052 | 516 | 4100 | 1028 | 516 | 1028 |
| `validate_ops` | 118 | 140 | 276 | 548 | 1092 | 2180 | 548 | 4356 | 1092 | 548 | 1092 |
| `split_multi_ops` | 110 | 132 | 260 | 516 | 1028 | 2052 | 516 | 4100 | 1028 | 516 | 1028 |

**Cost per input operation (µs/op = ms/n_ops × 1000):**

| pass | 256×1024 | 512×512 | 512×1024 | 512×2048 | 512×4096 | 512×8192 | 1024×1024 | 1024×8192 | 2048×1024 | H16 512×1024 | H32 512×1024 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `dedup_and_promote_constants` | 1633.3 | 1642.4 | 3150.9 | 6361.8 | 12921.4 | 25066.8 | 6320.6 | 51761.8 | 12917.9 | 6396.5 | 12625.8 |
| `optimize_restickify_locations` | 5766.3 | 5169.2 | 6160.5 | 8171.8 | 11657.0 | 18107.7 | 8150.5 | 30457.0 | 11591.8 | 8130.9 | 11667.0 |
| `_maybe_scratchpad_planning` | 3593.3 | 3285.2 | 3688.7 | 4656.2 | 6538.8 | 10252.0 | 4632.7 | 18056.9 | 6554.4 | 4720.3 | 6576.6 |
| `propagate_spyre_tensor_layouts` | 3716.4 | 3400.5 | 2367.0 | 2317.8 | 2461.5 | 2285.4 | 2323.8 | 2328.9 | 2505.4 | 2337.3 | 2493.9 |
| `span_reduction` | 1729.4 | 1709.2 | 1716.5 | 1721.7 | 1727.1 | 1708.4 | 1715.6 | 1740.4 | 1742.3 | 1733.1 | 1755.3 |
| `_distribute_work` | 1216.6 | 1191.3 | 1199.2 | 1215.7 | 1222.7 | 1235.7 | 1206.5 | 1298.9 | 1235.6 | 1221.1 | 1240.0 |
| `enforce_indirect_access_layout` | 223.1 | 225.1 | 220.7 | 224.3 | 231.8 | 225.0 | 228.7 | 226.0 | 231.7 | 227.0 | 226.5 |
| `deadcode_elimination` | 235.4 | 212.6 | 213.7 | 211.0 | 210.7 | 209.8 | 210.7 | 215.9 | 213.3 | 216.9 | 212.3 |
| `validate_ops` | 188.2 | 188.4 | 187.3 | 187.4 | 190.8 | 188.8 | 187.7 | 192.5 | 189.3 | 189.1 | 190.5 |
| `split_multi_ops` | 97.1 | 86.6 | 82.5 | 83.2 | 90.8 | 111.4 | 83.4 | 156.4 | 93.9 | 83.5 | 93.0 |

**Endpoint-to-endpoint log-log slope** (log(t)/log(n) between smallest and largest `input_operations` observed for that pass in the H=8 sweep — 1.0 = linear, 2.0 = quadratic):

| pass | smallest n_ops | largest n_ops | slope | interpretation |
|---|---:|---:|---:|---|
| `dedup_and_promote_constants` | 118 | 4356 | 1.96 | near-quadratic (~n²) |
| `optimize_restickify_locations` | 118 | 4356 | 1.46 | mildly superlinear |
| `_maybe_scratchpad_planning` | 110 | 4100 | 1.45 | mildly superlinear |
| `propagate_spyre_tensor_layouts` | 118 | 4356 | 0.87 | linear or sublinear |
| `span_reduction` | 110 | 4100 | 1.00 | linear or sublinear |
| `_distribute_work` | 110 | 4100 | 1.02 | linear or sublinear |
| `enforce_indirect_access_layout` | 118 | 4356 | 1.00 | linear or sublinear |
| `deadcode_elimination` | 110 | 4100 | 0.98 | linear or sublinear |
| `validate_ops` | 118 | 4356 | 1.01 | linear or sublinear |
| `split_multi_ops` | 110 | 4100 | 1.13 | linear or sublinear |

