"""네이버 메일(IMAP)에서 새 메일을 확인하고, 새 메일이 있으면 JSON 파일로 저장한다.

한 번 실행하면 한 번만 확인하고 종료한다. 주기 실행은 scheduler.py가 담당한다.

접속 정보는 credentials.json 에서 읽는다 (credentials.example.json 참고).

새 메일 판별은 IMAP UID를 사용한다.
- 첫 실행: 현재 마지막 UID만 state.json에 기록하고 종료 (기존 메일은 저장하지 않음)
- 이후 실행: 마지막 UID보다 큰 메일만 가져와 저장
- 메일함의 UIDVALIDITY가 바뀌면 UID가 무효이므로 기준점을 재설정
"""

import email
import imaplib
import json
import os
import sys
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = Path(os.environ.get("MAIL_CREDENTIALS_FILE", BASE_DIR / "credentials.json"))
STATE_FILE = BASE_DIR / "state.json"
OUTPUT_DIR = Path(os.environ.get("MAIL_OUTPUT_DIR", BASE_DIR / "mails"))

DEFAULTS = {"imap_server": "imap.naver.com", "imap_port": 993, "mailbox": "INBOX"}


def load_credentials():
    if not CREDENTIALS_FILE.exists():
        sys.exit(
            f"[오류] {CREDENTIALS_FILE} 가 없습니다. "
            "credentials.example.json 을 복사해 credentials.json 을 만들고 값을 채우세요."
        )
    config = {**DEFAULTS, **json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))}
    missing = [key for key in ("username", "password") if not config.get(key)]
    if missing:
        sys.exit(f"[오류] {CREDENTIALS_FILE.name} 에 {', '.join(missing)} 값이 없습니다.")
    return config


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_FILE)


def connect(config):
    imap = imaplib.IMAP4_SSL(config["imap_server"], int(config["imap_port"]))
    try:
        imap.login(config["username"], config["password"])
    except imaplib.IMAP4.error as e:
        sys.exit(
            f"[오류] 로그인 실패: {e}\n"
            "네이버 메일 환경설정에서 IMAP 사용을 켰는지, "
            "2단계 인증 사용 시 애플리케이션 비밀번호를 넣었는지 확인하세요."
        )
    return imap


def select_mailbox(imap, mailbox):
    """메일함을 읽기 전용으로 선택하고 UIDVALIDITY를 반환."""
    status, _ = imap.select(mailbox, readonly=True)
    if status != "OK":
        sys.exit(f"[오류] 메일함 '{mailbox}' 를 열 수 없습니다.")
    _, data = imap.response("UIDVALIDITY")
    return int(data[0])


def search_uids(imap, criteria):
    status, data = imap.uid("SEARCH", None, criteria)
    if status != "OK" or not data or not data[0]:
        return []
    return sorted(int(uid) for uid in data[0].split())


def latest_uid(imap):
    uids = search_uids(imap, "ALL")
    return uids[-1] if uids else 0


def decode_str(value):
    if value is None:
        return None
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def decode_payload(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def parse_message(uid, raw):
    msg = email.message_from_bytes(raw)
    text, html, attachments = [], [], []

    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                {
                    "filename": decode_str(filename),
                    "mimeType": part.get_content_type(),
                    "size": len(payload),
                }
            )
        elif part.get_content_type() == "text/plain":
            text.append(decode_payload(part))
        elif part.get_content_type() == "text/html":
            html.append(decode_payload(part))

    try:
        date_iso = parsedate_to_datetime(msg["Date"]).isoformat() if msg["Date"] else None
    except (TypeError, ValueError):
        date_iso = None

    return {
        "uid": uid,
        "message_id": msg["Message-ID"],
        "from": decode_str(msg["From"]),
        "to": decode_str(msg["To"]),
        "cc": decode_str(msg["Cc"]),
        "subject": decode_str(msg["Subject"]),
        "date": msg["Date"],
        "date_iso": date_iso,
        "body_text": "\n".join(text),
        "body_html": "\n".join(html),
        "attachments": attachments,
    }


def fetch_message(imap, uid):
    # BODY.PEEK 를 사용해 메일을 '읽음'으로 바꾸지 않음
    status, data = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
    if status != "OK":
        return None
    for item in data:
        if isinstance(item, tuple):
            return parse_message(uid, item[1])
    return None


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


def own_addresses(config):
    """이 스크립트가 쓰는 내 메일 주소들 (내가 보낸 답장이 다시 분석되지 않도록 거르는 데 사용)."""
    username = config.get("username", "")
    addresses = {username if "@" in username else f"{username}@naver.com"}
    from_address = (config.get("reply") or {}).get("from_address")
    if from_address:
        addresses.add(from_address)
    return {a.lower() for a in addresses}


def attach_analysis(mails, config):
    """credentials.json 에 grok 설정이 있으면 메일마다 Grok 분석 + A 시스템 조회 결과를 붙인다."""
    if not (config.get("grok") or {}).get("api_key"):
        return

    # 내 주소에서 온 메일(내가 보낸 답장 등)은 분석하지 않음: 답장 → 재분석 → 재주문 루프 방지
    mine = own_addresses(config)
    targets = []
    for mail in mails:
        if parseaddr(mail.get("from") or "")[1].lower() in mine:
            mail["analysis"] = {"skipped": "내 메일 주소에서 온 메일이라 분석하지 않았습니다."}
        else:
            targets.append(mail)
    if not targets:
        print(f"[분석] 내 주소에서 온 메일 {len(mails)}건은 분석하지 않음")
        return

    try:
        from analyzer import analyze_mails

        results = analyze_mails(targets, config)
    except Exception as e:
        # 분석이 실패해도 메일 저장은 계속 진행
        print(f"[오류] 메일 분석 실패: {e}")
        results = [{"error": str(e)}] * len(targets)
    for mail, result in zip(targets, results):
        mail["analysis"] = result
        modes = result.get("modes")
        if modes:
            print(f"[분석] 적용된 모드: 주문={modes['order']}, 답장={modes['reply']}")
    failed = sum(1 for result in results if "error" in result)
    skipped = len(mails) - len(targets)
    print(f"[분석] {len(targets)}건 중 {len(targets) - failed}건 성공, {failed}건 실패" + (f" (내 메일 {skipped}건 제외)" if skipped else ""))


def main():
    config = load_credentials()
    state = load_state()
    imap = connect(config)

    try:
        uid_validity = select_mailbox(imap, config["mailbox"])

        if "last_uid" not in state or state.get("uid_validity") != uid_validity:
            state = {"uid_validity": uid_validity, "last_uid": latest_uid(imap)}
            save_state(state)
            print(f"[초기화] 기준 UID={state['last_uid']} 저장. 다음 실행부터 새 메일을 확인합니다.")
            return

        last_uid = state["last_uid"]
        # 'N:*' 는 새 메일이 없어도 마지막 메일을 돌려주므로 last_uid 초과만 남김
        new_uids = [uid for uid in search_uids(imap, f"UID {last_uid + 1}:*") if uid > last_uid]

        mails = [m for m in (fetch_message(imap, uid) for uid in new_uids) if m]

        if mails:
            attach_analysis(mails, config)
            path = save_mails(mails)
            print(f"[새 메일] {len(mails)}건 → {path}")
        else:
            print("[확인] 새 메일 없음")

        # 저장이 끝난 뒤에 상태를 갱신해야 실패 시 메일이 누락되지 않음
        if new_uids:
            state["last_uid"] = new_uids[-1]
            save_state(state)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
