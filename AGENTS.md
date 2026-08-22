# sleeptimegrt-skills — agent map

Reusable, domain-neutral agent skills for engineering harness work across repositories.
This repo's skills are modeled on general-purpose, cross-tool skill collections like
[obra/superpowers](https://github.com/obra/superpowers) and
[mattpocock/skills](https://github.com/mattpocock/skills).

This repo is meant to hold skills shared across the coding agents the user runs
day to day: Claude Code, Codex, and Antigravity. Every skill under `skills/` is
authored as a `SKILL.md` with YAML frontmatter (`name` + `description`) and
progressive disclosure. Confirmed 2026-07-22 (see
[vercel-labs/skills](https://github.com/vercel-labs/skills) and the
[Agent Skills spec](https://agentskills.io)): this format is cross-tool as-is —
Claude Code, Codex, and Antigravity (and 70+ other agents) all consume the same
`SKILL.md` without conversion via the `npx skills` installer. The one caveat:
some frontmatter features are Claude-Code-only (`allowed-tools` behavior
details, `context: fork`, hooks) — avoid depending on those in a skill meant to
be portable. See issue #2 for the installer-adoption discussion (catalog vs.
flat layout, publishing this repo via `npx skills add`, plugin-marketplace
distribution).

## Methodology reference

`docs/references/anthropic-building-skills-for-claude.pdf` ("The Complete Guide to Building
Skills for Claude") is this repo's north star for skill design, testing, and iteration — when a
skill-authoring choice here needs a tiebreaker, check this doc before improvising.

**Skills in this repo must be developed against that guide.** Read
`docs/references/anthropic-building-skills-for-claude.md` — a page-anchored summary of the PDF —
before authoring or substantially changing a skill, and use its Reference A checklist before
merging. Open the PDF pages the summary cites whenever the exact wording matters; the PDF stays
canonical, the summary is an index. The summary also flags where the guide does *not* apply here
(its Chapter 4 distribution path is Claude.ai/API-specific, ours is `scripts/deploy-skills.sh`;
`allowed-tools` is listed as standard there but its enforcement behavior is Claude-Code-only per
the cross-tool caveat above).

The guide's "Testing
and iteration" chapter names three test categories: **triggering tests** (does the skill load at
the right times — should-trigger/should-NOT-trigger phrasing), **functional tests** (does the
skill produce correct real outputs — live/simulated execution against Given/When/Then
expectations), and **performance comparison** (with-skill vs without-skill baselines: message
count, token count, failed calls). `tests/` in this repo covers **only the functional category, and
only partially**. It is an execution suite: every test file runs real code — the shell/python
scripts (`deploy-skills.sh`, premerge/hook/audit scripts). Prose-pinning tests that assert specific
strings or ordering inside `SKILL.md` are not written here: they freeze current wording as the
spec, so every intentional doc edit produces a false failure, and they verify nothing about whether
a skill actually works. **Triggering tests and performance comparison remain uncovered**, so
don't describe a skill here as "tested per the guide". Nothing enforces the suite automatically —
no CI, no git hook; run `python3 -m pytest tests/ -q` yourself after touching a script or a
documented bash procedure.

## Fresh agent protocol

1. Read this file.
2. Read `HANDOFF.md` when it exists; it contains the current work state and verified evidence.
3. For skill creation or substantial skill changes, read
   `docs/references/anthropic-building-skills-for-claude.md` (see Methodology reference above), then
   use the `skill-creator` skill before editing. Note: it's a
   Claude Code skill, so its packaging advice may not be tuned for Codex/Antigravity — sanity-check anything
   Claude-Code-specific it suggests against the cross-tool goal above.
4. Load only the target skill and the resources directly required for the task.

## Gate-output design constraints

For skills that inspect or modify hooks, verify commands, CI, shell scripts, or package scripts:

- Distinguish non-interactive gates from interactive development, deploy, migration, and destructive commands.
- Compact only non-interactive gate output by default. Do not silence interactive progress indiscriminately.
- Preserve `PASS`, `WARN`, `FAIL`, and `SKIP` as distinct outcomes.
- Preserve the original exit code, signal behavior, command order, and fail-fast semantics.
- Keep full diagnostics discoverable through bounded, untracked, worktree-safe logs.
- Treat persisted logs as sensitive assets: use restrictive permissions and review commands for secret output.
- Prefer progressive disclosure: summary first, then targeted `rg`, `tail`, or stage-specific log reads.

## Validation

- Test scripts against temporary fixture repositories before using them on real repositories.
- Cover success, warning, failure, spaces in paths, interrupted execution, worktrees, and log cleanup.
- Compare the gate stages before and after a change so output refactoring cannot silently remove verification.
- Run representative pilots before extracting a shared abstraction or applying changes across repositories.

## Skill deployment

This repo's skills are installed globally as commit-pinned copies in
`~/.agents/skills/`, with `~/.claude/skills/` symlinking into that user-scope directory.
The deploy script removes its own commit-pinned legacy copies from `~/.codex/skills/` but
leaves unmarked manual installs untouched. These are not worktree symlinks — editing
`skills/` does nothing until redeployed. After committing a skill change, run
`scripts/deploy-skills.sh [skill-name ...]` (no args = all skills). It refuses dirty
skills so the recorded commit never lies about the deployed content.

### Live-symlink exception: `epic-drain`

`~/.agents/skills/epic-drain` is a plain symlink to this repo's local main-branch checkout
(`skills/epic-drain/`), not a commit-pinned copy — single machine, single consumer, and the skill
is still being shaped by pilots, so changes go live the moment they merge to main with no deploy
step to forget. `deploy-skills.sh` detects the symlink and skips it (no rsync, no metadata) so it
never dirties the repo. Accepted risks: no dirty-tree refusal or sha256 check (an edit committed
straight to the main checkout goes live instantly), and edits in a feature worktree are invisible
at `~/.agents/skills/epic-drain` until merged. To convert back to a pinned copy, remove the symlink
and run `scripts/deploy-skills.sh epic-drain`.

## Retired: Orca-driven issue pipeline

The `orca-workflow*`/`orca-task-runner`/`orca-evaluate`/`orca-retro` skill set and the
`orca-workflows/` reference tree were removed on 2026-08-22 — see
`docs/adr/0002-retire-orca-workflow-pipeline.md` for the evidence and reasoning. Do not rebuild a
pipeline that drives other agent terminals through Orca from an LLM session in this repo without
re-reading that ADR; issue-driven implementation work now runs through the `superpowers` skills
(brainstorming → writing-plans → subagent-driven-development → finishing-a-development-branch)
directly in the agent session, with Orca used only ad hoc via its own `orca-cli`/`orchestration`
skills.

## Repository operations

- Do not run deploy, release, migration, seed, wipe, or other external-write commands merely to measure output.
- Keep changes to different target repositories in independent commits.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`SleepTimeGRT/skills`), managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
