"""fixture: delete-only-push — a push that only deletes a ref must short-circuit
without running static verification, but a push that mixes a delete ref with
a real (statically-invalid) ref must still be blocked.

Uses no external probe: the difference between the two push outcomes below is
its own liveness evidence (see .orca/impl-contract-23.md §4).
"""

from __future__ import annotations

from pathlib import Path

from ..harness import BOOTSTRAP_FAILED_PREFIX, Result, commit_invalid_static, scratch_clone

NAME = "delete-only-push"
STAGE = "pre-push"
USES_EXTERNAL_PROBE = False

STATIC_VERIFY_SIGNATURES = ("biome", "tsc", "eslint", "verify:static", "playwright", "jest", "vitest")


def _looks_like_static_verify_ran(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in STATIC_VERIFY_SIGNATURES)


def run(source: Path, manifest: dict, cfg: dict) -> Result:
    with scratch_clone(source, manifest) as repo:
        if repo.bootstrap_result is not None and repo.bootstrap_result.status != "PASS":
            return Result(NAME, "SKIP", f"{BOOTSTRAP_FAILED_PREFIX} {repo.bootstrap_result.detail}")

        remote = repo.temp_remote()

        setup = repo.run(["git", "push", "--no-verify", remote, "HEAD:refs/heads/conf-victim"])
        if setup.returncode != 0:
            tail = (setup.stderr or "").strip()[-300:]
            return Result(NAME, "FAIL", f"setup push failed: {tail}")

        probe_commit = commit_invalid_static(repo, "conformance: delete-only-push fixture (mixed-push probe commit)")
        if probe_commit.returncode != 0:
            tail = (probe_commit.stderr or "").strip()[-300:]
            return Result(NAME, "FAIL", f"could not create probe commit: {tail}")

        mixed = repo.run([
            "git", "push", remote,
            "HEAD:refs/heads/conf-mixed", ":refs/heads/conf-victim",
        ])
        if mixed.returncode == 0:
            return Result(NAME, "FAIL", "mixed push (statically-invalid ref + delete ref) was not blocked")

        still_present = repo.run(["git", "ls-remote", remote, "refs/heads/conf-victim"])
        if not (still_present.stdout or "").strip():
            return Result(
                NAME,
                "FAIL",
                "mixed push was blocked but conf-victim ref is gone — push was not rejected atomically",
            )

        solo = repo.run(["git", "push", remote, ":refs/heads/conf-victim"])
        if solo.returncode != 0:
            tail = (solo.stderr or "").strip()[-300:]
            return Result(NAME, "FAIL", f"delete-only push was blocked (exit {solo.returncode}), expected pass-through: {tail}")

        combined_output = (solo.stdout or "") + (solo.stderr or "")
        if _looks_like_static_verify_ran(combined_output):
            return Result(
                NAME,
                "FAIL",
                "delete-only push exited 0 but output shows static verification ran — deletion short-circuit missing",
            )

        return Result(
            NAME,
            "PASS",
            "mixed push blocked, delete-only push passed through — liveness demonstrated by the difference, no external probe used",
        )
