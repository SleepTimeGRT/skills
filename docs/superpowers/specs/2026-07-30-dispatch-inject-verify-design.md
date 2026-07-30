# Dispatch-Inject Verify Design

**Date:** 2026-07-30

**Scope:** every `orca orchestration dispatch --task <id> --to <handle> --inject` call site in
`orca-workflow`, `orca-task-runner`, `orca-evaluate`, plus a new shared `orca-workflows/dispatch-verify.md`
reference document and one new row in `orca-workflows/spawn-failures.md`

## 1. Purpose

Issue #43: `dispatch --inject` can land text in a target terminal's input box without the trailing Enter
actually registering. The terminal is left holding an unsent draft. `terminal read` alone cannot tell this
apart from "task finished, terminal legitimately idle" — both render as static output with no further
activity. In the observed case (medicount #401/#411, `task-evaluate-411`), repeated `terminal read` calls
from the orchestrating session all looked identical to normal idle; only resending `--enter` confirmed the
terminal had actually been stuck.

This is a different failure category from the existing `spawn-failures.md` #16/#37 rows: the terminal is
alive and the session itself launched fine — the relay protocol's send step silently dropped between
`terminal send`-equivalent injection and Enter.

## 2. Detection: provider-agnostic tail diff

Immediately after every `dispatch --inject`, run a bounded two-read comparison instead of trusting a single
`terminal read`:

```bash
# t0 — immediately after dispatch --inject
tail_0="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
sleep 15
# t0+15s
tail_1="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
```

If `tail_0` and `tail_1` are byte-identical, treat the dispatch as unsent. A genuinely-received prompt
produces *some* visible change within 15s on any REPL-capable provider — a streaming token, a busy
indicator, a tool-call line — regardless of which provider's UI is rendering it. This deliberately avoids
matching literal prompt/idle markers (e.g. Claude Code's `❯`/`⏺`): those are provider-specific and would
need a parallel definition for Codex's REPL UI, with no shared primitive to keep them in sync. The 15s
window is a starting default; tune it during implementation if a provider's typical first-token latency
needs more headroom.

This check reads tail content only to compare it for equality — it does not parse or act on what the
content says. `orca-workflow`'s existing boundary ("diff/report 본문을 직접 읽지 않는다") is not violated:
opaque equality comparison is not content interpretation.

## 3. Recovery: single Enter retry, then hand off to spawn-failures.md

```bash
if [ "$tail_0" = "$tail_1" ]; then
  orca orchestration dispatch --task <task_id> --to <handle> --inject --enter --json   # or the CLI's
    # dedicated "send Enter only" form, confirmed against `orca skills get orca-cli` at implementation time
  sleep 15
  tail_2="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
  if [ "$tail_1" = "$tail_2" ]; then
    # unresolved — hand off to the standard spawn-failures.md procedure (grep known signatures first,
    # diagnose if no match, re-dispatch only if the fix calls for it)
    :
  fi
fi
```

- The retry resends only Enter, not the original text — resending the full `--inject` payload risks a
  duplicate prompt if the first attempt actually *did* land moments after `tail_0` was captured.
- A second static comparison escalates to the existing `spawn-failures.md` grep-first procedure rather than
  looping retries indefinitely.

## 4. New shared reference: `orca-workflows/dispatch-verify.md`

Added alongside `logging.md`/`spawn-failures.md`, same two-layer precedent (git-tracked operational
procedure, one copy, three `SKILL.md` files point to it instead of repeating the bash). Holds:

- The tail-diff snippet (Section 2)
- The retry-then-escalate snippet (Section 3)
- A note that the default 15s window is a placeholder to validate against real provider latency, not a
  guaranteed-correct constant

Each of the 6 existing `dispatch --inject` call sites gets a short pointer comment added directly after the
`dispatch --inject` line, in the same style already used for `spawn-failures.md`/`logging.md` references:

- `skills/orca-task-runner/SKILL.md:116` (wave impl dispatch)
- `skills/orca-workflow/SKILL.md:65` (task-runner dispatch)
- `skills/orca-workflow/SKILL.md:87` (evaluate dispatch)
- `skills/orca-evaluate/SKILL.md:25` (self-relative mirror of the evaluate-session launch dispatch)
- `skills/orca-evaluate/SKILL.md:44` (contract-review dispatch)
- `skills/orca-evaluate/SKILL.md:141` (code-review dispatch)

## 5. New `spawn-failures.md` row: log-based signature (exception to the literal-substring rule)

The table's existing "Adding a new row" guidance requires `failure_signature` to be a literal, grep-able
substring from `terminal read` output. This failure mode has no such substring — its signature is an
*absence* of change, which is a structural/relational pattern, not a literal string. The new row documents
this explicitly as an exception, and gives a signature grep-able against the persisted log instead of live
terminal output, reusing `logging.md` §2's existing `term-<handle>.jsonl` `sent`/`recv` schema:

> **Signature (log-based, not literal terminal text):** in `term-<handle>.jsonl`, a `sent` event with no
> `recv` event after it for an unusually long span, or two consecutive `recv` events whose `content` is
> identical. Check with `jq` over the terminal's own `term-<handle>.jsonl`, not `grep` over live terminal
> output.
>
> **Root cause:** the relay's send step (text injection) and its Enter confirmation are not atomic from the
> caller's side; one can complete while the other silently does not, and a single `terminal read` cannot
> distinguish the resulting stuck state from normal post-completion idle.
>
> **Fix:** `dispatch-verify.md` procedure — bounded tail-diff, single Enter-only retry, escalate if still
> static.
>
> **known_issue:** #43

## 6. Edge cases

- A dispatch that never gets a `terminal read` back today (e.g. `orca-workflow`'s task-runner dispatch,
  which relies on `task-list` polling / `worker_done` rather than reading the terminal) still gets the
  tail-diff check — it is a cheap, opaque liveness probe, not the same thing as the skill reading
  diff/report content for judgment.
- If the provider's first-token latency legitimately exceeds 15s (e.g. a slow cold boot), the retry-then-
  escalate path may fire on a false positive. The Enter-only retry is harmless in that case (Enter on an
  already-submitted prompt is a no-op for every provider checked here), so the cost of a false positive is
  one extra wait cycle, not a corrupted session.
- This does not replace `orca-task-runner`'s existing wave-loop timeout/`count:0` checkpoint (`terminal
  read` for "생사 확인") — that check covers stalls *during* a task's execution; this one covers the
  narrower window immediately after `dispatch --inject` itself.

## 7. Validation

1. Confirm `orca terminal read --json`'s `.result.terminal.tail` shape matches what `logging.md` §2 already
   documents (it does — reuse, don't re-derive).
2. Confirm all 6 call sites listed in Section 4 get the pointer comment, by re-grepping
   `dispatch --task.*--inject` across the three `SKILL.md` files after the edit.
3. Confirm the CLI's actual "Enter only" affordance (`--enter` flag, a separate `terminal send` primitive, or
   re-`dispatch --inject` with empty text) against `orca skills get orca-cli` before wiring Section 3's
   snippet — do not assume the flag name shown here is final.
4. Dry-run the tail-diff snippet against a real terminal handle for both outcomes (genuinely idle after
   completion vs. immediately after a fresh dispatch) to confirm the 15s default does not false-positive on
   a normal fast turnaround.
5. Confirm the new `spawn-failures.md` row does not collide with the `#37` row (both involve `dispatch
   --inject` and a terminal that looks idle) — the distinguishing detail is `#37`'s target already exited to
   a bare shell (`zsh: parse error` reappears), while #43's target is still a live, waiting REPL.

No skill deployment step applies under the existing `orca-workflows/` symlink-tracks-main convention — this
change goes live on merge to `main`.
