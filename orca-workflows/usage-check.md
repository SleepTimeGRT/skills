# Orca Workflows Usage Check

> verified_at: 2026-08-03

Shared procedure for checking provider (Claude/Codex/Antigravity/Gemini/...) rate-limit usage and reset
time — for a coordinator deciding whether to keep dispatching to a provider or avoid it because it's close
to quota (same precedent as `logging.md`/`spawn-failures.md`/`dispatch-verify.md`: split out here instead of
each `SKILL.md` repeating it). Not currently wired into any of the three skills' dispatch flow — this is a
reference a coordinator consults on demand, not an automated gate.

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

## Reverify before relying on this

`rateLimits`'s shape is CLI/API surface that can change across `orca` versions. Run
`orca account list --help` (or a live call) to confirm the shape still matches this file before trusting it.
