# mail-script

10초마다 네이버 메일(IMAP)의 새 메일을 확인해 로컬에 JSON 파일로 저장하는 스크립트.
새 메일이 있으면 Grok AI로 본문을 분석해 상품명·가격·개수를 유추하고, MCP를 통해 A 시스템에 주문 가능 여부를 조회한 뒤,
Grok이 직접 `send_reply` 도구를 호출해 보낸 사람에게 답장합니다 (기본값은 실제로 보내지 않는 `dry_run`).

| 파일 | 역할 |
| --- | --- |
| `check_mail.py` | 새 메일을 한 번 확인하고, 있으면 분석 후 `mails/mails_YYYYMMDD_HHMMSS_ffffff.json`으로 저장 |
| `scheduler.py` | `check_mail.py`를 10초마다 실행 |
| `analyzer.py` | Grok API 호출 + MCP 클라이언트. 메일 본문 분석 및 A 시스템 조회 |
| `mcp_server_a.py` | A 시스템 주문 가능 여부 조회 MCP 서버 (`analyzer.py`가 자동 실행) |
| `reply_tool.py` | Grok이 호출하는 답장 발송 도구 `send_reply` (SMTP, 안전장치 포함) |
| `system_a_server.py` | A 시스템 웹 서버 (주문 가능 여부 API, 별도 실행) |
| `system_a_products.json` | A 시스템 상품 목록 (상품명, 판매가, 재고) |
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

   메일 분석·상품 조회를 쓰려면 `grok`, `system_a` 항목도 채웁니다 ([메일 분석 및 A 시스템 조회](#메일-분석-및-a-시스템-조회) 참고).
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
        "summary": "무선 마우스 10개 주문 문의",
        "products": [
          {
            "name_in_mail": "무선마우스 10개 (개당 25,000원)",
            "product_name": "무선마우스",
            "price": 25000,
            "quantity": 10,
            "orderable": true,
            "reason": "주문 가능합니다.",
            "system_product": {"name": "무선 마우스", "price": 25000, "stock": 50, "total_price": 250000},
            "note": ""
          }
        ],
        "replied": true,
        "reply_skipped_reason": null,
        "tool_calls": [
          {"tool": "check_order", "arguments": {"product_name": "무선마우스", "price": 25000, "quantity": 10},
           "result": "{\"orderable\": true, ...}"},
          {"tool": "send_reply", "arguments": {"to": "buyer@example.com", "body": "안녕하세요. ..."},
           "result": "{\"ok\": true, \"status\": \"sent\", ...}"}
        ],
        "reply": {
          "mode": "send", "status": "sent",
          "to": "buyer@example.com", "subject": "Re: 주문 문의", "body": "안녕하세요. ...",
          "message_id": "<...@naver.com>", "at": "2026-10-13T10:00:05.123456"
        }
      }
    }
  ]
}
```

새 메일이 없으면 파일을 만들지 않습니다.

`analysis`는 Grok 설정이 있을 때만 생깁니다. 분석이 실패하면 `{"error": "..."}`가 들어가고 메일은 그대로 저장됩니다.
Grok 답변이 JSON이 아니면 `{"raw_answer": "..."}`로 원문을 남깁니다.

`reply`는 `send_reply` 도구가 실제로 성공했을 때의 기록입니다 (답장하지 않았으면 `null`).
`replied`는 Grok의 자기 보고이므로, 실제 답장 여부는 `reply`를 기준으로 보세요.

## 메일 분석, A 시스템 조회, 답장 (에이전트 루프)

```
check_mail.py ── 새 메일 ──▶ analyzer.py ──(1) 본문 + 도구 목록──▶ Grok API
                                │  ▲                                  │
                                │  └──── (2) 도구 호출 요청 / (4) 최종 JSON ┘
                                │
                (3) 도구 이름에 따라 실행하고 결과를 Grok에 돌려줌
                    ├─ check_order ─MCP─▶ mcp_server_a.py ──POST──▶ system_a_server.py
                    └─ send_reply  ─────▶ reply_tool.py (로컬) ──SMTP──▶ 보낸 사람
```

1. 메일마다 본문(`body_text`, 없으면 HTML에서 추출)과 도구 목록을 Grok에 보냅니다.
2. Grok이 문맥에서 상품명·단가·개수를 뽑아 `check_order(product_name, quantity, price)` 호출을 요청합니다.
   단가가 메일에 없으면 `price`는 생략하고, 개수가 없으면 1로 봅니다.
3. `analyzer.py`가 도구 이름을 보고 MCP 서버(`check_order`) 또는 로컬 도구(`send_reply`)로 실행합니다.
   결과를 Grok에 돌려주면 Grok은 다음 행동을 정합니다.
   - 상품이 없으면 상품명 표기를 바꿔 다시 조회
   - 조회가 끝나면 결과를 정리해 `send_reply(to, subject, body)`로 답장
   - 답장이 거부되면 사유를 보고 고쳐서 다시 시도하거나 포기

   이 반복은 메일 1건당 최대 `max_tool_rounds`회입니다.
4. Grok이 더 이상 도구를 호출하지 않고 최종 결과를 JSON으로 답하면 메일의 `analysis`에 저장합니다.

### 왜 `send_reply`는 MCP가 아니라 로컬 도구인가

받는 사람을 검증하려면 "지금 어떤 메일을 처리 중인지"를 알아야 합니다.
MCP 서버는 별도 프로세스라 그 맥락을 모르므로, 메일마다 `ReplyTool` 객체를 새로 만들어 그 메일에 묶어 둡니다.
Grok 입장에서는 MCP 도구와 로컬 도구가 똑같은 함수 목록으로 보입니다.

### `send_reply` 안전장치

Grok이 도구 인자를 어떻게 넣든 아래 규칙은 코드가 강제하고, 위반하면 `{"ok": false, "error": "사유"}`를 Grok에 돌려줍니다.

| 규칙 | 막는 것 |
| --- | --- |
| 받는 사람 = 원래 메일의 보낸 사람 | 메일 본문 속 "xxx로 보내라" 같은 지시(프롬프트 인젝션)로 엉뚱한 곳에 발송 |
| 메일 1건당 답장 1통 | 같은 사람에게 중복 발송 |
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

SMTP 로그인에는 IMAP과 같은 `username`/`password`를 사용합니다. 네이버 메일 환경설정의 **IMAP/SMTP 설정**에서 SMTP도 사용으로 되어 있어야 합니다.
처음에는 `dry_run`으로 `mails/*.json`의 `reply.body`를 확인하고, 답장 품질이 괜찮으면 `send`로 바꾸세요.

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
등록된 상품 목록은 `GET /api/products`로 볼 수 있습니다.

상품은 `system_a_products.json`에서 관리합니다. 요청마다 파일을 다시 읽으므로 수정 후 서버를 재시작할 필요가 없습니다.

```json
[
  {"name": "무선 마우스", "price": 25000, "stock": 50}
]
```

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
| `headers` | 인증 등 추가 헤더 (예: `{"Authorization": "Bearer ..."}`) | `{}` |
| `timeout` | 요청 제한 시간(초) | `10` |

## 동작 방식

- IMAP UID로 마지막으로 확인한 메일 이후의 메일만 가져오므로 중복 저장이 없습니다.
- 메일함을 읽기 전용으로 열고 `BODY.PEEK`로 가져오므로 메일이 '읽음'으로 바뀌지 않습니다.
- 메일함의 `UIDVALIDITY`가 바뀌면 기준점을 현재로 재설정합니다.
- Grok 분석이 실패해도 메일은 저장되고 기준점도 갱신됩니다 (분석 실패 메일은 다시 분석하지 않음).
- 메일 본문은 Grok에 분석 대상 데이터로만 전달하며, 본문 속 지시문은 따르지 않도록 지시합니다.
  다만 프롬프트 지시만으로는 완전히 막을 수 없으므로, 외부에 영향을 주는 `send_reply`는 코드 안전장치로 한 번 더 막습니다.
- Grok이 쓸 수 있는 도구는 A 시스템 주문 가능 여부 **조회**(`check_order`, 실제 주문은 하지 않음)와 **답장**(`send_reply`)입니다.
- 답장을 보낸 뒤 처리가 중단되면(시간 초과 등) 기준점이 갱신되지 않아, 다음 실행 때 같은 메일에 다시 답장할 수 있습니다.
  `send` 모드에서는 `--timeout`을 넉넉히 두세요.
- `credentials.json`(메일 비밀번호, Grok API 키, A 시스템 토큰 포함), `state.json`, `mails/`는 `.gitignore`에 포함되어 있습니다.
