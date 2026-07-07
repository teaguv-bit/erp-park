from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

old_anchor = '''    tiny_order_id = quote.get("tiny_order_id")
    tiny_order_number = quote.get("tiny_order_number")

    if tiny_order_id:
'''

new_anchor = '''    tiny_order_id = quote.get("tiny_order_id")
    tiny_order_number = quote.get("tiny_order_number")

    now_approved = _now()
    payload_saved = _from_json(quote.get("payload"), {}) or {}
    if not isinstance(payload_saved, dict):
        payload_saved = {}
    payload_saved["approved_at"] = now_approved.isoformat()

    if tiny_order_id:
'''

if old_anchor not in txt:
    raise SystemExit("ERRO: bloco tiny_order_id/tiny_order_number nao encontrado.")
txt = txt.replace(old_anchor, new_anchor, 1)

old_update_with_tiny = '''                    UPDATE erp.quotes
                    SET internal_status='Aprovado',
                        status='ordered',
                        updated_at=now()
                    WHERE quote_id=%s AND company_key=%s
                    """,
                    (quote_id, company_key),
'''

new_update_with_tiny = '''                    UPDATE erp.quotes
                    SET internal_status='Aprovado',
                        status='ordered',
                        payload=%s,
                        updated_at=%s
                    WHERE quote_id=%s AND company_key=%s
                    """,
                    (psycopg2.extras.Json(payload_saved), now_approved, quote_id, company_key),
'''

if old_update_with_tiny not in txt:
    raise SystemExit("ERRO: bloco UPDATE com tiny_order_id nao encontrado.")
txt = txt.replace(old_update_with_tiny, new_update_with_tiny, 1)

old_update_without_tiny = '''                    UPDATE erp.quotes
                    SET internal_status='Aprovado',
                        updated_at=now()
                    WHERE quote_id=%s AND company_key=%s
                    """,
                    (quote_id, company_key),
'''

new_update_without_tiny = '''                    UPDATE erp.quotes
                    SET internal_status='Aprovado',
                        payload=%s,
                        updated_at=%s
                    WHERE quote_id=%s AND company_key=%s
                    """,
                    (psycopg2.extras.Json(payload_saved), now_approved, quote_id, company_key),
'''

if old_update_without_tiny not in txt:
    raise SystemExit("ERRO: bloco UPDATE sem tiny_order_id nao encontrado.")
txt = txt.replace(old_update_without_tiny, new_update_without_tiny, 1)

path.write_text(txt, encoding="utf-8")
print("OK - approved_at agora sera salvo no payload ao aprovar pedido.")
