# Orca Workflows Usage Check

> verified_at: 2026-08-03

Shared procedure for checking provider (Claude/Codex/Antigravity/Gemini/...) rate-limit usage and reset
time — for a coordinator deciding whether to keep dispatching to a provider or avoid it because it's close
to quota (same precedent as `logging.md`/`spawn-failures.md`/`dispatch-verify.md`: split out here instead of
each `SKILL.md` repeating it). Wired into `model-selection.md`'s pinning step (see its "Quota check before
pinning" section) — every provider choice that goes through that file's tables or preference order runs
this check first. `orca-evaluate` §3's `codex_available` flag is a separate, narrower mechanism (session-known
information, not a live call to this procedure) scoped only to that section's reviewer-selection script; the
two can disagree until unified.

## `orca account list --json`

```bash
orca account list --json
```

`.result.rateLimits.<provider>` returns the same shape for every provider (`claude`, `codex`, `gemini`,
`antigravity`, `opencodeGo`, `kimi`, `minimax`, `grok`):

```json
{
  "provider": "<name>",
  "session": { "usedPercent": 8, "windowMinutes": 300, "resetsAt": 1785777000057, "resetDescription": "Tue 2:10 AM" },
  "weekly": { "usedPercent": 38, "windowMinutes": 10080, "resetsAt": 1786204800057, "resetDescription": "Sun 1:00 AM" },
  "status": "ok",
  "error": null
}
```

One parser handles every provider — `usedPercent`/`windowMinutes`/`resetsAt` (absolute epoch ms)/
`resetDescription` are the same fields regardless of provider. Confirmed live in this environment
(2026-08-03):

- `claude` has `session` (5h window) + `weekly` + `fableWeekly`.
- `codex` (GPT) has no `session` key — only `weekly` + `rateLimitResetCredits`. Don't assume every provider
  has both windows; check for the key's presence.
- `gemini` and `antigravity` each have `session` (1h window) + a `buckets` array (e.g. a `"Pro"` bucket), no
  `weekly`. In this environment the two providers' `session`/`buckets` values were byte-identical — same
  underlying account exposed under two provider names.
- `status` is `"ok"` when the provider has working credentials; otherwise `"unavailable"` with an `error`
  string (observed for `opencodeGo`/`kimi`/`minimax`/`grok` here — missing credentials, not a tool defect).

No account setup or extra flags needed to read this — `account list --json` returns `rateLimits` for every
provider regardless of whether `account add` was run for it.

## `accounts` is not a quota signal

`.result.<provider>.accounts` (the orca managed-auth registry for that provider, e.g. `.result.codex.accounts`)
lives under the provider's own top-level object — a sibling of the shared `.result.rateLimits` object, not a
field nested inside `.result.rateLimits.<provider>`. Candidate exclusion (hard-exclude) and deprioritization
(prefer-avoid) are decided only by the `rateLimits` rules in `model-selection.md`'s "Quota check before
pinning" — the `accounts` array is not a quota signal and plays no role in that decision.

An empty `accounts` array (`accounts: []`, i.e. the provider isn't registered in orca's managed-auth registry)
does not mean the provider can't be dispatched: CLI-native login can still make a spawn work. Don't exclude a
candidate just because its `accounts` array is empty — check `rateLimits` instead.

## Reverify before relying on this

`rateLimits`'s shape is CLI/API surface that can change across `orca` versions. Run
`orca account list --help` (or a live call) to confirm the shape still matches this file before trusting it.
