---
name: model-claude-code
description: Claude Code(Anthropic) 모델·effort 용도 — coordinator·SDD 구현 워커·task 리뷰
---

# Claude Code (Anthropic)

**verified_at: 2026-07-26 — re-verify trigger: any new Claude model release (`platform.claude.com/docs/en/about-claude/models/overview`), not a calendar cadence.**

coordinator 세션과 SDD 구현 워커에 쓰는 provider.

launch: `claude --model <id> --effort <low|medium|high|xhigh|max>`. SDD 구현 워커는 `--permission-mode bypassPermissions`(빌드·테스트 실행에 Bash 전체 필요, worktree 격리 전제). **`claude-opus-5`는 Claude Code >= 2.1.219 필요** — 그 이전 버전은 `/model` picker에 없고 선택 자체가 안 된다(`code.claude.com/docs/en/model-config`, 2026-07-26 확인).

| 모델 | 강점 | 용도 | effort |
|---|---|---|---|
| `claude-opus-5` | 최상위 판단 | coordinator, high-risk 직접 작업, Claude Code `/advisor` 리뷰 백엔드. **오탐 비용이 큰 리뷰엔 Opus 5** — 정밀도 우선, Sol보다 커버리지 낮음(2026-07 웹 리서치, CodeRabbit·BSWEN 방향 일치·수치 미확정) | xhigh (coordinator는 세션값). **`/advisor` 백엔드는 예외 — 아래 "advisor 도구" 항목 참고, effort 지정 불가** |
| `claude-sonnet-5` | 균형 | 통합·판단 구현 | high |
| `claude-haiku-4-5-20251001` | 빠르고 저렴 | 전사·기계적 구현 | — (effort 미지원) |

`claude-fable-5`는 사용하지 않는다 — Anthropic 공식 발표 기준(`anthropic.com/news/claude-opus-5`, 2026-07-26 확인) OSWorld 2.0·CursorBench 3.2에서 Fable 5와 동등 이상 성능을 절반 이하 가격($5/$25 vs $10/$50)으로 낸다. high-risk 작업은 Opus 5로 통일한다. Fable 5가 맡던 "Routine이지만 설계 비중 큰 구현"은 Opus 5가 아니라 Sonnet 5(high)가 맡는다 — Opus 5를 primary generator로 쓰는 건 아래에 있는 대로 task 자체가 high-risk일 때뿐이고, 아키텍처 "결정" 자체는 High Risk tier로 승격한다.

**Claude Code 안전 분류기가 launch 모델을 바꿀 수 있다 (Automatic model fallback).** cybersecurity/biology로 flag된 요청은 launch한 모델이 아니라 다음 모델에서 재실행된다 — worker의 실제 실행 모델은 launch 인자만으로 보장되지 않는다:

- Opus 5 + cybersecurity flag → `claude-opus-4-8`에서 자동 재실행, transcript에 notice 표시
- Opus 5 + biology flag → fallback 없음(Opus 5는 자체 biology 분류기를 돌리며 fallback 대상이 없다), refusal로 종료
- Fable 5 + biology flag → 세션 전체가 Opus 5로 전환되고, 이후 biology-flag 요청은 거기서도 refusal
- 첫 요청(워크스페이스 컨텍스트 — CLAUDE.md·git status 포함)만으로도 트리거될 수 있다
- 카테고리별 fallback은 Claude Code >= 2.1.219부터 동작한다. 그 이전 버전은 Fable 5의 모든 flag가 provider 기본 Opus로 재실행됐고 Opus 5는 fallback 대상이 아니었다
- `--output-format json`에서는 결과의 `modelUsage` 필드로 실제 실행 모델을 확인한다(대화형 transcript notice의 프로그램적 대응)

출처: `code.claude.com/docs/en/model-config`("Automatic model fallback", 2026-07-26 확인). 게이트 워커 검증 절차는 `../model-selection.md` §2, 탐지 신호는 `../spawn-failures.md` 참조.

- **Sonnet 5 패턴(routine 기본)**: Sonnet 5 @ high로 작업하고, 더 깊은 리뷰가 필요하면 generator effort를 올리는 대신 **Claude Code의 advisor 도구**(model = Opus 5)로 리뷰받는다. `/advisor`는 **Sonnet 5로 작업할 때** 쓴다. advisor의 effort는 아래 "advisor 도구" 항목 참고 — xhigh로 고정된다는 이전 서술은 근거가 없어 삭제했다.
- Opus를 primary generator로 직접 쓰는 건 task가 high-risk일 때뿐. Opus 5를 **별도 세션으로 스폰해 리뷰시키는 경우**(orca-evaluate §1/§3처럼 독립 터미널을 띄우는 패턴)는 advisor 도구가 아니라 일반 launch이므로 `--effort`가 정상 적용된다 — advisor 도구와 혼동하지 않는다.
- Haiku 4.5는 Anthropic effort 파라미터 지원 모델 목록에 없다 → haiku 워커는 `--effort`를 **생략**한다. `--effort`는 나머지 2개 모델에만 준다.
- effort 지원: xhigh/max는 Opus 5·Sonnet 5, high는 Haiku 제외 전 모델. **Opus 5의 API 기본값은 `high`다** — Opus 4.7/4.8의 "xhigh로 시작" 권장을 그대로 재사용하지 않는다. 공식 문서: "Start with high, the default... If you carried effort settings over from an earlier model, run a fresh effort sweep on your evals rather than reusing them"(`platform.claude.com/docs/en/build-with-claude/effort`, 2026-07-26 확인). architecture/auth/migration/crypto/production-review처럼 demanding한 coding·agentic 작업엔 `xhigh`로 올리는 것을 권장하고, `low`/`medium`은 평가로 품질이 유지되는 범위에서 주 비용 통제 수단으로 쓴다. max는 프런티어 문제 전용(과추론·비용 위험).
- **Opus 5 @ xhigh를 다른 provider effort의 캘리브레이션 기준점으로 쓴다** — 단 Anthropic이 Opus 5의 SWE-Bench Pro 수치를 공식 공개하지 않으므로(2026-07-26 확인) 이건 "동일 축 벤치마크 비교"가 아니라 조직 내부 기준점이다.

evaluator로도 쓸 수 있다 — cross-model 강제 없음, fresh-context 원칙은 `orca-evaluate` 스킬 참조.

### advisor 도구 (`/advisor`, `--advisor`, `advisorModel`)

Claude Code의 advisor는 **모델만 선택하고 effort는 선택할 수 없는** 별도 기능이다 — 세션 전체를 특정 모델로 바꾸는 `/model`이나 별도 세션을 새로 띄우는 것과 다르다. 공식 문서(`code.claude.com/docs/en/advisor`, `platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool`, 둘 다 2026-07-26 확인) 기준:

- **CLI 플래그**: `--advisor <model>`은 실제로 존재하는 플래그이지만 **`claude --help`에는 나오지 않는다**(문서에 명시: "isn't listed in `claude --help`"). `--model`과 조합해 쓴다 — 예: `claude --model sonnet --advisor opus`. 세션당 1회성이며 `advisorModel` 설정보다 우선한다.
- **다른 설정 방법**: 세션 중 `/advisor opus`, 또는 설정 파일의 `advisorModel` 필드로 영구 기본값 지정.
- **effort는 노출되지 않는다**: `/advisor`·`--advisor`·`advisorModel` 어디에도 effort 인자가 없다. API 레벨 advisor tool 문서도 effort 관련 절("Pairing with effort settings")에서 **executor의** effort만 다루고 advisor 쪽 effort는 언급하지 않는다. `usage.iterations[]`의 `advisor_message` 항목도 `model`·토큰 수만 보고하고 effort 필드가 없다 — 실행 후에도 advisor가 어떤 effort로 돌았는지 확인할 방법이 없다. 따라서 "Opus 5 xhigh 백엔드"처럼 특정 effort를 단정하는 서술은 전부 근거 없는 값이며, 이 문서와 `../model-selection.md`에서 제거했다.
- **Anthropic API 전용**: advisor 도구는 Amazon Bedrock·Claude Platform on AWS(API 레벨 tool은 지원)·Google Cloud·Microsoft Foundry에서 가용성이 다르다 — Claude Code의 `/advisor`·`--advisor`는 Anthropic API 세션에서만 동작한다(문서: "It is not available on Amazon Bedrock, Claude Platform on AWS, Google Cloud's Agent Platform, or Microsoft Foundry").
- **모델 페어링 제약**: advisor는 main model보다 같거나 더 강해야 한다. Sonnet 5 main은 Fable 5·Opus 5·Sonnet 5만 advisor로 받아들이고 Sonnet 4.6은 거부된다.
- **용도 범위**: 공식 문서는 advisor를 "장기 multi-step 작업 중 대부분은 routine이지만 plan 품질이 성패를 가르는" 상황에 맞춘다고 설명한다 — 매 턴 최강 모델이 필요한 작업이나, 계획할 게 거의 없는 단문 작업에는 가치가 적다고 명시(`/model`로 세션 모델 자체를 바꾸는 편이 낫다).
