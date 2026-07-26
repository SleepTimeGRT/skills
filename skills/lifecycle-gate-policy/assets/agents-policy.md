## Harness policy (common across repositories)

### Verification gates — three layers

| Layer | When | What | Nature |
|---|---|---|---|
| `pre-commit` | every commit | gitleaks secret scan + biome auto-fix on staged files | auto-correction |
| `pre-push` | every push | `pnpm verify:static` — typecheck + lint/format check + repo static lints. No tests. | fast block |
| `scripts/premerge.sh` | right before squash merge | full `pnpm verify` + e2e (if configured, skipped when the diff is entirely docs/config-only per `E2E_EXEMPT_REGEX`) + review for code changes | final gate |

`verify:static` must stay static: no test execution, no emulators, no network.
Heavy verification is deliberately absent from hooks — it lives at the merge, where
code actually enters the default branch. `git push --no-verify` is acceptable on WIP
branches only, never for a branch about to merge.

The hook manager is a repository choice. Each repository declares its observable
stage entrypoints and categories in `lifecycle-gate.toml`; the policy checks that
declaration and conformance behavior rather than requiring a particular hook layout.

### Merge policy

- Squash merge only: `gh pr merge --squash --delete-branch`. Never `--merge`/`--rebase`.
- **Issue closure**: if the PR resolves an issue, include a closing keyword
  (`Closes #N` / `Fixes #N` / `Resolves #N`) in the PR body. Right after the
  merge, check the issue's state — if it is still OPEN, close it explicitly:
  `gh issue close <N> --comment "Merged via PR #<PR-number>"`. The fallback is
  required because the closing keyword only auto-closes an issue when the PR's
  base is the repository's default branch; PRs based on anything else (e.g. an
  epic integration branch) never trigger it.
- **Self-merge**: the agent that authored a PR may merge it itself when
  `scripts/premerge.sh` exits PASS. For code changes this includes a clean
  review pass, then `premerge.sh --review-done`.
- Merge one PR at a time. If `origin/main` moved after PASS, re-run premerge.
- **Escalate to a human merge** (no self-merge) when: premerge reports PROTECTED
  (gate-integrity paths changed — hooks, premerge/token-gate scripts, biome config,
  root package.json scripts), verify/e2e fails and the fix is non-obvious, the PR is
  not mergeable-clean, or the change touches schema/migrations (unless this repo has
  a migration-safety gate configured — `MIGRATION_LINT_ENABLED=true` in
  `scripts/premerge.conf.sh` — in which case `premerge.sh` already hard-blocks
  self-merge automatically when the lint flags something, so no separate check is
  needed; repos without the gate configured keep escalating unconditionally) or
  deploy configuration.
- Rationale: green must mean "the code is correct", never "the gate was weakened".
  When a bad change slips through, improve verify/e2e/review — do not revoke self-merge.

### Branches, commits, worktrees

- Branch naming: `<type>/issue-<num>-<slug>` (e.g. `feat/issue-42-jackpot-cap`).
- Commits: Conventional Commits, issue reference in scope or suffix (`feat(#42): …`).
- Attribution: human interactive commits as the user; agent commits carry
  `Co-Authored-By:` naming the actual model; autonomous-loop commits identify
  themselves as autonomous.
- Worktrees live outside the repo at `~/worktrees/<repo>/issue-<num>-<slug>/`
  (not dot-prefixed, so editor/tool trustedWorkspace prompts pick it up like any
  normal project directory; also prevents the parent repo's lint/tsc configs from
  descending into them).
  `post-checkout` symlinks gitignored env/secrets per `.githooks/worktree-links.conf`.
