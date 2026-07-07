import sys
import traceback

backend = r"C:\TRML_LOCAL\ERP\backend"
if backend not in sys.path:
    sys.path.insert(0, backend)

try:
    import api
    app = getattr(api, "app", None)
    print("IMPORT_OK=", bool(app))
    if app:
        print("ROUTES_COUNT=", len(getattr(app, "routes", [])))
        for r in getattr(app, "routes", [])[:60]:
            print("ROUTE=", getattr(r, "path", ""), getattr(r, "methods", ""))
except Exception:
    print("IMPORT_ERROR")
    traceback.print_exc()
