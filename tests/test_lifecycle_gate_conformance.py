from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
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
from conformance import harness  # noqa: E402  (needs SCRIPTS_DIR on sys.path)
from conformance.fixtures import premerge_secret_scan  # noqa: E402  (needs SCRIPTS_DIR on sys.path)


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
        'categories = ["full-verify", "protected-escalation", "secret-scan"]\n'
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
            categories = ["full-verify", "protected-escalation", "secret-scan"]
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
        # Structure-only: nothing ran, so this is explicitly not a compliance claim.
        self.assertEqual(report["verdict"], "STRUCTURE-ONLY")
        self.assertFalse(report["compliant"])
        self.assertFalse(
            [r for r in report["results"] if r["status"] in ("FAIL", "MISSING")],
            report,
        )
        # No check failed merely because husky is present; this additionally proves
        # no check specifically targets husky as a mechanism (the removed
        # LEGACY/dependency:husky machinery).
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
        self.assertEqual(set(report.keys()), {"repo", "verdict", "compliant", "results"})
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


NO_SECRET_SCAN_PREMERGE = r"""
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=main
git fetch --quiet origin "$DEFAULT_BRANCH"
if ! git merge-base --is-ancestor "origin/$DEFAULT_BRANCH" HEAD; then
  echo "[premerge] FAIL — behind origin/$DEFAULT_BRANCH" >&2
  exit 2
fi
CHANGED=$(git diff --name-only "origin/$DEFAULT_BRANCH..HEAD")
if [ -z "$CHANGED" ]; then
  echo "[premerge] FAIL — nothing to merge" >&2
  exit 2
fi
# no secret-scan stage in this implementation at all
echo "[premerge] REVIEW required" >&2
exit 4
"""

WRONG_RANGE_SCAN_WITH_DOWNSTREAM_BLOCK = r"""
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=main
git fetch --quiet origin "$DEFAULT_BRANCH"
if ! git merge-base --is-ancestor "origin/$DEFAULT_BRANCH" HEAD; then
  echo "[premerge] FAIL — behind origin/$DEFAULT_BRANCH" >&2
  exit 2
fi
CHANGED=$(git diff --name-only "origin/$DEFAULT_BRANCH..HEAD")
if [ -z "$CHANGED" ]; then
  echo "[premerge] FAIL — nothing to merge" >&2
  exit 2
fi
# wrong range on purpose: only the tip commit, never sees a secret buried underneath
echo "[premerge:secret-scan] PASS (0s)"
gitleaks detect --source . --log-opts "HEAD~1..HEAD" --no-banner --redact || true
# unconditional downstream block, unrelated to secret-scan
echo "[premerge] REVIEW required" >&2
exit 4
"""

NO_SCAN_REWRITES_TRACKED_FILE = r"""
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=main
git fetch --quiet origin "$DEFAULT_BRANCH"
if ! git merge-base --is-ancestor "origin/$DEFAULT_BRANCH" HEAD; then
  echo "[premerge] FAIL — behind origin/$DEFAULT_BRANCH" >&2
  exit 2
fi
CHANGED=$(git diff --name-only "origin/$DEFAULT_BRANCH..HEAD")
if [ -z "$CHANGED" ]; then
  echo "[premerge] FAIL — nothing to merge" >&2
  exit 2
fi
# no secret-scan stage at all; instead simulates codegen/formatter/lockfile rewriting a
# tracked file and committing it, then exiting clean
mkdir -p src
echo "generated: rewritten" > src/generated.txt
git add src/generated.txt
git commit -q --no-verify -m "codegen"
exit 0
"""

HANGS_FOREVER = "#!/usr/bin/env bash\nsleep 999\n"

DIRECT_CHILD_EXITS_DESCENDANT_HOLDS_STDOUT = r"""
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=main
git fetch --quiet origin "$DEFAULT_BRANCH"
if ! git merge-base --is-ancestor "origin/$DEFAULT_BRANCH" HEAD; then
  echo "[premerge] FAIL — behind origin/$DEFAULT_BRANCH" >&2
  exit 2
fi
CHANGED=$(git diff --name-only "origin/$DEFAULT_BRANCH..HEAD")
if [ -z "$CHANGED" ]; then
  echo "[premerge] FAIL — nothing to merge" >&2
  exit 2
fi
# direct child exits immediately (never reports a [premerge:secret-scan] line), but backgrounds a
# descendant that keeps the stdout pipe open well past any reasonable timeout — the shape
# task-26-review-round3 Finding F1 exists to catch.
(sleep 15) &
exit 0
"""

def worktree_only_scan_script(secret_relpath: str) -> str:
    """A stub premerge entrypoint that decides purely from what's checked out on disk right now
    (`test -f`), never from git history/the commit range — the shape task-26-review-round3
    Finding F2 exists to catch. Checks file *existence*, not content, so the check itself never
    needs to embed the secret payload's own text in the script's source (which would make the
    check self-match on the script file, independent of whatever is actually on disk)."""
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        REPO_ROOT=$(git rev-parse --show-toplevel)
        cd "$REPO_ROOT"
        DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)
        [ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=main
        git fetch --quiet origin "$DEFAULT_BRANCH"
        if ! git merge-base --is-ancestor "origin/$DEFAULT_BRANCH" HEAD; then
          echo "[premerge] FAIL — behind origin/$DEFAULT_BRANCH" >&2
          exit 2
        fi
        CHANGED=$(git diff --name-only "origin/$DEFAULT_BRANCH..HEAD")
        if [ -z "$CHANGED" ]; then
          echo "[premerge] FAIL — nothing to merge" >&2
          exit 2
        fi
        if [ -f "{secret_relpath}" ]; then
          echo "[premerge:secret-scan] FAIL (exit 1, 0s) — log: worktree-only scan found the secret file on disk" >&2
          exit 1
        fi
        echo "[premerge:secret-scan] PASS (0s)"
        exit 0
        """
    )


class PremergeSecretScanFixtureTests(ManifestRepo):
    """Behavioral coverage for the premerge-secret-scan fixture — the one fixture that actually
    drives the declared premerge entrypoint, by running it once and watching stdout for the
    reference implementation's own `[premerge:secret-scan] PASS|FAIL` line (see
    premerge_secret_scan.py's module docstring for why two earlier designs — a loose substring
    search, then a secret-free/secret-added differential double-run — were rejected)."""

    def install_reference_premerge(self, *, gitleaks_toml: str | None, verify_cmd: str = "true") -> None:
        premerge_src = (SKILL_DIR / "assets" / "scripts" / "premerge.sh").read_text(encoding="utf-8")
        token_gate_src = (SKILL_DIR / "assets" / "scripts" / "token-gate.sh").read_text(encoding="utf-8")
        self.write("scripts/premerge.sh", premerge_src, executable=True)
        self.write("scripts/token-gate.sh", token_gate_src, executable=True)
        self.write("scripts/premerge.conf.sh", f'VERIFY_CMD="{verify_cmd}"\n')
        if gitleaks_toml is not None:
            self.write(".gitleaks.toml", gitleaks_toml)

    @pytest.mark.slow
    def test_reference_premerge_blocks_and_oracle_confirms_finding(self) -> None:
        """case a) — working ruleset: PASS."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.install_reference_premerge(gitleaks_toml="[extend]\nuseDefault = true\n")
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("reference premerge with working gitleaks ruleset")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "PASS", fixture_check["detail"])

    @pytest.mark.slow
    def test_reference_premerge_with_empty_ruleset_warns_not_fails(self) -> None:
        """case b) — no [extend] block (a real pilot repo's actual shape at one point: finding=0
        against a synthetic secret because gitleaks itself runs cleanly with zero [[rules]]). The
        stage's own line says PASS, but a live scan that lets a known-detectable synthetic secret
        through is itself the vacuous-ruleset signal (see premerge_secret_scan.run()'s final
        branch) — always WARN, never FAIL (FAIL is reserved for the stage never reporting at all,
        case c below) and never PASS. A WARN here must also drag the overall verdict to
        UNVERIFIED/exit 3 — assert both, since that link (audit.INCONCLUSIVE_STATUSES) is exactly
        what the vacuous-pass AC depends on."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        # A *valid* allowlist (matching the shape actually found in a pilot repo's checked-in
        # .gitleaks.toml — `[allowlist]` needs at least one of paths/regexes/commits/stopwords or
        # gitleaks refuses to load the config at all and exits 1 on *any* run, clean or not,
        # which is a different failure mode than "loads fine with zero [[rules]]").
        self.install_reference_premerge(
            gitleaks_toml="[allowlist]\ndescription = \"no [extend] block — vacuous-ruleset repro\"\n"
            "paths = ['''\\.env\\.example''']\n"
        )
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("reference premerge with empty gitleaks ruleset (vacuous-pass repro)")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "WARN", fixture_check["detail"])
        self.assertEqual(report["verdict"], "UNVERIFIED", report)
        self.assertEqual(result.returncode, 3)

    @pytest.mark.slow
    def test_premerge_without_secret_scan_stage_fails(self) -> None:
        """case c) — declared premerge entrypoint never runs gitleaks at all and never prints a
        [premerge:secret-scan] line; it just blocks unconditionally (review requirement). Runs to
        completion (no timeout involved) without ever reporting — FAIL, the only case that is."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.write("scripts/premerge.sh", NO_SECRET_SCAN_PREMERGE, executable=True)
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("premerge entrypoint with no secret-scan stage")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "FAIL", fixture_check["detail"])
        self.assertIn("without ever reporting", fixture_check["detail"])

    @pytest.mark.slow
    def test_wrong_range_scan_masked_by_downstream_block_is_not_falsely_passed(self) -> None:
        """Regression for task-26-review.md Finding 1 (Critical, round 1): a premerge entrypoint
        that (a) scans the wrong range (tip-only, HEAD~1..HEAD — never sees a secret buried under
        a later commit) and (b) unconditionally blocks every non-empty diff for an unrelated
        reason (review) used to earn a false `PASS` under the original substring-marker design.
        Under the current single-run design, the entrypoint's own line says PASS (it truly did not
        block), which — combined with the independent oracle confirming a real finding in range —
        is exactly the vacuous-ruleset shape: WARN, never PASS. The process is also killed the
        instant that line appears, so the "unconditional downstream block" this stub adds after
        the scan is never even reached; this doubles as evidence for NEW-3-A below."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.write("scripts/premerge.sh", WRONG_RANGE_SCAN_WITH_DOWNSTREAM_BLOCK, executable=True)
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("premerge entrypoint: wrong-range scan + unconditional downstream block")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertNotEqual(fixture_check["status"], "PASS", fixture_check["detail"])
        self.assertEqual(fixture_check["status"], "WARN", fixture_check["detail"])

    @pytest.mark.slow
    def test_worktree_only_scanner_is_not_falsely_certified_as_range_scan_f2_regression(self) -> None:
        """Regression for task-26-review-round3.md Finding F2: the fixture's harmless commit must
        actually `git rm` the synthetic secret file, not merely add a new file on top of it. Before
        that fix, the secret stayed physically present in the checked-out tree even after the
        harmless commit, so a worktree-only scanner (this stub: `grep` over files on disk, never
        the commit range) would still stumble onto it and report FAIL — and the fixture's own
        oracle re-run (a genuine range scan) would also find it in secret_commit's diff, so the two
        would agree and the fixture would wrongly return PASS, certifying "range-scanning" a
        stub that never actually looked at git history. With the secret removed from the worktree
        by the harmless commit, this same stub now finds nothing on disk and reports PASS (did not
        block) — while the independent oracle range-scan still finds it in history — so the
        fixture must return WARN, correctly refusing to certify this stub's capability."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.write("scripts/premerge.sh", worktree_only_scan_script(harness.SYNTHETIC_SECRET_RELPATH), executable=True)
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("premerge entrypoint: worktree-only scan, never the commit range")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "WARN", fixture_check["detail"])
        self.assertNotEqual(fixture_check["status"], "PASS", fixture_check["detail"])

    @pytest.mark.slow
    def test_verify_dependency_never_reached_new1_regression(self) -> None:
        """Regression for task-26-review-round2.md NEW-1: the differential design forced a
        secret-free baseline run to complete the entrypoint's *entire* chain, including
        `VERIFY_CMD`, which every pilot repo's real config needs installed dependencies for inside
        a scratch clone that intentionally never installs any (manifest-schema.md's bootstrap
        constraint: "wiring only, never a dependency install"). Set `VERIFY_CMD` to a command that
        does not exist at all — if this fixture ever reaches it, the run fails loudly and
        differently from the assertions below. A working ruleset must still report PASS,
        proving verify is never invoked."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.install_reference_premerge(
            gitleaks_toml="[extend]\nuseDefault = true\n",
            verify_cmd="node_modules/.bin/definitely-does-not-exist-checker",
        )
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("reference premerge with a VERIFY_CMD that would fail if ever reached")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "PASS", fixture_check["detail"])
        self.assertNotIn("127", fixture_check["detail"])

    @pytest.mark.slow
    def test_review_exemption_never_reached_new3a_regression(self) -> None:
        """Regression for task-26-review-round2.md NEW-3 (the review-exemption variant): a
        `REVIEW_EXEMPT_REGEX` narrowed to `docs/` only would make the reference implementation's
        review gate (step 5) block this fixture's own probe files (all `.txt`, at repo root) if
        that gate were ever reached. It must not be — the process is killed right after the
        secret-scan stage's own line, before step 5."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        premerge_src = (SKILL_DIR / "assets" / "scripts" / "premerge.sh").read_text(encoding="utf-8")
        token_gate_src = (SKILL_DIR / "assets" / "scripts" / "token-gate.sh").read_text(encoding="utf-8")
        self.write("scripts/premerge.sh", premerge_src, executable=True)
        self.write("scripts/token-gate.sh", token_gate_src, executable=True)
        self.write("scripts/premerge.conf.sh", 'VERIFY_CMD="true"\nREVIEW_EXEMPT_REGEX="(^|/)docs/"\n')
        self.write(".gitleaks.toml", "[extend]\nuseDefault = true\n")
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("reference premerge with a review exemption narrow enough to catch this fixture's probe files")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "PASS", fixture_check["detail"])

    @pytest.mark.slow
    def test_no_scan_but_tracked_rewrite_still_fails_new2_regression(self) -> None:
        """Regression for task-26-review-round2.md NEW-2: under the differential design, an
        entrypoint with zero secret-scanning that merely rewrote a tracked file (simulating
        codegen/formatters/lockfiles) between its two runs could earn a false PASS, because the
        second run's dirty-tree precondition failure looked identical to "newly blocked by the
        secret." This design runs the entrypoint exactly once, so there is no second run for a
        rewrite to corrupt — an entrypoint that never prints the stage's line must FAIL regardless
        of what else it does to the tree."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.write("scripts/premerge.sh", NO_SCAN_REWRITES_TRACKED_FILE, executable=True)
        self.write_manifest(compliant_manifest(fixtures_enabled=("premerge-secret-scan",)))
        self.commit("premerge entrypoint with no scan, rewrites a tracked file, exits 0")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertNotEqual(fixture_check["status"], "PASS", fixture_check["detail"])
        self.assertEqual(fixture_check["status"], "FAIL", fixture_check["detail"])

    @pytest.mark.slow
    def test_timeout_is_warn_not_fail_new3b_regression(self) -> None:
        """Regression for task-26-review-round2.md NEW-3 (the timeout variant): "no evidence"
        must never be encoded as FAIL (a status reserved for an observed violation). An entrypoint
        that never prints anything and never exits must resolve as WARN (→ UNVERIFIED/exit 3) once
        the fixture's timeout elapses, not FAIL (→ NON-COMPLIANT/exit 1)."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.write("scripts/premerge.sh", HANGS_FOREVER, executable=True)
        self.write_manifest(
            compliant_manifest(
                fixtures_enabled=("premerge-secret-scan",),
                fixtures_extra="\n[fixtures.premerge-secret-scan]\ntimeout_seconds = 3\n",
            )
        )
        self.commit("premerge entrypoint that hangs forever")

        result, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "WARN", fixture_check["detail"])
        self.assertIn("exceeded", fixture_check["detail"])
        self.assertNotEqual(report["verdict"], "NON-COMPLIANT", report)

    @pytest.mark.slow
    def test_orphaned_descendant_does_not_defeat_timeout_f1_regression(self) -> None:
        """Regression for task-26-review-round3.md Finding F1: the direct child process can exit
        while a background descendant it spawned keeps holding the stdout pipe open. The watchdog
        must kill the whole process group once timeout_seconds elapses regardless of whether the
        direct child has already exited — previously it checked proc.poll() first and did nothing
        in that case, so the read blocked until the descendant died on its own (here, 15s) and the
        result was then misclassified as FAIL (no evidence treated as a violation) instead of WARN.
        Asserts both: the wall time is actually bounded near timeout_seconds, and the status is
        WARN, not FAIL."""
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")
        self.write("scripts/premerge.sh", DIRECT_CHILD_EXITS_DESCENDANT_HOLDS_STDOUT, executable=True)
        self.write_manifest(
            compliant_manifest(
                fixtures_enabled=("premerge-secret-scan",),
                fixtures_extra="\n[fixtures.premerge-secret-scan]\ntimeout_seconds = 3\n",
            )
        )
        self.commit("premerge entrypoint: direct child exits, descendant holds stdout open")

        t0 = time.monotonic()
        result, report = self.run_audit()
        elapsed = time.monotonic() - t0

        fixture_check = self.find_check(report, "fixture:premerge-secret-scan")
        self.assertEqual(fixture_check["status"], "WARN", fixture_check["detail"])
        self.assertIn("exceeded", fixture_check["detail"])
        self.assertLess(elapsed, 10, f"watchdog did not bound wall time: took {elapsed:.1f}s against a 3s timeout and a 15s descendant")
        self.assertNotEqual(report["verdict"], "NON-COMPLIANT", report)


class PilotRepoOracleTests(unittest.TestCase):
    """Exercises premerge_secret_scan.run() directly against real pilot-repo .gitleaks.toml
    configs, inside disposable scratch clones only (the source repo is only ever `git clone
    --local`-read, never written to)."""

    def _run_against(self, repo_name: str, expected_statuses: tuple[str, ...] | None = None):
        pilot_path = Path.home() / "Projects" / repo_name
        if not (pilot_path / ".git").is_dir():
            self.skipTest(f"{pilot_path} not present on this machine")
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")

        with tempfile.TemporaryDirectory(prefix="lgp-pilot-oracle-") as tmp_str:
            tmp = Path(tmp_str)
            scratch = tmp / "repo"
            run("git", "clone", "--local", "--quiet", str(pilot_path), str(scratch), cwd=tmp)
            run("git", "-C", str(scratch), "remote", "remove", "origin", cwd=tmp, check=False)
            run("git", "-C", str(scratch), "config", "user.email", "pilot-oracle@lifecycle-gate-policy.invalid", cwd=tmp)
            run("git", "-C", str(scratch), "config", "user.name", "pilot oracle test", cwd=tmp)

            premerge_src = (SKILL_DIR / "assets" / "scripts" / "premerge.sh").read_text(encoding="utf-8")
            token_gate_src = (SKILL_DIR / "assets" / "scripts" / "token-gate.sh").read_text(encoding="utf-8")
            (scratch / "scripts").mkdir(parents=True, exist_ok=True)
            (scratch / "scripts" / "premerge.sh").write_text(premerge_src)
            (scratch / "scripts" / "premerge.sh").chmod(0o755)
            (scratch / "scripts" / "token-gate.sh").write_text(token_gate_src)
            (scratch / "scripts" / "token-gate.sh").chmod(0o755)
            # Deliberately broken, not stubbed to "true": if this fixture ever reached VERIFY_CMD
            # (it must not — see NEW-1 in task-26-review-round2.md), this command would fail
            # loudly and differently from the PASS/WARN assertions below, proving verify really
            # is never invoked even against real pilot .gitleaks.toml configs.
            (scratch / "scripts" / "premerge.conf.sh").write_text(
                'VERIFY_CMD="node_modules/.bin/definitely-does-not-exist-checker"\n'
            )
            run(
                "git", "-C", str(scratch), "add", "-f",
                "scripts/premerge.sh", "scripts/token-gate.sh", "scripts/premerge.conf.sh",
                cwd=tmp,
            )
            run(
                "git", "-C", str(scratch), "commit", "--no-verify", "-qm",
                "inject reference premerge implementation for pilot oracle validation",
                cwd=tmp,
            )

            manifest = {
                "policy_version": "2",
                "bootstrap": {"entrypoint": "true"},
                "stages": {
                    "pre-commit": {"entrypoint": "git commit", "categories": ["secret-scan"]},
                    "pre-push": {"entrypoint": "git push", "categories": ["static-verify"]},
                    "premerge": {
                        "entrypoint": "bash scripts/premerge.sh",
                        "categories": ["full-verify", "protected-escalation", "secret-scan"],
                    },
                },
                "fixtures": {"enabled": ["premerge-secret-scan"]},
            }

            result = premerge_secret_scan.run(scratch, manifest, {})
            if expected_statuses is not None:
                self.assertIn(
                    result.status, expected_statuses,
                    f"{repo_name}: expected one of {expected_statuses}, got {result.status}: {result.detail}",
                )
            return result

    def test_medicount_ruleset_state_is_caught_correctly(self) -> None:
        """medicount's `.gitleaks.toml` may or may not currently have `[extend] useDefault = true`
        — the synthetic case in PremergeSecretScanFixtureTests already covers the missing-extend
        shape as a fixed, controlled repro (`test_reference_premerge_with_empty_ruleset_warns_not_fails`).
        This pilot test intentionally does not hardcode either state: a hardcoded `WARN` would start
        failing — for the right reason (a real fix to medicount) but as an unrelated, confusing test
        break — the moment someone corrects medicount's ruleset. `PASS` (fixed) and `WARN` (still
        broken) are both evidence the oracle is doing its job; only `FAIL`/`SKIP` here would
        indicate an actual regression in the fixture or the pilot checkout.

        Accepting either status here is not, by itself, discriminating (a fixture that always
        returned PASS would also pass this line) — see
        test_medicount_status_matches_independently_measured_finding_count below for the check
        that actually proves the vacuous-ruleset case is caught."""
        self._run_against("medicount", ("PASS", "WARN"))

    def test_medicount_status_matches_independently_measured_finding_count(self) -> None:
        """review-round3.md AC #6: the assertion above cannot tell a vacuous (0-rule) ruleset
        apart from a working one, since it accepts both outcomes unconditionally. This test
        closes that gap by parsing the oracle finding count premerge_secret_scan.run() itself
        measured (an independent `gitleaks detect` re-run over the same commit range, reported
        verbatim in the result detail) and asserting the fixture's status is the correct function
        of that count: >=1 real finding must mean PASS, and 0 findings must mean WARN. A future
        regression that reported PASS despite 0 findings (i.e. certified a vacuous ruleset as
        clean) would fail this assertion even though it would have silently passed the lenient
        tuple check above."""
        result = self._run_against("medicount")
        self.assertIn(result.status, ("PASS", "WARN"), result.detail)
        match = re.search(r"oracle found (\d+) finding", result.detail)
        self.assertIsNotNone(match, f"could not find an oracle finding count in: {result.detail!r}")
        finding_count = int(match.group(1))
        if finding_count >= 1:
            self.assertEqual(result.status, "PASS", result.detail)
        else:
            self.assertEqual(result.status, "WARN", result.detail)

    def test_samhaengsi_working_ruleset_passes(self) -> None:
        self._run_against("toss-samhaengsi", ("PASS",))

    def test_goldrush_no_config_file_uses_default_ruleset_and_passes(self) -> None:
        self._run_against("toss-space-goldrush", ("PASS",))


if __name__ == "__main__":
    unittest.main()


# A pre-commit hook whose scanner runs and speaks but never objects. This is the
# medicount shape found by the task-level gate: a scanner config that replaces the
# default ruleset leaves the stage live with zero rules. "Live" and "effective" are
# different claims and the report must not collapse them.
INEFFECTIVE_SCANNER_PRE_COMMIT = """\
#!/usr/bin/env bash
set -euo pipefail
printf 'scan: 0 rules loaded, no findings\\n' >&2
exit 0
"""


class ProbeReportingTests(ManifestRepo):
    """Semantics added after the task-level gate ran against real pilot repositories."""

    @pytest.mark.slow
    def test_probe_warns_when_stage_runs_but_does_not_block(self) -> None:
        if shutil.which("gitleaks") is None:
            self.skipTest("gitleaks not installed")

        self.write("src/lib/ignored.ts", "export const ignored = true;\n")
        self.write(".githooks/pre-commit", INEFFECTIVE_SCANNER_PRE_COMMIT, executable=True)
        self.write_manifest(
            compliant_manifest(
                fixtures_enabled=("biome-noop",),
                fixtures_extra='\n[fixtures.biome-noop]\nignored_path = "src/lib/ignored.ts"\n',
            )
        )
        self.commit("pre-commit stage live but scanner has no rules")

        _, report = self.run_audit()

        # The stage fires, so the fixture is not vacuous and still reports its own verdict.
        fixture_check = self.find_check(report, "fixture:biome-noop")
        self.assertEqual(fixture_check["status"], "PASS", fixture_check["detail"])

        # ...and the ineffective scanner is a finding in its own right, on its own line.
        probe_check = self.find_check(report, "probe:pre-commit")
        self.assertEqual(probe_check["status"], "WARN", probe_check["detail"])
        self.assertIn("did not block", probe_check["detail"])

    @pytest.mark.slow
    def test_biome_noop_skips_when_path_is_not_formatter_processed(self) -> None:
        self.write("docs/notes.md", "# notes\n")
        self.install_gitleaks_pre_commit()
        self.write_manifest(
            compliant_manifest(
                fixtures_enabled=("biome-noop",),
                fixtures_extra='\n[fixtures.biome-noop]\nignored_path = "docs/notes.md"\n',
            )
        )
        self.commit("ignored_path the formatter would never process")

        _, report = self.run_audit()

        fixture_check = self.find_check(report, "fixture:biome-noop")
        self.assertEqual(fixture_check["status"], "SKIP", fixture_check["detail"])
        self.assertIn("fixture-inapplicable", fixture_check["detail"])


class FailClosedVerdictTests(ManifestRepo):
    """The verdict layer must never certify a repository it did not observe.

    Reproduces the fail-open case found in diff review: a repo with no hooks at
    all, a bootstrap that cannot run, and a misspelled fixture was reported
    COMPLIANT with exit 0 because SKIP and WARN were non-terminal.
    """

    def test_audit_does_not_certify_repo_with_no_working_gates(self) -> None:
        self.write_manifest(
            compliant_manifest(fixtures_enabled=("delete-only-push", "typo-fixture"))
            .replace('entrypoint = "git config core.hooksPath .githooks"', 'entrypoint = "false"')
        )
        self.commit("no hooks, bootstrap always fails, one fixture name misspelled")

        result, report = self.run_audit()

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotEqual(report["verdict"], "COMPLIANT")
        self.assertFalse(report["compliant"])
        # A failing bootstrap is promoted out of the fixture detail into its own
        # terminal line: nothing downstream of it can produce evidence.
        bootstrap_check = self.find_check(report, "bootstrap.behavioral")
        self.assertEqual(bootstrap_check["status"], "FAIL")
        self.assertEqual(report["verdict"], "NON-COMPLIANT")

    def test_audit_does_not_certify_when_no_fixtures_declared(self) -> None:
        self.write_manifest(compliant_manifest())
        self.commit("structurally valid, declares no fixtures")

        result, report = self.run_audit()

        self.assertEqual(report["verdict"], "UNVERIFIED")
        self.assertFalse(report["compliant"])
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.find_check(report, "fixtures")["status"], "SKIP")

    @pytest.mark.slow
    def test_audit_does_not_certify_when_a_fixture_skips(self) -> None:
        # The fixture cannot run (no ignored_path configured), so nothing observed
        # the pre-commit stage. A SKIP must not be promoted to compliance.
        self.install_gitleaks_pre_commit()
        self.install_static_pre_push()
        self.write_manifest(compliant_manifest(fixtures_enabled=("biome-noop", "delete-only-push")))
        self.commit("one fixture observes, one skips")

        result, report = self.run_audit()

        self.assertEqual(self.find_check(report, "fixture:biome-noop")["status"], "SKIP")
        self.assertEqual(self.find_check(report, "fixture:delete-only-push")["status"], "PASS")
        self.assertEqual(report["verdict"], "UNVERIFIED")
        self.assertEqual(result.returncode, 3)

    @pytest.mark.slow
    def test_advisory_structural_warning_does_not_block_compliance(self) -> None:
        # compliant_manifest() omits the premerge 'e2e' category, which is advice
        # about the declaration, not missing evidence. It must not downgrade a repo
        # whose fixtures actually observed the policy holding.
        self.install_static_pre_push()
        self.write_manifest(compliant_manifest(fixtures_enabled=("delete-only-push",)))
        self.commit("advisory warning present, behavior observed")

        result, report = self.run_audit()

        e2e_advice = [
            r for r in report["results"]
            if r["check"] == "stages.premerge.categories" and r["status"] == "WARN"
        ]
        self.assertTrue(e2e_advice, report)
        self.assertEqual(report["verdict"], "COMPLIANT")
        self.assertEqual(result.returncode, 0)
