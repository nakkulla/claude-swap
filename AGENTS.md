# claude-swap fork — 에이전트 가이드

`realiti4/claude-swap`(MIT)의 개인 fork다. `origin`은 `nakkulla/claude-swap`,
`upstream`은 원본이다. fork 고유 변경은 Beads로 추적하고, 그 밖의 코드와 동작은
upstream이 정본이다.

## upstream 추적

- base는 `main`이다. upstream 반영은 `git fetch upstream` 뒤 `upstream/main`을
  `main`에 merge하는 커밋 하나로 한다. rebase나 force-push로 이력을 다시 쓰지 않는다.
- fork 고유 변경은 작게, 기존 모듈 안에서 끝낸다. upstream 파일의 대규모 재배치·
  포맷 변경은 merge 충돌만 늘리므로 하지 않는다.
- fork 전용 파일은 `AGENTS.md`, `CLAUDE.md`, `docs/`로 한정한다. upstream에 PR을
  보낼 때는 이 파일들을 뺀 별도 브랜치를 쓴다.
- `.beads/`는 `bd init`의 fork 보호로 `.git/info/exclude`에 들어가 커밋하지 않는다.
  Beads 데이터는 중앙 dolt(`claude_swap` DB)에 있고, worktree의 `bd`는 이 checkout의
  `.beads`를 찾아 쓴다.

## 환경

- `uv`만 쓴다. 환경은 `uv sync --locked`로 repo-local `.venv`에 만들고, 실행은
  `uv run ...`으로 한다. 시스템 python·pip 직접 설치는 쓰지 않는다.
- 실제로 설치된 `cswap`은 `uv tool`로 PyPI 버전을 설치한 별도 사본이다. fork를
  설치본으로 바꾸는 일은 승인된 스펙의 배포 절차로만 한다.

## 검증

- 기본 검증: `uv run pytest` (pytest-xdist로 기본 병렬, CI와 같은 명령).
- 좁은 검증: `uv run pytest tests/<file>.py`.
- ADR 인용 검사: `python3 ~/.claude/skills/adr/scripts/adr-cite-check.py --repo .`

## 실제 계정 보호

- 테스트는 autouse 가짜 Keychain과 real-store guard(`tests/test_real_store_guard.py`)
  위에서만 돈다. 이 guard를 끄거나 우회하는 테스트를 만들지 않는다.
  → 실제 `~/.claude`·Keychain의 토큰은 실행 중인 Worker들이 쓰고 있다.
    한 번 덮어쓰면 그 Worker의 로그인이 풀린다.
- 개발 중 실제 계정에 `cswap switch`·`run`·`add`·`remove` 같은 변경 명령을 돌리지
  않는다. 실측이 필요하면 명령과 대상 계정을 먼저 사용자에게 승인받는다.

## Beads와 설계 결정

- 이 저장소는 중앙 Beads를 쓴다(`bd prime`). 작업 흐름은 전역 workflow 규칙을 따른다.
- 설계 결정의 정본은 `docs/adr/README.md`의 "현재 유효한 결정"이다. 인덱스는
  생성물이라 직접 편집하지 않는다(`adr` 스킬).
