"""Doc-schema regression coverage for issue #119 -- orca-evaluate had no rule distinguishing a
finding the diff *introduced* from one the diff merely *revealed* (a pre-existing defect in code
the diff never touched). In a shared-primitive migration (root #626, child #631) the same defect
class kept surfacing in a different call site every attempt, and FAIL never converged on its own
-- convergence only happened once a human manually scoped the finding out and filed it as a
separate target-repo issue (#642).

Decision (2026-08-13 triage): implement the structural gate only -- a finding's `evidence` file
path is checked against the confirmed proposal's `scope.files`, with no LLM self-assessment
involved. The issue's own proposed "reviewer judges introduced-vs-revealed in prose" alternative
was explicitly declined: trusting a reviewer's own "this is pre-existing" assertion, with no
independent check, is a hole an evaluator could use to talk itself out of a real FAIL. The issue's
compound condition ("scope.files AND outside the AC") was also narrowed to scope.files alone --
an AC-boundary check requires judgment and would undermine the gate's auditability, which was the
whole point of choosing the structural option. Auto-filing separated findings as target-repo
issues (the other half of the issue's fix direction) is explicitly deferred to a follow-up, not
implemented here.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCA_EVALUATE_SKILL = REPO_ROOT / "skills" / "orca-evaluate" / "SKILL.md"
CONTRACT_SCHEMA = REPO_ROOT / "orca-workflows" / "contract-schema.md"


def _section_4(text: str) -> str:
    start = text.index("## 4. 리포트 합성")
    end = text.index("## 폴백", start)
    return text[start:end]


def test_section_4_defines_diff_footprint_classification():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    assert "in_diff_footprint" in section
    assert "issue #119" in section
    assert "scope.files" in section


def test_classification_is_structural_not_reviewer_prose():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    assert "신뢰하지 않는다" in section  # explicitly does not trust reviewer's own prose judgment


def test_ac_boundary_half_of_original_proposal_explicitly_declined():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    assert "AC 밖" in section
    assert "넣지 않는다" in section


def test_e2e_findings_default_to_in_footprint_true():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    assert "e2e" in section.lower()
    # The e2e default-true rule must sit near the in_diff_footprint definition.
    idx = section.index("in_diff_footprint")
    nearby = section[idx: idx + 600]
    assert "true" in nearby


def test_pass_condition_requires_in_footprint_true_not_bare_critical_important():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    pass_line = next(line for line in section.splitlines() if line.strip().startswith("- **PASS**"))
    assert "in_diff_footprint: true" in pass_line


def test_fail_condition_excludes_out_of_footprint_findings():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    fail_line = next(line for line in section.splitlines() if line.strip().startswith("- **FAIL**"))
    assert "in_diff_footprint" in fail_line


def test_out_of_footprint_findings_are_not_dropped_from_the_report():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    assert "빠지지 않고" in section or "그대로 남" in section


def test_auto_filing_to_target_repo_is_explicitly_out_of_scope():
    section = _section_4(ORCA_EVALUATE_SKILL.read_text())
    assert "범위 밖" in section


def test_contract_schema_eval_report_documents_in_diff_footprint_field():
    text = CONTRACT_SCHEMA.read_text()
    start = text.index("## eval-report-a&lt;k&gt;.json")
    end = text.index("## ", start + 10)
    section = text[start:end]
    assert '"in_diff_footprint"' in section
    assert "scope.files" in section


def test_contract_schema_pass_invariant_updated_for_in_footprint():
    text = CONTRACT_SCHEMA.read_text()
    start = text.index("## eval-report-a&lt;k&gt;.json")
    end = text.index("## ", start + 10)
    section = text[start:end]
    assert "in_diff_footprint: true" in section
