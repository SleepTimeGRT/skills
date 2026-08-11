# agy Model Evidence

> verified_at: 2026-07-30

Load this file only to audit, change, or re-validate `../../models/agy.md`.

## 2026-07-30 REPL retirement (reverses 2026-07-29 promotion)

The 2026-07-29 smoke below promoted REPL to the primary agy launch pattern. Further live testing
the next day found two failure modes serious enough to retire agy REPL entirely and move
agy to headless-only (`../../models/agy.md` no longer documents a REPL section for agy):

- **Unfocused-boot hang.** A REPL terminal created via `orca terminal create` with no explicit
  focus stalled indefinitely before reaching the interactive prompt. `cli.log` for the agy
  process went silent for 90s+ (no new lines at all, not just a slow render) while the terminal
  stayed on the pre-auth "not signed in" banner. Calling `orca terminal switch --terminal
  <handle>` produced an immediate `Full redraw completed` log line and the session finished
  booting right after.
- **Concurrent-focus deadlock.** Creating two REPL agy terminals back-to-back, each with
  `--focus`, in the same worktree: both got stuck on the same partial banner. `ps -o
  pid,stat,pgid,tpgid` showed both processes as `S+` (normal sleeping, each already the
  foreground process group of its own pty) — not `T` (stopped), ruling out a SIGTTIN/job-control
  explanation. A subsequent `orca terminal switch` to one of the two did **not** recover it —
  `cli.log` stayed silent for 30s+ after the switch. This matches
  [stablyai/orca#7442](https://github.com/stablyai/orca/issues/7442): a renderer IPC handshake
  that assumes an active/focused window, evaluated once at boot, unrecoverable by a later focus
  change.
- **Headless has none of this.** A single headless (`-p`) launch with no focus at all completed
  in ~15s. Two headless launches created back-to-back with no focus, run concurrently, both
  completed independently and correctly (~10-15s each) with no contention.
- **Consequence for the "agent e2e reporting is a ping-pong role" claim below (2026-07-29
  entry).** That claim assumed agy needed REPL because a *later* `dispatch --inject` had to
  reach a live process. The actual fix is narrower: put the complete task in the `-p` argument
  at launch time and never `dispatch --inject` into agy at all — this removes agy from the
  REPL requirement without reintroducing the issue #37 failure the 2026-07-29 promotion fixed.
  `orca-evaluate`'s own top-level session (previously hosted on agy) now runs on a REPL-capable
  provider other than agy; agy is only spawned headless, for agent e2e specifically.

## 2026-07-29 REPL smoke

- The trustedWorkspace re-prompt reproduced even from a path inside an already-trusted parent
  directory (`~/worktrees/...`), not only on a first-time launch directory. Automation cannot skip
  the trust-confirm step just because a parent directory was trusted earlier.
- `orca orchestration task-create` followed by `dispatch --inject` reached a still-running REPL
  process successfully. This is the direct evidence behind promoting REPL to the primary launch
  pattern in `../../models/agy.md` and retiring one-shot `-p` launches for any role the coordinator
  later injects into (see `../../spawn-failures.md`, issue #37).
- A bare `agy` invocation with no `--model` flag booted into `Gemini 3.6 Flash (High)` per the
  startup banner — the basis for the `--model` requirement in `../../models/agy.md`.
- **Limit**: account quota was exhausted mid-session (`Individual quota reached`, 119h reset)
  before the full round trip through to `worker_done` could be exercised. "REPL launch through
  `dispatch --inject` succeeds" and "a full evaluator round trip completes" are separately verified
  claims — only the former is confirmed by this smoke.

## Runtime behavior

The 2026-07-25 smoke found:

- `gemini-3.6-flash-high` booted and returned exit 0;
- headless tool calls without `--dangerously-skip-permissions` could be auto-denied while the process
  still exited successfully with no useful output;
- workspace-trust registration did not change that behavior for files inside the launch directory;
- paths outside the launch directory were not evaluated.

This is why the permission flag remains in the operational launch command. It is used only for workers
already isolated by the surrounding workflow.

## Model-generation decision

`gemini-3.6-flash` replaced the previous flash generation after it appeared in `agy models` on 2026-07-21.
The recorded public list price was $1.50 input and $7.50 output per 1M tokens, with $0.15 cached input.

Published and third-party reports collected during the decision recorded:

- OSWorld-Verified: 83.0%;
- Browser Use Benchmark: 68%;
- GDM-MRCR v2 at 128K: 91.8%;
- SWE-Bench Pro: 58.7%.

These results were not broken down by agy `low`, `medium`, and `high` effort. They support evaluating the
model generation for computer/browser execution, but they do not prove that medium is optimal. The
medium assignment comes from the narrower execution/reporting role and remains subject to representative
agent-e2e pilots.

Sources recorded during the 2026-07-21 to 2026-07-25 research included Google release material, Browser
Use, Artificial Analysis, OpenRouter, CodingFleet, and BuildFastWithAI. Because several are secondary
sources and URLs were not captured in the original decision, re-validation must replace this paragraph
with direct links before these numbers are used for a new routing change.

## Routing limits

The recorded 58.7% SWE-Bench Pro result was below the published Codex Terra and Sol results, so agy was not
promoted to Routine or High Risk code judgment. Cross-provider benchmark differences still limit that
comparison; it is a guardrail, not a precise quality ranking.

The Computer Use route favors agy because the Browser Use result is closer to Playwright agent e2e than a
general desktop benchmark. Long context alone is not a routing reason: context capacity and retrieval
scores are different properties, and no representative Orca long-log comparison is recorded.

## BrowserMCP and quota gaps

The intended agent-e2e setup is agy plus the project-declared e2e tool (resolved from the consuming
skill's `docs/agents/e2e-tooling.md`, not necessarily an MCP — e.g. a raw CLI). The repository still needs
a recorded connection smoke before treating that path as verified.

Public sources did not establish that the new model generation kept the previous quota and rate limits.
Track 429 and quota-skip frequency during pilots. `orca-evaluate` and `orca-task-runner` own runtime
fallback behavior.

## Re-validation

Re-check this file when `agy models`, launch flags, Google model availability, quota behavior, BrowserMCP
integration, or representative agent-e2e results change.
