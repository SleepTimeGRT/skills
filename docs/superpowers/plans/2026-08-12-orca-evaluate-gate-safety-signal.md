# orca-evaluate 게이트-안전 신호 코드화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `orca-evaluate/SKILL.md` §3의 리뷰어 tier 선택이 `migration_files_present` 하나에만 의존하지 않고, 게이트/훅/CI-안전 관련 경로를 건드리는 diff도 같은 방식으로 `--high-risk-signal`을 세우게 한다.

**Architecture:** `migration_files_present`와 동일한 shape의 사전 경로 체크(`gate_safety_files_present`)를 §3에 추가하고, 기존 `select_reviewer.py` 호출의 `--high-risk-signal` 조건을 두 신호의 OR로 확장한다. `select_reviewer.py` 자체는 수정하지 않는다.

**Tech Stack:** Markdown(`SKILL.md`) 안의 bash, pytest(subprocess로 추출된 bash 블록 실행).

**Spec:** `docs/superpowers/specs/2026-08-12-orca-evaluate-gate-safety-signal-design.md`

## Global Constraints

- `skills/orca-evaluate/scripts/select_reviewer.py`는 인터페이스 변경 없음 — 기존 `--high-risk-signal` 플래그만 재사용한다.
- `skills/orca-evaluate/SKILL.md` §3 ⑤(게이트-안전성 prose 판단 지시)는 그대로 둔다 — 삭제·축약하지 않는다.
- 기존 87개 텍스트-단언 + 207개 실행 기반 테스트는 건드리지 않는다.
- `migration_files`/`gate_safety_files` 배열 계산부는 이 레포의 기존 관례대로 `<...>` placeholder로 남는다(실제 값은 라이브 에이전트가 실행 시점에 diff를 보고 채운다) — 자동 테스트는 이 두 불리언이 이미 계산됐다고 가정하고 그 이후 로직(OR 조건, `select_reviewer.py` 호출)만 검증한다.

---

### Task 1: 게이트-안전 경로 체크 추가 + `select_reviewer.py` 호출부 OR 조건 확장

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md:135-151` (마이그레이션 설명 문단 뒤, 리뷰어 스폰 문단 앞에 새 bash 블록 삽입 + `reviewer_json=` 호출의 high-risk-signal 조건 확장)
- Test: `tests/test_orca_evaluate_gate_safety_signal.py` (신규)

**Interfaces:**
- Consumes: 없음 (기존 `migration_files_present` 변수명·`select_reviewer.py --high-risk-signal` 플래그는 이미 존재).
- Produces: `gate_safety_files_present`(bool, `skills/orca-evaluate/SKILL.md` §3에서 새로 계산되는 셸 변수). 이후 이 spec 범위 밖의 후속 작업(로그 배선 등)이 참조한다면 이 이름을 그대로 쓴다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/test_orca_evaluate_gate_safety_signal.py`를 새로 만든다:

```python
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
```

- [ ] **Step 2: 테스트를 돌려서 실패를 확인한다**

Run: `python3 -m pytest tests/test_orca_evaluate_gate_safety_signal.py -v`
Expected: 5개 전부 실패(또는 error) —
`test_gate_safety_block_sits_between_migration_block_and_reviewer_spawn`는 `GATE_START`가
아직 파일에 없어 `ValueError: substring not found`로 실패, 나머지 4개는 `_reviewer_json_block`
자체는 추출되지만(기존 OR 조건이 없으므로) `gate_safety_alone`/`both_signals` 케이스가
`--high-risk-signal`이 없다고 잘못 나와 assertion 실패.

- [ ] **Step 3: `skills/orca-evaluate/SKILL.md`를 수정해 최소 구현을 넣는다**

`skills/orca-evaluate/SKILL.md`에서 아래 문자열(135번째 줄, 마이그레이션 설명 문단 전체)을:

```
(`scripts/migration-lint.py`가 없는 repo는 린터 실행만 건너뛴다 — opt-in 게이트라 아무 일도 안 한다. `migration_files_present`는 린터 실행 여부와 무관하게 diff에 migration 파일이 있었다는 사실 자체를 기록해 리뷰어 tier 선택에 넘긴다. **rc=1은 실패가 아니라 flag 발견이다**(린터 docstring: "0=clean, 1=flag found") — 여기서 중단하면 §4의 유일한 하드 ESCALATE 경로(린터가 flag했는데 code-reviewer가 미커버로 판정)가 영원히 도달 불가가 된다. 문제는 uncaught exception도 rc=1로 끝난다는 것(`FileNotFoundError` 등, 실측: traceback + stdout 0바이트) — 그래서 rc=1일 때 `.migration-lint.json`의 JSON 유효성까지 같이 확인해야 "진짜 flag"와 "크래시"를 구분할 수 있다. rc>1이거나 rc=1인데 JSON이 무효/비어 있으면 그때만 크래시로 보고 신뢰하지 않은 채 중단한다.)

fresh-context code-reviewer terminal을 하나 스폰한다
```

아래로 교체한다(마이그레이션 설명 문단은 그대로 두고 그 뒤에 새 문단 + 새 bash 블록을 추가):

```
(`scripts/migration-lint.py`가 없는 repo는 린터 실행만 건너뛴다 — opt-in 게이트라 아무 일도 안 한다. `migration_files_present`는 린터 실행 여부와 무관하게 diff에 migration 파일이 있었다는 사실 자체를 기록해 리뷰어 tier 선택에 넘긴다. **rc=1은 실패가 아니라 flag 발견이다**(린터 docstring: "0=clean, 1=flag found") — 여기서 중단하면 §4의 유일한 하드 ESCALATE 경로(린터가 flag했는데 code-reviewer가 미커버로 판정)가 영원히 도달 불가가 된다. 문제는 uncaught exception도 rc=1로 끝난다는 것(`FileNotFoundError` 등, 실측: traceback + stdout 0바이트) — 그래서 rc=1일 때 `.migration-lint.json`의 JSON 유효성까지 같이 확인해야 "진짜 flag"와 "크래시"를 구분할 수 있다. rc>1이거나 rc=1인데 JSON이 무효/비어 있으면 그때만 크래시로 보고 신뢰하지 않은 채 중단한다.)

같은 이유로, diff가 이 파이프라인 자신의 게이트/훅/CI 안전성에 관련된 경로를 건드리는지도 리뷰어가 스폰되기 전에 기계적으로 확인해 둔다(§3 ⑤의 게이트-안전성 판단 지시는 그대로 두되, 이 사전 체크가 놓치는 회색지대의 backstop으로만 남긴다 — `docs/superpowers/specs/2026-08-12-orca-evaluate-gate-safety-signal-design.md`):

```bash
# Gate-safety path check (docs/superpowers/specs/2026-08-12-orca-evaluate-gate-safety-signal-design.md)
gate_safety_files=( <diff에 포함된 경로 중 .githooks/*, lifecycle-gate.toml, orca-workflows/**/*.md, orca-workflows/scripts/*, skills/*/scripts/*, skills/*/SKILL.md, .github/workflows/*, premerge*.sh, token-gate.sh 패턴에 매칭되는 것들...> )   # migration_files와 동일한 quoting 규칙(개별 quoted 원소, unquoted 문자열 확장 금지)
gate_safety_files_present=false
[ ${#gate_safety_files[@]} -gt 0 ] && gate_safety_files_present=true
# End gate-safety path check
```

fresh-context code-reviewer terminal을 하나 스폰한다
```

그리고 이어서(같은 파일) 아래 문자열을:

```
# migration_files_present: 위에서 이미 계산해 둔 것을 그대로 넘긴다 — churn이 작아도 migration
# 파일이 있으면 최저 tier로 떨어지지 않는다.
reviewer_json="$(python3 <skill-dir>/scripts/select_reviewer.py --shortstat "$diff_shortstat" \
  $( [ "$codex_available" = true ] && echo --codex-available || echo --no-codex-available ) \
  $( [ "$migration_files_present" = true ] && echo --high-risk-signal ))"
```

아래로 교체한다:

```
# migration_files_present / gate_safety_files_present: 위에서 이미 계산해 둔 것을 그대로 넘긴다 —
# churn이 작아도 둘 중 하나라도 있으면 최저 tier로 떨어지지 않는다.
reviewer_json="$(python3 <skill-dir>/scripts/select_reviewer.py --shortstat "$diff_shortstat" \
  $( [ "$codex_available" = true ] && echo --codex-available || echo --no-codex-available ) \
  $( { [ "$migration_files_present" = true ] || [ "$gate_safety_files_present" = true ]; } && echo --high-risk-signal ))"
```

- [ ] **Step 4: 테스트를 다시 돌려서 통과를 확인한다**

Run: `python3 -m pytest tests/test_orca_evaluate_gate_safety_signal.py -v`
Expected: 5개 전부 PASS

**Step 5는 없다 — `skills/orca-evaluate/SKILL.md` 전체에 대한 `bash -n` 검증은 이 파일에서 유효하지
않다.** 실측(이 plan 작성 중 확인): 이 파일은 이번 변경과 무관하게, `§3` 앞부분의 기존 줄
(`git diff "$(git merge-base origin/main HEAD)"...HEAD > <worktree 루트>/.evaluate-diff.patch`)이
`<worktree 루트>`를 quote 밖에 둬서 `bash -n`이 이걸 출력 리다이렉션으로 오해해 이미 실패한다 — 이 파일
전체가 원래도 `bash -n`을 통과하지 못했다(이 task의 범위 밖, 손대지 않는다). 새로 추가/수정하는 두 블록의
문법 유효성은 Step 4의 pytest가 `subprocess.run(..., check=True)`로 이미 검증한다(문법 오류가 있었다면
`CalledProcessError`로 Step 4 자체가 실패했을 것).

- [ ] **Step 5: 전체 스위트 실행 — 회귀 없음 확인**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_deploy_skills.py`
Expected: 이전 통과 개수(294) + 이번에 추가한 5개 = 299 passed. (`test_deploy_skills.py`는
워킹트리가 dirty하면 실패하는 게 기존부터의 정상 동작이므로 제외.)

- [ ] **Step 6: 커밋**

```bash
git add skills/orca-evaluate/SKILL.md tests/test_orca_evaluate_gate_safety_signal.py
git commit -m "orca-evaluate: 게이트-안전 경로 체크를 select_reviewer.py의 high-risk-signal에 배선

migration_files_present뿐이던 사전 신호에 gate_safety_files_present를 OR로 추가한다.
select_reviewer.py 인터페이스는 그대로 두고, orca-evaluate/SKILL.md §3의 호출부만 확장.
§3 ⑤의 prose 판단 지시는 그대로 남겨 이 사전 체크가 놓치는 회색지대의 backstop으로 유지.

design: docs/superpowers/specs/2026-08-12-orca-evaluate-gate-safety-signal-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Post-implementation

- 이 세트(`orca-evaluate`가 속한 `orca-set.version`)는 커밋만으로 배포되지 않는다 — 실제로 살아있는
  에이전트가 이 변경을 쓰게 하려면 `scripts/deploy-skills.sh orca-evaluate`(또는 인자 없이 전체)를
  실행해야 한다(AGENTS.md "Skill deployment" 절차). 이 스텝은 구현 계획이 아니라 사용자 승인이 필요한
  배포 액션이므로 이 plan의 Task로 넣지 않는다 — 구현이 끝나면 사용자에게 배포 여부를 확인한다.
