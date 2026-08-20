# Static assessment — {{TARGET}}

**Written BEFORE any measurement.** Do not edit after `03-results.md`
exists.

## Target

- Kind: {{pr|commit_range|branch}}
- Repo: {{repo}}
- PR: {{#pr}}
- Base ref → head ref: {{base_ref}} → {{head_ref}}
- Base SHA: {{base_sha}}
- Head SHA: {{head_sha}}
- URL: {{url}}

## Diff summary

- Files changed: {{n}}
- +{{additions}} / −{{deletions}}
- Changed paths (one per line, grouped by top-level directory):
  ```
  {{paths}}
  ```

## Per-path static triage

| Path | Stage | Hot-path? | Confidence | Rule that fired |
|---|---|---|---|---|
| {{path}} | {{stage}} | {{yes/gated/no/uncertain}} | {{low/med/high}} | {{rule}} |

## Predicted affected compiler surface

- Passes/stages expected to move: {{...}}
- Passes/stages expected NOT to move: {{...}}

## Prediction

- **Direction**: {{improvement / regression / neutral / unknown}}
- **Magnitude class**: {{none / small / moderate / potentially_large / unknown}}
- **Reasoning** (short): {{...}}

## Failure modes for this prediction

- If measurement shows movement in passes not listed above, the
  static triage missed a hot path — record which one and update
  `references/compiler-stage-map.md`.
- If measurement shows no movement despite HIGH-confidence
  prediction, the change may be on a gated path — record the gate
  and confirm the sentinel activates it.
- If structural counters change but pass time does not, the
  classification is likely `STRUCTURAL_CHANGE_NEUTRAL`; the
  prediction should be revisited.

## Confidence

{{low / medium / high}} — {{why}}
