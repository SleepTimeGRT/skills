"""fixture: premerge-secret-scan — the entrypoint declared for `premerge` in a repo's manifest must
independently rescan for secrets, catching a commit whose pre-commit hook was bypassed
(`git commit --no-verify`) anywhere in the commit range vs the default branch, not only the tip
commit.

Design: this fixture runs the entrypoint exactly once and watches its stdout for the one line the
reference implementation's `token_gate_capture` helper (this skill's own bundled shell library) prints
for the `premerge:secret-scan` stage — `[premerge:secret-scan] PASS (Ns)` or
`[premerge:secret-scan] FAIL (exit N, Ns) — log: ...`. As soon as that line appears, the process
(and its whole process group) is terminated: gitleaks has already finished by the time that line is
printed, so the stage's own verdict is fully formed, and none of the entrypoint's later stages
(gate-integrity, review, full verify, e2e) are ever reached — this fixture does not exercise a
target repo's real verify/e2e chain or its dependencies. Two earlier designs were tried and
rejected: a substring search over the entrypoint's combined output ("secret-scan"/"gitleaks"
anywhere) was fail-open (an unrelated downstream gate blocking after a wrongly-scoped scan still
"mentions" those words and earned a false PASS), and a differential double-run (secret-free
baseline vs. secret-added run, comparing exit codes) forced the baseline run to complete the
target's *entire* premerge chain — which pilot repos' `verify`/`e2e` commands cannot do inside an
isolated scratch clone (missing `node_modules`, emulator/DB seeding) — and was still fail-open
whenever the entrypoint rewrote a tracked file (codegen, formatters, lockfiles) between the two
runs. This design's trade-off: it recognizes only the reference implementation's
`token_gate_capture premerge:secret-scan` output tag. A `[stages.premerge].entrypoint` that
performs secret-scanning through some entirely different, untagged mechanism is reported as
unobserved (see `manifest-schema.md`) even if that mechanism actually works — a narrower but far
more accurate signal than either rejected approach produced.

Independently of that structured line, this fixture also re-runs gitleaks itself over the same
commit range to assert at least one real finding — a config with an empty ruleset must not be able
to pass vacuously merely because the stage's own tooling exited cleanly.

Unlike the other fixtures in this package, this one reads and runs whichever command
[stages.premerge].entrypoint names, per manifest-schema.md's documented exception for this fixture
— it is the one fixture that actually drives premerge.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
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

DEFAULT_TIMEOUT_SECONDS = 60

# The reference implementation's premerge script names this stage exactly "premerge:secret-scan"
# via its `token_gate_capture premerge:secret-scan -- gitleaks detect ...` call, and the shared
# token-gate helper library always prints "[<name>] PASS|WARN|FAIL ..." to stdout for it, never stderr.
STAGE_LABEL = "premerge:secret-scan"
STAGE_LINE_RE = re.compile(rf"^\[{re.escape(STAGE_LABEL)}\]\s+(PASS|WARN|FAIL)\b")
GITLEAKS_NOT_FOUND_MARKER = "gitleaks not found"


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


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _run_until_stage_line(argv: list[str], cwd: Path, timeout_seconds: float):
    """Runs argv, terminating the whole process group the moment a line matching
    STAGE_LINE_RE appears on stdout (stderr merged in). Returns (matched_status_or_None,
    "timed-out"|"natural-exit"|"matched", collected_output_tail)."""
    proc = subprocess.Popen(
        argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )

    outcome = {"kind": "natural-exit"}

    def _watchdog() -> None:
        time.sleep(timeout_seconds)
        if proc.poll() is None:
            outcome["kind"] = "timed-out"
            _kill_process_group(proc)

    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()

    lines: list[str] = []
    matched_status = None
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        if len(lines) > 400:
            lines.pop(0)
        m = STAGE_LINE_RE.match(line)
        if m:
            matched_status = m.group(1)
            outcome["kind"] = "matched"
            _kill_process_group(proc)
            break

    proc.stdout.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)

    return matched_status, outcome["kind"], "".join(lines)


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

        matched_status, kind, tail = _run_until_stage_line(["bash", "-lc", entrypoint], repo.path, timeout_seconds)

        if kind == "timed-out" and matched_status is None:
            return Result(NAME, "WARN", f"entrypoint exceeded {timeout_seconds}s without the {STAGE_LABEL} stage reporting — inconclusive, not evidence of a violation; raise [fixtures.premerge-secret-scan].timeout_seconds if step 1 (fetch) or the scan itself is legitimately slow")

        if matched_status is None:
            # Natural exit, never saw our stage's line at all.
            if GITLEAKS_NOT_FOUND_MARKER in tail:
                return Result(NAME, "SKIP", "entrypoint reported gitleaks not found on its own PATH — tooling unavailable inside the scratch clone, not a policy verdict")
            return Result(NAME, "FAIL", f"entrypoint ran to completion without ever reporting a [{STAGE_LABEL}] line — secret-scan stage is not live (or does not use the reference token_gate_capture tagging this fixture recognizes)")

        finding_count = _oracle_finding_count(repo.path, f"{remote_name}/{branch}..HEAD")
        finding_note = "unconfirmed (oracle re-run could not be parsed)" if finding_count is None else f"oracle found {finding_count} finding(s) in the same range"

        if matched_status == "FAIL":
            if finding_count is not None and finding_count >= 1:
                return Result(NAME, "PASS", f"[{STAGE_LABEL}] reported FAIL (blocked) and {finding_note}")
            return Result(NAME, "WARN", f"[{STAGE_LABEL}] reported FAIL (blocked), but {finding_note} — treat as unconfirmed rather than assuming the block was for the right reason")

        # matched_status in ("PASS", "WARN"): the stage's own tooling did not block. The synthetic
        # secret is a known-detectable payload (harness.SYNTHETIC_SECRET matches gitleaks' default
        # ruleset), so a live scan that still says PASS/WARN here is itself the vacuous-ruleset
        # signal — never treated as a clean bill of health regardless of what the oracle adds.
        return Result(NAME, "WARN", f"[{STAGE_LABEL}] reported {matched_status} (did not block) on a commit range that does contain a synthetic secret — {finding_note}; the declared secret-scan category is likely ineffective (check .gitleaks.toml's [extend])")
