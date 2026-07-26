"""fixture: biome-noop — a no-op edit inside the repo's biome ignore-set must
still be committable through pre-commit.

Regresses a real bug class: hook scripts that don't handle "biome had nothing
to process" as success.
"""

from __future__ import annotations

from pathlib import Path

from ..harness import Result, probe_pre_commit, scratch_clone

FORMATTER_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonc"}

# Markers that mean "the tool never ran", as opposed to "the tool ran and objected".
_TOOL_RESOLUTION_MARKERS = (
    "command not found",
    "not found",
    "no such file or directory",
    "ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL",
    "ERR_PNPM_NO_SCRIPT",
)


def _tool_resolution_failed(output: str) -> bool:
    lowered = output.lower()
    return any(marker.lower() in lowered for marker in _TOOL_RESOLUTION_MARKERS)


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

        # The formatter has to be resolvable or this fixture cannot observe anything.
        repo.link_node_modules()

        # The subject is the formatter's ignore-set, so the configured path must be a
        # file the formatter would otherwise process. A path it never looks at (docs,
        # logs, markdown) makes the commit succeed for an unrelated reason — a
        # vacuous PASS, which is exactly what this fixture set exists to prevent.
        if Path(ignored_path).suffix.lower() not in FORMATTER_EXTENSIONS:
            return Result(
                NAME,
                "SKIP",
                f"fixture-inapplicable: {ignored_path!r} is not a formatter-processed "
                f"extension {sorted(FORMATTER_EXTENSIONS)} — a commit touching only this "
                "path would succeed without exercising the formatter no-op path",
            )

        probe = probe_pre_commit(repo)
        if probe.status == "SKIP":
            return Result(NAME, "SKIP", f"probe-unavailable: {probe.detail}")
        if probe.status == "FAIL":
            return Result(NAME, "FAIL", f"stage-not-live: {probe.detail}")
        # WARN = the stage fires but its secret scan is ineffective. That is a
        # finding about secret-scan, not about this fixture: the stage is live, so
        # this fixture's observation is not vacuous and it still runs. The probe's
        # WARN is reported separately by the audit.
        probe_note = "" if probe.status == "PASS" else " — see probe:pre-commit"
        extra = [] if probe.status == "PASS" else [probe]

        def out(status: str, detail: str):
            return [Result(NAME, status, detail), *extra]

        target = repo.path / ignored_path
        try:
            original = target.read_text()
        except OSError as exc:
            return out("FAIL", f"could not read {ignored_path!r}: {exc}")

        repo.write(ignored_path, original + "\n")
        repo.stage(ignored_path)

        head_before = repo.run(["git", "rev-parse", "HEAD"]).stdout.strip()
        commit = repo.commit("conformance: biome-noop fixture (no-op edit on ignored path)")
        if commit.returncode != 0:
            combined = f"{commit.stdout or ''}\n{commit.stderr or ''}"
            if _tool_resolution_failed(combined):
                return out(
                    "SKIP",
                    "tooling-unavailable: the formatter could not be resolved inside the "
                    "scratch clone, so the commit outcome says nothing about policy: "
                    f"{combined.strip()[-200:]}",
                )
            return out("FAIL", f"commit blocked on biome-ignored path: {combined.strip()[-300:]}")

        head_after = repo.run(["git", "rev-parse", "HEAD"]).stdout.strip()
        if not head_after or head_after == head_before:
            return out("FAIL", "commit exited 0 but HEAD did not advance")

        return out("PASS", f"commit succeeded on biome-ignored path {ignored_path!r}{probe_note}")
