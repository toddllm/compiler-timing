# CustomPreSchedulingPasses — top passes per shape

Top 12 passes by median inclusive ms.

## flash-512x1024

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 1356.6 |
| 2 | span_reduction | 791.9 |
| 3 | _maybe_scratchpad_planning | 788.2 |
| 4 | _distribute_work | 555.3 |
| 5 | propagate_spyre_tensor_layouts | 542.6 |
| 6 | insert_restickify_padding | 209.1 |
| 7 | deadcode_elimination | 56.3 |
| 8 | validate_ops | 53.2 |
| 9 | dedup_and_promote_constants | 51.6 |
| 10 | enforce_indirect_access_layout | 40.5 |
| 11 | split_multi_ops | 31.7 |
| 12 | finalize_layouts | 6.3 |

## flash-512x4096

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 11718.1 |
| 2 | _maybe_scratchpad_planning | 3456.8 |
| 3 | span_reduction | 3172.9 |
| 4 | _distribute_work | 2229.0 |
| 5 | propagate_spyre_tensor_layouts | 2113.2 |
| 6 | insert_restickify_padding | 833.1 |
| 7 | deadcode_elimination | 223.0 |
| 8 | validate_ops | 211.7 |
| 9 | dedup_and_promote_constants | 206.2 |
| 10 | enforce_indirect_access_layout | 161.6 |
| 11 | split_multi_ops | 144.4 |
| 12 | finalize_layouts | 28.4 |

## flash-512x8192

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 38541.2 |
| 2 | _maybe_scratchpad_planning | 8188.0 |
| 3 | span_reduction | 6313.3 |
| 4 | _distribute_work | 4491.8 |
| 5 | propagate_spyre_tensor_layouts | 4200.7 |
| 6 | insert_restickify_padding | 1662.8 |
| 7 | deadcode_elimination | 452.2 |
| 8 | validate_ops | 423.8 |
| 9 | dedup_and_promote_constants | 419.0 |
| 10 | split_multi_ops | 350.9 |
| 11 | enforce_indirect_access_layout | 320.3 |
| 12 | finalize_layouts | 56.9 |

