---
name: project-setup
description: Invoke explicitly via `/project-setup` — do not phrase-match. One-time-per-repo onboarding for project-level agent config docs under `docs/agents/`: issue tracker (`issue-tracker.md`) and agent-e2e tooling (`e2e-tooling.md`). Idempotent — sections whose doc already exists are skipped and reported as already-configured. `orca-workflow` §0 and `~/.agents/orca-workflows/issue-trackers/selection.md` §2 both redirect here instead of onboarding inline. Self-relative.
---

# Project Setup

대상 repo에 아직 없는 `docs/agents/*.md` 온보딩 문서를 만든다. 인자 없이 아래 섹션을 순서대로
확인한다 — 이미 있는 문서는 스킵하고 "이미 설정됨"만 보고한다.

**크로스툴 이식성**: "사용자에게 직접 묻는다"는 표현을 일반적으로만 쓴다 — 특정 도구(예: Claude
Code의 질문 UI)의 이름을 이 문서 본문에 넣지 않는다. 플랫폼마다 자기 방식으로 묻는다.

## 1. Issue tracker

`docs/agents/issue-tracker.md`가 있으면 스킵.

없으면 사용자에게 직접 묻는다: ①이 repo가 GitHub Issues를 쓰는지, 다른 트래커(Jira/Linear 등)를
쓰는지 ②(GitHub가 아니면) 그 tracker의 API를 부르는 데 필요한 최소 정보(Jira라면 site·cloudId·
project key) ③"완료" transition/상태 이름 ④acceptance-criteria가 적히는 섹션 이름.

**GitHub면 문서를 만들지 않고 이 섹션을 종료한다** — 숫자 ID 폴백(`~/.agents/orca-workflows/
issue-trackers/selection.md` §2)이 문서 부재를 전제로 동작하므로, 여기서 GitHub 전용 문서를 만들면
그 폴백 경로가 깨진다.

다른 트래커면 받은 답으로 `docs/agents/issue-tracker.md` 형식의 초안을 작성해 사용자에게 보여주고,
승인되면 별도의 작은 커밋으로 대상 repo에 반영한다. 이후 실행부터는 문서가 있으므로 이 섹션이 다시
트리거되지 않는다.
