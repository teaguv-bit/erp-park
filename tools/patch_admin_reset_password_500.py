from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

def replace_function(src, name, replacement):
    start = src.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"ERRO: funcao {name} nao encontrada.")
    next_def = src.find("\ndef ", start + 1)
    next_app = src.find("\n@app.", start + 1)
    candidates = [x for x in [next_def, next_app] if x > 0]
    end = min(candidates) if candidates else len(src)
    return src[:start] + replacement.rstrip() + "\n\n" + src[end:].lstrip("\n")

new_audit = r'''
def _auth_audit_log(actor_login: str, target_login: str, action: str, before_data: Any = None, after_data: Any = None):
    """
    Auditoria administrativa não pode derrubar ações críticas como reset de senha.
    Se a tabela não existir ou houver erro de JSON, registra aviso no console e segue.
    """
    try:
        before_json = json.dumps(before_data, ensure_ascii=False, default=_json_default) if before_data is not None else None
        after_json = json.dumps(after_data, ensure_ascii=False, default=_json_default) if after_data is not None else None

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS erp.user_audit_log (
                      id BIGSERIAL PRIMARY KEY,
                      actor_login TEXT,
                      target_login TEXT,
                      action TEXT NOT NULL,
                      before_data JSONB,
                      after_data JSONB,
                      created_at TIMESTAMPTZ DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT INTO erp.user_audit_log (actor_login, target_login, action, before_data, after_data, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, now())
                    """,
                    (actor_login, target_login, action, before_json, after_json),
                )
    except Exception as e:
        print(f"[WARN] Falha ao gravar auditoria de usuario action={action}: {e}")
'''

txt = replace_function(txt, "_auth_audit_log", new_audit)

old = '''    body = await request.json() if request.method != "GET" else {}
    new_password = _clean_str(body.get("password") or body.get("new_password") or "1234")
    before_row = _auth_find_user_by_id(user_id)
'''

new = '''    body = await request.json() if request.method != "GET" else {}
    new_password = _clean_str(body.get("password") or body.get("new_password") or "1234")
    must_change_password = bool(body.get("must_change_password", True))
    before_row = _auth_find_user_by_id(user_id)
'''

if old not in txt:
    raise SystemExit("ERRO: bloco body/new_password nao encontrado no reset-password.")
txt = txt.replace(old, new, 1)

old = '''                UPDATE erp.users
                SET password_hash=%s,
                    must_change_password=TRUE,
                    updated_at=now()
                WHERE id=%s
                """,
                (_auth_password_hash(new_password), user_id),
'''

new = '''                UPDATE erp.users
                SET password_hash=%s,
                    must_change_password=%s,
                    updated_at=now()
                WHERE id=%s
                """,
                (_auth_password_hash(new_password), must_change_password, user_id),
'''

if old not in txt:
    raise SystemExit("ERRO: bloco UPDATE reset-password nao encontrado.")
txt = txt.replace(old, new, 1)

path.write_text(txt, encoding="utf-8")
print("OK - reset-password admin corrigido para nao cair por auditoria e respeitar must_change_password.")
