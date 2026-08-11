# Reviewer Selection Rationale

Background for `scripts/select_reviewer.py`'s model/effort choice in `../SKILL.md` §3. Load this
only when auditing, changing, or debugging that selection — `SKILL.md` only needs the mechanism
(call the script, branch on its output), not the reasoning behind it.

## Fresh-context, not "different provider"

The code-reviewer session must be fresh-context, not necessarily a different provider than
`orca-task-runner` (the generator). `models/codex.md` already states "Evaluators require fresh
context, not a different provider" — the reviewer coincidentally landing on the same model as the
generator is fine. A different provider is a diversity benefit, not a hard requirement.

## Candidate pool and exclusions

Model/effort come from feeding diff stats (changed files, changed lines) to
`scripts/select_reviewer.py`. Candidate pool: Codex's `gpt-5.6-terra`/`gpt-5.6-sol` and Claude's
`claude-sonnet-5` (+ `--advisor opus`)/`claude-opus-5`. `claude-fable-5` is excluded — no
significant edge over opus-5 in 2026-07 benchmarks, so `model-selection.md`'s existing prohibition
stands.

## High-risk-signal override

Diff stats alone can let a low-churn destructive-migration diff fall into the lowest tier, so the
already-computed `migration_files_present` (§3's destructive-op linter step) is passed through as
`--high-risk-signal`, forcing that diff into the high-risk tier regardless of churn. This isn't a
new path-matching rule for that source — it reuses a value §3 already computes for a different
purpose (deciding whether to run the destructive-op linter at all).

A second source, `gate_safety_files_present`
(docs/superpowers/specs/2026-08-12-orca-evaluate-gate-safety-signal-design.md), ORs into the same
flag. Unlike the migration source, its path list exists only to compute this boolean — §3 has no
other use for it. That's accepted deliberately: `classify_tier` itself still only ever consumes a
boolean, never a path list, so the pure-function contract holds; the path matching lives entirely
in the caller (§3), which is allowed to introduce one to compute a source. §3 ⑤'s prose
gate-safety judgment stays unconditional and uncoupled from this list on purpose, so the reviewer
never anchors its own judgment to what the precheck matched.

## Codex availability

Primary evidence is what the user told this session directly — `command -v codex` only proves the
binary exists, not that tokens/quota are available. Nothing in `SKILL.md` should hardcode "Codex is
unavailable in this environment" as a fixed claim; availability is a per-session fact, not a
property of the repo.

## Retry on spawn failure

If the Codex session spawn fails (confirm via `spawn-failures.md` before assuming this is why),
don't re-diagnose from scratch — call `select_reviewer.py --no-codex-available` again to re-spawn
on the Claude branch. `select_reviewer` itself is a pure function and can't detect spawn failure,
so this retry is the caller's (the spawn site's) responsibility.
