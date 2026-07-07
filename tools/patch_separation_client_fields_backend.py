from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

helper_marker = '''
def _normalize_ops_tiny_status(v: str) -> str:
'''

helper_code = r'''
def _client_dict_from_snapshot(snap):
    c = snap or {}
    if isinstance(c, str):
        c = _from_json(c, {}) or {}
    if isinstance(c, dict) and isinstance(c.get("contato"), dict):
        c = c.get("contato") or {}
    if isinstance(c, dict) and isinstance(c.get("cliente"), dict):
        c = c.get("cliente") or {}
    return c if isinstance(c, dict) else {}


def _client_first_value_from_snapshot(snap, *keys):
    c = _client_dict_from_snapshot(snap)
    for key in keys:
        value = _clean_str(c.get(key))
        if value:
            return value
    return ""


def _client_address_from_snapshot(snap):
    c = _client_dict_from_snapshot(snap)
    endereco = _clean_str(c.get("endereco") or c.get("logradouro"))
    numero = _clean_str(c.get("numero"))
    complemento = _clean_str(c.get("complemento"))
    bairro = _clean_str(c.get("bairro"))
    cidade = _clean_str(c.get("cidade"))
    uf = _clean_str(c.get("uf"))
    cep = _clean_str(c.get("cep"))

    parts = []
    line1 = endereco
    if numero:
        line1 = (line1 + ", " + numero).strip(", ")
    if complemento:
        line1 = (line1 + " - " + complemento).strip(" -")
    if line1:
        parts.append(line1)
    if bairro:
        parts.append(bairro)

    city_uf = cidade
    if uf:
        city_uf = (city_uf + "/" + uf).strip("/")
    if city_uf:
        parts.append(city_uf)

    if cep:
        parts.append("CEP " + cep)

    return " - ".join([p for p in parts if p])

'''

if "_client_dict_from_snapshot" not in txt:
    if helper_marker not in txt:
        raise SystemExit("ERRO: marcador para inserir helpers nao encontrado.")
    txt = txt.replace(helper_marker, helper_code + "\n\n" + helper_marker, 1)

old_block = '''    seller_name = (
        _clean_str(row.get("seller_name"))
        or _clean_str((seller_snapshot or {}).get("name"))
        or _clean_str((seller_snapshot or {}).get("nome"))
    )

    created_at = row.get("created_at")
'''

new_block = '''    seller_name = (
        _clean_str(row.get("seller_name"))
        or _clean_str((seller_snapshot or {}).get("name"))
        or _clean_str((seller_snapshot or {}).get("nome"))
    )

    client_document = _client_first_value_from_snapshot(
        client_snapshot,
        "cpf_cnpj",
        "cpfCnpj",
        "cpf",
        "cnpj",
        "documento",
    )
    client_phone = _client_first_value_from_snapshot(
        client_snapshot,
        "fone",
        "telefone",
        "celular",
        "phone",
    )
    client_email = _client_first_value_from_snapshot(
        client_snapshot,
        "email",
        "email_nfe",
        "emailNfe",
    )
    client_address = _client_address_from_snapshot(client_snapshot)

    created_at = row.get("created_at")
'''

if old_block not in txt:
    raise SystemExit("ERRO: bloco seller_name/created_at nao encontrado.")
txt = txt.replace(old_block, new_block, 1)

old_out = '''        "client_name": client_name,
        "seller_name": seller_name,
'''

new_out = '''        "client_name": client_name,
        "client_document": client_document,
        "client_phone": client_phone,
        "client_email": client_email,
        "client_address": client_address,
        "client_snapshot": client_snapshot,
        "seller_name": seller_name,
'''

if old_out not in txt:
    raise SystemExit("ERRO: bloco client_name no out nao encontrado.")
txt = txt.replace(old_out, new_out, 1)

path.write_text(txt, encoding="utf-8")
print("OK - campos de cliente adicionados ao retorno da Separacao")
