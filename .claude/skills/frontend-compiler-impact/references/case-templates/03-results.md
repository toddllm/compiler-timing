# Results — {{TARGET}}

## Raw measurements

Data files:

- `data/{{sentinel}}-base-*.json`
- `data/{{sentinel}}-head-*.json`

## Per-metric summary

For each sentinel point:

### {{sentinel}} — {{point}}

| Metric | Base median | Base spread | Head median | Head spread | Δ ms | Δ % |
|---|---:|---|---:|---|---:|---:|
| compile_fx_wrapper | | | | | | |
| pipeline:CustomPreSchedulingPasses | | | | | | |
| pass:_maybe_coarse_tile_hints | | | | | | |
| pass:dedup_and_promote_constants | | | | | | |
| pass:optimize_restickify_locations | | | | | | |
| pass:_maybe_scratchpad_planning | | | | | | |
| pass:propagate_spyre_tensor_layouts | | | | | | |
| sdsc_total | | | | | | |
| dxp_standalone | | | | | | |

### Structural counters

| Counter | Base | Head | Changed? |
|---|---|---|---|
| fx_nodes_at_entry | | | |
| n_specs | | | |
| pass:dedup:input_operations | | | |
| pass:dedup:ops_delta | | | |

## Growth-ratio comparison (Level 3 only)

| Sentinel | Base t(2n)/t(n) | Head t(2n)/t(n) | Ratio change |
|---|---|---|---|

## Classification

**{{FRONTEND_IMPROVEMENT / FRONTEND_REGRESSION / NO_MEASURABLE_FRONTEND_IMPACT / STRUCTURAL_CHANGE_NEUTRAL / BACKEND_IMPACT_ONLY / ACTIVATION_SPECIFIC_IMPACT / INSUFFICIENT_EVIDENCE / NO_RUN}}**

Confidence: {{none / low / medium / high}}

Absolute effect: {{Δ_ms}} on {{metric}}.
Relative effect: {{Δ_%}}.
Sample spread: {{...}}.

## Attribution

Why did numbers move (or not)?

- Structural: {{...}}
- Per-op cost: {{...}}
- Gated path: {{...}}
- Backend: {{...}}

## Device time used

- Actual: {{...}} minutes
- Naive baseline (run everything): {{...}} minutes
- Avoided: {{...}} minutes
