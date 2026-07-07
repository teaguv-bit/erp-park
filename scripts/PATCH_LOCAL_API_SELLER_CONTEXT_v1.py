from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8")

insert_after = '''@app.get("/api/me")
@app.get("/me")
def me():
    return {
        "email": "local@trml",
        "role": "admin",
        "is_admin": True,
        "is_allowed": True,
        "is_expedition": False,
        "can_access_quotes": True,
        "can_access_separation": True,
        "access_source": "local",
    }


'''

addition = '''@app.get("/api/seller/context")
@app.get("/seller/context")
def seller_context(company: str = "parton"):
    company_key = _company_key(company)
    return {
        "ok": True,
        "email": "local@trml",
        "is_admin": True,
        "role": "admin",
        "company": company_key,
        "company_key": company_key,
        "mapping_source": "local",
        "sellers": [],
        "seller_ids": [],
        "primary_seller": None,
    }


@app.get("/api/seller/client-wallet")
@app.get("/seller/client-wallet")
def seller_client_wallet(company: str = "parton", limit: int = 300):
    return {
        "ok": True,
        "company": _company_key(company),
        "email": "local@trml",
        "is_admin": True,
        "sellers": [],
        "seller_ids": [],
        "items": [],
        "count": 0,
        "limit": limit,
        "source": "local_empty",
    }


@app.get("/api/seller/order-wallet")
@app.get("/seller/order-wallet")
def seller_order_wallet(company: str = "parton", start_date: str = "", end_date: str = "", limit: int = 500):
    return {
        "ok": True,
        "company": _company_key(company),
        "email": "local@trml",
        "is_admin": True,
        "items": [],
        "count": 0,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        "source": "local_empty",
    }


@app.get("/api/seller/tiny-wallet-live")
@app.get("/seller/tiny-wallet-live")
def seller_tiny_wallet_live(company: str = "parton", q: str = "", page_num: int = 1):
    return {
        "ok": True,
        "company": _company_key(company),
        "items": [],
        "page_num": page_num,
        "source": "local_empty",
    }


'''

if addition.strip() not in txt:
    if insert_after not in txt:
        raise SystemExit("Bloco /api/me não encontrado para inserir seller context.")
    txt = txt.replace(insert_after, insert_after + addition)

path.write_text(txt, encoding="utf-8")
print("OK: rotas seller context locais adicionadas.")
