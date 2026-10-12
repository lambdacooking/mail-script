"""A 시스템 주문 가능 여부 조회 MCP 서버 (stdio).

analyzer.py 가 이 파일을 하위 프로세스로 실행해 MCP로 접속한다. 직접 실행할 일은 없다.
A 시스템 접속 정보는 credentials.json 의 "system_a" 항목에서 읽는다.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.mcpserver import MCPServer

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = Path(os.environ.get("MAIL_CREDENTIALS_FILE", BASE_DIR / "credentials.json"))

DEFAULTS = {"base_url": "http://127.0.0.1:8000", "check_path": "/api/orders/check", "headers": {}, "timeout": 10}


def load_config():
    config = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8")).get("system_a") or {}
    return {**DEFAULTS, **config}


mcp = MCPServer("system-a")


@mcp.tool(
    description=(
        "A 시스템에 상품의 주문 가능 여부를 조회한다. "
        "product_name 은 상품명, price 는 메일에 적힌 단가(원, 모르면 생략), quantity 는 주문 개수. "
        "응답의 orderable 이 주문 가능 여부, reason 이 사유, product 가 A 시스템에 등록된 상품 정보(없으면 null)다."
    )
)
def check_order(product_name: str, quantity: int, price: float | None = None) -> str:
    config = load_config()
    url = config["base_url"].rstrip("/") + "/" + config["check_path"].lstrip("/")
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


if __name__ == "__main__":
    mcp.run("stdio")
