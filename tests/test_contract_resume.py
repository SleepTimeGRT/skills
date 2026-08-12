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


def _run(contract_dir: Path, shell: str, extra_args: str = "") -> subprocess.CompletedProcess[str]:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    full_script = f"source '{SCRIPT}'\ncontract_resume_state '{contract_dir}' {extra_args}\n"
    return subprocess.run(
        [shell, "-c", full_script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )


def _state(contract_dir: Path, shell: str, extra_args: str = "") -> dict:
    result = _run(contract_dir, shell, extra_args)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return json.loads(result.stdout)


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
def test_rejected_r2_without_override_resumes_override_step(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3  # the proposal round the override step produces (issue #130)


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
    """Round limit hit, plan_coverage-only rejection, override step completed (override + r3)."""
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "override.json", _override())
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


R3_REQUIRED_SINCE_EPOCH = 1786495497  # 2026-08-12T09:44:57+09:00 -- mirrors contract_resume.sh's R3_REQUIRED_SINCE


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
def test_r3_without_override_or_approval_escalates(tmp_path: Path, shell: str) -> None:
    """proposal-r3+ may only exist after override — anything else is an out-of-contract state."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


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
