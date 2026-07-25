from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "scripts" / "token-gate.sh"
PRE_COMMIT = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "githooks" / "pre-commit"
PREMERGE = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "scripts" / "premerge.sh"


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


class PathFallbackTests(GitFixture):
    def setUp(self) -> None:
        super().setUp()
        self.fixture_home = Path(self.tempdir.name) / "fixture home"
        self.fixture_home.mkdir()
        self.fake_bin = Path(self.tempdir.name) / "fake bin"
        self.fake_bin.mkdir()
        pnpm_stub = self.fake_bin / "pnpm"
        pnpm_stub.write_text("#!/usr/bin/env bash\necho fake-pnpm \"$@\"\n", encoding="utf-8")
        pnpm_stub.chmod(0o755)

    def write_fake_nvm(self) -> None:
        nvm_dir = self.fixture_home / ".nvm"
        nvm_dir.mkdir()
        (nvm_dir / "nvm.sh").write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                nvm() {{
                  case "${{1:-}}" in
                    use)
                      if [ "${{2:-}}" = "default" ]; then
                        export PATH={json.dumps(str(self.fake_bin))}:"$PATH"
                        return 0
                      fi
                      if [ -f "$(pwd)/.nvmrc" ]; then
                        export PATH={json.dumps(str(self.fake_bin))}:"$PATH"
                        return 0
                      fi
                      echo "No .nvmrc file found" >&2
                      return 1
                      ;;
                  esac
                }}
                """
            ).lstrip(),
            encoding="utf-8",
        )

    def run_source_probe(self, *, home: Path, path: str) -> subprocess.CompletedProcess[str]:
        script = self.write(
            "probe.sh",
            f"""
            #!/usr/bin/env bash
            set -u
            source {json.dumps(str(RUNNER))}
            command -v pnpm
            """,
            True,
        )
        return run("bash", str(script), cwd=self.repo, check=False, env={"HOME": str(home), "PATH": path})

    def test_falls_back_to_nvm_default_alias_when_no_nvmrc(self) -> None:
        self.write_fake_nvm()
        result = self.run_source_probe(home=self.fixture_home, path="/usr/bin:/bin")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.fake_bin / "pnpm"))

    def test_uses_nvmrc_version_when_present(self) -> None:
        self.write_fake_nvm()
        self.write(".nvmrc", "v22.18.0\n")
        result = self.run_source_probe(home=self.fixture_home, path="/usr/bin:/bin")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.fake_bin / "pnpm"))

    def test_does_not_invoke_nvm_when_pnpm_already_on_path(self) -> None:
        result = self.run_source_probe(home=self.fixture_home, path=f"{self.fake_bin}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.fake_bin / "pnpm"))

    def test_leaves_pnpm_unresolved_when_nvm_is_unavailable(self) -> None:
        result = self.run_source_probe(home=self.fixture_home, path="/usr/bin:/bin")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_does_not_crash_when_home_unset_under_set_euo(self) -> None:
        # Regression: ensure the nvm fallback guard doesn't crash under set -euo pipefail
        # when HOME is unset. The guard should gracefully skip the fallback instead of
        # crashing with "HOME: unbound variable".
        script = self.write(
            "probe-no-home.sh",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            source {json.dumps(str(RUNNER))}
            command -v pnpm
            """,
            True,
        )
        # Omit HOME from env entirely, provide minimal PATH for bash to work
        result = run("bash", str(script), cwd=self.repo, check=False, env={"PATH": "/usr/bin:/bin"})

        # Should not crash with unbound variable; should fail gracefully
        self.assertNotIn("unbound variable", result.stderr, f"stderr: {result.stderr}")
        self.assertEqual(result.returncode, 1, f"stderr: {result.stderr}")
        self.assertEqual(result.stdout, "")


class PreCommitHookTests(GitFixture):
    def setUp(self) -> None:
        super().setUp()
        hooks_dir = self.repo / ".githooks"
        hooks_dir.mkdir()
        scripts_dir = self.repo / "scripts"
        scripts_dir.mkdir()
        shutil.copy(PRE_COMMIT, hooks_dir / "pre-commit")
        (hooks_dir / "pre-commit").chmod(0o755)
        shutil.copy(RUNNER, scripts_dir / "token-gate.sh")

        self.stub_bin = Path(self.tempdir.name) / "stub bin"
        self.stub_bin.mkdir()
        self.biome_marker = Path(self.tempdir.name) / "biome-invoked.marker"
        (self.stub_bin / "gitleaks").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (self.stub_bin / "gitleaks").chmod(0o755)
        (self.stub_bin / "pnpm").write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                if [ "$1" = "exec" ] && [ "$2" = "biome" ]; then
                  touch {json.dumps(str(self.biome_marker))}
                fi
                exit 0
                """
            ).lstrip(),
            encoding="utf-8",
        )
        (self.stub_bin / "pnpm").chmod(0o755)

    def run_pre_commit(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.stub_bin}:{env['PATH']}"
        return run("bash", str(self.repo / ".githooks" / "pre-commit"), cwd=self.repo, check=False, env=env)

    def test_still_runs_gitleaks_then_biome_after_sourcing_token_gate(self) -> None:
        self.write("src/app.ts", "export const x = 1;\n")
        result = self.run_pre_commit()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.biome_marker.exists())


class PremergeE2eExemptionTests(unittest.TestCase):
    """scripts/premerge.sh: E2E_EXEMPT_REGEX skip logic."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="premerge fixture ")
        base = Path(self.tempdir.name)
        self.origin = base / "origin.git"
        run("git", "init", "-q", "--bare", str(self.origin), cwd=base)

        self.repo = base / "repo"
        self.repo.mkdir()
        run("git", "init", "-qb", "main", cwd=self.repo)
        run("git", "config", "user.email", "fixture@example.test", cwd=self.repo)
        run("git", "config", "user.name", "Fixture", cwd=self.repo)
        run("git", "remote", "add", "origin", str(self.origin), cwd=self.repo)

        self.marker = base / "e2e-ran.marker"
        self._write_gate_scripts(e2e_exempt_regex="")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        run("git", "add", "-A", cwd=self.repo)
        run("git", "commit", "-qm", "init", cwd=self.repo)
        run("git", "push", "-q", "origin", "main", cwd=self.repo)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_gate_scripts(self, e2e_exempt_regex: str) -> None:
        scripts_dir = self.repo / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        shutil.copy(PREMERGE, scripts_dir / "premerge.sh")
        shutil.copy(RUNNER, scripts_dir / "token-gate.sh")
        (scripts_dir / "premerge.sh").chmod(0o755)

        conf_lines = [
            'VERIFY_CMD="true"',
            f'E2E_CMD="touch {shlex.quote(str(self.marker))}"',
        ]
        if e2e_exempt_regex:
            conf_lines.append(f"E2E_EXEMPT_REGEX={shlex.quote(e2e_exempt_regex)}")
        (scripts_dir / "premerge.conf.sh").write_text(
            "\n".join(conf_lines) + "\n", encoding="utf-8"
        )

    def configure_main(self, e2e_exempt_regex: str) -> None:
        """Push a repo-config change to main, as if the repo had already adopted it."""
        self._write_gate_scripts(e2e_exempt_regex)
        run("git", "add", "-A", cwd=self.repo)
        run("git", "commit", "-qm", "chore: configure premerge e2e exemption", cwd=self.repo)
        run("git", "push", "-q", "origin", "main", cwd=self.repo)

    def branch_with_changes(self, files: dict[str, str]) -> None:
        run("git", "checkout", "-qb", "feature", cwd=self.repo)
        for relative, content in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            run("git", "add", relative, cwd=self.repo)
        run("git", "commit", "-qm", "feature commit", cwd=self.repo)

    def run_premerge(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run("bash", "scripts/premerge.sh", *args, cwd=self.repo, check=False)

    def test_skips_e2e_when_every_changed_path_is_exempt(self) -> None:
        self.configure_main(r"\.(md|mdx|txt)$")
        self.branch_with_changes({"NOTES.md": "docs only\n"})

        result = self.run_premerge()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "[premerge] SKIP e2e — all changed paths match E2E_EXEMPT_REGEX", result.stdout
        )
        self.assertIn("PASS — self-merge allowed (e2e skipped", result.stdout)
        self.assertFalse(self.marker.exists())

    def test_runs_e2e_when_any_changed_path_is_not_exempt(self) -> None:
        self.configure_main(r"\.(md|mdx|txt)$")
        self.branch_with_changes({"NOTES.md": "docs only\n", "src.py": "print('x')\n"})

        result = self.run_premerge("--review-done")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("SKIP e2e", result.stdout)
        self.assertIn("PASS — self-merge allowed (e2e ran)", result.stdout)
        self.assertTrue(self.marker.exists())

    def test_gitignore_only_diff_skips_e2e_but_still_requires_review(self) -> None:
        # Mirrors the motivating case in issue #10: a .gitignore-only PR should skip
        # e2e once the repo opts in, but REVIEW_EXEMPT_REGEX (docs/md only, unchanged)
        # does not cover .gitignore, so the review gate still fires independently.
        self.configure_main(r"^\.gitignore$")
        self.branch_with_changes({".gitignore": "*.log\n"})

        result = self.run_premerge()

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("[premerge] REVIEW required", result.stdout)
        self.assertNotIn("SKIP e2e", result.stdout)
        self.assertFalse(self.marker.exists())

        result = self.run_premerge("--review-done")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[premerge] SKIP e2e", result.stdout)
        self.assertFalse(self.marker.exists())

    def test_e2e_runs_by_default_when_regex_unset_even_for_docs_only_diff(self) -> None:
        # setUp already wired E2E_EXEMPT_REGEX="" (the default) — guards against a
        # `grep -Ev ''` implementation matching every line and skipping unconditionally.
        self.branch_with_changes({"NOTES.md": "docs only\n"})

        result = self.run_premerge()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("SKIP e2e", result.stdout)
        self.assertIn("PASS — self-merge allowed (e2e ran)", result.stdout)
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
