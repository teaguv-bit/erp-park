from local_api import app

print("=== ROTAS RESET PASSWORD REGISTRADAS ===")
for i, r in enumerate(app.router.routes):
    path = getattr(r, "path", "")
    methods = ",".join(sorted(getattr(r, "methods", []) or []))
    endpoint = getattr(r, "endpoint", None)
    name = getattr(endpoint, "__name__", str(endpoint))
    if "reset-password" in path:
        print(i, methods, path, name)
