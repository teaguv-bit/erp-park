from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

marker = "# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ==="

if marker in txt:
    print("OK - rota final de reset-password ja existe. Nada alterado.")
else:
    block = r'''

# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ===
# Remove rotas anteriores de reset-password e registra uma versao final, simples e robusta.
# Motivo: endpoint anterior retornava 500 em producao local ao trocar senha pelo painel admin.
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
    print(f"[WARN] Falha ao limpar rotas antigas de reset-password: {e}")


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

    raw_must_change = body.get("must_change_password", False)
    if isinstance(raw_must_change, str):
        must_change_password = raw_must_change.strip().lower() in {"1", "true", "sim", "yes", "s"}
    else:
        must_change_password = bool(raw_must_change)

    before_row = _auth_find_user_by_id(user_id)
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
                    """,
                    (_auth_password_hash(new_password), must_change_password, user_id),
                )
    except Exception as e:
        print(f"[ERROR] reset-password update falhou user_id={user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Falha ao atualizar senha: {e}")

    after_row = _auth_find_user_by_id(user_id)

    try:
        _auth_audit_log(
            actor.get("login"),
            before_row.get("login"),
            "reset_password",
            _admin_user_payload(before_row),
            _admin_user_payload(after_row or before_row),
        )
    except Exception as e:
        print(f"[WARN] reset-password auditoria ignorada user_id={user_id}: {e}")

    return {
        "ok": True,
        "item": _admin_user_payload(after_row or before_row),
    }
'''
    txt = txt.rstrip() + "\n\n" + block + "\n"
    path.write_text(txt, encoding="utf-8")
    print("OK - rota final robusta de reset-password adicionada.")
