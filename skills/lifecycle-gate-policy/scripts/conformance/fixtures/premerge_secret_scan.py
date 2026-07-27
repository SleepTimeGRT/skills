"""fixture: premerge-secret-scan — the entrypoint declared for `premerge` in a repo's manifest must
independently rescan for secrets, catching a commit whose pre-commit hook was bypassed
(`git commit --no-verify`) anywhere in the commit range vs the default branch, not only the tip
commit. A block that would have happened even without the secret is not evidence this category
holds, so this fixture runs the entrypoint twice — once on a secret-free baseline, once after the
secret is added — and only counts a *new* block as attributable. It also, independently of the
entrypoint's own exit code, re-runs gitleaks itself to assert at least one real finding — a config
with an empty ruleset must not be able to pass vacuously (see issue #26's background on a pilot
repo's `.gitleaks.toml` missing `[extend] useDefault = true`).

Unlike the other fixtures in this package, this one reads and runs whichever command
[stages.premerge].entrypoint names, per manifest-schema.md's documented exception for this fixture
— it is the one fixture that actually drives premerge. That means it executes the target repo's
real premerge chain (verify/e2e included) inside the scratch clone, twice; a repo whose entrypoint
is expensive should set `[fixtures.premerge-secret-scan].timeout_seconds` (see DEFAULT_TIMEOUT_SECONDS
below) to bound that cost. Side effects the entrypoint itself makes (network calls, emulators, etc.)
are the target repo's own responsibility, not something this fixture can sandbox away, since driving
that entrypoint faithfully is the whole point.
"""

from __future__ import annotations

import json
import os
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

DEFAULT_TIMEOUT_SECONDS = 300


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
    os.close(fd)
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

    timeout_seconds = cfg.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)

    with scratch_clone(source, manifest) as repo:
        if repo.bootstrap_result is not None and repo.bootstrap_result.status != "PASS":
            return Result(NAME, "SKIP", f"{BOOTSTRAP_FAILED_PREFIX} {repo.bootstrap_result.detail}")

        branch = _current_branch(repo.path)
        # Named "origin" (not harness's default "conformance"): premerge-style entrypoints
        # hardcode `git fetch origin ...` / `refs/remotes/origin/HEAD`. Created via
        # repo.temp_remote() so its bare dir lives under repo._tmp_root and is guaranteed
        # cleaned up by scratch_clone()'s own teardown — no separate cleanup needed here.
        remote_name = repo.temp_remote(name="origin")

        base_push = repo.run(["git", "push", remote_name, f"HEAD:refs/heads/{branch}"])
        if base_push.returncode != 0:
            return Result(NAME, "FAIL", f"could not push baseline to origin: {(base_push.stderr or '').strip()[-300:]}")

        # Premerge entrypoints commonly fall back to a hardcoded "main" default branch when
        # refs/remotes/origin/HEAD isn't set. A plain `git remote add` + `git push` never
        # creates that symbolic ref, so without this the fixture would misattribute a
        # branch-name mismatch (e.g. a pilot repo not checked out on "main") to secret-scan
        # never having run.
        set_head = repo.run(["git", "remote", "set-head", remote_name, branch])
        if set_head.returncode != 0:
            return Result(NAME, "FAIL", f"could not set {remote_name}/HEAD to {branch}: {(set_head.stderr or '').strip()[-300:]}")

        # ---- clean baseline: a real diff vs origin, but no secret in it -----------------------
        # Run the entrypoint BEFORE any secret exists. Any block observed here cannot be caused by
        # secret-scan — attributing it anyway (e.g. by grepping the entrypoint's output for a
        # "secret-scan"/"gitleaks" marker) is exactly how an unrelated downstream gate (review,
        # protected-path, a scanner that speaks without actually blocking) can be mistaken for
        # secret-scan working. Comparing this run against the post-secret run below is the
        # differential the fixture's verdict rests on instead.
        repo.write("__conformance_clean_baseline.txt", "conformance: clean baseline commit (no secret yet)\n")
        repo.stage("__conformance_clean_baseline.txt")
        clean_commit = repo.run(["git", "commit", "--no-verify", "-m", "conformance: clean baseline (range-scan + attribution probe)"])
        if clean_commit.returncode != 0:
            return Result(NAME, "FAIL", f"could not create clean baseline commit: {(clean_commit.stderr or '').strip()[-300:]}")

        clean_run = repo.run(["bash", "-lc", entrypoint], timeout=timeout_seconds)
        if clean_run.returncode is None:
            return Result(NAME, "FAIL", f"premerge entrypoint exceeded {timeout_seconds}s on the secret-free baseline — cannot establish attribution; raise [fixtures.premerge-secret-scan].timeout_seconds if this repo's chain is legitimately slow")
        if clean_run.returncode != 0:
            tail = f"{(clean_run.stdout or '')}{(clean_run.stderr or '')}".strip()[-300:]
            return Result(NAME, "FAIL", f"premerge already blocks a secret-free baseline (exit {clean_run.returncode}) — any later block cannot be attributed to secret-scan, so this run produces no evidence about it: {tail}")

        # ---- secret run: same clone, secret added on top, buried under one more commit --------
        # The secret must not be the tip, so a scan that only looked at HEAD (instead of the
        # origin..HEAD range) cannot pass by accident.
        repo.write(SYNTHETIC_SECRET_RELPATH, SYNTHETIC_SECRET)
        repo.stage(SYNTHETIC_SECRET_RELPATH)
        secret_commit = repo.run(["git", "commit", "--no-verify", "-m", "conformance: premerge-secret-scan fixture (pre-commit bypassed)"])
        if secret_commit.returncode != 0:
            return Result(NAME, "FAIL", f"could not create secret commit: {(secret_commit.stderr or '').strip()[-300:]}")

        repo.write("__conformance_harmless.txt", "conformance: harmless commit on top of the secret\n")
        repo.stage("__conformance_harmless.txt")
        harmless_commit = repo.run(["git", "commit", "--no-verify", "-m", "conformance: harmless commit on top (range-scan probe)"])
        if harmless_commit.returncode != 0:
            return Result(NAME, "FAIL", f"could not create harmless commit: {(harmless_commit.stderr or '').strip()[-300:]}")

        secret_run = repo.run(["bash", "-lc", entrypoint], timeout=timeout_seconds)
        if secret_run.returncode is None:
            return Result(NAME, "FAIL", f"premerge entrypoint exceeded {timeout_seconds}s after the secret was added — inconclusive; raise [fixtures.premerge-secret-scan].timeout_seconds if this repo's chain is legitimately slow")
        blocked_only_after_secret = secret_run.returncode != 0

        finding_count = _oracle_finding_count(repo.path, f"{remote_name}/{branch}..HEAD")

        if blocked_only_after_secret:
            if finding_count is None:
                return Result(NAME, "WARN", "premerge passed the secret-free baseline and blocked once the secret was added, but the independent oracle re-run could not be parsed — treat as unconfirmed")
            if finding_count >= 1:
                return Result(NAME, "PASS", f"premerge passed the secret-free baseline and blocked only after the secret was added (exit {secret_run.returncode}), oracle confirmed {finding_count} finding(s) in the same range")
            return Result(NAME, "WARN", "premerge blocked only after the secret was added, but the independent oracle found 0 findings in that range — treat as unconfirmed, since a block that correlates with the secret without a matching finding is not itself proof of correct scanning")

        # not blocked even after the secret was added
        if finding_count is not None and finding_count >= 1:
            return Result(NAME, "FAIL", f"premerge did not block even though the independent oracle confirmed {finding_count} finding(s) in the origin..HEAD range — secret-scan stage is not live or is scanning the wrong range")
        if finding_count == 0:
            return Result(NAME, "WARN", "premerge did not block, and the independent oracle found 0 findings — the declared secret-scan category is ineffective, most likely an empty/misconfigured gitleaks ruleset (check .gitleaks.toml's [extend])")
        return Result(NAME, "FAIL", "premerge did not block a synthetic secret in the origin..HEAD range, and the independent oracle re-run could not be parsed — secret-scan stage is not live")
