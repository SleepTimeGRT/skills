---
name: lifecycle-gate-policy
description: 'Local development-lifecycle gate policy for solo, agent-driven repositories with no remote-CI enforcement: stage-level policy specification, lifecycle-gate.toml manifest, and mechanism-agnostic conformance fixtures for pre-commit secret scan + autofix, static-only pre-push, full premerge verify+e2e, and agent self-merge with mechanical gate-integrity protection. Hook-manager choice and implementation are repository decisions; bundled .githooks/ and premerge/token-gate scripts are optional reference implementations. Use whenever the user asks to review, compare, unify, audit, standardize, or set up a repository''s development gates, git hooks, verify chains, merge or self-merge policy, premerge gates, or worktree conventions — and before changing an implementation declared in lifecycle-gate.toml. Stops at merge into the default branch; does not cover deploy-time gating. Excludes remote CI cost judgment (remote-ci-economics) and generic agent-facing output compaction (token-efficient-gates) — cross-references their conclusions but ships nothing that requires either to be present.'
---

# Lifecycle Gate Policy

One policy, many repositories. This skill owns the stage-level policy specification,
the `lifecycle-gate.toml` manifest contract, and mechanism-agnostic conformance
fixtures. Bundled hooks and scripts are optional reference implementations; each
repository chooses its hook manager and implementation without a runtime dependency
on this skills repository.

## The policy

Full statement lives in [assets/agents-policy.md](assets/agents-policy.md) (the
template installed into each repo's AGENTS.md). Summary:

| Layer | When | What |
|---|---|---|
| `.githooks/pre-commit` | commit | gitleaks + biome auto-fix on staged files |
| `.githooks/pre-push` | push | `pnpm verify:static` — static checks only, token-gated |
| `scripts/premerge.sh` | before squash merge | sync check → gate-integrity check → migration-safety lint (opt-in) → review requirement → full `pnpm verify` → e2e (skippable via `E2E_EXEMPT_REGEX` when every changed path is docs/config-only) |

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

## Reference implementation conventions

The bundled scripts conventionally use `verify`, `verify:static`, `premerge`, and
`prepare`; a repository may instead choose its own command names and hook manager.
Declare the observable stage entrypoints and categories in `lifecycle-gate.toml` so
the audit can check policy conformance without inspecting implementation bytes.

## Audit a repository

```bash
python3 <skill-dir>/scripts/audit.py --repo <path> [--skip-fixtures] [--format text|json]
```

Read-only. The report checks whether manifest categories satisfy the policy and
whether enabled conformance fixtures observed the declared stages. The audit
compares behavior and declared categories, not script bytes, so a
repository-local implementation can conform. Premerge has no fixture and is
reported as `NOT-EXERCISED`.

The verdict is fail-closed — absence of evidence is never compliance:

| Verdict | Exit | Meaning |
|---|---|---|
| `COMPLIANT` | 0 | a fixture observed the policy holding, and nothing behavioral was inconclusive |
| `STRUCTURE-ONLY` | 0 | `--skip-fixtures`: the declaration was checked, no stage was observed |
| `UNVERIFIED` | 3 | nothing failed, but a fixture skipped or warned, or none ran |
| `NON-COMPLIANT` | 1 | a check failed outright (`FAIL` / `MISSING`) |

A skipped fixture, an unimplemented fixture name, a bootstrap entrypoint that
does not run, and a manifest declaring no fixtures all keep a repository out of
`COMPLIANT`. Treat exit 3 as "not yet shown to work", not as "fine".

Read [references/policy-spec.md](references/policy-spec.md) for required stages and
categories, [references/manifest-schema.md](references/manifest-schema.md) for the
manifest fields, and [assets/lifecycle-gate.toml.example](assets/lifecycle-gate.toml.example)
for an opt-in starting point.

## Apply to a repository (only on explicit request)

Audit first; apply only when the user asks. One repository per commit. Steps:

1. Create `lifecycle-gate.toml` with the repository's stage entrypoints and policy
   categories. Choose and configure any hook manager that makes those entrypoints
   observable to the conformance fixtures.
2. Optionally copy and adapt `assets/githooks/{pre-commit,pre-push,post-checkout}`
   and `assets/scripts/{premerge.sh,token-gate.sh,premerge.conf.sh,migration-lint.py}`
   as a reference implementation. If using its worktree helper, write
   `.githooks/worktree-links.conf` with the repo's actual gitignored env/secret paths.
3. If using the reference premerge implementation, fill `scripts/premerge.conf.sh`:
   set `E2E_CMD` if the repo has a merge-blocking
   e2e suite; extend `PROTECTED_EXTRA_REGEX` for repo-specific gate tooling; optionally
   set `PROTECTED_SCRIPT_KEYS` by tracing the repo's actual verify/premerge chain to the
   script keys it calls (leave unset to keep guarding the whole `scripts` block); optionally
   set `E2E_EXEMPT_REGEX` to skip `$E2E_CMD` when a diff is entirely docs/config-only —
   independent of `REVIEW_EXEMPT_REGEX`, so a path exempt from e2e may still need
   `--review-done` unless the repo also covers it there.
   If the repo has SQL migrations, consider setting `MIGRATION_LINT_ENABLED="true"` and
   `MIGRATION_LINT_REGEX` to opt into the destructive-op lint — this is a separate,
   per-repo decision made only on explicit request, not a default part of applying
   this skill. Enabling this replaces the unconditional human-escalation for
   schema/migration changes with lint+review-based self-merge, and only provides real
   destructive-op protection if migrations are raw SQL.
4. Keep every previously-gated stage somewhere — compare the before/after stage
   lists explicitly so no verification silently disappears.
5. Insert or adapt `assets/agents-policy.md` in the repo's AGENTS.md, adjusting
   only repo-specific facts. Fix any docs the audit or diff
   reveals as stale (hooks or workflows they describe that no longer exist).
6. Run `audit.py` — it must reach `COMPLIANT`, which requires fixtures that
   actually observed the stages. `UNVERIFIED` (exit 3) means the manifest is
   declared but unproven: read which fixture skipped and fix that, rather than
   accepting the declaration. Then confirm by hand: make a scratch commit
   (pre-commit), push a WIP branch (pre-push), run premerge on a branch with a
   trivial change.

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
