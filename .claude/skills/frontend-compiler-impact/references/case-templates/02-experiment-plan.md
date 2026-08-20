# Experiment plan — {{TARGET}}

**Written BEFORE any measurement.** Fixes the experimental design so
the retrospective can judge whether the prediction was tested.

## Level decision

- **Chosen level**: {{0 / 1 / 2 / 3 / 4}}
- **Rationale**: {{...}}

## Sentinels selected

| Sentinel | Point(s) | Samples/point | Paired? | Rationale |
|---|---|---|---|---|
| {{sentinel}} | {{point}} | {{n}} | yes/no | {{...}} |

## Metrics expected to move

- Positive: {{...}}
- Negative: {{...}}

## Metrics expected NOT to move

- {{...}}

## Structural counters to record

- `fx_nodes_at_entry`
- `n_specs`
- per-pass `input_operations` (for any pass listed as expected-to-move)
- per-pass `ops_delta`

## C-extension rebuild required?

- {{yes/no}} — if yes, note both revisions will be freshly rebuilt
  in isolated checkouts.

## Estimated device time

- Base: {{n × wall}}
- Head: {{n × wall}}
- Total: {{...}}

## Naive baseline

- If we ran WA_baseline + WB_scaling_pair + WA_scaling_pair on every
  PR, this PR would consume: {{...}} device-minutes.
- This plan consumes: {{...}}
- **Device-time saved by targeted selection**: {{...}}
