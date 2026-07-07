from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

# 1) A listagem de separação precisa selecionar o payload da quote.
old_select = '''        q.internal_status,
        q.client_snapshot,
        q.seller_name,
'''
new_select = '''        q.internal_status,
        q.payload,
        q.client_snapshot,
        q.seller_name,
'''

if old_select not in txt:
    raise SystemExit("ERRO: bloco SELECT q.internal_status/q.client_snapshot nao encontrado.")
txt = txt.replace(old_select, new_select, 1)

# 2) A linha da separação precisa expor approved_at para o frontend.
old_row = '''    client_snapshot = _from_json(row.get("client_snapshot"), {}) or {}
    seller_snapshot = _from_json(row.get("seller_snapshot"), {}) or {}
'''
new_row = '''    payload = _from_json(row.get("payload"), {}) or {}
    if not isinstance(payload, dict):
        payload = {}
    approved_at = payload.get("approved_at") or payload.get("approvedAt")

    client_snapshot = _from_json(row.get("client_snapshot"), {}) or {}
    seller_snapshot = _from_json(row.get("seller_snapshot"), {}) or {}
'''

if old_row not in txt:
    raise SystemExit("ERRO: bloco client_snapshot/seller_snapshot nao encontrado.")
txt = txt.replace(old_row, new_row, 1)

old_out = '''        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "separation_status": separation_status,
'''
new_out = '''        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "approved_at": approved_at,
        "approvedAt": approved_at,
        "payload": payload,
        "separation_status": separation_status,
'''

if old_out not in txt:
    raise SystemExit("ERRO: bloco updated_at/separation_status nao encontrado.")
txt = txt.replace(old_out, new_out, 1)

path.write_text(txt, encoding="utf-8")
print("OK - API de separacao agora devolve approved_at e payload.")
