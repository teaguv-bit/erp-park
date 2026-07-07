import json
import os
import urllib.request

BASE = "http://localhost:3002"

def req(method, path, body=None, token=None):
    data = None
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

login = req("POST", "/api/auth/login", {"login": os.getenv("ERP_DIAG_LOGIN", "Admin"), "password": os.getenv("ERP_DIAG_PASSWORD", "")})
token = login["token"]

data = req("GET", "/api/separation/orders?company=parton&q=23999&limit=5", token=token)
item = data["items"][0]

addr = item.get("client_address", "")
snap_addr = (item.get("client_snapshot") or {}).get("endereco", "")

print("client_address repr:", repr(addr))
print("snapshot endereco repr:", repr(snap_addr))
print("client_address unicode_escape:", addr.encode("unicode_escape").decode("ascii"))
print("snapshot endereco unicode_escape:", snap_addr.encode("unicode_escape").decode("ascii"))

try:
    fixed = addr.encode("latin1").decode("utf-8")
    print("manual fixed repr:", repr(fixed))
    print("manual fixed unicode_escape:", fixed.encode("unicode_escape").decode("ascii"))
except Exception as e:
    print("manual fixed error:", repr(e))
