---
name: lifecycle-gate-policy
description: 'Canonical local development-lifecycle gate policy for solo, agent-driven repositories with no remote-CI enforcement: pre-commit secret scan + autofix, static-only pre-push, full premerge verify+e2e, and agent self-merge with mechanical gate-integrity protection — the local substitute for what remote CI and branch protection would otherwise enforce. Ships canonical .githooks/ and premerge/token-gate templates with a hash-based drift audit so N repos share one answer instead of drifting independently. Use whenever the user asks to review, compare, unify, audit, standardize, or set up a repository''s development gates, git hooks, verify chains, merge or self-merge policy, premerge gates, or worktree conventions — and before hand-editing any .githooks/, token-gate, or premerge file in a repository that follows this convention, since those files are canonical copies managed here. Stops at merge into the default branch; does not cover deploy-time gating. Excludes remote CI cost judgment (remote-ci-economics) and generic agent-facing output compaction (token-efficient-gates) — cross-references their conclusions but ships nothing that requires either to be present.'
---

# Lifecycle Gate Policy

One policy, many repositories. This skill holds the canonical rules, the canonical
file templates, and a drift audit. Repositories carry **copies** of the templates —
never runtime references to this skills repository.

## The policy

Full statement lives in [assets/agents-policy.md](assets/agents-policy.md) (the
template installed into each repo's AGENTS.md). Summary:

| Layer | When | What |
|---|---|---|
| `.githooks/pre-commit` | commit | gitleaks + biome auto-fix on staged files |
| `.githooks/pre-push` | push | `pnpm verify:static` — static checks only, token-gated |
| `scripts/premerge.sh` | right before squash merge | gate-integrity check → migration-safety lint (opt-in) → review requirement → full `pnpm verify` + e2e (if configured) |

Self-merge: the authoring agent may merge its own PR when `premerge.sh` passes
(including `--review-done` after a clean review pass for code changes).
`premerge.sh` exits `PROTECTED` when the PR touches gate-integrity paths
(`.githooks/`, premerge/token-gate scripts, biome config, root package.json
`scripts` — narrowable per repo to specific script keys via
`PROTECTED_SCRIPT_KEYS`, default guards the whole block) — those PRs are merged
by a human. The design rule behind all of this:
a green gate must mean "the code is correct", never "the gate was weakened", so
the gate is never writable by the agent it judges. When something bad ships,
improve verify/e2e/review; do not revoke self-merge.

Why each rule exists (with research provenance): read
[references/policy-rationale.md](references/policy-rationale.md).

## Naming contract (package.json)

- `verify` — full chain minus e2e (lint, typecheck, static lints, unit/integration tests)
- `verify:static` — static subset only: typecheck + lint/format + repo static lints.
  No test execution, no emulators, no network.
- `premerge` — `bash scripts/premerge.sh`
- `prepare` — must contain `git config core.hooksPath .githooks`
- e2e stays under `test:e2e*` and is wired into premerge via `scripts/premerge.conf.sh`.

## Audit a repository

```bash
python3 <skill-dir>/scripts/audit.py --repo <target> [--format json]
```

Read-only. Canonical files are compared by hash: `DRIFT` means the repo copy was
hand-edited — either re-apply the template or, if the edit is an improvement,
upstream it into `assets/` here first, then re-apply everywhere. Config files
(`premerge.conf.sh`, `worktree-links.conf`, `pre-push.conf`) are repo-owned and
only checked for presence.

## Apply to a repository (only on explicit request)

Audit first; apply only when the user asks. One repository per commit. Steps:

1. Copy `assets/githooks/{pre-commit,pre-push,post-checkout}` → `<repo>/.githooks/`,
   `assets/scripts/{premerge.sh,token-gate.sh,premerge.conf.sh,migration-lint.py}` →
   `<repo>/scripts/`. Mark hooks and scripts executable.
2. Write `.githooks/worktree-links.conf` with the repo's actual gitignored
   env/secret paths (inspect the previous post-checkout hook or `.gitignore`).
3. Fill `scripts/premerge.conf.sh`: set `E2E_CMD` if the repo has a merge-blocking
   e2e suite; extend `PROTECTED_EXTRA_REGEX` for repo-specific gate tooling; optionally
   set `PROTECTED_SCRIPT_KEYS` by tracing the repo's actual verify/premerge chain to the
   script keys it calls (leave unset to keep guarding the whole `scripts` block).
   If the repo has SQL migrations, consider setting `MIGRATION_LINT_ENABLED="true"` and
   `MIGRATION_LINT_REGEX` to opt into the destructive-op lint — this is a separate,
   per-repo decision made only on explicit request, not a default part of applying
   this skill.
4. Wire package.json to the naming contract above. Compose `verify:static` from the
   repo's existing static stages; move test stages out of any previous pre-push into
   `verify`/premerge. Keep every previously-gated stage somewhere — compare the
   before/after stage lists explicitly so no verification silently disappears.
5. Remove the legacy hook manager (husky/lefthook/raw `.git/hooks`) and stale
   stamp/gate scripts it referenced. Uninstall its dependency.
6. Insert `assets/agents-policy.md` into the repo's AGENTS.md (keep the marker
   comment), adjusting only repo-specific facts. Fix any docs the audit or diff
   reveals as stale (hooks or workflows they describe that no longer exist).
7. Run `audit.py` — it must exit COMPLIANT. Verify hooks fire: make a scratch
   commit (pre-commit), push a WIP branch (pre-push), run `pnpm premerge` on a
   branch with a trivial change.

## Boundaries

Every sibling-skill mention below is a citation of rationale, not a runtime
dependency: the deployed templates (`.githooks/*`, `premerge.sh`, `token-gate.sh`,
`agents-policy.md`) and `scripts/audit.py` work correctly even if neither sibling
skill is installed.

- **token-efficient-gates** owns agent-facing output economics; its `capture.py` is
  for ad-hoc agent runs, while the `token-gate.sh` template here is the persistent
  in-repo adapter. Keep their design constraints (PASS one-liner, bounded indexes).
- **remote-ci-economics** owns whether remote CI should exist at all; this skill
  only reports workflow presence.
- This skill defines *when* a review pass is required (`--review-done`) for code
  changes; it is agnostic to what fills that signal.
- **superpowers** skills (finishing-a-development-branch, using-git-worktrees) stay
  useful as generic procedure; the AGENTS.md policy template supplies the declared
  preferences (worktree location, merge choice) those skills ask about.
