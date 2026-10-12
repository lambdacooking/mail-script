"""Gmail에서 새 메일을 확인하고, 새 메일이 있으면 JSON 파일로 저장한다.

한 번 실행하면 한 번만 확인하고 종료한다. 주기 실행은 scheduler.py가 담당한다.

새 메일 판별은 Gmail History API(historyId)를 사용한다.
- 첫 실행: 현재 historyId만 state.json에 기록하고 종료 (기존 메일은 저장하지 않음)
- 이후 실행: 마지막 historyId 이후 INBOX에 추가된 메일만 가져와 저장
"""

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
STATE_FILE = BASE_DIR / "state.json"
OUTPUT_DIR = Path(os.environ.get("MAIL_OUTPUT_DIR", BASE_DIR / "mails"))


def get_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                sys.exit(f"[오류] {CREDENTIALS_FILE} 가 없습니다. README.md의 설정 방법을 참고하세요.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_FILE)


def current_history_id(service):
    return service.users().getProfile(userId="me").execute()["historyId"]


def fetch_new_message_ids(service, start_history_id):
    """start_history_id 이후 INBOX에 추가된 메시지 ID 목록과 최신 historyId를 반환."""
    message_ids = []
    latest_history_id = start_history_id
    page_token = None

    while True:
        resp = (
            service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=start_history_id,
                historyTypes=["messageAdded"],
                labelId="INBOX",
                pageToken=page_token,
            )
            .execute()
        )
        latest_history_id = resp.get("historyId", latest_history_id)
        for record in resp.get("history", []):
            for added in record.get("messagesAdded", []):
                msg_id = added["message"]["id"]
                if msg_id not in message_ids:
                    message_ids.append(msg_id)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return message_ids, latest_history_id


def decode_body(data):
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def extract_bodies(payload):
    """메시지 payload에서 text/plain, text/html 본문을 추출."""
    text, html = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and not part.get("filename"):
            if mime == "text/plain":
                text.append(decode_body(data))
            elif mime == "text/html":
                html.append(decode_body(data))
        for sub in part.get("parts", []):
            walk(sub)

    walk(payload)
    return "\n".join(text), "\n".join(html)


def extract_attachments(payload):
    attachments = []

    def walk(part):
        if part.get("filename"):
            attachments.append(
                {
                    "filename": part["filename"],
                    "mimeType": part.get("mimeType"),
                    "size": part.get("body", {}).get("size"),
                    "attachmentId": part.get("body", {}).get("attachmentId"),
                }
            )
        for sub in part.get("parts", []):
            walk(sub)

    walk(payload)
    return attachments


def get_message(service, msg_id):
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    body_text, body_html = extract_bodies(payload)

    return {
        "id": msg["id"],
        "threadId": msg.get("threadId"),
        "labelIds": msg.get("labelIds", []),
        "internalDate": datetime.fromtimestamp(int(msg["internalDate"]) / 1000).isoformat(),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "cc": headers.get("cc"),
        "subject": headers.get("subject"),
        "date": headers.get("date"),
        "snippet": msg.get("snippet"),
        "body_text": body_text,
        "body_html": body_html,
        "attachments": extract_attachments(payload),
    }


def save_mails(mails):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 마이크로초까지 포함한 타임스탬프로 파일명을 고유하게 생성
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = OUTPUT_DIR / f"mails_{timestamp}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {"fetched_at": datetime.now().isoformat(), "count": len(mails), "mails": mails},
            f,
            ensure_ascii=False,
            indent=2,
        )
    return path


def main():
    service = get_service()
    state = load_state()

    if "historyId" not in state:
        state["historyId"] = current_history_id(service)
        save_state(state)
        print(f"[초기화] 기준 historyId={state['historyId']} 저장. 다음 실행부터 새 메일을 확인합니다.")
        return

    try:
        msg_ids, latest_history_id = fetch_new_message_ids(service, state["historyId"])
    except HttpError as e:
        # historyId가 너무 오래되면 404가 반환됨 → 기준점을 재설정
        if e.resp.status == 404:
            state["historyId"] = current_history_id(service)
            save_state(state)
            print("[경고] historyId 만료. 기준점을 재설정했습니다.")
            return
        raise

    mails = []
    for msg_id in msg_ids:
        try:
            mails.append(get_message(service, msg_id))
        except HttpError as e:
            # 확인 사이에 삭제된 메일 등은 건너뜀
            if e.resp.status == 404:
                continue
            raise

    if mails:
        path = save_mails(mails)
        print(f"[새 메일] {len(mails)}건 → {path}")
    else:
        print("[확인] 새 메일 없음")

    # 저장이 끝난 뒤에 상태를 갱신해야 실패 시 메일이 누락되지 않음
    state["historyId"] = latest_history_id
    save_state(state)


if __name__ == "__main__":
    main()
