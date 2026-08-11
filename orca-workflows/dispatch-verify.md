# Orca Workflows Dispatch Verify

> verified_at: 2026-07-30

Shared post-`dispatch --inject`-or-`worker-start` verification procedure for
`orca-task-runner`/`orca-evaluate`/`orca-workflow-task`/`orca-workflow-epic`/`orca-workflow` (issue #43) — split out so the `SKILL.md` files point
here instead of each repeating the same bash (same precedent as `logging.md`/`spawn-failures.md`). The
same unsubmitted-draft failure mode reproduces identically under `worker-start`
(`docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md`, Test 3) — the bash below is
identical regardless of which command injected the text.

## Why

`dispatch --inject` can land text in a target terminal's input box without Enter actually registering. A
single `terminal read` right after cannot tell "stuck, unsent" apart from "task already finished, terminal
legitimately idle" — both render as static output with no further activity. This file defines a bounded
check that can, without depending on any provider-specific UI marker (Claude Code's prompt-ready/recording
indicators vs. Codex's own REPL chrome — a marker-based check would need a parallel definition per provider
with no shared primitive to keep them in sync).

## Pre-dispatch — freshly launched REPL은 boot-quiesce 확인 후에만 inject (issue #84)

`terminal wait --for tui-idle`은 `dispatch --inject`의 충분조건이 아니다 — codex는 tui-idle이
satisfied된 뒤에도 MCP 서버 부팅이 계속되며(실측 2026-08-08: tui-idle 만족 시점에 `Starting MCP
servers (4/5)` 스피너가 여전히 동작 중), 그 구간에 주입된 bracketed-paste 텍스트는 일부 또는 전부
유실된다. 유실되면 아래 사후 확인의 Enter-only 재시도도 무의미하다 — 재전송할 초안 자체가 없다.

**freshly launched REPL(터미널 생성 직후의 첫 dispatch)**에는 tui-idle 이후 다음을 추가로 요구한다:

```bash
cur="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.latestCursor')"
sleep 12
new="$(orca terminal read --terminal <handle> --cursor "$cur" --json | jq -r '.result.terminal.returnedLineCount')"
# new가 0이면 boot 출력이 정지(quiesce)한 것 — dispatch --inject 진행.
# 0이 아니면 아직 부팅 중 — cur를 최신 latestCursor로 갱신해 반복(상한은 호출부의 스폰 timeout 예산).
```

scrollback 전체를 문자열 grep하는 방식은 쓰지 않는다 — TUI 리페인트 잔재가 과거 `Starting MCP
servers` 프레임에 계속 매칭돼 "아직 부팅 중"으로 오판한다(실측). cursor-scoped 신규-출력 카운트만이
애니메이션 정지를 정확히 판별한다. 이미 dispatch를 한 번 이상 정상 처리한 터미널(라운드 2+ 재-engage
등)에는 이 검사가 필요 없다 — boot 구간이 이미 지났다.

## Procedure — run immediately after every `dispatch --inject`

**This is a positive-confirmation check, not a tail-changed check.** An earlier version treated "tail
changed" as proof of submission — the contrapositive of "tail unchanged ⇒ unsent" — without ever confirming
submission actually happened. That contrapositive doesn't hold: `.result.terminal.tail` includes provider
TUI chrome (spinner frames, elapsed-time counters, token-usage footers) that changes on its own, submitted
or not, and an MCP auth modal rendering between `tail_0` and `tail_1` changes the tail while leaving the
prompt sitting unsubmitted in the input box. Both produced an observed false-OK in practice — the pipeline
reported "sent" while a human had to press Enter manually (issue #58). The fix: confirm the injected text
itself is echoed back as a submitted turn, not merely that *something* in the tail moved.

```bash
spec_prefix="$(printf '%s' "$spec_text" | head -c 80)"   # first ~80 chars of the exact string passed to
                                                            # `task-create --spec` — enough to be a
                                                            # distinctive fragment, not a content read
sleep 15
tail_1="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
if printf '%s' "$tail_1" | grep -qF "$spec_prefix"; then
  :   # confirmed — the payload we injected is echoed back as a submitted turn
else
  # Not confirmed. This covers both the old "tail unchanged" case and the false-OK case (tail moved for
  # an unrelated reason, e.g. chrome or an auth modal, but the prompt never actually submitted).
  # Resend Enter only, never resend the original text (avoids a duplicate prompt if the first attempt
  # actually landed and the echo simply scrolled out of the tail window before this check ran).
  # `orca terminal send` with `--enter` and no `--text` sends Enter alone and does not touch the
  # terminal's existing input — confirmed against a live scratch terminal.
  orca terminal send --terminal <handle> --enter --json
  sleep 15
  tail_2="$(orca terminal read --terminal <handle> --json | jq -r '.result.terminal.tail | join("\n")')"
  if ! printf '%s' "$tail_2" | grep -qF "$spec_prefix"; then
    # Still not confirmed — hand off to ~/.agents/orca-workflows/spawn-failures.md (grep known
    # signatures first, diagnose if no match) rather than looping this retry indefinitely.
    :
  fi
fi
```

15s is a starting default, not a validated constant — tune it if a provider's typical first-token latency
needs more headroom. A false negative (the echo has already scrolled out of the tail window by the time
this check runs, on an already-submitted prompt) costs one harmless extra Enter (a no-op on an
already-submitted prompt) plus one more 15s wait, not a corrupted session — the same asymmetry the old
check relied on, just applied to the opposite failure direction. A false positive (this check confirms
submission that didn't happen) is not possible by construction: `$spec_prefix` only appears in the tail if
that exact string was actually written there.

When dispatching a parallel wave (multiple handles at once — e.g. `orca-task-runner`'s wave loop), the wait
is shared, not per-handle: compute `spec_prefix` for every handle first (each from that handle's own
`$spec_text`), `sleep 15` once, then re-read all handles for `tail_1` and check each against its own prefix.
Waiting 15s per handle serially is unnecessary. The same sharing applies to the retry round: send the
Enter-only retry to every handle that came back unconfirmed, then `sleep 15` once and re-read all of them
for `tail_2` — not a per-handle serial retry wait.

These reads never pass `--limit`, so `tail_1` and `tail_2` both use the same (unspecified) default retained
tail window — a very long streaming response could in principle scroll the echoed prompt out of the window
before either read runs, which is exactly the false-negative case already priced in above (costs one
harmless extra Enter, not a corrupted session).

**This check does not violate a skill's "don't read terminal output for judgment" principle** (e.g.
`orca-workflow-task`, "diff/report 본문을 직접 읽지 않는다"). It only tests whether a literal, known-in-advance
substring — the exact bytes this procedure itself injected — is present in the tail. It never inspects,
interprets, or acts on anything the *target* produced; a byte-for-byte membership test against your own
payload is not content interpretation, the same distinction the prior equality-only version relied on,
just applied to a substring match instead of a whole-string comparison.

## Escalation

A second static comparison means: apply the `spawn-failures.md` procedure (grep known signatures, diagnose
if no match) rather than blindly retrying `orca terminal send --enter` a second time in a loop. This is not
a prohibition on ever sending Enter again — `spawn-failures.md`'s `#43` row may itself direct one further
Enter, but only after manually confirming via `orca terminal read` that the terminal is still holding
unsubmitted input, not as an unconditional retry.

**Before that retry, distinguish "stuck draft" from "composer empty" — the Enter-only remedy only fixes the
former.** The procedure above (and `spawn-failures.md`'s `#43` row) was written for the case where the
injected text landed in the composer but the trailing Enter didn't register — resending Enter alone submits
that already-present draft. A live `worker-start --agent codex` failure (issue #151, 2026-08-11) showed a
different failure shape: the paste happened before the target TUI could accept input at all, so *nothing*
reached the composer — no draft, partial or otherwise, anywhere in `tail_2`. Sending Enter into an empty
composer is a no-op; the loop above would exhaust its retries and still report "not confirmed" for a reason
the remedy can't address.

```bash
# After tail_2 still fails the $spec_prefix check: look for *any* trace of the injected payload, not just
# the clean prefix match above (a garbled/partial paste still counts as "something is there to submit").
spec_fragment="$(printf '%s' "$spec_text" | head -c 24)"   # shorter, coarser than $spec_prefix on purpose —
                                                              # tolerate mid-string corruption from a
                                                              # partial paste, not just a clean prefix
if printf '%s' "$tail_2" | grep -qF "$spec_fragment"; then
  : # some form of our payload is present but unsubmitted — the stuck-draft case, spawn-failures.md #43 applies
else
  # Composer is empty, not stuck. Resending Enter cannot help — there is nothing to submit. Treat this as a
  # lost dispatch, not a submit failure: worker-abandon the dispatch, then worker-start --retry-of it (same
  # provider/model/effort, unchanged spec) rather than retrying `terminal send --enter` further.
  :
fi
```

This distinction matters most for providers with a heavier boot sequence (MCP-server fan-out, plugin
loading) where the empty-composer shape is far more likely than the stuck-draft shape — `orca-task-runner`'s
codex path already avoids the race with the pre-dispatch boot-quiesce check above, so this branch is mainly
defense-in-depth there. Any dispatch path that skips that pre-check (a different skill, a low-level
`dispatch --inject` call outside `orca-task-runner`) is exactly where this branch is load-bearing.

## Edge cases

- This does not replace `orca-task-runner`'s existing wave-loop timeout/`count:0` checkpoint (`terminal
  read` for "생사 확인") — that check covers stalls *during* a task's execution, potentially minutes later.
  This procedure covers only the narrow window immediately after `dispatch --inject` itself.
- Distinguish from `spawn-failures.md`'s `#37` row: both involve `dispatch --inject` landing on a terminal
  that looks idle, but `#37`'s target has already exited to a bare shell (`zsh: parse error` reappears on
  the *next* interaction), while this procedure's target is still a live, waiting REPL — the text is
  genuinely sitting in that REPL's own input box, not falling through to a dead shell underneath it.
