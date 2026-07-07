from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(r"C:\TRML_LOCAL\ERP")
path = ROOT / "backend" / "local_api.py"

ts = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = ROOT / "backups" / f"before-restore-frontend-spa-fallback-{ts}"
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(path, backup_dir / "local_api.py")

txt = path.read_text(encoding="utf-8", errors="replace")

marker = "# === FINAL FRONTEND SPA FALLBACK RESTORE ==="
if marker in txt:
    print("OK - bloco de fallback do frontend ja existe. Nada alterado.")
    print("Backup:", backup_dir)
    raise SystemExit(0)

block = r