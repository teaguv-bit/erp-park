import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://localhost:3002"
OUT = Path(os.getenv("ERP_DIAG_OUT", "DIAG_separacao_cliente_origem_real.txt"))

def write(s=""):
    with OUT.open("a", encoding="utf-8") as f:
        f.write(str(s) + "\n")

def request_json(method, path, token=None, body=None):
    data = None
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        return e.code, payload

OUT.write_text("", encoding="utf-8")

write("=== DIAG SEPARACAO CLIENTE ORIGEM REAL ===")

status, login = request_json("POST", "/api/auth/login", body={"login": os.getenv("ERP_DIAG_LOGIN", "Admin"), "password": os.getenv("ERP_DIAG_PASSWORD", "")})
write("LOGIN_STATUS=" + str(status))
token = login.get("token")

pedidos = ["23999", "23442", "24129"]

for p in pedidos:
    write("")
    write("========================================")
    write("PEDIDO_NUMERO=" + p)
    write("========================================")

    q = urllib.parse.urlencode({"company": "parton", "q": p, "limit": 10})
    status, listing = request_json("GET", "/api/separation/orders?" + q, token=token)
    write("LIST_STATUS=" + str(status))
    write("LIST_JSON=")
    write(json.dumps(listing, ensure_ascii=False, indent=2))

    items = listing.get("items") or listing.get("orders") or []
    if not items:
        write("NO_ITEMS_FOUND_IN_LIST")
        continue

    first = items[0]
    write("FIRST_ITEM_KEYS=" + ", ".join(sorted(first.keys())))

    tiny_order_id = first.get("tiny_order_id") or first.get("id") or first.get("order_id")
    tiny_order_number = first.get("tiny_order_number") or first.get("numero") or first.get("number")

    write("FIRST_tiny_order_id=" + str(tiny_order_id))
    write("FIRST_tiny_order_number=" + str(tiny_order_number))
    write("FIRST_client_name=" + str(first.get("client_name")))
    write("FIRST_client_document=" + str(first.get("client_document")))
    write("FIRST_client_phone=" + str(first.get("client_phone")))
    write("FIRST_client_email=" + str(first.get("client_email")))
    write("FIRST_client_address=" + str(first.get("client_address")))
    write("FIRST_client_snapshot=" + str(first.get("client_snapshot"))[:2000])
    write("FIRST_payload=" + str(first.get("payload"))[:2000])

    if tiny_order_id:
        status, detail = request_json("GET", "/api/separation/orders/" + urllib.parse.quote(str(tiny_order_id)) + "?company=parton", token=token)
        write("DETAIL_BY_ID_STATUS=" + str(status))
        write("DETAIL_BY_ID_JSON=")
        write(json.dumps(detail, ensure_ascii=False, indent=2))

    if tiny_order_number:
        status, detail = request_json("GET", "/api/separation/orders/" + urllib.parse.quote(str(tiny_order_number)) + "?company=parton", token=token)
        write("DETAIL_BY_NUMBER_STATUS=" + str(status))
        write("DETAIL_BY_NUMBER_JSON=")
        write(json.dumps(detail, ensure_ascii=False, indent=2))

write("")
write("=== FIM ===")
print("Arquivo gerado:", OUT)
