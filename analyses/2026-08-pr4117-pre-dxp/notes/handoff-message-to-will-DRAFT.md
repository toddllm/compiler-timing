# Draft: handoff message to Will (send-ready)

**Not sent.** Terminal draft — Todd's technical work is complete, so
this is what a final send would look like. For Todd to review, adjust,
and send in his own words (or discard) when he chooses; nothing here
should change further from the Todd side unless a maintainer response
on #4139 alters the story. Deliberately short and forward-looking; the
durable evidence lives in the repo.

---

Hey Will,

Before I head out I wrapped up the #4117 baseline and the two current
Torch-Spyre PRs I was carrying:

- **#4139** — certified greedy seed for placement-only CP-SAT (Ready
  for Review). Dave Grove commented on 2026-08-31 that joint CP-SAT
  co-optimization is imminent as the shipped default. That obviously
  changes the value proposition — #4139 accelerates only the
  placement-only path, not the joint solver. I've asked Dave whether
  the placement-only path stays a supported path or whether #4139
  should be closed as performance-study evidence for #3932. Awaiting
  his call; no code churn while that decision is pending.
- **#4141** — lazy OR-Tools loading; Ready for Review, stacked on
  #4139, A/B is about -1 s on cold first useful certified compile.
  Rebased onto upstream `7c1d5b6` (post-#4084); all 5 required
  workflows green. Its headline startup win compounds #4139, so if
  the joint switch happens, the win no longer applies to the default
  compile path. Held with #4139 pending Dave's direction.

If joint CP-SAT does become the default, the first performance task
on the new default path is to profile the actual joint solver at
production graph scale — model-building time and solve time
separately, decision-var / constraint counts if practical, scaling
vs graph size. Don't assume it scales like placement-only did.
Reuse `harness/frontend_reconnaissance.py`. Full experiment plan in
`notes/pr4139-pr4141-coopt-transition.md`. **Don't try to extend
#4139's placement-only certificate into the joint solver** — the
joint objective has axes (parallelism, balance, `cost_expr`) that
the forced-spill lower bound doesn't cover.

Your restickify investigation is still the biggest known large-graph
lane by a wide margin — the frozen-tree study had
`optimize_restickify_locations` at ~138 s on flash-1024x8192, and
nothing I did touches it. My reconnaissance on stand-alone workloads
after #4139/#4141 doesn't stress it, so the production data you
already have is the right starting point.

After restickify, the cleanest next target from where I sat was
**SDSC per-spec bundle generation**. Historical ~35.7 s /
~4097 specs / ~9 ms/spec, and I reproduced the per-spec relationship
on a small workload. The interesting bit is that `_compile_specs`
runs `compile_op_spec` twice per spec when `sdsc_cache` is enabled —
one canonical compile just for the cache key. Halving that on cache
misses is a clean, well-bounded lane.

**Shared cross-pass analysis caching** looks speculative on the
data I have. `op_read_writes` is already memoised, and on the small
workloads I could measure, nothing else looked repeated at a
suspicious count. Please only pursue it if a large-graph rerun of
`frontend_reconnaissance.py` (path below) actually shows expensive
repeated work — don't build an architecture on my small-workload
evidence.

Full measurements, harnesses, decision trees, and continuation order
live in `toddllm/compiler-timing`. The one-page starting point:

`analyses/2026-08-pr4117-pre-dxp/notes/will-continuation-plan.md`

That page has the "run this first" command, the counters to watch,
and the decision tree for what each pattern of results points at.
The full six-card roadmap is in
`notes/frontend-roadmap-handoff.md` next to it.

Ping me if anything about #4139 or #4141 doesn't survive review and
you want context on why we ended up where we did.

Good luck.

— Todd

---

## Cover text options (pick as appropriate to the channel)

**Slack DM to Will:** Send as-is.

**Email to Will:** Prepend a brief subject like
"Torch-Spyre #4117 handoff — continuation plan link inside".

**GitHub @tardieu comment on #4141 or #4139:** *Do not use this
message for that.* Keep any GitHub comment to one paragraph about
the specific PR, per the standing rule about avoiding large
@tardieu updates. If you want to tell Olivier the handoff exists,
one sentence — "the durable roadmap and Will's continuation plan
live at `toddllm/compiler-timing/analyses/2026-08-pr4117-pre-dxp/notes/`"
— is enough.
