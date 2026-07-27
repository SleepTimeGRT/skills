---
name: model-agy
description: agy Gemini worker model and effort selection for Simple work and computer-use execution
---

# agy (Gemini / Google)

Launch:

```bash
agy -p '<instructions + artifact paths>' --model <token> --print-timeout 15m \
  --dangerously-skip-permissions
```

`--dangerously-skip-permissions` is required for headless workers. Without it, tool calls can be
auto-denied while the process exits successfully with no useful output.

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
