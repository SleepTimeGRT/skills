"""fixture: biome-noop — a no-op edit inside the repo's biome ignore-set must
still be committable through pre-commit.

Regresses a real bug class: hook scripts that don't handle "biome had nothing
to process" as success.
"""

from __future__ import annotations

from pathlib import Path

from ..harness import Result, probe_pre_commit, scratch_clone

NAME = "biome-noop"
STAGE = "pre-commit"
USES_EXTERNAL_PROBE = True


def run(source: Path, manifest: dict, cfg: dict) -> Result:
    ignored_path = cfg.get("ignored_path")
    if not ignored_path:
        return Result(NAME, "SKIP", "manifest has no [fixtures.biome-noop].ignored_path")
    if not (Path(source) / ignored_path).is_file():
        return Result(NAME, "SKIP", f"ignored_path {ignored_path!r} not found in repo")

    with scratch_clone(source, manifest) as repo:
        if repo.bootstrap_result is not None and repo.bootstrap_result.status != "PASS":
            return Result(NAME, "SKIP", f"bootstrap-failed: {repo.bootstrap_result.detail}")

        probe = probe_pre_commit(repo)
        if probe.status == "SKIP":
            return Result(NAME, "SKIP", f"probe-unavailable: {probe.detail}")
        if probe.status != "PASS":
            return Result(NAME, "FAIL", f"stage-not-live: {probe.detail}")

        target = repo.path / ignored_path
        try:
            original = target.read_text()
        except OSError as exc:
            return Result(NAME, "FAIL", f"could not read {ignored_path!r}: {exc}")

        repo.write(ignored_path, original + "\n")
        repo.stage(ignored_path)

        head_before = repo.run(["git", "rev-parse", "HEAD"]).stdout.strip()
        commit = repo.commit("conformance: biome-noop fixture (no-op edit on ignored path)")
        if commit.returncode != 0:
            tail = (commit.stderr or "").strip()[-300:]
            return Result(NAME, "FAIL", f"commit blocked on biome-ignored path: {tail}")

        head_after = repo.run(["git", "rev-parse", "HEAD"]).stdout.strip()
        if not head_after or head_after == head_before:
            return Result(NAME, "FAIL", "commit exited 0 but HEAD did not advance")

        return Result(NAME, "PASS", f"commit succeeded on biome-ignored path {ignored_path!r}")
