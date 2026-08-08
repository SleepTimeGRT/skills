import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-skills.sh"
SET_FILE = REPO_ROOT / "skills" / "orca-set.version"


def test_deploy_uses_user_scope_and_removes_managed_legacy_copy(tmp_path):
    deploy_home = tmp_path / "home with spaces"
    legacy_skill = deploy_home / ".codex" / "skills" / "orca-workflow"
    legacy_skill.mkdir(parents=True)
    (legacy_skill / ".installed-version.json").write_text(
        '{"version":"v0.0.0","commit":"old","date":"old","hash":"old"}\n'
    )
    (legacy_skill / "SKILL.md").write_text("legacy copy\n")

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "orca-workflow"],
        cwd=REPO_ROOT,
        env={**os.environ, "DEPLOY_HOME": str(deploy_home)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (deploy_home / ".agents" / "skills" / "orca-workflow" / "SKILL.md").is_file()
    assert not legacy_skill.exists()
    assert (deploy_home / ".claude" / "skills" / "orca-workflow").is_symlink()


def _set_version_and_members():
    lines = [l for l in SET_FILE.read_text().splitlines() if l.strip()]
    return lines[0], lines[1:]


def test_deploying_one_set_member_deploys_whole_set_at_set_version(tmp_path):
    deploy_home = tmp_path / "home"
    set_version, members = _set_version_and_members()

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), members[0]],
        cwd=REPO_ROOT,
        env={**os.environ, "DEPLOY_HOME": str(deploy_home)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    for name in members:
        meta_path = deploy_home / ".agents" / "skills" / name / ".installed-version.json"
        assert meta_path.is_file(), f"{name} not deployed with the set"
        assert json.loads(meta_path.read_text())["version"] == set_version


def test_version_flag_conflicting_with_set_version_aborts(tmp_path):
    deploy_home = tmp_path / "home"
    set_version, members = _set_version_and_members()
    assert set_version != "v9.9.9"

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--version", "v9.9.9", members[0]],
        cwd=REPO_ROOT,
        env={**os.environ, "DEPLOY_HOME": str(deploy_home)},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "orca-set.version" in result.stderr
    assert not (deploy_home / ".agents" / "skills" / members[0]).exists()
