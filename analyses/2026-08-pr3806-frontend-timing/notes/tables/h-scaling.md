### H-dimension controlled scaling (Lq=512, Lk=1024)

Varying `H` at fixed `Lq, Lk` (all other block sizes unchanged). `h_block_size = 4`, so the H-tile count is `H / 4`. Predicted inner bodies grow linearly with H.

| H | H tiles | inner_bodies | FX nodes | pre-sched ops | n_specs | compile_fx (s) | Spyre passes (s) | dxp (s) | sdsc_prep (s) | unattributed (s) | n |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 2 | 8 | 236 | 276 | 273 | 99.36 | 5.28 | 79.60 | 1.74 | 12.45 | 3 |
| 16 | 4 | 16 | 460 | 548 | 545 | 220.91 | 13.89 | 188.00 | 3.35 | 14.64 | 3 |
| 32 | 8 | 32 | 908 | 1092 | 1089 | 580.10 | 40.39 | 509.65 | 6.57 | 24.36 | 3 |

**Ratios relative to H=8, Lq=512, Lk=1024:**

| H | inner_bodies × | FX nodes × | pre-sched ops × | n_specs × | compile_fx × | Spyre passes × | dxp × |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 16 | 2.00 | 1.95 | 1.99 | 2.00 | 2.22 | 2.63 | 2.36 |
| 32 | 4.00 | 3.85 | 3.96 | 3.99 | 5.84 | 7.65 | 6.40 |

### Equal-inner-body comparison: H growth vs Lk growth

The `flash` closure's inner-body count is `(B/b) · (H/h) · (Lq/q) · (Lk/kv)`. Growing `H` or growing `Lk` at fixed other dimensions both multiply that count. Pairs below reach the same predicted inner-body count by different routes; if compiler scaling is a function of compiler-visible program size only, the pairs should agree in FX nodes, `n_specs`, and front-end pass time.

| bodies | H | Lq | Lk | FX nodes | pre-sched ops | n_specs | compile_fx (s) | Spyre passes (s) | dxp (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 16 | 16 | 512 | 1024 | 460 | 548 | 545 | 220.91 | 13.89 | 188.00 |
| 16 | 8 | 512 | 2048 | 444 | 548 | 545 | 219.50 | 13.84 | 186.58 |
| 32 | 32 | 512 | 1024 | 908 | 1092 | 1089 | 580.10 | 40.39 | 509.65 |
| 32 | 8 | 512 | 4096 | 860 | 1092 | 1089 | 568.03 | 40.71 | 497.70 |

