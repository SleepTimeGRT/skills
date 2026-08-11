# FAIL 재시도 Dispatch 확정 계약 파일 포인터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FAIL 재시도로 재-dispatch되는 generator가 `eval-report-a<attempt>.json`뿐 아니라 확정 계약(`proposal-r<확정라운드>.json`)도 반드시 읽도록, `orca-workflow-task`(dispatch를 구성하는 쪽)와 `orca-task-runner`(dispatch를 소비하는 쪽) 양쪽의 문구를 대응시킨다.

**Architecture:** 두 skill 파일에 대한 독립적인 anchor-based 텍스트 편집. `orca-workflow-task/SKILL.md` §2 "Generate"에는 기존에 없던 `spec_text="<...>"` 템플릿을 신설해 두 파일 경로를 순서대로 넘기도록 강제하고, `orca-task-runner/SKILL.md` §7의 대응 문단에 두 번째 파일을 추가한다. 두 파일 모두 `skills/orca-set.version`으로 묶인 버전 세트 멤버이므로, 세트 버전을 bump하고 그 값을 하드코딩한 두 기존 회귀 테스트를 함께 갱신한다. 코드 로직 변경은 없다 — 전부 prose/문서 편집.

**Tech Stack:** Markdown(skill 문서), Python/pytest(버전 세트 회귀 테스트). Prose 편집 자체의 검증은 `grep -F` 카운트로 한다 — 이 두 파일엔 실행 가능한 테스트 러너가 없다.

## Global Constraints

- `skills/orca-workflow-task/SKILL.md`, `skills/orca-task-runner/SKILL.md`, `skills/orca-set.version`, `tests/test_log_enum_schema.py`, `tests/test_contract_schema_fails_before_fix.py` 외의 파일은 건드리지 않는다(spec §범위 경계 — `contract-schema.md`/`orca-evaluate`는 제외).
- `orca-task-runner` §7에 "diff를 확정 AC 전체와 재대조"하는 새 검증 단계를 추가하지 않는다 — spec §검토 후 기각한 대안에서 명시적으로 범위 제외(generator/evaluator 역할 분리 원칙과 충돌).
- `<확정라운드>`는 generator나 코디네이터가 `CONTRACT_DIR`를 listing해서 스스로 찾는 게 아니라, `orca-workflow-task`가 §1 라운드 루프에서 이미 로그로 남긴 `round` 값을 그대로 리터럴 치환한다(spec §결정 1, §검토 후 기각한 대안).
- 두 SKILL.md 파일 편집 후 `skills/orca-set.version`의 버전 라인을 반드시 bump한다 — 이 저장소의 기존 관행(모든 세트 멤버 content 변경 커밋이 이 파일을 bump해 왔다 — `git log -- skills/orca-set.version` 확인됨)이며, `tests/test_log_enum_schema.py::test_orca_set_version_bumped`와 `tests/test_contract_schema_fails_before_fix.py::test_orca_set_version_line1_is_v1_1_8`이 정확한 버전 문자열을 하드코딩해서 이 규칙을 강제한다.

---

### Task 1: `orca-workflow-task/SKILL.md` §2 — FAIL 재시도 dispatch 템플릿 신설

**Files:**
- Modify: `skills/orca-workflow-task/SKILL.md` (현재 L252, §2 "Generate"의 두 번째 문단)

**Interfaces:**
- Consumes: 없음(첫 task).
- Produces: `orca-workflow-task`가 FAIL 재시도 시 구성하는 `spec_text`에 `eval-report-a<attempt>.json`과 `proposal-r<확정라운드>.json` 두 파일 경로가 이 순서로 포함된다는 문서상의 계약. Task 2는 이 계약을 소비하는 쪽 문서를 수정하므로, 두 파일명·순서 표기가 정확히 일치해야 한다(아래 Step 3의 정확한 문자열을 Task 2에서도 그대로 재사용).

- [ ] **Step 1: Write the failing check**

```bash
grep -Fc "proposal-r<확정라운드>.json" skills/orca-workflow-task/SKILL.md
```

- [ ] **Step 2: Run the check to verify it currently fails (pointer absent)**

Run the command from Step 1.
Expected output: `0`

- [ ] **Step 3: Replace the FAIL-retry sentence with an explicit dispatch template**

Use the Edit tool on `skills/orca-workflow-task/SKILL.md` with:

`old_string`:
```
`orca-task-runner` 호출, 결과로 **task 전체 diff 경로** 또는 **`GATE_FAIL`**을 받는다(`orca-task-runner`가 자기 task-레벨 게이트를 재시도 한도(2회) 안에 못 넘긴 경우 — `skills/orca-task-runner/SKILL.md` §6). §4의 FAIL 재시도로 돌아온 호출이면 spec에 직전 attempt 번호를 넣는다 — generator가 `CONTRACT_DIR`의 `eval-report-a<attempt>.json`을 직접 읽는다(이 스킬은 feedback 본문을 중계하지 않는다).
```

`new_string`:
```
`orca-task-runner` 호출, 결과로 **task 전체 diff 경로** 또는 **`GATE_FAIL`**을 받는다(`orca-task-runner`가 자기 task-레벨 게이트를 재시도 한도(2회) 안에 못 넘긴 경우 — `skills/orca-task-runner/SKILL.md` §6). §4의 FAIL 재시도로 돌아온 호출이면 spec을 아래 템플릿대로 구성한다 — findings를 prose로 요약하지 않고 파일 경로만 넘긴다:

```
spec_text="<... + 직전 attempt 번호 + \"CONTRACT_DIR의 eval-report-a<attempt>.json과 proposal-r<확정라운드>.json을 이 순서로 전부 읽어라 — findings를 요약해 넘기지 않는다\" + orphan-폴백 계약(§0) 전문>"
```

`<확정라운드>`는 이 세션이 §1에서 이미 로그로 남긴 `CONTRACT_APPROVED`/`CONTRACT_FINALIZED_BY_GENERATOR`의 `round` 값을 그대로 리터럴 치환한다(추가 조회 없음) — generator가 두 파일을 직접 읽는다(이 스킬은 feedback 본문도 확정 AC 본문도 중계하지 않는다).
```

- [ ] **Step 4: Run the check again to verify it passes**

Run the same command from Step 1.
Expected output: `1`

- [ ] **Step 5: Confirm the old bare sentence is gone**

```bash
grep -Fc "spec에 직전 attempt 번호를 넣는다" skills/orca-workflow-task/SKILL.md
```

Expected output: `0`

- [ ] **Step 6: Commit**

```bash
git add skills/orca-workflow-task/SKILL.md
git commit -m "$(cat <<'EOF'
orca-workflow-task: §2 FAIL 재시도 dispatch에 확정 계약 파일 포인터 추가 (issue #141)

§2 "Generate"는 §1과 달리 spec_text 강제 템플릿이 없어 순수 prose 지시뿐이었고,
실측에서 findings가 prose로 요약되며 proposal-r<n>.json 언급 자체가 빠지는
드리프트가 관측됐다(studio-hevv/selah-android#10 attempt3). eval-report-a<attempt>.json과
proposal-r<확정라운드>.json을 이 순서로 전부 읽으라는 명시적 템플릿으로 교체해
prose 요약 여지를 차단한다. 라운드 번호는 이 세션이 §1에서 이미 로그로 남긴
값을 리터럴 치환한다 — 추가 조회 없음.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `orca-task-runner/SKILL.md` §7 — 수신 측 문단에 확정 계약 파일 추가

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md` (현재 L252, §7 "완료"의 "Evaluate-FAIL 재시도로 재호출된 경우" 문단)

**Interfaces:**
- Consumes: Task 1이 정의한 두 파일명·순서(`eval-report-a<attempt>.json` → `proposal-r<확정라운드>.json`) — 이 task는 그 값을 소비하는 쪽 문서를 정확히 같은 이름·순서로 갱신한다.
- Produces: 없음(마지막 skill-문서 task).

- [ ] **Step 1: Write the failing check**

```bash
grep -Fc "proposal-r<확정라운드>.json" skills/orca-task-runner/SKILL.md
```

- [ ] **Step 2: Run the check to verify it currently fails (pointer absent)**

Run the command from Step 1.
Expected output: `0`

- [ ] **Step 3: Add the second file to the FAIL-retry paragraph**

Use the Edit tool on `skills/orca-task-runner/SKILL.md` with:

`old_string`:
```
**Evaluate-FAIL 재시도로 재호출된 경우**(spec에 attempt 번호가 있음): contract 협상(§1)을 다시 하지 않는다 — 확정 AC는 그대로다. `CONTRACT_DIR`의 `eval-report-a<attempt>.json`에서 `findings`를 직접 읽고(`orca-workflow-task`는 본문을 중계하지 않는다 — `~/.agents/orca-workflows/contract-schema.md`), 그 수정에 필요한 만큼만 §2~§5를 다시 태운 뒤 §6 task-레벨 게이트를 전체 재통과시키고 위 §7 반환을 반복한다. 수정 결과에 대한 서술형 해명을 evaluator에게 보내지 않는다 — 재평가의 입력은 diff의 사실 변화뿐이다(같은 문서의 "재시도 입력 격리").
```

`new_string`:
```
**Evaluate-FAIL 재시도로 재호출된 경우**(spec에 attempt 번호가 있음): contract 협상(§1)을 다시 하지 않는다 — 확정 AC는 그대로다. `CONTRACT_DIR`의 `eval-report-a<attempt>.json`과 `proposal-r<확정라운드>.json`을 이 순서로 직접 읽고(`orca-workflow-task`는 findings 본문도 확정 AC 본문도 중계하지 않는다 — `~/.agents/orca-workflows/contract-schema.md`의 "확정 AC의 정본"), 그 수정에 필요한 만큼만 §2~§5를 다시 태운 뒤 §6 task-레벨 게이트를 전체 재통과시키고 위 §7 반환을 반복한다. 수정 결과에 대한 서술형 해명을 evaluator에게 보내지 않는다 — 재평가의 입력은 diff의 사실 변화뿐이다(같은 문서의 "재시도 입력 격리").
```

- [ ] **Step 4: Run the check again to verify it passes**

Run the same command from Step 1.
Expected output: `1`

- [ ] **Step 5: Confirm the schema cross-reference resolves to a real section**

```bash
grep -Fc "확정 AC의 정본" ~/.agents/orca-workflows/contract-schema.md
```

Expected output: `1` (or more) — proves the new `"확정 AC의 정본"` cross-reference added in Step 3 points at a section that actually exists in `contract-schema.md`, not a dangling reference.

- [ ] **Step 6: Commit**

```bash
git add skills/orca-task-runner/SKILL.md
git commit -m "$(cat <<'EOF'
orca-task-runner: §7 FAIL 재시도 수신 문단에 확정 계약 파일 추가 (issue #141)

orca-workflow-task §2가 이제 eval-report-a<attempt>.json과 함께
proposal-r<확정라운드>.json 경로도 spec에 실어 보내므로, 이를 실제로
소비하는 §7 문단도 두 파일을 이 순서로 직접 읽는다고 명시한다.
contract-schema.md의 "확정 AC의 정본" 절을 참조해 이 순서(eval-report →
proposal)가 그 절의 규칙과 일치함을 밝힌다.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 버전 세트 bump + 하드코딩된 회귀 테스트 갱신

**Files:**
- Modify: `skills/orca-set.version` (L1: `v1.1.8` → `v1.1.9`)
- Modify: `tests/test_log_enum_schema.py:213-227` (`test_orca_set_version_bumped`)
- Modify: `tests/test_contract_schema_fails_before_fix.py:154-162` (`test_orca_set_version_line1_is_v1_1_8`)

**Interfaces:**
- Consumes: Task 1·2가 `orca-set.version`의 세트 멤버(`orca-workflow-task`, `orca-task-runner`) content를 변경했다는 사실 — 이 저장소 관행상 세트 버전 bump가 필수(Global Constraints 참고).
- Produces: 없음(마지막 task) — 전체 회귀 스위트가 새 버전 문자열 기준으로 green이 되는 최종 상태.

- [ ] **Step 1: Write the failing check**

```bash
python3 -m pytest tests/test_log_enum_schema.py::test_orca_set_version_bumped tests/test_contract_schema_fails_before_fix.py::test_orca_set_version_line1_is_v1_1_8 -q
```

- [ ] **Step 2: Run the check to verify it currently passes against the OLD version (baseline)**

Run the command from Step 1.
Expected output: `2 passed` — this confirms the starting state (`v1.1.8`) before the bump, not a failure; the actual "red" step is Step 4 below, once the version file is bumped but the tests aren't updated yet.

- [ ] **Step 3: Bump `skills/orca-set.version`**

Use the Edit tool on `skills/orca-set.version` with:

`old_string`:
```
v1.1.8
```

`new_string`:
```
v1.1.9
```

- [ ] **Step 4: Run the check again to verify it now fails (tests still expect the old string)**

Run the command from Step 1.
Expected output: `2 failed` — both assertions still hardcode `"v1.1.8"`.

- [ ] **Step 5: Update `test_orca_set_version_bumped` in `tests/test_log_enum_schema.py`**

Use the Edit tool on `tests/test_log_enum_schema.py` with:

`old_string`:
```
    # then again per issue #113 (v1.1.7 -> v1.1.8, set member orca-workflow-task touched by that
    # issue's proposal-r2.json scope).
    # Invariant unchanged: exact version string + 6-member list are still both enforced.
    lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
    assert lines[0] == "v1.1.8"
```

`new_string`:
```
    # then again per issue #113 (v1.1.7 -> v1.1.8, set member orca-workflow-task touched by that
    # issue's proposal-r2.json scope).
    # then again per issue #141 (v1.1.8 -> v1.1.9, set members orca-workflow-task/orca-task-runner
    # touched by that issue's proposal scope).
    # Invariant unchanged: exact version string + 6-member list are still both enforced.
    lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
    assert lines[0] == "v1.1.9"
```

- [ ] **Step 6: Update `test_orca_set_version_line1_is_v1_1_8` in `tests/test_contract_schema_fails_before_fix.py`**

Use the Edit tool on `tests/test_contract_schema_fails_before_fix.py` with:

`old_string`:
```
# ---------------------------------------------------------------------------
# ac8 -- skills/orca-set.version bumped to v1.1.8 (new assertion, separate from the
# existing_tests_affected update to tests/test_log_enum_schema.py)
# ---------------------------------------------------------------------------


def test_orca_set_version_line1_is_v1_1_8():
    lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
    assert lines[0] == "v1.1.8"
```

`new_string`:
```
# ---------------------------------------------------------------------------
# ac8 -- skills/orca-set.version bumped to v1.1.8 (new assertion, separate from the
# existing_tests_affected update to tests/test_log_enum_schema.py)
# then again per issue #141 -- v1.1.8 -> v1.1.9 (separate from the
# existing_tests_affected update to tests/test_log_enum_schema.py)
# ---------------------------------------------------------------------------


def test_orca_set_version_line1_is_v1_1_9():
    lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
    assert lines[0] == "v1.1.9"
```

- [ ] **Step 7: Run the check again to verify it passes**

```bash
python3 -m pytest tests/test_log_enum_schema.py::test_orca_set_version_bumped tests/test_contract_schema_fails_before_fix.py::test_orca_set_version_line1_is_v1_1_9 -q
```

Expected output: `2 passed`

- [ ] **Step 8: Full regression run**

```bash
python3 -m pytest tests/ -q
```

Expected output: `238 passed, 4 skipped` (same baseline as before this plan's changes — confirms no other test hardcodes the old version string or the old SKILL.md wording touched in Task 1/2).

- [ ] **Step 9: Commit**

```bash
git add skills/orca-set.version tests/test_log_enum_schema.py tests/test_contract_schema_fails_before_fix.py
git commit -m "$(cat <<'EOF'
deploy: bump orca skill set to v1.1.9 (issue #141)

orca-workflow-task and orca-task-runner (both orca-set.version members) had
their SKILL.md content changed by the two preceding commits. Bump the set
version per this repo's standing practice and update the two regression
tests that hardcode the version string.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 스킬 세트 재배포

**Files:**
- None modified directly — this task runs the repo's deploy script against the already-committed state from Tasks 1-3.

**Interfaces:**
- Consumes: Task 3's commit (deploy script refuses to run against a dirty tree for any set member).
- Produces: updated `~/.agents/skills/orca-workflow-task/` and `~/.agents/skills/orca-task-runner/` (and the other 4 set members, redeployed at the same new version per AGENTS.md's all-or-nothing set rule) with `.installed-version.json` recording `v1.1.9` and the Task 3 commit hash.

- [ ] **Step 1: Confirm a clean tree for all six set members**

```bash
git status --porcelain -- skills/orca-evaluate skills/orca-retro skills/orca-task-runner skills/orca-workflow skills/orca-workflow-epic skills/orca-workflow-task
```

Expected output: nothing (clean).

- [ ] **Step 2: Deploy the set**

```bash
scripts/deploy-skills.sh orca-workflow-task orca-task-runner
```

(Passing any one set member expands to the full 6-member set per the script's set-membership logic — see `scripts/deploy-skills.sh`'s "버전 세트" section.)

Expected output: no `ABORT`/`FAIL` lines; script exits 0.

- [ ] **Step 3: Spot-check the deployed version label**

```bash
python3 -c "import json; print(json.load(open('$HOME/.agents/skills/orca-task-runner/.installed-version.json'))['version'])"
```

Expected output: `v1.1.9`

(No commit for this task — it only touches the global `~/.agents/skills/` deployment target, not this repo's git history.)

---

## Self-Review Notes

- **Spec coverage:** §결정 1 (orca-workflow-task §2 template) → Task 1. §결정 2 (orca-task-runner §7 파일 추가) → Task 2. §범위 경계의 배포 절차 언급 → Task 3(버전 bump, 이 저장소 관행에 따라 필수) + Task 4(실제 배포, AGENTS.md 명시 절차). §검토 후 기각한 대안(③ 미포함, listing 방식 미채택) → Global Constraints에 명시적으로 박아 실수로 재도입되지 않게 함.
- **Placeholder scan:** TBD/TODO 없음 — 모든 step이 리터럴 `old_string`/`new_string` 또는 실행 가능한 명령+기대 출력을 담고 있음.
- **Type consistency:** 코드 타입은 없음(prose 편집). 유일한 cross-task 의존은 Task 1→Task 2의 파일명·순서 문자열 일치인데, 두 곳 모두 정확히 같은 리터럴(`eval-report-a<attempt>.json` → `proposal-r<확정라운드>.json`)을 쓰는지 Task 2 Step 1/4의 grep이 기계적으로 검증한다. Task 3의 두 테스트 함수명(`test_orca_set_version_bumped`, `test_orca_set_version_line1_is_v1_1_9` — 기존 `..._v1_1_8`에서 리네임)이 Step 5/6/7에서 일관되게 사용됨을 확인함.
