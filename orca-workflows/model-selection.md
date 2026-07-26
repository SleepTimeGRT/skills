# Model Selection

> verified_at: 2026-07-25

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

---

# Default Mapping

| Tier | Provider | Model | Effort | Note |
|------|----------|-------|--------|------|
| High Risk | Claude | `claude-opus-5` | xhigh | architecture / auth / migration / crypto / production review / final approval |
| High Risk | Codex | `gpt-5.6-sol` | xhigh (high = cost floor) | architecture / auth / migration / crypto / production review / final approval |
| Routine | Claude | `claude-sonnet-5` | high | primary generator |
| Routine | Claude | `claude-opus-5` | xhigh | advisor/reviewer only — not primary generator unless the task itself is High Risk |
| Routine | Codex | `gpt-5.6-terra` | medium | primary generator; escalate to Sol when additional reasoning is required |
| Simple | Claude | `claude-haiku-4-5-20251001` | — (effort 미지원) | transcription, boilerplate, mechanical edits |
| Simple | Codex | `gpt-5.6-luna` | low | ⚠️ 부팅 스모크 미검증 — launch 전 `codex exec`로 먼저 확인(`models/codex.md`). MRCR 41.3%로 대형 diff/장문 컨텍스트엔 부적합 |
| Simple | Gemini (agy) | `gemini-3.6-flash-low` | low | 간단·기계적 작업. Routine 승격은 보류 — SWE-Bench Pro 58.7%(Terra 63.4% 대비 -4.7pt) |

`claude-fable-5`는 사용하지 않는다 — Opus 5가 대부분 벤치마크(SWE-bench Pro, Frontier-Bench, GDPval-AA v2)에서 Fable 5와 동등 이상이면서 가격은 절반이다(2026-07-25 웹 리서치로 확인, 상세는 Benchmarks 섹션). High Risk 티어도 동일하게 Opus 5를 쓴다.

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

These values are informational only.

| Model | SWE-Bench Pro |
|--------|---------------|
| Claude Opus 5 | Reference anchor |
| GPT-5.6 Sol | 64.6% |
| GPT-5.6 Terra | 63.4% |
| Gemini 3.6 Flash | 58.7% |

Gemini 3.6 Flash 수치는 2026-07-25 웹 리서치로 확인(codingfleet.com SWE-bench Pro leaderboard, buildfastwithai.com 교차확인) — 상세는 `models/agy.md`.

Opus 5 vs Fable 5(2026-07-25 웹 리서치, codersera.com·benchlm.ai 교차확인): SWE-bench Verified는 Opus 5 96% vs Fable 5 95%, SWE-bench Pro는 1%p 이내로 동률, Frontier-Bench(43.3% vs 33.7%)·GDPval-AA v2(1,861 vs 1,747)·ARC-AGI-3는 Opus 5 우위. 가격은 Opus 5 $5/$25, Fable 5 $10/$50(1M 토큰당, input/output) — Opus 5가 대부분 벤치마크에서 동등 이상이면서 절반 가격이라 Fable 5를 별도로 쓸 이유가 없다.

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