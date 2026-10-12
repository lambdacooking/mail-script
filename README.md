# mail-script

10초마다 Gmail의 새 메일을 확인해 로컬에 JSON 파일로 저장하는 스크립트.

| 파일 | 역할 |
| --- | --- |
| `check_mail.py` | 새 메일을 한 번 확인하고, 있으면 `mails/mails_YYYYMMDD_HHMMSS_ffffff.json`으로 저장 |
| `scheduler.py` | `check_mail.py`를 10초마다 실행 |

## 설정

1. 패키지 설치

   ```bash
   pip install -r requirements.txt
   ```

2. Gmail API 자격 증명 준비
   1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트 생성
   2. **API 및 서비스 → 라이브러리**에서 **Gmail API** 사용 설정
   3. **OAuth 동의 화면** 구성 (테스트 사용자에 본인 Gmail 추가)
   4. **사용자 인증 정보 → OAuth 클라이언트 ID 생성 → 데스크톱 앱**
   5. 다운로드한 JSON을 이 폴더에 `credentials.json`으로 저장

3. 최초 인증 (브라우저가 열림)

   ```bash
   python check_mail.py
   ```

   로그인하면 `token.json`이 생성되고, 현재 시점이 기준점으로 `state.json`에 기록됩니다.
   이 시점 **이후** INBOX에 들어온 메일만 "새 메일"로 저장됩니다.

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
      "id": "...", "threadId": "...", "labelIds": ["INBOX", "UNREAD"],
      "internalDate": "2026-10-12T09:59:58",
      "from": "...", "to": "...", "cc": null,
      "subject": "...", "date": "...", "snippet": "...",
      "body_text": "...", "body_html": "...",
      "attachments": [{"filename": "...", "mimeType": "...", "size": 1234, "attachmentId": "..."}]
    }
  ]
}
```

새 메일이 없으면 파일을 만들지 않습니다.

## 동작 방식

- Gmail History API(`historyId`)로 마지막 확인 이후 INBOX에 추가된 메일만 조회하므로 중복 저장이 없습니다.
- `historyId`가 만료되면(오랫동안 실행하지 않은 경우) 기준점을 현재로 재설정합니다.
- `credentials.json`, `token.json`, `state.json`, `mails/`는 `.gitignore`에 포함되어 있습니다.
