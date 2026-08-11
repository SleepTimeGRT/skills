---
name: project-setup
description: >-
  Invoke explicitly via `/project-setup` — do not phrase-match. One-time-per-repo onboarding for
  project-level agent config docs under `docs/agents/`: issue tracker (`issue-tracker.md`) and
  agent-e2e tooling (`e2e-tooling.md`). Idempotent — sections whose doc already exists are skipped and
  reported as already-configured. `orca-workflow` §0 and
  `~/.agents/orca-workflows/issue-trackers/selection.md` §2 both redirect here instead of onboarding
  inline. Self-relative. Do NOT use for general repo scaffolding, project bootstrapping, or CI setup —
  this skill only creates the one-time `docs/agents/` config docs.
compatibility: Requires the `orca` CLI (skill set last verified against Orca app 1.4.180), the `~/.agents/orca-workflows/` symlink to this repo's orca-workflows/, and the `gh` CLI.
---

# Project Setup

대상 repo에 아직 없는 `docs/agents/*.md` 온보딩 문서를 만든다. 인자 없이 아래 섹션을 순서대로
확인한다 — 이미 있는 문서는 스킵하고 "이미 설정됨"만 보고한다.

**크로스툴 이식성**: "사용자에게 직접 묻는다"는 표현을 일반적으로만 쓴다 — 특정 도구(예: Claude
Code의 질문 UI)의 이름을 이 문서 본문에 넣지 않는다. 플랫폼마다 자기 방식으로 묻는다.

## 1. Issue tracker

`docs/agents/issue-tracker.md`가 있으면 스킵. ("이미 설정됨"은 이 문서 파일과, 이를 가리키는
AGENTS.md/CLAUDE.md의 "Issue tracker" pointer가 함께 있는 상태를 뜻한다 — 스킵 판정 자체는 문서
파일 존재만 기계적으로 확인하는데, 아래 흐름이 이제 문서와 pointer를 항상 같이 만들기 때문이다.
pointer 없이 문서만 있는 기존 repo의 마이그레이션은 이 작업의 범위 밖이다.)

없으면 사용자에게 직접 묻는다: ①이 repo가 GitHub Issues를 쓰는지, 다른 트래커(Jira/Linear 등)를
쓰는지 ②(GitHub가 아니면) 그 tracker의 API를 부르는 데 필요한 최소 정보(Jira라면 site·cloudId·
project key) ③"완료" transition/상태 이름.

**GitHub면 문서를 만들지 않고 이 섹션을 종료한다** — 숫자 ID 폴백(`~/.agents/orca-workflows/
issue-trackers/selection.md` §2)이 문서 부재를 전제로 동작하므로, 여기서 GitHub 전용 문서를 만들면
그 폴백 경로가 깨진다.

다른 트래커면 받은 답으로 `docs/agents/issue-tracker.md` 형식의 초안을 작성해 사용자에게 보여주고,
승인되면 같은 승인 단계에서 대상 repo의 AGENTS.md(그 repo가 CLAUDE.md를 쓰면 CLAUDE.md)에 이 문서를
가리키는 "Issue tracker" pointer 섹션(예: `### Issue tracker` 헤딩, `docs/agents/issue-tracker.md`
링크 — `~/.agents/orca-workflows/issue-trackers/selection.md` §1이 찾는 패턴과 동일)을 추가하거나
이미 있는지 확인한다. 문서와 pointer를 함께 별도의 작은 커밋으로 대상 repo에 반영한다. 이후
실행부터는 문서가 있으므로 이 섹션이 다시 트리거되지 않는다.

## 2. E2E tooling

`docs/agents/e2e-tooling.md`가 있으면 스킵.

없으면 **무조건** 사용자에게 직접 묻는다(GitHub 같은 무조건-기본값이 없다) — ①Platform(자유
텍스트, 예시: `web`/`native-android`/`native-ios`/`desktop`) ②Tool(MCP/도구 이름 — Platform이
`web`류면 기본 제안으로 "Playwright MCP"를 보여주되, 사람이 최종 승인한다) ③Usage guidance(그
도구를 쓸 때 알아야 할 사항 — accessibility-tree 기반인지, YAML 시나리오인지 등) ④Precondition(연결
전 충족해야 하는 인프라 조건 — 에뮬레이터 부팅, 앱 사전 설치 등).

받은 답으로 아래 형식의 초안을 작성해 사용자에게 보여주고, 승인되면 별도의 작은 커밋으로 대상
repo에 반영한다:

```markdown
# E2E Tooling

## Platform
<답변>

## Tool
<답변>

## Usage guidance
<답변>

## Precondition
<답변, 없으면 "없음">
```

이후 실행부터는 문서가 있으므로 이 섹션이 다시 트리거되지 않는다. `orca-evaluate` §2가 이 문서를
agent-e2e 스폰 시 읽는다.
