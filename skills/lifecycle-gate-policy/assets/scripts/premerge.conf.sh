# lifecycle-gate-policy reference implementation config (edit freely) — sourced by
# scripts/premerge.sh. Copying is optional; a repository may implement the same policy
# any way it likes and declare it in lifecycle-gate.toml.
# Uncomment and adjust for this repository. Deleting this file falls back to defaults.

# Full verification command (default: "pnpm verify").
#VERIFY_CMD="pnpm verify"

# Merge-blocking e2e command; leave empty if this repo has no e2e gate.
#E2E_CMD="pnpm test:e2e:ci"

# Files matching this regex do not require review (docs-only PRs).
#REVIEW_EXEMPT_REGEX='(^|/)docs/|\.(md|mdx|txt)$'

# When every changed path matches this regex, premerge.sh skips $E2E_CMD (verify still
# runs). Independent of REVIEW_EXEMPT_REGEX by design — a diff can be e2e-exempt without
# being review-exempt, or vice versa. Share the same pattern between the two only if this
# repo wants both skipped together; a repo that only sets this one still needs
# --review-done for non-REVIEW_EXEMPT_REGEX paths (e.g. a bare .gitignore change is not
# docs by default, so it still hits the review gate even once it skips e2e here).
# This regex cannot weaken gate-integrity protection: this file is itself inside
# PROTECTED_REGEX, so widening the pattern requires a human merge before it takes effect.
#E2E_EXEMPT_REGEX='^\.gitignore$|(^|/)docs/|\.(md|mdx|txt)$'

# Repo-specific additions to the gate-integrity protected set.
#PROTECTED_EXTRA_REGEX='^tools/spec-trace\.mjs$'

# Narrow the package.json "scripts" gate-integrity check to only these keys (space-
# separated) instead of the whole scripts block. Trace the actual verify/premerge chain
# to derive the list — a synthesized key like "verify:static" only guards its own value,
# not the leaf keys it calls, so list leaves too. Leave unset/empty to keep guarding the
# entire scripts block (safe default; matches pre-PROTECTED_SCRIPT_KEYS behavior).
#PROTECTED_SCRIPT_KEYS="verify verify:guides check-types premerge prepare e2e"

# Destructive-op lint (opt-in). Enable and set a regex matching this repo's
# migration file paths; the lint hard-blocks self-merge when it flags a
# destructive operation (DROP TABLE/COLUMN, TRUNCATE, DELETE without WHERE,
# RENAME, ALTER COLUMN TYPE) with no override in this script.
#
# WARNING: Enabling this REPLACES the unconditional human-escalation for
# schema/migration changes (per agents-policy.md) with lint+review-based self-merge.
# The lint is raw-SQL-only: enabling it for non-SQL migrations (Prisma, Django, etc.)
# provides no destructive-op protection while still allowing self-merge.
#MIGRATION_LINT_ENABLED="true"
#MIGRATION_LINT_REGEX='^supabase/migrations/.*\.sql$'

# Skip $E2E_CMD when orca-task-runner (skills/orca-task-runner/SKILL.md §6) already ran
# this exact command against this exact HEAD commit and cached a PASS. The cache is keyed
# by repo + commit SHA and the record's e2e_cmd is compared against this file's $E2E_CMD —
# any mismatch (different command, different commit, no record) is a cache miss and e2e
# runs normally, so nothing here can silently skip a check that wasn't actually run.
# Read-only from premerge.sh's side: only orca-task-runner writes cache entries. Only
# useful in repos whose PRs are driven through orca-task-runner — otherwise the cache
# simply never has entries and this knob is a no-op even when enabled.
# This file is itself inside PROTECTED_REGEX, so an agent cannot enable this and benefit
# from it within the same PR.
#E2E_CACHE_ENABLED="true"
