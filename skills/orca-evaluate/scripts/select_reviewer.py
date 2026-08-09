#!/usr/bin/env python3
"""Diff-stats-based reviewer selection for orca-evaluate's §3 diff-review spawn point.

Picks a code-reviewer provider/model/effort from the size of a diff instead of always
spawning the fixed High-Risk model regardless of how small the change is. Does not read
or classify which files changed — only aggregate file/line counts — so it structurally
cannot become a static path-matching gate (that design was tried and discarded; see
`orca-evaluate/SKILL.md` §3).

Usage:
    python3 select_reviewer.py --shortstat "<git diff --shortstat output>" \\
        [--codex-available | --no-codex-available] [--high-risk-signal]

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
    provider: str  # "claude-code" | "codex"
    model: str
    effort: str
    advisor: Optional[str] = None  # e.g. "opus" — only for claude-sonnet-5(+ --advisor opus)


# "Highest applicable tier" — same spirit as model-selection.md: if either count crosses its
# threshold, the diff is promoted to high-risk. Named ROUTINE_MAX_* (not "HIGH_RISK_MIN_*"): the
# comparison below is strict (`>`), so the smallest value that actually triggers high-risk is one
# more than this constant — ROUTINE_MAX_* names the boundary the constant actually represents.
#
# ROUTINE_MAX_LINES = 400 is validated against a real case in this repo's history: issue #24's
# round0 diff (5 files, +496 -13 = 509 churn) was in fact reviewed at claude-opus-5/xhigh.
# ROUTINE_MAX_FILES = 15 has no such evidence — it is an untested tuning parameter based on the
# judgment that a change spanning many files has a wide blast radius, not on a measured case.
# Adjust freely if real diffs show it miscalibrated.
ROUTINE_MAX_FILES = 15
ROUTINE_MAX_LINES = 400


def classify_tier(stats: DiffStats, *, high_risk_signal: bool = False) -> str:
    """Returns "routine" or "high-risk" only. Code review never uses model-selection.md's Simple
    tier — Simple's own examples (formatting, rename, boilerplate) are not code-review subjects,
    and model-selection.md lists "bounded code review" under Routine itself. So the valid range
    for this call site is Routine..High Risk, not Simple..High Risk.

    high_risk_signal lets the caller pass through a High-Risk indicator it has *already computed*
    for an unrelated reason (§3 already runs a migration/schema-file check before spawning the
    reviewer, to decide whether to run the destructive-op linter — without this passthrough, a
    small-churn migration diff would fall to the cheapest reviewer tier with no later local gate
    to catch it: merge-time verification is delegated to repo CI). This is
    still not path matching: the caller decides what counts as a "known high-risk kind" using
    whatever pre-existing check it already ran (migration-lint's own file list here); this
    function and its caller never introduce a new static path list to satisfy it — the boolean is
    the only thing that crosses this boundary, same shape as `codex_available`.
    """
    if high_risk_signal or stats.files_changed > ROUTINE_MAX_FILES or stats.lines_changed > ROUTINE_MAX_LINES:
        return "high-risk"
    return "routine"


def select_reviewer(
    stats: DiffStats, *, codex_available: bool = True, high_risk_signal: bool = False,
) -> ReviewerChoice:
    """codex_available is injected by the caller (this session's own knowledge of Codex
    availability is the primary signal; `command -v codex` is only a supporting check for binary
    presence, not token/quota availability) — this function never probes the environment itself,
    which keeps it pure and deterministic. If a Codex session spawn later fails, the caller must
    re-invoke with codex_available=False; this function cannot detect a spawn failure on its own.

    high_risk_signal: see classify_tier(). Defaults to False so a caller that doesn't have (or
    doesn't check for) any such signal gets exactly the prior churn-only behavior.

    claude-fable-5 never appears in any branch — model-selection.md already bans it (2026-07
    benchmark: opus-5 leads fable-5 on the coding-agentic benchmark closest to code review, and
    SWE-bench Pro is a near-tie at roughly double fable-5's price).
    """
    tier = classify_tier(stats, high_risk_signal=high_risk_signal)
    if tier == "routine":
        if codex_available:
            return ReviewerChoice("codex", "gpt-5.6-terra", "medium")
        # Advisor effort cannot be set or verified (models/claude-code.md) — effort="high" here
        # is the *session's own* pinned effort, so model-selection.md's "launch with an explicit
        # model+effort" invariant still holds; only the advisor's own effort is unverifiable.
        return ReviewerChoice("claude-code", "claude-sonnet-5", "high", advisor="opus")
    # high-risk: diff-review-before-merge is exactly the "final review" model-selection.md refers
    # to, so both providers use xhigh here (codex.md's "high; xhigh for security/final gates").
    # (gpt-5.6-terra's own row says to "escalate final or high-risk review to Sol" — this branch
    # is that escalation; terra is never reached once high-risk is decided, by either signal.)
    if codex_available:
        return ReviewerChoice("codex", "gpt-5.6-sol", "xhigh")
    return ReviewerChoice("claude-code", "claude-opus-5", "xhigh")


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

    Raises ValueError if shortstat is non-empty but the "N file(s) changed" clause cannot be
    found at all — e.g. a locale-translated `git` build (shortstat text is a gettext translation
    target) or unrelated garbage passed in by mistake. That case must never silently degrade to
    DiffStats(0, 0), which classify_tier() would then read as the smallest possible diff and
    route to the cheapest reviewer tier — exactly the kind of silent fail-open this module exists
    to avoid elsewhere (see high_risk_signal in classify_tier()).
    """
    if not shortstat.strip():
        return DiffStats(files_changed=0, lines_changed=0)
    files_match = _FILES_RE.search(shortstat)
    if files_match is None:
        raise ValueError(
            f"could not find a 'N file(s) changed' clause in --shortstat input: {shortstat!r}"
        )
    files_changed = int(files_match.group(1))
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
    parser.add_argument(
        "--high-risk-signal", action="store_true", default=False,
        help=(
            "Caller already knows this diff is a known high-risk kind (e.g. touches "
            "migration/schema files) from a check it ran for its own reason — force high-risk "
            "tier regardless of diff size"
        ),
    )
    args = parser.parse_args(argv)

    stats = parse_shortstat(args.shortstat)
    choice = select_reviewer(stats, codex_available=args.codex_available, high_risk_signal=args.high_risk_signal)
    print(_to_json(choice))
    return 0


if __name__ == "__main__":
    sys.exit(main())
