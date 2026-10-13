"""메일 대화(스레드) 기록.

고객이 우리 답장에 회신하면, 그 메일의 In-Reply-To / References 헤더에 우리 답장의 Message-ID 가 들어 있다.
이 Message-ID 들을 대화 ID에 연결해 두면(index), 회신이 어느 대화에 속하는지 알 수 있다.

threads.json 구조:
{
  "threads": {
    "<대화 ID>": {
      "participant": "고객 주소",
      "replies_sent": 3,               # 이 대화에서 send_reply 로 보낸 답장 수
      "messages": [                    # 주고받은 내용 (오래된 순)
        {"from": "customer", "at": "...", "subject": "...", "body": "..."},
        {"from": "us", "at": "...", "subject": "...", "body": "..."}
      ]
    }
  },
  "index": {"<Message-ID>": "<대화 ID>"}   # 고객 메일·우리 답장의 Message-ID → 대화 ID
}
"""

import json
import re
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
THREADS_FILE = BASE_DIR / "threads.json"

MAX_HISTORY_MESSAGES = 10  # Grok에게 넘기는 이전 대화 개수 (최근 것부터)
MAX_STORED_BODY = 2000  # 대화 기록에 저장하는 본문 최대 길이


def message_ids(header):
    """References / In-Reply-To 헤더에서 <...> 형태의 Message-ID 목록을 뽑는다."""
    return re.findall(r"<[^<>\s]+>", header or "")


class ThreadStore:
    def __init__(self, path=THREADS_FILE):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"threads": {}, "index": {}}

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def find_thread_id(self, mail):
        """이 메일이 이어지는 기존 대화의 ID. 새 대화면 None."""
        ids = message_ids(mail.get("references")) + message_ids(mail.get("in_reply_to"))
        for mid in reversed(ids):  # 가장 최근에 참조한 메일부터
            if mid in self.data["index"]:
                return self.data["index"][mid]
        return None

    def context(self, mail):
        """분석 전에 필요한 대화 정보: 대화 ID, 지금까지 보낸 답장 수, 이전 대화 내용."""
        thread_id = self.find_thread_id(mail)
        thread = self.data["threads"].get(thread_id) if thread_id else None
        if thread is None:
            thread_id = mail.get("message_id") or f"uid-{mail.get('uid')}"
            return {"thread_id": thread_id, "is_followup": False, "replies_sent": 0, "history": []}
        return {
            "thread_id": thread_id,
            "is_followup": True,
            "replies_sent": thread["replies_sent"],
            "history": thread["messages"][-MAX_HISTORY_MESSAGES:],
        }

    def record(self, mail, context, replies):
        """분석이 끝난 뒤, 고객 메일과 보낸 답장을 대화에 기록하고 저장."""
        thread_id = context["thread_id"]
        thread = self.data["threads"].setdefault(
            thread_id,
            {"participant": parseaddr(mail.get("from") or "")[1].lower(), "replies_sent": 0, "messages": []},
        )
        thread["messages"].append(
            {
                "from": "customer",
                "at": mail.get("date_iso") or datetime.now().isoformat(),
                "subject": mail.get("subject"),
                "body": (mail.get("body_text") or "")[:MAX_STORED_BODY],
            }
        )
        if mail.get("message_id"):
            self.data["index"][mail["message_id"]] = thread_id

        for reply in replies or []:
            thread["messages"].append(
                {"from": "us", "at": reply.get("at"), "subject": reply.get("subject"), "body": reply.get("body")}
            )
            if reply.get("message_id"):
                self.data["index"][reply["message_id"]] = thread_id
        thread["replies_sent"] += len(replies or [])
        self.save()
        return thread["replies_sent"]
