from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

start = txt.find("# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ===")
if start < 0:
    raise SystemExit("ERRO: bloco final reset-password nao encontrado.")

txt = txt[:start].rstrip() + r'''

# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ===
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

    before_row = _auth_find_user_by_id(user_id)
    if not before_row:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

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

    if not updated:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    after_row = _auth_find_user_by_id(user_id)
    return {"ok": True, "item": _admin_user_payload(after_row or before_row)}
''' + "\n"

path.write_text(txt, encoding="utf-8")
print("OK - funcao final reset-password substituida por versao minima.")
