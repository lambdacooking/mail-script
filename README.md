# mail-script

10초마다 네이버 메일(IMAP)의 새 메일을 확인해 로컬에 JSON 파일로 저장하는 스크립트.
새 메일이 있으면 Grok AI가 메일을 **주문확정 / 문의 / 기타**로 분류하고, 상품명·가격·개수를 유추해 MCP를 통해 A 시스템에 주문 가능 여부를 조회합니다.
주문확정 메일이면 A 시스템에 주문을 등록하고, 주문번호를 담아 보낸 사람에게 답장합니다.
주문과 답장 모두 기본값은 실제로 실행하지 않는 `dry_run`입니다.

| 파일 | 역할 |
| --- | --- |
| `check_mail.py` | 새 메일을 한 번 확인하고, 있으면 분석 후 `mails/mails_YYYYMMDD_HHMMSS_ffffff.json`으로 저장 |
| `scheduler.py` | `check_mail.py`를 10초마다 실행 |
| `analyzer.py` | Grok API 호출 + MCP 클라이언트. 에이전트 루프 (메일 분석, 도구 실행) |
| `mcp_server_a.py` | A 시스템 MCP 서버: `check_order`(조회), `place_order`(주문 등록) (`analyzer.py`가 자동 실행) |
| `order_guard.py` | `place_order` 호출 안전장치 (조회 후에만 주문, 중복 주문 방지, dry_run) |
| `reply_tool.py` | Grok이 호출하는 답장 발송 도구 `send_reply` (SMTP, 안전장치 포함) |
| `threads.py` | 같은 고객과의 대화(스레드) 기록·답장 횟수 추적 (`threads.json`, 자동 생성, git 제외) |
| `system_a_server.py` | A 시스템 웹 서버 (주문 가능 여부 조회·주문 등록 API, 별도 실행) |
| `system_a_products.json` | A 시스템 상품 목록 (상품명, 판매가, 등록 재고) |
| `system_a_orders.json` | A 시스템 주문 내역 (서버가 자동 생성, git 제외) |
| `credentials.example.json` | 접속 정보 파일 예시 |

## 설정

1. 가상환경 만들고 패키지 설치

   최신 Debian/Ubuntu 등에서는 시스템 파이썬에 `pip install`을 하면
   `error: externally-managed-environment` 오류가 납니다. 프로젝트 폴더에 가상환경을 만들어 설치하세요.

   ```bash
   sudo apt install python3-venv     # venv 생성이 실패할 때만 (또는 python3-full)
   python3 -m venv .venv             # 가상환경 생성 (최초 1회)
   source .venv/bin/activate         # 가상환경 활성화 (터미널을 새로 열 때마다)
   pip install -r requirements.txt
   ```

   활성화하면 프롬프트 앞에 `(.venv)`가 표시됩니다. 이후 `python` 명령은 모두 활성화된 상태에서 실행합니다.
   Windows에서는 `.venv\Scripts\activate`로 활성화합니다.

2. 네이버 메일 IMAP 켜기
   - 네이버 메일 → **환경설정 → POP3/IMAP 설정 → IMAP/SMTP 설정** 에서 **IMAP 사용함** 선택 후 저장

3. 접속 정보 파일 만들기

   ```bash
   cp credentials.example.json credentials.json
   ```

   `credentials.json`의 값을 채웁니다.

   | 키 | 설명 | 기본값 |
   | --- | --- | --- |
   | `username` | 네이버 아이디 (`@naver.com` 제외) | (필수) |
   | `password` | 네이버 비밀번호. **2단계 인증 사용 시 애플리케이션 비밀번호** | (필수) |
   | `imap_server` | IMAP 서버 | `imap.naver.com` |
   | `imap_port` | IMAP 포트 (SSL) | `993` |
   | `mailbox` | 확인할 메일함 | `INBOX` (받은메일함) |

   애플리케이션 비밀번호는 네이버 **내정보 → 보안설정 → 2단계 인증 → 애플리케이션 비밀번호 관리**에서 만들 수 있습니다.
   다른 위치의 파일을 쓰려면 환경 변수 `MAIL_CREDENTIALS_FILE`에 경로를 지정하세요.

   메일 분석·주문·답장을 쓰려면 `grok`, `system_a`, `order`, `reply` 항목도 채웁니다 ([메일 분석, 주문, 답장](#메일-분석-주문-답장-에이전트-루프) 참고).
   `grok.api_key`가 없으면 분석 없이 메일만 저장합니다.

4. 최초 실행

   ```bash
   python check_mail.py
   ```

   현재 시점의 마지막 메일이 기준점으로 `state.json`에 기록됩니다.
   이 시점 **이후** 들어온 메일만 "새 메일"로 저장됩니다.

## 실행

```bash
python scheduler.py               # 10초마다
python scheduler.py --interval 30 # 간격 변경
python scheduler.py --timeout 900 # check_mail.py 1회 최대 실행 시간(초), 기본 600
```

Grok 분석은 메일 1건당 수 초~수십 초가 걸릴 수 있습니다. 한 번에 새 메일이 많이 들어오면
`--timeout`을 늘리세요. 시간이 초과되면 기준점이 갱신되지 않으므로 다음 실행 때 같은 메일을 다시 처리합니다.

가상환경을 활성화하지 않고 실행하려면(cron, systemd 등) 가상환경의 파이썬 경로를 직접 지정하세요.

```bash
/path/to/mail-script/.venv/bin/python /path/to/mail-script/scheduler.py
```

저장 위치를 바꾸려면 환경 변수 `MAIL_OUTPUT_DIR`를 지정하세요.

## 저장 형식

```json
{
  "fetched_at": "2026-10-12T10:00:00.123456",
  "count": 1,
  "mails": [
    {
      "uid": 1234, "message_id": "<...>",
      "from": "...", "to": "...", "cc": null,
      "subject": "...", "date": "Mon, 12 Oct 2026 09:59:58 +0900",
      "date_iso": "2026-10-12T09:59:58+09:00",
      "body_text": "...", "body_html": "...",
      "attachments": [{"filename": "...", "mimeType": "...", "size": 1234}],
      "analysis": {
        "mail_type": "order",
        "summary": "무선 마우스 10개 주문 확정",
        "products": [
          {
            "name_in_mail": "무선마우스 10개 (개당 25,000원)",
            "product_name": "무선마우스",
            "price": 25000,
            "quantity": 10,
            "orderable": true,
            "reason": "주문 가능합니다.",
            "system_product": {"name": "무선 마우스", "price": 25000, "stock": 50, "total_price": 250000},
            "order_id": "ORD-20261013-0001",
            "note": ""
          }
        ],
        "replied": true,
        "reply_skipped_reason": null,
        "tool_calls": [
          {"tool": "check_order", "arguments": {"product_name": "무선마우스", "price": 25000, "quantity": 10},
           "result": "{\"orderable\": true, ...}"},
          {"tool": "place_order", "arguments": {"product_name": "무선마우스", "price": 25000, "quantity": 10},
           "result": "{\"ordered\": true, \"order_id\": \"ORD-20261013-0001\", ...}"},
          {"tool": "send_reply", "arguments": {"to": "buyer@example.com", "body": "안녕하세요. ..."},
           "result": "{\"ok\": true, \"status\": \"sent\", ...}"}
        ],
        "orders": [
          {"arguments": {"product_name": "무선마우스", "price": 25000, "quantity": 10},
           "ordered": true, "order_id": "ORD-20261013-0001", "product_name": "무선 마우스",
           "unit_price": 25000, "quantity": 10, "total_price": 250000, "remaining_stock": 40}
        ],
        "replies": [
          {
            "mode": "send", "status": "sent",
            "to": "buyer@example.com", "subject": "Re: 발주", "body": "안녕하세요. ...",
            "message_id": "<...@naver.com>", "at": "2026-10-13T10:00:05.123456"
          }
        ]
      }
    }
  ]
}
```

새 메일이 없으면 파일을 만들지 않습니다.

`analysis`는 Grok 설정이 있을 때만 생깁니다. 분석이 실패하면 `{"error": "..."}`가 들어가고 메일은 그대로 저장됩니다.
Grok 답변이 JSON이 아니면 `{"raw_answer": "..."}`로 원문을 남깁니다.

`modes`는 실제로 적용된 주문·답장 모드입니다 (예: `{"order": "live", "reply": "send"}`). 기대와 다르게 동작하면 먼저 이 값을 확인하세요.
`credentials.json`의 `mode` 값이 허용되지 않는 값(오타 등)이면 스케줄러 출력에 경고가 나오고 `dry_run`으로 동작합니다.
`order.mode`는 `off`/`dry_run`/`live`, `reply.mode`는 `off`/`dry_run`/`send`로 **값이 서로 다르니** 주의하세요.

내 메일 주소(`username@naver.com`, `reply.from_address`)에서 온 메일은 분석하지 않고 `{"skipped": "..."}`로 저장합니다.
자기 자신에게 테스트 메일을 보내거나 답장이 받은메일함으로 돌아와도, 답장 → 재분석 → 재주문이 반복되지 않게 하기 위해서입니다.
테스트 주문 메일은 **다른 계정에서** 보내세요.

`orders`와 `replies`는 도구가 실제로 실행된 기록입니다 (`orders`: 주문 시도 결과 목록, `replies`: 보낸 답장 목록, 답장하지 않았으면 `[]`).
`products[].order_id`, `replied`는 Grok의 자기 보고이므로, 실제 주문·답장 여부는 `orders`/`replies`를 기준으로 보세요.

## 메일 분석, 주문, 답장 (에이전트 루프)

```
check_mail.py ── 새 메일 ──▶ analyzer.py ──(1) 본문 + 도구 목록──▶ Grok API
                                │  ▲                                  │
                                │  └──── (2) 도구 호출 요청 / (4) 최종 JSON ┘
                                │
                (3) 도구 이름에 따라 실행하고 결과를 Grok에 돌려줌
                    ├─ check_order ──────────────MCP─▶ mcp_server_a.py ──POST /api/orders/check──▶ system_a_server.py
                    ├─ place_order ─▶ order_guard ─MCP─▶ mcp_server_a.py ──POST /api/orders────────▶ system_a_server.py
                    └─ send_reply  ─────────────────▶ reply_tool.py (로컬) ──SMTP──▶ 보낸 사람
```

1. 메일마다 본문(`body_text`, 없으면 HTML에서 추출)과 도구 목록을 Grok에 보냅니다.
2. Grok이 메일을 분류합니다 (`mail_type`).

   | 분류 | 예 | Grok의 행동 |
   | --- | --- | --- |
   | `order` (주문) | "주문합니다", "발주드립니다", "가능하면 바로 주문할게요", "재고 있으면 보내주세요" | 조회 → 조건을 만족하는 상품만 **주문 등록** → 주문번호를 담아 답장 |
   | `inquiry` (문의) | "주문 가능할까요?", "견적 부탁드립니다", "재고 있나요?" | 조회 → 가능 여부 안내 답장 (주문은 하지 않음) |
   | `other` (기타) | 광고, 알림, 무관한 메일 | 아무것도 하지 않음 |

   "가능하면 주문" 같은 조건부 주문은 조건을 `check_order`로 확인할 수 있으므로 `order`로 봅니다.
   구매 의사 없이 묻기만 하거나, 상품·개수를 특정할 수 없으면 `inquiry`입니다.
3. `analyzer.py`가 도구 이름을 보고 MCP 서버(`check_order`, `place_order`) 또는 로컬 도구(`send_reply`)로 실행하고,
   결과를 Grok에 돌려줍니다. Grok은 결과를 보고 다음 행동을 정합니다.
   - 상품이 없으면 상품명 표기를 바꿔 다시 조회
   - 주문확정이면 `orderable=true`인 상품만 `place_order`로 주문
   - 끝나면 `send_reply(to, subject, body)`로 답장
   - 도구가 거부되면 사유를 보고 고쳐서 다시 시도하거나 포기

   이 반복은 메일 1건당 최대 `max_tool_rounds`회입니다.
4. Grok이 더 이상 도구를 호출하지 않고 최종 결과를 JSON으로 답하면 메일의 `analysis`에 저장합니다.
   단, `mail_type`이 `order`/`inquiry`인데 답장 없이 끝내려 하면 **한 번** "아직 답장하지 않았다"고 되돌려 보냅니다
   (지시문만으로는 LLM이 답장을 건너뛸 수 있어서 코드로 확인). 그래도 답장하지 않으면 그 판단과 `reply_skipped_reason`을 그대로 기록합니다.
   재요청이 있었으면 `tool_calls`에 `(reminder)` 항목이 남습니다.

### `place_order` 안전장치 (`order_guard.py`)

`place_order`는 MCP 서버의 도구지만, MCP 서버는 어떤 메일을 처리 중인지 모릅니다.
그래서 `analyzer.py`가 호출을 MCP 서버로 넘기기 전에 메일마다 새로 만든 `OrderGuard`를 거치게 합니다
(도구 호출 앞뒤에 끼는 정책 계층). 위반하면 `{"ordered": false, "error": "사유"}`를 Grok에 돌려줍니다.

| 규칙 | 막는 것 |
| --- | --- |
| 같은 상품명·개수로 `check_order`를 먼저 호출해 `orderable=true`를 받아야 함 | 조회 없이 바로 주문, 주문 불가 상품 주문, 조회와 다른 개수로 주문 |
| 메일 1건당 같은 상품은 1번만 | 중복 주문 |
| 메일 1건당 최대 `max_orders_per_mail`개 상품 | 비정상적으로 많은 주문 |
| `mode: dry_run` (기본값) | 검증 전 실제 주문 (가상 주문번호 `DRYRUN-n`만 발급) |

A 시스템 서버도 주문 시점에 재고·가격을 다시 확인하므로, 조회와 주문 사이에 재고가 바뀌어도 초과 주문되지 않습니다.

주문이 `dry_run`이면 답장에 가짜 주문번호가 들어가므로, `reply.mode`가 `send`여도 그 메일의 답장은 보내지 않고 기록만 합니다.

### `order` 설정

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `mode` | `off`: `place_order`를 Grok에 주지 않음 (문의 답장만) · `dry_run`: 가상 주문 · `live`: A 시스템에 실제 주문 | `dry_run` |
| `max_orders_per_mail` | 메일 1건당 주문할 수 있는 최대 상품 수 | `5` |

권장 순서: `order`·`reply` 모두 `dry_run`으로 `mails/*.json`의 `analysis`를 확인 → `order: live`, `reply: dry_run`으로 주문 확인 → 둘 다 실제 모드.

### 왜 `send_reply`는 MCP가 아니라 로컬 도구인가

받는 사람을 검증하려면 "지금 어떤 메일을 처리 중인지"를 알아야 합니다.
MCP 서버는 별도 프로세스라 그 맥락을 모르므로, 메일마다 `ReplyTool` 객체를 새로 만들어 그 메일에 묶어 둡니다.
Grok 입장에서는 MCP 도구와 로컬 도구가 똑같은 함수 목록으로 보입니다.

### `send_reply` 안전장치

Grok이 도구 인자를 어떻게 넣든 아래 규칙은 코드가 강제하고, 위반하면 `{"ok": false, "error": "사유"}`를 Grok에 돌려줍니다.

| 규칙 | 막는 것 |
| --- | --- |
| 받는 사람 = 원래 메일의 보낸 사람 | 메일 본문 속 "xxx로 보내라" 같은 지시(프롬프트 인젝션)로 엉뚱한 곳에 발송 |
| 메일 1건당 답장 `max_replies_per_mail`통까지 (기본 1통) | 같은 사람에게 반복 발송 |
| `allowed_senders` (설정 시) | 허용하지 않은 발신자에게 답장 |
| 본문 길이 제한 | 비정상적으로 긴 본문 |
| `mode: dry_run` (기본값) | 검증 전 실제 발송 |

답장은 `In-Reply-To`/`References` 헤더를 넣어 원래 메일과 같은 대화로 묶입니다.

### `reply` 설정

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `mode` | `off`: 도구를 Grok에 주지 않음 · `dry_run`: 답장 내용만 기록하고 보내지 않음 · `send`: 실제 발송 | `dry_run` |
| `smtp_server` / `smtp_port` | SMTP 서버 (SSL) | `smtp.naver.com` / `465` |
| `from_address` | 보내는 주소. 비우면 `username@naver.com` | `""` |
| `allowed_senders` | 이 주소들에게만 답장 허용. 비우면 모두 허용 | `[]` |
| `max_body_chars` | 답장 본문 최대 길이 | `5000` |
| `max_replies_per_mail` | 메일 1건당 보낼 수 있는 답장 수 (1 이상). Grok에게 주는 도구 설명에도 이 횟수가 표시됨 | `1` |
| `max_replies_per_thread` | 같은 고객과의 한 대화에서 보낼 수 있는 답장 수 (1 이상). 아래 "대화(스레드)" 참고 | `10` |

### 대화(스레드)와 답장 한도

고객이 우리 답장에 **회신**하면, 그 메일의 `In-Reply-To`/`References` 헤더에 우리 답장의 `Message-ID`가 들어 있습니다.
`threads.py`는 고객 메일과 우리 답장의 `Message-ID`를 대화 ID에 연결해 `threads.json`에 기록해 두고, 이걸로 회신이 어느 대화에 속하는지 찾습니다.

- 같은 대화에서 답장은 `max_replies_per_thread`번(기본 10번)까지 나갑니다. 한도에 도달하면 그 뒤 회신에는
  Grok에게 `send_reply` 도구를 주지 않고, 분석·저장만 합니다 (주문은 `order` 설정대로 처리됨).
- 회신 메일을 분석할 때는 이전 대화(최근 10개 메시지: 고객 메일과 우리 답장)를 Grok에게 함께 넘깁니다.
  그래서 "그럼 그걸로 주문할게요" 같은 회신도 앞서 안내한 상품·개수로 이어서 처리합니다.
- 답장이 아니라 **새로 쓴 메일**은 같은 고객이어도 새 대화로 시작합니다.
- `dry_run` 답장도 횟수에 포함됩니다 (기록상 보낸 것으로 취급).
- 메일 JSON에는 `thread_id`와 `analysis.thread`(`is_followup`, `replies_sent_total`, `replies_limit`)가 남고,
  스케줄러 출력에 `[대화] 기존 대화의 회신, 이 대화의 답장 3/10회`처럼 표시됩니다.
- 대화 기록을 초기화하려면 스케줄러를 끄고 `threads.json`을 지우세요.

SMTP 로그인에는 IMAP과 같은 `username`/`password`를 사용합니다. 네이버 메일 환경설정의 **IMAP/SMTP 설정**에서 SMTP도 사용으로 되어 있어야 합니다.
처음에는 `dry_run`으로 `mails/*.json`의 `replies[].body`를 확인하고, 답장 품질이 괜찮으면 `send`로 바꾸세요.

### `grok` 설정

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `api_key` | xAI 콘솔(https://console.x.ai)에서 발급한 API 키 | (필수) |
| `model` | 사용할 모델 ID. 도구 호출(function calling)을 지원하는 모델이어야 함 | `grok-4` |
| `base_url` | API 주소 (OpenAI 호환 Chat Completions) | `https://api.x.ai/v1` |
| `timeout` | Grok API 1회 호출 제한 시간(초) | `60` |
| `max_tool_rounds` | 메일 1건당 Grok ↔ 도구 호출 최대 반복 횟수 | `8` |

모델 이름은 xAI 콘솔의 모델 목록에서 현재 제공되는 ID를 확인해 넣으세요.

### A 시스템 서버 (`system_a_server.py`)

파이썬 기본 라이브러리만으로 동작하는 간단한 웹 서버입니다. 스케줄러와 **별도 터미널에서 먼저 실행**해 두세요.

```bash
python system_a_server.py                          # http://127.0.0.1:8000
python system_a_server.py --host 0.0.0.0 --port 9000
```

| API | 설명 |
| --- | --- |
| `POST /api/orders/check` | 주문 가능 여부 조회 (재고 변화 없음) |
| `POST /api/orders` | 주문 등록 (재고 차감, 주문번호 발급) |
| `GET /api/products` | 상품 목록과 남은 재고 |
| `GET /api/orders` | 등록된 주문 목록 |

**`POST /api/orders/check`**

요청:

```json
{"product_name": "무선 마우스", "price": 25000, "quantity": 10}
```

| 필드 | 설명 |
| --- | --- |
| `product_name` | 상품명 (필수). 띄어쓰기·대소문자는 무시하고 비교 |
| `quantity` | 주문 개수, 1 이상의 정수 (필수) |
| `price` | 요청 단가(원). 생략하면 가격은 검사하지 않음 |

응답 (`200`):

```json
{
  "orderable": false,
  "reason": "재고 부족 (재고 5개, 요청 6개)",
  "requested": {"product_name": "27인치 모니터", "price": 320000, "quantity": 6},
  "product": {"name": "27인치 모니터", "price": 320000, "stock": 5, "total_price": 1920000}
}
```

판단 기준:

- 등록되지 않은 상품 → 주문 불가 (`product`는 `null`)
- 재고 < 요청 개수 → 주문 불가
- 요청 단가 < 판매가 → 주문 불가
- 모두 통과하면 `"orderable": true`, `"reason": "주문 가능합니다."`

요청 형식이 틀리면 `400`과 `{"error": "..."}`를 돌려줍니다.

**`POST /api/orders`**

요청은 `/api/orders/check`와 같습니다. 같은 기준으로 다시 확인한 뒤, 주문 가능하면 등록합니다.

```json
{
  "ordered": true,
  "reason": "주문이 등록되었습니다.",
  "order_id": "ORD-20261013-0001",
  "product_name": "무선 마우스",
  "unit_price": 25000,
  "quantity": 10,
  "total_price": 250000,
  "ordered_at": "2026-10-13T10:00:03",
  "remaining_stock": 40
}
```

주문 불가면 `"ordered": false`와 `reason`(재고 부족 등)을 돌려줍니다.

**상품과 재고**

상품은 `system_a_products.json`에서 관리합니다. 요청마다 파일을 다시 읽으므로 수정 후 서버를 재시작할 필요가 없습니다.

```json
[
  {"name": "무선 마우스", "price": 25000, "stock": 50}
]
```

주문 내역은 `system_a_orders.json`에 쌓이고, **남은 재고 = 등록 재고(`stock`) − 주문된 수량 합계**로 계산합니다
(상품 파일 자체는 바뀌지 않음). 재고를 처음 상태로 되돌리려면 서버를 끄고 `system_a_orders.json`을 지우세요.

직접 테스트:

```bash
curl -X POST http://127.0.0.1:8000/api/orders/check \
     -H "Content-Type: application/json" \
     -d '{"product_name": "무선 마우스", "price": 25000, "quantity": 10}'
```

### `system_a` 설정

`mcp_server_a.py`가 A 시스템 서버에 보내는 요청을 정합니다. 위 서버를 기본 주소로 실행했다면 비워 둬도 됩니다.

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `base_url` | A 시스템 서버 주소 | `http://127.0.0.1:8000` |
| `check_path` | 주문 가능 여부 API 경로 | `/api/orders/check` |
| `order_path` | 주문 등록 API 경로 | `/api/orders` |
| `headers` | 인증 등 추가 헤더 (예: `{"Authorization": "Bearer ..."}`) | `{}` |
| `timeout` | 요청 제한 시간(초) | `10` |

## 동작 방식

- IMAP UID로 마지막으로 확인한 메일 이후의 메일만 가져오므로 중복 저장이 없습니다.
- 메일함을 읽기 전용으로 열고 `BODY.PEEK`로 가져오므로 메일이 '읽음'으로 바뀌지 않습니다.
- 메일함의 `UIDVALIDITY`가 바뀌면 기준점을 현재로 재설정합니다.
- Grok 분석이 실패해도 메일은 저장되고 기준점도 갱신됩니다 (분석 실패 메일은 다시 분석하지 않음).
- 메일 본문은 Grok에 분석 대상 데이터로만 전달하며, 본문 속 지시문은 따르지 않도록 지시합니다.
  다만 프롬프트 지시만으로는 완전히 막을 수 없으므로, 외부에 영향을 주는 `place_order`와 `send_reply`는 코드 안전장치로 한 번 더 막습니다.
- Grok이 쓸 수 있는 도구는 **조회**(`check_order`), **주문 등록**(`place_order`), **답장**(`send_reply`)입니다.
- 주문·답장 후 처리가 중단되면(시간 초과 등) 기준점이 갱신되지 않아, 다음 실행 때 같은 메일을 다시 처리하면서
  **중복 주문·중복 답장**이 생길 수 있습니다. `live`/`send` 모드에서는 `--timeout`을 넉넉히 두세요.
- `credentials.json`(메일 비밀번호, Grok API 키, A 시스템 토큰 포함), `state.json`, `mails/`, `system_a_orders.json`, `threads.json`은 `.gitignore`에 포함되어 있습니다.
