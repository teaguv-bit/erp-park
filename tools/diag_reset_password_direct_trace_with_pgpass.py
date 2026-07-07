import sys
import json
import asyncio
import traceback

sys.path.insert(0, r"C:\TRML_LOCAL\ERP\backend")

import local_api

class FakeRequest:
    def __init__(self, token, body):
        self.headers = {"authorization": "Bearer " + token}
        self.method = "POST"
        self._body = body

    async def json(self):
        return self._body

async def main():
    try:
        admin = local_api._auth_lookup_user_by_login("Admin")
        print("ADMIN:", bool(admin), admin.get("login") if admin else None, admin.get("role") if admin else None)

        token = local_api._auth_encode_token(admin)

        user_id = "28344317-bb83-472c-aee4-617ee6ee3113"  # Dada
        before = local_api._auth_find_user_by_id(user_id)
        print("BEFORE:", before)

        req = FakeRequest(token, {"password": "1234", "must_change_password": True})

        fn = getattr(local_api, "admin_reset_password_final", None)
        print("FUNCTION:", fn)

        resp = await fn(user_id, req)
        print("RESP:")
        print(json.dumps(resp, ensure_ascii=False, indent=2, default=str))

        after = local_api._auth_find_user_by_id(user_id)
        print("AFTER:", after)

    except Exception:
        print("=== TRACEBACK REAL ===")
        traceback.print_exc()

asyncio.run(main())
