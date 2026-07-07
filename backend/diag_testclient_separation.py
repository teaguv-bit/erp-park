import os

from fastapi.testclient import TestClient
from local_api import app

client = TestClient(app)

login = client.post("/api/auth/login", json={
    "login": os.getenv("ERP_DIAG_LOGIN", "Admin"),
    "password": os.getenv("ERP_DIAG_PASSWORD", ""),
})
print("LOGIN:", login.status_code, login.text[:300])

token = login.json().get("token")
headers = {"Authorization": f"Bearer {token}"} if token else {}

resp = client.get("/api/separation/orders?company=parton&limit=5", headers=headers)
print("SEPARATION:", resp.status_code)
print(resp.text[:2000])

resp2 = client.get("/api/separation/orders/23999?company=parton", headers=headers)
print("DETAIL 23999:", resp2.status_code)
print(resp2.text[:2000])
