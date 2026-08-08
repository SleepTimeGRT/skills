#!/usr/bin/env bash
# deploy-skills.sh — 이 repo의 skills/를 글로벌 agent 경로에 배포한다.
#
# 배포 구조:
#   ~/.agents/skills/<name>/   전체 스킬 디렉터리 복사(정본 저장소)
#   ~/.claude/skills/<name>    → ../../.agents/skills/<name> 상대 symlink(없으면 생성)
#   ~/.codex/skills/<name>/    과거 배포본은 commit-pin 메타데이터가 있을 때 제거
#   배포본에 .installed-version.json (version/commit/date/hash) 기록
#     - hash = SKILL.md의 sha256 (기존 형식과 호환)
#     - version = 사람이 관리하는 라벨. --version 없으면 기존 설치본 값을 유지,
#       설치본이 없으면 v0.0.0. 실질적 pin은 commit+hash다.
#   - 버전 세트: skills/orca-set.version(1행 = 버전, 이후 행 = 멤버 이름)에 묶인
#     스킬들은 항상 같은 버전으로 함께 배포된다 — 멤버가 하나라도 지정되면 세트
#     전체로 확장하고, 버전은 세트 파일 값만 쓰며(--version과 다르면 중단),
#     멤버 중 하나라도 dirty면 세트 전체를 배포하지 않는다(부분 배포 금지).
#
# 안전 규칙:
#   - 대상 스킬의 working tree가 dirty면 중단한다 — .installed-version.json의
#     commit이 실제 배포 내용과 달라지는(거짓 기록) 것을 막기 위해서다. 커밋 후 재실행.
#   - 배포 후 SKILL.md sha256을 원본과 대조 검증하고 불일치면 비0 종료.
#
# 사용법:
#   scripts/deploy-skills.sh [--version vX.Y.Z] [skill-name ...]
#   (skill-name 생략 시 skills/ 아래 전부)
#
# 테스트 훅: DEPLOY_HOME 환경변수로 $HOME을 대체할 수 있다(fixture 테스트용).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"
HOME_DIR="${DEPLOY_HOME:-$HOME}"

VERSION_ARG=""
NAMES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION_ARG="${2:?--version requires a value}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) NAMES+=("$1"); shift ;;
  esac
done

if [ ${#NAMES[@]} -eq 0 ]; then
  while IFS= read -r d; do NAMES+=("$(basename "$d")"); done \
    < <(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d | sort)
fi

# ── 버전 세트(헤더 주석 참고) ─────────────────────────────────────────────
SET_FILE="$SKILLS_DIR/orca-set.version"
SET_VERSION=""
SET_MEMBERS=()
if [ -f "$SET_FILE" ]; then
  { IFS= read -r SET_VERSION
    while IFS= read -r m; do [ -n "$m" ] && SET_MEMBERS+=("$m"); done; } < "$SET_FILE"
fi

in_set() {
  local n="$1" m
  [ ${#SET_MEMBERS[@]} -eq 0 ] && return 1
  for m in "${SET_MEMBERS[@]}"; do [ "$m" = "$n" ] && return 0; done
  return 1
}

if [ ${#SET_MEMBERS[@]} -gt 0 ]; then
  need_set=0
  for n in "${NAMES[@]}"; do in_set "$n" && need_set=1; done
  if [ "$need_set" -eq 1 ]; then
    if [ -n "$VERSION_ARG" ] && [ "$VERSION_ARG" != "$SET_VERSION" ]; then
      echo "ABORT: 세트 멤버의 버전은 skills/orca-set.version($SET_VERSION)이 정본 — --version $VERSION_ARG 와 충돌. 세트 파일을 수정·커밋 후 재실행" >&2
      exit 1
    fi
    for m in "${SET_MEMBERS[@]}"; do
      found=0
      for n in "${NAMES[@]}"; do [ "$n" = "$m" ] && found=1; done
      [ "$found" -eq 0 ] && NAMES+=("$m")
    done
    for m in "${SET_MEMBERS[@]}"; do
      if [ -n "$(git -C "$REPO_ROOT" status --porcelain -- "skills/$m")" ]; then
        echo "ABORT: 세트 멤버 skills/$m 에 커밋되지 않은 변경 — 세트는 전부-아니면-전무로 배포한다(버전 어긋남 방지). 커밋 후 재실행" >&2
        exit 1
      fi
    done
  fi
fi

COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
DATE="$(date +%Y-%m-%dT%H:%M:%S%z | sed 's/\([0-9][0-9]\)$/:\1/')"
FAIL=0

for name in "${NAMES[@]}"; do
  src="$SKILLS_DIR/$name"
  if [ ! -f "$src/SKILL.md" ]; then
    echo "SKIP $name: $src/SKILL.md 없음" >&2; FAIL=1; continue
  fi
  if [ -n "$(git -C "$REPO_ROOT" status --porcelain -- "skills/$name")" ]; then
    echo "ABORT $name: skills/$name 에 커밋되지 않은 변경 — 커밋 후 재실행" >&2; FAIL=1; continue
  fi

  skill_fail=0
  hash="$(shasum -a 256 "$src/SKILL.md" | awk '{print $1}')"
  if in_set "$name"; then
    version="$SET_VERSION"
  else
    version="$VERSION_ARG"
  fi
  if [ -z "$version" ]; then
    existing="$HOME_DIR/.agents/skills/$name/.installed-version.json"
    if [ -f "$existing" ]; then
      version="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('version','v0.0.0'))" "$existing")"
    else
      version="v0.0.0"
    fi
  fi

  dst="$HOME_DIR/.agents/skills/$name"
  mkdir -p "$dst"
  rsync -a --delete "$src/" "$dst/"
  printf '{\n  "version": "%s",\n  "commit": "%s",\n  "date": "%s",\n  "hash": "%s"\n}\n' \
    "$version" "$COMMIT" "$DATE" "$hash" > "$dst/.installed-version.json"
  got="$(shasum -a 256 "$dst/SKILL.md" | awk '{print $1}')"
  if [ "$got" != "$hash" ]; then
    echo "FAIL $name: $dst/SKILL.md sha256 불일치" >&2; FAIL=1; skill_fail=1
  fi

  legacy="$HOME_DIR/.codex/skills/$name"
  if [ -f "$legacy/.installed-version.json" ]; then
    rm -rf -- "$legacy"
  fi

  link="$HOME_DIR/.claude/skills/$name"
  if [ -L "$link" ]; then
    : # 이미 symlink — 대상은 정본 경로라 갱신 불필요
  elif [ -e "$link" ]; then
    echo "FAIL $name: $link 가 symlink가 아닌 실제 파일/디렉터리 — 수동 확인 필요" >&2; FAIL=1; skill_fail=1
  else
    mkdir -p "$HOME_DIR/.claude/skills"
    ln -s "../../.agents/skills/$name" "$link"
  fi

  [ "$skill_fail" -eq 0 ] && echo "OK $name ($version, ${COMMIT:0:7}, sha256 ${hash:0:12}…)"
done

exit "$FAIL"
