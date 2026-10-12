"""A 시스템 (테스트용 간단 웹 서버).

POST /api/orders/check 로 상품명·가격·개수를 받아 주문 가능 여부를 JSON으로 응답한다.
상품 목록은 system_a_products.json 에서 읽는다 (요청마다 다시 읽으므로 수정 후 재시작 불필요).

실행:
    python system_a_server.py                 # http://127.0.0.1:8000
    python system_a_server.py --port 9000 --host 0.0.0.0

요청 예:
    curl -X POST http://127.0.0.1:8000/api/orders/check \\
         -H "Content-Type: application/json" \\
         -d '{"product_name": "무선 마우스", "price": 25000, "quantity": 10}'
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PRODUCTS_FILE = Path(__file__).resolve().parent / "system_a_products.json"
CHECK_PATH = "/api/orders/check"


def normalize(name):
    return "".join(str(name).split()).lower()


def load_products():
    return json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))


def find_product(products, product_name):
    key = normalize(product_name)
    for product in products:
        if normalize(product["name"]) == key:
            return product
    return None


def check_order(body):
    """주문 가능 여부를 판단. (HTTP 상태 코드, 응답 dict) 반환."""
    name = body.get("product_name")
    price = body.get("price")
    quantity = body.get("quantity")

    if not isinstance(name, str) or not name.strip():
        return 400, {"error": "product_name 은 비어 있지 않은 문자열이어야 합니다."}
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        return 400, {"error": "quantity 는 1 이상의 정수여야 합니다."}
    if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0):
        return 400, {"error": "price 는 0 이상의 숫자여야 합니다 (모르면 생략)."}

    requested = {"product_name": name, "price": price, "quantity": quantity}
    product = find_product(load_products(), name)

    if product is None:
        return 200, {"orderable": False, "reason": "등록되지 않은 상품입니다.", "requested": requested, "product": None}

    reasons = []
    if product["stock"] < quantity:
        reasons.append(f"재고 부족 (재고 {product['stock']}개, 요청 {quantity}개)")
    if price is not None and price < product["price"]:
        reasons.append(f"요청 단가가 판매가보다 낮음 (판매가 {product['price']}원, 요청 {price}원)")

    return 200, {
        "orderable": not reasons,
        "reason": ", ".join(reasons) if reasons else "주문 가능합니다.",
        "requested": requested,
        "product": {
            "name": product["name"],
            "price": product["price"],
            "stock": product["stock"],
            "total_price": product["price"] * quantity,
        },
    }


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path.rstrip("/") != CHECK_PATH:
            return self.send_json(404, {"error": f"없는 경로입니다. POST {CHECK_PATH} 를 사용하세요."})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json(400, {"error": "요청 본문은 JSON 객체여야 합니다."})
        self.send_json(*check_order(body))

    def do_GET(self):
        # 동작 확인용: 등록된 상품 목록
        if self.path.rstrip("/") == "/api/products":
            return self.send_json(200, {"products": load_products()})
        self.send_json(404, {"error": f"없는 경로입니다. POST {CHECK_PATH} 를 사용하세요."})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"A 시스템 서버 시작: http://{args.host}:{args.port}{CHECK_PATH} (Ctrl+C로 종료)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nA 시스템 서버 종료")


if __name__ == "__main__":
    main()
