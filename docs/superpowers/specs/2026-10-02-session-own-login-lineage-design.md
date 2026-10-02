---
scope:
  - src/claude_swap/session.py
  - src/claude_swap/switcher.py
  - src/claude_swap/autoswitch.py
  - src/claude_swap/json_output.py
  - src/claude_swap/cli.py
  - tests/
  - repo-ops/
  - AGENTS.md
---

# 세션 프로필 독립 로그인 계열 — Worker 계정 전환 충돌 제거 (claude-swap-q2v)

- 작성일: 2026-10-02
- 소유 Bead: `claude-swap-q2v` (rig `claude-swap`, fork `nakkulla/claude-swap`)
- 기준 커밋: fork `main` `1c4df930251b769f8a961426a7699ac7c01b8a6d`

## 1. 배경

beads-ui Worker는 `cswap run <계정>`으로 계정별 세션 프로필(`CLAUDE_CONFIG_DIR`)에서
Claude Code를 실행한다. cswap은 이 프로필에 계정 백업 토큰을 **복사**해 심고, 프로필과
백업 사이를 양방향으로 동기화해 "계정 하나 = 토큰 계열 하나"를 유지한다. 같은 계정을
기본 로그인으로 전환하면 회전하는 refresh 토큰 계열 하나가 두 저장소(기본 로그인 키체인,
세션 프로필 키체인)에 동시에 살아 있게 되고, 먼저 갱신한 쪽만 살아남는다. 그래서
`cswap switch`는 경고를 내거나 전환을 거부하고, beads-ui는 전환 전 확인 창을 띄운다.

같은 계정이라도 OAuth 로그인을 따로 하면 서로 무관한 토큰 계열(grant)이 생긴다.
세션 프로필이 자기 로그인 계열을 갖고 cswap이 그 계열을 다른 저장소와 섞지 않으면
충돌 원인 자체가 사라진다.

## 2. 검증된 전제

- 세션 프로필은 백업 토큰을 `.credentials.json`으로 복사해 시딩한다 — `src/claude_swap/session.py:860`, `:907`
- `setup_session`은 실행 전 백업 grant를 갱신하고, stale 표식·지문 불일치·검증 실패 때 백업으로 재시딩하거나 프로필을 지운다 — `session.py:690`, `:693`, `:706`, `:792`, `:799`, `:826`
- 백업이 바뀌면 프로필 자격을 무효화하거나 stale 표식을 남긴다 — `switcher.py:784`(`_post_backup_write`)
- 백업 갱신 gate는 프로필이 더 새 세대면 그 토큰을 백업으로 옮긴다 — `switcher.py:2174`
- 프로필이 앞선 세대면 전환 때 백업으로 흡수하고, live면 전환을 거부·경고한다 — `switcher.py:2779`, `:2830`, `:6738`, `:6769`
- 사용량 조회는 프로필 토큰을 우선 읽고 흡수를 시도한다 — `switcher.py:4808`, `:4865`
- 자동 전환은 live 세션 계정을 건너뛴다 — `autoswitch.py:782`
- 기본 로그인과 같은 계정이면 `run`은 세션 없이 기본 로그인으로 실행한다(fast path) — `session.py:582`
- `list --json` 행은 추가 필드만 덧붙이는 관례를 쓴다 — `json_output.py:305`, `:344`
- `claude auth login --claudeai --email <email>`과 `claude auth status --json`이 있다 — `claude auth login --help`(Claude Code 2.1.287), `session.py:1009`
- beads-ui Worker는 `cswap run <email> --share-history`로 실행한다 — beads-ui `server/worker/runner/claude.js:910`
- beads-ui 전환 API는 Worker가 쓰는 계정이면 `account_in_use`를 돌려주고, 행 정규화는 모르는 필드를 버린다 — beads-ui `server/routes/account-switch.js:295`, `server/routes/claude-usage.js:112`
- 설치본은 PyPI `claude-swap` 0.25.0을 `uv tool`로 설치한 것이고, cswap launch agent는 없다 — `uv tool list`, `launchctl list`
- 이 Mac의 계정은 3·4번 두 개이고 둘 다 세션 프로필이 있다 — `cswap list --json`
- 미확인: 같은 계정의 새 OAuth 로그인이 기존 grant(기본 로그인)를 취소하지 않는다 — 여러 기기 동시 로그인 관행으로 추정, 수용 기준 L2에서 실측

## 3. 목표와 비목표

목표: 세션 프로필이 독립 로그인 계열을 가진 계정은, Worker가 실행 중이어도 기본 로그인을
그 계정으로 전환할 수 있고 양쪽 로그인이 모두 유지된다.

비목표: Codex 계정 전환 문제, 독립 로그인이 없는 계정의 기존 복사 방식 변경,
upstream PR 제출, PyPI 업데이트 알림 변경.

## 4. 설계

### 4.1 계열 경계 (핵심 불변식)

결정: 세션 프로필 안에 **독립 로그인 표식**이 있으면 그 프로필의 토큰 계열은 프로필만
소유한다. cswap은 그 계열을 백업·기본 로그인으로 복사하지 않고, 백업 계열로 그 프로필을
덮어쓰지도 않는다. 표식이 없는 프로필은 지금과 똑같이 동작한다.

표식은 프로필 디렉터리 안의 작은 JSON 파일이다(예: `.cswap-own-login.json`,
`{email, organizationUuid, createdAt}`). 쓰는 곳은 `cswap session login` 하나다(재로그인은
지우고 새로 쓴다). 지우는 곳은 그것과 `cswap session logout`, 프로필 삭제뿐이다. 판정은 한 곳의 술어로 모은다(예: `has_own_login(session_dir)`).

표식이 있을 때 경로별 동작:

| 경로 | 지금 | 독립 로그인 프로필 |
|---|---|---|
| `setup_session` 백업 grant 선갱신 (`session.py:706`) | 실행 | 건너뜀 |
| stale 표식·지문 불일치 재시딩 (`:690`, `:792`) | 재시딩 | 건너뜀 |
| 재사용 검사 실패 (`:693`)·시딩 뒤 검증 `invalid` (`:826`) | 재시딩, 그래도 실패면 프로필 삭제 후 재추가 안내 | 재시딩 없음, 프로필 보존, `cswap session login N` 안내 후 실패 |
| `_post_backup_write`·`_invalidate_session_credentials` | 무효화·stale 표식 | 건드리지 않음 |
| 백업 갱신 gate의 프로필 우선 (`switcher.py:2174`) | 프로필 토큰을 백업으로 | 건너뜀 |
| `_session_profile_ahead`·`_adopt_session_credential` | 흡수 | 없음/거짓 |
| `_perform_switch` 거부·경고 (`:6738`) | 거부 또는 경고 | 둘 다 없음 |
| 사용량 조회 프로필 우선 (`:4808`) | 프로필 토큰 읽기·흡수 | 백업 경로 사용 |
| 자동 전환 `skip-live-session` (`autoswitch.py:782`) | 건너뜀 | 건너뛰지 않음 |
| `run` fast path (`session.py:582`) | 기본 로그인으로 실행 | 항상 세션 프로필로 실행 |

`run`이 항상 세션 프로필을 쓰는 이유: 기본 로그인으로 뜬 Worker는 나중에 기본 로그인이
다른 계정으로 바뀌면 실행 중에 계정이 바뀐다. 독립 로그인이 있으면 두 번째 복사본 걱정이
없으므로 fast path가 필요 없다. 같은 이유로 `--require-session`은 이 경우 거부하지 않는다.

### 4.2 만료·무효 처리 (fail-closed)

결정: 독립 로그인 프로필이 검증에서 `invalid`이면(로그아웃, 다른 계정, 지원하지 않는 인증 방식)
백업으로 재시딩하지 않는다. `SessionError`로 "Account-N 세션 로그인이 유효하지 않음 —
`cswap session login N`" 안내를 내고 프로필·표식은 그대로 둔다. 검증 `unknown`은 지금처럼
로컬 자료로 판단한다. 복사 방식으로 조용히 돌아가면 이번에 없앤 충돌이 다시 생기기 때문이다.

### 4.3 CLI

- `cswap session login <NUM|EMAIL>`
  1. 계정을 해석하고 API key·setup-token 계정은 거부한다.
  2. 그 프로필에 live 세션이 있거나 기록을 읽을 수 없으면 거부한다(기존 `_ensure_no_live_session` 규칙).
  3. 기존 프로필 자격이 백업보다 앞선 세대면 먼저 백업으로 흡수한다(`_adopt_session_credential`).
     흡수 없이 지우면 백업에는 이미 소비된 세대만 남아, 다음 전환에서 `invalid_grant`가 난다.
     그다음 기존 자격(키체인 항목, `.credentials.json`)과 표식을 지운다. 프로필 디렉터리가
     없으면 만들고 `.claude.json` 신원·온보딩 값을 심는다(공유 링크는 다음 `run`이 맞춘다).
  4. 인증 override 환경변수를 지우고 `CLAUDE_CONFIG_DIR=<프로필>`로
     `claude auth login --claudeai --email <email>`을 대화형으로 실행한다.
  5. `claude auth status --json`이 그 계정(email, org)으로 `valid`일 때만 표식을 원자적으로 쓴다.
     다른 계정이면 방금 받은 자격을 지우고 실패한다.
- `cswap session logout <NUM|EMAIL>`: live 세션이면 거부한다. 아니면 프로필에서
  `claude auth logout`을 실행하고 자격과 표식을 지운다. 다음 `run`은 기존 복사 방식으로 재시딩한다.
- `cswap list`는 독립 로그인 계정에 표시를 붙인다. `list --json` 행에는 추가 필드
  `"sessionLogin": "own"`을 표식이 있을 때만 넣는다.
- `cswap switch --json`은 독립 로그인 계정에 대해 live 세션 경고를 넣지 않는다.

### 4.4 배포

결정: fork에 `repo-ops/config.toml`(`base = "main"`, `[deploy]`만 선언)과
`repo-ops/script/deploy`를 둔다. 스크립트는 dotfiles 계약의 인터페이스를 따른다
(`REPO_OPS_*` 환경변수, `.worktrees/.repo-ops-deploy.lock` 자체 잠금, 시작·끝 HEAD 일치,
tracked-clean). 그 checkout에서 `uv tool install --force --reinstall <repo_root>`로 비편집 설치하고,
설치된 `cswap session --help` 성공과 설치 출처가 그 checkout 경로임을 읽어 확인한다.
`[verify]`는 선언하지 않는다. 첫 설치는 이 선언이 없는 이전 base 때문에 자동으로 돌지
않으므로, 착지 뒤 같은 스크립트를 수동 rollout으로 한 번 실행한다. `AGENTS.md`의
설치본 문단을 이 배포 경로로 고친다.

### 4.5 기존 Worker와 전환 순서

배포 뒤 계정별로 Worker가 없을 때 `cswap session login 3`·`4`를 실행한다. 표식 전에
떠 있던 Worker는 복사 계열을 계속 쓰므로, 그 Worker가 끝나기 전에는 기존 경고가 그대로 뜬다.

## 5. 테스트 범위

기존 fake(autouse 가짜 Keychain, real-store guard, `claude` subprocess fake) 위에서:

1. 표식 프로필: stale 표식·백업 변경·지문 불일치·선갱신 경로에서 재시딩·무효화되지 않는다 — `tests/test_session.py`, `tests/test_switcher.py`
2. 표식 프로필 + 검증 `invalid`: 프로필·키체인 항목·표식이 보존되고 재로그인 안내 `SessionError` — `tests/test_session.py`
3. 백업 갱신 gate·`_session_profile_ahead`·`_adopt_session_credential`가 표식 프로필 토큰을 백업에 쓰지 않는다 — `tests/test_switcher.py`
4. `_perform_switch`: 표식 프로필이 live여도 거부·경고 없이 전환된다. 표식 없는 기존 거부·경고는 유지된다 — `tests/test_switcher.py`
5. 자동 전환 freshen이 표식 계정을 `skip-live-session`으로 건너뛰지 않는다 — `tests/test_autoswitch.py`
6. 사용량 조회가 표식 계정에서 백업 경로를 쓴다 — `tests/test_switcher.py`
7. `run`: 표식 계정이 기본 로그인과 같아도 세션 프로필로 실행하고, `--require-session`이 거부하지 않는다 — `tests/test_session.py`
8. `session login`: 앞선 세대 프로필 자격을 지우기 전에 백업으로 흡수, 성공 시 표식 기록, 다른 계정 로그인 시 표식 없음·자격 삭제·실패, live 세션·API key 계정 거부 — `tests/test_session.py`, `tests/test_cli.py`
9. `session logout`: 자격·표식 삭제, live 세션 거부 — 같은 파일
10. `list --json`: 표식이 있을 때만 `sessionLogin: "own"` — `tests/test_json_output.py`
11. 배포 스크립트: 환경변수 누락, cwd 불일치, HEAD 불일치, dirty tree에서 실패한다(`uv`를 shim으로 대체) — `tests/test_repo_ops_deploy.py`(신규)

전체: `uv run pytest` 통과(기준 2310 passed, 4 skipped). `python3 <dotfiles>/scripts/repo_ops_check.py --repo .` 통과.

## 6. 수용 기준

- A1: 5절 테스트와 전체 `uv run pytest`가 통과한다.
- A2: 표식이 없는 계정의 동작(복사 시딩, 동기화, 경고·거부)이 기존 테스트 그대로 통과한다.
- L1 (실측, 사용자 승인): 배포 뒤 설치된 `cswap`에 `session login`이 있고, 설치 출처가 fork다.
- L2 (실측, 사용자 브라우저 로그인): `cswap session login 3`, `4` 뒤 `list --json`에 `sessionLogin: "own"`이 있고,
  기본 로그인이 여전히 유효하다(`claude auth status`와 실제 요청 1회). 세션 프로필과 백업의
  자격 지문이 다르다(지문만 비교, 토큰은 출력하지 않음).
- L3: 독립 로그인 Worker가 실행 중인 계정으로 `cswap switch`해도 경고·거부가 없고, 그 Worker가 계속 응답한다.

## 7. 결정 (ADR 후보)

- 세션 프로필의 독립 로그인 계열은 프로필만 소유하고 cswap은 그것을 백업·기본 로그인과 동기화하지 않으며, 무효면 재시딩 없이 재로그인을 요구한다. 되돌리기 어려움: `session.py`의 시딩·검증 경로, `switcher.py`의 갱신 gate·흡수·전환·사용량 경로, `autoswitch.py`, 사용자 프로필의 표식 파일, beads-ui `account-switch.js`의 확인 기준이 함께 움직여야 한다. 맥락 없이 놀라움: upstream은 계정 하나에 계열 하나를 유지하려고 양방향 동기화를 일부러 넣었으므로, upstream merge 때 이 예외를 모르면 되돌리게 된다. 실재한 대안: setup-token(회전 없음, 추론 전용 scope), `CLAUDE_SECURESTORAGE_CONFIG_DIR` 공유(갱신 잠금이 폴더별이라 동시 갱신 충돌 잔존), 경고 유지를 기각했다. 새 주제: 인접 ADR 없음.
  `summary`: "독립 로그인 표식이 있는 세션 프로필의 토큰 계열은 프로필만 소유하고 cswap은 백업·기본 로그인과 동기화하지 않으며, 무효면 재시딩 없이 재로그인을 요구한다"
  → ADR
- fork 설치를 repo-ops `[deploy]`로 한다 — 설정 파일 하나로 되돌릴 수 있음(첫 조건 실패) → ADR 아님
- `list --json` 추가 필드 이름 `sessionLogin` — 필드 이름(기본 제외 목록) → ADR 아님

## 8. 경계·후속

| 종류(형제\|발견) | 저장소/rig | admission 클래스 | 분할 근거 | 선행(blocked_by) | Bead ID |
|---|---|---|---|---|---|
| 형제 | beads-ui / UI | user_request | different_repository + prerequisite_order — `account_in_use` 판정에서 `sessionLogin: "own"` 계정을 제외하고 행 정규화가 그 필드를 전달한다(route quick_fix) | claude-swap-q2v | UI-b8cm |
| 형제 | claude-swap / claude-swap | user_request | next_owner_requires_prior_acceptance_and_handoff — L2 뒤 며칠 동안 Worker 인증 실패·전환 경고 부재를 관찰하고 닫는다(route quick_fix, defer) | claude-swap-q2v | claude-swap-89w |

- 관찰: Codex도 같은 구조다(`~/.codex/auth.json` 복사본, Worker 홈은 계정 파일 링크) — 사용자가 이번 범위에서 뺐다.
- 관찰: 계정 없이(`claude_account` 빈 값) 뜨는 Worker는 기본 로그인을 따라 계정이 바뀐다 — 이 설계와 무관하고 현재 요청 범위 밖이다.
