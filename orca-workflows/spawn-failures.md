# Spawn Failures

> verified_at: 2026-07-25

Shared reference for `orca-workflow`/`orca-task-runner`/`orca-evaluate` so a spawn failure gets checked
against known causes before re-diagnosing from scratch. The recurring problem (issue #16) wasn't that
spawn failures happened — it's that nobody could tell whether a given failure was already known before
starting a fresh investigation.

## Two-layer mechanism

- **This table (git-tracked)** — known failure signatures mapped to root cause, fix, and GitHub issue.
  Small, reviewed, changes rarely. This is what actually answers "is this known?" — a jsonl log alone
  can't, since it starts empty and can't record history it never saw.
- **`~/.local/state/orca-workflows/logs/spawn-failures.jsonl`** (git-untracked, append-only, same
  directory as `assignments.jsonl` — see the `orca-logs-not-git-tracked` convention) — every occurrence,
  whether it matched a row below or not. Lets patterns emerge across runs and is the evidence base for
  adding new rows here.

## Procedure

Run this whenever a spawn produces no usable output, a shell error, or a timeout with zero output (each
skill's launch section says where in its own flow to check for this).

1. grep the `failure_signature` column below for a substring match against what was actually observed.
   - **Match found** → apply the documented fix, cite the `known_issue`. Do not re-diagnose from scratch.
   - **No match** → diagnose normally. Once the cause is known, add a row to this table (not just the
     jsonl) and open a GitHub issue in this repo if one doesn't already cover it.
2. Always append an occurrence record, regardless of (1)'s outcome:

   ```bash
   install -d -m 700 ~/.local/state/orca-workflows/logs
   printf '{"ts":"%s","skill":"<skill>","role":"<role>","provider":"<provider>","failure_signature":"<signature>","fix_applied":"<fix or null>","known_issue":<issue-num-or-null>}\n' \
     "$(date -u +%FT%TZ)" >> ~/.local/state/orca-workflows/logs/spawn-failures.jsonl
   chmod 600 ~/.local/state/orca-workflows/logs/spawn-failures.jsonl
   ```

## Known signatures

| `failure_signature` (grep substring) | root cause | fix | known_issue |
|---|---|---|---|
| `zsh: parse error` (or similar shell syntax error surfacing on the *target* terminal right after `orca terminal create`/`terminal send`) | `orca terminal create --command` / `terminal send` type the string into a live shell character-by-character instead of exec'ing it atomically — parens, quotes, and newlines inside an inline multi-line prompt (e.g. `agy -p '<prompt>'`) get parsed as shell metacharacters by the target shell | write the prompt to a file first, then pass `-p "$(cat <prompt-file>)"` — text captured inside double quotes via command substitution isn't re-parsed | #16 |
| `jetski: no output produced` (agy headless call silently produces nothing, exit 0) | agy headless auto-denies tool calls when `--dangerously-skip-permissions` is missing — equivalent to Claude's `--permission-mode bypassPermissions` | add `--dangerously-skip-permissions` to the agy launch command | #15 |
| `terminal list` shows a terminal with `worktreePath: ""` and `branch: ""` that no longer responds, coinciding with a worktree base-path rename (e.g. `~/.worktrees` → `~/worktrees`) | orca's terminal/worktree registry doesn't track path renames — a session bound to the old path is orphaned, not migrated | none (structural orca limitation) — avoid renaming worktree base paths while sessions are active; re-spawn the terminal under the new path if orphaned | #14 |

## Adding a new row

Keep `failure_signature` a short, literal substring that would actually appear in `terminal read` output —
not a paraphrase, or grep won't find it next time. Link the GitHub issue number rather than re-explaining
the cause here; this table maps symptom → issue, it doesn't replace the issue body.
