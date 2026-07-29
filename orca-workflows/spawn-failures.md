# Spawn Failures

> verified_at: 2026-07-26

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
skill's launch section says where in its own flow to check for this). One row below is unconditional
rather than failure-triggered: every High Risk `claude-opus-5` launch, check for it regardless of whether
the run looked like it succeeded — see that row's fix column.

1. grep the `failure_signature` column below for a substring match against what was actually observed.
   - **Match found** → apply the documented fix, cite the `known_issue`. Do not re-diagnose from scratch.
   - **No match** → diagnose normally. Once the cause is known, add a row to this table (not just the
     jsonl) and open a GitHub issue in this repo if one doesn't already cover it.
2. Always append an occurrence record, regardless of (1)'s outcome:

   ```bash
   install -d -m 700 ~/.local/state/orca-workflows/logs
   jq -cn \
     --arg ts "$(date -u +%FT%TZ)" \
     --arg skill "<skill>" \
     --arg role "<role>" \
     --arg provider "<provider>" \
     --arg failure_signature "<signature>" \
     --arg fix_applied "<fix or empty>" \
     --argjson known_issue '<issue-num-or-null>' \
     '{
       ts: $ts,
       skill: $skill,
       role: $role,
       provider: $provider,
       failure_signature: $failure_signature,
       fix_applied: (if $fix_applied == "" then null else $fix_applied end),
       known_issue: $known_issue
     }' >> ~/.local/state/orca-workflows/logs/spawn-failures.jsonl
   chmod 600 ~/.local/state/orca-workflows/logs/spawn-failures.jsonl
   ```

   `known_issue`에는 issue 번호 또는 JSON `null`을 넣는다. `jq`가 signature/fix의 따옴표·역슬래시·개행을
   escape하므로 각 append는 유효한 JSON 한 줄을 유지한다.

## Known signatures

| `failure_signature` (grep substring) | root cause | fix | known_issue |
|---|---|---|---|
| `zsh: parse error` (or similar shell syntax error surfacing on the *target* terminal right after `orca terminal create`/`terminal send`) | `orca terminal create --command` / `terminal send` type the string into a live shell character-by-character instead of exec'ing it atomically — parens, quotes, and newlines inside an inline multi-line prompt (e.g. `agy -p '<prompt>'`) get parsed as shell metacharacters by the target shell | write the prompt to a file first, then pass `-p "$(cat <prompt-file>)"` — text captured inside double quotes via command substitution isn't re-parsed | #16 |
| `jetski: no output produced` (agy headless call silently produces nothing, exit 0) | agy headless auto-denies tool calls when `--dangerously-skip-permissions` is missing — equivalent to Claude's `--permission-mode bypassPermissions` | add `--dangerously-skip-permissions` to the agy launch command | #15 |
| `terminal list` shows a terminal with `worktreePath: ""` and `branch: ""` that no longer responds, coinciding with a worktree base-path rename (e.g. `~/.worktrees` → `~/worktrees`) | orca's terminal/worktree registry doesn't track path renames — a session bound to the old path is orphaned, not migrated | none (structural orca limitation) — avoid renaming worktree base paths while sessions are active; re-spawn the terminal under the new path if orphaned | #14 |
| `claude-opus-4-8` shows up in `modelUsage` (`--output-format json`) or in the transcript's model-substitution notice for a worker launched with `--model claude-opus-5` | Claude Code's cybersecurity safety classifier flagged the request (often just the first request's workspace context — CLAUDE.md, git status) and auto-reran it on Opus 4.8, Opus 5's only classifier fallback; a biology flag has no fallback and ends in refusal instead. This isn't a launch failure — the run "succeeds" silently on the wrong model. Requires Claude Code >= 2.1.219 for category-based fallback | not a bug to fix — a required check. After every High Risk `claude-opus-5` launch, grep for `claude-opus-4-8` in `modelUsage`/transcript before trusting the gate report; if found, correct the report to say it ran on Opus 4.8, not Opus 5 xhigh. A biology-flag refusal has no fallback — ESCALATE to human review instead of PASS/FAIL | #21 |
| `zsh: parse error` right after `dispatch --inject`, where the target terminal's *previous* command had already finished and returned to an idle shell prompt — not right after `terminal create`/`terminal send` (that's `#16` above) | the terminal was running a one-shot headless process (`agy -p ...`, `codex exec`) that already exited by the time `dispatch --inject` arrived, so the injected payload lands on a bare shell instead of a live application — a different root cause from `#16`'s quoting/parsing problem even though the surface error string is identical | fix depends on the provider. For a provider other than agy: do not launch ping-pong roles (contract review, code review) as one-shot — launch as a persistent REPL and confirm `tui-idle` before `dispatch --inject`. For agy specifically: do not use REPL at all (agy REPL is unsupported here, `models/agy.md` — 2026-07-30 unfocused-boot hang and concurrent-focus deadlock, `references/models/agy.md`) — instead put the complete task in the `-p` argument at launch time so no later `dispatch --inject` is ever needed; this is why agent-e2e reporting (`skills/orca-evaluate/SKILL.md` §2) is headless, not REPL | #37 |

## Adding a new row

Keep `failure_signature` a short, literal substring that would actually appear in `terminal read` output —
not a paraphrase, or grep won't find it next time. Link the GitHub issue number rather than re-explaining
the cause here; this table maps symptom → issue, it doesn't replace the issue body.
