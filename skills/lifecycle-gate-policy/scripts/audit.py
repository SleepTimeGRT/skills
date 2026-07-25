#!/usr/bin/env python3
"""Read-only drift audit for the lifecycle-gate-policy skill.

Compares a target repository against the canonical assets bundled with this
skill and the package-script naming contract. Never modifies the target.

Usage:
    python3 audit.py --repo /path/to/repo [--format text|json]

Exit code 0 = compliant (INFO/WARN allowed), 1 = drift found (FAIL/DRIFT/MISSING).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"

# repo-relative installed path -> asset path (exact-hash canonical files)
CANONICAL = {
    ".githooks/pre-commit": ASSETS / "githooks" / "pre-commit",
    ".githooks/pre-push": ASSETS / "githooks" / "pre-push",
    ".githooks/post-checkout": ASSETS / "githooks" / "post-checkout",
    "scripts/premerge.sh": ASSETS / "scripts" / "premerge.sh",
    "scripts/token-gate.sh": ASSETS / "scripts" / "token-gate.sh",
    "scripts/migration-lint.py": ASSETS / "scripts" / "migration-lint.py",
}

# repo-relative path -> severity when absent (repo-editable config files)
CONFIG_FILES = {
    "scripts/premerge.conf.sh": "WARN",
    ".githooks/worktree-links.conf": "INFO",
}

REQUIRED_SCRIPTS = ("verify", "verify:static", "premerge")
POLICY_MARKER = "lifecycle-gate-policy: policy v1"

LEGACY = {
    ".husky": "husky hook directory",
    "lefthook.yml": "lefthook config",
    ".lefthook.yml": "lefthook config",
    ".pre-commit-config.yaml": "pre-commit framework config",
}

FAILING = {"FAIL", "DRIFT", "MISSING"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_config(repo: Path, key: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "config", key],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def check_repo(repo: Path) -> list[dict]:
    results: list[dict] = []

    def add(check: str, status: str, detail: str) -> None:
        results.append({"check": check, "status": status, "detail": detail})

    # 1. hooksPath
    hooks_path = git_config(repo, "core.hooksPath")
    if hooks_path == ".githooks":
        add("core.hooksPath", "PASS", ".githooks")
    elif hooks_path:
        add("core.hooksPath", "FAIL", f"set to {hooks_path!r}, expected '.githooks'")
    else:
        add("core.hooksPath", "FAIL", "unset — run the package.json prepare script")

    # 2. canonical files (exact hash)
    for rel, asset in CANONICAL.items():
        installed = repo / rel
        if not asset.is_file():
            add(rel, "FAIL", f"asset missing in skill: {asset}")
            continue
        if not installed.is_file():
            add(rel, "MISSING", "not installed")
            continue
        if sha256(installed) == sha256(asset):
            add(rel, "PASS", "matches canonical")
        else:
            add(rel, "DRIFT", "differs from canonical — re-apply or upstream the change")

    # 3. repo config files
    for rel, severity in CONFIG_FILES.items():
        if (repo / rel).is_file():
            add(rel, "PASS", "present")
        else:
            add(rel, severity, "absent (repo-editable config)")

    # 4. package.json contract
    pkg_path = repo / "package.json"
    if not pkg_path.is_file():
        add("package.json", "FAIL", "not found at repo root")
    else:
        try:
            pkg = json.loads(pkg_path.read_text())
        except json.JSONDecodeError as exc:
            pkg = None
            add("package.json", "FAIL", f"unparseable: {exc}")
        if pkg is not None:
            scripts = pkg.get("scripts", {})
            prepare = scripts.get("prepare", "")
            if "core.hookspath .githooks" in prepare.lower():
                add("scripts.prepare", "PASS", "sets core.hooksPath .githooks")
            else:
                add("scripts.prepare", "FAIL", f"does not set hooksPath: {prepare!r}")
            for name in REQUIRED_SCRIPTS:
                if name in scripts:
                    add(f"scripts.{name}", "PASS", scripts[name])
                else:
                    add(f"scripts.{name}", "MISSING", "required by naming contract")
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for legacy_dep in ("husky", "simple-git-hooks", "lefthook"):
                if legacy_dep in deps:
                    add(f"dependency:{legacy_dep}", "FAIL", "legacy hook manager still installed")

    # 5. legacy hook managers on disk
    for rel, label in LEGACY.items():
        if (repo / rel).exists():
            add(rel, "FAIL", f"legacy {label} present — remove after migration")

    # 6. AGENTS.md policy marker
    agents = repo / "AGENTS.md"
    if agents.is_file() and POLICY_MARKER in agents.read_text(errors="replace"):
        add("AGENTS.md policy", "PASS", "policy marker present")
    else:
        add("AGENTS.md policy", "WARN", f"marker {POLICY_MARKER!r} not found")

    # 7. remote CI presence — informational only; judged by remote-ci-economics
    workflows = repo / ".github" / "workflows"
    if workflows.is_dir() and any(workflows.iterdir()):
        add(".github/workflows", "INFO", "remote CI present — audit with remote-ci-economics")
    else:
        add(".github/workflows", "INFO", "no remote CI workflows")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="path to the target repository")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / ".git").exists():
        print(f"audit: {repo} is not a git repository", file=sys.stderr)
        return 2

    results = check_repo(repo)
    failed = [r for r in results if r["status"] in FAILING]

    if args.format == "json":
        print(json.dumps({"repo": str(repo), "compliant": not failed, "results": results}, indent=2))
    else:
        width = max(len(r["check"]) for r in results)
        for r in results:
            print(f"[{r['status']:>7}] {r['check']:<{width}}  {r['detail']}")
        verdict = "COMPLIANT" if not failed else f"DRIFT — {len(failed)} failing check(s)"
        print(f"\n{repo.name}: {verdict}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
