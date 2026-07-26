---
name: model-codex
description: Codex(OpenAI) 모델·effort 용도 — coordinator·구현 워커·evaluator 어디에나 쓸 수 있음(cross-model 강제 없음)
---

# Codex (OpenAI)

**verified_at: 2026-07-26**

`gpt-5.6-*` 계열. coordinator·구현 워커·evaluator 어디에나 쓴다. evaluator로 쓸 때는 fresh-context(별도 세션)이기만 하면 되고 provider가 같아도 된다 — 원칙은 `orca-evaluate` 스킬.

launch: `codex --model <id> -c model_reasoning_effort=<low|medium|high|xhigh>` (게이트 리뷰는 `-s workspace-write -a never`로 read-only 슬라이싱 승인 없이, headless는 `codex exec`).

| 모델 | 강점 | 용도 | effort |
|---|---|---|---|
| `gpt-5.6-sol` (Sol) | 최상위 추론 + 장문 recall(MRCR 91.5%, SWE-Bench Pro 64.6%). $5/$30 per 1M | 정확성이 결정적인 리뷰·분석: server 로직·schema/migration·크립토·RLS/auth | xhigh (high=비용 floor) |
| `gpt-5.6-terra` (Terra) | Sol 근접(MRCR 89.6%, SWE-Bench Pro 63.4%, Coding Agent Index 77), 출력 절반가 $2.50/$15 | Routine tier 전반: 기능 구현·리팩터·디버깅·테스트·코드 리뷰(`model-selection.md` Routine 정의와 동일 범위). 기본 codex 리뷰어·구현 워커 | medium |
| `gpt-5.6-luna` (Luna) | 저가 $1/$6, 고속·고볼륨. Coding Agent Index 75로 Opus 4.8(72.5) 상회 — 단 MRCR(장문 recall) 41.3%로 Sol/Terra 대비 급락 | 짧은 컨텍스트의 경량 작업: 전사·분류·라우팅, 대량 병렬 서브태스크(`model-selection.md` Simple tier). ⚠️ 대형 diff/로그를 훑는 코드 리뷰·장문 컨텍스트 작업엔 MRCR 근거로 부적합 — 이 축은 대체하지 않음 | low |

effort는 `-c model_reasoning_effort=<minimal|low|medium|high|xhigh>`로 지정한다. xhigh는 medium 대비 비용이 크게 뛴다 — 고위험 게이트는 Claude Opus 5 xhigh 앵커(`../model-selection.md` 참조, SWE-Bench Pro 등 동일 축 벤치마크가 아니라 조직 내부 캘리브레이션 기준점)에 맞춰 Sol도 xhigh, 비용이 문제면 high로 내린다.

스모크(2026-07-21, `codex exec`): `gpt-5.6-terra`(medium)·`gpt-5.6-sol`(high·xhigh) 부팅·응답 exit 0. `gpt-5.6-luna`는 아직 부팅 스모크 없음 — 실제 워커로 launch하기 전에 먼저 `codex exec`로 검증할 것. 모델 세대 교체 시 재검증 후 verified_at 갱신.

Coding Agent Index 수치(Terra 77, Luna 75, Opus 4.8 72.5): 2026-07-25 웹 리서치(Artificial Analysis) — 이 repo에서 직접 스모크 검증한 값은 아니다.
