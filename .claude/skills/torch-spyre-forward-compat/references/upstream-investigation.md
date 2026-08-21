# Upstream investigation — root-causing a torch-spyre break against
# newer PyTorch main

When a torch-spyre import, compile, or runtime step fails against a
PyTorch build newer than the one declared in `pyproject.toml`, the
symptom on its own is not a root cause. Two failures can look
identical at the traceback level (`ImportError`, `AttributeError`,
`TypeError`, silent numerical divergence) and require completely
different adaptations: a rename that a one-line import shim fixes;
a semantic contract change that requires a call-site rewrite; or a
deprecation whose replacement API is not yet available at the
version torch-spyre declares support for. The whole point of this
reference is to make that distinction *before* patching, so the fix
lands at the right layer and the retrospective can defend the
adaptation choice.

The investigation is a fixed six-step pipeline. Every step produces
a written artifact in the case directory
(`cases/<case-id>/upstream/<symbol>.md`) that the next step reads.
Do not skip steps; do not merge steps. A missing step is how a
"one-line rename" fix ends up masking a semantic contract change
that resurfaces months later as a numerical bug.

The declared supported torch pin lives in
`torch-spyre@<sha>:pyproject.toml`. **Every script in this skill
MUST re-read it at runtime**; never hard-code `2.13.0` or any other
version. The declared pin is the ground truth for what
torch-spyre's authors intended to compile against, and every
upstream contract in this document is anchored to it.

## Step 1 — Identify the failing torch-spyre call site

The failure lands somewhere concrete. Convert the traceback into a
single `(file, line, function, imported_symbol)` tuple. This is the
first row of `upstream/<symbol>.md` and every later step depends on
it.

Prefer the deepest torch-spyre frame in the traceback — the frame
whose line number moves when torch-spyre code moves, not the frame
whose line number moves when PyTorch code moves. If the deepest
torch-spyre frame is a re-export (a module that does
`from torch._inductor.foo import bar`), record BOTH the re-export
site and the first genuine use site — they may need different
adaptations.

Concrete extraction from a traceback:

```
$ python -c 'import torch_spyre; torch_spyre.compile(model)(x)' 2>&1 \
    | awk '/torch_spyre/ && /^  File/' | tail -n 1
  File "/…/torch_spyre/_inductor/spyre_backend.py", line 47, in _init
    from torch._inductor.decomposition import decompositions as _upstream_decomps
```

Then capture the surrounding context so the retrospective can quote
it verbatim (this is the citation the reviewer will look for):

```
$ git -C ~/torch-spyre-work/torch-spyre rev-parse --short HEAD
a3128985
$ sed -n '40,55p' torch_spyre/_inductor/spyre_backend.py
```

Record it as: `torch-spyre@a3128985:torch_spyre/_inductor/spyre_backend.py:47`
in function `_init`, imported symbol
`torch._inductor.decomposition.decompositions`. Never abbreviate
the citation form to just a filename — the SHA and line number are
what let a reader six months from now find the exact call.

If more than one call site is failing (common with a batched
compile), triage them independently. Two failures at the same
upstream symbol usually share a root cause; two failures at
different symbols do not, no matter how similar the tracebacks
read.

## Step 2 — Identify the upstream contract at the DECLARED supported version

Read `pyproject.toml` at the torch-spyre SHA under investigation
and extract the declared torch requirement — do NOT trust a locally
installed torch version, and do NOT hard-code the pin into the
investigation script:

```
$ git -C ~/torch-spyre-work/torch-spyre show a3128985:pyproject.toml \
    | grep -E '^\s*"?torch[~=<>]'
    "torch~=2.13.0",
```

`~=2.13.0` means "compatible with 2.13.x". Pick the *highest*
release that matches the specifier — that is the declared upper
bound of what the authors intended to work. For `~=2.13.0` this is
the tip of the `release/2.13` branch; for `>=2.13,<2.14` it is the
same. Record the exact tag or commit:

```
$ gh api repos/pytorch/pytorch/releases --jq '.[].tag_name' \
    | grep -E '^v2\.13\.' | head -n 1
v2.13.0
$ gh api repos/pytorch/pytorch/git/refs/tags/v2.13.0 --jq '.object.sha'
<v2.13.0 sha>
```

Now capture the upstream contract for the failing symbol at that
tag. There are three things to record and they are not
interchangeable:

- **Symbol location**: which module/class exports it. Example:
  `torch._inductor.decomposition.decompositions`.
- **Signature/type**: for a callable, the argument list and return
  type. For a data attribute, the type and shape (dict-of-what,
  list-of-what).
- **Semantics**: what the symbol *does*. For a decomposition
  registry, whether entries are keyed by `OpOverload` or
  `OpOverloadPacket`; whether an entry replaces or augments
  upstream defaults; whether a missing entry falls back or raises.

The public github.com/pytorch/pytorch tree makes this cheap:

```
# Signature and location at the declared version
$ gh api repos/pytorch/pytorch/contents/torch/_inductor/decomposition.py \
    --field ref=v2.13.0 -q .content | base64 -d \
    | grep -nE '^(def |class |decompositions\s*=)' | head
```

Cite whatever you find as
`https://github.com/pytorch/pytorch/blob/<v2.13.0 sha>/torch/_inductor/decomposition.py#L<line>` — that
form is durable across future upstream refactors.

If the symbol torch-spyre imports **does not exist at the declared
version**, stop here and jump straight to
`SUPPORTED_VERSION_NO_LONGER_PRACTICAL` in Step 6 — torch-spyre is
already using a symbol from a newer upstream than it declares, and
the "break" is really "torch-spyre never actually worked at the
declared pin". This case is more common than it sounds and is the
single most useful reason to keep the declared-supported control
run in the case plan.

## Step 3 — Compare with current upstream main; find the changing commit/PR

`main` today is at
`73961011bf64f1c04b3291bf90ac1dbbe197c2ca` (2026-08-21). Re-fetch
the current tip at investigation time rather than reusing this
value:

```
$ gh api repos/pytorch/pytorch/branches/main --jq '.commit.sha'
```

Snapshot the symbol at main and diff it against the declared
version:

```
$ gh api repos/pytorch/pytorch/contents/torch/_inductor/decomposition.py \
    --field ref=<main sha> -q .content | base64 -d > /tmp/main.py
$ gh api repos/pytorch/pytorch/contents/torch/_inductor/decomposition.py \
    --field ref=v2.13.0 -q .content | base64 -d > /tmp/v213.py
$ diff -u /tmp/v213.py /tmp/main.py | less
```

Then find the commit that introduced the change. Three tools, in
order of preference:

**`git log -S` for the exact literal that vanished or appeared.**
Best when the change removes or renames a function/attribute — the
literal string is a stable landmark:

```
$ git -C ~/pytorch log --oneline -S 'decompositions =' \
    -- torch/_inductor/decomposition.py \
    v2.13.0..<main sha>
```

`-S` reports commits where the count of the literal changed, so a
rename shows up as one commit that both added the new spelling and
removed the old. Prefer this over `-G` (regex-based, prints
every hit even when the count is unchanged) unless you are
searching for a *pattern* rather than a *literal*.

**`git log --follow` for a file that was moved.**
If the module itself moved (`torch/_inductor/decomposition.py` →
`torch/_inductor/decomp/registry.py`, hypothetical), plain
`git log` on the old path stops at the move commit and pretends the
file was deleted. `--follow` walks through renames:

```
$ git -C ~/pytorch log --follow --oneline \
    -- torch/_inductor/decomposition.py \
    v2.13.0..<main sha>
```

**`git bisect run` for a semantic change** — old signature works,
new signature does not, and the boundary is not textually obvious:

```
$ cat > /tmp/probe.sh <<'EOF'
#!/usr/bin/env bash
set -e
cd ~/pytorch && pip install -e . >/dev/null 2>&1 || exit 125
python /tmp/probe.py
EOF
$ chmod +x /tmp/probe.sh
$ git -C ~/pytorch bisect start <main sha> v2.13.0
$ git -C ~/pytorch bisect run /tmp/probe.sh
```

Return codes matter: `0` = old behavior (good), `1` = new behavior
(bad), `125` = skip (build failed, unrelated). A bisect probe that
returns `1` on unrelated failures will mis-attribute the change to
whatever commit it happened to hit first — always confirm the
probe reproduces the target failure on `main` and NOT on the
declared-version tag before starting the bisect.

Once the commit is identified, resolve its PR (upstream PyTorch
uses GitHub PRs with squash-merged commit messages that include the
PR number):

```
$ SHA=<candidate sha>
$ git -C ~/pytorch log -1 --format='%s' $SHA
migrate decomposition registry to OpOverload keying (#12345)
$ gh -R pytorch/pytorch pr view 12345 --json title,url,body,mergedAt,files \
    --jq '{title, url, mergedAt}'
```

Record the PR number and URL in `upstream/<symbol>.md`. That URL
is the durable citation the retrospective quotes; do not paraphrase
the PR title, quote it verbatim.

## Step 4 — Extract the four contract fields

At this point you have the declared-version symbol, the main
symbol, and the connecting PR. Fill in the four fields exactly:

**Old contract** — what upstream promised at the declared
supported version. Write it as a signature line plus a one-sentence
semantic statement. Cite the file and line at the declared version
tag.

**New contract** — what upstream promises at main today. Same
form: signature, one-sentence semantic statement, cite the file
and line at main.

**Torch-spyre assumption** — which of the two contracts the call
site actually relies on, and *why we can tell*. This is not always
obvious: a call site can import from a location that changed
without actually depending on any changed behavior. Read the
torch-spyre code around the call site (Step 1's line number ±10)
and quote the concrete usage that binds it to the old contract.
Cite as `torch-spyre@<sha>:<path>:<line>`.

**Required adaptation** — the smallest change to torch-spyre that
would satisfy both the declared version and current main
simultaneously, if such a change exists. Do not sketch the diff
yet; state the *shape* of the fix in one sentence.

Example filled-in block (illustrative — the exact symbols depend
on the case):

```
Failing call site:
  torch-spyre@a3128985:torch_spyre/_inductor/spyre_backend.py:47
  Imports torch._inductor.decomposition.decompositions

Old contract (v2.13.0):
  File: torch/_inductor/decomposition.py:118
  decompositions: dict[torch._ops.OpOverloadPacket, Callable]
  Semantics: registry keyed by OpOverloadPacket; a missing
  entry falls back to the ATen default.

New contract (main <sha>):
  File: torch/_inductor/decomp/registry.py:42
  DECOMPOSITIONS: dict[torch._ops.OpOverload, Callable]
  Semantics: registry keyed by OpOverload; a missing entry
  raises DecompNotFound (behavior change PR pytorch/pytorch#12345).

Torch-spyre assumption:
  torch-spyre@a3128985:torch_spyre/_inductor/spyre_backend.py:63
  iterates the dict and does `packet.default in table`, which is
  an OpOverloadPacket-keyed lookup — it directly depends on the
  OLD keying semantics, not just the import location.

Required adaptation:
  Not a rename. The lookup logic must change from
  "packet-keyed with implicit fallback" to
  "overload-keyed with explicit fallback". This is a semantic
  contract change, not a symbol move.
```

If the "required adaptation" line is longer than one sentence, you
have not finished the analysis — split the case into multiple
`upstream/*.md` files, one per contract change.

## Step 5 — Verify the change is semantic, not just cosmetic

Not every upstream change that touches a torch-spyre import site is
a real contract change. The most common false-alarm shapes:

- **Pure import path move.** The symbol is re-exported at the old
  location for backward compatibility. Verify by checking whether
  the old import still resolves against current main:

  ```
  $ cd ~/pytorch && git checkout <main sha>
  $ python -c 'from torch._inductor.decomposition import decompositions; print(decompositions)'
  ```

  If this works, the "break" is at a different call site — go back
  to Step 1 and re-triage. If it errors with `ImportError`, the
  symbol truly moved.

- **Signature widening with default argument.** `foo(a, b)` became
  `foo(a, b, c=None)`. All existing call sites still work; the
  "break" is somewhere else.

- **Type alias rename.** `Layout` became `MemoryLayout`, but
  `Layout` is aliased to the new name. Verify with
  `torch._inductor.foo.Layout is torch._inductor.foo.MemoryLayout`.

The verification is a small, positive check that the OLD call
pattern still produces the OLD behavior at current main. Concrete
recipe:

```
$ cd ~/pytorch && git checkout <main sha>
$ python - <<'EOF'
from torch._inductor.decomposition import decompositions
import torch
# Old pattern: OpOverloadPacket key
packet = torch.ops.aten.add
result = packet.default in decompositions
print("old pattern still works:", result)
EOF
```

If the old pattern still works and produces the old result, the
change is *cosmetic at this call site*. Downgrade the case to
`LATEST_ONLY_FIX` at most (probably no fix needed at all) and
document that torch-spyre's import spelling is stale but not
broken.

If the old pattern raises, produces a different type, or produces
a different value, the change is *semantic*. Proceed to Step 6
with that in hand — the required adaptation is a call-site
rewrite, not an import shim.

**Never** conclude "semantic change" from source-diff structure
alone. A PR that reshuffles a class hierarchy can leave every
observable behavior identical, and a one-line change to a default
value can flip semantics without any structural signal at all.
The runnable check is what separates the two.

## Step 6 — Choose the adaptation strategy

Exactly three labels. Every case is one of them; do not invent a
fourth.

### `LATEST_ONLY_FIX`

The break exists only against upstream main. The declared
supported version (at Step 2's tag) works today and is expected to
keep working through the next torch-spyre release. Torch-spyre
should adapt to the new contract; the old contract will be dropped
along with the pyproject.toml pin bump when the maintainers are
ready.

Use when:

- The old contract has an announced deprecation window and the
  window is still open at the declared version.
- The new contract subsumes the old — a call written for the new
  contract also works against the old one, or vice versa, so
  supporting both simultaneously is not worth the branch.
- The change is aligned with the direction torch-spyre would move
  anyway (e.g. OpOverload keying is the direction the whole
  inductor ecosystem is going).

The fix touches only torch-spyre; the pyproject.toml pin update
happens later, as a coordinated release step, not as part of the
compat fix.

### `DUAL_COMPAT_FIX`

Torch-spyre must work against BOTH the declared supported version
and current main simultaneously — typically because downstream
consumers pin an older torch and cannot upgrade on torch-spyre's
schedule.

Use when:

- Torch-spyre has downstream users pinned to the declared version
  who need continued support (e.g. the Spyre inference stack pins
  a specific torch, unrelated to what upstream main does).
- The change is a rename or a symbol move where both spellings
  are cheap to keep alive with a `try: … except ImportError: …`
  shim.
- The change adds a required argument that has an obvious default
  the old version can supply.

The fix pattern is a compatibility shim, isolated to one module.
Do NOT scatter `if torch.__version__ >= ...` checks across the
codebase; the shim owns the version knowledge and everyone else
imports from it. Example shape (do not copy blindly — the actual
shim depends on the contract):

```python
# torch_spyre/_compat/inductor_decomp.py
try:
    from torch._inductor.decomp.registry import DECOMPOSITIONS as _table
    _KEY_IS_OVERLOAD = True
except ImportError:
    from torch._inductor.decomposition import decompositions as _table
    _KEY_IS_OVERLOAD = False


def lookup(op):
    key = op.default if _KEY_IS_OVERLOAD else op
    return _table.get(key)
```

Every call site imports `lookup` from the compat module; no call
site knows about the two upstreams.

### `SUPPORTED_VERSION_NO_LONGER_PRACTICAL`

The declared supported version cannot be made to work in
combination with something torch-spyre actually needs from a newer
upstream. This is the verdict when the compatibility bridge would
be a substantial engineering project rather than a shim.

Use when:

- The declared version's symbol does not exist at all (Step 2 hit
  the "already using a newer symbol" case).
- Supporting both contracts requires reimplementing an upstream
  algorithm inside torch-spyre — the shim is not a shim, it is a
  fork.
- The declared version has a known-broken interaction with a
  torch-spyre feature that has since shipped (the declared pin
  claims support that empirically does not exist).
- Building the declared version on the fresh pod fails for reasons
  torch-spyre cannot fix (system libs too old, C++ ABI drift).

The correct action is a `pyproject.toml` pin bump proposal,
recorded as a case artifact with the concrete blocker cited. Do
NOT ship a "sort-of works" shim under this label — the whole
point of the label is to escalate to a version-support decision
rather than paper over it.

## Deliverables for the case directory

For each investigated symbol, `cases/<case-id>/upstream/<symbol>.md`
contains, in this order:

1. The `(file, line, function, imported_symbol)` tuple from Step 1.
2. The declared-version tag and the exact symbol contract at that
   tag (Step 2).
3. The current-main SHA and the exact symbol contract at that SHA,
   plus the PR that introduced the change and its URL (Step 3).
4. The four-field extraction block from Step 4.
5. The verification recipe and result from Step 5.
6. The chosen strategy label from Step 6, with the one-paragraph
   rationale that ties it back to the four fields.

The case's top-level `03-results.md` lists every investigated
symbol with its strategy label; the `04-retrospective.md` records
whether the chosen strategy held up after the fresh-pod repro run
and, if not, what the next investigation should try instead.

## Anti-patterns

- **Fixing the symptom.** A silent `try: import X; except ImportError: X = None`
  around a failed import hides the semantic contract change behind
  a `None` sentinel that resurfaces as an `AttributeError` on the
  first real use. The strategy labels exist precisely so that a
  contributor cannot silently downgrade a semantic change to an
  import shim.

- **One-shot rename.** Changing every call site to the new symbol
  name is a `LATEST_ONLY_FIX`; do not describe it as a
  `DUAL_COMPAT_FIX`. Downstream users pinned to the declared
  version will see the fix as a regression.

- **Skipping Step 2.** Diffing against the pod's currently-installed
  torch rather than the declared-supported tag conflates the
  "what actually broke" with "what happens to be installed". The
  latter changes with the base image; the former is what the case
  file must anchor on.

- **Skipping Step 5.** Concluding "semantic change" from a PR
  title alone. Upstream commit messages describe intent; a
  positive runnable check describes reality. Both belong in the
  investigation file, in that order.

- **Blanket `SUPPORTED_VERSION_NO_LONGER_PRACTICAL`.** This label
  is a request to change `pyproject.toml`. Do not use it because a
  fix would take an afternoon; use it because a fix would take a
  quarter.

## Cross-references

- The failing-call-site discovery loop is driven by the fresh-pod
  reproduction run in the sibling `experiment-plan.md` reference.
- The declared-version control run is described in the sibling
  `declared-version-control.md` reference.
- The strategy label chosen here directly feeds the
  hypothesis-before-fix step in the sibling `patch-policy.md`
  reference — the label constrains which patch shapes are valid.
- Every citation form in this file is either
  `torch-spyre@<short-sha>:<path>:<line>` (private repo) or
  `https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>`
  (public). Do not use branch names in citations; they move.
