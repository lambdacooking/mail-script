"""A 시스템 MCP 서버 (stdio). 주문 가능 여부 조회(check_order)와 주문 등록(place_order) 도구를 제공한다.

analyzer.py 가 이 파일을 하위 프로세스로 실행해 MCP로 접속한다. 직접 실행할 일은 없다.
A 시스템 접속 정보는 credentials.json 의 "system_a" 항목에서 읽는다.

이 서버는 A 시스템 API를 그대로 전달할 뿐이다. '메일 1건당 한 번', '조회 후에만 주문' 같은
안전장치는 어떤 메일을 처리 중인지 아는 analyzer.py(order_guard.py)가 강제한다.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.mcpserver import MCPServer

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = Path(os.environ.get("MAIL_CREDENTIALS_FILE", BASE_DIR / "credentials.json"))

DEFAULTS = {
    "base_url": "http://127.0.0.1:8000",
    "check_path": "/api/orders/check",
    "order_path": "/api/orders",
    "headers": {},
    "timeout": 10,
}


def load_config():
    config = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8")).get("system_a") or {}
    return {**DEFAULTS, **config}


def post(path_key, product_name, quantity, price):
    config = load_config()
    url = config["base_url"].rstrip("/") + "/" + config[path_key].lstrip("/")
    body = {"product_name": product_name, "quantity": quantity}
    if price is not None:
        body["price"] = price

    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", **config["headers"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config["timeout"])) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return json.dumps(
            {"http_status": e.code, "error": e.read().decode("utf-8", errors="replace")}, ensure_ascii=False
        )


mcp = MCPServer("system-a")


@mcp.tool(
    description=(
        "A 시스템에 상품의 주문 가능 여부를 조회한다 (조회만 하며 재고는 바뀌지 않는다). "
        "product_name 은 상품명, price 는 메일에 적힌 단가(원, 모르면 생략), quantity 는 주문 개수. "
        "응답의 orderable 이 주문 가능 여부, reason 이 사유, product 가 A 시스템에 등록된 상품 정보(없으면 null)다."
    )
)
def check_order(product_name: str, quantity: int, price: float | None = None) -> str:
    return post("check_path", product_name, quantity, price)


@mcp.tool(
    description=(
        "A 시스템에 주문을 실제로 등록한다 (재고가 차감되며 되돌릴 수 없다). "
        "보낸 사람이 주문을 확정한 메일에서만, 같은 상품명·개수로 check_order 를 먼저 호출해 orderable=true 를 확인한 뒤 호출한다. "
        "응답의 ordered 가 등록 여부, order_id 가 주문번호, total_price 가 총액, reason 이 사유다."
    )
)
def place_order(product_name: str, quantity: int, price: float | None = None) -> str:
    return post("order_path", product_name, quantity, price)


if __name__ == "__main__":
    mcp.run("stdio")
