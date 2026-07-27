#!/usr/bin/env python3
"""Manifest-based behavioral conformance audit for lifecycle-gate-policy.

Validates a target repository's lifecycle-gate.toml against the policy
category vocabulary (structural check), then — unless --skip-fixtures —
exercises the declared conformance fixtures against an isolated scratch
clone (behavioral check). Never modifies the target repository: fixtures run
in a disposable `git clone --local` copy with `origin` removed.

Usage:
    python3 audit.py --repo /path/to/repo [--skip-fixtures] [--format text|json]

The verdict describes the run as a whole and is fail-closed at that scope: a run
that observed nothing is never reported as compliance. It is not a per-stage
certificate — a declared stage that no enabled fixture drives is unobserved, and
COMPLIANT stays reachable without it (see references/manifest-schema.md).

    COMPLIANT      exit 0  at least one fixture observed the policy holding, and
                           nothing was inconclusive
    STRUCTURE-ONLY exit 0  --skip-fixtures was requested, so no behavioral claim
                           is made at all — this is not evidence of compliance
    UNVERIFIED     exit 3  nothing failed, but the evidence is incomplete: a
                           fixture was skipped or warned, or none ran
    NON-COMPLIANT  exit 1  a check failed outright (FAIL / MISSING)

exit 2 is reserved for usage errors (e.g. --repo is not a git repository).
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

from conformance.harness import BOOTSTRAP_FAILED_PREFIX  # noqa: E402  (needs SCRIPT_DIR on sys.path)

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

# Neither a failure nor evidence. A skipped fixture means the policy went
# unobserved — the manifest's claim is untested, so it cannot be certified.
INCONCLUSIVE_STATUSES = {"WARN", "SKIP"}

# Checks that report what was *observed*. An inconclusive result here means the
# behavioral claim is untested and the repo cannot be certified. Structural checks
# are excluded on purpose: their advisory WARNs (e.g. "no e2e category declared —
# recommended, not required") are advice about the declaration, not missing evidence.
BEHAVIORAL_CHECK_PREFIXES = ("fixture:", "probe:", "fixtures", "behavioral-evidence", "bootstrap.behavioral")


def is_behavioral(check: str) -> bool:
    return check.startswith(BEHAVIORAL_CHECK_PREFIXES)

VERDICT_COMPLIANT = "COMPLIANT"
VERDICT_STRUCTURE_ONLY = "STRUCTURE-ONLY"
VERDICT_UNVERIFIED = "UNVERIFIED"
VERDICT_NON_COMPLIANT = "NON-COMPLIANT"

EXIT_CODES = {
    VERDICT_COMPLIANT: 0,
    VERDICT_STRUCTURE_ONLY: 0,
    VERDICT_NON_COMPLIANT: 1,
    VERDICT_UNVERIFIED: 3,
}


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
        if not (stage_cfg or {}).get("entrypoint"):
            results.append(_result(
                f"stages.{stage_name}.entrypoint",
                "MISSING",
                "required — the manifest's claim is that this stage is satisfied at a named "
                "observable entrypoint; without it there is nothing to hold the repo to",
            ))

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
        results.append(_result(
            "fixtures",
            "SKIP",
            "no [fixtures].enabled declared — nothing observed the declared stages, so this "
            "manifest cannot be certified compliant on its declaration alone",
        ))
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

    results.extend(summarize_behavior(results, enabled))
    return results


def summarize_behavior(fixture_results: list[dict], enabled: list[str]) -> list[dict]:
    """Top-level lines for facts that would otherwise hide inside fixture details."""
    summary: list[dict] = []
    fixtures = [r for r in fixture_results if r["check"].startswith("fixture:")]

    # A bootstrap that cannot run is a manifest-level defect, not a fixture footnote:
    # nothing downstream of it can produce evidence in this environment.
    # Any one is enough: every fixture bootstraps the same way, so one failure means
    # the declared entrypoint does not reproduce this repo's wiring here.
    bootstrap_failed = [r for r in fixtures if BOOTSTRAP_FAILED_PREFIX in r["detail"]]
    if bootstrap_failed:
        summary.append(_result(
            "bootstrap.behavioral",
            "FAIL",
            "[bootstrap].entrypoint did not succeed in a scratch clone, so no fixture could "
            f"reproduce this repo's gate wiring: {bootstrap_failed[0]['detail']}",
        ))

    observed = [r["check"] for r in fixtures if r["status"] == "PASS"]
    if observed:
        summary.append(_result(
            "behavioral-evidence",
            "PASS",
            f"{len(observed)} of {len(enabled)} declared fixture(s) observed the policy holding: "
            + ", ".join(sorted(observed)),
        ))
    else:
        summary.append(_result(
            "behavioral-evidence",
            "SKIP",
            f"none of the {len(enabled)} declared fixture(s) observed the policy holding — "
            "a skipped or unimplemented fixture is not evidence of compliance",
        ))
    return summary


def decide_verdict(results: list[dict], skip_fixtures: bool) -> str:
    """Fail-closed: only observed behavior earns COMPLIANT."""
    if any(r["status"] in TERMINAL_FAIL_STATUSES for r in results):
        return VERDICT_NON_COMPLIANT
    if skip_fixtures:
        # The caller asked for structure only, so no behavioral claim is made.
        # Reported as its own verdict rather than as compliance.
        return VERDICT_STRUCTURE_ONLY
    if any(is_behavioral(r["check"]) and r["status"] in INCONCLUSIVE_STATUSES for r in results):
        return VERDICT_UNVERIFIED
    observed = any(r["check"].startswith("fixture:") and r["status"] == "PASS" for r in results)
    return VERDICT_COMPLIANT if observed else VERDICT_UNVERIFIED


def audit(repo: Path, skip_fixtures: bool) -> dict:
    manifest, missing_or_invalid = load_manifest(repo)
    results: list[dict] = []

    if missing_or_invalid is not None:
        results.append(missing_or_invalid)
    else:
        results.extend(check_structure(manifest))
        if skip_fixtures:
            results.append(_result(
                "fixtures",
                "SKIP",
                "--skip-fixtures: structural checks only — no stage was observed",
            ))
        else:
            results.extend(run_fixtures(repo, manifest))

    verdict = decide_verdict(results, skip_fixtures)
    return {
        "repo": str(repo),
        "verdict": verdict,
        "compliant": verdict == VERDICT_COMPLIANT,
        "results": results,
    }


def render_text(report: dict) -> str:
    lines: list[str] = []
    width = max((len(r["check"]) for r in report["results"]), default=0)
    for r in report["results"]:
        lines.append(f"[{r['status']:>13}] {r['check']:<{width}}  {r['detail']}")
    lines.append("")
    lines.append(f"{Path(report['repo']).name}: {report['verdict']}")
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

    return EXIT_CODES[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
