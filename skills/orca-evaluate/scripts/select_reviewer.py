#!/usr/bin/env python3
"""Diff-stats-based reviewer selection for orca-evaluate's §3 diff-review spawn point.

Picks a code-reviewer provider/model/effort from the size of a diff instead of always
spawning the fixed High-Risk model regardless of how small the change is. Does not read
or classify which files changed — only aggregate file/line counts — so it structurally
cannot become a static path-matching gate (that design was tried and discarded; see
`orca-evaluate/SKILL.md` §3).

Usage:
    python3 select_reviewer.py --shortstat "<git diff --shortstat output>" \\
        [--codex-available | --no-codex-available]

Prints one line of JSON: {"provider": ..., "model": ..., "effort": ..., "advisor": ...}.
`advisor` is null except for the one candidate that uses one (claude-sonnet-5 + --advisor opus).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DiffStats:
    files_changed: int
    lines_changed: int  # total churn = insertions + deletions


@dataclass(frozen=True)
class ReviewerChoice:
    provider: str  # "claude" | "codex"
    model: str
    effort: str
    advisor: Optional[str] = None  # e.g. "opus" — only for claude-sonnet-5(+ --advisor opus)


# "Highest applicable tier" — same spirit as model-selection.md: if either count crosses its
# threshold, the diff is promoted to high-risk (an "and" condition to *stay* routine).
#
# HIGH_RISK_MIN_LINES = 400 is validated against a real case in this repo's history: issue #24's
# round0 diff (5 files, +496 -13 = 509 churn) was in fact reviewed at claude-opus-5/xhigh.
# HIGH_RISK_MIN_FILES = 15 has no such evidence — it is an untested tuning parameter based on the
# judgment that a change spanning many files has a wide blast radius, not on a measured case.
# Adjust freely if real diffs show it miscalibrated.
HIGH_RISK_MIN_FILES = 15
HIGH_RISK_MIN_LINES = 400


def classify_tier(stats: DiffStats) -> str:
    """Returns "routine" or "high-risk" only. Code review never uses model-selection.md's Simple
    tier — Simple's own examples (formatting, rename, boilerplate) are not code-review subjects,
    and model-selection.md lists "bounded code review" under Routine itself. So the valid range
    for this call site is Routine..High Risk, not Simple..High Risk.
    """
    if stats.files_changed > HIGH_RISK_MIN_FILES or stats.lines_changed > HIGH_RISK_MIN_LINES:
        return "high-risk"
    return "routine"


def select_reviewer(stats: DiffStats, *, codex_available: bool = True) -> ReviewerChoice:
    """codex_available is injected by the caller (this session's own knowledge of Codex
    availability is the primary signal; `command -v codex` is only a supporting check for binary
    presence, not token/quota availability) — this function never probes the environment itself,
    which keeps it pure and deterministic. If a Codex session spawn later fails, the caller must
    re-invoke with codex_available=False; this function cannot detect a spawn failure on its own.

    claude-fable-5 never appears in any branch — model-selection.md already bans it (2026-07
    benchmark: opus-5 leads fable-5 on the coding-agentic benchmark closest to code review, and
    SWE-bench Pro is a near-tie at roughly double fable-5's price).
    """
    tier = classify_tier(stats)
    if tier == "routine":
        if codex_available:
            return ReviewerChoice("codex", "gpt-5.6-terra", "medium")
        # Advisor effort cannot be set or verified (models/claude-code.md) — effort="high" here
        # is the *session's own* pinned effort, so model-selection.md's "launch with an explicit
        # model+effort" invariant still holds; only the advisor's own effort is unverifiable.
        return ReviewerChoice("claude", "claude-sonnet-5", "high", advisor="opus")
    # high-risk: diff-review-before-merge is exactly the "final review" model-selection.md refers
    # to, so both providers use xhigh here (codex.md's "high; xhigh for security/final gates").
    if codex_available:
        return ReviewerChoice("codex", "gpt-5.6-sol", "xhigh")
    return ReviewerChoice("claude", "claude-opus-5", "xhigh")


_FILES_RE = re.compile(r"(\d+) files? changed")
_INSERTIONS_RE = re.compile(r"(\d+) insertions?\(\+\)")
_DELETIONS_RE = re.compile(r"(\d+) deletions?\(-\)")


def parse_shortstat(shortstat: str) -> DiffStats:
    """Parses `git diff --shortstat` output, e.g.:
        ' 5 files changed, 496 insertions(+), 13 deletions(-)'  (both clauses present)
        ' 1 file changed, 3 deletions(-)'                        (pure deletion — no insertions clause)
        ' 1 file changed, 1 insertion(+)'                        (pure insertion — no deletions clause, singular)
        ''                                                        (no diff at all)

    git omits the insertions/deletions clause entirely whenever its count is exactly zero (only
    listing whichever clauses are non-zero, comma-separated) — so both are treated as optional.
    Singular forms ("1 file changed", "1 insertion(+)", "1 deletion(-)") are matched by the same
    regex as their plural counterparts via `s?`, not as a separate case.
    """
    if not shortstat.strip():
        return DiffStats(files_changed=0, lines_changed=0)
    files_match = _FILES_RE.search(shortstat)
    files_changed = int(files_match.group(1)) if files_match else 0
    insertions_match = _INSERTIONS_RE.search(shortstat)
    deletions_match = _DELETIONS_RE.search(shortstat)
    insertions = int(insertions_match.group(1)) if insertions_match else 0
    deletions = int(deletions_match.group(1)) if deletions_match else 0
    return DiffStats(files_changed=files_changed, lines_changed=insertions + deletions)


def _to_json(choice: ReviewerChoice) -> str:
    return json.dumps({
        "provider": choice.provider,
        "model": choice.model,
        "effort": choice.effort,
        "advisor": choice.advisor,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shortstat", required=True, help="`git diff --shortstat` output")
    availability = parser.add_mutually_exclusive_group()
    availability.add_argument(
        "--codex-available", dest="codex_available", action="store_true", default=True,
        help="Codex is available this session (default)",
    )
    availability.add_argument(
        "--no-codex-available", dest="codex_available", action="store_false",
        help="Codex is not available this session (or a prior Codex spawn attempt failed)",
    )
    args = parser.parse_args(argv)

    stats = parse_shortstat(args.shortstat)
    choice = select_reviewer(stats, codex_available=args.codex_available)
    print(_to_json(choice))
    return 0


if __name__ == "__main__":
    sys.exit(main())
