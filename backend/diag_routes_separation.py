from local_api import app

print("=== ROTAS SEPARATION REGISTRADAS ===")
for r in app.routes:
    path = getattr(r, "path", "")
    methods = ",".join(sorted(getattr(r, "methods", []) or []))
    if "separation" in path.lower():
        print(methods, path)

print("\n=== ROTAS CATCH/FALLBACK POSSÍVEIS ===")
for r in app.routes:
    path = getattr(r, "path", "")
    methods = ",".join(sorted(getattr(r, "methods", []) or []))
    if "{full_path" in path or "{path" in path or path in ["/{full_path:path}", "/api/{full_path:path}"]:
        print(methods, path)
