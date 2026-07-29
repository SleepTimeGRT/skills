---
name: model-agy
description: agy Gemini worker model and effort selection for Simple work and computer-use execution
---

# agy (Gemini / Google)

## Headless only — agy REPL is unsupported here

agy is launched headless (`-p`, one-shot) for every role in this repo, including roles that
would otherwise need back-and-forth (ping-pong) with the coordinator — contract review, diff
review, agent-e2e reporting. Do not launch agy as a REPL (bare `agy` with a later
`dispatch --inject`) for any role. This is a hard exclusion, not a preference:

- **Unfocused-boot hang.** A REPL launch created via `orca terminal create` with no explicit
  focus can stall indefinitely before reaching the interactive prompt — the process itself
  stops producing log output, not just the rendered screen (2026-07-30 smoke: `cli.log` silent
  for 90s+ on an unfocused terminal; calling `orca terminal switch` to focus it produced an
  immediate `Full redraw completed` and a normal boot right after).
- **Concurrent-focus deadlock.** Launching two REPL agy sessions back-to-back, each requesting
  focus (`terminal create --focus`), can wedge **both** permanently — neither backend process
  produces further log output, and a later `orca terminal switch` / `terminal send --enter`
  does not recover either one (2026-07-30 smoke). This matches the failure class in
  [stablyai/orca#7442](https://github.com/stablyai/orca/issues/7442): the renderer IPC
  handshake assumes an active/focused window and is a one-shot negotiation evaluated only at
  boot — later focusing cannot recover it. Process state was confirmed `S+` via `ps`
  (normal sleeping, correct foreground pgrp for its own pty), ruling out a SIGTTIN/job-control
  explanation — this is Orca's renderer-side handshake, not a shell job-control issue.
- **The original reason for routing agent-e2e to REPL no longer holds.** It used to be routed
  there because a one-shot launch was paired with a *later* `dispatch --inject`, and an
  already-exited one-shot process can't receive that (`../spawn-failures.md`, issue #37). The
  fix is not "use REPL for this role" — it's "put the complete task in the `-p` argument at
  launch time and never `dispatch --inject` into agy at all" (see `skills/orca-evaluate/SKILL.md`
  §2).

If a role genuinely needs a live, injectable session — the coordinator doesn't have the full
task yet at spawn time, or the role needs a true multi-round exchange — route it to a provider
other than agy that supports REPL reliably (resolve via
`~/.agents/orca-workflows/model-selection.md`, the same way `orca-evaluate`'s §1/§3 sub-agent
spawns already do). Do not default that role to agy just because agy is already in use
elsewhere in the same skill.

## Headless (`-p`, one-shot — the only supported launch pattern)

```bash
agy -p '<complete instructions + artifact paths, fully resolved at launch time>' \
  --model <token> --print-timeout 15m --dangerously-skip-permissions
```

- **`--dangerously-skip-permissions` is required.** Without it, tool calls can be auto-denied
  while the process exits successfully with no useful output.
- **Embed the complete task in the `-p` argument.** There is no later injection step — if part
  of the task depends on something not known until a previous step finishes (e.g. a
  dynamically-created identifier), resolve it and interpolate it into the `-p` string before
  launching. Don't try to defer any part of it.
- **No focus needed, and no focus-related contention.** Two headless launches created
  back-to-back with no focus at all completed independently and correctly (2026-07-30 smoke,
  ~10-15s each, run concurrently, no interference between them).
- **Completion detection.** The shell hosting the one-shot process does **not** exit when agy
  exits (the shell just returns to its own prompt) — `orca terminal wait --for exit` will time
  out against it. Use `orca terminal wait --for tui-idle --timeout-ms <print-timeout + buffer>`
  and then `orca terminal read`, or (more robust for longer output) have the `-p` prompt
  instruct agy to write its result to a report file and read that file directly instead of
  tail-scraping terminal text.
- **Run inside an Orca-managed terminal**, not a bare subprocess with no controlling tty —
  headless agy launched without any tty at all is a separately-documented hang class upstream
  ([google-antigravity/antigravity-cli#508](https://github.com/google-antigravity/antigravity-cli/issues/508)).

## Mapping

| Model token | Use | Effort |
|---|---|---|
| `gemini-3.6-flash-high` | Higher-accuracy computer-use/artifact cross-check when needed | high |
| `gemini-3.6-flash-medium` | Default agent e2e and skeptical raw-artifact cross-check | medium |
| `gemini-3.6-flash-low` | Simple mechanical work | low |

Do not route Routine or High Risk code judgment to agy. Technical judgment stays with a risk-tier worker
even when agy executes the browser or synthesizes raw traces.

For agent e2e, configure an accessibility-tree Playwright MCP and smoke-test the connection before relying
on it. On quota or provider errors, use the fallback procedure owned by `orca-evaluate` or
`orca-task-runner`.

Load [the agy evidence reference](../references/models/agy.md) only when auditing, changing, or
re-validating this mapping.
