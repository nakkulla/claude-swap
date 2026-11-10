---
scope:
  - src/claude_swap/cli.py
  - src/claude_swap/switcher.py
  - src/claude_swap/session.py
  - src/claude_swap/json_output.py
  - tests/
---

# 화면에서 쓸 격리 로그인 `cswap login`과 확인 없는 `cswap remove --yes --json` (claude-swap-3uj)

## 1. 배경

beads-ui UI-xm29는 사용량 카드의 버튼으로 Claude 계정을 재로그인·추가·삭제한다(beads-ui `docs/superpowers/specs/2026-11-10-account-login-add-remove-buttons-design.md` §4.3). 화면 로그인은 활성 로그인을 바꾸면 안 된다 — 실행 중 세션과 Worker가 다른 계정으로 바뀌기 때문이다. 지금 명령으로는 그렇게 할 수 없다. beads-ui는 이 명령을 tmux 창에 띄워 인증 URL을 읽고, 사용자가 붙여 넣은 코드를 넣고, 마지막 JSON 줄로 결과를 읽는다.

## 2. 검증된 전제

- `add_account`는 신원을 `CLAUDE_CONFIG_DIR` 프로필에서 읽고, 자격은 `CLAUDE_SECURESTORAGE_CONFIG_DIR`가 정의돼 있으면(빈 값이면 기본 저장소) 그쪽에서, 아니면 `CLAUDE_CONFIG_DIR`에서 읽는다 — src/claude_swap/switcher.py:661-723
- 같은 신원이 있으면 그 슬롯을 갱신하고 만료 표시를 지우지만, 새 슬롯이든 갱신이든 `activeAccountNumber`를 그 슬롯으로 쓴다 — src/claude_swap/switcher.py:3553-3617, switcher.py:3763
- `add_account`의 슬롯·`sequence.json` 갱신은 `FileLock`으로 감싸여 있지 않다 — src/claude_swap/switcher.py:3519-3771
- 전환 계열은 `FileLock(self.lock_file)`과 `claude_credentials_lock()`·`claude_config_lock()`을 함께 잡는다 — src/claude_swap/switcher.py:6856
- 활성 자격의 저수준 쓰기는 `_write_credentials`이고, 활성화 경로가 이를 부른다. 일반 `_perform_switch`는 쓰기 전에 지금 활성 자격을 그 슬롯에 먼저 백업한다 — src/claude_swap/switcher.py:740-741, switcher.py:6971-6975, switcher.py:7098-7237
- `session login`이 새로 받은 독립 로그인 자격은 슬롯 백업에 저장하지 않는다. 단, 표식 없는 세션 프로필이 백업보다 앞서 있으면 로그인 전에 그 자격을 백업에 흡수한다 — src/claude_swap/session.py:987-1112, session.py:1036-1046
- `_probe_env`는 표식 없는 프로필에서 `CLAUDE_SECURESTORAGE_CONFIG_DIR`를 지우지 않는다 — src/claude_swap/session.py:591-594
- `session login`이 `claude auth login --claudeai --email <email>`을 프로필 환경으로 실행하고, 로그인 뒤 신원 불일치·새 로그인 없음을 검사하는 선례가 있다 — src/claude_swap/session.py:1056-1104
- 사용자 지정 설정 폴더의 키체인 서비스 이름 규칙과 항목 삭제 함수가 있다 — src/claude_swap/session.py:292-304, session.py:315
- `remove_account`는 `assume_yes`가 거짓이면 표준 입력으로 `y`를 묻고, CLI는 거짓으로 부른다 — src/claude_swap/switcher.py:3981-4065, cli.py:1483
- `_refuse_session_shell`은 `CLAUDE_CONFIG_DIR`이 세션 프로필 폴더 아래일 때만 거부한다 — src/claude_swap/switcher.py:6725-6750
- `--json` 출력은 `json_output`의 schema-v1 모양을 CLI가 한 번 `json.dumps`한다 — src/claude_swap/json_output.py:1-14
- `claude auth login`은 TTY에서 URL과 `Paste code here if prompted >`를 보인다 — 실행: 임시 `CLAUDE_CONFIG_DIR` tmux 캡처 (Claude Code 2.1.322, 2026-11-10)

## 3. 목표와 비목표

목표

1. `cswap login <num|email> --json`: 그 슬롯의 로그인을 활성 로그인과 활성 기록을 건드리지 않고 새로 받는다.
2. `cswap login --new --json`: 새 계정을 같은 방식으로 넣는다. 이미 있는 신원이면 그 슬롯을 갱신한다.
3. `cswap remove <num|email> --yes --json`: 확인 없이 지우고 결과를 JSON으로 낸다.

비목표

- 세션 프로필 독립 로그인(ADR 0001)은 바꾸지 않는다. 임시 프로필은 세션 프로필이 아니고 독립 로그인 표식도 만들지 않는다.
- 기존 `add`·`remove`(인자 없는 대화형)·`session login`의 동작은 그대로다.

## 4. 설계

### 4.1 `cswap login`

1. 대상 결정: `<num|email>`이면 슬롯을 찾고(없으면 `account_not_found`), API 키·setup-token 슬롯이면 `session login`과 같은 이유로 거부한다(`unsupported_account`). `--new`면 대상 없음.
2. 임시 프로필: cswap 백업 폴더 아래 `login-<임의값>` 폴더(0700)를 만든다. 세션 프로필 폴더(`sessions/`) 밖이어서 `_refuse_session_shell`에 걸리지 않는다.
3. 그 프로필 환경(인증 덮어쓰기 환경변수 제거, `CLAUDE_SECURESTORAGE_CONFIG_DIR`는 빈 값이어도 무조건 제거, `CLAUDE_CONFIG_DIR`=임시 프로필)으로 — 남아 있으면 로그인이 활성 저장소에 쓰거나 캡처가 활성 자격을 읽는다 — `claude auth login --claudeai`를 실행한다. 대상이 있으면 `--email <슬롯 이메일>`을 붙인다. 표준 입출력은 그대로 이어서 tmux 창에서 사람이 코드를 넣을 수 있게 한다.
4. 로그인 뒤 임시 프로필에서 신원(이메일·조직)과 자격을 읽는다. 대상이 있는데 신원이 다르면 아무것도 저장하지 않고 `identity_mismatch`. 자격이 없거나 로그인이 0이 아닌 값으로 끝나면 `login_incomplete`.
5. 저장: 인증 대기(3)는 잠금 밖에서 하고, 저장은 전환과 같은 `FileLock(self.lock_file)` 안에서 한다. 잠금 안에서 목록·대상 슬롯의 신원·지금 활성 계정을 다시 읽고, 그 사이 대상 슬롯이 사라졌거나 신원이 바뀌었으면 저장하지 않고 `account_not_found`/`identity_mismatch`. 통과하면 `add_account`의 검증(외부 자격·API 키 거부)을 거쳐 슬롯 자격·설정을 쓰고 만료 표시를 지운다. 신원이 목록에 있으면 `updated`, 없으면 새 슬롯에 `added`.
6. 결정: `activeAccountNumber`도 활성 로그인도 바꾸지 않는다 — beads-ui가 실행 중 세션을 보호하려고 이 명령을 쓴다. 단, 잠금 안에서 다시 읽은 활성 계정이 대상 슬롯이면 `claude_credentials_lock()`을 더 잡고 저수준 `_write_credentials`로 활성 로그인에도 새 자격을 쓴다(만료된 활성 로그인이 바로 풀리게). 결정: `_perform_switch`는 쓰지 않는다 — 지금 활성 자격(만료된 옛 자격)을 슬롯에 먼저 백업해 방금 저장한 새 자격을 덮는다.
7. 정리: 성공·실패·취소 모두 임시 프로필 폴더와 그 프로필의 키체인 항목(`keychain_service_name(<임시 프로필>)`)을 지운다. 중단은 SIGINT(KeyboardInterrupt)·SIGTERM·SIGHUP 모두 같은 정리로 이어진다 — beads-ui는 시간 초과·취소 때 tmux 창을 닫아(SIGHUP) 끝낸다. `claude auth logout`은 부르지 않는다 — 토큰 계열이 폐기되어 방금 저장한 자격까지 죽는다.
8. 뒷정리: 명령을 시작할 때 백업 폴더 아래 15분보다 오래된 `login-*` 임시 프로필과 그 키체인 항목을 먼저 지운다(서버 재시작·강제 종료로 7을 못 한 경우).
9. 출력: 사람이 보는 진행 문장은 그대로 찍고, `--json`이면 마지막 줄에 JSON 한 줄을 낸다.
   - 성공 `{ "schemaVersion": 1, "ok": true, "outcome": "updated"|"added", "number": N, "email": "..." }`
   - 실패 `{ "schemaVersion": 1, "ok": false, "error": "identity_mismatch"|"login_incomplete"|"account_not_found"|"unsupported_account", "message": "..." }`, 종료 코드 0이 아닌 값.

### 4.2 `cswap remove --yes --json`

- `--yes`는 `remove_account(..., assume_yes=True)`로 확인을 건너뛴다. 이메일이 여러 슬롯에 맞으면 대화형 선택 대신 `ambiguous_account`로 실패한다.
- `--json`은 성공 `{ "schemaVersion": 1, "ok": true, "removed": { "number": N, "email": "..." } }`, 실패 `{ "schemaVersion": 1, "ok": false, "error": "<code>", "message": "..." }`를 낸다.
- 활성 계정 삭제는 지금처럼 경고만 하고 진행한다. 막는 판단은 소비자(beads-ui)가 한다.

### 4.3 오류 처리

- `claude` 없음: `login_incomplete`와 안내 문장.
- 임시 프로필 정리 실패: 결과는 그대로 내고 `message`에 남은 경로를 덧붙인다(토큰 값은 쓰지 않는다).
- 로그에는 코드·토큰을 쓰지 않는다.

## 5. 테스트

모든 테스트는 가짜 Keychain과 real-store guard 위에서 돈다.

- `login <num>`: 같은 신원이면 슬롯 갱신·만료 표시 해제·`activeAccountNumber` 불변, 다른 신원이면 저장 없음과 `identity_mismatch`, 대상이 활성이면 활성 로그인도 갱신.
- `login --new`: 새 신원 `added`, 기존 신원 `updated`.
- 잠금: 인증 대기 중에는 `FileLock`을 잡지 않고, 저장 단계가 동시 전환과 겹쳐도 슬롯·`sequence.json`·활성 자격이 한쪽으로만 정해진다. 활성 슬롯 재로그인 뒤 슬롯 자격이 옛 자격으로 덮이지 않는다.
- 환경: `CLAUDE_SECURESTORAGE_CONFIG_DIR`가 지정값·빈 값일 때 모두 활성 저장소가 바뀌지 않고, 캡처가 임시 프로필 자격을 읽는다.
- 정리: 성공·실패·SIGINT·SIGTERM·SIGHUP 중단 모두 임시 폴더와 그 키체인 항목이 사라지고 `claude auth logout`은 불리지 않음. 시작 때 15분보다 오래된 `login-*` 프로필만 지워지고 새것은 남음.
- `remove --yes --json`: 표준 입력 없이 삭제, 모호한 이메일 `ambiguous_account`, JSON 모양.
- JSON: 마지막 줄 하나만 JSON이고 `schemaVersion: 1`.

## 6. 경계·후속

- 소비자 beads-ui UI-xm29가 이 Bead를 `blocks`로 기다린다. 화면·서버 쪽은 그 Bead가 한다.

## 결정 (ADR 후보)

- 전제: ADR 0001 — 임시 로그인 프로필은 세션 프로필이 아니고 독립 로그인 표식을 만들지 않으며, 세션 프로필 동기화 경로는 건드리지 않는다.
- `cswap login`은 활성 기록·활성 로그인을 바꾸지 않는 격리 로그인이다 — 새 명령을 더할 뿐 기존 경로를 바꾸지 않아 되돌리기 쉽고, 결정 기록은 소비자 쪽 beads-ui UI-xm29 ADR이 갖는다 → ADR 아님
- `remove --yes --json` — 기존 동작에 비대화형 옵션을 더할 뿐이라 되돌리기 쉽다 → ADR 아님
