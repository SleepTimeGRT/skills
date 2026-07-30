# Orca Workflows Dispatch Verify

> verified_at: 2026-07-30

Shared post-`dispatch --inject` verification procedure for `orca-task-runner`/`orca-evaluate`/`orca-workflow`
(issue #43) — split out so the three `SKILL.md` files point here instead of each repeating the same bash
(same precedent as `logging.md`/`spawn-failures.md`).

## Why

`dispatch --inject` can land text in a target terminal's input box without Enter actually registering. A
single `terminal read` right after cannot tell "stuck, unsent" apart from "task already finished, terminal
legitimately idle" — both render as static output with no further activity. This file defines a bounded
check that can, without depending on any provider-specific UI marker (Claude Code's prompt-ready/recording
indicators vs. Codex's own REPL chrome — a marker-based check would need a parallel definition per provider
with no shared primitive to keep them in sync).

## Procedure — run immediately after every `dispatch --inject`

```bash
tail_0="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
sleep 15
tail_1="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
if [ "$tail_0" = "$tail_1" ]; then
  # Unsent — resend Enter only, never resend the original text (avoids a duplicate prompt if the
  # first attempt actually landed a moment after tail_0 was captured). Confirm the CLI's exact
  # "Enter only" affordance against `orca skills get orca-cli` — do not assume a flag name.
  orca orchestration dispatch --task <task_id> --to <handle> --inject --enter --json
  sleep 15
  tail_2="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
  if [ "$tail_1" = "$tail_2" ]; then
    # Still static — hand off to ~/.agents/orca-workflows/spawn-failures.md (grep known
    # signatures first, diagnose if no match) rather than looping this retry indefinitely.
    :
  fi
fi
```

15s is a starting default, not a validated constant — tune it if a provider's typical first-token latency
needs more headroom. A false positive (retry fires on a merely slow turn) costs one harmless extra Enter (a
no-op on an already-submitted prompt) plus one more 15s wait, not a corrupted session.

This check compares tail content for equality only — it never parses or acts on what the content says.
Skills whose stated principle is not reading a terminal's output directly for judgment (e.g.
`orca-workflow`, "diff/report 본문을 직접 읽지 않는다") are not violating that principle by running this
check — opaque equality comparison is not content interpretation.

## Escalation

A second static comparison means: apply the `spawn-failures.md` procedure (grep known signatures, diagnose
if no match) rather than retrying `--enter` a second time.

## Edge cases

- This does not replace `orca-task-runner`'s existing wave-loop timeout/`count:0` checkpoint (`terminal
  read` for "생사 확인") — that check covers stalls *during* a task's execution, potentially minutes later.
  This procedure covers only the narrow window immediately after `dispatch --inject` itself.
- Distinguish from `spawn-failures.md`'s `#37` row: both involve `dispatch --inject` landing on a terminal
  that looks idle, but `#37`'s target has already exited to a bare shell (`zsh: parse error` reappears on
  the *next* interaction), while this procedure's target is still a live, waiting REPL — the text is
  genuinely sitting in that REPL's own input box, not falling through to a dead shell underneath it.
