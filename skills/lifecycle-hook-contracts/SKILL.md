---
name: lifecycle-hook-contracts
description: 'Cross-runtime contract, canonical adapters, and drift audit for agent lifecycle hooks shared between Claude Code and Codex, starting with the Stop hook. Use whenever a repo wires the same or related script into both .claude/settings.json and .codex/hooks.json, when a Stop hook reports invalid JSON output or fails after a cwd change, or before hand-editing .claude/hooks/stop.sh or .codex/hooks.json in a repository that follows this convention. Excludes Git-native hooks (lifecycle-gate-policy), output-volume compaction (token-efficient-gates), and remote CI (remote-ci-economics).'
---

# Lifecycle Hook Contracts

One Stop-hook protocol, two runtimes. Each runtime's actual contract is
verified against its own official docs in
[references/protocol-contracts.md](references/protocol-contracts.md) — read
it before changing either adapter, since the two runtimes' rules differ in
ways that are easy to get wrong from memory (see the `"decision":"approve"`
regression this skill exists to catch).

## The contract

| Outcome | Response |
|---|---|
| Allow stop | exit 0, stdout `{}` |
| Keep working | exit 2, human-readable diagnostic on stderr |

Both `assets/hooks/stop-adapter-claude.sh` and
`assets/hooks/stop-adapter-codex.sh` implement exactly this, wrapping the
repo's existing capture engine unmodified. Both source
`$REPO_ROOT/scripts/token-gate.sh` and call `token_gate_capture`; those two
names are literal in the adapter, not configurable — `lifecycle-hook.conf`
defines `STOP_HOOK_CMD` and nothing else. Neither adapter emits a
`decision` field — no runtime-specific JSON schema is needed for the
Stop-only scope this skill covers.

**Dependency**: the target repo must provide a capture engine at
`scripts/token-gate.sh` that defines a `token_gate_capture` function.
`lifecycle-gate-policy` no longer installs that file — its
`assets/scripts/token-gate.sh` is an optional reference implementation you may
copy. If the repo's real engine lives elsewhere, put a shim at
`scripts/token-gate.sh` that sources it; do not repoint the adapter, because
`scripts/audit.py` below compares the installed adapter against the canonical
one by hash and reports `canonical-hash DRIFT` (exit 1) for any edit. This skill
does not ship its own copy of the capture engine.

## Audit a repository

```bash
python3 <skill-dir>/scripts/audit.py --repo <target> [--format json]
```

Read-only. Flags: a script shared verbatim across both runtime configs
without per-runtime adapters, an unsupported `decision` value (e.g.
`"approve"`), a cwd-relative command with no `${CLAUDE_PROJECT_DIR}` or
`$(git rev-parse --show-toplevel)` rooting, drift against the canonical
adapter hash, and JSON output mixed with an exit code outside `{0, 2}`.

## Apply to a repository (only on explicit request)

Audit first; apply only when the user asks. One repository per commit.

1. Copy `assets/hooks/stop-adapter-claude.sh` → `<repo>/.claude/hooks/stop.sh`,
   `assets/hooks/stop-adapter-codex.sh` → `<repo>/.codex/hooks/stop.sh`. Mark
   both executable.
2. Point `.claude/settings.json`'s Stop hook at
   `${CLAUDE_PROJECT_DIR}/.claude/hooks/stop.sh`, and `.codex/hooks.json`'s
   Stop hook at `$(git rev-parse --show-toplevel)/.codex/hooks/stop.sh` — not
   at the previous shared script directly.
3. If the repo's Stop validation needs something other than
   `pnpm verify:static`, copy `assets/lifecycle-hook.conf` to
   `<repo>/scripts/lifecycle-hook.conf` and set `STOP_HOOK_CMD`.
4. Run `audit.py` — it must exit COMPLIANT. Trigger a real Stop in each
   runtime once to confirm no "invalid hook output" warning appears.

## Boundaries

- **lifecycle-gate-policy** owns Git-native hooks (pre-commit/pre-push/premerge)
  only; it does not gain a lifecycle-hook asset. This skill owns agent
  lifecycle hooks — Stop today, other events only if a real need appears.
- **token-efficient-gates** owns the capture-and-inspect convention that
  `scripts/token-gate.sh` implements, but ships no copy of it; the only bundled
  implementation is `lifecycle-gate-policy`'s optional reference asset. This
  skill wraps whatever the repo has at that path, unmodified, and never forks it.
- Antigravity has a third, distinct Stop contract (`decision: "continue"`,
  no documented exit-2 escape hatch) and is not covered — see
  `references/protocol-contracts.md`.
