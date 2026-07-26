from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "lifecycle-gate-policy"
SCRIPTS_DIR = SKILL_DIR / "scripts"
AUDIT = SCRIPTS_DIR / "audit.py"
FIXTURES_DIR = SCRIPTS_DIR / "conformance" / "fixtures"
POLICY_SPEC = SKILL_DIR / "references" / "policy-spec.md"
HOOK_CONTRACTS_SKILL = ROOT / "skills" / "lifecycle-hook-contracts" / "SKILL.md"
TOKEN_EFFICIENT_GATES_DIR = ROOT / "skills" / "token-efficient-gates"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import audit  # noqa: E402  (module under test — imported for its constants, not run as __main__)


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


# ---------------------------------------------------------------------------
# Module-level (no git fixture needed): doc/code drift, static-source, and
# repo-layout checks — these describe the shape of the shipped files, not
# runtime behavior.
# ---------------------------------------------------------------------------


def _markdown_section(text: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.MULTILINE)
    assert match, f"heading {heading!r} not found"
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end]


def _table_rows(section: str) -> list[list[str]]:
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue  # separator row
        rows.append(cells)
    return rows


def _backticked(cell: str) -> list[str]:
    return re.findall(r"`([a-z0-9-]+)`", cell)


def test_policy_spec_declares_required_categories() -> None:
    text = POLICY_SPEC.read_text(encoding="utf-8")

    vocab_rows = _table_rows(_markdown_section(text, "Category vocabulary"))[1:]
    doc_vocabulary = {name for row in vocab_rows for name in _backticked(row[0])}
    assert doc_vocabulary == audit.CATEGORY_VOCABULARY

    stage_rows = _table_rows(_markdown_section(text, "Required categories by stage"))[1:]
    doc_required: dict[str, set[str]] = {}
    for row in stage_rows:
        stage_names = _backticked(row[0])
        if not stage_names:
            continue
        doc_required[stage_names[0]] = set(_backticked(row[1]))
    assert doc_required == audit.REQUIRED_CATEGORIES


def test_fixtures_do_not_read_hook_sources() -> None:
    banned = (".githooks/", "premerge.sh", "token-gate.sh", ".husky/", "sha256", "hashlib", "read_bytes")
    fixture_files = [p for p in sorted(FIXTURES_DIR.glob("*.py")) if p.name != "__init__.py"]
    assert fixture_files, "expected fixture modules under conformance/fixtures/"
    for path in fixture_files:
        text = path.read_text(encoding="utf-8")
        for phrase in banned:
            assert phrase not in text, f"{path.name} contains banned mechanism-reading phrase {phrase!r}"


def test_audit_no_longer_hashes_canonical_assets() -> None:
    text = AUDIT.read_text(encoding="utf-8")
    for phrase in ("sha256", "CANONICAL", "hashlib"):
        assert phrase not in text, f"audit.py still references {phrase!r}"


def _iter_text_files(base: Path):
    for path in sorted(base.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_no_enforcement_language_remains() -> None:
    banned_phrases = (
        "do not hand-edit",
        "re-apply the template",
        "re-apply everywhere",
        "Remove the legacy hook manager",
        "policy v1",
    )
    scanned = list(_iter_text_files(SKILL_DIR))
    assert scanned, f"expected readable files under {SKILL_DIR}"
    for path, text in scanned:
        for phrase in banned_phrases:
            assert phrase not in text, f"{path} still contains {phrase!r}"

    hook_contracts_text = HOOK_CONTRACTS_SKILL.read_text(encoding="utf-8")
    for phrase in banned_phrases:
        assert phrase not in hook_contracts_text, f"{HOOK_CONTRACTS_SKILL} still contains {phrase!r}"

    audit_text = AUDIT.read_text(encoding="utf-8")
    for marker in ("husky", "lefthook", "core.hooksPath", "REQUIRED_SCRIPTS"):
        assert marker not in audit_text, f"audit.py still enforces {marker!r}"


def test_token_gate_stays_in_lifecycle_gate_policy() -> None:
    token_gate = SKILL_DIR / "assets" / "scripts" / "token-gate.sh"
    assert token_gate.is_file()
    assert TOKEN_EFFICIENT_GATES_DIR.is_dir(), f"expected {TOKEN_EFFICIENT_GATES_DIR} to exist"
    assert not list(TOKEN_EFFICIENT_GATES_DIR.rglob("token-gate*"))


# ---------------------------------------------------------------------------
# Synthetic-repo behavioral tests: a throwaway `git init` repo (never a pilot
# repo under ~/Projects) with a lifecycle-gate.toml and a minimal hook layout,
# audited via `audit.py --repo <synthetic repo>`.
# ---------------------------------------------------------------------------


GITLEAKS_PRE_COMMIT = r"""
#!/usr/bin/env bash
set -euo pipefail
if ! command -v gitleaks &>/dev/null; then
  echo "pre-commit: gitleaks not found" >&2
  exit 1
fi
gitleaks protect --staged --no-banner --redact
"""

STATIC_PRE_PUSH = r"""
#!/usr/bin/env bash
set -euo pipefail
delete_only=1
saw_ref=0
while read -r _local_ref local_oid _remote_ref _remote_oid; do
  saw_ref=1
  case "$local_oid" in
  *[!0]*) delete_only=0 ;;
  esac
done
if [ "$saw_ref" -eq 1 ] && [ "$delete_only" -eq 1 ]; then
  exit 0
fi
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
if grep -rlE ';;;|function \( \{' --include='*.ts' . >/dev/null 2>&1; then
  echo "static-verify: invalid syntax detected" >&2
  exit 1
fi
exit 0
"""

DISABLED_HOOK = "#!/usr/bin/env bash\nexit 0\n"


def compliant_manifest(
    *,
    hooks_dir: str = ".githooks",
    fixtures_enabled: tuple[str, ...] = (),
    fixtures_extra: str = "",
) -> str:
    fixtures_block = ""
    if fixtures_enabled:
        enabled = ", ".join(f'"{name}"' for name in fixtures_enabled)
        fixtures_block = f"\n[fixtures]\nenabled = [{enabled}]\n{fixtures_extra}"
    return (
        'policy_version = "2"\n\n'
        "[bootstrap]\n"
        f'entrypoint = "git config core.hooksPath {hooks_dir}"\n\n'
        "[stages.pre-commit]\n"
        'entrypoint = "git commit"\n'
        'categories = ["secret-scan"]\n\n'
        "[stages.pre-push]\n"
        'entrypoint = "git push"\n'
        'categories = ["static-verify"]\n\n'
        "[stages.premerge]\n"
        'entrypoint = "bash scripts/premerge.sh"\n'
        'categories = ["full-verify", "protected-escalation"]\n'
        f"{fixtures_block}"
    )


class ManifestRepo(unittest.TestCase):
    """A throwaway synthetic git repo — never a pilot repo under ~/Projects."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="lifecycle gate conformance ")
        self.repo = Path(self.tempdir.name) / "repo with spaces"
        self.repo.mkdir()
        run("git", "init", "-q", cwd=self.repo)
        run("git", "config", "user.email", "fixture@example.test", cwd=self.repo)
        run("git", "config", "user.name", "Fixture", cwd=self.repo)

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

    def commit(self, message: str = "fixture commit") -> None:
        run("git", "commit", "-q", "-m", message, cwd=self.repo)

    def write_manifest(self, text: str) -> None:
        self.write("lifecycle-gate.toml", text)

    def install_gitleaks_pre_commit(self, *, hooks_dir: str = ".githooks", disabled: bool = False) -> None:
        self.write(f"{hooks_dir}/pre-commit", DISABLED_HOOK if disabled else GITLEAKS_PRE_COMMIT, executable=True)

    def install_static_pre_push(self, *, hooks_dir: str = ".githooks", disabled: bool = False) -> None:
        self.write(f"{hooks_dir}/pre-push", DISABLED_HOOK if disabled else STATIC_PRE_PUSH, executable=True)

    def run_audit(self, *extra_args: str) -> tuple[subprocess.CompletedProcess[str], dict | None]:
        result = run(
            sys.executable, str(AUDIT), "--repo", str(self.repo), "--format", "json", *extra_args,
            cwd=self.repo, check=False,
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            report = None
        return result, report

    def find_check(self, report: dict, name: str) -> dict:
        return next(r for r in report["results"] if r["check"] == name)


class AuditStructuralTests(ManifestRepo):
    def test_audit_missing_manifest_reports_actionable_failure(self) -> None:
        run("git", "commit", "--allow-empty", "-qm", "init", cwd=self.repo)

        result, report = self.run_audit()

        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report["compliant"])
        manifest_check = self.find_check(report, "manifest")
        self.assertEqual(manifest_check["status"], "MISSING")
        self.assertIn("lifecycle-gate.toml", manifest_check["detail"])
        self.assertIn("lifecycle-gate.toml.example", manifest_check["detail"])

    def test_audit_missing_bootstrap_entrypoint_is_missing(self) -> None:
        self.write_manifest(
            """
            policy_version = "2"

            [stages.pre-commit]
            entrypoint = "git commit"
            categories = ["secret-scan"]

            [stages.pre-push]
            entrypoint = "git push"
            categories = ["static-verify"]

            [stages.premerge]
            entrypoint = "bash scripts/premerge.sh"
            categories = ["full-verify", "protected-escalation"]
            """
        )
        self.commit("manifest without bootstrap")

        result, report = self.run_audit("--skip-fixtures")

        self.assertEqual(result.returncode, 1)
        bootstrap_check = self.find_check(report, "bootstrap.entrypoint")
        self.assertEqual(bootstrap_check["status"], "MISSING")

    def test_audit_reports_premerge_as_not_exercised(self) -> None:
        self.write_manifest(compliant_manifest())
        self.commit("compliant, no fixtures")

        result, report = self.run_audit("--skip-fixtures")

        self.assertEqual(result.returncode, 0)
        premerge_check = self.find_check(report, "stages.premerge.behavioral")
        self.assertEqual(premerge_check["status"], "NOT-EXERCISED")

    def test_audit_does_not_penalize_husky(self) -> None:
        self.write("package.json", json.dumps({"devDependencies": {"husky": "^9.0.0"}}))
        self.write(".husky/pre-commit", DISABLED_HOOK, executable=True)
        self.write_manifest(compliant_manifest(hooks_dir=".husky"))
        self.commit("husky layout, structural check only")

        result, report = self.run_audit("--skip-fixtures")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(report["compliant"])
        # compliant=True already proves no check failed merely because husky is
        # present; this additionally proves no check specifically targets husky
        # as a mechanism (the removed LEGACY/dependency:husky machinery).
        for r in report["results"]:
            self.assertNotIn("husky", r["check"].lower())
            if r["status"] in ("FAIL", "WARN"):
                self.assertNotIn("husky", r["detail"].lower())


class AuditFixtureTests(ManifestRepo):
    @pytest.mark.slow
    def test_audit_reports_category_and_fixture_results(self) -> None:
        self.install_static_pre_push()
        self.write_manifest(compliant_manifest(fixtures_enabled=("delete-only-push",)))
        self.commit("compliant repo with delete-only-push fixture")

        result, report = self.run_audit()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(set(report.keys()), {"repo", "compliant", "results"})
        self.assertTrue(report["compliant"], report)
        for r in report["results"]:
            self.assertEqual(set(r.keys()), {"check", "status", "detail"})

        category_check = self.find_check(report, "stages.pre-push.categories")
        self.assertEqual(category_check["status"], "PASS")
        fixture_check = self.find_check(report, "fixture:delete-only-push")
        self.assertEqual(fixture_check["status"], "PASS", fixture_check["detail"])

    @pytest.mark.slow
    def test_audit_marks_fixture_fail_when_stage_not_live(self) -> None:
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")

        self.write("src/lib/ignored.ts", "export const ignored = true;\n")
        # gitleaks is on PATH, but the hook itself never invokes it — the probe
        # must observe "not blocked" and report stage-not-live, not vacuously PASS.
        self.install_gitleaks_pre_commit(disabled=True)
        self.write_manifest(
            compliant_manifest(
                fixtures_enabled=("biome-noop",),
                fixtures_extra='\n[fixtures.biome-noop]\nignored_path = "src/lib/ignored.ts"\n',
            )
        )
        self.commit("pre-commit hook wired but inert")

        result, report = self.run_audit()

        self.assertEqual(result.returncode, 1)
        fixture_check = self.find_check(report, "fixture:biome-noop")
        self.assertEqual(fixture_check["status"], "FAIL")
        self.assertIn("stage-not-live", fixture_check["detail"])

    @pytest.mark.slow
    def test_audit_passes_husky_layout_repo(self) -> None:
        self.write("src/keep.ts", "export const keep = 1;\n")
        self.install_static_pre_push(hooks_dir=".husky")
        self.write_manifest(compliant_manifest(hooks_dir=".husky", fixtures_enabled=("delete-only-push",)))
        self.commit("husky layout, working pre-push")

        result, report = self.run_audit()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(report["compliant"], report)
        fixture_check = self.find_check(report, "fixture:delete-only-push")
        self.assertEqual(fixture_check["status"], "PASS", fixture_check["detail"])

        # Same manifest, same hook manager wiring — only the script body changes
        # to a no-op. Mechanism (husky) stays constant; only liveness changes.
        self.install_static_pre_push(hooks_dir=".husky", disabled=True)
        self.commit("disable pre-push hook")

        result2, report2 = self.run_audit()

        self.assertEqual(result2.returncode, 1)
        self.assertFalse(report2["compliant"])
        fixture_check2 = self.find_check(report2, "fixture:delete-only-push")
        self.assertEqual(fixture_check2["status"], "FAIL", fixture_check2["detail"])


if __name__ == "__main__":
    unittest.main()
