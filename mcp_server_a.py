"""A 시스템 상품 조회 MCP 서버 (stdio).

analyzer.py 가 이 파일을 하위 프로세스로 실행해 MCP로 접속한다. 직접 실행할 일은 없다.
A 시스템 접속 정보는 credentials.json 의 "system_a" 항목에서 읽는다.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.mcpserver import MCPServer

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = Path(os.environ.get("MAIL_CREDENTIALS_FILE", BASE_DIR / "credentials.json"))

# Grok에 넘길 응답 최대 길이 (너무 긴 응답은 잘라서 토큰 낭비를 막음)
MAX_RESPONSE_CHARS = 20000


def load_config():
    config = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8")).get("system_a") or {}
    if not config.get("base_url"):
        raise RuntimeError(f"{CREDENTIALS_FILE.name} 의 system_a.base_url 값이 없습니다.")
    return {
        "search_path": "/",
        "method": "GET",
        "query_param": "q",
        "headers": {},
        "extra_params": {},
        "timeout": 10,
        **config,
    }


mcp = MCPServer("system-a")


@mcp.tool(description="A 시스템에서 상품을 검색한다. 상품명, 모델명, 상품코드 등의 키워드로 조회하며 A 시스템의 응답을 그대로 반환한다.")
def search_products(keyword: str) -> str:
    config = load_config()
    params = {**config["extra_params"], config["query_param"]: keyword}
    url = config["base_url"].rstrip("/") + "/" + config["search_path"].lstrip("/")
    headers = {"Accept": "application/json", **config["headers"]}
    method = config["method"].upper()

    if method == "GET":
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        data = None
    else:
        data = json.dumps(params).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=float(config["timeout"])) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        status = e.code

    if len(body) > MAX_RESPONSE_CHARS:
        body = body[:MAX_RESPONSE_CHARS] + "...(생략)"
    return json.dumps({"keyword": keyword, "status": status, "response": body}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run("stdio")
