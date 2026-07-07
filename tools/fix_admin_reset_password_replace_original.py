from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(r"C:\TRML_LOCAL\ERP")
path = ROOT / "backend" / "local_api.py"

ts = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = ROOT / "backups" / f"before-replace-admin-reset-password-body-{ts}"
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(path, backup_dir / "local_api.py")

txt = path.read_text(encoding="utf-8", errors="replace")

start = txt.find("async def admin_reset_password(user_id: str, request: Request):")
if start < 0:
    raise SystemExit("ERRO: nao encontrei a funcao async def admin_reset_password.")

end_candidates = []
for marker in [
    '\n\n@app.post("/api/admin/users/{user_id}/set-companies")',
    '\n\n@app.delete("/api/admin/users/{email}")',
    '\n\n@app.post("/api/admin/companies")',
]:
    idx = txt.find(marker, start)
    if idx > start:
        end_candidates.append(idx)

if not end_candidates:
    raise SystemExit("ERRO: nao encontrei o fim da funcao admin_reset_password.")

end = min(end_candidates)

new_func = 'async def admin_reset_password(user_id: str, request: Request):\n    actor = _require_auth_user(request)\n    if _clean_str(actor.get("role")).lower() != "admin":\n        raise HTTPException(status_code=403, detail="Apenas admin.")\n\n    try:\n        body = await request.json()\n        if not isinstance(body, dict):\n            body = {}\n    except Exception:\n        body = {}\n\n    new_password = _clean_str(body.get("password") or body.get("new_password") or "")\n    if not new_password:\n        raise HTTPException(status_code=400, detail="Senha obrigatoria.")\n\n    raw = body.get("must_change_password", False)\n    if isinstance(raw, str):\n        must_change_password = raw.strip().lower() in {"1", "true", "sim", "yes", "s"}\n    else:\n        must_change_password = bool(raw)\n\n    with _db() as conn:\n        with conn.cursor() as cur:\n            cur.execute(\n                """\n                SELECT id, login, display_name, role, active, must_change_password, created_at, updated_at\n                FROM erp.users\n                WHERE id=%s\n                LIMIT 1\n                """,\n                (user_id,),\n            )\n            before_row = cur.fetchone()\n\n    if not before_row:\n        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")\n\n    before_row = dict(before_row)\n\n    with _db() as conn:\n        with conn.cursor() as cur:\n            cur.execute(\n                """\n                UPDATE erp.users\n                SET password_hash=%s,\n                    must_change_password=%s,\n                    updated_at=now()\n                WHERE id=%s\n                RETURNING id\n                """,\n                (_auth_password_hash(new_password), must_change_password, user_id),\n            )\n            updated = cur.fetchone()\n\n    if not updated:\n        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")\n\n    with _db() as conn:\n        with conn.cursor() as cur:\n            cur.execute(\n                """\n                SELECT id, login, display_name, role, active, must_change_password, created_at, updated_at\n                FROM erp.users\n                WHERE id=%s\n                LIMIT 1\n                """,\n                (user_id,),\n            )\n            after_row = cur.fetchone()\n\n            cur.execute(\n                """\n                SELECT company_key\n                FROM erp.user_companies\n                WHERE user_id=%s\n                ORDER BY company_key\n                """,\n                (user_id,),\n            )\n            companies = [r.get("company_key") for r in cur.fetchall()]\n\n    after_row = dict(after_row or before_row)\n    role = _clean_str(after_row.get("role")).lower()\n    item = {\n        "id": str(after_row.get("id")),\n        "login": after_row.get("login"),\n        "display_name": after_row.get("display_name"),\n        "role": role,\n        "companies": companies,\n        "active": bool(after_row.get("active")),\n        "must_change_password": bool(after_row.get("must_change_password")),\n        "is_admin": role == "admin",\n        "is_vendedor": role == "vendedor",\n        "is_separacao": role == "separacao",\n        "can_access_quotes": role in {"admin", "vendedor"},\n        "can_access_separation": role in {"admin", "separacao"},\n        "email": after_row.get("login"),\n        "created_at": after_row.get("created_at").isoformat() if hasattr(after_row.get("created_at"), "isoformat") else after_row.get("created_at"),\n        "updated_at": after_row.get("updated_at").isoformat() if hasattr(after_row.get("updated_at"), "isoformat") else after_row.get("updated_at"),\n    }\n\n    return {"ok": True, "item": item}\n'

txt2 = txt[:start] + new_func + txt[end:]

# Remove bloco final quebrado, se existir, para evitar duplicidade.
final_marker = "# === FINAL ADMIN RESET PASSWORD ROUTE - SAFE OVERRIDE ==="
idx = txt2.find(final_marker)
if idx >= 0:
    txt2 = txt2[:idx].rstrip() + "\n"

path.write_text(txt2, encoding="utf-8")
print("OK - corpo da funcao admin_reset_password substituido com versao robusta.")
print("Backup:", backup_dir)
print("Arquivo:", path)
