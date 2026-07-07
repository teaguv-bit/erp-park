from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

marker = '''
def _client_dict_from_snapshot(snap):
'''

helper = r'''
def _fix_mojibake_text(value):
    s = _clean_str(value)
    if not s:
        return ""
    try:
        # Fix common UTF-8 text incorrectly decoded/stored as latin1.
        # Example: Ros\xc3\xa1rio displayed as RosÃ¡rio.
        if ("\u00c3" in s) or ("\u00c2" in s) or ("\u00e2\u20ac" in s):
            fixed = s.encode("latin1").decode("utf-8")
            if fixed:
                return fixed
    except Exception:
        pass
    return s


'''

if "_fix_mojibake_text" not in txt:
    if marker not in txt:
        raise SystemExit("ERRO: marcador _client_dict_from_snapshot nao encontrado.")
    txt = txt.replace(marker, helper + marker, 1)

txt = txt.replace(
'''        value = _clean_str(c.get(key))
        if value:
            return value
''',
'''        value = _fix_mojibake_text(c.get(key))
        if value:
            return value
''',
1
)

old_address = '''    endereco = _clean_str(c.get("endereco") or c.get("logradouro"))
    numero = _clean_str(c.get("numero"))
    complemento = _clean_str(c.get("complemento"))
    bairro = _clean_str(c.get("bairro"))
    cidade = _clean_str(c.get("cidade"))
    uf = _clean_str(c.get("uf"))
    cep = _clean_str(c.get("cep"))
'''

new_address = '''    endereco = _fix_mojibake_text(c.get("endereco") or c.get("logradouro"))
    numero = _fix_mojibake_text(c.get("numero"))
    complemento = _fix_mojibake_text(c.get("complemento"))
    bairro = _fix_mojibake_text(c.get("bairro"))
    cidade = _fix_mojibake_text(c.get("cidade"))
    uf = _fix_mojibake_text(c.get("uf"))
    cep = _fix_mojibake_text(c.get("cep"))
'''

if old_address not in txt:
    raise SystemExit("ERRO: bloco de endereco nao encontrado.")
txt = txt.replace(old_address, new_address, 1)

path.write_text(txt, encoding="utf-8")
print("OK - fix mojibake backend aplicado")
