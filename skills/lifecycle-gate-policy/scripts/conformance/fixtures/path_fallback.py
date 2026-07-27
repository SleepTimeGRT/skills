"""fixture: path-fallback — pre-push must still resolve its tooling (and still
block a statically-invalid push) under a minimal PATH, not just the
developer's interactively-configured shell PATH.

Predicted result (see .orca/proposal-23.md §0-A, §1-D): none of the three
pilot hooks correct PATH, so this fixture is expected to FAIL on all three —
that is the bug this fixture exists to surface. Do not relax the assertions
to make it pass.
"""

from __future__ import annotations

from pathlib import Path

from ..harness import BOOTSTRAP_FAILED_PREFIX, Result, probe_pre_push, scratch_clone

NAME = "path-fallback"
STAGE = "pre-push"
USES_EXTERNAL_PROBE = True

DEFAULT_TIMEOUT_SECONDS = 60
MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

TOOL_RESOLUTION_FAILURE_MARKERS = (
    "command not found",
    ": not found",
    "no such file or directory",
)


def _looks_like_tool_resolution_failure(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in TOOL_RESOLUTION_FAILURE_MARKERS):
        return True
    stripped = text.rstrip()
    return stripped.endswith(": 127") or stripped.endswith(" 127")


def run(source: Path, manifest: dict, cfg: dict) -> Result:
    timeout_seconds = cfg.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)

    with scratch_clone(source, manifest) as repo:
        if repo.bootstrap_result is not None and repo.bootstrap_result.status != "PASS":
            return Result(NAME, "SKIP", f"{BOOTSTRAP_FAILED_PREFIX} {repo.bootstrap_result.detail}")

        repo.link_node_modules()

        probe = probe_pre_push(repo)
        if probe.status == "SKIP":
            return Result(NAME, "SKIP", f"probe-unavailable: {probe.detail}")
        if probe.status != "PASS":
            return Result(NAME, "FAIL", f"stage-not-live: {probe.detail}")

        home = repo.run(["sh", "-c", "printf %s \"$HOME\""]).stdout.strip()
        minimal_env = {"PATH": MINIMAL_PATH}
        if home:
            minimal_env["HOME"] = home

        remote = repo.temp_remote()
        push = repo.run(
            ["git", "push", remote, "HEAD:refs/heads/conf-path-fallback"],
            env=minimal_env,
            timeout=timeout_seconds,
        )

        if push.returncode is None:
            return Result(
                NAME,
                "PASS",
                f"push exceeded {timeout_seconds}s under minimal PATH — verification appears to be running, not stuck resolving tools",
            )

        combined_output = (push.stdout or "") + (push.stderr or "")
        if _looks_like_tool_resolution_failure(combined_output):
            return Result(
                NAME,
                "FAIL",
                "push under minimal PATH shows a tool-resolution failure (command not found / exit 127) — no PATH fallback",
            )

        if push.returncode == 0:
            return Result(NAME, "FAIL", "push under minimal PATH succeeded — pre-push did not block a statically-invalid tree")

        return Result(NAME, "PASS", "push blocked under minimal PATH without a tool-resolution failure")
