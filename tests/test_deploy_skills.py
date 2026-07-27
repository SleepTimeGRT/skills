import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-skills.sh"


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
