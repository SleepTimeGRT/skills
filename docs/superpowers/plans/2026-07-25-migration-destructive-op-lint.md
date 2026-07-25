# Migration Destructive-Op Lint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, dependency-free destructive-op lint gate (`scripts/migration-lint.py`) to the `lifecycle-gate-policy` canonical assets, wire it into `premerge.sh` (hard block) and `orca-evaluate` (contract-aware ESCALATE), and update the canonical self-merge policy wording accordingly.

**Architecture:** One new canonical Python script scans SQL migration files against a destructive-op deny-list and reports JSON. Two independent consumers: `premerge.sh` (generic self-merge path — hard-blocks unconditionally on any flag) and `orca-evaluate` §3/§4 (`orca-workflow` path — compares flags against a new declared-intent field in `orca-task-runner`'s §1 proposal, ESCALATEs only on undeclared flags). `audit.py` gains the new script as a canonical hash-checked file. No new runtime dependencies anywhere.

**Tech Stack:** Bash (`premerge.sh`), Python 3 stdlib-only (`migration-lint.py`, matching `audit.py`'s style), Markdown/YAML (`SKILL.md`, `agents-policy.md`), `unittest`/`pytest` (tests, following the existing `GitFixture` dynamic-fixture pattern — no static fixture files).

**Source spec:** `docs/superpowers/specs/2026-07-25-migration-destructive-op-lint-design.md` (Approved).

## Global Constraints

- Scope is this canonical repo (`sleeptimegrt-skills`) only. No file in `medicount`, `sidework-dashboard`, or `pokeplant` is touched by this plan — per-repo opt-in application is separate, future work requested explicitly, one repo per commit (spec Non-goals).
- `scripts/migration-lint.py` is Python 3, standard library only — no third-party dependencies (matches `audit.py`'s existing constraint; spec "정적분석기 대신 deny-list").
- Config variable names are fixed: `MIGRATION_LINT_ENABLED` (default `"false"`), `MIGRATION_LINT_REGEX` (default `""`, required — hard error if enabled without it). Path-matching config in `premerge.conf.sh` is always a regex, never a glob (matches `REVIEW_EXEMPT_REGEX`/`PROTECTED_EXTRA_REGEX` convention).
- New `premerge.sh` exit code `5` = `MIGRATION_ESCALATE`. When the lint flags something in this path, it is an unconditional hard block — no override flag (spec section B: no contract mechanism exists in the generic path).
- `PROTECTED_REGEX` in `premerge.sh` must include `scripts/migration-lint.py` so an agent cannot silently weaken this gate in the same PR it's judged by (matches the existing gate-integrity design rule).
- Confirmed and must not be re-litigated: `orca-workflow`'s PASS path calls `gh pr merge` directly and never invokes `scripts/premerge.sh` (`skills/orca-workflow/SKILL.md` §2d). The two enforcement paths built in this plan are genuinely independent — do not add cross-calls between them.
- Tests use the repo's existing dynamic-fixture convention (`GitFixture`: `tempfile.TemporaryDirectory` + `git init` + `self.write(relative, content)`), not static files under `tests/fixtures/`. Reuse this pattern for all new tests.
- Baseline: `uv run --with pytest pytest tests/ -q` currently passes **58/58**. It must stay green after every task; each task's expected count is stated in its steps.
- Commits: Conventional Commits referencing the issue, e.g. `feat(#9): ...` / `docs(#9): ...` (this repo's branch/commit convention). Work happens directly on the current branch/worktree (`SleepTimeGRT/issue-9-db-migration-destructive`) — no new worktree needed, it already exists.
- Do not run any actual database migration, deploy, or seed command anywhere in this plan — all verification is against in-memory/tempdir SQL text fixtures, never a real database.

---

### Task 1: `scripts/migration-lint.py` — destructive-op deny-list scanner

**Files:**
- Create: `skills/lifecycle-gate-policy/assets/scripts/migration-lint.py`
- Modify: `tests/test_lifecycle_gate_policy.py` (add `import sys`, add `MIGRATION_LINT` path constant, add `MigrationLintTests` class)

**Interfaces:**
- Produces: CLI contract consumed by Task 2 (`premerge.sh`) and by `orca-evaluate` (design spec §E, doc-only in this plan): `python3 migration-lint.py <file> [<file> ...]` → stdout JSON `{"clean": bool, "flags": [{"file": str, "line": int, "rule": str, "snippet": str}, ...]}`, exit code `0` (clean) or `1` (flags present). Rule names produced: `drop-table`, `drop-column`, `alter-column-type`, `truncate`, `rename`, `delete-without-where`.

- [ ] **Step 1: Write the failing tests**

Add near the top of `tests/test_lifecycle_gate_policy.py`, alongside the existing `RUNNER` constant:

```python
import sys
```

(add to the existing `import` block, keeping alphabetical grouping with the other stdlib imports)

```python
MIGRATION_LINT = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "scripts" / "migration-lint.py"
```

Then append this new class at the end of the file, before the `if __name__ == "__main__":` block:

```python
class MigrationLintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="migration lint ")
        self.dir = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_sql(self, name: str, content: str) -> Path:
        path = self.dir / name
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def lint(self, *paths: Path) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(MIGRATION_LINT), *[str(p) for p in paths]],
            capture_output=True,
            text=True,
        )
        return result.returncode, json.loads(result.stdout)

    def test_flags_drop_table(self) -> None:
        path = self.write_sql("0001.sql", "DROP TABLE users;\n")
        code, report = self.lint(path)
        self.assertEqual(code, 1)
        self.assertFalse(report["clean"])
        self.assertEqual(report["flags"][0]["rule"], "drop-table")
        self.assertEqual(report["flags"][0]["line"], 1)

    def test_flags_drop_column(self) -> None:
        path = self.write_sql("0002.sql", "ALTER TABLE users DROP COLUMN email;\n")
        code, report = self.lint(path)
        self.assertEqual(code, 1)
        self.assertEqual({f["rule"] for f in report["flags"]}, {"drop-column"})

    def test_flags_alter_column_type(self) -> None:
        path = self.write_sql("0003.sql", "ALTER TABLE items ALTER COLUMN price TYPE integer;\n")
        code, report = self.lint(path)
        self.assertEqual(code, 1)
        self.assertIn("alter-column-type", {f["rule"] for f in report["flags"]})

    def test_flags_truncate(self) -> None:
        path = self.write_sql("0004.sql", "TRUNCATE orders;\n")
        code, report = self.lint(path)
        self.assertEqual(code, 1)
        self.assertEqual(report["flags"][0]["rule"], "truncate")

    def test_flags_rename(self) -> None:
        path = self.write_sql("0005.sql", "ALTER TABLE accounts RENAME TO users;\n")
        code, report = self.lint(path)
        self.assertEqual(code, 1)
        self.assertEqual(report["flags"][0]["rule"], "rename")

    def test_flags_delete_without_where_multiline(self) -> None:
        path = self.write_sql(
            "0006.sql",
            """
            DELETE FROM
              sessions;
            """,
        )
        code, report = self.lint(path)
        self.assertEqual(code, 1)
        self.assertEqual(report["flags"][0]["rule"], "delete-without-where")
        self.assertEqual(report["flags"][0]["line"], 1)

    def test_clean_migration_passes(self) -> None:
        path = self.write_sql(
            "0007.sql",
            """
            CREATE TABLE widgets (id serial primary key);
            DELETE FROM sessions
            WHERE created_at < now() - interval '30 days';
            """,
        )
        code, report = self.lint(path)
        self.assertEqual(code, 0)
        self.assertTrue(report["clean"])
        self.assertEqual(report["flags"], [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k MigrationLintTests -v`
Expected: 7 errors/failures — `migration-lint.py` does not exist yet (`FileNotFoundError` or non-zero unexpected exit from `subprocess.run`, surfaced as a test failure when `json.loads` gets empty stdout).

- [ ] **Step 3: Write the implementation**

Create `skills/lifecycle-gate-policy/assets/scripts/migration-lint.py`:

```python
#!/usr/bin/env python3
"""lifecycle-gate-policy: canonical scripts/migration-lint.py v1 — do not
hand-edit in the target repository; change the copy in sleeptimegrt-skills
and re-apply.

Deterministic destructive-op deny-list scan for SQL migration files. Tuned
for recall, not precision: narrowing vs widening ALTER COLUMN TYPE is not
distinguished (both flag), and statement splitting on ';' does not account
for semicolons inside string literals or comments. A flag routes the change
to an intent check (human review, or orca-evaluate contract comparison) — it
never blocks by itself beyond that, so over-flagging is the accepted
trade-off against under-flagging a real destructive operation.

Usage:
    python3 migration-lint.py <file> [<file> ...]

Exit code 0 = clean (no flags), 1 = one or more flags found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("drop-table", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)),
    ("drop-column", re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)),
    (
        "alter-column-type",
        re.compile(r"\bALTER\s+COLUMN\b.{0,80}?\b(SET\s+DATA\s+)?TYPE\b", re.IGNORECASE | re.DOTALL),
    ),
    ("truncate", re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
    (
        "rename",
        re.compile(
            r"\bRENAME\s+(TABLE|COLUMN)\b|\bALTER\s+TABLE\b.{0,80}?\bRENAME\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
]

DELETE_FROM = re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)
WHERE = re.compile(r"\bWHERE\b", re.IGNORECASE)


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def snippet_of(text: str, start: int, end: int) -> str:
    return text[start:end].split("\n")[0].strip()[:120]


def statements(text: str) -> list[tuple[str, int]]:
    """Split into (statement_text, start_offset) pairs on ';'. Best-effort —
    does not account for ';' inside string literals or comments."""
    result = []
    start = 0
    for m in re.finditer(";", text):
        result.append((text[start : m.start()], start))
        start = m.end()
    if start < len(text):
        result.append((text[start:], start))
    return result


def scan(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        text = f.read()

    flags = []
    for rule, pattern in RULES:
        for m in pattern.finditer(text):
            flags.append(
                {
                    "file": path,
                    "line": line_of(text, m.start()),
                    "rule": rule,
                    "snippet": snippet_of(text, m.start(), m.end()),
                }
            )

    for statement, offset in statements(text):
        m = DELETE_FROM.search(statement)
        if m and not WHERE.search(statement):
            flags.append(
                {
                    "file": path,
                    "line": line_of(text, offset + m.start()),
                    "rule": "delete-without-where",
                    "snippet": statement.strip().split("\n")[0][:120],
                }
            )

    return flags


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="migration files to scan")
    args = parser.parse_args()

    all_flags: list[dict] = []
    for path in args.files:
        all_flags.extend(scan(path))

    print(json.dumps({"clean": not all_flags, "flags": all_flags}, indent=2))
    return 0 if not all_flags else 1


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```bash
chmod +x skills/lifecycle-gate-policy/assets/scripts/migration-lint.py
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k MigrationLintTests -v`
Expected: 7 passed.

Run the full suite to confirm no regression: `uv run --with pytest pytest tests/ -q`
Expected: 65 passed (58 baseline + 7 new).

- [ ] **Step 5: Commit**

```bash
git add skills/lifecycle-gate-policy/assets/scripts/migration-lint.py tests/test_lifecycle_gate_policy.py
git commit -m "feat(#9): add migration-lint.py destructive-op deny-list scanner"
```

---

### Task 2: `premerge.sh` integration — hard-block migration-safety stage

**Files:**
- Modify: `skills/lifecycle-gate-policy/assets/scripts/premerge.sh`
- Modify: `tests/test_lifecycle_gate_policy.py` (add `PREMERGE` constant, add `PremergeFixture` + `MigrationLintPremergeTests` classes)

**Interfaces:**
- Consumes: `python3 scripts/migration-lint.py <files>` CLI contract from Task 1 (exit 0/1, JSON on stdout).
- Produces: new `premerge.sh` exit code `5` (`MIGRATION_ESCALATE`), consumed conceptually by the policy wording in Task 4 (no code dependency, doc reference only).

- [ ] **Step 1: Write the failing tests**

Add near the top of `tests/test_lifecycle_gate_policy.py` (alongside `RUNNER`/`MIGRATION_LINT`):

```python
PREMERGE = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "scripts" / "premerge.sh"
```

Append this class (it needs `RUNNER`, `PREMERGE`, `MIGRATION_LINT` already defined, and reuses `GitFixture`/`run`/helpers already in the file):

```python
class PremergeFixture(GitFixture):
    def setUp(self) -> None:
        super().setUp()
        run("git", "config", "user.email", "fixture@example.test", cwd=self.repo)
        run("git", "config", "user.name", "Fixture", cwd=self.repo)
        run("git", "checkout", "-q", "-b", "main", cwd=self.repo)
        self.write("scripts/premerge.sh", PREMERGE.read_text(encoding="utf-8"), executable=True)
        self.write("scripts/token-gate.sh", RUNNER.read_text(encoding="utf-8"), executable=True)
        self.write("scripts/migration-lint.py", MIGRATION_LINT.read_text(encoding="utf-8"), executable=True)
        run("git", "commit", "-qm", "init", cwd=self.repo)

        self.origin = Path(self.tempdir.name) / "origin.git"
        run("git", "init", "-q", "--bare", str(self.origin))
        run("git", "remote", "add", "origin", str(self.origin), cwd=self.repo)
        run("git", "push", "-q", "-u", "origin", "main", cwd=self.repo)
        run("git", "remote", "set-head", "origin", "main", cwd=self.repo)

    def configure(self, conf: str) -> None:
        run("git", "checkout", "-q", "main", cwd=self.repo)
        self.write("scripts/premerge.conf.sh", conf)
        run("git", "commit", "-qm", "configure migration lint", cwd=self.repo)
        run("git", "push", "-q", "origin", "main", cwd=self.repo)
        run("git", "checkout", "-q", "-b", "feature", cwd=self.repo)

    def add_migration(self, relative: str, sql: str) -> None:
        self.write(relative, sql)
        run("git", "commit", "-qm", f"add {relative}", cwd=self.repo)

    def run_premerge(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        runtime_tmp = Path(self.tempdir.name) / "runtime tmp"
        runtime_tmp.mkdir(mode=0o700, exist_ok=True)
        env["TMPDIR"] = str(runtime_tmp)
        return run("bash", "scripts/premerge.sh", cwd=self.repo, check=False, env=env)


class MigrationLintPremergeTests(PremergeFixture):
    def test_flags_destructive_migration_blocks_selfmerge(self) -> None:
        self.configure(
            """
            MIGRATION_LINT_ENABLED="true"
            MIGRATION_LINT_REGEX='^supabase/migrations/.*\\.sql$'
            """
        )
        self.add_migration("supabase/migrations/0001_drop_users.sql", "DROP TABLE users;\n")

        result = self.run_premerge()

        self.assertEqual(result.returncode, 5)
        self.assertIn("MIGRATION_ESCALATE", result.stderr)
        self.assertIn("drop-table", result.stderr)

    def test_clean_migration_reaches_review_stage(self) -> None:
        self.configure(
            """
            MIGRATION_LINT_ENABLED="true"
            MIGRATION_LINT_REGEX='^supabase/migrations/.*\\.sql$'
            """
        )
        self.add_migration(
            "supabase/migrations/0002_add_widgets.sql",
            "CREATE TABLE widgets (id serial primary key);\n",
        )

        result = self.run_premerge()

        self.assertEqual(result.returncode, 4)
        self.assertIn("REVIEW required", result.stdout)

    def test_disabled_by_default_does_not_block_destructive_migration(self) -> None:
        self.configure("")
        self.add_migration("supabase/migrations/0001_drop_users.sql", "DROP TABLE users;\n")

        result = self.run_premerge()

        self.assertEqual(result.returncode, 4)
        self.assertIn("REVIEW required", result.stdout)

    def test_enabled_without_regex_fails_fast(self) -> None:
        self.configure('MIGRATION_LINT_ENABLED="true"\n')
        self.add_migration("supabase/migrations/0001_drop_users.sql", "DROP TABLE users;\n")

        result = self.run_premerge()

        self.assertEqual(result.returncode, 2)
        self.assertIn("MIGRATION_LINT_REGEX unset", result.stderr)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k MigrationLintPremergeTests -v`
Expected: 4 failures — current `premerge.sh` has no migration-safety stage, so the destructive-migration test gets exit `4` (REVIEW) instead of `5`, and the misconfiguration test doesn't fail at all (no such check exists yet).

- [ ] **Step 3: Modify `premerge.sh`**

Edit the exit-code header comment (currently lines 9-15):

```diff
 #   4  REVIEW — code changes present and --review-done not given; run your
 #      review process first, then re-run with --review-done
+#   5  MIGRATION_ESCALATE — destructive-op lint flagged a migration change;
+#      a human must review and merge this PR (opt-in via MIGRATION_LINT_ENABLED)
 #   *  verify/e2e failure (their exit codes pass through)
```

Edit the repo-config defaults block (currently lines 22-29) to add two new defaults before `CONF=`:

```diff
 PROTECTED_EXTRA_REGEX="" # repo-specific additions to the protected set
 PROTECTED_SCRIPT_KEYS="" # space-separated package.json script keys to guard; empty = guard the whole scripts block
+MIGRATION_LINT_ENABLED="false" # opt-in destructive-op lint for schema/migration files
+MIGRATION_LINT_REGEX="" # e.g. '^supabase/migrations/.*\.sql$' — required when MIGRATION_LINT_ENABLED=true
 CONF="$REPO_ROOT/scripts/premerge.conf.sh"
 [ -f "$CONF" ] && . "$CONF"
```

Edit `PROTECTED_REGEX` (currently line 69):

```diff
-PROTECTED_REGEX='^\.githooks/|^scripts/(premerge\.sh|premerge\.conf\.sh|token-gate\.sh)$|^biome\.json$|^\.gitleaks\.toml$'
+PROTECTED_REGEX='^\.githooks/|^scripts/(premerge\.sh|premerge\.conf\.sh|token-gate\.sh|migration-lint\.py)$|^biome\.json$|^\.gitleaks\.toml$'
```

Insert a new stage between the end of "2. gate integrity" (the `fi` that closes the `PROTECTED_HITS` check, right before the `# ---- 3. review requirement` comment) and renumber the two stages that follow it:

```diff
 if [ -n "$PROTECTED_HITS" ]; then
   printf '[premerge] PROTECTED — this PR changes gate-integrity paths:\n'
   printf '%s\n' "$PROTECTED_HITS" | sed 's/^/[premerge]   /'
   printf '[premerge] self-merge is not allowed for gate changes; escalate — a human merges this PR\n'
   exit 3
 fi
 
-# ---- 3. review requirement ----------------------------------------------------
+# ---- 3. migration safety (opt-in) --------------------------------------------
+# Deterministic destructive-op scan for schema/migration files. Disabled by
+# default; a repo opts in via scripts/premerge.conf.sh. When enabled and the
+# lint flags something, this hard-blocks self-merge with no override — a
+# contract-aware alternative exists in orca-evaluate's separate merge path,
+# which does not go through this script.
+if [ "$MIGRATION_LINT_ENABLED" = "true" ]; then
+  if [ -z "$MIGRATION_LINT_REGEX" ]; then
+    printf '[premerge] FAIL — MIGRATION_LINT_ENABLED=true but MIGRATION_LINT_REGEX unset in premerge.conf.sh\n' >&2
+    exit 2
+  fi
+  MIGRATION_FILES=$(printf '%s\n' "$CHANGED" | grep -E "$MIGRATION_LINT_REGEX" || true)
+  if [ -n "$MIGRATION_FILES" ]; then
+    if ! LINT_OUT=$(printf '%s\n' "$MIGRATION_FILES" | xargs python3 scripts/migration-lint.py 2>&1); then
+      printf '[premerge] MIGRATION_ESCALATE — destructive-op lint flagged a migration change:\n' >&2
+      printf '%s\n' "$LINT_OUT" | sed 's/^/[premerge]   /' >&2
+      printf '[premerge] self-merge is not allowed — a human must review and merge this PR\n' >&2
+      exit 5
+    fi
+  fi
+fi
+
+# ---- 4. review requirement ----------------------------------------------------
 CODE_CHANGES=$(printf '%s\n' "$CHANGED" | grep -Ev "$REVIEW_EXEMPT_REGEX" || true)
 if [ -n "$CODE_CHANGES" ] && [ "$REVIEW_DONE" -ne 1 ]; then
   CODE_COUNT=$(printf '%s\n' "$CODE_CHANGES" | wc -l | tr -d ' ')
   printf '[premerge] REVIEW required — %s code file(s) changed\n' "$CODE_COUNT"
   printf '[premerge] resolve blocking findings from your review process,\n'
   printf '[premerge] then re-run: scripts/premerge.sh --review-done\n'
   exit 4
 fi
 
-# ---- 4. full verification -------------------------------------------------------
+# ---- 5. full verification -------------------------------------------------------
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k MigrationLintPremergeTests -v`
Expected: 4 passed.

Run the full suite: `uv run --with pytest pytest tests/ -q`
Expected: 69 passed (65 from Task 1 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add skills/lifecycle-gate-policy/assets/scripts/premerge.sh tests/test_lifecycle_gate_policy.py
git commit -m "feat(#9): hard-block premerge.sh self-merge on flagged destructive migrations"
```

---

### Task 3: `audit.py` — register `migration-lint.py` as a canonical file

**Files:**
- Modify: `skills/lifecycle-gate-policy/scripts/audit.py`
- Modify: `tests/test_lifecycle_gate_policy.py` (add `AUDIT` constant, add `AuditMigrationLintTests` class)

**Interfaces:**
- Consumes: `skills/lifecycle-gate-policy/assets/scripts/migration-lint.py` (from Task 1) as the canonical source for hash comparison.
- Produces: a new entry in `audit.py`'s `CANONICAL` dict keyed `"scripts/migration-lint.py"`, reported under that exact `check` name in both text and JSON output — relied on only by this task's own tests (no other task consumes this key).

- [ ] **Step 1: Write the failing tests**

Add near the top of `tests/test_lifecycle_gate_policy.py`:

```python
AUDIT = ROOT / "skills" / "lifecycle-gate-policy" / "scripts" / "audit.py"
```

Append this class:

```python
class AuditMigrationLintTests(GitFixture):
    def setUp(self) -> None:
        super().setUp()
        run("git", "config", "user.email", "fixture@example.test", cwd=self.repo)
        run("git", "config", "user.name", "Fixture", cwd=self.repo)

    def run_audit(self) -> dict:
        result = run(
            sys.executable, str(AUDIT), "--repo", str(self.repo), "--format", "json",
            cwd=self.repo, check=False,
        )
        return json.loads(result.stdout)

    def find_check(self, report: dict, name: str) -> dict:
        return next(r for r in report["results"] if r["check"] == name)

    def test_missing_migration_lint_reports_missing(self) -> None:
        run("git", "commit", "--allow-empty", "-qm", "init", cwd=self.repo)

        report = self.run_audit()

        check = self.find_check(report, "scripts/migration-lint.py")
        self.assertEqual(check["status"], "MISSING")

    def test_canonical_migration_lint_reports_pass(self) -> None:
        self.write(
            "scripts/migration-lint.py",
            MIGRATION_LINT.read_text(encoding="utf-8"),
            executable=True,
        )
        run("git", "commit", "-qm", "add migration-lint.py", cwd=self.repo)

        report = self.run_audit()

        check = self.find_check(report, "scripts/migration-lint.py")
        self.assertEqual(check["status"], "PASS")

    def test_drifted_migration_lint_reports_drift(self) -> None:
        self.write("scripts/migration-lint.py", "# hand-edited, not canonical\n")
        run("git", "commit", "-qm", "drift migration-lint.py", cwd=self.repo)

        report = self.run_audit()

        check = self.find_check(report, "scripts/migration-lint.py")
        self.assertEqual(check["status"], "DRIFT")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k AuditMigrationLintTests -v`
Expected: all 3 fail with `StopIteration` (`find_check` finds no result named `"scripts/migration-lint.py"` because the `CANONICAL` dict doesn't have that key yet).

- [ ] **Step 3: Modify `audit.py`**

In `skills/lifecycle-gate-policy/scripts/audit.py`, edit the `CANONICAL` dict:

```diff
 CANONICAL = {
     ".githooks/pre-commit": ASSETS / "githooks" / "pre-commit",
     ".githooks/pre-push": ASSETS / "githooks" / "pre-push",
     ".githooks/post-checkout": ASSETS / "githooks" / "post-checkout",
     "scripts/premerge.sh": ASSETS / "scripts" / "premerge.sh",
     "scripts/token-gate.sh": ASSETS / "scripts" / "token-gate.sh",
+    "scripts/migration-lint.py": ASSETS / "scripts" / "migration-lint.py",
 }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k AuditMigrationLintTests -v`
Expected: 3 passed.

Run the full suite: `uv run --with pytest pytest tests/ -q`
Expected: 72 passed (69 from Task 2 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add skills/lifecycle-gate-policy/scripts/audit.py tests/test_lifecycle_gate_policy.py
git commit -m "feat(#9): register migration-lint.py as an audit.py canonical file"
```

---

### Task 4: Canonical docs & config wording — `agents-policy.md`, `premerge.conf.sh`, `lifecycle-gate-policy/SKILL.md`

**Files:**
- Modify: `skills/lifecycle-gate-policy/assets/agents-policy.md`
- Modify: `skills/lifecycle-gate-policy/assets/scripts/premerge.conf.sh`
- Modify: `skills/lifecycle-gate-policy/SKILL.md`
- Modify: `tests/test_lifecycle_gate_policy.py` (add `ASSETS` constant, add `test_agents_policy_escalation_mentions_migration_lint_gate`)

**Interfaces:**
- Consumes: nothing new (pure documentation/config-comment wording; no code path reads these strings).
- Produces: nothing consumed by other tasks — this task closes out the design spec's sections F/G.

- [ ] **Step 1: Write the failing test**

Add near the top of `tests/test_lifecycle_gate_policy.py`:

```python
ASSETS = ROOT / "skills" / "lifecycle-gate-policy" / "assets"
```

Append this module-level test function (not a class — plain function, matching the style of a simple content assertion; place it after the imports/constants, before the first class):

```python
def test_agents_policy_escalation_mentions_migration_lint_gate() -> None:
    text = (ASSETS / "agents-policy.md").read_text(encoding="utf-8")
    assert "MIGRATION_LINT_ENABLED" in text
    assert "schema/migrations/deploy configuration" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k test_agents_policy_escalation_mentions_migration_lint_gate -v`
Expected: FAIL — `agents-policy.md` doesn't mention `MIGRATION_LINT_ENABLED` yet, and still contains the old unconditional phrase.

- [ ] **Step 3: Edit `agents-policy.md`**

In `skills/lifecycle-gate-policy/assets/agents-policy.md`, replace the self-merge escalation bullet:

```diff
 - **Escalate to a human merge** (no self-merge) when: premerge reports PROTECTED
   (gate-integrity paths changed — hooks, premerge/token-gate scripts, biome config,
   root package.json scripts), verify/e2e fails and the fix is non-obvious, the PR is
-  not mergeable-clean, or the change touches schema/migrations/deploy configuration.
+  not mergeable-clean, or the change touches schema/migrations (unless this repo has
+  a migration-safety gate configured — `MIGRATION_LINT_ENABLED=true` in
+  `scripts/premerge.conf.sh` — in which case `premerge.sh` already hard-blocks
+  self-merge automatically when the lint flags something, so no separate check is
+  needed; repos without the gate configured keep escalating unconditionally) or
+  deploy configuration.
```

- [ ] **Step 4: Edit `premerge.conf.sh`**

Append to the end of `skills/lifecycle-gate-policy/assets/scripts/premerge.conf.sh` (after the existing `PROTECTED_SCRIPT_KEYS` comment/example):

```diff
 #PROTECTED_SCRIPT_KEYS="verify verify:guides check-types premerge prepare e2e"
+
+# Destructive-op lint (opt-in). Enable and set a regex matching this repo's
+# migration file paths; the lint hard-blocks self-merge when it flags a
+# destructive operation (DROP TABLE/COLUMN, TRUNCATE, DELETE without WHERE,
+# RENAME, ALTER COLUMN TYPE) with no override in this script.
+#MIGRATION_LINT_ENABLED="true"
+#MIGRATION_LINT_REGEX='^supabase/migrations/.*\.sql$'
```

- [ ] **Step 5: Edit `lifecycle-gate-policy/SKILL.md`**

Edit the summary table (currently lines 17-21):

```diff
 | `.githooks/pre-push` | push | `pnpm verify:static` — static checks only, token-gated |
-| `scripts/premerge.sh` | right before squash merge | full `pnpm verify` + e2e (if configured) + review for code changes |
+| `scripts/premerge.sh` | right before squash merge | gate-integrity check → migration-safety lint (opt-in) → review requirement → full `pnpm verify` + e2e (if configured) |
```

Edit the "Apply to a repository" step 1 file-copy list:

```diff
 1. Copy `assets/githooks/{pre-commit,pre-push,post-checkout}` → `<repo>/.githooks/`,
-   `assets/scripts/{premerge.sh,token-gate.sh,premerge.conf.sh}` → `<repo>/scripts/`.
-   Mark hooks and scripts executable.
+   `assets/scripts/{premerge.sh,token-gate.sh,premerge.conf.sh,migration-lint.py}` →
+   `<repo>/scripts/`. Mark hooks and scripts executable.
```

Edit step 3 (`premerge.conf.sh` fill-in instructions):

```diff
 3. Fill `scripts/premerge.conf.sh`: set `E2E_CMD` if the repo has a merge-blocking
    e2e suite; extend `PROTECTED_EXTRA_REGEX` for repo-specific gate tooling; optionally
    set `PROTECTED_SCRIPT_KEYS` by tracing the repo's actual verify/premerge chain to the
    script keys it calls (leave unset to keep guarding the whole `scripts` block).
+   If the repo has SQL migrations, consider setting `MIGRATION_LINT_ENABLED="true"` and
+   `MIGRATION_LINT_REGEX` to opt into the destructive-op lint — this is a separate,
+   per-repo decision made only on explicit request, not a default part of applying
+   this skill.
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_lifecycle_gate_policy.py -k test_agents_policy_escalation_mentions_migration_lint_gate -v`
Expected: PASS.

Run the full suite: `uv run --with pytest pytest tests/ -q`
Expected: 73 passed (72 from Task 3 + 1 new).

- [ ] **Step 7: Commit**

```bash
git add skills/lifecycle-gate-policy/assets/agents-policy.md \
        skills/lifecycle-gate-policy/assets/scripts/premerge.conf.sh \
        skills/lifecycle-gate-policy/SKILL.md \
        tests/test_lifecycle_gate_policy.py
git commit -m "docs(#9): scope schema/migrations self-merge escalation to unconfigured repos"
```

---

### Task 5: `orca-task-runner` + `orca-evaluate` — declared destructive ops and 4th ESCALATE condition

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md`
- Modify: `skills/orca-evaluate/SKILL.md`
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `migration-lint.py`'s CLI/JSON contract from Task 1 (referenced in prose only — `orca-evaluate` is an instruction document, not executable code).
- Produces: no new code interface — this task closes out design spec sections D/E (the §1 declared-destructive-ops field and the §4 4th ESCALATE condition), verified by doc-level tests matching this repo's existing convention for the orca skill family.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orca_skills.py` (reuses the existing `_read_skill` helper already defined in that file):

```python
def test_orca_task_runner_declares_destructive_ops_field():
    text = _read_skill("orca-task-runner")
    assert "의도된 destructive 오퍼레이션" in text, (
        "orca-task-runner's proposal format must require a declared destructive-ops field"
    )


def test_orca_evaluate_has_migration_escalate_condition():
    text = _read_skill("orca-evaluate")
    assert "destructive-op 린터가 flag" in text and "선언에 커버되지 않는다" in text, (
        "orca-evaluate §4 must add the migration destructive-op ESCALATE condition"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_orca_skills.py -k "destructive_ops_field or migration_escalate_condition" -v`
Expected: both FAIL — neither phrase exists in the skill docs yet.

- [ ] **Step 3: Edit `orca-task-runner/SKILL.md` §1**

Replace the proposal bullet list:

```diff
 `orca-workflow`가 이 task를 넘기면, 코드를 쓰기 전에 **제안서**를 먼저 쓴다:
 
 - 구현 범위(무엇을 만들 것인가, 어떤 파일을 건드릴 것인가)
 - 검증 방법(구체적인 파일/함수/테스트로 — issue의 `## Acceptance criteria`를 어떻게 커버할지)
+- (schema/migration 파일을 건드리는 경우) **의도된 destructive 오퍼레이션 목록.** 없으면
+  명시적으로 "없음"이라고 쓴다(공란은 "언급 안 함"이지 "없음"이 아니므로 구분한다). 이 선언은
+  나중에 `orca-evaluate` §3가 diff에서 실제로 flag된 destructive-op와 대조하는 근거가 된다.
 
 `orca-evaluate`가 이 제안을 issue의 원본 acceptance criteria에 대조해 검토한다. 반려되면 수정해서 다시 제안한다. **최대 2 라운드.** 2라운드 안에 합의가 안 되면 이 스킬(generator)이 결정권을 가지고 그 제안대로 진행한다 — evaluator의 이견은 기록에 남기되 진행을 막지 않는다.
```

- [ ] **Step 4: Edit `orca-evaluate/SKILL.md` §3**

Insert a migration-lint step after the `git diff` code block and before the code-reviewer-spawn paragraph, and extend that paragraph's numbered list with a 4th item:

```diff
 ## 3. Diff 리뷰 (coding agent 스폰, agent e2e 결과 반영)
 
 ```bash
 git diff "$(git merge-base origin/main HEAD)"...HEAD > <worktree 루트>/.evaluate-diff.patch
 ```
 
-fresh-context code-reviewer terminal을 하나 스폰한다(이 evaluator 세션·generator와 별도 세션 — **강한 reasoning 모델 고정**, `model-selection.md` High Risk tier 참고: Claude Opus 4.8 xhigh / Codex Sol xhigh 등. "provider 자유, 가장 싼 provider"가 아니다 — 코드 정오 판단은 이 세션의 Gemini가 약하다고 표시된 지점이라 일부러 다른 모델을 쓰는 것). 리뷰어는 반드시 이 세 가지를 갖는다: ①skeptical 지침("동의 표명 불필요, 결함·spec-divergence만 보고, 근거 있는 우려를 안이하게 넘기지 말 것") ②issue의 acceptance criteria 원문 ③**§2 agent e2e 결과 요약** — diff만으로는 안 보이는 런타임 동작(무엇이 실제로 실패했는지)을 code review가 근거로 쓸 수 있게 한다.
+diff에 schema/migration 파일이 포함돼 있으면, code-reviewer를 스폰하기 전에 destructive-op 린터를 돌린다:
+
+```bash
+python3 scripts/migration-lint.py <diff에 포함된 migration 파일 경로...> > <worktree 루트>/.migration-lint.json
+```
+
+(repo에 `scripts/migration-lint.py`가 없으면 이 단계를 건너뛴다 — opt-in 게이트이므로 미구성 repo에서는 아무 일도 하지 않는다.)
+
+fresh-context code-reviewer terminal을 하나 스폰한다(이 evaluator 세션·generator와 별도 세션 — **강한 reasoning 모델 고정**, `model-selection.md` High Risk tier 참고: Claude Opus 4.8 xhigh / Codex Sol xhigh 등. "provider 자유, 가장 싼 provider"가 아니다 — 코드 정오 판단은 이 세션의 Gemini가 약하다고 표시된 지점이라 일부러 다른 모델을 쓰는 것). 리뷰어는 반드시 이 항목들을 갖는다: ①skeptical 지침("동의 표명 불필요, 결함·spec-divergence만 보고, 근거 있는 우려를 안이하게 넘기지 말 것") ②issue의 acceptance criteria 원문 ③**§2 agent e2e 결과 요약** — diff만으로는 안 보이는 런타임 동작(무엇이 실제로 실패했는지)을 code review가 근거로 쓸 수 있게 한다 ④**(schema/migration 변경이 있으면) `.migration-lint.json` 결과 + §1에서 받은 "의도된 destructive 오퍼레이션" 선언** — 린터가 flag한 항목 중 선언에 커버되지 않는 게 있으면 report에 명시하라는 지시와 함께.
 
 ```bash
 orca terminal create --worktree active --title eval-review \
   --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
 orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
-orca orchestration task-create --spec "<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지>" --json
+orca orchestration task-create --spec "<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 §1 destructive-op 선언 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지>" --json
 orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
 printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"code-review","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<review-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
   >> ~/.agents/orca-workflows/logs/assignments.jsonl   # 할당 로그 — §1 참고
 ```
```

- [ ] **Step 5: Edit `orca-evaluate/SKILL.md` §4**

Extend the ESCALATE bullet with a 4th condition:

```diff
-- **ESCALATE** — 다음 중 하나면 재시도 없이 즉시: acceptance criteria 자체가 애매해서 판정이 불가능, 구현이 issue 스코프 밖의 것을 건드림, agent e2e가 인프라 문제(계정·secret·환경)로 판단 불가.
+- **ESCALATE** — 다음 중 하나면 재시도 없이 즉시: acceptance criteria 자체가 애매해서 판정이 불가능, 구현이 issue 스코프 밖의 것을 건드림, agent e2e가 인프라 문제(계정·secret·환경)로 판단 불가, **destructive-op 린터가 flag했는데 code-reviewer report가 그 항목이 제안서의 destructive-op 선언에 커버되지 않는다고 명시함**.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_orca_skills.py -v`
Expected: 20 passed (18 baseline + 2 new), 0 failures.

Run the full suite: `uv run --with pytest pytest tests/ -q`
Expected: 75 passed (73 from Task 4 + 2 new).

- [ ] **Step 7: Commit**

```bash
git add skills/orca-task-runner/SKILL.md skills/orca-evaluate/SKILL.md tests/test_orca_skills.py
git commit -m "feat(#9): declare destructive ops in orca-task-runner proposal, add orca-evaluate 4th ESCALATE condition"
```

---

## Final verification

- [ ] Run the complete suite once more from a clean state: `uv run --with pytest pytest tests/ -q` → expect **75 passed**, 0 failures, 0 errors.
- [ ] `git log --oneline -5` shows the 5 commits from this plan in order, each referencing `#9`.
- [ ] Confirm no file outside `sleeptimegrt-skills` was touched: `git status --porcelain` shows a clean tree, and `git diff main...HEAD --stat` only lists paths under `skills/lifecycle-gate-policy/`, `skills/orca-task-runner/`, `skills/orca-evaluate/`, `tests/`, `docs/superpowers/specs/`, `docs/superpowers/plans/`.
