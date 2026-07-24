<!-- lifecycle-gate-policy: policy v1 — keep this marker line; the drift audit checks for it. -->
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

### Merge policy

- Squash merge only: `gh pr merge --squash --delete-branch`. Never `--merge`/`--rebase`.
- **Self-merge**: the agent that authored a PR may merge it itself when
  `scripts/premerge.sh` exits PASS. For code changes this includes a clean
  review pass, then `premerge.sh --review-done`.
- Merge one PR at a time. If `origin/main` moved after PASS, re-run premerge.
- **Escalate to a human merge** (no self-merge) when: premerge reports PROTECTED
  (gate-integrity paths changed — hooks, premerge/token-gate scripts, biome config,
  root package.json scripts), verify/e2e fails and the fix is non-obvious, the PR is
  not mergeable-clean, or the change touches schema/migrations/deploy configuration.
- Rationale: green must mean "the code is correct", never "the gate was weakened".
  When a bad change slips through, improve verify/e2e/review — do not revoke self-merge.

### Branches, commits, worktrees

- Branch naming: `<type>/issue-<num>-<slug>` (e.g. `feat/issue-42-jackpot-cap`).
- Commits: Conventional Commits, issue reference in scope or suffix (`feat(#42): …`).
- Attribution: human interactive commits as the user; agent commits carry
  `Co-Authored-By:` naming the actual model; autonomous-loop commits identify
  themselves as autonomous.
- Worktrees live outside the repo at `~/.worktrees/<repo>/issue-<num>-<slug>/`
  (prevents the parent repo's lint/tsc configs from descending into them).
  `post-checkout` symlinks gitignored env/secrets per `.githooks/worktree-links.conf`.
