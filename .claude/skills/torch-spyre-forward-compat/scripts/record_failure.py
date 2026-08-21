#!/usr/bin/env python3
"""Materialize the six-file per-failure record for a forward-compat break.

Purpose
-------

When Stages 0..5 of the forward-compat validation ladder surface a
break, the response is not "start editing torch-spyre". The response
is: open a per-failure record, write down what actually happened,
write down the hypothesis, write down the plan — and only then apply
a patch. This script enforces that ordering on disk.

Concretely, invoked as::

    record_failure.py --dir CASE_DIR --index N \
                      --classification CLASS \
                      --torch-spyre-loc "torch-spyre@<sha>:<path>:<line>" \
                      [--upstream-loc "https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>"] \
                      [--observation OBSERVATION_FILE] \
                      [--stdin]

it creates::

    <CASE_DIR>/failures/<NN>-<slug>/
        01-observation.md          filled from --observation FILE or --stdin
        02-diagnosis-hypothesis.md placeholder — FILL BEFORE FIX
        03-remediation-plan.md     placeholder — FILL BEFORE FIX
        04-patch.md                placeholder — DO NOT write patch until 02,03 done
        05-verification.md         placeholder — populated by verify_patch.sh
        06-retrospective.md        placeholder — written last

Hypothesis-before-fix enforcement
---------------------------------

The whole point of the per-failure record is to keep diagnosis from
being retconned. If 04-patch.md / 05-verification.md / 06-retrospective.md
already exist in the target directory when this script is invoked
without ``--allow-post-fix``, the script refuses to run and exits
non-zero. That protects against re-running the script over a partly-
completed record and blowing away the diagnosis-hypothesis or plan
after a patch has already been drafted — the kind of tidying that
turns "hypothesis" into "rationalization".

The ``--allow-post-fix`` escape hatch exists for one legitimate case:
a scripted regeneration where the caller has already read the
existing 04/05/06 and knows the placeholders should be re-templated
(e.g. the case is being migrated to a new schema). It is never
correct to pass it during normal use.

Design rules
------------

- Stdlib only. This script must run in the fresh-pod venv, the
  laptop venv, and anywhere else a case is prepared.
- The classification, torch-spyre citation, and (optional) upstream
  citation are written into 01-observation.md in the fixed positions
  that patch-policy.md expects — the observation file's own body
  goes below that header. That way a fresh observation captured
  from a copy-pasted traceback still gets the mandatory metadata.
- All placeholders carry a visible "FILL BEFORE FIX" banner. Every
  placeholder file additionally records the script version, the
  timestamp it was created, and the case-directory + failure-index
  it belongs to, so a stray file in the tree can be traced back to
  its context.
- Slug generation is deterministic: derived from the classification
  string (lower-cased, non-alnum → hyphen, trimmed, capped at 40
  characters). No random bits — re-running the script with the same
  arguments produces the same directory name, which matters for
  reproducibility of the case-index → path map.

Exit codes
----------

- 0: record created (or, with ``--allow-post-fix``, re-created).
- 1: refused because a post-fix file already exists.
- 2: usage error (missing args, unreadable observation file, index
     already claimed by a different slug, etc.).
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Optional

SCRIPT_VERSION = 1

# The six templated files, in on-disk order. The record_failure.py
# contract says all six exist after a successful run.
TEMPLATED_FILES = (
    "01-observation.md",
    "02-diagnosis-hypothesis.md",
    "03-remediation-plan.md",
    "04-patch.md",
    "05-verification.md",
    "06-retrospective.md",
)

# The three files whose existence blocks re-templating without
# --allow-post-fix. These are the ones written *after* the patch is
# drafted; if they exist, someone has moved past hypothesis-first and
# re-templating would erase that work.
POST_FIX_FILES = (
    "04-patch.md",
    "05-verification.md",
    "06-retrospective.md",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 40) -> str:
    """Deterministic slug derived from ``text``.

    Lower-cases, collapses runs of non-alphanumerics to a single
    hyphen, strips leading/trailing hyphens, truncates at
    ``max_len`` characters at a hyphen boundary where possible.
    Empty input becomes ``"unclassified"``.
    """
    if not text:
        return "unclassified"
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    if not s:
        return "unclassified"
    if len(s) <= max_len:
        return s
    # Prefer cutting at a hyphen boundary within the last 10 chars of
    # the budget, to avoid mid-word chops when it's cheap to avoid.
    cut = s.rfind("-", 0, max_len)
    if cut >= max_len - 10:
        return s[:cut]
    return s[:max_len]


def read_observation_body(args: argparse.Namespace) -> str:
    """Load the free-text body of 01-observation.md.

    Precedence: ``--observation FILE`` wins over ``--stdin``. Neither
    is required (the caller may want a pure-placeholder observation).
    """
    if args.observation:
        try:
            with open(args.observation, "r") as f:
                return f.read().rstrip() + "\n"
        except OSError as e:
            print(f"error: cannot read --observation file: {e}", file=sys.stderr)
            sys.exit(2)
    if args.stdin:
        return sys.stdin.read().rstrip() + "\n"
    return "(No observation body supplied. Paste the failing command, "\
           "the full traceback / output, and the environment metadata here "\
           "before advancing to 02-diagnosis-hypothesis.md.)\n"


def _banner(kind: str, case_dir: Path, failure_dir_name: str) -> str:
    """A visible marker at the top of every placeholder file.

    Records the script version, the moment the placeholder was
    written, and the case/failure it belongs to. If a stray copy of
    the file surfaces later, this block lets us trace it back.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return textwrap.dedent(
        f"""\
        <!--
          {kind}
          Generated by record_failure.py v{SCRIPT_VERSION}
          Case:            {case_dir}
          Failure dir:     failures/{failure_dir_name}
          Written (UTC):   {now}
        -->
        """
    )


def observation_body_template(
    case_dir: Path,
    failure_dir_name: str,
    classification: str,
    torch_spyre_loc: str,
    upstream_loc: Optional[str],
    body: str,
) -> str:
    """Render 01-observation.md.

    The classification and citation lines occupy fixed positions so
    that downstream tooling (e.g. an eventual index generator) can
    parse them without a full markdown pass.
    """
    banner = _banner("01-observation.md", case_dir, failure_dir_name)
    upstream_line = upstream_loc if upstream_loc else "(none — upstream site not yet located)"
    return (
        banner
        + textwrap.dedent(
            f"""\

            # 01 — Observation

            Written directly from the run that produced the failure.
            No hypothesis in this file. If a "probably because…" sentence
            appears below, move it to `02-diagnosis-hypothesis.md`.

            ## Classification

            {classification}

            (Must match one of the categories in
            `references/failure-taxonomy.md`. If none fits, extend the
            taxonomy first — do not invent an ad-hoc category here.)

            ## Citations

            - torch-spyre site: `{torch_spyre_loc}`
            - upstream PyTorch site: {upstream_line}

            Cite torch-spyre as `torch-spyre@<short-sha>:<path>:<line>`
            (private repo — no permalink). Cite PyTorch as
            `https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>`.

            ## Observation body

            """
        )
        + body
        + textwrap.dedent(
            """\

            ## Determinism

            (State whether the failure reproduces every run, or with what
            fraction. If unknown, run the trigger command three more times
            and record.)
            """
        )
    )


def placeholder_body(
    kind: str,
    case_dir: Path,
    failure_dir_name: str,
    instructions: str,
) -> str:
    """Render a placeholder for 02..06.

    Every placeholder starts with a "FILL BEFORE FIX" (or, for 05/06,
    "FILL BEFORE MERGE") banner in the body itself, in addition to
    the HTML-comment metadata banner at the very top. The HTML
    comment is machine-parseable; the text banner is what a human
    editor sees the moment they open the file.
    """
    banner = _banner(kind, case_dir, failure_dir_name)
    if kind in {"05-verification.md", "06-retrospective.md"}:
        text_banner = "FILL BEFORE MERGE — DO NOT SKIP"
    else:
        text_banner = "FILL BEFORE FIX — DO NOT WRITE 04-patch.md UNTIL THIS FILE IS DONE"
    return (
        banner
        + textwrap.dedent(
            f"""\

            # {kind[:-3]}

            > **{text_banner}**

            {instructions}
            """
        )
    )


def diagnosis_hypothesis_template(case_dir: Path, failure_dir_name: str) -> str:
    return placeholder_body(
        "02-diagnosis-hypothesis.md",
        case_dir,
        failure_dir_name,
        textwrap.dedent(
            """\
            Written before `04-patch.md` exists on disk.

            ## Upstream change identified

            (The specific PyTorch commit or PR that introduced the
            change torch-spyre is now incompatible with. Cite by SHA
            and file:line as
            `https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>`.
            If not yet located, say so and record what was searched.)

            ## torch-spyre call site(s) affected

            (Each cited as `torch-spyre@<short-sha>:<path>:<line>`.)

            ## Mechanism

            (What did PyTorch used to expose that torch-spyre relied
            on? What does it expose now? What is the smallest change
            that makes torch-spyre compatible again?)

            ## Falsifiable prediction

            (Concrete observable that must hold after the patch. This
            is what `05-verification.md` grades against.)

            ## Confidence and unknowns

            (Guesswork is fine, but it must be labeled. The
            retrospective in 06- will grade it.)
            """
        ),
    )


def remediation_plan_template(case_dir: Path, failure_dir_name: str) -> str:
    return placeholder_body(
        "03-remediation-plan.md",
        case_dir,
        failure_dir_name,
        textwrap.dedent(
            """\
            Also written before `04-patch.md` exists on disk.

            ## Fix class

            (One of LATEST_ONLY_FIX / DUAL_COMPAT_FIX /
            SUPPORTED_VERSION_NO_LONGER_PRACTICAL — see
            `references/patch-policy.md`.)

            ## The 1–3 lines that will change, in words

            (Describe the change in prose, not the diff itself. If it
            takes more than three sentences it is a design, not a
            plan — narrow it or split the case.)

            ## Files touched, and why each is required

            (Named files, with a one-line justification per file. A
            helper or import that moves is named explicitly.)

            ## Anti-scope-creep clause: what this fix does NOT change

            (Adjacent code a reader might expect to be touched but
            which the hypothesis says should not be. This is what
            keeps a "rename" from turning into a "refactor".)

            ## Neighbor set (for Row 2 of the verification matrix)

            (At least three tests from `references/failure-taxonomy.md`
            that exercise the same subsystem, at least one of which
            does NOT touch the patched code path. Chosen BEFORE the
            patch is written.)

            ## Broader smoke set (for Row 7 of the verification matrix)

            (At least three tests, one each covering frontend/dynamo,
            mid-stack lowering, and backend/codegen. Chosen BEFORE
            the patch is written.)

            ## Upstream candidate?

            (Is this a candidate for torch-spyre or PyTorch upstream?
            What form would the upstream change take? An upstream
            candidate must look nothing like a hotfix — this is why
            we keep the local patch minimal.)
            """
        ),
    )


def patch_template(case_dir: Path, failure_dir_name: str) -> str:
    return placeholder_body(
        "04-patch.md",
        case_dir,
        failure_dir_name,
        textwrap.dedent(
            """\
            The fix itself. Do NOT start writing this file until
            `02-diagnosis-hypothesis.md` and `03-remediation-plan.md`
            are complete and their claims stand on their own.

            ## Patch metadata

            - Applies against torch-spyre SHA: (short SHA cited in
              01-observation.md; must be exact — do not rebase to a
              newer tree between hypothesis and patch)
            - `git hash-object` of the patch file: (recorded so
              05-verification.md rows can detect stale evidence)

            ## Diff

            ```diff
            (Paste `git diff` output here, or link to
            `04-patch.diff` / `04-patch/` if multi-hunk.)
            ```

            ## Matches the plan?

            (If the patch as actually written differs from the plan
            in 03-remediation-plan.md, update the plan file first,
            then adjust the patch to match, then land both together.
            Never let the plan lag the patch.)
            """
        ),
    )


def verification_template(case_dir: Path, failure_dir_name: str) -> str:
    return placeholder_body(
        "05-verification.md",
        case_dir,
        failure_dir_name,
        textwrap.dedent(
            """\
            Populated by `scripts/verify_patch.sh`. Do not fill in by
            hand except where the script explicitly says to. The full
            seven-row policy lives in `references/verification-policy.md`.

            A patch is VERIFIED exactly when every applicable row is
            PASS and no row is DEFERRED or stale.

            ## Substrate

            - Substrate kind: (dev-pod | fresh-pod)
            - Pod name: (populated by verify_patch.sh)
            - Base image + digest: (populated by verify_patch.sh)
            - Timestamp (UTC): (populated by verify_patch.sh)

            ## Matrix

            | # | Row                             | Status | Evidence path                  | Timestamp | Notes |
            |---|---------------------------------|--------|--------------------------------|-----------|-------|
            | 1 | TARGETED TEST                   |  ---   |                                |           |       |
            | 2 | NEIGHBOR TESTS                  |  ---   |                                |           |       |
            | 3 | SUPPORTED-PYTORCH CHECK         |  ---   |                                |           |       |
            | 4 | LATEST-PYTORCH CHECK            |  ---   |                                |           |       |
            | 5 | DEVICE CORRECTNESS              |  ---   |                                |           |       |
            | 6 | BUILD/IMPORT (clean env)        |  ---   |                                |           |       |
            | 7 | BROADER COMPILER SMOKE          |  ---   |                                |           |       |

            ## §18 — Fresh-pod reproduction

            (When re-run on the fresh pod, append the same matrix
            here under a `### Matrix (fresh pod)` heading and record
            any per-row divergence from the dev-pod matrix.)

            ## Verdict

            (VERIFIED / UNVERIFIED. If UNVERIFIED, list the rows
            preventing verification.)
            """
        ),
    )


def retrospective_template(case_dir: Path, failure_dir_name: str) -> str:
    return placeholder_body(
        "06-retrospective.md",
        case_dir,
        failure_dir_name,
        textwrap.dedent(
            """\
            Written last, after `05-verification.md` says VERIFIED.

            ## Prediction vs. outcome

            (Did `02-diagnosis-hypothesis.md` correctly explain the
            break? If not, what was actually wrong?)

            ## Was the fix class right?

            (Did a planned LATEST_ONLY_FIX have to become a
            DUAL_COMPAT_FIX to keep the supported version working?
            Record the reason.)

            ## Upstream-ability

            (Is this a candidate for landing in torch-spyre or in
            PyTorch? What would need to change to make it
            upstream-quality?)

            ## One-sentence lesson for the next case

            (What the next similar break should look for.)
            """
        ),
    )


TEMPLATE_FUNCTIONS = {
    "02-diagnosis-hypothesis.md": diagnosis_hypothesis_template,
    "03-remediation-plan.md": remediation_plan_template,
    "04-patch.md": patch_template,
    "05-verification.md": verification_template,
    "06-retrospective.md": retrospective_template,
}


def check_index_collision(failures_root: Path, index: int, slug: str) -> Optional[str]:
    """If the numeric index is already claimed by a different slug, return
    a description of the collision; otherwise return None.

    A repeat invocation with the same slug is treated as a resumption
    (the existing directory is re-used, subject to the post-fix guard
    downstream). A different slug at the same index is always an
    error — silently renaming a case would break references from
    earlier documents.
    """
    prefix = f"{index:02d}-"
    if not failures_root.exists():
        return None
    for child in failures_root.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith(prefix):
            continue
        existing_slug = child.name[len(prefix):]
        if existing_slug != slug:
            return (
                f"index {index:02d} is already claimed by "
                f"failures/{child.name}; refusing to add "
                f"failures/{prefix}{slug} beside it"
            )
    return None


def check_post_fix_guard(target_dir: Path) -> Optional[str]:
    """Refuse to re-template if any post-fix file already exists.

    Returns a human-readable reason string on refusal, or None if
    it is safe to proceed.
    """
    if not target_dir.exists():
        return None
    offenders = [name for name in POST_FIX_FILES if (target_dir / name).exists()]
    if not offenders:
        return None
    return (
        f"{target_dir} already contains: {', '.join(offenders)}. "
        f"Refusing to overwrite — post-fix files are present, which "
        f"means a patch has already been drafted. Re-templating would "
        f"erase the diagnosis / hypothesis it was drafted against. "
        f"Pass --allow-post-fix to override (rare; only when you have "
        f"already read the existing files and want them re-templated)."
    )


def write_files(
    target_dir: Path,
    case_dir: Path,
    classification: str,
    torch_spyre_loc: str,
    upstream_loc: Optional[str],
    observation_body: str,
) -> None:
    """Write the six templated files into ``target_dir``."""
    target_dir.mkdir(parents=True, exist_ok=True)
    failure_dir_name = target_dir.name

    obs_path = target_dir / "01-observation.md"
    obs_path.write_text(
        observation_body_template(
            case_dir=case_dir,
            failure_dir_name=failure_dir_name,
            classification=classification,
            torch_spyre_loc=torch_spyre_loc,
            upstream_loc=upstream_loc,
            body=observation_body,
        )
    )

    for name, fn in TEMPLATE_FUNCTIONS.items():
        (target_dir / name).write_text(fn(case_dir, failure_dir_name))


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="record_failure.py",
        description="Create the six-file per-failure record for a forward-compat break.",
    )
    p.add_argument("--dir", required=True, help="Case directory (contains failures/).")
    p.add_argument("--index", required=True, type=int, help="Failure index (1..99).")
    p.add_argument("--classification", required=True,
                   help="Failure category (must match references/failure-taxonomy.md).")
    p.add_argument("--torch-spyre-loc", required=True,
                   help='torch-spyre@<short-sha>:<path>:<line>.')
    p.add_argument("--upstream-loc", default=None,
                   help="https://github.com/pytorch/pytorch/blob/<sha>/<path>#L<line>.")
    p.add_argument("--observation", default=None,
                   help="Path to a file whose contents become the observation body.")
    p.add_argument("--stdin", action="store_true",
                   help="Read the observation body from stdin (ignored if --observation given).")
    p.add_argument("--allow-post-fix", action="store_true",
                   help="Override the hypothesis-before-fix guard. Rare.")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.index < 0 or args.index > 99:
        print("error: --index must be in 0..99 (two-digit prefix)", file=sys.stderr)
        return 2

    case_dir = Path(args.dir).resolve()
    if not case_dir.exists():
        print(f"error: --dir does not exist: {case_dir}", file=sys.stderr)
        return 2
    if not case_dir.is_dir():
        print(f"error: --dir is not a directory: {case_dir}", file=sys.stderr)
        return 2

    failures_root = case_dir / "failures"
    slug = slugify(args.classification)
    collision = check_index_collision(failures_root, args.index, slug)
    if collision:
        print(f"error: {collision}", file=sys.stderr)
        return 2

    failure_dir_name = f"{args.index:02d}-{slug}"
    target_dir = failures_root / failure_dir_name

    if not args.allow_post_fix:
        reason = check_post_fix_guard(target_dir)
        if reason:
            print(f"error: {reason}", file=sys.stderr)
            return 1

    observation_body = read_observation_body(args)

    write_files(
        target_dir=target_dir,
        case_dir=case_dir,
        classification=args.classification,
        torch_spyre_loc=args.torch_spyre_loc,
        upstream_loc=args.upstream_loc,
        observation_body=observation_body,
    )

    print(str(target_dir))
    for name in TEMPLATED_FILES:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
