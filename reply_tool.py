"""Grok이 호출하는 답장 발송 도구 (send_reply).

MCP 서버가 아니라 analyzer.py 안에서 직접 실행하는 로컬 도구다.
'지금 처리 중인 메일'을 알아야 받는 사람을 검증할 수 있기 때문이다.

LLM이 도구 인자를 마음대로 정해도 아래 안전장치는 코드가 강제한다.
- 받는 사람은 원래 메일의 보낸 사람이어야 함 (다른 주소면 거부)
- 메일 1건당 답장 1통
- allowed_senders 가 있으면 그 발신자에게만 답장
- mode 가 dry_run 이면 실제로 보내지 않고 기록만 함
- 같은 메일에서 주문이 dry_run(가상 주문)이었다면 send 모드여도 보내지 않음
"""

import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

REPLY_DEFAULTS = {
    "mode": "dry_run",  # off: 도구 비활성화, dry_run: 기록만, send: 실제 발송
    "smtp_server": "smtp.naver.com",
    "smtp_port": 465,
    "from_address": "",  # 비우면 username@naver.com
    "allowed_senders": [],  # 비우면 모든 발신자에게 답장 허용
    "max_body_chars": 5000,
}

SPEC = {
    "type": "function",
    "function": {
        "name": "send_reply",
        "description": (
            "지금 분석 중인 메일의 보낸 사람에게 답장을 보낸다. 메일 1건당 한 번만 호출할 수 있다. "
            "주문·견적·재고 문의처럼 답장이 필요한 메일에만, check_order 조회를 모두 마친 뒤 호출한다. "
            "광고·알림·자동발송 메일에는 호출하지 않는다. "
            "결과로 성공 여부(ok)와 거부·실패 사유(error)를 돌려준다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "받는 사람 이메일 주소 (원래 메일의 보낸 사람)"},
                "subject": {"type": "string", "description": "답장 제목. 비우면 'Re: 원래 제목'"},
                "body": {"type": "string", "description": "답장 본문 (일반 텍스트)"},
            },
            "required": ["to", "body"],
        },
    },
}


def load_reply_config(config):
    reply = {**REPLY_DEFAULTS, **(config.get("reply") or {})}
    if not reply["from_address"]:
        username = config.get("username", "")
        reply["from_address"] = username if "@" in username else f"{username}@naver.com"
    return reply


def is_enabled(config):
    return load_reply_config(config)["mode"] in ("dry_run", "send")


def build_message(mail, from_address, to, subject, body):
    msg = EmailMessage()
    msg["From"] = from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_address.split("@")[-1])
    # 원래 메일과 같은 대화(스레드)로 묶이도록 함
    if mail.get("message_id"):
        msg["In-Reply-To"] = mail["message_id"]
        msg["References"] = mail["message_id"]
    msg.set_content(body)
    return msg


def send_smtp(config, reply, msg):
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(reply["smtp_server"], int(reply["smtp_port"]), context=context, timeout=30) as smtp:
        smtp.login(config["username"], config["password"])
        smtp.send_message(msg)


class ReplyTool:
    """메일 1건에 대한 send_reply 도구. 메일마다 새로 만든다."""

    def __init__(self, mail, config, order_guard=None):
        self.mail = mail
        self.config = config
        self.reply = load_reply_config(config)
        self.order_guard = order_guard
        self.record = None  # 성공한 답장 기록 (analysis.reply 에 저장)

    def reject(self, reason):
        return {"ok": False, "error": reason}

    def __call__(self, args):
        if self.record is not None:
            return self.reject("이 메일에는 이미 답장했습니다. 메일 1건당 답장은 한 번만 가능합니다.")

        original_sender = parseaddr(self.mail.get("from") or "")[1].lower()
        to = parseaddr(str(args.get("to") or ""))[1].lower()
        body = str(args.get("body") or "").strip()
        subject = str(args.get("subject") or "").strip() or self.default_subject()

        if not original_sender:
            return self.reject("원래 메일의 보낸 사람 주소를 알 수 없어 답장할 수 없습니다.")
        if to != original_sender:
            return self.reject(f"받는 사람은 원래 메일의 보낸 사람({original_sender})이어야 합니다.")
        allowed = [a.lower() for a in self.reply["allowed_senders"]]
        if allowed and original_sender not in allowed:
            return self.reject("답장이 허용되지 않은 발신자입니다 (allowed_senders).")
        if not body:
            return self.reject("본문이 비어 있습니다.")
        if len(body) > int(self.reply["max_body_chars"]):
            return self.reject(f"본문이 너무 깁니다 (최대 {self.reply['max_body_chars']}자).")

        msg = build_message(self.mail, self.reply["from_address"], to, subject, body)
        record = {
            "mode": self.reply["mode"],
            "to": to,
            "subject": subject,
            "body": body,
            "message_id": msg["Message-ID"],
            "at": datetime.now().isoformat(),
        }

        # 주문이 dry_run(가상 주문)이었다면 답장에 가짜 주문번호가 들어 있으므로 실제 발송하지 않음
        simulated_order = self.order_guard is not None and self.order_guard.simulated
        if self.reply["mode"] == "send" and not simulated_order:
            try:
                send_smtp(self.config, self.reply, msg)
            except Exception as e:
                return self.reject(f"발송 실패: {e}")
            record["status"] = "sent"
        elif self.reply["mode"] == "send":
            record["status"] = "dry_run (주문이 dry_run이라 가짜 주문번호가 나가지 않도록 발송 보류)"
        else:
            record["status"] = "dry_run (실제로 보내지 않음)"

        self.record = record
        return {"ok": True, "status": record["status"], "to": to, "subject": subject}

    def default_subject(self):
        original = self.mail.get("subject") or ""
        return original if original.lower().startswith("re:") else f"Re: {original}".strip()
