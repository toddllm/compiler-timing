# Verification policy

Non-negotiable rules for declaring a forward-compat patch VERIFIED. A
patch that has not passed the full matrix appropriate to its scope is
UNVERIFIED, no matter how confidently it "builds" or "imports".

"Build passes" alone is not "compatible". A green `pip install -e .`
proves that setup.py ran to completion — nothing more. It says
nothing about whether the module imports, whether the affected
subsystem still works, whether the changed path produces the same
values on device as on CPU, or whether unrelated compiler stages
still function.

Every accepted patch carries a **verification matrix** recorded in
`04-verification.md` for that case. The matrix has seven required
rows. A row is either **PASS** (with evidence), **FAIL** (patch is
rejected, back to `02-fault-plan.md`), **N/A** (with justification —
e.g. no supported-torch install available on this pod), or
**DEFERRED** (with the specific condition under which the row must
be revisited before merge).

Only when every row is PASS or an explicitly-justified N/A is the
patch **VERIFIED**. Any DEFERRED row blocks merge; it does not block
recording the interim state.

## The seven-row matrix

Each row states what evidence is required, what artifact captures it,
and what disqualifies a claim of PASS.

### Row 1 — TARGETED TEST

**Claim.** The exact original reproducer that surfaced the
incompatibility now completes successfully.

**Evidence required.**

- The original failing invocation, verbatim (same script, same args,
  same env). Not a paraphrased variant, not a minimized extract —
  the actual command from `01-symptom.md`.
- Exit code 0, or the specific success signal the reproducer defines
  (e.g. "produced N tokens", "compile_fx returned a callable").
- Full stdout+stderr captured to `04-verification.md/targeted.log`.

**Disqualifiers.**

- A "similar" reproducer. If you shrank the input, that is a
  neighbor test (Row 2), not the targeted test.
- Silent success — a script that swallows the exception and prints
  nothing. The success signal must be positive.
- Success on a different torch version than the one the failure was
  filed against.

### Row 2 — NEIGHBOR TESTS

**Claim.** The subsystem surrounding the patched call site still
works. Fixes are locally-correct-and-globally-broken by default;
this row is what breaks that default.

**Evidence required.**

- Identify the subsystem from `compat-taxonomy.md` (e.g. "dynamo
  frontend", "inductor lowering", "torch.export path", "custom-op
  registration"). The taxonomy row names the neighbor test set.
- Run the neighbor set from a fresh Python process per test. Record
  pass/fail counts and any newly-failing test with its full
  traceback.
- Minimum neighbor coverage: three tests exercising the same
  subsystem, at least one of which does NOT exercise the patched
  code path (to catch collateral damage).

**Disqualifiers.**

- Neighbors chosen after the patch was written to match its shape.
  Neighbor tests must be selected from `compat-taxonomy.md` before
  the patch, and recorded in `02-fault-plan.md` under
  `## Neighbor set`.
- "The failure is unrelated to my change" — if a neighbor test that
  passed before the patch fails after, the patch owns the
  regression until proven otherwise.

### Row 3 — SUPPORTED-PYTORCH CHECK

**Claim.** On the torch version torch-spyre currently declares as
supported (the version pin in `pyproject.toml` at the tip of
torch-spyre `main`), the changed path still works.

**Evidence required.**

- Re-read torch-spyre's declared pin at runtime — do NOT hard-code
  a version. The current declared support is `torch~=2.13.0` in
  torch-spyre@a3128985:pyproject.toml, but this file is authoritative
  and the scripts must query it.
- Install exactly that torch version in a separate virtualenv (or
  use an existing pod venv known to match). Record the installed
  `torch.__version__` and `torch.__file__` in the matrix.
- Re-run the targeted test (Row 1) under the supported torch. It
  must still pass — the forward-compat fix must not regress the
  version we officially support.

**Disqualifiers.**

- "Supported torch is already broken here" — if the targeted test
  fails on supported torch *before* the patch, the failure is not
  a forward-compat issue; escalate to `compat-taxonomy.md` and
  reclassify.
- Version drift — `torch==2.13.1` when the pin is `~=2.13.0` is
  fine; `torch==2.14.0` is not, no matter how close.

**When N/A is acceptable.** The pod has no compatible venv AND
building supported-torch from source would exceed the fault
budget. Justify in the matrix and mark this row DEFERRED until
merge review.

### Row 4 — LATEST-PYTORCH CHECK

**Claim.** On the exact latest upstream pytorch revision the fix
was authored against, the changed path works.

**Evidence required.**

- The specific pytorch commit SHA the patch was verified against —
  not "main", not "nightly", the resolved 40-hex SHA. As of
  2026-08-21 that reference is
  `73961011bf64f1c04b3291bf90ac1dbbe197c2ca` for pytorch main; the
  scripts must resolve this from `git ls-remote` at run time and
  record what they resolved.
- The installed torch's `torch.__version__` and the git SHA of its
  source tree (from `python -c "import torch; print(torch.version.git_version)"`
  or equivalent).
- Re-run the targeted test (Row 1) under that exact pytorch. It
  must pass.

**Disqualifiers.**

- A different SHA than what `02-fault-plan.md` recorded. If
  upstream moved during authoring, re-verify at the new SHA and
  update the plan.
- A local build with uncommitted changes. `git status` must be
  clean in the pytorch tree used for this row.

### Row 5 — DEVICE CORRECTNESS

**Claim.** Where the patched path produces tensor outputs, those
outputs match a CPU/eager oracle within the tolerance the affected
op documents.

**Evidence required.**

- The same input fed to (a) the patched Spyre path and (b) an eager
  CPU reference. Both invocations recorded in
  `04-verification.md/device-correctness.log`.
- `torch.allclose` (or `torch.testing.assert_close`) with the
  op-appropriate `rtol`/`atol`. Record the tolerances used and why
  (link to the upstream op's documented precision or to the
  existing torch-spyre reference for that op).
- If the change is a graph-transform / pass-pipeline change with no
  new numerics, still run the oracle — the point of the row is that
  the transform did not silently mutate values.

**When N/A is acceptable.** The patched path produces no tensors
(pure metadata, registration wiring, error-message change). State
which and cite the changed lines.

**Disqualifiers.**

- Oracle chosen to be permissive. `atol=1e-1` on an op that
  documents `1e-5` is a failing row, not a passing one.
- CPU oracle that shares the buggy path (e.g. both invocations go
  through the same Python helper). The oracle must be independent.

### Row 6 — BUILD/IMPORT (clean environment)

**Claim.** A clean Python environment can install torch-spyre with
the patch applied, and `import torch_spyre` succeeds without
warnings that were not present before the patch.

**Evidence required.**

- A fresh venv (`python -m venv .venv-verify` in an empty
  directory), `pip install -e .` from the patched tree, followed by
  `python -c "import torch_spyre; print(torch_spyre.__version__)"`
  in a separate process.
- The output of `pip install` and the import are both captured.
- Any new `DeprecationWarning`, `UserWarning`, or `RuntimeWarning`
  that the pre-patch tree did NOT emit is flagged and either
  justified in the matrix or fixed.

**Disqualifiers.**

- Reusing the development venv where the patch was authored.
  Author-venv state (stray `.pth` files, `pip install`ed local
  editable siblings, environment variables in the shell rc) can
  mask install-time regressions.
- Skipping the separate-process import. A build that only imports
  in the same process as its installer can miss import-order bugs.

### Row 7 — BROADER COMPILER SMOKE

**Claim.** Representative compiler tests NOT directly related to
the patched failure still pass. This catches the class of bug where
a well-intentioned fix in one lowering breaks an unrelated pass
that happened to depend on the old shape.

**Evidence required.**

- A named smoke set of at least three tests drawn from
  torch-spyre's compiler test suite, picked to cover: (a) a
  frontend/dynamo path, (b) a mid-stack lowering path, (c) a
  backend/codegen path. The specific tests are recorded in
  `02-fault-plan.md` under `## Broader smoke set` so they cannot be
  chosen post-hoc.
- Each test invoked from a fresh process, results captured.
- No test that passed pre-patch may fail post-patch. A test that
  was already failing pre-patch can be recorded as pre-existing
  and does not block the row, but its pre-existing failure must be
  cited (issue number, commit that introduced it, or a
  `git bisect` result).

**Disqualifiers.**

- Smoke set of one test. Three is the floor.
- All three tests exercising the same subsystem. If the patch is
  in the frontend and all three smoke tests are frontend tests,
  the row is meaningless — it collapses into Row 2.

## The FRESH-POD REPRODUCTION test — §18

The seven-row matrix above verifies the patch on the substrate where
the fix was developed. That substrate has accumulated state — venvs
built up over the investigation, torch versions installed for
neighbor comparisons, `TORCHINDUCTOR_CACHE_DIR` values scattered
across `/tmp`. A patch that PASSes the matrix on a well-worn dev pod
can still fail on a clean pod that a coworker (or CI) creates
tomorrow from the same base image.

The fresh-pod reproduction test is the **acceptance gate**: it
proves the patch works on a clean substrate, not just in the pod
where it was authored.

### When §18 is required

Always, before a patch is merged. The seven-row matrix is necessary
but not sufficient; §18 is the closing check.

The one exception: the patch is a documentation-only or comment-only
change with no code paths touched. State this explicitly in
`04-verification.md/fresh-pod.md` and cite `git diff --stat` showing
only `.md` files.

### The reference fresh pod

For the first empirical case of this skill, the fresh pod is:

- **Pod name:** `tdeshane-forward-compat-2026-08-21`
- **Namespace:** `a5-deepview`
- **Base image:** `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest`
- **Image digest:** to be recorded at pod-creation time (immutable
  once resolved) into `04-verification.md/fresh-pod.md` under
  `## Substrate`.

Subsequent cases spin their own fresh pods. Name them
`tdeshane-forward-compat-<yyyy-mm-dd>[-suffix]` and record the same
substrate metadata.

### What runs on the fresh pod

The full seven-row matrix, re-executed. Not a "spot check", not
"just the targeted test" — the full matrix. The dev-pod matrix
proves the patch is right; the fresh-pod matrix proves the substrate
is not lying.

Concretely:

1. Create the pod from the base image. Record the resolved digest
   (`skopeo inspect` or the equivalent registry query) — pin the
   digest in the record, not the mutable `:latest` tag.
2. Clone torch-spyre at the patched SHA (or apply the patch to a
   clean checkout of the target base). Nothing else is
   pre-installed beyond what the base image ships.
3. Resolve pytorch's exact latest SHA at pod-creation time (fresh
   `git ls-remote`) and record it. Do not assume it still matches
   the SHA in Row 4 — upstream may have moved.
4. Re-read torch-spyre's declared torch pin from `pyproject.toml`
   at runtime. Do NOT hard-code `2.13.0` or any other version;
   the pin may have moved between dev-pod verification and
   fresh-pod verification.
5. Run each of the seven rows. Same evidence bar as before.
6. Compare results row-by-row against the dev-pod matrix. Any
   divergence — a row that PASSed on the dev pod and FAILs on the
   fresh pod, or vice versa — is a substrate-dependence finding.
   The patch cannot be VERIFIED until the divergence is explained
   and either fixed (the patch is amended) or documented as an
   environment requirement (added to the fix's prerequisites in
   `04-verification.md`).

### The substrate-dependence trap

The failure mode this section exists to catch: a patch that leans
on state present only on the dev pod. Common instances:

- An import that works because a sibling package happens to be
  editable-installed at the dev pod but is not on a fresh pod.
- A `sys.path` order that only holds when the dev pod's shell rc
  has been sourced.
- A cached compile artifact under an old `TORCHINDUCTOR_CACHE_DIR`
  that satisfies a lookup the patch assumed would miss.
- An env var (`TORCH_SPYRE_*`, `PYTORCH_*`) exported in the dev
  pod's session but absent from the fresh pod.

The fresh-pod matrix catches these because the fresh pod has none
of that history. If the matrix passes there, the patch is portable.

### Recording §18

Under `04-verification.md/fresh-pod.md`:

- `## Substrate` — pod name, namespace, base image, resolved image
  digest, pod-creation timestamp.
- `## Resolved refs` — torch-spyre SHA under test, pytorch SHA
  under test, torch-spyre's declared torch pin as read from
  `pyproject.toml` at pod-creation time.
- `## Matrix` — the seven-row table, each row PASS/FAIL/N/A with
  its evidence path (log files stored under
  `04-verification.md/fresh-pod-logs/`).
- `## Divergence from dev-pod matrix` — either "none" or a list of
  rows that differed, with the resolution.

## Recording the matrix

The matrix lives in `04-verification.md` for each case. The
`case-templates/` directory carries a starter file with the seven
rows and the §18 section pre-populated with placeholders — copy it,
fill it in, do not edit its structure without updating this policy.

Each row records, at minimum:

- **Status** — PASS / FAIL / N/A / DEFERRED.
- **Evidence path** — path to the log / json / diff that supports
  the status.
- **Timestamp** — when the row was executed. A row older than the
  latest patch amendment is stale and must be re-run.
- **Substrate** — dev-pod name and SHA, or fresh-pod name and
  resolved image digest.

A row with a stale timestamp is not PASS. If you amend the patch
after Row 5 was recorded, Rows 1–7 all become stale and must be
re-run — the matrix is per-patch-version, not per-patch-idea.

## VERIFIED — the terminal state

A patch is **VERIFIED** exactly when:

- All seven rows on the dev pod are PASS or justified N/A.
- All seven rows on the fresh pod (§18) are PASS or justified N/A.
- No row is DEFERRED.
- No row is stale relative to the current patch content
  (`git hash-object` of the patch file matches what each row
  recorded).
- The `04-verification.md` file is complete: matrix, §18 section,
  divergence resolution.

Any other state is UNVERIFIED. UNVERIFIED patches may be shared for
review, discussed, or held for later; they may NOT be described as
"forward-compat fixed" in reviewer-facing text, commit messages, or
PR descriptions.

"Build passes" is Row 6 alone. It is one row out of seven, on one
substrate out of two. Do not confuse it with "compatible".
