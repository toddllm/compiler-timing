### Backend scaling per SDSC spec

SDSC bundle generation feeds `dxp_standalone` a bundle of `n_specs` op specs. If the backend were linear in the size of the bundle it receives, `dxp / n_specs` would be constant.

| H | Lq | Lk | n_specs | sdsc_bundle_gen (ms) | dxp_standalone (ms) | bundle_gen / spec (ms) | dxp / spec (ms) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 256 | 1024 | 115 | 620 | 31173 | 5.39 | 271.07 |
| 8 | 512 | 512 | 137 | 742 | 36094 | 5.42 | 263.46 |
| 8 | 512 | 1024 | 273 | 1634 | 79604 | 5.99 | 291.59 |
| 8 | 512 | 2048 | 545 | 3170 | 186584 | 5.82 | 342.36 |
| 8 | 512 | 4096 | 1089 | 6103 | 497698 | 5.60 | 457.02 |
| 8 | 512 | 8192 | 2177 | 12481 | 2198927 | 5.73 | 1010.07 |
| 8 | 1024 | 1024 | 545 | 3138 | 195975 | 5.76 | 359.59 |
| 8 | 1024 | 8192 | 4353 | 25042 | 13401007 | 5.75 | 3078.57 |
| 8 | 2048 | 1024 | 1089 | 6134 | 538534 | 5.63 | 494.52 |
| 16 | 512 | 1024 | 545 | 3136 | 188001 | 5.75 | 344.96 |
| 32 | 512 | 1024 | 1089 | 6150 | 509652 | 5.65 | 468.00 |

`sdsc_bundle_gen` per spec is approximately constant across the measured range: torch-side bundle generation is linear in `n_specs`. `dxp / n_specs` increases substantially over the same range, indicating strongly superlinear backend scaling in the size of the bundle it receives. The external backend is outside the scope of this study and is reported here only for context; it dominates the absolute compile time attributed to `compile_fx_wrapper` at every measured workload point.

