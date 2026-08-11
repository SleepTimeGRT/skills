"""Doc-schema + execution guard for orca-evaluate's gate-safety signal
(docs/superpowers/specs/2026-08-12-orca-evaluate-gate-safety-signal-design.md). Before this
change, orca-evaluate/SKILL.md §3 only promoted the reviewer tier via
`migration_files_present` -- a diff that touches gate/hook/CI-safety paths (but no migration
files) stayed at the cheapest tier regardless of size, relying entirely on the spawned
reviewer's own prose-only judgment (§3 item 5) to notice. This guards that
`gate_safety_files_present` now feeds the same `--high-risk-signal` flag as
`migration_files_present`, via OR (either alone is sufficient, neither leaves it unset).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCA_EVALUATE_SKILL = REPO_ROOT / "skills" / "orca-evaluate" / "SKILL.md"
GATE_START = "# Gate-safety path check (docs/superpowers/specs/2026-08-12-orca-evaluate-gate-safety-signal-design.md)"
GATE_END = "# End gate-safety path check"


def _reviewer_json_block(text: str) -> str:
    start = text.index('reviewer_json="$(python3')
    end = text.index("reviewer_provider=", start)
    # <skill-dir> is an unquoted bash placeholder token -- executed literally it's parsed as
    # `<skill-dir` (stdin redirect from a file literally named "skill-dir") followed by
    # `>/scripts/select_reviewer.py` (stdout redirect), not as an argument to python3. Strip the
    # angle brackets so the extracted block is actually runnable, same substitution-before-exec
    # approach tests/test_dispatch_boot_quiesce_wiring.py uses for its own handle placeholders.
    return text[start:end].replace("<skill-dir>/scripts/select_reviewer.py", "skill-dir/scripts/select_reviewer.py")


def test_gate_safety_block_sits_between_migration_block_and_reviewer_spawn():
    text = ORCA_EVALUATE_SKILL.read_text()
    migration_end = text.index("migration-lint 크래시")
    reviewer_start = text.index('reviewer_json="$(python3')
    gate_start = text.index(GATE_START)
    gate_end = text.index(GATE_END)
    assert migration_end < gate_start < gate_end < reviewer_start

    gate_block = text[gate_start:gate_end]
    assert "gate_safety_files=(" in gate_block
    assert "gate_safety_files_present=false" in gate_block
    assert "gate_safety_files_present=true" in gate_block


def _run_reviewer_json_call(text: str, *, migration: bool, gate_safety: bool, tmp_path) -> list[str]:
    block = _reviewer_json_block(text)
    calls = tmp_path / f"calls-{migration}-{gate_safety}.txt"
    calls.write_text("")
    script = f'''\
migration_files_present={"true" if migration else "false"}
gate_safety_files_present={"true" if gate_safety else "false"}
codex_available=true
diff_shortstat=""
python3() {{ printf '%s\\n' "$*" >> "$CALLS"; printf '{{}}'; }}
{block}
'''
    subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "CALLS": str(calls)},
        capture_output=True, text=True, check=True,
    )
    return calls.read_text().splitlines()


def test_gate_safety_alone_sets_high_risk_signal(tmp_path):
    text = ORCA_EVALUATE_SKILL.read_text()
    calls = _run_reviewer_json_call(text, migration=False, gate_safety=True, tmp_path=tmp_path)
    assert len(calls) == 1
    assert "--high-risk-signal" in calls[0]


def test_migration_alone_still_sets_high_risk_signal(tmp_path):
    text = ORCA_EVALUATE_SKILL.read_text()
    calls = _run_reviewer_json_call(text, migration=True, gate_safety=False, tmp_path=tmp_path)
    assert len(calls) == 1
    assert "--high-risk-signal" in calls[0]


def test_neither_signal_omits_high_risk_signal(tmp_path):
    text = ORCA_EVALUATE_SKILL.read_text()
    calls = _run_reviewer_json_call(text, migration=False, gate_safety=False, tmp_path=tmp_path)
    assert len(calls) == 1
    assert "--high-risk-signal" not in calls[0]


def test_both_signals_still_sets_high_risk_signal_once(tmp_path):
    text = ORCA_EVALUATE_SKILL.read_text()
    calls = _run_reviewer_json_call(text, migration=True, gate_safety=True, tmp_path=tmp_path)
    assert len(calls) == 1
    assert "--high-risk-signal" in calls[0]
