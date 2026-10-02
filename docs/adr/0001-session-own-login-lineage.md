---
id: 1
title: 세션 프로필 독립 로그인 계열의 소유
status: accepted
date: 2026-10-02
summary: "독립 로그인 표식이 있는 세션 프로필의 토큰 계열은 프로필만 소유하고 cswap은 백업·기본 로그인과 동기화하지 않으며, 무효·미완료면 재시딩 없이 재로그인을 요구한다"
spec: docs/superpowers/specs/2026-10-02-session-own-login-lineage-design.md
bead: claude-swap-q2v
---

# 세션 프로필 독립 로그인 계열의 소유

## Context

beads-ui Worker는 `cswap run <계정>`으로 계정별 세션 프로필(`CLAUDE_CONFIG_DIR`)에서 Claude Code를
실행한다. upstream cswap은 계정 백업 토큰을 세션 프로필에 복사해 심고, 프로필과 백업 사이를 양방향으로
동기화해 "계정 하나 = 토큰 계열 하나"를 유지한다. 그래서 Worker가 쓰는 계정을 기본 로그인으로 전환하면
회전하는 refresh 토큰 계열 하나가 기본 로그인과 세션 프로필에 동시에 살아 있게 되고, 먼저 갱신한 쪽만
살아남는다. `cswap switch`는 경고하거나 거부했고, beads-ui는 전환 전 확인 창을 띄웠다.

같은 계정이라도 OAuth 로그인을 따로 하면 서로 무관한 토큰 계열(grant)이 생긴다. 세션 프로필이 자기
계열을 갖고 cswap이 그 계열을 다른 저장소와 섞지 않으면 충돌 원인 자체가 사라진다.

## Decision

- 세션 프로필 안의 독립 로그인 표식(`.cswap-own-login.json`, 상태 `pending` 또는 `own`)이 있으면 그
  프로필의 토큰 계열은 프로필만 소유한다. 판정은 `session.own_login_state` 한 곳에서 하고, 읽을 수 없는
  표식은 `pending`으로 본다.
- cswap은 표식 프로필의 계열을 백업이나 기본 로그인으로 복사하지 않고, 백업 계열로 그 프로필을 덮어쓰거나
  지우지도 않는다. 시딩·선갱신·재시딩, 백업 무효화, 갱신 gate의 프로필 우선, 흡수, 사용량 조회의 프로필
  우선, 표식 프로필 환경에서의 활성 조회 resync가 모두 이 프로필을 건너뛴다. 전환 경고·거부와 자동 전환의
  live 세션 건너뛰기도 표식 계정에는 적용하지 않는다.
- 무효(`own`인데 검증 `invalid`)나 미완료(`pending`)면 백업으로 재시딩하지 않고 `cswap session login N`
  재로그인(또는 `cswap session logout N`)을 요구한다. 복사 방식으로 조용히 돌아가면 없앤 충돌이 다시 생긴다.
- 표식은 `cswap session login`만 쓰고, `cswap session logout`과 계정 삭제만 지운다. 로그인은 표식을
  `pending`으로 먼저 기록한 뒤 인증하고, 검증된 뒤에만 `own`으로 바꾼다. 같은 계정의 login·logout은 서로
  직렬화된다.
- 표식 프로필에서는 `CLAUDE_SECURESTORAGE_CONFIG_DIR`를 값과 무관하게 지워 프로필 자기 저장소만 쓰게
  하고, `own` 계정의 `run`은 기본 로그인과 같은 계정이어도 세션 프로필로 실행한다.
- 키체인 항목 이름이 프로필 경로의 해시라 독립 자격을 옮길 수 없으므로, 표식 계정의 번호 이동·교환은
  아무것도 바꾸기 전에 거부한다.
- `list --json` 행은 표식이 있을 때만 `sessionLogin`(`own`/`pending`)을 덧붙인다. beads-ui는 이 필드로
  `account_in_use` 판정을 고친다.

기각한 대안:
- `claude setup-token` + `CLAUDE_CODE_OAUTH_TOKEN`: 회전은 없지만 추론 전용 scope라 사용량 조회 등
  계정 기능이 빠진다.
- `CLAUDE_SECURESTORAGE_CONFIG_DIR`로 저장소 공유: 갱신 잠금이 설정 폴더별이라 동시 갱신 충돌이 남는다.
- 경고 유지: 충돌 원인을 그대로 두고 사람에게 판단을 넘긴다.

## Consequences

- upstream은 계정 하나에 계열 하나를 유지하려고 양방향 동기화를 일부러 넣었다. upstream merge에서 세션
  프로필·백업 동기화 경로를 받을 때 이 예외(표식 프로필 건너뛰기)를 유지해야 한다. 되돌리려면
  `session.py`의 시딩·검증·실행 환경·login/logout 경로, `switcher.py`의 갱신 gate·흡수·전환·사용량·활성
  조회·이동·교환 경로, `autoswitch.py`, 사용자 프로필의 표식 파일, beads-ui `account-switch.js`의 확인
  기준이 함께 움직여야 한다.
- 독립 로그인에는 계정마다 사용자 브라우저 인증이 한 번 필요하다. 표식 없는 계정은 기존 복사 방식 그대로다.
- 표식 전에 세션 프로필에서 떠 있던 Worker는 복사 계열을 계속 쓰므로, 그 Worker가 끝날 때까지는 그 계정
  전환에 기존 경고가 남는다.
- 표식 계정의 번호 이동·교환을 지원하려면 독립 자격 이전을 따로 구현해야 한다.
