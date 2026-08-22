# Retire the Orca-driven issue pipeline (orca-workflow*, orca-task-runner, orca-evaluate, orca-retro)

2026-08-22. The six `orca-*` skills, `skills/orca-set.version`, the `orca-workflows/` reference
tree (contract schema, logging, self-recovery, spawn-failures, model selection, issue-tracker
adapters, helper scripts), the `project-setup` onboarding skill that existed only to feed them,
and their tests are deleted from this repo. Issue-driven implementation work runs through the
`superpowers` skills (brainstorming → writing-plans → subagent-driven-development →
finishing-a-development-branch) directly in the agent session. Orca stays available ad hoc through
its own `orca-cli`/`orchestration` skills; nothing in this repo wraps it any more.

## Evidence

Measured on this repo and on `~/.local/state/orca-workflows/` logs, 2026-07-22 → 2026-08-22.

- **Maintenance share**: 151 of 216 commits (70%) and 94 of 115 issues (82%) touched the orca
  pipeline. Skill + reference prose reached ~3,300 lines, most of it terminal-plumbing: boot
  quiesce, classifier denial, MCP login prompts, transport stalls, app auto-restart,
  dispatch-verify, heartbeat suppression, alive/stuck/dead wait loops, Run/sidecar files, model
  triple-check, crash-resume branches.
- **Contract negotiation did not converge** (`studio-hevv/selah` issue 85, 12-line issue "add unit
  tests for SubscriptionManager"): 3 proposal/verdict rounds in 49 min, 9 → 8 → 4 rejections, all
  `plan_coverage`, proposal grew 6.5 KB → 17.5 KB (AC 7 → 21) while zero code was written; run was
  abandoned at the round-3 boundary with no outcome logged. Sibling issue 86: 3 contract rounds +
  2 generate attempts + 2 evaluate passes (4 agent-e2e re-spawns) + a merge conflict → PASS after
  ~5.5 h. The epic's remaining children (#87–#90) were never dispatched.
- **Failures were mostly plumbing, not protocol**: `UNMAPPED_BRANCH` from a launch that dropped
  `--model`, agy e2e failing 3 of 4 spawns (project `.mcp.json` not loaded, maestro disconnect,
  simulator contention), 26 `self_recovery resumed_wait` events in the last week alone. Switching
  the protocol to superpowers would have kept every one of these per dispatch.
- **Multi-provider value unproven**: of 1,430 logged dispatches, codex = 62 and agy = 90 (~11%);
  the rest ran on Claude. No log compares codex/agy output quality against Claude-only subagents,
  and Claude Code's Agent tool already selects models per subagent (SDD escalates to a stronger
  model at fix-round ≥ 4).

## Considered Options

- **Thin superpowers wrapper with SDD dispatch over Orca terminals** (keep codex/agy fan-out) —
  removes the contract protocol but keeps the plumbing on every implementer/reviewer dispatch, and
  SDD dispatches more often than the old pipeline did. Estimated 30–40% of the prose and a
  proportional issue inflow survive. Rejected.
- **Superpowers in-session, Orca off the critical path** (optional fail-open second-opinion
  reviewer from another vendor) — viable, but only worth it if cross-vendor review has demonstrated
  value; it has not. Deferred, not chosen.
- **Retire (chosen)** — zero maintenance; what is lost is cross-vendor review, separate rate-limit
  pools, epic-level automation, and Orca UI visibility of workers.

## Consequences

- `~/.agents/skills/orca-*`, `~/.claude/skills/orca-*`, and the `~/.agents/orca-workflows` symlink
  are removed on the machine; `~/.local/state/orca-workflows/` (logs, contracts) is left in place
  as data.
- `lifecycle-gate-policy`'s premerge `E2E_CACHE` opt-in (whose only writer was
  `orca-task-runner`) is removed with it.
- `docs/superpowers/specs|plans/` and ADR 0001 keep their orca history unchanged.
- Open orca issues on `SleepTimeGRT/skills` are closed as `wontfix` pointing here.
- Any future proposal to drive other agent terminals from an LLM session must start from this
  ADR's evidence, not from the deleted skills.
