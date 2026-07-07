from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

marker = "# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ==="
insert_marker = "if os.path.isdir(FRONTEND_DIST):"

# Remove any existing final override block from marker to end, because prior attempts appended it after SPA fallback.
idx = txt.find(marker)
if idx >= 0:
    txt = txt[:idx].rstrip() + "\n"

insert_at = txt.find(insert_marker)
if insert_at < 0:
    raise SystemExit("ERRO: nao encontrei o bloco if os.path.isdir(FRONTEND_DIST).")

block = """
# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ===
# IMPORTANTE: este bloco precisa ficar ANTES do SPA fallback "/{full_path:path}".
# Se ficar depois do fallback, /api/admin/users/.../reset-password pode cair no fallback.
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

    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    \"\"\"
                    UPDATE erp.users
                    SET password_hash=%s,
                        must_change_password=%s,
                        updated_at=now()
                    WHERE id=%s
                    RETURNING id
                    \"\"\",
                    (_auth_password_hash(new_password), must_change_password, user_id),
                )
                updated = cur.fetchone()
    except Exception as e:
        print(f"[ERROR] reset-password update falhou user_id={user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Falha ao atualizar senha: {e}")

    if not updated:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    after_row = _auth_find_user_by_id(user_id)
    return {"ok": True, "item": _admin_user_payload(after_row or before_row)}


"""

txt = txt[:insert_at] + block + txt[insert_at:]
path.write_text(txt, encoding="utf-8")
print("OK - reset-password final movido para antes do SPA fallback e reescrito limpo.")
print(path)
