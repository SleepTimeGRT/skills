#!/usr/bin/env bash
# lifecycle-gate-policy reference implementation — copying is optional; a repository
# may implement the same policy any way it likes and declare it in lifecycle-gate.toml.
#
# The merge gate. Run from the PR branch's worktree before `gh pr merge --squash`.
# Self-merge policy: an agent may merge its own PR only when this script prints PASS.
# Merge one PR at a time; if origin/<default> moves after PASS, re-run.
#
# Exit codes:
#   0  PASS — merge allowed
#   2  precondition failed (dirty tree / behind default branch / empty diff)
#   3  PROTECTED — diff touches gate-integrity paths; a human must merge this PR
#   4  REVIEW — code changes present and --review-done not given; run your
#      review process first, then re-run with --review-done
#   5  MIGRATION_ESCALATE — destructive-op lint flagged a migration change;
#      a human must review and merge this PR (opt-in via MIGRATION_LINT_ENABLED)
#   *  verify/e2e/secret-scan failure (their exit codes pass through)
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
. "$REPO_ROOT/scripts/token-gate.sh"

# ---- repo config (scripts/premerge.conf.sh overrides these defaults) --------
VERIFY_CMD="pnpm verify"
E2E_CMD="" # e.g. "pnpm test:e2e:ci"; empty = repo has no merge-blocking e2e
REVIEW_EXEMPT_REGEX='(^|/)docs/|\.(md|mdx|txt)$'
E2E_EXEMPT_REGEX="" # empty = no exemption, e2e always runs when E2E_CMD is set
PROTECTED_EXTRA_REGEX="" # repo-specific additions to the protected set
PROTECTED_SCRIPT_KEYS="" # space-separated package.json script keys to guard; empty = guard the whole scripts block
MIGRATION_LINT_ENABLED="false" # opt-in destructive-op lint for schema/migration files
MIGRATION_LINT_REGEX="" # e.g. '^supabase/migrations/.*\.sql$' — required when MIGRATION_LINT_ENABLED=true
E2E_CACHE_ENABLED="false" # opt-in: skip $E2E_CMD when orca-task-runner already cached a PASS for this exact commit
CONF="$REPO_ROOT/scripts/premerge.conf.sh"
[ -f "$CONF" ] && . "$CONF"

REVIEW_DONE=0
for arg in "$@"; do
  case "$arg" in
    --review-done) REVIEW_DONE=1 ;;
    *)
      printf 'premerge: unknown argument %s\n' "$arg" >&2
      exit 64
      ;;
  esac
done

# ---- 1. preconditions --------------------------------------------------------
# Verify must run against exactly the committed state that will be merged.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  printf '[premerge] FAIL — uncommitted tracked changes; commit or stash first\n' >&2
  exit 2
fi

DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=main
git fetch --quiet origin "$DEFAULT_BRANCH"

# Green against a stale main is not green: two branches can each pass alone and
# fail combined. Require the branch to already contain origin/<default>.
if ! git merge-base --is-ancestor "origin/$DEFAULT_BRANCH" HEAD; then
  printf '[premerge] FAIL — branch is behind origin/%s; merge or rebase it in, then re-run\n' "$DEFAULT_BRANCH" >&2
  exit 2
fi

CHANGED=$(git diff --name-only "origin/$DEFAULT_BRANCH..HEAD")
if [ -z "$CHANGED" ]; then
  printf '[premerge] FAIL — no changes vs origin/%s; nothing to merge\n' "$DEFAULT_BRANCH" >&2
  exit 2
fi

# ---- 2. independent secret rescan --------------------------------------------
# Unconditional, like pre-commit's own gitleaks call (assets/githooks/pre-commit) — this stage
# must run before gate integrity/review below so a synthetic-secret-only commit is never
# misattributed to the review gate. Scans the full commit range (not a single staged diff), so a
# commit that bypassed pre-commit (git commit --no-verify) is still caught here.
if ! command -v gitleaks &>/dev/null; then
  printf '[premerge] FAIL — gitleaks not found — install: brew install gitleaks\n' >&2
  exit 1
fi
token_gate_capture premerge:secret-scan -- gitleaks detect --source . \
  --log-opts "origin/$DEFAULT_BRANCH..HEAD" --no-banner --redact

# ---- 3. gate integrity --------------------------------------------------------
# The gate an agent is judged by must not be editable by that agent in the same PR
# (a green result must mean "code is correct", never "gate was weakened").
PROTECTED_REGEX='^\.githooks/|^scripts/(premerge\.sh|premerge\.conf\.sh|token-gate\.sh|migration-lint\.py)$|^biome\.json$|^\.gitleaks\.toml$'
PROTECTED_HITS=$(printf '%s\n' "$CHANGED" | grep -E "$PROTECTED_REGEX" || true)
if [ -n "$PROTECTED_EXTRA_REGEX" ]; then
  EXTRA_HITS=$(printf '%s\n' "$CHANGED" | grep -E "$PROTECTED_EXTRA_REGEX" || true)
  PROTECTED_HITS=$(printf '%s\n%s\n' "$PROTECTED_HITS" "$EXTRA_HITS" | sed '/^$/d' | sort -u)
fi

# The root package.json "scripts" block defines the verify chain itself. By default the
# whole block is guarded (all-or-nothing). A repo can narrow this to only the script keys
# its own gate chain actually calls via PROTECTED_SCRIPT_KEYS (see premerge.conf.sh) — e.g.
# adding an unrelated e2e project entry no longer trips PROTECTED, but touching a guarded
# key still does. Guarding a synthesized key (e.g. "verify:static") only catches changes to
# that key's own value, not the leaf keys it calls into — list the leaves too.
if printf '%s\n' "$CHANGED" | grep -qx 'package.json'; then
  if [ -n "$PROTECTED_SCRIPT_KEYS" ]; then
    OLD_SCRIPTS=$(git show "origin/$DEFAULT_BRANCH:package.json" |
      PROTECTED_SCRIPT_KEYS="$PROTECTED_SCRIPT_KEYS" node -e '
        let d="";
        process.stdin.on("data",c=>d+=c).on("end",()=>{
          const scripts = JSON.parse(d).scripts || {};
          const keys = process.env.PROTECTED_SCRIPT_KEYS.split(/\s+/).filter(Boolean).sort();
          const picked = {};
          for (const k of keys) picked[k] = scripts[k];
          console.log(JSON.stringify(picked));
        })')
    NEW_SCRIPTS=$(PROTECTED_SCRIPT_KEYS="$PROTECTED_SCRIPT_KEYS" node -e '
      const scripts = require("./package.json").scripts || {};
      const keys = process.env.PROTECTED_SCRIPT_KEYS.split(/\s+/).filter(Boolean).sort();
      const picked = {};
      for (const k of keys) picked[k] = scripts[k];
      console.log(JSON.stringify(picked));')
  else
    OLD_SCRIPTS=$(git show "origin/$DEFAULT_BRANCH:package.json" |
      node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>console.log(JSON.stringify(JSON.parse(d).scripts||{})))')
    NEW_SCRIPTS=$(node -e 'console.log(JSON.stringify(require("./package.json").scripts||{}))')
  fi
  if [ "$OLD_SCRIPTS" != "$NEW_SCRIPTS" ]; then
    PROTECTED_HITS=$(printf '%s\npackage.json (scripts block)\n' "$PROTECTED_HITS" | sed '/^$/d')
  fi
fi

if [ -n "$PROTECTED_HITS" ]; then
  printf '[premerge] PROTECTED — this PR changes gate-integrity paths:\n'
  printf '%s\n' "$PROTECTED_HITS" | sed 's/^/[premerge]   /'
  printf '[premerge] self-merge is not allowed for gate changes; escalate — a human merges this PR\n'
  exit 3
fi

# ---- 4. migration safety (opt-in) --------------------------------------------
# Deterministic destructive-op scan for schema/migration files. Disabled by
# default; a repo opts in via scripts/premerge.conf.sh. When enabled and the
# lint flags something, this hard-blocks self-merge with no override — a
# contract-aware alternative exists in orca-evaluate's separate merge path,
# which does not go through this script.
if [ "$MIGRATION_LINT_ENABLED" = "true" ]; then
  if [ -z "$MIGRATION_LINT_REGEX" ]; then
    printf '[premerge] FAIL — MIGRATION_LINT_ENABLED=true but MIGRATION_LINT_REGEX unset in premerge.conf.sh\n' >&2
    exit 2
  fi
  MIGRATION_FILES=$(printf '%s\n' "$CHANGED" | grep -E "$MIGRATION_LINT_REGEX" || true)
  if [ -n "$MIGRATION_FILES" ]; then
    if ! LINT_OUT=$(printf '%s\n' "$MIGRATION_FILES" | xargs python3 scripts/migration-lint.py 2>&1); then
      printf '[premerge] MIGRATION_ESCALATE — destructive-op lint flagged a migration change:\n' >&2
      printf '%s\n' "$LINT_OUT" | sed 's/^/[premerge]   /' >&2
      printf '[premerge] self-merge is not allowed — a human must review and merge this PR\n' >&2
      exit 5
    fi
  fi
fi

# ---- 5. review requirement ----------------------------------------------------
CODE_CHANGES=$(printf '%s\n' "$CHANGED" | grep -Ev "$REVIEW_EXEMPT_REGEX" || true)
if [ -n "$CODE_CHANGES" ] && [ "$REVIEW_DONE" -ne 1 ]; then
  CODE_COUNT=$(printf '%s\n' "$CODE_CHANGES" | wc -l | tr -d ' ')
  printf '[premerge] REVIEW required — %s code file(s) changed\n' "$CODE_COUNT"
  printf '[premerge] resolve blocking findings from your review process,\n'
  printf '[premerge] then re-run: scripts/premerge.sh --review-done\n'
  exit 4
fi

# ---- 6. full verification -------------------------------------------------------
# *_CMD strings run through `bash -c` so quoting inside them behaves like a shell line.
token_gate_capture premerge:verify -- bash -c "$VERIFY_CMD"

E2E_NOTE=""
if [ -n "$E2E_CMD" ]; then
  # Skip only when EVERY changed path matches E2E_EXEMPT_REGEX (unset = never skip,
  # matching prior behavior). A diff that is entirely docs/config-only cannot change
  # e2e's outcome; anything else runs the suite as before. Widening this regex itself
  # requires a human merge — scripts/premerge.conf.sh is inside PROTECTED_REGEX (step 2),
  # so an agent cannot both loosen the exemption and benefit from it in the same PR.
  E2E_NON_EXEMPT=""
  if [ -n "$E2E_EXEMPT_REGEX" ]; then
    E2E_NON_EXEMPT=$(printf '%s\n' "$CHANGED" | grep -Ev "$E2E_EXEMPT_REGEX" || true)
  else
    E2E_NON_EXEMPT=$CHANGED
  fi
  if [ -z "$E2E_NON_EXEMPT" ]; then
    printf '[premerge] SKIP e2e — all changed paths match E2E_EXEMPT_REGEX\n'
    E2E_NOTE=" (e2e skipped — E2E_EXEMPT_REGEX)"
  else
    # Opt-in cache check: orca-task-runner (see skills/orca-task-runner/SKILL.md §6) may have
    # already run this exact $E2E_CMD against this exact commit and cached a PASS. This block
    # only *reads* that cache — it never writes to it, so a generic (non-orca) repo that turns
    # this on simply never gets a hit and always falls through to running e2e below.
    E2E_CACHE_HIT=0
    if [ "$E2E_CACHE_ENABLED" = "true" ]; then
      CACHE_REPO_ID=$(git remote get-url origin 2>/dev/null || git rev-parse --show-toplevel)
      CACHE_REPO_HASH=$(node -e 'console.log(require("crypto").createHash("sha256").update(process.argv[1]).digest("hex").slice(0,16))' "$CACHE_REPO_ID")
      CACHE_FILE="$HOME/.local/state/orca-workflows/e2e-cache/$CACHE_REPO_HASH/$(git rev-parse HEAD).json"
      if [ -f "$CACHE_FILE" ]; then
        CACHE_MATCH=$(E2E_CMD="$E2E_CMD" python3 -c '
import json, os, sys
try:
    with open(sys.argv[1]) as f:
        rec = json.load(f)
except Exception:
    print("0"); sys.exit()
print("1" if rec.get("e2e_cmd") == os.environ["E2E_CMD"] and rec.get("result") == "PASS" else "0")
' "$CACHE_FILE" 2>/dev/null || echo 0)
        [ "$CACHE_MATCH" = "1" ] && E2E_CACHE_HIT=1
      fi
    fi
    if [ "$E2E_CACHE_HIT" = "1" ]; then
      printf '[premerge] SKIP e2e — cached PASS for this exact commit (orca-task-runner §6)\n'
      E2E_NOTE=" (e2e skipped — cache hit)"
    else
      token_gate_capture premerge:e2e -- bash -c "$E2E_CMD"
      E2E_NOTE=" (e2e ran)"
    fi
  fi
fi

printf '[premerge] PASS — self-merge allowed%s (squash only, one PR at a time; re-run if origin/%s moves)\n' "$E2E_NOTE" "$DEFAULT_BRANCH"
