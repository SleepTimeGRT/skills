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
The orca skills are a version set pinned by `skills/orca-set.version` (line 1 = version,
rest = members): deploying any member deploys the whole set at that one version, `--version`
must not contradict the set file, and one dirty member aborts the whole set — so the seven
always carry the same version label.

### `orca-workflows/` deploy path (decision, #22)

`orca-workflows/` is intentionally *not* brought under the commit-pinned mechanism above.
`~/.agents/orca-workflows/` is a plain symlink to this repo's local main-branch checkout
(single machine, single consumer: the `orca-*` skills that read
`model-selection.md`/`spawn-failures.md`/`logging.md` from it, plus `orca-workflows/scripts/` for
executable helpers such as `orca_call_with_retry.sh` — issue #42 — that call sites `source`
directly and invoke, not just read as reference prose). It isn't installed by other repos via
`npx skills add`, so `skills/`'s N-repo integrity guarantees don't apply here — changes go
live the moment they merge to main, with no separate deploy step to forget.

Known risk from this choice (accepted, not fixed): the symlink has no dirty-tree refusal or
sha256 verification, so an edit committed directly to the main checkout (bypassing PR review)
goes live instantly with no integrity check — the inverse of `skills/`'s stale-deployed-copy
risk. Separately, edits made in a feature worktree are invisible at `~/.agents/orca-workflows/`
until merged to main, since the symlink always resolves to the main checkout, never the
worktree currently in use.

## Orca-\* skill design principle: diagnose + self-recover, don't bypass

For `orca-workflow`/`orca-workflow-epic`/`orca-workflow-task`/`orca-task-runner`/`orca-evaluate` (and any future skill wrapping Orca's CLI/features):
use Orca's own features as fully as possible. When one of them misbehaves, the required fix order is:

1. **Diagnose** — reproduce, capture the exact failure text/signature and where it fires (this is what
   `spawn-failures.md`'s known-signature table and `logging.md`'s `self_recovery` event exist for).
2. **Self-recover** — build recovery into the skill using Orca's own mechanisms as the primary fix: wait on
   `orca status --json`/`check --wait`, retry via `orca_call_with_retry.sh`, resume via
   `worker-start --retry-of` (see `self-recovery.md`, `scripts/orca_call_with_retry.sh`). This is the main
   remedy, not a fallback tried after a manual workaround.
3. **Bypass/disable, last resort only, with explicit user sign-off** — turning off the misbehaving Orca
   feature entirely to make the symptom go away is not an acceptable substitute for 1-2 on its own.

### Prefer Orca's current recommended mechanism over ad-hoc CLI composition

Before implementing any orca-* skill behavior — waiting on a worker, reading its output, retrying,
cleaning up a terminal, or any other operation — load the current guide (`orca skills get <name>`, `--help`,
or `agent-context --json`) for that exact operation and use whatever it documents as the primary/composed
path. Do not substitute a lower-level primitive (raw `terminal read`, `terminal wait --for tui-idle`, manual
`terminal send`) just because it is more familiar or already at hand. When a documented command names its
own fallback (e.g. `worker-read`'s hook-based transcript degrading to a `terminal` source), treat the
fallback as evidence the primary path carries guarantees the fallback does not — using the fallback by
default forfeits those guarantees, it does not substitute for them.

When Orca's version changes, do not assume a skill's existing behavior or workaround still reflects Orca's
current recommended path. Re-check whether a newer, more direct mechanism now exists for that operation —
Orca's own CLI help, `skills get`, and changelog are the source of truth, not memory of a prior version's
limitations — and adapt the skill's structure to match, rather than carrying forward a workaround built for
a capability gap that may have since closed.

**Orca CLI baseline**: the orca-* skills in this repo, and the principles above, were last verified against
Orca app version 1.4.176. Check `orca status --json`'s `runtime.appVersion` against this number before
trusting any Orca-specific mechanism claim here as still accurate — a mismatch means the claim needs
re-verification against the current version's own `skills get`/`--help` output, not blind reuse.

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
