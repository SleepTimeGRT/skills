"""Behavioral conformance harness for lifecycle-gate-policy.

Runs probes and fixtures against an isolated `git clone --local` scratch copy
of a target repository, never against the repository itself. Fixtures observe
exit codes, block/pass outcomes, and output text only — they never read or
hash hook/script files (mechanism-agnostic).
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, Optional, Sequence

STATUSES = ("PASS", "WARN", "FAIL", "SKIP")

# Not `AKIAIOSFODNN7EXAMPLE` (the AWS-docs example key): verified against
# gitleaks 8.30.1's default ruleset that key is allowlisted and produces no
# finding, which would make probe_pre_commit report stage-not-live on every
# repo regardless of whether the hook actually runs. This pair does trigger
# `aws-access-token` + `generic-api-key` under the same default ruleset.
SYNTHETIC_SECRET = (
    "aws_access_key_id = AKIAABCDEFGHIJKLMNOP\n"
    "aws_secret_access_key = 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\n"
)
SYNTHETIC_SECRET_RELPATH = "__conformance_probe_secret.txt"

INVALID_STATIC_SNIPPET = (
    'export const broken : number = "not a number" ;;;\n'
    "function ( { }\n"
)


@dataclasses.dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _run(argv: Sequence[str], cwd: Path, *, env=None, timeout=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=env,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            list(argv),
            None,
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr),
        )


class ScratchRepo:
    """An isolated `git clone --local` copy of a source repo.

    Yielded by scratch_clone(); cleaned up when that context manager exits.
    """

    def __init__(self, path: Path, source: Path, manifest: dict, tmp_root: Path):
        self.path = path
        self.source = source
        self.manifest = manifest
        self.bootstrap_result: Optional[Result] = None
        self._tmp_root = tmp_root
        self._remote_dirs: dict[str, Path] = {}

    def bootstrap(self) -> Result:
        entrypoint = (self.manifest.get("bootstrap") or {}).get("entrypoint")
        if not entrypoint:
            result = Result("bootstrap", "SKIP", "manifest has no [bootstrap].entrypoint")
            self.bootstrap_result = result
            return result

        proc = _run(["bash", "-lc", entrypoint], cwd=self.path)
        if proc.returncode == 0:
            result = Result("bootstrap", "PASS", f"entrypoint exited 0: {entrypoint!r}")
        else:
            tail = _decode(proc.stderr).strip().splitlines()
            tail_line = tail[-1] if tail else ""
            detail = f"entrypoint exited {proc.returncode}: {entrypoint!r}"
            if tail_line:
                detail += f" — {tail_line}"
            result = Result("bootstrap", "FAIL", detail)
        self.bootstrap_result = result
        return result

    def link_node_modules(self) -> bool:
        source_nm = self.source / "node_modules"
        target_nm = self.path / "node_modules"
        if not source_nm.is_dir() or target_nm.exists():
            return False
        try:
            target_nm.symlink_to(source_nm, target_is_directory=True)
        except OSError:
            return False
        return True

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Optional[dict] = None,
        timeout: Optional[float] = None,
        extra_env: Optional[dict] = None,
    ) -> subprocess.CompletedProcess:
        run_env = dict(env) if env is not None else dict(os.environ)
        if extra_env:
            run_env.update(extra_env)
        return _run(argv, cwd=self.path, env=run_env, timeout=timeout)

    def temp_remote(self) -> str:
        name = "conformance"
        bare_dir = Path(tempfile.mkdtemp(prefix="lgp-remote-", dir=str(self._tmp_root)))
        subprocess.run(
            ["git", "init", "--quiet", "--bare", str(bare_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.path), "remote", "remove", name],
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(self.path), "remote", "add", name, str(bare_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        self._remote_dirs[name] = bare_dir
        return name

    def write(self, relpath: str, content: str) -> Path:
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def stage(self, *relpaths: str) -> None:
        # -f: a path can be both git-ignored and inside the repository's formatter
        # ignore-set (e.g. a tracked file under an ignored log directory). The
        # fixture's subject is the formatter's ignore-set, not git's, so staging
        # must not fail on git's.
        subprocess.run(
            ["git", "-C", str(self.path), "add", "-f", *relpaths],
            check=True,
            capture_output=True,
            text=True,
        )

    def commit(self, message: str) -> subprocess.CompletedProcess:
        return _run(["git", "commit", "-m", message], cwd=self.path)


@contextlib.contextmanager
def scratch_clone(source: Path, manifest: dict) -> Iterator[ScratchRepo]:
    """git clone --local -> remove origin -> configure identity -> run bootstrap.

    Yields a ScratchRepo even if bootstrap fails (repo.bootstrap_result holds
    the failure). Deletes the scratch tree and any temp bare remotes on exit.
    """
    source = Path(source).resolve()
    tmp_root = Path(tempfile.mkdtemp(prefix="lgp-conformance-"))
    scratch_path = tmp_root / "repo"
    try:
        clone = subprocess.run(
            ["git", "clone", "--local", "--quiet", str(source), str(scratch_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if clone.returncode != 0:
            raise RuntimeError(
                f"git clone --local failed for {source}: {clone.stderr.strip()}"
            )

        subprocess.run(
            ["git", "-C", str(scratch_path), "remote", "remove", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(scratch_path), "config", "user.email", "conformance@lifecycle-gate-policy.invalid"],
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(scratch_path), "config", "user.name", "lifecycle-gate-policy conformance harness"],
            capture_output=True,
            text=True,
            check=False,
        )

        repo = ScratchRepo(path=scratch_path, source=source, manifest=manifest, tmp_root=tmp_root)
        repo.bootstrap()
        yield repo
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def invalid_static_relpath(repo: ScratchRepo) -> str:
    if (repo.path / "src").is_dir():
        return "src/__conformance_invalid__.ts"
    return "__conformance_invalid__.ts"


def commit_invalid_static(repo: ScratchRepo, message: str) -> subprocess.CompletedProcess:
    """Write+stage+commit a file that must fail static verification.

    Uses --no-verify: this commit is meant to exercise pre-push, and must not
    itself be caught (or auto-fixed) by pre-commit.
    """
    relpath = invalid_static_relpath(repo)
    repo.write(relpath, INVALID_STATIC_SNIPPET)
    repo.stage(relpath)
    return repo.run(["git", "commit", "--no-verify", "-m", message])


def probe_pre_commit(repo: ScratchRepo) -> Result:
    """Stage a synthetic secret and commit (hooks live).

    Three outcomes, deliberately distinguished — collapsing them misreports a
    working stage with an ineffective scanner as an absent stage:

    * blocked                      -> PASS: stage is live *and* the scan catches secrets.
    * not blocked, stage spoke     -> WARN: the stage ran (its tooling produced output)
      but let a synthetic secret through. The declared ``secret-scan`` category is
      ineffective — commonly a scanner config that replaces the default ruleset
      instead of extending it. Fixtures on this stage may still run: the stage fires.
    * not blocked, stage silent    -> FAIL: nothing ran. Fixtures here would be vacuous.
    """
    if not _tool_available("gitleaks"):
        return Result("probe:pre-commit", "SKIP", "gitleaks not found on PATH")

    repo.write(SYNTHETIC_SECRET_RELPATH, SYNTHETIC_SECRET)
    repo.stage(SYNTHETIC_SECRET_RELPATH)
    commit = repo.commit("conformance: synthetic-secret probe (expected to be blocked)")
    if commit.returncode != 0:
        # Blocked: the file is still staged (never committed). Clear it so the
        # clone is back to its pre-probe state for whatever runs next in it.
        repo.run(["git", "reset", "--hard", "HEAD"])
        return Result("probe:pre-commit", "PASS", "commit blocked — pre-commit stage is live")

    # Not blocked. Did the stage run at all? A commit that only git itself handled
    # prints nothing but git's own summary; a stage that ran leaves its tooling's
    # output behind. This observes output, never hook file contents.
    cleanup = repo.run(["git", "reset", "--hard", "HEAD~1"])
    if cleanup.returncode != 0:
        # The probe's secret commit is still in this clone; anything running next in it
        # would inherit contaminated state. Refuse to report a usable verdict.
        return Result(
            "probe:pre-commit",
            "SKIP",
            "probe-cleanup-failed: could not undo the probe commit, so this clone cannot "
            f"carry a trustworthy fixture result: {_decode(cleanup.stderr).strip()[-160:]}",
        )
    if _stage_spoke(commit):
        return Result(
            "probe:pre-commit",
            "WARN",
            "pre-commit stage ran but did not block a synthetic secret — the declared "
            "secret-scan category is ineffective (check whether the scanner config "
            "extends the default ruleset instead of replacing it)",
        )
    return Result(
        "probe:pre-commit",
        "FAIL",
        "commit succeeded with no stage output — pre-commit stage is not live",
    )


# Output that git itself emits for a successful commit. Anything beyond these
# markers means some stage spoke during the commit.
_GIT_COMMIT_CHATTER = ("file changed", "files changed", "insertion", "deletion", "create mode", "delete mode")


def _stage_spoke(proc: subprocess.CompletedProcess) -> bool:
    """True when the commit produced output that git alone would not have produced."""
    text = f"{_decode(proc.stdout)}\n{_decode(proc.stderr)}"
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("["):  # "[main abc1234] message"
            continue
        if any(marker in line for marker in _GIT_COMMIT_CHATTER):
            continue
        return True
    return False


def probe_pre_push(repo: ScratchRepo) -> Result:
    """Commit a statically-invalid file and push it. Blocked => PASS."""
    commit = commit_invalid_static(repo, "conformance: static-verify probe (expected to be blocked)")
    if commit.returncode != 0:
        tail = _decode(commit.stderr).strip()[-300:]
        return Result("probe:pre-push", "FAIL", f"could not create probe commit: {tail}")

    remote = repo.temp_remote()
    push = repo.run(["git", "push", remote, "HEAD:refs/heads/conformance-probe"])
    if push.returncode != 0:
        return Result("probe:pre-push", "PASS", "push blocked — pre-push stage is live")
    return Result(
        "probe:pre-push",
        "FAIL",
        "push succeeded — pre-push stage did not block a statically-invalid tree",
    )
