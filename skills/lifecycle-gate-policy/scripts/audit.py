#!/usr/bin/env python3
"""Manifest-based behavioral conformance audit for lifecycle-gate-policy.

Validates a target repository's lifecycle-gate.toml against the policy
category vocabulary (structural check), then — unless --skip-fixtures —
exercises the declared conformance fixtures against an isolated scratch
clone (behavioral check). Never modifies the target repository: fixtures run
in a disposable `git clone --local` copy with `origin` removed.

Usage:
    python3 audit.py --repo /path/to/repo [--skip-fixtures] [--format text|json]

Exit code 0 = compliant (only PASS/WARN/SKIP/NOT-EXERCISED present),
1 = FAIL or MISSING present.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tomllib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

POLICY_VERSION = "2"

CATEGORY_VOCABULARY = {
    "secret-scan",
    "format-autofix",
    "static-verify",
    "full-verify",
    "e2e",
    "protected-escalation",
    "sync-check",
}

REQUIRED_CATEGORIES = {
    "pre-commit": {"secret-scan"},
    "pre-push": {"static-verify"},
    "premerge": {"full-verify", "protected-escalation"},
}

TERMINAL_FAIL_STATUSES = {"FAIL", "MISSING"}


def _result(check: str, status: str, detail: str) -> dict:
    return {"check": check, "status": status, "detail": detail}


def load_manifest(repo: Path) -> tuple[dict | None, dict | None]:
    """Returns (manifest, missing_or_invalid_result); exactly one is None."""
    manifest_path = repo / "lifecycle-gate.toml"
    if not manifest_path.is_file():
        return None, _result(
            "manifest",
            "MISSING",
            "no lifecycle-gate.toml at repo root — copy "
            "skills/lifecycle-gate-policy/assets/lifecycle-gate.toml.example and adapt it",
        )
    try:
        manifest = tomllib.loads(manifest_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        return None, _result("manifest", "FAIL", f"lifecycle-gate.toml is not valid TOML: {exc}")
    return manifest, None


def check_structure(manifest: dict) -> list[dict]:
    results: list[dict] = []

    version = manifest.get("policy_version")
    if version != POLICY_VERSION:
        results.append(_result("policy_version", "FAIL", f"expected {POLICY_VERSION!r}, got {version!r}"))
    else:
        results.append(_result("policy_version", "PASS", version))

    bootstrap = manifest.get("bootstrap") or {}
    if not bootstrap.get("entrypoint"):
        results.append(_result(
            "bootstrap.entrypoint",
            "MISSING",
            "required — without it a scratch clone can't reproduce gate wiring and fixtures would pass vacuously",
        ))
    else:
        results.append(_result("bootstrap.entrypoint", "PASS", bootstrap["entrypoint"]))

    stages = manifest.get("stages") or {}
    if not stages:
        results.append(_result("stages", "MISSING", "at least one [stages.<name>] table is required"))

    for stage_name, stage_cfg in stages.items():
        categories = set((stage_cfg or {}).get("categories") or [])
        unknown = categories - CATEGORY_VOCABULARY
        required = REQUIRED_CATEGORIES.get(stage_name)
        missing_required = (required - categories) if required else set()

        problems = []
        if unknown:
            problems.append(f"unknown categories not in vocabulary: {', '.join(sorted(unknown))}")
        if missing_required:
            problems.append(f"missing required categories: {', '.join(sorted(missing_required))}")

        if problems:
            results.append(_result(f"stages.{stage_name}.categories", "FAIL", "; ".join(problems)))
        else:
            results.append(_result(f"stages.{stage_name}.categories", "PASS", ", ".join(sorted(categories))))

        if stage_name == "premerge":
            if "e2e" not in categories:
                results.append(_result(
                    "stages.premerge.categories",
                    "WARN",
                    "no 'e2e' category declared — recommended when the repo has an e2e suite, not required",
                ))
            results.append(_result(
                "stages.premerge.behavioral",
                "NOT-EXERCISED",
                "premerge is not covered by conformance fixtures — structural check only, not a PASS",
            ))

    for required_stage in REQUIRED_CATEGORIES:
        if required_stage not in stages:
            results.append(_result(f"stages.{required_stage}", "MISSING", "stage not declared in manifest"))

    return results


def load_fixture_module(name: str):
    module_name = name.replace("-", "_")
    try:
        module = importlib.import_module(f"conformance.fixtures.{module_name}")
    except ImportError:
        return None
    if getattr(module, "NAME", None) != name:
        return None
    return module


def run_fixtures(repo: Path, manifest: dict) -> list[dict]:
    results: list[dict] = []
    fixtures_cfg = manifest.get("fixtures") or {}
    enabled = fixtures_cfg.get("enabled") or []

    if not enabled:
        results.append(_result("fixtures", "SKIP", "no [fixtures].enabled declared in manifest"))
        return results

    for name in enabled:
        module = load_fixture_module(name)
        if module is None:
            results.append(_result(f"fixture:{name}", "WARN", "unknown fixture name — not implemented by this audit"))
            continue

        cfg = fixtures_cfg.get(name, {})
        try:
            fixture_result = module.run(repo, manifest, cfg)
        except Exception as exc:  # a broken fixture must not crash the whole audit
            results.append(_result(f"fixture:{name}", "FAIL", f"fixture raised {type(exc).__name__}: {exc}"))
            continue
        # A fixture may return one Result or several: its own plus any stage-level
        # finding its probe surfaced (e.g. a live pre-commit stage whose secret scan
        # is ineffective). Those are policy findings in their own right, not fixture
        # detail, so they get their own report lines.
        for item in fixture_result if isinstance(fixture_result, (list, tuple)) else [fixture_result]:
            label = item.name if item.name.startswith("probe:") else f"fixture:{name}"
            results.append(_result(label, item.status, item.detail))

    return results


def audit(repo: Path, skip_fixtures: bool) -> dict:
    manifest, missing_or_invalid = load_manifest(repo)
    results: list[dict] = []

    if missing_or_invalid is not None:
        results.append(missing_or_invalid)
    else:
        results.extend(check_structure(manifest))
        if skip_fixtures:
            results.append(_result("fixtures", "SKIP", "--skip-fixtures: structural checks only"))
        else:
            results.extend(run_fixtures(repo, manifest))

    compliant = not any(r["status"] in TERMINAL_FAIL_STATUSES for r in results)
    return {"repo": str(repo), "compliant": compliant, "results": results}


def render_text(report: dict) -> str:
    lines: list[str] = []
    width = max((len(r["check"]) for r in report["results"]), default=0)
    for r in report["results"]:
        lines.append(f"[{r['status']:>13}] {r['check']:<{width}}  {r['detail']}")
    verdict = "COMPLIANT" if report["compliant"] else "NON-COMPLIANT"
    lines.append("")
    lines.append(f"{Path(report['repo']).name}: {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="path to the target repository")
    parser.add_argument("--skip-fixtures", action="store_true", help="run structural manifest checks only")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / ".git").exists():
        print(f"audit: {repo} is not a git repository", file=sys.stderr)
        return 2

    report = audit(repo, args.skip_fixtures)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))

    return 0 if report["compliant"] else 1


if __name__ == "__main__":
    sys.exit(main())
