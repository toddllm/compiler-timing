# Scan mode — fast triage of many open PRs

`scripts/scan_open_prs.sh <owner>/<repo>` fetches the current open
PRs from the specified repo and, per PR, produces a static impact
classification without running anything.

## Output format

For each PR: one line, formatted as:

```
<pr#>  <label>  <impact_level>  <affected_stages>  <run_recommendation>  — <title>
```

Where:

- `label`: FRONTEND / BACKEND / TEST-ONLY / DOCS / MIXED / UNKNOWN.
- `impact_level`: HIGH / MEDIUM / LOW / NONE. Interest level for
  frontend-perf review, not a pass/fail.
- `affected_stages`: comma-separated stage names from the compiler
  stage map (`coarse_tile`, `dedup`, `restickify`, `scratchpad`,
  `layout_prop`, `csrc`, `scheduler`, `backend_handoff`, `setup`, …).
- `run_recommendation`: NO_RUN / TARGETED_RUN / SCALING_RUN / DEEP_DIVE.
  Corresponds to Level 0 / 1 / 3 / 4 in the level ladder.

## Ranking rules

Rank HIGH:
- Touches a known measured hotspot (`coarse_tile`, `dedup`,
  `restickify`) AND on the hot path (see the three-questions rule
  in `compiler-stage-map.md`).
- Adds/removes a compiler pass in the pre-scheduling pipeline.
- Modifies `BEAM_WIDTH`, `_reads_buffer`, `_find_outside_consumers*`,
  `_patch_retiled_load_indexes`, `_plan_tiling_propagation`,
  `_redirect_consumers`, `_drop_constant`, or the beam-search DP
  routines.

Rank MEDIUM:
- Touches a hotspot file but on a validation/error/setup path.
- Touches `propagate_layouts.py` or hint propagation.
- Touches C-extension code (requires rebuild — higher effort).
- Modifies decomposition table / `_inductor/__init__.py` wrapper.
- Modifies fusion, scheduler, work_division.

Rank LOW:
- Touches non-hotspot compiler code (`spyre_kernel.py`,
  `deadcode_elimination.py`, small utility modules).
- Modifies runtime code with a minor compile-side interface change.

Rank NONE:
- `tests/**` only.
- `docs/**` only.
- `.github/**`, CI config, README, licensing.
- Runtime-only changes with no import from compile-side.
- Backend-only changes to `dxp_standalone` subprocess management
  (classify separately from frontend).

## Ambiguity

If a PR mixes surfaces (e.g. tests + one Spyre pass), classify as
MIXED and pick the highest of the component levels for the run
recommendation. Report the ambiguity in the reasoning field so the
next human/AI can see why.

## Runtime budget

Scan mode is meant to be near-instant per PR: it reads the diff via
`gh pr view` / `gh pr diff` and applies the classification rules.
No device time. No repo clone. Should finish in under 10 seconds
per PR on a warm `gh` cache.

## Emitting a batch report

`scripts/scan_open_prs.sh` writes a Markdown table sorted by rank
(HIGH first) plus a JSON manifest for machine consumption. The
Markdown table's row per PR includes:

- PR number, title, author (visible in `gh pr view`).
- Label + rank + affected stages + run recommendation.
- 1–2 line reasoning (referencing the compiler stage map).

## What scan mode does NOT do

- It does not diff files across revisions to decide whether a hot
  loop was actually changed. It reads the head diff. If the diff
  changed `_reads_buffer`, scan mode escalates to HIGH; a Level-1
  static assessment later will read the actual change and may
  decide it was a comment fix.
- It does not run tests or benchmarks. Only reads.
- It does not know about draft/WIP status; it looks at all open PRs
  including drafts unless `--exclude-drafts` is passed to `gh`.

## Chaining to full assessment

The scan-mode manifest can be fed into a batch run:

```
scripts/scan_open_prs.sh torch-spyre/torch-spyre > /tmp/scan.json
jq -r '.prs[] | select(.rank == "HIGH") | .number' /tmp/scan.json \
  | xargs -I {} scripts/resolve_target.sh {}
```

Then apply the full skill discipline (static assessment → prediction
→ selective measurement) to each HIGH-rank PR.
