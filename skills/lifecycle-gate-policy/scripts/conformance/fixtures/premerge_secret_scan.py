"""fixture: premerge-secret-scan — the entrypoint declared for `premerge` in a repo's manifest must
independently rescan for secrets, catching a commit whose pre-commit hook was bypassed
(`git commit --no-verify`) anywhere in the commit range vs the default branch, not only the tip
commit. A block attributed to a review/protected-path gate instead of secret-scan is not evidence
this category holds, so this fixture double-checks attribution and, independently of the
entrypoint's own exit code, re-runs gitleaks itself to assert at least one real finding — a config
with an empty ruleset must not be able to pass vacuously (see .orca/task-26-proposal.md and issue
#26's background on medicount's `.gitleaks.toml` missing `[extend] useDefault = true`).

Unlike the other fixtures in this package, this one reads and runs whichever command
[stages.premerge].entrypoint names, per manifest-schema.md's documented exception for this fixture
— it is the one fixture that actually drives premerge.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..harness import (
    BOOTSTRAP_FAILED_PREFIX,
    SYNTHETIC_SECRET,
    SYNTHETIC_SECRET_RELPATH,
    Result,
    scratch_clone,
)

NAME = "premerge-secret-scan"
STAGE = "premerge"
USES_EXTERNAL_PROBE = False

ATTRIBUTION_MARKERS = ("secret-scan", "gitleaks")


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def _current_branch(repo_path: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_path), capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _oracle_finding_count(repo_path: Path, log_range: str) -> int | None:
    """Independent gitleaks re-run — never reads the target repo's hook/script bytes, only its
    .gitleaks.toml ruleset (a repo-specific config fact, not "mechanism"). Same layer as
    harness.probe_pre_commit already requiring gitleaks on PATH."""
    fd, report_path = tempfile.mkstemp(suffix=".json")
    report = Path(report_path)
    try:
        subprocess.run(
            [
                "gitleaks", "detect", "--source", str(repo_path),
                "--log-opts", log_range, "--no-banner", "--redact",
                "--report-format", "json", "--report-path", str(report), "--exit-code", "0",
            ],
            capture_output=True, text=True, check=False,
        )
        try:
            return len(json.loads(report.read_text() or "[]"))
        except (json.JSONDecodeError, OSError):
            return None
    finally:
        report.unlink(missing_ok=True)


def run(source: Path, manifest: dict, cfg: dict) -> Result:
    if not _tool_available("gitleaks"):
        return Result(NAME, "SKIP", "gitleaks not found on PATH")

    entrypoint = ((manifest.get("stages") or {}).get("premerge") or {}).get("entrypoint")
    if not entrypoint:
        return Result(NAME, "SKIP", "manifest has no [stages.premerge].entrypoint")

    with scratch_clone(source, manifest) as repo:
        if repo.bootstrap_result is not None and repo.bootstrap_result.status != "PASS":
            return Result(NAME, "SKIP", f"{BOOTSTRAP_FAILED_PREFIX} {repo.bootstrap_result.detail}")

        branch = _current_branch(repo.path)
        remote_name = "origin"
        bare_dir = Path(tempfile.mkdtemp(prefix="lgp-premerge-origin-"))
        add_remote = repo.run(["git", "remote", "add", remote_name, str(bare_dir)])
        if add_remote.returncode != 0:
            return Result(NAME, "FAIL", f"could not add origin remote in scratch clone: {(add_remote.stderr or '').strip()[-300:]}")

        base_push = repo.run(["git", "push", remote_name, f"HEAD:refs/heads/{branch}"])
        if base_push.returncode != 0:
            return Result(NAME, "FAIL", f"could not push baseline to origin: {(base_push.stderr or '').strip()[-300:]}")

        repo.write(SYNTHETIC_SECRET_RELPATH, SYNTHETIC_SECRET)
        repo.stage(SYNTHETIC_SECRET_RELPATH)
        secret_commit = repo.run(["git", "commit", "--no-verify", "-m", "conformance: premerge-secret-scan fixture (pre-commit bypassed)"])
        if secret_commit.returncode != 0:
            return Result(NAME, "FAIL", f"could not create secret commit: {(secret_commit.stderr or '').strip()[-300:]}")

        # Harmless commit on top: the secret must not be the tip, so a scan that only looked at
        # HEAD (instead of the origin..HEAD range) cannot pass by accident.
        repo.write("__conformance_harmless.txt", "conformance: harmless commit on top of the secret\n")
        repo.stage("__conformance_harmless.txt")
        harmless_commit = repo.run(["git", "commit", "--no-verify", "-m", "conformance: harmless commit on top (range-scan probe)"])
        if harmless_commit.returncode != 0:
            return Result(NAME, "FAIL", f"could not create harmless commit: {(harmless_commit.stderr or '').strip()[-300:]}")

        entry = repo.run(["bash", "-lc", entrypoint])
        combined = f"{entry.stdout or ''}\n{entry.stderr or ''}".lower()
        blocked = entry.returncode != 0
        attributed = any(marker in combined for marker in ATTRIBUTION_MARKERS)

        finding_count = _oracle_finding_count(repo.path, f"{remote_name}/{branch}..HEAD")

        if blocked and attributed:
            if finding_count is None:
                return Result(NAME, "WARN", "premerge blocked and attributed to secret-scan, but the independent oracle re-run could not be parsed — treat as unconfirmed")
            if finding_count >= 1:
                return Result(NAME, "PASS", f"premerge blocked, attributed to secret-scan, oracle confirmed {finding_count} finding(s)")
            return Result(NAME, "WARN", "premerge blocked and attributed to secret-scan, but the independent oracle found 0 — a scanner that speaks without a working ruleset looks identical from the exit code alone; treat as unconfirmed")

        if blocked and not attributed:
            return Result(NAME, "FAIL", "premerge blocked, but not attributable to secret-scan (no gitleaks/secret-scan marker in its output) — likely blocked for an unrelated reason (review/protected-path), so this is not evidence secret-scan works")

        # not blocked
        if finding_count is not None and finding_count == 0:
            return Result(NAME, "WARN", "premerge did not block, and the independent oracle found 0 findings — the declared secret-scan category is ineffective, most likely an empty/misconfigured gitleaks ruleset (check .gitleaks.toml's [extend])")
        return Result(NAME, "FAIL", "premerge did not block a synthetic secret in the origin..HEAD range — secret-scan stage is not live")
