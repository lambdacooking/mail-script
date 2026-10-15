# mail-script

네이버 메일함을 주기적으로 확인하고, 새 메일이 오면 LLM(Grok)이 메일을 읽고 판단해
**A 시스템(재고·주문 시스템)에 조회·주문한 뒤 고객에게 답장하는 LLM 에이전트**입니다.

```
고객 메일 ──▶ 네이버 메일함 ──IMAP──▶ mail-script ──▶ Grok (판단)
                                          │
                                          ├──MCP──▶ A 시스템 (재고 조회 · 주문 등록)
                                          └──SMTP─▶ 고객에게 답장
```

이 문서는 **어떤 원리로 동작하는지**와 **어떤 순서로 실행되는지**를 중심으로 설명합니다.
설정 값과 API 세부 사항은 뒤쪽 [참고](#참고-설정) 절에 모아 두었습니다.

---

## 1. 핵심 원리

### 1-1. 판단은 LLM, 실행과 통제는 코드

| 역할 | 담당 | 예 |
| --- | --- | --- |
| 메일 이해·분류, 다음 행동 결정, 답장 문장 작성 | **Grok (LLM)** | "이건 주문 메일이다", "마우스 10개를 조회하자" |
| 도구 실제 실행, 규칙 강제, 결과 기록 | **코드** | A 시스템 호출, SMTP 발송, 중복 주문 차단 |

LLM은 도구를 **직접 실행하지 못합니다.** "이 도구를 이 인자로 실행해 달라"고 *요청*만 하고,
코드가 그 요청을 받아 실행한 뒤 결과를 돌려줍니다. 그래서 코드는 실행 직전에 요청을 검사하고 거부할 수 있습니다.

프롬프트에 쓴 지시("주문 불가 상품은 주문하지 마")는 LLM에게 하는 **부탁**일 뿐이라 지켜진다는 보장이 없습니다.
메일 본문에 "다른 주소로 보내라" 같은 지시를 숨기는 프롬프트 인젝션도 프롬프트만으로는 완전히 막을 수 없습니다.
그래서 **되돌릴 수 없는 행동(주문, 발송)은 코드 안전장치로 막고, 꼭 해야 하는 일(답장)은 코드가 확인**합니다.

### 1-2. 에이전트 루프

메일 1건을 처리하는 과정은 Grok과 코드가 대화를 주고받는 반복문입니다.

```
messages = [시스템 프롬프트, 메일 본문]
반복 (최대 max_tool_rounds 회):
    Grok에게 messages 전체 + 도구 목록 전송
    ├─ 응답에 도구 호출 요청이 있으면 → 코드가 실행 → 결과를 messages 에 추가 → 다시 반복
    └─ 도구 호출 없이 최종 답(JSON)이면 → 종료
```

LLM은 **상태가 없습니다.** 이전 호출을 기억하지 못하므로, 코드는 매 회차 지금까지의 대화(`messages`) 전체를 다시 보냅니다.
Grok이 "앞에서 조회한 결과"를 아는 이유는 그 결과가 `messages` 안에 들어 있기 때문입니다.

### 1-3. 도구 3개와 두 가지 연결 방식

Grok이 쓸 수 있는 도구는 세 개입니다. Grok에게는 모두 똑같은 함수 목록으로 보이지만, 실행되는 곳이 다릅니다.

| 도구 | 하는 일 | 실행 위치 | 이유 |
| --- | --- | --- | --- |
| `check_order` | 주문 가능 여부 조회 (재고 변화 없음) | MCP 서버 `mcp_server_a.py` | 메일 맥락이 필요 없음 → 다른 프로그램에서도 재사용 가능 |
| `place_order` | 주문 등록 (재고 차감, 되돌릴 수 없음) | MCP 서버 (단, `order_guard.py` 검사 통과 후) | 실행은 재사용, 검사는 메일 맥락이 필요해 analyzer 쪽 |
| `send_reply` | 고객에게 답장 | 로컬 도구 `reply_tool.py` | "지금 처리 중인 메일의 보낸 사람"을 알아야 검증 가능 |

MCP(Model Context Protocol)는 LLM 애플리케이션이 외부 도구를 표준 방식으로 연결하는 규약입니다.
MCP 서버는 별도 프로세스라 **어떤 메일을 처리 중인지 모릅니다.** 그래서 메일에 묶인 검사(받는 사람 확인, 메일당 주문 횟수)는
메일 정보를 가진 `analyzer.py` 쪽에서 합니다.

### 1-4. dry_run

주문과 답장에는 각각 모드가 있습니다. `dry_run`은 **부작용(실제 주문, 실제 발송)만 가짜로 바꾸고 나머지는 전부 실제로 실행**합니다.
Grok 분석, A 시스템 조회, 안전장치 검사는 모두 그대로 돌기 때문에, 실제 운영 전에 에이전트의 판단을 안전하게 확인할 수 있습니다.

---

## 2. 구성 요소

실행하면 다음 프로세스들이 함께 동작합니다.

```
[터미널 1] system_a_server.py          ← A 시스템 (HTTP 서버, 계속 실행)
                ▲ HTTP
                │
[터미널 2] scheduler.py                 ← 10초마다 아래를 새 프로세스로 실행
              └─ check_mail.py          ← 1회 실행 후 종료
                   └─ analyzer.py       ← (모듈) 에이전트 루프
                        ├─ mcp_server_a.py   ← 자식 프로세스 (stdio로 MCP 통신)
                        ├─ order_guard.py    ← place_order 안전장치
                        ├─ reply_tool.py     ← send_reply 도구 + 안전장치
                        └─ threads.py        ← 대화(스레드) 기록
```

| 파일 | 역할 |
| --- | --- |
| `scheduler.py` | 일정 간격으로 `check_mail.py`를 별도 프로세스로 실행. 한 번 실행이 오래 걸리면 `--timeout`에서 강제 종료 |
| `check_mail.py` | IMAP으로 새 메일을 가져와 분석을 맡기고, 결과를 `mails/`에 저장한 뒤 기준점(`state.json`) 갱신 |
| `analyzer.py` | 에이전트 루프. MCP 서버를 띄우고 Grok과 도구 호출을 반복. 시스템 프롬프트, 완료 검사, 기본 답장 포함 |
| `mcp_server_a.py` | MCP 서버. `check_order`, `place_order`를 A 시스템 HTTP API로 전달. A 시스템이 꺼져 있으면 `system_unavailable: true` 반환 |
| `order_guard.py` | 메일 1건 단위로 `place_order`를 검사 (조회 후에만, 상품당 1회, 개수 상한, dry_run) |
| `reply_tool.py` | `send_reply` 도구. 받는 사람·횟수·길이 검사 후 SMTP 발송 (또는 dry_run 기록) |
| `threads.py` | 고객 회신을 이전 대화와 연결하고 대화별 답장 횟수를 기록 (`threads.json`) |
| `system_a_server.py` | 테스트용 A 시스템. 파이썬 기본 라이브러리만 사용 |
| `system_a_products.json` | A 시스템 상품 목록 (상품명, 판매가, 등록 재고) |
| `credentials.example.json` | 설정 파일 예시. 복사해서 `credentials.json`으로 사용 |

실행 중 자동으로 생기는 파일 (모두 git 제외):

| 파일 | 내용 |
| --- | --- |
| `credentials.json` | 모든 설정과 비밀번호, API 키 |
| `state.json` | 마지막으로 처리한 메일의 IMAP UID (기준점) |
| `mails/mails_<타임스탬프>.json` | 확인 주기마다 새 메일 + 분석 결과 |
| `threads.json` | 대화 기록과 대화별 답장 횟수 |
| `system_a_orders.json` | A 시스템에 등록된 주문 내역 |

---

## 3. 실행 순서

### 3-1. 처음 한 번 준비

1. **가상환경과 패키지 설치**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate          # 터미널을 새로 열 때마다
   pip install -r requirements.txt    # schedule, mcp
   ```

   Debian/Ubuntu에서 `externally-managed-environment` 오류가 나면 위처럼 가상환경을 쓰세요
   (`venv` 생성이 실패하면 `sudo apt install python3-venv`).

2. **네이버 메일에서 IMAP/SMTP 켜기**
   네이버 메일 → 환경설정 → POP3/IMAP 설정 → IMAP/SMTP 설정 → **사용함**.
   2단계 인증을 쓰면 내정보 → 보안설정 → 2단계 인증 → **애플리케이션 비밀번호**를 만들어 비밀번호 대신 씁니다.

3. **설정 파일 만들기**

   ```bash
   cp credentials.example.json credentials.json
   ```

   최소한 `username`, `password`, `grok.api_key`를 채웁니다.
   처음에는 `order.mode`, `reply.mode`를 기본값 `dry_run`으로 두세요. 자세한 항목은 [참고: 설정](#참고-설정).

### 3-2. 매번 실행

**터미널 1: A 시스템을 먼저 실행합니다.**

```bash
python system_a_server.py                  # http://127.0.0.1:8000
```

**터미널 2: 스케줄러를 실행합니다.**

```bash
python scheduler.py                        # 10초마다 확인
python scheduler.py --interval 30          # 간격 변경
python scheduler.py --timeout 900          # 1회 최대 실행 시간(초), 기본 600
```

- 스케줄러는 시작하자마자 한 번 확인하고, 그 뒤 간격마다 반복합니다. `Ctrl+C`로 종료합니다.
- **맨 처음 실행**에서는 `state.json`이 없으므로 메일을 처리하지 않고, 현재 마지막 메일의 UID만 기준점으로 기록합니다.
  그 **이후에 도착한** 메일부터 처리합니다. (기존 메일함의 메일에 답장이 나가지 않게 하기 위해서입니다.)
- 오래 떠 있는 프로세스(`system_a_server.py`, `scheduler.py`)는 코드를 고친 뒤 **재시작해야** 바뀐 코드가 적용됩니다.
  `check_mail.py`와 MCP 서버는 매 주기 새로 실행되므로 재시작이 필요 없습니다.
- cron·systemd처럼 가상환경을 활성화하지 않는 곳에서는 `.venv/bin/python scheduler.py`처럼 경로를 직접 지정합니다.

### 3-3. 권장 운영 순서

1. `order: dry_run`, `reply: dry_run` → `mails/*.json`에서 분류·조회·답장 문장이 괜찮은지 확인
2. `order: live`, `reply: dry_run` → A 시스템에 실제 주문이 들어가는지 확인
3. `order: live`, `reply: send` → 실제 운영

테스트 메일은 **다른 계정**에서 보내세요. 내 주소에서 온 메일은 분석하지 않습니다 (아래 4-1의 2단계).

---

## 4. 한 번의 확인 주기에서 일어나는 일

스케줄러가 `check_mail.py`를 실행할 때마다 아래 순서로 진행됩니다.

### 4-1. 메일 가져오기 (`check_mail.py`)

1. `credentials.json`, `state.json`을 읽고 IMAP에 로그인한 뒤, 메일함을 **읽기 전용**으로 엽니다.
2. `state.json`의 `last_uid`보다 UID가 큰 메일만 찾습니다. 없으면 "새 메일 없음"을 출력하고 끝납니다.
   - IMAP UID는 메일함 안에서 메일마다 붙는, 계속 커지는 번호입니다. 이 번호로 "어디까지 처리했는지"를 기억합니다.
   - 메일함의 `UIDVALIDITY`가 바뀌면(메일함 재구성 등) UID가 무효이므로 기준점을 다시 잡습니다.
3. 새 메일을 `BODY.PEEK`로 가져옵니다 (메일이 '읽음'으로 바뀌지 않음). 보낸 사람, 제목, 본문, `Message-ID`,
   `In-Reply-To`/`References`, 첨부파일 정보를 뽑습니다.
4. 보낸 사람이 **내 주소**(`username@naver.com`, `reply.from_address`)인 메일은 분석하지 않고 `skipped`로 표시합니다.
   내가 보낸 답장이 다시 들어와 "답장 → 분석 → 재주문"이 반복되는 것을 막습니다.
5. `grok.api_key`가 있으면 나머지 메일을 `analyzer.py`에 넘깁니다 (4-2). 없으면 분석 없이 저장만 합니다.
6. 메일과 분석 결과를 `mails/mails_<타임스탬프>.json`에 저장합니다.
7. **저장이 끝난 뒤에** `state.json`의 `last_uid`를 갱신합니다. 저장 전에 죽으면 다음 주기에 같은 메일을 다시 가져오므로 메일이 누락되지 않습니다.

### 4-2. 분석 준비 (`analyzer.py`)

1. `mcp_server_a.py`를 **자식 프로세스로 실행**하고, 표준 입출력(stdio)으로 MCP 연결을 맺습니다.
2. MCP 서버에 도구 목록을 물어 `check_order`, `place_order`의 이름·설명·인자 형식을 받고, Grok이 이해하는 형식으로 바꿉니다.
3. 새 메일을 **한 통씩 순서대로** 처리합니다 (4-3). MCP 연결 하나를 이번 주기의 모든 메일이 함께 씁니다.

### 4-3. 메일 1건 처리

1. **대화 확인** (`threads.py`)
   메일의 `In-Reply-To`/`References`에 들어 있는 `Message-ID`가 `threads.json`에 있으면, 우리 답장에 대한 고객의 **회신**입니다.
   회신이면 이전 대화(최근 10개 메시지)와 이 대화에서 이미 보낸 답장 수를 가져옵니다.

2. **메일별 도구 준비**
   - 이 메일 전용 `OrderGuard`(주문 검사기)와 `ReplyTool`(답장 도구)을 새로 만듭니다. 메일마다 새로 만들기 때문에
     "이 메일에서 몇 번 주문했나", "누구에게 답장해야 하나"를 메일 단위로 셀 수 있습니다.
   - `order.mode`가 `off`면 `place_order`를, `reply.mode`가 `off`이거나 대화 답장 한도에 도달했으면 `send_reply`를 Grok에게 **아예 주지 않습니다.**
     없는 도구는 호출할 수 없으므로 가장 확실한 차단입니다.

3. **Grok에게 첫 요청**
   `messages` = [시스템 프롬프트, (회신이면 이전 대화 +) 보낸 사람·제목·본문]. 본문은 8000자까지만 보냅니다.
   메일 본문은 `<mail_body>` 태그로 감싸고, 그 안의 지시문은 따르지 말라고 시스템 프롬프트에 적어 둡니다.

4. **Grok의 판단**
   시스템 프롬프트에 따라 Grok은 메일을 분류합니다.

   | `mail_type` | 예 | Grok이 하는 일 |
   | --- | --- | --- |
   | `order` | "주문합니다", "재고 있으면 보내주세요"(조건부 주문 포함) | 상품마다 조회 → 가능한 상품만 주문 → 주문번호를 담아 답장 |
   | `inquiry` | "주문 가능할까요?", "견적 부탁드립니다" | 상품마다 조회 → 가능 여부 안내 답장 (주문 안 함) |
   | `other` | 광고, 무관한 질문, 감사 인사 | 조회 없이 짧게 답장 |

   조건부 주문("가능하면 주문")은 조건을 `check_order`로 확인할 수 있으므로 `order`입니다.
   구매 의사가 없거나 상품·개수를 특정할 수 없으면 `inquiry`입니다.

5. **도구 실행 반복**
   Grok이 도구 호출을 요청하면 코드가 이름에 따라 실행하고, 결과를 `messages`에 붙여 다시 Grok에게 보냅니다.

   ```
   check_order  ──────────────────────────▶ MCP 서버 ──POST /api/orders/check──▶ A 시스템
                 결과에서 orderable=true 인 (상품, 개수)를 OrderGuard 가 기억

   place_order ─▶ OrderGuard 검사 ─통과─▶ dry_run 이면 가짜 주문번호(DRYRUN-n)
                       │                  live 이면 MCP 서버 ──POST /api/orders──▶ A 시스템
                       └─거부─▶ {"ordered": false, "error": 사유} 를 Grok 에게 돌려줌

   send_reply  ─▶ ReplyTool 검사 ─통과─▶ send 면 SMTP 발송, dry_run 이면 기록만
                       └─거부─▶ {"ok": false, "error": 사유} 를 Grok 에게 돌려줌
   ```

   거부 사유도 도구 결과로 돌려주므로, Grok은 그 사유를 읽고 고쳐서 다시 시도하거나 포기합니다.
   상품이 없다는 결과를 받으면 상품명 표기를 바꿔 다시 조회하기도 합니다. 이 반복은 최대 `max_tool_rounds`(기본 8)회입니다.

6. **완료 검사: 답장 보장**
   모든 메일에는 답장해야 합니다. 이를 코드가 두 단계로 확인합니다.
   1. **재요청**: Grok이 답장 없이 최종 답을 내면, 한 번 "아직 답장하지 않았다"는 메시지를 붙여 되돌려 보냅니다 → `tool_calls`에 `(reminder)`
   2. **기본 답장**: 그래도 답장하지 않거나, Grok API 오류·반복 한도 초과로 끝나면 코드가 정해진 문구로 직접 답장합니다 → `tool_calls`에 `(fallback)`

   기본 답장도 같은 `ReplyTool`을 거치므로 받는 사람·횟수·dry_run 규칙이 똑같이 적용됩니다.
   답장하지 않는 경우는 **내 주소에서 온 메일**과 **대화 답장 한도에 도달한 경우**뿐입니다.

7. **결과 정리**
   Grok의 최종 JSON(분류, 요약, 상품별 판단)에 코드가 다음을 덧붙여 `analysis`로 저장합니다.
   - `tool_calls`: 도구 호출 전체 기록
   - `orders`, `replies`: **도구가 실제로 실행한 기록**
   - `modes`: 실제 적용된 주문·답장 모드

   Grok의 자기 보고(`products[].order_id`, `replied`)는 틀릴 수 있으므로, 실제 주문·답장 여부는 `orders`/`replies`를 기준으로 봅니다.

8. **대화 기록**
   고객 메일과 보낸 답장을 `threads.json`의 해당 대화에 추가하고 답장 횟수를 늘립니다.
   우리 답장의 `Message-ID`도 기록해 두므로, 고객이 그 답장에 회신하면 다음 주기에 같은 대화로 연결됩니다.

---

## 5. 안전장치 정리

### `place_order` (`order_guard.py`)

| 규칙 | 막는 것 |
| --- | --- |
| 같은 상품명·개수로 `check_order`를 먼저 호출해 `orderable=true`를 받아야 함 | 조회 없는 주문, 주문 불가 상품 주문, 조회와 다른 개수로 주문 |
| 메일 1건당 같은 상품은 1번만 | 중복 주문 |
| 메일 1건당 최대 `max_orders_per_mail`개 상품 | 비정상적으로 많은 주문 |
| `mode: dry_run` | 검증 전 실제 주문 |

A 시스템도 주문 시점에 재고·가격을 다시 확인하므로, 조회와 주문 사이에 재고가 바뀌어도 초과 주문되지 않습니다.

### `send_reply` (`reply_tool.py`)

| 규칙 | 막는 것 |
| --- | --- |
| 받는 사람 = 원래 메일의 보낸 사람 | 본문 속 지시(프롬프트 인젝션)로 엉뚱한 곳에 발송 |
| 메일 1건당 `max_replies_per_mail`통 (기본 1) | 같은 메일에 반복 발송 |
| 대화 1개당 `max_replies_per_thread`통 (기본 10) | 고객과 자동 답장이 끝없이 오가는 것 |
| `allowed_senders` (설정 시) | 허용하지 않은 발신자에게 답장 |
| 본문 길이 `max_body_chars` | 비정상적으로 긴 본문 |
| `mode: dry_run` | 검증 전 실제 발송 |
| 주문이 dry_run이면 `send` 모드여도 발송 보류 | 가짜 주문번호(`DRYRUN-n`)가 고객에게 나가는 것 |

답장에는 `In-Reply-To`/`References` 헤더가 들어가 고객 메일함에서 원래 메일과 같은 대화로 묶입니다.

### 그 밖의 방어

- 내 주소에서 온 메일은 분석하지 않음 (자기 답장 루프 방지)
- A 시스템이 꺼져 있으면 MCP 서버가 오류 대신 `system_unavailable: true`를 돌려주고, Grok은 주문하지 않고 "확인 후 연락드리겠다"고 안내
- 설정의 `mode` 값이 잘못되면(오타 등) 경고를 출력하고 `dry_run`으로 동작. 실제 적용된 모드는 `analysis.modes`와 스케줄러 출력에서 확인
- 한 메일의 분석이 실패해도 다른 메일 처리와 저장은 계속 진행

---

## 6. 결과 확인

스케줄러 출력 예:

```
--- 2026-10-13 10:00:00 check_mail.py 실행
[분석] 적용된 모드: 주문=live, 답장=send
[대화] 새 대화, 이 대화의 답장 1/10회
[분석] 1건 중 1건 성공, 0건 실패
[새 메일] 1건 → mails/mails_20261013_100005_123456.json
```

저장 파일 구조 (주요 항목만):

```json
{
  "fetched_at": "2026-10-13T10:00:05.123456",
  "count": 1,
  "mails": [
    {
      "uid": 1234, "message_id": "<...>", "from": "buyer@example.com",
      "subject": "발주", "body_text": "무선마우스 10개 주문합니다 (개당 25,000원)",
      "thread_id": "<...>",
      "analysis": {
        "mail_type": "order",
        "summary": "무선 마우스 10개 주문",
        "products": [
          {"product_name": "무선마우스", "price": 25000, "quantity": 10,
           "orderable": true, "reason": "주문 가능합니다.", "order_id": "ORD-20261013-0001"}
        ],
        "tool_calls": [
          {"tool": "check_order", "arguments": {...}, "result": "..."},
          {"tool": "place_order", "arguments": {...}, "result": "..."},
          {"tool": "send_reply",  "arguments": {...}, "result": "..."}
        ],
        "modes":   {"order": "live", "reply": "send"},
        "orders":  [{"ordered": true, "order_id": "ORD-20261013-0001", "total_price": 250000, ...}],
        "replies": [{"mode": "send", "status": "sent", "to": "buyer@example.com", "body": "...", ...}],
        "thread":  {"id": "<...>", "is_followup": false, "replies_sent_total": 1, "replies_limit": 10}
      }
    }
  ]
}
```

- 분석에 실패하면 `analysis`에 `error`가 들어가고, Grok 답이 JSON이 아니면 `raw_answer`에 원문이 남습니다.
- 내 주소에서 온 메일은 `analysis: {"skipped": "..."}`입니다.
- 기대와 다르게 동작하면 `modes` → `tool_calls` → `orders`/`replies` 순서로 확인하세요.

초기화 방법 (스케줄러와 A 시스템을 끈 상태에서):

| 되돌릴 것 | 지울 파일 |
| --- | --- |
| 기준점 (다음 실행 때 "지금"으로 다시 잡음) | `state.json` |
| 대화 기록과 답장 횟수 | `threads.json` |
| A 시스템 재고 (처음 상태로) | `system_a_orders.json` |

---

## 7. 알려진 한계

- **중복 주문·답장 가능성**: 주문·답장 후 `--timeout`으로 중단되면 기준점이 갱신되지 않아, 다음 주기에 같은 메일을 다시 처리합니다.
  `live`/`send` 모드에서는 `--timeout`을 넉넉히 두세요.
- **A 시스템이 꺼져 있을 때 온 메일**은 "확인 후 연락드리겠다"는 답장만 보내고 처리가 끝납니다. 나중에 다시 처리하지 않습니다.
- **분석이 실패한 메일**도 기준점은 갱신되므로 다시 분석하지 않습니다.
- `order.mode`(`off`/`dry_run`/`live`)와 `reply.mode`(`off`/`dry_run`/`send`)는 **실제 동작 값의 이름이 다릅니다.**

---

## 참고: 설정

모든 설정은 `credentials.json` 한 파일에 있습니다. 다른 위치의 파일을 쓰려면 환경 변수 `MAIL_CREDENTIALS_FILE`에 경로를 지정합니다.
메일 저장 위치는 `MAIL_OUTPUT_DIR`로 바꿀 수 있습니다.

### 메일 (최상위)

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `username` | 네이버 아이디 (`@naver.com` 제외) | (필수) |
| `password` | 비밀번호. 2단계 인증 사용 시 애플리케이션 비밀번호. SMTP 발송에도 사용 | (필수) |
| `imap_server` / `imap_port` | IMAP 서버 (SSL) | `imap.naver.com` / `993` |
| `mailbox` | 확인할 메일함 | `INBOX` |

### `grok`

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `api_key` | xAI 콘솔(https://console.x.ai)의 API 키. 없으면 분석하지 않고 메일만 저장 | (없음) |
| `model` | 모델 ID. 도구 호출(function calling)을 지원해야 함 | `grok-4` |
| `base_url` | API 주소 (OpenAI 호환 `/chat/completions`) | `https://api.x.ai/v1` |
| `timeout` | Grok API 1회 호출 제한 시간(초) | `60` |
| `max_tool_rounds` | 메일 1건당 Grok ↔ 도구 최대 반복 횟수 | `8` |

### `order`

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `mode` | `off`: `place_order`를 주지 않음 · `dry_run`: 가상 주문 · `live`: 실제 주문 | `dry_run` |
| `max_orders_per_mail` | 메일 1건당 주문할 수 있는 최대 상품 수 | `5` |

### `reply`

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `mode` | `off`: `send_reply`를 주지 않음 · `dry_run`: 기록만 · `send`: 실제 발송 | `dry_run` |
| `smtp_server` / `smtp_port` | SMTP 서버 (SSL) | `smtp.naver.com` / `465` |
| `from_address` | 보내는 주소. 비우면 `username@naver.com` | `""` |
| `allowed_senders` | 이 주소들에게만 답장. 비우면 모두 허용 | `[]` |
| `max_body_chars` | 답장 본문 최대 길이 | `5000` |
| `max_replies_per_mail` | 메일 1건당 답장 수 | `1` |
| `max_replies_per_thread` | 대화 1개당 답장 수. dry_run 답장도 포함 | `10` |

### `system_a`

`mcp_server_a.py`가 A 시스템에 보내는 요청 설정입니다. 기본 주소로 A 시스템을 실행했다면 비워 둬도 됩니다.

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `base_url` | A 시스템 주소 | `http://127.0.0.1:8000` |
| `check_path` | 조회 API 경로 | `/api/orders/check` |
| `order_path` | 주문 API 경로 | `/api/orders` |
| `headers` | 추가 헤더 (예: `{"Authorization": "Bearer ..."}`) | `{}` |
| `timeout` | 요청 제한 시간(초) | `10` |

## 참고: A 시스템 API (`system_a_server.py`)

```bash
python system_a_server.py --host 0.0.0.0 --port 9000   # 주소 변경
```

| API | 설명 |
| --- | --- |
| `POST /api/orders/check` | 주문 가능 여부 조회 (재고 변화 없음) |
| `POST /api/orders` | 같은 기준으로 다시 확인한 뒤 주문 등록 (주문번호 발급) |
| `GET /api/products` | 상품 목록과 남은 재고 |
| `GET /api/orders` | 등록된 주문 목록 |

요청 본문 (두 POST 공통):

```json
{"product_name": "무선 마우스", "price": 25000, "quantity": 10}
```

- `product_name`(필수): 띄어쓰기·대소문자를 무시하고 비교
- `quantity`(필수): 1 이상의 정수
- `price`(선택): 요청 단가. 생략하면 가격은 검사하지 않음

판단 기준: 등록되지 않은 상품, 재고 < 요청 개수, 요청 단가 < 판매가 중 하나라도 해당하면 주문 불가입니다.
응답은 조회가 `{"orderable", "reason", "requested", "product"}`, 주문이 `{"ordered", "reason", "order_id", "total_price", "remaining_stock", ...}`이며,
요청 형식이 틀리면 `400`과 `{"error": "..."}`를 돌려줍니다.

**재고 계산**: 남은 재고 = `system_a_products.json`의 `stock` − `system_a_orders.json`의 주문 수량 합계.
상품 파일은 바뀌지 않고, 요청마다 다시 읽으므로 상품을 고쳐도 서버를 재시작할 필요가 없습니다.

직접 테스트:

```bash
curl -X POST http://127.0.0.1:8000/api/orders/check \
     -H "Content-Type: application/json" \
     -d '{"product_name": "무선 마우스", "price": 25000, "quantity": 10}'
```
