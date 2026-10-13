"""A 시스템 (테스트용 간단 웹 서버).

- POST /api/orders/check : 상품명·가격·개수를 받아 주문 가능 여부를 응답 (조회만, 재고 변화 없음)
- POST /api/orders       : 주문 가능하면 주문을 등록하고 주문번호를 응답 (재고 차감)
- GET  /api/products     : 상품 목록과 남은 재고
- GET  /api/orders       : 등록된 주문 목록

상품 목록(판매가, 등록 재고)은 system_a_products.json 에서 읽고,
주문 내역은 system_a_orders.json 에 쌓는다. 남은 재고 = 등록 재고 - 주문된 수량 합계.
재고를 처음 상태로 되돌리려면 서버를 끄고 system_a_orders.json 을 지우면 된다.

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
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_FILE = BASE_DIR / "system_a_products.json"
ORDERS_FILE = BASE_DIR / "system_a_orders.json"
CHECK_PATH = "/api/orders/check"
ORDERS_PATH = "/api/orders"

# 주문 등록은 '재고 확인 → 기록'이 한 덩어리여야 하므로 동시 요청을 직렬화
ORDER_LOCK = threading.Lock()


def normalize(name):
    return "".join(str(name).split()).lower()


def load_products():
    return json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))


def load_orders():
    if ORDERS_FILE.exists():
        return json.loads(ORDERS_FILE.read_text(encoding="utf-8"))
    return []


def save_orders(orders):
    tmp = ORDERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ORDERS_FILE)


def remaining_stock(product, orders):
    ordered = sum(o["quantity"] for o in orders if normalize(o["product_name"]) == normalize(product["name"]))
    return product["stock"] - ordered


def find_product(products, product_name):
    key = normalize(product_name)
    for product in products:
        if normalize(product["name"]) == key:
            return product
    return None


def validate(body):
    """요청 형식 검사. 문제가 있으면 오류 메시지, 없으면 None."""
    name, price, quantity = body.get("product_name"), body.get("price"), body.get("quantity")
    if not isinstance(name, str) or not name.strip():
        return "product_name 은 비어 있지 않은 문자열이어야 합니다."
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        return "quantity 는 1 이상의 정수여야 합니다."
    if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0):
        return "price 는 0 이상의 숫자여야 합니다 (모르면 생략)."
    return None


def evaluate(body, orders):
    """주문 가능 여부 판단. (product 또는 None, 사유 목록, 남은 재고) 반환."""
    product = find_product(load_products(), body["product_name"])
    if product is None:
        return None, ["등록되지 않은 상품입니다."], None

    stock = remaining_stock(product, orders)
    reasons = []
    if stock < body["quantity"]:
        reasons.append(f"재고 부족 (재고 {stock}개, 요청 {body['quantity']}개)")
    price = body.get("price")
    if price is not None and price < product["price"]:
        reasons.append(f"요청 단가가 판매가보다 낮음 (판매가 {product['price']}원, 요청 {price}원)")
    return product, reasons, stock


def product_info(product, stock, quantity):
    return {
        "name": product["name"],
        "price": product["price"],
        "stock": stock,
        "total_price": product["price"] * quantity,
    }


def requested(body):
    return {"product_name": body["product_name"], "price": body.get("price"), "quantity": body["quantity"]}


def check_order(body):
    """주문 가능 여부만 조회. (HTTP 상태 코드, 응답 dict) 반환."""
    error = validate(body)
    if error:
        return 400, {"error": error}

    product, reasons, stock = evaluate(body, load_orders())
    return 200, {
        "orderable": not reasons,
        "reason": ", ".join(reasons) if reasons else "주문 가능합니다.",
        "requested": requested(body),
        "product": product_info(product, stock, body["quantity"]) if product else None,
    }


def place_order(body):
    """주문 가능하면 주문을 등록. (HTTP 상태 코드, 응답 dict) 반환."""
    error = validate(body)
    if error:
        return 400, {"error": error}

    with ORDER_LOCK:
        orders = load_orders()
        product, reasons, stock = evaluate(body, orders)
        if reasons:
            return 200, {
                "ordered": False,
                "reason": ", ".join(reasons),
                "requested": requested(body),
                "product": product_info(product, stock, body["quantity"]) if product else None,
            }

        now = datetime.now()
        order = {
            "order_id": f"ORD-{now:%Y%m%d}-{len(orders) + 1:04d}",
            "product_name": product["name"],
            "unit_price": product["price"],
            "quantity": body["quantity"],
            "total_price": product["price"] * body["quantity"],
            "ordered_at": now.isoformat(timespec="seconds"),
        }
        orders.append(order)
        save_orders(orders)

    return 200, {"ordered": True, "reason": "주문이 등록되었습니다.", **order, "remaining_stock": stock - order["quantity"]}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def not_found(self):
        self.send_json(404, {"error": f"없는 경로입니다. POST {CHECK_PATH} 또는 POST {ORDERS_PATH} 를 사용하세요."})

    def do_POST(self):
        path = self.path.rstrip("/")
        handlers = {CHECK_PATH: check_order, ORDERS_PATH: place_order}
        if path not in handlers:
            return self.not_found()
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json(400, {"error": "요청 본문은 JSON 객체여야 합니다."})
        self.send_json(*handlers[path](body))

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/api/products":
            orders = load_orders()
            products = [{**p, "stock": remaining_stock(p, orders)} for p in load_products()]
            return self.send_json(200, {"products": products})
        if path == ORDERS_PATH:
            return self.send_json(200, {"orders": load_orders()})
        self.not_found()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"A 시스템 서버 시작: http://{args.host}:{args.port} (Ctrl+C로 종료)")
    print(f"  POST {CHECK_PATH}  주문 가능 여부 조회")
    print(f"  POST {ORDERS_PATH}        주문 등록")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nA 시스템 서버 종료")


if __name__ == "__main__":
    main()
