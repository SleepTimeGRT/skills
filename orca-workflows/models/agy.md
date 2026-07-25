---
name: model-agy
description: agy(Gemini/Google) 모델·effort 용도 — coordinator·구현 워커·evaluator 어디에나 쓸 수 있음, quota가 넉넉해 적합한 작업엔 우선 고려
---

# agy (Gemini / Google)

**verified_at: 2026-07-25**

quota가 넉넉해 coordinator·구현 워커·evaluator 어디에든 적합한 작업엔 우선 고려한다.

launch: `agy -p '<지침 + diff·report 경로>' --model <token> --print-timeout 15m --dangerously-skip-permissions`. effort는 모델 토큰 suffix(`-high|-medium|-low`) 또는 `--effort`로 지정한다.

**`--dangerously-skip-permissions` 필수**: 없으면 tool 호출(예: 파일 읽기용 `command`)이 headless에서 **exit 0인 채로 조용히 auto-deny**된다(`jetski: no output produced — ... auto-denied`) — 멈추는 게 아니라 아무 일도 안 하고 성공한 것처럼 끝나는 쪽이라 더 위험하다(#15, Claude 쪽 `--permission-mode bypassPermissions`와 동등한 목적).

workspace-trust 등록 여부는 이 게이트와 무관하다(2026-07-25 실측, launch 디렉터리 내부 파일 접근 기준) — 등록/미등록 모두 플래그 없이는 auto-deny, 플래그를 주면 성공한다. launch 디렉터리 바깥 경로 접근은 미검증.

agy는 `model-selection.md` Default Mapping에서 Simple tier(코드/구현 판단)와 Computer Use/Long-Context 축(실행·리포팅, 판단 아님)에만 배정된다 — Routine/High Risk 코드 판단엔 쓰지 않는다(SWE-Bench Pro 근거는 아래).

| 모델 토큰 | 용도 | effort |
|---|---|---|
| `gemini-3.6-flash-high` | Computer Use/Long-Context 축 내 고정확도 필요 시(예: 다중 로그 skeptical 대조). flash의 effort 천장(위에 xhigh/max 없음) | high |
| `gemini-3.6-flash-medium` | Computer Use/Long-Context 축 기본값 — agent e2e(컴퓨터/브라우저 조작 실행 + 결과 요약, `skills/orca-evaluate/SKILL.md` §2). "판단"이 아니라 실행·리포팅이라 high가 benchmark상 강제되지 않음 | medium |
| `gemini-3.6-flash-low` | Simple tier(간단·기계적 작업) | low |

`gemini-3.5-flash-*`는 retire — `gemini-3.6-flash`(2026-07-21 릴리스, `agy models`에 노출)로 완전히 대체한다:

- **가격**(공개 API 리스트가, per 1M token): `$1.50 in / $7.50 out`, 캐시 히트 `$0.15`. 이전 세대(3.5-flash, `$1.50 in / $9.00 out`) 대비 output이 16.7% 저렴 — 전환에 토큰 단가 손해 없음.
- **벤치**: OSWorld-Verified(컴퓨터 사용) 83.0%, BU Benchmark(Browser Use사, 브라우저 자동화) 68%, GDM-MRCR v2 128k(롱컨텍스트) 91.8% — 이전 세대(각각 78.4%/58%/77.3%) 대비 세 축 모두 개선. 컴퓨터/브라우저 사용 개선폭이 가장 커서 `orca-evaluate`의 agent-e2e(Playwright MCP) 용도와 직결된다. **이 수치들은 공개 자료 어디에도 effort(low/medium/high)별로 나뉘어 있지 않다** — 모델 세대 전체의 점수다(위 테이블의 agent e2e = medium 배정은 §2가 "판단"이 아니라 실행·리포팅이라는 근거에서 나온 것이지, 이 벤치 수치에서 나온 게 아니다).
- **유보 사항(미확인)**: quota·rate-limit이 이전 세대와 동일한지는 공개 문서에서 모델별 차이를 찾지 못했다 — "가격/성능이 이득"이 "총 비용이 이득"을 보장하진 않는다. 실사용 중 429/quota-skip 빈도가 늘면 여기 기록하고 verified_at을 갱신할 것.
- 참고: raw Gemini API(REST/SDK) 레벨에서 `temperature`/`top_p`/`thinking_budget` 등 일부 파라미터가 3.x에서 deprecate된다는 보고가 있으나, `agy` CLI는 이 파라미터들을 노출하지 않으므로 이 리포의 launch 패턴엔 영향 없음.
- 출처: 가격·벤치 모두 웹 검색 기준(OpenRouter/ArtificialAnalysis/Browser Use/Google 블로그 등 2026-07-21~22 게시물) — 이 리포에서 직접 측정한 수치는 아니다.

`agy models`에 `gemini-3.1-pro-*`도 있다 — flash 계열이 에이전틱 벤치(Terminal-Bench·MCP Atlas 등)에서 이를 앞서 현행 기본. `gemini-3.6-flash` SWE-Bench Pro는 **58.7%**(2026-07-25 웹 리서치 확인: codingfleet.com SWE-bench Pro leaderboard, buildfastwithai.com 교차확인). Codex Terra(63.4%)·Sol(64.6%)·Opus 앵커보다 낮고, Coding Agent Index류 agentic 코딩 지표는 공개 자료에서 아직 못 찾음 — tier 배정은 `model-selection.md` 참고.

**agent e2e(Playwright)**: agy/Antigravity CLI에 BrowserMCP를 설정하면 accessibility-tree 기반 Playwright 브라우저 조작이 가능하다(`~/.gemini/settings.json` 또는 Antigravity CLI 설정에 MCP 서버 등록). 스크린샷·좌표 클릭보다 UI 변경에 덜 깨지므로 `orca-evaluate`의 agent-e2e 스트림은 이 조합(agy + BrowserMCP)을 기본으로 한다 — 실제 launch 전 이 리포에서 BrowserMCP 연결 자체를 한 번 스모크 테스트할 것.

스모크(2026-07-25): `gemini-3.6-flash-high` 부팅·응답 exit 0, permission 게이트(위 참고)도 함께 확인. 모델 세대 교체 시 재검증 후 verified_at 갱신.

quota·오류로 호출이 skip될 수 있다 — 그때의 대체 처리는 `orca-evaluate`/`orca-task-runner` 스킬의 폴백 절이 소유한다.
