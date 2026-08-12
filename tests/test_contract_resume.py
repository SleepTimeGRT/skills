"""Functional tests for the contract_resume_state bash helper (issue #156).

Like test_log_outcome.py, this wraps executable code, not prose: the script is sourced and invoked
via subprocess, parametrized across bash *and* zsh (the helper is sourced into whatever shell runs
the orca-workflow-task §0 block -- zsh on this machine), with a timeout on every call.

The helper reconstructs a crashed coordinator session's progress purely from CONTRACT_DIR artifact
files (contract-schema.md): filename numbers are the canonical round/attempt/retry counters, never
the dead session's conversation context. Ambiguous states (a file that exists but doesn't parse --
died mid-write) are treated as absent, so the producing step re-runs (fail-closed).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "orca-workflows" / "scripts" / "contract_resume.sh"
SHELLS = ["bash", "zsh"]


def _run(
    contract_dir: Path, shell: str, extra_args: str = "", env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    full_script = f"source '{SCRIPT}'\ncontract_resume_state '{contract_dir}' {extra_args}\n"
    return subprocess.run(
        [shell, "-c", full_script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        env=env,
    )


def _state(
    contract_dir: Path, shell: str, extra_args: str = "", env: dict[str, str] | None = None
) -> dict:
    result = _run(contract_dir, shell, extra_args, env=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return json.loads(result.stdout)


def _stub_touch_dir(tmp_path: Path) -> Path:
    """A directory holding a `touch` shim that fails any `-t` invocation (simulating touch -t
    itself failing) and delegates everything else to the real `touch`, resolved before the shim
    is put on PATH so the delegation doesn't recurse into itself."""
    real_touch = shutil.which("touch")
    assert real_touch, "no real `touch` found on PATH to wrap"
    bindir = tmp_path / "stub-bin"
    bindir.mkdir()
    shim = bindir / "touch"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "for a in \"$@\"; do\n"
        '  if [ "$a" = "-t" ]; then exit 1; fi\n'
        "done\n"
        f'exec "{real_touch}" "$@"\n'
    )
    shim.chmod(0o755)
    return bindir


def _age(path: Path, seconds: int = 3600) -> None:
    """Backdate a file's mtime so it doesn't trip the recent_write guard."""
    old = time.time() - seconds
    os.utime(path, (old, old))


def _write(contract_dir: Path, name: str, obj, fresh: bool = False) -> Path:
    contract_dir.mkdir(parents=True, exist_ok=True)
    p = contract_dir / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    if not fresh:
        _age(p)
    return p


def _proposal(n: int) -> dict:
    return {"schema_version": 1, "issue": "42", "round": n}


def _verdict(n: int, status: str, targets: list[str] | None = None) -> dict:
    reasons = [{"target": t, "ac_id": None, "reason": "x"} for t in (targets or [])]
    return {"schema_version": 1, "issue": "42", "round": n, "status": status, "reasons": reasons}


def _override() -> dict:
    return {"schema_version": 1, "issue": "42", "overridden_by": "generator", "final_round": 2}


def _eval_report(k: int, verdict: str) -> dict:
    return {"schema_version": 1, "issue": "42", "attempt": k, "verdict": verdict}


# ── negotiation phase ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_dir_is_fresh_start(tmp_path: Path, shell: str) -> None:
    state = _state(tmp_path / "does-not-exist", shell)
    assert state["resume"] == "section-1-proposal"
    assert state["round"] == 1
    assert state["contract"] == "fresh"
    assert state["recent_write"] is False


@pytest.mark.parametrize("shell", SHELLS)
def test_empty_dir_is_fresh_start(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    d.mkdir()
    state = _state(d, shell)
    assert state["resume"] == "section-1-proposal"
    assert state["round"] == 1


@pytest.mark.parametrize("shell", SHELLS)
def test_proposal_without_verdict_resumes_verdict_step(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    state = _state(d, shell)
    assert state["resume"] == "section-1-verdict"
    assert state["round"] == 1
    assert state["contract"] == "negotiating"


@pytest.mark.parametrize("shell", SHELLS)
def test_invalid_proposal_reruns_proposal_step(tmp_path: Path, shell: str) -> None:
    """Died mid-write: the file exists but doesn't parse -- treated absent, producer re-runs."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", '{"round": 1, truncated')
    state = _state(d, shell)
    assert state["resume"] == "section-1-proposal"
    assert state["round"] == 1


@pytest.mark.parametrize("shell", SHELLS)
def test_rejected_r1_resumes_round2_proposal(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-proposal"
    assert state["round"] == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_round2_proposal_without_verdict_resumes_verdict_step(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    state = _state(d, shell)
    assert state["resume"] == "section-1-verdict"
    assert state["round"] == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_invalid_verdict_status_reruns_verdict_step(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "maybe"))
    state = _state(d, shell)
    assert state["resume"] == "section-1-verdict"
    assert state["round"] == 1


@pytest.mark.parametrize("shell", SHELLS)
def test_rejected_r2_plan_coverage_only_resumes_round3_proposal(tmp_path: Path, shell: str) -> None:
    """Round-cap conditional extension: plan_coverage-only at round 2 gets one more negotiated
    round instead of an immediate override (contract-sprint-improvements design, 2026-08-12)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-proposal"
    assert state["round"] == 3


@pytest.mark.parametrize("shell", SHELLS)
def test_rejected_r2_with_ac_fidelity_still_resumes_override_step(tmp_path: Path, shell: str) -> None:
    """ac_fidelity at round 2 is unchanged by the extension -- still goes straight to override."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage", "ac_fidelity"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3


# ── override gate (mirrors orca-workflow-task §1) ───────────────────────────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_override_with_ac_fidelity_escalates(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage", "ac_fidelity"]))
    _write(d, "override.json", _override())
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_without_verdict_r2_fails_closed(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "override.json", _override())
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


def _finalized_contract(d: Path) -> None:
    """Round limit hit, plan_coverage-only rejection, override step completed (override + r3).
    Backdated before ROUND3_NEGOTIATION_SINCE: this is the legacy final_round=2 finalize path --
    post-gate, plan_coverage-only at round 2 goes through the round-3 extension instead (see
    test_rejected_r2_plan_coverage_only_resumes_round3_proposal)."""
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, ROUND3_NEGOTIATION_SINCE_EPOCH - 3600)
    _write(d, "proposal-r3.json", _proposal(3))


@pytest.mark.parametrize("shell", SHELLS)
def test_override_plan_coverage_only_finalizes_and_resumes_generate(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _finalized_contract(d)
    state = _state(d, shell)
    assert state["contract"] == "finalized"
    assert state["resume"] == "section-2"
    assert state["approved_round"] == 3  # the override follow-up round IS the final contract (#130)
    assert state["attempt"] == 1
    assert state["retry"] == 0


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round2_plan_coverage_after_gate_is_anomalous(tmp_path: Path, shell: str) -> None:
    """final_round=2 + plan_coverage-only found AFTER ROUND3_NEGOTIATION_SINCE should never happen
    if the coordinator routes correctly (post-gate, that case goes through round-3 negotiation
    instead) -- fail closed to CONTRACT_ESCALATE rather than silently finalizing."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, ROUND3_NEGOTIATION_SINCE_EPOCH + 3600)
    _write(d, "proposal-r3.json", _proposal(3))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_without_r3_reruns_override_step(tmp_path: Path, shell: str) -> None:
    """override.json written but the step died before proposal-r3 (fixed write order) — re-burn it."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "override.json", _override())
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3


R3_REQUIRED_SINCE_EPOCH = 1786495497  # 2026-08-12T09:44:57+09:00, commit 79b7c3b -- mirrors contract_resume.sh's R3_REQUIRED_SINCE

ROUND3_NEGOTIATION_SINCE_EPOCH = 1786549920  # 2026-08-13T00:52:00+09:00
# mirrors contract_resume.sh's ROUND3_NEGOTIATION_SINCE


def _set_mtime(path: Path, epoch: float) -> None:
    """Set an absolute mtime (unlike _age, which subtracts a delta from 'now')."""
    os.utime(path, (epoch, epoch))


@pytest.mark.parametrize("shell", SHELLS)
def test_override_predating_r3_gate_reports_contract_schema_stale(tmp_path: Path, shell: str) -> None:
    """override.json completed before the proposal-r3 requirement existed -- not a violation (#160)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, R3_REQUIRED_SINCE_EPOCH - 3600)  # 1 hour before the gate
    state = _state(d, shell)
    assert state["contract"] == "escalated"
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_SCHEMA_STALE"


@pytest.mark.parametrize("shell", SHELLS)
def test_post_gate_override_not_misclassified_stale_under_non_kst_host_tz(
    tmp_path: Path, shell: str
) -> None:
    """The script pins TZ='Asia/Seoul' internally so its cutoff comparison is independent of the
    calling environment's TZ (issue #160 review: an unpinned touch -t interprets R3_REQUIRED_SINCE
    against the host's local TZ, producing an epoch off by hours on a non-KST host).

    This fixture is deliberately placed inside the 9-hour KST/UTC skew window so the test actually
    discriminates: R3_REQUIRED_SINCE_EPOCH ('202608120944.57') is 2026-08-12T09:44:57+09:00 KST.
    Interpreted as UTC instead (i.e. if the TZ pin were missing/broken), the same digit string
    means 2026-08-12T09:44:57+00:00 -- 2026-08-12T18:44:57+09:00, nine hours later. A fixture
    mtime one hour AFTER the real (KST) cutoff -- so it should NOT be stale -- falls BEFORE the
    wrongly-shifted (UTC-misread) cutoff, so an unpinned script would misreport it as
    CONTRACT_SCHEMA_STALE. Force TZ=UTC on the subprocess (distinct from whatever TZ this test
    runner's own host happens to have) and confirm the pin keeps the correct, not-stale
    classification regardless."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, R3_REQUIRED_SINCE_EPOCH + 3600)  # 1 hour after the real (KST) gate
    state = _state(d, shell, env={**os.environ, "TZ": "UTC"})
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3
    assert state["outcome"] != "CONTRACT_SCHEMA_STALE"


@pytest.mark.parametrize("shell", SHELLS)
def test_touch_t_backdating_failure_falls_closed_not_stale(tmp_path: Path, shell: str) -> None:
    """Finding-1 regression guard: if `touch -t` itself fails (backdating never happens), $ref is
    left at its just-created "now" mtime. A naive `-newer`/`! -newer` polarity swap is a pure
    boolean no-op for this case (proved empirically during the #160 final review: both the original
    and a literal `! -newer` inversion reported CONTRACT_SCHEMA_STALE here), because any
    already-written override.json is virtually always older than "now" regardless of polarity. The
    actual fix checks touch -t's own exit status and refuses to compare at all on failure.

    Fixture: a genuine POST-gate override.json (a real violation, NOT a legacy pre-gate session) --
    exactly the case a fail-open mechanism failure would misreport as CONTRACT_SCHEMA_STALE.
    Shadow PATH with a `touch` shim that fails any `-t` call, and confirm the result is still the
    existing violation-suspecting path (resume=section-1-override), not CONTRACT_SCHEMA_STALE."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, R3_REQUIRED_SINCE_EPOCH + 3600)  # genuine post-gate violation
    bindir = _stub_touch_dir(tmp_path)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}
    state = _state(d, shell, env=env)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3
    assert state["outcome"] != "CONTRACT_SCHEMA_STALE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_at_exact_r3_gate_boundary_is_stale(tmp_path: Path, shell: str) -> None:
    """mtime == cutoff (to the second) classifies as stale -- a deliberate boundary choice (design
    doc: 'mtime이 상수와 정확히 같은 초면... stale로 분류된다'). After the Finding-1 fail-closed
    inversion (! -newer instead of relying on the absence of -newer), '! -newer' still matches
    'not newer than', which includes exact equality, so this boundary must still classify stale."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, R3_REQUIRED_SINCE_EPOCH)  # exactly at the gate
    state = _state(d, shell)
    assert state["outcome"] == "CONTRACT_SCHEMA_STALE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_after_r3_gate_still_reruns_override_step(tmp_path: Path, shell: str) -> None:
    """Regression guard: an override.json written on/after the gate keeps the pre-existing
    "died mid-write, re-run it" behavior -- only pre-gate overrides get CONTRACT_SCHEMA_STALE."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, R3_REQUIRED_SINCE_EPOCH + 3600)  # 1 hour after the gate
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3


@pytest.mark.parametrize("shell", SHELLS)
def test_r3_proposal_without_verdict_resumes_verdict_step(tmp_path: Path, shell: str) -> None:
    """proposal-r3 without override.json is now legitimate: the round-2->3 extension's negotiated
    round, waiting for verdict-r3 (not the old out-of-contract state)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    state = _state(d, shell)
    assert state["resume"] == "section-1-verdict"
    assert state["round"] == 3


@pytest.mark.parametrize("shell", SHELLS)
def test_r4_without_override_or_approval_escalates(tmp_path: Path, shell: str) -> None:
    """proposal-r4+ may only exist after a final_round=3 override -- anything else is
    out-of-contract (the extension's equivalent of the old r3 guard)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r4.json", _proposal(4))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_r3_approved_resumes_generate_attempt1(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "approved"))
    state = _state(d, shell)
    assert state["contract"] == "approved"
    assert state["approved_round"] == 3
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_r3_rejected_ac_fidelity_escalates_round3(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["ac_fidelity"]))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_r3_rejected_plan_coverage_only_resumes_override_round4(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 4


def _override_r3(unresolved: list[str] | None = None) -> dict:
    return {
        "schema_version": 1, "issue": "42", "overridden_by": "generator",
        "final_round": 3,
        "unresolved_reasons": [{"target": t, "ac_id": None, "reason": "x"} for t in (unresolved or [])],
    }


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_with_ac_fidelity_escalates(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage", "ac_fidelity"]))
    _write(d, "override.json", _override_r3())
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_without_verdict_r3_fails_closed(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "override.json", _override_r3())
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_without_r4_reruns_override_step(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    _write(d, "override.json", _override_r3())
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 4


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_plan_coverage_only_finalizes(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    _write(d, "override.json", _override_r3())
    _write(d, "proposal-r4.json", _proposal(4))
    state = _state(d, shell)
    assert state["contract"] == "finalized"
    assert state["approved_round"] == 4
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_correction_round_after_override_updates_final_round(tmp_path: Path, shell: str) -> None:
    """A post-override contract correction (proposal-r4, #130) becomes the final contract round."""
    d = tmp_path / "issue-42"
    _finalized_contract(d)
    _write(d, "proposal-r4.json", _proposal(4))
    _write(d, "eval-report-a1.json", _eval_report(1, "FAIL"))
    state = _state(d, shell)
    assert state["approved_round"] == 4
    assert state["resume"] == "section-2"
    assert state["attempt"] == 2


# ── implementation phase ─────────────────────────────────────────────────────────────────────


def _approved_contract(d: Path, approved_round: int = 1) -> None:
    for n in range(1, approved_round):
        _write(d, f"proposal-r{n}.json", _proposal(n))
        _write(d, f"verdict-r{n}.json", _verdict(n, "rejected", ["plan_coverage"]))
    _write(d, f"proposal-r{approved_round}.json", _proposal(approved_round))
    _write(d, f"verdict-r{approved_round}.json", _verdict(approved_round, "approved"))


@pytest.mark.parametrize("shell", SHELLS)
def test_approved_contract_resumes_generate_attempt1(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    state = _state(d, shell)
    assert state["contract"] == "approved"
    assert state["resume"] == "section-2"
    assert state["approved_round"] == 1
    assert state["attempt"] == 1
    assert state["retry"] == 0


@pytest.mark.parametrize("shell", SHELLS)
def test_approved_at_round2_reports_approved_round2(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d, approved_round=2)
    state = _state(d, shell)
    assert state["approved_round"] == 2
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_fail_report_resumes_next_attempt(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    _write(d, "eval-report-a1.json", _eval_report(1, "FAIL"))
    state = _state(d, shell)
    assert state["resume"] == "section-2"
    assert state["attempt"] == 2
    assert state["retry"] == 1


@pytest.mark.parametrize("shell", SHELLS)
def test_two_fails_resume_third_attempt(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    _write(d, "eval-report-a1.json", _eval_report(1, "FAIL"))
    _write(d, "eval-report-a2.json", _eval_report(2, "FAIL"))
    state = _state(d, shell)
    assert state["resume"] == "section-2"
    assert state["attempt"] == 3
    assert state["retry"] == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_third_fail_exhausts_retries(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    for k in (1, 2, 3):
        _write(d, f"eval-report-a{k}.json", _eval_report(k, "FAIL"))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "FAIL"
    assert state["retry"] == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_pass_report_resumes_merge_routing(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    _write(d, "eval-report-a1.json", _eval_report(1, "PASS"))
    state = _state(d, shell)
    assert state["resume"] == "section-4"
    assert state["outcome"] == "PASS"
    assert state["attempt"] == 1


@pytest.mark.parametrize("shell", SHELLS)
def test_escalate_report_resumes_section5(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    _write(d, "eval-report-a1.json", _eval_report(1, "ESCALATE"))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_invalid_eval_report_reruns_that_attempt(tmp_path: Path, shell: str) -> None:
    """eval-report-a2 died mid-write: attempt 2 re-runs, its FAIL predecessor still counts."""
    d = tmp_path / "issue-42"
    _approved_contract(d)
    _write(d, "eval-report-a1.json", _eval_report(1, "FAIL"))
    _write(d, "eval-report-a2.json", '{"verdict": "FA')
    state = _state(d, shell)
    assert state["resume"] == "section-2"
    assert state["attempt"] == 2
    assert state["retry"] == 1


@pytest.mark.parametrize("shell", SHELLS)
def test_gate_flake_files_do_not_affect_routing(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    _write(d, "gate-flake-a1.json", {"schema_version": 1, "issue": "42", "attempt": 1, "gates": []})
    state = _state(d, shell)
    assert state["resume"] == "section-2"
    assert state["attempt"] == 1


# ── recent-write guard / misc ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_recent_write_flag_set_for_fresh_artifacts(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1), fresh=True)
    state = _state(d, shell)
    assert state["recent_write"] is True


@pytest.mark.parametrize("shell", SHELLS)
def test_recent_write_flag_clear_for_old_artifacts(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    state = _state(d, shell)
    assert state["recent_write"] is False


@pytest.mark.parametrize("shell", SHELLS)
def test_recent_secs_is_tunable(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    p = _write(d, "proposal-r1.json", _proposal(1))
    _age(p, seconds=120)
    assert _state(d, shell, "--recent-secs 60")["recent_write"] is False
    assert _state(d, shell, "--recent-secs 600")["recent_write"] is True


@pytest.mark.parametrize("shell", SHELLS)
def test_spaces_in_contract_dir_path(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "my project" / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    state = _state(d, shell)
    assert state["resume"] == "section-1-verdict"


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_dir_argument_is_usage_error(tmp_path: Path, shell: str) -> None:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    result = subprocess.run(
        [shell, "-c", f"source '{SCRIPT}'\ncontract_resume_state\n"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )
    assert result.returncode == 64
    assert "usage" in result.stderr.lower()


@pytest.mark.parametrize("shell", SHELLS)
def test_output_is_single_json_object(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _approved_contract(d)
    result = _run(d, shell)
    assert result.returncode == 0
    parsed = json.loads(result.stdout)  # raises if extra output pollutes stdout
    assert parsed["schema_version"] == 1
