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

**Launch precondition (Claude Code)**: `claude-opus-5` requires Claude Code >= 2.1.219. Below that version it doesn't appear in the `/model` picker and can't be selected at all — check `claude --version` before assuming a launch script's `--model claude-opus-5` will work. Source: `code.claude.com/docs/en/model-config` (2026-07-26 확인).

**Claude Code 런타임이 이 원칙(model/effort fixed at launch)을 깬다.** `claude-opus-5`로 launch해도 Claude Code의 안전 분류기가 요청을 cybersecurity/biology로 flag하면 세션이 자동으로 다른 모델에서 재실행된다 — launch 인자만으로는 워커가 실제로 어느 모델에서 응답을 만들었는지 보장되지 않는다. 정확한 동작은 `models/claude-code.md`("Automatic model fallback"), 탐지 신호는 `spawn-failures.md` 참조.

**High Risk 게이트 워커는 반드시 확인한다**: `--output-format json` 실행이면 결과의 `modelUsage`에 `claude-opus-4-8` 키가 잡히는지, 대화형이면 transcript의 모델 치환 notice를 확인한다. 잡히면 게이트 리포트에 "Opus 5 xhigh로 실행"이 아니라 "cybersecurity 재실행으로 Opus 4.8에서 실행됨"이라고 정정해서 기록한다. High Risk 작업 정의(auth/RLS/crypto/security review)가 정확히 cyber 분류기를 트리거하는 영역과 겹치므로, 이 확인을 생략하면 게이트가 침묵 속에 4.8로 실행되고도 리포트는 Opus 5로 실행됐다고 주장하게 된다. biology flag로 refusal이 나면 fallback이 없으므로(Opus 5는 자체 biology 분류기를 돌리며 fallback 모델이 없다) PASS/FAIL이 아니라 인간 리뷰로 ESCALATE한다.

---

# Default Mapping

| Tier | Provider | Model | Effort | Note |
|------|----------|-------|--------|------|
| High Risk | Claude | `claude-opus-5` | xhigh | architecture / auth / migration / crypto / production review / final approval |
| High Risk | Codex | `gpt-5.6-sol` | xhigh (high = cost floor) | architecture / auth / migration / crypto / production review / final approval |
| Routine | Claude | `claude-sonnet-5` | high | primary generator, 설계 비중 큰 구현 포함(Fable 5가 맡던 자리) — 아키텍처 "결정" 자체는 High Risk tier로 승격 |
| Routine | Claude | `claude-opus-5` | xhigh | advisor/reviewer only — not primary generator unless the task itself is High Risk |
| Routine | Codex | `gpt-5.6-terra` | medium | primary generator; escalate to Sol when additional reasoning is required |
| Simple | Claude | `claude-haiku-4-5-20251001` | — (effort 미지원) | transcription, boilerplate, mechanical edits |
| Simple | Codex | `gpt-5.6-luna` | low | ⚠️ 부팅 스모크 미검증 — launch 전 `codex exec`로 먼저 확인(`models/codex.md`). MRCR 41.3%로 대형 diff/장문 컨텍스트엔 부적합 |
| Simple | Gemini (agy) | `gemini-3.6-flash-low` | low | 간단·기계적 작업. Routine 승격은 보류 — SWE-Bench Pro 58.7%(Terra 63.4% 대비 -4.7pt) |

`claude-fable-5`는 사용하지 않는다 — Anthropic 공식 발표(`anthropic.com/news/claude-opus-5`, 2026-07-26 확인) 기준 OSWorld 2.0에서 "Opus 5 outperforms every other model at any given cost, surpassing Fable 5's best result at just over a third of the cost", CursorBench 3.2에서 "at max effort, the model performs within 0.5% of Fable 5's peak score, but at half the cost per task" — Fable 5와 동등 이상 성능을 절반 이하 가격($5/$25 vs $10/$50, 1M 토큰당)으로 낸다. 상세는 Benchmarks 섹션. High Risk 티어도 동일하게 Opus 5를 쓴다.

**Effort는 이전 모델에서 그대로 들고 오지 않는다.** Opus 5의 API 기본값은 `high`다 — Opus 4.7/4.8의 "xhigh로 시작" 권장을 그대로 재사용하면 안 된다. 공식 문서: "If you carried effort settings over from an earlier model, run a fresh effort sweep on your evals rather than reusing them"(`platform.claude.com/docs/en/build-with-claude/effort`, 2026-07-26 확인). 위 표의 xhigh는 그 스윕 결과가 아니라 architecture/auth/migration/crypto/production-review처럼 "demanding coding and agentic work"에 해당한다는 판단으로 유지한 것이며, 공식 문서도 이런 작업엔 xhigh로 올릴 것을 권장한다 — Routine 이하로 내려가는 재사용은 금지한다는 뜻이다.

**Claude Sonnet 5 pattern**: Sonnet 5(high)로 생성하고, 더 깊은 리뷰가 필요하면 generator effort를 올리는 대신 `/advisor`(Opus 5 xhigh)로 리뷰받는다.

```
Sonnet 5 (high)
      ↓
/advisor opus (xhigh)
```

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
| Gemini (agy) | `gemini-3.6-flash-medium` | Computer use 83%, browser automation 68%, long-context (MRCR v2 128k) 91.8% — see `~/.agents/orca-workflows/models/agy.md`. |

Consumer: `orca-evaluate` §2 (agent-e2e gate + raw-trace re-check) and §4 (report synthesis). Its §1/§3 sub-sessions are deliberately *not* consumers — those stay on High Risk.

⚠️ **Long-context 근거 재확인 필요**: 위 라우팅의 long-context 수치는 128k MRCR v2 기준이다. Claude Opus 5는 1M 토큰 컨텍스트를 기본값이자 최댓값으로 갖는다(`anthropic.com/news/claude-opus-5`, 2026-07-26 확인). 이 축의 라우팅 근거는 computer-use·browser-automation 강점이지 long-context 단독이 아니므로 그대로 유지하지만, long-context만 필요한 작업이라면 128k 대 1M 비교 없이 Gemini 우위를 전제할 수 없다 — A/B 없이는 이 축을 long-context 단독 사유로 확장하지 말 것.

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

# Benchmarks (Reference Only)

These values are informational only. **Single-axis, cross-provider comparisons don't hold** — each lab reports its own suite, so a model leading on one axis can trail on another that neither side publishes in the same units. This is exactly why High Risk keeps cross-model gates (e.g. Claude generator + Codex reviewer) instead of picking one "best" model off this table.

| Model | SWE-Bench Pro | 출처 |
|--------|---------------|------|
| GPT-5.6 Sol | 64.6% | 미검증 — 이번 재검증 대상은 Claude 쪽 소스뿐이었다. 출처는 `models/codex.md` 참조(거기도 출처 표기 없음) |
| GPT-5.6 Terra | 63.4% | 미검증 — 이번 재검증 대상은 Claude 쪽 소스뿐이었다. 출처는 `models/codex.md` 참조(거기도 출처 표기 없음) |
| Gemini 3.6 Flash | 58.7% | 2026-07-25 웹 리서치(codingfleet.com SWE-bench Pro leaderboard, buildfastwithai.com 교차확인) — `models/agy.md` |
| Claude Opus 5 | 미공개 | Anthropic이 공식 공개하지 않음(2026-07-26 확인, `anthropic.com/news/claude-opus-5`의 벤치마크 목록은 Frontier-Bench v0.1·CursorBench 3.2·ARC-AGI 3·Zapier AutomationBench·OSWorld 2.0·GDPval-AA v2·HLEAutomationBench·DeepSearchQA뿐, SWE-Bench Pro 없음) — 위 세 수치와 직접 비교 불가 |

Claude Opus 5 자체 벤치마크(Anthropic 공식 발표 원문, 2026-07-26 확인 — 수치가 아니라 정성적 비교만 공개됨):

- Frontier-Bench v0.1: "Opus 5 surpasses all other models, and more than doubles Opus 4.8's performance at a lower cost per task."
- CursorBench 3.2: "At max effort, the model performs within 0.5% of Fable 5's peak score, but at half the cost per task."
- ARC-AGI 3: "Opus 5's score is three times as high as the next-best model."
- OSWorld 2.0: "Opus 5 outperforms every other model at any given cost, surpassing Fable 5's best result at just over a third of the cost."
- 가격: $5/$25 per 1M 토큰(input/output) — Opus 4.8과 동일. Fable 5는 $10/$50.

이전 버전에 있던 "SWE-bench Verified 96% vs 95%", "Frontier-Bench 43.3% vs 33.7%", "GDPval-AA v2 1,861 vs 1,747" 수치는 2026-07-25 제3자 웹 리서치(codersera.com·benchlm.ai)로만 확인됐던 것으로, 이번 재검증에서 Anthropic 공식 소스로 재확인되지 않아 제거했다 — Anthropic은 이 벤치마크들에서 정성적 비교만 공개하고 구체적 스코어는 공개하지 않는다.

Benchmarks help align tiers.

Model selection should always be based on **task risk**, not benchmark scores alone.

---

# Provider Documents

- Claude Code
  - `~/.agents/orca-workflows/models/claude-code.md`

- Codex
  - `~/.agents/orca-workflows/models/codex.md`

- agy (Gemini)
  - `~/.agents/orca-workflows/models/agy.md`