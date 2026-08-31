# Draft: handoff message to Will

**Not sent.** For Todd to review, adjust, and send in his own words
(or discard). Deliberately short and forward-looking; the durable
evidence lives in the repo.

---

Hey Will,

Before I head out I wrapped up the #4117 baseline and the two current
Torch-Spyre PRs I was carrying:

- **#4139** — certified greedy seed for placement-only CP-SAT (Ready
  for Review).
- **#4141** — makes OR-Tools genuinely lazy so certified compiles
  skip the SWIG bootstrap entirely (Ready for Review; compounds
  #4139; A/B is about -1 s on cold first useful compile).

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
