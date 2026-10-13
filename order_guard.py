"""place_order 도구 호출에 대한 안전장치 (메일 1건 단위).

place_order 자체는 MCP 서버의 도구지만, MCP 서버는 '어떤 메일을 처리 중인지' 모른다.
그래서 analyzer.py 가 도구 호출을 MCP 서버로 넘기기 전후에 이 객체를 거치게 한다.

LLM이 어떤 인자로 호출하든 아래 규칙은 코드가 강제한다.
- 같은 상품명·개수로 check_order 를 먼저 호출해 orderable=true 를 받은 경우에만 주문
- 메일 1건당 같은 상품은 한 번만 주문
- 메일 1건당 주문 건수 상한 (max_orders_per_mail)
- mode 가 dry_run 이면 A 시스템에 주문하지 않고 가상의 결과만 돌려줌
"""

import json

from reply_tool import check_mode

ORDER_DEFAULTS = {
    "mode": "dry_run",  # off: place_order 를 Grok에 주지 않음, dry_run: 가상 주문, live: 실제 주문
    "max_orders_per_mail": 5,
}


def normalize(name):
    return "".join(str(name).split()).lower()


ORDER_MODES = ("off", "dry_run", "live")


def load_order_config(config):
    order = {**ORDER_DEFAULTS, **(config.get("order") or {})}
    order["mode"] = check_mode("order", order["mode"], ORDER_MODES)
    return order


def is_enabled(config):
    return load_order_config(config)["mode"] in ("dry_run", "live")


def parse_json(text):
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


class OrderGuard:
    """메일 1건 동안 check_order / place_order 호출을 추적한다. 메일마다 새로 만든다."""

    def __init__(self, config):
        self.order_config = load_order_config(config)
        self.orderable = set()  # check_order 에서 주문 가능으로 확인된 (상품명, 개수)
        self.ordered = set()  # 이미 주문한 상품명
        self.records = []  # analysis.orders 에 저장할 주문 기록

    @property
    def dry_run(self):
        return self.order_config["mode"] == "dry_run"

    @property
    def simulated(self):
        """dry_run 으로 가상 주문을 한 적이 있는지. 있으면 답장도 실제로 보내면 안 된다."""
        return any(r.get("dry_run") for r in self.records)

    def after_check(self, args, result_text):
        result = parse_json(result_text)
        if not result.get("orderable"):
            return
        quantity = args.get("quantity")
        names = {normalize(args.get("product_name", ""))}
        if result.get("product"):
            names.add(normalize(result["product"]["name"]))
        for name in names:
            self.orderable.add((name, quantity))

    def before_order(self, args):
        """주문하면 안 되는 경우 Grok에 돌려줄 거부 응답, 괜찮으면 None."""
        name = normalize(args.get("product_name", ""))
        quantity = args.get("quantity")
        if (name, quantity) not in self.orderable:
            return {
                "ordered": False,
                "error": "같은 상품명·개수로 check_order 를 먼저 호출해 orderable=true 를 확인한 뒤에만 주문할 수 있습니다.",
            }
        if name in self.ordered:
            return {"ordered": False, "error": "이 메일에서 이미 주문한 상품입니다. 같은 상품은 한 번만 주문할 수 있습니다."}
        limit = int(self.order_config["max_orders_per_mail"])
        if len(self.ordered) >= limit:
            return {"ordered": False, "error": f"메일 1건당 최대 {limit}개 상품까지만 주문할 수 있습니다."}
        return None

    def simulate(self, args):
        name = args.get("product_name")
        self.ordered.add(normalize(name))
        record = {
            "ordered": True,
            "dry_run": True,
            "order_id": f"DRYRUN-{len(self.records) + 1}",
            "product_name": name,
            "quantity": args.get("quantity"),
            "reason": "dry_run 모드: A 시스템에 실제로 주문하지 않았습니다.",
        }
        self.records.append(record)
        return record

    def after_order(self, args, result_text):
        result = parse_json(result_text)
        if result.get("ordered"):
            self.ordered.add(normalize(args.get("product_name", "")))
        self.records.append({"arguments": args, **result} if result else {"arguments": args, "raw": result_text})
