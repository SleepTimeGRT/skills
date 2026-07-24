from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "scripts" / "token-gate.sh"
MIGRATION_LINT = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "scripts" / "migration-lint.py"


def run(
    *args: str,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def retained_log(stdout: str) -> Path:
    line = next(line for line in stdout.splitlines() if "log:" in line)
    return Path(line.split(" — log: ", 1)[1])


class GitFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="lifecycle gate policy ")
        self.repo = Path(self.tempdir.name) / "repo with spaces"
        self.repo.mkdir()
        run("git", "init", "-q", cwd=self.repo)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write(self, relative: str, content: str, executable: bool = False) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        if executable:
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        run("git", "add", relative, cwd=self.repo)
        return path


class RunnerTests(GitFixture):
    def setUp(self) -> None:
        super().setUp()
        self.runtime_tmp = (Path(self.tempdir.name) / "runtime tmp").resolve()
        self.runtime_tmp.mkdir(mode=0o700)

    def runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["TMPDIR"] = str(self.runtime_tmp)
        return env

    def run_gate(self, body: str) -> subprocess.CompletedProcess[str]:
        script = self.write(
            "run-gate.sh",
            f"""
            #!/usr/bin/env bash
            set -u
            source {json.dumps(str(RUNNER))}
            token_gate_begin verify
            {body}
            token_gate_finish
            """,
            True,
        )
        return run("bash", str(script), cwd=self.repo, check=False, env=self.runtime_env())

    def run_capture(self, command: str, *options: str) -> subprocess.CompletedProcess[str]:
        script = self.write(
            "run-capture.sh",
            f"""
            #!/usr/bin/env bash
            set -u
            source {json.dumps(str(RUNNER))}
            token_gate_capture {' '.join(options)} verify -- bash -c {shlex.quote(command)}
            """,
            True,
        )
        return run("bash", str(script), cwd=self.repo, check=False, env=self.runtime_env())

    def test_whole_command_capture_hides_success_log_path(self) -> None:
        result = self.run_capture("printf 'noisy-success\\n%.0s' {1..100}")

        self.assertEqual(result.returncode, 0)
        self.assertRegex(result.stdout, r"^\[verify\] PASS \([0-9]+s\)\n$")
        self.assertNotIn("log:", result.stdout)
        self.assertNotIn("noisy-success", result.stdout)
        self.assertEqual(list(self.runtime_tmp.rglob("latest.log")), [])
        self.assertEqual(list((self.repo / ".git" / "token-gates").rglob("latest.log")), [])

    def test_whole_command_failure_returns_bounded_line_index(self) -> None:
        result = self.run_capture(
            "printf 'progress-%s\\n' {1..30}; "
            "echo 'src/check.ts:14:3 error TS2322: wrong type'; "
            "printf 'after-%s\\n' {1..20}; exit 19"
        )

        self.assertEqual(result.returncode, 19)
        lines = result.stdout.splitlines()
        self.assertRegex(lines[0], r"^\[verify\] FAIL \(exit 19, [0-9]+s\) — log: .+/latest\.log$")
        self.assertEqual(lines[1], "[verify] INDEX L31: src/check.ts:14:3 error TS2322: wrong type")
        self.assertEqual(len(lines), 2)
        self.assertTrue(retained_log(result.stdout).is_relative_to(self.runtime_tmp))

    def test_whole_command_warning_uses_explicit_detector(self) -> None:
        result = self.run_capture("echo 'NOTICE quota nearing limit'", "--warn-regex", "'^NOTICE '")

        self.assertEqual(result.returncode, 0)
        self.assertRegex(result.stdout.splitlines()[0], r"^\[verify\] WARN \([0-9]+s\) — log: .+/latest\.log$")
        self.assertEqual(result.stdout.splitlines()[1], "[verify] INDEX L1: NOTICE quota nearing limit")

    def test_whole_command_failure_without_marker_points_to_tail(self) -> None:
        result = self.run_capture("printf 'opaque-%s\\n' {1..37}; exit 2")

        self.assertEqual(result.returncode, 2)
        self.assertIn("[verify] INDEX no high-confidence marker; inspect L18-L37", result.stdout)
        self.assertNotIn("opaque-37", result.stdout)

    def test_whole_command_capture_re_raises_signal(self) -> None:
        result = self.run_capture("kill -TERM $$")

        self.assertEqual(result.returncode, -15)
        self.assertRegex(
            result.stdout.splitlines()[0],
            r"^\[verify\] FAIL \(signal (?:TERM|15), [0-9]+s\) — log: .+/latest\.log$",
        )

    def test_runner_compacts_pass_warn_and_fail_while_preserving_diagnostics(self) -> None:
        result = self.run_gate(
            """
            token_gate_stage pass -- bash -c 'echo many; echo lines'
            token_gate_stage --warn-regex 'deprecated' vocab -- bash -c 'echo deprecated >&2'
            token_gate_stage broken -- bash -c 'echo failure detail >&2; exit 23'
            exit $?
            """
        )

        self.assertEqual(result.returncode, 23)
        self.assertNotIn("many", result.stdout)
        self.assertNotIn("failure detail", result.stdout)
        self.assertRegex(result.stdout, r"\[verify\] PASS pass \([0-9.]+s\)")
        self.assertRegex(result.stdout, r"\[verify\] WARN vocab \([0-9.]+s\) — log: .+")
        self.assertRegex(result.stdout, r"\[verify\] FAIL broken \(exit 23, [0-9.]+s\) — log: .+")

        log_path = retained_log(result.stdout)
        self.assertTrue(log_path.is_file())
        self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)
        log = log_path.read_text(encoding="utf-8")
        self.assertIn("many", log)
        self.assertIn("deprecated", log)
        self.assertIn("failure detail", log)
        self.assertEqual(run("git", "status", "--porcelain=v1", cwd=self.repo).stdout.count("token-gates"), 0)

    def test_runner_deletes_log_after_all_stages_pass(self) -> None:
        result = self.run_gate("token_gate_stage first -- bash -c 'echo success-marker'")

        self.assertEqual(result.returncode, 0)
        self.assertNotIn("log:", result.stdout)
        self.assertEqual(list(self.runtime_tmp.rglob("latest.log")), [])

    def test_runner_preserves_signal_termination(self) -> None:
        result = self.run_gate("token_gate_stage signaled -- bash -c 'kill -TERM $$'")

        self.assertEqual(result.returncode, -15)
        self.assertRegex(result.stdout, r"\[verify\] FAIL signaled \(signal (?:TERM|15), [0-9.]+s\) — log: .+")

    def test_runner_reports_skip_as_a_distinct_outcome(self) -> None:
        result = self.run_gate("token_gate_skip integration 'database is unavailable'")

        self.assertEqual(result.returncode, 0)
        self.assertIn("[verify] SKIP integration — database is unavailable", result.stdout)
        self.assertIn("[verify] WARN 1 stages", result.stdout)

    def test_runner_accumulates_failure_when_the_caller_continues(self) -> None:
        result = self.run_gate(
            """
            token_gate_stage broken -- bash -c 'echo broken-detail; exit 7' || true
            token_gate_stage later -- bash -c 'echo later-detail'
            """
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("[verify] FAIL broken (exit 7", result.stdout)
        self.assertIn("[verify] PASS later", result.stdout)
        self.assertIn("[verify] FAIL 2 stages", result.stdout)

    def test_runner_isolates_logs_between_linked_worktrees(self) -> None:
        self.write("tracked.txt", "fixture\n")
        run("git", "config", "user.email", "fixture@example.test", cwd=self.repo)
        run("git", "config", "user.name", "Fixture", cwd=self.repo)
        run("git", "commit", "-qm", "fixture", cwd=self.repo)
        linked = Path(self.tempdir.name) / "linked worktree"
        run("git", "worktree", "add", "-q", "-b", "linked", str(linked), cwd=self.repo)

        main_result = self.run_gate(
            "token_gate_stage --warn-regex warning main -- bash -c 'echo main-warning'"
        )
        linked_script = linked / "linked-gate.sh"
        linked_script.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                source {json.dumps(str(RUNNER))}
                token_gate_begin verify
                token_gate_stage --warn-regex warning linked -- bash -c 'echo linked-warning'
                token_gate_finish
                """
            ).lstrip(),
            encoding="utf-8",
        )
        linked_result = run("bash", str(linked_script), cwd=linked, check=False, env=self.runtime_env())

        main_log = retained_log(main_result.stdout)
        linked_log = retained_log(linked_result.stdout)
        self.assertNotEqual(main_log, linked_log)
        self.assertIn("main-warning", main_log.read_text(encoding="utf-8"))
        self.assertIn("linked-warning", linked_log.read_text(encoding="utf-8"))


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


if __name__ == "__main__":
    unittest.main()
