### Cost decomposition (median ms per point)

| point (Lq×Lk) | samples | total | grouping | redirect(scan) | get_read_writes | list_remove | merge_provenance | bookkeeping | front_load | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 512x1024 | 3 | 976.91 | 0.097 | 1.522 | 967.650 | 0.273 | 0.273 | 0.065 | 0.077 | 0.214 |
| 512x4096 | 3 | 15697.05 | 0.264 | 21.816 | 15568.036 | 3.212 | 1.539 | 0.315 | 0.337 | 0.821 |
| 512x8192 | 3 | 62189.39 | 0.486 | 84.624 | 61687.571 | 12.801 | 3.908 | 0.701 | 0.937 | 1.727 |

### Cost decomposition (percent of dedup total, median)

| point | grouping | redirect(scan) | get_read_writes | list_remove | merge_provenance | bookkeeping | front_load | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 512x1024 | 0.0% | 0.2% | 99.1% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 512x4096 | 0.0% | 0.1% | 99.2% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 512x8192 | 0.0% | 0.1% | 99.2% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

### Consumer-index evidence (name_to_users vs gold scan)

| point | dups | median gold consumers/dup | median NU raw/dup | median NU unique/dup | Σ TP | Σ FP | Σ FN | Σ unwrap fail | consumer types (count) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 512x1024 | 48 | 1 | 1 | 1 | 0 | 45 | 48 | 3 | TensorBox=48 |
| 512x4096 | 192 | 1 | 1 | 1 | 0 | 189 | 192 | 3 | TensorBox=192 |
| 512x8192 | 384 | 1 | 1 | 1 | 0 | 381 | 384 | 3 | TensorBox=384 |

### Verdict

- name_to_users has **624 false negatives** across the sweep. Option A requires a `get_read_writes` filter over the union of the candidate set and the full-scan gold set, or Option E should be preferred.
