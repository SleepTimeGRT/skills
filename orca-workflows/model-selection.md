# Model Selection

> verified_at: 2026-07-26 — re-verify trigger: any new Claude model release (check `https://platform.claude.com/docs/en/about-claude/models/overview`), not a calendar cadence. Four Claude releases landed between 2026-06-09 and 2026-07-24; a fixed re-check interval will always lag that.

Select the model and effort **before launch**.

This file owns the **tier → model/effort mapping** below. Provider documents own launch flags, pricing, effort semantics, and model-specific caveats.

Workflow orchestration (issue-drain, contract 협상, evaluate 판정, task-runner wave 구성)은 `orca-workflow`·`orca-task-runner`·`orca-evaluate`가 관리한다.

---

# Rules

## 1. Classify the task

Choose the highest applicable tier.

| Tier | Typical work |
|-------|--------------|
| **High Risk** | Architecture, auth, RLS, migration, crypto, server logic, production review |
| **Routine** | Feature development, refactor, debugging, testing, code review |
| **Simple** | Formatting, rename, boilerplate, transcription |

If uncertain, choose the higher tier.

---

## 2. Launch with explicit model/effort

Model and effort are fixed at launch.

Examples

- orca terminal argv
- Agent model
- Workflow model

Never assume the CLI automatically chooses effort.

When reusing an existing worker, verify that its launch model still matches the current task.

**Launch precondition (Claude Code)**: `claude-opus-5` 실행 전 CLI 버전을 확인한다 — 최소 버전 기준과 출처는 `models/claude-code.md` 참조.

**Claude Code 런타임이 이 원칙(model/effort fixed at launch)을 깬다.** `claude-opus-5`로 launch해도 Claude Code의 안전 분류기가 요청을 cybersecurity/biology로 flag하면 세션이 자동으로 다른 모델에서 재실행된다 — launch 인자만으로는 워커가 실제로 어느 모델에서 응답을 만들었는지 보장되지 않는다. 정확한 동작은 `models/claude-code.md`("Automatic model fallback"), 탐지 신호는 `spawn-failures.md` 참조.

**High Risk 게이트 워커는 확인한다**: `modelUsage`(json 실행) 또는 transcript notice(대화형)에 `claude-opus-4-8`이 잡히면 리포트를 "Opus 4.8에서 실행됨"으로 정정, biology-flag refusal이면 PASS/FAIL 대신 인간 ESCALATE. 상세: `spawn-failures.md`.

---

# Default Mapping

| Tier | Provider | Model | Effort | Note |
|------|----------|-------|--------|------|
| High Risk | Claude | `claude-opus-5` | xhigh | architecture / auth / migration / crypto / production review / final approval. Review는 오탐 비용이 클 때 이쪽(정밀도 우선) |
| High Risk | Codex | `gpt-5.6-sol` | xhigh (high = cost floor) | architecture / auth / migration / crypto / production review / final approval. Review는 놓치면 안 될 때 이쪽(재현율 우선) |
| Routine | Claude | `claude-sonnet-5` | high | primary generator, 설계 비중 큰 구현 포함(Fable 5가 맡던 자리) — 아키텍처 "결정" 자체는 High Risk tier로 승격 |
| Routine | Claude | `claude-opus-5` | xhigh (별도 세션으로 스폰할 때만 적용) | reviewer only — not primary generator unless the task itself is High Risk. **advisor 도구(`/advisor`·`--advisor`)로 붙일 때는 effort 자체를 지정할 수 없다** — 이 xhigh는 orca-evaluate §1/§3처럼 Opus 5를 독립 세션으로 새로 launch하는 경우에만 적용되는 값. 상세: `models/claude-code.md`("advisor 도구") |
| Routine | Codex | `gpt-5.6-terra` | medium | primary generator; escalate to Sol when additional reasoning is required |
| Simple | Claude | `claude-haiku-4-5-20251001` | — (effort 미지원) | transcription, boilerplate, mechanical edits |
| Simple | Codex | `gpt-5.6-luna` | low | ⚠️ 부팅 스모크 미검증 — launch 전 `codex exec`로 먼저 확인(`models/codex.md`). MRCR 41.3%로 대형 diff/장문 컨텍스트엔 부적합 |
| Simple | Gemini (agy) | `gemini-3.6-flash-low` | low | 간단·기계적 작업. Routine 승격은 보류 — SWE-Bench Pro 58.7%(Terra 63.4% 대비 -4.7pt) |

`claude-fable-5`는 사용하지 않는다 — Anthropic 공식 발표(`anthropic.com/news/claude-opus-5`, 2026-07-26 확인) 기준 OSWorld 2.0·CursorBench 3.2에서 Fable 5와 동등 이상 성능을 절반 이하 가격($5/$25 vs $10/$50, 1M 토큰당)으로 낸다. High Risk 티어도 동일하게 Opus 5를 쓴다.

**Effort는 이전 모델에서 그대로 들고 오지 않는다** — Opus 5 API 기본값은 `high`이며, 공식 문서는 이전 모델 값 재사용 대신 새 effort sweep을 권장한다(원문 인용·상세 근거는 `models/claude-code.md` effort 항목 참조). 위 표의 xhigh는 그 스윕 결과가 아니라 architecture/auth/migration/crypto/production-review급 demanding 작업이라는 판단으로 유지한 것 — Routine 이하로 내려가는 재사용은 금지한다는 뜻이다.

**xhigh가 과한 건 아닌지 재검토(2026-07-26 웹 리서치)**: `platform.claude.com/docs/en/build-with-claude/effort`의 effort 레벨 표는 xhigh를 "long-running agentic and coding tasks (over 30 minutes) with token budgets in the millions"로 정의한다. 반면 `skills/orca-evaluate/SKILL.md` §1(contract 검토)·§3(diff 리뷰)가 실제로 스폰하는 High Risk 게이트 워커는 **경계가 뚜렷한 단발 리뷰**다 — diff/제안서 하나를 읽고 승인/반려나 finding을 내는 일이지, 30분 이상 이어지는 장기 에이전틱 루프가 아니다. 이 형태만 보면 공식 문서가 "difficult coding problems"의 typical use case로 명시한 `high`가 더 정확히 들어맞는다. 그럼에도 xhigh를 유지하는 이유는 이 스윕 결과가 아니라 **오탐/누락 비용이 비대칭적으로 큰 최종 게이트라 정밀도를 비용보다 우선한다는 판단**이지, "장기 작업이라 xhigh"라는 근거는 아니다 — 위 문단의 표현을 이 지점만큼은 정정한다. 값을 낮출 근거가 아니라 근거 자체를 바로잡은 것이니 유지 결정은 그대로다. 비용이 문제가 되면 이 게이트 워커 한정으로 `high` 시범 운영 후 report 품질을 비교해볼 것.

**Claude Sonnet 5 pattern**: Sonnet 5(high)로 생성하고, 더 깊은 리뷰가 필요하면 generator effort를 올리는 대신 advisor 도구(model=Opus 5)로 리뷰받는다. advisor의 effort는 지정·확인이 불가능하다 — "xhigh 백엔드"라는 이전 서술은 근거가 없어 삭제했다. launch 문법·API 세부사항은 `models/claude-code.md`("advisor 도구") 소유.

---

## Computer Use / Long-Context Skeptical Cross-Check

Separate axis from the risk tiers above — doesn't replace them. A task can be Routine risk *and* need this axis (e.g. agent-driven UI e2e is routine risk but benefits from computer-use strength).

Use when the task:

- drives a browser/desktop directly (agent e2e, Playwright-based UI testing)
- re-reads multiple raw logs/artifacts skeptically, to catch what each artifact's own summary might miss and correlate failures across streams

Do **not** use this axis just because a stream produces a log — deterministic structured output (TAP, JUnit/JSON reporters) needs a parser, not a model. This axis is for when trusting a summary at face value is the risk, not a substitute for log parsing.

**Exclusion**: technical judgment calls never belong on this axis, even when the calling session itself runs on it. `orca-evaluate`'s session defaults here for its own log/e2e work, but its two judgment calls (§1 contract approval, §3 diff review of `skills/orca-evaluate/SKILL.md`) are spawned to a separate High Risk tier session instead.

| Provider | Model | Why |
|----------|-------|-----|
| Gemini (agy) | `gemini-3.6-flash-medium` | Computer use 83%(OSWorld-Verified), browser automation 68%(BU Benchmark), long-context (MRCR v2 128k) 91.8% — see `~/.agents/orca-workflows/models/agy.md`. Playwright 기반 agent e2e와 가장 직접 관련 있는 수치는 BU Benchmark 쪽이다 — OSWorld-Verified는 데스크톱 컴퓨터 사용 전반이라 브라우저 자동화 품질의 대리지표로는 약하다. agy.md도 명시하듯 이 수치들은 effort별로 나뉘어 있지 않다(세대 전체 점수). |
| Claude | `claude-sonnet-5` (medium) | **agy 쿼터 소진 시 fallback.** OSWorld-**Verified**(컴퓨터 사용) 81.2% — 위 Gemini의 83%와 **같은 벤치 스위트라 직접 비교 가능**, 근접한 점수(2026-07 웹 리서치). 1M 토큰 네이티브 컨텍스트로 Gemini의 128k MRCR 실측치를 상회. 가격은 $2/$10(~2026-08-31 introductory) → $3/$15(표준), Opus 5($5/$25)의 40~60% 수준 — 이 축이 judgment가 아니라 실행·리포팅이라는 §Exclusion 원칙에 따라 Opus 5 대신 Sonnet 5를, 그중에서도 `high`가 아니라 `medium`을 골랐다(agy.md가 Gemini에 medium을 배정한 논리와 동일). **주의**: BU Benchmark(브라우저 자동화, Playwright e2e와 더 직접 관련)의 Sonnet 5 수치는 미확인 — OSWorld 근접이 브라우저 e2e 근접을 보장하지 않는다. effort를 medium으로 낮췄을 때 tool-call 검증이 얕아질 위험(공식 문서의 "낮은 effort일수록 tool call 감소·확인 없이 행동" 경고)도 미검증 — 실사용 중 §2의 skeptical 재확인 단계에서 품질 저하가 보이면 `high`로 올릴 것. Opus 5(OSWorld 2.0 70.6%, 다른 스위트라 위 수치와 직접 비교 불가)는 정밀도가 더 중요해지면 대안으로 남겨둔다. |

Consumer: `orca-evaluate` §2 (agent-e2e gate + raw-trace re-check) and §4 (report synthesis). Its §1/§3 sub-sessions are deliberately *not* consumers — those stay on High Risk. agy fallback 발동 시점(429/quota-skip 감지)과 처리 절차는 `orca-evaluate`/`orca-task-runner`의 폴백 절이 소유 — 이 표는 fallback **모델**만 지정한다.

⚠️ **Long-context 근거 재확인 필요**: 위 라우팅의 long-context 수치는 128k MRCR v2 기준이다. Claude Opus 5·Sonnet 5는 모두 Anthropic API에서 1M 토큰 컨텍스트를 네이티브로 갖는다(`anthropic.com/news/claude-opus-5`·`code.claude.com/docs/en/model-config`, 2026-07-26 확인). 이 축의 라우팅 근거는 computer-use·browser-automation 강점이지 long-context 단독이 아니므로 그대로 유지하지만, long-context만 필요한 작업이라면 128k 대 1M 비교 없이 Gemini 우위를 전제할 수 없다 — A/B 없이는 이 축을 long-context 단독 사유로 확장하지 말 것.

---

# Provider Preference

**Routine** — if multiple providers are appropriate:

1. Claude Sonnet 5
2. Codex Terra

**Simple** — if multiple providers are appropriate:

1. Claude Haiku 4.5
2. Codex Luna (부팅 스모크 검증 후)
3. Gemini (agy) flash-low

Escalate immediately to higher tiers for:

- architecture
- security
- migration
- production incidents
- final review

---

# Provider Documents

- Claude Code
  - `~/.agents/orca-workflows/models/claude-code.md`

- Codex
  - `~/.agents/orca-workflows/models/codex.md`

- agy (Gemini)
  - `~/.agents/orca-workflows/models/agy.md`