# Retrospective — {{TARGET}}

## Was the static prediction correct?

- Predicted direction: {{...}}
- Measured direction: {{...}}
- Predicted magnitude: {{...}}
- Measured magnitude: {{...}}

Verdict: {{correct / partially correct / wrong}}

## Was the experiment selection correct?

- The change touched: {{...}}
- The sentinel exercised: {{...}}
- Did the sentinel actually hit the changed code path?
  {{yes / no / unknown}}
- If not, what would have been better?

## Did static-source suspicion match measured impact?

- Files listed as HIGH interest: {{...}}
- Files that actually contributed to the measurement: {{...}}
- Any files predicted HIGH but not observed to move? — refuted
  hypothesis. Record here.
- Any files predicted LOW but observed to move? — new hot path.
  Update the stage map.

## False positive / false negative check

- False positive: predicted regression, none observed. Cause?
- False negative: predicted no impact, observed regression. Cause?

## Skill lessons learned

- Durable rule change to `references/compiler-stage-map.md`?
- Durable rule change to `references/sentinel-workloads.md`?
- Add a new refuted-hypothesis entry?

## Efficiency

- Device time used: {{...}}
- Naive baseline device time: {{...}}
- Savings: {{...}}
- Was this appropriate level of scrutiny?

## Follow-ups

- Actions: {{...}}
