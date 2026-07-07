import os
import json
import uuid
import threading
import time
import datetime as dt
import unicodedata
import hashlib
import hmac
import secrets
import base64
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import requests
import jwt
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tiny_client import TinyClient, TinyConfig, TinyAPIError, TinyV3Client, TinyV3Config

load_dotenv()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIST = os.path.join(APP_ROOT, "frontend", "dist")

DB_HOST = os.getenv("PGHOST", "127.0.0.1")
DB_PORT = int(os.getenv("PGPORT", "5432"))
DB_NAME = os.getenv("PGDATABASE", "trml_erp")
DB_USER = os.getenv("PGUSER", "postgres")
DB_PASS = os.getenv("PGPASSWORD", "")

MAX_DISCOUNT_PCT = float(os.getenv("MAX_DISCOUNT_PCT", "35"))
ENABLE_TINY_STATUS_SYNC_LOCAL = str(os.getenv("ENABLE_TINY_STATUS_SYNC_LOCAL", "true")).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
# Capability master-switch da etapa de Conferência da separação (foto + conferência).
# OFF por padrão: o frontend coage HARD para 'off' enquanto me().features.conferencia != true.
ENABLE_SEP_CONFERENCIA = str(os.getenv("ENABLE_SEP_CONFERENCIA", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
    "sim",
}
AUTH_JWT_SECRET = os.getenv("ERP_LOCAL_AUTH_JWT_SECRET", "trml-local-dev-secret-change-me")
AUTH_JWT_ALG = "HS256"
AUTH_TOKEN_TTL_HOURS = int(os.getenv("ERP_LOCAL_AUTH_TOKEN_TTL_HOURS", "12"))
PBKDF2_ITERATIONS = int(os.getenv("ERP_LOCAL_AUTH_PBKDF2_ITERATIONS", "210000"))
CLIENT_WALLET_DAILY_SYNC_TZ = ZoneInfo("America/Sao_Paulo")
CLIENT_WALLET_DAILY_SYNC_COMPANIES = ("parton", "park")
CLIENT_WALLET_DAILY_SYNC_HOUR = 8
CLIENT_WALLET_DAILY_SYNC_MINUTE = 0
CLIENT_WALLET_AUX_CACHE_TTL_SECONDS = 30
_CLIENT_WALLET_AUX_CACHE: Dict[str, Any] = {}

app = FastAPI(title="TRML ERP Local API", version="1.0.0-local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _client_wallet_cache_get(key: str):
    cached = _CLIENT_WALLET_AUX_CACHE.get(key)
    if not cached:
        return None
    expires_at, value = cached
    if time.time() >= expires_at:
        _CLIENT_WALLET_AUX_CACHE.pop(key, None)
        return None
    return value


def _client_wallet_cache_set(key: str, value: Any, ttl: int = CLIENT_WALLET_AUX_CACHE_TTL_SECONDS):
    _CLIENT_WALLET_AUX_CACHE[key] = (time.time() + ttl, value)
    return value


def _client_wallet_cache_clear():
    _CLIENT_WALLET_AUX_CACHE.clear()


def _to_jsonb(value):
    return json.dumps(value or {}, ensure_ascii=False, default=_json_default)


def _from_json(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _db():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _company_key(company: str = "parton") -> str:
    c = str(company or "parton").strip().lower()
    aliases = {
        "suprimentos": "parton",
        "suprimento": "parton",
        "parton": "parton",
        "informatica": "park",
        "informática": "park",
        "park": "park",
    }
    return aliases.get(c, c or "parton")


def _seed_companies():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.companies (company_key, company_name, tiny_base_url, active)
                VALUES
                  ('parton', 'Suprimentos / Parton', 'https://api.tiny.com.br/api2', TRUE),
                  ('park', 'Informática / Park', 'https://api.tiny.com.br/api2', TRUE)
                ON CONFLICT (company_key) DO UPDATE SET
                  company_name = EXCLUDED.company_name,
                  tiny_base_url = COALESCE(erp.companies.tiny_base_url, EXCLUDED.tiny_base_url),
                  active = TRUE,
                  updated_at = now()
                """
            )


def _company_row(company: str = "parton") -> Dict[str, Any]:
    key = _company_key(company)
    _seed_companies()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.companies WHERE company_key=%s LIMIT 1", (key,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Empresa não encontrada: {key}")
    return dict(row)


def _auth_password_hash(password: str, salt_hex: Optional[str] = None) -> str:
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_hex}${digest}"


def _auth_password_verify(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations, salt_hex, digest = str(stored_hash or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        expected = _auth_password_hash(password, salt_hex)
        return hmac.compare_digest(expected, f"{algo}${iterations}${salt_hex}${digest}")
    except Exception:
        return False


def _auth_user_companies(user_id: Any) -> List[str]:
    if not user_id:
        return []
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT company_key
                FROM erp.user_companies
                WHERE user_id = %s
                ORDER BY company_key
                """,
                (str(user_id),),
            )
            rows = cur.fetchall()
    companies: List[str] = []
    for row in rows:
        company_key = _company_key(row.get("company_key"))
        if company_key and company_key not in companies:
            companies.append(company_key)
    return companies


def _auth_public_user_row(user: Dict[str, Any]) -> Dict[str, Any]:
    companies = _auth_user_companies(user.get("id"))
    role = _clean_str(user.get("role")).lower()
    is_admin = role == "admin"
    is_separacao = role == "separacao"
    is_vendedor = role == "vendedor"
    return {
        "id": str(user.get("id")),
        "login": user.get("login"),
        "display_name": user.get("display_name"),
        "role": role,
        "companies": companies,
        "active": bool(user.get("active")),
        "must_change_password": bool(user.get("must_change_password")),
        "is_admin": is_admin,
        "is_vendedor": is_vendedor,
        "is_separacao": is_separacao,
        "can_access_quotes": is_admin or is_vendedor,
        "can_access_separation": is_admin or is_separacao,
        "seller_links": _auth_user_seller_links(user.get("id")),
        "email": user.get("login"),
        "features": {
            "conferencia": _sep_conferencia_enabled(),
            "conferencia_mode": _sep_conferencia_mode(),
        },
    }


def _auth_encode_token(user: Dict[str, Any]) -> str:
    payload = {
        "sub": str(user.get("id")),
        "login": user.get("login"),
        "role": _clean_str(user.get("role")).lower(),
        "display_name": user.get("display_name"),
        "companies": _auth_user_companies(user.get("id")),
        "iat": int(_now().timestamp()),
        "exp": int((_now() + dt.timedelta(hours=AUTH_TOKEN_TTL_HOURS)).timestamp()),
    }
    token = jwt.encode(payload, AUTH_JWT_SECRET, algorithm=AUTH_JWT_ALG)
    return token.decode("utf-8") if isinstance(token, bytes) else str(token)


def _auth_decode_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, AUTH_JWT_SECRET, algorithms=[AUTH_JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado.")
    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Token inválido.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.users WHERE id=%s LIMIT 1", (user_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Usuário não encontrado.")

    user = dict(row)
    if not bool(user.get("active", True)):
        raise HTTPException(status_code=401, detail="Usuário inativo.")
    return user


def _auth_user_from_request(request: Request) -> Optional[Dict[str, Any]]:
    user = getattr(request.state, "auth_user", None)
    if user:
        return user
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None
    user = _auth_decode_token(token)
    request.state.auth_user = user
    return user


def _require_auth_user(request: Request) -> Dict[str, Any]:
    user = _auth_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return user


def _auth_lookup_user_by_login(login: str) -> Optional[Dict[str, Any]]:
    login_norm = _clean_str(login)
    if not login_norm:
        return None
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.users WHERE LOWER(login)=LOWER(%s) LIMIT 1", (login_norm,))
            row = cur.fetchone()
    return dict(row) if row else None


def _auth_find_user_by_id(user_id: Any) -> Optional[Dict[str, Any]]:
    user_id = _clean_str(user_id)
    if not user_id:
        return None
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.users WHERE id=%s LIMIT 1", (user_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def _auth_update_user_companies(user_id: Any, companies: List[str]):
    user_id = _clean_str(user_id)
    if not user_id:
        return
    normalized: List[str] = []
    for company in companies or []:
        company_key = _company_key(company)
        if company_key in {"parton", "park"} and company_key not in normalized:
            normalized.append(company_key)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM erp.user_companies WHERE user_id=%s", (user_id,))
            for company_key in normalized:
                cur.execute(
                    """
                    INSERT INTO erp.user_companies (user_id, company_key)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (user_id, company_key),
                )


def _auth_user_seller_links(user_id: Any) -> Dict[str, Dict[str, str]]:
    user_id = _clean_str(user_id)
    if not user_id:
        return {}
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT company_key, tiny_seller_id, tiny_seller_name
                    FROM erp.user_seller_links
                    WHERE user_id=%s
                      AND active=TRUE
                    ORDER BY company_key
                    """,
                    (user_id,),
                )
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[WARN] Falha ao carregar vinculos Tiny do usuario {user_id}: {e}")
        return {}

    links: Dict[str, Dict[str, str]] = {}
    for row in rows:
        company_key = _company_key(row.get("company_key"))
        if company_key not in {"parton", "park"}:
            continue
        tiny_seller_id = _clean_str(row.get("tiny_seller_id"))
        tiny_seller_name = _clean_str(row.get("tiny_seller_name"))
        if not tiny_seller_id or not tiny_seller_name:
            continue
        links[company_key] = {
            "tiny_seller_id": tiny_seller_id,
            "tiny_seller_name": tiny_seller_name,
        }
    return links


def _auth_user_can_access_company(user: Dict[str, Any], company_key: str) -> bool:
    company_key = _company_key(company_key)
    return company_key in _auth_user_companies(user.get("id"))


def _auth_user_default_company(user: Dict[str, Any]) -> str:
    companies = _auth_user_companies(user.get("id"))
    return companies[0] if companies else "parton"


def _auth_company_or_default(user: Dict[str, Any], company: str = "") -> str:
    if not company:
        return _auth_user_default_company(user)
    company_key = _company_key(company)
    if not _auth_user_can_access_company(user, company_key):
        raise HTTPException(status_code=403, detail="Sem permissão para esta empresa.")
    return company_key


_CLIENT_WALLET_NO_SELLER_LINK_MESSAGE = "Usuário sem vendedor Tiny vinculado para esta empresa."


def _resolve_client_wallet_scope(user: Dict[str, Any], company_key: str) -> Dict[str, Any]:
    company_key = _company_key(company_key)
    is_admin = _clean_str(user.get("role")).lower() == "admin"
    if is_admin:
        return {
            "is_admin": True,
            "company_key": company_key,
            "forced_tiny_seller_id": "",
            "linked_seller_name": "",
        }

    link = (_auth_user_seller_links(user.get("id")) or {}).get(company_key) or {}
    tiny_seller_id = _clean_str(link.get("tiny_seller_id"))
    if not tiny_seller_id:
        raise HTTPException(status_code=403, detail=_CLIENT_WALLET_NO_SELLER_LINK_MESSAGE)

    return {
        "is_admin": False,
        "company_key": company_key,
        "forced_tiny_seller_id": tiny_seller_id,
        "linked_seller_name": _clean_str(link.get("tiny_seller_name")),
    }


def _apply_client_wallet_scope(where: List[str], params: List[Any], scope: Dict[str, Any]):
    forced_tiny_seller_id = _clean_str(scope.get("forced_tiny_seller_id"))
    if forced_tiny_seller_id:
        where.append("COALESCE(vendedor_id, '') = %s")
        params.append(forced_tiny_seller_id)


_QUOTE_SELLER_NO_LINK_MESSAGE = "Usuário sem vendedor Tiny vinculado para esta empresa."
_QUOTE_SELLER_MISMATCH_MESSAGE = "Orçamento vinculado a vendedor Tiny diferente do usuário logado."
_QUOTE_SELLER_INVALID_MESSAGE = "Vendedor Tiny vinculado inválido para esta empresa."


def _resolve_quote_seller_scope(user: Dict[str, Any], company_key: str) -> Dict[str, Any]:
    company_key = _company_key(company_key)
    is_admin = _clean_str(user.get("role")).lower() == "admin"
    if is_admin:
        return {
            "is_admin": True,
            "company_key": company_key,
            "forced_seller_id": None,
            "forced_seller_name": "",
        }

    link = (_auth_user_seller_links(user.get("id")) or {}).get(company_key) or {}
    seller_id_raw = _clean_str(link.get("tiny_seller_id"))
    if not seller_id_raw:
        raise HTTPException(status_code=403, detail=_QUOTE_SELLER_NO_LINK_MESSAGE)
    try:
        seller_id = int(seller_id_raw)
    except Exception:
        raise HTTPException(status_code=400, detail=_QUOTE_SELLER_INVALID_MESSAGE)

    return {
        "is_admin": False,
        "company_key": company_key,
        "forced_seller_id": seller_id,
        "forced_seller_name": _clean_str(link.get("tiny_seller_name")) or str(seller_id),
    }


def _quote_payload_with_forced_seller(payload: "QuoteCreateIn", scope: Dict[str, Any]) -> "QuoteCreateIn":
    if scope.get("is_admin"):
        return payload
    return payload.model_copy(update={
        "seller_id": int(scope.get("forced_seller_id") or 0),
        "seller_name": _clean_str(scope.get("forced_seller_name")) or str(scope.get("forced_seller_id") or ""),
    })


def _assert_quote_seller_scope(quote: Dict[str, Any], scope: Dict[str, Any]):
    if scope.get("is_admin"):
        return
    try:
        quote_seller_id = int(quote.get("seller_id") or 0)
        forced_seller_id = int(scope.get("forced_seller_id") or 0)
    except Exception:
        raise HTTPException(status_code=403, detail=_QUOTE_SELLER_MISMATCH_MESSAGE)
    if not forced_seller_id or quote_seller_id != forced_seller_id:
        raise HTTPException(status_code=403, detail=_QUOTE_SELLER_MISMATCH_MESSAGE)



def _auth_audit_log(actor_login: str, target_login: str, action: str, before_data: Any = None, after_data: Any = None):
    """
    Auditoria administrativa não pode derrubar ações críticas como reset de senha.
    Se a tabela não existir ou houver erro de JSON, registra aviso no console e segue.
    """
    try:
        before_json = json.dumps(before_data, ensure_ascii=False, default=_json_default) if before_data is not None else None
        after_json = json.dumps(after_data, ensure_ascii=False, default=_json_default) if after_data is not None else None

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS erp.user_audit_log (
                      id BIGSERIAL PRIMARY KEY,
                      actor_login TEXT,
                      target_login TEXT,
                      action TEXT NOT NULL,
                      before_data JSONB,
                      after_data JSONB,
                      created_at TIMESTAMPTZ DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT INTO erp.user_audit_log (actor_login, target_login, action, before_data, after_data, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, now())
                    """,
                    (actor_login, target_login, action, before_json, after_json),
                )
    except Exception as e:
        print(f"[WARN] Falha ao gravar auditoria de usuario action={action}: {e}")

def _ensure_auth_schema():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.users (
                  id UUID PRIMARY KEY,
                  login TEXT UNIQUE NOT NULL,
                  display_name TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL,
                  active BOOLEAN DEFAULT TRUE,
                  must_change_password BOOLEAN DEFAULT FALSE,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.user_companies (
                  user_id UUID REFERENCES erp.users(id) ON DELETE CASCADE,
                  company_key TEXT NOT NULL,
                  PRIMARY KEY (user_id, company_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.user_audit_log (
                  id BIGSERIAL PRIMARY KEY,
                  actor_login TEXT,
                  target_login TEXT,
                  action TEXT NOT NULL,
                  before_data JSONB,
                  after_data JSONB,
                  created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )


def _seed_auth_users():
    # Usuários iniciais. A senha do admin vem de ERP_LOCAL_ADMIN_INITIAL_PASSWORD;
    # se ausente, é gerada aleatoriamente e impressa no primeiro boot. Os demais são
    # criados já com must_change_password=True. Não há senha fixa versionada.
    admin_pwd = os.getenv("ERP_LOCAL_ADMIN_INITIAL_PASSWORD", "").strip()
    if not admin_pwd:
        admin_pwd = secrets.token_urlsafe(16)
        print(f"[seed] Senha inicial do Admin (troque no primeiro acesso): {admin_pwd}")

    default_seller_pwd = os.getenv("ERP_LOCAL_SEED_PASSWORD", "trocar-no-primeiro-acesso")
    seed_users = [
        {"login": "vendedor1", "display_name": "Vendedor 1", "password": default_seller_pwd, "role": "vendedor", "companies": ["parton", "park"], "must_change_password": True},
        {"login": "vendedor2", "display_name": "Vendedor 2", "password": default_seller_pwd, "role": "vendedor", "companies": ["parton", "park"], "must_change_password": True},
        {"login": "separacao1", "display_name": "Separação 1", "password": default_seller_pwd, "role": "separacao", "companies": ["parton", "park"], "must_change_password": True},
        {"login": "Admin", "display_name": "Admin", "password": admin_pwd, "role": "admin", "companies": ["parton", "park"], "must_change_password": True},
    ]

    with _db() as conn:
        with conn.cursor() as cur:
            for seed in seed_users:
                cur.execute("SELECT * FROM erp.users WHERE LOWER(login)=LOWER(%s) LIMIT 1", (seed["login"],))
                existing = cur.fetchone()
                if existing:
                    continue

                user_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO erp.users (id, login, display_name, password_hash, role, active, must_change_password, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, TRUE, %s, now(), now())
                    """,
                    (
                        user_id,
                        seed["login"],
                        seed["display_name"],
                        _auth_password_hash(seed["password"]),
                        seed["role"],
                        bool(seed["must_change_password"]),
                    ),
                )
                for company_key in seed["companies"]:
                    cur.execute(
                        "INSERT INTO erp.user_companies (user_id, company_key) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (user_id, _company_key(company_key)),
                    )


def _auth_bootstrap():
    _ensure_auth_schema()
    _seed_auth_users()


def _tiny_for_company(company: str = "parton") -> TinyClient:
    row = _company_row(company)
    key = row["company_key"]

    env_names = [
        f"TINY_TOKEN_{key.upper()}",
        f"TINY_{key.upper()}_TOKEN",
    ]
    if key == "parton":
        env_names += ["TINY_TOKEN_SUPRIMENTOS", "TINY_SUPRIMENTOS_TOKEN"]
    if key == "park":
        env_names += ["TINY_TOKEN_INFORMATICA", "TINY_INFORMATICA_TOKEN"]

    token = ""
    for name in env_names:
        token = os.getenv(name, "").strip()
        if token:
            break

    if not token:
        token = str(row.get("tiny_token") or "").strip()

    if not token:
        raise HTTPException(
            status_code=500,
            detail=f"Token Tiny não configurado para empresa '{key}'. Configure no .env local ou no painel de empresas.",
        )

    base_url = (
        os.getenv(f"TINY_BASE_URL_{key.upper()}", "").strip()
        or str(row.get("tiny_base_url") or "").strip()
        or os.getenv("TINY_BASE_URL", "https://api.tiny.com.br/api2").strip()
    )

    return TinyClient(TinyConfig(token=token, base_url=base_url))


# ---------- Tiny/Olist V3 OAuth helpers ----------
# Endpoints OAuth configuráveis via env var (defaults: Olist Identity / Keycloak da Tiny).
TINY_V3_OAUTH_STATE_TTL_SECONDS = 10 * 60  # ~10 minutos
TINY_V3_TOKEN_REFRESH_SKEW_SECONDS = 60  # renova um pouco antes de expirar


def _tiny_v3_auth_base_url() -> str:
    return os.getenv(
        "TINY_V3_AUTH_BASE_URL",
        "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth",
    ).strip()


def _tiny_v3_token_url() -> str:
    return os.getenv(
        "TINY_V3_TOKEN_URL",
        "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token",
    ).strip()


def _tiny_v3_default_redirect_uri() -> str:
    return os.getenv(
        "TINY_V3_REDIRECT_URI",
        "http://localhost:3002/api/tiny-v3/oauth/callback",
    ).strip()


def _tiny_v3_oauth_scope() -> str:
    return os.getenv("TINY_V3_OAUTH_SCOPE", "openid").strip()


def _tiny_v3_oauth_secret() -> str:
    return os.getenv("TINY_V3_OAUTH_SECRET", "").strip() or AUTH_JWT_SECRET


def _tiny_v3_tail(value: Any) -> str:
    v = str(value or "").strip()
    return f"...{v[-4:]}" if len(v) >= 4 else ("***" if v else "")


def _tiny_v3_sign_state(payload_b64: str) -> str:
    return hmac.new(
        _tiny_v3_oauth_secret().encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _tiny_v3_make_state(company_key: str):
    """Gera um state assinado (HMAC-SHA256) com company_key, timestamp e nonce.

    Retorna (state, expires_at_utc).
    """
    ts = int(_now().timestamp())
    nonce = secrets.token_urlsafe(16)
    raw = json.dumps({"k": company_key, "ts": ts, "n": nonce}, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
    sig = _tiny_v3_sign_state(payload_b64)
    state = f"{payload_b64}.{sig}"
    expires_at = _now() + dt.timedelta(seconds=TINY_V3_OAUTH_STATE_TTL_SECONDS)
    return state, expires_at


def _tiny_v3_parse_state(state: str) -> Dict[str, Any]:
    """Valida assinatura e expiração do state. Levanta ValueError se inválido."""
    state = str(state or "").strip()
    if not state or "." not in state:
        raise ValueError("state ausente ou malformado")
    payload_b64, _, sig = state.partition(".")
    expected = _tiny_v3_sign_state(payload_b64)
    if not hmac.compare_digest(sig, expected):
        raise ValueError("assinatura do state inválida")
    padding = "=" * (-len(payload_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii")).decode("utf-8")
        data = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"payload do state inválido: {exc}")
    company_key = _clean_str(data.get("k"))
    ts = int(data.get("ts") or 0)
    if not company_key:
        raise ValueError("state sem company_key")
    age = int(_now().timestamp()) - ts
    if age < 0 or age > TINY_V3_OAUTH_STATE_TTL_SECONDS:
        raise ValueError("state expirado")
    return {"company_key": company_key, "ts": ts, "nonce": _clean_str(data.get("n"))}


def _tiny_v3_exchange_token(
    grant_type: str,
    *,
    client_id: str,
    client_secret: str,
    code: Optional[str] = None,
    refresh_token: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """Chama o token endpoint OAuth da Tiny V3 e retorna o JSON da resposta."""
    data: Dict[str, Any] = {
        "grant_type": grant_type,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if grant_type == "authorization_code":
        data["code"] = code or ""
        data["redirect_uri"] = redirect_uri or ""
    elif grant_type == "refresh_token":
        data["refresh_token"] = refresh_token or ""

    try:
        resp = requests.post(
            _tiny_v3_token_url(),
            data=data,
            headers={"Accept": "application/json"},
            timeout=int(os.getenv("TINY_V3_TIMEOUT_SECONDS", "30")),
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Falha de rede ao chamar token endpoint Tiny V3: {exc}")

    try:
        payload = resp.json()
    except Exception:
        payload = {"raw_text": (resp.text or "")[:2000]}

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Token endpoint Tiny V3 retornou HTTP {resp.status_code}: "
            f"{json.dumps(payload, ensure_ascii=False)[:1000]}",
        )
    return payload


def _tiny_v3_store_tokens(company_key: str, payload: Dict[str, Any], *, authorized: bool = False):
    """Persiste tokens retornados pelo OAuth. refresh_token só é sobrescrito se vier."""
    access_token = _clean_str(payload.get("access_token"))
    refresh_token = _clean_str(payload.get("refresh_token"))
    expires_in = payload.get("expires_in")

    expires_at = None
    try:
        if expires_in is not None:
            expires_at = _now() + dt.timedelta(seconds=int(expires_in))
    except Exception:
        expires_at = None

    sets = ["tiny_v3_access_token = %s", "tiny_v3_token_expires_at = %s", "updated_at = now()"]
    params: List[Any] = [access_token, expires_at]
    if refresh_token:
        sets.append("tiny_v3_refresh_token = %s")
        params.append(refresh_token)
    if authorized:
        sets.append("tiny_v3_authorized_at = now()")
    params.append(company_key)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE erp.companies SET {', '.join(sets)} WHERE company_key = %s",
                tuple(params),
            )
    return {"access_token": access_token, "refresh_token": refresh_token, "expires_at": expires_at}


def _tiny_v3_for_company(company: str = "parton") -> TinyV3Client:
    row = _company_row(company)
    key = row["company_key"]

    env_names = [
        f"TINY_V3_ACCESS_TOKEN_{key.upper()}",
        f"TINY_V3_{key.upper()}_TOKEN",
    ]
    if key == "parton":
        env_names += ["TINY_V3_ACCESS_TOKEN_SUPRIMENTOS", "TINY_V3_SUPRIMENTOS_TOKEN"]
    if key == "park":
        env_names += ["TINY_V3_ACCESS_TOKEN_INFORMATICA", "TINY_V3_INFORMATICA_TOKEN"]

    env_token = ""
    for name in env_names:
        env_token = os.getenv(name, "").strip()
        if env_token:
            break

    base_url = os.getenv("TINY_V3_BASE_URL", "https://api.tiny.com.br/public-api/v3").strip()
    timeout = int(os.getenv("TINY_V3_TIMEOUT_SECONDS", "30"))

    # Token via env var: mantém comportamento atual, sem tentar refresh.
    if env_token:
        return TinyV3Client(TinyV3Config(access_token=env_token, base_url=base_url, timeout_seconds=timeout))

    token = str(row.get("tiny_v3_access_token") or "").strip()
    refresh_token = str(row.get("tiny_v3_refresh_token") or "").strip()
    expires_at = row.get("tiny_v3_token_expires_at")
    client_id = str(row.get("tiny_v3_client_id") or "").strip()
    client_secret = str(row.get("tiny_v3_client_secret") or "").strip()

    if not token and not refresh_token:
        raise HTTPException(
            status_code=500,
            detail=f"Token Tiny V3 não configurado para empresa '{key}'. "
            f"Configure as credenciais e autorize via OAuth, ou use POST /api/admin/v3-token.",
        )

    # Decide se precisa renovar (expirado, perto de expirar, ou sem access_token).
    needs_refresh = False
    if not token:
        needs_refresh = True
    elif expires_at:
        now_utc = _now()
        try:
            if getattr(expires_at, "tzinfo", None):
                exp = expires_at
            else:
                exp = expires_at.replace(tzinfo=dt.timezone.utc)
            needs_refresh = exp <= (now_utc + dt.timedelta(seconds=TINY_V3_TOKEN_REFRESH_SKEW_SECONDS))
        except Exception:
            needs_refresh = False

    if needs_refresh:
        if not refresh_token:
            raise HTTPException(
                status_code=500,
                detail=f"Token Tiny V3 da empresa '{key}' expirado e sem refresh_token. "
                f"Refaça a autorização OAuth.",
            )
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=500,
                detail=f"Renovação do token Tiny V3 da empresa '{key}' requer client_id/client_secret. "
                f"Configure via POST /api/admin/tiny-v3/credentials.",
            )
        payload = _tiny_v3_exchange_token(
            "refresh_token",
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        stored = _tiny_v3_store_tokens(key, payload, authorized=False)
        token = stored["access_token"] or token

    if not token:
        raise HTTPException(
            status_code=500,
            detail=f"Não foi possível obter um access_token Tiny V3 válido para a empresa '{key}'.",
        )

    return TinyV3Client(TinyV3Config(access_token=token, base_url=base_url, timeout_seconds=timeout))


def _clean_str(v):
    return str(v or "").strip()


def _strip_accents(v: Any) -> str:
    text = _clean_str(v)
    if not text:
        return ""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _normalize_status_text(v: Any) -> str:
    return _strip_accents(v).strip().lower()


def _env_truthy(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _safe_float(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(str(v).replace(",", "."))
    except Exception:
        return default


def _safe_int(v, default=None):
    try:
        if v is None or v == "":
            return default
        return int(v)
    except Exception:
        return default


def _parse_iso_ts(value):
    """Parseia timestamp ISO 8601 (aceita sufixo Z e offset, ex.: -03:00).
    Retorna datetime ou None se inválido/vazio."""
    text = _clean_str(value)
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _active_flag(value):
    return str(value or "").strip().upper() not in ("I", "INATIVO", "INATIVA")


def _client_name_from_snapshot(snap):
    c = snap or {}
    if isinstance(c, str):
        c = _from_json(c, {}) or {}
    if isinstance(c, dict) and isinstance(c.get("contato"), dict):
        c = c.get("contato") or {}
    if isinstance(c, dict) and isinstance(c.get("cliente"), dict):
        c = c.get("cliente") or {}
    if not isinstance(c, dict):
        return ""
    return (
        c.get("nome")
        or c.get("name")
        or c.get("razao_social")
        or c.get("razaoSocial")
        or c.get("fantasia")
        or ""
    )



def _fix_mojibake_text(value):
    s = _clean_str(value)
    if not s:
        return ""

    # Corrige textos UTF-8 que ficaram armazenados/interpretados como Latin-1/Windows-1252.
    # Exemplo: "Ros" + "Ã¡" + "rio" vira "Rosário".
    markers = [
        chr(0x00C3),  # Ã
        chr(0x00C2),  # Â
        chr(0x00E2),  # â
    ]

    if any(m in s for m in markers):
        for enc in ("latin1", "cp1252"):
            try:
                fixed = s.encode(enc).decode("utf-8")
                if fixed and fixed != s:
                    return fixed
            except Exception:
                pass

    return s


def _client_dict_from_snapshot(snap):
    c = snap or {}
    if isinstance(c, str):
        c = _from_json(c, {}) or {}
    if isinstance(c, dict) and isinstance(c.get("contato"), dict):
        c = c.get("contato") or {}
    if isinstance(c, dict) and isinstance(c.get("cliente"), dict):
        c = c.get("cliente") or {}
    return c if isinstance(c, dict) else {}


def _client_first_value_from_snapshot(snap, *keys):
    c = _client_dict_from_snapshot(snap)
    for key in keys:
        value = _fix_mojibake_text(c.get(key))
        if value:
            return value
    return ""


def _client_address_from_snapshot(snap):
    c = _client_dict_from_snapshot(snap)
    endereco = _fix_mojibake_text(c.get("endereco") or c.get("logradouro"))
    numero = _fix_mojibake_text(c.get("numero"))
    complemento = _fix_mojibake_text(c.get("complemento"))
    bairro = _fix_mojibake_text(c.get("bairro"))
    cidade = _fix_mojibake_text(c.get("cidade"))
    uf = _fix_mojibake_text(c.get("uf"))
    cep = _fix_mojibake_text(c.get("cep"))

    parts = []
    line1 = endereco
    if numero:
        line1 = (line1 + ", " + numero).strip(", ")
    if complemento:
        line1 = (line1 + " - " + complemento).strip(" -")
    if line1:
        parts.append(line1)
    if bairro:
        parts.append(bairro)

    city_uf = cidade
    if uf:
        city_uf = (city_uf + "/" + uf).strip("/")
    if city_uf:
        parts.append(city_uf)

    if cep:
        parts.append("CEP " + cep)

    return " - ".join([p for p in parts if p])




def _normalize_ops_tiny_status(v: str) -> str:
    s = str(v or "").strip().lower()
    if not s:
        return ""
    if s == "em aberto":
        return "Em Aberto"
    if s == "aprovado":
        return "Aprovado"
    if s == "preparando envio":
        return "Preparando Envio"
    if s == "pronto para envio":
        return "Pronto para Envio"
    if s == "faturado":
        return "Faturado"
    if s == "cancelado":
        return "Cancelado"
    return str(v or "").strip()


def _tiny_order_status_text(order_resp: Dict[str, Any]) -> str:
    def _search(value: Any) -> str:
        if isinstance(value, dict):
            for key in ("pedido", "retorno", "response", "data", "order"):
                found = _search(value.get(key))
                if found:
                    return found
            for key in (
                "situacao",
                "situacaoTexto",
                "statusTexto",
                "texto",
                "descricao",
                "descricaoSituacao",
            ):
                if key in value:
                    found = _search(value.get(key))
                    if found:
                        return found
            if "status" in value:
                found = _search(value.get("status"))
                if found and found != "ok":
                    return found
        elif isinstance(value, list):
            for item in value:
                found = _search(item)
                if found:
                    return found
        elif value is not None:
            text = _normalize_status_text(value)
            if text:
                return text
        return ""

    raw_status = _search(order_resp)
    if not raw_status:
        return ""

    normalized = _normalize_status_text(raw_status)
    mapping = {
        "em aberto": "em aberto",
        "aprovado": "aprovado",
        "aprovada": "aprovado",
        "preparando envio": "preparando envio",
        "pronto para envio": "pronto para envio",
        "faturado": "faturado",
        "cancelado": "cancelado",
        "cancelada": "cancelado",
    }
    return mapping.get(normalized, normalized)


def _tiny_change_order_status(company_key: str, tiny_order_id: Any, situacao: str):
    tiny = _tiny_for_company(company_key)
    return tiny.alterar_situacao_pedido(int(tiny_order_id), str(situacao))


def _tiny_sync_and_verify_status(company_key: str, tiny_order_id: Any, target_status: str, context: str):
    if not ENABLE_TINY_STATUS_SYNC_LOCAL:
        raise HTTPException(status_code=503, detail="Sincronização Tiny desabilitada no ambiente local.")

    tiny = _tiny_for_company(company_key)
    target_norm = _normalize_status_text(target_status)
    before = tiny.obter_pedido(int(tiny_order_id))
    before_status = _tiny_order_status_text(before)
    print(
        f"[tiny-sync] context={context} tiny_order_id={tiny_order_id} before={before_status!r} target={target_norm!r}"
    )

    if before_status != target_norm:
        _tiny_change_order_status(company_key, tiny_order_id, target_norm)

    after = tiny.obter_pedido(int(tiny_order_id))
    after_status = _tiny_order_status_text(after)
    print(
        f"[tiny-sync] context={context} tiny_order_id={tiny_order_id} after={after_status!r} target={target_norm!r}"
    )
    if after_status != target_norm:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao alterar status do pedido no Tiny para '{target_status}'.",
        )
    return after


def _ensure_separation_orders_table():
    columns = _table_columns("erp", "separation_orders")
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.separation_orders (
                    tiny_order_id BIGINT PRIMARY KEY
                )
                """
            )

            required_columns = [
                "tiny_order_number TEXT",
                "quote_id TEXT",
                "quote_number BIGINT",
                "company_key TEXT",
                "client_name TEXT",
                "seller_name TEXT",
                "status TEXT",
                "printed BOOLEAN DEFAULT FALSE",
                "label_printed BOOLEAN DEFAULT FALSE",
                "printed_at TIMESTAMPTZ NULL",
                "label_printed_at TIMESTAMPTZ NULL",
                "started_at TIMESTAMPTZ NULL",
                "separated_at TIMESTAMPTZ NULL",
                "checked_at TIMESTAMPTZ NULL",
                "awaiting_conference BOOLEAN DEFAULT FALSE",
                "separation_photo_url TEXT",
                "conference_photo_url TEXT",
                "assigned_to TEXT",
                "operator_name TEXT",
                "notes TEXT",
                "packaging_boxes INTEGER",
                "packaging_bags INTEGER",
                "packaging_weight_kg NUMERIC",
                "packaging_height_cm NUMERIC",
                "packaging_width_cm NUMERIC",
                "packaging_length_cm NUMERIC",
                "packaging_volumes INTEGER",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ]
            for column_def in required_columns:
                column_name = column_def.split()[0]
                if column_name.lower() not in columns:
                    cur.execute(f"ALTER TABLE erp.separation_orders ADD COLUMN IF NOT EXISTS {column_def}")
    _TABLE_COLUMNS_CACHE.pop("erp.separation_orders", None)


def _ensure_app_settings_table():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.app_settings (
                  key TEXT PRIMARY KEY,
                  value TEXT,
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )


def _get_setting(key: str, default=None):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM erp.app_settings WHERE key=%s LIMIT 1", (key,))
            row = cur.fetchone()
    if not row:
        return default
    return row.get("value")


def _set_setting(key: str, value: str):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.app_settings (key, value, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                (key, value),
            )


# Modo da etapa de Conferência, controlado em RUNTIME pelo admin (persistido em
# erp.app_settings). Default herda do env ENABLE_SEP_CONFERENCIA (OFF por padrão).
# Cache em memória — a app roda single-worker; é atualizado no toggle do admin.
_SEP_CONFERENCIA_MODE_CACHE = None


def _sep_conferencia_mode() -> str:
    global _SEP_CONFERENCIA_MODE_CACHE
    if _SEP_CONFERENCIA_MODE_CACHE is None:
        raw = _get_setting("sep_conferencia_mode", None)
        if raw is None:
            _SEP_CONFERENCIA_MODE_CACHE = "soft" if ENABLE_SEP_CONFERENCIA else "off"
        else:
            val = _clean_str(raw).lower()
            _SEP_CONFERENCIA_MODE_CACHE = val if val in {"off", "soft", "strict"} else "off"
    return _SEP_CONFERENCIA_MODE_CACHE


def _set_sep_conferencia_mode(mode: str) -> str:
    global _SEP_CONFERENCIA_MODE_CACHE
    val = _clean_str(mode).lower()
    if val not in {"off", "soft", "strict"}:
        val = "off"
    _set_setting("sep_conferencia_mode", val)
    _SEP_CONFERENCIA_MODE_CACHE = val
    return val


def _sep_conferencia_enabled() -> bool:
    return _sep_conferencia_mode() != "off"


def _ensure_client_wallet_tables():
    wallet_columns = _table_columns("erp", "client_wallet")
    state_columns = _table_columns("erp", "client_wallet_sync_state")
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.client_wallet (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  tiny_client_id TEXT NOT NULL,
                  codigo TEXT,
                  nome TEXT,
                  fantasia TEXT,
                  cpf_cnpj TEXT,
                  email TEXT,
                  telefone TEXT,
                  celular TEXT,
                  cidade TEXT,
                  uf TEXT,
                  endereco TEXT,
                  numero TEXT,
                  bairro TEXT,
                  cep TEXT,
                  situacao TEXT,
                  ativo BOOLEAN,
                  vendedor_id TEXT,
                  vendedor_nome TEXT,
                  raw_json JSONB,
                  last_seen_at TIMESTAMPTZ,
                  last_purchase_date TIMESTAMPTZ,
                  last_purchase_order_number TEXT,
                  last_purchase_total NUMERIC,
                  last_purchase_synced_at TIMESTAMPTZ,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            wallet_required_columns = [
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "tiny_client_id TEXT",
                "codigo TEXT",
                "nome TEXT",
                "fantasia TEXT",
                "cpf_cnpj TEXT",
                "email TEXT",
                "telefone TEXT",
                "celular TEXT",
                "cidade TEXT",
                "uf TEXT",
                "endereco TEXT",
                "numero TEXT",
                "bairro TEXT",
                "cep TEXT",
                "situacao TEXT",
                "ativo BOOLEAN",
                "vendedor_id TEXT",
                "vendedor_nome TEXT",
                "raw_json JSONB",
                "last_seen_at TIMESTAMPTZ",
                "last_purchase_date TIMESTAMPTZ",
                "last_purchase_order_number TEXT",
                "last_purchase_total NUMERIC",
                "last_purchase_synced_at TIMESTAMPTZ",
                "tiny_sync_status TEXT",
                "tiny_sync_error TEXT",
                "tiny_synced_at TIMESTAMPTZ",
                "origin TEXT",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
                "complemento TEXT",
                "telefone2 TEXT",
                "website TEXT",
                "email_nfe TEXT",
                "observacoes TEXT",
                "contribuinte TEXT",
                "inscricao_estadual TEXT",
                "inscricao_municipal TEXT",
                "tipo_contato TEXT",
                "codigo_regime_tributario TEXT",
                "inscricao_suframa TEXT",
                "data_nascimento DATE",
                "status_crm TEXT",
            ]
            for column_def in wallet_required_columns:
                column_name = column_def.split()[0]
                if column_name.lower() not in wallet_columns:
                    cur.execute(f"ALTER TABLE erp.client_wallet ADD COLUMN IF NOT EXISTS {column_def}")
            # Cadastro local-first cria registros antes de existir tiny_client_id.
            # Garante que a coluna aceite NULL (idempotente; índice único é parcial).
            cur.execute("ALTER TABLE erp.client_wallet ALTER COLUMN tiny_client_id DROP NOT NULL")
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS client_wallet_company_tiny_uidx
                ON erp.client_wallet (company_key, tiny_client_id)
                WHERE tiny_client_id IS NOT NULL
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_nome_idx ON erp.client_wallet (company_key, nome)")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_cpf_idx ON erp.client_wallet (company_key, cpf_cnpj)")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_ativo_idx ON erp.client_wallet (company_key, ativo)")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_vendedor_idx ON erp.client_wallet (company_key, vendedor_nome)")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_uf_idx ON erp.client_wallet (company_key, uf)")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_updated_idx ON erp.client_wallet (company_key, updated_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_last_purchase_idx ON erp.client_wallet (company_key, last_purchase_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_nome_lower_idx ON erp.client_wallet (company_key, LOWER(nome))")
            cur.execute("CREATE INDEX IF NOT EXISTS client_wallet_company_fantasia_lower_idx ON erp.client_wallet (company_key, LOWER(fantasia))")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.client_wallet_sync_state (
                  company_key TEXT PRIMARY KEY,
                  current_page INTEGER,
                  next_page INTEGER DEFAULT 1,
                  page_size INTEGER DEFAULT 50,
                  total_pages INTEGER,
                  total_remote INTEGER,
                  total_local INTEGER,
                  progress_percent NUMERIC,
                  last_run_at TIMESTAMPTZ,
                  last_success_at TIMESTAMPTZ,
                  last_error TEXT,
                  total_imported INTEGER DEFAULT 0,
                  total_updated INTEGER DEFAULT 0,
                  finished BOOLEAN DEFAULT FALSE,
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            state_required_columns = [
                "current_page INTEGER",
                "next_page INTEGER DEFAULT 1",
                "page_size INTEGER DEFAULT 50",
                "total_pages INTEGER",
                "total_remote INTEGER",
                "total_local INTEGER",
                "progress_percent NUMERIC",
                "last_run_at TIMESTAMPTZ",
                "last_success_at TIMESTAMPTZ",
                "last_error TEXT",
                "total_imported INTEGER DEFAULT 0",
                "total_updated INTEGER DEFAULT 0",
                "finished BOOLEAN DEFAULT FALSE",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ]
            for column_def in state_required_columns:
                column_name = column_def.split()[0]
                if column_name.lower() not in state_columns:
                    cur.execute(f"ALTER TABLE erp.client_wallet_sync_state ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.client_wallet_sync_log (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT,
                  started_at TIMESTAMPTZ,
                  finished_at TIMESTAMPTZ,
                  status TEXT,
                  imported INTEGER DEFAULT 0,
                  updated INTEGER DEFAULT 0,
                  processed INTEGER DEFAULT 0,
                  error TEXT,
                  created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.client_wallet_purchase_enrich_log (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT,
                  started_at TIMESTAMPTZ,
                  finished_at TIMESTAMPTZ,
                  processed INTEGER DEFAULT 0,
                  updated INTEGER DEFAULT 0,
                  without_purchases INTEGER DEFAULT 0,
                  errors INTEGER DEFAULT 0,
                  status TEXT,
                  error TEXT,
                  created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for sql in (
                "CREATE INDEX IF NOT EXISTS quotes_company_internal_status_idx ON erp.quotes (company_key, internal_status)",
                "CREATE INDEX IF NOT EXISTS quotes_company_created_idx ON erp.quotes (company_key, created_at)",
                "CREATE INDEX IF NOT EXISTS quotes_company_updated_idx ON erp.quotes (company_key, updated_at)",
                "CREATE INDEX IF NOT EXISTS quotes_company_client_id_idx ON erp.quotes (company_key, client_id)",
                "CREATE INDEX IF NOT EXISTS quote_items_quote_id_idx ON erp.quote_items (quote_id)",
                "CREATE INDEX IF NOT EXISTS quote_items_product_id_idx ON erp.quote_items (product_id)",
                "CREATE INDEX IF NOT EXISTS quote_items_sku_snapshot_idx ON erp.quote_items (sku_snapshot)",
            ):
                try:
                    cur.execute(sql)
                except Exception as e:
                    print(f"[client-wallet] indice ignorado: {e}")
    _TABLE_COLUMNS_CACHE.pop("erp.client_wallet", None)
    _TABLE_COLUMNS_CACHE.pop("erp.client_wallet_sync_state", None)


def _ensure_quotes_tiny_status_sync_columns():
    columns = _table_columns("erp", "quotes")
    required_columns = [
        "tiny_status_synced_at TIMESTAMPTZ",
        "tiny_status_sync_error TEXT",
        "tiny_status_raw TEXT",
    ]
    with _db() as conn:
        with conn.cursor() as cur:
            for column_def in required_columns:
                column_name = column_def.split()[0]
                if column_name.lower() not in columns:
                    cur.execute(f"ALTER TABLE erp.quotes ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS quotes_company_tiny_status_synced_idx
                ON erp.quotes (company_key, tiny_status_synced_at)
                """
            )
    _TABLE_COLUMNS_CACHE.pop("erp.quotes", None)


def _ensure_quotes_ordered_at_column():
    columns = _table_columns("erp", "quotes")
    with _db() as conn:
        with conn.cursor() as cur:
            if "ordered_at" not in columns:
                cur.execute("ALTER TABLE erp.quotes ADD COLUMN IF NOT EXISTS ordered_at TIMESTAMPTZ")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS quotes_company_ordered_idx
                ON erp.quotes (company_key, ordered_at)
                """
            )
    _TABLE_COLUMNS_CACHE.pop("erp.quotes", None)


def _ensure_companies_v3_columns():
    columns = _table_columns("erp", "companies")
    with _db() as conn:
        with conn.cursor() as cur:
            for col, col_type in [
                ("tiny_v3_access_token", "TEXT"),
                ("tiny_v3_refresh_token", "TEXT"),
                ("tiny_v3_token_expires_at", "TIMESTAMPTZ"),
                ("tiny_v3_client_id", "TEXT"),
                ("tiny_v3_client_secret", "TEXT"),
                ("tiny_v3_redirect_uri", "TEXT"),
                ("tiny_v3_oauth_state", "TEXT"),
                ("tiny_v3_oauth_state_expires_at", "TIMESTAMPTZ"),
                ("tiny_v3_authorized_at", "TIMESTAMPTZ"),
            ]:
                if col not in columns:
                    cur.execute(
                        f"ALTER TABLE erp.companies ADD COLUMN IF NOT EXISTS {col} {col_type}"
                    )
    _TABLE_COLUMNS_CACHE.pop("erp.companies", None)


def _upsert_separation_order(*, tiny_order_id: Any, values: Dict[str, Any]):
    if tiny_order_id is None or str(tiny_order_id).strip() == "":
        return

    values = dict(values or {})
    values["tiny_order_id"] = int(tiny_order_id)
    values.setdefault("updated_at", _now())
    columns = [
        "tiny_order_id",
        "tiny_order_number",
        "quote_id",
        "quote_number",
        "company_key",
        "client_name",
        "seller_name",
        "status",
        "printed",
        "label_printed",
        "printed_at",
        "label_printed_at",
        "started_at",
        "separated_at",
        "checked_at",
        "awaiting_conference",
        "separation_photo_url",
        "conference_photo_url",
        "assigned_to",
        "operator_name",
        "notes",
        "packaging_boxes",
        "packaging_bags",
        "packaging_weight_kg",
        "packaging_height_cm",
        "packaging_width_cm",
        "packaging_length_cm",
        "packaging_volumes",
        "created_at",
        "updated_at",
    ]
    insert_columns = [col for col in columns if col in values]
    if "tiny_order_id" not in insert_columns:
        insert_columns.insert(0, "tiny_order_id")
    if "created_at" not in insert_columns:
        values["created_at"] = values.get("created_at") or _now()
        insert_columns.append("created_at")
    if "updated_at" not in insert_columns:
        values["updated_at"] = _now()
        insert_columns.append("updated_at")

    update_columns = [col for col in insert_columns if col not in {"tiny_order_id", "created_at", "updated_at"}]
    update_sql = ", ".join(f"{col} = COALESCE(EXCLUDED.{col}, erp.separation_orders.{col})" for col in update_columns)
    placeholders = ", ".join(f"%({col})s" for col in insert_columns)
    column_sql = ", ".join(insert_columns)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO erp.separation_orders ({column_sql})
                VALUES ({placeholders})
                ON CONFLICT (tiny_order_id) DO UPDATE SET
                    {update_sql},
                    updated_at = now()
                """,
                values,
            )


def _ops_sync_progress_snapshot():
    with _OPS_SYNC_PROGRESS_LOCK:
        return dict(_OPS_SYNC_PROGRESS)


def _ops_sync_progress_update(**kwargs):
    with _OPS_SYNC_PROGRESS_LOCK:
        _OPS_SYNC_PROGRESS.update(kwargs)


def _ops_sync_progress_reset():
    with _OPS_SYNC_PROGRESS_LOCK:
        _OPS_SYNC_PROGRESS.update({
            "running": False,
            "started_at": None,
            "finished_at": None,
            "updated_total": 0,
            "checked_total": 0,
            "rounds_completed": 0,
            "last_error": "",
            "last_result": None,
            "company": None,
        })


def _ops_extract_tiny_status_from_order_obter(order_resp: Dict[str, Any]) -> tuple[str, str, str]:
    pedido = order_resp.get("pedido") or order_resp or {}
    if not isinstance(pedido, dict):
        pedido = {}
    raw_status = (
        pedido.get("situacao")
        or pedido.get("situacao_nome")
        or pedido.get("descricao_situacao")
        or pedido.get("status")
        or ""
    )
    normalized = _normalize_ops_tiny_status(raw_status)
    tiny_order_number = (
        pedido.get("numero")
        or order_resp.get("numero")
        or pedido.get("numero_pedido")
        or ""
    )
    return normalized, str(raw_status or ""), str(tiny_order_number or "")


def _ops_fetch_local_order_status_rows(company_key: str, q_norm: str = "", limit: Optional[int] = None):
    _ensure_quotes_tiny_status_sync_columns()
    where = [
        "q.company_key = %s",
        "q.status = 'ordered'",
        "q.tiny_order_id IS NOT NULL",
        "LOWER(COALESCE(q.internal_status, '')) NOT IN ('cancelado', 'faturado')",
    ]
    params: List[Any] = [company_key]
    q_trim = str(q_norm or "").strip()
    if q_trim:
        where.append(
            "("
            "CAST(q.tiny_order_id AS TEXT) = %s OR "
            "CAST(q.tiny_order_number AS TEXT) = %s OR "
            "CAST(q.quote_number AS TEXT) = %s OR "
            "CAST(q.quote_id AS TEXT) = %s"
            ")"
        )
        params.extend([q_trim, q_trim, q_trim, q_trim])

    sql = f"""
    SELECT
        q.quote_id,
        q.quote_number,
        q.company_key,
        q.tiny_order_id,
        q.tiny_order_number,
        q.internal_status
    FROM erp.quotes q
    WHERE {' AND '.join(where)}
    ORDER BY
        q.tiny_status_synced_at ASC NULLS FIRST,
        q.updated_at ASC NULLS LAST,
        q.created_at ASC NULLS LAST
    """
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def _ops_sync_touch_quote(
    quote_id: str,
    company_key: str,
    *,
    internal_status: Optional[str] = None,
    tiny_order_number: Optional[str] = None,
    tiny_status_raw: Optional[str] = None,
    tiny_status_sync_error: Optional[str] = None,
    clear_tiny_status_sync_error: bool = True,
):
    set_parts = []
    params: List[Any] = []
    has_real_change = internal_status is not None or tiny_order_number is not None

    if tiny_order_number is not None:
        set_parts.append("tiny_order_number = %s")
        params.append(tiny_order_number)

    if internal_status is not None:
        set_parts.append("internal_status = %s")
        params.append(internal_status)

    if has_real_change:
        set_parts.append("updated_at = now()")
    set_parts.append("tiny_status_synced_at = now()")

    if tiny_status_raw is not None:
        set_parts.append("tiny_status_raw = %s")
        params.append(tiny_status_raw)

    if tiny_status_sync_error is not None:
        set_parts.append("tiny_status_sync_error = %s")
        params.append(tiny_status_sync_error)
    elif clear_tiny_status_sync_error:
        set_parts.append("tiny_status_sync_error = NULL")

    params.extend([quote_id, company_key])

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE erp.quotes
                SET {", ".join(set_parts)}
                WHERE quote_id = %s AND company_key = %s
                """,
                params,
            )


def _ops_run_sync_one_local_order_status(tiny: TinyClient, company_key: str, row: Dict[str, Any]):
    quote_id = row.get("quote_id")
    tiny_order_id = row.get("tiny_order_id")
    current_status = _normalize_ops_tiny_status(row.get("internal_status"))
    current_tiny_number = str(row.get("tiny_order_number") or "").strip()

    if not tiny_order_id:
        return {
            "ok": False,
            "updated": False,
            "skipped": True,
            "error": "Pedido local sem tiny_order_id.",
            "quote_id": quote_id,
        }

    try:
        raw = tiny.obter_pedido(int(tiny_order_id))
        new_status, raw_status, new_tiny_number = _ops_extract_tiny_status_from_order_obter(raw)
    except TinyAPIError as e:
        _ops_sync_touch_quote(
            quote_id,
            company_key,
            tiny_status_sync_error=str(e),
            clear_tiny_status_sync_error=False,
        )
        return {
            "ok": False,
            "updated": False,
            "tiny_status_sync_error": str(e),
            "error": str(e),
            "quote_id": quote_id,
            "tiny_order_id": tiny_order_id,
        }
    except Exception as e:
        _ops_sync_touch_quote(
            quote_id,
            company_key,
            tiny_status_sync_error=str(e),
            clear_tiny_status_sync_error=False,
        )
        return {
            "ok": False,
            "updated": False,
            "tiny_status_sync_error": str(e),
            "error": str(e),
            "quote_id": quote_id,
            "tiny_order_id": tiny_order_id,
        }

    allowed_statuses = {
        "Em Aberto",
        "Aprovado",
        "Preparando Envio",
        "Pronto para Envio",
        "Faturado",
        "Cancelado",
    }

    if new_status not in allowed_statuses:
        sync_error = "Status Tiny nao mapeado para o fluxo local."
        _ops_sync_touch_quote(
            quote_id,
            company_key,
            tiny_status_raw=raw_status,
            tiny_status_sync_error=sync_error,
            clear_tiny_status_sync_error=False,
        )
        return {
            "ok": True,
            "updated": False,
            "skipped": True,
            "tiny_status_sync_error": sync_error,
            "quote_id": quote_id,
            "quote_number": row.get("quote_number"),
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": current_tiny_number or new_tiny_number or None,
            "from": current_status or "",
            "to": new_status,
            "tiny_status_raw": raw_status,
            "reason": "Status Tiny não mapeado para o fluxo local.",
        }

    target_tiny_number = str(new_tiny_number or "").strip()
    status_changed = new_status != current_status
    number_changed = bool(target_tiny_number) and target_tiny_number != current_tiny_number

    if not status_changed and not number_changed:
        _ops_sync_touch_quote(quote_id, company_key, tiny_status_raw=raw_status)
        return {
            "ok": True,
            "updated": False,
            "unchanged": True,
            "quote_id": quote_id,
            "quote_number": row.get("quote_number"),
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": current_tiny_number or target_tiny_number or None,
            "from": current_status or "",
            "to": new_status,
            "tiny_status_raw": raw_status,
        }

    _ops_sync_touch_quote(
        quote_id,
        company_key,
        internal_status=new_status if status_changed else None,
        tiny_order_number=target_tiny_number if number_changed else None,
        tiny_status_raw=raw_status,
    )

    return {
        "ok": True,
        "updated": True,
        "quote_id": quote_id,
        "quote_number": row.get("quote_number"),
        "tiny_order_id": int(tiny_order_id),
        "tiny_order_number": target_tiny_number or current_tiny_number or None,
        "from": current_status or "",
        "to": new_status,
        "tiny_status_raw": raw_status,
    }


def _ops_run_sync_local_order_statuses_batch(company_key: str, limit: int = 5):
    rows = _ops_fetch_local_order_status_rows(company_key, limit=limit)
    tiny = _tiny_for_company(company_key)

    checked = 0
    updated_count = 0
    skipped_count = 0
    errors = []
    results = []

    for row in rows:
        checked += 1
        try:
            result = _ops_run_sync_one_local_order_status(tiny, company_key, row)
            results.append(result)
            if result.get("updated"):
                updated_count += 1
            if result.get("skipped"):
                skipped_count += 1
            if not result.get("ok") and result.get("error"):
                errors.append({
                    "quote_id": row.get("quote_id"),
                    "tiny_order_id": row.get("tiny_order_id"),
                    "error": result.get("error"),
                })
        except Exception as e:
            errors.append({
                "quote_id": row.get("quote_id"),
                "tiny_order_id": row.get("tiny_order_id"),
                "error": str(e),
            })

    return {
        "ok": True,
        "company": company_key,
        "checked": checked,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "errors": errors[:20],
        "results": results,
        "total_verificado": checked,
        "total_atualizado": updated_count,
    }


def _ops_run_sync_local_order_statuses_all(company_key: str):
    rows = _ops_fetch_local_order_status_rows(company_key, limit=None)
    tiny = _tiny_for_company(company_key)

    checked = 0
    updated_total = 0
    errors = []
    last_result = None

    _ops_sync_progress_update(
        running=True,
        started_at=_now().isoformat(),
        finished_at=None,
        updated_total=0,
        checked_total=0,
        rounds_completed=0,
        last_error="",
        last_result=None,
        company=company_key,
    )

    try:
        for row in rows:
            checked += 1
            try:
                result = _ops_run_sync_one_local_order_status(tiny, company_key, row)
                last_result = result
                if result.get("updated"):
                    updated_total += 1
                if not result.get("ok") and result.get("error"):
                    errors.append({
                        "quote_id": row.get("quote_id"),
                        "tiny_order_id": row.get("tiny_order_id"),
                        "error": result.get("error"),
                    })
                    _ops_sync_progress_update(last_error=str(result.get("error") or ""))
                _ops_sync_progress_update(
                    checked_total=checked,
                    updated_total=updated_total,
                    rounds_completed=checked,
                    last_result=result,
                )
            except Exception as e:
                errors.append({
                    "quote_id": row.get("quote_id"),
                    "tiny_order_id": row.get("tiny_order_id"),
                    "error": str(e),
                })
                _ops_sync_progress_update(
                    checked_total=checked,
                    updated_total=updated_total,
                    rounds_completed=checked,
                    last_error=str(e),
                )
    finally:
        _ops_sync_progress_update(
            running=False,
            finished_at=_now().isoformat(),
            checked_total=checked,
            updated_total=updated_total,
            last_result=last_result,
        )

    return {
        "ok": True,
        "company": company_key,
        "checked": checked,
        "updated_count": updated_total,
        "errors": errors[:20],
        "last_result": last_result,
        "total_verificado": checked,
        "total_atualizado": updated_total,
    }


def _ops_find_local_order_row(company_key: str, q_norm: str):
    q_trim = str(q_norm or "").strip()
    if not q_trim:
        return None

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    q.quote_id,
                    q.quote_number,
                    q.company_key,
                    q.tiny_order_id,
                    q.tiny_order_number,
                    q.status,
                    q.internal_status,
                    q.client_snapshot,
                    q.seller_name,
                    q.shipping_method_name,
                    q.freight_method_name,
                    q.created_at,
                    q.updated_at
                FROM erp.quotes q
                WHERE q.company_key=%s
                  AND (
                        CAST(q.quote_id AS TEXT) = %s OR
                        CAST(q.quote_number AS TEXT) = %s OR
                        CAST(q.tiny_order_id AS TEXT) = %s OR
                        CAST(q.tiny_order_number AS TEXT) = %s
                  )
                ORDER BY q.updated_at DESC NULLS LAST, q.created_at DESC NULLS LAST
                LIMIT 1
                """,
                (company_key, q_trim, q_trim, q_trim, q_trim),
            )
            return cur.fetchone()


def _ops_list_local_tiny_order_rows(
    company_key: str,
    *,
    status: str = "",
    search: str = "",
    limit: Optional[int] = None,
    offset: int = 0,
):
    status_norm = str(status or "").strip().lower()
    search_norm = str(search or "").strip().lower()

    where = [
        "q.company_key = %s",
        "q.tiny_order_id IS NOT NULL",
    ]
    params: List[Any] = [company_key]

    if status_norm:
        if status_norm in {"a separar", "separando", "separado", "entregue", "cancelado"}:
            if status_norm == "a separar":
                where.append("LOWER(COALESCE(q.internal_status, '')) NOT IN ('preparando envio', 'pronto para envio', 'faturado', 'cancelado')")
            elif status_norm == "separando":
                where.append("LOWER(COALESCE(q.internal_status, '')) = 'preparando envio'")
            elif status_norm == "separado":
                where.append("LOWER(COALESCE(q.internal_status, '')) = 'pronto para envio'")
            elif status_norm == "entregue":
                where.append("LOWER(COALESCE(q.internal_status, '')) = 'faturado'")
            elif status_norm == "cancelado":
                where.append("LOWER(COALESCE(q.internal_status, '')) = 'cancelado'")
        elif status_norm in {"draft", "ordered"}:
            where.append("LOWER(COALESCE(q.status, '')) = %s")
            params.append(status_norm)
        else:
            where.append("LOWER(COALESCE(q.internal_status, '')) = %s")
            params.append(status_norm)

    if search_norm:
        where.append(
            "("
            "LOWER(COALESCE(CAST(q.quote_id AS TEXT), '')) LIKE %s OR "
            "LOWER(COALESCE(CAST(q.quote_number AS TEXT), '')) LIKE %s OR "
            "LOWER(COALESCE(CAST(q.tiny_order_id AS TEXT), '')) LIKE %s OR "
            "LOWER(COALESCE(CAST(q.tiny_order_number AS TEXT), '')) LIKE %s OR "
            "LOWER(COALESCE(q.client_snapshot->>'nome', q.client_snapshot->>'name', '')) LIKE %s OR "
            "LOWER(COALESCE(q.seller_name, '')) LIKE %s OR "
            "LOWER(COALESCE(q.internal_status, '')) LIKE %s OR "
            "LOWER(COALESCE(q.status, '')) LIKE %s"
            ")"
        )
        like = f"%{search_norm}%"
        params.extend([like, like, like, like, like, like, like, like])

    sql = f"""
    SELECT
        q.quote_id,
        q.quote_number,
        q.company_key,
        q.tiny_order_id,
        q.tiny_order_number,
        q.status,
        q.internal_status,
        q.payload,
        q.client_snapshot,
        q.seller_name,
        q.shipping_method_name,
        q.freight_method_name,
        q.created_at,
        q.updated_at
    FROM erp.quotes q
    WHERE {' AND '.join(where)}
    ORDER BY q.updated_at DESC NULLS LAST, q.created_at DESC NULLS LAST
    """
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params.extend([int(limit), int(offset)])

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"SELECT COUNT(*) AS total FROM erp.quotes q WHERE {' AND '.join(where)}",
                params[:-2] if limit is not None else params,
            )
            total = int((cur.fetchone() or {}).get("total") or 0)

    return rows, total


def _quote_insertable_clone_row(source_row: Dict[str, Any], quote_id: str, quote_number: int, company_key: str) -> Dict[str, Any]:
    payload = _from_json(source_row.get("payload"), {}) or {}
    totals = _from_json(source_row.get("totals"), {}) or {}
    client_snapshot = _from_json(source_row.get("client_snapshot"), {}) or {}
    seller_snapshot = _from_json(source_row.get("seller_snapshot"), {}) or {}

    return {
        "quote_id": quote_id,
        "quote_number": quote_number,
        "company_key": company_key,
        "tiny_order_id": None,
        "tiny_order_number": None,
        "status": "draft",
        "internal_status": None,
        "client_id": source_row.get("client_id"),
        "client_snapshot": client_snapshot,
        "seller_id": source_row.get("seller_id"),
        "seller_name": _clean_str(source_row.get("seller_name")),
        "seller_snapshot": seller_snapshot,
        "shipping_method_id": source_row.get("shipping_method_id"),
        "shipping_method_name": source_row.get("shipping_method_name"),
        "freight_method_id": source_row.get("freight_method_id"),
        "freight_method_name": source_row.get("freight_method_name"),
        "payment_method_code": source_row.get("payment_method_code"),
        "payment_method_name": source_row.get("payment_method_name"),
        "payment_meio": source_row.get("payment_meio"),
        "payment_conta": source_row.get("payment_conta"),
        "payment_due_date": source_row.get("payment_due_date"),
        "payment_category": source_row.get("payment_category"),
        "payment_notify": _boolish(source_row.get("payment_notify")),
        "totals": totals,
        "notes": source_row.get("notes"),
        "payload": payload,
    }


def _extract_avg_cost_from_item(item: Dict[str, Any]) -> float:
    raw = _from_json(item.get("raw"), {}) or {}
    candidates = [
        raw.get("preco_custo_medio"),
        (raw.get("produto") or {}).get("preco_custo_medio") if isinstance(raw.get("produto"), dict) else None,
        raw.get("preco_custo"),
        (raw.get("produto") or {}).get("preco_custo") if isinstance(raw.get("produto"), dict) else None,
        item.get("preco_custo_medio"),
        item.get("preco_custo"),
    ]
    for candidate in candidates:
        value = _safe_float(candidate, 0)
        if value > 0:
            return round(value, 6)
    return 0.0


def _normalize_quote_item_financials(item: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(item or {})
    raw = _from_json(row.get("raw"), {}) or {}

    qty = _safe_float(row.get("qty"), _safe_float(row.get("quantity"), 0))
    list_price = _safe_float(row.get("list_price"), 0)
    discount_pct = _safe_float(row.get("discount_pct"), 0)
    unit_price_disc = _safe_float(row.get("unit_price_disc"), 0)
    if unit_price_disc <= 0:
        unit_price_disc = list_price
    unit_price = _safe_float(row.get("unit_price"), unit_price_disc)
    if unit_price <= 0:
        unit_price = unit_price_disc

    line_total = _safe_float(row.get("line_total"), 0)
    if line_total <= 0 and qty > 0 and unit_price_disc > 0:
        line_total = round(qty * unit_price_disc, 2)
    total_price = _safe_float(row.get("total_price"), line_total)
    if total_price <= 0:
        total_price = line_total

    cost_price = _extract_avg_cost_from_item(row)
    average_cost = cost_price
    unit_cost = cost_price
    cost_total = round(qty * cost_price, 2)
    profit = round(line_total - cost_total, 2)
    markup_pct = 0.0
    if cost_price > 0:
        markup_pct = round(((unit_price_disc - cost_price) / cost_price) * 100.0, 2)

    sku = (
        _clean_str(row.get("sku"))
        or _clean_str(row.get("sku_snapshot"))
        or _clean_str(raw.get("sku"))
        or _clean_str(raw.get("codigo"))
        or _clean_str(raw.get("code"))
    )
    nome = (
        _clean_str(row.get("name_snapshot"))
        or _clean_str(raw.get("nome"))
        or _clean_str(raw.get("name"))
        or _clean_str(raw.get("descricao"))
        or _clean_str(raw.get("description"))
    )
    descricao = (
        _clean_str(raw.get("descricao"))
        or _clean_str(raw.get("description"))
        or _clean_str(raw.get("nome"))
        or nome
    )

    out = dict(row)
    out.update(
        {
            "qty": qty,
            "quantity": qty,
            "list_price": list_price,
            "discount_pct": discount_pct,
            "unit_price_disc": unit_price_disc,
            "unit_price": unit_price,
            "line_total": round(line_total, 2),
            "total_price": round(total_price, 2),
            "cost_price": round(cost_price, 6),
            "average_cost": round(average_cost, 6),
            "unit_cost": round(unit_cost, 6),
            "cost_total": round(cost_total, 2),
            "profit": round(profit, 2),
            "markup_pct": round(markup_pct, 2),
            "sku": sku,
            "codigo": sku,
            "nome": nome,
            "descricao": descricao,
            "name_snapshot": _clean_str(row.get("name_snapshot")) or nome,
            "sku_snapshot": _clean_str(row.get("sku_snapshot")) or sku,
            "product_snapshot": raw,
            "raw": raw,
        }
    )
    return out


def _compute_quote_financials(quote: Dict[str, Any], items: List[Dict[str, Any]]):
    quote_out = dict(quote or {})
    normalized_items = [_normalize_quote_item_financials(item) for item in (items or [])]

    sale_total_products = round(sum(_safe_float(item.get("line_total"), 0) for item in normalized_items), 2)
    cost_total_products = round(sum(_safe_float(item.get("cost_total"), 0) for item in normalized_items), 2)
    profit_total_products = round(sum(_safe_float(item.get("profit"), 0) for item in normalized_items), 2)
    markup_total_order = 0.0
    if cost_total_products > 0:
        markup_total_order = round(((sale_total_products - cost_total_products) / cost_total_products) * 100.0, 2)

    totals = _from_json(quote_out.get("totals"), {}) or {}
    total_net = _safe_float(
        totals.get("net")
        or totals.get("total")
        or totals.get("total_net")
        or totals.get("total_amount")
        or quote_out.get("total_net")
        or quote_out.get("total_amount"),
        sale_total_products,
    )
    if total_net <= 0:
        total_net = sale_total_products

    quote_out["sale_total_products"] = sale_total_products
    quote_out["cost_total_products"] = cost_total_products
    quote_out["profit_total_products"] = profit_total_products
    quote_out["markup_total_order"] = markup_total_order
    quote_out["items_total"] = sale_total_products
    quote_out["total"] = total_net
    quote_out["total_net"] = total_net
    quote_out["total_amount"] = total_net

    return quote_out, normalized_items


def _seller_allowed_for_company(company_key: str, seller_name: str) -> bool:
    name = str(seller_name or "").strip().lower()

    if company_key == "parton":
        # Suprimentos não deve mostrar vendedores de Informática
        if "informática" in name or "informatica" in name:
            return False
        return True

    if company_key == "park":
        # Informática não deve mostrar vendedores de Suprimentos
        if "suprimento" in name or "suprimentos" in name or "parton" in name:
            return False
        return True

    return True


def _normalize_payment_code(code: Optional[str]) -> str:
    c = str(code or "").strip().lower()
    aliases = {
        "credito": "cartao_credito",
        "cartao": "cartao_credito",
        "cartao de credito": "cartao_credito",
        "cartão de crédito": "cartao_credito",
        "debito": "cartao_debito",
        "cartao de debito": "cartao_debito",
        "cartão de débito": "cartao_debito",
        "pix": "pix",
        "boleto": "boleto",
        "dinheiro": "dinheiro",
        "cheque": "cheque",
        "link": "link_pagamento",
        "link_pagamento": "link_pagamento",
        "deposito": "deposito",
        "depósito": "deposito",
    }
    return aliases.get(c, c)


PAYMENT_METHODS = {
    "dinheiro": "Dinheiro",
    "cartao_credito": "Cartão de crédito",
    "cartao_debito": "Cartão de débito",
    "pix": "Pix",
    "boleto": "Boleto",
    "cheque": "Cheque",
    "link_pagamento": "Link de pagamento",
    "deposito": "Depósito",
}

PAYMENT_CONTA_PORTADOR_MAP = {
    "suprimento_parton_olist": "(Suprimento)Parton - Olist",
    "suprimento_parton_stone": "(Suprimento)Parton - Stone",
    "park_olist": "(Informática)Park - Olist",
}


def _map_payment_code_for_tiny(code: Optional[str]) -> str:
    code = _normalize_payment_code(code)
    mapping = {
        "cartao_credito": "credito",
        "cartao_debito": "debito",
    }
    return mapping.get(code, code)


def _apply_payment_business_rules(
    method_code: Optional[str],
    meio: Optional[str],
    conta: Optional[str],
    company_key: Optional[str] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    code = _normalize_payment_code(method_code)
    meio_norm = _clean_str(meio)
    conta_norm = _clean_str(conta)
    company = _company_key(company_key or "parton")

    olist_default = "park_olist" if company == "park" else "suprimento_parton_olist"
    stone_default = "park_olist" if company == "park" else "suprimento_parton_stone"

    if code == "link_pagamento":
        return code, "gateway", conta_norm or olist_default

    if code in ("cartao_credito", "credito"):
        return "credito", "gateway", conta_norm or stone_default

    if code in ("cartao_debito", "debito"):
        return "debito", meio_norm or "gateway", conta_norm or stone_default

    return code, meio_norm, conta_norm


def _resolve_portador_nome(payment_conta: Optional[str]) -> Optional[str]:
    conta = (payment_conta or "").strip()
    if not conta:
        return None
    return PAYMENT_CONTA_PORTADOR_MAP.get(conta) or conta


def _assert_payment_conta_company_scope(company_key: str, payment_conta: Optional[str]):
    conta = _clean_str(payment_conta)
    if not conta:
        return
    company_norm = _company_key(company_key)
    if company_norm == "park" and conta.startswith("suprimento_parton_"):
        raise HTTPException(status_code=400, detail="Conta bancária de Suprimentos não pode ser usada na empresa Informática.")
    if company_norm == "parton" and conta.startswith("park_"):
        raise HTTPException(status_code=400, detail="Conta bancária de Informática não pode ser usada na empresa Suprimentos.")


def _resolve_meio_pagamento_tiny(payment_meio: Optional[str], payment_conta: Optional[str]) -> Optional[str]:
    meio = (payment_meio or "").strip().lower()
    if meio == "banco":
        return "Banco"
    if meio == "gateway":
        return "Gateway"
    return None



_OPS_SYNC_PROGRESS = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "updated_total": 0,
    "checked_total": 0,
    "rounds_completed": 0,
    "last_error": "",
    "last_result": None,
    "company": None,
}
_OPS_SYNC_PROGRESS_LOCK = threading.Lock()
_OPS_SYNC_BATCH_LOCK = threading.Lock()


class QuoteItemIn(BaseModel):
    product_id: int
    qty: float = Field(gt=0)
    list_price: float = Field(gt=0)
    discount_pct: float = Field(ge=0, le=MAX_DISCOUNT_PCT)
    unit_price_disc: float = Field(gt=0)


class QuoteCreateIn(BaseModel):
    client_id: int
    seller_id: int
    seller_name: Optional[str] = None
    shipping_method_id: int
    freight_method_id: Optional[int] = None
    payment_method_code: str
    payment_meio: Optional[str] = None
    payment_conta: Optional[str] = None
    payment_due_date: Optional[str] = None
    payment_category: Optional[str] = None
    payment_notify: Optional[bool] = None
    payment_condition: Optional[str] = None
    payment_installments: Optional[List[Dict[str, Any]]] = None
    payment_card_brand: Optional[str] = None
    freight_paid_client: Optional[float] = 0
    freight_paid_company: Optional[float] = 0
    notes: Optional[str] = None
    internal_notes: Optional[str] = None
    internalNotes: Optional[str] = None
    invoice_profile: Optional[str] = "A"
    items: List[QuoteItemIn] = []

PUBLIC_AUTH_PATHS = {
    "/",
    "/index.html",
    "/api/health",
    "/health",
    "/api/auth/login",
    "/auth/login",
    "/api/auth/logout",
    "/auth/logout",
    "/logo.png",
    # Callback público OAuth Tiny V3 — sem auth ERP, protegido por state assinado
    "/api/tiny-v3/oauth/callback",
    "/tiny-v3/oauth/callback",
    "/api/admin/tiny-v3/oauth/callback",
    "/admin/tiny-v3/oauth/callback",
}

PUBLIC_AUTH_PREFIXES = (
    "/assets/",
    "/catalog-images/",
    "/static/",
    "/favicon",
    "/docs",
    "/redoc",
    "/openapi.json",
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_AUTH_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_AUTH_PREFIXES):
        return await call_next(request)

    try:
        user = _auth_user_from_request(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    if not user:
        return JSONResponse(status_code=401, content={"detail": "Não autenticado."})

    request.state.auth_user = user

    if path.startswith(("/api/admin/users", "/admin/users")) and _clean_str(user.get("role")).lower() != "admin":
        return JSONResponse(status_code=403, content={"detail": "Apenas admin."})
    if path.startswith(("/api/admin/settings", "/admin/settings")) and _clean_str(user.get("role")).lower() != "admin":
        return JSONResponse(status_code=403, content={"detail": "Apenas admin."})
    if path.startswith(("/api/admin/dashboard", "/admin/dashboard")) and _clean_str(user.get("role")).lower() != "admin":
        return JSONResponse(status_code=403, content={"detail": "Apenas admin."})
    if path.startswith(("/api/admin/seller-metas", "/admin/seller-metas")) and _clean_str(user.get("role")).lower() != "admin":
        return JSONResponse(status_code=403, content={"detail": "Apenas admin."})

    company = request.query_params.get("company")
    if company:
        try:
            _auth_company_or_default(user, company)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return await call_next(request)


@app.on_event("startup")
def startup():
    _seed_companies()
    _auth_bootstrap()
    _ensure_separation_orders_table()
    _ensure_app_settings_table()
    _ensure_client_wallet_tables()
    _ensure_products_local_first_table()
    _ensure_quotes_tiny_status_sync_columns()
    _ensure_quotes_ordered_at_column()
    _ensure_companies_v3_columns()
    _start_client_wallet_daily_scheduler()


@app.get("/health")
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "app": "TRML ERP Local",
        "mode": "local_postgresql",
        "db": DB_NAME,
        "frontend_dist_exists": os.path.isdir(FRONTEND_DIST),
        "time": _now().isoformat(),
    }


@app.get("/api/me")
@app.get("/me")
def me(request: Request):
    user = _require_auth_user(request)
    public = _auth_public_user_row(user)
    default_company = _auth_user_default_company(user)
    return {
        "ok": True,
        **public,
        "company": default_company,
        "company_key": default_company,
        "access_source": "local_postgresql",
        "is_allowed": bool(public.get("active")) and bool(public.get("companies")),
    }


@app.post("/api/auth/login")
@app.post("/auth/login")
async def auth_login(request: Request):
    body = await request.json()
    login = _clean_str(body.get("login"))
    password = _clean_str(body.get("password"))
    if not login or not password:
        raise HTTPException(status_code=400, detail="Login e senha são obrigatórios.")

    user = _auth_lookup_user_by_login(login)
    if not user or not _auth_password_verify(password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="Login ou senha inválidos.")
    if not bool(user.get("active", True)):
        raise HTTPException(status_code=401, detail="Usuário inativo.")

    token = _auth_encode_token(user)
    public = _auth_public_user_row(user)
    default_company = _auth_user_default_company(user)
    return {
        "ok": True,
        "token": token,
        "user": {
            **public,
            "company": default_company,
            "company_key": default_company,
            "access_source": "local_postgresql",
        },
    }


@app.post("/api/auth/logout")
@app.post("/auth/logout")
def auth_logout(request: Request):
    _auth_user_from_request(request)
    return {"ok": True}


@app.get("/api/seller/context")
@app.get("/seller/context")
def seller_context(request: Request, company: str = "parton"):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    return {
        "ok": True,
        "email": user.get("login"),
        "display_name": user.get("display_name"),
        "is_admin": _clean_str(user.get("role")).lower() == "admin",
        "role": _clean_str(user.get("role")).lower(),
        "company": company_key,
        "company_key": company_key,
        "mapping_source": "local_postgresql",
        "sellers": [],
        "seller_ids": [],
        "primary_seller": None,
        "seller_links": _auth_user_seller_links(user.get("id")),
    }


def _resolve_home_dashboard_period(period: str, date_from: str = "", date_to: str = "") -> Optional[Dict[str, Any]]:
    period_key = _clean_str(period).lower()
    if not period_key:
        return None

    today = dt.datetime.now(CLIENT_WALLET_DAILY_SYNC_TZ).date()

    def _parse_date(value: str, field_name: str) -> dt.date:
        raw = _clean_str(value)
        if not raw:
            raise HTTPException(status_code=400, detail=f"Informe {field_name} no formato YYYY-MM-DD.")
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{field_name} inválido. Use YYYY-MM-DD.")

    if period_key == "today":
        start_date = today
        end_date = today
        label = today.strftime("%d/%m/%Y")
    elif period_key == "last_7_days":
        start_date = today - dt.timedelta(days=6)
        end_date = today
        label = f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
    elif period_key == "current_month":
        start_date = today.replace(day=1)
        end_date = today
        label = f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
    elif period_key == "previous_month":
        first_current_month = today.replace(day=1)
        end_date = first_current_month - dt.timedelta(days=1)
        start_date = end_date.replace(day=1)
        label = f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
    elif period_key == "custom":
        start_date = _parse_date(date_from, "date_from")
        end_date = _parse_date(date_to, "date_to")
        if start_date > end_date:
            raise HTTPException(status_code=400, detail="date_from não pode ser maior que date_to.")
        label = f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
    else:
        raise HTTPException(status_code=400, detail="Período inválido. Use today, last_7_days, current_month, previous_month ou custom.")

    end_exclusive = end_date + dt.timedelta(days=1)
    if (end_exclusive - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Período customizado não pode exceder 366 dias.")

    return {
        "period_key": period_key,
        "start_at": start_date,
        "end_at": end_exclusive,
        "date_from": start_date.isoformat(),
        "date_to": end_date.isoformat(),
        "label": label,
        "source": "created_at",
    }


@app.get("/api/home/dashboard")
@app.get("/home/dashboard")
def home_dashboard(request: Request, company: str = "parton", seller_id: str = "", period: str = "", date_from: str = "", date_to: str = ""):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    scope = _resolve_quote_seller_scope(user, company_key)
    selected_period_filter = _resolve_home_dashboard_period(period, date_from, date_to)

    admin_seller_filter_id = ""
    if scope.get("is_admin"):
        candidate = _clean_str(seller_id)
        if candidate.lower() not in {"", "all", "todos"}:
            admin_seller_filter_id = candidate

    where = ["company_key = %s"]
    params: List[Any] = [company_key]
    if scope.get("is_admin"):
        if admin_seller_filter_id:
            where.append("CAST(seller_id AS TEXT) = %s")
            params.append(admin_seller_filter_id)
    else:
        where.append("CAST(seller_id AS TEXT) = %s")
        params.append(str(scope.get("forced_seller_id")))
    where_sql = " AND ".join(where)

    amount_expr = """
        CASE
          WHEN COALESCE(totals->>'net', '') ~ '^-?[0-9]+(\\.[0-9]+)?$'
          THEN (totals->>'net')::numeric
          ELSE 0
        END
    """
    active_order_sql = "tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) <> 'cancelado'"
    approved_sql = "LOWER(COALESCE(internal_status, '')) = 'aprovado'"
    order_date_expr = "COALESCE(ordered_at, created_at)"
    approved_or_advanced_sql = """
        LOWER(COALESCE(internal_status, '')) <> 'cancelado'
        AND (
          LOWER(COALESCE(internal_status, '')) = 'aprovado'
          OR tiny_order_id IS NOT NULL
          OR LOWER(COALESCE(internal_status, '')) IN ('preparando envio', 'pronto para envio', 'faturado')
        )
    """
    active_order_sql_q = "q.tiny_order_id IS NOT NULL AND LOWER(COALESCE(q.internal_status, '')) <> 'cancelado'"
    approved_sql_q = "LOWER(COALESCE(q.internal_status, '')) = 'aprovado'"
    order_date_expr_q = "COALESCE(q.ordered_at, q.created_at)"
    amount_expr_q = """
        CASE
          WHEN COALESCE(q.totals->>'net', '') ~ '^-?[0-9]+(\\.[0-9]+)?$'
          THEN (q.totals->>'net')::numeric
          ELSE 0
        END
    """
    selected_period_metrics = None
    selected_period_result_payload = None

    def _num(value: Any) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _rate(part: Any, total: Any) -> float:
        total_value = _num(total)
        if not total_value:
            return 0
        return round((_num(part) / total_value) * 100, 2)

    def _item_raw_cost(row: Dict[str, Any]) -> float:
        raw = _from_json(row.get("raw"), {}) or {}
        nested = raw.get("produto") if isinstance(raw.get("produto"), dict) else {}
        for key in (
            "average_cost",
            "custo_medio",
            "preco_custo",
            "price_cost",
            "avg_cost",
            "custo_unitario",
            "cost",
            "unit_cost",
            "preco_custo_medio",
        ):
            value = _safe_float(raw.get(key), None)
            if value is None:
                value = _safe_float(nested.get(key), None)
            if value is not None and value > 0:
                return value
        return 0.0

    def _build_home_dashboard_result_payload(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        items_sales_amount = 0.0
        cost_total = 0.0
        total_items = len(rows)
        items_with_cost = 0

        for row in rows:
            qty = _safe_float(row.get("qty"), 0)
            unit_price = _safe_float(row.get("unit_price_disc"), 0)
            line_total = _safe_float(row.get("line_total"), None)
            if line_total is None:
                line_total = qty * unit_price
            items_sales_amount += line_total

            unit_cost = _item_raw_cost(row)
            if unit_cost <= 0:
                unit_cost = _safe_float(row.get("catalog_average_cost"), 0)
            if unit_cost > 0:
                items_with_cost += 1
            cost_total += qty * unit_cost

        gross_result = items_sales_amount - cost_total
        margin = round((gross_result / items_sales_amount) * 100, 2) if items_sales_amount else 0
        missing_cost_items = total_items - items_with_cost

        return {
            "visible": True,
            "label": "Resultado bruto estimado",
            "period": "month",
            "sales_amount_month": round(items_sales_amount, 2),
            "items_sales_amount_month": round(items_sales_amount, 2),
            "cost_total_month": round(cost_total, 2),
            "gross_result_month": round(gross_result, 2),
            "gross_margin_month": margin,
            "total_items_month": total_items,
            "items_with_cost_month": items_with_cost,
            "missing_cost_items_month": missing_cost_items,
            "cost_coverage_percent_month": _rate(items_with_cost, total_items),
            "is_estimated": True,
            "notes": [
                "Resultado bruto estimado antes de taxas, impostos, fretes, comissões e despesas.",
                "Custo calculado por snapshot local do item e/ou custo médio atual do catálogo.",
                "Não representa lucro líquido.",
            ],
        }

    def _build_home_dashboard_selected_result_payload(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        monthly = _build_home_dashboard_result_payload(rows)
        return {
            "visible": True,
            "cost_total": monthly["cost_total_month"],
            "gross_result": monthly["gross_result_month"],
            "gross_margin": monthly["gross_margin_month"],
            "total_items": monthly["total_items_month"],
            "items_with_cost": monthly["items_with_cost_month"],
            "missing_cost_items": monthly["missing_cost_items_month"],
            "cost_coverage_percent": monthly["cost_coverage_percent_month"],
            "is_estimated": True,
            "notes": monthly["notes"],
        }

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS quotes_today,
                  COUNT(*) FILTER (WHERE created_at >= date_trunc('week', now())) AS quotes_week,
                  COUNT(*) FILTER (WHERE created_at >= date_trunc('month', now())) AS quotes_month,
                  COUNT(*) FILTER (WHERE {approved_sql} AND created_at::date = CURRENT_DATE) AS approved_today,
                  COUNT(*) FILTER (WHERE {approved_sql} AND created_at >= date_trunc('week', now())) AS approved_week,
                  COUNT(*) FILTER (WHERE {approved_sql} AND created_at >= date_trunc('month', now())) AS approved_month,
                  COUNT(*) FILTER (WHERE {approved_or_advanced_sql} AND created_at >= date_trunc('month', now())) AS approved_or_advanced_month,
                  COUNT(*) FILTER (WHERE {active_order_sql} AND {order_date_expr}::date = CURRENT_DATE) AS orders_today,
                  COUNT(*) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= date_trunc('week', now())) AS orders_week,
                  COUNT(*) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= date_trunc('month', now())) AS orders_month,
                  COALESCE(SUM({amount_expr}) FILTER (WHERE {active_order_sql} AND {order_date_expr}::date = CURRENT_DATE), 0) AS amount_today,
                  COALESCE(SUM({amount_expr}) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= date_trunc('week', now())), 0) AS amount_week,
                  COALESCE(SUM({amount_expr}) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= date_trunc('month', now())), 0) AS amount_month,
                  COUNT(*) FILTER (WHERE LOWER(COALESCE(status, '')) = 'draft') AS quotes_draft,
                  COUNT(*) FILTER (WHERE tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) = 'em aberto') AS orders_open,
                  COUNT(*) FILTER (WHERE tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) = 'aprovado') AS orders_approved,
                  COUNT(*) FILTER (WHERE tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) = 'faturado' AND updated_at >= date_trunc('month', now())) AS orders_invoiced_month,
                  COUNT(*) FILTER (WHERE tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) = 'cancelado' AND updated_at >= date_trunc('month', now())) AS orders_cancelled_month,
                  COUNT(*) FILTER (WHERE tiny_order_id IS NOT NULL AND {order_date_expr} >= date_trunc('month', now())) AS orders_total_by_period_month,
                  COUNT(*) FILTER (WHERE tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) = 'cancelado' AND {order_date_expr} >= date_trunc('month', now())) AS cancelled_by_period_month,
                  COUNT(*) FILTER (WHERE LOWER(COALESCE(status, '')) = 'draft' OR LOWER(COALESCE(internal_status, '')) = 'rascunho') AS status_draft,
                  COUNT(*) FILTER (WHERE LOWER(COALESCE(internal_status, '')) = 'em aberto') AS status_open,
                  COUNT(*) FILTER (WHERE LOWER(COALESCE(internal_status, '')) = 'aprovado') AS status_approved,
                  COUNT(*) FILTER (WHERE tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) NOT IN ('cancelado', 'faturado')) AS status_ordered,
                  COUNT(*) FILTER (WHERE LOWER(COALESCE(internal_status, '')) = 'faturado') AS status_invoiced,
                  COUNT(*) FILTER (WHERE LOWER(COALESCE(internal_status, '')) = 'cancelado') AS status_cancelled
                FROM erp.quotes
                WHERE {where_sql}
                """,
                params,
            )
            metrics = dict(cur.fetchone() or {})

            cur.execute(
                f"""
                WITH days AS (
                  SELECT generate_series(CURRENT_DATE - INTERVAL '6 days', CURRENT_DATE, INTERVAL '1 day')::date AS day
                ),
                scoped AS (
                  SELECT *
                  FROM erp.quotes
                  WHERE {where_sql}
                )
                SELECT
                  d.day::text AS date,
                  to_char(d.day, 'DD/MM') AS label,
                  COUNT(q.quote_id) FILTER (WHERE q.created_at::date = d.day) AS quotes_created,
                  COUNT(q.quote_id) FILTER (WHERE {approved_sql_q} AND q.created_at::date = d.day) AS quotes_approved,
                  COUNT(q.quote_id) FILTER (WHERE {active_order_sql_q} AND {order_date_expr_q}::date = d.day) AS orders,
                  COALESCE(SUM({amount_expr_q}) FILTER (WHERE {active_order_sql_q} AND {order_date_expr_q}::date = d.day), 0) AS amount
                FROM days d
                LEFT JOIN scoped q ON (
                  q.created_at::date = d.day
                  OR {order_date_expr_q}::date = d.day
                )
                GROUP BY d.day
                ORDER BY d.day
                """,
                params,
            )
            series_last_7_days = []
            for row in cur.fetchall():
                item = dict(row)
                item_orders = int(item.get("orders") or 0)
                item_amount = _num(item.get("amount"))
                series_last_7_days.append({
                    "date": item.get("date"),
                    "label": item.get("label"),
                    "quotes_created": int(item.get("quotes_created") or 0),
                    "quotes_approved": int(item.get("quotes_approved") or 0),
                    "orders": item_orders,
                    "amount": item_amount,
                    "average_ticket": round(item_amount / item_orders, 2) if item_orders else 0,
                })

            cur.execute(
                f"""
                SELECT quote_id, quote_number, tiny_order_number,
                       COALESCE(client_snapshot->>'nome', client_snapshot->>'name', '') AS client_name,
                       seller_name,
                       {amount_expr} AS total,
                       status, internal_status, created_at
                FROM erp.quotes
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT 5
                """,
                params,
            )
            recent = [dict(row) for row in cur.fetchall()]

            result_payload = None
            if scope.get("is_admin"):
                result_params: List[Any] = [company_key]
                admin_result_seller_filter_sql = ""
                if admin_seller_filter_id:
                    admin_result_seller_filter_sql = "AND CAST(q.seller_id AS TEXT) = %s"
                    result_params.append(admin_seller_filter_id)
                cur.execute(
                    f"""
                    SELECT
                      qi.qty,
                      qi.unit_price_disc,
                      qi.line_total,
                      qi.raw,
                      pc.average_cost AS catalog_average_cost
                    FROM erp.quotes q
                    JOIN erp.quote_items qi ON qi.quote_id = q.quote_id
                    LEFT JOIN LATERAL (
                      SELECT pc.average_cost
                      FROM erp.product_catalog pc
                      WHERE pc.company_key = q.company_key
                        AND (
                          (
                            pc.tiny_product_id IS NOT NULL
                            AND pc.tiny_product_id <> ''
                            AND CAST(qi.product_id AS TEXT) = pc.tiny_product_id
                          )
                          OR (
                            pc.sku IS NOT NULL
                            AND pc.sku <> ''
                            AND LOWER(COALESCE(qi.sku_snapshot, qi.raw->>'sku', qi.raw->>'codigo', '')) = LOWER(pc.sku)
                          )
                        )
                      ORDER BY
                        CASE
                          WHEN pc.tiny_product_id IS NOT NULL
                           AND pc.tiny_product_id <> ''
                           AND CAST(qi.product_id AS TEXT) = pc.tiny_product_id
                          THEN 0
                          ELSE 1
                        END,
                        pc.id DESC
                      LIMIT 1
                    ) pc ON TRUE
                    WHERE q.company_key = %s
                      AND q.tiny_order_id IS NOT NULL
                      AND LOWER(COALESCE(q.internal_status, '')) <> 'cancelado'
                      AND {order_date_expr_q} >= date_trunc('month', now())
                      {admin_result_seller_filter_sql}
                    """,
                    result_params,
                )
                result_rows = [dict(row) for row in cur.fetchall()]
                result_payload = _build_home_dashboard_result_payload(result_rows)

            if selected_period_filter:
                cur.execute(
                    f"""
                    SELECT
                      COUNT(*) FILTER (WHERE created_at >= %s AND created_at < %s) AS quotes_created,
                      COUNT(*) FILTER (WHERE {approved_sql} AND created_at >= %s AND created_at < %s) AS quotes_approved,
                      COUNT(*) FILTER (WHERE {approved_or_advanced_sql} AND created_at >= %s AND created_at < %s) AS approved_or_advanced,
                      COUNT(*) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= %s AND {order_date_expr} < %s) AS orders,
                      COALESCE(SUM({amount_expr}) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= %s AND {order_date_expr} < %s), 0) AS amount,
                      COUNT(*) FILTER (
                        WHERE tiny_order_id IS NOT NULL
                          AND {order_date_expr} >= %s
                          AND {order_date_expr} < %s
                      ) AS orders_total,
                      COUNT(*) FILTER (
                        WHERE tiny_order_id IS NOT NULL
                          AND LOWER(COALESCE(internal_status, '')) = 'cancelado'
                          AND {order_date_expr} >= %s
                          AND {order_date_expr} < %s
                      ) AS cancelled
                    FROM erp.quotes
                    WHERE {where_sql}
                    """,
                    [
                        selected_period_filter["start_at"], selected_period_filter["end_at"],
                        selected_period_filter["start_at"], selected_period_filter["end_at"],
                        selected_period_filter["start_at"], selected_period_filter["end_at"],
                        selected_period_filter["start_at"], selected_period_filter["end_at"],
                        selected_period_filter["start_at"], selected_period_filter["end_at"],
                        selected_period_filter["start_at"], selected_period_filter["end_at"],
                        selected_period_filter["start_at"], selected_period_filter["end_at"],
                    ] + params,
                )
                selected_period_metrics = dict(cur.fetchone() or {})

                if scope.get("is_admin"):
                    selected_result_params: List[Any] = [company_key]
                    selected_result_seller_filter_sql = ""
                    if admin_seller_filter_id:
                        selected_result_seller_filter_sql = "AND CAST(q.seller_id AS TEXT) = %s"
                        selected_result_params.append(admin_seller_filter_id)
                    selected_result_params.extend([
                        selected_period_filter["start_at"],
                        selected_period_filter["end_at"],
                    ])
                    cur.execute(
                        f"""
                        SELECT
                          qi.qty,
                          qi.unit_price_disc,
                          qi.line_total,
                          qi.raw,
                          pc.average_cost AS catalog_average_cost
                        FROM erp.quotes q
                        JOIN erp.quote_items qi ON qi.quote_id = q.quote_id
                        LEFT JOIN LATERAL (
                          SELECT pc.average_cost
                          FROM erp.product_catalog pc
                          WHERE pc.company_key = q.company_key
                            AND (
                              (
                                pc.tiny_product_id IS NOT NULL
                                AND pc.tiny_product_id <> ''
                                AND CAST(qi.product_id AS TEXT) = pc.tiny_product_id
                              )
                              OR (
                                pc.sku IS NOT NULL
                                AND pc.sku <> ''
                                AND LOWER(COALESCE(qi.sku_snapshot, qi.raw->>'sku', qi.raw->>'codigo', '')) = LOWER(pc.sku)
                              )
                            )
                          ORDER BY
                            CASE
                              WHEN pc.tiny_product_id IS NOT NULL
                               AND pc.tiny_product_id <> ''
                               AND CAST(qi.product_id AS TEXT) = pc.tiny_product_id
                              THEN 0
                              ELSE 1
                            END,
                            pc.id DESC
                          LIMIT 1
                        ) pc ON TRUE
                        WHERE q.company_key = %s
                          AND q.tiny_order_id IS NOT NULL
                          AND LOWER(COALESCE(q.internal_status, '')) <> 'cancelado'
                          {selected_result_seller_filter_sql}
                          AND {order_date_expr_q} >= %s
                          AND {order_date_expr_q} < %s
                        """,
                        selected_result_params,
                    )
                    selected_result_rows = [dict(row) for row in cur.fetchall()]
                    selected_period_result_payload = _build_home_dashboard_selected_result_payload(selected_result_rows)

    orders_month = int(metrics.get("orders_month") or 0)
    orders_today = int(metrics.get("orders_today") or 0)
    orders_week = int(metrics.get("orders_week") or 0)
    quotes_month = int(metrics.get("quotes_month") or 0)
    approved_month = int(metrics.get("approved_month") or 0)
    approved_or_advanced_month = int(metrics.get("approved_or_advanced_month") or 0)
    cancelled_month = int(metrics.get("orders_cancelled_month") or 0)
    orders_total_by_period_month = int(metrics.get("orders_total_by_period_month") or 0)
    cancelled_by_period_month = int(metrics.get("cancelled_by_period_month") or 0)
    amount_today = _num(metrics.get("amount_today"))
    amount_week = _num(metrics.get("amount_week"))
    amount_month = _num(metrics.get("amount_month"))
    if scope.get("is_admin"):
        scope_payload = {"type": "admin", "seller_filter": None}
        if admin_seller_filter_id:
            scope_payload["seller_filter"] = {"seller_id": admin_seller_filter_id}
    else:
        scope_payload = {
            "type": "seller",
            "seller_id": str(scope.get("forced_seller_id")),
            "seller_name": _clean_str(scope.get("forced_seller_name")),
        }

    payload = {
        "ok": True,
        "company_key": company_key,
        "scope": scope_payload,
        "periods": {
            "today": {
                "quotes_created": int(metrics.get("quotes_today") or 0),
                "quotes_approved": int(metrics.get("approved_today") or 0),
                "orders": int(metrics.get("orders_today") or 0),
                "amount": amount_today,
                "average_ticket": round(amount_today / orders_today, 2) if orders_today else 0,
            },
            "week": {
                "quotes_created": int(metrics.get("quotes_week") or 0),
                "quotes_approved": int(metrics.get("approved_week") or 0),
                "orders": orders_week,
                "amount": amount_week,
                "average_ticket": round(amount_week / orders_week, 2) if orders_week else 0,
            },
            "month": {
                "quotes_created": quotes_month,
                "quotes_approved": approved_month,
                "orders": orders_month,
                "amount": amount_month,
                "average_ticket": round(amount_month / orders_month, 2) if orders_month else 0,
            },
        },
        "sales": {
            "amount_today": amount_today,
            "amount_week": amount_week,
            "amount_month": amount_month,
            "average_ticket_today": round(amount_today / orders_today, 2) if orders_today else 0,
            "average_ticket_week": round(amount_week / orders_week, 2) if orders_week else 0,
            "average_ticket_month": round(amount_month / orders_month, 2) if orders_month else 0,
        },
        "quotes": {
            "draft": int(metrics.get("quotes_draft") or 0),
            "open": int(metrics.get("orders_open") or 0),
            "approved": int(metrics.get("orders_approved") or 0),
            "approved_today": int(metrics.get("approved_today") or 0),
            "approved_week": int(metrics.get("approved_week") or 0),
            "approved_month": approved_month,
        },
        "orders": {
            "open": int(metrics.get("orders_open") or 0),
            "approved": int(metrics.get("orders_approved") or 0),
            "invoiced_month": int(metrics.get("orders_invoiced_month") or 0),
            "cancelled_month": int(metrics.get("orders_cancelled_month") or 0),
        },
        "status_breakdown": {
            "draft": int(metrics.get("status_draft") or 0),
            "open": int(metrics.get("status_open") or 0),
            "approved": int(metrics.get("status_approved") or 0),
            "ordered": int(metrics.get("status_ordered") or 0),
            "invoiced": int(metrics.get("status_invoiced") or 0),
            "cancelled": int(metrics.get("status_cancelled") or 0),
        },
        "conversion": {
            "month_quote_to_order_rate": _rate(orders_month, quotes_month),
            "month_approval_rate": _rate(approved_or_advanced_month, quotes_month),
            "month_cancel_rate": _rate(cancelled_by_period_month, orders_total_by_period_month),
        },
        "series": {
            "last_7_days": series_last_7_days,
        },
        "recent": recent,
        "notes": {
            "quotes_period_source": "created_at",
            "sales_period_source": "ordered_at_with_created_at_fallback",
            "sales_definition": "tiny_order_id IS NOT NULL AND internal_status <> 'Cancelado'",
            "approval_rate_definition": "Orçamentos aprovados ou que avançaram para pedido/status posterior sobre orçamentos criados no mês.",
            "conversion_cancel_rate_base": "orders_total_by_period_month",
        },
    }
    if selected_period_filter:
        selected_quotes_created = int(selected_period_metrics.get("quotes_created") or 0)
        selected_orders = int(selected_period_metrics.get("orders") or 0)
        selected_amount = _num(selected_period_metrics.get("amount"))
        selected_approved_or_advanced = int(selected_period_metrics.get("approved_or_advanced") or 0)
        selected_cancelled = int(selected_period_metrics.get("cancelled") or 0)
        selected_orders_total = int(selected_period_metrics.get("orders_total") or 0)

        payload["selected_period"] = {
            "filter": {
                "period": selected_period_filter["period_key"],
                "date_from": selected_period_filter["date_from"],
                "date_to": selected_period_filter["date_to"],
                "source": selected_period_filter["source"],
                "label": selected_period_filter["label"],
            },
            "quotes_created": selected_quotes_created,
            "quotes_approved": int(selected_period_metrics.get("quotes_approved") or 0),
            "approved_or_advanced": selected_approved_or_advanced,
            "orders": selected_orders,
            "amount": selected_amount,
            "average_ticket": round(selected_amount / selected_orders, 2) if selected_orders else 0,
            "conversion": {
                "quote_to_order_rate": _rate(selected_orders, selected_quotes_created),
                "approval_rate": _rate(selected_approved_or_advanced, selected_quotes_created),
                "cancel_rate": _rate(selected_cancelled, selected_orders_total),
            },
            "result": selected_period_result_payload or {"visible": False},
        }
        payload["notes"].update({
            "selected_period_available": True,
            "selected_period_quotes_source": "created_at",
            "selected_period_sales_source": "ordered_at_with_created_at_fallback",
            "selected_period_sales_date_definition": "Vendas do período usam ordered_at; registros legados sem ordered_at usam created_at.",
        })
    if result_payload is not None:
        payload["result"] = result_payload
    return payload


@app.get("/api/home/dashboard/hourly")
@app.get("/home/dashboard/hourly")
def home_dashboard_hourly(request: Request, company: str = "parton", date: str = "", seller_id: str = ""):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    scope = _resolve_quote_seller_scope(user, company_key)

    date_text = _clean_str(date)
    try:
        target_date = dt.date.fromisoformat(date_text)
    except Exception:
        raise HTTPException(status_code=400, detail="Data inválida. Use YYYY-MM-DD.")

    admin_seller_filter_id = ""
    if scope.get("is_admin"):
        candidate = _clean_str(seller_id)
        if candidate.lower() not in {"", "all", "todos"}:
            admin_seller_filter_id = candidate

    where = ["company_key = %s"]
    params: List[Any] = [company_key]
    if scope.get("is_admin"):
        if admin_seller_filter_id:
            where.append("CAST(seller_id AS TEXT) = %s")
            params.append(admin_seller_filter_id)
    else:
        where.append("CAST(seller_id AS TEXT) = %s")
        params.append(str(scope.get("forced_seller_id")))
    where_sql = " AND ".join(where)

    if scope.get("is_admin"):
        scope_payload = {"type": "admin", "seller_filter": None}
        if admin_seller_filter_id:
            scope_payload["seller_filter"] = {"seller_id": admin_seller_filter_id}
    else:
        scope_payload = {
            "type": "seller",
            "seller_id": str(scope.get("forced_seller_id")),
            "seller_name": _clean_str(scope.get("forced_seller_name")),
        }

    amount_expr = """
        CASE
          WHEN COALESCE(totals->>'net', '') ~ '^-?[0-9]+(\\.[0-9]+)?$'
          THEN (totals->>'net')::numeric
          ELSE 0
        END
    """
    active_order_sql = "tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) <> 'cancelado'"
    order_date_expr = "COALESCE(ordered_at, created_at)"
    start_dt = dt.datetime.combine(target_date, dt.time.min)
    end_dt = start_dt + dt.timedelta(days=1)
    query_params = [*params, start_dt, end_dt]

    def _num(value: Any) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  EXTRACT(HOUR FROM {order_date_expr})::int AS hour,
                  COUNT(*) AS orders,
                  COALESCE(SUM({amount_expr}), 0) AS amount
                FROM erp.quotes
                WHERE {where_sql}
                  AND {active_order_sql}
                  AND {order_date_expr} >= %s
                  AND {order_date_expr} < %s
                GROUP BY EXTRACT(HOUR FROM {order_date_expr})::int
                ORDER BY hour
                """,
                query_params,
            )
            rows = [dict(row) for row in cur.fetchall()]

    by_hour = {int(row.get("hour") or 0): row for row in rows}
    hours = []
    total_orders = 0
    total_amount = 0.0
    for hour in range(24):
        row = by_hour.get(hour, {})
        orders = int(row.get("orders") or 0)
        amount = _num(row.get("amount"))
        total_orders += orders
        total_amount += amount
        hours.append({
            "hour": hour,
            "label": f"{hour:02d}h",
            "orders": orders,
            "amount": round(amount, 2),
            "average_ticket": round(amount / orders, 2) if orders else 0,
        })

    peak_hour = None
    non_zero_hours = [item for item in hours if item.get("orders") or item.get("amount")]
    if non_zero_hours:
        peak = max(non_zero_hours, key=lambda item: (item.get("amount") or 0, item.get("orders") or 0))
        peak_hour = {
            "hour": peak["hour"],
            "label": peak["label"],
            "orders": peak["orders"],
            "amount": peak["amount"],
        }

    return {
        "ok": True,
        "company_key": company_key,
        "date": target_date.isoformat(),
        "scope": scope_payload,
        "summary": {
            "orders": total_orders,
            "amount": round(total_amount, 2),
            "average_ticket": round(total_amount / total_orders, 2) if total_orders else 0,
            "peak_hour": peak_hour,
        },
        "hours": hours,
        "notes": {
            "sales_period_source": "ordered_at_with_created_at_fallback",
            "sales_definition": "tiny_order_id IS NOT NULL AND internal_status <> 'Cancelado'",
        },
    }


@app.get("/api/admin/dashboard/sales-performance")
@app.get("/admin/dashboard/sales-performance")
def admin_dashboard_sales_performance(
    request: Request,
    company: str = "parton",
    period: str = "",
    date_from: str = "",
    date_to: str = "",
    year_month: str = "",
):
    """Performance de vendas por vendedor (admin-only) com metas mensais.

    Dupla proteção: o `auth_middleware` nega não-admins nos prefixos
    `/api/admin/dashboard` e `/admin/dashboard` (deny-by-default) e o
    `_admin_require_user` no handler é a defesa em profundidade.
    As expressões de venda/valor batem com /home/dashboard (mesmas strings SQL) para
    manter consistência entre o dashboard executivo e os cards da home.
    """
    user = _admin_require_user(request)
    company_key = _auth_company_or_default(user, company)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")
    _ensure_seller_metas_table()
    _ensure_user_seller_links_table()

    pf = _resolve_home_dashboard_period(period or "current_month", date_from, date_to)

    override_ym = _clean_str(year_month)
    if override_ym:
        override_ym = _seller_metas_validate_year_month(override_ym)

    # Metas são mensais e comparadas SEM rateio (pro-rata). Só estão disponíveis quando
    # há um mês de referência inequívoco: um year_month explícito OU um período contido
    # em um único mês-calendário.
    start_date = pf["start_at"]
    end_inclusive = pf["end_at"] - dt.timedelta(days=1)
    single_calendar_month = (
        start_date.year == end_inclusive.year and start_date.month == end_inclusive.month
    )
    if override_ym:
        meta_year_month = override_ym
        meta_available = True
    elif single_calendar_month:
        meta_year_month = start_date.strftime("%Y-%m")
        meta_available = True
    else:
        meta_year_month = None
        meta_available = False

    amount_expr = """
        CASE
          WHEN COALESCE(totals->>'net', '') ~ '^-?[0-9]+(\\.[0-9]+)?$'
          THEN (totals->>'net')::numeric
          ELSE 0
        END
    """
    active_order_sql = "tiny_order_id IS NOT NULL AND LOWER(COALESCE(internal_status, '')) <> 'cancelado'"
    order_date_expr = "COALESCE(ordered_at, created_at)"

    start_at = pf["start_at"]
    end_at = pf["end_at"]
    # O OR das duas janelas é necessário: orçamento conta por created_at, venda por
    # order_date_expr — uma quote criada mês passado e pedida neste período precisa
    # entrar na varredura para contar como venda do vendedor.
    agg_sql = f"""
        SELECT
          COALESCE(NULLIF(CAST(seller_id AS TEXT), ''), '__none__') AS seller_key,
          (ARRAY_AGG(COALESCE(seller_name, '') ORDER BY (COALESCE(seller_name, '') <> '') DESC, updated_at DESC NULLS LAST))[1] AS seller_name,
          COUNT(*) FILTER (WHERE created_at >= %s AND created_at < %s) AS quotes_created,
          COUNT(*) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= %s AND {order_date_expr} < %s) AS orders,
          COALESCE(SUM({amount_expr}) FILTER (WHERE {active_order_sql} AND {order_date_expr} >= %s AND {order_date_expr} < %s), 0) AS amount
        FROM erp.quotes
        WHERE company_key = %s
          AND ((created_at >= %s AND created_at < %s) OR ({order_date_expr} >= %s AND {order_date_expr} < %s))
        GROUP BY 1
    """
    agg_params = [
        start_at, end_at,   # quotes_created (created_at)
        start_at, end_at,   # orders (order_date_expr)
        start_at, end_at,   # amount (order_date_expr)
        company_key,        # company filter
        start_at, end_at,   # created_at window
        start_at, end_at,   # order_date_expr window
    ]

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(agg_sql, agg_params)
            agg_rows = [dict(r) for r in cur.fetchall()]

            # Nomes confiáveis e company-scoped (mesma query de admin_company_sellers).
            cur.execute(
                """
                SELECT DISTINCT ON (tiny_seller_id)
                       tiny_seller_id AS seller_id,
                       tiny_seller_name AS seller_name
                FROM erp.user_seller_links
                WHERE company_key = %s
                  AND active = TRUE
                  AND COALESCE(tiny_seller_id, '') <> ''
                  AND COALESCE(tiny_seller_name, '') <> ''
                ORDER BY tiny_seller_id, tiny_seller_name
                """,
                (company_key,),
            )
            link_names = {
                _clean_str(r["seller_id"]): _clean_str(r["seller_name"]) for r in cur.fetchall()
            }

            metas: Dict[str, Dict[str, Any]] = {}
            if meta_available:
                cur.execute(
                    """
                    SELECT seller_id, seller_name, meta_amount
                    FROM erp.seller_metas
                    WHERE company_key = %s AND year_month = %s
                    """,
                    (company_key, meta_year_month),
                )
                for r in cur.fetchall():
                    metas[_clean_str(r.get("seller_id"))] = dict(r)

    def _resolve_seller_name(seller_key: str, agg_name: str = "", meta_name: str = "") -> str:
        if seller_key == "__none__":
            return "Sem vendedor"
        # Pick do ARRAY_AGG sobreposto pelo nome do user_seller_links (fonte confiável),
        # com fallback para o nome da meta e, por fim, "Vendedor {id}".
        name = link_names.get(seller_key) or _clean_str(agg_name) or _clean_str(meta_name)
        return name or f"Vendedor {seller_key}"

    entries: Dict[str, Dict[str, Any]] = {}
    for row in agg_rows:
        seller_key = row.get("seller_key")
        quotes_created = int(row.get("quotes_created") or 0)
        orders = int(row.get("orders") or 0)
        amount = round(_safe_float(row.get("amount"), 0.0), 2)
        # A janela do WHERE inclui pedidos cuja order_date cai no período mesmo se
        # cancelados/criados fora — descarta linhas sem atividade real (inclui o
        # bucket '__none__', que só entra se houver atividade).
        if quotes_created <= 0 and orders <= 0 and amount == 0:
            continue
        entries[seller_key] = {
            "seller_key": seller_key,
            "seller_name": _resolve_seller_name(seller_key, row.get("seller_name")),
            "amount": amount,
            "orders": orders,
            "quotes_created": quotes_created,
        }

    # Vendedor com meta e ZERO atividade → linha zerada para o gap aparecer no gráfico.
    if meta_available:
        for sid, meta in metas.items():
            if not sid or sid == "__none__" or sid in entries:
                continue
            entries[sid] = {
                "seller_key": sid,
                "seller_name": _resolve_seller_name(sid, "", meta.get("seller_name")),
                "amount": 0.0,
                "orders": 0,
                "quotes_created": 0,
            }

    # Totals somados em Python a partir das linhas dos vendedores (consistência garantida
    # com a tabela; sem segunda query de totais).
    total_amount = round(sum(e["amount"] for e in entries.values()), 2)
    total_orders = sum(e["orders"] for e in entries.values())
    total_quotes = sum(e["quotes_created"] for e in entries.values())

    sellers: List[Dict[str, Any]] = []
    for e in entries.values():
        seller_key = e["seller_key"]
        is_none = seller_key == "__none__"
        amount = e["amount"]
        orders = e["orders"]
        quotes_created = e["quotes_created"]

        conversion_rate = round((orders / quotes_created) * 100, 2) if quotes_created else 0
        average_ticket = round(amount / orders, 2) if orders else 0
        share_percent = round((amount / total_amount) * 100, 2) if total_amount else 0

        has_meta = False
        meta_amount = None
        meta_attainment_percent = None
        if meta_available and not is_none and seller_key in metas:
            has_meta = True
            meta_amount = round(_safe_float(metas[seller_key].get("meta_amount"), 0.0), 2)
            # meta_amount armazenada = 0 → atingimento indefinido (null), mas has_meta=True.
            if meta_amount > 0:
                meta_attainment_percent = round((amount / meta_amount) * 100, 2)

        sellers.append({
            "seller_id": None if is_none else seller_key,
            "seller_name": e["seller_name"],
            "amount": amount,
            "orders": orders,
            "quotes_created": quotes_created,
            "conversion_rate": conversion_rate,
            "average_ticket": average_ticket,
            "share_percent": share_percent,
            "meta_amount": meta_amount,
            "meta_attainment_percent": meta_attainment_percent,
            "has_meta": has_meta,
        })

    # Ordena por amount DESC; empate → nome (asc) para determinismo.
    sellers.sort(key=lambda s: (-s["amount"], _clean_str(s["seller_name"]).lower()))

    real_sellers = [s for s in sellers if s["seller_id"] is not None]

    top_seller = None
    if total_amount:
        top_candidates = [s for s in real_sellers if s["amount"] > 0]
        if top_candidates:
            best = top_candidates[0]  # já ordenado por amount DESC, nome ASC
            top_seller = {
                "seller_id": best["seller_id"],
                "seller_name": best["seller_name"],
                "amount": best["amount"],
                "share_percent": best["share_percent"],
            }

    def _pick_highlight(candidates: List[Dict[str, Any]], metric: str) -> Optional[Dict[str, Any]]:
        # Empate no métrico → maior amount, depois nome (asc).
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda s: (-s[metric], -s["amount"], _clean_str(s["seller_name"]).lower()),
        )[0]

    best_conversion = _pick_highlight([s for s in real_sellers if s["quotes_created"] > 0], "conversion_rate")
    best_average_ticket = _pick_highlight([s for s in real_sellers if s["orders"] > 0], "average_ticket")
    most_quotes = _pick_highlight([s for s in real_sellers if s["quotes_created"] > 0], "quotes_created")

    highlights = {
        "best_conversion": {
            "seller_id": best_conversion["seller_id"],
            "seller_name": best_conversion["seller_name"],
            "conversion_rate": best_conversion["conversion_rate"],
            "orders": best_conversion["orders"],
            "quotes_created": best_conversion["quotes_created"],
        } if best_conversion else None,
        "best_average_ticket": {
            "seller_id": best_average_ticket["seller_id"],
            "seller_name": best_average_ticket["seller_name"],
            "average_ticket": best_average_ticket["average_ticket"],
            "orders": best_average_ticket["orders"],
            "amount": best_average_ticket["amount"],
        } if best_average_ticket else None,
        "most_quotes": {
            "seller_id": most_quotes["seller_id"],
            "seller_name": most_quotes["seller_name"],
            "quotes_created": most_quotes["quotes_created"],
            "orders": most_quotes["orders"],
        } if most_quotes else None,
    }

    meta_total = None
    sellers_with_meta = 0
    if meta_available:
        meta_total = round(sum(_safe_float(m.get("meta_amount"), 0.0) for m in metas.values()), 2)
        sellers_with_meta = len(metas)

    totals_meta_attainment = None
    if meta_available and meta_total and meta_total > 0:
        totals_meta_attainment = round((total_amount / meta_total) * 100, 2)

    return {
        "ok": True,
        "company_key": company_key,
        "filter": {
            "period": pf["period_key"],
            "date_from": pf["date_from"],
            "date_to": pf["date_to"],
            "source": pf["source"],
            "label": pf["label"],
        },
        "meta": {
            "year_month": meta_year_month,
            "available": meta_available,
            "meta_total": meta_total,
            "sellers_with_meta": sellers_with_meta,
        },
        "totals": {
            "amount": total_amount,
            "orders": total_orders,
            "quotes_created": total_quotes,
            "average_ticket": round(total_amount / total_orders, 2) if total_orders else 0,
            "conversion_rate": round((total_orders / total_quotes) * 100, 2) if total_quotes else 0,
            "meta_attainment_percent": totals_meta_attainment,
        },
        "top_seller": top_seller,
        "highlights": highlights,
        "sellers": sellers,
        "notes": {
            "quotes_period_source": "created_at",
            "sales_period_source": "ordered_at_with_created_at_fallback",
            "sales_definition": "tiny_order_id IS NOT NULL AND internal_status <> 'Cancelado'",
            "amount_source": "totals->>'net' (validado por regex numérico).",
            "conversion_rate_definition": "Pedidos no período sobre orçamentos criados no período, por vendedor.",
            "average_ticket_definition": "Faturamento do vendedor dividido pelos pedidos do período.",
            "share_percent_definition": "Participação do vendedor no faturamento total do período.",
            "no_seller_bucket": "Vendas/orçamentos sem vendedor entram nos totais como 'Sem vendedor', fora de top_seller e highlights.",
            "meta_source": "erp.seller_metas por (empresa, mês de referência).",
            "meta_no_prorata": "Metas são mensais e comparadas sem rateio (pro-rata); indisponíveis quando o período cruza mais de um mês-calendário sem year_month explícito.",
            "meta_attainment_definition": "Faturamento do período dividido pela meta do mês; meta_amount=0 resulta em atingimento nulo.",
        },
    }


@app.get("/api/seller/client-wallet")
@app.get("/seller/client-wallet")
def seller_client_wallet(request: Request, company: str = "parton", limit: int = 300):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    return {
        "ok": True,
        "company": company_key,
        "email": user.get("login"),
        "is_admin": _clean_str(user.get("role")).lower() == "admin",
        "sellers": [],
        "seller_ids": [],
        "items": [],
        "count": 0,
        "limit": limit,
        "source": "local_empty",
    }


CLIENT_WALLET_DEFAULT_PAGE_SIZE = 50
CLIENT_WALLET_MAX_PAGE_SIZE = 100
CLIENT_WALLET_DAILY_SYNC_MAX_PAGES_PER_COMPANY = 1
CLIENT_WALLET_PURCHASE_ENRICH_DAILY_LIMIT = int(os.getenv("CLIENT_WALLET_PURCHASE_ENRICH_DAILY_LIMIT", "20"))
_CLIENT_WALLET_DAILY_SYNC_LOCK = threading.Lock()
_CLIENT_WALLET_DAILY_SCHEDULER_STARTED = False
_CLIENT_WALLET_DAILY_LAST_RUN_DATE: Optional[dt.date] = None


def _client_wallet_require_admin(user: Dict[str, Any]):
    if _clean_str(user.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Importação da carteira exige usuário admin.")


def _client_wallet_pick(source: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def _client_wallet_unwrap_contact(item: Dict[str, Any]) -> Dict[str, Any]:
    contact = item or {}
    if isinstance(contact.get("contato"), dict):
        contact = contact.get("contato") or {}
    if isinstance(contact.get("cliente"), dict):
        contact = contact.get("cliente") or {}
    return contact if isinstance(contact, dict) else {}


def _client_wallet_normalize_contact(raw: Dict[str, Any]) -> Dict[str, Any]:
    c = _client_wallet_unwrap_contact(raw)
    vendedor = c.get("vendedor") if isinstance(c.get("vendedor"), dict) else {}
    situacao = _client_wallet_pick(c, "situacao", "status")
    tiny_client_id = _client_wallet_pick(c, "id", "id_contato", "idContato", "codigo")
    return {
        "tiny_client_id": tiny_client_id,
        "codigo": _client_wallet_pick(c, "codigo", "id"),
        "nome": _client_wallet_pick(c, "nome", "razao_social", "razaoSocial", "name"),
        "fantasia": _client_wallet_pick(c, "fantasia", "nome_fantasia", "nomeFantasia"),
        "cpf_cnpj": _client_wallet_pick(c, "cpf_cnpj", "cpfCnpj", "cnpj", "cpf"),
        "email": _client_wallet_pick(c, "email"),
        "telefone": _client_wallet_pick(c, "fone", "telefone", "telefone_comercial", "telefoneComercial"),
        "celular": _client_wallet_pick(c, "celular", "telefone_celular", "telefoneCelular"),
        "cidade": _client_wallet_pick(c, "cidade", "municipio"),
        "uf": _client_wallet_pick(c, "uf", "estado"),
        "endereco": _client_wallet_pick(c, "endereco", "logradouro"),
        "numero": _client_wallet_pick(c, "numero"),
        "bairro": _client_wallet_pick(c, "bairro"),
        "cep": _client_wallet_pick(c, "cep"),
        "situacao": situacao,
        "ativo": _active_flag(situacao),
        "vendedor_id": _client_wallet_pick(c, "id_vendedor", "idVendedor", "vendedor_id") or _client_wallet_pick(vendedor, "id"),
        "vendedor_nome": _client_wallet_pick(c, "nome_vendedor", "nomeVendedor", "vendedor_nome") or _client_wallet_pick(vendedor, "nome", "name"),
        "raw_json": c,
    }


def _client_wallet_status(company_key: str) -> Dict[str, Any]:
    cache_key = f"status:{company_key}"
    cached = _client_wallet_cache_get(cache_key)
    if cached is not None:
        return cached
    _ensure_client_wallet_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM erp.client_wallet WHERE company_key=%s", (company_key,))
            total = int((cur.fetchone() or {}).get("total") or 0)
            cur.execute("SELECT * FROM erp.client_wallet_sync_state WHERE company_key=%s", (company_key,))
            state = dict(cur.fetchone() or {})
            if state:
                cur.execute(
                    """
                    UPDATE erp.client_wallet_sync_state
                    SET total_local=%s, updated_at=now()
                    WHERE company_key=%s
                    """,
                    (total, company_key),
                )
    last_error = state.get("last_error") or ""
    finished = bool(state.get("finished", False))
    current_page = _safe_int(state.get("current_page"), None)
    next_page = int(state.get("next_page") or 1)
    total_pages = _safe_int(state.get("total_pages"), None)
    total_remote = _safe_int(state.get("total_remote"), None)
    progress_percent = _safe_float(state.get("progress_percent"), None)
    if progress_percent is None:
        progress_percent = _client_wallet_progress_percent(total, total_remote, current_page, total_pages, finished)
    status_text = _client_wallet_status_text(state, total)
    result = {
        "company_key": company_key,
        "total_local": total,
        "total_remote": total_remote,
        "current_page": current_page,
        "next_page": next_page,
        "total_pages": total_pages,
        "page_size": int(state.get("page_size") or CLIENT_WALLET_DEFAULT_PAGE_SIZE),
        "progress_percent": progress_percent,
        "status": status_text,
        "last_run_at": state.get("last_run_at"),
        "last_success_at": state.get("last_success_at"),
        "last_error": last_error,
        "total_imported": int(state.get("total_imported") or 0),
        "total_updated": int(state.get("total_updated") or 0),
        "finished": finished,
        "updated_at": state.get("updated_at"),
    }
    return _client_wallet_cache_set(cache_key, result)


def _client_wallet_extract_total(response: Dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = _safe_int((response or {}).get(key), None)
        if value is not None:
            return value
    return None


def _client_wallet_progress_percent(
    total_local: int,
    total_remote: Optional[int],
    current_page: Optional[int],
    total_pages: Optional[int],
    finished: bool,
) -> Optional[float]:
    if finished:
        return 100.0
    if total_remote and total_remote > 0:
        return round(min(100.0, (float(total_local or 0) / float(total_remote)) * 100.0), 2)
    if total_pages and total_pages > 0 and current_page:
        return round(min(100.0, (float(current_page) / float(total_pages)) * 100.0), 2)
    return None


def _client_wallet_status_text(state: Dict[str, Any], total_local: int = 0) -> str:
    if state.get("last_error"):
        return "Erro"
    if bool(state.get("finished", False)):
        return "Finalizado"
    if state.get("last_run_at") or state.get("last_success_at"):
        return "Em andamento"
    return "Não iniciado"


def _client_wallet_parse_purchase_date(value: Any) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=CLIENT_WALLET_DAILY_SYNC_TZ)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=CLIENT_WALLET_DAILY_SYNC_TZ)
    text = _clean_str(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(text[:19], fmt) if "%Y-%m-%dT" in fmt else dt.datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=CLIENT_WALLET_DAILY_SYNC_TZ)
        except Exception:
            continue
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=CLIENT_WALLET_DAILY_SYNC_TZ)
    except Exception:
        return None


def _client_wallet_purchase_recency(last_purchase_date: Any) -> Dict[str, Any]:
    parsed = _client_wallet_parse_purchase_date(last_purchase_date)
    if not parsed:
        return {"days_without_purchase": None, "purchase_recency_level": "unknown"}
    today = dt.datetime.now(CLIENT_WALLET_DAILY_SYNC_TZ).date()
    purchase_day = parsed.astimezone(CLIENT_WALLET_DAILY_SYNC_TZ).date()
    days = max(0, (today - purchase_day).days)
    if days <= 3:
        level = "fresh"
    elif days <= 5:
        level = "warning"
    else:
        level = "danger"
    return {"days_without_purchase": days, "purchase_recency_level": level}


def _client_wallet_row_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    out.update(_client_wallet_purchase_recency(out.get("last_purchase_date")))
    return out


def _client_wallet_import_page(company_key: str, page: int, page_size: int) -> Dict[str, Any]:
    _ensure_client_wallet_tables()
    page = max(1, int(page or 1))
    page_size = min(CLIENT_WALLET_MAX_PAGE_SIZE, max(1, int(page_size or CLIENT_WALLET_DEFAULT_PAGE_SIZE)))
    tiny = _tiny_for_company(company_key)
    now = _now()

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.client_wallet_sync_state (company_key, current_page, next_page, page_size, last_run_at, finished, updated_at)
                VALUES (%s, %s, %s, %s, %s, FALSE, now())
                ON CONFLICT (company_key) DO UPDATE SET
                  current_page = EXCLUDED.current_page,
                  page_size = EXCLUDED.page_size,
                  last_run_at = EXCLUDED.last_run_at,
                  updated_at = now()
                """,
                (company_key, page, page, page_size, now),
            )

    try:
        response = tiny.pesquisar_contatos(pesquisa="", pagina=page, situacao="A")
    except TinyAPIError as e:
        msg = str(e)
        if "não retornou registros" in msg.lower() or "nao retornou registros" in msg.lower():
            response = {"contatos": []}
        else:
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO erp.client_wallet_sync_state (company_key, current_page, next_page, page_size, last_run_at, last_error, finished, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, FALSE, now())
                        ON CONFLICT (company_key) DO UPDATE SET
                          current_page = EXCLUDED.current_page,
                          page_size = EXCLUDED.page_size,
                          last_run_at = EXCLUDED.last_run_at,
                          last_error = EXCLUDED.last_error,
                          updated_at = now()
                        """,
                        (company_key, page, page, page_size, now, msg),
                    )
            raise HTTPException(status_code=502, detail=f"Falha ao importar clientes do Tiny: {msg}")

    raw_items = response.get("contatos") or response.get("clientes") or response.get("registros") or []
    imported = 0
    updated = 0
    processed = 0

    with _db() as conn:
        with conn.cursor() as cur:
            for item in raw_items:
                raw_contact = _client_wallet_unwrap_contact(item)
                normalized = _client_wallet_normalize_contact(raw_contact)
                if not normalized["tiny_client_id"]:
                    continue
                if not normalized["ativo"]:
                    continue
                processed += 1
                cur.execute(
                    """
                    INSERT INTO erp.client_wallet (
                      company_key, tiny_client_id, codigo, nome, fantasia, cpf_cnpj, email,
                      telefone, celular, cidade, uf, endereco, numero, bairro, cep, situacao,
                      ativo, vendedor_id, vendedor_nome, raw_json, last_seen_at, created_at, updated_at
                    )
                    VALUES (
                      %(company_key)s, %(tiny_client_id)s, %(codigo)s, %(nome)s, %(fantasia)s, %(cpf_cnpj)s, %(email)s,
                      %(telefone)s, %(celular)s, %(cidade)s, %(uf)s, %(endereco)s, %(numero)s, %(bairro)s, %(cep)s, %(situacao)s,
                      %(ativo)s, %(vendedor_id)s, %(vendedor_nome)s, %(raw_json)s::jsonb, %(last_seen_at)s, now(), now()
                    )
                    ON CONFLICT (company_key, tiny_client_id) WHERE tiny_client_id IS NOT NULL DO UPDATE SET
                      codigo = EXCLUDED.codigo,
                      nome = EXCLUDED.nome,
                      fantasia = EXCLUDED.fantasia,
                      cpf_cnpj = EXCLUDED.cpf_cnpj,
                      email = EXCLUDED.email,
                      telefone = EXCLUDED.telefone,
                      celular = EXCLUDED.celular,
                      cidade = EXCLUDED.cidade,
                      uf = EXCLUDED.uf,
                      endereco = EXCLUDED.endereco,
                      numero = EXCLUDED.numero,
                      bairro = EXCLUDED.bairro,
                      cep = EXCLUDED.cep,
                      situacao = EXCLUDED.situacao,
                      ativo = EXCLUDED.ativo,
                      vendedor_id = EXCLUDED.vendedor_id,
                      vendedor_nome = EXCLUDED.vendedor_nome,
                      raw_json = EXCLUDED.raw_json,
                      last_seen_at = EXCLUDED.last_seen_at,
                      updated_at = now()
                    RETURNING (xmax = '0'::xid) AS inserted
                    """,
                    {
                        **normalized,
                        "company_key": company_key,
                        "raw_json": _to_jsonb(normalized.get("raw_json")),
                        "last_seen_at": now,
                    },
                )
                if bool((cur.fetchone() or {}).get("inserted")):
                    imported += 1
                else:
                    updated += 1

            total_pages = _client_wallet_extract_total(
                response,
                "numero_paginas",
                "numeroPaginas",
                "total_paginas",
                "totalPaginas",
                "paginas",
                "pages",
            )
            total_remote = _client_wallet_extract_total(
                response,
                "total",
                "total_registros",
                "totalRegistros",
                "quantidade",
                "registros",
            )
            cur.execute("SELECT COUNT(*) AS total FROM erp.client_wallet WHERE company_key=%s", (company_key,))
            total_local = int((cur.fetchone() or {}).get("total") or 0)
            finished = bool(total_pages and page >= total_pages) or (not raw_items) or (len(raw_items) < page_size) or (processed == 0)
            next_page = page if finished else page + 1
            progress_percent = _client_wallet_progress_percent(total_local, total_remote, page, total_pages, finished)
            cur.execute(
                """
                INSERT INTO erp.client_wallet_sync_state (
                  company_key, current_page, next_page, page_size, total_pages, total_remote, total_local,
                  progress_percent, last_run_at, last_success_at, last_error,
                  total_imported, total_updated, finished, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, now())
                ON CONFLICT (company_key) DO UPDATE SET
                  current_page = EXCLUDED.current_page,
                  next_page = EXCLUDED.next_page,
                  page_size = EXCLUDED.page_size,
                  total_pages = COALESCE(EXCLUDED.total_pages, erp.client_wallet_sync_state.total_pages),
                  total_remote = COALESCE(EXCLUDED.total_remote, erp.client_wallet_sync_state.total_remote),
                  total_local = EXCLUDED.total_local,
                  progress_percent = EXCLUDED.progress_percent,
                  last_run_at = EXCLUDED.last_run_at,
                  last_success_at = EXCLUDED.last_success_at,
                  last_error = NULL,
                  total_imported = erp.client_wallet_sync_state.total_imported + EXCLUDED.total_imported,
                  total_updated = erp.client_wallet_sync_state.total_updated + EXCLUDED.total_updated,
                  finished = EXCLUDED.finished,
                  updated_at = now()
                """,
                (
                    company_key,
                    page,
                    next_page,
                    page_size,
                    total_pages,
                    total_remote,
                    total_local,
                    progress_percent,
                    now,
                    now,
                    imported,
                    updated,
                    finished,
                ),
            )

    return {
        "ok": True,
        "company_key": company_key,
        "page": page,
        "page_size": page_size,
        "imported": imported,
        "updated": updated,
        "total_processed": processed,
        "total_local": total_local,
        "total_remote": total_remote,
        "current_page": page,
        "total_pages": total_pages,
        "progress_percent": progress_percent,
        "next_page": next_page,
        "finished": finished,
        "status": "Finalizado" if finished else "Em andamento",
    }


def _client_wallet_log_sync(company_key: str, started_at: dt.datetime, finished_at: dt.datetime, result: Dict[str, Any]):
    _ensure_client_wallet_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.client_wallet_sync_log (
                  company_key, started_at, finished_at, status, imported, updated, processed, error, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    company_key,
                    started_at,
                    finished_at,
                    result.get("status") or ("Erro" if result.get("error") else "OK"),
                    int(result.get("imported") or 0),
                    int(result.get("updated") or 0),
                    int(result.get("total_processed") or result.get("processed") or 0),
                    result.get("error") or "",
                ),
            )


def _client_wallet_restore_finished_if_daily_check(company_key: str, before_status: Dict[str, Any], result: Dict[str, Any]):
    if not before_status.get("finished"):
        return result
    if int(result.get("imported") or 0) > 0:
        return result
    total_remote = _safe_int(result.get("total_remote"), None)
    total_local = _safe_int(result.get("total_local"), 0)
    if total_remote is not None and total_local < total_remote:
        return result

    current_page = before_status.get("current_page") or result.get("current_page") or 1
    next_page = before_status.get("next_page") or current_page
    total_pages = result.get("total_pages") or before_status.get("total_pages")
    total_remote = result.get("total_remote") or before_status.get("total_remote")
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.client_wallet_sync_state
                SET current_page=%s,
                    next_page=%s,
                    total_pages=COALESCE(%s, total_pages),
                    total_remote=COALESCE(%s, total_remote),
                    progress_percent=100,
                    finished=TRUE,
                    last_error=NULL,
                    updated_at=now()
                WHERE company_key=%s
                """,
                (current_page, next_page, total_pages, total_remote, company_key),
            )
    return {**result, "finished": True, "status": "Finalizado", "progress_percent": 100.0}


def _client_wallet_daily_sync_company(company_key: str) -> Dict[str, Any]:
    company_key = _company_key(company_key)
    started_at = _now()
    try:
        before_status = _client_wallet_status(company_key)
        page_size = int(before_status.get("page_size") or CLIENT_WALLET_DEFAULT_PAGE_SIZE)
        page = 1 if before_status.get("finished") else int(before_status.get("next_page") or 1)
        result = _client_wallet_import_page(company_key, page, page_size)
        result = _client_wallet_restore_finished_if_daily_check(company_key, before_status, result)
        finished_at = _now()
        result = {
            **result,
            "company_key": company_key,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "error": "",
        }
        _client_wallet_log_sync(company_key, started_at, finished_at, result)
        return result
    except Exception as e:
        finished_at = _now()
        msg = getattr(e, "detail", None) or str(e)
        result = {
            "ok": False,
            "company_key": company_key,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "imported": 0,
            "updated": 0,
            "total_processed": 0,
            "status": "Erro",
            "error": str(msg),
        }
        try:
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO erp.client_wallet_sync_state (company_key, last_run_at, last_error, finished, updated_at)
                        VALUES (%s, %s, %s, FALSE, now())
                        ON CONFLICT (company_key) DO UPDATE SET
                          last_run_at = EXCLUDED.last_run_at,
                          last_error = EXCLUDED.last_error,
                          updated_at = now()
                        """,
                        (company_key, started_at, str(msg)),
                    )
            _client_wallet_log_sync(company_key, started_at, finished_at, result)
        except Exception as log_error:
            print(f"[client-wallet-daily-sync] Falha ao registrar erro company={company_key}: {log_error}")
        return result


def _run_client_wallet_daily_sync() -> Dict[str, Any]:
    if not _CLIENT_WALLET_DAILY_SYNC_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "status": "already_running",
            "message": "Sincronização diária da Carteira de Clientes já está em andamento.",
            "results": [],
        }

    started_at = _now()
    print(f"[client-wallet-daily-sync] Iniciando sync diario started_at={started_at.isoformat()}")
    try:
        results = [_client_wallet_daily_sync_company(company_key) for company_key in CLIENT_WALLET_DAILY_SYNC_COMPANIES]
        finished_at = _now()
        errors = [r for r in results if r.get("error")]
        summary = {
            "ok": not bool(errors),
            "status": "Erro" if errors else "OK",
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "results": results,
            "errors": errors,
        }
        print(
            "[client-wallet-daily-sync] Concluido "
            f"finished_at={finished_at.isoformat()} empresas={len(results)} erros={len(errors)}"
        )
        return summary
    finally:
        _CLIENT_WALLET_DAILY_SYNC_LOCK.release()


def _client_wallet_daily_scheduler_loop():
    global _CLIENT_WALLET_DAILY_LAST_RUN_DATE
    while True:
        try:
            now_sp = dt.datetime.now(CLIENT_WALLET_DAILY_SYNC_TZ)
            today = now_sp.date()
            should_run = (
                now_sp.hour == CLIENT_WALLET_DAILY_SYNC_HOUR
                and now_sp.minute == CLIENT_WALLET_DAILY_SYNC_MINUTE
                and _CLIENT_WALLET_DAILY_LAST_RUN_DATE != today
            )
            if should_run:
                _CLIENT_WALLET_DAILY_LAST_RUN_DATE = today
                _run_client_wallet_daily_sync()
        except Exception as e:
            print(f"[client-wallet-daily-sync] Erro no scheduler: {e}")
        time.sleep(30)


def _start_client_wallet_daily_scheduler():
    global _CLIENT_WALLET_DAILY_SCHEDULER_STARTED
    if _CLIENT_WALLET_DAILY_SCHEDULER_STARTED:
        return
    _CLIENT_WALLET_DAILY_SCHEDULER_STARTED = True
    thread = threading.Thread(target=_client_wallet_daily_scheduler_loop, daemon=True)
    thread.start()
    print("Sync diário da Carteira de Clientes agendado para 08:00 (America/Sao_Paulo).")


@app.get("/api/client-wallet/sync/status")
@app.get("/client-wallet/sync/status")
def client_wallet_sync_status(request: Request, company: str = "parton"):
    started = time.perf_counter()
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    result = {"ok": True, **_client_wallet_status(company_key)}
    print(f"[client-wallet] status company={company_key} tempo={_elapsed_ms(started)}ms")
    return result


@app.post("/api/client-wallet/sync/reset")
@app.post("/client-wallet/sync/reset")
def client_wallet_sync_reset(request: Request, company: str = "parton", page_size: int = CLIENT_WALLET_DEFAULT_PAGE_SIZE):
    user = _require_auth_user(request)
    _client_wallet_require_admin(user)
    company_key = _auth_company_or_default(user, company)
    page_size = min(CLIENT_WALLET_MAX_PAGE_SIZE, max(1, int(page_size or CLIENT_WALLET_DEFAULT_PAGE_SIZE)))
    _ensure_client_wallet_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.client_wallet_sync_state (
                  company_key, current_page, next_page, page_size, total_pages, total_remote,
                  progress_percent, last_error, finished, updated_at
                )
                VALUES (%s, NULL, 1, %s, NULL, NULL, NULL, NULL, FALSE, now())
                ON CONFLICT (company_key) DO UPDATE SET
                  current_page = NULL,
                  next_page = 1,
                  page_size = EXCLUDED.page_size,
                  total_pages = NULL,
                  total_remote = NULL,
                  total_local = NULL,
                  progress_percent = NULL,
                  last_run_at = NULL,
                  last_success_at = NULL,
                  last_error = NULL,
                  total_imported = 0,
                  total_updated = 0,
                  finished = FALSE,
                  updated_at = now()
                """,
                (company_key, page_size),
            )
    _client_wallet_cache_clear()
    return {"ok": True, **_client_wallet_status(company_key)}


@app.post("/api/client-wallet/sync/next")
@app.post("/client-wallet/sync/next")
def client_wallet_sync_next(request: Request, company: str = "parton", page_size: int = CLIENT_WALLET_DEFAULT_PAGE_SIZE):
    user = _require_auth_user(request)
    _client_wallet_require_admin(user)
    company_key = _auth_company_or_default(user, company)
    status = _client_wallet_status(company_key)
    page = int(status.get("next_page") or 1)
    effective_page_size = int(status.get("page_size") or page_size or CLIENT_WALLET_DEFAULT_PAGE_SIZE)
    result = _client_wallet_import_page(company_key, page, effective_page_size)
    _client_wallet_cache_clear()
    return result


@app.post("/api/client-wallet/sync/page")
@app.post("/client-wallet/sync/page")
def client_wallet_sync_page(
    request: Request,
    company: str = "parton",
    page: int = Query(default=1, ge=1),
    page_size: int = CLIENT_WALLET_DEFAULT_PAGE_SIZE,
):
    user = _require_auth_user(request)
    _client_wallet_require_admin(user)
    company_key = _auth_company_or_default(user, company)
    result = _client_wallet_import_page(company_key, page, page_size)
    _client_wallet_cache_clear()
    return result


@app.post("/api/client-wallet/sync/daily-run")
@app.post("/client-wallet/sync/daily-run")
def client_wallet_sync_daily_run(request: Request):
    user = _require_auth_user(request)
    _client_wallet_require_admin(user)
    return _run_client_wallet_daily_sync()


@app.get("/api/client-wallet")
@app.get("/client-wallet")
def client_wallet_list(
    request: Request,
    company: str = "parton",
    q: str = "",
    uf: str = "",
    seller: str = "",
    active: Optional[bool] = True,
    has_email: Optional[bool] = None,
    has_phone: Optional[bool] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    started = time.perf_counter()
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    wallet_scope = _resolve_client_wallet_scope(user, company_key)
    _ensure_client_wallet_tables()
    where = ["company_key = %s"]
    params: List[Any] = [company_key]
    q_norm = _clean_str(q).lower()
    if q_norm:
        like = f"%{q_norm}%"
        where.append(
            """
            (
              LOWER(COALESCE(nome, '')) LIKE %s OR
              LOWER(COALESCE(fantasia, '')) LIKE %s OR
              LOWER(COALESCE(cpf_cnpj, '')) LIKE %s OR
              LOWER(COALESCE(email, '')) LIKE %s OR
              LOWER(COALESCE(telefone, '')) LIKE %s OR
              LOWER(COALESCE(celular, '')) LIKE %s
            )
            """
        )
        params.extend([like, like, like, like, like, like])
    if _clean_str(uf):
        where.append("UPPER(COALESCE(uf, '')) = %s")
        params.append(_clean_str(uf).upper())
    if wallet_scope.get("is_admin") and _clean_str(seller):
        where.append("LOWER(COALESCE(vendedor_nome, '')) = LOWER(%s)")
        params.append(_clean_str(seller))
    _apply_client_wallet_scope(where, params, wallet_scope)
    if active is not None:
        where.append("ativo = %s")
        params.append(bool(active))
    if has_email is not None:
        where.append("(COALESCE(email, '') <> '') = %s")
        params.append(bool(has_email))
    if has_phone is not None:
        where.append("(COALESCE(telefone, '') <> '' OR COALESCE(celular, '') <> '') = %s")
        params.append(bool(has_phone))
    where_sql = " AND ".join(where)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM erp.client_wallet WHERE {where_sql}", params)
            total = int((cur.fetchone() or {}).get("total") or 0)
            cur.execute(
                f"""
                SELECT id, company_key, tiny_client_id, codigo, nome, fantasia, cpf_cnpj, email,
                       telefone, celular, cidade, uf, endereco, numero, bairro, cep, situacao,
                       ativo, vendedor_id, vendedor_nome, last_seen_at,
                       origin, tiny_sync_status, tiny_sync_error,
                       last_purchase_date, last_purchase_order_number, last_purchase_total, last_purchase_synced_at,
                       created_at, updated_at
                FROM erp.client_wallet
                WHERE {where_sql}
                ORDER BY LOWER(COALESCE(nome, fantasia, '')), id
                LIMIT %s OFFSET %s
                """,
                [*params, int(limit), int(offset)],
            )
            rows = [_client_wallet_row_public(dict(r)) for r in cur.fetchall()]
    rows = [_client_wallet_refresh_last_purchase_from_local_history(row) for row in rows]
    seller_log = _clean_str(seller) or "Todos"
    if not wallet_scope.get("is_admin"):
        seller_log = _clean_str(wallet_scope.get("linked_seller_name")) or _clean_str(wallet_scope.get("forced_tiny_seller_id")) or "Vinculado"
    q_log = "sim" if _clean_str(q) else "nao"
    print(
        f"[client-wallet] list company={company_key} limit={int(limit)} offset={int(offset)} "
        f"seller={seller_log} q={q_log} uf={_clean_str(uf) or 'Todos'} active={active} tempo={_elapsed_ms(started)}ms"
    )
    return {"ok": True, "company_key": company_key, "items": rows, "total": total, "limit": limit, "offset": offset}


# ---------- Cadastro local-first de cliente + envio ao Tiny V3 ----------
def _normalize_cpf_cnpj(value: Any) -> str:
    """Remove pontuação/espaços, mantendo apenas dígitos."""
    return _client_wallet_digits_only(value)


# Contribuinte ICMS conforme contrato Tiny/Olist V3: 1, 2 ou 9.
#   1 = Contribuinte ICMS
#   2 = Contribuinte isento de Inscrição no cadastro de Contribuintes do ICMS
#   9 = Não Contribuinte
# Mapeia também os valores legados locais (S/N/I) gravados antes desta fase.
_CONTRIBUINTE_VALID_CODES = ("1", "2", "9")
_CONTRIBUINTE_LEGACY_MAP = {
    "S": "1",  # Sim, contribuinte ICMS -> 1
    "I": "2",  # Isento -> 2
    "N": "9",  # Não contribuinte -> 9
}


def _normalize_contribuinte(value: Any) -> str:
    """Devolve '1', '2', '9' ou '' (não informado), aceitando legados S/N/I."""
    s = _clean_str(value).upper()
    if not s:
        return ""
    if s in _CONTRIBUINTE_VALID_CODES:
        return s
    if s in _CONTRIBUINTE_LEGACY_MAP:
        return _CONTRIBUINTE_LEGACY_MAP[s]
    return ""


def _tiny_v3_extract_contact_id(payload: Any) -> str:
    """Extrai o id do contato da resposta do Tiny V3 tentando caminhos comuns."""
    def _dig(obj: Any, path: str) -> Any:
        cur = obj
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    candidates = (
        "id",
        "contato.id",
        "data.id",
        "data.contato.id",
        "id_contato",
        "idContato",
    )
    sources: List[Any] = []
    if isinstance(payload, dict):
        sources.append(payload)
        # _request envolve o corpo em {"ok","status_code","data": <body>}
        inner = payload.get("data")
        if isinstance(inner, dict):
            sources.append(inner)
    for source in sources:
        for path in candidates:
            value = _dig(source, path)
            if value is not None and str(value).strip() != "":
                return str(value).strip()
    return ""


def _build_tiny_v3_contato_payload(fields: Dict[str, Any], cpf_cnpj_digits: str) -> Dict[str, Any]:
    """Monta um payload conservador de contato para o Tiny V3."""
    payload: Dict[str, Any] = {"nome": fields["nome"]}
    if fields.get("fantasia"):
        payload["fantasia"] = fields["fantasia"]
    if cpf_cnpj_digits:
        payload["cpfCnpj"] = cpf_cnpj_digits
        if len(cpf_cnpj_digits) == 14:
            payload["tipoPessoa"] = "J"
        elif len(cpf_cnpj_digits) == 11:
            payload["tipoPessoa"] = "F"
    if fields.get("email"):
        payload["email"] = fields["email"]
    if fields.get("telefone"):
        payload["telefone"] = fields["telefone"]
    if fields.get("celular"):
        payload["celular"] = fields["celular"]

    endereco: Dict[str, Any] = {}
    if fields.get("endereco"):
        endereco["endereco"] = fields["endereco"]
    if fields.get("numero"):
        endereco["numero"] = fields["numero"]
    if fields.get("bairro"):
        endereco["bairro"] = fields["bairro"]
    if fields.get("cep"):
        endereco["cep"] = fields["cep"]
    if fields.get("cidade"):
        endereco["municipio"] = fields["cidade"]
    if fields.get("uf"):
        endereco["uf"] = fields["uf"]
    if fields.get("complemento"):
        endereco["complemento"] = fields["complemento"]
    if endereco:
        payload["endereco"] = endereco

    if fields.get("telefone2"):
        payload["telefone2"] = fields["telefone2"]
    if fields.get("website"):
        payload["website"] = fields["website"]
    if fields.get("email_nfe"):
        payload["emailNfe"] = fields["email_nfe"]
    if fields.get("observacoes"):
        payload["observacoes"] = fields["observacoes"]
    contribuinte_code = _normalize_contribuinte(fields.get("contribuinte"))
    if contribuinte_code:
        # Tiny V3 espera o código numérico do contribuinte (1, 2 ou 9).
        payload["contribuinte"] = int(contribuinte_code)
    if fields.get("inscricao_estadual"):
        payload["inscricaoEstadual"] = fields["inscricao_estadual"]
    if fields.get("inscricao_municipal"):
        payload["inscricaoMunicipal"] = fields["inscricao_municipal"]
    if fields.get("tipo_contato"):
        payload["tipoContato"] = fields["tipo_contato"]
    if fields.get("vendedor_id"):
        try:
            payload["idVendedor"] = int(fields["vendedor_id"])
        except (TypeError, ValueError):
            payload["idVendedor"] = str(fields["vendedor_id"])
    if fields.get("vendedor_nome"):
        payload["nomeVendedor"] = fields["vendedor_nome"]

    return payload


@app.post("/api/client-wallet")
@app.post("/client-wallet")
async def client_wallet_create(request: Request, company: str = "parton"):
    user = _require_auth_user(request)
    body = await request.json()
    # Query param tem prioridade; body.company é fallback para clientes que enviam no corpo.
    body_company = _clean_str(body.get("company"))
    company_key = _auth_company_or_default(user, company or body_company or "parton")
    _ensure_client_wallet_tables()

    nome = _clean_str(body.get("nome"))
    if not nome:
        raise HTTPException(status_code=400, detail="O campo 'nome' é obrigatório.")

    cpf_cnpj_digits = _normalize_cpf_cnpj(body.get("cpf_cnpj"))

    # Validação: contribuinte aceita os códigos Tiny 1, 2, 9 (ou legados S/N/I) ou vazio.
    contribuinte_raw = _clean_str(body.get("contribuinte")).upper()
    if contribuinte_raw and contribuinte_raw not in _CONTRIBUINTE_VALID_CODES and contribuinte_raw not in _CONTRIBUINTE_LEGACY_MAP:
        raise HTTPException(status_code=400, detail="contribuinte deve ser '1', '2' ou '9'.")
    contribuinte = _normalize_contribuinte(contribuinte_raw)

    # Validação: data_nascimento deve ser YYYY-MM-DD se fornecida.
    data_nascimento_raw = _clean_str(body.get("data_nascimento"))
    data_nascimento = None
    if data_nascimento_raw:
        try:
            dt.date.fromisoformat(data_nascimento_raw)
            data_nascimento = data_nascimento_raw
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="data_nascimento inválida. Use formato YYYY-MM-DD (ex: 1990-01-25).",
            )

    tipo_contato = _clean_str(body.get("tipo_contato")) or "cliente"

    fields = {
        "nome": nome,
        "fantasia": _clean_str(body.get("fantasia")),
        "cpf_cnpj": cpf_cnpj_digits,
        "email": _clean_str(body.get("email")),
        "telefone": _clean_str(body.get("telefone")),
        "celular": _clean_str(body.get("celular")),
        "cep": _clean_str(body.get("cep")),
        "endereco": _clean_str(body.get("endereco")),
        "numero": _clean_str(body.get("numero")),
        "bairro": _clean_str(body.get("bairro")),
        "cidade": _clean_str(body.get("cidade")),
        "uf": _clean_str(body.get("uf")).upper(),
        "codigo": _clean_str(body.get("codigo")),
        "complemento": _clean_str(body.get("complemento")),
        "telefone2": _clean_str(body.get("telefone2")),
        "website": _clean_str(body.get("website")),
        "email_nfe": _clean_str(body.get("email_nfe")),
        "observacoes": _clean_str(body.get("observacoes")),
        "contribuinte": contribuinte,
        "inscricao_estadual": _clean_str(body.get("inscricao_estadual")),
        "inscricao_municipal": _clean_str(body.get("inscricao_municipal")),
        "tipo_contato": tipo_contato,
        "codigo_regime_tributario": _clean_str(body.get("codigo_regime_tributario")),
        "inscricao_suframa": _clean_str(body.get("inscricao_suframa")),
        "data_nascimento": data_nascimento,
        "status_crm": _clean_str(body.get("status_crm")),
    }

    # Vendedor: admin pode escolher explicitamente no body; não-admin usa seller_links.
    is_admin_user = _clean_str(user.get("role")).lower() == "admin"
    if is_admin_user:
        vendedor_id   = _clean_str(body.get("vendedor_id"))   or None
        vendedor_nome = _clean_str(body.get("vendedor_nome")) or None
    else:
        link = (_auth_user_seller_links(user.get("id")) or {}).get(company_key) or {}
        vendedor_id   = _clean_str(link.get("tiny_seller_id"))   or None
        vendedor_nome = _clean_str(link.get("tiny_seller_name")) or None
    fields["vendedor_id"] = vendedor_id
    fields["vendedor_nome"] = vendedor_nome

    # Duplicidade por CPF/CNPJ dentro da mesma empresa.
    if cpf_cnpj_digits:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, nome, tiny_client_id, cpf_cnpj, tiny_sync_status
                    FROM erp.client_wallet
                    WHERE company_key = %s
                      AND regexp_replace(COALESCE(cpf_cnpj, ''), '[^0-9]', '', 'g') = %s
                    ORDER BY id
                    LIMIT 1
                    """,
                    (company_key, cpf_cnpj_digits),
                )
                existing = dict(cur.fetchone() or {})
        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Já existe um cliente com este CPF/CNPJ nesta empresa.",
                    "company_key": company_key,
                    "existing": {
                        "id": existing.get("id"),
                        "nome": existing.get("nome"),
                        "cpf_cnpj": existing.get("cpf_cnpj"),
                        "tiny_client_id": existing.get("tiny_client_id"),
                        "tiny_sync_status": existing.get("tiny_sync_status"),
                    },
                },
            )

    now = _now()
    raw_input = {k: v for k, v in fields.items() if v}

    # 1) Insere localmente primeiro (local-first), sem tiny_client_id.
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.client_wallet (
                  company_key, tiny_client_id, nome, fantasia, cpf_cnpj, email,
                  telefone, celular, cidade, uf, endereco, numero, bairro, cep,
                  ativo, vendedor_id, vendedor_nome, raw_json,
                  origin, tiny_sync_status, tiny_sync_error,
                  last_seen_at, created_at, updated_at,
                  codigo, complemento, telefone2, website, email_nfe, observacoes,
                  contribuinte, inscricao_estadual, inscricao_municipal, tipo_contato,
                  codigo_regime_tributario, inscricao_suframa, data_nascimento, status_crm
                )
                VALUES (
                  %(company_key)s, NULL, %(nome)s, %(fantasia)s, %(cpf_cnpj)s, %(email)s,
                  %(telefone)s, %(celular)s, %(cidade)s, %(uf)s, %(endereco)s, %(numero)s, %(bairro)s, %(cep)s,
                  TRUE, %(vendedor_id)s, %(vendedor_nome)s, %(raw_json)s::jsonb,
                  'local', 'pending', NULL,
                  %(now)s, now(), now(),
                  %(codigo)s, %(complemento)s, %(telefone2)s, %(website)s, %(email_nfe)s, %(observacoes)s,
                  %(contribuinte)s, %(inscricao_estadual)s, %(inscricao_municipal)s, %(tipo_contato)s,
                  %(codigo_regime_tributario)s, %(inscricao_suframa)s, %(data_nascimento)s, %(status_crm)s
                )
                RETURNING id
                """,
                {
                    **fields,
                    "company_key": company_key,
                    "vendedor_id": vendedor_id,
                    "vendedor_nome": vendedor_nome,
                    "raw_json": _to_jsonb(raw_input),
                    "now": now,
                },
            )
            new_id = int((cur.fetchone() or {}).get("id"))

    # 2) Tenta criar/enviar ao Tiny V3.
    tiny_payload = _build_tiny_v3_contato_payload(fields, cpf_cnpj_digits)
    tiny_client_id = ""
    sync_error = ""
    try:
        v3 = _tiny_v3_for_company(company_key)
        resp = v3.criar_contato(tiny_payload)
        tiny_client_id = _tiny_v3_extract_contact_id(resp)
        if not tiny_client_id:
            sync_error = "Tiny V3 respondeu sem um id de contato reconhecível."
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
        sync_error = str(detail)[:2000]
    except Exception as exc:  # noqa: BLE001 — registra erro de sync, mantém cliente local
        sync_error = str(exc)[:2000]

    # 3) Atualiza status conforme resultado.
    if tiny_client_id and not sync_error:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE erp.client_wallet
                    SET tiny_client_id = %s,
                        tiny_sync_status = 'synced',
                        tiny_sync_error = NULL,
                        tiny_synced_at = now(),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (tiny_client_id, new_id),
                )
        print(f"[client-wallet] create company={company_key} id={new_id} tiny_id={tiny_client_id} status=synced")
        return {
            "ok": True,
            "id": new_id,
            "company_key": company_key,
            "tiny_client_id": tiny_client_id,
            "tiny_sync_status": "synced",
            "origin": "local",
            "message": "Cliente cadastrado localmente e sincronizado com o Tiny V3.",
        }

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.client_wallet
                SET tiny_sync_status = 'error',
                    tiny_sync_error = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (sync_error or "Falha desconhecida ao sincronizar com o Tiny V3.", new_id),
            )
    print(f"[client-wallet] create company={company_key} id={new_id} status=error erro={sync_error[:200]}")
    return {
        "ok": True,
        "id": new_id,
        "company_key": company_key,
        "tiny_client_id": None,
        "tiny_sync_status": "error",
        "tiny_sync_error": sync_error or "Falha desconhecida ao sincronizar com o Tiny V3.",
        "origin": "local",
        "message": "Cliente cadastrado localmente, mas a sincronização com o Tiny V3 falhou.",
    }


_CLIENT_WALLET_EDITABLE_FIELDS = [
    "codigo", "nome", "fantasia", "cpf_cnpj", "email", "telefone", "celular",
    "cep", "endereco", "numero", "bairro", "cidade", "uf", "complemento",
    "telefone2", "website", "email_nfe", "observacoes", "contribuinte",
    "inscricao_estadual", "inscricao_municipal", "tipo_contato",
    "codigo_regime_tributario", "inscricao_suframa", "data_nascimento",
    "status_crm", "vendedor_id", "vendedor_nome", "situacao", "ativo",
]


@app.patch("/api/client-wallet/{tiny_client_id}")
@app.patch("/client-wallet/{tiny_client_id}")
async def client_wallet_update(request: Request, tiny_client_id: str, company: str = "parton"):
    user = _require_auth_user(request)
    _client_wallet_require_admin(user)
    company_key = _auth_company_or_default(user, company)
    body = await request.json()
    _ensure_client_wallet_tables()

    # Localiza o registro existente para garantir que pertence a esta empresa.
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM erp.client_wallet WHERE company_key=%s AND tiny_client_id=%s LIMIT 1",
                (company_key, str(tiny_client_id)),
            )
            existing = cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Cliente não encontrado na carteira desta empresa.")
    existing = dict(existing)

    # Monta dicionário com apenas os campos enviados no body que são editáveis.
    updates: Dict[str, Any] = {}

    for field in _CLIENT_WALLET_EDITABLE_FIELDS:
        if field not in body:
            continue
        raw = body[field]

        if field == "nome":
            val = _clean_str(raw)
            if val == "":
                raise HTTPException(status_code=400, detail="O campo 'nome' não pode ficar vazio.")
            updates["nome"] = val

        elif field == "uf":
            updates["uf"] = _clean_str(raw).upper()

        elif field == "contribuinte":
            val = _clean_str(raw).upper()
            if val and val not in _CONTRIBUINTE_VALID_CODES and val not in _CONTRIBUINTE_LEGACY_MAP:
                raise HTTPException(status_code=400, detail="contribuinte deve ser '1', '2' ou '9'.")
            updates["contribuinte"] = _normalize_contribuinte(val)

        elif field == "data_nascimento":
            val = _clean_str(raw)
            if val:
                try:
                    dt.date.fromisoformat(val)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="data_nascimento inválida. Use formato YYYY-MM-DD.",
                    )
                updates["data_nascimento"] = val
            else:
                updates["data_nascimento"] = None

        elif field == "tipo_contato":
            val = _clean_str(raw) or "cliente"
            updates["tipo_contato"] = val

        elif field == "cpf_cnpj":
            digits = _normalize_cpf_cnpj(raw)
            if digits:
                with _db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT id, nome, tiny_client_id, cpf_cnpj
                            FROM erp.client_wallet
                            WHERE company_key = %s
                              AND regexp_replace(COALESCE(cpf_cnpj, ''), '[^0-9]', '', 'g') = %s
                              AND tiny_client_id != %s
                            ORDER BY id
                            LIMIT 1
                            """,
                            (company_key, digits, str(tiny_client_id)),
                        )
                        dup = cur.fetchone()
                if dup:
                    dup = dict(dup)
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Já existe outro cliente com este CPF/CNPJ nesta empresa.",
                            "company_key": company_key,
                            "existing": {
                                "id": dup.get("id"),
                                "nome": dup.get("nome"),
                                "cpf_cnpj": dup.get("cpf_cnpj"),
                                "tiny_client_id": dup.get("tiny_client_id"),
                            },
                        },
                    )
            updates["cpf_cnpj"] = digits if digits else _clean_str(raw)

        elif field == "ativo":
            if raw is None:
                updates["ativo"] = None
            else:
                updates["ativo"] = bool(raw)

        else:
            updates[field] = _clean_str(raw) if isinstance(raw, str) else raw

    if not updates:
        # Nenhum campo editável enviado — retorna o estado atual sem alterar.
        return {"ok": True, "company_key": company_key, "item": existing, "updated_fields": []}

    # Aplica UPDATE no banco.
    set_clauses = ", ".join(f"{k} = %s" for k in updates)
    set_values = list(updates.values())
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE erp.client_wallet
                SET {set_clauses}, updated_at = now()
                WHERE company_key = %s AND tiny_client_id = %s
                RETURNING *
                """,
                (*set_values, company_key, str(tiny_client_id)),
            )
            updated_row = cur.fetchone()

    updated_row = dict(updated_row) if updated_row else existing
    sync_error = ""
    tiny_payload = _build_tiny_v3_contato_payload(
        {**updated_row, "nome": _clean_str(updated_row.get("nome"))},
        _normalize_cpf_cnpj(updated_row.get("cpf_cnpj")),
    )
    try:
        v3 = _tiny_v3_for_company(company_key)
        v3.atualizar_contato(int(tiny_client_id), tiny_payload)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
        sync_error = str(detail)[:2000]
    except Exception as exc:  # noqa: BLE001 — mantém edição local e registra falha de sync
        sync_error = str(exc)[:2000]

    with _db() as conn:
        with conn.cursor() as cur:
            if sync_error:
                cur.execute(
                    """
                    UPDATE erp.client_wallet
                    SET tiny_sync_status = 'error',
                        tiny_sync_error = %s,
                        updated_at = now()
                    WHERE company_key = %s AND tiny_client_id = %s
                    RETURNING *
                    """,
                    (sync_error or "Falha desconhecida ao sincronizar com o Tiny V3.", company_key, str(tiny_client_id)),
                )
            else:
                cur.execute(
                    """
                    UPDATE erp.client_wallet
                    SET tiny_sync_status = 'synced',
                        tiny_sync_error = NULL,
                        tiny_synced_at = now(),
                        updated_at = now()
                    WHERE company_key = %s AND tiny_client_id = %s
                    RETURNING *
                    """,
                    (company_key, str(tiny_client_id)),
                )
            synced_row = cur.fetchone()
    if synced_row:
        updated_row = dict(synced_row)

    _client_wallet_cache_clear()
    print(
        f"[client-wallet] update admin company={company_key} tiny_id={tiny_client_id} "
        f"fields={list(updates.keys())} tiny_sync_status={updated_row.get('tiny_sync_status') or '-'}"
    )
    return {
        "ok": True,
        "company_key": company_key,
        "item": _client_wallet_row_public(updated_row),
        "updated_fields": list(updates.keys()),
        "tiny_sync_status": updated_row.get("tiny_sync_status"),
        "tiny_sync_error": updated_row.get("tiny_sync_error"),
        "message": (
            "Cliente atualizado localmente e sincronizado com o Tiny V3."
            if not sync_error
            else "Cliente atualizado localmente, mas a sincronização com o Tiny V3 falhou."
        ),
    }


# ---------- Reenvio manual de cliente local não sincronizado ao Tiny ----------
def _tiny_v3_error_is_auth(msg: str) -> bool:
    """Heurística: a falha do Tiny indica token expirado/inválido?"""
    m = (msg or "").lower()
    markers = (
        "401", "403", "unauthorized", "invalid_token", "invalid token",
        "token expir", "expired", "bearer", "não autoriz", "nao autoriz",
        "access_denied", "forbidden", "token",
    )
    return any(t in m for t in markers)


def _tiny_v1_match_contact_by_cpf(resp: Dict[str, Any], cpf_digits: str):
    """Retorna (tiny_id, raw) do primeiro contato com CPF/CNPJ idêntico, ou None."""
    contatos = (resp or {}).get("contatos") or []
    for it in contatos:
        c = it.get("contato", it) if isinstance(it, dict) else {}
        if not isinstance(c, dict):
            continue
        cid = _clean_str(c.get("id"))
        if not cid:
            continue
        c_cpf = _client_wallet_digits_only(
            c.get("cpf_cnpj") or c.get("cpfCnpj") or c.get("cnpj") or c.get("cpf")
        )
        if cpf_digits and c_cpf and c_cpf == cpf_digits:
            return (cid, c)
    return None


def _tiny_find_contact_by_cpf(company_key: str, cpf_digits: str):
    """Procura um contato existente no Tiny pelo CPF/CNPJ (via API V1, token longo)."""
    if not cpf_digits:
        return None
    tiny = _tiny_for_company(company_key)
    try:
        resp = tiny.pesquisar_contatos(pesquisa="", cpf_cnpj=cpf_digits)
    except TinyAPIError as e:
        msg = str(e).lower()
        if "não retornou registros" in msg or "nao retornou registros" in msg:
            return None
        raise
    return _tiny_v1_match_contact_by_cpf(resp, cpf_digits)


def _client_wallet_link_tiny_id(company_key: str, local_id: int, tiny_id: str):
    """Vincula o tiny_client_id ao registro local. Retorna (linha_atualizada, id_conflitante)."""
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM erp.client_wallet WHERE company_key=%s AND tiny_client_id=%s AND id<>%s LIMIT 1",
                (company_key, str(tiny_id), int(local_id)),
            )
            other = cur.fetchone()
            if other:
                return (None, dict(other).get("id"))
            cur.execute(
                """
                UPDATE erp.client_wallet
                SET tiny_client_id = %s,
                    tiny_sync_status = 'synced',
                    tiny_sync_error = NULL,
                    tiny_synced_at = now(),
                    origin = COALESCE(origin, 'local'),
                    updated_at = now()
                WHERE company_key = %s AND id = %s
                RETURNING *
                """,
                (str(tiny_id), company_key, int(local_id)),
            )
            updated = cur.fetchone()
    _client_wallet_cache_clear()
    return (dict(updated) if updated else None, None)


def _client_wallet_mark_sync_error(company_key: str, local_id: int, error: str) -> Dict[str, Any]:
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.client_wallet
                SET tiny_sync_status = 'error',
                    tiny_sync_error = %s,
                    updated_at = now()
                WHERE company_key = %s AND id = %s
                RETURNING *
                """,
                (error[:2000], company_key, int(local_id)),
            )
            updated = cur.fetchone()
    _client_wallet_cache_clear()
    return dict(updated) if updated else {}


@app.post("/api/client-wallet/{local_id}/resync")
@app.post("/client-wallet/{local_id}/resync")
async def client_wallet_resync_tiny(request: Request, local_id: int, company: str = "parton"):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    wallet_scope = _resolve_client_wallet_scope(user, company_key)
    _ensure_client_wallet_tables()

    # Carrega o cliente local existente (respeitando o escopo do vendedor).
    where = ["id=%s", "company_key=%s"]
    params: List[Any] = [int(local_id), company_key]
    _apply_client_wallet_scope(where, params, wallet_scope)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM erp.client_wallet WHERE {' AND '.join(where)} LIMIT 1", params)
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente não encontrado na carteira desta empresa.")
    row = dict(row)

    # Idempotência: já vinculado ao Tiny -> não cria outro contato.
    existing_tiny_id = _clean_str(row.get("tiny_client_id"))
    if existing_tiny_id:
        return {
            "ok": True,
            "company_key": company_key,
            "id": row.get("id"),
            "tiny_client_id": existing_tiny_id,
            "tiny_sync_status": "synced",
            "action": "already_linked",
            "message": "Cliente já vinculado ao Tiny.",
            "item": _client_wallet_row_public(row),
        }

    cpf_digits = _normalize_cpf_cnpj(row.get("cpf_cnpj"))

    # 1) Procura no Tiny por CPF/CNPJ; se já existir, apenas vincula (não duplica).
    found = None
    search_error = ""
    try:
        found = _tiny_find_contact_by_cpf(company_key, cpf_digits)
    except Exception as exc:  # noqa: BLE001 — registra, mas tenta criar em seguida
        search_error = str(exc)[:2000]

    if found:
        found_id = found[0]
        linked, conflict_id = _client_wallet_link_tiny_id(company_key, int(row["id"]), str(found_id))
        if conflict_id:
            return {
                "ok": False,
                "company_key": company_key,
                "id": row.get("id"),
                "tiny_client_id": str(found_id),
                "action": "conflict",
                "message": (
                    f"O contato {found_id} do Tiny já está vinculado a outro cliente local "
                    f"(id {conflict_id}) nesta empresa. Verifique duplicidade antes de sincronizar."
                ),
                "item": _client_wallet_row_public(row),
            }
        print(f"[client-wallet] resync company={company_key} id={row.get('id')} tiny_id={found_id} action=linked")
        return {
            "ok": True,
            "company_key": company_key,
            "id": row.get("id"),
            "tiny_client_id": str(found_id),
            "tiny_sync_status": "synced",
            "action": "linked",
            "message": "Contato já existia no Tiny — vinculado ao cliente local, sem criar duplicado.",
            "item": _client_wallet_row_public(linked or row),
        }

    # 2) Não existe no Tiny -> cria via V3 e grava o id no mesmo registro local.
    tiny_payload = _build_tiny_v3_contato_payload({**row, "nome": _clean_str(row.get("nome"))}, cpf_digits)
    tiny_client_id = ""
    sync_error = ""
    try:
        v3 = _tiny_v3_for_company(company_key)
        resp = v3.criar_contato(tiny_payload)
        tiny_client_id = _tiny_v3_extract_contact_id(resp)
        if not tiny_client_id:
            sync_error = "Tiny V3 respondeu sem um id de contato reconhecível."
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
        sync_error = str(detail)[:2000]
    except Exception as exc:  # noqa: BLE001 — mantém cliente local e registra falha
        sync_error = str(exc)[:2000]

    if tiny_client_id and not sync_error:
        linked, conflict_id = _client_wallet_link_tiny_id(company_key, int(row["id"]), str(tiny_client_id))
        if conflict_id:
            return {
                "ok": False,
                "company_key": company_key,
                "id": row.get("id"),
                "tiny_client_id": str(tiny_client_id),
                "action": "conflict",
                "message": (
                    f"O contato {tiny_client_id} retornado pelo Tiny já está vinculado a outro "
                    f"cliente local (id {conflict_id})."
                ),
                "item": _client_wallet_row_public(row),
            }
        print(f"[client-wallet] resync company={company_key} id={row.get('id')} tiny_id={tiny_client_id} action=created")
        return {
            "ok": True,
            "company_key": company_key,
            "id": row.get("id"),
            "tiny_client_id": str(tiny_client_id),
            "tiny_sync_status": "synced",
            "action": "created",
            "message": "Cliente enviado ao Tiny V3 e vinculado com sucesso.",
            "item": _client_wallet_row_public(linked or row),
        }

    # 3) Falhou -> preserva o cliente local, registra erro e orienta reautorização.
    combined_error = sync_error or search_error or "Falha desconhecida ao sincronizar com o Tiny V3."
    token_expired = _tiny_v3_error_is_auth(combined_error)
    friendly = (
        "Token do Tiny V3 expirado ou inativo. Reautorize o Tiny e tente sincronizar novamente."
        if token_expired
        else f"Não foi possível sincronizar com o Tiny V3: {combined_error}"
    )
    updated = _client_wallet_mark_sync_error(company_key, int(row["id"]), combined_error)
    print(f"[client-wallet] resync company={company_key} id={row.get('id')} action=error token_expired={token_expired} erro={combined_error[:200]}")
    return {
        "ok": False,
        "company_key": company_key,
        "id": row.get("id"),
        "tiny_client_id": None,
        "tiny_sync_status": "error",
        "tiny_sync_error": combined_error,
        "token_expired": token_expired,
        "action": "error",
        "message": friendly,
        "item": _client_wallet_row_public(updated or row),
    }


@app.get("/api/client-wallet/sellers")
@app.get("/client-wallet/sellers")
def client_wallet_sellers(request: Request, company: str = "parton"):
    started = time.perf_counter()
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    wallet_scope = _resolve_client_wallet_scope(user, company_key)
    if not wallet_scope.get("is_admin"):
        seller_name = _clean_str(wallet_scope.get("linked_seller_name"))
        result = {"ok": True, "company_key": company_key, "items": [seller_name] if seller_name else []}
        print(f"[client-wallet] sellers company={company_key} scoped=1 total={len(result['items'])} tempo={_elapsed_ms(started)}ms")
        return result
    cache_key = f"sellers:{company_key}"
    cached = _client_wallet_cache_get(cache_key)
    if cached is not None:
        print(f"[client-wallet] sellers company={company_key} cache=hit tempo={_elapsed_ms(started)}ms")
        return cached
    _ensure_client_wallet_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT vendedor_nome
                FROM erp.client_wallet
                WHERE company_key=%s
                  AND COALESCE(vendedor_nome, '') <> ''
                ORDER BY vendedor_nome
                """,
                (company_key,),
            )
            sellers = [_clean_str((row or {}).get("vendedor_nome")) for row in cur.fetchall()]
    result = {"ok": True, "company_key": company_key, "items": [s for s in sellers if s]}
    _client_wallet_cache_set(cache_key, result)
    print(f"[client-wallet] sellers company={company_key} total={len(result['items'])} tempo={_elapsed_ms(started)}ms")
    return result


@app.get("/api/client-wallet/product-last-sale")
@app.get("/client-wallet/product-last-sale")
def client_wallet_product_last_sale(
    request: Request,
    company: str = "parton",
    client_id: str = "",
    cpf_cnpj: str = "",
    name: str = "",
    product_id: str = "",
    sku: str = "",
    product_name: str = "",
):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    result = _client_wallet_product_last_sale(
        company_key,
        {"client_id": client_id, "cpf_cnpj": cpf_cnpj, "name": name},
        {"product_id": product_id, "sku": sku, "name": product_name},
    )
    return {"ok": True, "company_key": company_key, "source": "local_history", **result}


@app.get("/api/client-wallet/{tiny_client_id}")
@app.get("/client-wallet/{tiny_client_id}")
def client_wallet_detail(request: Request, tiny_client_id: str, company: str = "parton"):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    wallet_scope = _resolve_client_wallet_scope(user, company_key)
    _ensure_client_wallet_tables()
    where = ["company_key=%s", "tiny_client_id=%s"]
    params: List[Any] = [company_key, str(tiny_client_id)]
    _apply_client_wallet_scope(where, params, wallet_scope)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM erp.client_wallet
                WHERE {" AND ".join(where)}
                LIMIT 1
                """,
                params,
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente não encontrado na carteira desta empresa.")
    return {"ok": True, "company_key": company_key, "item": dict(row)}


def _client_wallet_order_unwrap(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    if isinstance(value.get("pedido"), dict):
        return value.get("pedido") or {}
    return value


def _client_wallet_order_items(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_items = (
        order.get("itens")
        or order.get("items")
        or order.get("produtos")
        or []
    )
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("item") or raw_items.get("itens") or []
    if not isinstance(raw_items, list):
        return []

    items: List[Dict[str, Any]] = []
    for raw in raw_items:
        item = raw.get("item") if isinstance(raw, dict) and isinstance(raw.get("item"), dict) else raw
        if not isinstance(item, dict):
            continue
        quantity = _safe_float(item.get("quantidade") or item.get("qtd") or item.get("quantity"), 0)
        unit_price = _safe_float(
            item.get("valor_unitario")
            or item.get("valorUnitario")
            or item.get("preco_unitario")
            or item.get("preco")
            or item.get("unit_price"),
            0,
        )
        total_price = _safe_float(
            item.get("valor_total")
            or item.get("valorTotal")
            or item.get("total")
            or item.get("total_price"),
            round(quantity * unit_price, 2),
        )
        items.append({
            "sku": _clean_str(item.get("codigo") or item.get("sku") or item.get("codigo_produto")),
            "name": _clean_str(item.get("descricao") or item.get("nome") or item.get("produto") or item.get("name")),
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": total_price,
            "discount": _safe_float(item.get("desconto") or item.get("discount"), 0),
            "unit": _clean_str(item.get("unidade") or item.get("unit")),
            "raw": item,
        })
    return items


def _client_wallet_order_summary(order_resp: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    order = _client_wallet_order_unwrap(order_resp)
    if isinstance(order.get("pedido"), dict):
        order = order.get("pedido") or {}
    if not order:
        order = fallback or {}

    seller = order.get("vendedor") if isinstance(order.get("vendedor"), dict) else {}
    payment = order.get("forma_pagamento") or order.get("formaPagamento") or order.get("condicao_pagamento") or order.get("condicaoPagamento")
    if isinstance(payment, dict):
        payment_name = _clean_str(payment.get("nome") or payment.get("descricao") or payment.get("name"))
    else:
        payment_name = _clean_str(payment)

    tiny_order_id = _client_wallet_pick(order, "id", "id_pedido", "idPedido") or _client_wallet_pick(fallback, "id")
    tiny_order_number = (
        _client_wallet_pick(order, "numero", "numero_pedido", "numeroPedido")
        or _client_wallet_pick(fallback, "numero")
    )
    return {
        "tiny_order_id": tiny_order_id,
        "tiny_order_number": tiny_order_number,
        "date": _client_wallet_pick(order, "data_pedido", "dataPedido", "data", "data_criacao") or _client_wallet_pick(fallback, "data_pedido", "data"),
        "status": _client_wallet_pick(order, "situacao", "status") or _client_wallet_pick(fallback, "situacao", "status"),
        "total_value": _safe_float(order.get("valor") or order.get("valor_total") or order.get("total") or fallback.get("valor"), 0),
        "seller_name": _client_wallet_pick(order, "nome_vendedor", "nomeVendedor", "vendedor_nome") or _client_wallet_pick(seller, "nome", "name"),
        "payment_name": payment_name,
        "notes": _client_wallet_pick(order, "obs", "observacoes", "observacao", "observacao_interna"),
        "products": _client_wallet_order_items(order),
        "raw": order,
    }


def _client_wallet_update_last_purchase(company_key: str, tiny_client_id: str, purchases: List[Dict[str, Any]]) -> Dict[str, Any]:
    parsed_purchases = []
    for purchase in purchases or []:
        parsed = _client_wallet_parse_purchase_date(purchase.get("date"))
        if parsed:
            parsed_purchases.append((parsed, purchase))
    latest_dt = None
    latest = None
    if parsed_purchases:
        latest_dt, latest = max(parsed_purchases, key=lambda item: item[0])

    with _db() as conn:
        with conn.cursor() as cur:
            if latest_dt and latest:
                cur.execute(
                    """
                    UPDATE erp.client_wallet
                    SET last_purchase_date=%s,
                        last_purchase_order_number=%s,
                        last_purchase_total=%s,
                        last_purchase_synced_at=now(),
                        updated_at=now()
                    WHERE company_key=%s AND tiny_client_id=%s
                    RETURNING id, company_key, tiny_client_id, codigo, nome, fantasia, cpf_cnpj, email,
                              telefone, celular, cidade, uf, endereco, numero, bairro, cep, situacao,
                              ativo, vendedor_id, vendedor_nome, last_seen_at,
                              last_purchase_date, last_purchase_order_number, last_purchase_total, last_purchase_synced_at,
                              created_at, updated_at
                    """,
                    (
                        latest_dt,
                        latest.get("tiny_order_number") or latest.get("tiny_order_id"),
                        latest.get("total_value") or 0,
                        company_key,
                        str(tiny_client_id),
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE erp.client_wallet
                    SET last_purchase_synced_at=now(),
                        updated_at=now()
                    WHERE company_key=%s AND tiny_client_id=%s
                    RETURNING id, company_key, tiny_client_id, codigo, nome, fantasia, cpf_cnpj, email,
                              telefone, celular, cidade, uf, endereco, numero, bairro, cep, situacao,
                              ativo, vendedor_id, vendedor_nome, last_seen_at,
                              last_purchase_date, last_purchase_order_number, last_purchase_total, last_purchase_synced_at,
                              created_at, updated_at
                    """,
                    (company_key, str(tiny_client_id)),
                )
            row = cur.fetchone()
    return _client_wallet_row_public(dict(row)) if row else {}


def _client_wallet_digits_only(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _client_wallet_purchase_date_from_quote(row: Dict[str, Any]) -> Optional[dt.datetime]:
    payload = _from_json(row.get("payload"), {}) or {}
    for value in (
        payload.get("approved_at"),
        payload.get("data_aprovacao"),
        payload.get("data_pedido"),
        payload.get("date"),
        row.get("separated_at"),
        row.get("checked_at"),
        row.get("updated_at"),
        row.get("created_at"),
    ):
        parsed = _client_wallet_parse_purchase_date(value)
        if parsed:
            return parsed
    return None


def _client_wallet_quote_items(quote_id: str) -> List[Dict[str, Any]]:
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM erp.quote_items
                WHERE quote_id=%s
                ORDER BY line
                """,
                (str(quote_id),),
            )
            rows = [dict(r) for r in cur.fetchall()]

    products: List[Dict[str, Any]] = []
    for raw in rows:
        item = _normalize_quote_item_financials(raw)
        products.append({
            "sku": _clean_str(item.get("sku") or item.get("codigo")),
            "name": _clean_str(item.get("nome") or item.get("descricao")),
            "quantity": _safe_float(item.get("quantity") or item.get("qty"), 0),
            "unit_price": _safe_float(item.get("unit_price_disc") or item.get("unit_price"), 0),
            "total_price": _safe_float(item.get("line_total") or item.get("total_price"), 0),
            "discount": _safe_float(item.get("discount_pct"), 0),
            "unit": _clean_str(item.get("unit") or item.get("unidade")),
            "raw": item.get("raw") or raw,
        })
    return products


def _client_wallet_quote_total(row: Dict[str, Any], products: List[Dict[str, Any]]) -> float:
    quote = _quote_row_public(row)
    total = _safe_float(
        quote.get("total")
        or quote.get("total_net")
        or quote.get("valor_total")
        or quote.get("amount_total"),
        0,
    )
    if total <= 0:
        total = sum(_safe_float(item.get("total_price"), 0) for item in products or [])
    return round(total, 2)


def _client_wallet_fetch_purchase_summaries(company_key: str, client: Dict[str, Any], limit: int = 3) -> List[Dict[str, Any]]:
    company_key = _company_key(company_key)
    limit = max(1, min(3, int(limit or 3)))
    tiny_client_id = _clean_str(client.get("tiny_client_id"))
    cpf_digits = _client_wallet_digits_only(client.get("cpf_cnpj"))
    client_name = _clean_str(client.get("nome") or client.get("fantasia"))

    match_sql: List[str] = []
    match_params: List[Any] = []
    if tiny_client_id:
        match_sql.append("CAST(q.client_id AS TEXT) = %s")
        match_params.append(tiny_client_id)
    if cpf_digits:
        match_sql.append(
            "regexp_replace(COALESCE(q.client_snapshot->>'cpf_cnpj', q.client_snapshot->>'cpfCnpj', q.client_snapshot->>'cpf', ''), '[^0-9]', '', 'g') = %s"
        )
        match_params.append(cpf_digits)
    if client_name:
        match_sql.append("LOWER(COALESCE(q.client_snapshot->>'nome', q.client_snapshot->>'name', '')) = LOWER(%s)")
        match_params.append(client_name)
    if not match_sql:
        return []

    valid_statuses = (
        "aprovado",
        "preparando envio",
        "pronto para envio",
        "faturado",
        "separado",
        "entregue",
    )
    invalid_statuses = ("cancelado", "cancelada", "em aberto", "rascunho", "excluido", "excluído")
    params: List[Any] = [company_key, valid_statuses, valid_statuses, invalid_statuses, *match_params, limit]

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT q.quote_id, q.quote_number, q.company_key, q.tiny_order_id, q.tiny_order_number,
                       q.status, q.internal_status, q.client_id, q.client_snapshot, q.seller_name,
                       q.totals, q.payload, q.created_at, q.updated_at,
                       so.status AS separation_status, so.separated_at, so.checked_at
                FROM erp.quotes q
                LEFT JOIN erp.separation_orders so
                  ON so.company_key = q.company_key
                 AND (
                       so.quote_id = q.quote_id
                       OR (q.tiny_order_id IS NOT NULL AND so.tiny_order_id = q.tiny_order_id)
                     )
                WHERE q.company_key = %s
                  AND (
                        LOWER(COALESCE(q.internal_status, '')) IN %s
                        OR LOWER(COALESCE(so.status, '')) IN %s
                      )
                  AND LOWER(COALESCE(q.internal_status, '')) NOT IN %s
                  AND ({' OR '.join(match_sql)})
                ORDER BY COALESCE(so.separated_at, so.checked_at, q.updated_at, q.created_at) DESC
                LIMIT %s
                """,
                params,
            )
            rows = [dict(r) for r in cur.fetchall()]

    summaries: List[Dict[str, Any]] = []
    for row in rows:
        products = _client_wallet_quote_items(str(row.get("quote_id")))
        purchase_dt = _client_wallet_purchase_date_from_quote(row)
        quote_number = _clean_str(row.get("quote_number"))
        tiny_order_number = _clean_str(row.get("tiny_order_number"))
        order_number = tiny_order_number or quote_number
        payload = _from_json(row.get("payload"), {}) or {}
        summaries.append({
            "source": "local_orders",
            "quote_id": _clean_str(row.get("quote_id")),
            "quote_number": quote_number,
            "order_number": order_number,
            "tiny_order_id": _clean_str(row.get("tiny_order_id")),
            "tiny_order_number": order_number,
            "date": purchase_dt.isoformat() if purchase_dt else "",
            "status": _clean_str(row.get("internal_status") or row.get("separation_status") or row.get("status")),
            "total_value": _client_wallet_quote_total(row, products),
            "seller_name": _clean_str(row.get("seller_name")),
            "payment_name": _clean_str(
                payload.get("payment_name")
                or payload.get("forma_pagamento")
                or payload.get("condicao_pagamento")
                or payload.get("payment")
            ),
            "notes": _clean_str(payload.get("notes") or payload.get("observacoes") or payload.get("observacao")),
            "products": products,
            "raw": {"quote": _quote_row_public(row), "source": "local_orders"},
        })
    return summaries


def _client_wallet_refresh_last_purchase_from_local_history(row: Dict[str, Any]) -> Dict[str, Any]:
    client = dict(row or {})
    if client.get("last_purchase_date"):
        return client
    company_key = _clean_str(client.get("company_key"))
    tiny_client_id = _clean_str(client.get("tiny_client_id"))
    if not company_key or not tiny_client_id:
        return client
    try:
        summaries = _client_wallet_fetch_purchase_summaries(company_key, client, limit=1)
        if not summaries:
            return client
        updated = _client_wallet_update_last_purchase(company_key, tiny_client_id, summaries)
        return updated or client
    except Exception as e:
        print(f"[client-wallet-local-history] Falha ao atualizar ultima compra client={tiny_client_id}: {e}")
        return client


@app.get("/api/client-wallet/{tiny_client_id}/last-purchases")
@app.get("/client-wallet/{tiny_client_id}/last-purchases")
def client_wallet_last_purchases(
    request: Request,
    tiny_client_id: str,
    company: str = "parton",
    limit: int = Query(default=3, ge=1, le=3),
):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    wallet_scope = _resolve_client_wallet_scope(user, company_key)
    _ensure_client_wallet_tables()
    where = ["company_key=%s", "tiny_client_id=%s"]
    params: List[Any] = [company_key, str(tiny_client_id)]
    _apply_client_wallet_scope(where, params, wallet_scope)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM erp.client_wallet
                WHERE {" AND ".join(where)}
                LIMIT 1
                """,
                params,
            )
            client = dict(cur.fetchone() or {})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado na carteira desta empresa.")

    try:
        summaries = _client_wallet_fetch_purchase_summaries(company_key, client, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar histórico local de compras: {e}")

    updated_client = _client_wallet_update_last_purchase(company_key, str(tiny_client_id), summaries)

    return {
        "ok": True,
        "source": "local_orders",
        "company_key": company_key,
        "tiny_client_id": str(tiny_client_id),
        "limit": limit,
        "client": {
            "nome": client.get("nome"),
            "fantasia": client.get("fantasia"),
            "cpf_cnpj": client.get("cpf_cnpj"),
        },
        "updated_client": updated_client,
        "items": summaries,
        "message": "" if summaries else "Nenhuma compra encontrada no histórico local.",
    }


@app.get("/api/seller/order-wallet")
@app.get("/seller/order-wallet")
def seller_order_wallet(request: Request, company: str = "parton", start_date: str = "", end_date: str = "", limit: int = 500):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    return {
        "ok": True,
        "company": company_key,
        "email": user.get("login"),
        "is_admin": _clean_str(user.get("role")).lower() == "admin",
        "items": [],
        "count": 0,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        "source": "local_empty",
    }


@app.get("/api/seller/tiny-wallet-live")
@app.get("/seller/tiny-wallet-live")
def seller_tiny_wallet_live(request: Request, company: str = "parton", q: str = "", page_num: int = 1):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    return {
        "ok": True,
        "company": company_key,
        "items": [],
        "page_num": page_num,
        "source": "local_empty",
    }


@app.get("/api/admin/companies")
@app.get("/admin/companies")
def list_companies(request: Request):
    user = _require_auth_user(request)
    user_role = _clean_str(user.get("role")).lower()
    allowed_companies = set(_auth_user_companies(user.get("id")))
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT company_key, company_name, tiny_base_url, active,
                       CASE WHEN COALESCE(tiny_token, '') <> '' THEN TRUE ELSE FALSE END AS has_db_token,
                       updated_at
                FROM erp.companies
                ORDER BY company_key
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
    if user_role != "admin":
        rows = [row for row in rows if _company_key(row.get("company_key")) in allowed_companies]
    return {"ok": True, "items": rows}


@app.get("/api/company/context")
@app.get("/company/context")
def company_context(request: Request, company: str = "parton"):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    row = _company_row(company_key)
    key = row["company_key"]
    return {
        "ok": True,
        "company": key,
        "company_key": key,
        "company_name": row.get("company_name"),
        "active": bool(row.get("active")),
        "tiny_token_configured": bool(
            os.getenv(f"TINY_TOKEN_{key.upper()}", "").strip()
            or os.getenv(f"TINY_{key.upper()}_TOKEN", "").strip()
            or row.get("tiny_token")
        ),
        "user": _auth_public_user_row(user),
    }


def _catalog_require_admin(request: Request) -> Dict[str, Any]:
    user = _require_auth_user(request)
    if _clean_str(user.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")
    return user


_PRODUCTS_LOCAL_FIRST_COLUMNS = [
    "id",
    "company_key",
    "tiny_product_id",
    "tiny_sync_status",
    "tiny_sync_error",
    "tiny_synced_at",
    "origin",
    "tipo_produto",
    "nome",
    "sku",
    "gtin",
    "origem",
    "unidade",
    "ncm",
    "cest",
    "preco_venda",
    "preco_custo",
    "peso_liquido",
    "peso_bruto",
    "numero_volumes",
    "tipo_embalagem",
    "embalagem",
    "largura",
    "altura",
    "comprimento",
    "controlar_estoque",
    "estoque_inicial",
    "estoque_minimo",
    "estoque_maximo",
    "controlar_lotes",
    "localizacao",
    "dias_preparacao",
    "marca",
    "tabela_medidas",
    "descricao_complementar",
    "link_video",
    "slug",
    "keywords",
    "titulo_seo",
    "descricao_seo",
    "tags",
    "unidade_por_caixa",
    "linha_produto",
    "garantia",
    "markup",
    "permitir_vendas",
    "gtin_tributavel",
    "unidade_tributavel",
    "fator_conversao",
    "codigo_enquadramento_ipi",
    "valor_ipi_fixo",
    "codigo_enquadramento_legal_ipi",
    "ex_tipi",
    "codigo_fornecedor",
    "observacoes",
    "dimensoes_payload",
    "estoque_payload",
    "seo_payload",
    "atributos_payload",
    "anuncios_payload",
    "custos_payload",
    "fornecedores_payload",
    "imagens_payload",
    "tiny_raw_payload",
    "created_at",
    "updated_at",
]


def _ensure_products_local_first_table():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS erp")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.products (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  tiny_product_id TEXT,
                  tiny_sync_status TEXT DEFAULT 'local',
                  tiny_sync_error TEXT,
                  tiny_synced_at TIMESTAMPTZ,
                  origin TEXT DEFAULT 'local',
                  tipo_produto TEXT,
                  nome TEXT NOT NULL,
                  sku TEXT,
                  gtin TEXT,
                  origem TEXT,
                  unidade TEXT,
                  ncm TEXT,
                  cest TEXT,
                  preco_venda NUMERIC,
                  preco_custo NUMERIC,
                  peso_liquido NUMERIC,
                  peso_bruto NUMERIC,
                  numero_volumes NUMERIC,
                  tipo_embalagem TEXT,
                  embalagem TEXT,
                  largura NUMERIC,
                  altura NUMERIC,
                  comprimento NUMERIC,
                  controlar_estoque BOOLEAN DEFAULT FALSE,
                  estoque_inicial NUMERIC,
                  estoque_minimo NUMERIC,
                  estoque_maximo NUMERIC,
                  controlar_lotes BOOLEAN DEFAULT FALSE,
                  localizacao TEXT,
                  dias_preparacao INTEGER,
                  marca TEXT,
                  tabela_medidas TEXT,
                  descricao_complementar TEXT,
                  link_video TEXT,
                  slug TEXT,
                  keywords TEXT,
                  titulo_seo TEXT,
                  descricao_seo TEXT,
                  tags TEXT,
                  unidade_por_caixa NUMERIC,
                  linha_produto TEXT,
                  garantia TEXT,
                  markup NUMERIC,
                  permitir_vendas BOOLEAN DEFAULT TRUE,
                  gtin_tributavel TEXT,
                  unidade_tributavel TEXT,
                  fator_conversao NUMERIC,
                  codigo_enquadramento_ipi TEXT,
                  valor_ipi_fixo NUMERIC,
                  codigo_enquadramento_legal_ipi TEXT,
                  ex_tipi TEXT,
                  codigo_fornecedor TEXT,
                  observacoes TEXT,
                  dimensoes_payload JSONB DEFAULT '{}'::jsonb,
                  estoque_payload JSONB DEFAULT '{}'::jsonb,
                  seo_payload JSONB DEFAULT '{}'::jsonb,
                  atributos_payload JSONB DEFAULT '[]'::jsonb,
                  anuncios_payload JSONB DEFAULT '[]'::jsonb,
                  custos_payload JSONB DEFAULT '{}'::jsonb,
                  fornecedores_payload JSONB DEFAULT '[]'::jsonb,
                  imagens_payload JSONB DEFAULT '[]'::jsonb,
                  tiny_raw_payload JSONB DEFAULT '{}'::jsonb,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for column_def in (
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "tiny_product_id TEXT",
                "tiny_sync_status TEXT DEFAULT 'local'",
                "tiny_sync_error TEXT",
                "tiny_synced_at TIMESTAMPTZ",
                "origin TEXT DEFAULT 'local'",
                "tipo_produto TEXT",
                "nome TEXT NOT NULL DEFAULT ''",
                "sku TEXT",
                "gtin TEXT",
                "origem TEXT",
                "unidade TEXT",
                "ncm TEXT",
                "cest TEXT",
                "preco_venda NUMERIC",
                "preco_custo NUMERIC",
                "peso_liquido NUMERIC",
                "peso_bruto NUMERIC",
                "numero_volumes NUMERIC",
                "tipo_embalagem TEXT",
                "embalagem TEXT",
                "largura NUMERIC",
                "altura NUMERIC",
                "comprimento NUMERIC",
                "controlar_estoque BOOLEAN DEFAULT FALSE",
                "estoque_inicial NUMERIC",
                "estoque_minimo NUMERIC",
                "estoque_maximo NUMERIC",
                "controlar_lotes BOOLEAN DEFAULT FALSE",
                "localizacao TEXT",
                "dias_preparacao INTEGER",
                "marca TEXT",
                "tabela_medidas TEXT",
                "descricao_complementar TEXT",
                "link_video TEXT",
                "slug TEXT",
                "keywords TEXT",
                "titulo_seo TEXT",
                "descricao_seo TEXT",
                "tags TEXT",
                "unidade_por_caixa NUMERIC",
                "linha_produto TEXT",
                "garantia TEXT",
                "markup NUMERIC",
                "permitir_vendas BOOLEAN DEFAULT TRUE",
                "gtin_tributavel TEXT",
                "unidade_tributavel TEXT",
                "fator_conversao NUMERIC",
                "codigo_enquadramento_ipi TEXT",
                "valor_ipi_fixo NUMERIC",
                "codigo_enquadramento_legal_ipi TEXT",
                "ex_tipi TEXT",
                "codigo_fornecedor TEXT",
                "observacoes TEXT",
                "dimensoes_payload JSONB DEFAULT '{}'::jsonb",
                "estoque_payload JSONB DEFAULT '{}'::jsonb",
                "seo_payload JSONB DEFAULT '{}'::jsonb",
                "atributos_payload JSONB DEFAULT '[]'::jsonb",
                "anuncios_payload JSONB DEFAULT '[]'::jsonb",
                "custos_payload JSONB DEFAULT '{}'::jsonb",
                "fornecedores_payload JSONB DEFAULT '[]'::jsonb",
                "imagens_payload JSONB DEFAULT '[]'::jsonb",
                "tiny_raw_payload JSONB DEFAULT '{}'::jsonb",
                "stock_physical NUMERIC",
                "stock_reserved NUMERIC",
                "stock_available NUMERIC",
                "stock_synced_at TIMESTAMPTZ",
                "stock_sync_error TEXT",
                "stock_payload JSONB DEFAULT '{}'::jsonb",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ):
                column_name = column_def.split()[0]
                cur.execute(f"ALTER TABLE erp.products ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS products_company_tiny_uidx
                ON erp.products (company_key, tiny_product_id)
                WHERE tiny_product_id IS NOT NULL AND tiny_product_id <> ''
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS products_company_sku_uidx
                ON erp.products (company_key, sku)
                WHERE sku IS NOT NULL AND sku <> ''
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS products_company_idx ON erp.products (company_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS products_company_name_idx ON erp.products (company_key, nome)")
            cur.execute("CREATE INDEX IF NOT EXISTS products_company_gtin_idx ON erp.products (company_key, gtin)")
            cur.execute("CREATE INDEX IF NOT EXISTS products_company_sync_idx ON erp.products (company_key, tiny_sync_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS products_company_stock_synced_idx ON erp.products (company_key, stock_synced_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS products_company_updated_idx ON erp.products (company_key, updated_at)")
    _TABLE_COLUMNS_CACHE.pop("erp.products", None)


def _ensure_product_stock_sync_tables():
    _ensure_products_local_first_table()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.product_stock_sync_runs (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  status TEXT NOT NULL,
                  dry_run BOOLEAN NOT NULL DEFAULT true,
                  started_at TIMESTAMPTZ DEFAULT now(),
                  finished_at TIMESTAMPTZ NULL,
                  requested_by TEXT NULL,
                  limit_per_run INTEGER NULL,
                  processed_count INTEGER DEFAULT 0,
                  updated_count INTEGER DEFAULT 0,
                  skipped_count INTEGER DEFAULT 0,
                  errors_count INTEGER DEFAULT 0,
                  errors JSONB DEFAULT '[]'::jsonb,
                  summary JSONB DEFAULT '{}'::jsonb,
                  params JSONB DEFAULT '{}'::jsonb
                )
                """
            )
            for column_def in (
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "status TEXT NOT NULL DEFAULT 'dry_run'",
                "dry_run BOOLEAN NOT NULL DEFAULT true",
                "started_at TIMESTAMPTZ DEFAULT now()",
                "finished_at TIMESTAMPTZ NULL",
                "requested_by TEXT NULL",
                "limit_per_run INTEGER NULL",
                "processed_count INTEGER DEFAULT 0",
                "updated_count INTEGER DEFAULT 0",
                "skipped_count INTEGER DEFAULT 0",
                "errors_count INTEGER DEFAULT 0",
                "errors JSONB DEFAULT '[]'::jsonb",
                "summary JSONB DEFAULT '{}'::jsonb",
                "params JSONB DEFAULT '{}'::jsonb",
            ):
                cur.execute(f"ALTER TABLE erp.product_stock_sync_runs ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_sync_runs_company_started_idx
                ON erp.product_stock_sync_runs (company_key, started_at DESC)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_sync_runs_running_idx
                ON erp.product_stock_sync_runs (company_key)
                WHERE status = 'running'
                """
            )


_PRODUCT_CONFLICT_DECISIONS = {
    "ignore_duplicate_old_tiny",
    "needs_tiny_sku_fix",
    "review_later",
    "import_as_separate_local_later",
}


def _ensure_product_conflict_decisions_table():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS erp")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.product_conflict_decisions (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  sku TEXT NOT NULL,
                  local_product_id BIGINT NULL,
                  local_tiny_product_id TEXT NULL,
                  conflict_tiny_product_id TEXT NULL,
                  conflict_tiny_name TEXT NULL,
                  decision TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'active',
                  notes TEXT NULL,
                  created_by TEXT NULL,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now(),
                  raw_payload JSONB NULL
                )
                """
            )
            for column_def in (
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "sku TEXT NOT NULL DEFAULT ''",
                "local_product_id BIGINT NULL",
                "local_tiny_product_id TEXT NULL",
                "conflict_tiny_product_id TEXT NULL",
                "conflict_tiny_name TEXT NULL",
                "decision TEXT NOT NULL DEFAULT 'review_later'",
                "status TEXT NOT NULL DEFAULT 'active'",
                "notes TEXT NULL",
                "created_by TEXT NULL",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
                "raw_payload JSONB NULL",
            ):
                cur.execute(f"ALTER TABLE erp.product_conflict_decisions ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_conflict_decisions_lookup_idx
                ON erp.product_conflict_decisions (
                  company_key, sku, local_product_id, local_tiny_product_id, conflict_tiny_product_id, status
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_conflict_decisions_company_status_idx
                ON erp.product_conflict_decisions (company_key, status, updated_at)
                """
            )


def _product_conflict_decision_key(item: Dict[str, Any]) -> tuple:
    return (
        _clean_str(item.get("sku")),
        _safe_int(item.get("local_product_id"), None),
        _clean_str(item.get("local_tiny_product_id")),
        _clean_str(item.get("conflict_tiny_product_id") or item.get("tiny_product_id")),
    )


def _product_conflict_decision_public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "company_key": row.get("company_key"),
        "sku": row.get("sku"),
        "local_product_id": row.get("local_product_id"),
        "local_tiny_product_id": row.get("local_tiny_product_id"),
        "conflict_tiny_product_id": row.get("conflict_tiny_product_id"),
        "conflict_tiny_name": row.get("conflict_tiny_name"),
        "decision": row.get("decision"),
        "status": row.get("status"),
        "notes": row.get("notes"),
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "raw_payload": row.get("raw_payload"),
    }


def _product_conflict_decisions_for_company(company_key: str, status: str = "active") -> List[Dict[str, Any]]:
    _ensure_product_conflict_decisions_table()
    where = ["company_key=%s"]
    params: List[Any] = [company_key]
    if _clean_str(status):
        where.append("status=%s")
        params.append(_clean_str(status))
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM erp.product_conflict_decisions
                WHERE {' AND '.join(where)}
                ORDER BY updated_at DESC, id DESC
                """,
                params,
            )
            return [_product_conflict_decision_public(dict(r)) for r in cur.fetchall()]


def _attach_product_conflict_decisions(company_key: str, result: Dict[str, Any]) -> Dict[str, Any]:
    decisions = _product_conflict_decisions_for_company(company_key, status="active")
    by_key = {_product_conflict_decision_key(item): item for item in decisions}

    enriched_conflicts = []
    for conflict in result.get("tiny_vs_local_conflicts") or []:
        item = dict(conflict)
        decision = by_key.get(_product_conflict_decision_key(item))
        item["decision"] = decision
        item["decision_status"] = decision.get("status") if decision else None
        item["decision_value"] = decision.get("decision") if decision else None
        enriched_conflicts.append(item)
    if "tiny_vs_local_conflicts" in result:
        result["tiny_vs_local_conflicts"] = enriched_conflicts
    result["conflict_decisions"] = {
        "count": len(decisions),
        "items": decisions[:100],
    }
    return result


def _ensure_product_catalog_tables():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.product_catalog (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  tiny_product_id TEXT,
                  sku TEXT,
                  name_tiny TEXT,
                  description_tiny TEXT,
                  category TEXT,
                  brand TEXT,
                  unit TEXT,
                  price_tiny NUMERIC,
                  average_cost NUMERIC,
                  stock_available NUMERIC,
                  stock_synced_at TIMESTAMPTZ,
                  situation TEXT,
                  image_url_tiny TEXT,
                  catalog_title TEXT,
                  catalog_description TEXT,
                  catalog_benefits TEXT,
                  catalog_tags TEXT,
                  catalog_price NUMERIC,
                  catalog_image_url TEXT,
                  catalog_image_path TEXT,
                  catalog_image_filename TEXT,
                  full_price_percent NUMERIC,
                  full_price_value NUMERIC,
                  billed_price_percent NUMERIC,
                  billed_price_value NUMERIC,
                  cash_price_percent NUMERIC,
                  cash_price_value NUMERIC,
                  price_mode TEXT DEFAULT 'custom',
                  price_table_id BIGINT,
                  catalog_active BOOLEAN DEFAULT FALSE,
                  catalog_featured BOOLEAN DEFAULT FALSE,
                  catalog_order INTEGER,
                  internal_notes TEXT,
                  last_source_sync_at TIMESTAMPTZ,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for column_def in (
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "tiny_product_id TEXT",
                "sku TEXT",
                "name_tiny TEXT",
                "description_tiny TEXT",
                "category TEXT",
                "brand TEXT",
                "unit TEXT",
                "price_tiny NUMERIC",
                "average_cost NUMERIC",
                "stock_available NUMERIC",
                "stock_synced_at TIMESTAMPTZ",
                "situation TEXT",
                "image_url_tiny TEXT",
                "catalog_title TEXT",
                "catalog_description TEXT",
                "catalog_benefits TEXT",
                "catalog_tags TEXT",
                "catalog_price NUMERIC",
                "catalog_image_url TEXT",
                "catalog_image_path TEXT",
                "catalog_image_filename TEXT",
                "full_price_percent NUMERIC",
                "full_price_value NUMERIC",
                "billed_price_percent NUMERIC",
                "billed_price_value NUMERIC",
                "cash_price_percent NUMERIC",
                "cash_price_value NUMERIC",
                "price_mode TEXT DEFAULT 'custom'",
                "price_table_id BIGINT",
                "catalog_active BOOLEAN DEFAULT FALSE",
                "catalog_featured BOOLEAN DEFAULT FALSE",
                "catalog_order INTEGER",
                "internal_notes TEXT",
                "last_source_sync_at TIMESTAMPTZ",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ):
                cur.execute(f"ALTER TABLE erp.product_catalog ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS product_catalog_company_tiny_uidx
                ON erp.product_catalog (company_key, tiny_product_id)
                WHERE tiny_product_id IS NOT NULL AND tiny_product_id <> ''
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS product_catalog_company_sku_uidx
                ON erp.product_catalog (company_key, sku)
                WHERE sku IS NOT NULL AND sku <> ''
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS product_catalog_company_idx ON erp.product_catalog (company_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS product_catalog_active_idx ON erp.product_catalog (company_key, catalog_active)")
            cur.execute("CREATE INDEX IF NOT EXISTS product_catalog_featured_idx ON erp.product_catalog (company_key, catalog_featured)")
            cur.execute("CREATE INDEX IF NOT EXISTS product_catalog_sku_idx ON erp.product_catalog (company_key, sku)")
            cur.execute("CREATE INDEX IF NOT EXISTS product_catalog_name_idx ON erp.product_catalog (company_key, name_tiny)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.catalog_price_tables (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  mode TEXT NOT NULL DEFAULT 'percent',
                  base_field TEXT,
                  full_price_percent NUMERIC,
                  billed_price_percent NUMERIC,
                  cash_price_percent NUMERIC,
                  active BOOLEAN DEFAULT TRUE,
                  is_default BOOLEAN DEFAULT FALSE,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for column_def in (
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "name TEXT NOT NULL DEFAULT 'Tabela'",
                "mode TEXT NOT NULL DEFAULT 'percent'",
                "base_field TEXT",
                "full_price_percent NUMERIC",
                "billed_price_percent NUMERIC",
                "cash_price_percent NUMERIC",
                "active BOOLEAN DEFAULT TRUE",
                "is_default BOOLEAN DEFAULT FALSE",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ):
                cur.execute(f"ALTER TABLE erp.catalog_price_tables ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_price_tables_company_idx ON erp.catalog_price_tables (company_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_price_tables_active_idx ON erp.catalog_price_tables (company_key, active)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_price_tables_default_idx ON erp.catalog_price_tables (company_key, is_default)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.catalog_campaigns (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  description TEXT,
                  start_date DATE NOT NULL,
                  end_date DATE NOT NULL,
                  discount_percent NUMERIC,
                  price_table_id BIGINT,
                  active BOOLEAN DEFAULT TRUE,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for column_def in (
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "name TEXT NOT NULL DEFAULT 'Campanha'",
                "description TEXT",
                "start_date DATE NOT NULL DEFAULT CURRENT_DATE",
                "end_date DATE NOT NULL DEFAULT CURRENT_DATE",
                "discount_percent NUMERIC",
                "price_table_id BIGINT",
                "active BOOLEAN DEFAULT TRUE",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ):
                cur.execute(f"ALTER TABLE erp.catalog_campaigns ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.catalog_campaign_items (
                  id BIGSERIAL PRIMARY KEY,
                  campaign_id BIGINT NOT NULL,
                  product_catalog_id BIGINT NOT NULL,
                  custom_full_price_value NUMERIC,
                  custom_billed_price_value NUMERIC,
                  custom_cash_price_value NUMERIC,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for column_def in (
                "campaign_id BIGINT NOT NULL DEFAULT 0",
                "product_catalog_id BIGINT NOT NULL DEFAULT 0",
                "custom_full_price_value NUMERIC",
                "custom_billed_price_value NUMERIC",
                "custom_cash_price_value NUMERIC",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ):
                cur.execute(f"ALTER TABLE erp.catalog_campaign_items ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_campaigns_company_idx ON erp.catalog_campaigns (company_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_campaigns_active_idx ON erp.catalog_campaigns (company_key, active)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_campaigns_period_idx ON erp.catalog_campaigns (company_key, start_date, end_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_campaign_items_campaign_idx ON erp.catalog_campaign_items (campaign_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_campaign_items_product_idx ON erp.catalog_campaign_items (product_catalog_id)")
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS catalog_campaign_items_campaign_product_uidx
                ON erp.catalog_campaign_items (campaign_id, product_catalog_id)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.catalog_layouts (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  title TEXT,
                  subtitle TEXT,
                  notes TEXT,
                  valid_until DATE,
                  use_active_campaigns BOOLEAN DEFAULT TRUE,
                  show_full_price BOOLEAN DEFAULT TRUE,
                  show_billed_price BOOLEAN DEFAULT TRUE,
                  show_cash_price BOOLEAN DEFAULT TRUE,
                  show_sku BOOLEAN DEFAULT TRUE,
                  show_tags BOOLEAN DEFAULT FALSE,
                  show_stock BOOLEAN DEFAULT FALSE,
                  show_without_image BOOLEAN DEFAULT TRUE,
                  only_active_products BOOLEAN DEFAULT TRUE,
                  active BOOLEAN DEFAULT TRUE,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for column_def in (
                "company_key TEXT NOT NULL DEFAULT 'parton'",
                "name TEXT NOT NULL DEFAULT 'Configuração'",
                "title TEXT",
                "subtitle TEXT",
                "notes TEXT",
                "valid_until DATE",
                "use_active_campaigns BOOLEAN DEFAULT TRUE",
                "show_full_price BOOLEAN DEFAULT TRUE",
                "show_billed_price BOOLEAN DEFAULT TRUE",
                "show_cash_price BOOLEAN DEFAULT TRUE",
                "show_sku BOOLEAN DEFAULT TRUE",
                "show_tags BOOLEAN DEFAULT FALSE",
                "show_stock BOOLEAN DEFAULT FALSE",
                "show_without_image BOOLEAN DEFAULT TRUE",
                "only_active_products BOOLEAN DEFAULT TRUE",
                "active BOOLEAN DEFAULT TRUE",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ):
                cur.execute(f"ALTER TABLE erp.catalog_layouts ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_layouts_company_idx ON erp.catalog_layouts (company_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_layouts_active_idx ON erp.catalog_layouts (company_key, active)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.catalog_layout_items (
                  id BIGSERIAL PRIMARY KEY,
                  layout_id BIGINT NOT NULL,
                  product_catalog_id BIGINT NOT NULL,
                  sort_order INTEGER,
                  selected BOOLEAN DEFAULT TRUE,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for column_def in (
                "layout_id BIGINT NOT NULL DEFAULT 0",
                "product_catalog_id BIGINT NOT NULL DEFAULT 0",
                "sort_order INTEGER",
                "selected BOOLEAN DEFAULT TRUE",
                "created_at TIMESTAMPTZ DEFAULT now()",
                "updated_at TIMESTAMPTZ DEFAULT now()",
            ):
                cur.execute(f"ALTER TABLE erp.catalog_layout_items ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_layout_items_layout_idx ON erp.catalog_layout_items (layout_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS catalog_layout_items_product_idx ON erp.catalog_layout_items (product_catalog_id)")
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS catalog_layout_items_layout_product_uidx
                ON erp.catalog_layout_items (layout_id, product_catalog_id)
                """
            )


def _catalog_row_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    fallback_raw = _from_json(out.get("latest_product_raw"), {}) or {}
    if out.get("average_cost") is None:
        out["average_cost"] = _catalog_extract_average_cost(fallback_raw)
    for key in (
        "price_tiny",
        "average_cost",
        "stock_available",
        "catalog_price",
        "full_price_percent",
        "full_price_value",
        "billed_price_percent",
        "billed_price_value",
        "cash_price_percent",
        "cash_price_value",
        "table_full_price_percent",
        "table_billed_price_percent",
        "table_cash_price_percent",
        "simulated_full_price_percent",
        "simulated_billed_price_percent",
        "simulated_cash_price_percent",
        "campaign_discount_percent",
        "campaign_custom_full_price_value",
        "campaign_custom_billed_price_value",
        "campaign_custom_cash_price_value",
    ):
        if out.get(key) is not None:
            out[key] = _safe_float(out.get(key), 0)
    out["catalog_active"] = bool(out.get("catalog_active"))
    out["catalog_featured"] = bool(out.get("catalog_featured"))
    out["price_mode"] = _clean_str(out.get("price_mode") or "custom").lower() or "custom"
    using_simulation = bool(out.get("simulated_price_table_id") and out.get("simulated_price_table_active"))
    if using_simulation and _clean_str(out.get("simulated_price_table_mode") or "percent").lower() == "percent":
        base_value = _catalog_price_base_value(out, out.get("simulated_base_field") or "price_tiny")
        out["simulated_price_table_id"] = int(out.get("simulated_price_table_id"))
        out["final_full_price_percent"] = out.get("simulated_full_price_percent")
        out["final_billed_price_percent"] = out.get("simulated_billed_price_percent")
        out["final_cash_price_percent"] = out.get("simulated_cash_price_percent")
        out["final_full_price_value"] = _catalog_calculated_price(base_value, out.get("simulated_full_price_percent"))
        out["final_billed_price_value"] = _catalog_calculated_price(base_value, out.get("simulated_billed_price_percent"))
        out["final_cash_price_value"] = _catalog_calculated_price(base_value, out.get("simulated_cash_price_percent"))
    else:
        base_value = _catalog_price_base_value(out, out.get("table_base_field") or "price_tiny")
        using_table = out["price_mode"] == "table" and out.get("price_table_id") and bool(out.get("price_table_active"))
        if using_table and _clean_str(out.get("price_table_mode") or "percent").lower() == "percent":
            out["final_full_price_percent"] = out.get("table_full_price_percent")
            out["final_billed_price_percent"] = out.get("table_billed_price_percent")
            out["final_cash_price_percent"] = out.get("table_cash_price_percent")
            out["final_full_price_value"] = _catalog_calculated_price(base_value, out.get("table_full_price_percent"))
            out["final_billed_price_value"] = _catalog_calculated_price(base_value, out.get("table_billed_price_percent"))
            out["final_cash_price_value"] = _catalog_calculated_price(base_value, out.get("table_cash_price_percent"))
        else:
            out["final_full_price_percent"] = out.get("full_price_percent")
            out["final_billed_price_percent"] = out.get("billed_price_percent")
            out["final_cash_price_percent"] = out.get("cash_price_percent")
            out["final_full_price_value"] = out.get("full_price_value")
            out["final_billed_price_value"] = out.get("billed_price_value")
            out["final_cash_price_value"] = out.get("cash_price_value")
    for key in ("final_full_price_value", "final_billed_price_value", "final_cash_price_value"):
        if out.get(key) is not None:
            out[key] = _safe_float(out.get(key), 0)
    return _catalog_apply_campaign_to_product(out)


def _catalog_layout_parse_date(value: Any) -> Optional[dt.date]:
    text = _clean_str(value)
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data de validade inválida.") from exc


def _catalog_layout_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    for key in (
        "use_active_campaigns",
        "show_full_price",
        "show_billed_price",
        "show_cash_price",
        "show_sku",
        "show_tags",
        "show_stock",
        "show_without_image",
        "only_active_products",
        "active",
    ):
        out[key] = bool(out.get(key))
    for key in ("created_at", "updated_at", "valid_until"):
        value = out.get(key)
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


def _catalog_layout_item_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    out["selected"] = bool(out.get("selected"))
    if out.get("sort_order") is not None:
        out["sort_order"] = int(out.get("sort_order") or 0)
    return out


def _catalog_raw_nested(raw: Dict[str, Any], key: str) -> Any:
    if not isinstance(raw, dict):
        return None
    if raw.get(key) is not None:
        return raw.get(key)
    product = raw.get("produto")
    if isinstance(product, dict):
        return product.get(key)
    return None


def _catalog_extract_average_cost(raw: Dict[str, Any]) -> Optional[float]:
    for key in (
        "average_cost",
        "custo_medio",
        "cost",
        "preco_custo",
        "price_cost",
        "medium_cost",
        "avg_cost",
        "preco_custo_medio",
        "custo",
        "custo_unitario",
        "custoUnitario",
    ):
        value = _safe_float(_catalog_raw_nested(raw, key), None)
        if value is not None:
            return value
    return None


def _catalog_extract_stock_available(raw: Dict[str, Any]) -> Optional[float]:
    for key in (
        "stock_available",
        "estoque_disponivel",
        "available_stock",
        "qty_available",
        "saldoDisponivel",
        "saldo_disponivel",
        "estoque",
        "estoque_atual",
        "estoqueAtual",
        "saldo",
        "quantity",
    ):
        value = _safe_float(_catalog_raw_nested(raw, key), None)
        if value is not None:
            return value
    return None


def _catalog_extract_tiny_stock_available(raw: Dict[str, Any]) -> Optional[float]:
    source = raw.get("produto") if isinstance(raw, dict) and isinstance(raw.get("produto"), dict) else raw
    if not isinstance(source, dict):
        return None
    for key in ("estoque_disponivel", "saldoDisponivel", "saldo_disponivel", "disponivel"):
        value = _safe_float(source.get(key), None)
        if value is not None:
            return value
    saldo = _safe_float(source.get("saldo"), None)
    reservado = _safe_float(source.get("saldoReservado") or source.get("saldo_reservado"), None)
    if saldo is not None and reservado is not None:
        return max(0, saldo - reservado)
    # Fallback: Tiny nem sempre retorna reservado; neste caso usamos o saldo bruto.
    if saldo is not None:
        return saldo
    return None


def _catalog_price_base_value(row: Dict[str, Any], base_field: str) -> Optional[float]:
    field = _clean_str(base_field or "price_tiny")
    if field not in {"price_tiny", "average_cost", "custo_medio", "cost", "preco_custo", "price_cost"}:
        field = "price_tiny"
    value = row.get(field)
    if value is None and field != "price_tiny":
        value = row.get("price_tiny")
    value = _safe_float(value, None)
    return value if value and value > 0 else None


def _catalog_calculated_price(base_value: Optional[float], percent: Any) -> Optional[float]:
    base = _safe_float(base_value, None)
    pct = _safe_float(percent, None)
    if base is None or pct is None:
        return None
    return round(base * (1 + pct / 100), 2)


def _catalog_price_table_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    for key in ("full_price_percent", "billed_price_percent", "cash_price_percent"):
        if out.get(key) is not None:
            out[key] = _safe_float(out.get(key), 0)
    out["active"] = bool(out.get("active"))
    out["is_default"] = bool(out.get("is_default"))
    return out


def _catalog_campaign_status(row: Dict[str, Any]) -> str:
    if not bool((row or {}).get("active")):
        return "Inativa"
    today = dt.datetime.now().date()
    start = (row or {}).get("start_date")
    end = (row or {}).get("end_date")
    if isinstance(start, str):
        start = dt.datetime.fromisoformat(start[:10]).date()
    if isinstance(end, str):
        end = dt.datetime.fromisoformat(end[:10]).date()
    if start and today < start:
        return "Agendada"
    if end and today > end:
        return "Expirada"
    return "Ativa"


def _catalog_campaign_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    for key in ("discount_percent",):
        if out.get(key) is not None:
            out[key] = _safe_float(out.get(key), 0)
    out["active"] = bool(out.get("active"))
    out["status"] = _catalog_campaign_status(out)
    return out


def _catalog_campaign_price(base_value: Any, discount_percent: Any, custom_value: Any = None) -> Optional[float]:
    custom = _safe_float(custom_value, None)
    if custom is not None:
        return custom
    base = _safe_float(base_value, None)
    if base is None:
        return None
    discount = _safe_float(discount_percent, None)
    if discount is None:
        return base
    return round(base * (1 - discount / 100), 2)


def _catalog_apply_campaign_to_product(out: Dict[str, Any]) -> Dict[str, Any]:
    if not out.get("campaign_id"):
        return out
    discount = out.get("campaign_discount_percent")
    out["campaign_active"] = True
    out["campaign_full_price_value"] = _catalog_campaign_price(out.get("final_full_price_value"), discount, out.get("campaign_custom_full_price_value"))
    out["campaign_billed_price_value"] = _catalog_campaign_price(out.get("final_billed_price_value"), discount, out.get("campaign_custom_billed_price_value"))
    out["campaign_cash_price_value"] = _catalog_campaign_price(out.get("final_cash_price_value"), discount, out.get("campaign_custom_cash_price_value"))
    return out


def _catalog_source_value(raw: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _catalog_sync_source_products(company_key: str, limit: int = 1000) -> Dict[str, Any]:
    _ensure_product_catalog_tables()
    company_key = _company_key(company_key)
    created = 0
    updated = 0
    ignored = 0
    errors = 0
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (
                  q.company_key,
                  COALESCE(NULLIF(CAST(qi.product_id AS TEXT), ''), LOWER(COALESCE(qi.sku_snapshot, '')), LOWER(COALESCE(qi.name_snapshot, '')))
                )
                  q.company_key,
                  CAST(qi.product_id AS TEXT) AS tiny_product_id,
                  qi.sku_snapshot AS sku,
                  qi.name_snapshot AS name_tiny,
                  qi.list_price,
                  qi.unit_price_disc,
                  qi.raw,
                  q.updated_at
                FROM erp.quotes q
                JOIN erp.quote_items qi ON qi.quote_id = q.quote_id
                WHERE q.company_key=%s
                  AND COALESCE(qi.name_snapshot, qi.sku_snapshot, '') <> ''
                ORDER BY
                  q.company_key,
                  COALESCE(NULLIF(CAST(qi.product_id AS TEXT), ''), LOWER(COALESCE(qi.sku_snapshot, '')), LOWER(COALESCE(qi.name_snapshot, ''))),
                  q.updated_at DESC NULLS LAST
                LIMIT %s
                """,
                (company_key, int(limit)),
            )
            sources = [dict(r) for r in cur.fetchall()]

            for source in sources:
                try:
                    raw = _from_json(source.get("raw"), {}) or {}
                    tiny_product_id = _clean_str(source.get("tiny_product_id"))
                    sku = _clean_str(source.get("sku") or raw.get("codigo") or raw.get("sku"))
                    name_tiny = _clean_str(source.get("name_tiny") or raw.get("nome") or raw.get("descricao"))
                    if not tiny_product_id and not sku and not name_tiny:
                        ignored += 1
                        continue
                    price_tiny = _safe_float(source.get("list_price") or source.get("unit_price_disc") or raw.get("preco"), 0)
                    average_cost = _catalog_extract_average_cost(raw)
                    category = _catalog_source_value(raw, "categoria", "category", "grupo")
                    brand = _catalog_source_value(raw, "marca", "brand")
                    unit = _catalog_source_value(raw, "unidade", "unit")
                    situation = _catalog_source_value(raw, "situacao", "status")
                    image_url = _catalog_source_value(raw, "url_imagem", "image_url", "imagem", "foto")

                    cur.execute(
                        """
                        SELECT id
                        FROM erp.product_catalog
                        WHERE company_key=%s
                          AND (
                            (COALESCE(%s, '') <> '' AND tiny_product_id=%s)
                            OR (COALESCE(%s, '') <> '' AND sku=%s)
                          )
                        LIMIT 1
                        """,
                        (company_key, tiny_product_id, tiny_product_id, sku, sku),
                    )
                    existing = cur.fetchone()
                    if existing:
                        cur.execute(
                            """
                            UPDATE erp.product_catalog
                            SET tiny_product_id=COALESCE(NULLIF(%s, ''), tiny_product_id),
                                sku=COALESCE(NULLIF(%s, ''), sku),
                                name_tiny=%s,
                                description_tiny=%s,
                                category=%s,
                                brand=%s,
                                unit=%s,
                                price_tiny=%s,
                                average_cost=%s,
                                situation=%s,
                                image_url_tiny=%s,
                                last_source_sync_at=now(),
                                updated_at=now()
                            WHERE id=%s
                            """,
                            (
                                tiny_product_id,
                                sku,
                                name_tiny,
                                _catalog_source_value(raw, "descricao", "description", "nome"),
                                category,
                                brand,
                                unit,
                                price_tiny,
                                average_cost,
                                situation,
                                image_url,
                                existing.get("id"),
                            ),
                        )
                        updated += 1
                    else:
                        cur.execute(
                            """
                            INSERT INTO erp.product_catalog (
                              company_key, tiny_product_id, sku, name_tiny, description_tiny,
                              category, brand, unit, price_tiny, average_cost, situation,
                              image_url_tiny, last_source_sync_at, created_at, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), now())
                            """,
                            (
                                company_key,
                                tiny_product_id or None,
                                sku or None,
                                name_tiny,
                                _catalog_source_value(raw, "descricao", "description", "nome"),
                                category,
                                brand,
                                unit,
                                price_tiny,
                                average_cost,
                                situation,
                                image_url,
                            ),
                        )
                        created += 1
                except Exception as e:
                    errors += 1
                    print(f"[catalog] falha ao sincronizar produto local company={company_key}: {e}")
    return {"ok": errors == 0, "company_key": company_key, "created": created, "updated": updated, "ignored": ignored, "errors": errors}


def _admin_user_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    user = dict(row or {})
    public = _auth_public_user_row(user)
    public.update(
        {
            "login": user.get("login"),
            "email": user.get("login"),
            "display_name": user.get("display_name"),
            "role": _clean_str(user.get("role")).lower(),
            "active": bool(user.get("active")),
            "must_change_password": bool(user.get("must_change_password")),
            "created_at": _iso_value(user.get("created_at")),
            "updated_at": _iso_value(user.get("updated_at")),
            "companies": _auth_user_companies(user.get("id")),
        }
    )
    return public


def _admin_require_user(request: Request) -> Dict[str, Any]:
    user = _require_auth_user(request)
    if _clean_str(user.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")
    return user


def _parse_tiny_ordered_at(value: Any) -> Optional[dt.datetime]:
    text = _clean_str(value)
    if not text:
        return None
    try:
        parsed = dt.datetime.strptime(text, "%d/%m/%Y")
        return parsed.replace(tzinfo=CLIENT_WALLET_DAILY_SYNC_TZ)
    except Exception:
        return None


def _ordered_at_backfill_candidate_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "quote_id": row.get("quote_id"),
        "company_key": row.get("company_key"),
        "quote_number": row.get("quote_number"),
        "tiny_order_id": row.get("tiny_order_id"),
        "tiny_order_number": row.get("tiny_order_number"),
        "created_at": _iso_value(row.get("created_at")),
        "updated_at": _iso_value(row.get("updated_at")),
        "internal_status": row.get("internal_status"),
    }


@app.post("/api/admin/backfill-ordered-at")
@app.post("/admin/backfill-ordered-at")
def admin_backfill_ordered_at(
    request: Request,
    company: str = "parton",
    date_from: str = "2026-05-01",
    limit: int = Query(default=20, ge=1, le=50),
    dry_run: bool = False,
):
    user = _admin_require_user(request)
    company_key = _auth_company_or_default(user, company)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")

    try:
        date_from_value = dt.date.fromisoformat(_clean_str(date_from) or "2026-05-01")
    except Exception:
        raise HTTPException(status_code=400, detail="date_from inválido. Use YYYY-MM-DD.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT quote_id, company_key, quote_number, tiny_order_id, tiny_order_number,
                       created_at, updated_at, internal_status
                FROM erp.quotes
                WHERE company_key=%s
                  AND tiny_order_id IS NOT NULL
                  AND ordered_at IS NULL
                  AND created_at >= %s::date
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (company_key, date_from_value.isoformat(), int(limit)),
            )
            rows = [dict(r) for r in cur.fetchall()]

    candidates = [_ordered_at_backfill_candidate_payload(row) for row in rows]
    updated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    if dry_run:
        return {
            "ok": True,
            "company_key": company_key,
            "date_from": date_from_value.isoformat(),
            "limit": int(limit),
            "dry_run": True,
            "selected": len(rows),
            "updated_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "candidates": candidates,
            "updated": [],
            "skipped": [],
            "failed": [],
        }

    tiny = _tiny_for_company(company_key)

    for row in rows:
        base = _ordered_at_backfill_candidate_payload(row)
        tiny_called = False
        try:
            tiny_order_id = _safe_int(row.get("tiny_order_id"))
            if not tiny_order_id:
                skipped.append({**base, "reason": "tiny_order_id inválido"})
                continue

            tiny_called = True
            raw = tiny.obter_pedido(int(tiny_order_id))
            pedido = (raw.get("pedido") or raw) if isinstance(raw, dict) else {}
            data_pedido = _clean_str((pedido or {}).get("data_pedido"))
            ordered_at = _parse_tiny_ordered_at(data_pedido)
            if not ordered_at:
                skipped.append({**base, "data_pedido": data_pedido, "reason": "data_pedido ausente ou inválida"})
                continue

            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE erp.quotes
                        SET ordered_at = %s
                        WHERE quote_id = %s
                          AND company_key = %s
                          AND ordered_at IS NULL
                        """,
                        (ordered_at, row.get("quote_id"), company_key),
                    )
                    changed = int(cur.rowcount or 0)

            if changed:
                updated.append(
                    {
                        **base,
                        "data_pedido": data_pedido,
                        "ordered_at": _iso_value(ordered_at),
                    }
                )
            else:
                skipped.append(
                    {
                        **base,
                        "data_pedido": data_pedido,
                        "ordered_at": _iso_value(ordered_at),
                        "reason": "ordered_at já preenchido",
                    }
                )
        except Exception as e:
            failed.append({**base, "error": str(e)})
        finally:
            if tiny_called:
                time.sleep(0.5)

    return {
        "ok": True,
        "company_key": company_key,
        "date_from": date_from_value.isoformat(),
        "limit": int(limit),
        "dry_run": False,
        "selected": len(rows),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "candidates": candidates,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
    }


def _ensure_user_seller_links_table():
    _ensure_auth_schema()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.user_seller_links (
                  id BIGSERIAL PRIMARY KEY,
                  user_id UUID NOT NULL REFERENCES erp.users(id) ON DELETE CASCADE,
                  company_key TEXT NOT NULL,
                  tiny_seller_id TEXT NOT NULL,
                  tiny_seller_name TEXT NOT NULL,
                  active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now(),
                  created_by TEXT,
                  updated_by TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS user_seller_links_active_uidx
                ON erp.user_seller_links (user_id, company_key)
                WHERE active = TRUE
                """
            )


def _admin_user_seller_link_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row or {})
    return {
        "id": item.get("id"),
        "user_id": str(item.get("user_id")) if item.get("user_id") is not None else None,
        "company_key": item.get("company_key"),
        "tiny_seller_id": item.get("tiny_seller_id"),
        "tiny_seller_name": item.get("tiny_seller_name"),
        "active": bool(item.get("active")),
        "created_at": _iso_value(item.get("created_at")),
        "updated_at": _iso_value(item.get("updated_at")),
        "created_by": item.get("created_by"),
        "updated_by": item.get("updated_by"),
    }


def _admin_user_seller_links_find_user(user_id: str) -> Dict[str, Any]:
    user_id = _clean_str(user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="Usuário obrigatório.")
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.users WHERE id=%s LIMIT 1", (user_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return dict(row)


def _admin_user_seller_links_company(user: Dict[str, Any], company_key: str) -> str:
    company_key = _company_key(company_key)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")
    if company_key not in _auth_user_companies(user.get("id")):
        raise HTTPException(status_code=400, detail="Usuário não possui esta empresa.")
    return company_key


def _admin_merge_local_seller(target: Dict[str, Any], row: Dict[str, Any]):
    seller_id = _clean_str(row.get("seller_id"))
    if not seller_id:
        return

    seller_name = _clean_str(row.get("seller_name"))
    last_seen_at = row.get("last_seen_at")
    source = _clean_str(row.get("source"))
    item = target.setdefault(
        seller_id,
        {
            "seller_id": seller_id,
            "seller_name": "",
            "source": [],
            "last_seen_at": None,
        },
    )

    if source and source not in item["source"]:
        item["source"].append(source)

    current_last_seen = item.get("last_seen_at")
    is_newer = bool(last_seen_at and (not current_last_seen or last_seen_at > current_last_seen))
    if last_seen_at and (not current_last_seen or is_newer):
        item["last_seen_at"] = last_seen_at
    if seller_name and (not item.get("seller_name") or is_newer):
        item["seller_name"] = seller_name


def _admin_local_seller_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    seller_id = _clean_str(item.get("seller_id"))
    seller_name = _clean_str(item.get("seller_name")) or f"Vendedor {seller_id}"
    return {
        "seller_id": seller_id,
        "seller_name": seller_name,
        "source": ",".join(item.get("source") or []),
        "last_seen_at": _iso_value(item.get("last_seen_at")),
    }


@app.get("/api/admin/sellers")
@app.get("/admin/sellers")
def admin_list_sellers(request: Request, company: str = ""):
    user = _admin_require_user(request)
    company_key = _auth_company_or_default(user, company)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")

    sellers: Dict[str, Dict[str, Any]] = {}
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (CAST(seller_id AS TEXT))
                       CAST(seller_id AS TEXT) AS seller_id,
                       seller_name,
                       updated_at AS last_seen_at,
                       'quotes' AS source
                FROM erp.quotes
                WHERE company_key=%s
                  AND COALESCE(CAST(seller_id AS TEXT), '') <> ''
                ORDER BY CAST(seller_id AS TEXT),
                         (COALESCE(seller_name, '') <> '') DESC,
                         updated_at DESC NULLS LAST
                """,
                (company_key,),
            )
            for row in cur.fetchall():
                _admin_merge_local_seller(sellers, dict(row))

            cur.execute(
                """
                SELECT DISTINCT ON (vendedor_id)
                       vendedor_id AS seller_id,
                       vendedor_nome AS seller_name,
                       last_seen_at,
                       'client_wallet' AS source
                FROM erp.client_wallet
                WHERE company_key=%s
                  AND COALESCE(vendedor_id, '') <> ''
                ORDER BY vendedor_id,
                         (COALESCE(vendedor_nome, '') <> '') DESC,
                         last_seen_at DESC NULLS LAST
                """,
                (company_key,),
            )
            for row in cur.fetchall():
                _admin_merge_local_seller(sellers, dict(row))

    payload = [_admin_local_seller_payload(item) for item in sellers.values()]
    payload.sort(key=lambda item: ((_clean_str(item.get("seller_name")) or _clean_str(item.get("seller_id"))).lower(), _clean_str(item.get("seller_id"))))
    return {"ok": True, "company_key": company_key, "sellers": payload}


@app.get("/api/admin/company-sellers")
@app.get("/admin/company-sellers")
def admin_company_sellers(request: Request, company: str = ""):
    """Vendedores configurados para a empresa via erp.user_seller_links — fonte confiável e company-scoped."""
    user = _admin_require_user(request)
    company_key = _auth_company_or_default(user, company)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")
    _ensure_user_seller_links_table()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (tiny_seller_id)
                       tiny_seller_id AS seller_id,
                       tiny_seller_name AS seller_name
                FROM erp.user_seller_links
                WHERE company_key = %s
                  AND active = TRUE
                  AND COALESCE(tiny_seller_id, '') <> ''
                  AND COALESCE(tiny_seller_name, '') <> ''
                ORDER BY tiny_seller_id, tiny_seller_name
                """,
                (company_key,),
            )
            rows = [
                {"seller_id": _clean_str(r["seller_id"]), "seller_name": _clean_str(r["seller_name"])}
                for r in cur.fetchall()
            ]
    rows.sort(key=lambda r: _clean_str(r.get("seller_name")).lower())
    return {"ok": True, "company_key": company_key, "sellers": rows}


@app.get("/api/admin/users/{user_id}/seller-links")
@app.get("/admin/users/{user_id}/seller-links")
def admin_list_user_seller_links(user_id: str, request: Request):
    _admin_require_user(request)
    _ensure_user_seller_links_table()
    _admin_user_seller_links_find_user(user_id)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM erp.user_seller_links
                WHERE user_id=%s
                ORDER BY company_key, active DESC, updated_at DESC, id DESC
                """,
                (_clean_str(user_id),),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"ok": True, "items": [_admin_user_seller_link_payload(row) for row in rows]}


@app.put("/api/admin/users/{user_id}/seller-links/{company_key}")
@app.put("/admin/users/{user_id}/seller-links/{company_key}")
async def admin_save_user_seller_link(user_id: str, company_key: str, request: Request):
    actor = _admin_require_user(request)
    _ensure_user_seller_links_table()
    target_user = _admin_user_seller_links_find_user(user_id)
    company_key = _admin_user_seller_links_company(target_user, company_key)
    body = await request.json()
    tiny_seller_id = _clean_str(body.get("tiny_seller_id"))
    tiny_seller_name = _clean_str(body.get("tiny_seller_name"))
    if not tiny_seller_id or not tiny_seller_name:
        raise HTTPException(status_code=400, detail="Vendedor Tiny obrigatório.")

    actor_login = _clean_str(actor.get("login"))
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.user_seller_links
                SET active=FALSE,
                    updated_at=now(),
                    updated_by=%s
                WHERE user_id=%s
                  AND company_key=%s
                  AND active=TRUE
                """,
                (actor_login, _clean_str(user_id), company_key),
            )
            cur.execute(
                """
                INSERT INTO erp.user_seller_links (
                  user_id, company_key, tiny_seller_id, tiny_seller_name,
                  active, created_at, updated_at, created_by, updated_by
                )
                VALUES (%s, %s, %s, %s, TRUE, now(), now(), %s, %s)
                RETURNING *
                """,
                (_clean_str(user_id), company_key, tiny_seller_id, tiny_seller_name, actor_login, actor_login),
            )
            row = dict(cur.fetchone())
    return {"ok": True, "item": _admin_user_seller_link_payload(row)}


@app.delete("/api/admin/users/{user_id}/seller-links/{company_key}")
@app.delete("/admin/users/{user_id}/seller-links/{company_key}")
def admin_delete_user_seller_link(user_id: str, company_key: str, request: Request):
    actor = _admin_require_user(request)
    _ensure_user_seller_links_table()
    target_user = _admin_user_seller_links_find_user(user_id)
    company_key = _admin_user_seller_links_company(target_user, company_key)
    actor_login = _clean_str(actor.get("login"))
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.user_seller_links
                SET active=FALSE,
                    updated_at=now(),
                    updated_by=%s
                WHERE user_id=%s
                  AND company_key=%s
                  AND active=TRUE
                RETURNING *
                """,
                (actor_login, _clean_str(user_id), company_key),
            )
            row = cur.fetchone()
    return {
        "ok": True,
        "item": _admin_user_seller_link_payload(dict(row)) if row else None,
    }


def _ensure_seller_metas_table():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.seller_metas (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  seller_id TEXT NOT NULL,
                  seller_name TEXT,
                  year_month TEXT NOT NULL,
                  meta_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now(),
                  created_by TEXT,
                  updated_by TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS seller_metas_company_seller_month_uidx
                ON erp.seller_metas (company_key, seller_id, year_month)
                """
            )


def _seller_metas_validate_year_month(year_month: str) -> str:
    """Valida YYYY-MM (equivalente ao regex ^\\d{4}-(0[1-9]|1[0-2])$) sem depender de `re`."""
    ym = _clean_str(year_month)
    ok = False
    if len(ym) == 7 and ym[4] == "-":
        year_part, month_part = ym[:4], ym[5:]
        if year_part.isdigit() and month_part.isdigit() and 1 <= int(month_part) <= 12:
            ok = True
    if not ok:
        raise HTTPException(status_code=400, detail="year_month inválido. Use YYYY-MM.")
    return ym


def _seller_metas_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row or {})
    meta_amount = item.get("meta_amount")
    return {
        "id": item.get("id"),
        "company_key": item.get("company_key"),
        "seller_id": _clean_str(item.get("seller_id")) or None,
        "seller_name": item.get("seller_name"),
        "year_month": item.get("year_month"),
        "meta_amount": round(_safe_float(meta_amount, 0.0), 2) if meta_amount is not None else None,
        "created_at": _iso_value(item.get("created_at")),
        "updated_at": _iso_value(item.get("updated_at")),
        "created_by": item.get("created_by"),
        "updated_by": item.get("updated_by"),
    }


@app.get("/api/admin/seller-metas")
@app.get("/admin/seller-metas")
def admin_list_seller_metas(request: Request, company: str = "", year_month: str = ""):
    user = _admin_require_user(request)
    company_key = _auth_company_or_default(user, company)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")
    ym = _seller_metas_validate_year_month(year_month)
    _ensure_seller_metas_table()
    _ensure_user_seller_links_table()

    with _db() as conn:
        with conn.cursor() as cur:
            # Vendedores ativos da empresa (mesma query de admin_company_sellers).
            cur.execute(
                """
                SELECT DISTINCT ON (tiny_seller_id)
                       tiny_seller_id AS seller_id,
                       tiny_seller_name AS seller_name
                FROM erp.user_seller_links
                WHERE company_key = %s
                  AND active = TRUE
                  AND COALESCE(tiny_seller_id, '') <> ''
                  AND COALESCE(tiny_seller_name, '') <> ''
                ORDER BY tiny_seller_id, tiny_seller_name
                """,
                (company_key,),
            )
            linked = [
                {"seller_id": _clean_str(r["seller_id"]), "seller_name": _clean_str(r["seller_name"])}
                for r in cur.fetchall()
            ]
            cur.execute(
                """
                SELECT seller_id, seller_name, meta_amount, updated_at, updated_by
                FROM erp.seller_metas
                WHERE company_key = %s AND year_month = %s
                """,
                (company_key, ym),
            )
            metas: Dict[str, Dict[str, Any]] = {}
            for r in cur.fetchall():
                metas[_clean_str(r.get("seller_id"))] = dict(r)

    items: List[Dict[str, Any]] = []
    linked_ids = set()
    for seller in linked:
        sid = seller["seller_id"]
        linked_ids.add(sid)
        meta = metas.get(sid)
        items.append({
            "seller_id": sid,
            "seller_name": seller["seller_name"] or (_clean_str(meta.get("seller_name")) if meta else "") or f"Vendedor {sid}",
            "meta_amount": round(_safe_float(meta.get("meta_amount"), 0.0), 2) if meta else None,
            "has_meta": bool(meta),
            "updated_at": _iso_value(meta.get("updated_at")) if meta else None,
            "updated_by": meta.get("updated_by") if meta else None,
            "linked": True,
        })
    # Metas órfãs: vendedor não mais linkado, mas com meta gravada no mês.
    for sid, meta in metas.items():
        if sid in linked_ids or not sid:
            continue
        items.append({
            "seller_id": sid,
            "seller_name": _clean_str(meta.get("seller_name")) or f"Vendedor {sid}",
            "meta_amount": round(_safe_float(meta.get("meta_amount"), 0.0), 2),
            "has_meta": True,
            "updated_at": _iso_value(meta.get("updated_at")),
            "updated_by": meta.get("updated_by"),
            "linked": False,
        })
    items.sort(key=lambda it: _clean_str(it.get("seller_name")).lower())
    return {"ok": True, "company_key": company_key, "year_month": ym, "items": items}


@app.put("/api/admin/seller-metas/{company_key}/{year_month}/{seller_id}")
@app.put("/admin/seller-metas/{company_key}/{year_month}/{seller_id}")
async def admin_save_seller_meta(company_key: str, year_month: str, seller_id: str, request: Request):
    actor = _admin_require_user(request)
    company_key = _auth_company_or_default(actor, company_key)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")
    ym = _seller_metas_validate_year_month(year_month)
    seller_key = _clean_str(seller_id)
    if not seller_key:
        raise HTTPException(status_code=400, detail="Vendedor obrigatório.")
    _ensure_seller_metas_table()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corpo JSON inválido.")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Corpo JSON inválido.")
    meta_amount = _safe_float(body.get("meta_amount"), None)
    if meta_amount is None or meta_amount < 0:
        raise HTTPException(status_code=400, detail="meta_amount inválido. Informe um valor numérico maior ou igual a zero.")
    # Rejeita não-finitos (nan/inf) e valores acima do teto de NUMERIC(14,2).
    # (math não está importado; NaN != NaN e inf comparado explicitamente.)
    if meta_amount != meta_amount or meta_amount == float("inf") or meta_amount == float("-inf") or meta_amount > 999999999999.99:
        raise HTTPException(status_code=400, detail="meta_amount inválido. Informe um valor numérico dentro do limite permitido.")
    meta_amount = round(meta_amount, 2)
    seller_name = _clean_str(body.get("seller_name"))

    actor_login = _clean_str(actor.get("login"))
    with _db() as conn:
        with conn.cursor() as cur:
            # Captura o estado anterior na MESMA transação para auditar o before real em updates.
            cur.execute(
                """
                SELECT * FROM erp.seller_metas
                WHERE company_key = %s AND seller_id = %s AND year_month = %s
                """,
                (company_key, seller_key, ym),
            )
            existing = cur.fetchone()
            before_item = _seller_metas_payload(dict(existing)) if existing else None
            cur.execute(
                """
                INSERT INTO erp.seller_metas (
                  company_key, seller_id, seller_name, year_month,
                  meta_amount, created_at, updated_at, created_by, updated_by
                )
                VALUES (%s, %s, NULLIF(%s, ''), %s, %s, now(), now(), %s, %s)
                ON CONFLICT (company_key, seller_id, year_month) DO UPDATE
                SET meta_amount = EXCLUDED.meta_amount,
                    seller_name = COALESCE(NULLIF(EXCLUDED.seller_name, ''), erp.seller_metas.seller_name),
                    updated_at = now(),
                    updated_by = EXCLUDED.updated_by
                RETURNING *
                """,
                (company_key, seller_key, seller_name, ym, meta_amount, actor_login, actor_login),
            )
            row = dict(cur.fetchone())

    item = _seller_metas_payload(row)
    _auth_audit_log(actor_login, seller_key, "seller_meta_upsert", before_item, item)
    return {"ok": True, "item": item}


@app.delete("/api/admin/seller-metas/{company_key}/{year_month}/{seller_id}")
@app.delete("/admin/seller-metas/{company_key}/{year_month}/{seller_id}")
def admin_delete_seller_meta(company_key: str, year_month: str, seller_id: str, request: Request):
    actor = _admin_require_user(request)
    company_key = _auth_company_or_default(actor, company_key)
    if company_key not in {"parton", "park"}:
        raise HTTPException(status_code=400, detail="Empresa inválida.")
    ym = _seller_metas_validate_year_month(year_month)
    seller_key = _clean_str(seller_id)
    if not seller_key:
        raise HTTPException(status_code=400, detail="Vendedor obrigatório.")
    _ensure_seller_metas_table()

    actor_login = _clean_str(actor.get("login"))
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM erp.seller_metas
                WHERE company_key = %s AND year_month = %s AND seller_id = %s
                RETURNING *
                """,
                (company_key, ym, seller_key),
            )
            row = cur.fetchone()

    item = _seller_metas_payload(dict(row)) if row else None
    if item is not None:
        _auth_audit_log(actor_login, seller_key, "seller_meta_delete", item, None)
    return {"ok": True, "item": item}


@app.get("/api/admin/users")
@app.get("/admin/users")
def admin_list_users(request: Request):
    user = _require_auth_user(request)
    if _clean_str(user.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.users ORDER BY login")
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) AS total, role FROM erp.users GROUP BY role ORDER BY role")
            role_counts = [dict(r) for r in cur.fetchall()]

    items = [_admin_user_payload(row) for row in rows]
    env_counts = {str(item.get("role")): int(next((r.get("total") for r in role_counts if r.get("role") == item.get("role")), 0)) for item in items}
    return {"ok": True, "items": items, "env_counts": env_counts}


@app.get("/api/admin/catalog/products")
@app.get("/admin/catalog/products")
def admin_catalog_products(
    request: Request,
    company: str = "parton",
    search: str = "",
    status: str = "",
    image: str = "",
    featured: Optional[bool] = None,
    category: str = "",
    situation: str = "",
    simulate_price_table_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    _catalog_require_admin(request)
    company_key = _company_key(company)
    _ensure_product_catalog_tables()
    where = ["company_key=%s"]
    params: List[Any] = [company_key]
    if _clean_str(search):
        like = f"%{_clean_str(search).lower()}%"
        where.append("(LOWER(COALESCE(sku, '')) LIKE %s OR LOWER(COALESCE(name_tiny, '')) LIKE %s OR LOWER(COALESCE(catalog_title, '')) LIKE %s OR LOWER(COALESCE(catalog_description, '')) LIKE %s)")
        params.extend([like, like, like, like])
    status_norm = _clean_str(status).lower()
    if status_norm == "active":
        where.append("catalog_active = TRUE")
    elif status_norm == "inactive":
        where.append("COALESCE(catalog_active, FALSE) = FALSE")
    image_norm = _clean_str(image).lower()
    if image_norm == "with":
        where.append("(COALESCE(catalog_image_path, catalog_image_url, image_url_tiny, '') <> '')")
    elif image_norm == "without":
        where.append("(COALESCE(catalog_image_path, catalog_image_url, image_url_tiny, '') = '')")
    if featured is not None:
        where.append("catalog_featured = %s")
        params.append(bool(featured))
    if _clean_str(category):
        where.append("category = %s")
        params.append(_clean_str(category))
    if _clean_str(situation):
        where.append("situation = %s")
        params.append(_clean_str(situation))
    where_sql = " AND ".join(where)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM erp.product_catalog WHERE {where_sql}", params)
            total = int((cur.fetchone() or {}).get("total") or 0)
            cur.execute(
                f"""
                SELECT
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE catalog_active) AS active,
                  COUNT(*) FILTER (WHERE catalog_featured) AS featured,
                  COUNT(*) FILTER (WHERE COALESCE(catalog_image_path, catalog_image_url, image_url_tiny, '') = '') AS without_image
                FROM erp.product_catalog
                WHERE company_key=%s
                """,
                (company_key,),
            )
            summary = dict(cur.fetchone() or {})
            cur.execute(
                f"""
                SELECT
                  pc.*,
                  cpt.name AS price_table_name,
                  cpt.mode AS price_table_mode,
                  cpt.base_field AS table_base_field,
                  cpt.active AS price_table_active,
                  cpt.full_price_percent AS table_full_price_percent,
                  cpt.billed_price_percent AS table_billed_price_percent,
                  cpt.cash_price_percent AS table_cash_price_percent,
                  latest.raw AS latest_product_raw,
                  simpt.id AS simulated_price_table_id,
                  simpt.name AS simulated_price_table_name,
                  simpt.mode AS simulated_price_table_mode,
                  simpt.base_field AS simulated_base_field,
                  simpt.active AS simulated_price_table_active,
                  simpt.full_price_percent AS simulated_full_price_percent,
                  simpt.billed_price_percent AS simulated_billed_price_percent,
                  simpt.cash_price_percent AS simulated_cash_price_percent,
                  campaign.id AS campaign_id,
                  campaign.name AS campaign_name,
                  campaign.discount_percent AS campaign_discount_percent,
                  campaign.custom_full_price_value AS campaign_custom_full_price_value,
                  campaign.custom_billed_price_value AS campaign_custom_billed_price_value,
                  campaign.custom_cash_price_value AS campaign_custom_cash_price_value
                FROM erp.product_catalog pc
                LEFT JOIN erp.catalog_price_tables cpt
                  ON cpt.id = pc.price_table_id
                 AND cpt.company_key = pc.company_key
                LEFT JOIN LATERAL (
                  SELECT qi.raw
                  FROM erp.quote_items qi
                  JOIN erp.quotes q ON q.quote_id = qi.quote_id
                  WHERE q.company_key = pc.company_key
                    AND (
                      (pc.tiny_product_id IS NOT NULL AND CAST(qi.product_id AS TEXT) = pc.tiny_product_id)
                      OR (pc.sku IS NOT NULL AND LOWER(COALESCE(qi.sku_snapshot, qi.raw->>'sku', qi.raw->>'codigo', '')) = LOWER(pc.sku))
                    )
                  ORDER BY q.updated_at DESC NULLS LAST
                  LIMIT 1
                ) latest ON TRUE
                LEFT JOIN erp.catalog_price_tables simpt
                  ON simpt.id = %s
                 AND simpt.company_key = pc.company_key
                 AND simpt.active = TRUE
                LEFT JOIN LATERAL (
                  SELECT
                    cc.id,
                    cc.name,
                    cc.discount_percent,
                    cci.custom_full_price_value,
                    cci.custom_billed_price_value,
                    cci.custom_cash_price_value
                  FROM erp.catalog_campaign_items cci
                  JOIN erp.catalog_campaigns cc ON cc.id = cci.campaign_id
                  WHERE cci.product_catalog_id = pc.id
                    AND cc.company_key = pc.company_key
                    AND cc.active = TRUE
                    AND CURRENT_DATE BETWEEN cc.start_date AND cc.end_date
                  ORDER BY cc.start_date DESC, cc.id DESC
                  LIMIT 1
                ) campaign ON TRUE
                WHERE {where_sql.replace('company_key', 'pc.company_key').replace('catalog_active', 'pc.catalog_active').replace('catalog_featured', 'pc.catalog_featured').replace('category', 'pc.category').replace('situation', 'pc.situation').replace('sku', 'pc.sku').replace('name_tiny', 'pc.name_tiny').replace('catalog_title', 'pc.catalog_title').replace('catalog_description', 'pc.catalog_description').replace('catalog_image_path', 'pc.catalog_image_path').replace('catalog_image_url', 'pc.catalog_image_url').replace('image_url_tiny', 'pc.image_url_tiny')}
                ORDER BY COALESCE(pc.catalog_order, 999999), LOWER(COALESCE(pc.catalog_title, pc.name_tiny, pc.sku, '')), pc.id
                LIMIT %s OFFSET %s
                """,
                [_safe_int(simulate_price_table_id, None), *params, int(limit), int(offset)],
            )
            items = [_catalog_row_public(dict(r)) for r in cur.fetchall()]
            cur.execute(
                "SELECT DISTINCT category FROM erp.product_catalog WHERE company_key=%s AND COALESCE(category, '') <> '' ORDER BY category",
                (company_key,),
            )
            categories = [_clean_str((r or {}).get("category")) for r in cur.fetchall()]
            cur.execute(
                "SELECT DISTINCT situation FROM erp.product_catalog WHERE company_key=%s AND COALESCE(situation, '') <> '' ORDER BY situation",
                (company_key,),
            )
            situations = [_clean_str((r or {}).get("situation")) for r in cur.fetchall()]
    return {
        "ok": True,
        "company_key": company_key,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": {
            "total": int(summary.get("total") or 0),
            "active": int(summary.get("active") or 0),
            "featured": int(summary.get("featured") or 0),
            "without_image": int(summary.get("without_image") or 0),
        },
        "filters": {"categories": categories, "situations": situations},
    }


@app.post("/api/admin/catalog/products/sync-local")
@app.post("/admin/catalog/products/sync-local")
def admin_catalog_sync_local(request: Request, company: str = "parton", limit: int = Query(default=1000, ge=1, le=5000)):
    _catalog_require_admin(request)
    return _catalog_sync_source_products(_company_key(company), limit=limit)


def _tiny_v3_product_public(raw: Dict[str, Any]) -> Dict[str, Any]:
    p = raw.get("produto") if isinstance(raw.get("produto"), dict) else raw
    precos = p.get("precos") if isinstance(p.get("precos"), dict) else {}
    estoque = p.get("estoque") if isinstance(p.get("estoque"), dict) else {}
    sku = _clean_str(p.get("sku") or p.get("codigo"))
    return {
        "id": p.get("id"),
        "tiny_product_id": _clean_str(p.get("id")),
        "sku": sku,
        "codigo": sku,
        "nome": _clean_str(p.get("nome") or p.get("descricao")),
        "descricao": _clean_str(p.get("descricao") or p.get("nome")),
        "unidade": _clean_str(p.get("unidade")),
        "gtin": _clean_str(p.get("gtin")),
        "situacao": _clean_str(p.get("situacao")),
        "data_criacao": _clean_str(p.get("dataCriacao")),
        "data_alteracao": _clean_str(p.get("dataAlteracao")),
        "preco": _safe_float(precos.get("preco"), None),
        "preco_promocional": _safe_float(precos.get("precoPromocional"), None),
        "preco_custo": _safe_float(precos.get("precoCusto"), None),
        "preco_custo_medio": _safe_float(precos.get("precoCustoMedio"), None),
        "estoque_localizacao": _clean_str(estoque.get("localizacao")),
        "raw": p,
    }


@app.get("/api/admin/tiny-v3/products")
@app.get("/admin/tiny-v3/products")
def admin_tiny_v3_products(
    request: Request,
    company: str = "parton",
    q: str = Query(default=""),
    field: str = Query(default="nome"),
    situation: str = Query(default="A"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    field_key = _clean_str(field).lower()
    if field_key == "sku":
        field_key = "codigo"
    if field_key not in {"nome", "codigo", "gtin"}:
        raise HTTPException(status_code=400, detail="Campo de busca inválido. Use nome, codigo, sku ou gtin.")

    params: Dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
    q_norm = _clean_str(q)
    if q_norm:
        params[field_key] = q_norm
    situation_norm = _clean_str(situation).upper()
    if situation_norm:
        if situation_norm not in {"A", "I", "E"}:
            raise HTTPException(status_code=400, detail="Situação inválida. Use A, I ou E.")
        params["situacao"] = situation_norm

    try:
        response = _tiny_v3_for_company(company_key).listar_produtos(params)
    except TinyAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payload = response.get("data") if isinstance(response.get("data"), dict) else response
    raw_items = payload.get("itens") or payload.get("produtos") or []
    items = [_tiny_v3_product_public(item) for item in raw_items if isinstance(item, dict)]
    return {
        "ok": True,
        "company_key": company_key,
        "items": items,
        "paginacao": payload.get("paginacao") or {"limit": int(limit), "offset": int(offset), "total": len(items)},
        "query": {"q": q_norm, "field": field_key, "situation": situation_norm, "limit": int(limit), "offset": int(offset)},
    }


@app.get("/api/admin/products/schema")
@app.get("/admin/products/schema")
def admin_products_schema(request: Request):
    _catalog_require_admin(request)
    _ensure_products_local_first_table()
    columns = sorted(_table_columns("erp", "products"))
    expected = list(_PRODUCTS_LOCAL_FIRST_COLUMNS)
    return {
        "ok": True,
        "table": "erp.products",
        "strategy": "local-first",
        "expected_columns": expected,
        "columns": columns,
        "missing_columns": [col for col in expected if col not in columns],
        "notes": [
            "Tabela separada de erp.product_catalog para não impactar catálogo, campanhas, layouts e custos usados em fluxos atuais.",
            "Nenhum produto é criado, editado ou excluído no Tiny V3 nesta fase.",
        ],
    }


def _park_wrong_tiny_products_counts(cur) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT company_key, COALESCE(origin, '') AS origin, COUNT(*) AS total
        FROM erp.products
        GROUP BY company_key, COALESCE(origin, '')
        ORDER BY company_key, COALESCE(origin, '')
        """
    )
    by_company_origin = [dict(row) for row in cur.fetchall()]
    cur.execute(
        """
        SELECT
          COUNT(*) AS park_total,
          COUNT(*) FILTER (WHERE origin = 'tiny') AS park_tiny,
          COUNT(*) FILTER (WHERE origin = 'local') AS park_local
        FROM erp.products
        WHERE company_key = 'park'
        """
    )
    park = dict(cur.fetchone() or {})
    return {"by_company_origin": by_company_origin, "park": park}


def _park_wrong_tiny_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


@app.post("/api/admin/products/cleanup-park-wrong-tiny")
@app.post("/admin/products/cleanup-park-wrong-tiny")
async def admin_products_cleanup_park_wrong_tiny(
    request: Request,
    company: str = "park",
    dry_run: bool = True,
    confirm: bool = False,
    export_backup: bool = True,
):
    _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        company = _clean_str(body.get("company")) or company
        if body.get("dry_run") is not None:
            dry_run = _park_wrong_tiny_bool(body.get("dry_run"), dry_run)
        if body.get("confirm") is not None:
            confirm = _park_wrong_tiny_bool(body.get("confirm"), confirm)
        if body.get("export_backup") is not None:
            export_backup = _park_wrong_tiny_bool(body.get("export_backup"), export_backup)

    company_key = _company_key(company)
    if company_key != "park":
        raise HTTPException(status_code=400, detail="Esta microfase aceita apenas company='park'.")

    _ensure_products_local_first_table()
    backup_dir = None
    backup_file = None
    sample: List[Dict[str, Any]] = []
    deleted_count = 0
    counts_after = None

    with _db() as conn:
        with conn.cursor() as cur:
            counts_before = _park_wrong_tiny_products_counts(cur)
            cur.execute(
                """
                SELECT id, company_key, origin, tiny_product_id, sku, nome, tiny_sync_status, updated_at
                FROM erp.products
                WHERE company_key = 'park' AND origin = 'tiny'
                ORDER BY id
                LIMIT 20
                """
            )
            sample = [dict(row) for row in cur.fetchall()]

            if export_backup:
                backup_dir = os.path.join(
                    APP_ROOT,
                    "backups",
                    f"before-clean-park-products-wrong-tiny-account-endpoint-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}",
                )
                os.makedirs(backup_dir, exist_ok=True)
                backup_file = os.path.join(backup_dir, "park_products_before_cleanup.json")
                cur.execute("SELECT * FROM erp.products WHERE company_key = 'park' ORDER BY id")
                rows = [dict(row) for row in cur.fetchall()]
                with open(backup_file, "w", encoding="utf-8") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2, default=_json_default)

            would_delete = int((counts_before.get("park") or {}).get("park_tiny") or 0)
            if dry_run or not confirm:
                return {
                    "ok": True,
                    "company_key": company_key,
                    "dry_run": True,
                    "confirm": bool(confirm),
                    "backup_dir": backup_dir,
                    "backup_file": backup_file,
                    "counts_before": counts_before,
                    "would_delete_count": would_delete,
                    "deleted_count": 0,
                    "sample_to_delete": sample,
                    "message": "Dry-run: nenhum produto foi apagado.",
                }

            cur.execute("DELETE FROM erp.products WHERE company_key = %s AND origin = %s", ("park", "tiny"))
            deleted_count = int(cur.rowcount or 0)
            counts_after = _park_wrong_tiny_products_counts(cur)

    return {
        "ok": True,
        "company_key": company_key,
        "dry_run": False,
        "confirm": True,
        "backup_dir": backup_dir,
        "backup_file": backup_file,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "would_delete_count": deleted_count,
        "deleted_count": deleted_count,
        "sample_deleted": sample,
        "message": "Limpeza concluida: removidos apenas produtos Park com origin='tiny'.",
    }


def _product_jsonb_dict(value: Any) -> Dict[str, Any]:
    """JSONB do erp.products pode chegar como dict (psycopg2) ou string. Normaliza."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _product_list_stock_cost(row: Dict[str, Any]) -> Dict[str, Any]:
    """Deriva estoque físico/reservado/disponível e custo médio SOMENTE a partir do
    que já está persistido em erp.products (estoque_payload/custos_payload/colunas).
    Não consulta o Tiny. Campos ausentes voltam como None (frontend mostra '—').

    Nomes reais procurados: estoque_payload é o objeto `estoque` do detalhe Tiny v3;
    custos_payload guarda `{"precos": {...}}` com precoCusto/precoCustoMedio.
    """
    est = _product_jsonb_dict(row.get("estoque_payload"))
    custos = _product_jsonb_dict(row.get("custos_payload"))
    precos = custos.get("precos") if isinstance(custos.get("precos"), dict) else {}

    def _pick(d: Dict[str, Any], *keys: str) -> Optional[float]:
        for k in keys:
            if isinstance(d, dict) and d.get(k) is not None:
                v = _safe_float(d.get(k), None)
                if v is not None:
                    return v
        return None

    estoque_fisico = _safe_float(row.get("stock_physical"), None)
    if estoque_fisico is None:
        estoque_fisico = _pick(est, "saldo", "saldoFisico", "saldoFisicoTotal", "estoqueAtual", "quantidade")
    if estoque_fisico is None:
        estoque_fisico = _safe_float(row.get("estoque_inicial"), None)
    estoque_reservado = _safe_float(row.get("stock_reserved"), None)
    if estoque_reservado is None:
        estoque_reservado = _pick(est, "saldoReservado", "saldo_reservado", "reservado")
    estoque_disponivel = _safe_float(row.get("stock_available"), None)
    if estoque_disponivel is None:
        estoque_disponivel = _pick(est, "saldoDisponivel", "saldo_disponivel", "disponivel")
    if estoque_disponivel is None and estoque_fisico is not None and estoque_reservado is not None:
        estoque_disponivel = estoque_fisico - estoque_reservado
    custo_medio = _pick(precos, "precoCustoMedio", "preco_custo_medio", "custoMedio")
    if custo_medio is None:
        custo_medio = _safe_float(row.get("preco_custo"), None)
    return {
        "estoque_fisico": estoque_fisico,
        "estoque_reservado": estoque_reservado,
        "estoque_disponivel": estoque_disponivel,
        "custo_medio": custo_medio,
    }


@app.get("/api/admin/products")
@app.get("/admin/products")
def admin_products_local_list(
    request: Request,
    company: str = "parton",
    q: str = "",
    sync_status: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_products_local_first_table()
    where = ["company_key=%s"]
    params: List[Any] = [company_key]
    q_norm = _clean_str(q).lower()
    if q_norm:
        like = f"%{q_norm}%"
        where.append(
            """
            (
              LOWER(COALESCE(nome, '')) LIKE %s OR
              LOWER(COALESCE(sku, '')) LIKE %s OR
              LOWER(COALESCE(gtin, '')) LIKE %s OR
              LOWER(COALESCE(marca, '')) LIKE %s
            )
            """
        )
        params.extend([like, like, like, like])
    if _clean_str(sync_status):
        where.append("tiny_sync_status=%s")
        params.append(_clean_str(sync_status))
    where_sql = " AND ".join(where)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM erp.products WHERE {where_sql}", params)
            total = int((cur.fetchone() or {}).get("total") or 0)
            cur.execute(
                f"""
                SELECT id, company_key, tiny_product_id, tiny_sync_status, tiny_sync_error,
                       tiny_synced_at, origin, tipo_produto, nome, sku, gtin, ncm, cest,
                       origem, unidade, preco_venda, preco_custo, peso_liquido, peso_bruto,
                       largura, altura, comprimento, controlar_estoque, estoque_inicial,
                       estoque_minimo, estoque_maximo, localizacao, dias_preparacao, marca,
                       descricao_complementar, observacoes, estoque_payload, custos_payload,
                       stock_physical, stock_reserved, stock_available, stock_synced_at,
                       stock_sync_error, stock_payload,
                       created_at, updated_at
                FROM erp.products
                WHERE {where_sql}
                ORDER BY LOWER(COALESCE(nome, sku, '')), id
                LIMIT %s OFFSET %s
                """,
                [*params, int(limit), int(offset)],
            )
            items = []
            for r in cur.fetchall():
                item = dict(r)
                # Deriva estoque/custo a partir do que já está salvo (sem consultar Tiny)
                # e remove os JSONB brutos da resposta para mantê-la enxuta.
                item.update(_product_list_stock_cost(item))
                item.pop("estoque_payload", None)
                item.pop("custos_payload", None)
                items.append(item)
    return {"ok": True, "company_key": company_key, "items": items, "total": total, "limit": int(limit), "offset": int(offset)}


@app.get("/api/admin/products/stats")
@app.get("/admin/products/stats")
def admin_products_local_stats(request: Request, company: str = ""):
    """Indicadores de saúde da base local-first de produtos (erp.products) por empresa.

    Somente leitura: não consulta o Tiny e não altera o banco. Admin-only.
    O critério de detalhes completos/pendentes reaproveita _PRODUCTS_DETAILS_MISSING_SQL
    (mesmo de only_missing=true em refresh-tiny-details).
    """
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_products_local_first_table()
    has_tiny = "COALESCE(tiny_product_id, '') <> ''"
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE origin = 'tiny') AS origin_tiny,
                  COUNT(*) FILTER (WHERE origin = 'local') AS origin_local,
                  COUNT(*) FILTER (WHERE {has_tiny}) AS with_tiny_product_id,
                  COUNT(*) FILTER (WHERE {has_tiny} AND NOT {_PRODUCTS_DETAILS_MISSING_SQL}) AS details_complete,
                  COUNT(*) FILTER (WHERE {has_tiny} AND {_PRODUCTS_DETAILS_MISSING_SQL}) AS details_pending,
                  COUNT(*) FILTER (WHERE tiny_sync_status = 'pending') AS sync_pending,
                  COUNT(*) FILTER (WHERE tiny_sync_status = 'synced') AS sync_synced,
                  COUNT(*) FILTER (WHERE tiny_sync_status = 'error') AS sync_error,
                  MAX(tiny_synced_at) AS last_tiny_synced_at,
                  MAX(updated_at) AS last_updated_at
                FROM erp.products
                WHERE company_key = %s
                """,
                [company_key],
            )
            row = dict(cur.fetchone() or {})

    def _i(key: str) -> int:
        return int(row.get(key) or 0)

    total = _i("total")
    details_pending = _i("details_pending")
    if total == 0:
        notes = "Sem produtos nesta empresa"
    elif details_pending > 0:
        notes = "Há produtos pendentes de detalhes"
    else:
        notes = "Detalhes completos"

    return {
        "ok": True,
        "company_key": company_key,
        "total": total,
        "origin_tiny": _i("origin_tiny"),
        "origin_local": _i("origin_local"),
        "with_tiny_product_id": _i("with_tiny_product_id"),
        "details_complete": _i("details_complete"),
        "details_pending": details_pending,
        "sync_pending": _i("sync_pending"),
        "sync_synced": _i("sync_synced"),
        "sync_error": _i("sync_error"),
        "last_tiny_synced_at": row.get("last_tiny_synced_at"),
        "last_updated_at": row.get("last_updated_at"),
        "notes": notes,
    }


def _product_stock_sync_day_bounds() -> tuple:
    tz = ZoneInfo("America/Sao_Paulo")
    today = dt.datetime.now(tz).date()
    start_local = dt.datetime(today.year, today.month, today.day, tzinfo=tz)
    end_local = start_local + dt.timedelta(days=1)
    return start_local.astimezone(dt.timezone.utc), end_local.astimezone(dt.timezone.utc)


def _product_stock_sync_public_run(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "company_key": row.get("company_key"),
        "status": row.get("status"),
        "dry_run": bool(row.get("dry_run")),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "requested_by": row.get("requested_by"),
        "limit_per_run": row.get("limit_per_run"),
        "processed_count": row.get("processed_count"),
        "updated_count": row.get("updated_count"),
        "skipped_count": row.get("skipped_count"),
        "errors_count": row.get("errors_count"),
        "errors": row.get("errors") or [],
        "summary": row.get("summary") or {},
        "params": row.get("params") or {},
    }


def _product_stock_sync_status(company_key: str) -> Dict[str, Any]:
    _ensure_product_stock_sync_tables()
    start_utc, end_utc = _product_stock_sync_day_bounds()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM erp.product_stock_sync_runs
                WHERE company_key=%s
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (company_key,),
            )
            last_run = _product_stock_sync_public_run(cur.fetchone())
            cur.execute(
                """
                SELECT *
                FROM erp.product_stock_sync_runs
                WHERE company_key=%s AND dry_run=false
                  AND status IN ('completed', 'completed_with_errors')
                ORDER BY finished_at DESC NULLS LAST, started_at DESC, id DESC
                LIMIT 1
                """,
                (company_key,),
            )
            last_completed_run = _product_stock_sync_public_run(cur.fetchone())
            cur.execute(
                """
                SELECT *
                FROM erp.product_stock_sync_runs
                WHERE company_key=%s AND status='running'
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (company_key,),
            )
            running_run = _product_stock_sync_public_run(cur.fetchone())
            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM erp.product_stock_sync_runs
                WHERE company_key=%s AND dry_run=false
                  AND started_at >= %s AND started_at < %s
                  AND status IN ('running', 'completed', 'completed_with_errors', 'failed')
                """,
                (company_key, start_utc, end_utc),
            )
            today_run_count = int((cur.fetchone() or {}).get("total") or 0)
    return {
        "ok": True,
        "company_key": company_key,
        "last_run": last_run,
        "last_completed_run": last_completed_run,
        "running_run": running_run,
        "can_run_today": running_run is None and today_run_count == 0,
        "today_run_count": today_run_count,
        "daily_limit": 1,
        "default_params": {
            "dry_run": True,
            "limit": 20,
            "sleep_ms": 1000,
            "only_with_tiny_product_id": True,
            "force": False,
            "max_errors": 10,
            "update_payload": True,
        },
        "notes": "Dry-run nao consome a cota diaria. Execucao real e limitada a 1x ao dia por empresa, salvo force=true.",
    }


@app.get("/api/admin/products/stock-sync/status")
@app.get("/admin/products/stock-sync/status")
def admin_products_stock_sync_status(request: Request, company: str = ""):
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    return _product_stock_sync_status(company_key)


def _product_stock_payload_source(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return {}
    for key in ("produto", "estoque", "stock", "saldo"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return data


def _product_stock_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
    source = _product_stock_payload_source(payload)

    def pick(*keys: str) -> Optional[float]:
        for key in keys:
            if isinstance(source, dict) and source.get(key) is not None:
                parsed = _safe_float(source.get(key), None)
                if parsed is not None:
                    return parsed
        return None

    physical = pick("saldo", "saldoFisico", "saldo_fisico", "estoqueAtual", "estoque_atual", "quantidade")
    reserved = pick("saldoReservado", "saldo_reservado", "reservado", "estoqueReservado", "estoque_reservado")
    available = pick("saldoDisponivel", "saldo_disponivel", "disponivel", "estoqueDisponivel", "estoque_disponivel")
    if available is None and physical is not None and reserved is not None:
        available = physical - reserved
    return {
        "stock_physical": physical,
        "stock_reserved": reserved,
        "stock_available": available,
        "source": source,
    }


@app.post("/api/admin/products/stock-sync/run")
@app.post("/admin/products/stock-sync/run")
async def admin_products_stock_sync_run(
    request: Request,
    company: str = "parton",
    dry_run: bool = True,
    limit: int = Query(default=20, ge=1, le=100),
    sleep_ms: int = Query(default=1000, ge=0, le=5000),
    only_with_tiny_product_id: bool = True,
    after_id: Optional[int] = None,
    force: bool = False,
    max_errors: int = Query(default=10, ge=1, le=100),
    update_payload: bool = True,
):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        company = _clean_str(body.get("company")) or company
        limit = int(_safe_int(body.get("limit"), limit) or limit)
        sleep_ms = int(_safe_int(body.get("sleep_ms"), sleep_ms) or sleep_ms)
        after_id = _safe_int(body.get("after_id"), after_id)
        max_errors = int(_safe_int(body.get("max_errors"), max_errors) or max_errors)
        if body.get("dry_run") is not None:
            dry_run = _park_wrong_tiny_bool(body.get("dry_run"), dry_run)
        if body.get("only_with_tiny_product_id") is not None:
            only_with_tiny_product_id = _park_wrong_tiny_bool(body.get("only_with_tiny_product_id"), only_with_tiny_product_id)
        if body.get("force") is not None:
            force = _park_wrong_tiny_bool(body.get("force"), force)
        if body.get("update_payload") is not None:
            update_payload = _park_wrong_tiny_bool(body.get("update_payload"), update_payload)

    company_norm = _clean_str(company).lower()
    if company_norm == "all":
        company_keys = ["parton", "park"]
    elif company_norm in {"parton", "park"}:
        company_keys = [_auth_company_or_default(user, company_norm)]
    else:
        raise HTTPException(status_code=400, detail="company deve ser parton, park ou all.")

    limit = min(100, max(1, int(limit or 20)))
    sleep_ms = min(5000, max(0, int(sleep_ms or 0)))
    max_errors = min(100, max(1, int(max_errors or 10)))
    requested_by = _clean_str(user.get("login") or user.get("email") or user.get("id"))
    params_payload = {
        "company": company_norm,
        "dry_run": bool(dry_run),
        "limit": limit,
        "sleep_ms": sleep_ms,
        "only_with_tiny_product_id": bool(only_with_tiny_product_id),
        "after_id": after_id,
        "force": bool(force),
        "max_errors": max_errors,
        "update_payload": bool(update_payload),
        "stock_path_template": os.getenv("TINY_V3_STOCK_PATH_TEMPLATE", "estoque/{id_produto}"),
    }

    _ensure_product_stock_sync_tables()
    company_results: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    all_samples: List[Dict[str, Any]] = []
    total_processed = 0
    total_updated = 0
    total_skipped = 0
    run_ids: List[int] = []

    for company_key in company_keys:
        status_info = _product_stock_sync_status(company_key)
        if status_info.get("running_run"):
            raise HTTPException(status_code=409, detail=f"Ja existe sincronizacao de estoque em andamento para {company_key}.")
        if not dry_run and not status_info.get("can_run_today") and not force:
            raise HTTPException(
                status_code=409,
                detail=f"Sincronizacao real de estoque ja executada hoje para {company_key}. Use force=true apenas para continuacao/teste controlado.",
            )

        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO erp.product_stock_sync_runs (
                      company_key, status, dry_run, requested_by, limit_per_run, params, started_at
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
                    RETURNING id
                    """,
                    (
                        company_key,
                        "dry_run" if dry_run else "running",
                        bool(dry_run),
                        requested_by or None,
                        limit,
                        json.dumps({**params_payload, "company": company_key}, ensure_ascii=False, default=_json_default),
                    ),
                )
                run_id = int(cur.fetchone()["id"])
        run_ids.append(run_id)

        where = ["company_key=%s"]
        query_params: List[Any] = [company_key]
        if only_with_tiny_product_id:
            where.append("COALESCE(tiny_product_id, '') <> ''")
        if after_id is not None:
            where.append("id > %s")
            query_params.append(int(after_id))
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, company_key, tiny_product_id, sku, nome
                    FROM erp.products
                    WHERE {' AND '.join(where)}
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    [*query_params, limit],
                )
                products = [dict(r) for r in cur.fetchall()]

        tiny = _tiny_v3_for_company(company_key)
        processed_count = 0
        updated_count = 0
        skipped_count = 0
        errors: List[Dict[str, Any]] = []
        samples: List[Dict[str, Any]] = []
        next_after_id = after_id
        stopped_reason = "limit_reached"

        for idx, product in enumerate(products):
            product_id = int(product.get("id"))
            next_after_id = product_id
            tiny_product_id = _clean_str(product.get("tiny_product_id"))
            if not tiny_product_id:
                skipped_count += 1
                errors.append({"id": product_id, "sku": product.get("sku"), "error": "Produto sem tiny_product_id."})
                continue
            try:
                response = tiny.obter_estoque_produto(int(tiny_product_id))
                payload = _product_import_payload(response)
                stock = _product_stock_extract(payload)
                if stock.get("stock_physical") is None and stock.get("stock_reserved") is None and stock.get("stock_available") is None:
                    raise TinyAPIError("Tiny V3 nao retornou campos reconheciveis de estoque.")
                processed_count += 1
                sample_item = {
                    "id": product_id,
                    "sku": product.get("sku"),
                    "tiny_product_id": tiny_product_id,
                    "dry_run": bool(dry_run),
                    "stock_physical": stock.get("stock_physical"),
                    "stock_reserved": stock.get("stock_reserved"),
                    "stock_available": stock.get("stock_available"),
                }
                if not dry_run:
                    with _db() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE erp.products
                                SET stock_physical=%s,
                                    stock_reserved=%s,
                                    stock_available=%s,
                                    stock_synced_at=now(),
                                    stock_sync_error=NULL,
                                    stock_payload=CASE WHEN %s THEN %s::jsonb ELSE stock_payload END,
                                    updated_at=now()
                                WHERE company_key=%s AND id=%s
                                """,
                                (
                                    stock.get("stock_physical"),
                                    stock.get("stock_reserved"),
                                    stock.get("stock_available"),
                                    bool(update_payload),
                                    json.dumps(payload, ensure_ascii=False, default=_json_default),
                                    company_key,
                                    product_id,
                                ),
                            )
                            updated_count += int(cur.rowcount or 0)
                    sample_item["action"] = "updated"
                else:
                    sample_item["action"] = "would_update"
                samples.append(sample_item)
            except Exception as exc:
                detail = str(exc)[:500]
                low = detail.lower()
                errors.append({"id": product_id, "sku": product.get("sku"), "tiny_product_id": tiny_product_id, "error": detail})
                skipped_count += 1
                if ("401" in low or "403" in low or "unauthorized" in low or "forbidden" in low or "invalid_grant" in low) and "429" not in low:
                    stopped_reason = "auth_error"
                    break
                if "429" in low:
                    stopped_reason = "rate_limited"
                    break
                if len(errors) >= max_errors:
                    stopped_reason = "max_errors"
                    break
            if sleep_ms and idx < len(products) - 1:
                time.sleep(sleep_ms / 1000.0)

        if not products:
            stopped_reason = "empty_selection"
        elif len(products) < limit and stopped_reason == "limit_reached":
            stopped_reason = "short_batch"
        final_status = "dry_run" if dry_run else ("completed_with_errors" if errors else "completed")
        if stopped_reason == "auth_error":
            final_status = "failed"
        summary = {
            "next_after_id": next_after_id,
            "stopped_reason": stopped_reason,
            "can_continue": bool(next_after_id and stopped_reason in {"limit_reached", "max_errors", "rate_limited"}),
            "samples": samples[:20],
        }
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE erp.product_stock_sync_runs
                    SET status=%s,
                        finished_at=now(),
                        processed_count=%s,
                        updated_count=%s,
                        skipped_count=%s,
                        errors_count=%s,
                        errors=%s::jsonb,
                        summary=%s::jsonb
                    WHERE id=%s
                    """,
                    (
                        final_status,
                        processed_count,
                        updated_count,
                        skipped_count,
                        len(errors),
                        json.dumps(errors, ensure_ascii=False, default=_json_default),
                        json.dumps(summary, ensure_ascii=False, default=_json_default),
                        run_id,
                    ),
                )
        company_results.append({
            "company_key": company_key,
            "run_id": run_id,
            "processed_count": processed_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "errors_count": len(errors),
            "errors": errors,
            **summary,
        })
        total_processed += processed_count
        total_updated += updated_count
        total_skipped += skipped_count
        all_errors.extend(errors)
        all_samples.extend(samples[: max(0, 20 - len(all_samples))])

    primary = company_results[0] if company_results else {}
    return {
        "ok": not any(item.get("stopped_reason") == "auth_error" for item in company_results),
        "company_key": company_norm,
        "dry_run": bool(dry_run),
        "run_id": run_ids[0] if len(run_ids) == 1 else None,
        "run_ids": run_ids,
        "processed_count": total_processed,
        "updated_count": total_updated,
        "skipped_count": total_skipped,
        "errors_count": len(all_errors),
        "errors": all_errors,
        "next_after_id": primary.get("next_after_id"),
        "stopped_reason": primary.get("stopped_reason") or "completed",
        "samples": all_samples,
        "can_continue": bool(primary.get("can_continue")),
        "daily_limit_consumed": not dry_run,
        "companies": company_results,
        "params": params_payload,
    }


def _products_sku_conflicts_tiny_probe(
    company_key: str,
    *,
    limit: int,
    max_pages: int,
    sleep_ms: int,
) -> Dict[str, Any]:
    """Sonda somente-leitura do Tiny (listar_produtos) para diagnóstico de SKUs.

    Não busca detalhes produto a produto, não grava nada, não importa. Apenas
    pagina a listagem (com travas de limite/páginas/pausa) e coleta sku/id/nome
    de cada item para detectar SKUs duplicados na própria conta Tiny/Olist e
    reproduzir o critério de conflito do importador contra a base local.
    """
    tiny = _tiny_v3_for_company(company_key)
    offset = 0
    pages_processed = 0
    expected_total: Optional[int] = None
    stopped_reason = "max_pages"
    errors: List[Dict[str, Any]] = []
    # sku_key (sku exato) -> lista de {tiny_product_id, nome}
    tiny_by_sku: Dict[str, List[Dict[str, Any]]] = {}

    for page_idx in range(max_pages):
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        try:
            list_response = _product_import_payload(tiny.listar_produtos(params))
        except TinyAPIError as exc:
            errors.append({"offset": offset, "error": str(exc)[:500]})
            stopped_reason = "tiny_error"
            break
        raw_items = list_response.get("itens") or list_response.get("produtos") or []
        if not isinstance(raw_items, list):
            raw_items = []
        paginacao = list_response.get("paginacao") if isinstance(list_response.get("paginacao"), dict) else {}
        expected_total = _safe_int(paginacao.get("total"), expected_total)

        if not raw_items:
            stopped_reason = "empty_page"
            break

        for item in raw_items:
            mapped = _product_import_map_tiny(item if isinstance(item, dict) else {})
            sku = _clean_str(mapped.get("sku"))
            if not sku:
                continue
            tiny_by_sku.setdefault(sku, []).append(
                {
                    "tiny_product_id": _clean_str(mapped.get("tiny_product_id")),
                    "nome": _clean_str(mapped.get("nome")),
                }
            )

        pages_processed += 1
        offset += limit
        if expected_total is not None and offset >= int(expected_total):
            stopped_reason = "total_reached"
            break
        if len(raw_items) < limit:
            stopped_reason = "short_page"
            break
        if sleep_ms and page_idx < max_pages - 1:
            time.sleep(sleep_ms / 1000.0)

    # Duplicidades dentro do próprio Tiny (mesmo SKU em mais de um produto Tiny).
    tiny_duplicates: List[Dict[str, Any]] = []
    tiny_duplicate_rows = 0
    for sku, items in tiny_by_sku.items():
        if len(items) > 1:
            tiny_duplicate_rows += len(items)
            tiny_duplicates.append({"sku": sku, "count": len(items), "items": items})
    tiny_duplicates.sort(key=lambda g: (-g["count"], g["sku"]))

    # Conflitos incoming(Tiny) vs base local, reproduzindo o critério do importador:
    # mesmo SKU existe localmente, mas com tiny_product_id diferente do produto Tiny.
    tiny_vs_local_conflicts: List[Dict[str, Any]] = []
    skus = list(tiny_by_sku.keys())
    if skus:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, sku, tiny_product_id, origin
                    FROM erp.products
                    WHERE company_key=%s AND sku = ANY(%s)
                    """,
                    (company_key, skus),
                )
                local_rows = [dict(r) for r in cur.fetchall()]
        local_by_sku: Dict[str, List[Dict[str, Any]]] = {}
        for r in local_rows:
            local_by_sku.setdefault(_clean_str(r.get("sku")), []).append(r)
        for sku, tiny_items in tiny_by_sku.items():
            locals_for_sku = local_by_sku.get(sku) or []
            if not locals_for_sku:
                continue
            for ti in tiny_items:
                tpid = _clean_str(ti.get("tiny_product_id"))
                # conflito quando nenhuma linha local desse SKU tem o mesmo tiny_product_id
                match = any(_clean_str(lr.get("tiny_product_id")) == tpid and tpid for lr in locals_for_sku)
                if not match:
                    for lr in locals_for_sku:
                        local_tpid = _clean_str(lr.get("tiny_product_id"))
                        if local_tpid != tpid:
                            tiny_vs_local_conflicts.append(
                                {
                                    "sku": sku,
                                    "tiny_product_id": tpid,
                                    "tiny_nome": _clean_str(ti.get("nome")),
                                    "local_product_id": lr.get("id"),
                                    "local_origin": lr.get("origin"),
                                    "local_tiny_product_id": local_tpid,
                                }
                            )

    return {
        "tiny_probe": {
            "pages_processed": pages_processed,
            "fetched_count": sum(len(v) for v in tiny_by_sku.values()),
            "distinct_skus": len(tiny_by_sku),
            "expected_total": expected_total,
            "stopped_reason": stopped_reason,
            "errors": errors,
        },
        "tiny_duplicate_skus_count": len(tiny_duplicates),
        "tiny_duplicate_rows_count": tiny_duplicate_rows,
        "tiny_duplicates": tiny_duplicates,
        "tiny_vs_local_conflicts": tiny_vs_local_conflicts,
    }


@app.get("/api/admin/products/sku-conflicts")
@app.get("/admin/products/sku-conflicts")
def admin_products_sku_conflicts(
    request: Request,
    company: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    include_tiny_probe: bool = False,
    tiny_limit: int = Query(default=100, ge=1, le=100),
    max_pages: int = Query(default=10, ge=1, le=20),
    sleep_ms: int = Query(default=500, ge=0, le=3000),
):
    """Diagnóstico admin-only somente-leitura de conflitos/duplicidades de SKU.

    Por padrão (include_tiny_probe=false) usa apenas erp.products e NÃO consulta o
    Tiny. Não altera banco, não importa, não completa detalhes. O critério de
    conflito de importação reproduz o do importador (mesmo SKU, tiny_product_id
    diferente).
    """
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_products_local_first_table()

    # Carrega linhas locais com SKU preenchido e agrupa por SKU exato (mesmo
    # critério de igualdade usado pelo importador: WHERE sku=%s).
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, sku, tiny_product_id, nome, origin, tiny_sync_status,
                       created_at, updated_at
                FROM erp.products
                WHERE company_key=%s AND COALESCE(TRIM(sku), '') <> ''
                ORDER BY sku, id
                """,
                (company_key,),
            )
            rows = [dict(r) for r in cur.fetchall()]

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(_clean_str(r.get("sku")), []).append(r)

    def _item(r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": r.get("id"),
            "tiny_product_id": r.get("tiny_product_id"),
            "nome": r.get("nome"),
            "origin": r.get("origin"),
            "tiny_sync_status": r.get("tiny_sync_status"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        }

    # Duplicidades locais: mesmo company_key + sku com mais de uma linha.
    local_dup_groups: List[Dict[str, Any]] = []
    local_duplicate_rows_count = 0
    # Conflitos derivados localmente: mesmo SKU ligado a tiny_product_ids distintos.
    known_conflict_items: List[Dict[str, Any]] = []
    for sku, items in groups.items():
        if len(items) > 1:
            local_duplicate_rows_count += len(items)
            local_dup_groups.append({"sku": sku, "count": len(items), "items": [_item(i) for i in items]})
        distinct_tpids = sorted({_clean_str(i.get("tiny_product_id")) for i in items if _clean_str(i.get("tiny_product_id"))})
        if len(distinct_tpids) > 1:
            known_conflict_items.append(
                {
                    "sku": sku,
                    "tiny_product_ids": distinct_tpids,
                    "local_ids": [i.get("id") for i in items],
                }
            )

    local_dup_groups.sort(key=lambda g: (-g["count"], g["sku"]))
    local_duplicate_skus_count = len(local_dup_groups)
    local_duplicates = local_dup_groups[: int(limit)]

    notes_parts: List[str] = []
    if local_duplicate_skus_count == 0:
        notes_parts.append("Sem SKUs duplicados na base local desta empresa.")
    else:
        notes_parts.append(
            f"{local_duplicate_skus_count} SKU(s) duplicado(s) localmente ({local_duplicate_rows_count} linhas)."
        )
    if known_conflict_items:
        notes_parts.append(
            f"{len(known_conflict_items)} SKU(s) ligado(s) a mais de um tiny_product_id na base local."
        )
    if not include_tiny_probe:
        notes_parts.append(
            "Conflitos entre produtos novos do Tiny e a base local (ex.: SKU já existente com outro "
            "tiny_product_id) só aparecem com include_tiny_probe=true."
        )

    result: Dict[str, Any] = {
        "ok": True,
        "company_key": company_key,
        "include_tiny_probe": bool(include_tiny_probe),
        "local_duplicate_skus_count": local_duplicate_skus_count,
        "local_duplicate_rows_count": local_duplicate_rows_count,
        "local_duplicates": local_duplicates,
        "known_import_conflicts": {
            "source": "local",
            "count": len(known_conflict_items),
            "items": known_conflict_items,
        },
        "notes": " ".join(notes_parts),
    }

    if include_tiny_probe:
        tiny_limit = min(100, max(1, int(tiny_limit or 100)))
        max_pages = min(20, max(1, int(max_pages or 10)))
        sleep_ms = min(3000, max(0, int(sleep_ms or 0)))
        probe = _products_sku_conflicts_tiny_probe(
            company_key,
            limit=tiny_limit,
            max_pages=max_pages,
            sleep_ms=sleep_ms,
        )
        result.update(probe)
        probe_meta = probe.get("tiny_probe") or {}
        result["notes"] += (
            f" Sonda Tiny: {probe_meta.get('fetched_count', 0)} itens em "
            f"{probe_meta.get('pages_processed', 0)} página(s); "
            f"{probe.get('tiny_duplicate_skus_count', 0)} SKU(s) duplicado(s) no Tiny; "
            f"{len(probe.get('tiny_vs_local_conflicts') or [])} conflito(s) Tiny↔local."
        )

    return _attach_product_conflict_decisions(company_key, result)


@app.get("/api/admin/products/conflict-decisions")
@app.get("/admin/products/conflict-decisions")
def admin_products_conflict_decisions(
    request: Request,
    company: str = "",
    sku: str = "",
    status: str = "active",
):
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_product_conflict_decisions_table()
    where = ["company_key=%s"]
    params: List[Any] = [company_key]
    sku_norm = _clean_str(sku)
    status_norm = _clean_str(status)
    if sku_norm:
        where.append("sku=%s")
        params.append(sku_norm)
    if status_norm:
        where.append("status=%s")
        params.append(status_norm)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM erp.product_conflict_decisions
                WHERE {' AND '.join(where)}
                ORDER BY updated_at DESC, id DESC
                """,
                params,
            )
            items = [_product_conflict_decision_public(dict(r)) for r in cur.fetchall()]
    return {
        "ok": True,
        "company_key": company_key,
        "items": items,
        "count": len(items),
        "allowed_decisions": sorted(_PRODUCT_CONFLICT_DECISIONS),
    }


@app.post("/api/admin/products/conflict-decisions")
@app.post("/admin/products/conflict-decisions")
async def admin_products_conflict_decision_save(request: Request):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload inválido.")

    company_key = _auth_company_or_default(user, _clean_str(body.get("company") or body.get("company_key")))
    sku = _clean_str(body.get("sku"))
    decision = _clean_str(body.get("decision"))
    status = _clean_str(body.get("status")) or "active"
    if not sku:
        raise HTTPException(status_code=400, detail="sku é obrigatório.")
    if decision not in _PRODUCT_CONFLICT_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"decision inválida. Use uma de: {', '.join(sorted(_PRODUCT_CONFLICT_DECISIONS))}.",
        )
    if status not in {"active", "archived"}:
        raise HTTPException(status_code=400, detail="status inválido. Use active ou archived.")

    local_product_id = _safe_int(body.get("local_product_id"), None)
    local_tiny_product_id = _clean_str(body.get("local_tiny_product_id"))
    conflict_tiny_product_id = _clean_str(body.get("conflict_tiny_product_id") or body.get("tiny_product_id"))
    conflict_tiny_name = _clean_str(body.get("conflict_tiny_name") or body.get("tiny_nome"))
    notes = _clean_str(body.get("notes")) or None
    raw_payload = body.get("raw_payload")
    if raw_payload is None:
        raw_payload = body
    created_by = _clean_str(user.get("login") or user.get("email") or user.get("id"))

    _ensure_product_conflict_decisions_table()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM erp.product_conflict_decisions
                WHERE company_key=%s
                  AND sku=%s
                  AND COALESCE(local_product_id, 0) = COALESCE(%s, 0)
                  AND COALESCE(local_tiny_product_id, '') = COALESCE(%s, '')
                  AND COALESCE(conflict_tiny_product_id, '') = COALESCE(%s, '')
                  AND status=%s
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (company_key, sku, local_product_id, local_tiny_product_id, conflict_tiny_product_id, status),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    UPDATE erp.product_conflict_decisions
                    SET decision=%s,
                        conflict_tiny_name=%s,
                        notes=%s,
                        created_by=COALESCE(NULLIF(%s, ''), created_by),
                        raw_payload=%s::jsonb,
                        updated_at=now()
                    WHERE id=%s
                    RETURNING *
                    """,
                    (
                        decision,
                        conflict_tiny_name or None,
                        notes,
                        created_by,
                        json.dumps(raw_payload, ensure_ascii=False, default=_json_default),
                        existing.get("id"),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO erp.product_conflict_decisions (
                      company_key, sku, local_product_id, local_tiny_product_id,
                      conflict_tiny_product_id, conflict_tiny_name, decision, status,
                      notes, created_by, raw_payload, created_at, updated_at
                    ) VALUES (
                      %s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''),
                      %s, %s, %s, NULLIF(%s, ''), %s::jsonb, now(), now()
                    )
                    RETURNING *
                    """,
                    (
                        company_key,
                        sku,
                        local_product_id,
                        local_tiny_product_id,
                        conflict_tiny_product_id,
                        conflict_tiny_name,
                        decision,
                        status,
                        notes,
                        created_by,
                        json.dumps(raw_payload, ensure_ascii=False, default=_json_default),
                    ),
                )
            row = _product_conflict_decision_public(dict(cur.fetchone()))

    return {
        "ok": True,
        "company_key": company_key,
        "item": row,
        "allowed_decisions": sorted(_PRODUCT_CONFLICT_DECISIONS),
        "message": "Decisão registrada localmente. Nenhum produto local ou Tiny foi alterado.",
    }


@app.post("/api/admin/products")
@app.post("/admin/products")
async def admin_products_local_create(request: Request, company: str = ""):
    user = _catalog_require_admin(request)
    body = await request.json()
    body_company = _clean_str(body.get("company"))
    company_key = _auth_company_or_default(user, company or body_company or "parton")
    _ensure_products_local_first_table()

    nome = _clean_str(body.get("nome"))
    if not nome:
        raise HTTPException(status_code=400, detail="Campo 'nome' é obrigatório.")

    sku = _clean_str(body.get("sku") or body.get("codigo")) or None

    def _bv(v, default=False):
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() not in {"0", "false", "no", "off", ""}

    def _jv(v, empty="{}"):
        if v is None:
            return empty
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False, default=_json_default)
        try:
            parsed = json.loads(str(v))
            return json.dumps(parsed, ensure_ascii=False, default=_json_default)
        except Exception:
            return empty

    tipo_produto = _clean_str(body.get("tipo_produto")) or None
    gtin = _clean_str(body.get("gtin")) or None
    ncm = _clean_str(body.get("ncm")) or None
    cest = _clean_str(body.get("cest")) or None
    origem = _clean_str(body.get("origem")) or None
    unidade = _clean_str(body.get("unidade")) or None
    tipo_embalagem = _clean_str(body.get("tipo_embalagem")) or None
    embalagem = _clean_str(body.get("embalagem")) or None
    localizacao = _clean_str(body.get("localizacao")) or None
    marca = _clean_str(body.get("marca")) or None
    descricao_complementar = _clean_str(body.get("descricao_complementar")) or None
    observacoes = _clean_str(body.get("observacoes")) or None
    linha_produto = _clean_str(body.get("linha_produto")) or None
    garantia = _clean_str(body.get("garantia")) or None

    preco_venda = _safe_float(body.get("preco_venda"), None)
    preco_custo = _safe_float(body.get("preco_custo"), None)
    peso_liquido = _safe_float(body.get("peso_liquido"), None)
    peso_bruto = _safe_float(body.get("peso_bruto"), None)
    numero_volumes = _safe_float(body.get("numero_volumes"), None)
    largura = _safe_float(body.get("largura"), None)
    altura = _safe_float(body.get("altura"), None)
    comprimento = _safe_float(body.get("comprimento"), None)
    estoque_inicial = _safe_float(body.get("estoque_inicial"), None)
    estoque_minimo = _safe_float(body.get("estoque_minimo"), None)
    estoque_maximo = _safe_float(body.get("estoque_maximo"), None)
    dias_preparacao = _safe_int(body.get("dias_preparacao"))
    unidade_por_caixa = _safe_float(body.get("unidade_por_caixa"), None)
    markup = _safe_float(body.get("markup"), None)

    controlar_estoque = _bv(body.get("controlar_estoque"), False)
    controlar_lotes = _bv(body.get("controlar_lotes"), False)
    _piv = body.get("permitir_inclusao_vendas")
    _pv = body.get("permitir_vendas")
    permitir_vendas_val = _bv(_piv if _piv is not None else _pv, True)

    dimensoes_payload = _jv(body.get("dimensoes"))
    estoque_payload = _jv(body.get("estoque"))
    seo_payload = _jv(body.get("seo"))
    atributos_payload = _jv(body.get("atributos"), "[]")
    anuncios_payload = _jv(body.get("anuncios"), "[]")
    custos_payload = _jv(body.get("custos"))
    fornecedores_payload = _jv(body.get("fornecedores"), "[]")
    imagens_payload = _jv(body.get("imagens"), "[]")
    tiny_raw_payload = _jv(body.get("tiny_raw"))

    with _db() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO erp.products (
                        company_key, origin, tiny_sync_status, tiny_product_id, tiny_sync_error, tiny_synced_at,
                        tipo_produto, nome, sku, gtin, ncm, cest, origem, unidade,
                        preco_venda, preco_custo, peso_liquido, peso_bruto, numero_volumes,
                        tipo_embalagem, embalagem, largura, altura, comprimento,
                        controlar_estoque, estoque_inicial, estoque_minimo, estoque_maximo, controlar_lotes,
                        localizacao, dias_preparacao, marca, descricao_complementar, observacoes,
                        unidade_por_caixa, linha_produto, garantia, markup, permitir_vendas,
                        dimensoes_payload, estoque_payload, seo_payload, atributos_payload,
                        anuncios_payload, custos_payload, fornecedores_payload, imagens_payload, tiny_raw_payload,
                        created_at, updated_at
                    ) VALUES (
                        %s, 'local', 'pending', NULL, NULL, NULL,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                        now(), now()
                    ) RETURNING *
                    """,
                    (
                        company_key,
                        tipo_produto, nome, sku, gtin, ncm, cest, origem, unidade,
                        preco_venda, preco_custo, peso_liquido, peso_bruto, numero_volumes,
                        tipo_embalagem, embalagem, largura, altura, comprimento,
                        controlar_estoque, estoque_inicial, estoque_minimo, estoque_maximo, controlar_lotes,
                        localizacao, dias_preparacao, marca, descricao_complementar, observacoes,
                        unidade_por_caixa, linha_produto, garantia, markup, permitir_vendas_val,
                        dimensoes_payload, estoque_payload, seo_payload, atributos_payload,
                        anuncios_payload, custos_payload, fornecedores_payload, imagens_payload, tiny_raw_payload,
                    ),
                )
                row = dict(cur.fetchone())
            except psycopg2.IntegrityError as e:
                if getattr(e, "pgcode", None) == "23505":
                    sku_info = f" '{sku}'" if sku else ""
                    raise HTTPException(status_code=409, detail=f"SKU{sku_info} já cadastrado para empresa '{company_key}'.")
                raise HTTPException(status_code=409, detail="Conflito ao salvar produto.")

    return {"ok": True, "product": row}


def _product_import_json(value: Any, empty: str = "{}") -> str:
    if value is None:
        return empty
    try:
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    except Exception:
        return empty


def _product_import_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    payload = response.get("data") if isinstance(response.get("data"), dict) else response
    return payload if isinstance(payload, dict) else {}


def _product_import_pick(source: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def _product_import_map_tiny(raw: Dict[str, Any]) -> Dict[str, Any]:
    p = raw.get("produto") if isinstance(raw.get("produto"), dict) else raw
    if not isinstance(p, dict):
        p = {}
    precos = p.get("precos") if isinstance(p.get("precos"), dict) else {}
    estoque = p.get("estoque") if isinstance(p.get("estoque"), dict) else {}
    dimensoes = p.get("dimensoes") if isinstance(p.get("dimensoes"), dict) else {}
    marca = p.get("marca") if isinstance(p.get("marca"), dict) else {}
    seo = p.get("seo") if isinstance(p.get("seo"), dict) else {}
    tributacao = p.get("tributacao") if isinstance(p.get("tributacao"), dict) else {}
    embalagem = dimensoes.get("embalagem") if isinstance(dimensoes.get("embalagem"), dict) else {}
    fornecedores = p.get("fornecedores") if isinstance(p.get("fornecedores"), list) else []
    anexos = p.get("anexos") if isinstance(p.get("anexos"), list) else []
    variacoes = p.get("variacoes") if isinstance(p.get("variacoes"), list) else []
    tags = p.get("tags") if isinstance(p.get("tags"), list) else []
    keywords = seo.get("keywords")
    if isinstance(keywords, list):
        keywords_value = ", ".join(str(item).strip() for item in keywords if str(item).strip())
    else:
        keywords_value = _clean_str(keywords)

    mapped = {
        "tiny_product_id": _clean_str(p.get("id")),
        "tipo_produto": _clean_str(p.get("tipo")),
        "nome": _product_import_pick(p, "descricao", "nome"),
        "sku": _product_import_pick(p, "sku", "codigo"),
        "gtin": _clean_str(p.get("gtin")),
        "origem": _product_import_pick(tributacao, "origem", "origemProduto"),
        "unidade": _clean_str(p.get("unidade")),
        "ncm": _clean_str(p.get("ncm")),
        "cest": _product_import_pick(p, "cest") or _product_import_pick(tributacao, "cest"),
        "preco_venda": _safe_float(precos.get("preco"), None),
        "preco_custo": _safe_float(precos.get("precoCusto"), None),
        "peso_liquido": _safe_float(dimensoes.get("pesoLiquido"), None),
        "peso_bruto": _safe_float(dimensoes.get("pesoBruto"), None),
        "numero_volumes": _safe_float(dimensoes.get("quantidadeVolumes"), None),
        "tipo_embalagem": _clean_str(embalagem.get("id")),
        "embalagem": _clean_str(embalagem.get("descricao")),
        "largura": _safe_float(dimensoes.get("largura"), None),
        "altura": _safe_float(dimensoes.get("altura"), None),
        "comprimento": _safe_float(dimensoes.get("comprimento"), None),
        "controlar_estoque": bool(estoque.get("controlar")) if estoque.get("controlar") is not None else False,
        "estoque_inicial": _safe_float(estoque.get("quantidade"), None),
        "estoque_minimo": _safe_float(estoque.get("minimo"), None),
        "estoque_maximo": _safe_float(estoque.get("maximo"), None),
        "controlar_lotes": bool(p.get("controlarLotes")) if p.get("controlarLotes") is not None else False,
        "localizacao": _clean_str(estoque.get("localizacao")),
        "dias_preparacao": _safe_int(estoque.get("diasPreparacao"), None),
        "marca": _clean_str(marca.get("nome") or p.get("marca")),
        "descricao_complementar": _clean_str(p.get("descricaoComplementar")),
        "link_video": _clean_str(seo.get("linkVideo")),
        "slug": _clean_str(seo.get("slug")),
        "keywords": keywords_value,
        "titulo_seo": _clean_str(seo.get("titulo")),
        "descricao_seo": _clean_str(seo.get("descricao")),
        "tags": ", ".join(_clean_str(tag.get("nome") if isinstance(tag, dict) else tag) for tag in tags if _clean_str(tag.get("nome") if isinstance(tag, dict) else tag)),
        "unidade_por_caixa": _safe_float(p.get("unidadePorCaixa"), None),
        "linha_produto": _clean_str(p.get("linhaProduto")),
        "garantia": _clean_str(p.get("garantia")),
        "gtin_tributavel": _clean_str(tributacao.get("gtinEmbalagem")),
        "valor_ipi_fixo": _safe_float(tributacao.get("valorIPIFixo"), None),
        "codigo_enquadramento_legal_ipi": _clean_str(tributacao.get("classeIPI")),
        "codigo_fornecedor": _clean_str(fornecedores[0].get("codigoProdutoNoFornecedor")) if fornecedores and isinstance(fornecedores[0], dict) else "",
        "observacoes": _clean_str(p.get("observacoes")),
        "dimensoes_payload": _product_import_json(dimensoes),
        "estoque_payload": _product_import_json(estoque),
        "seo_payload": _product_import_json(seo),
        "atributos_payload": _product_import_json(p.get("grade") or [], "[]"),
        "anuncios_payload": _product_import_json(p.get("ecommerce") or p.get("marketplaces") or [], "[]"),
        "custos_payload": _product_import_json({"precos": precos}),
        "fornecedores_payload": _product_import_json(fornecedores, "[]"),
        "imagens_payload": _product_import_json(anexos, "[]"),
        "tiny_raw_payload": _product_import_json(p),
    }
    mapped["tiny_raw_payload_dict"] = p
    mapped["variations_count"] = len(variacoes)
    return mapped


@app.post("/api/admin/products/import-tiny")
@app.post("/admin/products/import-tiny")
async def admin_products_import_tiny(
    request: Request,
    company: str = "parton",
    q: str = "",
    field: str = "nome",
    situacao: str = "A",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    dry_run: bool = True,
    import_details: bool = True,
):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        company = _clean_str(body.get("company")) or company
        q = _clean_str(body.get("q")) or q
        field = _clean_str(body.get("field")) or field
        situacao = _clean_str(body.get("situacao")) or situacao
        limit = int(_safe_int(body.get("limit"), limit) or limit)
        offset = int(_safe_int(body.get("offset"), offset) or offset)
        if body.get("dry_run") is not None:
            dry_run = bool(body.get("dry_run"))
        if body.get("import_details") is not None:
            import_details = bool(body.get("import_details"))

    company_key = _auth_company_or_default(user, company)
    limit = min(100, max(1, int(limit or 20)))
    offset = max(0, int(offset or 0))
    field_key = _clean_str(field).lower()
    if field_key == "sku":
        field_key = "codigo"
    if field_key not in {"nome", "codigo", "gtin"}:
        raise HTTPException(status_code=400, detail="Campo de busca inválido. Use nome, codigo, sku ou gtin.")
    situacao_norm = _clean_str(situacao).upper()
    if situacao_norm and situacao_norm not in {"A", "I", "E"}:
        raise HTTPException(status_code=400, detail="Situação inválida. Use A, I ou E.")

    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    q_norm = _clean_str(q)
    if q_norm:
        params[field_key] = q_norm
    if situacao_norm:
        params["situacao"] = situacao_norm

    _ensure_products_local_first_table()
    tiny = _tiny_v3_for_company(company_key)
    try:
        list_response = _product_import_payload(tiny.listar_produtos(params))
    except TinyAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raw_items = list_response.get("itens") or list_response.get("produtos") or []
    if not isinstance(raw_items, list):
        raw_items = []

    created_count = 0
    updated_count = 0
    skipped_count = 0
    conflicts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    sample: List[Dict[str, Any]] = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            skipped_count += 1
            continue
        list_product = raw_item.get("produto") if isinstance(raw_item.get("produto"), dict) else raw_item
        tiny_product_id = _clean_str(list_product.get("id") if isinstance(list_product, dict) else "")
        raw_product = list_product if isinstance(list_product, dict) else {}
        if import_details and tiny_product_id:
            try:
                raw_product = _product_import_payload(tiny.obter_produto(int(tiny_product_id)))
            except Exception as exc:
                errors.append({"tiny_product_id": tiny_product_id, "error": str(exc)[:500]})
                raw_product = list_product
        mapped = _product_import_map_tiny(raw_product)
        tiny_product_id = mapped.get("tiny_product_id") or tiny_product_id
        sku = _clean_str(mapped.get("sku"))
        nome = _clean_str(mapped.get("nome"))
        if not tiny_product_id and not sku:
            skipped_count += 1
            errors.append({"tiny_product_id": "", "sku": "", "error": "Produto Tiny sem id e sem SKU."})
            continue
        if not nome:
            mapped["nome"] = sku or f"Produto Tiny {tiny_product_id}"

        action = "create"
        existing = None
        sku_conflict = None
        with _db() as conn:
            with conn.cursor() as cur:
                if tiny_product_id:
                    cur.execute(
                        "SELECT id, origin, tiny_product_id, sku FROM erp.products WHERE company_key=%s AND tiny_product_id=%s LIMIT 1",
                        (company_key, tiny_product_id),
                    )
                    existing = cur.fetchone()
                if sku:
                    cur.execute(
                        """
                        SELECT id, origin, tiny_product_id, sku
                        FROM erp.products
                        WHERE company_key=%s AND sku=%s
                          AND (%s IS NULL OR COALESCE(tiny_product_id, '') <> %s)
                        LIMIT 1
                        """,
                        (company_key, sku, tiny_product_id or None, tiny_product_id or ""),
                    )
                    sku_conflict = cur.fetchone()
        if sku_conflict:
            conflict = dict(sku_conflict)
            conflicts.append({
                "reason": "sku_conflict",
                "sku": sku,
                "tiny_product_id": tiny_product_id,
                "local_product_id": conflict.get("id"),
                "local_origin": conflict.get("origin"),
                "local_tiny_product_id": conflict.get("tiny_product_id"),
            })
            skipped_count += 1
            action = "conflict"
        elif existing:
            action = "update"

        sample.append({
            "tiny_product_id": tiny_product_id,
            "sku": sku,
            "nome": mapped.get("nome"),
            "action": action,
            "dry_run": bool(dry_run),
            "details": bool(import_details),
            "variations_count": mapped.get("variations_count", 0),
        })
        if dry_run or action == "conflict":
            continue

        values = (
            company_key, tiny_product_id or None, mapped.get("tipo_produto") or None, mapped.get("nome"),
            sku or None, mapped.get("gtin") or None, mapped.get("origem") or None, mapped.get("unidade") or None,
            mapped.get("ncm") or None, mapped.get("cest") or None, mapped.get("preco_venda"), mapped.get("preco_custo"),
            mapped.get("peso_liquido"), mapped.get("peso_bruto"), mapped.get("numero_volumes"), mapped.get("tipo_embalagem") or None,
            mapped.get("embalagem") or None, mapped.get("largura"), mapped.get("altura"), mapped.get("comprimento"),
            mapped.get("controlar_estoque"), mapped.get("estoque_inicial"), mapped.get("estoque_minimo"), mapped.get("estoque_maximo"),
            mapped.get("controlar_lotes"), mapped.get("localizacao") or None, mapped.get("dias_preparacao"), mapped.get("marca") or None,
            mapped.get("descricao_complementar") or None, mapped.get("link_video") or None, mapped.get("slug") or None,
            mapped.get("keywords") or None, mapped.get("titulo_seo") or None, mapped.get("descricao_seo") or None, mapped.get("tags") or None,
            mapped.get("unidade_por_caixa"), mapped.get("linha_produto") or None, mapped.get("garantia") or None,
            mapped.get("gtin_tributavel") or None, mapped.get("valor_ipi_fixo"), mapped.get("codigo_enquadramento_legal_ipi") or None,
            mapped.get("codigo_fornecedor") or None, mapped.get("observacoes") or None, mapped.get("dimensoes_payload"),
            mapped.get("estoque_payload"), mapped.get("seo_payload"), mapped.get("atributos_payload"), mapped.get("anuncios_payload"),
            mapped.get("custos_payload"), mapped.get("fornecedores_payload"), mapped.get("imagens_payload"), mapped.get("tiny_raw_payload"),
        )
        try:
            with _db() as conn:
                with conn.cursor() as cur:
                    if existing:
                        cur.execute(
                            """
                            UPDATE erp.products
                            SET origin='tiny',
                                tiny_sync_status='synced',
                                tiny_sync_error=NULL,
                                tiny_synced_at=now(),
                                tiny_product_id=%s,
                                tipo_produto=%s,
                                nome=%s,
                                sku=%s,
                                gtin=%s,
                                origem=%s,
                                unidade=%s,
                                ncm=%s,
                                cest=%s,
                                preco_venda=%s,
                                preco_custo=%s,
                                peso_liquido=%s,
                                peso_bruto=%s,
                                numero_volumes=%s,
                                tipo_embalagem=%s,
                                embalagem=%s,
                                largura=%s,
                                altura=%s,
                                comprimento=%s,
                                controlar_estoque=%s,
                                estoque_inicial=%s,
                                estoque_minimo=%s,
                                estoque_maximo=%s,
                                controlar_lotes=%s,
                                localizacao=%s,
                                dias_preparacao=%s,
                                marca=%s,
                                descricao_complementar=%s,
                                link_video=%s,
                                slug=%s,
                                keywords=%s,
                                titulo_seo=%s,
                                descricao_seo=%s,
                                tags=%s,
                                unidade_por_caixa=%s,
                                linha_produto=%s,
                                garantia=%s,
                                gtin_tributavel=%s,
                                valor_ipi_fixo=%s,
                                codigo_enquadramento_legal_ipi=%s,
                                codigo_fornecedor=%s,
                                observacoes=%s,
                                dimensoes_payload=%s::jsonb,
                                estoque_payload=%s::jsonb,
                                seo_payload=%s::jsonb,
                                atributos_payload=%s::jsonb,
                                anuncios_payload=%s::jsonb,
                                custos_payload=%s::jsonb,
                                fornecedores_payload=%s::jsonb,
                                imagens_payload=%s::jsonb,
                                tiny_raw_payload=%s::jsonb,
                                updated_at=now()
                            WHERE company_key=%s AND id=%s
                            """,
                            (*values[1:], company_key, existing.get("id")),
                        )
                        updated_count += int(cur.rowcount or 0)
                    else:
                        cur.execute(
                            """
                            INSERT INTO erp.products (
                                company_key, origin, tiny_sync_status, tiny_sync_error, tiny_synced_at, tiny_product_id,
                                tipo_produto, nome, sku, gtin, origem, unidade, ncm, cest, preco_venda, preco_custo,
                                peso_liquido, peso_bruto, numero_volumes, tipo_embalagem, embalagem, largura, altura,
                                comprimento, controlar_estoque, estoque_inicial, estoque_minimo, estoque_maximo,
                                controlar_lotes, localizacao, dias_preparacao, marca, descricao_complementar,
                                link_video, slug, keywords, titulo_seo, descricao_seo, tags, unidade_por_caixa,
                                linha_produto, garantia, gtin_tributavel, valor_ipi_fixo, codigo_enquadramento_legal_ipi,
                                codigo_fornecedor, observacoes, dimensoes_payload, estoque_payload, seo_payload,
                                atributos_payload, anuncios_payload, custos_payload, fornecedores_payload, imagens_payload,
                                tiny_raw_payload, created_at, updated_at
                            ) VALUES (
                                %s, 'tiny', 'synced', NULL, now(), %s,
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                                %s::jsonb, now(), now()
                            )
                            """,
                            values,
                        )
                        created_count += int(cur.rowcount or 0)
        except Exception as exc:
            errors.append({"tiny_product_id": tiny_product_id, "sku": sku, "error": str(exc)[:500]})
            skipped_count += 1

    return {
        "ok": not errors,
        "company_key": company_key,
        "dry_run": bool(dry_run),
        "import_details": bool(import_details),
        "query": {"q": q_norm, "field": field_key, "situacao": situacao_norm, "limit": limit, "offset": offset},
        "paginacao": list_response.get("paginacao") or {"limit": limit, "offset": offset, "total": len(raw_items)},
        "fetched_count": len(raw_items),
        "created_count": created_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "conflicts": conflicts,
        "errors": errors,
        "sample": sample[:20],
    }


_PRODUCT_IMPORT_DB_FIELDS = [
    "tiny_product_id", "tipo_produto", "nome", "sku", "gtin", "origem", "unidade", "ncm", "cest",
    "preco_venda", "preco_custo", "peso_liquido", "peso_bruto", "numero_volumes", "tipo_embalagem",
    "embalagem", "largura", "altura", "comprimento", "controlar_estoque", "estoque_inicial",
    "estoque_minimo", "estoque_maximo", "controlar_lotes", "localizacao", "dias_preparacao",
    "marca", "descricao_complementar", "link_video", "slug", "keywords", "titulo_seo",
    "descricao_seo", "tags", "unidade_por_caixa", "linha_produto", "garantia", "gtin_tributavel",
    "valor_ipi_fixo", "codigo_enquadramento_legal_ipi", "codigo_fornecedor", "observacoes",
    "dimensoes_payload", "estoque_payload", "seo_payload", "atributos_payload", "anuncios_payload",
    "custos_payload", "fornecedores_payload", "imagens_payload", "tiny_raw_payload",
]
_PRODUCT_IMPORT_JSON_FIELDS = {
    "dimensoes_payload", "estoque_payload", "seo_payload", "atributos_payload", "anuncios_payload",
    "custos_payload", "fornecedores_payload", "imagens_payload", "tiny_raw_payload",
}


def _product_import_process_items(
    company_key: str,
    tiny: TinyV3Client,
    raw_items: List[Dict[str, Any]],
    dry_run: bool,
    import_details: bool,
) -> Dict[str, Any]:
    created_count = 0
    updated_count = 0
    skipped_count = 0
    conflicts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    sample: List[Dict[str, Any]] = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            skipped_count += 1
            continue
        list_product = raw_item.get("produto") if isinstance(raw_item.get("produto"), dict) else raw_item
        tiny_product_id = _clean_str(list_product.get("id") if isinstance(list_product, dict) else "")
        raw_product = list_product if isinstance(list_product, dict) else {}
        if import_details and tiny_product_id:
            try:
                raw_product = _product_import_payload(tiny.obter_produto(int(tiny_product_id)))
            except Exception as exc:
                errors.append({"tiny_product_id": tiny_product_id, "error": str(exc)[:500]})
                raw_product = list_product

        mapped = _product_import_map_tiny(raw_product)
        tiny_product_id = mapped.get("tiny_product_id") or tiny_product_id
        sku = _clean_str(mapped.get("sku"))
        if not tiny_product_id and not sku:
            skipped_count += 1
            errors.append({"tiny_product_id": "", "sku": "", "error": "Produto Tiny sem id e sem SKU."})
            continue
        if not _clean_str(mapped.get("nome")):
            mapped["nome"] = sku or f"Produto Tiny {tiny_product_id}"

        action = "create"
        existing = None
        sku_conflict = None
        with _db() as conn:
            with conn.cursor() as cur:
                if tiny_product_id:
                    cur.execute(
                        "SELECT id, origin, tiny_product_id, sku FROM erp.products WHERE company_key=%s AND tiny_product_id=%s LIMIT 1",
                        (company_key, tiny_product_id),
                    )
                    existing = cur.fetchone()
                if sku:
                    cur.execute(
                        """
                        SELECT id, origin, tiny_product_id, sku
                        FROM erp.products
                        WHERE company_key=%s AND sku=%s
                          AND (%s IS NULL OR COALESCE(tiny_product_id, '') <> %s)
                        LIMIT 1
                        """,
                        (company_key, sku, tiny_product_id or None, tiny_product_id or ""),
                    )
                    sku_conflict = cur.fetchone()

        if sku_conflict:
            conflict = dict(sku_conflict)
            conflicts.append({
                "reason": "sku_conflict",
                "sku": sku,
                "tiny_product_id": tiny_product_id,
                "local_product_id": conflict.get("id"),
                "local_origin": conflict.get("origin"),
                "local_tiny_product_id": conflict.get("tiny_product_id"),
            })
            skipped_count += 1
            action = "conflict"
        elif existing:
            action = "update"

        sample.append({
            "tiny_product_id": tiny_product_id,
            "sku": sku,
            "nome": mapped.get("nome"),
            "action": action,
            "dry_run": bool(dry_run),
            "details": bool(import_details),
            "variations_count": mapped.get("variations_count", 0),
        })
        if dry_run or action == "conflict":
            continue

        db_values = []
        for field in _PRODUCT_IMPORT_DB_FIELDS:
            value = tiny_product_id if field == "tiny_product_id" else mapped.get(field)
            if isinstance(value, str) and field not in _PRODUCT_IMPORT_JSON_FIELDS:
                value = value or None
            db_values.append(value)

        try:
            with _db() as conn:
                with conn.cursor() as cur:
                    if existing:
                        set_parts = [
                            f"{field}=%s::jsonb" if field in _PRODUCT_IMPORT_JSON_FIELDS else f"{field}=%s"
                            for field in _PRODUCT_IMPORT_DB_FIELDS
                        ]
                        cur.execute(
                            f"""
                            UPDATE erp.products
                            SET origin='tiny',
                                tiny_sync_status='synced',
                                tiny_sync_error=NULL,
                                tiny_synced_at=now(),
                                {', '.join(set_parts)},
                                updated_at=now()
                            WHERE company_key=%s AND id=%s
                            """,
                            (*db_values, company_key, existing.get("id")),
                        )
                        updated_count += int(cur.rowcount or 0)
                    else:
                        placeholders = [
                            "%s::jsonb" if field in _PRODUCT_IMPORT_JSON_FIELDS else "%s"
                            for field in _PRODUCT_IMPORT_DB_FIELDS
                        ]
                        cur.execute(
                            f"""
                            INSERT INTO erp.products (
                                company_key, origin, tiny_sync_status, tiny_sync_error, tiny_synced_at,
                                {', '.join(_PRODUCT_IMPORT_DB_FIELDS)},
                                created_at, updated_at
                            ) VALUES (
                                %s, 'tiny', 'synced', NULL, now(),
                                {', '.join(placeholders)},
                                now(), now()
                            )
                            """,
                            (company_key, *db_values),
                        )
                        created_count += int(cur.rowcount or 0)
        except Exception as exc:
            errors.append({"tiny_product_id": tiny_product_id, "sku": sku, "error": str(exc)[:500]})
            skipped_count += 1

    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "conflicts": conflicts,
        "errors": errors,
        "sample": sample,
    }


def _product_update_tiny_details(product_id: int, company_key: str, mapped: Dict[str, Any]) -> int:
    db_values = []
    for field in _PRODUCT_IMPORT_DB_FIELDS:
        value = mapped.get("tiny_product_id") if field == "tiny_product_id" else mapped.get(field)
        if isinstance(value, str) and field not in _PRODUCT_IMPORT_JSON_FIELDS:
            value = value or None
        db_values.append(value)
    set_parts = [
        f"{field}=%s::jsonb" if field in _PRODUCT_IMPORT_JSON_FIELDS else f"{field}=%s"
        for field in _PRODUCT_IMPORT_DB_FIELDS
    ]
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE erp.products
                SET tiny_sync_status='synced',
                    tiny_sync_error=NULL,
                    tiny_synced_at=now(),
                    {', '.join(set_parts)},
                    updated_at=now()
                WHERE company_key=%s AND id=%s AND COALESCE(tiny_product_id, '') <> ''
                """,
                (*db_values, company_key, int(product_id)),
            )
            return int(cur.rowcount or 0)


def _tiny_list_item_sku(raw_item: Dict[str, Any]) -> str:
    """SKU/código de um item da resposta de listar_produtos (achatado ou em 'produto')."""
    p = raw_item.get("produto") if isinstance(raw_item.get("produto"), dict) else raw_item
    if not isinstance(p, dict):
        return ""
    return _clean_str(p.get("sku") or p.get("codigo"))


def _tiny_auth_error(message: str) -> bool:
    """Heurística para erro de token/autorização do Tiny V3 (mensagem amigável)."""
    m = _clean_str(message).lower()
    return any(
        t in m
        for t in ("invalid_grant", "not active", "unauthorized", "invalid_token", "expired_token", "401", "reautor")
    )


_TINY_REAUTH_MESSAGE = (
    "Não foi possível consultar o Tiny V3 para esta empresa. Reautorize a conta Tiny V3 em "
    "Administração antes de importar SKUs faltantes."
)


@app.post("/api/admin/products/import-missing-skus-from-tiny")
@app.post("/admin/products/import-missing-skus-from-tiny")
async def admin_products_import_missing_skus_from_tiny(request: Request, company: str = ""):
    """Busca no Tiny V3 os SKUs não encontrados na conferência de estoque e importa
    o CADASTRO desses produtos para erp.products (reaproveita a mesma lógica de
    "Importar do Tiny"). NÃO altera estoque, NÃO cria movimento, NÃO escreve no Tiny.
    Admin-only."""
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    company = _clean_str(body.get("company")) or company
    company_key = _auth_company_or_default(user, company)
    import_details = True
    if body.get("import_details") is not None:
        import_details = bool(body.get("import_details"))

    raw_skus = body.get("skus") if isinstance(body.get("skus"), list) else []
    seen = set()
    skus: List[str] = []
    for s in raw_skus:
        cs = _clean_str(s)
        if not cs:
            continue
        low = cs.lower()
        if low in seen:
            continue
        seen.add(low)
        skus.append(cs)
    if not skus:
        raise HTTPException(status_code=400, detail="Informe ao menos um SKU para buscar no Tiny.")
    if len(skus) > 30:
        raise HTTPException(status_code=400, detail="Máximo de 30 SKUs por chamada. Reduza a seleção e tente novamente.")

    _ensure_products_local_first_table()

    # Token Tiny indisponível -> mensagem clara por empresa.
    try:
        tiny = _tiny_v3_for_company(company_key)
    except HTTPException as exc:
        raise HTTPException(status_code=502, detail=_TINY_REAUTH_MESSAGE) from exc

    items: List[Dict[str, Any]] = []
    imported_count = already_exists_count = not_found_count = multiple_candidates_count = 0
    errors: List[Dict[str, Any]] = []

    for sku in skus:
        # 1) Já existe na base local? (não reimporta nem mexe em estoque)
        with _db() as conn:
            with conn.cursor() as cur:
                existing_local = _product_resolve_by_sku(cur, company_key, sku)
        if existing_local:
            ex = existing_local[0]
            already_exists_count += 1
            items.append({
                "sku": sku,
                "status": "already_exists",
                "product_id": ex.get("id"),
                "tiny_product_id": ex.get("tiny_product_id"),
                "name": ex.get("nome"),
            })
            continue

        # 2) Consultar Tiny V3 por código/SKU (somente leitura).
        try:
            list_response = _product_import_payload(tiny.listar_produtos({"codigo": sku, "limit": 50}))
        except TinyAPIError as exc:
            if _tiny_auth_error(str(exc)):
                raise HTTPException(status_code=502, detail=_TINY_REAUTH_MESSAGE) from exc
            errors.append({"sku": sku, "error": str(exc)[:500]})
            items.append({"sku": sku, "status": "error", "message": str(exc)[:300]})
            continue

        raw_list = list_response.get("itens") or list_response.get("produtos") or []
        if not isinstance(raw_list, list):
            raw_list = []
        # Match EXATO de SKU (case-insensitive). Não escolher silenciosamente.
        exact = [it for it in raw_list if isinstance(it, dict) and _tiny_list_item_sku(it).lower() == sku.lower()]

        if len(exact) == 0:
            not_found_count += 1
            items.append({"sku": sku, "status": "not_found_in_tiny", "message": "SKU não encontrado no Tiny."})
            continue
        if len(exact) > 1:
            multiple_candidates_count += 1
            items.append({
                "sku": sku,
                "status": "multiple_candidates",
                "message": "Tiny retornou múltiplos produtos para este SKU; resolver manualmente.",
                "candidates": [
                    {
                        "tiny_product_id": _clean_str((it.get("produto") if isinstance(it.get("produto"), dict) else it).get("id")),
                        "name": _clean_str(
                            (it.get("produto") if isinstance(it.get("produto"), dict) else it).get("descricao")
                            or (it.get("produto") if isinstance(it.get("produto"), dict) else it).get("nome")
                        ),
                    }
                    for it in exact
                ],
            })
            continue

        # 3) Exatamente 1 candidato: importa o CADASTRO reaproveitando a lógica existente.
        #    dry_run=False grava em erp.products; NÃO toca estoque nem cria movimento.
        result = _product_import_process_items(company_key, tiny, exact, dry_run=False, import_details=import_details)
        if result.get("errors"):
            errors.extend([{"sku": sku, **e} for e in result["errors"]])
        if result.get("conflicts"):
            multiple_candidates_count += 1
            items.append({
                "sku": sku,
                "status": "multiple_candidates",
                "message": "Conflito de SKU na base local; resolver manualmente.",
            })
            continue
        if (result.get("created_count") or 0) + (result.get("updated_count") or 0) <= 0:
            items.append({"sku": sku, "status": "error", "message": "Falha ao importar cadastro do Tiny."})
            if not result.get("errors"):
                errors.append({"sku": sku, "error": "Falha ao importar cadastro do Tiny."})
            continue

        with _db() as conn:
            with conn.cursor() as cur:
                created = _product_resolve_by_sku(cur, company_key, sku)
        prod = created[0] if created else {}
        imported_count += 1
        items.append({
            "sku": sku,
            "status": "imported",
            "product_id": prod.get("id"),
            "tiny_product_id": prod.get("tiny_product_id"),
            "name": prod.get("nome"),
        })

    return {
        "ok": not errors,
        "company_key": company_key,
        "requested_count": len(skus),
        "imported_count": imported_count,
        "already_exists_count": already_exists_count,
        "not_found_count": not_found_count,
        "multiple_candidates_count": multiple_candidates_count,
        "items": items,
        "errors": errors,
    }


@app.post("/api/admin/products/import-tiny-all")
@app.post("/admin/products/import-tiny-all")
async def admin_products_import_tiny_all(
    request: Request,
    company: str = "parton",
    q: str = "",
    field: str = "nome",
    situacao: str = "A",
    limit: int = Query(default=50, ge=1, le=100),
    offset_start: int = Query(default=0, ge=0),
    max_pages: int = Query(default=20, ge=1, le=100),
    dry_run: bool = True,
    import_details: bool = True,
    sleep_ms: int = Query(default=300, ge=0, le=5000),
):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        company = _clean_str(body.get("company")) or company
        q = _clean_str(body.get("q")) or q
        field = _clean_str(body.get("field")) or field
        situacao = _clean_str(body.get("situacao")) or situacao
        limit = int(_safe_int(body.get("limit"), limit) or limit)
        offset_start = int(_safe_int(body.get("offset_start"), offset_start) or offset_start)
        max_pages = int(_safe_int(body.get("max_pages"), max_pages) or max_pages)
        sleep_ms = int(_safe_int(body.get("sleep_ms"), sleep_ms) or sleep_ms)
        if body.get("dry_run") is not None:
            dry_run = bool(body.get("dry_run"))
        if body.get("import_details") is not None:
            import_details = bool(body.get("import_details"))

    company_norm = _clean_str(company).lower()
    if company_norm == "all":
        company_keys = ["parton", "park"]
    else:
        company_keys = [_auth_company_or_default(user, company)]

    limit = min(100, max(1, int(limit or 50)))
    offset_start = max(0, int(offset_start or 0))
    max_pages = min(100, max(1, int(max_pages or 20)))
    sleep_ms = min(5000, max(0, int(sleep_ms or 0)))
    field_key = _clean_str(field).lower()
    if field_key == "sku":
        field_key = "codigo"
    if field_key not in {"nome", "codigo", "gtin"}:
        raise HTTPException(status_code=400, detail="Campo de busca inválido. Use nome, codigo, sku ou gtin.")
    situacao_norm = _clean_str(situacao).upper()
    if situacao_norm and situacao_norm not in {"A", "I", "E"}:
        raise HTTPException(status_code=400, detail="Situação inválida. Use A, I ou E.")

    _ensure_products_local_first_table()
    summaries: List[Dict[str, Any]] = []
    total_created = 0
    total_updated = 0
    total_skipped = 0
    total_fetched = 0
    all_conflicts: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []

    for company_key in company_keys:
        tiny = _tiny_v3_for_company(company_key)
        offset = offset_start
        pages_processed = 0
        expected_total = None
        stopped_reason = "max_pages"
        company_sample: List[Dict[str, Any]] = []
        company_created = 0
        company_updated = 0
        company_skipped = 0
        company_fetched = 0
        company_conflicts: List[Dict[str, Any]] = []
        company_errors: List[Dict[str, Any]] = []

        for page_idx in range(max_pages):
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            q_norm = _clean_str(q)
            if q_norm:
                params[field_key] = q_norm
            if situacao_norm:
                params["situacao"] = situacao_norm

            try:
                list_response = _product_import_payload(tiny.listar_produtos(params))
            except TinyAPIError as exc:
                company_errors.append({"company_key": company_key, "offset": offset, "error": str(exc)[:500]})
                stopped_reason = "tiny_error"
                break
            raw_items = list_response.get("itens") or list_response.get("produtos") or []
            if not isinstance(raw_items, list):
                raw_items = []
            paginacao = list_response.get("paginacao") if isinstance(list_response.get("paginacao"), dict) else {}
            expected_total = _safe_int(paginacao.get("total"), expected_total)

            if not raw_items:
                stopped_reason = "empty_page"
                break

            page_result = _product_import_process_items(company_key, tiny, raw_items, dry_run, import_details)
            pages_processed += 1
            company_fetched += len(raw_items)
            company_created += int(page_result.get("created_count") or 0)
            company_updated += int(page_result.get("updated_count") or 0)
            company_skipped += int(page_result.get("skipped_count") or 0)
            company_conflicts.extend(page_result.get("conflicts") or [])
            company_errors.extend(page_result.get("errors") or [])
            if len(company_sample) < 20:
                company_sample.extend((page_result.get("sample") or [])[: 20 - len(company_sample)])

            offset += limit
            if expected_total is not None and offset >= int(expected_total):
                stopped_reason = "total_reached"
                break
            if len(raw_items) < limit:
                stopped_reason = "short_page"
                break
            if sleep_ms and page_idx < max_pages - 1:
                time.sleep(sleep_ms / 1000.0)

        next_offset = offset
        summary = {
            "company_key": company_key,
            "pages_processed": pages_processed,
            "fetched_count": company_fetched,
            "created_count": company_created,
            "updated_count": company_updated,
            "skipped_count": company_skipped,
            "conflicts": company_conflicts,
            "errors": company_errors,
            "offset_start": offset_start,
            "next_offset": next_offset,
            "expected_total": expected_total,
            "stopped_reason": stopped_reason,
            "sample": company_sample,
        }
        summaries.append(summary)
        total_created += company_created
        total_updated += company_updated
        total_skipped += company_skipped
        total_fetched += company_fetched
        all_conflicts.extend(company_conflicts)
        all_errors.extend(company_errors)

    return {
        "ok": not all_errors,
        "dry_run": bool(dry_run),
        "import_details": bool(import_details),
        "query": {
            "company": company_norm or company,
            "q": _clean_str(q),
            "field": field_key,
            "situacao": situacao_norm,
            "limit": limit,
            "offset_start": offset_start,
            "max_pages": max_pages,
            "sleep_ms": sleep_ms,
        },
        "companies": summaries,
        "pages_processed": sum(int(item.get("pages_processed") or 0) for item in summaries),
        "fetched_count": total_fetched,
        "created_count": total_created,
        "updated_count": total_updated,
        "skipped_count": total_skipped,
        "conflicts": all_conflicts,
        "errors": all_errors,
    }


@app.post("/api/admin/products/refresh-tiny-details")
@app.post("/admin/products/refresh-tiny-details")
async def admin_products_refresh_tiny_details(
    request: Request,
    company: str = "parton",
    limit: int = Query(default=10, ge=1, le=30),
    offset: int = Query(default=0, ge=0),
    after_id: Optional[int] = None,
    sleep_ms: int = Query(default=2000, ge=0, le=10000),
    dry_run: bool = True,
    only_missing: bool = True,
    retry_429: bool = True,
    retry_after_ms: int = Query(default=5000, ge=0, le=60000),
    max_retries: int = Query(default=1, ge=0, le=3),
):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        company = _clean_str(body.get("company")) or company
        limit = int(_safe_int(body.get("limit"), limit) or limit)
        offset = int(_safe_int(body.get("offset"), offset) or offset)
        after_id = _safe_int(body.get("after_id"), after_id)
        sleep_ms = int(_safe_int(body.get("sleep_ms"), sleep_ms) or sleep_ms)
        retry_after_ms = int(_safe_int(body.get("retry_after_ms"), retry_after_ms) or retry_after_ms)
        max_retries = int(_safe_int(body.get("max_retries"), max_retries) or max_retries)
        if body.get("dry_run") is not None:
            dry_run = _park_wrong_tiny_bool(body.get("dry_run"), dry_run)
        if body.get("only_missing") is not None:
            only_missing = _park_wrong_tiny_bool(body.get("only_missing"), only_missing)
        if body.get("retry_429") is not None:
            retry_429 = _park_wrong_tiny_bool(body.get("retry_429"), retry_429)

    return _products_refresh_tiny_details_batch(
        user,
        company=company,
        limit=limit,
        offset=offset,
        after_id=after_id,
        sleep_ms=sleep_ms,
        dry_run=dry_run,
        only_missing=only_missing,
        retry_429=retry_429,
        retry_after_ms=retry_after_ms,
        max_retries=max_retries,
    )


# Critério único de "detalhes Tiny pendentes": produto cujo tiny_raw_payload ainda
# não contém os blocos típicos de detalhe do Tiny. É exatamente o mesmo critério
# aplicado em only_missing=true no refresh-tiny-details. Centralizado aqui para que
# o endpoint de stats e o batch de atualização nunca divirjam.
_PRODUCTS_DETAILS_MISSING_SQL = (
    "("
    " tiny_raw_payload IS NULL OR"
    " tiny_raw_payload = '{}'::jsonb OR"
    " NOT (tiny_raw_payload ?| ARRAY['dimensoes','tributacao','fornecedores','seo','anexos','variacoes','kit','producao'])"
    ")"
)


def _products_refresh_tiny_details_batch(
    user: Dict[str, Any],
    *,
    company: str = "parton",
    limit: int = 10,
    offset: int = 0,
    after_id: Optional[int] = None,
    sleep_ms: int = 2000,
    dry_run: bool = True,
    only_missing: bool = True,
    retry_429: bool = True,
    retry_after_ms: int = 5000,
    max_retries: int = 1,
) -> Dict[str, Any]:
    company_norm = _clean_str(company).lower()
    if company_norm == "all":
        company_keys = ["parton", "park"]
    else:
        company_keys = [_auth_company_or_default(user, company)]

    limit = min(30, max(1, int(limit or 10)))
    offset = max(0, int(offset or 0))
    sleep_ms = min(10000, max(0, int(sleep_ms or 0)))
    retry_after_ms = min(60000, max(0, int(retry_after_ms or 0)))
    max_retries = min(3, max(0, int(max_retries or 0)))

    _ensure_products_local_first_table()
    summaries: List[Dict[str, Any]] = []
    total_processed = 0
    total_updated = 0
    total_skipped = 0
    all_errors: List[Dict[str, Any]] = []
    all_sample: List[Dict[str, Any]] = []
    critical_error = False

    for company_key in company_keys:
        where = ["company_key=%s", "COALESCE(tiny_product_id, '') <> ''"]
        params: List[Any] = [company_key]
        if after_id is not None:
            where.append("id > %s")
            params.append(int(after_id))
        if only_missing:
            where.append(_PRODUCTS_DETAILS_MISSING_SQL)
        where_sql = " AND ".join(where)
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, company_key, tiny_product_id, sku, nome, origin, tiny_sync_status
                    FROM erp.products
                    WHERE {where_sql}
                    ORDER BY id
                    LIMIT %s OFFSET %s
                    """,
                    [*params, limit, 0 if after_id is not None else offset],
                )
                products = [dict(row) for row in cur.fetchall()]

        tiny = _tiny_v3_for_company(company_key)
        processed_count = 0
        updated_count = 0
        skipped_count = 0
        errors: List[Dict[str, Any]] = []
        sample: List[Dict[str, Any]] = []
        last_id = after_id or 0
        stopped_reason = "limit_reached"

        for idx, product in enumerate(products):
            product_id = int(product.get("id"))
            last_id = product_id
            tiny_product_id = _clean_str(product.get("tiny_product_id"))
            attempts = 0
            detail_payload: Optional[Dict[str, Any]] = None
            detail_error = ""
            while attempts <= max_retries:
                attempts += 1
                try:
                    detail_payload = _product_import_payload(tiny.obter_produto(int(tiny_product_id)))
                    detail_error = ""
                    break
                except Exception as exc:
                    detail_error = str(exc)[:500]
                    low = detail_error.lower()
                    if (
                        "401" in low
                        or "403" in low
                        or "unauthorized" in low
                        or "forbidden" in low
                        or "invalid_grant" in low
                        or "invalid token" in low
                    ) and not ("429" in low):
                        critical_error = True
                        stopped_reason = "auth_error"
                        break
                    if retry_429 and "429" in low and attempts <= max_retries:
                        if retry_after_ms:
                            time.sleep(retry_after_ms / 1000.0)
                        continue
                    break
            if critical_error:
                errors.append({"id": product_id, "tiny_product_id": tiny_product_id, "error": detail_error, "critical": True})
                break
            if detail_payload is None:
                skipped_count += 1
                errors.append({"id": product_id, "tiny_product_id": tiny_product_id, "error": detail_error, "attempts": attempts})
                continue

            mapped = _product_import_map_tiny(detail_payload)
            if not mapped.get("tiny_product_id"):
                mapped["tiny_product_id"] = tiny_product_id
            processed_count += 1
            sample_item = {
                "id": product_id,
                "tiny_product_id": tiny_product_id,
                "sku": product.get("sku"),
                "nome": mapped.get("nome") or product.get("nome"),
                "dry_run": bool(dry_run),
                "attempts": attempts,
            }
            if dry_run:
                sample_item["action"] = "would_update"
            else:
                try:
                    rowcount = _product_update_tiny_details(product_id, company_key, mapped)
                    updated_count += rowcount
                    sample_item["action"] = "updated" if rowcount else "not_found"
                except Exception as exc:
                    skipped_count += 1
                    sample_item["action"] = "error"
                    errors.append({"id": product_id, "tiny_product_id": tiny_product_id, "error": str(exc)[:500]})
            sample.append(sample_item)
            if sleep_ms and idx < len(products) - 1:
                time.sleep(sleep_ms / 1000.0)

        if critical_error:
            stopped_reason = "auth_error"
        elif not products:
            stopped_reason = "empty_selection"
        elif len(products) < limit:
            stopped_reason = "short_batch"

        summary = {
            "company_key": company_key,
            "processed_count": processed_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "errors": errors,
            "next_offset": offset + len(products) if after_id is None else None,
            "next_after_id": last_id or None,
            "sample": sample,
            "stopped_reason": stopped_reason,
        }
        summaries.append(summary)
        total_processed += processed_count
        total_updated += updated_count
        total_skipped += skipped_count
        all_errors.extend(errors)
        if len(all_sample) < 20:
            all_sample.extend(sample[: 20 - len(all_sample)])
        if critical_error:
            break

    return {
        "ok": not all_errors,
        "dry_run": bool(dry_run),
        "only_missing": bool(only_missing),
        "retry_429": bool(retry_429),
        "query": {
            "company": company_norm or company,
            "limit": limit,
            "offset": offset,
            "after_id": after_id,
            "sleep_ms": sleep_ms,
            "retry_after_ms": retry_after_ms,
            "max_retries": max_retries,
        },
        "companies": summaries,
        "processed_count": total_processed,
        "updated_count": total_updated,
        "skipped_count": total_skipped,
        "errors": all_errors,
        "sample": all_sample,
        "stopped_reason": "auth_error" if critical_error else "completed",
    }


def _products_auto_error_has_429(errors: List[Dict[str, Any]]) -> bool:
    for error in errors or []:
        if "429" in _clean_str(error.get("error")).lower():
            return True
    return False


@app.post("/api/admin/products/refresh-tiny-details-auto")
@app.post("/admin/products/refresh-tiny-details-auto")
async def admin_products_refresh_tiny_details_auto(
    request: Request,
    company: str = "parton",
    dry_run: bool = True,
    only_missing: bool = True,
    limit: int = Query(default=10, ge=1, le=30),
    sleep_ms: int = Query(default=3000, ge=0, le=10000),
    retry_429: bool = True,
    retry_after_ms: int = Query(default=5000, ge=0, le=60000),
    max_retries: int = Query(default=1, ge=0, le=3),
    start_after_id: Optional[int] = None,
    max_cycles: int = Query(default=10, ge=1, le=100),
    max_products: Optional[int] = None,
    stop_on_error: bool = False,
    stop_on_429: bool = False,
    company_delay_ms: int = Query(default=3000, ge=0, le=30000),
):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        company = _clean_str(body.get("company")) or company
        limit = int(_safe_int(body.get("limit"), limit) or limit)
        sleep_ms = int(_safe_int(body.get("sleep_ms"), sleep_ms) or sleep_ms)
        retry_after_ms = int(_safe_int(body.get("retry_after_ms"), retry_after_ms) or retry_after_ms)
        max_retries = int(_safe_int(body.get("max_retries"), max_retries) or max_retries)
        start_after_id = _safe_int(body.get("start_after_id"), start_after_id)
        max_cycles = int(_safe_int(body.get("max_cycles"), max_cycles) or max_cycles)
        max_products = _safe_int(body.get("max_products"), max_products)
        company_delay_ms = int(_safe_int(body.get("company_delay_ms"), company_delay_ms) or company_delay_ms)
        if body.get("dry_run") is not None:
            dry_run = _park_wrong_tiny_bool(body.get("dry_run"), dry_run)
        if body.get("only_missing") is not None:
            only_missing = _park_wrong_tiny_bool(body.get("only_missing"), only_missing)
        if body.get("retry_429") is not None:
            retry_429 = _park_wrong_tiny_bool(body.get("retry_429"), retry_429)
        if body.get("stop_on_error") is not None:
            stop_on_error = _park_wrong_tiny_bool(body.get("stop_on_error"), stop_on_error)
        if body.get("stop_on_429") is not None:
            stop_on_429 = _park_wrong_tiny_bool(body.get("stop_on_429"), stop_on_429)

    company_norm = _clean_str(company).lower()
    if company_norm == "all":
        company_keys = ["parton", "park"]
    elif company_norm in {"parton", "park"}:
        company_keys = [_auth_company_or_default(user, company_norm)]
    else:
        raise HTTPException(status_code=400, detail="company deve ser parton, park ou all.")

    limit = min(30, max(1, int(limit or 10)))
    sleep_ms = min(10000, max(0, int(sleep_ms or 0)))
    retry_after_ms = min(60000, max(0, int(retry_after_ms or 0)))
    max_retries = min(3, max(0, int(max_retries or 0)))
    max_cycles = min(100, max(1, int(max_cycles or 10)))
    company_delay_ms = min(30000, max(0, int(company_delay_ms or 0)))
    if max_products is not None:
        max_products = max(1, int(max_products))

    started_at_dt = _now()
    started = time.time()
    first_after_id = start_after_id
    current_after_by_company: Dict[str, Optional[int]] = {key: start_after_id for key in company_keys}
    summaries: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    all_samples: List[Dict[str, Any]] = []
    total_cycles = 0
    total_processed = 0
    total_updated = 0
    total_skipped = 0
    stopped_reason = "completed"

    for company_idx, company_key in enumerate(company_keys):
        company_summary = {
            "company_key": company_key,
            "cycles_processed": 0,
            "processed_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "errors_count": 0,
            "errors": [],
            "first_after_id": current_after_by_company.get(company_key),
            "last_after_id": current_after_by_company.get(company_key),
            "next_after_id": current_after_by_company.get(company_key),
            "stopped_reason": "not_started",
            "samples": [],
        }
        company_stop = "completed"

        for _cycle in range(max_cycles):
            if max_products is not None and total_processed >= max_products:
                company_stop = "max_products_reached"
                break

            remaining = None if max_products is None else max_products - total_processed
            effective_limit = limit if remaining is None else min(limit, max(1, remaining))
            current_after_id = current_after_by_company.get(company_key)
            batch = _products_refresh_tiny_details_batch(
                user,
                company=company_key,
                limit=effective_limit,
                offset=0,
                after_id=current_after_id,
                sleep_ms=sleep_ms,
                dry_run=dry_run,
                only_missing=only_missing,
                retry_429=retry_429,
                retry_after_ms=retry_after_ms,
                max_retries=max_retries,
            )

            total_cycles += 1
            company_summary["cycles_processed"] += 1
            batch_processed = int(batch.get("processed_count") or 0)
            batch_updated = int(batch.get("updated_count") or 0)
            batch_skipped = int(batch.get("skipped_count") or 0)
            total_processed += batch_processed
            total_updated += batch_updated
            total_skipped += batch_skipped
            company_summary["processed_count"] += batch_processed
            company_summary["updated_count"] += batch_updated
            company_summary["skipped_count"] += batch_skipped

            batch_errors = list(batch.get("errors") or [])
            company_summary["errors"].extend(batch_errors)
            all_errors.extend(batch_errors)
            batch_sample = list(batch.get("sample") or [])
            if len(company_summary["samples"]) < 20:
                company_summary["samples"].extend(batch_sample[: 20 - len(company_summary["samples"])])
            if len(all_samples) < 30:
                all_samples.extend(batch_sample[: 30 - len(all_samples)])

            next_after_id = batch.get("companies", [{}])[0].get("next_after_id") if batch.get("companies") else None
            batch_stopped = batch.get("stopped_reason") or "completed"
            company_summary["last_after_id"] = current_after_id
            company_summary["next_after_id"] = next_after_id
            current_after_by_company[company_key] = next_after_id

            has_429 = _products_auto_error_has_429(batch_errors)
            if batch_stopped == "auth_error":
                company_stop = "auth_error"
                break
            if has_429 and stop_on_429:
                company_stop = "rate_limited"
                break
            if batch_errors and stop_on_error:
                company_stop = "error"
                break
            if batch_processed == 0 and batch_stopped in {"completed", "empty_selection"}:
                company_stop = "empty_selection"
                break
            if not next_after_id:
                company_stop = batch_stopped or "completed"
                break
            if batch_stopped in {"empty_selection", "short_batch"}:
                company_stop = batch_stopped
                break

        else:
            company_stop = "max_cycles_reached"

        company_summary["errors_count"] = len(company_summary["errors"])
        company_summary["stopped_reason"] = company_stop
        summaries.append(company_summary)

        if company_stop in {"auth_error", "rate_limited"} or (company_stop == "error" and stop_on_error):
            stopped_reason = company_stop
            break
        if max_products is not None and total_processed >= max_products:
            stopped_reason = "max_products_reached"
            break
        if company_delay_ms and company_idx < len(company_keys) - 1:
            time.sleep(company_delay_ms / 1000.0)

    if stopped_reason == "completed":
        if total_cycles >= max_cycles * len(summaries) and any(s.get("stopped_reason") == "max_cycles_reached" for s in summaries):
            stopped_reason = "max_cycles_reached"
        elif max_products is not None and total_processed >= max_products:
            stopped_reason = "max_products_reached"
        elif all(s.get("stopped_reason") in {"empty_selection", "short_batch", "completed"} for s in summaries):
            stopped_reason = "completed"

    finished_at_dt = _now()
    return {
        "ok": stopped_reason not in {"auth_error", "rate_limited", "error"},
        "dry_run": bool(dry_run),
        "only_missing": bool(only_missing),
        "companies": summaries,
        "company_key": company_norm,
        "cycles_processed": total_cycles,
        "processed_count": total_processed,
        "updated_count": total_updated,
        "skipped_count": total_skipped,
        "errors_count": len(all_errors),
        "errors": all_errors,
        "first_after_id": first_after_id,
        "last_after_id": summaries[-1].get("last_after_id") if summaries else first_after_id,
        "next_after_id": summaries[-1].get("next_after_id") if summaries else first_after_id,
        "stopped_reason": stopped_reason,
        "samples": all_samples,
        "started_at": started_at_dt.isoformat(),
        "finished_at": finished_at_dt.isoformat(),
        "duration_seconds": round(time.time() - started, 3),
        "query": {
            "company": company_norm,
            "limit": limit,
            "sleep_ms": sleep_ms,
            "retry_429": bool(retry_429),
            "retry_after_ms": retry_after_ms,
            "max_retries": max_retries,
            "start_after_id": start_after_id,
            "max_cycles": max_cycles,
            "max_products": max_products,
            "stop_on_error": bool(stop_on_error),
            "stop_on_429": bool(stop_on_429),
            "company_delay_ms": company_delay_ms,
        },
    }


@app.get("/api/admin/products/{product_id:int}")
@app.get("/admin/products/{product_id:int}")
def admin_products_local_get(request: Request, product_id: int, company: str = "parton"):
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_products_local_first_table()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM erp.products WHERE id=%s AND company_key=%s LIMIT 1",
                (product_id, company_key),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    return {"ok": True, "product": dict(row)}


# ===========================================================================
# Controle de Estoque Local — Fase 1 (movimentações manuais em histórico)
# Apenas saldos locais em erp.products (stock_physical/reserved/available).
# NÃO escreve no Tiny/Olist. NÃO integra com orçamento/pedido/separação.
# ===========================================================================

_PRODUCT_STOCK_MOVEMENT_TYPES = {
    "manual_entry",
    "manual_exit",
    "manual_adjustment",
    "reserve",
    "release_reserve",
    "set_initial",
}


def _ensure_product_stock_movements_table():
    _ensure_products_local_first_table()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.product_stock_movements (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL,
                  product_id BIGINT NOT NULL,
                  tiny_product_id TEXT NULL,
                  sku TEXT NULL,
                  movement_type TEXT NOT NULL,
                  quantity NUMERIC NOT NULL,
                  previous_physical NUMERIC NULL,
                  previous_reserved NUMERIC NULL,
                  previous_available NUMERIC NULL,
                  new_physical NUMERIC NULL,
                  new_reserved NUMERIC NULL,
                  new_available NUMERIC NULL,
                  reason TEXT NULL,
                  notes TEXT NULL,
                  reference_type TEXT NULL,
                  reference_id TEXT NULL,
                  created_by TEXT NULL,
                  created_at TIMESTAMPTZ DEFAULT now(),
                  raw_payload JSONB DEFAULT '{}'::jsonb
                )
                """
            )
            # Fase 2 — estorno auditável: colunas idempotentes (não destrutivas).
            for column_def in (
                "reversed_at TIMESTAMPTZ NULL",
                "reversed_by TEXT NULL",
                "reversal_reason TEXT NULL",
                "reversal_movement_id BIGINT NULL",
                "is_reversal BOOLEAN NOT NULL DEFAULT false",
                "reverses_movement_id BIGINT NULL",
            ):
                cur.execute(f"ALTER TABLE erp.product_stock_movements ADD COLUMN IF NOT EXISTS {column_def}")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_movements_company_product_created_idx
                ON erp.product_stock_movements (company_key, product_id, created_at DESC)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_movements_company_created_idx
                ON erp.product_stock_movements (company_key, created_at DESC)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_movements_product_created_idx
                ON erp.product_stock_movements (product_id, created_at DESC)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_movements_company_product_reversed_idx
                ON erp.product_stock_movements (company_key, product_id, reversed_at)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_movements_reverses_idx
                ON erp.product_stock_movements (reverses_movement_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS product_stock_movements_reversal_idx
                ON erp.product_stock_movements (reversal_movement_id)
                """
            )


def _product_stock_number(value: Any) -> float:
    """Converte saldo para float, tratando NULL/inválido como 0."""
    parsed = _safe_float(value, None)
    return float(parsed) if parsed is not None else 0.0


def _product_get_for_stock(cur, company_key: str, product_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, company_key, tiny_product_id, sku, nome, origin,
               stock_physical, stock_reserved, stock_available,
               stock_synced_at, stock_sync_error
        FROM erp.products
        WHERE id=%s AND company_key=%s
        LIMIT 1
        """,
        (int(product_id), company_key),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _product_calculate_stock_movement(
    movement_type: str,
    quantity: Any,
    new_stock_physical: Any,
    prev_physical: float,
    prev_reserved: float,
) -> Dict[str, float]:
    """Calcula novos saldos e a quantidade a registrar. Levanta HTTPException(400)
    com mensagem amigável em qualquer violação de regra. Não toca no banco.

    Convenção de `quantity` registrada no histórico:
      - manual_entry/manual_exit/reserve/release_reserve: valor positivo informado;
      - manual_adjustment/set_initial: diferença assinada (new_physical - previous_physical),
        podendo ser negativa apenas nesses dois tipos.
    """
    new_reserved = prev_reserved
    new_physical = prev_physical

    if movement_type in ("manual_entry", "manual_exit", "reserve", "release_reserve"):
        qty = _product_stock_number(quantity)
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Quantidade deve ser maior que zero.")
        recorded_qty = qty
        if movement_type == "manual_entry":
            new_physical = prev_physical + qty
        elif movement_type == "manual_exit":
            new_physical = prev_physical - qty
            if new_physical < 0:
                raise HTTPException(status_code=400, detail="Saída maior que o estoque físico disponível.")
            if new_physical < new_reserved:
                raise HTTPException(status_code=400, detail="Estoque físico ficaria menor que o reservado.")
        elif movement_type == "reserve":
            new_reserved = prev_reserved + qty
            if new_reserved > new_physical:
                raise HTTPException(status_code=400, detail="Reserva maior que o estoque físico disponível.")
        elif movement_type == "release_reserve":
            if qty > prev_reserved:
                raise HTTPException(status_code=400, detail="Liberação maior que o total reservado.")
            new_reserved = prev_reserved - qty
    elif movement_type in ("manual_adjustment", "set_initial"):
        if new_stock_physical is None or _clean_str(new_stock_physical) == "":
            raise HTTPException(status_code=400, detail="Informe o novo estoque físico.")
        target = _product_stock_number(new_stock_physical)
        if target < 0:
            raise HTTPException(status_code=400, detail="Estoque físico não pode ser negativo.")
        if target < new_reserved:
            raise HTTPException(status_code=400, detail="Estoque físico ficaria menor que o reservado.")
        new_physical = target
        recorded_qty = new_physical - prev_physical
    else:
        raise HTTPException(status_code=400, detail="Tipo de movimento inválido.")

    new_available = new_physical - new_reserved

    # Guardas finais de segurança (defesa em profundidade).
    if new_physical < 0 or new_reserved < 0 or new_available < 0 or new_reserved > new_physical:
        raise HTTPException(status_code=400, detail="Movimento resultaria em saldo inválido.")

    return {
        "quantity": recorded_qty,
        "new_physical": new_physical,
        "new_reserved": new_reserved,
        "new_available": new_available,
    }


def _product_insert_stock_movement(
    cur,
    *,
    company_key: str,
    product: Dict[str, Any],
    movement_type: str,
    calc: Dict[str, float],
    prev_physical: float,
    prev_reserved: float,
    prev_available: float,
    reason: str,
    notes: str,
    created_by: str,
    raw_payload: Dict[str, Any],
    is_reversal: bool = False,
    reverses_movement_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[str] = None,
) -> Dict[str, Any]:
    cur.execute(
        """
        INSERT INTO erp.product_stock_movements (
            company_key, product_id, tiny_product_id, sku, movement_type, quantity,
            previous_physical, previous_reserved, previous_available,
            new_physical, new_reserved, new_available,
            reason, notes, reference_type, reference_id, created_by, raw_payload,
            is_reversal, reverses_movement_id
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s::jsonb,
            %s, %s
        ) RETURNING *
        """,
        (
            company_key,
            int(product.get("id")),
            _clean_str(product.get("tiny_product_id")) or None,
            _clean_str(product.get("sku")) or None,
            movement_type,
            calc["quantity"],
            prev_physical,
            prev_reserved,
            prev_available,
            calc["new_physical"],
            calc["new_reserved"],
            calc["new_available"],
            _clean_str(reason) or None,
            _clean_str(notes) or None,
            _clean_str(reference_type) or None,
            _clean_str(reference_id) or None,
            created_by or None,
            _product_import_json(raw_payload),
            bool(is_reversal),
            int(reverses_movement_id) if reverses_movement_id is not None else None,
        ),
    )
    return dict(cur.fetchone())


def _product_stock_public(product: Dict[str, Any]) -> Dict[str, Any]:
    physical = _product_stock_number(product.get("stock_physical"))
    reserved = _product_stock_number(product.get("stock_reserved"))
    stored_available = product.get("stock_available")
    available = _product_stock_number(stored_available) if stored_available is not None else physical - reserved
    return {
        "stock_physical": physical,
        "stock_reserved": reserved,
        "stock_available": available,
        "stock_synced_at": product.get("stock_synced_at"),
        "stock_sync_error": product.get("stock_sync_error"),
    }


@app.get("/api/admin/products/{product_id:int}/stock")
@app.get("/admin/products/{product_id:int}/stock")
def admin_product_stock_get(request: Request, product_id: int, company: str = ""):
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_product_stock_movements_table()
    with _db() as conn:
        with conn.cursor() as cur:
            product = _product_get_for_stock(cur, company_key, product_id)
            if not product:
                raise HTTPException(status_code=404, detail="Produto não encontrado nesta empresa.")
            cur.execute(
                """
                SELECT * FROM erp.product_stock_movements
                WHERE company_key=%s AND product_id=%s
                ORDER BY created_at DESC, id DESC
                LIMIT 20
                """,
                (company_key, int(product_id)),
            )
            movements = [dict(r) for r in cur.fetchall()]
    return {
        "ok": True,
        "company_key": company_key,
        "product": {
            "id": product.get("id"),
            "nome": product.get("nome"),
            "sku": product.get("sku"),
            "tiny_product_id": product.get("tiny_product_id"),
            "origin": product.get("origin"),
        },
        "stock": _product_stock_public(product),
        "movements": movements,
    }


@app.post("/api/admin/products/{product_id:int}/stock/movements")
@app.post("/admin/products/{product_id:int}/stock/movements")
async def admin_product_stock_movement_create(request: Request, product_id: int, company: str = ""):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    company = _clean_str(body.get("company")) or company
    company_key = _auth_company_or_default(user, company)
    movement_type = _clean_str(body.get("movement_type")).lower()
    if movement_type not in _PRODUCT_STOCK_MOVEMENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de movimento inválido.")
    quantity = body.get("quantity")
    new_stock_physical = body.get("new_stock_physical")
    reason = _clean_str(body.get("reason"))
    notes = _clean_str(body.get("notes"))
    created_by = _clean_str(user.get("login") or user.get("email") or user.get("id"))

    _ensure_product_stock_movements_table()
    with _db() as conn:
        with conn.cursor() as cur:
            product = _product_get_for_stock(cur, company_key, product_id)
            if not product:
                raise HTTPException(status_code=404, detail="Produto não encontrado nesta empresa.")
            prev_physical = _product_stock_number(product.get("stock_physical"))
            prev_reserved = _product_stock_number(product.get("stock_reserved"))
            prev_available = prev_physical - prev_reserved

            calc = _product_calculate_stock_movement(
                movement_type, quantity, new_stock_physical, prev_physical, prev_reserved
            )

            movement = _product_insert_stock_movement(
                cur,
                company_key=company_key,
                product=product,
                movement_type=movement_type,
                calc=calc,
                prev_physical=prev_physical,
                prev_reserved=prev_reserved,
                prev_available=prev_available,
                reason=reason,
                notes=notes,
                created_by=created_by,
                raw_payload={
                    "movement_type": movement_type,
                    "quantity": quantity,
                    "new_stock_physical": new_stock_physical,
                },
            )

            cur.execute(
                """
                UPDATE erp.products
                SET stock_physical=%s,
                    stock_reserved=%s,
                    stock_available=%s,
                    updated_at=now()
                WHERE id=%s AND company_key=%s
                """,
                (
                    calc["new_physical"],
                    calc["new_reserved"],
                    calc["new_available"],
                    int(product_id),
                    company_key,
                ),
            )

    return {
        "ok": True,
        "company_key": company_key,
        "product_id": int(product_id),
        "movement": movement,
        "stock": {
            "previous_physical": prev_physical,
            "previous_reserved": prev_reserved,
            "previous_available": prev_available,
            "stock_physical": calc["new_physical"],
            "stock_reserved": calc["new_reserved"],
            "stock_available": calc["new_available"],
        },
    }


def _product_calculate_stock_reversal(
    original: Dict[str, Any],
    prev_physical: float,
    prev_reserved: float,
) -> Dict[str, Any]:
    """Calcula o efeito inverso de um movimento original sobre os saldos ATUAIS.
    Levanta HTTPException(400) se o estorno geraria saldo inválido. Não toca no banco.

    Regras por tipo do movimento original:
      - manual_entry:    desfaz a entrada -> físico -= quantity (bloqueia se <0 ou < reservado).
      - manual_exit:     desfaz a saída   -> físico += quantity.
      - reserve:         desfaz a reserva -> reservado -= quantity (bloqueia se reserva atual insuficiente).
      - release_reserve: desfaz a liberação -> reservado += quantity (bloqueia se reservado > físico).
      - manual_adjustment / set_initial: volta o físico para previous_physical do movimento
        original (bloqueia se < reservado atual ou < 0).

    `quantity` registrada no movimento de estorno: magnitude positiva nos tipos por
    quantidade; diferença assinada (new_physical - prev_physical) em ajuste/inicial.
    """
    mtype = _clean_str(original.get("movement_type")).lower()
    orig_qty = _product_stock_number(original.get("quantity"))
    new_physical = prev_physical
    new_reserved = prev_reserved

    if mtype == "manual_entry":
        new_physical = prev_physical - orig_qty
        if new_physical < 0:
            raise HTTPException(status_code=400, detail="O estorno deixaria o estoque físico negativo.")
        if new_physical < new_reserved:
            raise HTTPException(status_code=400, detail="O estorno deixaria o estoque físico menor que o reservado.")
        recorded_qty = orig_qty
    elif mtype == "manual_exit":
        new_physical = prev_physical + orig_qty
        recorded_qty = orig_qty
    elif mtype == "reserve":
        new_reserved = prev_reserved - orig_qty
        if new_reserved < 0:
            raise HTTPException(status_code=400, detail="O estorno excede a reserva atual disponível para liberar.")
        recorded_qty = orig_qty
    elif mtype == "release_reserve":
        new_reserved = prev_reserved + orig_qty
        if new_reserved > new_physical:
            raise HTTPException(status_code=400, detail="O estorno deixaria o reservado maior que o estoque físico.")
        recorded_qty = orig_qty
    elif mtype in ("manual_adjustment", "set_initial"):
        target = _product_stock_number(original.get("previous_physical"))
        if target < 0:
            raise HTTPException(status_code=400, detail="O estorno resultaria em estoque físico negativo.")
        if target < new_reserved:
            raise HTTPException(status_code=400, detail="O estorno deixaria o estoque físico menor que o reservado atual.")
        new_physical = target
        recorded_qty = new_physical - prev_physical
    else:
        raise HTTPException(status_code=400, detail="Tipo de movimento não pode ser estornado.")

    new_available = new_physical - new_reserved
    if new_physical < 0 or new_reserved < 0 or new_available < 0 or new_reserved > new_physical:
        raise HTTPException(status_code=400, detail="O estorno resultaria em saldo inválido.")

    return {
        "movement_type": mtype,
        "quantity": recorded_qty,
        "new_physical": new_physical,
        "new_reserved": new_reserved,
        "new_available": new_available,
    }


@app.post("/api/admin/products/{product_id:int}/stock/movements/{movement_id:int}/reverse")
@app.post("/admin/products/{product_id:int}/stock/movements/{movement_id:int}/reverse")
async def admin_product_stock_movement_reverse(
    request: Request, product_id: int, movement_id: int, company: str = ""
):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    company = _clean_str(body.get("company")) or company
    company_key = _auth_company_or_default(user, company)
    reason = _clean_str(body.get("reason"))
    notes = _clean_str(body.get("notes"))
    if not reason:
        raise HTTPException(status_code=400, detail="Informe o motivo do estorno.")
    reversed_by = _clean_str(user.get("login") or user.get("email") or user.get("id"))

    _ensure_product_stock_movements_table()
    with _db() as conn:
        with conn.cursor() as cur:
            product = _product_get_for_stock(cur, company_key, product_id)
            if not product:
                raise HTTPException(status_code=404, detail="Produto não encontrado nesta empresa.")

            cur.execute(
                """
                SELECT * FROM erp.product_stock_movements
                WHERE id=%s AND company_key=%s AND product_id=%s
                LIMIT 1
                """,
                (int(movement_id), company_key, int(product_id)),
            )
            original = cur.fetchone()
            if not original:
                raise HTTPException(status_code=404, detail="Movimento não encontrado para este produto/empresa.")
            original = dict(original)
            if original.get("reversed_at") is not None:
                raise HTTPException(status_code=400, detail="Este movimento já foi estornado.")
            if bool(original.get("is_reversal")):
                raise HTTPException(status_code=400, detail="Não é possível estornar um movimento de estorno.")

            prev_physical = _product_stock_number(product.get("stock_physical"))
            prev_reserved = _product_stock_number(product.get("stock_reserved"))
            prev_available = prev_physical - prev_reserved

            calc = _product_calculate_stock_reversal(original, prev_physical, prev_reserved)

            reversal = _product_insert_stock_movement(
                cur,
                company_key=company_key,
                product=product,
                movement_type=calc["movement_type"],
                calc=calc,
                prev_physical=prev_physical,
                prev_reserved=prev_reserved,
                prev_available=prev_available,
                reason=reason,
                notes=notes,
                created_by=reversed_by,
                raw_payload={
                    "kind": "reversal",
                    "reverses_movement_id": int(movement_id),
                    "original_movement_type": calc["movement_type"],
                },
                is_reversal=True,
                reverses_movement_id=int(movement_id),
            )

            cur.execute(
                """
                UPDATE erp.products
                SET stock_physical=%s,
                    stock_reserved=%s,
                    stock_available=%s,
                    updated_at=now()
                WHERE id=%s AND company_key=%s
                """,
                (
                    calc["new_physical"],
                    calc["new_reserved"],
                    calc["new_available"],
                    int(product_id),
                    company_key,
                ),
            )

            cur.execute(
                """
                UPDATE erp.product_stock_movements
                SET reversed_at=now(),
                    reversed_by=%s,
                    reversal_reason=%s,
                    reversal_movement_id=%s
                WHERE id=%s AND company_key=%s AND product_id=%s
                """,
                (
                    reversed_by or None,
                    reason or None,
                    int(reversal.get("id")),
                    int(movement_id),
                    company_key,
                    int(product_id),
                ),
            )

    return {
        "ok": True,
        "company_key": company_key,
        "product_id": int(product_id),
        "original_movement_id": int(movement_id),
        "reversal_movement_id": int(reversal.get("id")),
        "movement": reversal,
        "stock": {
            "previous_physical": prev_physical,
            "previous_reserved": prev_reserved,
            "previous_available": prev_available,
            "stock_physical": calc["new_physical"],
            "stock_reserved": calc["new_reserved"],
            "stock_available": calc["new_available"],
        },
    }


@app.get("/api/admin/products/stock-movements")
@app.get("/admin/products/stock-movements")
def admin_product_stock_movements_report(
    request: Request,
    company: str = "",
    product_id: int = Query(default=0, ge=0),
    sku: str = "",
    q: str = "",
    movement_type: str = "",
    date_from: str = "",
    date_to: str = "",
    include_reversed: bool = True,
    only_reversed: bool = False,
    only_reversals: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Relatório/auditoria de movimentações de estoque local (Fase 3).

    SOMENTE LEITURA: não cria/edita/exclui movimento, não altera saldo, produto
    ou Tiny/Olist. Admin-only. Lê erp.product_stock_movements com JOIN opcional
    em erp.products (nome) e aplica filtros simples sempre escopados por empresa.
    """
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_product_stock_movements_table()

    where = ["m.company_key=%s"]
    params: List[Any] = [company_key]

    if int(product_id) > 0:
        where.append("m.product_id=%s")
        params.append(int(product_id))

    sku_norm = _clean_str(sku).lower()
    if sku_norm:
        where.append("LOWER(COALESCE(m.sku, '')) LIKE %s")
        params.append(f"%{sku_norm}%")

    q_norm = _clean_str(q).lower()
    if q_norm:
        like = f"%{q_norm}%"
        where.append("(LOWER(COALESCE(p.nome, '')) LIKE %s OR LOWER(COALESCE(m.sku, '')) LIKE %s)")
        params.extend([like, like])

    mtype = _clean_str(movement_type).lower()
    if mtype:
        if mtype not in _PRODUCT_STOCK_MOVEMENT_TYPES:
            raise HTTPException(status_code=400, detail="Tipo de movimento inválido.")
        where.append("m.movement_type=%s")
        params.append(mtype)

    date_from_norm = _clean_str(date_from)
    if date_from_norm:
        where.append("m.created_at >= %s::date")
        params.append(date_from_norm)

    date_to_norm = _clean_str(date_to)
    if date_to_norm:
        # Inclui o dia inteiro de date_to (até o fim do dia).
        where.append("m.created_at < (%s::date + INTERVAL '1 day')")
        params.append(date_to_norm)

    if only_reversals:
        where.append("m.is_reversal = true")
    if only_reversed:
        where.append("m.reversed_at IS NOT NULL")
    if not include_reversed and not only_reversed and not only_reversals:
        # Esconde tanto os já estornados quanto os próprios movimentos de estorno.
        where.append("m.reversed_at IS NULL AND m.is_reversal = false")

    where_sql = " AND ".join(where)
    base_from = "FROM erp.product_stock_movements m LEFT JOIN erp.products p ON p.id = m.product_id AND p.company_key = m.company_key"

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total {base_from} WHERE {where_sql}", params)
            total = int((cur.fetchone() or {}).get("total") or 0)

            cur.execute(
                f"""
                SELECT
                  COUNT(*) FILTER (WHERE m.movement_type='manual_entry') AS entries,
                  COUNT(*) FILTER (WHERE m.movement_type='manual_exit') AS exits,
                  COUNT(*) FILTER (WHERE m.movement_type IN ('manual_adjustment','set_initial')) AS adjustments,
                  COUNT(*) FILTER (WHERE m.movement_type='reserve') AS reservations,
                  COUNT(*) FILTER (WHERE m.movement_type='release_reserve') AS releases,
                  COUNT(*) FILTER (WHERE m.is_reversal = true) AS reversals,
                  COUNT(*) FILTER (WHERE m.reversed_at IS NOT NULL) AS reversed,
                  COALESCE(SUM(m.quantity) FILTER (WHERE m.movement_type='manual_entry'), 0) AS quantity_entry_total,
                  COALESCE(SUM(m.quantity) FILTER (WHERE m.movement_type='manual_exit'), 0) AS quantity_exit_total
                {base_from} WHERE {where_sql}
                """,
                params,
            )
            srow = dict(cur.fetchone() or {})

            cur.execute(
                f"""
                SELECT
                  m.id, m.company_key, m.product_id, p.nome AS product_name, m.sku, m.tiny_product_id,
                  m.movement_type, m.quantity,
                  m.previous_physical, m.previous_reserved, m.previous_available,
                  m.new_physical, m.new_reserved, m.new_available,
                  m.reason, m.notes, m.created_by, m.created_at,
                  m.reversed_at, m.reversed_by, m.reversal_reason, m.reversal_movement_id,
                  m.is_reversal, m.reverses_movement_id
                {base_from}
                WHERE {where_sql}
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT %s OFFSET %s
                """,
                [*params, int(limit), int(offset)],
            )
            items = [dict(r) for r in cur.fetchall()]

    def _si(key: str) -> int:
        return int(srow.get(key) or 0)

    def _sf(key: str) -> float:
        return _product_stock_number(srow.get(key))

    return {
        "ok": True,
        "company_key": company_key,
        "items": items,
        "total": total,
        "limit": int(limit),
        "offset": int(offset),
        "summary": {
            "entries": _si("entries"),
            "exits": _si("exits"),
            "adjustments": _si("adjustments"),
            "reservations": _si("reservations"),
            "releases": _si("releases"),
            "reversals": _si("reversals"),
            "reversed": _si("reversed"),
            "quantity_entry_total": _sf("quantity_entry_total"),
            "quantity_exit_total": _sf("quantity_exit_total"),
        },
    }


def _stock_position_status(physical: float, min_stock: float) -> str:
    """Classifica o saldo físico local em negative/zero/low/positive."""
    if physical < 0:
        return "negative"
    if physical == 0:
        return "zero"
    if physical <= min_stock:
        return "low"
    return "positive"


@app.get("/api/admin/products/stock-position")
@app.get("/admin/products/stock-position")
def admin_product_stock_position(
    request: Request,
    company: str = "",
    q: str = "",
    stock_status: str = "all",
    min_stock: float = Query(default=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Posição atual de estoque LOCAL (Fase: posição de estoque) — somente leitura.

    Foca na coluna `stock_physical` de erp.products (NULL tratado como 0), que é
    onde o Controle de Estoque Local grava saldos. NÃO altera produto/saldo, NÃO
    cria movimento, NÃO consulta nem escreve no Tiny. Admin-only, sempre escopado
    por empresa. O `summary` reflete o conjunto company+q (independente de
    stock_status) para os cards mostrarem o panorama completo; a lista aplica
    também o filtro stock_status e pagina. `min_stock` é só critério de
    classificação (não remove linhas do conjunto).
    """
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_products_local_first_table()

    min_stock_num = _product_stock_number(min_stock)
    status = _clean_str(stock_status).lower() or "all"
    if status not in ("all", "positive", "zero", "low", "negative"):
        raise HTTPException(status_code=400, detail="Status de estoque inválido.")

    base_where = ["company_key=%s"]
    base_params: List[Any] = [company_key]
    q_norm = _clean_str(q).lower()
    if q_norm:
        like = f"%{q_norm}%"
        base_where.append("(LOWER(COALESCE(nome,'')) LIKE %s OR LOWER(COALESCE(sku,'')) LIKE %s)")
        base_params.extend([like, like])
    base_where_sql = " AND ".join(base_where)

    phys_expr = "COALESCE(stock_physical, 0)"
    status_sql = {
        "positive": f"{phys_expr} > %s",
        "zero": f"{phys_expr} = 0",
        "low": f"{phys_expr} > 0 AND {phys_expr} <= %s",
        "negative": f"{phys_expr} < 0",
    }

    list_cols = """
        id, company_key, nome, sku, tiny_product_id, origin,
        stock_physical, stock_reserved, stock_available,
        preco_custo, preco_venda, marca, tiny_sync_status, updated_at,
        estoque_inicial, estoque_payload, custos_payload
    """

    with _db() as conn:
        with conn.cursor() as cur:
            # ---- Resumo: company + q (não aplica stock_status) ----
            cur.execute(
                f"SELECT stock_physical, preco_custo, custos_payload FROM erp.products WHERE {base_where_sql}",
                base_params,
            )
            products_total = 0
            positive_count = zero_count = low_count = negative_count = 0
            stock_physical_total = 0.0
            estimated_stock_value = 0.0
            for r in cur.fetchall():
                rd = dict(r)
                phys = _product_stock_number(rd.get("stock_physical"))
                st = _stock_position_status(phys, min_stock_num)
                products_total += 1
                if st == "positive":
                    positive_count += 1
                elif st == "zero":
                    zero_count += 1
                elif st == "low":
                    low_count += 1
                elif st == "negative":
                    negative_count += 1
                stock_physical_total += phys
                avg_cost = _product_stock_number(_product_list_stock_cost(rd).get("custo_medio"))
                estimated_stock_value += phys * avg_cost

            # ---- Lista: company + q + stock_status, paginada ----
            list_where = list(base_where)
            list_params = list(base_params)
            if status in status_sql:
                list_where.append(status_sql[status])
                if status in ("positive", "low"):
                    list_params.append(min_stock_num)
            list_where_sql = " AND ".join(list_where)

            cur.execute(f"SELECT COUNT(*) AS total FROM erp.products WHERE {list_where_sql}", list_params)
            total = int((cur.fetchone() or {}).get("total") or 0)

            cur.execute(
                f"""
                SELECT {list_cols}
                FROM erp.products
                WHERE {list_where_sql}
                ORDER BY LOWER(COALESCE(nome, sku, '')), id
                LIMIT %s OFFSET %s
                """,
                [*list_params, int(limit), int(offset)],
            )
            items = []
            for r in cur.fetchall():
                rd = dict(r)
                phys = _product_stock_number(rd.get("stock_physical"))
                avg_cost = _product_list_stock_cost(rd).get("custo_medio")
                avg_cost_num = _product_stock_number(avg_cost)
                items.append(
                    {
                        "id": rd.get("id"),
                        "company_key": rd.get("company_key"),
                        "nome": rd.get("nome"),
                        "sku": rd.get("sku"),
                        "tiny_product_id": rd.get("tiny_product_id"),
                        "origin": rd.get("origin"),
                        "stock_physical": phys,
                        "stock_reserved": _product_stock_number(rd.get("stock_reserved")),
                        "stock_available": _product_stock_number(rd.get("stock_available")),
                        "preco_custo": rd.get("preco_custo"),
                        "preco_venda": rd.get("preco_venda"),
                        "marca": rd.get("marca"),
                        "tiny_sync_status": rd.get("tiny_sync_status"),
                        "updated_at": rd.get("updated_at"),
                        "average_cost": avg_cost,
                        "stock_physical_value": phys,
                        "stock_estimated_value": phys * avg_cost_num,
                        "stock_status": _stock_position_status(phys, min_stock_num),
                    }
                )

    return {
        "ok": True,
        "company_key": company_key,
        "total": total,
        "limit": int(limit),
        "offset": int(offset),
        "summary": {
            "products_total": products_total,
            "positive_count": positive_count,
            "zero_count": zero_count,
            "low_count": low_count,
            "negative_count": negative_count,
            "stock_physical_total": stock_physical_total,
            "estimated_stock_value": estimated_stock_value,
        },
        "items": items,
    }


# ===========================================================================
# Importação/conferência de ajustes de estoque local EM LOTE (por SKU).
# Fluxo de 2 etapas: preview (somente leitura) -> commit (grava após conferência).
# Modos: manual_entry (entrada), manual_exit (saída), manual_adjustment (estoque final).
# NÃO escreve no Tiny, NÃO mexe em preço/custo, NÃO cria produto novo.
# ===========================================================================

_STOCK_BULK_MODES = {"manual_entry", "manual_exit", "manual_adjustment"}


def _stock_bulk_qty(value: Any) -> Optional[float]:
    """Quantidade numérica (aceita vírgula decimal BR). None se inválida/vazia.

    Atenção: não usar _clean_str para detectar vazio aqui, pois _clean_str(0) == ""
    (0 é falsy em `str(v or "")`) e isso marcaria a quantidade 0 como inválida —
    0 é válido no modo Ajustar estoque final (zera o estoque)."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return _safe_float(value, None)


def _product_resolve_by_sku(cur, company_key: str, sku: str) -> List[Dict[str, Any]]:
    """Resolve produto(s) por SKU exato (case-insensitive) dentro da empresa."""
    cur.execute(
        """
        SELECT id, company_key, tiny_product_id, sku, nome,
               stock_physical, stock_reserved, stock_available
        FROM erp.products
        WHERE company_key=%s AND LOWER(COALESCE(sku, '')) = LOWER(%s)
        ORDER BY id
        """,
        (company_key, sku),
    )
    return [dict(r) for r in cur.fetchall()]


def _product_get_by_id(cur, company_key: str, product_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, company_key, tiny_product_id, sku, nome,
               stock_physical, stock_reserved, stock_available
        FROM erp.products
        WHERE id=%s AND company_key=%s
        LIMIT 1
        """,
        (int(product_id), company_key),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _stock_bulk_calc_for_mode(mode: str, qty: float, prev_physical: float, prev_reserved: float) -> Dict[str, float]:
    """Reaproveita _product_calculate_stock_movement conforme o modo do lote.
    Levanta HTTPException(400) em regra violada (saldo inválido/negativo)."""
    if mode == "manual_adjustment":
        # qty importada é o ESTOQUE FÍSICO FINAL desejado (0 é válido: zera o estoque).
        # Passa como string ("0" em vez de 0) porque a função compartilhada usa
        # _clean_str(new_stock_physical) == "" para detectar "alvo ausente", e
        # _clean_str(0) == "" (0 é falsy). Manter localizado aqui não altera o
        # comportamento do endpoint de movimento individual. Quantidade negativa
        # continua bloqueada lá dentro (target < 0).
        return _product_calculate_stock_movement(
            "manual_adjustment", None, str(qty), prev_physical, prev_reserved
        )
    # manual_entry / manual_exit: qty é a quantidade a somar/subtrair (deve ser > 0).
    return _product_calculate_stock_movement(mode, qty, None, prev_physical, prev_reserved)


@app.post("/api/admin/products/stock-bulk/preview")
@app.post("/admin/products/stock-bulk/preview")
async def admin_product_stock_bulk_preview(request: Request, company: str = ""):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    company = _clean_str(body.get("company")) or company
    company_key = _auth_company_or_default(user, company)
    mode = _clean_str(body.get("mode")).lower()
    if mode not in _STOCK_BULK_MODES:
        raise HTTPException(status_code=400, detail="Modo de importação inválido.")
    rows = body.get("rows")
    if not isinstance(rows, list):
        rows = []

    _ensure_product_stock_movements_table()
    items: List[Dict[str, Any]] = []
    ok_count = error_count = not_found_count = duplicate_count = 0

    with _db() as conn:
        with conn.cursor() as cur:
            for idx, raw in enumerate(rows, start=1):
                raw = raw if isinstance(raw, dict) else {}
                line = _safe_int(raw.get("line"), None) or idx
                input_sku = _clean_str(raw.get("sku"))
                forced_pid = _safe_int(raw.get("product_id"), None)
                qty = _stock_bulk_qty(raw.get("quantity"))

                item: Dict[str, Any] = {
                    "line": line,
                    "input_sku": input_sku,
                    "quantity": qty,
                    "status": "ok",
                    "product_id": None,
                    "product_name": "",
                    "resolved_sku": "",
                    "current_stock_physical": None,
                    "projected_stock_physical": None,
                    "message": "",
                    "options": [],
                }

                # 1) Resolver produto (por product_id forçado ou por SKU).
                product = None
                if forced_pid and forced_pid > 0:
                    product = _product_get_by_id(cur, company_key, forced_pid)
                    if not product:
                        item["status"] = "error"
                        item["message"] = "Produto selecionado não encontrado nesta empresa."
                        error_count += 1
                        items.append(item)
                        continue
                elif not input_sku:
                    item["status"] = "error"
                    item["message"] = "SKU vazio."
                    error_count += 1
                    items.append(item)
                    continue
                else:
                    matches = _product_resolve_by_sku(cur, company_key, input_sku)
                    if len(matches) == 0:
                        item["status"] = "not_found"
                        item["message"] = "SKU não encontrado na base local."
                        not_found_count += 1
                        items.append(item)
                        continue
                    if len(matches) > 1:
                        item["status"] = "duplicate_sku"
                        item["message"] = "SKU duplicado na base local. Selecione o produto correto."
                        item["options"] = [
                            {
                                "product_id": m.get("id"),
                                "sku": m.get("sku"),
                                "product_name": m.get("nome"),
                                "current_stock_physical": _product_stock_number(m.get("stock_physical")),
                            }
                            for m in matches
                        ]
                        duplicate_count += 1
                        items.append(item)
                        continue
                    product = matches[0]

                # 2) Produto resolvido: preencher dados e projetar.
                item["product_id"] = product.get("id")
                item["product_name"] = product.get("nome")
                item["resolved_sku"] = product.get("sku")
                prev_physical = _product_stock_number(product.get("stock_physical"))
                prev_reserved = _product_stock_number(product.get("stock_reserved"))
                item["current_stock_physical"] = prev_physical

                if qty is None:
                    item["status"] = "error"
                    item["message"] = "Quantidade inválida."
                    error_count += 1
                    items.append(item)
                    continue

                try:
                    calc = _stock_bulk_calc_for_mode(mode, qty, prev_physical, prev_reserved)
                    item["projected_stock_physical"] = calc["new_physical"]
                    ok_count += 1
                except HTTPException as he:
                    item["status"] = "error"
                    item["message"] = str(he.detail)
                    error_count += 1

                items.append(item)

    return {
        "ok": True,
        "company_key": company_key,
        "mode": mode,
        "items": items,
        "summary": {
            "total_rows": len(items),
            "ok_count": ok_count,
            "error_count": error_count,
            "not_found_count": not_found_count,
            "duplicate_count": duplicate_count,
        },
    }


@app.post("/api/admin/products/stock-bulk/commit")
@app.post("/admin/products/stock-bulk/commit")
async def admin_product_stock_bulk_commit(request: Request, company: str = ""):
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    company = _clean_str(body.get("company")) or company
    company_key = _auth_company_or_default(user, company)
    mode = _clean_str(body.get("mode")).lower()
    if mode not in _STOCK_BULK_MODES:
        raise HTTPException(status_code=400, detail="Modo de importação inválido.")
    reason = _clean_str(body.get("reason"))
    notes = _clean_str(body.get("notes"))
    origin = _clean_str(body.get("origin")) or "text"
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Nenhum item para importar.")

    created_by = _clean_str(user.get("login") or user.get("email") or user.get("id"))

    # ---- Pré-validação (sem tocar no banco): bloqueia o lote inteiro se houver
    #      item sem product_id ou com quantidade inválida. ----
    prepared: List[Dict[str, Any]] = []
    for idx, raw in enumerate(items, start=1):
        raw = raw if isinstance(raw, dict) else {}
        line = _safe_int(raw.get("line"), None) or idx
        pid = _safe_int(raw.get("product_id"), None)
        if not pid or pid <= 0:
            raise HTTPException(status_code=400, detail=f"Linha {line}: produto não selecionado. Conferência incompleta.")
        qty = _stock_bulk_qty(raw.get("quantity"))
        if qty is None:
            raise HTTPException(status_code=400, detail=f"Linha {line}: quantidade inválida.")
        prepared.append({"line": line, "product_id": int(pid), "sku": _clean_str(raw.get("sku")), "quantity": qty})

    bulk_id = f"bulk-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    _ensure_product_stock_movements_table()

    movement_ids: List[int] = []
    # Transação única: qualquer falha levanta exceção e o context manager do
    # psycopg2 faz ROLLBACK de TODO o lote (sem rollback parcial silencioso).
    with _db() as conn:
        with conn.cursor() as cur:
            for it in prepared:
                product = _product_get_by_id(cur, company_key, it["product_id"])
                if not product:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Linha {it['line']}: produto {it['product_id']} não encontrado nesta empresa.",
                    )
                prev_physical = _product_stock_number(product.get("stock_physical"))
                prev_reserved = _product_stock_number(product.get("stock_reserved"))
                prev_available = prev_physical - prev_reserved

                # Reaproveita a MESMA regra do movimento individual (levanta 400 se inválido).
                calc = _stock_bulk_calc_for_mode(mode, it["quantity"], prev_physical, prev_reserved)

                movement = _product_insert_stock_movement(
                    cur,
                    company_key=company_key,
                    product=product,
                    movement_type=mode,
                    calc=calc,
                    prev_physical=prev_physical,
                    prev_reserved=prev_reserved,
                    prev_available=prev_available,
                    reason=reason,
                    notes=notes,
                    created_by=created_by,
                    raw_payload={
                        "kind": "stock_bulk_import",
                        "bulk_id": bulk_id,
                        "line": it["line"],
                        "input_sku": it["sku"],
                        "mode": mode,
                        "origin": origin,
                    },
                    reference_type="stock_bulk_import",
                    reference_id=bulk_id,
                )

                cur.execute(
                    """
                    UPDATE erp.products
                    SET stock_physical=%s,
                        stock_reserved=%s,
                        stock_available=%s,
                        updated_at=now()
                    WHERE id=%s AND company_key=%s
                    """,
                    (
                        calc["new_physical"],
                        calc["new_reserved"],
                        calc["new_available"],
                        int(it["product_id"]),
                        company_key,
                    ),
                )
                movement_ids.append(int(movement.get("id")))

    return {
        "ok": True,
        "company_key": company_key,
        "mode": mode,
        "bulk_id": bulk_id,
        "processed_count": len(movement_ids),
        "movement_ids": movement_ids,
        "errors": [],
        "summary": {"updated_count": len(movement_ids)},
    }


# ===========================================================================
# Diagnóstico de impacto de estoque por pedido/separação (SOMENTE LEITURA).
# Simula reserva/baixa/cancelamento de um pedido contra o estoque LOCAL, SEM
# gravar nada, SEM criar movimento e SEM tocar Tiny/Olist. Admin-only.
# Os tipos automáticos abaixo NÃO são gravados nesta fase — só nomeiam o efeito
# futuro e servem ao critério de idempotência em erp.product_stock_movements.
# ===========================================================================

_AUTOMATIC_STOCK_MOVEMENT_TYPES = (
    "automatic_reserve",
    "automatic_release_reserve",
    "automatic_exit",
    "automatic_cancel_reversal",
)

_ORDER_STOCK_IMPACT_MODES = {"reserve", "exit", "cancel_reversal"}


def _product_get_by_tiny_id(cur, company_key: str, tiny_pid: str) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, company_key, tiny_product_id, sku, nome,
               stock_physical, stock_reserved, stock_available
        FROM erp.products
        WHERE company_key=%s AND COALESCE(tiny_product_id, '') = %s
        ORDER BY id
        LIMIT 1
        """,
        (company_key, _clean_str(tiny_pid)),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _order_find_quote(cur, company_key: str, order_id: str, quote_id_q: str, tiny_order_id_q: str) -> Optional[Dict[str, Any]]:
    """Localiza o pedido/orçamento por quote_id, tiny_order_id ou tiny_order_number.
    Prioridade: quote_id (query) -> tiny_order_id (query) -> {order_id} do path."""
    for cand in (quote_id_q, tiny_order_id_q, order_id):
        c = _clean_str(cand)
        if not c:
            continue
        cur.execute(
            """
            SELECT * FROM erp.quotes
            WHERE company_key=%s AND (
              quote_id=%s
              OR CAST(tiny_order_id AS TEXT)=%s
              OR CAST(tiny_order_number AS TEXT)=%s
            )
            LIMIT 1
            """,
            (company_key, c, c, c),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
    return None


def _order_existing_auto_movements(cur, company_key: str, product_id: int, reference_id: str) -> Dict[str, int]:
    """Conta movimentos automáticos JÁ existentes para o par pedido/produto.
    Base do critério de idempotência da fase futura (não cria índice único agora)."""
    if not reference_id:
        return {}
    cur.execute(
        """
        SELECT movement_type, COUNT(*) AS n
        FROM erp.product_stock_movements
        WHERE company_key=%s AND product_id=%s
          AND reference_type='order' AND reference_id=%s
          AND movement_type = ANY(%s)
        GROUP BY movement_type
        """,
        (company_key, int(product_id), _clean_str(reference_id), list(_AUTOMATIC_STOCK_MOVEMENT_TYPES)),
    )
    return {r["movement_type"]: int(r["n"]) for r in cur.fetchall()}


def _simulate_order_stock_item(mode: str, qty: float, phys: float, reserved: float, existing: Dict[str, int]):
    """Calcula o efeito SIMULADO de um item. Não toca no banco.
    Retorna (status, message, projected_physical, projected_reserved, projected_available)."""
    available = phys - reserved
    pp, pr = phys, reserved
    status, msg = "ok", ""

    if mode == "reserve":
        if existing.get("automatic_reserve"):
            status, msg = "already_reserved", "Já existe reserva automática para este pedido/produto."
        pr = reserved + qty
        if status == "ok" and qty > available:
            status, msg = "insufficient", "Estoque disponível insuficiente para reservar."
    elif mode == "exit":
        if existing.get("automatic_exit"):
            status, msg = "already_deducted", "Já existe baixa automática para este pedido/produto."
        pp = phys - qty
        pr = reserved - qty if reserved >= qty else 0.0
        if status == "ok" and pp < 0:
            status, msg = "insufficient", "Estoque físico insuficiente para baixa."
        elif status == "ok" and reserved < qty:
            msg = "Atenção: reserva automática menor que a quantidade; será baixado do físico."
    elif mode == "cancel_reversal":
        if existing.get("automatic_cancel_reversal"):
            status, msg = "already_reversed", "Já existe estorno automático para este pedido/produto."
        elif existing.get("automatic_exit"):
            pp = phys + qty
            msg = "Devolve estoque físico (havia baixa automática)."
        elif existing.get("automatic_reserve"):
            pr = reserved - qty if reserved >= qty else 0.0
            msg = "Libera reserva automática (não houve baixa)."
        else:
            status, msg = "nothing_to_reverse", "Nada a reverter para este pedido/produto."

    pa = pp - pr
    return status, msg, pp, pr, pa


@app.get("/api/admin/orders/{order_id}/stock-impact")
@app.get("/admin/orders/{order_id}/stock-impact")
def admin_order_stock_impact(
    request: Request,
    order_id: str,
    company: str = "",
    mode: str = "reserve",
    quote_id: str = "",
    tiny_order_id: str = "",
):
    """Diagnóstico SOMENTE LEITURA do impacto de estoque local de um pedido.

    Simula reserva/baixa/cancelamento contra erp.products (saldos locais) sem
    gravar nada, sem criar movimento e sem tocar no Tiny/Olist. Resolve os itens
    do pedido (erp.quote_items) em produtos locais por tiny_product_id e, em
    fallback, por SKU. Detecta movimentos automáticos anteriores do mesmo pedido
    em erp.product_stock_movements (idempotência da fase futura). Admin-only.
    """
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    mode = _clean_str(mode).lower() or "reserve"
    if mode not in _ORDER_STOCK_IMPACT_MODES:
        raise HTTPException(status_code=400, detail="Modo de simulação inválido (use reserve, exit ou cancel_reversal).")

    _ensure_product_stock_movements_table()

    with _db() as conn:
        with conn.cursor() as cur:
            quote = _order_find_quote(cur, company_key, order_id, quote_id, tiny_order_id)
            if not quote:
                raise HTTPException(status_code=404, detail="Pedido/orçamento não encontrado nesta empresa.")

            q_quote_id = _clean_str(quote.get("quote_id"))
            q_tiny_order_id = _clean_str(quote.get("tiny_order_id"))
            q_tiny_order_number = _clean_str(quote.get("tiny_order_number"))
            # reference_id do efeito futuro: idealmente o tiny_order_id; senão o quote_id local.
            order_ref = q_tiny_order_id or q_quote_id

            cur.execute(
                "SELECT * FROM erp.quote_items WHERE quote_id=%s ORDER BY line",
                (q_quote_id,),
            )
            raw_items = [dict(r) for r in cur.fetchall()]

            items: List[Dict[str, Any]] = []
            ok_count = not_found_count = insufficient_count = 0
            already_reserved_count = already_deducted_count = already_reversed_count = 0
            errors: List[str] = []

            for raw in raw_items:
                norm = _normalize_quote_item_financials(raw)
                line = _safe_int(raw.get("line"), None) or (len(items) + 1)
                input_sku = _clean_str(norm.get("sku"))
                name = _clean_str(norm.get("nome"))
                qty = _safe_float(norm.get("quantity") or norm.get("qty"), 0.0)
                tiny_pid = _clean_str(raw.get("product_id"))

                item: Dict[str, Any] = {
                    "line": line,
                    "input_sku": input_sku,
                    "name": name,
                    "quantity": qty,
                    "product_id": None,
                    "product_name": "",
                    "resolved_sku": "",
                    "stock_physical": None,
                    "stock_reserved": None,
                    "stock_available": None,
                    "projected_physical": None,
                    "projected_reserved": None,
                    "projected_available": None,
                    "status": "ok",
                    "message": "",
                }

                # Resolução SKU/Tiny -> produto local (kit/combo tratado como produto único).
                product = None
                resolve_msg = None
                if tiny_pid:
                    product = _product_get_by_tiny_id(cur, company_key, tiny_pid)
                if not product and input_sku:
                    matches = _product_resolve_by_sku(cur, company_key, input_sku)
                    if len(matches) == 1:
                        product = matches[0]
                    elif len(matches) > 1:
                        resolve_msg = "SKU duplicado na base local; resolver manualmente."

                if not product:
                    item["status"] = "not_found"
                    item["message"] = resolve_msg or (
                        "Item sem SKU." if not input_sku else "SKU não encontrado na base local."
                    )
                    not_found_count += 1
                    errors.append(f"Linha {line}: {item['message']} (SKU '{input_sku or '—'}')")
                    items.append(item)
                    continue

                if qty <= 0:
                    item["product_id"] = product.get("id")
                    item["product_name"] = product.get("nome")
                    item["resolved_sku"] = product.get("sku")
                    item["status"] = "not_found"
                    item["message"] = "Quantidade do item inválida (<= 0)."
                    not_found_count += 1
                    errors.append(f"Linha {line}: quantidade inválida.")
                    items.append(item)
                    continue

                phys = _product_stock_number(product.get("stock_physical"))
                reserved = _product_stock_number(product.get("stock_reserved"))
                existing = _order_existing_auto_movements(cur, company_key, int(product.get("id")), order_ref)

                status, msg, pp, pr, pa = _simulate_order_stock_item(mode, qty, phys, reserved, existing)

                item.update(
                    {
                        "product_id": product.get("id"),
                        "product_name": product.get("nome"),
                        "resolved_sku": product.get("sku"),
                        "stock_physical": phys,
                        "stock_reserved": reserved,
                        "stock_available": phys - reserved,
                        "projected_physical": pp,
                        "projected_reserved": pr,
                        "projected_available": pa,
                        "status": status,
                        "message": msg,
                    }
                )

                if status == "ok":
                    ok_count += 1
                elif status == "insufficient":
                    insufficient_count += 1
                    errors.append(f"Linha {line}: {msg}")
                elif status == "already_reserved":
                    already_reserved_count += 1
                elif status == "already_deducted":
                    already_deducted_count += 1
                elif status == "already_reversed":
                    already_reversed_count += 1
                elif status == "nothing_to_reverse":
                    errors.append(f"Linha {line}: {msg}")

                items.append(item)

    can_apply = len(items) > 0 and ok_count == len(items)

    return {
        "ok": True,
        "company_key": company_key,
        "order": {
            "quote_id": q_quote_id,
            "tiny_order_id": q_tiny_order_id,
            "tiny_order_number": q_tiny_order_number,
            "internal_status": _clean_str(quote.get("internal_status")),
            "reference_id": order_ref,
        },
        "mode": mode,
        "can_apply": can_apply,
        "items": items,
        "summary": {
            "items_count": len(items),
            "ok_count": ok_count,
            "not_found_count": not_found_count,
            "insufficient_count": insufficient_count,
            "already_reserved_count": already_reserved_count,
            "already_deducted_count": already_deducted_count,
            "already_reversed_count": already_reversed_count,
        },
        "errors": errors,
    }


# ===========================================================================
# Marco de início do CONTROLE AUTOMÁTICO de estoque local POR EMPRESA.
# Fase preparatória: SÓ guarda config/baseline. NÃO reserva, NÃO baixa, NÃO
# liga em pedido/separação e NÃO toca Tiny/Olist. A regra futura será:
#   pedido entra no fluxo automático se config.is_enabled E
#   quote.created_at >= config.started_at  (NÃO aplicada em lugar nenhum ainda).
# ===========================================================================

def _ensure_stock_auto_control_config_table():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS erp.stock_auto_control_config (
                  id BIGSERIAL PRIMARY KEY,
                  company_key TEXT NOT NULL UNIQUE,
                  is_enabled BOOLEAN NOT NULL DEFAULT false,
                  started_at TIMESTAMPTZ NULL,
                  baseline_reference_id TEXT NULL,
                  baseline_source TEXT NULL,
                  baseline_notes TEXT NULL,
                  enabled_by TEXT NULL,
                  enabled_at TIMESTAMPTZ NULL,
                  disabled_by TEXT NULL,
                  disabled_at TIMESTAMPTZ NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )


def _stock_auto_control_defaults(company_key: str) -> Dict[str, Any]:
    return {
        "company_key": company_key,
        "is_enabled": False,
        "started_at": None,
        "baseline_reference_id": None,
        "baseline_source": None,
        "baseline_notes": None,
        "enabled_by": None,
        "enabled_at": None,
        "disabled_by": None,
        "disabled_at": None,
        "created_at": None,
        "updated_at": None,
    }


def _get_stock_auto_control_config(cur, company_key: str) -> Dict[str, Any]:
    """Config do controle automático local com defaults (sem registro -> inativo).

    USO FUTURO (ainda NÃO aplicado): um pedido só entra no fluxo automático se
    `config['is_enabled']` for True e `quote.created_at >= config['started_at']`.
    Nesta fase serve apenas para status/configuração e diagnóstico."""
    cur.execute(
        "SELECT * FROM erp.stock_auto_control_config WHERE company_key=%s LIMIT 1",
        (company_key,),
    )
    row = cur.fetchone()
    return dict(row) if row else _stock_auto_control_defaults(company_key)


def _stock_auto_control_last_bulk_import(cur, company_key: str) -> Optional[Dict[str, Any]]:
    """Último lote de importação em lote (reference_type='stock_bulk_import')
    para sugerir como baseline. Somente leitura."""
    cur.execute(
        """
        SELECT reference_id, MAX(created_at) AS created_at, COUNT(*) AS n
        FROM erp.product_stock_movements
        WHERE company_key=%s AND reference_type='stock_bulk_import'
          AND COALESCE(reference_id, '') <> ''
        GROUP BY reference_id
        ORDER BY MAX(created_at) DESC
        LIMIT 1
        """,
        (company_key,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "reference_id": row.get("reference_id"),
        "created_at": row.get("created_at"),
        "movements_count": int(row.get("n") or 0),
    }


def _stock_auto_control_public(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "is_enabled": bool(config.get("is_enabled")),
        "started_at": config.get("started_at"),
        "baseline_reference_id": config.get("baseline_reference_id"),
        "baseline_source": config.get("baseline_source"),
        "baseline_notes": config.get("baseline_notes"),
        "enabled_by": config.get("enabled_by"),
        "enabled_at": config.get("enabled_at"),
        "disabled_by": config.get("disabled_by"),
        "disabled_at": config.get("disabled_at"),
        "updated_at": config.get("updated_at"),
    }


@app.get("/api/admin/stock-auto-control/status")
@app.get("/admin/stock-auto-control/status")
def admin_stock_auto_control_status(request: Request, company: str = ""):
    """Status do marco de controle automático local (SOMENTE LEITURA)."""
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    _ensure_stock_auto_control_config_table()
    _ensure_product_stock_movements_table()
    with _db() as conn:
        with conn.cursor() as cur:
            config = _get_stock_auto_control_config(cur, company_key)
            last_bulk = _stock_auto_control_last_bulk_import(cur, company_key)
    if config.get("is_enabled"):
        notes = "Controle automático ativo para esta empresa (marco definido). Nenhuma reserva/baixa automática é aplicada nesta fase."
    else:
        notes = "Controle automático ainda não ativado para esta empresa."
    return {
        "ok": True,
        "company_key": company_key,
        "config": _stock_auto_control_public(config),
        "last_bulk_import": last_bulk,
        "notes": notes,
    }


@app.post("/api/admin/stock-auto-control/configure")
@app.post("/admin/stock-auto-control/configure")
async def admin_stock_auto_control_configure(request: Request, company: str = ""):
    """Ativa/configura o marco de controle automático local (upsert por empresa).

    NÃO reserva, NÃO baixa, NÃO cria movimento, NÃO altera saldo/pedido/Tiny.
    Apenas grava a configuração/baseline para uso de fases futuras."""
    user = _catalog_require_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    company = _clean_str(body.get("company")) or company
    company_key = _auth_company_or_default(user, company)
    is_enabled = bool(body.get("is_enabled"))
    actor = _clean_str(user.get("login") or user.get("email") or user.get("id")) or None

    started_at_raw = _clean_str(body.get("started_at"))
    started_at_parsed = _parse_iso_ts(started_at_raw) if started_at_raw else None
    if is_enabled and started_at_raw and started_at_parsed is None:
        raise HTTPException(status_code=400, detail="started_at inválido (use ISO 8601, ex.: 2026-06-08T12:05:00-03:00).")

    baseline_reference_id = _clean_str(body.get("baseline_reference_id")) or None
    baseline_source = _clean_str(body.get("baseline_source")) or None
    baseline_notes = _clean_str(body.get("baseline_notes")) or None
    raw_payload = body.get("raw_payload") if isinstance(body.get("raw_payload"), dict) else {}

    now = dt.datetime.now(dt.timezone.utc)

    _ensure_stock_auto_control_config_table()
    with _db() as conn:
        with conn.cursor() as cur:
            existing = _get_stock_auto_control_config(cur, company_key)

            if is_enabled:
                started_at_val = started_at_parsed or now  # "Ativar a partir de agora" quando não informado
                enabled_by_val = actor
                enabled_at_val = now
                disabled_by_val = existing.get("disabled_by")
                disabled_at_val = existing.get("disabled_at")
            else:
                started_at_val = existing.get("started_at")  # preserva marco histórico
                enabled_by_val = existing.get("enabled_by")
                enabled_at_val = existing.get("enabled_at")
                disabled_by_val = actor
                disabled_at_val = now

            # Campos de baseline: atualização parcial não apaga o que já existe.
            baseline_reference_id = baseline_reference_id or existing.get("baseline_reference_id")
            baseline_source = baseline_source or existing.get("baseline_source")
            baseline_notes = baseline_notes if baseline_notes is not None else existing.get("baseline_notes")

            cur.execute(
                """
                INSERT INTO erp.stock_auto_control_config
                  (company_key, is_enabled, started_at, baseline_reference_id, baseline_source,
                   baseline_notes, enabled_by, enabled_at, disabled_by, disabled_at, raw_payload, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                ON CONFLICT (company_key) DO UPDATE SET
                  is_enabled = EXCLUDED.is_enabled,
                  started_at = EXCLUDED.started_at,
                  baseline_reference_id = EXCLUDED.baseline_reference_id,
                  baseline_source = EXCLUDED.baseline_source,
                  baseline_notes = EXCLUDED.baseline_notes,
                  enabled_by = EXCLUDED.enabled_by,
                  enabled_at = EXCLUDED.enabled_at,
                  disabled_by = EXCLUDED.disabled_by,
                  disabled_at = EXCLUDED.disabled_at,
                  raw_payload = EXCLUDED.raw_payload,
                  updated_at = now()
                RETURNING *
                """,
                (
                    company_key,
                    is_enabled,
                    started_at_val,
                    baseline_reference_id,
                    baseline_source,
                    baseline_notes,
                    enabled_by_val,
                    enabled_at_val,
                    disabled_by_val,
                    disabled_at_val,
                    _product_import_json(raw_payload),
                ),
            )
            saved = dict(cur.fetchone())

    return {
        "ok": True,
        "company_key": company_key,
        "config": _stock_auto_control_public(saved),
    }


# ===========================================================================
# Aplicação REAL de movimentos automáticos de estoque por pedido/separação.
# Backend-only, transacional e idempotente. NÃO está ligado a nenhum evento de
# pedido/separação ainda (teste manual via console). NÃO toca Tiny/Olist.
# Tipos: automatic_reserve / automatic_exit / automatic_cancel_reversal /
# automatic_release_reserve. reference_type='order', reference_id=order.reference_id.
# ===========================================================================

def _ts_ge(a, b) -> bool:
    """a >= b para timestamps, tolerando naive vs aware (naive tratado como UTC)."""
    try:
        if a is None or b is None:
            return False
        if getattr(a, "tzinfo", None) is None:
            a = a.replace(tzinfo=dt.timezone.utc)
        if getattr(b, "tzinfo", None) is None:
            b = b.replace(tzinfo=dt.timezone.utc)
        return a >= b
    except Exception:
        return False


def _order_resolve_quote_items(cur, company_key: str, quote_id: str) -> List[Dict[str, Any]]:
    """Itens do pedido normalizados + resolução em produto local (tiny_product_id
    forte, fallback SKU exato). Mesma estratégia do diagnóstico stock-impact."""
    cur.execute("SELECT * FROM erp.quote_items WHERE quote_id=%s ORDER BY line", (quote_id,))
    rows = [dict(r) for r in cur.fetchall()]
    resolved: List[Dict[str, Any]] = []
    for idx, raw in enumerate(rows, start=1):
        norm = _normalize_quote_item_financials(raw)
        line = _safe_int(raw.get("line"), None) or idx
        input_sku = _clean_str(norm.get("sku"))
        name = _clean_str(norm.get("nome"))
        qty = _safe_float(norm.get("quantity") or norm.get("qty"), 0.0)
        tiny_pid = _clean_str(raw.get("product_id"))
        product = None
        resolve_status = "ok"
        resolve_msg = ""
        if tiny_pid:
            product = _product_get_by_tiny_id(cur, company_key, tiny_pid)
        if not product and input_sku:
            matches = _product_resolve_by_sku(cur, company_key, input_sku)
            if len(matches) == 1:
                product = matches[0]
            elif len(matches) > 1:
                resolve_status = "duplicate"
                resolve_msg = "SKU duplicado na base local; resolver manualmente."
        if not product and resolve_status == "ok":
            resolve_status = "not_found"
            resolve_msg = "Item sem SKU." if not input_sku else "SKU não encontrado na base local."
        resolved.append({
            "line": line,
            "input_sku": input_sku,
            "name": name,
            "quantity": qty,
            "tiny_pid": tiny_pid,
            "product": product,
            "resolve_status": resolve_status,
            "resolve_msg": resolve_msg,
        })
    return resolved


def _order_stock_auto_apply(
    request: Request,
    order_id: str,
    action: str,
    company: str,
    quote_id_q: str,
    tiny_order_id_q: str,
    force: bool,
    reason: str,
    notes: str,
) -> Dict[str, Any]:
    """Núcleo transacional/idempotente das aplicações automáticas.
    action ∈ {reserve, exit, cancel_reversal}. Bloqueia o lote inteiro (rollback)
    se algum item for not_found/duplicate/insufficient/inválido."""
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    created_by = _clean_str(user.get("login") or user.get("email") or user.get("id")) or None

    _ensure_product_stock_movements_table()
    _ensure_stock_auto_control_config_table()

    with _db() as conn:
        with conn.cursor() as cur:
            quote = _order_find_quote(cur, company_key, order_id, quote_id_q, tiny_order_id_q)
            if not quote:
                raise HTTPException(status_code=404, detail="Pedido/orçamento não encontrado nesta empresa.")
            q_quote_id = _clean_str(quote.get("quote_id"))
            q_tiny_order_id = _clean_str(quote.get("tiny_order_id"))
            q_tiny_order_number = _clean_str(quote.get("tiny_order_number"))
            q_internal_status = _clean_str(quote.get("internal_status"))
            q_created_at = quote.get("created_at")
            order_ref = q_tiny_order_id or q_quote_id

            # Marco de controle automático.
            config = _get_stock_auto_control_config(cur, company_key)
            is_enabled = bool(config.get("is_enabled"))
            started_at = config.get("started_at")
            within_marco = is_enabled and started_at is not None and _ts_ge(q_created_at, started_at)
            forced = False
            if not within_marco:
                if force:
                    forced = True
                elif not is_enabled:
                    raise HTTPException(status_code=400, detail="Controle automático local desativado para esta empresa. Ative em Produtos → Controle automático.")
                elif started_at is None:
                    raise HTTPException(status_code=400, detail="Marco de controle automático (started_at) não definido para esta empresa.")
                else:
                    raise HTTPException(status_code=400, detail="Pedido criado antes do marco de controle automático local. Nenhum movimento aplicado.")

            resolved = _order_resolve_quote_items(cur, company_key, q_quote_id)
            if not resolved:
                raise HTTPException(status_code=400, detail="Pedido sem itens para processar.")

            running: Dict[int, Dict[str, float]] = {}
            existing_cache: Dict[int, Dict[str, int]] = {}
            blocking: List[str] = []
            plan: List[Dict[str, Any]] = []
            result_items: List[Dict[str, Any]] = []

            for it in resolved:
                line = it["line"]
                qty = it["quantity"]
                product = it["product"]
                base: Dict[str, Any] = {
                    "line": line,
                    "input_sku": it["input_sku"],
                    "name": it["name"],
                    "quantity": qty,
                    "product_id": None,
                    "resolved_sku": "",
                    "movement_type": None,
                    "status": "ok",
                    "message": "",
                    "stock_before": None,
                    "stock_after": None,
                }

                if it["resolve_status"] != "ok" or not product:
                    base["status"] = it["resolve_status"] if it["resolve_status"] != "ok" else "not_found"
                    base["message"] = it["resolve_msg"]
                    blocking.append(f"Linha {line}: {base['message']} (SKU '{it['input_sku'] or '—'}')")
                    result_items.append(base)
                    continue
                if qty <= 0:
                    base["product_id"] = product.get("id")
                    base["resolved_sku"] = product.get("sku")
                    base["status"] = "invalid_qty"
                    base["message"] = "Quantidade do item inválida (<= 0)."
                    blocking.append(f"Linha {line}: quantidade inválida.")
                    result_items.append(base)
                    continue

                pid = int(product.get("id"))
                if pid not in running:
                    running[pid] = {
                        "physical": _product_stock_number(product.get("stock_physical")),
                        "reserved": _product_stock_number(product.get("stock_reserved")),
                    }
                if pid not in existing_cache:
                    existing_cache[pid] = _order_existing_auto_movements(cur, company_key, pid, order_ref)
                phys = running[pid]["physical"]
                reserved = running[pid]["reserved"]
                existing = existing_cache[pid]
                base["product_id"] = pid
                base["resolved_sku"] = product.get("sku")
                before = {"physical": phys, "reserved": reserved, "available": phys - reserved}
                base["stock_before"] = before

                mv_type = None
                new_phys = phys
                new_res = reserved
                warn = ""

                if action == "reserve":
                    if existing.get("automatic_reserve"):
                        base["status"] = "already_reserved"
                        base["message"] = "Já reservado para este pedido/produto."
                        result_items.append(base)
                        continue
                    if qty > (phys - reserved):
                        base["status"] = "insufficient"
                        base["message"] = "Estoque disponível insuficiente para reservar."
                        blocking.append(f"Linha {line}: {base['message']}")
                        result_items.append(base)
                        continue
                    mv_type = "automatic_reserve"
                    new_res = reserved + qty
                elif action == "exit":
                    if existing.get("automatic_exit"):
                        base["status"] = "already_deducted"
                        base["message"] = "Baixa já aplicada para este pedido/produto."
                        result_items.append(base)
                        continue
                    new_phys = phys - qty
                    if new_phys < 0:
                        base["status"] = "insufficient"
                        base["message"] = "Estoque físico insuficiente para baixa."
                        blocking.append(f"Linha {line}: {base['message']}")
                        result_items.append(base)
                        continue
                    if reserved >= qty:
                        new_res = reserved - qty
                    else:
                        new_res = 0.0
                        warn = "Reserva automática não encontrada ou menor que a quantidade; baixa aplicada diretamente no físico."
                    mv_type = "automatic_exit"
                elif action == "cancel_reversal":
                    if existing.get("automatic_cancel_reversal") or existing.get("automatic_release_reserve"):
                        base["status"] = "already_reversed"
                        base["message"] = "Reversão já aplicada para este pedido/produto."
                        result_items.append(base)
                        continue
                    if existing.get("automatic_exit"):
                        mv_type = "automatic_cancel_reversal"
                        new_phys = phys + qty
                        new_res = reserved
                    elif existing.get("automatic_reserve"):
                        mv_type = "automatic_release_reserve"
                        new_res = reserved - qty if reserved >= qty else 0.0
                        new_phys = phys
                    else:
                        base["status"] = "nothing_to_reverse"
                        base["message"] = "Nada a reverter para este pedido/produto."
                        result_items.append(base)
                        continue
                else:
                    raise HTTPException(status_code=400, detail="Ação automática inválida.")

                new_avail = new_phys - new_res
                if new_phys < 0 or new_res < 0 or new_avail < 0:
                    base["status"] = "insufficient"
                    base["message"] = "Movimento resultaria em saldo inválido."
                    blocking.append(f"Linha {line}: {base['message']}")
                    result_items.append(base)
                    continue

                after = {"physical": new_phys, "reserved": new_res, "available": new_avail}
                base["stock_after"] = after
                base["movement_type"] = mv_type
                if warn:
                    base["message"] = warn
                running[pid]["physical"] = new_phys
                running[pid]["reserved"] = new_res
                plan.append({
                    "product": product,
                    "mv_type": mv_type,
                    "qty": qty,
                    "prev": before,
                    "new": after,
                    "line": line,
                    "input_sku": it["input_sku"],
                    "resolved_sku": product.get("sku"),
                })
                result_items.append(base)

            if blocking:
                raise HTTPException(
                    status_code=400,
                    detail="Bloqueado (nada foi aplicado): " + " | ".join(blocking[:10]),
                )

            # Aplicação (após validar tudo). Transação única -> rollback total em erro.
            applied: List[int] = []
            for p in plan:
                prod = p["product"]
                before = p["prev"]
                after = p["new"]
                calc = {
                    "quantity": p["qty"],
                    "new_physical": after["physical"],
                    "new_reserved": after["reserved"],
                    "new_available": after["available"],
                }
                raw_payload = {
                    "source": "order_stock_auto_apply",
                    "action": action,
                    "quote_id": q_quote_id,
                    "tiny_order_id": q_tiny_order_id,
                    "tiny_order_number": q_tiny_order_number,
                    "reference_id": order_ref,
                    "internal_status": q_internal_status,
                    "line": p["line"],
                    "input_sku": p["input_sku"],
                    "resolved_sku": p["resolved_sku"],
                    "quantity": p["qty"],
                    "stock_before": before,
                    "stock_after": after,
                    "reason": reason,
                    "notes": notes,
                    "forced": forced,
                }
                mv = _product_insert_stock_movement(
                    cur,
                    company_key=company_key,
                    product=prod,
                    movement_type=p["mv_type"],
                    calc=calc,
                    prev_physical=before["physical"],
                    prev_reserved=before["reserved"],
                    prev_available=before["available"],
                    reason=reason,
                    notes=notes,
                    created_by=created_by,
                    raw_payload=raw_payload,
                    reference_type="order",
                    reference_id=order_ref,
                )
                cur.execute(
                    """
                    UPDATE erp.products
                    SET stock_physical=%s, stock_reserved=%s, stock_available=%s, updated_at=now()
                    WHERE id=%s AND company_key=%s
                    """,
                    (after["physical"], after["reserved"], after["available"], int(prod.get("id")), company_key),
                )
                applied.append(int(mv.get("id")))

    applied_count = len(applied)
    skipped_count = sum(
        1 for r in result_items
        if r["status"] in ("already_reserved", "already_deducted", "already_reversed", "nothing_to_reverse")
    )
    movement_type_label = {
        "reserve": "automatic_reserve",
        "exit": "automatic_exit",
        "cancel_reversal": "automatic_cancel_reversal",
    }[action]
    return {
        "ok": True,
        "company_key": company_key,
        "order": {
            "quote_id": q_quote_id,
            "tiny_order_id": q_tiny_order_id,
            "tiny_order_number": q_tiny_order_number,
            "internal_status": q_internal_status,
            "reference_id": order_ref,
        },
        "action": action,
        "movement_type": movement_type_label,
        "forced": forced,
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "already_applied": applied_count == 0 and skipped_count > 0,
        "movement_ids": applied,
        "items": result_items,
    }


async def _order_stock_apply_body(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


@app.post("/api/admin/orders/{order_id}/stock-reserve")
@app.post("/admin/orders/{order_id}/stock-reserve")
async def admin_order_stock_reserve(
    request: Request, order_id: str, company: str = "", quote_id: str = "", tiny_order_id: str = "", force: bool = False
):
    body = await _order_stock_apply_body(request)
    if body.get("force") is not None:
        force = bool(body.get("force"))
    return _order_stock_auto_apply(
        request, order_id, "reserve",
        _clean_str(body.get("company")) or company,
        _clean_str(body.get("quote_id")) or quote_id,
        _clean_str(body.get("tiny_order_id")) or tiny_order_id,
        force, _clean_str(body.get("reason")), _clean_str(body.get("notes")),
    )


@app.post("/api/admin/orders/{order_id}/stock-exit")
@app.post("/admin/orders/{order_id}/stock-exit")
async def admin_order_stock_exit(
    request: Request, order_id: str, company: str = "", quote_id: str = "", tiny_order_id: str = "", force: bool = False
):
    body = await _order_stock_apply_body(request)
    if body.get("force") is not None:
        force = bool(body.get("force"))
    return _order_stock_auto_apply(
        request, order_id, "exit",
        _clean_str(body.get("company")) or company,
        _clean_str(body.get("quote_id")) or quote_id,
        _clean_str(body.get("tiny_order_id")) or tiny_order_id,
        force, _clean_str(body.get("reason")), _clean_str(body.get("notes")),
    )


@app.post("/api/admin/orders/{order_id}/stock-cancel-reversal")
@app.post("/admin/orders/{order_id}/stock-cancel-reversal")
async def admin_order_stock_cancel_reversal(
    request: Request, order_id: str, company: str = "", quote_id: str = "", tiny_order_id: str = "", force: bool = False
):
    body = await _order_stock_apply_body(request)
    if body.get("force") is not None:
        force = bool(body.get("force"))
    return _order_stock_auto_apply(
        request, order_id, "cancel_reversal",
        _clean_str(body.get("company")) or company,
        _clean_str(body.get("quote_id")) or quote_id,
        _clean_str(body.get("tiny_order_id")) or tiny_order_id,
        force, _clean_str(body.get("reason")), _clean_str(body.get("notes")),
    )


def _catalog_images_dir() -> str:
    image_dir = os.path.abspath(os.path.join(APP_ROOT, "storage", "catalog-images"))
    os.makedirs(image_dir, exist_ok=True)
    return image_dir


@app.get("/api/admin/catalog/images")
@app.get("/admin/catalog/images")
def admin_catalog_list_images(request: Request):
    _catalog_require_admin(request)
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
    image_dir = _catalog_images_dir()
    items: List[Dict[str, Any]] = []
    with os.scandir(image_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext not in allowed_exts:
                continue
            stat = entry.stat()
            items.append(
                {
                    "filename": entry.name,
                    "url": f"/catalog-images/{quote(entry.name)}",
                    "size": int(stat.st_size),
                    "modified_at": dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc).isoformat(),
                }
            )
    items.sort(key=lambda item: item["filename"].lower())
    return {"ok": True, "items": items}


def _catalog_safe_image_filename(filename: str) -> str:
    raw = os.path.basename(_clean_str(filename or "catalog-image"))
    name, ext = os.path.splitext(raw)
    ext = ext.lower()
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    safe = []
    previous_dash = False
    for char in normalized.lower():
        if char.isalnum() or char in {"_", "-"}:
            safe.append(char)
            previous_dash = False
        elif not previous_dash:
            safe.append("-")
            previous_dash = True
    stem = "".join(safe).strip("-._") or "catalog-image"
    return f"{stem}{ext}"


def _catalog_unique_image_path(directory: str, filename: str) -> tuple[str, str]:
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 2
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}-{counter}{ext}"
        counter += 1
    final_path = os.path.abspath(os.path.join(directory, candidate))
    root = os.path.abspath(directory)
    if not (final_path == root or final_path.startswith(root + os.sep)):
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
    return candidate, final_path


@app.post("/api/admin/catalog/images/upload")
@app.post("/admin/catalog/images/upload")
async def admin_catalog_upload_image(request: Request, file: UploadFile = File(...)):
    _catalog_require_admin(request)
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    content_type = _clean_str(file.content_type).lower()
    original_name = _clean_str(file.filename or "")
    safe_name = _catalog_safe_image_filename(original_name)
    ext = os.path.splitext(safe_name)[1].lower()
    expected_kind = _IMAGE_EXT_TO_KIND.get(ext)
    if content_type not in allowed_types or not expected_kind:
        raise HTTPException(status_code=400, detail="Envie uma imagem JPG, PNG ou WEBP.")
    image_dir = _catalog_images_dir()
    filename, final_path = _catalog_unique_image_path(image_dir, safe_name)
    max_bytes = 10 * 1024 * 1024
    chunk_size = 1024 * 1024
    total = 0
    try:
        first = await file.read(chunk_size)
        # Assinatura tem que existir E bater com a extensão declarada (anti-polyglot).
        if _sniff_image_kind(first) != expected_kind:
            raise HTTPException(status_code=400, detail="Arquivo não é uma imagem válida (assinatura não confere).")
        with open(final_path, "wb") as out:
            chunk = first
            while chunk:
                total += len(chunk)
                if total > max_bytes:
                    out.close()
                    try:
                        os.remove(final_path)
                    except OSError:
                        pass
                    raise HTTPException(status_code=400, detail="Imagem maior que 10 MB.")
                out.write(chunk)
                chunk = await file.read(chunk_size)
    finally:
        await file.close()
    return {"ok": True, "filename": filename, "url": f"/catalog-images/{filename}"}


@app.post("/api/admin/catalog/products/sync-stock")
@app.post("/admin/catalog/products/sync-stock")
async def admin_catalog_sync_stock(request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    product_ids = [int(x) for x in (body.get("product_ids") or []) if _safe_int(x, None)]
    if not product_ids:
        raise HTTPException(status_code=400, detail="Informe produtos.")
    _ensure_product_catalog_tables()
    updated = 0
    errors = 0
    items: List[Dict[str, Any]] = []
    tiny = _tiny_for_company(company_key)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, company_key, tiny_product_id, sku, stock_available
                FROM erp.product_catalog
                WHERE company_key=%s AND id = ANY(%s)
                ORDER BY id
                """,
                (company_key, product_ids),
            )
            products = [dict(r) for r in cur.fetchall()]
            for product in products:
                product_id = product.get("id")
                tiny_product_id = _safe_int(product.get("tiny_product_id"), None)
                if not tiny_product_id:
                    errors += 1
                    items.append({"id": product_id, "ok": False, "error": "Produto sem ID Tiny para consultar estoque."})
                    continue
                try:
                    response = tiny.obter_estoque_produto(tiny_product_id)
                    stock_available = _catalog_extract_tiny_stock_available(response)
                    if stock_available is None:
                        errors += 1
                        items.append({"id": product_id, "ok": False, "error": "Tiny não retornou estoque disponível."})
                        continue
                    cur.execute(
                        """
                        UPDATE erp.product_catalog
                        SET stock_available=%s,
                            stock_synced_at=now(),
                            updated_at=now()
                        WHERE id=%s AND company_key=%s
                        """,
                        (stock_available, product_id, company_key),
                    )
                    updated += int(cur.rowcount or 0)
                    items.append({"id": product_id, "ok": True, "stock_available": stock_available})
                except TinyAPIError as e:
                    errors += 1
                    items.append({"id": product_id, "ok": False, "error": str(e)})
                except Exception as e:
                    errors += 1
                    items.append({"id": product_id, "ok": False, "error": str(e)})
    return {"ok": errors == 0, "company_key": company_key, "updated": updated, "errors": errors, "items": items}


@app.put("/api/admin/catalog/products/bulk-update")
@app.put("/admin/catalog/products/bulk-update")
async def admin_catalog_bulk_update_products(request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    payload_items = body.get("items") or []
    if not isinstance(payload_items, list) or not payload_items:
        raise HTTPException(status_code=400, detail="Informe produtos para atualizar.")
    _ensure_product_catalog_tables()
    updated = 0
    with _db() as conn:
        with conn.cursor() as cur:
            for item in payload_items:
                if not isinstance(item, dict):
                    continue
                product_id = _safe_int(item.get("id"), None)
                if not product_id:
                    continue
                price_mode = _clean_str(item.get("price_mode") or "custom").lower()
                if price_mode not in {"custom", "table"}:
                    price_mode = "custom"
                price_table_id = _safe_int(item.get("price_table_id"), None) if price_mode == "table" else None
                if price_mode == "table" and price_table_id:
                    cur.execute(
                        "SELECT id FROM erp.catalog_price_tables WHERE id=%s AND company_key=%s AND active=TRUE",
                        (price_table_id, company_key),
                    )
                    if not cur.fetchone():
                        raise HTTPException(status_code=400, detail="Tabela de preço inválida para a empresa.")
                cur.execute(
                    """
                    UPDATE erp.product_catalog
                    SET full_price_percent=%s,
                        full_price_value=%s,
                        billed_price_percent=%s,
                        billed_price_value=%s,
                        cash_price_percent=%s,
                        cash_price_value=%s,
                        catalog_active=%s,
                        catalog_featured=%s,
                        catalog_order=%s,
                        price_mode=%s,
                        price_table_id=%s,
                        updated_at=now()
                    WHERE id=%s AND company_key=%s
                    """,
                    (
                        _safe_float(item.get("full_price_percent"), None),
                        _safe_float(item.get("full_price_value"), None),
                        _safe_float(item.get("billed_price_percent"), None),
                        _safe_float(item.get("billed_price_value"), None),
                        _safe_float(item.get("cash_price_percent"), None),
                        _safe_float(item.get("cash_price_value"), None),
                        bool(item.get("catalog_active", False)),
                        bool(item.get("catalog_featured", False)),
                        _safe_int(item.get("catalog_order"), None),
                        price_mode,
                        price_table_id,
                        product_id,
                        company_key,
                    ),
                )
                updated += int(cur.rowcount or 0)
    return {"ok": True, "company_key": company_key, "updated": updated}


@app.get("/api/admin/catalog/price-tables")
@app.get("/admin/catalog/price-tables")
def admin_catalog_price_tables(request: Request, company: str = "parton"):
    _catalog_require_admin(request)
    company_key = _company_key(company)
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM erp.catalog_price_tables
                WHERE company_key=%s
                ORDER BY active DESC, is_default DESC, LOWER(name), id
                """,
                (company_key,),
            )
            items = [_catalog_price_table_public(dict(r)) for r in cur.fetchall()]
    return {"ok": True, "company_key": company_key, "items": items}


@app.post("/api/admin/catalog/price-tables")
@app.post("/admin/catalog/price-tables")
async def admin_catalog_create_price_table(request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    _ensure_product_catalog_tables()
    name = _clean_str(body.get("name")) or "Tabela de preço"
    mode = _clean_str(body.get("mode") or "percent").lower()
    if mode not in {"percent", "custom"}:
        mode = "percent"
    base_field = _clean_str(body.get("base_field") or "price_tiny") or "price_tiny"
    is_default = bool(body.get("is_default", False))
    with _db() as conn:
        with conn.cursor() as cur:
            if is_default:
                cur.execute("UPDATE erp.catalog_price_tables SET is_default=FALSE WHERE company_key=%s", (company_key,))
            cur.execute(
                """
                INSERT INTO erp.catalog_price_tables (
                  company_key, name, mode, base_field,
                  full_price_percent, billed_price_percent, cash_price_percent,
                  active, is_default
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    company_key,
                    name,
                    mode,
                    base_field,
                    _safe_float(body.get("full_price_percent"), None),
                    _safe_float(body.get("billed_price_percent"), None),
                    _safe_float(body.get("cash_price_percent"), None),
                    bool(body.get("active", True)),
                    is_default,
                ),
            )
            row = cur.fetchone()
    return {"ok": True, "item": _catalog_price_table_public(dict(row))}


@app.put("/api/admin/catalog/price-tables/{table_id}")
@app.put("/admin/catalog/price-tables/{table_id}")
async def admin_catalog_update_price_table(table_id: int, request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    _ensure_product_catalog_tables()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    name = _clean_str(body.get("name")) or "Tabela de preço"
    mode = _clean_str(body.get("mode") or "percent").lower()
    if mode not in {"percent", "custom"}:
        mode = "percent"
    is_default = bool(body.get("is_default", False))
    with _db() as conn:
        with conn.cursor() as cur:
            if is_default:
                cur.execute(
                    "UPDATE erp.catalog_price_tables SET is_default=FALSE WHERE company_key=%s AND id<>%s",
                    (company_key, int(table_id)),
                )
            cur.execute(
                """
                UPDATE erp.catalog_price_tables
                SET name=%s,
                    mode=%s,
                    base_field=%s,
                    full_price_percent=%s,
                    billed_price_percent=%s,
                    cash_price_percent=%s,
                    active=%s,
                    is_default=%s,
                    updated_at=now()
                WHERE id=%s AND company_key=%s
                RETURNING *
                """,
                (
                    name,
                    mode,
                    _clean_str(body.get("base_field") or "price_tiny") or "price_tiny",
                    _safe_float(body.get("full_price_percent"), None),
                    _safe_float(body.get("billed_price_percent"), None),
                    _safe_float(body.get("cash_price_percent"), None),
                    bool(body.get("active", True)),
                    is_default,
                    int(table_id),
                    company_key,
                ),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tabela de preço não encontrada.")
    return {"ok": True, "item": _catalog_price_table_public(dict(row))}


@app.post("/api/admin/catalog/products/apply-price-table")
@app.post("/admin/catalog/products/apply-price-table")
async def admin_catalog_apply_price_table(request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    price_mode = _clean_str(body.get("price_mode") or ("table" if body.get("price_table_id") else "custom")).lower()
    table_id = _safe_int(body.get("price_table_id"), None)
    product_ids = [int(x) for x in (body.get("product_ids") or []) if _safe_int(x, None)]
    if price_mode not in {"table", "custom"}:
        raise HTTPException(status_code=400, detail="Modo de preço inválido.")
    if not product_ids:
        raise HTTPException(status_code=400, detail="Informe produtos.")
    if price_mode == "table" and not table_id:
        raise HTTPException(status_code=400, detail="Informe a tabela de preço.")
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            if price_mode == "table":
                cur.execute(
                    "SELECT id FROM erp.catalog_price_tables WHERE id=%s AND company_key=%s AND active=TRUE",
                    (table_id, company_key),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Tabela de preço ativa não encontrada.")
            cur.execute(
                """
                UPDATE erp.product_catalog
                SET price_mode=%s,
                    price_table_id=%s,
                    updated_at=now()
                WHERE company_key=%s AND id = ANY(%s)
                """,
                (price_mode, table_id if price_mode == "table" else None, company_key, product_ids),
            )
            updated = cur.rowcount
    return {"ok": True, "company_key": company_key, "price_mode": price_mode, "updated": int(updated or 0)}


@app.get("/api/admin/catalog/campaigns")
@app.get("/admin/catalog/campaigns")
def admin_catalog_campaigns(request: Request, company: str = "parton"):
    _catalog_require_admin(request)
    company_key = _company_key(company)
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cc.*, COUNT(cci.id) AS product_count
                FROM erp.catalog_campaigns cc
                LEFT JOIN erp.catalog_campaign_items cci ON cci.campaign_id = cc.id
                WHERE cc.company_key=%s
                GROUP BY cc.id
                ORDER BY cc.active DESC, cc.start_date DESC, cc.id DESC
                """,
                (company_key,),
            )
            items = [_catalog_campaign_public(dict(r)) for r in cur.fetchall()]
    return {"ok": True, "company_key": company_key, "items": items}


@app.post("/api/admin/catalog/campaigns")
@app.post("/admin/catalog/campaigns")
async def admin_catalog_create_campaign(request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    _ensure_product_catalog_tables()
    today = dt.datetime.now().date().isoformat()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.catalog_campaigns (
                  company_key, name, description, start_date, end_date,
                  discount_percent, price_table_id, active
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    company_key,
                    _clean_str(body.get("name")) or "Campanha",
                    _clean_str(body.get("description")),
                    _clean_str(body.get("start_date")) or today,
                    _clean_str(body.get("end_date")) or today,
                    _safe_float(body.get("discount_percent"), None),
                    _safe_int(body.get("price_table_id"), None),
                    bool(body.get("active", True)),
                ),
            )
            row = cur.fetchone()
    return {"ok": True, "item": _catalog_campaign_public(dict(row))}


@app.put("/api/admin/catalog/campaigns/{campaign_id}")
@app.put("/admin/catalog/campaigns/{campaign_id}")
async def admin_catalog_update_campaign(campaign_id: int, request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    _ensure_product_catalog_tables()
    today = dt.datetime.now().date().isoformat()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.catalog_campaigns
                SET name=%s,
                    description=%s,
                    start_date=%s,
                    end_date=%s,
                    discount_percent=%s,
                    price_table_id=%s,
                    active=%s,
                    updated_at=now()
                WHERE id=%s AND company_key=%s
                RETURNING *
                """,
                (
                    _clean_str(body.get("name")) or "Campanha",
                    _clean_str(body.get("description")),
                    _clean_str(body.get("start_date")) or today,
                    _clean_str(body.get("end_date")) or today,
                    _safe_float(body.get("discount_percent"), None),
                    _safe_int(body.get("price_table_id"), None),
                    bool(body.get("active", True)),
                    int(campaign_id),
                    company_key,
                ),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Campanha não encontrada.")
    return {"ok": True, "item": _catalog_campaign_public(dict(row))}


@app.get("/api/admin/catalog/campaigns/{campaign_id}/items")
@app.get("/admin/catalog/campaigns/{campaign_id}/items")
def admin_catalog_campaign_items(campaign_id: int, request: Request, company: str = "parton"):
    _catalog_require_admin(request)
    company_key = _company_key(company)
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM erp.catalog_campaigns WHERE id=%s AND company_key=%s", (int(campaign_id), company_key))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Campanha não encontrada.")
            cur.execute(
                """
                SELECT cci.*, pc.sku, pc.name_tiny, pc.catalog_description
                FROM erp.catalog_campaign_items cci
                JOIN erp.product_catalog pc ON pc.id = cci.product_catalog_id
                WHERE cci.campaign_id=%s AND pc.company_key=%s
                ORDER BY LOWER(COALESCE(pc.catalog_description, pc.name_tiny, pc.sku, '')), pc.id
                """,
                (int(campaign_id), company_key),
            )
            items = [dict(r) for r in cur.fetchall()]
    return {"ok": True, "company_key": company_key, "campaign_id": int(campaign_id), "items": items}


@app.put("/api/admin/catalog/campaigns/{campaign_id}/items")
@app.put("/admin/catalog/campaigns/{campaign_id}/items")
async def admin_catalog_save_campaign_items(campaign_id: int, request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    product_ids = [int(x) for x in (body.get("product_ids") or []) if _safe_int(x, None)]
    item_payloads = body.get("items") if isinstance(body.get("items"), list) else []
    custom_by_product = {}
    for item in item_payloads:
        if not isinstance(item, dict):
            continue
        pid = _safe_int(item.get("product_catalog_id"), None)
        if pid:
            custom_by_product[int(pid)] = item
            if int(pid) not in product_ids:
                product_ids.append(int(pid))
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM erp.catalog_campaigns WHERE id=%s AND company_key=%s", (int(campaign_id), company_key))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Campanha não encontrada.")
            cur.execute("DELETE FROM erp.catalog_campaign_items WHERE campaign_id=%s", (int(campaign_id),))
            inserted = 0
            for product_id in product_ids:
                cur.execute("SELECT id FROM erp.product_catalog WHERE id=%s AND company_key=%s", (int(product_id), company_key))
                if not cur.fetchone():
                    continue
                custom = custom_by_product.get(int(product_id), {})
                cur.execute(
                    """
                    INSERT INTO erp.catalog_campaign_items (
                      campaign_id, product_catalog_id,
                      custom_full_price_value, custom_billed_price_value, custom_cash_price_value
                    )
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (
                        int(campaign_id),
                        int(product_id),
                        _safe_float(custom.get("custom_full_price_value"), None),
                        _safe_float(custom.get("custom_billed_price_value"), None),
                        _safe_float(custom.get("custom_cash_price_value"), None),
                    ),
                )
                inserted += 1
    return {"ok": True, "company_key": company_key, "campaign_id": int(campaign_id), "saved": inserted}


@app.get("/api/admin/catalog/layouts")
@app.get("/admin/catalog/layouts")
def admin_catalog_layouts(request: Request, company: str = "parton"):
    _catalog_require_admin(request)
    company_key = _company_key(company)
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  cl.*,
                  COALESCE(item_counts.total_items, 0) AS item_count,
                  COALESCE(item_counts.selected_items, 0) AS selected_count
                FROM erp.catalog_layouts cl
                LEFT JOIN LATERAL (
                  SELECT
                    COUNT(*) AS total_items,
                    COUNT(*) FILTER (WHERE selected = TRUE) AS selected_items
                  FROM erp.catalog_layout_items cli
                  WHERE cli.layout_id = cl.id
                ) item_counts ON TRUE
                WHERE cl.company_key=%s
                ORDER BY cl.active DESC, COALESCE(cl.updated_at, cl.created_at) DESC, cl.id DESC
                """,
                (company_key,),
            )
            items = [_catalog_layout_public(dict(r)) for r in cur.fetchall()]
    return {"ok": True, "company_key": company_key, "items": items}


@app.post("/api/admin/catalog/layouts")
@app.post("/admin/catalog/layouts")
async def admin_catalog_create_layout(request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    company_key = _company_key(body.get("company_key") or body.get("company") or "parton")
    _ensure_product_catalog_tables()
    name = _clean_str(body.get("name"))
    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome da configuração.")
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.catalog_layouts (
                  company_key, name, title, subtitle, notes, valid_until,
                  use_active_campaigns, show_full_price, show_billed_price, show_cash_price,
                  show_sku, show_tags, show_stock, show_without_image,
                  only_active_products, active
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    company_key,
                    name,
                    _clean_str(body.get("title")) or None,
                    _clean_str(body.get("subtitle")) or None,
                    _clean_str(body.get("notes")) or None,
                    _catalog_layout_parse_date(body.get("valid_until")),
                    bool(body.get("use_active_campaigns", True)),
                    bool(body.get("show_full_price", True)),
                    bool(body.get("show_billed_price", True)),
                    bool(body.get("show_cash_price", True)),
                    bool(body.get("show_sku", True)),
                    bool(body.get("show_tags", False)),
                    bool(body.get("show_stock", False)),
                    bool(body.get("show_without_image", True)),
                    bool(body.get("only_active_products", True)),
                    bool(body.get("active", True)),
                ),
            )
            row = cur.fetchone()
    return {"ok": True, "item": _catalog_layout_public(dict(row))}


@app.get("/api/admin/catalog/layouts/{layout_id}")
@app.get("/admin/catalog/layouts/{layout_id}")
def admin_catalog_get_layout(layout_id: int, request: Request):
    _catalog_require_admin(request)
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.catalog_layouts WHERE id=%s", (int(layout_id),))
            layout_row = cur.fetchone()
            if not layout_row:
                raise HTTPException(status_code=404, detail="Configuração não encontrada.")
            layout = dict(layout_row)
            company_key = _clean_str(layout.get("company_key"))
            cur.execute(
                """
                SELECT
                  cli.*,
                  pc.sku,
                  pc.name_tiny,
                  pc.catalog_title,
                  pc.catalog_description,
                  pc.catalog_image_url,
                  pc.catalog_image_path,
                  pc.catalog_image_filename,
                  pc.image_url_tiny,
                  pc.catalog_active,
                  pc.catalog_featured
                FROM erp.catalog_layout_items cli
                JOIN erp.product_catalog pc
                  ON pc.id = cli.product_catalog_id
                 AND pc.company_key = %s
                WHERE cli.layout_id = %s
                ORDER BY COALESCE(cli.sort_order, 999999), cli.id
                """,
                (company_key, int(layout_id)),
            )
            items = [dict(r) for r in cur.fetchall()]
    selected_product_ids = [int(item.get("product_catalog_id")) for item in items if item.get("selected")]
    return {
        "ok": True,
        "item": _catalog_layout_public(layout),
        "items": items,
        "selected_product_ids": selected_product_ids,
    }


@app.put("/api/admin/catalog/layouts/{layout_id}")
@app.put("/admin/catalog/layouts/{layout_id}")
async def admin_catalog_update_layout(layout_id: int, request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.catalog_layouts WHERE id=%s", (int(layout_id),))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Configuração não encontrada.")
            existing_row = dict(existing)
            company_key = _company_key(body.get("company_key") or body.get("company") or existing_row.get("company_key") or "parton")
            if _company_key(existing_row.get("company_key")) != company_key:
                raise HTTPException(status_code=400, detail="A configuração pertence a outra empresa.")
            name = _clean_str(body.get("name"))
            if not name:
                raise HTTPException(status_code=400, detail="Informe o nome da configuração.")
            cur.execute(
                """
                UPDATE erp.catalog_layouts
                SET name=%s,
                    title=%s,
                    subtitle=%s,
                    notes=%s,
                    valid_until=%s,
                    use_active_campaigns=%s,
                    show_full_price=%s,
                    show_billed_price=%s,
                    show_cash_price=%s,
                    show_sku=%s,
                    show_tags=%s,
                    show_stock=%s,
                    show_without_image=%s,
                    only_active_products=%s,
                    active=%s,
                    updated_at=now()
                WHERE id=%s AND company_key=%s
                RETURNING *
                """,
                (
                    name,
                    _clean_str(body.get("title")) or None,
                    _clean_str(body.get("subtitle")) or None,
                    _clean_str(body.get("notes")) or None,
                    _catalog_layout_parse_date(body.get("valid_until")),
                    bool(body.get("use_active_campaigns", existing_row.get("use_active_campaigns", True))),
                    bool(body.get("show_full_price", existing_row.get("show_full_price", True))),
                    bool(body.get("show_billed_price", existing_row.get("show_billed_price", True))),
                    bool(body.get("show_cash_price", existing_row.get("show_cash_price", True))),
                    bool(body.get("show_sku", existing_row.get("show_sku", True))),
                    bool(body.get("show_tags", existing_row.get("show_tags", False))),
                    bool(body.get("show_stock", existing_row.get("show_stock", False))),
                    bool(body.get("show_without_image", existing_row.get("show_without_image", True))),
                    bool(body.get("only_active_products", existing_row.get("only_active_products", True))),
                    bool(body.get("active", existing_row.get("active", True))),
                    int(layout_id),
                    company_key,
                ),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Configuração não encontrada.")
    return {"ok": True, "item": _catalog_layout_public(dict(row))}


@app.put("/api/admin/catalog/layouts/{layout_id}/items")
@app.put("/admin/catalog/layouts/{layout_id}/items")
async def admin_catalog_save_layout_items(layout_id: int, request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    _ensure_product_catalog_tables()
    payload_items = body.get("items") if isinstance(body.get("items"), list) else []
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.catalog_layouts WHERE id=%s", (int(layout_id),))
            layout_row = cur.fetchone()
            if not layout_row:
                raise HTTPException(status_code=404, detail="Configuração não encontrada.")
            layout = dict(layout_row)
            company_key = _company_key(body.get("company_key") or body.get("company") or layout.get("company_key") or "parton")
            if _company_key(layout.get("company_key")) != company_key:
                raise HTTPException(status_code=400, detail="A configuração pertence a outra empresa.")
            saved = 0
            for item in payload_items:
                if not isinstance(item, dict):
                    continue
                product_id = _safe_int(item.get("product_catalog_id"), None)
                if not product_id:
                    continue
                cur.execute(
                    "SELECT id FROM erp.product_catalog WHERE id=%s AND company_key=%s",
                    (int(product_id), company_key),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail="Produto inválido para a empresa da configuração.")
                cur.execute(
                    """
                    INSERT INTO erp.catalog_layout_items (
                      layout_id, product_catalog_id, sort_order, selected, updated_at
                    )
                    VALUES (%s,%s,%s,%s,now())
                    ON CONFLICT (layout_id, product_catalog_id)
                    DO UPDATE SET sort_order=EXCLUDED.sort_order,
                                  selected=EXCLUDED.selected,
                                  updated_at=now()
                    """,
                    (
                        int(layout_id),
                        int(product_id),
                        _safe_int(item.get("sort_order"), None),
                        bool(item.get("selected", True)),
                    ),
                )
                saved += 1
    return {"ok": True, "layout_id": int(layout_id), "saved": saved}


@app.get("/api/admin/catalog/layouts/{layout_id}/preview")
@app.get("/admin/catalog/layouts/{layout_id}/preview")
def admin_catalog_layout_preview(layout_id: int, request: Request):
    _catalog_require_admin(request)
    _ensure_product_catalog_tables()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.catalog_layouts WHERE id=%s", (int(layout_id),))
            layout_row = cur.fetchone()
            if not layout_row:
                raise HTTPException(status_code=404, detail="Configuração não encontrada.")
            layout = dict(layout_row)
            company_key = _clean_str(layout.get("company_key"))
            where = [
                "pc.company_key=%s",
                "li.layout_id=%s",
                "li.selected = TRUE",
            ]
            params: List[Any] = [company_key, company_key, int(layout_id)]
            if bool(layout.get("only_active_products", True)):
                where.append("pc.catalog_active = TRUE")
            if not bool(layout.get("show_without_image", True)):
                where.append("(COALESCE(pc.catalog_image_path, pc.catalog_image_url, pc.image_url_tiny, '') <> '')")
            where_sql = " AND ".join(where)
            cur.execute(
                f"""
                SELECT
                  pc.*,
                  cpt.name AS price_table_name,
                  cpt.mode AS price_table_mode,
                  cpt.base_field AS table_base_field,
                  cpt.active AS price_table_active,
                  cpt.full_price_percent AS table_full_price_percent,
                  cpt.billed_price_percent AS table_billed_price_percent,
                  cpt.cash_price_percent AS table_cash_price_percent,
                  latest.raw AS latest_product_raw,
                  campaign.id AS campaign_id,
                  campaign.name AS campaign_name,
                  campaign.discount_percent AS campaign_discount_percent,
                  campaign.custom_full_price_value AS campaign_custom_full_price_value,
                  campaign.custom_billed_price_value AS campaign_custom_billed_price_value,
                  campaign.custom_cash_price_value AS campaign_custom_cash_price_value,
                  li.sort_order AS layout_sort_order
                FROM erp.catalog_layout_items li
                JOIN erp.product_catalog pc
                  ON pc.id = li.product_catalog_id
                 AND pc.company_key = %s
                LEFT JOIN erp.catalog_price_tables cpt
                  ON cpt.id = pc.price_table_id
                 AND cpt.company_key = pc.company_key
                LEFT JOIN LATERAL (
                  SELECT qi.raw
                  FROM erp.quote_items qi
                  JOIN erp.quotes q ON q.quote_id = qi.quote_id
                  WHERE q.company_key = pc.company_key
                    AND (
                      (pc.tiny_product_id IS NOT NULL AND CAST(qi.product_id AS TEXT) = pc.tiny_product_id)
                      OR (pc.sku IS NOT NULL AND LOWER(COALESCE(qi.sku_snapshot, qi.raw->>'sku', qi.raw->>'codigo', '')) = LOWER(pc.sku))
                    )
                  ORDER BY q.updated_at DESC NULLS LAST
                  LIMIT 1
                ) latest ON TRUE
                LEFT JOIN LATERAL (
                  SELECT
                    cc.id,
                    cc.name,
                    cc.discount_percent,
                    cci.custom_full_price_value,
                    cci.custom_billed_price_value,
                    cci.custom_cash_price_value
                  FROM erp.catalog_campaign_items cci
                  JOIN erp.catalog_campaigns cc ON cc.id = cci.campaign_id
                  WHERE cci.product_catalog_id = pc.id
                    AND cc.company_key = pc.company_key
                    AND cc.active = TRUE
                    AND CURRENT_DATE BETWEEN cc.start_date AND cc.end_date
                  ORDER BY cc.start_date DESC, cc.id DESC
                  LIMIT 1
                ) campaign ON TRUE
                WHERE {where_sql}
                ORDER BY COALESCE(li.sort_order, 999999), LOWER(COALESCE(pc.catalog_title, pc.name_tiny, pc.sku, '')), pc.id
                """,
                params,
            )
            raw_items = [dict(r) for r in cur.fetchall()]
    items: List[Dict[str, Any]] = []
    use_active_campaigns = bool(layout.get("use_active_campaigns", True))
    for item in raw_items:
        if not use_active_campaigns:
            item["campaign_id"] = None
        public_item = _catalog_row_public(item)
        public_item["layout_sort_order"] = item.get("layout_sort_order")
        items.append(public_item)
    return {
        "ok": True,
        "layout": _catalog_layout_public(layout),
        "items": items,
        "selected_product_ids": [int(item.get("id")) for item in items],
    }


@app.put("/api/admin/catalog/products/{product_id}")
@app.put("/admin/catalog/products/{product_id}")
async def admin_catalog_update_product(product_id: int, request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    _ensure_product_catalog_tables()
    editable = {
        "catalog_title": _clean_str(body.get("catalog_title")),
        "catalog_description": _clean_str(body.get("catalog_description")),
        "catalog_benefits": _clean_str(body.get("catalog_benefits")),
        "catalog_tags": _clean_str(body.get("catalog_tags")),
        "catalog_price": _safe_float(body.get("catalog_price"), None),
        "catalog_image_url": _clean_str(body.get("catalog_image_url")),
        "catalog_image_path": _clean_str(body.get("catalog_image_path")),
        "catalog_image_filename": _clean_str(body.get("catalog_image_filename")),
        "full_price_percent": _safe_float(body.get("full_price_percent"), None),
        "full_price_value": _safe_float(body.get("full_price_value"), None),
        "billed_price_percent": _safe_float(body.get("billed_price_percent"), None),
        "billed_price_value": _safe_float(body.get("billed_price_value"), None),
        "cash_price_percent": _safe_float(body.get("cash_price_percent"), None),
        "cash_price_value": _safe_float(body.get("cash_price_value"), None),
        "price_mode": _clean_str(body.get("price_mode") or "custom").lower(),
        "price_table_id": _safe_int(body.get("price_table_id"), None),
        "catalog_active": bool(body.get("catalog_active", False)),
        "catalog_featured": bool(body.get("catalog_featured", False)),
        "catalog_order": _safe_int(body.get("catalog_order"), None),
        "internal_notes": _clean_str(body.get("internal_notes")),
    }
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.product_catalog
                SET catalog_title=%s,
                    catalog_description=%s,
                    catalog_benefits=%s,
                    catalog_tags=%s,
                    catalog_price=%s,
                    catalog_image_url=%s,
                    catalog_image_path=%s,
                    catalog_image_filename=%s,
                    full_price_percent=%s,
                    full_price_value=%s,
                    billed_price_percent=%s,
                    billed_price_value=%s,
                    cash_price_percent=%s,
                    cash_price_value=%s,
                    price_mode=%s,
                    price_table_id=%s,
                    catalog_active=%s,
                    catalog_featured=%s,
                    catalog_order=%s,
                    internal_notes=%s,
                    updated_at=now()
                WHERE id=%s
                RETURNING *
                """,
                (
                    editable["catalog_title"],
                    editable["catalog_description"],
                    editable["catalog_benefits"],
                    editable["catalog_tags"],
                    editable["catalog_price"],
                    editable["catalog_image_url"],
                    editable["catalog_image_path"],
                    editable["catalog_image_filename"],
                    editable["full_price_percent"],
                    editable["full_price_value"],
                    editable["billed_price_percent"],
                    editable["billed_price_value"],
                    editable["cash_price_percent"],
                    editable["cash_price_value"],
                    editable["price_mode"] if editable["price_mode"] in {"custom", "table"} else "custom",
                    editable["price_table_id"],
                    editable["catalog_active"],
                    editable["catalog_featured"],
                    editable["catalog_order"],
                    editable["internal_notes"],
                    int(product_id),
                ),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Produto de catálogo não encontrado.")
    return {"ok": True, "item": _catalog_row_public(dict(row))}


@app.get("/api/admin/users/audit")
@app.get("/admin/users/audit")
def admin_list_user_audit(request: Request, limit: int = Query(default=120, ge=1, le=500)):
    user = _require_auth_user(request)
    if _clean_str(user.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM erp.user_audit_log
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]

    items = []
    for row in rows:
        before_data = _from_json(row.get("before_data"), {}) or {}
        after_data = _from_json(row.get("after_data"), {}) or {}
        items.append(
            {
                "id": row.get("id"),
                "action": row.get("action"),
                "target_email": row.get("target_login"),
                "changed_by": row.get("actor_login"),
                "changed_at": _iso_value(row.get("created_at")),
                "before_role": before_data.get("role"),
                "after_role": after_data.get("role"),
                "before_active": before_data.get("active"),
                "after_active": after_data.get("active"),
                "before_data": before_data,
                "after_data": after_data,
            }
        )
    return {"ok": True, "items": items}


@app.post("/api/admin/users")
@app.post("/admin/users")
async def admin_save_user(request: Request):
    actor = _require_auth_user(request)
    if _clean_str(actor.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    body = await request.json()
    login = _clean_str(body.get("login") or body.get("email"))
    display_name = _clean_str(body.get("display_name") or body.get("name") or login)
    role = _clean_str(body.get("role") or "vendedor").lower()
    active = bool(body.get("active", True))
    must_change_password = bool(body.get("must_change_password", False))
    password = _clean_str(body.get("password") or body.get("senha") or "1234")
    companies = body.get("companies") or body.get("company_keys") or []
    user_id = _clean_str(body.get("id") or body.get("user_id"))

    if not login:
        raise HTTPException(status_code=400, detail="Login é obrigatório.")
    if role not in {"admin", "vendedor", "separacao"}:
        raise HTTPException(status_code=400, detail="Perfil inválido.")

    before_row = None
    if user_id:
        before_row = _auth_find_user_by_id(user_id)
    if before_row is None:
        before_row = _auth_lookup_user_by_login(login)

    if before_row:
        target_id = str(before_row.get("id"))
        update_password = bool(password)
        with _db() as conn:
            with conn.cursor() as cur:
                params: List[Any] = [display_name, role, active, must_change_password, now := _now(), target_id]
                sql = """
                    UPDATE erp.users
                    SET display_name=%s,
                        role=%s,
                        active=%s,
                        must_change_password=%s,
                        updated_at=%s
                """
                if update_password:
                    sql += ", password_hash=%s"
                    params.insert(4, _auth_password_hash(password))
                sql += " WHERE id=%s"
                cur.execute(sql, params)
        if companies is not None:
            _auth_update_user_companies(target_id, list(companies))
        after_row = _auth_find_user_by_id(target_id)
        _auth_audit_log(
            actor.get("login"),
            login,
            "updated",
            before_data=_admin_user_payload(before_row),
            after_data=_admin_user_payload(after_row or before_row),
        )
        return {"ok": True, "item": _admin_user_payload(after_row or before_row)}

    target_id = str(uuid.uuid4())
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.users (id, login, display_name, password_hash, role, active, must_change_password, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
                """,
                (target_id, login, display_name, _auth_password_hash(password), role, active, must_change_password),
            )
    _auth_update_user_companies(target_id, list(companies))
    new_row = _auth_find_user_by_id(target_id)
    _auth_audit_log(
        actor.get("login"),
        login,
        "created",
        before_data=None,
        after_data=_admin_user_payload(new_row or {"id": target_id, "login": login, "display_name": display_name, "role": role, "active": active, "must_change_password": must_change_password}),
    )
    return {"ok": True, "item": _admin_user_payload(new_row or {"id": target_id, "login": login, "display_name": display_name, "role": role, "active": active, "must_change_password": must_change_password})}


@app.patch("/api/admin/users/{user_id}")
@app.patch("/admin/users/{user_id}")
async def admin_patch_user(user_id: str, request: Request):
    actor = _require_auth_user(request)
    if _clean_str(actor.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    body = await request.json()
    before_row = _auth_find_user_by_id(user_id)
    if not before_row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    display_name = _clean_str(body.get("display_name") or body.get("name") or before_row.get("display_name"))
    role = _clean_str(body.get("role") or before_row.get("role")).lower()
    active = bool(body.get("active", before_row.get("active", True)))
    must_change_password = bool(body.get("must_change_password", before_row.get("must_change_password", False)))
    if role not in {"admin", "vendedor", "separacao"}:
        raise HTTPException(status_code=400, detail="Perfil inválido.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.users
                SET display_name=%s,
                    role=%s,
                    active=%s,
                    must_change_password=%s,
                    updated_at=now()
                WHERE id=%s
                """,
                (display_name, role, active, must_change_password, user_id),
            )
    after_row = _auth_find_user_by_id(user_id)
    _auth_audit_log(actor.get("login"), before_row.get("login"), "updated", _admin_user_payload(before_row), _admin_user_payload(after_row or before_row))
    return {"ok": True, "item": _admin_user_payload(after_row or before_row)}


@app.post("/api/admin/users/{user_id}/reset-password")
@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, request: Request):
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

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, login, display_name, role, active, must_change_password, created_at, updated_at
                FROM erp.users
                WHERE id=%s
                LIMIT 1
                """,
                (user_id,),
            )
            before_row = cur.fetchone()

    if not before_row:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    before_row = dict(before_row)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.users
                SET password_hash=%s,
                    must_change_password=%s,
                    updated_at=now()
                WHERE id=%s
                RETURNING id
                """,
                (_auth_password_hash(new_password), must_change_password, user_id),
            )
            updated = cur.fetchone()

    if not updated:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, login, display_name, role, active, must_change_password, created_at, updated_at
                FROM erp.users
                WHERE id=%s
                LIMIT 1
                """,
                (user_id,),
            )
            after_row = cur.fetchone()

            cur.execute(
                """
                SELECT company_key
                FROM erp.user_companies
                WHERE user_id=%s
                ORDER BY company_key
                """,
                (user_id,),
            )
            companies = [r.get("company_key") for r in cur.fetchall()]

    after_row = dict(after_row or before_row)
    role = _clean_str(after_row.get("role")).lower()
    item = {
        "id": str(after_row.get("id")),
        "login": after_row.get("login"),
        "display_name": after_row.get("display_name"),
        "role": role,
        "companies": companies,
        "active": bool(after_row.get("active")),
        "must_change_password": bool(after_row.get("must_change_password")),
        "is_admin": role == "admin",
        "is_vendedor": role == "vendedor",
        "is_separacao": role == "separacao",
        "can_access_quotes": role in {"admin", "vendedor"},
        "can_access_separation": role in {"admin", "separacao"},
        "email": after_row.get("login"),
        "created_at": after_row.get("created_at").isoformat() if hasattr(after_row.get("created_at"), "isoformat") else after_row.get("created_at"),
        "updated_at": after_row.get("updated_at").isoformat() if hasattr(after_row.get("updated_at"), "isoformat") else after_row.get("updated_at"),
    }

    return {"ok": True, "item": item}


@app.post("/api/admin/users/{user_id}/set-companies")
@app.post("/admin/users/{user_id}/set-companies")
async def admin_set_user_companies(user_id: str, request: Request):
    actor = _require_auth_user(request)
    if _clean_str(actor.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    body = await request.json()
    if isinstance(body, list):
        companies = body
    elif isinstance(body, dict):
        companies = body.get("companies") or body.get("company_keys") or []
    else:
        companies = []
    before_row = _auth_find_user_by_id(user_id)
    if not before_row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    _auth_update_user_companies(user_id, list(companies))
    after_row = _auth_find_user_by_id(user_id)
    _auth_audit_log(actor.get("login"), before_row.get("login"), "set_companies", _admin_user_payload(before_row), _admin_user_payload(after_row or before_row))
    return {"ok": True, "item": _admin_user_payload(after_row or before_row)}


@app.delete("/api/admin/users/{email}")
@app.delete("/admin/users/{email}")
async def admin_disable_user(email: str, request: Request):
    actor = _require_auth_user(request)
    if _clean_str(actor.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    user = _auth_lookup_user_by_login(email)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    before = _admin_user_payload(user)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.users
                SET active=FALSE, updated_at=now()
                WHERE id=%s
                """,
                (user.get("id"),),
            )
    after = _admin_user_payload(_auth_find_user_by_id(user.get("id")) or user)
    _auth_audit_log(actor.get("login"), user.get("login"), "deactivated", before, after)
    return {"ok": True, "item": after}


@app.post("/api/admin/companies")
@app.post("/admin/companies")
async def upsert_company(request: Request):
    body = await request.json()
    key = _company_key(body.get("company_key") or body.get("key") or "parton")
    name = _clean_str(body.get("company_name") or body.get("name") or key)
    base_url = _clean_str(body.get("tiny_base_url") or "https://api.tiny.com.br/api2")
    token = _clean_str(body.get("tiny_token") or "")
    active = bool(body.get("active", True))

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.companies (company_key, company_name, tiny_base_url, tiny_token, active, updated_at)
                VALUES (%s, %s, %s, NULLIF(%s, ''), %s, now())
                ON CONFLICT (company_key) DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    tiny_base_url = EXCLUDED.tiny_base_url,
                    tiny_token = COALESCE(EXCLUDED.tiny_token, erp.companies.tiny_token),
                    active = EXCLUDED.active,
                    updated_at = now()
                RETURNING company_key, company_name, tiny_base_url, active,
                          CASE WHEN COALESCE(tiny_token, '') <> '' THEN TRUE ELSE FALSE END AS has_db_token
                """,
                (key, name, base_url, token, active),
            )
            row = dict(cur.fetchone())
    return {"ok": True, "item": row}


@app.get("/api/admin/v3-status")
@app.get("/admin/v3-status")
def admin_v3_status(request: Request, company: str = "parton"):
    _catalog_require_admin(request)
    key = _company_key(company)

    env_names = [
        f"TINY_V3_ACCESS_TOKEN_{key.upper()}",
        f"TINY_V3_{key.upper()}_TOKEN",
    ]
    if key == "parton":
        env_names += ["TINY_V3_ACCESS_TOKEN_SUPRIMENTOS", "TINY_V3_SUPRIMENTOS_TOKEN"]
    if key == "park":
        env_names += ["TINY_V3_ACCESS_TOKEN_INFORMATICA", "TINY_V3_INFORMATICA_TOKEN"]

    env_token = ""
    env_token_var = ""
    for name in env_names:
        val = os.getenv(name, "").strip()
        if val:
            env_token = val
            env_token_var = name
            break

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tiny_v3_access_token, tiny_v3_refresh_token, tiny_v3_token_expires_at,
                       tiny_v3_client_id, tiny_v3_client_secret, tiny_v3_redirect_uri,
                       tiny_v3_oauth_state, tiny_v3_oauth_state_expires_at, tiny_v3_authorized_at
                FROM erp.companies
                WHERE company_key = %s
                """,
                (key,),
            )
            row = dict(cur.fetchone() or {})

    db_access = _clean_str(row.get("tiny_v3_access_token"))
    db_refresh = _clean_str(row.get("tiny_v3_refresh_token"))
    db_expires_at = row.get("tiny_v3_token_expires_at")
    db_client_id = _clean_str(row.get("tiny_v3_client_id"))
    db_client_secret = _clean_str(row.get("tiny_v3_client_secret"))
    db_redirect_uri = _clean_str(row.get("tiny_v3_redirect_uri"))
    db_oauth_state = _clean_str(row.get("tiny_v3_oauth_state"))
    db_oauth_state_expires_at = row.get("tiny_v3_oauth_state_expires_at")
    db_authorized_at = row.get("tiny_v3_authorized_at")

    effective_token = env_token or db_access
    resolved_redirect_uri = db_redirect_uri or _tiny_v3_default_redirect_uri()

    is_expired = None
    if db_expires_at:
        now_utc = _now()
        try:
            if hasattr(db_expires_at, "tzinfo") and db_expires_at.tzinfo:
                is_expired = db_expires_at <= now_utc
            else:
                is_expired = db_expires_at <= now_utc.replace(tzinfo=None)
        except Exception:
            is_expired = None

    _tail = _tiny_v3_tail

    oauth_state_pending = False
    if db_oauth_state:
        if db_oauth_state_expires_at:
            try:
                now_utc = _now()
                if getattr(db_oauth_state_expires_at, "tzinfo", None):
                    oauth_state_pending = db_oauth_state_expires_at > now_utc
                else:
                    oauth_state_pending = db_oauth_state_expires_at > now_utc.replace(tzinfo=None)
            except Exception:
                oauth_state_pending = True
        else:
            oauth_state_pending = True

    return {
        "ok": True,
        "company_key": key,
        "has_access_token": bool(effective_token),
        "has_refresh_token": bool(db_refresh),
        "has_expires_at": bool(db_expires_at),
        "token_source": "env" if env_token else ("db" if db_access else "none"),
        "env_var": env_token_var if env_token else None,
        "access_token_tail": _tail(effective_token) if effective_token else None,
        "refresh_token_tail": _tail(db_refresh) if db_refresh else None,
        "expires_at": db_expires_at.isoformat() if hasattr(db_expires_at, "isoformat") else (str(db_expires_at) if db_expires_at else None),
        "is_expired": is_expired,
        "has_client_id": bool(db_client_id),
        "client_id_tail": _tail(db_client_id) if db_client_id else None,
        "has_client_secret": bool(db_client_secret),
        "has_redirect_uri": bool(db_redirect_uri),
        "redirect_uri": resolved_redirect_uri,
        "authorized_at": db_authorized_at.isoformat() if hasattr(db_authorized_at, "isoformat") else (str(db_authorized_at) if db_authorized_at else None),
        "oauth_state_pending": oauth_state_pending,
        "oauth_state_expires_at": db_oauth_state_expires_at.isoformat() if hasattr(db_oauth_state_expires_at, "isoformat") else (str(db_oauth_state_expires_at) if db_oauth_state_expires_at else None),
    }


@app.post("/api/admin/v3-token")
@app.post("/admin/v3-token")
async def admin_v3_token_save(request: Request):
    _catalog_require_admin(request)
    body = await request.json()
    key = _company_key(_clean_str(body.get("company_key") or body.get("company") or "parton"))
    access_token = _clean_str(body.get("access_token") or "")
    refresh_token = _clean_str(body.get("refresh_token") or "")
    expires_at_raw = _clean_str(body.get("expires_at") or "")

    if not access_token:
        raise HTTPException(status_code=400, detail="access_token é obrigatório.")

    expires_at = None
    if expires_at_raw:
        try:
            expires_at = dt.datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="expires_at inválido. Use formato ISO 8601 (ex: 2025-12-31T23:59:59Z).",
            )

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.companies
                SET tiny_v3_access_token = %s,
                    tiny_v3_refresh_token = NULLIF(%s, ''),
                    tiny_v3_token_expires_at = %s,
                    updated_at = now()
                WHERE company_key = %s
                """,
                (access_token, refresh_token, expires_at, key),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Empresa '{key}' não encontrada.")

    def _tail(value: str) -> str:
        v = str(value or "").strip()
        return f"...{v[-4:]}" if len(v) >= 4 else ("***" if v else "")

    return {
        "ok": True,
        "company_key": key,
        "access_token_tail": _tail(access_token),
        "has_refresh_token": bool(refresh_token),
        "refresh_token_tail": _tail(refresh_token) if refresh_token else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "message": f"Token V3 salvo para empresa '{key}'.",
    }


# ---------- Tiny V3 OAuth: credenciais, auth-url e callback ----------
@app.post("/api/admin/tiny-v3/credentials")
@app.post("/admin/tiny-v3/credentials")
async def admin_tiny_v3_credentials(request: Request):
    _catalog_require_admin(request)
    _ensure_companies_v3_columns()
    body = await request.json()
    key = _company_key(_clean_str(body.get("company_key") or body.get("company") or "parton"))
    client_id = _clean_str(body.get("client_id"))
    client_secret = _clean_str(body.get("client_secret"))
    redirect_uri = _clean_str(body.get("redirect_uri"))

    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="client_id e client_secret são obrigatórios.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.companies
                SET tiny_v3_client_id = %s,
                    tiny_v3_client_secret = %s,
                    tiny_v3_redirect_uri = NULLIF(%s, ''),
                    updated_at = now()
                WHERE company_key = %s
                """,
                (client_id, client_secret, redirect_uri, key),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Empresa '{key}' não encontrada.")

    return {
        "ok": True,
        "company_key": key,
        "client_id_tail": _tiny_v3_tail(client_id),
        "has_client_secret": True,
        "redirect_uri": redirect_uri or _tiny_v3_default_redirect_uri(),
    }


@app.get("/api/admin/tiny-v3/auth-url")
@app.get("/admin/tiny-v3/auth-url")
def admin_tiny_v3_auth_url(request: Request, company: str = "parton"):
    _catalog_require_admin(request)
    _ensure_companies_v3_columns()
    key = _company_key(company)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tiny_v3_client_id, tiny_v3_client_secret, tiny_v3_redirect_uri
                FROM erp.companies
                WHERE company_key = %s
                """,
                (key,),
            )
            row = dict(cur.fetchone() or {})

    client_id = _clean_str(row.get("tiny_v3_client_id"))
    client_secret = _clean_str(row.get("tiny_v3_client_secret"))
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail=f"Credenciais OAuth V3 (client_id/client_secret) não configuradas para '{key}'. "
            f"Use POST /api/admin/tiny-v3/credentials.",
        )

    redirect_uri = _clean_str(row.get("tiny_v3_redirect_uri")) or _tiny_v3_default_redirect_uri()
    state, state_expires_at = _tiny_v3_make_state(key)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.companies
                SET tiny_v3_oauth_state = %s,
                    tiny_v3_oauth_state_expires_at = %s,
                    updated_at = now()
                WHERE company_key = %s
                """,
                (state, state_expires_at, key),
            )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    scope = _tiny_v3_oauth_scope()
    if scope:
        params["scope"] = scope

    auth_url = f"{_tiny_v3_auth_base_url()}?{urlencode(params)}"

    return {
        "ok": True,
        "company_key": key,
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "state_expires_at": state_expires_at.isoformat(),
    }


def _tiny_v3_callback_html(ok: bool, message: str) -> HTMLResponse:
    titulo = "Autorização concluída" if ok else "Falha na autorização"
    cor = "#15803d" if ok else "#b91c1c"
    html = (
        "<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Tiny V3 — {titulo}</title></head>"
        "<body style='font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f8fafc;"
        "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0'>"
        "<div style='background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:32px;"
        "max-width:460px;box-shadow:0 4px 16px rgba(0,0,0,.06)'>"
        f"<h1 style='color:{cor};font-size:20px;margin:0 0 12px'>{titulo}</h1>"
        f"<p style='color:#334155;font-size:14px;line-height:1.5;margin:0'>{message}</p>"
        "<p style='color:#94a3b8;font-size:12px;margin:16px 0 0'>Você já pode fechar esta janela.</p>"
        "</div></body></html>"
    )
    return HTMLResponse(content=html, status_code=200 if ok else 400)


@app.get("/api/tiny-v3/oauth/callback")
@app.get("/tiny-v3/oauth/callback")
@app.get("/api/admin/tiny-v3/oauth/callback")
@app.get("/admin/tiny-v3/oauth/callback")
def admin_tiny_v3_oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
):
    # Endpoint público (sem auth ERP). A segurança vem da validação do state assinado.
    _ensure_companies_v3_columns()

    if error:
        return _tiny_v3_callback_html(False, f"O provedor retornou um erro: {error}. {error_description}".strip())

    code = _clean_str(code)
    state = _clean_str(state)
    if not code or not state:
        return _tiny_v3_callback_html(False, "Parâmetros 'code' e/ou 'state' ausentes.")

    # 1) Valida assinatura e expiração do state.
    try:
        parsed = _tiny_v3_parse_state(state)
    except ValueError as exc:
        return _tiny_v3_callback_html(False, f"State inválido: {exc}.")

    key = parsed["company_key"]

    # 2) Carrega credenciais e confere igualdade/expiração com o state salvo no banco.
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tiny_v3_client_id, tiny_v3_client_secret, tiny_v3_redirect_uri,
                       tiny_v3_oauth_state, tiny_v3_oauth_state_expires_at
                FROM erp.companies
                WHERE company_key = %s
                """,
                (key,),
            )
            row = dict(cur.fetchone() or {})

    if not row:
        return _tiny_v3_callback_html(False, f"Empresa '{key}' não encontrada.")

    saved_state = _clean_str(row.get("tiny_v3_oauth_state"))
    saved_expires = row.get("tiny_v3_oauth_state_expires_at")
    if not saved_state or not hmac.compare_digest(saved_state, state):
        return _tiny_v3_callback_html(False, "State não confere com o registro salvo (possível reuso ou expirado).")

    if saved_expires:
        try:
            now_utc = _now()
            exp = saved_expires if getattr(saved_expires, "tzinfo", None) else saved_expires.replace(tzinfo=dt.timezone.utc)
            if exp <= now_utc:
                return _tiny_v3_callback_html(False, "O state salvo expirou. Gere uma nova URL de autorização.")
        except Exception:
            pass

    client_id = _clean_str(row.get("tiny_v3_client_id"))
    client_secret = _clean_str(row.get("tiny_v3_client_secret"))
    if not client_id or not client_secret:
        return _tiny_v3_callback_html(False, "Credenciais OAuth (client_id/client_secret) ausentes no servidor.")

    redirect_uri = _clean_str(row.get("tiny_v3_redirect_uri")) or _tiny_v3_default_redirect_uri()

    # 3) Troca o code por tokens.
    try:
        payload = _tiny_v3_exchange_token(
            "authorization_code",
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
    except HTTPException as exc:
        return _tiny_v3_callback_html(False, f"Falha na troca do code por token: {exc.detail}")

    if not _clean_str(payload.get("access_token")):
        return _tiny_v3_callback_html(False, "O provedor não retornou access_token.")

    # 4) Salva tokens + authorized_at e limpa o state.
    _tiny_v3_store_tokens(key, payload, authorized=True)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.companies
                SET tiny_v3_oauth_state = NULL,
                    tiny_v3_oauth_state_expires_at = NULL,
                    updated_at = now()
                WHERE company_key = %s
                """,
                (key,),
            )

    return _tiny_v3_callback_html(
        True,
        f"Tokens Tiny V3 obtidos e salvos para a empresa '{key}'. A renovação será automática.",
    )


@app.get("/tiny/payment-methods")
@app.get("/api/tiny/payment-methods")
def tiny_payment_methods(company: str = "parton"):
    tiny = _tiny_for_company(company)
    try:
        r = tiny.pesquisar_formas_recebimento()
        registros = (
            r.get("formas_recebimento")
            or r.get("formasRecebimento")
            or r.get("registros")
            or []
        )
        items = []
        for it in registros:
            f = it.get("forma_recebimento", it.get("formaRecebimento", it))
            tid = f.get("id") or f.get("codigo") or f.get("nome")
            name = f.get("nome") or f.get("descricao") or str(tid or "")
            if not name:
                continue
            items.append({
                "id": tid,
                "code": _normalize_payment_code(name),
                "name": name,
                "nome": name,
                "raw": f,
            })

        fixed = [{"id": k, "code": k, "name": v, "nome": v, "raw": {}} for k, v in PAYMENT_METHODS.items()]
        existing_names = {str(x["name"]).strip().lower() for x in items}
        for f in fixed:
            if f["name"].strip().lower() not in existing_names:
                items.append(f)

        return {"ok": True, "items": items}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/clients")
@app.get("/api/tiny/clients")
def tiny_clients(company: str = "parton", q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    tiny = _tiny_for_company(company)
    try:
        r = tiny.pesquisar_contatos(pesquisa=q, pagina=page)
        contatos = r.get("contatos") or []
        items = []
        for it in contatos:
            c = it.get("contato", it)
            if not c.get("id"):
                continue
            items.append({
                "id": _safe_int(c.get("id")),
                "nome": c.get("nome") or "",
                "cpf_cnpj": c.get("cpf_cnpj") or c.get("cpfCnpj") or "",
                "cidade": c.get("cidade") or "",
                "uf": c.get("uf") or "",
                "email": c.get("email") or "",
                "fone": c.get("fone") or c.get("telefone") or "",
                "raw": c,
            })
        return {"ok": True, "items": items, "page": page}
    except TinyAPIError as e:
        msg = str(e).lower()
        if "não retornou registros" in msg or "nao retornou registros" in msg:
            return {"ok": True, "items": [], "page": page}
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/products")
@app.get("/api/tiny/products")
def tiny_products(company: str = "parton", q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    tiny = _tiny_for_company(company)
    try:
        r = tiny.pesquisar_produtos(pesquisa=q, pagina=page)
        prods = r.get("produtos") or []
        items = []
        for it in prods:
            p = it.get("produto", it)
            if not p.get("id"):
                continue
            if not _active_flag(p.get("situacao")):
                continue

            price = _safe_float(p.get("preco") or p.get("preco_venda") or p.get("precoVenda"), 0)
            stock = _safe_float(p.get("saldo") or p.get("estoque") or p.get("estoque_atual") or p.get("estoqueAtual"), 0)

            items.append({
                "id": _safe_int(p.get("id")),
                "product_id": _safe_int(p.get("id")),
                "codigo": p.get("codigo") or p.get("sku") or "",
                "sku": p.get("codigo") or p.get("sku") or "",
                "nome": p.get("nome") or p.get("descricao") or "",
                "descricao": p.get("nome") or p.get("descricao") or "",
                "preco": price,
                "preco_venda": price,
                "list_price": price,
                "unit_price": price,
                "stock": stock,
                "estoque_atual": stock,
                "raw": p,
            })
        return {"ok": True, "items": items, "page": page}
    except TinyAPIError as e:
        msg = str(e).lower()
        if "não retornou registros" in msg or "nao retornou registros" in msg:
            return {"ok": True, "items": [], "page": page}
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/products/{product_id}/stock")
@app.get("/api/tiny/products/{product_id}/stock")
def tiny_stock(product_id: int, company: str = "parton"):
    tiny = _tiny_for_company(company)
    try:
        r = tiny.obter_estoque_produto(product_id)
        prod = r.get("produto") or r.get("estoque") or r
        saldo = prod.get("saldo") if isinstance(prod, dict) else None
        saldo_reservado = prod.get("saldoReservado") if isinstance(prod, dict) else None
        try:
            saldo_num = float(saldo or 0)
        except (TypeError, ValueError):
            saldo_num = 0
        try:
            reservado_num = float(saldo_reservado or 0)
        except (TypeError, ValueError):
            reservado_num = 0
        saldo_disponivel = max(0, saldo_num - reservado_num)
        if float(saldo_disponivel).is_integer():
            saldo_disponivel = int(saldo_disponivel)
        if float(saldo_num).is_integer():
            saldo_num = int(saldo_num)
        if float(reservado_num).is_integer():
            reservado_num = int(reservado_num)
        return {
            "ok": True,
            "product_id": product_id,
            "saldo": saldo_num,
            "saldoReservado": reservado_num,
            "saldoDisponivel": saldo_disponivel,
            "raw": prod,
        }
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/vendors")
@app.get("/api/tiny/vendors")
def tiny_vendors(company: str = "parton", q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    company_key = _company_key(company)
    tiny = _tiny_for_company(company_key)
    if not q or len(q.strip()) < 2:
        return {"ok": True, "items": [], "page": page}
    try:
        r = tiny.pesquisar_vendedores(pesquisa=q.strip(), pagina=page)
        vend = r.get("vendedores") or []
        items = []
        for it in vend:
            v = it.get("vendedor", it)
            if not v.get("id"):
                continue
            seller_name = v.get("nome") or ""
            if not _seller_allowed_for_company(company_key, seller_name):
                continue

            items.append({
                "id": _safe_int(v.get("id")),
                "seller_id": _safe_int(v.get("id")),
                "nome": seller_name,
                "seller_name": seller_name,
                "codigo": v.get("codigo") or "",
                "raw": v,
            })
        return {"ok": True, "items": items, "page": page}
    except TinyAPIError as e:
        msg = str(e).lower()
        if "não retornou registros" in msg or "nao retornou registros" in msg:
            return {"ok": True, "items": [], "page": page}
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/shipping-methods")
@app.get("/api/tiny/shipping-methods")
def tiny_shipping_methods(company: str = "parton", tipo_logistica: Optional[int] = Query(default=None)):
    tiny = _tiny_for_company(company)
    try:
        r = tiny.pesquisar_formas_envio(tipo_logistica=tipo_logistica)
        regs = r.get("registros") or []
        items = []
        for x in regs:
            f = x.get("forma_envio", x.get("formaEnvio", x))
            if not f.get("id"):
                continue
            items.append({
                "id": _safe_int(f.get("id")),
                "nome": f.get("nome") or f.get("descricao") or "",
                "name": f.get("nome") or f.get("descricao") or "",
                "raw": f,
            })
        items.sort(key=lambda a: (a.get("nome") or "").lower())
        return {"ok": True, "items": items}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/shipping-methods/{shipping_id}/freight-methods")
@app.get("/api/tiny/shipping-methods/{shipping_id}/freight-methods")
def tiny_freight_methods(shipping_id: int, company: str = "parton"):
    tiny = _tiny_for_company(company)
    try:
        r = tiny.obter_forma_envio(shipping_id)
        forma = r.get("forma_envio") or {}
        fretes = forma.get("formas_frete") or []
        items = []
        for f in fretes:
            if not f.get("id"):
                continue
            items.append({
                "id": _safe_int(f.get("id")),
                "descricao": f.get("descricao") or "",
                "nome": f.get("descricao") or "",
                "name": f.get("descricao") or "",
                "raw": f,
            })
        items.sort(key=lambda a: (a.get("descricao") or "").lower())
        return {"ok": True, "items": items, "shipping": {"id": shipping_id, "nome": forma.get("nome") or ""}}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/freight-methods")
@app.get("/api/tiny/freight-methods")
def tiny_freight_methods_alias(
    company: str = "parton",
    shipping_id: Optional[int] = Query(default=None),
    shipping_method_id: Optional[int] = Query(default=None),
):
    sid = shipping_id or shipping_method_id
    if not sid:
        raise HTTPException(status_code=400, detail="Missing shipping_id or shipping_method_id")
    return tiny_freight_methods(int(sid), company=company)


def _generate_quote_number():
    return int(dt.datetime.now().strftime("%y%m%d%H%M%S%f")[:15])


def _quote_row_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    for k in ("client_snapshot", "seller_snapshot", "totals", "payload"):
        out[k] = _from_json(out.get(k), out.get(k))

    totals = out.get("totals") or {}
    payload = out.get("payload") or {}

    total_net = _safe_float(totals.get("net"), 0)
    total_items = _safe_float(totals.get("items"), 0)
    total_from_payload = _safe_float(
        payload.get("total")
        or payload.get("total_net")
        or payload.get("total_amount")
        or payload.get("total_items"),
        0,
    )

    total_final = total_net or total_items or total_from_payload

    client_snapshot = out.get("client_snapshot") or {}
    client_name = _client_name_from_snapshot(client_snapshot)

    out["client_name"] = client_name or payload.get("client_name") or f"Cliente #{out.get('client_id')}"
    out["cliente_nome"] = out["client_name"]
    out["customer_name"] = out["client_name"]

    # Aliases para telas antigas, operações e impressão
    out["total"] = total_final
    out["total_net"] = total_final
    out["total_amount"] = total_final
    out["amount_total"] = total_final
    out["valor_total"] = total_final
    out["net"] = total_final

    out["sale_total_products"] = total_items or total_final
    out["items_total"] = total_items or total_final
    out["cost_total_products"] = _safe_float(out.get("cost_total_products"), 0)
    out["profit_total_products"] = _safe_float(out.get("profit_total_products"), 0)

    out["freight_paid_client"] = _safe_float(
        out.get("freight_paid_client")
        or payload.get("freight_paid_client")
        or totals.get("freight_paid_client"),
        0,
    )
    out["freight_paid_company"] = _safe_float(
        out.get("freight_paid_company")
        or payload.get("freight_paid_company")
        or totals.get("freight_paid_company"),
        0,
    )

    out["internal_notes"] = (
        out.get("internal_notes")
        or payload.get("internal_notes")
        or payload.get("internalNotes")
        or ""
    )
    out["internalNotes"] = out["internal_notes"]
    out["invoice_profile"] = str(payload.get("invoice_profile") or out.get("invoice_profile") or "A")

    # Aliases úteis para reidratação do front
    out["shipping_id"] = out.get("shipping_method_id")
    out["shipping_name"] = out.get("shipping_method_name")
    out["freight_id"] = out.get("freight_method_id")
    out["freight_name"] = out.get("freight_method_name")
    out["payment_code"] = out.get("payment_method_code")

    # Também reforça no payload para o editor antigo
    if isinstance(payload, dict):
        payload.setdefault("client_name", out["client_name"])
        payload.setdefault("total", total_final)
        payload.setdefault("total_net", total_final)
        payload.setdefault("freight_method_id", out.get("freight_method_id"))
        payload.setdefault("freight_method_name", out.get("freight_method_name"))
        payload.setdefault("shipping_method_id", out.get("shipping_method_id"))
        payload.setdefault("shipping_method_name", out.get("shipping_method_name"))
        payload.setdefault("internal_notes", out.get("internal_notes") or "")
        payload.setdefault("internalNotes", out.get("internal_notes") or "")
        payload.setdefault("invoice_profile", out.get("invoice_profile") or "A")
        out["payload"] = payload

    return out


@app.get("/quotes")
@app.get("/api/quotes")
def list_quotes(
    company: str = "parton",
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    company_key = _company_key(company)
    where = ["company_key = %s"]
    params = [company_key]

    if status:
        where.append("LOWER(status) = LOWER(%s)")
        params.append(status)

    if q:
        where.append("""
        (
            LOWER(COALESCE(client_snapshot->>'nome', client_snapshot->>'name', '')) LIKE LOWER(%s)
            OR LOWER(COALESCE(seller_name, '')) LIKE LOWER(%s)
            OR CAST(quote_number AS TEXT) LIKE %s
            OR COALESCE(tiny_order_number, '') LIKE %s
            OR LOWER(quote_id) LIKE LOWER(%s)
        )
        """)
        like = f"%{q}%"
        params += [like, like, like, like, like]

    where_sql = " AND ".join(where)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM erp.quotes WHERE {where_sql}", params)
            total = int(cur.fetchone()["total"] or 0)

            cur.execute(
                f"""
                SELECT *
                FROM erp.quotes
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            quote_rows = [dict(r) for r in cur.fetchall()]

            item_rows_by_quote: Dict[Any, List[Dict[str, Any]]] = {}
            quote_ids = [row.get("quote_id") for row in quote_rows if row.get("quote_id")]
            if quote_ids:
                cur.execute(
                    """
                    SELECT *
                    FROM erp.quote_items
                    WHERE quote_id = ANY(%s)
                    ORDER BY quote_id, line
                    """,
                    (quote_ids,),
                )
                for item_row in cur.fetchall():
                    item_dict = dict(item_row)
                    item_rows_by_quote.setdefault(item_dict.get("quote_id"), []).append(item_dict)

            rows = []
            for row in quote_rows:
                quote_public = _quote_row_public(dict(row))
                quote_public, _normalized_items = _compute_quote_financials(
                    quote_public,
                    item_rows_by_quote.get(row.get("quote_id"), []),
                )
                rows.append(quote_public)

    return {
        "ok": True,
        "company": company_key,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
        "items": rows,
    }


@app.get("/quotes/{quote_id}")
@app.get("/api/quotes/{quote_id}")
def get_quote(quote_id: str, company: str = "parton"):
    company_key = _company_key(company)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM erp.quotes WHERE quote_id=%s AND company_key=%s LIMIT 1", (quote_id, company_key))
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail="Orçamento não encontrado.")

            cur.execute("SELECT * FROM erp.quote_items WHERE quote_id=%s ORDER BY line", (quote_id,))
            items = [dict(r) for r in cur.fetchall()]

    quote = _quote_row_public(dict(q))
    quote, items = _compute_quote_financials(quote, items)
    return {"ok": True, "quote": quote, "items": items}


def _separation_status_from_internal(internal_status: str) -> str:
    s = str(internal_status or "").strip().lower()
    if s == "preparando envio":
        return "Separando"
    if s == "pronto para envio":
        return "Separado"
    if s == "faturado":
        return "Entregue"
    if s == "cancelado":
        return "Cancelado"
    return "A separar"


def _separation_status_from_row(row: Dict[str, Any]) -> str:
    separation_order_status = _clean_str(
        row.get("separation_order_status")
        or row.get("separation_status")
        or row.get("operational_status")
    )
    internal_status = _clean_str(row.get("internal_status"))

    if _normalize_status_text(separation_order_status) == "cancelado":
        return "Cancelado"
    if _normalize_status_text(internal_status) == "cancelado":
        return "Cancelado"
    if _normalize_status_text(internal_status) == "faturado":
        return "Entregue"
    if _normalize_status_text(internal_status) == "pronto para envio":
        return "Separado"
    if _normalize_status_text(internal_status) == "preparando envio":
        return "Separando"
    if separation_order_status:
        return separation_order_status
    return "A separar"


def _separation_list_row(row: Dict[str, Any]) -> Dict[str, Any]:
    internal_status = _clean_str(row.get("internal_status"))
    separation_status = _separation_status_from_row(row)
    tiny_order_id = row.get("tiny_order_id")
    tiny_order_number = row.get("tiny_order_number")
    payload = _from_json(row.get("payload"), {}) or {}
    if not isinstance(payload, dict):
        payload = {}
    approved_at = payload.get("approved_at") or payload.get("approvedAt")

    client_snapshot = _from_json(row.get("client_snapshot"), {}) or {}
    seller_snapshot = _from_json(row.get("seller_snapshot"), {}) or {}

    client_name = (
        _client_name_from_snapshot(client_snapshot)
        or _clean_str(row.get("client_name"))
        or _clean_str(row.get("cliente"))
    )
    seller_name = (
        _clean_str(row.get("seller_name"))
        or _clean_str((seller_snapshot or {}).get("name"))
        or _clean_str((seller_snapshot or {}).get("nome"))
    )

    client_document = _client_first_value_from_snapshot(
        client_snapshot,
        "cpf_cnpj",
        "cpfCnpj",
        "cpf",
        "cnpj",
        "documento",
    )
    client_phone = _client_first_value_from_snapshot(
        client_snapshot,
        "fone",
        "telefone",
        "celular",
        "phone",
    )
    client_email = _client_first_value_from_snapshot(
        client_snapshot,
        "email",
        "email_nfe",
        "emailNfe",
    )
    client_address = _client_address_from_snapshot(client_snapshot)

    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    printed_at = row.get("printed_at")
    label_printed_at = row.get("label_printed_at")
    started_at = row.get("started_at")
    separated_at = row.get("separated_at")
    checked_at = row.get("checked_at")

    out = {
        "quote_id": row.get("quote_id"),
        "quote_number": row.get("quote_number"),
        "tiny_order_id": tiny_order_id,
        "tiny_order_number": tiny_order_number,
        "company_key": row.get("company_key"),
        "client_name": client_name,
        "client_document": client_document,
        "client_phone": client_phone,
        "client_email": client_email,
        "client_address": client_address,
        "client_snapshot": client_snapshot,
        "seller_name": seller_name,
        "shipping_method_name": row.get("shipping_method_name") or "",
        "freight_method_name": row.get("freight_method_name") or "",
        "internal_status": internal_status,
        "quote_status": _clean_str(row.get("status")),
        "status": separation_status,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "approved_at": approved_at,
        "approvedAt": approved_at,
        "payload": payload,
        "separation_status": separation_status,
        "printed": _boolish(row.get("printed")),
        "label_printed": _boolish(row.get("label_printed")),
        "printed_at": _iso_value(printed_at),
        "label_printed_at": _iso_value(label_printed_at),
        "started_at": _iso_value(started_at),
        "separated_at": _iso_value(separated_at),
        "checked_at": _iso_value(checked_at),
        "awaiting_conference": _boolish(row.get("awaiting_conference")),
        "separation_photo_url": _clean_str(row.get("separation_photo_url")),
        "conference_photo_url": _clean_str(row.get("conference_photo_url")),
        "assigned_to": _clean_str(row.get("assigned_to")),
        "operator_name": _clean_str(row.get("operator_name")),
        "notes": _clean_str(row.get("notes")),
        "separation_notes": _clean_str(row.get("separation_notes") or row.get("notes")),
        "packaging_boxes": row.get("packaging_boxes"),
        "packaging_bags": row.get("packaging_bags"),
        "packaging_weight_kg": row.get("packaging_weight_kg"),
        "packaging_height_cm": row.get("packaging_height_cm"),
        "packaging_width_cm": row.get("packaging_width_cm"),
        "packaging_length_cm": row.get("packaging_length_cm"),
        "packaging_volumes": row.get("packaging_volumes"),
        "order_id": tiny_order_id,
        "order_number": tiny_order_number,
        "pedido": tiny_order_number,
        "cliente": client_name,
        "vendedor": seller_name,
        "envio": row.get("shipping_method_name") or "",
        "frete": row.get("freight_method_name") or "",
    }
    return out


_TABLE_COLUMNS_CACHE: Dict[str, set] = {}


def _table_columns(schema: str, table: str) -> set:
    cache_key = f"{schema}.{table}"
    cached = _TABLE_COLUMNS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema, table),
            )
            cols = {
                _clean_str(row.get("column_name")).lower()
                for row in cur.fetchall()
                if _clean_str(row.get("column_name"))
            }

    _TABLE_COLUMNS_CACHE[cache_key] = cols
    return cols


def _boolish(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        return bool(v)
    s = _clean_str(v).lower()
    if s in {"1", "true", "t", "yes", "y", "sim", "s", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "nao", "não", "off", ""}:
        return False
    return bool(v)


def _int_or_zero(v: Any) -> int:
    try:
        if v is None or v == "":
            return 0
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return 0


def _iso_value(v: Any):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _reverse_separation_status(value: Any) -> Optional[str]:
    s = _clean_str(value).lower()
    if not s:
        return None
    if s == "a separar":
        return None
    if s == "separando":
        return "Preparando Envio"
    if s == "separado":
        return "Pronto para Envio"
    if s == "entregue":
        return "Faturado"
    if s == "cancelado":
        return "Cancelado"
    return _clean_str(value)


def _separation_detail_order_row(row: Dict[str, Any]) -> Dict[str, Any]:
    base = _separation_list_row(row)
    notes = (
        _clean_str(row.get("notes"))
        or _clean_str(row.get("separation_notes"))
        or _clean_str(row.get("internal_notes"))
    )
    operator_name = _clean_str(row.get("operator_name") or row.get("assigned_to"))
    boxes = _int_or_zero(row.get("boxes") if row.get("boxes") is not None else row.get("packaging_boxes"))
    bags = _int_or_zero(row.get("bags") if row.get("bags") is not None else row.get("packaging_bags"))
    separation_status = _separation_status_from_row(row) or base.get("separation_status") or "A separar"

    detail = dict(base)
    detail.update(
        {
            "separation_status": separation_status,
            "printed": _boolish(row.get("printed")),
            "label_printed": _boolish(row.get("label_printed")),
            "operator_name": operator_name,
            "assigned_to": operator_name,
            "boxes": boxes,
            "packaging_boxes": boxes,
            "bags": bags,
            "packaging_bags": bags,
            "notes": notes,
            "separation_notes": notes,
            "internal_notes": notes,
            "printed_at": _iso_value(row.get("printed_at")),
            "label_printed_at": _iso_value(row.get("label_printed_at")),
            "started_at": _iso_value(row.get("started_at")),
            "separated_at": _iso_value(row.get("separated_at")),
            "checked_at": _iso_value(row.get("checked_at")),
            "packaging_weight_kg": row.get("packaging_weight_kg"),
            "packaging_height_cm": row.get("packaging_height_cm"),
            "packaging_width_cm": row.get("packaging_width_cm"),
            "packaging_length_cm": row.get("packaging_length_cm"),
            "packaging_volumes": row.get("packaging_volumes"),
            "created_at": _iso_value(row.get("created_at")),
            "updated_at": _iso_value(row.get("updated_at")),
        }
    )
    return detail


def _separation_detail_item_row(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_quote_item_financials(row)
    return {
        "line": normalized.get("line"),
        "product_id": normalized.get("product_id"),
        "sku": normalized.get("sku"),
        "codigo": normalized.get("codigo"),
        "nome": normalized.get("nome"),
        "descricao": normalized.get("descricao"),
        "name_snapshot": normalized.get("name_snapshot"),
        "sku_snapshot": normalized.get("sku_snapshot"),
        "qty": normalized.get("qty"),
        "quantity": normalized.get("quantity"),
        "list_price": normalized.get("list_price"),
        "discount_pct": normalized.get("discount_pct"),
        "unit_price_disc": normalized.get("unit_price_disc"),
        "unit_price": normalized.get("unit_price"),
        "line_total": normalized.get("line_total"),
        "total_price": normalized.get("total_price"),
        "cost_price": normalized.get("cost_price"),
        "average_cost": normalized.get("average_cost"),
        "unit_cost": normalized.get("unit_cost"),
        "cost_total": normalized.get("cost_total"),
        "profit": normalized.get("profit"),
        "markup_pct": normalized.get("markup_pct"),
        "product_snapshot": normalized.get("product_snapshot"),
        "raw": normalized.get("raw"),
    }


def _load_separation_order_detail(company_key: str, tiny_order_id: Any):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    q.*,
                    so.status AS separation_order_status,
                    so.printed,
                    so.label_printed,
                    so.printed_at,
                    so.label_printed_at,
                    so.started_at,
                    so.separated_at,
                    so.checked_at,
                    so.awaiting_conference,
                    so.separation_photo_url,
                    so.conference_photo_url,
                    so.assigned_to,
                    so.operator_name,
                    so.notes AS separation_notes,
                    so.packaging_boxes,
                    so.packaging_bags,
                    so.packaging_weight_kg,
                    so.packaging_height_cm,
                    so.packaging_width_cm,
                    so.packaging_length_cm,
                    so.packaging_volumes,
                    so.created_at AS separation_created_at,
                    so.updated_at AS separation_updated_at
                FROM erp.quotes q
                LEFT JOIN erp.separation_orders so
                    ON so.tiny_order_id = q.tiny_order_id
                   AND so.company_key = q.company_key
                WHERE q.tiny_order_id=%s AND q.company_key=%s
                LIMIT 1
                """,
                (tiny_order_id, company_key),
            )
            quote = cur.fetchone()
            if not quote:
                return None

            quote_id = quote.get("quote_id")
            cur.execute(
                "SELECT * FROM erp.quote_items WHERE quote_id=%s ORDER BY line",
                (quote_id,),
            )
            items = [dict(r) for r in cur.fetchall()]

    order = _separation_detail_order_row(dict(quote))
    detail_items = [_separation_detail_item_row(item) for item in items]
    return order, detail_items


@app.get("/separation/orders")
@app.get("/api/separation/orders")
def list_separation_orders(
    company: str = "parton",
    status: str = "",
    q: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    company_key = _company_key(company)
    q_norm = str(q or "").strip().lower()
    status_norm = str(status or "").strip().lower()

    where = [
        "q.company_key = %s",
        "q.tiny_order_id IS NOT NULL",
    ]
    params: List[Any] = [company_key]

    if status_norm:
        if status_norm in {"a separar", "separando", "separado", "entregue", "cancelado"}:
            if status_norm == "a separar":
                where.append(
                    "LOWER(COALESCE(q.internal_status, '')) NOT IN ('preparando envio', 'pronto para envio', 'faturado', 'cancelado') "
                    "AND LOWER(COALESCE(so.status, '')) <> 'cancelado'"
                )
            elif status_norm == "separando":
                where.append("LOWER(COALESCE(q.internal_status, '')) = 'preparando envio'")
            elif status_norm == "separado":
                where.append("LOWER(COALESCE(q.internal_status, '')) = 'pronto para envio'")
            elif status_norm == "entregue":
                where.append("LOWER(COALESCE(q.internal_status, '')) = 'faturado'")
            elif status_norm == "cancelado":
                where.append(
                    "(LOWER(COALESCE(q.internal_status, '')) = 'cancelado' OR LOWER(COALESCE(so.status, '')) = 'cancelado')"
                )
        else:
            where.append("LOWER(COALESCE(q.internal_status, '')) = %s")
            params.append(status_norm)

    if q_norm:
        where.append(
            "("
            "LOWER(COALESCE(CAST(q.tiny_order_id AS TEXT), '')) LIKE %s OR "
            "LOWER(COALESCE(CAST(q.tiny_order_number AS TEXT), '')) LIKE %s OR "
            "LOWER(COALESCE(CAST(q.quote_number AS TEXT), '')) LIKE %s OR "
            "LOWER(COALESCE(q.client_snapshot->>'nome', '')) LIKE %s OR "
            "LOWER(COALESCE(q.seller_name, '')) LIKE %s"
            ")"
        )
        like = f"%{q_norm}%"
        params.extend([like, like, like, like, like])

    sql = f"""
    SELECT
        q.quote_id,
        q.quote_number,
        q.company_key,
        q.tiny_order_id,
        q.tiny_order_number,
        q.status,
        q.internal_status,
        q.client_snapshot,
        q.seller_name,
        q.shipping_method_name,
        q.freight_method_name,
        q.created_at,
        q.updated_at,
        so.status AS separation_order_status,
        so.printed,
        so.label_printed,
        so.printed_at,
        so.label_printed_at,
        so.started_at,
        so.separated_at,
        so.checked_at,
        so.awaiting_conference,
        so.separation_photo_url,
        so.conference_photo_url,
        so.assigned_to,
        so.operator_name,
        so.notes AS separation_notes,
        so.packaging_boxes,
        so.packaging_bags,
        so.packaging_weight_kg,
        so.packaging_height_cm,
        so.packaging_width_cm,
        so.packaging_length_cm,
        so.packaging_volumes
    FROM erp.quotes q
    LEFT JOIN erp.separation_orders so
      ON so.tiny_order_id = q.tiny_order_id
     AND so.company_key = q.company_key
    WHERE {' AND '.join(where)}
    ORDER BY q.updated_at DESC NULLS LAST, q.created_at DESC NULLS LAST
    LIMIT %s OFFSET %s
    """
    params.extend([int(limit), int(offset)])

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM erp.quotes q
                LEFT JOIN erp.separation_orders so
                  ON so.tiny_order_id = q.tiny_order_id
                 AND so.company_key = q.company_key
                WHERE {' AND '.join(where)}
                """,
                params[:-2],
            )
            total = int((cur.fetchone() or {}).get("total") or 0)

    items = [_separation_list_row(row) for row in rows]
    return {
        "ok": True,
        "items": items,
        "count": len(items),
        "total": total,
        "company": company_key,
    }


@app.get("/separation/orders/{tiny_order_id}")
@app.get("/api/separation/orders/{tiny_order_id}")
def get_separation_order_detail(tiny_order_id: str, company: str = "parton"):
    company_key = _company_key(company)
    detail = _load_separation_order_detail(company_key, tiny_order_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    order, items = detail
    return {"ok": True, "order": order, "items": items}


@app.patch("/separation/orders/{tiny_order_id}")
@app.patch("/api/separation/orders/{tiny_order_id}")
def patch_separation_order_detail(tiny_order_id: str, payload: Dict[str, Any], request: Request, company: str = "parton"):
    company_key = _company_key(company)
    try:
        tiny_order_id_int = int(str(tiny_order_id).strip())
    except Exception:
        raise HTTPException(status_code=400, detail="tiny_order_id inválido.")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    q.*,
                    so.status AS separation_order_status,
                    so.printed,
                    so.label_printed,
                    so.printed_at,
                    so.label_printed_at,
                    so.started_at,
                    so.separated_at,
                    so.checked_at,
                    so.awaiting_conference,
                    so.separation_photo_url,
                    so.conference_photo_url,
                    so.assigned_to,
                    so.operator_name,
                    so.notes AS separation_notes,
                    so.packaging_boxes,
                    so.packaging_bags,
                    so.packaging_weight_kg,
                    so.packaging_height_cm,
                    so.packaging_width_cm,
                    so.packaging_length_cm,
                    so.packaging_volumes,
                    so.created_at AS separation_created_at,
                    so.updated_at AS separation_updated_at
                FROM erp.quotes q
                LEFT JOIN erp.separation_orders so
                  ON so.tiny_order_id = q.tiny_order_id
                 AND so.company_key = q.company_key
                WHERE q.tiny_order_id=%s AND q.company_key=%s
                LIMIT 1
                """,
                (tiny_order_id_int, company_key),
            )
            quote = cur.fetchone()
            if not quote:
                raise HTTPException(status_code=404, detail="Pedido não encontrado.")

            quote = dict(quote)
            quote_id = quote.get("quote_id")
            quote_number = quote.get("quote_number")
            tiny_order_number = quote.get("tiny_order_number")
            client_name = _clean_str(_client_name_from_snapshot(quote.get("client_snapshot")))
            seller_name = _clean_str(quote.get("seller_name"))

            current_sep_status = _separation_status_from_row(quote)
            explicit_status = _clean_str(
                payload.get("status")
                if "status" in payload
                else payload.get("separation_status")
            )
            explicit_internal_status = _clean_str(payload.get("internal_status"))
            explicit_status_norm = _normalize_status_text(explicit_status)
            explicit_internal_norm = _normalize_status_text(explicit_internal_status)
            current_internal_norm = _normalize_status_text(quote.get("internal_status"))
            printed_requested = _boolish(payload.get("printed")) if "printed" in payload else False

            target_operational_status = current_sep_status or "A separar"
            target_internal_status = _clean_str(quote.get("internal_status"))
            tiny_target_status = ""

            if explicit_status_norm == "separando" or explicit_internal_norm == "preparando envio":
                target_operational_status = "Separando"
                target_internal_status = "Preparando Envio"
                tiny_target_status = "preparando envio"
            elif explicit_status_norm == "separado" or explicit_internal_norm == "pronto para envio":
                target_operational_status = "Separado"
                target_internal_status = "Pronto para Envio"
                tiny_target_status = "pronto para envio"
            elif explicit_status_norm == "cancelado" or explicit_internal_norm == "cancelado":
                target_operational_status = "Cancelado"
                target_internal_status = "Cancelado"
            elif explicit_status_norm == "entregue" or explicit_internal_norm == "faturado":
                target_operational_status = "Entregue"
                target_internal_status = "Faturado"
            elif printed_requested and current_sep_status in {"A separar", "Aprovado"} and current_internal_norm in {"", "aprovado"}:
                target_operational_status = "Separando"
                target_internal_status = "Preparando Envio"
                tiny_target_status = "preparando envio"

            if tiny_target_status:
                try:
                    _tiny_sync_and_verify_status(
                        company_key,
                        tiny_order_id_int,
                        tiny_target_status,
                        "separation-preparing-shipment" if tiny_target_status == "preparando envio" else "separation-ready-to-ship",
                    )
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=str(exc))

            separation_updates: Dict[str, Any] = {
                "tiny_order_id": tiny_order_id_int,
                "tiny_order_number": tiny_order_number,
                "quote_id": quote_id,
                "quote_number": quote_number,
                "company_key": company_key,
                "client_name": client_name,
                "seller_name": seller_name,
                "status": target_operational_status,
                "updated_at": _now(),
            }

            for field in ("printed", "label_printed", "assigned_to", "operator_name", "packaging_weight_kg",
                           "packaging_height_cm", "packaging_width_cm", "packaging_length_cm", "packaging_volumes"):
                if field in payload:
                    separation_updates[field] = payload.get(field)

            if "printed" in payload:
                printed = _boolish(payload.get("printed"))
                separation_updates["printed"] = printed
                if printed and not _clean_str(quote.get("printed_at")):
                    separation_updates.setdefault("printed_at", _now())
            if "label_printed" in payload:
                label_printed = _boolish(payload.get("label_printed"))
                separation_updates["label_printed"] = label_printed
                if label_printed and not _clean_str(quote.get("label_printed_at")):
                    separation_updates.setdefault("label_printed_at", _now())

            if "notes" in payload:
                separation_updates["notes"] = payload.get("notes")
            elif "separation_notes" in payload:
                separation_updates["notes"] = payload.get("separation_notes")
            elif "internal_notes" in payload:
                separation_updates["notes"] = payload.get("internal_notes")

            if "assigned_to" in payload and "operator_name" not in payload:
                separation_updates["operator_name"] = _clean_str(payload.get("assigned_to"))
            if "operator_name" in payload and "assigned_to" not in payload:
                separation_updates["assigned_to"] = _clean_str(payload.get("operator_name"))

            if "packaging_boxes" in payload:
                separation_updates["packaging_boxes"] = _int_or_zero(payload.get("packaging_boxes"))
            elif "boxes" in payload:
                separation_updates["packaging_boxes"] = _int_or_zero(payload.get("boxes"))

            if "packaging_bags" in payload:
                separation_updates["packaging_bags"] = _int_or_zero(payload.get("packaging_bags"))
            elif "bags" in payload:
                separation_updates["packaging_bags"] = _int_or_zero(payload.get("bags"))

            if target_operational_status == "Separando":
                separation_updates.setdefault("started_at", _now())
                if "started_at" in payload:
                    separation_updates["started_at"] = payload.get("started_at")
                if "printed" in payload and printed_requested and not _clean_str(quote.get("printed_at")):
                    separation_updates.setdefault("printed_at", _now())
            elif target_operational_status == "Separado":
                separation_updates.setdefault("started_at", quote.get("started_at") or _now())
                separation_updates.setdefault("separated_at", quote.get("separated_at") or _now())
                if "started_at" in payload:
                    separation_updates["started_at"] = payload.get("started_at")
                if "separated_at" in payload:
                    separation_updates["separated_at"] = payload.get("separated_at")
            elif target_operational_status == "Cancelado":
                pass
            elif target_operational_status == "Entregue":
                if "separated_at" in payload:
                    separation_updates["separated_at"] = payload.get("separated_at")

            if target_internal_status and target_internal_status != _clean_str(quote.get("internal_status")):
                cur.execute(
                    """
                    UPDATE erp.quotes
                    SET internal_status=%s,
                        updated_at=now()
                    WHERE quote_id=%s AND company_key=%s
                    """,
                    (target_internal_status, quote_id, company_key),
                )

            # Campos da etapa de Conferência. Kill-switch real (modo de conferência em
            # runtime, _sep_conferencia_enabled) + restrição por papel (admin/separacao),
            # espelhando o upload e a leitura da foto. Com OFF ou papel sem permissão,
            # são ignorados (não gravam).
            _conf_user = _auth_user_from_request(request) or {}
            _conf_role = _clean_str(_conf_user.get("role")).lower()
            if _sep_conferencia_enabled() and _conf_role in {"admin", "separacao"}:
                if "awaiting_conference" in payload:
                    separation_updates["awaiting_conference"] = _boolish(payload.get("awaiting_conference"))
                if "separation_photo_url" in payload:
                    separation_updates["separation_photo_url"] = _clean_str(payload.get("separation_photo_url"))
                if "conference_photo_url" in payload:
                    separation_updates["conference_photo_url"] = _clean_str(payload.get("conference_photo_url"))
                if "checked_at" in payload:
                    separation_updates["checked_at"] = payload.get("checked_at") or _now()

            _upsert_separation_order(tiny_order_id=tiny_order_id_int, values=separation_updates)

    detail = _load_separation_order_detail(company_key, tiny_order_id_int)
    if not detail:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    order, items = detail
    return {"ok": True, "order": order, "items": items}


def _separation_photos_dir() -> str:
    photo_dir = os.path.abspath(os.path.join(APP_ROOT, "storage", "separation-photos"))
    os.makedirs(photo_dir, exist_ok=True)
    return photo_dir


_IMAGE_EXT_TO_KIND = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".webp": "webp"}


def _sniff_image_kind(head: bytes) -> str:
    """Detecta o tipo real da imagem pelos magic bytes (assinatura), ignorando o
    content-type/extensão informados pelo cliente (ambos forjáveis)."""
    if len(head) >= 3 and head[0:3] == b"\xff\xd8\xff":
        return "jpg"
    if len(head) >= 8 and head[0:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return ""


@app.post("/separation/photos/upload")
@app.post("/api/separation/photos/upload")
async def upload_separation_photo(request: Request, file: UploadFile = File(...)):
    """Upload da foto de separação/conferência. Liberado ao operador de separação
    (admin OU is_separacao). Kill-switch real: exige a conferência ativada (runtime). Valida
    a ASSINATURA do arquivo (magic bytes), não só extensão/content-type (forjáveis).
    A foto NÃO é pública: é lida pela rota autenticada GET /separation/photos/{file}.
    """
    user = _require_auth_user(request)
    role = _clean_str(user.get("role")).lower()
    if role not in {"admin", "separacao"}:
        raise HTTPException(status_code=403, detail="Apenas separação ou admin.")
    if not _sep_conferencia_enabled():
        raise HTTPException(status_code=403, detail="Conferência desabilitada.")

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    content_type = _clean_str(file.content_type).lower()
    safe_name = _catalog_safe_image_filename(_clean_str(file.filename or "") or "separacao")
    ext = os.path.splitext(safe_name)[1].lower()
    expected_kind = _IMAGE_EXT_TO_KIND.get(ext)
    if content_type not in allowed_types or not expected_kind:
        raise HTTPException(status_code=400, detail="Envie uma imagem JPG, PNG ou WEBP.")

    photo_dir = _separation_photos_dir()
    base_name = f"sep-{secrets.token_hex(6)}-{safe_name}"
    filename, final_path = _catalog_unique_image_path(photo_dir, base_name)
    max_bytes = 10 * 1024 * 1024
    chunk_size = 1024 * 1024
    total = 0
    try:
        first = await file.read(chunk_size)
        # Assinatura tem que existir E bater com a extensão declarada (anti-polyglot).
        if _sniff_image_kind(first) != expected_kind:
            raise HTTPException(status_code=400, detail="Arquivo não é uma imagem válida (assinatura não confere).")
        with open(final_path, "wb") as out:
            chunk = first
            while chunk:
                total += len(chunk)
                if total > max_bytes:
                    out.close()
                    try:
                        os.remove(final_path)
                    except OSError:
                        pass
                    raise HTTPException(status_code=400, detail="Imagem maior que 10 MB.")
                out.write(chunk)
                chunk = await file.read(chunk_size)
    finally:
        await file.close()

    return {"ok": True, "filename": filename, "url": f"/api/separation/photos/{filename}"}


@app.get("/separation/photos/{filename}")
@app.get("/api/separation/photos/{filename}")
def get_separation_photo(filename: str, request: Request):
    """Serve a foto de separação/conferência de forma AUTENTICADA e restrita por
    papel (admin OU separacao). Substitui o StaticFiles público: as fotos podem
    conter PII (etiqueta com nome/endereço do cliente, conteúdo do pedido).
    """
    user = _require_auth_user(request)
    role = _clean_str(user.get("role")).lower()
    if role not in {"admin", "separacao"}:
        raise HTTPException(status_code=403, detail="Apenas separação ou admin.")

    photo_dir = _separation_photos_dir()
    safe = os.path.basename(_clean_str(filename))
    target = os.path.abspath(os.path.join(photo_dir, safe))
    root = os.path.abspath(photo_dir)
    if not (target == root or target.startswith(root + os.sep)) or not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Foto não encontrada.")
    return FileResponse(target)


@app.get("/admin/settings/conferencia")
@app.get("/api/admin/settings/conferencia")
def admin_get_conferencia_setting(request: Request):
    """Lê o estado runtime da etapa de Conferência (admin-only)."""
    user = _require_auth_user(request)
    if _clean_str(user.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")
    mode = _sep_conferencia_mode()
    return {"ok": True, "mode": mode, "enabled": mode != "off"}


@app.put("/admin/settings/conferencia")
@app.put("/api/admin/settings/conferencia")
@app.post("/admin/settings/conferencia")
@app.post("/api/admin/settings/conferencia")
def admin_set_conferencia_setting(payload: Dict[str, Any], request: Request):
    """Liga/desliga (e define o modo de) a etapa de Conferência em runtime, sem
    reiniciar o ERP. Admin-only. Aceita {"mode": off|soft|strict} ou {"enabled": bool}.
    """
    user = _require_auth_user(request)
    if _clean_str(user.get("role")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin.")

    payload = payload or {}
    if "mode" in payload:
        mode = _clean_str(payload.get("mode")).lower()
        if mode not in {"off", "soft", "strict"}:
            raise HTTPException(status_code=400, detail="mode inválido (off|soft|strict).")
    elif "enabled" in payload:
        mode = "soft" if _boolish(payload.get("enabled")) else "off"
    else:
        raise HTTPException(status_code=400, detail="Informe 'mode' ou 'enabled'.")

    saved = _set_sep_conferencia_mode(mode)
    return {"ok": True, "mode": saved, "enabled": saved != "off"}


def _gen_order_op_ref(ok: bool, *, quote_id: str, company_key: str, status: str) -> Dict[str, str]:
    """Gera um código legível + hash de rastreio para a operação de criar pedido.
    Usado tanto em sucesso quanto em erro, para rastreabilidade no modal/log."""
    now = dt.datetime.now()
    rand = secrets.token_hex(3).upper()  # 6 caracteres hex
    code = f"PED-{'OK' if ok else 'ERR'}-{now.strftime('%Y%m%d-%H%M%S')}-{rand}"
    raw = f"{code}|{company_key}|{quote_id}|{status}|{now.isoformat()}|{secrets.token_hex(8)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {"code": code, "hash": digest}


def _stock_check_items_for_order(tiny: TinyClient, stock_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Consulta o estoque no Tiny para os itens do pedido ANTES de criá-lo.

    Retorna:
      {"ok": True}                                            -> todos os itens com saldo suficiente
      {"ok": False, "reason": "stock_check_error", ...}       -> falha ao consultar o Tiny
      {"ok": False, "reason": "insufficient_stock", ...}      -> algum item sem saldo suficiente

    Observações de robustez:
      - Agrega a quantidade necessária por produto (mesmo produto em várias linhas).
      - Considera o saldo disponível = saldo - saldoReservado quando o Tiny informa reserva.
      - Se a resposta do Tiny não trouxer um campo de saldo reconhecível, NÃO bloqueia por
        insuficiência (evita travar toda criação de pedido por mudança de formato da API);
        apenas a falha de consulta (exceção) bloqueia nesse cenário.
    """
    needed_by_product: Dict[int, Dict[str, Any]] = {}
    for it in stock_items:
        pid = _safe_int(it.get("product_id"))
        qty = _safe_float(it.get("qty"), 0.0)
        if not pid or qty <= 0:
            continue
        agg = needed_by_product.setdefault(
            pid,
            {"qty": 0.0, "sku": _clean_str(it.get("sku")), "name": _clean_str(it.get("name"))},
        )
        agg["qty"] += qty

    faltantes: List[Dict[str, Any]] = []
    for pid, info in needed_by_product.items():
        try:
            estoque = tiny.obter_estoque_produto(pid)
        except TinyAPIError as e:
            return {"ok": False, "reason": "stock_check_error", "detail": str(e), "product_id": pid}

        produto = (estoque or {}).get("produto")
        if not isinstance(produto, dict):
            produto = {}

        saldo_raw = produto.get("saldo")
        if saldo_raw is None and isinstance(estoque, dict):
            saldo_raw = estoque.get("saldo")
        if saldo_raw is None:
            # Sem campo de saldo reconhecível: consulta OK, não bloqueia por insuficiência.
            continue

        saldo = _safe_float(saldo_raw, 0.0)
        reservado = _safe_float(
            produto.get("saldoReservado") or produto.get("saldo_reservado") or 0, 0.0
        )
        disponivel = saldo - reservado
        if disponivel < info["qty"]:
            faltantes.append(
                {
                    "product_id": pid,
                    "sku": info["sku"],
                    "name": info["name"],
                    "needed": round(info["qty"], 4),
                    "available": round(disponivel, 4),
                }
            )

    if faltantes:
        return {"ok": False, "reason": "insufficient_stock", "faltantes": faltantes}
    return {"ok": True}


@app.post("/quotes/{quote_id}/order")
@app.post("/api/quotes/{quote_id}/order")
def create_order_from_quote_local(request: Request, quote_id: str, company: str = "parton"):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    quote_seller_scope = _resolve_quote_seller_scope(user, company_key)
    tiny = _tiny_for_company(company_key)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM erp.quotes WHERE quote_id=%s AND company_key=%s LIMIT 1",
                (quote_id, company_key),
            )
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail="Orçamento não encontrado.")

            quote = dict(q)
            _assert_quote_seller_scope(quote, quote_seller_scope)
            if quote.get("tiny_order_id"):
                ref = _gen_order_op_ref(
                    True, quote_id=quote_id, company_key=company_key, status="already_exists"
                )
                return {
                    "ok": True,
                    "status": "already_exists",
                    "title": "Pedido já criado",
                    "message": "Pedido já existe para este orçamento.",
                    "code": ref["code"],
                    "hash": ref["hash"],
                    "quote_id": quote_id,
                    "quote_number": quote.get("quote_number"),
                    "tiny_order_id": quote.get("tiny_order_id"),
                    "tiny_order_number": quote.get("tiny_order_number"),
                    "company": company_key,
                }

            cur.execute(
                "SELECT * FROM erp.quote_items WHERE quote_id=%s ORDER BY line",
                (quote_id,),
            )
            items = [dict(r) for r in cur.fetchall()]

    if not items:
        raise HTTPException(status_code=400, detail="Orçamento não possui itens.")

    payload_saved = _from_json(quote.get("payload"), {}) or {}
    client_raw = _from_json(quote.get("client_snapshot"), {}) or {}
    totals = _from_json(quote.get("totals"), {}) or {}
    client_name = _clean_str(_client_name_from_snapshot(client_raw))
    if not client_name:
        raise HTTPException(status_code=400, detail="Cliente sem nome no snapshot do orçamento.")

    def _pick_first_nonempty(source, *keys):
        if not isinstance(source, dict):
            return ""
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip() != "":
                return str(value).strip()
        return ""

    def _parse_due_date(value):
        raw = _clean_str(value)
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(raw, fmt).date()
            except Exception:
                pass
        return None

    def _build_parcelas(total_value):
        installments = payload_saved.get("payment_installments") or []
        quote_due_date = _parse_due_date(
            payload_saved.get("payment_due_date") or quote.get("payment_due_date")
        )
        base_date = quote_due_date or dt.datetime.now().date()
        parcelas_payload = []
        payment_code = payment_code_tiny or ""
        payment_meio = meio_txt or ""
        payment_conta = portador_txt or ""

        if isinstance(installments, list) and installments:
            for inst in installments:
                if not isinstance(inst, dict):
                    continue
                amount = _safe_float(inst.get("amount"), 0.0)
                if amount <= 0:
                    continue
                due_date = _parse_due_date(inst.get("due_date"))
                parcela = {
                    "dias": max(0, (due_date - base_date).days) if due_date else 0,
                    "valor": round(amount, 2),
                    "destino": "Contas a Receber",
                }
                if due_date:
                    parcela["data"] = due_date.strftime("%d/%m/%Y")
                if payment_code:
                    parcela["forma_pagamento"] = payment_code
                if payment_meio:
                    parcela["meio_pagamento"] = payment_meio
                if payment_conta:
                    parcela["portador"] = payment_conta
                parcelas_payload.append({"parcela": parcela})

        if not parcelas_payload and total_value > 0:
            parcela = {
                "dias": 0,
                "valor": round(total_value, 2),
                "data": base_date.strftime("%d/%m/%Y"),
                "destino": "Contas a Receber",
            }
            if payment_code:
                parcela["forma_pagamento"] = payment_code
            if payment_meio:
                parcela["meio_pagamento"] = payment_meio
            if payment_conta:
                parcela["portador"] = payment_conta
            parcelas_payload.append({"parcela": parcela})

        return parcelas_payload

    itens_payload = []
    stock_items = []
    total_pedido = 0.0
    for item in items:
        qty = _safe_float(item.get("qty"), 0.0)
        unit_price = _safe_float(item.get("unit_price_disc"), 0.0)
        if qty <= 0 or unit_price <= 0:
            continue
        total_pedido = round(total_pedido + (qty * unit_price), 2)
        stock_items.append(
            {
                "product_id": _safe_int(item.get("product_id")),
                "qty": qty,
                "sku": _clean_str(item.get("sku_snapshot")),
                "name": _clean_str(item.get("name_snapshot")),
            }
        )
        itens_payload.append(
            {
                "item": {
                    "id_produto": int(item.get("product_id")),
                    "codigo": _clean_str(item.get("sku_snapshot")),
                    "descricao": _clean_str(item.get("name_snapshot")),
                    "unidade": "Un",
                    "quantidade": qty,
                    "valor_unitario": round(unit_price, 2),
                }
            }
        )

    if not itens_payload:
        raise HTTPException(status_code=400, detail="Nenhum item válido para criar pedido.")

    cliente_payload = {
        "nome": client_name,
        "atualizar_cliente": "N",
    }
    for target, keys in (
        ("cpf_cnpj", ("cpf_cnpj",)),
        ("email", ("email",)),
        ("fone", ("fone", "telefone")),
        ("tipo_pessoa", ("tipo_pessoa",)),
        ("ie", ("ie",)),
        ("rg", ("rg",)),
        ("endereco", ("endereco",)),
        ("numero", ("numero",)),
        ("complemento", ("complemento",)),
        ("bairro", ("bairro",)),
        ("cep", ("cep",)),
        ("cidade", ("cidade",)),
        ("uf", ("uf",)),
        ("pais", ("pais", "nome_pais")),
    ):
        value = _pick_first_nonempty(client_raw, *keys)
        if value:
            cliente_payload[target] = value

    notes = _clean_str(quote.get("notes"))
    internal_notes = _clean_str(
        payload_saved.get("internal_notes") or payload_saved.get("internalNotes")
    )
    freight_paid_client = _safe_float(
        payload_saved.get("freight_paid_client"),
        _safe_float(totals.get("freight_paid_client"), 0.0),
    )
    freight_paid_company = _safe_float(
        payload_saved.get("freight_paid_company"),
        _safe_float(totals.get("freight_paid_company"), 0.0),
    )

    _assert_payment_conta_company_scope(company_key, quote.get("payment_conta"))
    payment_code_rule, payment_meio_rule, payment_conta_rule = _apply_payment_business_rules(
        quote.get("payment_method_code"),
        quote.get("payment_meio"),
        quote.get("payment_conta"),
        company_key=company_key,
    )
    payment_code_tiny = _map_payment_code_for_tiny(payment_code_rule)
    meio_txt = _resolve_meio_pagamento_tiny(payment_meio_rule, payment_conta_rule)
    portador_txt = _resolve_portador_nome(payment_conta_rule)

    if payment_code_tiny == "link_pagamento":
        portador_txt = None

    pedido = {
        "id_vendedor": int(quote.get("seller_id") or 0),
        "data_pedido": dt.datetime.now().strftime("%d/%m/%Y"),
        "cliente": cliente_payload,
        "itens": itens_payload,
        "obs": notes,
        "situacao": "aberto",
    }

    if internal_notes:
        pedido["obs_internas"] = internal_notes
    if payment_code_tiny:
        pedido["forma_pagamento"] = payment_code_tiny
    if meio_txt:
        pedido["meio_pagamento"] = meio_txt
    if portador_txt:
        pedido["portador"] = portador_txt

    parcelas_payload = _build_parcelas(total_pedido)
    if parcelas_payload:
        pedido["parcelas"] = parcelas_payload

    if _clean_str(quote.get("shipping_method_name")):
        pedido["forma_envio"] = _clean_str(quote.get("shipping_method_name"))
    if _clean_str(quote.get("freight_method_name")):
        pedido["forma_frete"] = _clean_str(quote.get("freight_method_name"))
    if freight_paid_client > 0:
        pedido["valor_frete"] = round(freight_paid_client, 2)
    if freight_paid_company > 0:
        pedido["outras_despesas"] = round(freight_paid_company, 2)

    # --- Checagem obrigatória de estoque no Tiny ANTES de criar o pedido ---
    stock_result = _stock_check_items_for_order(tiny, stock_items)
    if not stock_result.get("ok"):
        reason = stock_result.get("reason") or "stock_check_failed"
        ref = _gen_order_op_ref(False, quote_id=quote_id, company_key=company_key, status=reason)
        if reason == "insufficient_stock":
            faltantes = stock_result.get("faltantes") or []
            resumo = "; ".join(
                f"{(f.get('name') or f.get('sku') or f.get('product_id'))} "
                f"(disponível {f.get('available')}, necessário {f.get('needed')})"
                for f in faltantes
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "status": "insufficient_stock",
                    "title": "PEDIDO NÃO CRIADO",
                    "message": f"Estoque insuficiente: {resumo}"
                    if resumo
                    else "Estoque insuficiente para um ou mais itens.",
                    "code": ref["code"],
                    "hash": ref["hash"],
                    "faltantes": faltantes,
                    "quote_id": quote_id,
                    "company": company_key,
                },
            )
        raise HTTPException(
            status_code=502,
            detail={
                "ok": False,
                "status": "stock_check_failed",
                "title": "PEDIDO NÃO CRIADO",
                "message": "Erro ao verificar estoque, tente novamente em 30 segundos.",
                "code": ref["code"],
                "hash": ref["hash"],
                "retry_after_seconds": 30,
                "quote_id": quote_id,
                "company": company_key,
            },
        )

    try:
        resp = tiny.criar_pedido({"pedido": pedido})
    except TinyAPIError as e:
        ref = _gen_order_op_ref(False, quote_id=quote_id, company_key=company_key, status="order_create_failed")
        raise HTTPException(
            status_code=502,
            detail={
                "ok": False,
                "status": "order_create_failed",
                "title": "PEDIDO NÃO CRIADO",
                "message": str(e),
                "code": ref["code"],
                "hash": ref["hash"],
                "quote_id": quote_id,
                "company": company_key,
            },
        )

    reg = ((resp.get("registros") or {}).get("registro") or {})
    tiny_order_id = _safe_int(reg.get("id"))
    tiny_order_number = reg.get("numero")
    if not tiny_order_id:
        raise HTTPException(status_code=502, detail=f"Resposta do Tiny sem id do pedido: {resp}")

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.quotes
                SET tiny_order_id=%s,
                    tiny_order_number=%s,
                    status='ordered',
                    internal_status='Em Aberto',
                    ordered_at=now(),
                    updated_at=now()
                WHERE quote_id=%s AND company_key=%s
                  AND tiny_order_id IS NULL
                """,
                (tiny_order_id, str(tiny_order_number) if tiny_order_number else None, quote_id, company_key),
            )
            if cur.rowcount == 0:
                cur.execute(
                    "SELECT tiny_order_id, tiny_order_number FROM erp.quotes WHERE quote_id=%s AND company_key=%s LIMIT 1",
                    (quote_id, company_key),
                )
                existing = cur.fetchone()
                ref = _gen_order_op_ref(
                    True, quote_id=quote_id, company_key=company_key, status="already_exists"
                )
                return {
                    "ok": True,
                    "status": "already_exists",
                    "title": "Pedido já criado",
                    "message": "Pedido já existia para este orçamento.",
                    "code": ref["code"],
                    "hash": ref["hash"],
                    "quote_id": quote_id,
                    "quote_number": quote.get("quote_number"),
                    "tiny_order_id": existing.get("tiny_order_id") if existing else tiny_order_id,
                    "tiny_order_number": existing.get("tiny_order_number") if existing else tiny_order_number,
                    "company": company_key,
                }

    ref = _gen_order_op_ref(True, quote_id=quote_id, company_key=company_key, status="created")
    return {
        "ok": True,
        "status": "created",
        "title": "Pedido criado",
        "message": "Pedido criado",
        "code": ref["code"],
        "hash": ref["hash"],
        "quote_id": quote_id,
        "quote_number": quote.get("quote_number"),
        "tiny_order_id": tiny_order_id,
        "tiny_order_number": str(tiny_order_number) if tiny_order_number else None,
        "company": company_key,
    }


@app.post("/quotes/{quote_id}/cancel-order")
@app.post("/api/quotes/{quote_id}/cancel-order")
def cancel_order_from_quote_local(quote_id: str, company: str = "parton"):
    company_key = _company_key(company)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM erp.quotes WHERE quote_id=%s AND company_key=%s LIMIT 1",
                (quote_id, company_key),
            )
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail="Orçamento não encontrado.")

            quote = dict(q)

    current_internal = _clean_str(quote.get("internal_status"))
    tiny_order_id = quote.get("tiny_order_id")
    tiny_order_number = quote.get("tiny_order_number")

    if current_internal == "Cancelado":
        return {
            "ok": True,
            "quote_id": quote_id,
            "tiny_order_id": tiny_order_id,
            "tiny_order_number": tiny_order_number,
            "internal_status": "Cancelado",
            "company": company_key,
            "message": "Pedido já estava cancelado.",
        }

    if tiny_order_id:
        try:
            _tiny_sync_and_verify_status(company_key, tiny_order_id, "cancelado", "cancel-order")
        except TinyAPIError as e:
            raise HTTPException(status_code=502, detail=str(e))

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.quotes
                SET internal_status='Cancelado',
                    status='ordered',
                    updated_at=now()
                WHERE quote_id=%s AND company_key=%s
                """,
                (quote_id, company_key),
            )

    if tiny_order_id:
        _upsert_separation_order(
            tiny_order_id=tiny_order_id,
            values={
                "tiny_order_number": tiny_order_number,
                "quote_id": quote_id,
                "quote_number": quote.get("quote_number"),
                "company_key": company_key,
                "client_name": _clean_str(_client_name_from_snapshot(quote.get("client_snapshot"))),
                "seller_name": _clean_str(quote.get("seller_name")),
                "status": "Cancelado",
                "updated_at": _now(),
            },
        )

    return {
        "ok": True,
        "quote_id": quote_id,
        "tiny_order_id": tiny_order_id,
        "tiny_order_number": tiny_order_number,
        "internal_status": "Cancelado",
        "company": company_key,
    }


@app.post("/quotes/{quote_id}/approve-order")
@app.post("/api/quotes/{quote_id}/approve-order")
def approve_order_from_quote_local(quote_id: str, company: str = "parton"):
    company_key = _company_key(company)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM erp.quotes WHERE quote_id=%s AND company_key=%s LIMIT 1",
                (quote_id, company_key),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
            quote = dict(row)

    tiny_order_id = quote.get("tiny_order_id")
    tiny_order_number = quote.get("tiny_order_number")

    now_approved = _now()
    payload_saved = _from_json(quote.get("payload"), {}) or {}
    if not isinstance(payload_saved, dict):
        payload_saved = {}
    payload_saved["approved_at"] = now_approved.isoformat()

    if tiny_order_id:
        try:
            _tiny_sync_and_verify_status(company_key, tiny_order_id, "aprovado", "approve-order")
        except TinyAPIError as e:
            raise HTTPException(status_code=502, detail=str(e))

    with _db() as conn:
        with conn.cursor() as cur:
            if tiny_order_id:
                cur.execute(
                    """
                    UPDATE erp.quotes
                    SET internal_status='Aprovado',
                        status='ordered',
                        payload=%s,
                        updated_at=%s
                    WHERE quote_id=%s AND company_key=%s
                    """,
                    (psycopg2.extras.Json(payload_saved), now_approved, quote_id, company_key),
                )
            else:
                cur.execute(
                    """
                    UPDATE erp.quotes
                    SET internal_status='Aprovado',
                        payload=%s,
                        updated_at=%s
                    WHERE quote_id=%s AND company_key=%s
                    """,
                    (psycopg2.extras.Json(payload_saved), now_approved, quote_id, company_key),
                )

    if tiny_order_id:
        _upsert_separation_order(
            tiny_order_id=tiny_order_id,
            values={
                "tiny_order_number": tiny_order_number,
                "quote_id": quote_id,
                "quote_number": quote.get("quote_number"),
                "company_key": company_key,
                "client_name": _clean_str(_client_name_from_snapshot(quote.get("client_snapshot"))),
                "seller_name": _clean_str(quote.get("seller_name")),
                "status": "A separar",
                "updated_at": _now(),
            },
        )

    return {
        "ok": True,
        "status": "OK",
        "message": "Pedido aprovado com sucesso.",
        "quote_id": quote_id,
        "tiny_order_id": tiny_order_id,
        "tiny_order_number": tiny_order_number,
        "internal_status": "Aprovado",
        "company": company_key,
    }


@app.post("/quotes/{quote_id}/mark-invoiced")
@app.post("/api/quotes/{quote_id}/mark-invoiced")
def mark_invoiced_from_quote_local(quote_id: str, company: str = "parton"):
    company_key = _company_key(company)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM erp.quotes WHERE quote_id=%s AND company_key=%s LIMIT 1",
                (quote_id, company_key),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
            quote = dict(row)

    tiny_order_id = quote.get("tiny_order_id")
    tiny_order_number = quote.get("tiny_order_number")
    if not tiny_order_id:
        raise HTTPException(status_code=400, detail="Pedido sem tiny_order_id.")

    current_internal = _clean_str(quote.get("internal_status"))
    if current_internal == "Faturado":
        return {
            "ok": True,
            "status": "OK",
            "message": "Pedido já estava faturado.",
            "quote_id": quote_id,
            "tiny_order_id": tiny_order_id,
            "tiny_order_number": tiny_order_number,
            "internal_status": "Faturado",
            "company": company_key,
        }

    try:
        _tiny_sync_and_verify_status(company_key, tiny_order_id, "faturado", "mark-invoiced")
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.quotes
                SET internal_status='Faturado',
                    status='ordered',
                    updated_at=now()
                WHERE quote_id=%s AND company_key=%s
                """,
                (quote_id, company_key),
            )

    _upsert_separation_order(
        tiny_order_id=tiny_order_id,
        values={
            "tiny_order_number": tiny_order_number,
            "quote_id": quote_id,
            "quote_number": quote.get("quote_number"),
            "company_key": company_key,
            "client_name": _clean_str(_client_name_from_snapshot(quote.get("client_snapshot"))),
            "seller_name": _clean_str(quote.get("seller_name")),
            "status": "Entregue",
            "updated_at": _now(),
        },
    )

    return {
        "ok": True,
        "status": "OK",
        "message": "Pedido faturado com sucesso.",
        "quote_id": quote_id,
        "tiny_order_id": tiny_order_id,
        "tiny_order_number": tiny_order_number,
        "internal_status": "Faturado",
        "company": company_key,
    }


@app.post("/quotes/{quote_id}/clone")
@app.post("/api/quotes/{quote_id}/clone")
def clone_quote_local(quote_id: str, company: str = "parton"):
    company_key = _company_key(company)
    new_quote_id = uuid.uuid4().hex
    new_quote_number = _generate_quote_number()

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM erp.quotes WHERE quote_id=%s AND company_key=%s LIMIT 1",
                (quote_id, company_key),
            )
            source = cur.fetchone()
            if not source:
                raise HTTPException(status_code=404, detail="Orçamento não encontrado.")

            cur.execute(
                "SELECT * FROM erp.quote_items WHERE quote_id=%s ORDER BY line",
                (quote_id,),
            )
            items = [dict(r) for r in cur.fetchall()]

            clone_row = _quote_insertable_clone_row(dict(source), new_quote_id, new_quote_number, company_key)
            cur.execute(
                """
                INSERT INTO erp.quotes (
                    quote_id, quote_number, company_key, tiny_order_id, tiny_order_number, status, internal_status,
                    client_id, client_snapshot, seller_id, seller_name, seller_snapshot,
                    shipping_method_id, shipping_method_name, freight_method_id, freight_method_name,
                    payment_method_code, payment_method_name, payment_meio, payment_conta,
                    payment_due_date, payment_category, payment_notify,
                    totals, notes, payload, created_at, updated_at
                )
                VALUES (
                    %(quote_id)s, %(quote_number)s, %(company_key)s, %(tiny_order_id)s, %(tiny_order_number)s,
                    %(status)s, %(internal_status)s, %(client_id)s, %(client_snapshot)s::jsonb,
                    %(seller_id)s, %(seller_name)s, %(seller_snapshot)s::jsonb,
                    %(shipping_method_id)s, %(shipping_method_name)s, %(freight_method_id)s, %(freight_method_name)s,
                    %(payment_method_code)s, %(payment_method_name)s, %(payment_meio)s, %(payment_conta)s,
                    %(payment_due_date)s, %(payment_category)s, %(payment_notify)s,
                    %(totals)s::jsonb, %(notes)s, %(payload)s::jsonb, now(), now()
                )
                """,
                {
                    **clone_row,
                    "client_snapshot": _to_jsonb(clone_row["client_snapshot"]),
                    "seller_snapshot": _to_jsonb(clone_row["seller_snapshot"]),
                    "totals": _to_jsonb(clone_row["totals"]),
                    "payload": _to_jsonb(clone_row["payload"]),
                },
            )

            for it in items:
                item_row = dict(it)
                item_row["quote_id"] = new_quote_id
                cur.execute(
                    """
                    INSERT INTO erp.quote_items (
                        quote_id, line, product_id, sku_snapshot, name_snapshot,
                        qty, list_price, discount_pct, unit_price_disc, line_total, raw
                    )
                    VALUES (
                        %(quote_id)s, %(line)s, %(product_id)s, %(sku_snapshot)s, %(name_snapshot)s,
                        %(qty)s, %(list_price)s, %(discount_pct)s, %(unit_price_disc)s, %(line_total)s, %(raw)s::jsonb
                    )
                    """,
                    {**item_row, "raw": _to_jsonb(item_row.get("raw"))},
                )

    return {
        "ok": True,
        "source_quote_id": quote_id,
        "quote_id": new_quote_id,
        "quote_number": new_quote_number,
        "company": company_key,
    }


@app.post("/api/ops/sync-local-order-statuses")
@app.post("/ops/sync-local-order-statuses")
def ops_sync_local_order_statuses(company: str = "parton", limit: int = Query(default=5, ge=1, le=200)):
    company_key = _company_key(company)
    acquired = _OPS_SYNC_BATCH_LOCK.acquire(blocking=False)
    if not acquired:
        raise HTTPException(status_code=409, detail="Sincronização de status já está em andamento.")

    started = time.monotonic()
    try:
        result = _ops_run_sync_local_order_statuses_batch(company_key, limit=limit)
        return {
            "ok": True,
            "busy": False,
            "company": company_key,
            "checked": result["checked"],
            "updated_count": result["updated_count"],
            "skipped_count": result["skipped_count"],
            "errors": result["errors"],
            "total_verificado": result["total_verificado"],
            "total_atualizado": result["total_atualizado"],
            "selection_note": "Lote comum exclui pedidos terminalizados.",
            "excluded_terminal_statuses": ["Cancelado", "Faturado"],
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    finally:
        _OPS_SYNC_BATCH_LOCK.release()


@app.post("/api/ops/sync-local-order-status")
@app.post("/ops/sync-local-order-status")
def ops_sync_local_order_status(company: str = "parton", q: str = Query(default="")):
    company_key = _company_key(company)
    q_norm = str(q or "").strip()
    if not q_norm:
        raise HTTPException(status_code=400, detail="Informe o número ou ID do pedido.")

    row = _ops_find_local_order_row(company_key, q_norm)
    if not row:
        return {
            "ok": True,
            "found": False,
            "company": company_key,
            "message": "Pedido não encontrado na base local.",
            "search": q_norm,
        }

    quote_id = row.get("quote_id")
    tiny_order_id = row.get("tiny_order_id")
    tiny_order_number = row.get("tiny_order_number")
    internal_status = _normalize_ops_tiny_status(row.get("internal_status"))

    if not tiny_order_id:
        return {
            "ok": True,
            "found": True,
            "updated": False,
            "quote_id": quote_id,
            "tiny_order_id": None,
            "tiny_order_number": tiny_order_number,
            "internal_status": internal_status,
            "company": company_key,
            "message": "Registro local encontrado, mas sem tiny_order_id.",
        }

    tiny = _tiny_for_company(company_key)
    result = _ops_run_sync_one_local_order_status(tiny, company_key, dict(row))
    return {
        "ok": bool(result.get("ok", False)),
        "found": True,
        "updated": bool(result.get("updated")),
        "company": company_key,
        "quote_id": quote_id,
        "tiny_order_id": _safe_int(tiny_order_id),
        "tiny_order_number": result.get("tiny_order_number") or tiny_order_number,
        "internal_status": result.get("to") or internal_status,
    }


def _ops_sync_local_order_statuses_worker(company_key: str):
    try:
        _ops_sync_progress_update(
            running=True,
            started_at=_now().isoformat(),
            finished_at=None,
            updated_total=0,
            checked_total=0,
            rounds_completed=0,
            last_error="",
            last_result=None,
            company=company_key,
        )

        rows = _ops_fetch_local_order_status_rows(company_key, limit=None)
        tiny = _tiny_for_company(company_key)

        checked_total = 0
        updated_total = 0
        last_result = None

        for row in rows:
            checked_total += 1
            try:
                result = _ops_run_sync_one_local_order_status(tiny, company_key, row)
                last_result = result
                if result.get("updated"):
                    updated_total += 1
                if not result.get("ok") and result.get("error"):
                    _ops_sync_progress_update(last_error=str(result.get("error") or ""))
                _ops_sync_progress_update(
                    checked_total=checked_total,
                    updated_total=updated_total,
                    rounds_completed=checked_total,
                    last_result=result,
                )
            except Exception as e:
                _ops_sync_progress_update(
                    checked_total=checked_total,
                    updated_total=updated_total,
                    rounds_completed=checked_total,
                    last_error=str(e),
                )

        _ops_sync_progress_update(
            running=False,
            finished_at=_now().isoformat(),
            checked_total=checked_total,
            updated_total=updated_total,
            last_result=last_result,
        )
    except Exception as e:
        _ops_sync_progress_update(
            running=False,
            finished_at=_now().isoformat(),
            last_error=str(e),
        )


@app.post("/api/ops/start-sync-local-order-statuses")
@app.post("/ops/start-sync-local-order-statuses")
def ops_start_sync_local_order_statuses(company: str = "parton"):
    company_key = _company_key(company)
    snapshot = _ops_sync_progress_snapshot()
    if snapshot.get("running"):
        return {
            "ok": True,
            "started": False,
            "company": company_key,
            "message": "Sincronização já está em andamento.",
            "progress": snapshot,
        }

    _ops_sync_progress_reset()
    thread = threading.Thread(target=_ops_sync_local_order_statuses_worker, args=(company_key,), daemon=True)
    thread.start()

    return {
        "ok": True,
        "started": True,
        "company": company_key,
        "message": "Sincronização iniciada em segundo plano.",
        "progress": _ops_sync_progress_snapshot(),
    }


@app.get("/api/ops/sync-local-order-statuses-progress")
@app.get("/ops/sync-local-order-statuses-progress")
def ops_sync_local_order_statuses_progress(company: str = "parton"):
    company_key = _company_key(company)
    progress = _ops_sync_progress_snapshot()
    progress["company"] = company_key
    return {
        "ok": True,
        "company": company_key,
        "progress": progress,
    }


@app.get("/api/ops/tiny-sync-preview")
@app.get("/ops/tiny-sync-preview")
def ops_tiny_sync_preview(
    company: str = "parton",
    local_limit: int = Query(default=20, ge=1, le=500),
    include_remote: bool = Query(default=False),
    remote_pages: int = Query(default=0, ge=0, le=50),
    remote_search: str = Query(default=""),
):
    company_key = _company_key(company)
    rows, _total = _ops_list_local_tiny_order_rows(company_key, limit=local_limit, offset=0)
    local_items = [_separation_list_row(row) for row in rows]
    return {
        "ok": True,
        "company": company_key,
        "local_items": local_items,
        "remote_items": [],
        "count_local": len(local_items),
        "count_remote": 0,
        "source": "local_preview",
    }


@app.get("/api/ops/tiny-orders")
@app.get("/ops/tiny-orders")
def ops_tiny_orders(
    company: str = "parton",
    status: str = "",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    search: str = "",
    remote_pages: int = Query(default=0, ge=0, le=50),
):
    company_key = _company_key(company)
    offset = max(0, (int(page) - 1) * int(per_page))
    rows, total = _ops_list_local_tiny_order_rows(
        company_key,
        status=status,
        search=search,
        limit=per_page,
        offset=offset,
    )
    items = [_separation_list_row(row) for row in rows]
    return {
        "ok": True,
        "company": company_key,
        "items": items,
        "page": int(page),
        "per_page": int(per_page),
        "count": len(items),
        "total": total,
        "source": "local_postgresql",
    }


def _build_quote_records(payload: QuoteCreateIn, company_key: str, quote_id: Optional[str] = None):
    tiny = _tiny_for_company(company_key)

    client_resp = tiny.obter_contato(payload.client_id)
    client_raw = client_resp.get("contato") or client_resp.get("cliente") or client_resp
    if isinstance(client_raw, dict) and isinstance(client_raw.get("contato"), dict):
        client_raw = client_raw.get("contato") or {}
    if isinstance(client_raw, dict) and isinstance(client_raw.get("cliente"), dict):
        client_raw = client_raw.get("cliente") or {}

    fe = tiny.obter_forma_envio(payload.shipping_method_id)
    forma_envio = fe.get("forma_envio") or {}
    shipping_name = (forma_envio.get("nome") or "").strip()

    freight_name = ""
    if payload.freight_method_id:
        for f in (forma_envio.get("formas_frete") or []):
            try:
                if int(f.get("id")) == int(payload.freight_method_id):
                    freight_name = (f.get("descricao") or "").strip()
                    break
            except Exception:
                pass

    payment_code = _normalize_payment_code(payload.payment_method_code)
    payment_name = PAYMENT_METHODS.get(payment_code) or payload.payment_method_code

    items = []
    total_items = 0.0

    for idx, it in enumerate(payload.items or [], start=1):
        if float(it.discount_pct or 0) > MAX_DISCOUNT_PCT:
            raise HTTPException(status_code=400, detail=f"Desconto acima do permitido na linha {idx}.")

        p_resp = tiny.obter_produto(it.product_id)
        p_raw = p_resp.get("produto") or p_resp
        sku = p_raw.get("codigo") or p_raw.get("sku") or ""
        name = p_raw.get("nome") or p_raw.get("descricao") or ""

        qty = float(it.qty)
        unit = float(it.unit_price_disc)
        line_total = round(qty * unit, 2)
        total_items += line_total

        items.append({
            "quote_id": quote_id,
            "line": idx,
            "product_id": int(it.product_id),
            "sku_snapshot": sku,
            "name_snapshot": name,
            "qty": qty,
            "list_price": float(it.list_price),
            "discount_pct": float(it.discount_pct),
            "unit_price_disc": unit,
            "line_total": line_total,
            "raw": p_raw,
        })

    freight_client = float(payload.freight_paid_client or 0)
    freight_company = float(payload.freight_paid_company or 0)
    net = round(total_items + freight_client + freight_company, 2)

    quote = {
        "quote_id": quote_id or uuid.uuid4().hex,
        "quote_number": _generate_quote_number(),
        "company_key": company_key,
        "tiny_order_id": None,
        "tiny_order_number": None,
        "status": "draft",
        "internal_status": None,
        "client_id": int(payload.client_id),
        "client_snapshot": client_raw,
        "seller_id": int(payload.seller_id),
        "seller_name": _clean_str(payload.seller_name),
        "seller_snapshot": {"id": int(payload.seller_id), "name": _clean_str(payload.seller_name)},
        "shipping_method_id": int(payload.shipping_method_id),
        "shipping_method_name": shipping_name,
        "freight_method_id": int(payload.freight_method_id) if payload.freight_method_id else None,
        "freight_method_name": freight_name or None,
        "payment_method_code": payment_code,
        "payment_method_name": payment_name,
        "payment_meio": _clean_str(payload.payment_meio),
        "payment_conta": _clean_str(payload.payment_conta),
        "payment_due_date": _clean_str(payload.payment_due_date),
        "payment_category": _clean_str(payload.payment_category),
        "payment_notify": bool(payload.payment_notify),
        "totals": {
            "net": net,
            "items": round(total_items, 2),
            "freight_paid_client": freight_client,
            "freight_paid_company": freight_company,
        },
        "notes": _clean_str(payload.notes),
        "payload": {
            **payload.model_dump(),
            "internal_notes": _clean_str(payload.internal_notes or payload.internalNotes),
            "internalNotes": _clean_str(payload.internal_notes or payload.internalNotes),
            "invoice_profile": str(payload.invoice_profile or "A"),
            "freight_method_id": int(payload.freight_method_id) if payload.freight_method_id else None,
            "freight_method_name": freight_name or None,
            "shipping_method_id": int(payload.shipping_method_id),
            "shipping_method_name": shipping_name,
            "client_name": _client_name_from_snapshot(client_raw),
        },
    }

    for it in items:
        it["quote_id"] = quote["quote_id"]

    return quote, items


@app.post("/quotes")
@app.post("/api/quotes")
def create_quote(request: Request, payload: QuoteCreateIn, company: str = "parton"):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    quote_seller_scope = _resolve_quote_seller_scope(user, company_key)
    payload = _quote_payload_with_forced_seller(payload, quote_seller_scope)

    if not payload.items:
        raise HTTPException(status_code=400, detail="Inclua ao menos um produto.")
    if not payload.payment_method_code:
        raise HTTPException(status_code=400, detail="Forma de pagamento é obrigatória.")
    if not payload.payment_due_date:
        raise HTTPException(status_code=400, detail="Vencimento é obrigatório.")

    try:
        quote, items = _build_quote_records(payload, company_key)
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO erp.quotes (
                    quote_id, quote_number, company_key, tiny_order_id, tiny_order_number, status, internal_status,
                    client_id, client_snapshot, seller_id, seller_name, seller_snapshot,
                    shipping_method_id, shipping_method_name, freight_method_id, freight_method_name,
                    payment_method_code, payment_method_name, payment_meio, payment_conta,
                    payment_due_date, payment_category, payment_notify,
                    totals, notes, payload, created_at, updated_at
                )
                VALUES (
                    %(quote_id)s, %(quote_number)s, %(company_key)s, %(tiny_order_id)s, %(tiny_order_number)s,
                    %(status)s, %(internal_status)s, %(client_id)s, %(client_snapshot)s::jsonb,
                    %(seller_id)s, %(seller_name)s, %(seller_snapshot)s::jsonb,
                    %(shipping_method_id)s, %(shipping_method_name)s, %(freight_method_id)s, %(freight_method_name)s,
                    %(payment_method_code)s, %(payment_method_name)s, %(payment_meio)s, %(payment_conta)s,
                    %(payment_due_date)s, %(payment_category)s, %(payment_notify)s,
                    %(totals)s::jsonb, %(notes)s, %(payload)s::jsonb, now(), now()
                )
                """,
                {
                    **quote,
                    "client_snapshot": _to_jsonb(quote["client_snapshot"]),
                    "seller_snapshot": _to_jsonb(quote["seller_snapshot"]),
                    "totals": _to_jsonb(quote["totals"]),
                    "payload": _to_jsonb(quote["payload"]),
                },
            )

            for it in items:
                cur.execute(
                    """
                    INSERT INTO erp.quote_items (
                        quote_id, line, product_id, sku_snapshot, name_snapshot,
                        qty, list_price, discount_pct, unit_price_disc, line_total, raw
                    )
                    VALUES (
                        %(quote_id)s, %(line)s, %(product_id)s, %(sku_snapshot)s, %(name_snapshot)s,
                        %(qty)s, %(list_price)s, %(discount_pct)s, %(unit_price_disc)s, %(line_total)s, %(raw)s::jsonb
                    )
                    """,
                    {**it, "raw": _to_jsonb(it["raw"])},
                )

    return {"ok": True, "status": "OK", "quote_id": quote["quote_id"], "quote_number": quote["quote_number"], "quote": quote, "items": items}


@app.patch("/quotes/{quote_id}")
@app.patch("/api/quotes/{quote_id}")
def update_quote(request: Request, quote_id: str, payload: QuoteCreateIn, company: str = "parton"):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, company)
    quote_seller_scope = _resolve_quote_seller_scope(user, company_key)
    payload = _quote_payload_with_forced_seller(payload, quote_seller_scope)

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tiny_order_id FROM erp.quotes WHERE quote_id=%s AND company_key=%s", (quote_id, company_key))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
            if existing.get("tiny_order_id"):
                raise HTTPException(status_code=400, detail="Não é possível editar: este orçamento já gerou pedido no Tiny.")

    try:
        quote, items = _build_quote_records(payload, company_key, quote_id=quote_id)
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE erp.quotes SET
                    status='draft',
                    internal_status=NULL,
                    client_id=%(client_id)s,
                    client_snapshot=%(client_snapshot)s::jsonb,
                    seller_id=%(seller_id)s,
                    seller_name=%(seller_name)s,
                    seller_snapshot=%(seller_snapshot)s::jsonb,
                    shipping_method_id=%(shipping_method_id)s,
                    shipping_method_name=%(shipping_method_name)s,
                    freight_method_id=%(freight_method_id)s,
                    freight_method_name=%(freight_method_name)s,
                    payment_method_code=%(payment_method_code)s,
                    payment_method_name=%(payment_method_name)s,
                    payment_meio=%(payment_meio)s,
                    payment_conta=%(payment_conta)s,
                    payment_due_date=%(payment_due_date)s,
                    payment_category=%(payment_category)s,
                    payment_notify=%(payment_notify)s,
                    totals=%(totals)s::jsonb,
                    notes=%(notes)s,
                    payload=%(payload)s::jsonb,
                    updated_at=now()
                WHERE quote_id=%(quote_id)s AND company_key=%(company_key)s
                """,
                {
                    **quote,
                    "client_snapshot": _to_jsonb(quote["client_snapshot"]),
                    "seller_snapshot": _to_jsonb(quote["seller_snapshot"]),
                    "totals": _to_jsonb(quote["totals"]),
                    "payload": _to_jsonb(quote["payload"]),
                },
            )
            cur.execute("DELETE FROM erp.quote_items WHERE quote_id=%s", (quote_id,))
            for it in items:
                cur.execute(
                    """
                    INSERT INTO erp.quote_items (
                        quote_id, line, product_id, sku_snapshot, name_snapshot,
                        qty, list_price, discount_pct, unit_price_disc, line_total, raw
                    )
                    VALUES (
                        %(quote_id)s, %(line)s, %(product_id)s, %(sku_snapshot)s, %(name_snapshot)s,
                        %(qty)s, %(list_price)s, %(discount_pct)s, %(unit_price_disc)s, %(line_total)s, %(raw)s::jsonb
                    )
                    """,
                    {**it, "raw": _to_jsonb(it["raw"])},
                )

    return {"ok": True, "status": "OK", "quote_id": quote_id, "quote": quote, "items": items}


@app.get("/clients/{client_id}/products/{product_id}/last-price")
@app.get("/api/clients/{client_id}/products/{product_id}/last-price")
def last_price(client_id: int, product_id: int, company: str = "parton"):
    company_key = _company_key(company)
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT q.quote_id, q.quote_number, q.status, q.tiny_order_number,
                       qi.unit_price_disc, qi.discount_pct, qi.list_price, q.created_at
                FROM erp.quotes q
                JOIN erp.quote_items qi ON qi.quote_id = q.quote_id
                WHERE q.company_key=%s AND q.client_id=%s AND qi.product_id=%s
                ORDER BY q.created_at DESC, q.quote_number DESC
                LIMIT 1
                """,
                (company_key, client_id, product_id),
            )
            row = cur.fetchone()

    if not row:
        return {"found": False, "client_id": client_id, "product_id": product_id}
    return {"found": True, "client_id": client_id, "product_id": product_id, **dict(row)}


def _client_wallet_product_key(product: Dict[str, Any], idx: int = 0) -> str:
    return _clean_str(product.get("key") or product.get("product_id") or product.get("id") or product.get("sku") or product.get("codigo") or idx)


def _client_wallet_product_last_sale(company_key: str, client: Dict[str, Any], product: Dict[str, Any]) -> Dict[str, Any]:
    company_key = _company_key(company_key)
    client_id = _clean_str(client.get("client_id") or client.get("tiny_client_id") or client.get("id"))
    cpf_digits = _client_wallet_digits_only(client.get("cpf_cnpj") or client.get("cpfCnpj"))
    client_name = _clean_str(client.get("name") or client.get("nome") or client.get("fantasia"))
    product_id = _clean_str(product.get("product_id") or product.get("id") or product.get("tiny_product_id"))
    sku = _clean_str(product.get("sku") or product.get("codigo") or product.get("code"))
    product_name = _clean_str(product.get("name") or product.get("nome") or product.get("descricao"))

    client_matches: List[str] = []
    client_params: List[Any] = []
    if client_id:
        client_matches.append("CAST(q.client_id AS TEXT) = %s")
        client_params.append(client_id)
    if cpf_digits:
        client_matches.append(
            "regexp_replace(COALESCE(q.client_snapshot->>'cpf_cnpj', q.client_snapshot->>'cpfCnpj', q.client_snapshot->>'cpf', ''), '[^0-9]', '', 'g') = %s"
        )
        client_params.append(cpf_digits)
    if client_name:
        client_matches.append("LOWER(COALESCE(q.client_snapshot->>'nome', q.client_snapshot->>'name', '')) = LOWER(%s)")
        client_params.append(client_name)

    product_matches: List[str] = []
    product_params: List[Any] = []
    if product_id:
        product_matches.append("CAST(qi.product_id AS TEXT) = %s")
        product_params.append(product_id)
    if sku:
        product_matches.append("LOWER(COALESCE(qi.sku_snapshot, qi.raw->>'sku', qi.raw->>'codigo', '')) = LOWER(%s)")
        product_params.append(sku)
    if product_name:
        product_matches.append("LOWER(COALESCE(qi.name_snapshot, qi.raw->>'nome', qi.raw->>'descricao', '')) = LOWER(%s)")
        product_params.append(product_name)

    if not client_matches or not product_matches:
        return {"found": False, "message": "Sem histórico para este cliente/produto."}

    valid_statuses = (
        "aprovado",
        "preparando envio",
        "pronto para envio",
        "faturado",
        "separado",
        "entregue",
    )
    invalid_statuses = ("cancelado", "cancelada", "em aberto", "rascunho", "excluido", "excluído")
    params: List[Any] = [
        company_key,
        valid_statuses,
        valid_statuses,
        invalid_statuses,
        *client_params,
        *product_params,
    ]

    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT q.quote_id, q.quote_number, q.tiny_order_id, q.tiny_order_number,
                       q.status, q.internal_status, q.payload, q.created_at, q.updated_at,
                       so.status AS separation_status, so.separated_at, so.checked_at,
                       qi.*
                FROM erp.quotes q
                JOIN erp.quote_items qi ON qi.quote_id = q.quote_id
                LEFT JOIN erp.separation_orders so
                  ON so.company_key = q.company_key
                 AND (
                       so.quote_id = q.quote_id
                       OR (q.tiny_order_id IS NOT NULL AND so.tiny_order_id = q.tiny_order_id)
                     )
                WHERE q.company_key = %s
                  AND (
                        LOWER(COALESCE(q.internal_status, '')) IN %s
                        OR LOWER(COALESCE(so.status, '')) IN %s
                      )
                  AND LOWER(COALESCE(q.internal_status, '')) NOT IN %s
                  AND ({' OR '.join(client_matches)})
                  AND ({' OR '.join(product_matches)})
                ORDER BY COALESCE(so.separated_at, so.checked_at, q.updated_at, q.created_at) DESC
                LIMIT 1
                """,
                params,
            )
            row = dict(cur.fetchone() or {})

    if not row:
        return {"found": False, "message": "Sem histórico para este cliente/produto."}

    normalized = _normalize_quote_item_financials(row)
    purchase_dt = _client_wallet_purchase_date_from_quote(row)
    unit_price = _safe_float(normalized.get("unit_price_disc") or normalized.get("unit_price"), 0)
    total_price = _safe_float(normalized.get("line_total") or normalized.get("total_price"), 0)
    quantity = _safe_float(normalized.get("quantity") or normalized.get("qty"), 0)
    return {
        "ok": True,
        "found": True,
        "company_key": company_key,
        "last_unit_price": unit_price,
        "unit_price_disc": unit_price,
        "last_sale_date": purchase_dt.isoformat() if purchase_dt else "",
        "created_at": purchase_dt.isoformat() if purchase_dt else "",
        "order_number": _clean_str(row.get("tiny_order_number") or row.get("quote_number")),
        "quote_number": row.get("quote_number"),
        "tiny_order_id": _clean_str(row.get("tiny_order_id")),
        "tiny_order_number": _clean_str(row.get("tiny_order_number")),
        "quantity": quantity,
        "total_price": total_price,
        "discount_pct": _safe_float(normalized.get("discount_pct"), 0),
        "source": "local_history",
    }


@app.post("/api/client-wallet/product-last-sales/batch")
@app.post("/client-wallet/product-last-sales/batch")
def client_wallet_product_last_sales_batch(request: Request, body: Dict[str, Any]):
    user = _require_auth_user(request)
    company_key = _auth_company_or_default(user, body.get("company") or "parton")
    client = body.get("client") if isinstance(body.get("client"), dict) else {}
    products = body.get("products") if isinstance(body.get("products"), list) else []
    products = products[:20]
    items: Dict[str, Any] = {}
    for idx, product in enumerate(products):
        if not isinstance(product, dict):
            continue
        key = _client_wallet_product_key(product, idx)
        try:
            items[key] = _client_wallet_product_last_sale(company_key, client, product)
        except Exception as e:
            items[key] = {"found": False, "error": str(e), "message": "Falha ao consultar histórico local."}
    return {"ok": True, "company_key": company_key, "source": "local_history", "items": items}


# ============================================================
# COMPRAS — Pedidos de Compra e Atualizações de Estoque (Tiny)
# ============================================================

def _parse_tiny_date_br(value: Any) -> str:
    """Converte data BR dd/mm/aaaa para ISO yyyy-mm-dd (ou devolve original)."""
    s = _clean_str(value)
    if not s or len(s) < 8:
        return s
    try:
        parts = s.split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except Exception:
        pass
    return s


def _date_to_br(value: str) -> str:
    """Converte yyyy-mm-dd para dd/mm/aaaa."""
    s = _clean_str(value)
    if not s:
        return ""
    try:
        parts = s.split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except Exception:
        pass
    return s


def _normalize_pedido_compra(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    pc = raw.get("pedidoCompra") if isinstance(raw.get("pedidoCompra"), dict) else raw
    fornecedor = pc.get("fornecedor") or {}
    if isinstance(fornecedor, str):
        fornecedor = {"nome": fornecedor}
    return {
        "id": pc.get("id"),
        "numero": _clean_str(pc.get("numero") or pc.get("sequencia")),
        "data_pedido": _parse_tiny_date_br(pc.get("data_pedido") or pc.get("dataPedido")),
        "data_previsao": _parse_tiny_date_br(pc.get("data_previsao") or pc.get("dataPrevisao")),
        "data_chegada": _parse_tiny_date_br(pc.get("data_chegada") or pc.get("dataChegada")),
        "situacao": _clean_str(pc.get("situacao")),
        "fornecedor_id": fornecedor.get("id"),
        "fornecedor_nome": _clean_str(fornecedor.get("nome")),
        "fornecedor_cnpj": _clean_str(fornecedor.get("cpf_cnpj") or fornecedor.get("cpfCnpj")),
        "total_produtos": _safe_float(pc.get("total_produtos") or pc.get("totalProdutos"), None),
        "total_pedido": _safe_float(pc.get("total_pedido") or pc.get("totalPedido"), None),
        "desconto": _safe_float(pc.get("desconto"), None),
        "frete": _safe_float(pc.get("frete"), None),
        "obs": _clean_str(pc.get("obs")),
        "forma_pagamento": _clean_str(pc.get("forma_pagamento") or pc.get("formaPagamento")),
        "forma_frete": _clean_str(pc.get("forma_frete") or pc.get("formaFrete")),
        "raw": pc,
    }


def _normalize_atualizacao_estoque(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    at = raw.get("atualizacao") if isinstance(raw.get("atualizacao"), dict) else raw
    return {
        "id": at.get("id"),
        "id_produto": at.get("id_produto") or at.get("idProduto"),
        "codigo": _clean_str(at.get("codigo") or at.get("sku")),
        "nome": _clean_str(at.get("nome")),
        "tipo": _clean_str(at.get("tipo")),
        "quantidade": _safe_float(at.get("quantidade"), None),
        "saldo_anterior": _safe_float(at.get("saldo_anterior") or at.get("saldoAnterior"), None),
        "saldo_atual": _safe_float(at.get("saldo_atual") or at.get("saldoAtual"), None),
        "preco_custo": _safe_float(at.get("preco_custo") or at.get("precoCusto"), None),
        "data": _parse_tiny_date_br(at.get("data")),
        "hora": _clean_str(at.get("hora")),
        "observacoes": _clean_str(at.get("observacoes") or at.get("obs")),
        "id_origem": _clean_str(at.get("id_origem") or at.get("idOrigem")),
        "tipo_origem": _clean_str(at.get("tipo_origem") or at.get("tipoOrigem")),
        "usuario": _clean_str(at.get("usuario")),
    }


def _catalog_require_admin_or_raise(request: Request) -> Dict[str, Any]:
    return _catalog_require_admin(request)


@app.get("/api/admin/compras")
@app.get("/admin/compras")
def admin_compras_list(
    request: Request,
    company: str = "parton",
    pagina: int = Query(default=1, ge=1),
    situacao: str = Query(default=""),
    data_inicial: str = Query(default=""),
    data_final: str = Query(default=""),
    fornecedor: str = Query(default=""),
    pesquisa: str = Query(default=""),
    numero: str = Query(default=""),
    marketplace: str = Query(default=""),
):
    """Lista pedidos de compra do Tiny V2 com filtros. Admin-only."""
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    tiny = _tiny_for_company(company_key)

    try:
        raw = tiny.pesquisar_pedidos_compra(
            pesquisa=pesquisa,
            pagina=pagina,
            situacao=situacao,
            data_inicial=_date_to_br(data_inicial),
            data_final=_date_to_br(data_final),
            numero=numero,
            fornecedor=fornecedor,
        )
    except TinyAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Tiny: {str(exc)[:400]}")

    retorno = raw if isinstance(raw, dict) else {}

    # Extrai lista de pedidos independente da estrutura de wrapping
    raw_list = (
        retorno.get("pedidosCompra")
        or retorno.get("pedidos_compra")
        or retorno.get("pedidos")
        or []
    )
    if not isinstance(raw_list, list):
        raw_list = []

    pedidos = [_normalize_pedido_compra(item) for item in raw_list]

    # Filtro de marketplace (canal): "marketplace" = tem id_origem externo,
    # "direto" = pedido interno, "" = todos.
    if marketplace == "marketplace":
        pedidos = [p for p in pedidos if p.get("id_origem") or "ecommerce" in _clean_str(p.get("obs")).lower()]
    elif marketplace == "direto":
        pedidos = [p for p in pedidos if not p.get("id_origem")]

    return {
        "ok": True,
        "company_key": company_key,
        "pagina": int(retorno.get("pagina") or pagina),
        "numero_paginas": int(retorno.get("numero_paginas") or 1),
        "registros": int(retorno.get("registros") or len(pedidos)),
        "pedidos": pedidos,
    }


@app.get("/api/admin/compras/{id_pedido}")
@app.get("/admin/compras/{id_pedido}")
def admin_compras_detalhe(
    request: Request,
    id_pedido: int,
    company: str = "parton",
):
    """Retorna detalhe completo de um pedido de compra do Tiny. Admin-only."""
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    tiny = _tiny_for_company(company_key)

    try:
        raw = tiny.obter_pedido_compra(id_pedido)
    except TinyAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Tiny: {str(exc)[:400]}")

    retorno = raw if isinstance(raw, dict) else {}
    pc_raw = retorno.get("pedidoCompra") or retorno
    if not isinstance(pc_raw, dict):
        raise HTTPException(status_code=404, detail="Pedido de compra não encontrado.")

    normalized = _normalize_pedido_compra(pc_raw)

    # Normaliza itens
    raw_itens = pc_raw.get("itens") or []
    if not isinstance(raw_itens, list):
        raw_itens = []
    itens = []
    for it in raw_itens:
        item = it.get("item") if isinstance(it, dict) and isinstance(it.get("item"), dict) else it
        if not isinstance(item, dict):
            continue
        itens.append({
            "id": item.get("id"),
            "id_produto": item.get("id_produto") or item.get("idProduto"),
            "codigo": _clean_str(item.get("codigo") or item.get("sku")),
            "descricao": _clean_str(item.get("descricao") or item.get("nome")),
            "unidade": _clean_str(item.get("unidade")),
            "quantidade": _safe_float(item.get("quantidade"), None),
            "valor_unitario": _safe_float(item.get("valor_unitario") or item.get("valorUnitario"), None),
            "valor_total": _safe_float(item.get("valor_total") or item.get("valorTotal"), None),
        })

    normalized["itens"] = itens
    normalized.pop("raw", None)

    return {"ok": True, "company_key": company_key, "pedido": normalized}


@app.get("/api/admin/estoque/atualizacoes")
@app.get("/admin/estoque/atualizacoes")
def admin_estoque_atualizacoes(
    request: Request,
    company: str = "parton",
    pagina: int = Query(default=1, ge=1),
    data_inicial: str = Query(default=""),
    data_final: str = Query(default=""),
    pesquisa: str = Query(default=""),
    id_produto: Optional[int] = Query(default=None),
    marketplace: str = Query(default=""),
):
    """Lista histórico de movimentos de estoque do Tiny V2. Admin-only."""
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    tiny = _tiny_for_company(company_key)

    try:
        raw = tiny.pesquisar_atualizacoes_estoque(
            pesquisa=pesquisa,
            pagina=pagina,
            data_inicial=_date_to_br(data_inicial),
            data_final=_date_to_br(data_final),
            id_produto=id_produto,
        )
    except TinyAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Tiny: {str(exc)[:400]}")

    retorno = raw if isinstance(raw, dict) else {}
    raw_list = retorno.get("atualizacoes") or retorno.get("produtos") or []
    if not isinstance(raw_list, list):
        raw_list = []

    atualizacoes = [_normalize_atualizacao_estoque(item) for item in raw_list]

    # Filtro por marketplace/origem
    if marketplace == "marketplace":
        atualizacoes = [a for a in atualizacoes if a.get("id_origem") or _clean_str(a.get("tipo_origem")).lower() in ("pedido de compra", "venda", "ecommerce")]
    elif marketplace == "direto":
        atualizacoes = [a for a in atualizacoes if not a.get("id_origem")]

    return {
        "ok": True,
        "company_key": company_key,
        "pagina": int(retorno.get("pagina") or pagina),
        "numero_paginas": int(retorno.get("numero_paginas") or 1),
        "registros": int(retorno.get("registros") or len(atualizacoes)),
        "atualizacoes": atualizacoes,
    }


@app.get("/api/admin/compras/fornecedores")
@app.get("/admin/compras/fornecedores")
def admin_compras_fornecedores(
    request: Request,
    company: str = "parton",
    pesquisa: str = Query(default=""),
    pagina: int = Query(default=1, ge=1),
):
    """Pesquisa fornecedores no Tiny V2 para uso nos filtros de Compras. Admin-only."""
    user = _catalog_require_admin(request)
    company_key = _auth_company_or_default(user, company)
    tiny = _tiny_for_company(company_key)

    try:
        raw = tiny.pesquisar_fornecedores(pesquisa=pesquisa, pagina=pagina)
    except TinyAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Tiny: {str(exc)[:400]}")

    retorno = raw if isinstance(raw, dict) else {}
    raw_list = retorno.get("contatos") or []
    if not isinstance(raw_list, list):
        raw_list = []

    fornecedores = []
    for item in raw_list:
        c = item.get("contato") if isinstance(item, dict) and isinstance(item.get("contato"), dict) else item
        if not isinstance(c, dict):
            continue
        fornecedores.append({
            "id": c.get("id"),
            "nome": _clean_str(c.get("nome")),
            "cnpj": _clean_str(c.get("cpf_cnpj") or c.get("cpfCnpj")),
        })

    return {
        "ok": True,
        "company_key": company_key,
        "fornecedores": fornecedores,
        "registros": int(retorno.get("registros") or len(fornecedores)),
    }


# === FINAL FRONTEND SPA FALLBACK RESTORE V2 ===
# Restaura o frontend React/Vite servido pelo FastAPI local.
# Deve ficar no final do arquivo, depois das rotas de API.
try:
    _trml_frontend_dist = FRONTEND_DIST if "FRONTEND_DIST" in globals() else os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
    _trml_frontend_index = os.path.join(_trml_frontend_dist, "index.html")
    _trml_frontend_logo = os.path.join(_trml_frontend_dist, "logo.png")
    _trml_frontend_assets = os.path.join(_trml_frontend_dist, "assets")

    if os.path.isdir(_trml_frontend_assets):
        _has_assets_mount = any(getattr(r, "path", "") == "/assets" for r in app.router.routes)
        if not _has_assets_mount:
            app.mount("/assets", StaticFiles(directory=_trml_frontend_assets), name="assets")

    _trml_catalog_images = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "catalog-images")
    os.makedirs(_trml_catalog_images, exist_ok=True)
    if os.path.isdir(_trml_catalog_images):
        _has_catalog_images_mount = any(getattr(r, "path", "") == "/catalog-images" for r in app.router.routes)
        if not _has_catalog_images_mount:
            app.mount("/catalog-images", StaticFiles(directory=_trml_catalog_images), name="catalog-images")

    # Fotos de separação/conferência NÃO são públicas (podem conter PII). São
    # servidas pela rota autenticada GET /separation/photos/{filename} — sem mount.

    if os.path.isfile(_trml_frontend_index):
        if os.path.isfile(_trml_frontend_logo):
            @app.get("/logo.png")
            def trml_frontend_logo_final():
                return FileResponse(_trml_frontend_logo)

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

