# CustomPreSchedulingPasses — top passes per shape

Top 12 passes by median inclusive ms.

## flash-1024x8192

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 214356.7 |
| 2 | optimize_restickify_locations | 138175.7 |
| 3 | span_reduction | 12331.3 |
| 4 | propagate_spyre_tensor_layouts | 8910.0 |
| 5 | _distribute_work | 8795.2 |
| 6 | insert_restickify_padding | 3534.8 |
| 7 | dedup_and_promote_constants | 1017.3 |
| 8 | deadcode_elimination | 962.5 |
| 9 | split_multi_ops | 955.5 |
| 10 | validate_ops | 820.9 |
| 11 | enforce_indirect_access_layout | 661.5 |
| 12 | insert_bmm_padding | 63.2 |

## flash-512x1024

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 4552.0 |
| 2 | optimize_restickify_locations | 1359.7 |
| 3 | span_reduction | 775.5 |
| 4 | propagate_spyre_tensor_layouts | 570.9 |
| 5 | _distribute_work | 524.3 |
| 6 | insert_restickify_padding | 216.5 |
| 7 | deadcode_elimination | 60.4 |
| 8 | dedup_and_promote_constants | 59.7 |
| 9 | validate_ops | 49.9 |
| 10 | enforce_indirect_access_layout | 40.4 |
| 11 | split_multi_ops | 30.7 |
| 12 | insert_bmm_padding | 3.9 |

## flash-512x8192

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 59819.8 |
| 2 | optimize_restickify_locations | 38693.8 |
| 3 | span_reduction | 6155.6 |
| 4 | propagate_spyre_tensor_layouts | 4612.1 |
| 5 | _distribute_work | 4296.4 |
| 6 | insert_restickify_padding | 1750.3 |
| 7 | dedup_and_promote_constants | 486.3 |
| 8 | deadcode_elimination | 478.1 |
| 9 | validate_ops | 400.9 |
| 10 | split_multi_ops | 336.7 |
| 11 | enforce_indirect_access_layout | 328.0 |
| 12 | insert_bmm_padding | 31.6 |

## mlp-L2-w2048

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 2136.2 |
| 2 | _distribute_work | 18.4 |
| 3 | span_reduction | 17.7 |
| 4 | propagate_spyre_tensor_layouts | 12.5 |
| 5 | optimize_restickify_locations | 4.1 |
| 6 | insert_restickify_padding | 2.3 |
| 7 | deadcode_elimination | 1.6 |
| 8 | enforce_indirect_access_layout | 1.4 |
| 9 | insert_bmm_padding | 1.2 |
| 10 | validate_ops | 0.8 |
| 11 | split_multi_ops | 0.6 |
| 12 | finalize_layouts | 0.1 |

## mlp-L32-w2048

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 715.7 |
| 2 | span_reduction | 269.3 |
| 3 | _distribute_work | 227.3 |
| 4 | optimize_restickify_locations | 188.5 |
| 5 | propagate_spyre_tensor_layouts | 121.4 |
| 6 | insert_restickify_padding | 36.7 |
| 7 | enforce_indirect_access_layout | 21.0 |
| 8 | deadcode_elimination | 18.6 |
| 9 | validate_ops | 11.6 |
| 10 | split_multi_ops | 6.1 |
| 11 | insert_bmm_padding | 5.6 |
| 12 | finalize_layouts | 0.9 |

