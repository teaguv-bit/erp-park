from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

marker = "# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ==="
insert_marker = "if os.path.isdir(FRONTEND_DIST):"

idx = txt.find(marker)
if idx >= 0:
    txt = txt[:idx].rstrip() + "\n"

insert_at = txt.find(insert_marker)
if insert_at < 0:
    raise SystemExit("ERRO: nao encontrei o bloco if os.path.isdir(FRONTEND_DIST).")

block = """
# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ===
# Versao independente de _auth_find_user_by_id para evitar 500 por helper ausente.
# Deve ficar ANTES do SPA fallback.
try:
    _RESET_PASSWORD_PATHS = {
        "/api/admin/users/{user_id}/reset-password",
        "/admin/users/{user_id}/reset-password",
    }
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", "") not in _RESET_PASSWORD_PATHS
    ]
except Exception as e:
    print(f"[WARN] reset-password prune falhou: {e}")


def _admin_user_payload_direct(row, companies=None):
    role = _clean_str(row.get("role")).lower()
    companies = companies or []
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    return {
        "id": str(row.get("id")),
        "login": row.get("login"),
        "display_name": row.get("display_name"),
        "role": role,
        "companies": companies,
        "active": bool(row.get("active")),
        "must_change_password": bool(row.get("must_change_password")),
        "is_admin": role == "admin",
        "is_vendedor": role == "vendedor",
        "is_separacao": role == "separacao",
        "can_access_quotes": role in {"admin", "vendedor"},
        "can_access_separation": role in {"admin", "separacao"},
        "email": row.get("login"),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


def _admin_get_user_direct(user_id):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, login, display_name, role, active, must_change_password, created_at, updated_at
                FROM erp.users
                WHERE id=%s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None, []
            row = dict(row)
            cur.execute(
                """
                SELECT company_key
                FROM erp.user_companies
                WHERE user_id=%s
                ORDER BY company_key
                """,
                (user_id,),
            )
            companies = [r.get("company_key") for r in cur.fetchall()]
            return row, companies


@app.post("/api/admin/users/{user_id}/reset-password")
@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password_final(user_id: str, request: Request):
    actor = _require_auth_user(request)
    if _clean_str(actor.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    new_password = _clean_str(body.get("password") or body.get("new_password") or "")
    if not new_password:
        raise HTTPException(status_code=400, detail="Senha obrigatoria.")

    raw = body.get("must_change_password", False)
    if isinstance(raw, str):
        must_change_password = raw.strip().lower() in {"1", "true", "sim", "yes", "s"}
    else:
        must_change_password = bool(raw)

    before_row, companies = _admin_get_user_direct(user_id)
    if not before_row:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE erp.users
                    SET password_hash=%s,
                        must_change_password=%s,
                        updated_at=now()
                    WHERE id=%s
                    RETURNING id
                    """,
                    (_auth_password_hash(new_password), must_change_password, user_id),
                )
                updated = cur.fetchone()
    except Exception as e:
        print(f"[ERROR] reset-password update falhou user_id={user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Falha ao atualizar senha: {e}")

    if not updated:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    after_row, companies = _admin_get_user_direct(user_id)
    return {"ok": True, "item": _admin_user_payload_direct(after_row or before_row, companies)}


"""

txt = txt[:insert_at] + block + txt[insert_at:]
path.write_text(txt, encoding="utf-8")
print("OK - reset-password final reescrito sem depender de _auth_find_user_by_id.")
print(path)
