# pre-push nvm PATH 해결 + GUI 클라이언트 우회 — Design

**Date**: 2026-07-25
**Status**: Approved (brainstorming phase) — pending implementation plan
**Related**: GitHub issue #8 (SleepTimeGRT/sleeptimegrt-skills)

## Context

이슈 #8은 두 가지를 묶어서 제안했다: (1) `token-gate.sh`에 NVM/FNM/Volta/ASDF/MISE
전부를 위한 PATH 보정 로직 추가, (2) `.githooks/pre-push`에 env var 또는 config 파일
기반 우회(skip) 옵션 추가. 실제 불편의 진원은 사용자가 Fork(GUI git 클라이언트)로 직접
간단한 수정을 push할 때 `pnpm: command not found`(exit 127)로 훅이 막히는 것과, 막혔을
때 터미널처럼 `git push --no-verify`를 즉석에서 타이핑할 방법이 Fork에는 없다는 것이다.

두 조사 결과가 이슈 원안을 상당히 좁혔다.

**PATH 문제의 실제 원인**: 이 머신에는 NVM만 설치되어 있다(FNM/Volta/ASDF/MISE 디렉터리
전부 부재 확인됨). `pnpm`은 `~/.nvm/versions/node/v22.18.0/bin/pnpm`에서 resolve된다.
`~/.zshrc`에는 이미 한 번 겪었던 동일 계열 버그의 흔적이 남아있다: `nvm`/`node`/`pnpm`을
lazy-load 함수로 감쌌더니 "비대화형 subshell에서 래퍼 함수가 상속되지 않아 command not
found 스팸만 유발"했고, 그 우회로 `v22.18.0` bin 경로를 `.zshrc`에 하드코딩해뒀다
(줄 116-130). 하지만 zsh는 `.zshrc`를 **interactive 셸에서만** 읽는다. Fork Preferences
→ Git 탭의 `ENV PATH` 설정은 `System shell '/bin/zsh'`로 이미 최선값이 선택되어 있었지만,
Fork가 내부적으로 어떤 셸 모드(로그인/비대화형 등)로 그 값을 계산하는지는 비공개라
확인 불가 — 다만 증상이 "interactive-only 파일이 안 읽힌 경우"와 정확히 일치한다.

**Fork 우회 수단 조사**: Fork Preferences 전체(General/Git/Integration/Custom Commands)를
`computer-use`로 직접 열어 확인했다. Git 탭의 `ENV PATH` 드롭다운은 `Parent process +
brew (default)` / `Parent process` / `System shell '/bin/zsh'` 3개뿐이며 커스텀 PATH나
env var 입력란은 없다. Integration 탭에는 hook-skip이나 env var 설정이 없다. 반면 **Custom
Commands** 탭은 "Repository Custom Command"를 Action → Bash Command로 만들 수 있고,
`${git}`(Fork가 쓰는 git 실행 파일 경로), `${repo:path}`, `${repo:name}` 변수를 제공한다 —
즉 `${git} -C "${repo:path}" push --no-verify`를 등록하면 터미널에서 `--no-verify`를
타이핑하는 것과 동일한 동작을 Fork 안에서 원클릭으로 재현할 수 있다.

## 결정

### 1. PATH 보정 — `token-gate.sh`에 NVM 전용 fallback만 추가

```sh
if ! command -v pnpm >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  . "$HOME/.nvm/nvm.sh" --no-use
  nvm use >/dev/null 2>&1 || nvm use default >/dev/null 2>&1
fi
```

- `pnpm`이 이미 PATH에 있으면 아무 것도 하지 않는다 (정상적인 터미널 push는 영향 없음).
- 없을 때만 `nvm.sh`를 직접 source하고, 저장소에 `.nvmrc`가 있으면 `nvm use`가 그 버전을,
  없으면 `nvm use default`가 `~/.nvm/alias/default`(현재 `lts/*` → v22.18.0)를 선택한다.
- `env -i HOME="$HOME" SHELL=/bin/bash PATH="/usr/bin:/bin" bash -c '...'`로 Fork와
  동등한 최소 PATH 환경을 재현해 실측 검증 완료 — `.nvmrc` 있음/없음 두 경로 모두 확인.
- FNM/Volta/ASDF/MISE는 이 머신에 설치된 근거가 없으므로 추가하지 않는다(추측성 사전
  대응 금지 원칙). 다른 저장소에서 실제로 이 문제가 관측되면 그 증거를 근거로 그때
  추가한다.
- `.githooks/pre-commit`은 현재 `token-gate.sh`를 source하지 않고 `pnpm exec biome`을
  직접 호출한다(줄 21). Fork로 커밋할 때도 동일 원인으로 같은 오류가 날 수 있으므로,
  `pre-commit` 맨 위에 `. "$REPO_ROOT/scripts/token-gate.sh"`를 추가한다 — 이 파일이
  정의하는 `token_gate_*` 함수를 pre-commit이 호출할 필요는 없고, source 시점에 실행되는
  PATH 보정 부작용만 필요하다.

### 2. GUI 클라이언트 우회 — 훅/저장소 변경 없음, Fork 쪽 개인 설정으로 해결

Fork Preferences → Custom Commands → "Add Repository Custom Command" → Action을
Bash Command로 설정하고 스크립트에 `${git} -C "${repo:path}" push --no-verify`를
넣는다. 이 설정은 사용자의 로컬 Fork 앱 설정(`~/Library/Application Support/
com.DanPristupov.Fork/custom-commands.json`)에만 저장되며, 저장소나 스킬 템플릿에는
아무 파일도 추가되지 않는다.

기존 `.githooks/pre-push`의 주석("bypass: `git push --no-verify` — WIP branches only")이
이미 문서화한 우회 방법 그대로이므로, 정책이나 템플릿 문구를 바꿀 필요가 없다. Fork
설정 등록은 사용자가 본인 머신에서 직접 하는 일회성 작업이며 이 스킬의 "Apply to a
repository" 절차에도 포함하지 않는다(레포별이 아니라 Fork 앱별 설정이라서).

### 3. 검토 후 기각한 대안

- **저장소에 커밋되는 `.githooks/pre-push.conf`의 SKIP 플래그** (이슈 원안): 커밋되면
  이 레포를 체크아웃하는 모든 대상 — 에이전트가 push할 때도 포함 — 에 조용히 적용돼
  "훅은 결정적이어야 한다"는 정책 취지와 충돌한다. 깜빡하고 계속 켜진 채로 남을 위험도
  크다.
- **Fork의 env var 설정에 SKIP_PRE_PUSH 심기**: Fork에 그런 입력란 자체가 없음을
  Preferences 전수 확인으로 검증했다.
- **worktree-local 마커 파일** (`$(git rev-parse --git-dir)/skip-pre-push`): PATH 수정
  전 단계에서 검토했던 옵션. Custom Commands로 `--no-verify`를 직접 실행할 수 있다는
  게 확인된 이상 더 간단한 대안(2번)이 있어 채택하지 않는다.
- **git-native pre-push를 Claude Code `PreToolUse` 같은 agent 훅으로 대체**: Fork 수동
  push가 애초에 걸리지 않게 되어 사용자 의도에는 가장 정확히 부합하지만, (a) Codex에
  동등한 pre-execution 차단 이벤트가 있는지 이번 세션에서 검증되지 않았고, (b) git
  계층의 "누가 push하든 무조건 걸린다"는 무조건적 보장을 잃으며 정규식이 못 잡는
  호출 경로로 새어나갈 수 있고, (c) `lifecycle-hook-contracts` 스킬이 명시적으로 그어둔
  경계("Stop 훅만 다루고, git-native 훅은 `lifecycle-gate-policy` 소유")를 넘는 더 큰
  구조 변경이 필요하다. 이번 이슈 범위에서는 채택하지 않고, 별도 이슈로 필요성이
  재확인되면 그때 Codex 쪽부터 검증한다.

## 테스트 계획

- `env -i` 최소 PATH 환경에서 `.nvmrc` 있음/없음 두 경우 모두 `pnpm`/`node`가 resolve되는지 재확인.
- `pnpm`이 이미 PATH에 있는 정상 터미널 환경에서 fallback 분기가 타지 않는지(사이드이펙트 없음) 확인.
- `pre-commit`에 `token-gate.sh` source 추가 후 gitleaks → biome 순서가 그대로 동작하는지 확인(스테이징된 변경 없는 커밋, 있는 커밋 둘 다).
- `pre-push`에서 실제로 `pnpm verify:static`이 PASS/FAIL 모두 기존과 동일하게 동작하는지 회귀 확인.
- `python3 skills/lifecycle-gate-policy/scripts/audit.py --repo <fixture>` 로 드리프트 감사 통과 확인.

## 범위 경계

- 이 스킬(`sleeptimegrt-skills`)의 캐노니컬 템플릿(`assets/scripts/token-gate.sh`,
  `assets/githooks/pre-commit`)만 변경한다. 대상 저장소(medicount 등)에는 사용자가
  명시적으로 재적용을 요청할 때만 반영한다.
- Fork Custom Command 등록은 문서화 대상이 아니라 사용자의 로컬 1회성 설정으로 남긴다 —
  SKILL.md나 `agents-policy.md`에 특정 GUI 클라이언트 이름을 박아넣지 않는다("skills엔
  역사/특정 클라이언트 참조 남기지 않는다" 원칙).
