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

## Fresh agent protocol

1. Read this file.
2. Read `HANDOFF.md` when it exists; it contains the current work state and verified evidence.
3. For skill creation or substantial skill changes, use the `skill-creator` skill before editing. Note: it's a
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

### `orca-workflows/` deploy path (decision, #22)

`orca-workflows/` is intentionally *not* brought under the commit-pinned mechanism above.
`~/.agents/orca-workflows/` is a plain symlink to this repo's local main-branch checkout
(single machine, single consumer: the three `orca-*` skills that read
`model-selection.md`/`spawn-failures.md` from it). It isn't installed by other repos via
`npx skills add`, so `skills/`'s N-repo integrity guarantees don't apply here — changes go
live the moment they merge to main, with no separate deploy step to forget.

Known risk from this choice (accepted, not fixed): the symlink has no dirty-tree refusal or
sha256 verification, so an edit committed directly to the main checkout (bypassing PR review)
goes live instantly with no integrity check — the inverse of `skills/`'s stale-deployed-copy
risk. Separately, edits made in a feature worktree are invisible at `~/.agents/orca-workflows/`
until merged to main, since the symlink always resolves to the main checkout, never the
worktree currently in use.

## Repository operations

- Do not run deploy, release, migration, seed, wipe, or other external-write commands merely to measure output.
- Keep changes to different target repositories in independent commits.
