from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8")

# =====================================================
# 1) Adiciona helper de filtro de vendedores por empresa
# =====================================================
if "def _seller_allowed_for_company(" not in txt:
    marker = "def _normalize_payment_code(code: Optional[str]) -> str:"
    helper = r'''
def _seller_allowed_for_company(company_key: str, seller_name: str) -> bool:
    name = str(seller_name or "").strip().lower()

    if company_key == "parton":
        # Suprimentos não deve mostrar vendedores de Informática
        if "informática" in name or "informatica" in name:
            return False
        return True

    if company_key == "park":
        # Informática não deve mostrar vendedores de Suprimentos
        if "suprimento" in name or "suprimentos" in name or "parton" in name:
            return False
        return True

    return True


'''
    if marker not in txt:
        raise SystemExit("Marcador _normalize_payment_code não encontrado.")
    txt = txt.replace(marker, helper + marker)

# =====================================================
# 2) Garante aliases de total e cliente no retorno público
#    Mesmo se já existir uma versão anterior, reforça antes do return.
# =====================================================
pattern = r'def _quote_row_public\(row: Dict\[str, Any\]\) -> Dict\[str, Any\]:.*?    return out\n'
m = re.search(pattern, txt, flags=re.S)
if not m:
    raise SystemExit("Função _quote_row_public não encontrada.")

new_func = r'''def _quote_row_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    for k in ("client_snapshot", "seller_snapshot", "totals", "payload"):
        out[k] = _from_json(out.get(k), out.get(k))

    totals = out.get("totals") or {}
    payload = out.get("payload") or {}

    total_net = _safe_float(totals.get("net"), 0)
    total_items = _safe_float(totals.get("items"), 0)
    total_from_payload = _safe_float(
        payload.get("total")
        or payload.get("total_net")
        or payload.get("total_amount")
        or payload.get("total_items"),
        0,
    )

    total_final = total_net or total_items or total_from_payload

    client_snapshot = out.get("client_snapshot") or {}
    client_name = _client_name_from_snapshot(client_snapshot)

    out["client_name"] = client_name or payload.get("client_name") or f"Cliente #{out.get('client_id')}"
    out["cliente_nome"] = out["client_name"]
    out["customer_name"] = out["client_name"]

    # Aliases para telas antigas, operações e impressão
    out["total"] = total_final
    out["total_net"] = total_final
    out["total_amount"] = total_final
    out["amount_total"] = total_final
    out["valor_total"] = total_final
    out["net"] = total_final

    out["sale_total_products"] = total_items or total_final
    out["items_total"] = total_items or total_final
    out["cost_total_products"] = _safe_float(out.get("cost_total_products"), 0)
    out["profit_total_products"] = _safe_float(out.get("profit_total_products"), 0)

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
    out["invoice_profile"] = str(payload.get("invoice_profile") or out.get("invoice_profile") or "A")

    # Aliases úteis para reidratação do front
    out["shipping_id"] = out.get("shipping_method_id")
    out["shipping_name"] = out.get("shipping_method_name")
    out["freight_id"] = out.get("freight_method_id")
    out["freight_name"] = out.get("freight_method_name")
    out["payment_code"] = out.get("payment_method_code")

    # Também reforça no payload para o editor antigo
    if isinstance(payload, dict):
        payload.setdefault("client_name", out["client_name"])
        payload.setdefault("total", total_final)
        payload.setdefault("total_net", total_final)
        payload.setdefault("freight_method_id", out.get("freight_method_id"))
        payload.setdefault("freight_method_name", out.get("freight_method_name"))
        payload.setdefault("shipping_method_id", out.get("shipping_method_id"))
        payload.setdefault("shipping_method_name", out.get("shipping_method_name"))
        payload.setdefault("internal_notes", out.get("internal_notes") or "")
        payload.setdefault("internalNotes", out.get("internal_notes") or "")
        payload.setdefault("invoice_profile", out.get("invoice_profile") or "A")
        out["payload"] = payload

    return out
'''
txt = txt[:m.start()] + new_func + txt[m.end():]

# =====================================================
# 3) Filtra vendedores em tiny_vendors
# =====================================================
old = '''def tiny_vendors(company: str = "parton", q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    tiny = _tiny_for_company(company)
    if not q or len(q.strip()) < 2:
        return {"ok": True, "items": [], "page": page}
'''
new = '''def tiny_vendors(company: str = "parton", q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    company_key = _company_key(company)
    tiny = _tiny_for_company(company_key)
    if not q or len(q.strip()) < 2:
        return {"ok": True, "items": [], "page": page}
'''
if old not in txt:
    raise SystemExit("Cabeçalho de tiny_vendors não encontrado.")
txt = txt.replace(old, new)

old_block = '''            items.append({
                "id": _safe_int(v.get("id")),
                "seller_id": _safe_int(v.get("id")),
                "nome": v.get("nome") or "",
                "seller_name": v.get("nome") or "",
                "codigo": v.get("codigo") or "",
                "raw": v,
            })
'''
new_block = '''            seller_name = v.get("nome") or ""
            if not _seller_allowed_for_company(company_key, seller_name):
                continue

            items.append({
                "id": _safe_int(v.get("id")),
                "seller_id": _safe_int(v.get("id")),
                "nome": seller_name,
                "seller_name": seller_name,
                "codigo": v.get("codigo") or "",
                "raw": v,
            })
'''
if old_block not in txt:
    raise SystemExit("Bloco items.append de tiny_vendors não encontrado.")
txt = txt.replace(old_block, new_block)

path.write_text(txt, encoding="utf-8")
print("OK: total/aliases e filtro de vendedores por empresa aplicados.")
