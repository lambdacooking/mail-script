# mail-script

10초마다 네이버 메일(IMAP)의 새 메일을 확인해 로컬에 JSON 파일로 저장하는 스크립트.

| 파일 | 역할 |
| --- | --- |
| `check_mail.py` | 새 메일을 한 번 확인하고, 있으면 `mails/mails_YYYYMMDD_HHMMSS_ffffff.json`으로 저장 |
| `scheduler.py` | `check_mail.py`를 10초마다 실행 |
| `credentials.example.json` | 접속 정보 파일 예시 |

## 설정

1. 패키지 설치

   ```bash
   pip install -r requirements.txt
   ```

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
      "attachments": [{"filename": "...", "mimeType": "...", "size": 1234}]
    }
  ]
}
```

새 메일이 없으면 파일을 만들지 않습니다.

## 동작 방식

- IMAP UID로 마지막으로 확인한 메일 이후의 메일만 가져오므로 중복 저장이 없습니다.
- 메일함을 읽기 전용으로 열고 `BODY.PEEK`로 가져오므로 메일이 '읽음'으로 바뀌지 않습니다.
- 메일함의 `UIDVALIDITY`가 바뀌면 기준점을 현재로 재설정합니다.
- `credentials.json`, `state.json`, `mails/`는 `.gitignore`에 포함되어 있습니다.
