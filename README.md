# mail-script

10초마다 네이버 메일(IMAP)의 새 메일을 확인해 로컬에 JSON 파일로 저장하는 스크립트.
새 메일이 있으면 Grok AI로 본문을 분석해 상품을 유추하고, MCP를 통해 A 시스템에서 해당 상품을 조회합니다.

| 파일 | 역할 |
| --- | --- |
| `check_mail.py` | 새 메일을 한 번 확인하고, 있으면 분석 후 `mails/mails_YYYYMMDD_HHMMSS_ffffff.json`으로 저장 |
| `scheduler.py` | `check_mail.py`를 10초마다 실행 |
| `analyzer.py` | Grok API 호출 + MCP 클라이언트. 메일 본문 분석 및 A 시스템 조회 |
| `mcp_server_a.py` | A 시스템 상품 조회 MCP 서버 (`analyzer.py`가 자동 실행) |
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
        "summary": "무선 마우스 10개 견적 요청",
        "products": [
          {
            "name_in_mail": "무선마우스 10개",
            "inferred_product": "무선 마우스",
            "search_keywords": ["무선 마우스"],
            "found": true,
            "matches": [{"id": "P-100", "name": "무선 마우스 M720", "detail": "재고 12"}],
            "note": ""
          }
        ],
        "tool_calls": [{"tool": "search_products", "arguments": {"keyword": "무선 마우스"}}]
      }
    }
  ]
}
```

새 메일이 없으면 파일을 만들지 않습니다.

`analysis`는 Grok 설정이 있을 때만 생깁니다. 분석이 실패하면 `{"error": "..."}`가 들어가고 메일은 그대로 저장됩니다.
Grok 답변이 JSON이 아니면 `{"raw_answer": "..."}`로 원문을 남깁니다.

## 메일 분석 및 A 시스템 조회

```
check_mail.py ── 새 메일 ──▶ analyzer.py ──(1) 본문 + 도구 목록──▶ Grok API
                                  ▲   │                              │
                                  │   └──(3) MCP 도구 호출──▶ mcp_server_a.py ──HTTP──▶ A 시스템
                                  └──────(2) search_products 호출 요청 / (4) 최종 JSON ─┘
```

1. 메일마다 본문(`body_text`, 없으면 HTML에서 추출)과 MCP 도구 목록을 Grok에 보냅니다.
2. Grok이 문맥에서 상품을 유추하고 `search_products(keyword)` 호출을 요청합니다.
3. `analyzer.py`가 그 요청을 MCP 서버로 전달하고, MCP 서버가 A 시스템에 HTTP 요청을 보냅니다.
   결과를 Grok에 돌려주면 Grok은 필요에 따라 키워드를 바꿔 다시 조회합니다 (최대 `max_tool_rounds`회).
4. Grok이 최종 결과를 JSON으로 답하면 메일의 `analysis`에 저장합니다.

### `grok` 설정

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `api_key` | xAI 콘솔(https://console.x.ai)에서 발급한 API 키 | (필수) |
| `model` | 사용할 모델 ID. 도구 호출(function calling)을 지원하는 모델이어야 함 | `grok-4` |
| `base_url` | API 주소 (OpenAI 호환 Chat Completions) | `https://api.x.ai/v1` |
| `timeout` | Grok API 1회 호출 제한 시간(초) | `60` |
| `max_tool_rounds` | 메일 1건당 Grok ↔ 도구 호출 최대 반복 횟수 | `8` |

모델 이름은 xAI 콘솔의 모델 목록에서 현재 제공되는 ID를 확인해 넣으세요.

### `system_a` 설정

`mcp_server_a.py`가 A 시스템에 보내는 HTTP 요청을 정합니다.

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `base_url` | A 시스템 주소 | (필수) |
| `search_path` | 상품 검색 API 경로 | `/` |
| `method` | `GET`이면 쿼리스트링, 그 외(`POST` 등)면 JSON 본문으로 전송 | `GET` |
| `query_param` | 검색어를 담을 파라미터 이름 | `q` |
| `extra_params` | 항상 함께 보낼 파라미터 (예: `{"size": 20}`) | `{}` |
| `headers` | 인증 등 추가 헤더 (예: `{"Authorization": "Bearer ..."}`) | `{}` |
| `timeout` | A 시스템 요청 제한 시간(초) | `10` |

예) `base_url`=`https://a.example.com`, `search_path`=`/api/products`, `query_param`=`keyword`이면
`GET https://a.example.com/api/products?keyword=무선+마우스` 로 조회합니다.

A 시스템의 응답 본문은 가공하지 않고 Grok에 전달되며(최대 20,000자), Grok이 응답을 읽고 일치하는 상품을 판단합니다.

## 동작 방식

- IMAP UID로 마지막으로 확인한 메일 이후의 메일만 가져오므로 중복 저장이 없습니다.
- 메일함을 읽기 전용으로 열고 `BODY.PEEK`로 가져오므로 메일이 '읽음'으로 바뀌지 않습니다.
- 메일함의 `UIDVALIDITY`가 바뀌면 기준점을 현재로 재설정합니다.
- Grok 분석이 실패해도 메일은 저장되고 기준점도 갱신됩니다 (분석 실패 메일은 다시 분석하지 않음).
- 메일 본문은 Grok에 분석 대상 데이터로만 전달하며, 본문 속 지시문은 따르지 않도록 지시합니다.
  Grok이 쓸 수 있는 도구는 A 시스템 **조회**뿐입니다.
- `credentials.json`(메일 비밀번호, Grok API 키, A 시스템 토큰 포함), `state.json`, `mails/`는 `.gitignore`에 포함되어 있습니다.
