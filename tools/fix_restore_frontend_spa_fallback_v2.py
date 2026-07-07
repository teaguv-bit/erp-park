from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(r"C:\TRML_LOCAL\ERP")
path = ROOT / "backend" / "local_api.py"

ts = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = ROOT / "backups" / f"before-restore-frontend-spa-fallback-v2-{ts}"
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(path, backup_dir / "local_api.py")

txt = path.read_text(encoding="utf-8", errors="replace")

marker = "# === FINAL FRONTEND SPA FALLBACK RESTORE V2 ==="

if marker in txt:
    print("OK - fallback V2 ja existe. Nada alterado.")
    print("Backup:", backup_dir)
    raise SystemExit(0)

block = '''
# === FINAL FRONTEND SPA FALLBACK RESTORE V2 ===
# Restaura o frontend React/Vite servido pelo FastAPI local.
# Deve ficar no final do arquivo, depois das rotas de API.
try:
    _trml_frontend_dist = FRONTEND_DIST if "FRONTEND_DIST" in globals() else os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
    _trml_frontend_index = os.path.join(_trml_frontend_dist, "index.html")
    _trml_frontend_assets = os.path.join(_trml_frontend_dist, "assets")

    if os.path.isdir(_trml_frontend_assets):
        _has_assets_mount = any(getattr(r, "path", "") == "/assets" for r in app.router.routes)
        if not _has_assets_mount:
            app.mount("/assets", StaticFiles(directory=_trml_frontend_assets), name="assets")

    if os.path.isfile(_trml_frontend_index):
        @app.get("/")
        def trml_frontend_index_final():
            return FileResponse(_trml_frontend_index)

        @app.get("/{full_path:path}")
        def trml_frontend_spa_fallback_final(full_path: str):
            p = str(full_path or "")
            if p.startswith((
                "api/",
                "tiny/",
                "quotes/",
                "clients/",
                "admin/",
                "company/",
                "seller/",
                "separation/",
                "ops/",
            )):
                raise HTTPException(status_code=404, detail="Rota não encontrada.")
            return FileResponse(_trml_frontend_index)
    else:
        print(f"[WARN] Frontend index.html nao encontrado em: {_trml_frontend_index}")
except Exception as e:
    print(f"[WARN] Falha ao restaurar fallback do frontend: {e}")
'''

txt = txt.rstrip() + "\n\n" + block + "\n"
path.write_text(txt, encoding="utf-8")

print("OK - fallback do frontend restaurado no final do local_api.py.")
print("Backup:", backup_dir)
print("Arquivo:", path)
