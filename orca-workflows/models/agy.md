---
name: model-agy
description: agy Gemini worker model and effort selection for Simple work and computer-use execution
---

# agy (Gemini / Google)

## REPL (primary pattern)

Launch as a persistent interactive session, then attach orchestration to the live process —
launch-then-inject, the same pattern already validated for coding-agent workers elsewhere in this
repo:

```bash
orca terminal create --worktree active --title <role>-agy --command "agy --model <token>" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
# trustedWorkspace 재프롬프트가 보이면(이미 신뢰된 상위 폴더 하위에서도 재현됨 — 2026-07-29 실측).
# 기본 선택지가 이미 "Yes, I trust this folder"이므로 --enter만으로 확정된다(2026-07-29 스모크 실측:
# 이 커맨드로 trust 프롬프트를 통과하고 정상 부팅까지 확인함).
orca terminal send --terminal <handle> --enter --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
# 위 wait가 timeout이면(trust 대화상자가 죽었거나 응답 없음) fail-closed — dispatch --inject를
# 진행하지 않고 스폰 실패로 처리해 ../spawn-failures.md 절차부터 밟는다. 죽은 trust 대화상자에
# inject가 떨어지면 이슈 #37이 고친 것과 같은 부류의 실패가 재발한다.
orca orchestration task-create --spec "<instructions + artifact paths>" --json
orca orchestration dispatch --task <task_id> --to <handle> --inject --json
```

Use this form for any role that needs a back-and-forth (ping-pong) exchange with the coordinator —
contract review, code review, agent-e2e reporting. A one-shot headless launch (below) cannot
receive a later `dispatch --inject`: the process has already exited by the time the injection
arrives (see `../spawn-failures.md`, issue #37).

REPL launch requires all three of the following:

- **`--model <token>` explicit.** Omitting it boots the default effort, not the intended one.
  2026-07-29 smoke: a bare `agy` invocation (no `--model`) showed `Gemini 3.6 Flash (High)` in the
  startup banner — a silent change to the token/quota budget the caller intended.
- **trustedWorkspace re-prompt, auto-confirmed, fail-closed.** Reproduces even from a path inside
  an already-trusted parent directory (e.g. `~/worktrees/...`), not only on a first-time launch
  directory (2026-07-29 smoke). The default choice is already "Yes, I trust this folder", so
  `orca terminal send --terminal <handle> --enter --json` confirms it — no separate `--text` needed
  (2026-07-29 smoke: this command dismissed the prompt and reached a normal boot). Send it right
  after the first `tui-idle` wait, then re-check `tui-idle` before proceeding — a launch is not
  ready just because the process started. If that second wait times out, treat it as a spawn
  failure and do **not** `dispatch --inject` (fail-closed): an inject landing on a dead trust
  dialog reproduces the exact failure mode issue #37 fixed.
- **Sign-in latency, absorbed by the wait timeout.** Fast on a cached session (~2s, 2026-07-29
  smoke); a first-time or expired login can be slower. Keep the existing `orca terminal wait --for
  tui-idle --timeout-ms 60000` contract (same value already used for other coding-agent launches in
  this repo) rather than inventing a new timeout.

## Headless (`-p`, one-shot)

```bash
agy -p '<instructions + artifact paths>' --model <token> --print-timeout 15m \
  --dangerously-skip-permissions
```

`--dangerously-skip-permissions` is required for headless workers. Without it, tool calls can be
auto-denied while the process exits successfully with no useful output.

**Do not use this form for any role the coordinator will later `dispatch --inject` into** — the
process exits as soon as it prints its response, so a subsequent inject lands on a dead shell
instead of a live application (`../spawn-failures.md`, issue #37). Headless is for genuinely
fire-and-forget work only (e.g. a single bounded artifact cross-check with no follow-up message).

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
