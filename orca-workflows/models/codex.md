---
name: model-codex
description: Codex(OpenAI) worker model and effort selection for coordinators, implementers, and evaluators
---

# Codex (OpenAI)

Use GPT-5.6 workers with an explicit model and effort. Evaluators require fresh context, not a different
provider.

Launch (orchestration 왕복이 필요한 REPL 워커/코디네이터):

```bash
codex --model <id> -c model_reasoning_effort=<effort> --dangerously-bypass-approvals-and-sandbox
```

`--dangerously-bypass-approvals-and-sandbox`(단일 플래그, `-s danger-full-access -a never` 상당)가 orca
파이프라인의 codex posture다. 근거 2가지:

1. `-s workspace-write` 샌드박스 하에서 워커의 orca orchestration 회신(`worker_done`)이 도달하지 않는
   문제가 반복 관측됐고, bypass posture에서는 왕복이 검증됐다(2026-08-08, Orca 1.4.176 — dispatch 주입
   → 커밋 → `worker_done` 송신 → task `completed`/`provenance: worker_report`까지 완주,
   sleeptimegrt-skills#84의 검증 기록).
2. contract/log 산출물 경로(`~/.local/state/orca-workflows/…`)가 워크스페이스 밖이라 workspace-write로는
   쓸 수 없다(`contract-schema.md`의 launch posture 전제).

안전 전제는 **워크트리 격리**다 — main 체크아웃 등 격리 밖에서 이 posture로 launch하지 않는다. Orca
GUI의 codex 에이전트 설정(인수 필드)도 같은 플래그를 쓴다 — `--agent codex` 경로와 명시 `--command`
경로가 같은 posture를 유지해야 한다.

Use `codex exec` for headless runs. orchestration 회신이 필요 없는 1회성 headless 실행에는 위 posture를
요구하지 않는다 — `-s workspace-write` permits reads and writes inside the workspace (not read-only);
use `-s read-only` when the reviewer must not write. Approval policy is separate from the sandbox
boundary.

## Mapping

| Model | Use | Orca effort |
|---|---|---|
| `gpt-5.6-sol` | High Risk implementation and final review | high; xhigh for security/final gates with asymmetric miss cost |
| `gpt-5.6-terra` | Routine implementation and bounded first-pass triage | medium |
| `gpt-5.6-luna` | Clear, repeatable, high-volume work; narrow-context routine subtasks | medium |

Routine review path: Terra may triage a bounded diff, but final or high-risk judgment escalates to Sol.
Luna's role is clear, repeatable, high-volume work.

## Effort support

Use the lowest reasoning effort that produces the required result, then increase it when the task needs
more planning, analysis, or checking. `max` is for the hardest single-agent problems. Ultra uses automatic
task delegation. Do not use `ultra` for Orca workers; Orca owns parallel decomposition explicitly.

## Launch precondition

`gpt-5.6-luna` has no recorded boot smoke in this repository — it has never been dispatched to a real
worker here (confirmed by grepping `assignments*.jsonl`, 2026-08-04: zero occurrences). Before its first
real worker launch at the `max` effort above, run one bounded `codex exec` smoke and record the result in
the reference. This precondition is unchanged by the low→max effort update; it was never satisfied at any
effort level.

Load [the Codex evidence reference](../references/models/codex.md) only when auditing, changing, or
re-validating this mapping.
