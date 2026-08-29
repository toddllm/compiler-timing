# CustomPreSchedulingPasses — top passes per shape

Top 12 passes by median inclusive ms.

## flash-1024x1024

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 3863.9 |
| 2 | _maybe_scratchpad_planning | 2815.2 |
| 3 | span_reduction | 1586.8 |
| 4 | _distribute_work | 1114.0 |
| 5 | propagate_spyre_tensor_layouts | 1089.4 |
| 6 | insert_restickify_padding | 423.6 |
| 7 | deadcode_elimination | 111.5 |
| 8 | validate_ops | 109.4 |
| 9 | dedup_and_promote_constants | 103.1 |
| 10 | enforce_indirect_access_layout | 81.6 |
| 11 | split_multi_ops | 65.4 |
| 12 | finalize_layouts | 13.3 |

## flash-1024x8192

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 215121.5 |
| 2 | optimize_restickify_locations | 138354.0 |
| 3 | span_reduction | 12709.0 |
| 4 | _distribute_work | 9192.6 |
| 5 | propagate_spyre_tensor_layouts | 8482.1 |
| 6 | insert_restickify_padding | 3331.3 |
| 7 | split_multi_ops | 971.2 |
| 8 | deadcode_elimination | 885.2 |
| 9 | dedup_and_promote_constants | 853.5 |
| 10 | validate_ops | 849.1 |
| 11 | enforce_indirect_access_layout | 641.4 |
| 12 | finalize_layouts | 112.6 |

## flash-2048x1024

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 11734.3 |
| 2 | _maybe_scratchpad_planning | 11004.1 |
| 3 | span_reduction | 3162.0 |
| 4 | _distribute_work | 2245.8 |
| 5 | propagate_spyre_tensor_layouts | 2137.5 |
| 6 | insert_restickify_padding | 834.1 |
| 7 | deadcode_elimination | 222.8 |
| 8 | validate_ops | 211.1 |
| 9 | dedup_and_promote_constants | 205.8 |
| 10 | enforce_indirect_access_layout | 160.9 |
| 11 | split_multi_ops | 142.4 |
| 12 | finalize_layouts | 28.7 |

## flash-256x1024

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 499.6 |
| 2 | _maybe_scratchpad_planning | 389.6 |
| 3 | span_reduction | 340.0 |
| 4 | propagate_spyre_tensor_layouts | 257.1 |
| 5 | _distribute_work | 239.2 |
| 6 | insert_restickify_padding | 88.9 |
| 7 | deadcode_elimination | 23.8 |
| 8 | dedup_and_promote_constants | 22.1 |
| 9 | validate_ops | 20.5 |
| 10 | enforce_indirect_access_layout | 17.3 |
| 11 | split_multi_ops | 15.1 |
| 12 | finalize_layouts | 2.8 |

## flash-512x1024

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 1357.2 |
| 2 | _maybe_scratchpad_planning | 798.5 |
| 3 | span_reduction | 789.6 |
| 4 | _distribute_work | 553.7 |
| 5 | propagate_spyre_tensor_layouts | 542.8 |
| 6 | insert_restickify_padding | 208.3 |
| 7 | deadcode_elimination | 55.8 |
| 8 | validate_ops | 52.5 |
| 9 | dedup_and_promote_constants | 51.0 |
| 10 | enforce_indirect_access_layout | 40.3 |
| 11 | split_multi_ops | 31.5 |
| 12 | finalize_layouts | 6.3 |

## flash-512x2048

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 3832.7 |
| 2 | _maybe_scratchpad_planning | 2718.9 |
| 3 | span_reduction | 1576.2 |
| 4 | _distribute_work | 1110.8 |
| 5 | propagate_spyre_tensor_layouts | 1060.4 |
| 6 | insert_restickify_padding | 415.0 |
| 7 | deadcode_elimination | 112.0 |
| 8 | validate_ops | 106.9 |
| 9 | dedup_and_promote_constants | 105.0 |
| 10 | enforce_indirect_access_layout | 81.2 |
| 11 | split_multi_ops | 64.7 |
| 12 | finalize_layouts | 12.6 |

## flash-512x4096

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 11690.6 |
| 2 | _maybe_scratchpad_planning | 11187.5 |
| 3 | span_reduction | 3152.6 |
| 4 | _distribute_work | 2227.8 |
| 5 | propagate_spyre_tensor_layouts | 2121.5 |
| 6 | insert_restickify_padding | 834.0 |
| 7 | deadcode_elimination | 224.3 |
| 8 | validate_ops | 212.2 |
| 9 | dedup_and_promote_constants | 205.7 |
| 10 | enforce_indirect_access_layout | 162.1 |
| 11 | split_multi_ops | 144.7 |
| 12 | finalize_layouts | 28.8 |

## flash-512x512

| rank | pass | ms |
|---|---|---|
| 1 | optimize_restickify_locations | 520.1 |
| 2 | span_reduction | 403.1 |
| 3 | _maybe_scratchpad_planning | 391.9 |
| 4 | propagate_spyre_tensor_layouts | 282.0 |
| 5 | _distribute_work | 281.4 |
| 6 | insert_restickify_padding | 103.3 |
| 7 | deadcode_elimination | 28.5 |
| 8 | validate_ops | 26.3 |
| 9 | dedup_and_promote_constants | 26.2 |
| 10 | enforce_indirect_access_layout | 20.1 |
| 11 | split_multi_ops | 16.5 |
| 12 | finalize_layouts | 3.1 |

## flash-512x8192

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 75696.2 |
| 2 | optimize_restickify_locations | 38653.8 |
| 3 | span_reduction | 6377.4 |
| 4 | _distribute_work | 4536.1 |
| 5 | propagate_spyre_tensor_layouts | 4241.0 |
| 6 | insert_restickify_padding | 1662.2 |
| 7 | deadcode_elimination | 445.6 |
| 8 | validate_ops | 423.5 |
| 9 | dedup_and_promote_constants | 418.0 |
| 10 | split_multi_ops | 350.8 |
| 11 | enforce_indirect_access_layout | 319.8 |
| 12 | finalize_layouts | 57.4 |

## mlp-L16-w2048

| rank | pass | ms |
|---|---|---|
| 1 | span_reduction | 130.2 |
| 2 | _distribute_work | 110.7 |
| 3 | _maybe_scratchpad_planning | 82.1 |
| 4 | propagate_spyre_tensor_layouts | 65.6 |
| 5 | optimize_restickify_locations | 30.1 |
| 6 | insert_restickify_padding | 17.7 |
| 7 | deadcode_elimination | 10.8 |
| 8 | enforce_indirect_access_layout | 7.6 |
| 9 | validate_ops | 6.2 |
| 10 | split_multi_ops | 3.9 |
| 11 | insert_bmm_padding | 3.4 |
| 12 | finalize_layouts | 0.5 |

## mlp-L2-w2048

| rank | pass | ms |
|---|---|---|
| 1 | _maybe_scratchpad_planning | 19.1 |
| 2 | _distribute_work | 17.6 |
| 3 | span_reduction | 17.2 |
| 4 | propagate_spyre_tensor_layouts | 12.8 |
| 5 | optimize_restickify_locations | 4.0 |
| 6 | insert_restickify_padding | 2.3 |
| 7 | deadcode_elimination | 1.6 |
| 8 | enforce_indirect_access_layout | 1.1 |
| 9 | validate_ops | 0.8 |
| 10 | split_multi_ops | 0.7 |
| 11 | insert_bmm_padding | 0.5 |
| 12 | finalize_layouts | 0.1 |

## mlp-L32-w2048

| rank | pass | ms |
|---|---|---|
| 1 | span_reduction | 260.5 |
| 2 | _distribute_work | 215.8 |
| 3 | _maybe_scratchpad_planning | 154.1 |
| 4 | propagate_spyre_tensor_layouts | 119.3 |
| 5 | optimize_restickify_locations | 58.8 |
| 6 | insert_restickify_padding | 35.6 |
| 7 | deadcode_elimination | 20.1 |
| 8 | enforce_indirect_access_layout | 15.0 |
| 9 | validate_ops | 12.4 |
| 10 | split_multi_ops | 7.1 |
| 11 | insert_bmm_padding | 6.9 |
| 12 | finalize_layouts | 0.9 |

## mlp-L4-w2048

| rank | pass | ms |
|---|---|---|
| 1 | span_reduction | 34.0 |
| 2 | _distribute_work | 30.5 |
| 3 | _maybe_scratchpad_planning | 27.4 |
| 4 | propagate_spyre_tensor_layouts | 19.5 |
| 5 | optimize_restickify_locations | 7.6 |
| 6 | insert_restickify_padding | 4.6 |
| 7 | deadcode_elimination | 2.8 |
| 8 | enforce_indirect_access_layout | 2.3 |
| 9 | validate_ops | 1.7 |
| 10 | split_multi_ops | 1.3 |
| 11 | insert_bmm_padding | 1.1 |
| 12 | finalize_layouts | 0.2 |

## mlp-L64-w2048

| rank | pass | ms |
|---|---|---|
| 1 | span_reduction | 523.3 |
| 2 | _distribute_work | 434.4 |
| 3 | _maybe_scratchpad_planning | 318.6 |
| 4 | propagate_spyre_tensor_layouts | 235.5 |
| 5 | optimize_restickify_locations | 118.5 |
| 6 | insert_restickify_padding | 71.2 |
| 7 | deadcode_elimination | 39.9 |
| 8 | enforce_indirect_access_layout | 29.7 |
| 9 | validate_ops | 25.1 |
| 10 | split_multi_ops | 13.6 |
| 11 | insert_bmm_padding | 13.3 |
| 12 | finalize_layouts | 1.7 |

## mlp-L8-w2048

| rank | pass | ms |
|---|---|---|
| 1 | span_reduction | 66.2 |
| 2 | _distribute_work | 57.6 |
| 3 | _maybe_scratchpad_planning | 45.7 |
| 4 | propagate_spyre_tensor_layouts | 34.5 |
| 5 | optimize_restickify_locations | 15.3 |
| 6 | insert_restickify_padding | 9.0 |
| 7 | deadcode_elimination | 5.4 |
| 8 | enforce_indirect_access_layout | 3.9 |
| 9 | validate_ops | 3.3 |
| 10 | split_multi_ops | 2.0 |
| 11 | insert_bmm_padding | 1.7 |
| 12 | finalize_layouts | 0.3 |

