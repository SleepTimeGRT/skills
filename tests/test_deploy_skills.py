import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-skills.sh"
SKILL = "token-efficient-gates"


def _run(deploy_home, *args):
    return subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DEPLOY_HOME": str(deploy_home)},
        capture_output=True,
        text=True,
    )


def test_deploy_uses_user_scope_and_removes_managed_legacy_copy(tmp_path):
    deploy_home = tmp_path / "home with spaces"
    legacy_skill = deploy_home / ".codex" / "skills" / SKILL
    legacy_skill.mkdir(parents=True)
    (legacy_skill / ".installed-version.json").write_text(
        '{"version":"v0.0.0","commit":"old","date":"old","hash":"old"}\n'
    )
    (legacy_skill / "SKILL.md").write_text("legacy copy\n")

    result = _run(deploy_home, SKILL)

    assert result.returncode == 0, result.stderr
    assert (deploy_home / ".agents" / "skills" / SKILL / "SKILL.md").is_file()
    assert not legacy_skill.exists()
    assert (deploy_home / ".claude" / "skills" / SKILL).is_symlink()


def test_version_flag_is_recorded_and_kept_on_redeploy(tmp_path):
    deploy_home = tmp_path / "home"

    first = _run(deploy_home, "--version", "v1.2.3", SKILL)
    assert first.returncode == 0, first.stderr
    meta_path = deploy_home / ".agents" / "skills" / SKILL / ".installed-version.json"
    assert json.loads(meta_path.read_text())["version"] == "v1.2.3"

    second = _run(deploy_home, SKILL)
    assert second.returncode == 0, second.stderr
    assert json.loads(meta_path.read_text())["version"] == "v1.2.3"
