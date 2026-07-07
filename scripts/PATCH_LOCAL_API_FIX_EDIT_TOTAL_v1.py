from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8")

# 1) Melhorar extração do nome do cliente, inclusive quando vier wrapper contato/cliente.
old = '''def _client_name_from_snapshot(snap):
    c = snap or {}
    return c.get("nome") or c.get("name") or c.get("razao_social") or ""
'''

new = '''def _client_name_from_snapshot(snap):
    c = snap or {}
    if isinstance(c, str):
        c = _from_json(c, {}) or {}
    if isinstance(c, dict) and isinstance(c.get("contato"), dict):
        c = c.get("contato") or {}
    if isinstance(c, dict) and isinstance(c.get("cliente"), dict):
        c = c.get("cliente") or {}
    if not isinstance(c, dict):
        return ""
    return (
        c.get("nome")
        or c.get("name")
        or c.get("razao_social")
        or c.get("razaoSocial")
        or c.get("fantasia")
        or ""
    )
'''
if old not in txt:
    raise SystemExit("Bloco _client_name_from_snapshot não encontrado.")
txt = txt.replace(old, new)


# 2) Adicionar campos extras no QuoteCreateIn.
old = '''class QuoteCreateIn(BaseModel):
    client_id: int
    seller_id: int
    seller_name: Optional[str] = None
    shipping_method_id: int
    freight_method_id: Optional[int] = None
    payment_method_code: str
    payment_meio: Optional[str] = None
    payment_conta: Optional[str] = None
    payment_due_date: Optional[str] = None
    payment_category: Optional[str] = None
    payment_notify: Optional[bool] = None
    freight_paid_client: Optional[float] = 0
    freight_paid_company: Optional[float] = 0
    notes: Optional[str] = None
    items: List[QuoteItemIn] = []
'''

new = '''class QuoteCreateIn(BaseModel):
    client_id: int
    seller_id: int
    seller_name: Optional[str] = None
    shipping_method_id: int
    freight_method_id: Optional[int] = None
    payment_method_code: str
    payment_meio: Optional[str] = None
    payment_conta: Optional[str] = None
    payment_due_date: Optional[str] = None
    payment_category: Optional[str] = None
    payment_notify: Optional[bool] = None
    freight_paid_client: Optional[float] = 0
    freight_paid_company: Optional[float] = 0
    notes: Optional[str] = None
    internal_notes: Optional[str] = None
    internalNotes: Optional[str] = None
    invoice_profile: Optional[str] = "A"
    items: List[QuoteItemIn] = []
'''
if old not in txt:
    raise SystemExit("Bloco QuoteCreateIn não encontrado.")
txt = txt.replace(old, new)


# 3) Melhorar retorno público da quote: total, cliente, fretes e campos do payload.
old = '''def _quote_row_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    for k in ("client_snapshot", "seller_snapshot", "totals", "payload"):
        out[k] = _from_json(out.get(k), out.get(k))
    out["client_name"] = _client_name_from_snapshot(out.get("client_snapshot") or {})
    out["sale_total_products"] = float((out.get("totals") or {}).get("items") or (out.get("totals") or {}).get("net") or 0)
    out["cost_total_products"] = 0
    out["profit_total_products"] = 0
    return out
'''

new = '''def _quote_row_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    for k in ("client_snapshot", "seller_snapshot", "totals", "payload"):
        out[k] = _from_json(out.get(k), out.get(k))

    totals = out.get("totals") or {}
    payload = out.get("payload") or {}

    total_net = _safe_float(totals.get("net"), 0)
    total_items = _safe_float(totals.get("items"), 0)
    total_final = total_net if total_net else total_items

    client_snapshot = out.get("client_snapshot") or {}
    client_name = _client_name_from_snapshot(client_snapshot)

    out["client_name"] = client_name or f"Cliente #{out.get('client_id')}"
    out["total"] = total_final
    out["net"] = total_final
    out["sale_total_products"] = total_items if total_items else total_final
    out["cost_total_products"] = 0
    out["profit_total_products"] = 0

    out["freight_paid_client"] = _safe_float(
        out.get("freight_paid_client")
        or payload.get("freight_paid_client")
        or totals.get("freight_paid_client"),
        0,
    )
    out["freight_paid_company"] = _safe_float(
        out.get("freight_paid_company")
        or payload.get("freight_paid_company")
        or totals.get("freight_paid_company"),
        0,
    )

    out["internal_notes"] = (
        out.get("internal_notes")
        or payload.get("internal_notes")
        or payload.get("internalNotes")
        or ""
    )
    out["internalNotes"] = out["internal_notes"]
    out["invoice_profile"] = str(payload.get("invoice_profile") or "A")

    # Alias úteis para reidratação do front.
    out["shipping_id"] = out.get("shipping_method_id")
    out["freight_id"] = out.get("freight_method_id")
    out["payment_code"] = out.get("payment_method_code")

    return out
'''
if old not in txt:
    raise SystemExit("Bloco _quote_row_public não encontrado.")
txt = txt.replace(old, new)


# 4) Normalizar client_raw no _build_quote_records.
old = '''    client_resp = tiny.obter_contato(payload.client_id)
    client_raw = client_resp.get("contato") or client_resp.get("cliente") or client_resp
'''

new = '''    client_resp = tiny.obter_contato(payload.client_id)
    client_raw = client_resp.get("contato") or client_resp.get("cliente") or client_resp
    if isinstance(client_raw, dict) and isinstance(client_raw.get("contato"), dict):
        client_raw = client_raw.get("contato") or {}
    if isinstance(client_raw, dict) and isinstance(client_raw.get("cliente"), dict):
        client_raw = client_raw.get("cliente") or {}
'''
if old not in txt:
    raise SystemExit("Bloco client_resp/client_raw não encontrado.")
txt = txt.replace(old, new)


# 5) Garantir payload com internal_notes e invoice_profile.
old = '''        "payload": payload.model_dump(),
    }
'''

new = '''        "payload": {
            **payload.model_dump(),
            "internal_notes": _clean_str(payload.internal_notes or payload.internalNotes),
            "internalNotes": _clean_str(payload.internal_notes or payload.internalNotes),
            "invoice_profile": str(payload.invoice_profile or "A"),
            "freight_method_id": int(payload.freight_method_id) if payload.freight_method_id else None,
            "freight_method_name": freight_name or None,
            "shipping_method_id": int(payload.shipping_method_id),
            "shipping_method_name": shipping_name,
            "client_name": _client_name_from_snapshot(client_raw),
        },
    }
'''
if old not in txt:
    raise SystemExit("Bloco payload model_dump não encontrado.")
txt = txt.replace(old, new)

path.write_text(txt, encoding="utf-8")
print("OK: local_api.py corrigido para total, cliente, frete e observação interna.")
