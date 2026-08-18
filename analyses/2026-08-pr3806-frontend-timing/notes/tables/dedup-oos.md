### `dedup_and_promote_constants` — out-of-sample check

Coefficient frozen at the value fit through the origin on the H=8 sweep. Each H-sweep point is then evaluated as an out-of-sample prediction: no re-fitting on the new data.

H=8 fit: **t ≈ 201.8 µs × (operations × duplicates)**

| H | Lq | Lk | input_operations | duplicates | operations × duplicates | predicted t (ms) | measured t (ms) | error % |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 16 | 512 | 1024 | 548 | 32 | 17,536 | 3539 | 3505 | -1.0% |
| 32 | 512 | 1024 | 1092 | 64 | 69,888 | 14105 | 13787 | -2.2% |

Updated fit including H-sweep points: **t ≈ 201.8 µs × (operations × duplicates)** (-0.0% relative to the H=8-only coefficient).

