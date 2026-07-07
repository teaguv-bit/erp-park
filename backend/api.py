OPS_TINY_MIRROR_TABLE = "ops_tiny_orders_mirror"

import os
import secrets
import json
import time
import uuid
import datetime as dt
from typing import Optional, List, Dict, Any
from io import BytesIO
import re
import atexit
import threading
import random
import traceback
import requests

from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig
from pydantic import BaseModel, Field
from playwright.sync_api import sync_playwright, Browser, Playwright
from starlette.types import ASGIApp, Receive, Scope, Send

from tiny_client import TinyClient, load_config_from_env, TinyAPIError, TinyV3Client, load_v3_config_from_env
from bq_schema import get_bq_client, bootstrap
from datetime import datetime, timedelta

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "").strip()
DATASET_ID = os.getenv("BQ_DATASET_ID", "tiny_orcamento").strip()
ENABLE_TINY_STATUS_SYNC = os.getenv("ENABLE_TINY_STATUS_SYNC", "false").strip().lower() in ("1", "true", "yes", "on")
ERP_BASE_URL = os.getenv("ERP_BASE_URL", "https://erp.olist.com/vendas").strip()

ENABLE_OLIST_LINK_UI_FIX = os.getenv("ENABLE_OLIST_LINK_UI_FIX", "false").strip().lower() in ("1", "true", "yes", "on")
OLIST_UI_EMAIL = os.getenv("OLIST_UI_EMAIL", "").strip()
OLIST_UI_PASSWORD = os.getenv("OLIST_UI_PASSWORD", "").strip()
OLIST_UI_HEADLESS = os.getenv("OLIST_UI_HEADLESS", "true").strip().lower() in ("1", "true", "yes", "on")


ADMIN_EMAILS = set(
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
)

ALLOWED_EMAILS = set(
    e.strip().lower()
    for e in os.getenv("ALLOWED_EMAILS", "").split(",")
    if e.strip()
)

EXPEDITION_EMAILS = set(
    e.strip().lower()
    for e in os.getenv("EXPEDITION_EMAILS", "").split(",")
    if e.strip()
)

PAYMENT_CONTA_PORTADOR_MAP = {
    "suprimento_parton_olist": "(Suprimento)Parton - Olist",
    "suprimento_parton_stone": "(Suprimento)Parton - Stone",
}

if not PROJECT_ID:
    raise RuntimeError("Defina GCP_PROJECT_ID no .env")


_OPS_TINY_SUMMARY_CACHE = {}
_OPS_TINY_SUMMARY_CACHE_TTL = 60  # segundos


def _ops_tiny_summary_cache_get(key):
    row = _OPS_TINY_SUMMARY_CACHE.get(key)
    if not row:
        return None
    ts = row.get("ts", 0)
    if (time.time() - ts) > _OPS_TINY_SUMMARY_CACHE_TTL:
        _OPS_TINY_SUMMARY_CACHE.pop(key, None)
        return None
    return row.get("value")


def _ops_tiny_summary_cache_set(key, value):
    _OPS_TINY_SUMMARY_CACHE[key] = {
        "ts": time.time(),
        "value": value,
    }


_OPS_TINY_ORDERS_CACHE = {}
_OPS_TINY_ORDERS_CACHE_TTL = 60  # segundos


def _ops_tiny_cache_get(key):
    row = _OPS_TINY_ORDERS_CACHE.get(key)
    if not row:
        return None
    ts = row.get("ts", 0)
    if (time.time() - ts) > _OPS_TINY_ORDERS_CACHE_TTL:
        _OPS_TINY_ORDERS_CACHE.pop(key, None)
        return None
    return row.get("value")


def _ops_tiny_cache_set(key, value):
    _OPS_TINY_ORDERS_CACHE[key] = {
        "ts": time.time(),
        "value": value,
    }


app = FastAPI(title="Pré-venda Parton API", version="3.0.3")


@app.on_event("startup")
async def _debug_list_seller_routes():
    try:
        seller_paths = sorted(
            {
                getattr(r, "path", None)
                for r in app.routes
                if getattr(r, "path", None) and "seller" in getattr(r, "path", "")
            }
        )
        print("[PREVENDA] STARTUP_SELLER_ROUTES:", seller_paths, flush=True)
    except Exception as e:
        print(f"[PREVENDA] STARTUP_SELLER_ROUTES_ERROR: {e}", flush=True)



class StripApiPrefixMiddleware:
    def __init__(self, app: ASGIApp, prefix: str = "/api"):
        self.app = app
        self.prefix = prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                new_path = path[len(self.prefix):] or "/"
                scope = dict(scope)
                scope["path"] = new_path
        await self.app(scope, receive, send)


app.add_middleware(StripApiPrefixMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

bq: bigquery.Client = get_bq_client()
tiny = TinyClient(load_config_from_env())


_pw_lock = threading.Lock()
_pw_instance: Optional[Playwright] = None
_pw_browser: Optional[Browser] = None


def _get_pdf_browser() -> Browser:
    global _pw_instance, _pw_browser
    if _pw_browser is not None:
        return _pw_browser

    with _pw_lock:
        if _pw_browser is None:
            _pw_instance = sync_playwright().start()
            _pw_browser = _pw_instance.chromium.launch(
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
    return _pw_browser


def _close_pdf_browser():
    global _pw_instance, _pw_browser
    with _pw_lock:
        browser = _pw_browser
        pw = _pw_instance
        _pw_browser = None
        _pw_instance = None

    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass

    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass


atexit.register(_close_pdf_browser)


def _table(name: str) -> str:
    return f"`{PROJECT_ID}.{DATASET_ID}.{name}`"


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _to_json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def _from_json(s: Optional[str]) -> Any:
    if not s:
        return None
    return json.loads(s)


def _clean_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _coerce_due_date_not_past(value: Optional[str]) -> str:
    today = dt.datetime.now().date().isoformat()
    raw = (value or "").strip()
    if not raw:
        return today
    return raw if raw >= today else today


def _log_event(event: str, **data: Any):
    try:
        print(f"[PREVENDA] {event}: " + json.dumps(data, ensure_ascii=False, default=str))
    except Exception:
        print(f"[PREVENDA] {event}: {data}")


def _norm_text(v: Any) -> str:
    return (
        str(v or "")
        .strip()
        .lower()
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def _is_active_flag(v: Any) -> bool:
    txt = _norm_text(v)
    return txt in ("", "a", "ativo", "ativa", "1", "s", "sim", "true")


def _is_placeholder_name(v: Any) -> bool:
    txt = _norm_text(v)
    return txt in ("nao definida", "nao def", "nenhuma", "padrao", "-")


def _pick_first_nonempty(obj: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = obj.get(key)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return ""


def _normalize_payment_code(code: Optional[str]) -> str:
    s = (code or "").strip().lower()
    s = (
        s.replace("ã", "a")
         .replace("á", "a")
         .replace("à", "a")
         .replace("â", "a")
         .replace("é", "e")
         .replace("ê", "e")
         .replace("í", "i")
         .replace("ó", "o")
         .replace("ô", "o")
         .replace("õ", "o")
         .replace("ú", "u")
         .replace("ç", "c")
    )

    aliases = {
        "cartao de credito": "credito",
        "cartao_credito": "credito",
        "credito": "credito",
        "cartao de debito": "debito",
        "cartao_debito": "debito",
        "debito": "debito",
        "link de pagamento": "link_pagamento",
        "link_pagamento": "link_pagamento",
        "vale troca": "vale_troca",
        "vale_troca": "vale_troca",
    }
    return aliases.get(s, s)


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
) -> tuple[str, Optional[str], Optional[str]]:
    code = _normalize_payment_code(method_code)
    meio_norm = _clean_str(meio)
    conta_norm = _clean_str(conta)

    if code == "link_pagamento":
        return code, "gateway", "suprimento_parton_olist"

    if code in ("cartao_credito", "credito"):
        return "credito", "gateway", "suprimento_parton_stone"

    if code in ("cartao_debito", "debito"):
        return "debito", meio_norm or "gateway", conta_norm or "suprimento_parton_stone"

    return code, meio_norm, conta_norm

def _resolve_portador_nome(payment_conta: Optional[str]) -> Optional[str]:
    conta = (payment_conta or "").strip()
    if not conta:
        return None
    return PAYMENT_CONTA_PORTADOR_MAP.get(conta) or conta


def _resolve_meio_pagamento_tiny(payment_meio: Optional[str], payment_conta: Optional[str]) -> Optional[str]:
    meio = (payment_meio or "").strip().lower()
    if meio == "banco":
        return "Banco"
    if meio == "gateway":
        return "Gateway"
    return None


def _extract_tiny_order_debug(order_resp: Dict[str, Any]) -> Dict[str, Any]:
    pedido = order_resp.get("pedido") or {}
    parcelas = pedido.get("parcelas") or []
    pagamentos_integrados = (
        pedido.get("pagamentos_integrados")
        or pedido.get("pagamentosIntegrados")
        or []
    )

    resumo_parcelas = []
    for idx, p in enumerate(parcelas, start=1):
        parcela = p.get("parcela", p) if isinstance(p, dict) else {}
        resumo_parcelas.append({
            "index": idx,
            "forma_pagamento": parcela.get("forma_pagamento") or parcela.get("formaPagamento"),
            "meio_pagamento": parcela.get("meio_pagamento") or parcela.get("meioPagamento"),
            "data_vencimento": parcela.get("data") or parcela.get("dataVencimento"),
            "dias": parcela.get("dias"),
            "valor": parcela.get("valor"),
            "destino": parcela.get("destino"),
        })

    resumo_pagamentos_integrados = []
    for idx, p in enumerate(pagamentos_integrados, start=1):
        if not isinstance(p, dict):
            continue
        resumo_pagamentos_integrados.append({
            "index": idx,
            "valor": p.get("valor"),
            "tipo_pagamento": p.get("tipo_pagamento") or p.get("tipoPagamento"),
            "cnpj_intermediador": p.get("cnpj_intermediador") or p.get("CNPJIntermediador"),
            "codigo_autorizacao": p.get("codigo_autorizacao") or p.get("codigoAutorizacao"),
            "codigo_bandeira": p.get("codigo_bandeira") or p.get("codigoBandeira"),
        })

    return {
        "id": pedido.get("id"),
        "numero": pedido.get("numero"),
        "forma_pagamento": pedido.get("forma_pagamento") or pedido.get("formaPagamento"),
        "meio_pagamento": pedido.get("meio_pagamento") or pedido.get("meioPagamento"),
        "parcelas_count": len(parcelas),
        "parcelas": resumo_parcelas,
        "pagamentos_integrados_count": len(pagamentos_integrados),
        "pagamentos_integrados": resumo_pagamentos_integrados,
    }


def _tiny_error_looks_missing(err: Exception) -> bool:
    txt = _norm_text(str(err))
    needles = [
        "nao encontrado",
        "nao encontrada",
        "nao localizado",
        "nao localizada",
        "nao existe",
        "inexistente",
        "registro nao encontrado",
        "registro nao localizado",
        "nenhum registro",
        "pedido nao encontrado",
        "pedido nao localizado",
        "pedido inexistente",
        "id nao encontrado",
        "id nao localizado",
    ]
    return any(n in txt for n in needles)


def _extract_tiny_order_preview(order_resp: Dict[str, Any]) -> Dict[str, Any]:
    pedido = order_resp.get("pedido") or {}
    cliente = pedido.get("cliente") or {}
    if not isinstance(cliente, dict):
        cliente = {}

    return {
        "id": pedido.get("id"),
        "numero": pedido.get("numero"),
        "situacao": (
            pedido.get("situacao")
            or pedido.get("situacao_nome")
            or pedido.get("descricao_situacao")
            or pedido.get("status")
        ),
        "data_pedido": (
            pedido.get("data_pedido")
            or pedido.get("data")
            or pedido.get("dataPedido")
        ),
        "cliente_nome": (
            cliente.get("nome")
            or pedido.get("nome_cliente")
            or pedido.get("cliente_nome")
        ),
        "valor_total": (
            pedido.get("valor_total")
            or pedido.get("total_pedido")
            or pedido.get("total")
            or pedido.get("valor")
        ),
    }


def _extract_tiny_search_order_item(item: Any) -> Dict[str, Any]:
    pedido = item.get("pedido", item) if isinstance(item, dict) else {}
    if not isinstance(pedido, dict):
        pedido = {}

    cliente = pedido.get("cliente") or {}
    if not isinstance(cliente, dict):
        cliente = {}

    return {
        "id": pedido.get("id"),
        "numero": pedido.get("numero"),
        "situacao": (
            pedido.get("situacao")
            or pedido.get("situacao_nome")
            or pedido.get("descricao_situacao")
            or pedido.get("status")
        ),
        "data_pedido": (
            pedido.get("data_pedido")
            or pedido.get("data")
            or pedido.get("dataPedido")
        ),
        "cliente_nome": (
            cliente.get("nome")
            or pedido.get("nome_cliente")
            or pedido.get("cliente_nome")
        ),
        "valor_total": (
            pedido.get("valor_total")
            or pedido.get("total_pedido")
            or pedido.get("total")
            or pedido.get("valor")
        ),
    }


@app.on_event("startup")
def _startup():
    bootstrap()


FIREBASE_READY = False
_fb_error = None
_fb_auth = None

try:
    import base64
    import firebase_admin
    from firebase_admin import credentials, auth as fb_auth

    sa = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not sa:
        sa_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON_B64", "").strip()
        if sa_b64:
            sa = base64.b64decode(sa_b64).decode("utf-8").strip()

    if not sa:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON não configurado")

    if not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(sa))
        firebase_admin.initialize_app(cred)

    _fb_auth = fb_auth
    FIREBASE_READY = True
except Exception as e:
    FIREBASE_READY = False
    _fb_error = str(e)

PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/favicon.ico", "/v3-auth/start", "/api/v3-auth/start", "/v3-auth/callback", "/api/v3-auth/callback"}

APP_USER_ROLES = {"admin", "seller", "allowed", "expedition"}




class AdminSettingPayload(BaseModel):
    setting_key: str
    setting_value: str = ""
    value_type: str = "string"
    category: str = "Sistema"
    description: str = ""


DEFAULT_APP_SETTINGS = [
    {
        "setting_key": "ops_sync_status_batch_limit",
        "setting_value": "10",
        "value_type": "integer",
        "category": "Sincronização",
        "description": "Limite sugerido por lote da sincronização geral de status Tiny. Nesta primeira versão é apenas parametrização administrativa.",
    },
    {
        "setting_key": "app_user_cache_ttl_seconds",
        "setting_value": os.getenv("APP_USER_CACHE_TTL_SECONDS", "60"),
        "value_type": "integer",
        "category": "Acesso",
        "description": "Tempo sugerido de cache de permissões de usuário em segundos. O valor real atual ainda vem da env var APP_USER_CACHE_TTL_SECONDS.",
    },
    {
        "setting_key": "admin_internal_notice",
        "setting_value": "",
        "value_type": "string",
        "category": "Interface",
        "description": "Aviso interno livre para uso futuro na tela Administração.",
    },
]


def _app_settings_table() -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.app_settings"


def _ensure_app_settings_table():
    table_id = _app_settings_table()
    schema = [
        bigquery.SchemaField("setting_key", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("setting_value", "STRING"),
        bigquery.SchemaField("value_type", "STRING"),
        bigquery.SchemaField("category", "STRING"),
        bigquery.SchemaField("description", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_by", "STRING"),
    ]

    try:
        bq.get_table(table_id)
    except Exception:
        try:
            bq.create_table(bigquery.Table(table_id, schema=schema))
        except Exception:
            try:
                bq.get_table(table_id)
            except Exception:
                raise

    for col, typ in [
        ("setting_key", "STRING"),
        ("setting_value", "STRING"),
        ("value_type", "STRING"),
        ("category", "STRING"),
        ("description", "STRING"),
        ("created_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
        ("updated_by", "STRING"),
    ]:
        try:
            bq.query(f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS {col} {typ}").result()
        except Exception:
            pass


def _seed_default_app_settings():
    _ensure_app_settings_table()
    now = _now_utc()

    for item in DEFAULT_APP_SETTINGS:
        bq.query(
            f"""
            MERGE `{_app_settings_table()}` T
            USING (
              SELECT
                @setting_key AS setting_key,
                @setting_value AS setting_value,
                @value_type AS value_type,
                @category AS category,
                @description AS description,
                @now AS now_ts
            ) S
            ON T.setting_key = S.setting_key
            WHEN NOT MATCHED THEN
              INSERT (setting_key, setting_value, value_type, category, description, created_at, updated_at, updated_by)
              VALUES (S.setting_key, S.setting_value, S.value_type, S.category, S.description, S.now_ts, S.now_ts, "system:defaults")
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("setting_key", "STRING", item["setting_key"]),
                    bigquery.ScalarQueryParameter("setting_value", "STRING", item["setting_value"]),
                    bigquery.ScalarQueryParameter("value_type", "STRING", item["value_type"]),
                    bigquery.ScalarQueryParameter("category", "STRING", item["category"]),
                    bigquery.ScalarQueryParameter("description", "STRING", item["description"]),
                    bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                ]
            ),
        ).result()




def _app_settings_audit_table() -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.app_settings_audit"


def _ensure_app_settings_audit_table():
    table_id = _app_settings_audit_table()
    schema = [
        bigquery.SchemaField("audit_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("setting_key", "STRING"),
        bigquery.SchemaField("action", "STRING"),
        bigquery.SchemaField("before_value", "STRING"),
        bigquery.SchemaField("after_value", "STRING"),
        bigquery.SchemaField("before_type", "STRING"),
        bigquery.SchemaField("after_type", "STRING"),
        bigquery.SchemaField("before_category", "STRING"),
        bigquery.SchemaField("after_category", "STRING"),
        bigquery.SchemaField("before_description", "STRING"),
        bigquery.SchemaField("after_description", "STRING"),
        bigquery.SchemaField("changed_by", "STRING"),
        bigquery.SchemaField("changed_at", "TIMESTAMP"),
        bigquery.SchemaField("source", "STRING"),
    ]

    try:
        bq.get_table(table_id)
    except Exception:
        try:
            bq.create_table(bigquery.Table(table_id, schema=schema))
        except Exception:
            try:
                bq.get_table(table_id)
            except Exception:
                raise

    for col, typ in [
        ("audit_id", "STRING"),
        ("setting_key", "STRING"),
        ("action", "STRING"),
        ("before_value", "STRING"),
        ("after_value", "STRING"),
        ("before_type", "STRING"),
        ("after_type", "STRING"),
        ("before_category", "STRING"),
        ("after_category", "STRING"),
        ("before_description", "STRING"),
        ("after_description", "STRING"),
        ("changed_by", "STRING"),
        ("changed_at", "TIMESTAMP"),
        ("source", "STRING"),
    ]:
        try:
            bq.query(f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS {col} {typ}").result()
        except Exception:
            pass


def _get_app_setting_record(setting_key: str):
    key = str(setting_key or "").strip().lower()
    if not key:
        return None

    try:
        _ensure_app_settings_table()
        rows = list(
            bq.query(
                f"""
                SELECT
                  setting_key,
                  setting_value,
                  value_type,
                  category,
                  description,
                  created_at,
                  updated_at,
                  updated_by
                FROM `{_app_settings_table()}`
                WHERE setting_key = @setting_key
                LIMIT 1
                """,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("setting_key", "STRING", key),
                    ]
                ),
            ).result()
        )
        return dict(rows[0]) if rows else None
    except Exception as e:
        print(f"[ADMIN_SETTING_RECORD_ERROR] {e}")
        return None


def _write_app_setting_audit(
    *,
    setting_key: str,
    action: str,
    before_record=None,
    after_value: str = "",
    after_type: str = "",
    after_category: str = "",
    after_description: str = "",
    changed_by: str = "",
):
    try:
        _ensure_app_settings_audit_table()
        now = _now_utc()
        before_record = before_record or {}

        bq.query(
            f"""
            INSERT INTO `{_app_settings_audit_table()}`
              (audit_id, setting_key, action,
               before_value, after_value,
               before_type, after_type,
               before_category, after_category,
               before_description, after_description,
               changed_by, changed_at, source)
            VALUES
              (@audit_id, @setting_key, @action,
               @before_value, @after_value,
               @before_type, @after_type,
               @before_category, @after_category,
               @before_description, @after_description,
               @changed_by, @changed_at, @source)
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("audit_id", "STRING", str(uuid.uuid4())),
                    bigquery.ScalarQueryParameter("setting_key", "STRING", str(setting_key or "").strip().lower()),
                    bigquery.ScalarQueryParameter("action", "STRING", str(action or "")),
                    bigquery.ScalarQueryParameter("before_value", "STRING", str(before_record.get("setting_value") or "")),
                    bigquery.ScalarQueryParameter("after_value", "STRING", str(after_value or "")),
                    bigquery.ScalarQueryParameter("before_type", "STRING", str(before_record.get("value_type") or "")),
                    bigquery.ScalarQueryParameter("after_type", "STRING", str(after_type or "")),
                    bigquery.ScalarQueryParameter("before_category", "STRING", str(before_record.get("category") or "")),
                    bigquery.ScalarQueryParameter("after_category", "STRING", str(after_category or "")),
                    bigquery.ScalarQueryParameter("before_description", "STRING", str(before_record.get("description") or "")),
                    bigquery.ScalarQueryParameter("after_description", "STRING", str(after_description or "")),
                    bigquery.ScalarQueryParameter("changed_by", "STRING", str(changed_by or "")),
                    bigquery.ScalarQueryParameter("changed_at", "TIMESTAMP", now),
                    bigquery.ScalarQueryParameter("source", "STRING", "admin_settings"),
                ]
            ),
        ).result()
    except Exception as e:
        print(f"[ADMIN_SETTINGS_AUDIT_ERROR] {e}")


def _normalize_setting_key(value: str) -> str:
    key = str(value or "").strip().lower()
    key = re.sub(r"[^a-z0-9_\\-\\.]", "_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    if not key:
        raise HTTPException(status_code=400, detail="Chave do parâmetro inválida.")
    if len(key) > 120:
        raise HTTPException(status_code=400, detail="Chave do parâmetro muito longa.")
    return key


def _normalize_setting_type(value: str) -> str:
    typ = str(value or "string").strip().lower()
    allowed = {"string", "integer", "boolean", "decimal", "json"}
    if typ not in allowed:
        raise HTTPException(status_code=400, detail="Tipo inválido. Use string, integer, boolean, decimal ou json.")
    return typ




@app.get("/api/admin/settings/audit")
@app.get("/admin/settings/audit")
def admin_list_settings_audit(
    request: Request,
    limit: int = Query(default=120, ge=1, le=500),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar auditoria de parâmetros.")

    cache_key = f"admin_settings_audit:{int(limit)}"
    cached = _admin_cache_get(cache_key)
    if cached is not None:
        return cached

    _ensure_app_settings_audit_table()

    rows = list(
        bq.query(
            f"""
            SELECT
              audit_id,
              setting_key,
              action,
              before_value,
              after_value,
              before_type,
              after_type,
              before_category,
              after_category,
              before_description,
              after_description,
              changed_by,
              changed_at,
              source
            FROM `{_app_settings_audit_table()}`
            ORDER BY changed_at DESC
            LIMIT @limit
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("limit", "INT64", int(limit)),
                ]
            ),
        ).result()
    )

    return _admin_cache_set(cache_key, {
        "ok": True,
        "items": [
            {
                "audit_id": str(r.get("audit_id") or ""),
                "setting_key": str(r.get("setting_key") or ""),
                "action": str(r.get("action") or ""),
                "before_value": str(r.get("before_value") or ""),
                "after_value": str(r.get("after_value") or ""),
                "before_type": str(r.get("before_type") or ""),
                "after_type": str(r.get("after_type") or ""),
                "before_category": str(r.get("before_category") or ""),
                "after_category": str(r.get("after_category") or ""),
                "before_description": str(r.get("before_description") or ""),
                "after_description": str(r.get("after_description") or ""),
                "changed_by": str(r.get("changed_by") or ""),
                "changed_at": str(r.get("changed_at") or ""),
                "source": str(r.get("source") or ""),
            }
            for r in rows
        ],
        "table": _app_settings_audit_table(),
    })

@app.get("/api/admin/settings")
@app.get("/admin/settings")
def admin_list_settings(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar parâmetros.")

    cached = _admin_cache_get("admin_settings")
    if cached is not None:
        return cached

    _seed_default_app_settings()

    rows = list(
        bq.query(
            f"""
            SELECT
              setting_key,
              setting_value,
              value_type,
              category,
              description,
              created_at,
              updated_at,
              updated_by
            FROM `{_app_settings_table()}`
            ORDER BY category ASC, setting_key ASC
            """
        ).result()
    )

    return _admin_cache_set("admin_settings", {
        "ok": True,
        "items": [
            {
                "setting_key": str(r.get("setting_key") or ""),
                "setting_value": str(r.get("setting_value") or ""),
                "value_type": str(r.get("value_type") or "string"),
                "category": str(r.get("category") or "Sistema"),
                "description": str(r.get("description") or ""),
                "created_at": str(r.get("created_at") or ""),
                "updated_at": str(r.get("updated_at") or ""),
                "updated_by": str(r.get("updated_by") or ""),
            }
            for r in rows
        ],
        "table": _app_settings_table(),
    })


@app.post("/api/admin/settings")
@app.post("/admin/settings")
def admin_upsert_setting(payload: AdminSettingPayload, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem alterar parâmetros.")

    key = _normalize_setting_key(payload.setting_key)
    value = str(payload.setting_value or "")
    value_type = _normalize_setting_type(payload.value_type)
    category = str(payload.category or "Sistema").strip() or "Sistema"
    description = str(payload.description or "").strip()
    now = _now_utc()
    updated_by = _user_email(request)
    before_record = _get_app_setting_record(key)

    _ensure_app_settings_table()

    bq.query(
        f"""
        MERGE `{_app_settings_table()}` T
        USING (
          SELECT
            @setting_key AS setting_key,
            @setting_value AS setting_value,
            @value_type AS value_type,
            @category AS category,
            @description AS description,
            @now AS now_ts,
            @updated_by AS updated_by
        ) S
        ON T.setting_key = S.setting_key
        WHEN MATCHED THEN
          UPDATE SET
            setting_value = S.setting_value,
            value_type = S.value_type,
            category = S.category,
            description = S.description,
            updated_at = S.now_ts,
            updated_by = S.updated_by
        WHEN NOT MATCHED THEN
          INSERT (setting_key, setting_value, value_type, category, description, created_at, updated_at, updated_by)
          VALUES (S.setting_key, S.setting_value, S.value_type, S.category, S.description, S.now_ts, S.now_ts, S.updated_by)
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("setting_key", "STRING", key),
                bigquery.ScalarQueryParameter("setting_value", "STRING", value),
                bigquery.ScalarQueryParameter("value_type", "STRING", value_type),
                bigquery.ScalarQueryParameter("category", "STRING", category),
                bigquery.ScalarQueryParameter("description", "STRING", description),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("updated_by", "STRING", updated_by),
            ]
        ),
    ).result()

    action = "created" if before_record is None else "updated"

    _write_app_setting_audit(
        setting_key=key,
        action=action,
        before_record=before_record,
        after_value=value,
        after_type=value_type,
        after_category=category,
        after_description=description,
        changed_by=updated_by,
    )

    _clear_admin_data_cache("admin_settings")
    _clear_admin_data_cache("admin_settings_audit")

    return {
        "ok": True,
        "item": {
            "setting_key": key,
            "setting_value": value,
            "value_type": value_type,
            "category": category,
            "description": description,
            "updated_at": now.isoformat(),
            "updated_by": updated_by,
        },
    }


class AdminUserPayload(BaseModel):
    email: str
    role: str = "seller"
    active: bool = True


def _app_users_table() -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.app_users"


def _ensure_app_users_table():
    table_id = _app_users_table()
    schema = [
        bigquery.SchemaField("email", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("role", "STRING"),
        bigquery.SchemaField("active", "BOOL"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_by", "STRING"),
    ]

    try:
        bq.get_table(table_id)
    except Exception:
        try:
            bq.create_table(bigquery.Table(table_id, schema=schema))
        except Exception:
            # Pode ocorrer corrida se duas requisições criarem ao mesmo tempo.
            try:
                bq.get_table(table_id)
            except Exception:
                raise

    for col, typ in [
        ("email", "STRING"),
        ("role", "STRING"),
        ("active", "BOOL"),
        ("created_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
        ("updated_by", "STRING"),
    ]:
        try:
            bq.query(f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS {col} {typ}").result()
        except Exception:
            pass




def _app_user_audit_table() -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.app_user_audit"


def _ensure_app_user_audit_table():
    table_id = _app_user_audit_table()
    schema = [
        bigquery.SchemaField("audit_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("target_email", "STRING"),
        bigquery.SchemaField("action", "STRING"),
        bigquery.SchemaField("before_role", "STRING"),
        bigquery.SchemaField("after_role", "STRING"),
        bigquery.SchemaField("before_active", "BOOL"),
        bigquery.SchemaField("after_active", "BOOL"),
        bigquery.SchemaField("changed_by", "STRING"),
        bigquery.SchemaField("changed_at", "TIMESTAMP"),
        bigquery.SchemaField("source", "STRING"),
    ]

    try:
        bq.get_table(table_id)
    except Exception:
        try:
            bq.create_table(bigquery.Table(table_id, schema=schema))
        except Exception:
            try:
                bq.get_table(table_id)
            except Exception:
                raise

    for col, typ in [
        ("audit_id", "STRING"),
        ("target_email", "STRING"),
        ("action", "STRING"),
        ("before_role", "STRING"),
        ("after_role", "STRING"),
        ("before_active", "BOOL"),
        ("after_active", "BOOL"),
        ("changed_by", "STRING"),
        ("changed_at", "TIMESTAMP"),
        ("source", "STRING"),
    ]:
        try:
            bq.query(f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS {col} {typ}").result()
        except Exception:
            pass


def _write_app_user_audit(
    *,
    target_email: str,
    action: str,
    before_record=None,
    after_role: str = "",
    after_active=None,
    changed_by: str = "",
):
    try:
        _ensure_app_user_audit_table()
        now = _now_utc()
        before_record = before_record or {}
        before_role = str(before_record.get("role") or "") if before_record else ""
        before_active = before_record.get("active") if before_record else None

        bq.query(
            f"""
            INSERT INTO `{_app_user_audit_table()}`
              (audit_id, target_email, action, before_role, after_role,
               before_active, after_active, changed_by, changed_at, source)
            VALUES
              (@audit_id, @target_email, @action, @before_role, @after_role,
               @before_active, @after_active, @changed_by, @changed_at, @source)
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("audit_id", "STRING", str(uuid.uuid4())),
                    bigquery.ScalarQueryParameter("target_email", "STRING", str(target_email or "").strip().lower()),
                    bigquery.ScalarQueryParameter("action", "STRING", str(action or "")),
                    bigquery.ScalarQueryParameter("before_role", "STRING", before_role),
                    bigquery.ScalarQueryParameter("after_role", "STRING", str(after_role or "")),
                    bigquery.ScalarQueryParameter("before_active", "BOOL", before_active),
                    bigquery.ScalarQueryParameter("after_active", "BOOL", after_active),
                    bigquery.ScalarQueryParameter("changed_by", "STRING", str(changed_by or "")),
                    bigquery.ScalarQueryParameter("changed_at", "TIMESTAMP", now),
                    bigquery.ScalarQueryParameter("source", "STRING", "admin_settings"),
                ]
            ),
        ).result()
    except Exception as e:
        print(f"[ADMIN_AUDIT_ERROR] {e}")


def _normalize_app_role(role: str) -> str:
    r = str(role or "").strip().lower()
    if r == "allowed":
        r = "seller"
    if r not in APP_USER_ROLES:
        raise HTTPException(status_code=400, detail="Permissão inválida. Use admin, seller ou expedition.")
    return r


def _normalize_email(email: str) -> str:
    e = str(email or "").strip().lower()
    if not e or "@" not in e:
        raise HTTPException(status_code=400, detail="E-mail inválido.")
    return e


def _get_app_user_record(email: str):
    email = str(email or "").strip().lower()
    if not email:
        return None

    try:
        _ensure_app_users_table()
        rows = list(
            bq.query(
                f"""
                SELECT email, role, active, created_at, updated_at, updated_by
                FROM `{_app_users_table()}`
                WHERE LOWER(email) = @email
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("email", "STRING", email),
                    ]
                ),
            ).result()
        )
        return dict(rows[0]) if rows else None
    except Exception:
        # Segurança: falha no BigQuery não deve derrubar acesso via env vars.
        return None



ADMIN_DATA_CACHE_TTL_SECONDS = int(os.getenv("ADMIN_DATA_CACHE_TTL_SECONDS", "900"))
_ADMIN_DATA_CACHE = {}


def _admin_cache_get(key: str):
    item = _ADMIN_DATA_CACHE.get(str(key or ""))
    if not item:
        return None

    now_ts = time.time()
    if (now_ts - float(item.get("ts") or 0)) >= ADMIN_DATA_CACHE_TTL_SECONDS:
        _ADMIN_DATA_CACHE.pop(str(key or ""), None)
        return None

    return item.get("value")


def _admin_cache_set(key: str, value):
    _ADMIN_DATA_CACHE[str(key or "")] = {
        "ts": time.time(),
        "value": value,
    }
    return value


def _clear_admin_data_cache(prefix: str = ""):
    prefix = str(prefix or "")
    if not prefix:
        _ADMIN_DATA_CACHE.clear()
        return

    for key in list(_ADMIN_DATA_CACHE.keys()):
        if key.startswith(prefix):
            _ADMIN_DATA_CACHE.pop(key, None)

APP_USER_CACHE_TTL_SECONDS = int(os.getenv("APP_USER_CACHE_TTL_SECONDS", "60"))
_APP_USER_RECORD_CACHE = {}


def _clear_app_user_cache(email: str = ""):
    email = str(email or "").strip().lower()
    if email:
        _APP_USER_RECORD_CACHE.pop(email, None)
    else:
        _APP_USER_RECORD_CACHE.clear()


def _get_app_user_record_cached(email: str):
    email = str(email or "").strip().lower()
    if not email:
        return None

    now_ts = time.time()
    cached = _APP_USER_RECORD_CACHE.get(email)
    if cached and (now_ts - float(cached.get("ts") or 0)) < APP_USER_CACHE_TTL_SECONDS:
        return cached.get("record")

    record = _get_app_user_record(email)
    _APP_USER_RECORD_CACHE[email] = {
        "ts": now_ts,
        "record": record,
    }
    return record


def _access_flags_for_email(email: str):
    email = str(email or "").strip().lower()

    env_admin = email in ADMIN_EMAILS
    env_allowed = email in ALLOWED_EMAILS
    env_expedition = email in EXPEDITION_EMAILS

    # app_users é a fonte operacional da tela Administração.
    # Cache evita consultar BigQuery em toda requisição.
    # Regra:
    # - Se existe registro em app_users e active=false: bloqueia, mesmo se estiver em env var.
    # - Se existe registro em app_users e active=true: usa a role da tela.
    # - Se não existe registro em app_users: usa env vars como fallback legado.
    record = _get_app_user_record_cached(email)

    if record is not None:
        db_active = bool(record.get("active"))
        db_role = str(record.get("role") or "").strip().lower()

        if not db_active:
            return {
                "is_admin": False,
                "is_allowed": False,
                "is_expedition": False,
                "db_role": db_role,
                "db_active": False,
                "source": "bigquery_inactive_override_cached",
            }

        db_admin = db_role == "admin"
        db_expedition = db_role == "expedition"
        db_allowed = db_role in ("admin", "seller", "allowed")

        return {
            "is_admin": bool(db_admin),
            "is_allowed": bool(db_allowed),
            "is_expedition": bool(db_expedition),
            "db_role": db_role,
            "db_active": True,
            "source": "bigquery_cached",
        }

    return {
        "is_admin": bool(env_admin),
        "is_allowed": bool(env_allowed or env_admin),
        "is_expedition": bool(env_expedition),
        "db_role": "",
        "db_active": False,
        "source": "env",
    }



def _admin_user_row_to_dict(r):
    email = str(r.get("email") or "").strip().lower()
    role = str(r.get("role") or "").strip().lower() or "seller"
    active = bool(r.get("active"))
    return {
        "email": email,
        "role": role,
        "active": active,
        "created_at": str(r.get("created_at") or ""),
        "updated_at": str(r.get("updated_at") or ""),
        "updated_by": str(r.get("updated_by") or ""),
        "env_admin": email in ADMIN_EMAILS,
        "env_allowed": email in ALLOWED_EMAILS,
        "env_expedition": email in EXPEDITION_EMAILS,
    }



@app.middleware("http")
async def verify_firebase_token(request: Request, call_next):
    path = request.url.path

    if request.method == "OPTIONS":
        return await call_next(request)

    debug_key = (request.query_params.get("key") or "").strip()
    if (
        (path.startswith("/debug/conta-receber/") or path == "/debug/conta-receber-search")
        and debug_key and debug_key == os.getenv("DEBUG_KEY", "")
    ):
        return await call_next(request)

    if path in PUBLIC_PATHS:
        return await call_next(request)

    if path.startswith("/debug/receber/by-order/"):
        debug_key = request.query_params.get("key")
        if debug_key and debug_key == os.getenv("DEBUG_KEY", ""):
            return await call_next(request)

    sync_key = os.getenv("OPS_SYNC_KEY", "").strip()
    if path in (
        "/ops/sync-tiny-orders",
        "/api/ops/sync-tiny-orders",
        "/ops/enrich-tiny-financials",
        "/api/ops/enrich-tiny-financials",
    ):
        supplied_sync_key = (
            request.headers.get("x-ops-sync-key")
            or request.query_params.get("key")
            or ""
        ).strip()

        if sync_key and supplied_sync_key and secrets.compare_digest(sync_key, supplied_sync_key):
            request.state.user = {"email": "ops-sync@internal"}
            request.state.user_email = "ops-sync@internal"
            request.state.is_admin = True
            request.state.is_expedition = False
            return await call_next(request)

    if not FIREBASE_READY or _fb_auth is None:
        return JSONResponse(
            status_code=503,
            content={"detail": f"Auth não inicializado: {_fb_error}"},
        )

    auth_header = request.headers.get("authorization", "") or ""
    if not auth_header.lower().startswith("bearer "):
        return JSONResponse(status_code=401, content={"detail": "Missing bearer token"})

    token = auth_header.split(" ", 1)[1].strip()
    try:
        decoded = _fb_auth.verify_id_token(token)
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})

    email = (decoded.get("email") or "").strip().lower()

    access_flags = _access_flags_for_email(email)
    is_admin = bool(access_flags.get("is_admin"))
    is_allowed = bool(access_flags.get("is_allowed"))
    is_expedition = bool(access_flags.get("is_expedition"))

    if (ALLOWED_EMAILS or ADMIN_EMAILS or EXPEDITION_EMAILS) and not (is_admin or is_allowed or is_expedition):
        return JSONResponse(
            status_code=403,
            content={"detail": "Acesso negado: usuário não autorizado."},
        )

    if path.startswith("/separation") and not (is_admin or is_expedition):
        return JSONResponse(status_code=403, content={"detail": "Acesso negado à área de separação."})

    non_separation_allowed_paths = {
        "/",
        "/health",
        "/me",
        "/api/me",
        "/docs",
        "/openapi.json",
        "/favicon.ico",
    }

    if is_expedition and not is_admin and (path not in non_separation_allowed_paths) and not path.startswith("/separation") and not path.startswith("/api/separation"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Usuário de expedição sem acesso a este recurso."},
        )
        
    request.state.user = decoded
    request.state.user_email = email
    request.state.is_admin = is_admin
    request.state.is_allowed = is_allowed
    request.state.is_expedition = is_expedition
    request.state.access_source = access_flags.get("source")
    request.state.db_role = access_flags.get("db_role")
    return await call_next(request)


def _user_email(request: Request) -> str:
    u = getattr(request.state, "user", None) or {}
    return (u.get("email") or "").strip().lower()


def _is_admin(request: Request) -> bool:
    if hasattr(request.state, "is_admin"):
        return bool(getattr(request.state, "is_admin", False))
    return _user_email(request) in ADMIN_EMAILS


def _is_expedition(request: Request) -> bool:
    if hasattr(request.state, "is_expedition"):
        return bool(getattr(request.state, "is_expedition", False))
    return _user_email(request) in EXPEDITION_EMAILS


def _is_allowed_user(request: Request) -> bool:
    if hasattr(request.state, "is_allowed"):
        return bool(getattr(request.state, "is_allowed", False))
    email = _user_email(request)
    return email in ALLOWED_EMAILS or email in ADMIN_EMAILS


def _can_access_separation(request: Request) -> bool:
    return _is_admin(request) or _is_expedition(request)


def _separation_status_default() -> str:
    return "A separar"


def _tiny_order_status_text(order_resp: Dict[str, Any]) -> str:
    pedido = order_resp.get("pedido") or {}
    return str(
        pedido.get("situacao")
        or pedido.get("situacao_nome")
        or pedido.get("descricao_situacao")
        or pedido.get("status")
        or ""
    ).strip()


def _tiny_change_order_status(tiny_order_id: int, situacao: str) -> Dict[str, Any]:
    try:
        resp = tiny._post("pedido.alterar.situacao.php", {
            "id": int(tiny_order_id),
            "situacao": str(situacao).strip(),
        })
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=f"Erro ao alterar situação no Tiny: {e}")

    status_txt = str(resp.get("status") or "").strip().upper()
    if status_txt != "OK":
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao alterar situação no Tiny. Resposta: {resp}",
        )

    return resp


def _tiny_sync_and_verify_status(tiny_order_id: int, target_status: str, context: str) -> None:
    target_norm = _norm_text(target_status)

    before_resp = tiny.obter_pedido(int(tiny_order_id))
    before_status_raw = _tiny_order_status_text(before_resp)
    before_status = _norm_text(before_status_raw)

    if before_status != target_norm:
        sync_resp = _tiny_change_order_status(int(tiny_order_id), target_status)
        print(f"[TINY_STATUS_SYNC] {context} response:", json.dumps(sync_resp, ensure_ascii=False))

    after_resp = tiny.obter_pedido(int(tiny_order_id))
    after_status_raw = _tiny_order_status_text(after_resp)
    after_status = _norm_text(after_status_raw)

    print(f"[TINY_STATUS_SYNC] {context} verify:", json.dumps({
        "tiny_order_id": int(tiny_order_id),
        "target_status_raw": target_status,
        "target_status_norm": target_norm,
        "before_status_raw": before_status_raw,
        "before_status_norm": before_status,
        "after_status_raw": after_status_raw,
        "after_status_norm": after_status,
    }, ensure_ascii=False))

    if after_status != target_norm:
        raise HTTPException(
            status_code=502,
            detail=f"Pedido não ficou em '{target_status}' no Tiny. Status atual: {after_status_raw or 'desconhecido'}"
        )


def _upsert_separation_order(
    tiny_order_id: int,
    tiny_order_number: Optional[str],
    quote_id: Optional[str],
    quote_number: Optional[int],
    client_name: Optional[str],
    seller_name: Optional[str],
    status: Optional[str] = None,
    printed: Optional[bool] = None,
    assigned_to: Optional[str] = None,
    notes: Optional[str] = None,
    packaging_boxes: Optional[int] = None,
    packaging_bags: Optional[int] = None,
    packaging_weight_kg: Optional[float] = None,
    packaging_height_cm: Optional[float] = None,
    packaging_width_cm: Optional[float] = None,
    packaging_length_cm: Optional[float] = None,
    packaging_volumes: Optional[int] = None,
):
    now = _now_utc()
    sql = f"""
    MERGE {_table('separation_orders')} T
    USING (
      SELECT
        @tiny_order_id AS tiny_order_id,
        @tiny_order_number AS tiny_order_number,
        @quote_id AS quote_id,
        @quote_number AS quote_number,
        @client_name AS client_name,
        @seller_name AS seller_name,
        @status AS status,
        @printed AS printed,
        @assigned_to AS assigned_to,
        @notes AS notes,
        @packaging_boxes AS packaging_boxes,
        @packaging_bags AS packaging_bags,
        @packaging_weight_kg AS packaging_weight_kg,
        @packaging_height_cm AS packaging_height_cm,
        @packaging_width_cm AS packaging_width_cm,
        @packaging_length_cm AS packaging_length_cm,
        @packaging_volumes AS packaging_volumes,
        @now AS now
    ) S
    ON T.tiny_order_id = S.tiny_order_id
    WHEN MATCHED THEN UPDATE SET
      tiny_order_number = COALESCE(S.tiny_order_number, T.tiny_order_number),
      quote_id = COALESCE(S.quote_id, T.quote_id),
      quote_number = COALESCE(S.quote_number, T.quote_number),
      client_name = COALESCE(S.client_name, T.client_name),
      seller_name = COALESCE(S.seller_name, T.seller_name),
      status = COALESCE(S.status, T.status),
      printed = COALESCE(S.printed, T.printed),
      assigned_to = COALESCE(S.assigned_to, T.assigned_to),
      notes = COALESCE(S.notes, T.notes),
      packaging_boxes = COALESCE(S.packaging_boxes, T.packaging_boxes),
      packaging_bags = COALESCE(S.packaging_bags, T.packaging_bags),
      packaging_weight_kg = COALESCE(S.packaging_weight_kg, T.packaging_weight_kg),
      packaging_height_cm = COALESCE(S.packaging_height_cm, T.packaging_height_cm),
      packaging_width_cm = COALESCE(S.packaging_width_cm, T.packaging_width_cm),
      packaging_length_cm = COALESCE(S.packaging_length_cm, T.packaging_length_cm),
      packaging_volumes = COALESCE(S.packaging_volumes, T.packaging_volumes),
      updated_at = S.now
    WHEN NOT MATCHED THEN INSERT (
      tiny_order_id, tiny_order_number, quote_id, quote_number, client_name, seller_name,
      status, printed, assigned_to, notes, packaging_boxes, packaging_bags,
      packaging_weight_kg, packaging_height_cm, packaging_width_cm, packaging_length_cm, packaging_volumes,
      created_at, updated_at
    ) VALUES (
      S.tiny_order_id, S.tiny_order_number, S.quote_id, S.quote_number, S.client_name, S.seller_name,
      COALESCE(S.status, 'A separar'), COALESCE(S.printed, FALSE), S.assigned_to, S.notes, S.packaging_boxes, S.packaging_bags,
      S.packaging_weight_kg, S.packaging_height_cm, S.packaging_width_cm, S.packaging_length_cm, S.packaging_volumes,
      S.now, S.now
    )
    """
    bq.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("tiny_order_id", "INT64", int(tiny_order_id)),
        bigquery.ScalarQueryParameter("tiny_order_number", "STRING", str(tiny_order_number) if tiny_order_number else None),
        bigquery.ScalarQueryParameter("quote_id", "STRING", quote_id),
        bigquery.ScalarQueryParameter("quote_number", "INT64", int(quote_number) if quote_number is not None else None),
        bigquery.ScalarQueryParameter("client_name", "STRING", client_name),
        bigquery.ScalarQueryParameter("seller_name", "STRING", seller_name),
        bigquery.ScalarQueryParameter("status", "STRING", status),
        bigquery.ScalarQueryParameter("printed", "BOOL", printed),
        bigquery.ScalarQueryParameter("assigned_to", "STRING", assigned_to),
        bigquery.ScalarQueryParameter("notes", "STRING", notes),
        bigquery.ScalarQueryParameter("packaging_boxes", "INT64", packaging_boxes),
        bigquery.ScalarQueryParameter("packaging_bags", "INT64", packaging_bags),
        bigquery.ScalarQueryParameter("packaging_weight_kg", "FLOAT64", packaging_weight_kg),
        bigquery.ScalarQueryParameter("packaging_height_cm", "FLOAT64", packaging_height_cm),
        bigquery.ScalarQueryParameter("packaging_width_cm", "FLOAT64", packaging_width_cm),
        bigquery.ScalarQueryParameter("packaging_length_cm", "FLOAT64", packaging_length_cm),
        bigquery.ScalarQueryParameter("packaging_volumes", "INT64", packaging_volumes),
        bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
    ])).result()


@app.get("/")
def root():
    return {"ok": True, "service": "prevenda-api", "hint": "use /health"}


@app.get("/health")
def health():
    return {
        "ok": True,
        "project": PROJECT_ID,
        "dataset": DATASET_ID,
        "auth_ready": FIREBASE_READY,
        "admin_emails_loaded": len(ADMIN_EMAILS),
        "allowed_emails_loaded": len(ALLOWED_EMAILS),
        "expedition_emails_loaded": len(EXPEDITION_EMAILS),
    }



# ============================================================
# Tiny/Olist API V3 - OAuth automático + diagnóstico beta
# ============================================================

V3_TOKEN_TABLE = "tiny_v3_oauth_tokens"


def _ensure_v3_beta() -> None:
    # Nome legado mantido por compatibilidade com as rotas debug/preview.
    # Agora a V3 está liberada para leitura/preview nos datasets operacionais controlados.
    allowed = {"tiny_orcamento_beta", "tiny_orcamento", "tiny_orcamento_informatica"}
    if DATASET_ID not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Integração V3 bloqueada para dataset não permitido: {DATASET_ID}",
        )


def _ensure_v3_debug_allowed(request: Request) -> None:
    _ensure_v3_beta()
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar o diagnóstico V3.")


def _v3_tokens_table() -> str:
    return f"`{PROJECT_ID}.{DATASET_ID}.{V3_TOKEN_TABLE}`"


def _v3_token_plain_table() -> str:
    return f"{PROJECT_ID}.{DATASET_ID}.{V3_TOKEN_TABLE}"


def _v3_oauth_env() -> Dict[str, str]:
    return {
        "client_id": os.getenv("TINY_V3_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("TINY_V3_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("TINY_V3_REDIRECT_URI", "https://beta-projetotrml.web.app/api/v3-auth/callback").strip(),
        "auth_url": os.getenv("TINY_V3_AUTH_URL", "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth").strip(),
        "token_url": os.getenv("TINY_V3_TOKEN_URL", "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token").strip(),
    }


def _v3_bootstrap_token_table() -> None:
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{V3_TOKEN_TABLE}"
    schema = [
        bigquery.SchemaField("provider", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("environment", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("access_token", "STRING"),
        bigquery.SchemaField("refresh_token", "STRING"),
        bigquery.SchemaField("expires_at", "TIMESTAMP"),
        bigquery.SchemaField("scope", "STRING"),
        bigquery.SchemaField("token_type", "STRING"),
        bigquery.SchemaField("raw_response", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_by", "STRING"),
    ]
    table = bigquery.Table(table_ref, schema=schema)
    try:
        bq.create_table(table, exists_ok=True)
    except TypeError:
        try:
            bq.get_table(table_ref)
        except Exception:
            bq.create_table(table)


def _v3_get_token_row() -> Optional[Dict[str, Any]]:
    _v3_bootstrap_token_table()
    sql = f"""
    SELECT provider, environment, access_token, refresh_token, expires_at, scope, token_type, raw_response, created_at, updated_at, updated_by
    FROM {_v3_tokens_table()}
    WHERE provider = @provider AND environment = @environment
    ORDER BY updated_at DESC
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("provider", "STRING", "tiny_v3"),
        bigquery.ScalarQueryParameter("environment", "STRING", "beta"),
    ])
    rows = list(bq.query(sql, job_config=job_config).result())
    if not rows:
        return None
    return dict(rows[0])


def _v3_save_token(payload: Dict[str, Any], updated_by: str = "oauth-callback") -> Dict[str, Any]:
    _v3_bootstrap_token_table()

    now = _now_utc()
    expires_in = int(payload.get("expires_in") or 0)
    expires_at = now + dt.timedelta(seconds=max(0, expires_in - 120)) if expires_in else now + dt.timedelta(hours=3, minutes=50)

    current = _v3_get_token_row() or {}
    access_token = str(payload.get("access_token") or "").strip()
    refresh_token = str(payload.get("refresh_token") or current.get("refresh_token") or "").strip()

    if not access_token:
        raise HTTPException(status_code=502, detail="OAuth V3 não retornou access_token.")
    if not refresh_token:
        raise HTTPException(status_code=502, detail="OAuth V3 não retornou refresh_token.")

    row = {
        "provider": "tiny_v3",
        "environment": "beta",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at.isoformat(),
        "scope": str(payload.get("scope") or ""),
        "token_type": str(payload.get("token_type") or "Bearer"),
        "raw_response": json.dumps({k: ("***" if "token" in k else v) for k, v in payload.items()}, ensure_ascii=False, default=str),
        "created_at": (current.get("created_at") or now).isoformat() if current else now.isoformat(),
        "updated_at": now.isoformat(),
        "updated_by": updated_by,
    }

    sql = f"""
    DELETE FROM {_v3_tokens_table()}
    WHERE provider = @provider AND environment = @environment
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("provider", "STRING", "tiny_v3"),
        bigquery.ScalarQueryParameter("environment", "STRING", "beta"),
    ])
    bq.query(sql, job_config=job_config).result()

    errors = bq.insert_rows_json(_v3_token_plain_table(), [row])
    if errors:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar token V3 no BigQuery: {errors}")

    return row


def _v3_exchange_code_for_token(code: str) -> Dict[str, Any]:
    env = _v3_oauth_env()
    missing = [k for k in ("client_id", "client_secret", "redirect_uri") if not env.get(k)]
    if missing:
        raise HTTPException(status_code=500, detail=f"Env V3 ausente: {', '.join(missing)}")

    resp = requests.post(
        env["token_url"],
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "client_id": env["client_id"],
            "client_secret": env["client_secret"],
            "redirect_uri": env["redirect_uri"],
            "code": code,
        },
        timeout=30,
    )

    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": resp.text[:2000]}

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao trocar code por token V3: HTTP {resp.status_code} - {json.dumps(data, ensure_ascii=False)[:1500]}",
        )

    return data


def _v3_refresh_access_token() -> Dict[str, Any]:
    env = _v3_oauth_env()
    row = _v3_get_token_row()
    if not row or not row.get("refresh_token"):
        raise HTTPException(status_code=409, detail="Token V3 ainda não autorizado. Acesse /api/v3-auth/start primeiro.")

    resp = requests.post(
        env["token_url"],
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "client_id": env["client_id"],
            "client_secret": env["client_secret"],
            "refresh_token": row.get("refresh_token"),
        },
        timeout=30,
    )

    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": resp.text[:2000]}

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao renovar token V3: HTTP {resp.status_code} - {json.dumps(data, ensure_ascii=False)[:1500]}",
        )

    return _v3_save_token(data, updated_by="refresh-token")


def _v3_get_valid_access_token() -> str:
    row = _v3_get_token_row()
    if not row:
        raise HTTPException(status_code=409, detail="Token V3 ainda não autorizado. Acesse /api/v3-auth/start primeiro.")

    expires_at = row.get("expires_at")
    expired = True
    if expires_at:
        try:
            if isinstance(expires_at, str):
                exp = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            else:
                exp = expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=dt.timezone.utc)
            expired = exp <= (_now_utc() + dt.timedelta(minutes=5))
        except Exception:
            expired = True

    if expired:
        row = _v3_refresh_access_token()

    token = str(row.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=409, detail="Access token V3 vazio após autorização/refresh.")

    return token


def _tiny_v3_client() -> TinyV3Client:
    return TinyV3Client(load_v3_config_from_env(access_token=_v3_get_valid_access_token()))


@app.get("/api/v3-auth/start")
@app.get("/v3-auth/start")
def v3_auth_start(request: Request):
    # Público apenas para iniciar OAuth no beta.
    # Não expõe client_secret, não altera pedido e não salva token.
    _ensure_v3_beta()

    env = _v3_oauth_env()
    missing = [k for k in ("client_id", "redirect_uri", "auth_url") if not env.get(k)]
    if missing:
        raise HTTPException(status_code=500, detail=f"Env V3 ausente: {', '.join(missing)}")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": env["client_id"],
        "redirect_uri": env["redirect_uri"],
        "scope": "openid",
        "response_type": "code",
        "state": state,
    }

    from urllib.parse import urlencode
    url = f"{env['auth_url']}?{urlencode(params)}"

    return {
        "ok": True,
        "message": "Abra authorization_url no navegador para autorizar o aplicativo V3.",
        "authorization_url": url,
        "redirect_uri": env["redirect_uri"],
    }


@app.get("/api/v3-auth/callback")
@app.get("/v3-auth/callback")
def v3_auth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    _ensure_v3_beta()

    if error:
        raise HTTPException(status_code=400, detail=f"OAuth V3 retornou erro: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Callback OAuth V3 sem parâmetro code.")

    token_payload = _v3_exchange_code_for_token(code)
    saved = _v3_save_token(token_payload, updated_by="oauth-callback")

    return {
        "ok": True,
        "message": "Token V3 autorizado e salvo no BigQuery beta.",
        "provider": saved.get("provider"),
        "environment": saved.get("environment"),
        "expires_at": str(saved.get("expires_at")),
        "has_access_token": bool(saved.get("access_token")),
        "has_refresh_token": bool(saved.get("refresh_token")),
    }


@app.get("/api/v3-auth/status")
@app.get("/v3-auth/status")
def v3_auth_status(request: Request):
    _ensure_v3_debug_allowed(request)

    env = _v3_oauth_env()
    row = _v3_get_token_row()

    return {
        "ok": True,
        "dataset": DATASET_ID,
        "beta_only": True,
        "env": {
            "client_id_loaded": bool(env.get("client_id")),
            "client_secret_loaded": bool(env.get("client_secret")),
            "redirect_uri": env.get("redirect_uri"),
            "auth_url": env.get("auth_url"),
            "token_url": env.get("token_url"),
            "base_url": os.getenv("TINY_V3_BASE_URL", "https://api.tiny.com.br/public-api/v3").strip(),
        },
        "token": {
            "saved": bool(row),
            "has_access_token": bool(row and row.get("access_token")),
            "has_refresh_token": bool(row and row.get("refresh_token")),
            "expires_at": str(row.get("expires_at")) if row else None,
            "updated_at": str(row.get("updated_at")) if row else None,
            "updated_by": str(row.get("updated_by")) if row else None,
        },
    }


@app.get("/api/v3-auth/refresh")
@app.get("/v3-auth/refresh")
def v3_auth_refresh(request: Request):
    _ensure_v3_debug_allowed(request)
    row = _v3_refresh_access_token()
    return {
        "ok": True,
        "message": "Token V3 renovado.",
        "expires_at": str(row.get("expires_at")),
        "has_access_token": bool(row.get("access_token")),
        "has_refresh_token": bool(row.get("refresh_token")),
    }


@app.get("/api/v3-debug/config")
@app.get("/v3-debug/config")
def v3_debug_config(request: Request):
    _ensure_v3_debug_allowed(request)
    return v3_auth_status(request)


@app.get("/api/v3-debug/pedidos")
@app.get("/v3-debug/pedidos")
def v3_debug_list_pedidos(
    request: Request,
    numero: Optional[int] = None,
    nomeCliente: Optional[str] = None,
    dataInicial: Optional[str] = None,
    dataFinal: Optional[str] = None,
    situacao: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
):
    _ensure_v3_debug_allowed(request)

    params: Dict[str, Any] = {
        "limit": max(1, min(int(limit or 20), 100)),
        "offset": max(0, int(offset or 0)),
    }

    if numero is not None:
        params["numero"] = int(numero)
    if nomeCliente:
        params["nomeCliente"] = nomeCliente
    if dataInicial:
        params["dataInicial"] = dataInicial
    if dataFinal:
        params["dataFinal"] = dataFinal
    if situacao is not None:
        params["situacao"] = int(situacao)

    try:
        resp = _tiny_v3_client().listar_pedidos(params=params)
        return jsonable_encoder({
            "ok": True,
            "dataset": DATASET_ID,
            "params": params,
            "tiny_v3": resp,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao listar pedidos na API V3: {str(e)[:1500]}",
        )


def _v3_status_label(situacao: Any) -> str:
    try:
        code = int(situacao)
    except Exception:
        return "Desconhecido"

    return {
        0: "Em Aberto",
        1: "Faturado",
        2: "Cancelado",
        3: "Aprovado",
        4: "Preparando Envio",
        5: "Enviado",
        6: "Entregue",
        7: "Pronto para Envio",
        8: "Dados Incompletos",
        9: "Não Entregue",
    }.get(code, "Desconhecido")


def _normalize_status_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _v3_suggest_sync_action(local_row: Dict[str, Any], v3_label: str) -> str:
    local_internal = _normalize_status_text(local_row.get("internal_status"))
    local_status = _normalize_status_text(local_row.get("status"))
    v3_norm = _normalize_status_text(v3_label)

    if not local_row:
        return "Pedido encontrado na V3, mas não encontrado localmente no BigQuery."

    if v3_norm == "cancelado":
        if "cancel" in local_internal or "cancel" in local_status:
            return "OK: local já parece cancelado."
        return "Divergência: Tiny V3 está Cancelado. Verificar se local também deve ser marcado como Cancelado."

    if v3_norm == "faturado":
        if "fatur" in local_internal or "fatur" in local_status:
            return "OK: local já parece faturado."
        return "Divergência: Tiny V3 está Faturado. Verificar se local também deve ir para Faturado."

    if v3_norm == "preparando envio":
        if "preparando" in local_internal:
            return "OK: local já parece em Preparando Envio."
        return "Atenção: Tiny V3 está em Preparando Envio. Comparar com status local."

    if v3_norm == "pronto para envio":
        if "pronto" in local_internal:
            return "OK: local já parece Pronto para Envio."
        return "Atenção: Tiny V3 está Pronto para Envio. Comparar com status local."

    if v3_norm == "aprovado":
        if "aprov" in local_internal:
            return "OK: local já parece Aprovado."
        return "Atenção: Tiny V3 está Aprovado. Comparar com status local."

    if v3_norm == "em aberto":
        if "aberto" in local_internal:
            return "OK: local já parece Em Aberto."
        return "Atenção: Tiny V3 está Em Aberto. Comparar com status local."

    return "Sem sugestão automática. Revisar manualmente."


def _v3_fetch_local_quotes_by_numbers(numeros: List[int]) -> Dict[str, Dict[str, Any]]:
    if not numeros:
        return {}

    table = f"`{PROJECT_ID}.{DATASET_ID}.quotes`"
    numbers_str = [str(int(n)) for n in numeros]

    sql = f"""
    SELECT
      quote_id,
      quote_number,
      status,
      internal_status,
      tiny_order_id,
      tiny_order_number,
      seller_name,
      client_snapshot,
      updated_at,
      created_at
    FROM {table}
    WHERE CAST(tiny_order_number AS STRING) IN UNNEST(@numbers)
       OR CAST(quote_number AS STRING) IN UNNEST(@numbers)
    """

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ArrayQueryParameter("numbers", "STRING", numbers_str)
    ])

    rows = list(bq.query(sql, job_config=job_config).result())
    result: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        d = dict(row)
        keys = []
        if d.get("tiny_order_number") is not None:
            keys.append(str(d.get("tiny_order_number")))
        if d.get("quote_number") is not None:
            keys.append(str(d.get("quote_number")))

        for key in keys:
            if key and key not in result:
                result[key] = d

    return result


@app.get("/api/v3-debug/pedidos/sync-preview")
@app.get("/v3-debug/pedidos/sync-preview")
def v3_debug_sync_preview(request: Request, numeros: str):
    _ensure_v3_debug_allowed(request)

    raw_numbers = [x.strip() for x in str(numeros or "").split(",") if x.strip()]
    parsed_numbers: List[int] = []

    for raw in raw_numbers:
        try:
            parsed_numbers.append(int(raw))
        except Exception:
            continue

    parsed_numbers = parsed_numbers[:50]

    if not parsed_numbers:
        raise HTTPException(
            status_code=400,
            detail="Informe pelo menos um número de pedido em ?numeros=22560,23942",
        )

    local_by_number = _v3_fetch_local_quotes_by_numbers(parsed_numbers)
    client = _tiny_v3_client()
    resultados = []

    for numero in parsed_numbers:
        numero_key = str(numero)
        local_row = local_by_number.get(numero_key) or {}

        item_result = {
            "ok": False,
            "numeroPedido": numero,
            "local": {
                "found": bool(local_row),
                "quote_id": local_row.get("quote_id"),
                "quote_number": local_row.get("quote_number"),
                "status": local_row.get("status"),
                "internal_status": local_row.get("internal_status"),
                "tiny_order_id": local_row.get("tiny_order_id"),
                "tiny_order_number": local_row.get("tiny_order_number"),
                "seller_name": local_row.get("seller_name"),
                "updated_at": str(local_row.get("updated_at")) if local_row.get("updated_at") else None,
                "created_at": str(local_row.get("created_at")) if local_row.get("created_at") else None,
            },
            "tiny_v3": {
                "found": False,
                "idV3": None,
                "situacao": None,
                "statusLabel": None,
                "dataFaturamento": None,
                "idNotaFiscal": None,
                "cliente": None,
                "vendedor": None,
                "valorTotalPedido": None,
            },
            "comparacao": {
                "suggestion": None,
            },
            "erro": None,
        }

        try:
            list_resp = client.listar_pedidos(params={
                "numero": int(numero),
                "limit": 20,
                "offset": 0,
            })

            data = list_resp.get("data") or {}
            itens = data.get("itens") or []

            if not itens:
                item_result["erro"] = f"Nenhum pedido encontrado na API V3 com numeroPedido={numero}."
                item_result["comparacao"]["suggestion"] = "Pedido existe localmente? Não encontrado na V3 pelo número informado."
                resultados.append(item_result)
                continue

            first = itens[0] or {}
            id_v3 = first.get("id")

            if not id_v3:
                item_result["erro"] = f"Pedido numeroPedido={numero} encontrado, mas sem campo id no retorno V3."
                resultados.append(item_result)
                continue

            detail_resp = client.obter_pedido(int(id_v3))
            detalhe = detail_resp.get("data") or {}

            cliente_obj = detalhe.get("cliente") or {}
            vendedor_obj = detalhe.get("vendedor") or {}
            situacao = detalhe.get("situacao")
            label = _v3_status_label(situacao)

            item_result["ok"] = True
            item_result["tiny_v3"] = {
                "found": True,
                "idV3": int(id_v3),
                "situacao": situacao,
                "statusLabel": label,
                "dataFaturamento": detalhe.get("dataFaturamento"),
                "idNotaFiscal": detalhe.get("idNotaFiscal"),
                "cliente": cliente_obj.get("nome"),
                "vendedor": vendedor_obj.get("nome"),
                "valorTotalPedido": detalhe.get("valorTotalPedido"),
            }
            item_result["comparacao"]["suggestion"] = _v3_suggest_sync_action(local_row, label)

            resultados.append(item_result)

        except Exception as e:
            item_result["erro"] = str(e)[:1000]
            item_result["comparacao"]["suggestion"] = "Erro ao consultar/comparar. Revisar manualmente."
            resultados.append(item_result)

    return jsonable_encoder({
        "ok": True,
        "dataset": DATASET_ID,
        "read_only": True,
        "total_solicitado": len(parsed_numbers),
        "resultados": resultados,
        "observacao": "Prévia somente leitura. Nenhum status local ou Tiny foi alterado.",
    })




def _v3_target_local_internal_status(v3_situacao: Any, v3_label: str = "") -> Optional[str]:
    try:
        code = int(v3_situacao)
    except Exception:
        code = None

    by_code = {
        1: "Faturado",
        2: "Cancelado",
        4: "Preparando Envio",
        7: "Pronto para Envio",
    }

    if code in by_code:
        return by_code[code]

    norm = _normalize_status_text(v3_label)
    by_label = {
        "faturado": "Faturado",
        "cancelado": "Cancelado",
        "preparando envio": "Preparando Envio",
        "pronto para envio": "Pronto para Envio",
    }
    return by_label.get(norm)


@app.post("/api/v3/pedidos/sync-local-status")
@app.post("/v3/pedidos/sync-local-status")
def v3_sync_local_status_from_v3(
    request: Request,
    numeros: str,
    dry_run: bool = True,
    confirm: bool = False,
):
    _ensure_v3_debug_allowed(request)

    # Nesta fase, liberar escrita local apenas no Suprimentos produção.
    if DATASET_ID != "tiny_orcamento":
        raise HTTPException(
            status_code=403,
            detail=f"Sync local por V3 liberado apenas no Suprimentos nesta fase. Dataset atual: {DATASET_ID}",
        )

    raw_numbers = [x.strip() for x in str(numeros or "").split(",") if x.strip()]
    parsed_numbers: List[int] = []

    for raw in raw_numbers:
        try:
            parsed_numbers.append(int(raw))
        except Exception:
            continue

    parsed_numbers = parsed_numbers[:50]

    if not parsed_numbers:
        raise HTTPException(
            status_code=400,
            detail="Informe pelo menos um número de pedido em ?numeros=813,828",
        )

    should_write = (dry_run is False) and (confirm is True)

    local_by_number = _v3_fetch_local_quotes_by_numbers(parsed_numbers)
    client = _tiny_v3_client()
    resultados = []

    table = f"`{PROJECT_ID}.{DATASET_ID}.quotes`"
    updated_by = getattr(request.state, "user_email", "") or "v3-sync-local-status"

    for numero in parsed_numbers:
        numero_key = str(numero)
        local_row = local_by_number.get(numero_key) or {}

        item = {
            "ok": False,
            "numeroPedido": numero,
            "dry_run": bool(dry_run),
            "confirm": bool(confirm),
            "write_enabled": bool(should_write),
            "local": {
                "found": bool(local_row),
                "quote_id": local_row.get("quote_id"),
                "quote_number": local_row.get("quote_number"),
                "status": local_row.get("status"),
                "internal_status_before": local_row.get("internal_status"),
                "internal_status_after": None,
                "tiny_order_id": local_row.get("tiny_order_id"),
                "tiny_order_number": local_row.get("tiny_order_number"),
                "seller_name": local_row.get("seller_name"),
            },
            "tiny_v3": {
                "found": False,
                "idV3": None,
                "situacao": None,
                "statusLabel": None,
                "cliente": None,
                "vendedor": None,
                "valorTotalPedido": None,
            },
            "action": {
                "target_internal_status": None,
                "needs_update": False,
                "updated": False,
                "reason": None,
            },
            "erro": None,
        }

        try:
            if not local_row:
                item["action"]["reason"] = "Pedido não encontrado localmente no BigQuery."
                resultados.append(item)
                continue

            list_resp = client.listar_pedidos(params={
                "numero": int(numero),
                "limit": 20,
                "offset": 0,
            })

            data = list_resp.get("data") or {}
            itens = data.get("itens") or []

            if not itens:
                item["erro"] = f"Nenhum pedido encontrado na API V3 com numeroPedido={numero}."
                item["action"]["reason"] = "Sem pedido V3 para comparar."
                resultados.append(item)
                continue

            first = itens[0] or {}
            id_v3 = first.get("id")

            if not id_v3:
                item["erro"] = f"Pedido numeroPedido={numero} encontrado, mas sem campo id no retorno V3."
                item["action"]["reason"] = "Retorno V3 sem ID."
                resultados.append(item)
                continue

            detail_resp = client.obter_pedido(int(id_v3))
            detalhe = detail_resp.get("data") or {}

            cliente_obj = detalhe.get("cliente") or {}
            vendedor_obj = detalhe.get("vendedor") or {}
            situacao = detalhe.get("situacao")
            label = _v3_status_label(situacao)
            target = _v3_target_local_internal_status(situacao, label)

            item["ok"] = True
            item["tiny_v3"] = {
                "found": True,
                "idV3": int(id_v3),
                "situacao": situacao,
                "statusLabel": label,
                "cliente": cliente_obj.get("nome"),
                "vendedor": vendedor_obj.get("nome"),
                "valorTotalPedido": detalhe.get("valorTotalPedido"),
            }

            item["action"]["target_internal_status"] = target

            current_internal = str(local_row.get("internal_status") or "").strip()
            current_norm = _normalize_status_text(current_internal)
            target_norm = _normalize_status_text(target)

            if not target:
                item["action"]["needs_update"] = False
                item["action"]["reason"] = f"Situação V3 {situacao}/{label} sem mapeamento automático."
                resultados.append(item)
                continue

            if current_norm == target_norm:
                item["local"]["internal_status_after"] = current_internal
                item["action"]["needs_update"] = False
                item["action"]["reason"] = "Local já está igual ao Tiny V3."
                resultados.append(item)
                continue

            item["local"]["internal_status_after"] = target
            item["action"]["needs_update"] = True

            if not should_write:
                item["action"]["updated"] = False
                item["action"]["reason"] = "Prévia somente leitura. Para alterar use dry_run=false&confirm=true."
                resultados.append(item)
                continue

            sql = f"""
            UPDATE {table}
            SET internal_status = @target_status,
                updated_at = CURRENT_TIMESTAMP()
            WHERE quote_id = @quote_id
            """

            bq.query(
                sql,
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("target_status", "STRING", target),
                    bigquery.ScalarQueryParameter("quote_id", "STRING", local_row.get("quote_id")),
                ])
            ).result()

            item["action"]["updated"] = True
            item["action"]["reason"] = f"Status local atualizado por V3 por {updated_by}: {current_internal} -> {target}"

            print("[TINY_V3_LOCAL_STATUS_SYNC]", json.dumps({
                "dataset": DATASET_ID,
                "numeroPedido": numero,
                "quote_id": local_row.get("quote_id"),
                "before": current_internal,
                "after": target,
                "v3_situacao": situacao,
                "v3_label": label,
                "updated_by": updated_by,
            }, ensure_ascii=False, default=str))

            resultados.append(item)

        except Exception as e:
            item["erro"] = str(e)[:1500]
            item["action"]["reason"] = "Erro ao consultar ou atualizar. Revisar manualmente."
            resultados.append(item)

    return jsonable_encoder({
        "ok": True,
        "dataset": DATASET_ID,
        "operation": "sync_local_status_from_tiny_v3",
        "read_only": not should_write,
        "dry_run": bool(dry_run),
        "confirm": bool(confirm),
        "total_solicitado": len(parsed_numbers),
        "resultados": resultados,
        "observacao": (
            "Nenhum status local foi alterado."
            if not should_write
            else "Status local atualizado somente nos pedidos divergentes e mapeados."
        ),
    })


@app.get("/api/v3-debug/pedidos/mapa-status")
@app.get("/v3-debug/pedidos/mapa-status")
def v3_debug_mapa_status_pedidos(request: Request, numeros: str):
    _ensure_v3_debug_allowed(request)

    raw_numbers = [x.strip() for x in str(numeros or "").split(",") if x.strip()]
    parsed_numbers = []

    for raw in raw_numbers:
        try:
            parsed_numbers.append(int(raw))
        except Exception:
            continue

    parsed_numbers = parsed_numbers[:50]

    if not parsed_numbers:
        raise HTTPException(
            status_code=400,
            detail="Informe pelo menos um número de pedido em ?numeros=22560,23942",
        )

    client = _tiny_v3_client()
    resultados = []

    for numero in parsed_numbers:
        item_result = {
            "ok": False,
            "numeroPedido": numero,
            "idV3": None,
            "situacao": None,
            "situacaoListagem": None,
            "situacaoDetalhe": None,
            "dataFaturamento": None,
            "idNotaFiscal": None,
            "cliente": None,
            "vendedor": None,
            "pagamento": None,
            "meioPagamento": None,
            "erro": None,
        }

        try:
            list_resp = client.listar_pedidos(params={
                "numero": int(numero),
                "limit": 20,
                "offset": 0,
            })

            data = list_resp.get("data") or {}
            itens = data.get("itens") or []

            if not itens:
                item_result["erro"] = f"Nenhum pedido encontrado na API V3 com numeroPedido={numero}."
                resultados.append(item_result)
                continue

            first = itens[0] or {}
            id_v3 = first.get("id")

            if not id_v3:
                item_result["erro"] = f"Pedido numeroPedido={numero} encontrado, mas sem campo id no retorno V3."
                resultados.append(item_result)
                continue

            detail_resp = client.obter_pedido(int(id_v3))
            detalhe = detail_resp.get("data") or {}

            pagamento = detalhe.get("pagamento") or {}
            forma_pagamento = pagamento.get("formaPagamento") or {}
            meio_pagamento = pagamento.get("meioPagamento") or {}
            cliente_obj = detalhe.get("cliente") or {}
            vendedor_obj = detalhe.get("vendedor") or {}

            situacao_listagem = first.get("situacao")
            situacao_detalhe = detalhe.get("situacao")

            item_result.update({
                "ok": True,
                "numeroPedido": detalhe.get("numeroPedido") or numero,
                "idV3": int(id_v3),
                "situacao": situacao_detalhe,
                "situacaoListagem": situacao_listagem,
                "situacaoDetalhe": situacao_detalhe,
                "dataFaturamento": detalhe.get("dataFaturamento"),
                "idNotaFiscal": detalhe.get("idNotaFiscal"),
                "cliente": cliente_obj.get("nome"),
                "vendedor": vendedor_obj.get("nome"),
                "pagamento": forma_pagamento.get("nome"),
                "meioPagamento": meio_pagamento.get("nome"),
                "valorTotalPedido": detalhe.get("valorTotalPedido"),
                "valorFrete": detalhe.get("valorFrete"),
                "valorOutrasDespesas": detalhe.get("valorOutrasDespesas"),
            })

            resultados.append(item_result)

        except Exception as e:
            item_result["erro"] = str(e)[:1000]
            resultados.append(item_result)

    return jsonable_encoder({
        "ok": True,
        "dataset": DATASET_ID,
        "total_solicitado": len(parsed_numbers),
        "resultados": resultados,
        "mapa_inicial_situacoes": {
            "1": "Faturado - confirmado",
            "2": "Cancelado - confirmado",
            "4": "Preparando Envio - confirmado",
            "7": "Pronto para Envio - confirmado",
            "0": "Em Aberto - pendente confirmar",
            "3": "Aprovado - pendente confirmar",
        },
    })


@app.get("/api/v3-debug/pedidos/por-numero/{numero}")
@app.get("/v3-debug/pedidos/por-numero/{numero}")
def v3_debug_get_pedido_por_numero(numero: int, request: Request):
    _ensure_v3_debug_allowed(request)

    try:
        list_resp = _tiny_v3_client().listar_pedidos(params={
            "numero": int(numero),
            "limit": 20,
            "offset": 0,
        })

        data = list_resp.get("data") or {}
        itens = data.get("itens") or []

        if not itens:
            raise HTTPException(
                status_code=404,
                detail=f"Nenhum pedido encontrado na API V3 com numeroPedido={numero}.",
            )

        first = itens[0] or {}
        id_v3 = first.get("id")

        if not id_v3:
            raise HTTPException(
                status_code=502,
                detail=f"Pedido numeroPedido={numero} encontrado, mas sem campo id no retorno V3.",
            )

        detail_resp = _tiny_v3_client().obter_pedido(int(id_v3))

        return jsonable_encoder({
            "ok": True,
            "dataset": DATASET_ID,
            "numero_pedido": int(numero),
            "id_v3": int(id_v3),
            "listagem": list_resp,
            "detalhe": detail_resp,
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar pedido por número na API V3: {str(e)[:1500]}",
        )


@app.get("/api/v3-debug/pedidos/{id_pedido}")
@app.get("/v3-debug/pedidos/{id_pedido}")
def v3_debug_get_pedido(id_pedido: int, request: Request):
    _ensure_v3_debug_allowed(request)

    try:
        resp = _tiny_v3_client().obter_pedido(int(id_pedido))
        return jsonable_encoder({
            "ok": True,
            "dataset": DATASET_ID,
            "id_pedido": int(id_pedido),
            "tiny_v3": resp,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar pedido na API V3: {str(e)[:1500]}",
        )


def _v3_separacao_status_label(situacao: Any) -> str:
    try:
        code = int(situacao)
    except Exception:
        return "Desconhecido"

    return {
        1: "Aguardando Separação",
        4: "Em Separação",
        2: "Separada",
        3: "Embalada",
    }.get(code, "Desconhecido")


@app.get("/api/v3-debug/separacoes/mapa")
@app.get("/v3-debug/separacoes/mapa")
def v3_debug_mapa_separacoes(
    request: Request,
    numeros: str,
    dataInicial: Optional[str] = None,
    dataFinal: Optional[str] = None,
    limit: int = 100,
):
    _ensure_v3_debug_allowed(request)

    raw_numbers = [x.strip() for x in str(numeros or "").split(",") if x.strip()]
    parsed_numbers: List[int] = []

    for raw in raw_numbers:
        try:
            parsed_numbers.append(int(raw))
        except Exception:
            continue

    parsed_numbers = parsed_numbers[:50]

    if not parsed_numbers:
        raise HTTPException(
            status_code=400,
            detail="Informe pelo menos um número de pedido em ?numeros=22560,23942",
        )

    numeros_set = {int(n) for n in parsed_numbers}
    client = _tiny_v3_client()

    params: Dict[str, Any] = {
        "limit": max(1, min(int(limit or 100), 100)),
        "offset": 0,
        "orderBy": "desc",
    }

    if dataInicial:
        params["dataInicial"] = dataInicial
    if dataFinal:
        params["dataFinal"] = dataFinal

    encontrados: Dict[int, Dict[str, Any]] = {}
    bruto_paginas: List[Dict[str, Any]] = []

    # Faz poucas páginas para diagnóstico, sem varrer o Tiny inteiro.
    # Se precisarmos, depois aumentamos ou filtramos por data.
    max_pages = 5

    for page in range(max_pages):
        params["offset"] = page * params["limit"]
        resp = client.listar_separacoes(params=params)
        data = resp.get("data") or {}
        itens = data.get("itens") or []
        paginacao = data.get("paginacao") or {}

        bruto_paginas.append({
            "page": page + 1,
            "offset": params["offset"],
            "limit": params["limit"],
            "total": paginacao.get("total"),
            "qtd_itens": len(itens),
        })

        for sep in itens:
            venda = sep.get("venda") or {}
            numero_venda = venda.get("numero")

            try:
                numero_venda_int = int(numero_venda)
            except Exception:
                continue

            if numero_venda_int in numeros_set and numero_venda_int not in encontrados:
                encontrados[numero_venda_int] = sep

        if len(encontrados) >= len(numeros_set):
            break

        if not itens or len(itens) < params["limit"]:
            break

    resultados = []

    for numero in parsed_numbers:
        sep = encontrados.get(int(numero))

        item_result = {
            "ok": False,
            "numeroPedido": int(numero),
            "separacao": {
                "found": False,
                "id": None,
                "situacao": None,
                "statusLabel": None,
                "dataCriacao": None,
                "dataSeparacao": None,
                "dataCheckout": None,
                "idOrigemVinc": None,
                "objOrigemVinc": None,
            },
            "venda": None,
            "notaFiscal": None,
            "cliente": None,
            "formaEnvio": None,
            "detalhe": None,
            "erro": None,
        }

        if not sep:
            item_result["erro"] = "Separação não encontrada na V3 nas páginas consultadas."
            resultados.append(item_result)
            continue

        sep_id = sep.get("id")
        situacao = sep.get("situacao")

        item_result["ok"] = True
        item_result["separacao"].update({
            "found": True,
            "id": sep_id,
            "situacao": situacao,
            "statusLabel": _v3_separacao_status_label(situacao),
            "dataCriacao": sep.get("dataCriacao"),
            "dataSeparacao": sep.get("dataSeparacao"),
            "dataCheckout": sep.get("dataCheckout"),
            "idOrigemVinc": sep.get("idOrigemVinc"),
            "objOrigemVinc": sep.get("objOrigemVinc"),
        })
        item_result["venda"] = sep.get("venda")
        item_result["notaFiscal"] = sep.get("notaFiscal")
        item_result["cliente"] = sep.get("cliente")
        item_result["formaEnvio"] = sep.get("formaEnvio")

        if sep_id:
            try:
                detail_resp = client.obter_separacao(int(sep_id))
                item_result["detalhe"] = detail_resp
            except Exception as e:
                item_result["erro"] = f"Separação encontrada, mas falhou ao obter detalhe: {str(e)[:1000]}"

        resultados.append(item_result)

    return jsonable_encoder({
        "ok": True,
        "dataset": DATASET_ID,
        "read_only": True,
        "params": {
            "numeros": parsed_numbers,
            "dataInicial": dataInicial,
            "dataFinal": dataFinal,
            "limit": params["limit"],
            "max_pages": max_pages,
        },
        "paginas_consultadas": bruto_paginas,
        "resultados": resultados,
        "mapa_situacoes_separacao": {
            "1": "Aguardando Separação",
            "4": "Em Separação",
            "2": "Separada",
            "3": "Embalada",
        },
        "observacao": "Consulta somente leitura. Nenhuma separação foi alterada.",
    })




def _v3_find_separacao_by_order_number(
    client: TinyV3Client,
    numero_pedido: int,
    *,
    dataInicial: Optional[str] = None,
    dataFinal: Optional[str] = None,
    limit: int = 100,
    max_pages: int = 10,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "limit": max(1, min(int(limit or 100), 100)),
        "offset": 0,
        "orderBy": "desc",
    }

    if dataInicial:
        params["dataInicial"] = dataInicial
    if dataFinal:
        params["dataFinal"] = dataFinal

    paginas = []

    for page in range(max(1, int(max_pages or 10))):
        params["offset"] = page * params["limit"]
        resp = client.listar_separacoes(params=params)
        data = resp.get("data") or {}
        itens = data.get("itens") or []
        paginacao = data.get("paginacao") or {}

        paginas.append({
            "page": page + 1,
            "offset": params["offset"],
            "limit": params["limit"],
            "total": paginacao.get("total"),
            "qtd_itens": len(itens),
        })

        for sep in itens:
            venda = sep.get("venda") or {}
            try:
                numero_venda = int(venda.get("numero"))
            except Exception:
                continue

            if numero_venda == int(numero_pedido):
                return {
                    "found": True,
                    "separacao": sep,
                    "paginas_consultadas": paginas,
                    "params": dict(params),
                }

        if not itens or len(itens) < params["limit"]:
            break

    return {
        "found": False,
        "separacao": None,
        "paginas_consultadas": paginas,
        "params": dict(params),
    }



# ============================================================
# Tiny/Olist V3 - camada interna de sincronismo da separação
# ============================================================

def _tiny_v3_separation_sync_enabled() -> bool:
    return os.getenv("ENABLE_TINY_V3_SEPARATION_SYNC", "false").strip().lower() in ("1", "true", "yes", "on", "sim")


def _sync_tiny_v3_separation_by_order_number(
    *,
    numero_pedido: int,
    target_situacao: int,
    dataInicial: Optional[str] = None,
    dataFinal: Optional[str] = None,
    dry_run: bool = True,
    confirm: bool = False,
    max_pages: int = 10,
    updated_by: str = "system",
) -> Dict[str, Any]:
    if int(target_situacao) not in (1, 2, 3, 4):
        raise HTTPException(
            status_code=400,
            detail="Situação inválida. Use 1=Aguardando Separação, 2=Separada, 3=Embalada, 4=Em Separação.",
        )

    client = _tiny_v3_client()

    found = _v3_find_separacao_by_order_number(
        client,
        int(numero_pedido),
        dataInicial=dataInicial,
        dataFinal=dataFinal,
        max_pages=max_pages,
    )

    base_result: Dict[str, Any] = {
        "ok": False,
        "provider": "tiny_v3",
        "operation": "sync_separation_by_order_number",
        "dataset": DATASET_ID,
        "enabled": _tiny_v3_separation_sync_enabled(),
        "dry_run": bool(dry_run),
        "confirm": bool(confirm),
        "updated_by": updated_by,
        "numero_pedido": int(numero_pedido),
        "requested_situacao": int(target_situacao),
        "requested_statusLabel": _v3_separacao_status_label(int(target_situacao)),
        "found": False,
        "id_separacao": None,
        "before": None,
        "updated": False,
        "update_response": None,
        "after": None,
        "paginas_consultadas": found.get("paginas_consultadas"),
        "erro": None,
        "observacao": None,
    }

    if not found.get("found"):
        base_result["erro"] = "Separação oficial não encontrada na V3 para este número de pedido nas páginas consultadas."
        base_result["observacao"] = "Fluxo local deve continuar sem quebrar. Registrar alerta para revisão manual."
        return base_result

    sep = found.get("separacao") or {}
    id_separacao = sep.get("id")

    if not id_separacao:
        base_result["erro"] = "Separação encontrada, mas sem campo id no retorno V3."
        base_result["observacao"] = "Fluxo local deve continuar sem quebrar. Registrar alerta para revisão manual."
        return base_result

    before_resp = client.obter_separacao(int(id_separacao))
    before_data = before_resp.get("data") or {}
    before_situacao = before_data.get("situacao")

    base_result.update({
        "ok": True,
        "found": True,
        "id_separacao": int(id_separacao),
        "before": {
            "situacao": before_situacao,
            "statusLabel": _v3_separacao_status_label(before_situacao),
            "venda": before_data.get("venda"),
            "cliente": before_data.get("cliente"),
            "dataCriacao": before_data.get("dataCriacao"),
            "dataSeparacao": before_data.get("dataSeparacao"),
            "dataCheckout": before_data.get("dataCheckout"),
        },
        "observacao": "Dry-run: nenhuma separação foi alterada.",
    })

    if dry_run:
        return base_result

    if not _tiny_v3_separation_sync_enabled():
        base_result["ok"] = False
        base_result["erro"] = "Sincronismo V3 de separação está desativado por ENABLE_TINY_V3_SEPARATION_SYNC."
        base_result["observacao"] = "Para alterar de verdade, habilite ENABLE_TINY_V3_SEPARATION_SYNC=true no beta."
        return base_result

    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Para alterar de verdade, envie dry_run=false&confirm=true.",
        )

    update_resp = client.alterar_situacao_separacao(int(id_separacao), int(target_situacao))
    after_resp = client.obter_separacao(int(id_separacao))
    after_data = after_resp.get("data") or {}

    base_result["updated"] = True
    base_result["update_response"] = update_resp
    base_result["after"] = {
        "situacao": after_data.get("situacao"),
        "statusLabel": _v3_separacao_status_label(after_data.get("situacao")),
        "venda": after_data.get("venda"),
        "cliente": after_data.get("cliente"),
        "dataCriacao": after_data.get("dataCriacao"),
        "dataSeparacao": after_data.get("dataSeparacao"),
        "dataCheckout": after_data.get("dataCheckout"),
    }
    base_result["observacao"] = "Alteração executada na API V3 do Tiny/Olist."

    return base_result


@app.post("/api/v3/separacao/sync-por-pedido/{numero_pedido}")
@app.post("/v3/separacao/sync-por-pedido/{numero_pedido}")
def v3_sync_separacao_por_pedido_core(
    numero_pedido: int,
    request: Request,
    situacao: int,
    dataInicial: Optional[str] = None,
    dataFinal: Optional[str] = None,
    dry_run: bool = True,
    confirm: bool = False,
    max_pages: int = 10,
):
    _ensure_v3_debug_allowed(request)

    updated_by = getattr(request.state, "user_email", "") or "admin"

    try:
        result = _sync_tiny_v3_separation_by_order_number(
            numero_pedido=int(numero_pedido),
            target_situacao=int(situacao),
            dataInicial=dataInicial,
            dataFinal=dataFinal,
            dry_run=bool(dry_run),
            confirm=bool(confirm),
            max_pages=int(max_pages or 10),
            updated_by=updated_by,
        )
        return jsonable_encoder(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falha no sincronismo core da separação V3: {str(e)[:1500]}",
        )




@app.post("/api/v3-debug/separacoes/sync-por-pedido/{numero_pedido}")
@app.post("/v3-debug/separacoes/sync-por-pedido/{numero_pedido}")
def v3_debug_sync_separacao_por_pedido(
    numero_pedido: int,
    request: Request,
    situacao: int,
    dataInicial: Optional[str] = None,
    dataFinal: Optional[str] = None,
    dry_run: bool = True,
    confirm: bool = False,
    max_pages: int = 10,
):
    _ensure_v3_debug_allowed(request)

    if int(situacao) not in (1, 2, 3, 4):
        raise HTTPException(
            status_code=400,
            detail="Situação inválida. Use 1=Aguardando Separação, 2=Separada, 3=Embalada, 4=Em Separação.",
        )

    client = _tiny_v3_client()

    try:
        found = _v3_find_separacao_by_order_number(
            client,
            int(numero_pedido),
            dataInicial=dataInicial,
            dataFinal=dataFinal,
            max_pages=max_pages,
        )

        if not found.get("found"):
            return jsonable_encoder({
                "ok": False,
                "dataset": DATASET_ID,
                "read_only": bool(dry_run),
                "numero_pedido": int(numero_pedido),
                "requested_situacao": int(situacao),
                "requested_statusLabel": _v3_separacao_status_label(int(situacao)),
                "found": False,
                "updated": False,
                "erro": "Separação oficial não encontrada na V3 para este número de pedido nas páginas consultadas.",
                "paginas_consultadas": found.get("paginas_consultadas"),
                "observacao": "Fluxo local do ERP deve continuar sem quebrar. Registrar alerta para revisão manual.",
            })

        sep = found.get("separacao") or {}
        id_separacao = sep.get("id")

        if not id_separacao:
            raise HTTPException(
                status_code=502,
                detail="Separação encontrada, mas sem campo id no retorno V3.",
            )

        before_resp = client.obter_separacao(int(id_separacao))
        before_data = before_resp.get("data") or {}
        before_situacao = before_data.get("situacao")

        result = {
            "ok": True,
            "dataset": DATASET_ID,
            "numero_pedido": int(numero_pedido),
            "id_separacao": int(id_separacao),
            "dry_run": bool(dry_run),
            "confirm": bool(confirm),
            "requested_situacao": int(situacao),
            "requested_statusLabel": _v3_separacao_status_label(int(situacao)),
            "found": True,
            "before": {
                "situacao": before_situacao,
                "statusLabel": _v3_separacao_status_label(before_situacao),
                "venda": before_data.get("venda"),
                "cliente": before_data.get("cliente"),
                "dataCriacao": before_data.get("dataCriacao"),
                "dataSeparacao": before_data.get("dataSeparacao"),
                "dataCheckout": before_data.get("dataCheckout"),
            },
            "updated": False,
            "update_response": None,
            "after": None,
            "paginas_consultadas": found.get("paginas_consultadas"),
            "observacao": "Dry-run: nenhuma separação foi alterada.",
        }

        if dry_run:
            return jsonable_encoder(result)

        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Para alterar de verdade, envie dry_run=false&confirm=true.",
            )

        update_resp = client.alterar_situacao_separacao(int(id_separacao), int(situacao))
        after_resp = client.obter_separacao(int(id_separacao))
        after_data = after_resp.get("data") or {}

        result["updated"] = True
        result["update_response"] = update_resp
        result["after"] = {
            "situacao": after_data.get("situacao"),
            "statusLabel": _v3_separacao_status_label(after_data.get("situacao")),
            "venda": after_data.get("venda"),
            "cliente": after_data.get("cliente"),
            "dataCriacao": after_data.get("dataCriacao"),
            "dataSeparacao": after_data.get("dataSeparacao"),
            "dataCheckout": after_data.get("dataCheckout"),
        }
        result["observacao"] = "Alteração executada na API V3 do Tiny/Olist por número de pedido."

        return jsonable_encoder(result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao sincronizar separação V3 por número de pedido: {str(e)[:1500]}",
        )




@app.post("/api/v3-debug/separacoes/{id_separacao}/situacao")
@app.post("/v3-debug/separacoes/{id_separacao}/situacao")
def v3_debug_update_situacao_separacao(
    id_separacao: int,
    request: Request,
    situacao: int,
    dry_run: bool = True,
    confirm: bool = False,
):
    _ensure_v3_debug_allowed(request)

    if int(situacao) not in (1, 2, 3, 4):
        raise HTTPException(
            status_code=400,
            detail="Situação inválida. Use 1=Aguardando Separação, 2=Separada, 3=Embalada, 4=Em Separação.",
        )

    client = _tiny_v3_client()

    try:
        before_resp = client.obter_separacao(int(id_separacao))
        before_data = before_resp.get("data") or {}
        before_situacao = before_data.get("situacao")

        result = {
            "ok": True,
            "dataset": DATASET_ID,
            "read_before": True,
            "dry_run": bool(dry_run),
            "confirm": bool(confirm),
            "id_separacao": int(id_separacao),
            "requested_situacao": int(situacao),
            "requested_statusLabel": _v3_separacao_status_label(int(situacao)),
            "before": {
                "situacao": before_situacao,
                "statusLabel": _v3_separacao_status_label(before_situacao),
                "venda": before_data.get("venda"),
                "cliente": before_data.get("cliente"),
                "dataCriacao": before_data.get("dataCriacao"),
                "dataSeparacao": before_data.get("dataSeparacao"),
                "dataCheckout": before_data.get("dataCheckout"),
            },
            "updated": False,
            "update_response": None,
            "after": None,
            "observacao": "Dry-run: nenhuma separação foi alterada.",
        }

        if dry_run:
            return jsonable_encoder(result)

        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Para alterar de verdade, envie dry_run=false&confirm=true.",
            )

        update_resp = client.alterar_situacao_separacao(int(id_separacao), int(situacao))
        after_resp = client.obter_separacao(int(id_separacao))
        after_data = after_resp.get("data") or {}

        result["updated"] = True
        result["update_response"] = update_resp
        result["after"] = {
            "situacao": after_data.get("situacao"),
            "statusLabel": _v3_separacao_status_label(after_data.get("situacao")),
            "venda": after_data.get("venda"),
            "cliente": after_data.get("cliente"),
            "dataCriacao": after_data.get("dataCriacao"),
            "dataSeparacao": after_data.get("dataSeparacao"),
            "dataCheckout": after_data.get("dataCheckout"),
        }
        result["observacao"] = "Alteração executada na API V3 do Tiny/Olist."

        return jsonable_encoder(result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao alterar situação da separação V3: {str(e)[:1500]}",
        )




@app.get("/api/v3-debug/separacoes")
@app.get("/v3-debug/separacoes")
def v3_debug_list_separacoes(request: Request, idPedido: Optional[int] = None):
    _ensure_v3_debug_allowed(request)

    params = {}
    if idPedido is not None:
        params["idPedido"] = int(idPedido)

    try:
        resp = _tiny_v3_client().listar_separacoes(params=params)
        return jsonable_encoder({
            "ok": True,
            "dataset": DATASET_ID,
            "params": params,
            "tiny_v3": resp,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar separações na API V3: {str(e)[:1500]}",
        )






def _load_seller_email_map() -> Dict[str, List[Dict[str, Any]]]:
    raw = os.getenv("SELLER_EMAIL_MAP_JSON", "").strip()
    if not raw:
        raw_b64 = os.getenv("SELLER_EMAIL_MAP_JSON_B64", "").strip()
        if raw_b64:
            try:
                import base64 as _b64
                raw = _b64.b64decode(raw_b64).decode("utf-8").strip()
            except Exception:
                raw = ""

    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except Exception:
        return {}

    if not isinstance(parsed, dict):
        return {}

    out: Dict[str, List[Dict[str, Any]]] = {}
    for email, arr in parsed.items():
        email_norm = str(email or "").strip().lower()
        if not email_norm:
            continue
        if not isinstance(arr, list):
            continue

        rows = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            try:
                seller_id = int(item.get("seller_id"))
            except Exception:
                continue
            seller_name = str(item.get("seller_name") or "").strip()
            if not seller_name:
                continue
            rows.append({
                "seller_id": seller_id,
                "seller_id": seller_id,
            })

        if rows:
            out[email_norm] = rows

    return out


def _seller_bindings_for_email(email: str) -> List[Dict[str, Any]]:
    email_norm = str(email or "").strip().lower()
    mapping = _load_seller_email_map()
    items = list(mapping.get(email_norm) or [])
    items.sort(key=lambda x: _norm_person_name_v2(x.get("seller_name")))
    return items


def _seller_bindings_for_request(request: Request) -> List[Dict[str, Any]]:
    if _effective_is_admin(request):
        return _list_all_known_sellers_v2()
    return _seller_bindings_for_email(_effective_user_email(request))


def _seller_ids_for_request(request: Request) -> List[int]:
    ids = []
    for row in _seller_bindings_for_request(request):
        try:
            ids.append(int(row.get("seller_id")))
        except Exception:
            pass
    return ids


ENABLE_DEBUG_USER_EMAIL_OVERRIDE = os.getenv("ENABLE_DEBUG_USER_EMAIL_OVERRIDE", "false").strip().lower() in ("1", "true", "yes", "on")


def _debug_override_email(request: Request) -> str:
    if not ENABLE_DEBUG_USER_EMAIL_OVERRIDE:
        return ""
    if not _is_admin(request):
        return ""

    email = (
        request.query_params.get("debug_email")
        or request.headers.get("x-debug-user-email")
        or ""
    ).strip().lower()

    return email


def _effective_user_email(request: Request) -> str:
    return _debug_override_email(request) or _user_email(request)


def _effective_is_admin(request: Request) -> bool:
    if _debug_override_email(request):
        return False
    return _is_admin(request)


# Mapa e-mail -> apelidos de vendedor. Carregado do ambiente
# (SELLER_EMAIL_MAP_JSON / SELLER_EMAIL_MAP_JSON_B64); vazio por padrão.
SELLER_EMAIL_ALIASES = {}


def _norm_person_name(v: Any) -> str:
    return (
        str(v or "")
        .strip()
        .lower()
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def _seller_aliases_for_email(email: str) -> List[str]:
    return SELLER_EMAIL_ALIASES.get((email or "").strip().lower(), [])


def _resolve_sellers_for_email(email: str) -> List[Dict[str, Any]]:
    aliases = _seller_aliases_for_email(email)
    if not aliases:
        return []

    found: Dict[int, Dict[str, Any]] = {}

    for alias in aliases:
        try:
            r = tiny.pesquisar_vendedores(pesquisa=alias, pagina=1)
        except Exception:
            continueloud 

        vendedores = r.get("vendedores") or []
        alias_norm = _norm_person_name(alias)

        for item in vendedores:
            v = item.get("vendedor", item) if isinstance(item, dict) else {}
            try:
                sid = int(v.get("id"))
            except Exception:
                continue

            nome = str(v.get("nome") or "").strip()
            codigo = str(v.get("codigo") or "").strip()
            nome_norm = _norm_person_name(nome)

            if nome_norm == alias_norm:
                found[sid] = {"seller_id": sid, "seller_name": nome, "seller_code": codigo}

    # fallback suave por nome salvo em quotes, caso Tiny não devolva algum alias
    if len(found) < len(aliases):
        sql = f"""
        SELECT DISTINCT
          seller_id,
          seller_name
        FROM {_table('quotes')}
        WHERE seller_name IS NOT NULL
        """
        rows = list(bq.query(sql).result())
        for row in rows:
            sid = int(row["seller_id"])
            nome = str(row["seller_name"] or "").strip()
            nome_norm = _norm_person_name(nome)
            if any(nome_norm == _norm_person_name(alias) for alias in aliases):
                found.setdefault(sid, {"seller_id": sid, "seller_name": nome, "seller_code": ""})

    items = list(found.values())
    items.sort(key=lambda x: _norm_person_name(x.get("seller_name")))
    return items


def _list_all_known_sellers() -> List[Dict[str, Any]]:
    sql = f"""
    SELECT DISTINCT
      seller_id,
      seller_name
    FROM {_table('quotes')}
    WHERE seller_id IS NOT NULL
      AND seller_name IS NOT NULL
      AND TRIM(seller_name) != ''
    ORDER BY seller_name
    """
    rows = list(bq.query(sql).result())
    items = []
    for row in rows:
        try:
            sid = int(row["seller_id"])
        except Exception:
            continue
        items.append({
            "seller_id": sid,
            "seller_name": str(row["seller_name"] or "").strip(),
            "seller_code": "",
        })
    return items


@app.get("/api/seller/context")
@app.get("/seller/context")
def seller_context(request: Request):
    email = _effective_user_email(request)
    is_admin = _effective_is_admin(request)
    sellers = _seller_bindings_for_request(request)
    seller_ids = [int(x["seller_id"]) for x in sellers if x.get("seller_id") is not None]

    return {
        "email": email,
        "is_admin": is_admin,
        "mapping_source": "SELLER_EMAIL_MAP_JSON",
        "sellers": sellers,
        "seller_ids": seller_ids,
        "primary_seller": sellers[0] if sellers else None,
    }


@app.get("/api/seller/client-wallet")
@app.get("/seller/client-wallet")
def seller_client_wallet(request: Request, limit: int = Query(default=300, ge=1, le=1000)):
    email = _effective_user_email(request)
    is_admin = _effective_is_admin(request)
    sellers = _seller_bindings_for_request(request)
    seller_ids = [int(x["seller_id"]) for x in sellers if x.get("seller_id") is not None]

    if not seller_ids:
        return {
            "email": email,
            "is_admin": is_admin,
            "sellers": sellers,
            "items": [],
            "count": 0,
        }

    sql = f"""
    SELECT
      q.client_id,
      COALESCE(
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.nome'),
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.name')
      ) AS client_name,
      COALESCE(
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpf_cnpj'),
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpfCnpj')
      ) AS client_doc,
      COALESCE(JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cidade'), '') AS city,
      COALESCE(JSON_EXTRACT_SCALAR(q.client_snapshot, '$.uf'), '') AS uf,
      STRING_AGG(DISTINCT COALESCE(q.seller_name, ''), ' | ' ORDER BY COALESCE(q.seller_name, '')) AS seller_names,
      MAX(q.created_at) AS last_quote_at,
      COUNT(1) AS quotes_count,
      ROUND(SUM(COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(q.totals, '$.net') AS FLOAT64), 0)), 2) AS total_quoted
    FROM {_table('quotes')} q
    WHERE q.seller_id IN UNNEST(@seller_ids)
    GROUP BY client_id, client_name, client_doc, city, uf
    ORDER BY last_quote_at DESC, quotes_count DESC
    LIMIT @limit
    """

    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("seller_ids", "INT64", seller_ids),
            bigquery.ScalarQueryParameter("limit", "INT64", int(limit)),
        ]
    )

    rows = list(bq.query(sql, job_config=cfg).result())
    items = []
    for row in rows:
        items.append({
            "client_id": int(row["client_id"]) if row["client_id"] is not None else None,
            "client_name": row["client_name"] or "",
            "client_doc": row["client_doc"] or "",
            "city": row["city"] or "",
            "uf": row["uf"] or "",
            "seller_names": row["seller_names"] or "",
            "last_quote_at": row["last_quote_at"].isoformat() if row["last_quote_at"] else None,
            "quotes_count": int(row["quotes_count"] or 0),
            "total_quoted": float(row["total_quoted"] or 0),
        })

    return {
        "email": email,
        "is_admin": is_admin,
        "sellers": sellers,
        "seller_ids": seller_ids,
        "items": items,
        "count": len(items),
    }



# Mapa e-mail -> apelidos de vendedor (v2). Carregado do ambiente
# (SELLER_EMAIL_MAP_JSON / SELLER_EMAIL_MAP_JSON_B64); vazio por padrão.
SELLER_EMAIL_ALIASES_V2 = {}


def _norm_person_name_v2(v: Any) -> str:
    return (
        str(v or "")
        .strip()
        .lower()
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def _seller_aliases_for_email_v2(email: str) -> List[str]:
    return SELLER_EMAIL_ALIASES_V2.get((email or "").strip().lower(), [])


def _list_all_known_sellers_v2() -> List[Dict[str, Any]]:
    sql = f"""
    SELECT DISTINCT
      seller_id,
      seller_name
    FROM {_table('quotes')}
    WHERE seller_name IS NOT NULL
      AND TRIM(seller_name) != ''
    ORDER BY seller_name
    """
    rows = list(bq.query(sql).result())

    found = {}

    for row in rows:
        try:
            sid = int(row["seller_id"]) if row["seller_id"] is not None else None
        except Exception:
            sid = None

        name = str(row["seller_name"] or "").strip()
        if name:
            found[f"{sid}:{name}"] = {
                "seller_id": sid,
                "seller_name": name,
            }

    for arr in SELLER_EMAIL_ALIASES_V2.values():
        for name in (arr or []):
            name = str(name or "").strip()
            if name:
                found.setdefault(f"None:{name}", {
                    "seller_id": None,
                    "seller_name": name,
                })

    items = list(found.values())
    items.sort(key=lambda x: _norm_person_name_v2(x.get("seller_name")))
    return items


def _resolve_sellers_for_email_v2(email: str) -> List[Dict[str, Any]]:
    aliases = _seller_aliases_for_email_v2(email)
    if not aliases:
        return []

    sql = f"""
    SELECT DISTINCT
      seller_id,
      seller_name
    FROM {_table('quotes')}
    WHERE seller_name IS NOT NULL
      AND TRIM(seller_name) != ''
    """
    rows = list(bq.query(sql).result())

    found: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        try:
            sid = int(row["seller_id"]) if row["seller_id"] is not None else None
        except Exception:
            sid = None
        seller_name = str(row["seller_name"] or "").strip()
        norm_name = _norm_person_name_v2(seller_name)
        for alias in aliases:
            if norm_name == _norm_person_name_v2(alias):
                found[f"{sid}:{seller_name}"] = {
                    "seller_id": sid,
                    "seller_name": seller_name,
                }

    items = list(found.values())
    items.sort(key=lambda x: _norm_person_name_v2(x.get("seller_name")))
    return items


@app.get("/api/seller/order-wallet")
@app.get("/seller/order-wallet")
def seller_order_wallet(
    request: Request,
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
):
    email = _effective_user_email(request)
    is_admin = _effective_is_admin(request)

    today = dt.datetime.now().date()
    if not start_date:
        start_date = "2000-01-01"
    if not end_date:
        end_date = today.isoformat()

    try:
        start_dt = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Período inválido. Use YYYY-MM-DD.")

    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="end_date não pode ser menor que start_date.")

    sellers = _seller_bindings_for_request(request)
    seller_ids = [int(x["seller_id"]) for x in sellers if x.get("seller_id") is not None]

    if is_admin:
        seller_filter_sql = ""
        seller_params = []
    else:
        if not seller_ids:
            return {
                "email": email,
                "is_admin": is_admin,
                "sellers": sellers,
                "items": [],
                "count": 0,
                "start_date": start_date,
                "end_date": end_date,
            }
        seller_filter_sql = "AND q.seller_id IN UNNEST(@seller_ids)"
        seller_params = [bigquery.ArrayQueryParameter("seller_ids", "INT64", seller_ids)]

    sql = f"""
    WITH orders_base AS (
      SELECT
        q.quote_id,
        q.tiny_order_id,
        q.tiny_order_number,
        q.seller_id,
        COALESCE(NULLIF(TRIM(q.seller_name), ''), 'Sem vendedor') AS seller_name,
        COALESCE(
          JSON_EXTRACT_SCALAR(q.client_snapshot, '$.nome'),
          JSON_EXTRACT_SCALAR(q.client_snapshot, '$.name'),
          ''
        ) AS client_name,
        COALESCE(
          JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpf_cnpj'),
          JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpfCnpj'),
          ''
        ) AS client_doc,
        COALESCE(JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cidade'), '') AS city,
        COALESCE(JSON_EXTRACT_SCALAR(q.client_snapshot, '$.uf'), '') AS uf,
        COALESCE(
          SAFE_CAST(JSON_EXTRACT_SCALAR(q.totals, '$.net') AS FLOAT64),
          SAFE_CAST(JSON_EXTRACT_SCALAR(q.totals, '$.total') AS FLOAT64),
          SAFE_CAST(JSON_EXTRACT_SCALAR(q.totals, '$.gross') AS FLOAT64),
          0
        ) AS total_value,
        DATE(COALESCE(q.updated_at, q.created_at)) AS order_date,
        COALESCE(q.updated_at, q.created_at) AS order_ts
      FROM {_table('quotes')} q
      WHERE q.tiny_order_id IS NOT NULL
        AND DATE(COALESCE(q.updated_at, q.created_at)) BETWEEN @start_date AND @end_date
        {seller_filter_sql}
    ),
    wallet AS (
      SELECT
        client_name,
        client_doc,
        city,
        uf,
        STRING_AGG(DISTINCT seller_name, ' | ' ORDER BY seller_name) AS seller_names,
        COUNT(DISTINCT tiny_order_id) AS orders_count,
        ROUND(SUM(total_value), 2) AS total_orders,
        MAX(order_ts) AS last_order_at,
        DATE_DIFF(CURRENT_DATE(), MAX(order_date), DAY) AS days_without_buy
      FROM orders_base
      GROUP BY client_name, client_doc, city, uf
    )
    SELECT *
    FROM wallet
    ORDER BY last_order_at DESC, orders_count DESC
    LIMIT @limit
    """

    params = [
        bigquery.ScalarQueryParameter("start_date", "DATE", start_dt),
        bigquery.ScalarQueryParameter("end_date", "DATE", end_dt),
        bigquery.ScalarQueryParameter("limit", "INT64", int(limit)),
        *seller_params,
    ]

    cfg = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(bq.query(sql, job_config=cfg).result())

    items = []
    for row in rows:
        items.append({
            "client_name": row["client_name"] or "",
            "client_doc": row["client_doc"] or "",
            "city": row["city"] or "",
            "uf": row["uf"] or "",
            "seller_names": row["seller_names"] or "Sem vendedor",
            "orders_count": int(row["orders_count"] or 0),
            "total_orders": float(row["total_orders"] or 0),
            "last_order_at": row["last_order_at"].isoformat() if row["last_order_at"] else None,
            "days_without_buy": int(row["days_without_buy"] or 0),
        })

    seller_filter_options = {"Sem vendedor"}

    # vendedores vindos da resolução normal
    for s in sellers:
        name = str(s.get("seller_name") or "").strip()
        if name:
            seller_filter_options.add(name)

    # aliases mapeados manualmente no sistema
    for arr in SELLER_EMAIL_ALIASES_V2.values():
        for name in (arr or []):
            name = str(name or "").strip()
            if name:
                seller_filter_options.add(name)

    # nomes históricos já gravados no BigQuery
    try:
        sql_sellers = f"""
        SELECT DISTINCT seller_name
        FROM {_table('quotes')}
        WHERE seller_name IS NOT NULL
          AND TRIM(seller_name) != ''
        ORDER BY seller_name
        """
        for row in bq.query(sql_sellers).result():
            name = str(row["seller_name"] or "").strip()
            if name:
                seller_filter_options.add(name)
    except Exception:
        pass

    seller_filter_options = sorted(seller_filter_options, key=lambda x: _norm_person_name_v2(x))

    return {
        "email": email,
        "is_admin": is_admin,
        "sellers": sellers,
        "seller_filter_options": seller_filter_options,
        "items": items,
        "count": len(items),
        "start_date": start_date,
        "end_date": end_date,
    }



def _wallet_metrics_by_docs(docs: List[str]) -> Dict[str, Dict[str, Any]]:
    docs = [str(x or "").strip() for x in docs if str(x or "").strip()]
    if not docs:
        return {}

    sql = f"""
    WITH base AS (
      SELECT
        COALESCE(
          JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpf_cnpj'),
          JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpfCnpj'),
          ''
        ) AS client_doc,
        q.tiny_order_id,
        COALESCE(q.updated_at, q.created_at) AS order_ts,
        DATE(COALESCE(q.updated_at, q.created_at)) AS order_date,
        COALESCE(
          SAFE_CAST(JSON_EXTRACT_SCALAR(q.totals, '$.net') AS FLOAT64),
          SAFE_CAST(JSON_EXTRACT_SCALAR(q.totals, '$.total') AS FLOAT64),
          SAFE_CAST(JSON_EXTRACT_SCALAR(q.totals, '$.gross') AS FLOAT64),
          0
        ) AS total_value
      FROM {_table('quotes')} q
      WHERE q.tiny_order_id IS NOT NULL
    )
    SELECT
      client_doc,
      COUNT(DISTINCT tiny_order_id) AS orders_count,
      ROUND(SUM(total_value), 2) AS total_orders,
      MAX(order_ts) AS last_order_at,
      DATE_DIFF(CURRENT_DATE(), MAX(order_date), DAY) AS days_without_buy
    FROM base
    WHERE client_doc IN UNNEST(@docs)
    GROUP BY client_doc
    """

    rows = list(
        bq.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("docs", "STRING", docs),
                ]
            ),
        ).result()
    )

    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        doc = str(row["client_doc"] or "").strip()
        out[doc] = {
            "orders_count": int(row["orders_count"] or 0),
            "total_orders": float(row["total_orders"] or 0),
            "last_order_at": row["last_order_at"].isoformat() if row["last_order_at"] else None,
            "days_without_buy": int(row["days_without_buy"] or 0) if row["days_without_buy"] is not None else None,
        }
    return out


@app.get("/api/seller/tiny-wallet-live")
@app.get("/seller/tiny-wallet-live")
def seller_tiny_wallet_live(
    request: Request,
    q: str = Query(default=""),
    page_num: int = Query(default=1, ge=1, le=50),
):
    email = _user_email(request)
    is_admin = _is_admin(request)

    target_url = "https://erp.olist.com/contatos#/"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=OLIST_UI_HEADLESS,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context()
        page = context.new_page()

        try:
            _olist_login_if_needed(page, target_url)

            page.goto(target_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            print("WALLET_LIVE_DEBUG url:", page.url)
            try:
                print("WALLET_LIVE_DEBUG title:", page.title())
            except Exception as e:
                print("WALLET_LIVE_DEBUG title_error:", str(e))

            debug_selectors = [
                "table tbody tr",
                "table tr",
                "[role='row']",
                "main tr",
                "main [role='row']",
                "main li",
                "main .table-row",
                "main div",
            ]
            for sel in debug_selectors:
                try:
                    print("WALLET_LIVE_DEBUG count", sel, page.locator(sel).count())
                except Exception as e:
                    print("WALLET_LIVE_DEBUG count_error", sel, str(e))

            try:
                body_text = page.locator("body").inner_text()
                print("WALLET_LIVE_DEBUG body_head:", body_text[:3000])
            except Exception as e:
                print("WALLET_LIVE_DEBUG body_error:", str(e))

            if q and str(q).strip():
                search_input = page.locator('input[placeholder*="Pesquise por nome"], input[placeholder*="CPF/C"], input[type="search"]').first
                if search_input.count():
                    search_input.fill(str(q).strip())
                    page.wait_for_timeout(800)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(2200)

            if page_num > 1:
                for _ in range(page_num - 1):
                    next_btn = page.get_by_text("→", exact=True).first
                    if next_btn.count():
                        next_btn.click()
                        page.wait_for_timeout(1800)
                    else:
                        break

            rows = page.locator("table tbody tr")
            items = []

            total_rows = rows.count()
            for i in range(total_rows):
                row = rows.nth(i)
                tds = row.locator("td")
                if tds.count() < 5:
                    continue

                try:
                    name_block = tds.nth(1).inner_text().strip()
                except Exception:
                    name_block = ""

                try:
                    doc_block = tds.nth(2).inner_text().strip()
                except Exception:
                    doc_block = ""

                try:
                    city_block = tds.nth(3).inner_text().strip()
                except Exception:
                    city_block = ""

                try:
                    contact_block = tds.nth(4).inner_text().strip()
                except Exception:
                    contact_block = ""

                name_lines = [x.strip() for x in name_block.splitlines() if x.strip()]
                doc_lines = [x.strip() for x in doc_block.splitlines() if x.strip()]

                client_name = name_lines[0] if name_lines else ""
                client_fantasy = name_lines[1] if len(name_lines) > 1 else ""
                client_doc = doc_lines[0] if doc_lines else ""

                city = ""
                uf = ""
                if "/" in city_block:
                    parts = [x.strip() for x in city_block.split("/", 1)]
                    city = parts[0] if parts else ""
                    uf = parts[1] if len(parts) > 1 else ""
                else:
                    city = city_block.strip()

                items.append({
                    "client_name": client_name,
                    "client_fantasy": client_fantasy,
                    "client_doc": client_doc,
                    "city": city,
                    "uf": uf,
                    "contact": contact_block,
                })

            docs = [str(it.get("client_doc") or "").strip() for it in items]
            metrics_map = _wallet_metrics_by_docs(docs)

            enriched = []
            for it in items:
                doc = str(it.get("client_doc") or "").strip()
                m = metrics_map.get(doc, {})
                enriched.append({
                    **it,
                    "orders_count": int(m.get("orders_count") or 0),
                    "total_orders": float(m.get("total_orders") or 0),
                    "last_order_at": m.get("last_order_at"),
                    "days_without_buy": m.get("days_without_buy"),
                })

            return {
                "email": email,
                "is_admin": is_admin,
                "items": enriched,
                "page": page_num,
                "q": q,
                "count": len(enriched),
            }

        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass




@app.get("/api/routes-debug")
@app.get("/routes-debug")
def routes_debug():
    return {
        "seller_routes": sorted(
            list(
                {
                    getattr(r, "path", None)
                    for r in app.routes
                    if getattr(r, "path", None) and "seller" in getattr(r, "path", "")
                }
            )
        )
    }


@app.get("/me")
def me(request: Request):
    email = _effective_user_email(request)
    is_admin = _effective_is_admin(request)
    is_expedition = _is_expedition(request) if not _debug_override_email(request) else False
    is_allowed = _is_allowed_user(request) or bool(_debug_override_email(request))

    role = "admin" if is_admin else ("expedition" if is_expedition else "seller")
    tiny_sellers = _seller_bindings_for_request(request)
    tiny_seller_ids = [int(x["seller_id"]) for x in tiny_sellers if x.get("seller_id") is not None]

    return {
        "email": email,
        "role": role,
        "is_admin": is_admin,
        "is_expedition": is_expedition,
        "can_access_quotes": bool(is_admin or (is_allowed and not is_expedition)),
        "can_access_separation": bool(is_admin or is_expedition),
        "admin_emails_loaded": len(ADMIN_EMAILS),
        "allowed_emails_loaded": len(ALLOWED_EMAILS),
        "expedition_emails_loaded": len(EXPEDITION_EMAILS),
        "access_source": getattr(request.state, "access_source", "env"),
        "db_role": getattr(request.state, "db_role", ""),
        "tiny_sellers": tiny_sellers,
        "tiny_seller_ids": tiny_seller_ids,
        "primary_tiny_seller": tiny_sellers[0] if tiny_sellers else None,
    }



@app.get("/api/admin/users")
@app.get("/admin/users")
def admin_list_users(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar usuários.")

    cached = _admin_cache_get("admin_users")
    if cached is not None:
        return cached

    _ensure_app_users_table()

    rows = list(
        bq.query(
            f"""
            SELECT email, role, active, created_at, updated_at, updated_by
            FROM `{_app_users_table()}`
            ORDER BY updated_at DESC, email ASC
            """
        ).result()
    )

    users_by_email = {}

    for r in rows:
        item = _admin_user_row_to_dict(dict(r))
        users_by_email[item["email"]] = item

    # Exibe também permissões antigas via env vars, para não esconder acesso atual.
    for email in sorted(ADMIN_EMAILS):
        users_by_email.setdefault(email, {
            "email": email,
            "role": "admin",
            "active": True,
            "created_at": "",
            "updated_at": "",
            "updated_by": "env:ADMIN_EMAILS",
            "env_admin": True,
            "env_allowed": email in ALLOWED_EMAILS,
            "env_expedition": email in EXPEDITION_EMAILS,
        })

    for email in sorted(ALLOWED_EMAILS):
        users_by_email.setdefault(email, {
            "email": email,
            "role": "seller",
            "active": True,
            "created_at": "",
            "updated_at": "",
            "updated_by": "env:ALLOWED_EMAILS",
            "env_admin": email in ADMIN_EMAILS,
            "env_allowed": True,
            "env_expedition": email in EXPEDITION_EMAILS,
        })

    for email in sorted(EXPEDITION_EMAILS):
        users_by_email.setdefault(email, {
            "email": email,
            "role": "expedition",
            "active": True,
            "created_at": "",
            "updated_at": "",
            "updated_by": "env:EXPEDITION_EMAILS",
            "env_admin": email in ADMIN_EMAILS,
            "env_allowed": email in ALLOWED_EMAILS,
            "env_expedition": True,
        })

    return _admin_cache_set("admin_users", {
        "ok": True,
        "items": sorted(users_by_email.values(), key=lambda x: (not bool(x.get("active")), x.get("email") or "")),
        "env_counts": {
            "admin": len(ADMIN_EMAILS),
            "allowed": len(ALLOWED_EMAILS),
            "expedition": len(EXPEDITION_EMAILS),
        },
        "table": _app_users_table(),
    })




@app.get("/api/admin/users/audit")
@app.get("/admin/users/audit")
def admin_list_user_audit(
    request: Request,
    limit: int = Query(default=80, ge=1, le=300),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar auditoria.")

    cache_key = f"admin_user_audit:{int(limit)}"
    cached = _admin_cache_get(cache_key)
    if cached is not None:
        return cached

    _ensure_app_user_audit_table()

    rows = list(
        bq.query(
            f"""
            SELECT
              audit_id,
              target_email,
              action,
              before_role,
              after_role,
              before_active,
              after_active,
              changed_by,
              changed_at,
              source
            FROM `{_app_user_audit_table()}`
            ORDER BY changed_at DESC
            LIMIT @limit
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("limit", "INT64", int(limit)),
                ]
            ),
        ).result()
    )

    return _admin_cache_set(cache_key, {
        "ok": True,
        "items": [
            {
                "audit_id": str(r.get("audit_id") or ""),
                "target_email": str(r.get("target_email") or ""),
                "action": str(r.get("action") or ""),
                "before_role": str(r.get("before_role") or ""),
                "after_role": str(r.get("after_role") or ""),
                "before_active": r.get("before_active"),
                "after_active": r.get("after_active"),
                "changed_by": str(r.get("changed_by") or ""),
                "changed_at": str(r.get("changed_at") or ""),
                "source": str(r.get("source") or ""),
            }
            for r in rows
        ],
        "table": _app_user_audit_table(),
    })

@app.post("/api/admin/users")
@app.post("/admin/users")
def admin_upsert_user(payload: AdminUserPayload, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem alterar usuários.")

    email = _normalize_email(payload.email)
    role = _normalize_app_role(payload.role)
    active = bool(payload.active)
    now = _now_utc()
    updated_by = _user_email(request)
    before_record = _get_app_user_record(email)

    _ensure_app_users_table()

    bq.query(
        f"""
        MERGE `{_app_users_table()}` T
        USING (
          SELECT
            @email AS email,
            @role AS role,
            @active AS active,
            @now AS updated_at,
            @updated_by AS updated_by
        ) S
        ON LOWER(T.email) = LOWER(S.email)
        WHEN MATCHED THEN
          UPDATE SET
            role = S.role,
            active = S.active,
            updated_at = S.updated_at,
            updated_by = S.updated_by
        WHEN NOT MATCHED THEN
          INSERT (email, role, active, created_at, updated_at, updated_by)
          VALUES (S.email, S.role, S.active, S.updated_at, S.updated_at, S.updated_by)
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("email", "STRING", email),
                bigquery.ScalarQueryParameter("role", "STRING", role),
                bigquery.ScalarQueryParameter("active", "BOOL", active),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("updated_by", "STRING", updated_by),
            ]
        ),
    ).result()

    action = "created" if before_record is None else "updated"
    if before_record is not None and bool(before_record.get("active")) != bool(active):
        action = "activated" if active else "deactivated"

    _write_app_user_audit(
        target_email=email,
        action=action,
        before_record=before_record,
        after_role=role,
        after_active=active,
        changed_by=updated_by,
    )

    _clear_app_user_cache(email)
    _clear_admin_data_cache("admin_users")
    _clear_admin_data_cache("admin_user_audit")

    return {
        "ok": True,
        "item": {
            "email": email,
            "role": role,
            "active": active,
            "updated_at": now.isoformat(),
            "updated_by": updated_by,
        },
    }


@app.delete("/api/admin/users/{email:path}")
@app.delete("/admin/users/{email:path}")
def admin_disable_user(email: str, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem desativar usuários.")

    email = _normalize_email(email)
    now = _now_utc()
    updated_by = _user_email(request)
    before_record = _get_app_user_record(email)

    if email == updated_by and email not in ADMIN_EMAILS:
        raise HTTPException(
            status_code=400,
            detail="Por segurança, não é permitido desativar seu próprio acesso admin pela tela."
        )

    _ensure_app_users_table()

    bq.query(
        f"""
        MERGE `{_app_users_table()}` T
        USING (
          SELECT
            @email AS email,
            "seller" AS role,
            FALSE AS active,
            @now AS updated_at,
            @updated_by AS updated_by
        ) S
        ON LOWER(T.email) = LOWER(S.email)
        WHEN MATCHED THEN
          UPDATE SET
            active = FALSE,
            updated_at = S.updated_at,
            updated_by = S.updated_by
        WHEN NOT MATCHED THEN
          INSERT (email, role, active, created_at, updated_at, updated_by)
          VALUES (S.email, S.role, FALSE, S.updated_at, S.updated_at, S.updated_by)
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("email", "STRING", email),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("updated_by", "STRING", updated_by),
            ]
        ),
    ).result()

    _write_app_user_audit(
        target_email=email,
        action="deactivated",
        before_record=before_record,
        after_role=str((before_record or {}).get("role") or "seller"),
        after_active=False,
        changed_by=updated_by,
    )

    _clear_app_user_cache(email)
    _clear_admin_data_cache("admin_users")
    _clear_admin_data_cache("admin_user_audit")

    return {"ok": True, "email": email, "active": False}


@app.post("/quotes/{quote_id}/clone")
def clone_quote(quote_id: str, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem clonar orçamentos.")

    quote = _bq_get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")

    items = _bq_get_quote_items(quote_id)
    if not items:
        raise HTTPException(status_code=400, detail="Orçamento sem itens para clonar.")

    now_ts = _now_utc()

    quote_row = {
        "status": "draft",
        "internal_status": None,
        "client_id": quote.get("client_id"),
        "client_snapshot": quote.get("client_snapshot"),
        "seller_id": quote.get("seller_id"),
        "seller_name": quote.get("seller_name"),
        "shipping_method_id": quote.get("shipping_method_id"),
        "shipping_method_name": quote.get("shipping_method_name"),
        "freight_method_id": quote.get("freight_method_id"),
        "freight_method_name": quote.get("freight_method_name"),
        "payment_method_code": quote.get("payment_method_code"),
        "payment_method_name": quote.get("payment_method_name"),
        "payment_meio": quote.get("payment_meio"),
        "payment_conta": quote.get("payment_conta"),
        "payment_due_date": quote.get("payment_due_date"),
        "payment_category": quote.get("payment_category"),
        "notes": quote.get("notes"),
        "totals": quote.get("totals"),
        "payload": quote.get("payload"),
        "tiny_order_id": None,
        "tiny_order_number": None,
        "created_at": now_ts,
        "updated_at": now_ts,
    }

    items_rows = []
    for it in items:
        items_rows.append({
            "product_id": it.get("product_id"),
            "sku_snapshot": it.get("sku_snapshot"),
            "name_snapshot": it.get("name_snapshot"),
            "qty": it.get("qty"),
            "list_price": it.get("list_price"),
            "discount_pct": it.get("discount_pct"),
            "unit_price_disc": it.get("unit_price_disc"),
            "line_total": it.get("line_total"),
            "raw": it.get("raw"),
        })

    quote_row = jsonable_encoder(quote_row)
    items_rows = [jsonable_encoder(row) for row in items_rows]

    quote_row = jsonable_encoder(quote_row)


    items_rows = [jsonable_encoder(row) for row in items_rows]



    quote_row = jsonable_encoder(quote_row)
    items_rows = [jsonable_encoder(row) for row in items_rows]

    try:
        new_quote_id, new_quote_number = _insert_quote_bundle_with_retry(quote_row, items_rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao clonar orçamento: {e}")

    return {
        "ok": True,
        "quote_id": new_quote_id,
        "quote_number": new_quote_number,
    }


@app.delete("/quotes/{quote_id}")
def delete_quote(quote_id: str, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem excluir orçamentos.")

    sql_items = f"DELETE FROM {_table('quote_items')} WHERE quote_id = @qid"
    sql_quote = f"DELETE FROM {_table('quotes')} WHERE quote_id = @qid"

    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("qid", "STRING", quote_id)]
    )

    bq.query(sql_items, job_config=cfg).result()
    bq.query(sql_quote, job_config=cfg).result()
    return {"ok": True, "deleted": quote_id}


MAX_DISCOUNT_PCT = 33.33


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

    items: List[QuoteItemIn]
    notes: Optional[str] = ""

    class Config:
        extra = "allow"


def _min_unit_price(list_price: float) -> float:
    return float(list_price) * (1.0 - (MAX_DISCOUNT_PCT / 100.0))


def _enforce_discount_limits(items: List[QuoteItemIn]):
    for it in items:
        lp = float(it.list_price)
        min_unit = _min_unit_price(lp)
        if float(it.unit_price_disc) + 1e-9 < min_unit:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Desconto acima do permitido (máx {MAX_DISCOUNT_PCT:.2f}%). "
                    f"Produto {it.product_id}: valor mínimo unitário é {min_unit:.6f}"
                ),
            )


PAYMENT_METHODS = {
    "dinheiro": "Dinheiro",
    "cartao_credito": "Cartão de crédito",
    "credito": "Cartão de crédito",
    "cartao_debito": "Cartão de débito",
    "debito": "Cartão de débito",
    "boleto": "Boleto",
    "vale_troca": "Vale-troca",
    "pix": "Pix",
    "link_pagamento": "Link de pagamento",
    "multiplas": "Múltiplas",
    "cheque": "Cheque",
    "deposito": "Depósito",
    "crediario": "Crediário",
    "outros": "Outros",
}

@app.get("/debug/conta-receber-search")
def debug_conta_receber_search(
    key: str = Query(default=""),
    numero_doc: str = Query(default=""),
    nome_cliente: str = Query(default=""),
    data_ini_vencimento: str = Query(default=""),
    data_fim_vencimento: str = Query(default=""),
    situacao: str = Query(default=""),
    id_origem: str = Query(default=""),
    pagina: int = Query(default=1),
):
    if not key or key != os.getenv("DEBUG_KEY", ""):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        r = tiny.pesquisar_contas_receber(
            numero_doc=numero_doc,
            nome_cliente=nome_cliente,
            data_ini_vencimento=data_ini_vencimento,
            data_fim_vencimento=data_fim_vencimento,
            situacao=situacao,
            id_origem=id_origem,
            pagina=pagina,
        )
        return r
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/debug/conta-receber/{conta_id}")
def debug_conta_receber(conta_id: int, key: str = Query(default="")):
    if not key or key != os.getenv("DEBUG_KEY", ""):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        r = tiny.obter_conta_receber(conta_id)
        conta = r.get("conta") or {}
        return {
            "raw": r,
            "summary": {
                "id": conta.get("id"),
                "forma_pagamento": conta.get("forma_pagamento"),
                "portador": conta.get("portador"),
                "categoria": conta.get("categoria"),
                "vencimento": conta.get("vencimento"),
                "situacao": conta.get("situacao"),
                "historico": conta.get("historico"),
                "nro_documento": conta.get("nro_documento"),
            },
        }
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/tiny/payment-methods")
def tiny_payment_methods():
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
            fr = (
                it.get("forma_recebimento")
                or it.get("formaRecebimento")
                or it
            )

            raw_name = (
                fr.get("descricao")
                or fr.get("nome")
                or fr.get("forma_recebimento")
                or fr.get("formaRecebimento")
                or ""
            )
            name = str(raw_name or "").strip()
            if not name:
                continue

            raw_code = (
                fr.get("codigo")
                or fr.get("forma_pagamento")
                or fr.get("formaPagamento")
                or name
            )
            code = str(raw_code or "").strip().lower()
            if not code:
                code = name.strip().lower()

            items.append({
                "code": code,
                "name": name,
                "id": fr.get("id"),
                "raw": fr,
            })

        # dedup por code
        dedup = {}
        for item in items:
            dedup[item["code"]] = item

        final_items = sorted(dedup.values(), key=lambda x: (x.get("name") or "").lower())
        return {"items": final_items}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/clients")
def tiny_clients(q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    try:
        r = tiny.pesquisar_contatos(pesquisa=q, pagina=page)
        contatos = r.get("contatos") or []
        items = []
        for it in contatos:
            c = it.get("contato", it)
            if not c.get("id"):
                continue
            items.append({
                "id": int(c["id"]),
                "nome": c.get("nome") or "",
                "cpf_cnpj": c.get("cpf_cnpj") or "",
                "email": c.get("email") or "",
                "fone": c.get("fone") or "",
                "cidade": c.get("cidade") or "",
                "uf": c.get("uf") or "",
                "raw": c,
            })
        return {"items": items, "page": page}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _tiny_wallet_parse_date(value):
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _tiny_wallet_safe_float(value):
    try:
        return float(str(value or 0).replace(",", "."))
    except Exception:
        return 0.0


def _tiny_wallet_fetch_orders_for_contact(nome: str, cpf_cnpj: str):
    pedidos_all = []
    pagina = 1

    while True:
        try:
            if cpf_cnpj:
                resp = tiny.pesquisar_pedidos(
                    cpf_cnpj=cpf_cnpj,
                    pagina=pagina,
                    sort="DESC",
                )
            else:
                resp = tiny.pesquisar_pedidos(
                    cliente=nome,
                    pagina=pagina,
                    sort="DESC",
                )
        except TinyAPIError as e:
            msg = str(e).lower()
            if "não retornou registros" in msg or "nao retornou registros" in msg:
                break
            if "consulta nao retornou registros" in msg:
                break
            raise

        pedidos = resp.get("pedidos") or []
        if isinstance(pedidos, dict):
            pedidos = [pedidos]
        if not pedidos:
            break

        for row in pedidos:
            pedidos_all.append(row.get("pedido", row))

        try:
            numero_paginas = int(resp.get("numero_paginas") or pagina)
        except Exception:
            numero_paginas = pagina

        if pagina >= numero_paginas:
            break

        pagina += 1

    return pedidos_all


@app.get("/api/tiny/client-wallet-live")
@app.get("/tiny/client-wallet-live")
def tiny_client_wallet_live(
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=10),
    seller_id: str = Query(default=""),
):
    try:
        q = str(q or "").strip()
        seller_id = str(seller_id or "").strip()
        page_size = max(1, min(int(page_size or 10), 10))

        tiny_page = ((page - 1) * page_size) // 100 + 1
        slice_start = ((page - 1) * page_size) % 100
        slice_end = slice_start + page_size

        try:
            r = tiny.pesquisar_contatos(
                pesquisa=q,
                pagina=tiny_page,
                id_vendedor=int(seller_id) if seller_id else None,
            )
            contatos = r.get("contatos") or []
        except TinyAPIError as e:
            msg = str(e).lower()
            if "não retornou registros" in msg or "nao retornou registros" in msg:
                return {
                    "items": [],
                    "page": page,
                    "page_size": page_size,
                    "seller_id": seller_id,
                    "has_more": False,
                    "numero_paginas_tiny": 0,
                }
            raise
        contatos = contatos[slice_start:slice_end]

        items = []
        for it in contatos:
            c = it.get("contato", it)
            if not c.get("id"):
                continue

            nome = str(c.get("nome") or "").strip()
            cpf_cnpj = str(c.get("cpf_cnpj") or "").strip()

            qtd_pedidos = None
            total_pedidos = None
            ultimo_pedido_dt = None
            dias_sem_pedido = None

            search_active = bool(str(q or "").strip()) or bool(str(seller_id or "").strip())
            if search_active:
                pedidos = _tiny_wallet_fetch_orders_for_contact(nome=nome, cpf_cnpj=cpf_cnpj)

                qtd_pedidos = len(pedidos)
                total_pedidos = 0.0

                for pedido in pedidos:
                    total_pedidos += _tiny_wallet_safe_float(pedido.get("valor"))

                    dt = _tiny_wallet_parse_date(pedido.get("data_pedido"))
                    if dt and (ultimo_pedido_dt is None or dt > ultimo_pedido_dt):
                        ultimo_pedido_dt = dt

                if ultimo_pedido_dt:
                    dias_sem_pedido = (datetime.now().date() - ultimo_pedido_dt.date()).days

            items.append({
                "id": int(c["id"]),
                "nome": nome,
                "cpf_cnpj": cpf_cnpj,
                "email": c.get("email") or "",
                "fone": c.get("fone") or "",
                "cidade": c.get("cidade") or "",
                "uf": c.get("uf") or "",
                "id_vendedor": c.get("id_vendedor") or c.get("idVendedor"),
                "nome_vendedor": c.get("nome_vendedor") or c.get("nomeVendedor") or "",
                "qtd_pedidos": qtd_pedidos,
                "total_pedidos": total_pedidos,
                "ultimo_pedido": ultimo_pedido_dt.strftime("%d/%m/%Y") if ultimo_pedido_dt else "",
                "dias_sem_pedido": dias_sem_pedido,
                "raw": c,
            })

        try:
            numero_paginas_tiny = int(r.get("numero_paginas") or 1)
        except Exception:
            numero_paginas_tiny = 1

        has_more = (slice_end < 100) or (tiny_page < numero_paginas_tiny)

        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "seller_id": seller_id,
            "has_more": has_more,
            "numero_paginas_tiny": numero_paginas_tiny,
        }
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/products")
def tiny_products(q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    try:
        r = tiny.pesquisar_produtos(pesquisa=q, pagina=page)
        prods = r.get("produtos") or []
        items = []
        for it in prods:
            p = it.get("produto", it)
            if not p.get("id"):
                continue
            if not _is_active_flag(p.get("situacao")):
                continue
            items.append({
                "id": int(p["id"]),
                "codigo": p.get("codigo") or "",
                "nome": p.get("nome") or "",
                "preco": p.get("preco"),
                "unidade": p.get("unidade") or "Un",
                "situacao": p.get("situacao"),
                "raw": p,
            })
        return {"items": items, "page": page}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/products/{product_id}/stock")
def tiny_stock(product_id: int):
    try:
        r = tiny.obter_estoque_produto(product_id)
        prod = r.get("produto") or r.get("estoque") or r
        return {"product_id": product_id, "raw": prod}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/vendors")
def tiny_vendors(q: str = Query(default=""), page: int = Query(default=1, ge=1)):
    if not q or len(q.strip()) < 2:
        return {"items": [], "page": page}
    try:
        r = tiny.pesquisar_vendedores(pesquisa=q.strip(), pagina=page)
        vend = r.get("vendedores") or []
        items = []
        for it in vend:
            v = it.get("vendedor", it)
            if not v.get("id"):
                continue
            items.append({
                "id": int(v["id"]),
                "nome": v.get("nome") or "",
                "codigo": v.get("codigo") or "",
                "raw": v,
            })
        return {"items": items, "page": page}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/shipping-methods")
def tiny_shipping_methods(tipo_logistica: Optional[int] = Query(default=None)):
    try:
        r = tiny.pesquisar_formas_envio(tipo_logistica=tipo_logistica)
        try:
            print("[SHIPPING_METHODS_RAW]", json.dumps(r, ensure_ascii=False))
        except Exception:
            print("[SHIPPING_METHODS_RAW]", str(r))
        regs = r.get("registros") or []
        items = []
        for x in regs:
            try:
                xid = int(x.get("id"))
            except Exception:
                continue

            nome = (x.get("nome") or "").strip()
            if not nome:
                continue
            if _is_placeholder_name(nome):
                continue
            if not _is_active_flag(x.get("situacao")):
                continue

            items.append({
                "id": xid,
                "nome": nome,
                "situacao": x.get("situacao"),
                "tipo_logistica": x.get("tipo_logistica"),
                "raw": x,
            })
        items.sort(key=lambda a: _norm_text(a["nome"]))
        return {"items": items}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/shipping-methods/{shipping_id}/freight-methods")
def tiny_freight_methods(shipping_id: int):
    try:
        r = tiny.obter_forma_envio(shipping_id)
        try:
            print(f"[FREIGHT_METHODS_RAW][shipping_id={shipping_id}]", json.dumps(r, ensure_ascii=False))
        except Exception:
            print(f"[FREIGHT_METHODS_RAW][shipping_id={shipping_id}]", str(r))
        forma = r.get("forma_envio") or {}
        fretes = forma.get("formas_frete") or []
        items = []
        for f in fretes:
            try:
                fid = int(f.get("id"))
            except Exception:
                continue

            descricao = (f.get("descricao") or "").strip()
            if not descricao:
                continue
            if _is_placeholder_name(descricao):
                continue
            if not _is_active_flag(f.get("situacao")):
                continue

            items.append({
                "id": fid,
                "descricao": descricao,
                "codigo": f.get("codigo") or "",
                "codigo_externo": f.get("codigo_externo") or "",
                "raw": f,
            })
        items.sort(key=lambda a: _norm_text(a["descricao"]))
        return {"items": items, "shipping": {"id": shipping_id, "nome": forma.get("nome")}}
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tiny/freight-methods")
def tiny_freight_methods_alias(
    shipping_id: int = Query(default=None),
    shipping_method_id: int = Query(default=None),
):
    sid = shipping_id or shipping_method_id
    if not sid:
        raise HTTPException(status_code=400, detail="Missing shipping_id (or shipping_method_id)")
    return tiny_freight_methods(sid)


def _bq_insert_rows(table: str, rows: List[Dict[str, Any]]):
    if not rows:
        return
    ref = f"{PROJECT_ID}.{DATASET_ID}.{table}"
    job = bq.load_table_from_json(rows, ref)
    job.result()


def _bq_get_quote(quote_id: str) -> Dict[str, Any]:
    q_sql = f"SELECT * FROM {_table('quotes')} WHERE quote_id=@id LIMIT 1"
    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", quote_id)]
    )
    q_rows = list(bq.query(q_sql, job_config=cfg).result())
    if not q_rows:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    return dict(q_rows[0])


def _bq_get_quote_items(quote_id: str) -> List[Dict[str, Any]]:
    i_sql = f"SELECT * FROM {_table('quote_items')} WHERE quote_id=@id ORDER BY line"
    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", quote_id)]
    )
    return [dict(r) for r in bq.query(i_sql, job_config=cfg).result()]


def _quote_number_exists(quote_number: int) -> bool:
    sql = f"SELECT COUNT(1) AS c FROM {_table('quotes')} WHERE quote_number=@n"
    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("n", "INT64", int(quote_number))]
    )
    row = list(bq.query(sql, job_config=cfg).result())[0]
    return int(row["c"] or 0) > 0



def _next_quote_number() -> int:
    for _ in range(20):
        base = int(dt.datetime.now(dt.timezone.utc).strftime("%y%m%d%H%M%S%f"))
        candidate = int(str(base)[-15:])
        candidate += random.randint(0, 99)
        if not _quote_number_exists(candidate):
            return int(candidate)
    raise RuntimeError("Não foi possível gerar um quote_number único.")



def _delete_quote_bundle(quote_id: str):
    params = [bigquery.ScalarQueryParameter("qid", "STRING", quote_id)]
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    try:
        bq.query(f"DELETE FROM {_table('quote_items')} WHERE quote_id=@qid", job_config=cfg).result()
    finally:
        bq.query(f"DELETE FROM {_table('quotes')} WHERE quote_id=@qid", job_config=cfg).result()



def _insert_quote_bundle_with_retry(quote_row: Dict[str, Any], items_rows: List[Dict[str, Any]], max_attempts: int = 4) -> tuple[str, int]:
    last_err = None
    for attempt in range(1, max_attempts + 1):
        quote_id = uuid.uuid4().hex
        quote_number = _next_quote_number()
        quote_row["quote_id"] = quote_id
        quote_row["quote_number"] = quote_number
        for i, row in enumerate(items_rows, start=1):
            row["quote_id"] = quote_id
            row["line"] = i

        try:
            _bq_insert_rows("quotes", [quote_row])
            _bq_insert_rows("quote_items", items_rows)
            return quote_id, quote_number
        except Exception as e:
            last_err = e
            _log_event(
                "create_quote.insert_retry",
                attempt=attempt,
                quote_id=quote_id,
                quote_number=quote_number,
                error=str(e),
            )
            try:
                _delete_quote_bundle(quote_id)
            except Exception as rollback_err:
                _log_event(
                    "create_quote.rollback_error",
                    quote_id=quote_id,
                    quote_number=quote_number,
                    error=str(rollback_err),
                )
            if attempt < max_attempts:
                continue
    raise RuntimeError(f"Falha ao persistir orçamento após tentativas: {last_err}")


@app.get("/debug/orders/{tiny_order_id}")
def debug_order(tiny_order_id: int):
    try:
        resp = tiny.obter_pedido(tiny_order_id)
        return {
            "status": "OK",
            "tiny_order_id": tiny_order_id,
            "summary": _extract_tiny_order_debug(resp),
            "raw": resp,
        }
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/debug/receber/by-order/{tiny_order_id}")
def debug_receber_by_order(
    tiny_order_id: int,
    request: Request,
    key: Optional[str] = Query(default=None),
):
    debug_key = os.getenv("DEBUG_KEY", "")

    allowed = _is_admin(request) or (bool(key) and bool(debug_key) and key == debug_key)
    if not allowed:
        raise HTTPException(status_code=403, detail="Acesso negado ao diagnóstico.")

    try:
        pesq = tiny._post("contas.receber.pesquisa.php", {"id_origem": str(tiny_order_id)})
        contas = pesq.get("contas") or []
        conta = (contas[0].get("conta", contas[0]) if contas else {}) if isinstance(contas, list) else {}
        conta_id = conta.get("id")

        detalhe = None
        if conta_id:
            detalhe = tiny._post("conta.receber.obter.php", {"id": int(conta_id)})

        return {
            "status": "OK",
            "tiny_order_id": tiny_order_id,
            "conta_id": conta_id,
            "pesquisa": pesq,
            "detalhe": detalhe,
        }
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))



@app.get("/ops/tiny-sync-preview")
def tiny_sync_preview(
    request: Request,
    local_limit: int = Query(default=50, ge=1, le=500),
    include_remote: bool = Query(default=True),
    remote_pages: int = Query(default=1, ge=1, le=100),
    remote_search: str = Query(default=""),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem visualizar o preview de sincronização.")

    sql = f"""
    SELECT
      q.quote_id,
      q.quote_number,
      q.tiny_order_id,
      q.tiny_order_number,
      q.status,
      q.internal_status,
      COALESCE(
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.nome'),
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.name')
      ) AS client_name,
      q.seller_name,
      q.created_at,
      q.updated_at
    FROM {_table("quotes")} q
    WHERE q.tiny_order_id IS NOT NULL
    ORDER BY q.updated_at DESC, q.created_at DESC
    LIMIT @limit
    """

    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", int(local_limit))]
    )
    local_rows = [dict(r) for r in bq.query(sql, job_config=cfg).result()]

    preview_items = []
    local_tiny_ids = set()
    stats = {
        "local_checked": 0,
        "tiny_found": 0,
        "tiny_missing": 0,
        "tiny_errors": 0,
        "remote_only_found": 0,
    }

    for row in local_rows:
        tiny_order_id = row.get("tiny_order_id")
        if tiny_order_id is None:
            continue

        try:
            tiny_order_id = int(tiny_order_id)
        except Exception:
            preview_items.append({
                **row,
                "tiny_exists": False,
                "sync_state": "invalid_local_tiny_order_id",
                "tiny_error": f"tiny_order_id inválido: {tiny_order_id}",
                "tiny": None,
            })
            stats["local_checked"] += 1
            stats["tiny_errors"] += 1
            continue

        local_tiny_ids.add(tiny_order_id)
        stats["local_checked"] += 1

        try:
            raw = tiny.obter_pedido(tiny_order_id)
            snap = _extract_tiny_order_preview(raw)
            preview_items.append({
                **row,
                "tiny_exists": True,
                "sync_state": "ok",
                "tiny_error": None,
                "tiny": snap,
            })
            stats["tiny_found"] += 1
        except TinyAPIError as e:
            err_txt = str(e)
            missing = _tiny_error_looks_missing(e)
            preview_items.append({
                **row,
                "tiny_exists": False if missing else None,
                "sync_state": "missing_in_tiny" if missing else "tiny_error",
                "tiny_error": err_txt,
                "tiny": None,
            })
            if missing:
                stats["tiny_missing"] += 1
            else:
                stats["tiny_errors"] += 1

    remote_only = []
    remote_warning = None

    if include_remote:
        try:
            search_txt = str(remote_search or "").strip()

            # Se não houver busca específica e o front pedir apenas 1 página,
            # fazemos uma varredura automática mais ampla no beta.
            effective_remote_pages = int(remote_pages or 1)
            if not search_txt and effective_remote_pages <= 1:
                effective_remote_pages = 25

            seen_remote_ids = set()

            for pagina in range(1, effective_remote_pages + 1):
                search = tiny.pesquisar_pedidos(
                    pesquisa=search_txt,
                    pagina=pagina,
                )
                pedidos = search.get("pedidos") or []
                if isinstance(pedidos, dict):
                    pedidos = [pedidos]

                # Se a página vier vazia, encerramos a paginação
                if not pedidos:
                    break

                page_new = 0

                for item in pedidos:
                    snap = _extract_tiny_search_order_item(item)
                    rid = snap.get("id")
                    try:
                        rid_int = int(rid)
                    except Exception:
                        continue

                    if rid_int in seen_remote_ids:
                        continue
                    seen_remote_ids.add(rid_int)

                    if rid_int in local_tiny_ids:
                        continue

                    remote_only.append({
                        "tiny_order_id": rid_int,
                        "tiny_order_number": snap.get("numero"),
                        "client_name": snap.get("cliente_nome"),
                        "tiny_status": snap.get("situacao"),
                        "tiny": snap,
                    })
                    page_new += 1

                # Heurística segura:
                # se uma página inteira não trouxe nada novo, paramos
                if page_new == 0:
                    break

        except Exception as e:
            remote_warning = str(e)

    stats["remote_only_found"] = len(remote_only)

    response = {
        "mode": "preview_read_only",
        "writes_to_tiny": False,
        "writes_to_bigquery": False,
        "enable_tiny_status_sync_env": ENABLE_TINY_STATUS_SYNC,
        "dataset": DATASET_ID,
        "stats": stats,
        "items": preview_items,
        "remote_only": remote_only,
        "remote_warning": remote_warning,
        "params": {
            "local_limit": local_limit,
            "include_remote": include_remote,
            "remote_pages": remote_pages,
            "remote_search": remote_search,
        },
    }

    resp = JSONResponse(content=jsonable_encoder(response))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.get("/quotes")
def list_quotes(
    request: Request,
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=5, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    is_admin = _is_admin(request)
    email = _user_email(request)

    where_parts = []
    params = [
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
        bigquery.ScalarQueryParameter("offset", "INT64", offset),
    ]

    if status:
        where_parts.append("q.status=@status")
        params.insert(0, bigquery.ScalarQueryParameter("status", "STRING", status))

    if q:
        where_parts.append("""(
          LOWER(COALESCE(JSON_EXTRACT_SCALAR(q.client_snapshot, '$.nome'), JSON_EXTRACT_SCALAR(q.client_snapshot, '$.name'), '')) LIKE @q
          OR LOWER(COALESCE(q.seller_name, '')) LIKE @q
          OR CAST(q.quote_number AS STRING) LIKE @q_raw
          OR CAST(q.tiny_order_number AS STRING) LIKE @q_raw
          OR LOWER(COALESCE(q.quote_id, '')) LIKE @q
        )""")
        params.insert(0, bigquery.ScalarQueryParameter("q", "STRING", f"%{str(q).lower()}%"))
        params.insert(1, bigquery.ScalarQueryParameter("q_raw", "STRING", f"%{str(q)}%"))

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    sql = f"""
    SELECT
      q.quote_id,
      q.quote_number,
      q.tiny_order_id,
      q.tiny_order_number,
      q.status,
      q.client_id,
      COALESCE(
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.nome'),
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.name')
      ) AS client_name,
      COALESCE(
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpf_cnpj'),
        JSON_EXTRACT_SCALAR(q.client_snapshot, '$.cpfCnpj')
      ) AS client_cpf_cnpj,
      q.seller_id,
      COALESCE(
        q.seller_name,
        JSON_EXTRACT_SCALAR(q.seller_snapshot, '$.name'),
        JSON_EXTRACT_SCALAR(q.seller_snapshot, '$.nome')
      ) AS seller_name,
      q.shipping_method_id,
      q.shipping_method_name,
      q.freight_method_id,
      q.freight_method_name,
      q.payment_method_code,
      q.payment_method_name,
      q.payment_meio,
      q.payment_conta,
      q.payment_due_date,
      q.payment_category,
      q.payment_notify,
      q.internal_status,
      q.totals,
      q.notes,
      q.created_at,
      q.updated_at,
      s.status AS separation_status,
      s.printed AS separation_printed,
      COALESCE(fi.cost_total_products, 0) AS cost_total_products,
      COALESCE(fi.sale_total_products, 0) AS sale_total_products,
      COALESCE(fi.profit_total_products, 0) AS profit_total_products,
      COALESCE(fi.markup_total_order, 0) AS markup_total_order
    FROM {_table("quotes")} q
    LEFT JOIN {_table("separation_orders")} s
      ON q.tiny_order_id = s.tiny_order_id
    LEFT JOIN (
      SELECT
        qi.quote_id,
        ROUND(SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)), 2) AS cost_total_products,
        ROUND(SUM(COALESCE(CAST(qi.line_total AS FLOAT64), 0)), 2) AS sale_total_products,
        ROUND(
          SUM(COALESCE(CAST(qi.line_total AS FLOAT64), 0)) -
          SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)),
          2
        ) AS profit_total_products,
        ROUND(
          SAFE_DIVIDE(
            SUM(COALESCE(CAST(qi.line_total AS FLOAT64), 0)) -
            SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)),
            NULLIF(SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)), 0)
          ) * 100,
          2
        ) AS markup_total_order
      FROM {_table("quote_items")} qi
      GROUP BY qi.quote_id
    ) fi
      ON q.quote_id = fi.quote_id
    {where_sql}
    ORDER BY q.created_at DESC
    LIMIT @limit OFFSET @offset
    """
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(bq.query(sql, job_config=cfg).result())

    count_sql = f"""
    SELECT COUNT(1) AS c
    FROM {_table('quotes')} q
    {where_sql}
    """
    count_cfg = bigquery.QueryJobConfig(query_parameters=[p for p in params if p.name not in ("limit", "offset")])
    total = int(list(bq.query(count_sql, job_config=count_cfg).result())[0]["c"])

    next_offset = offset + limit
    return {
        "items": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": next_offset < total,
        "next_offset": (next_offset if next_offset < total else None),
    }


@app.get("/quotes/{quote_id}")
def get_quote(quote_id: str):
    quote = _bq_get_quote(quote_id)
    items = _bq_get_quote_items(quote_id)
    return {"quote": quote, "items": items}


@app.post("/quotes")
def create_quote(payload: QuoteCreateIn):
    try:
        if not payload.client_id:
            raise HTTPException(status_code=400, detail="Cliente é obrigatório.")
        if not payload.seller_id:
            raise HTTPException(status_code=400, detail="Vendedor é obrigatório.")
        if not payload.shipping_method_id:
            raise HTTPException(status_code=400, detail="Forma de envio é obrigatória.")
        if not payload.freight_method_id:
            raise HTTPException(status_code=400, detail="Forma de frete é obrigatória.")
        if not payload.payment_method_code:
            raise HTTPException(status_code=400, detail="Forma de pagamento é obrigatória.")
        if not getattr(payload, "payment_due_date", None):
            raise HTTPException(status_code=400, detail="Vencimento é obrigatório.")
        payload.payment_due_date = _coerce_due_date_not_past(payload.payment_due_date)
        if not getattr(payload, "payment_category", None):
            raise HTTPException(status_code=400, detail="Categoria é obrigatória.")
        if not payload.items:
            raise HTTPException(status_code=400, detail="items não pode ser vazio")

        _log_event(
            "create_quote.start",
            client_id=payload.client_id,
            seller_id=payload.seller_id,
            shipping_method_id=payload.shipping_method_id,
            freight_method_id=payload.freight_method_id,
            items_count=len(payload.items or []),
            payment_method_code=payload.payment_method_code,
        )

        _enforce_discount_limits(payload.items)

        for idx, item in enumerate(payload.items or [], start=1):
            if not getattr(item, "product_id", None):
                raise HTTPException(status_code=400, detail=f"Item {idx}: produto é obrigatório.")
            qty = float(getattr(item, "qty", 0) or 0)
            unit_price_disc = float(getattr(item, "unit_price_disc", 0) or 0)
            if qty <= 0:
                raise HTTPException(status_code=400, detail=f"Item {idx}: quantidade deve ser maior que zero.")
            if unit_price_disc <= 0:
                raise HTTPException(status_code=400, detail=f"Item {idx}: preço final deve ser maior que zero.")

        try:
            c_resp = tiny.obter_contato(payload.client_id)
            c_raw = (c_resp.get("contato") or c_resp.get("cliente") or c_resp)
            _log_event("create_quote.client_loaded", client_id=payload.client_id, client_name=c_raw.get("nome"))
        except TinyAPIError as e:
            _log_event("create_quote.client_error", client_id=payload.client_id, error=str(e))
            raise HTTPException(status_code=502, detail=f"Erro buscando cliente no Tiny: {e}")

        try:
            fe = tiny.obter_forma_envio(payload.shipping_method_id)
            forma_envio = fe.get("forma_envio") or {}
            shipping_name = (forma_envio.get("nome") or "").strip()

            freight_name = ""
            if payload.freight_method_id:
                for f in (forma_envio.get("formas_frete") or []):
                    if int(f.get("id")) == int(payload.freight_method_id):
                        freight_name = (f.get("descricao") or "").strip()
                        break
            _log_event(
                "create_quote.shipping_loaded",
                shipping_method_id=payload.shipping_method_id,
                shipping_name=shipping_name,
                freight_method_id=payload.freight_method_id,
                freight_name=freight_name,
            )
        except TinyAPIError as e:
            _log_event(
                "create_quote.shipping_error",
                shipping_method_id=payload.shipping_method_id,
                freight_method_id=payload.freight_method_id,
                error=str(e),
            )
            raise HTTPException(status_code=502, detail=f"Erro obtendo envio/frete no Tiny: {e}")

        payment_code, payment_meio_final, payment_conta_final = _apply_payment_business_rules(
            payload.payment_method_code,
            payload.payment_meio,
            payload.payment_conta,
        )

        if not payment_code:
            raise HTTPException(status_code=400, detail="Forma de pagamento é obrigatória")

        payment_name = PAYMENT_METHODS.get(payment_code)
        if not payment_name:
            raise HTTPException(status_code=400, detail="Forma de pagamento inválida")

        products_map: Dict[int, Dict[str, Any]] = {}
        for it in payload.items:
            if it.product_id in products_map:
                continue
            try:
                p_resp = tiny.obter_produto(it.product_id)
                p_raw = p_resp.get("produto") or p_resp
                products_map[it.product_id] = p_raw
            except TinyAPIError as e:
                _log_event("create_quote.product_error", product_id=it.product_id, error=str(e))
                raise HTTPException(status_code=502, detail=f"Erro buscando produto {it.product_id}: {e}")

        now = _now_utc()

        total_net = 0.0
        items_rows = []
        for line, it in enumerate(payload.items, start=1):
            p = products_map[it.product_id]
            qty = float(it.qty)
            unit_disc = float(it.unit_price_disc)
            line_net = round(qty * unit_disc, 2)
            total_net = round(total_net + line_net, 2)

            items_rows.append({
                "quote_id": None,
                "line": line,
                "product_id": int(it.product_id),
                "sku_snapshot": p.get("codigo") or "",
                "name_snapshot": p.get("nome") or "",
                "qty": qty,
                "list_price": float(it.list_price),
                "discount_pct": float(it.discount_pct or 0.0),
                "unit_price_disc": unit_disc,
                "line_total": line_net,
                "raw": _to_json({"product_raw": p, "item": it.model_dump()}),
            })

        payment_notify = False

        quote_row = {
            "quote_id": None,
            "quote_number": None,
            "tiny_order_id": None,
            "tiny_order_number": None,
            "status": "draft",
            "client_id": int(payload.client_id),
            "client_snapshot": _to_json(c_raw),
            "seller_id": int(payload.seller_id),
            "seller_name": (payload.seller_name or "").strip() or None,
            "seller_snapshot": _to_json({"id": payload.seller_id, "name": (payload.seller_name or "").strip()}),
            "shipping_method_id": int(payload.shipping_method_id),
            "shipping_method_name": shipping_name,
            "freight_method_id": int(payload.freight_method_id) if payload.freight_method_id else None,
            "freight_method_name": freight_name or None,
            "payment_method_code": payment_code or None,
            "payment_method_name": payment_name,
            "payment_meio": payment_meio_final,
            "payment_conta": payment_conta_final,
            "payment_due_date": _coerce_due_date_not_past(_clean_str(payload.payment_due_date)),
            "payment_category": _clean_str(payload.payment_category),
            "payment_notify": payment_notify,
            "internal_status": "Aguardando Aprovação",
            "totals": _to_json({"net": round(total_net, 2)}),
            "notes": payload.notes or "",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "payload": _to_json(payload.model_dump()),
        }

        quote_id, quote_number = _insert_quote_bundle_with_retry(quote_row, items_rows)

        _log_event(
            "create_quote.success",
            quote_id=quote_id,
            quote_number=quote_number,
            items_count=len(items_rows),
            total_net=round(total_net, 2),
        )

        return {
            "status": "OK",
            "quote_id": quote_id,
            "quote_number": quote_number,
            "quote_status": "draft",
            "totals": {"net": round(total_net, 2)},
            "message": "Orçamento salvo como rascunho.",
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_event("create_quote.unhandled_error", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro ao salvar orçamento: {e}")


@app.patch("/quotes/{quote_id}")
def update_quote(quote_id: str, payload: QuoteCreateIn):
    if not payload.shipping_method_id:
        raise HTTPException(status_code=400, detail="Forma de envio é obrigatória.")
    if not payload.freight_method_id:
        raise HTTPException(status_code=400, detail="Forma de frete é obrigatória.")
    if not payload.payment_method_code:
        raise HTTPException(status_code=400, detail="Forma de pagamento é obrigatória.")
    if not getattr(payload, "payment_due_date", None):
        raise HTTPException(status_code=400, detail="Vencimento é obrigatório.")
    payload.payment_due_date = _coerce_due_date_not_past(payload.payment_due_date)
    if not getattr(payload, "payment_category", None):
        raise HTTPException(status_code=400, detail="Categoria é obrigatória.")
    if not payload.items:
        raise HTTPException(status_code=400, detail="items não pode ser vazio")

    _enforce_discount_limits(payload.items)

    existing = _bq_get_quote(quote_id)
    if existing.get("tiny_order_id"):
        raise HTTPException(
            status_code=400,
            detail="Não é possível editar: este orçamento já gerou pedido no Tiny.",
        )

    try:
        c_resp = tiny.obter_contato(payload.client_id)
        c_raw = (c_resp.get("contato") or c_resp.get("cliente") or c_resp)
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=f"Erro buscando cliente no Tiny: {e}")

    try:
        fe = tiny.obter_forma_envio(payload.shipping_method_id)
        forma_envio = fe.get("forma_envio") or {}
        shipping_name = (forma_envio.get("nome") or "").strip()

        freight_name = ""
        if payload.freight_method_id:
            for f in (forma_envio.get("formas_frete") or []):
                if int(f.get("id")) == int(payload.freight_method_id):
                    freight_name = (f.get("descricao") or "").strip()
                    break
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=f"Erro obtendo envio/frete no Tiny: {e}")

    payment_code, payment_meio_final, payment_conta_final = _apply_payment_business_rules(
        payload.payment_method_code,
        payload.payment_meio,
        payload.payment_conta,
    )

    if not payment_code:
        raise HTTPException(status_code=400, detail="Forma de pagamento é obrigatória")

    payment_name = PAYMENT_METHODS.get(payment_code)
    if not payment_name:
        raise HTTPException(status_code=400, detail="Forma de pagamento inválida")
        
    products_map: Dict[int, Dict[str, Any]] = {}
    for it in payload.items:
        if it.product_id in products_map:
            continue
        try:
            p_resp = tiny.obter_produto(it.product_id)
            p_raw = p_resp.get("produto") or p_resp
            products_map[it.product_id] = p_raw
        except TinyAPIError as e:
            raise HTTPException(status_code=502, detail=f"Erro buscando produto {it.product_id}: {e}")

    total_net = 0.0
    items_rows = []
    for line, it in enumerate(payload.items, start=1):
        p = products_map[it.product_id]
        qty = round(float(it.qty), 4)
        list_price = round(float(it.list_price), 2)
        discount_pct = round(float(it.discount_pct or 0.0), 4)
        unit_disc = round(float(it.unit_price_disc), 2)
        line_net = round(qty * unit_disc, 2)
        total_net = round(total_net + line_net, 2)

        items_rows.append({
            "quote_id": quote_id,
            "line": line,
            "product_id": int(it.product_id),
            "sku_snapshot": p.get("codigo") or "",
            "name_snapshot": p.get("nome") or "",
            "qty": qty,
            "list_price": list_price,
            "discount_pct": discount_pct,
            "unit_price_disc": unit_disc,
            "line_total": line_net,
            "raw": _to_json({"product_raw": p, "item": it.model_dump()}),
        })

    payment_notify = False
    now = _now_utc()

    upd_sql = f"""
    UPDATE {_table('quotes')}
    SET
      status='draft',
      client_id=@client_id,
      client_snapshot=@client_snapshot,
      seller_id=@seller_id,
      seller_name=@seller_name,
      seller_snapshot=@seller_snapshot,
      shipping_method_id=@shipping_method_id,
      shipping_method_name=@shipping_method_name,
      freight_method_id=@freight_method_id,
      freight_method_name=@freight_method_name,
      payment_method_code=@payment_method_code,
      payment_method_name=@payment_method_name,
      payment_meio=@payment_meio,
      payment_conta=@payment_conta,
      payment_due_date=@payment_due_date,
      payment_category=@payment_category,
      payment_notify=@payment_notify,
      internal_status='Aguardando Aprovação',
      totals=@totals,
      notes=@notes,
      payload=@payload,
      updated_at=@updated_at
    WHERE quote_id=@quote_id
    """
    bq.query(
        upd_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("client_id", "INT64", int(payload.client_id)),
            bigquery.ScalarQueryParameter("client_snapshot", "STRING", _to_json(c_raw)),
            bigquery.ScalarQueryParameter("seller_id", "INT64", int(payload.seller_id)),
            bigquery.ScalarQueryParameter("seller_name", "STRING", (payload.seller_name or "").strip() or None),
            bigquery.ScalarQueryParameter("seller_snapshot", "STRING", _to_json({"id": payload.seller_id, "name": (payload.seller_name or "").strip()})),
            bigquery.ScalarQueryParameter("shipping_method_id", "INT64", int(payload.shipping_method_id)),
            bigquery.ScalarQueryParameter("shipping_method_name", "STRING", shipping_name),
            bigquery.ScalarQueryParameter(
                "freight_method_id",
                "INT64",
                int(payload.freight_method_id) if payload.freight_method_id else None,
            ),
            bigquery.ScalarQueryParameter("freight_method_name", "STRING", freight_name or None),
            bigquery.ScalarQueryParameter("payment_method_code", "STRING", payment_code or None),
            bigquery.ScalarQueryParameter("payment_method_name", "STRING", payment_name),
            bigquery.ScalarQueryParameter("payment_meio", "STRING", payment_meio_final),
            bigquery.ScalarQueryParameter("payment_conta", "STRING", payment_conta_final),
            bigquery.ScalarQueryParameter("payment_due_date", "STRING", _coerce_due_date_not_past(_clean_str(payload.payment_due_date))),
            bigquery.ScalarQueryParameter("payment_category", "STRING", _clean_str(payload.payment_category)),
            bigquery.ScalarQueryParameter("payment_notify", "BOOL", payment_notify),
            bigquery.ScalarQueryParameter("totals", "STRING", _to_json({"net": round(total_net, 2)})),
            bigquery.ScalarQueryParameter("notes", "STRING", payload.notes or ""),
            bigquery.ScalarQueryParameter("payload", "STRING", _to_json(payload.model_dump())),
            bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("quote_id", "STRING", quote_id),
        ])
    ).result()

    del_sql = f"DELETE FROM {_table('quote_items')} WHERE quote_id=@qid"
    bq.query(
        del_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("qid", "STRING", quote_id),
        ])
    ).result()
    _bq_insert_rows("quote_items", items_rows)

    return {
        "status": "OK",
        "quote_id": quote_id,
        "quote_number": existing.get("quote_number"),
        "quote_status": "draft",
        "totals": {"net": round(total_net, 2)},
        "message": "Orçamento atualizado.",
    }



@app.get("/clients/{client_id}/products/{product_id}/last-price")
def get_last_price_for_client_product(client_id: int, product_id: int):
    sql = f"""
    SELECT
      q.quote_id,
      q.quote_number,
      q.tiny_order_number,
      q.status,
      q.internal_status,
      q.created_at,
      qi.product_id,
      qi.qty,
      qi.list_price,
      qi.discount_pct,
      qi.unit_price_disc
    FROM {_table('quotes')} q
    JOIN {_table('quote_items')} qi
      ON qi.quote_id = q.quote_id
    WHERE q.client_id = @client_id
      AND qi.product_id = @product_id
    ORDER BY q.created_at DESC, q.quote_number DESC
    LIMIT 1
    """
    rows = list(bq.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("client_id", "INT64", int(client_id)),
                bigquery.ScalarQueryParameter("product_id", "INT64", int(product_id)),
            ]
        ),
    ).result())

    if not rows:
        return {
            "found": False,
            "client_id": int(client_id),
            "product_id": int(product_id),
        }

    row = rows[0]
    return {
        "found": True,
        "client_id": int(client_id),
        "product_id": int(product_id),
        "quote_id": row.get("quote_id"),
        "quote_number": row.get("quote_number"),
        "tiny_order_number": row.get("tiny_order_number"),
        "status": row.get("status"),
        "internal_status": row.get("internal_status"),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
        "qty": float(row.get("qty") or 0),
        "list_price": float(row.get("list_price") or 0),
        "discount_pct": float(row.get("discount_pct") or 0),
        "unit_price_disc": float(row.get("unit_price_disc") or 0),
    }


def _olist_login_if_needed(page, target_url: str):
    page.goto(target_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    has_email = page.locator('input[type="email"]').count() > 0
    has_password = page.locator('input[type="password"]').count() > 0

    if not has_email and not has_password:
        return

    if not OLIST_UI_EMAIL or not OLIST_UI_PASSWORD:
        raise RuntimeError("OLIST_UI_EMAIL/OLIST_UI_PASSWORD não configurados para automação do Olist.")

    if has_email:
        page.locator('input[type="email"]').first.fill(OLIST_UI_EMAIL)
        btn = page.get_by_role("button", name=re.compile("continuar|entrar|avançar", re.I)).first
        if btn.count():
            btn.click()
        page.wait_for_timeout(1200)

    if page.locator('input[type="password"]').count() > 0:
        page.locator('input[type="password"]').first.fill(OLIST_UI_PASSWORD)
        btn = page.get_by_role("button", name=re.compile("entrar|continuar|acessar", re.I)).first
        if btn.count():
            btn.click()
        page.wait_for_timeout(3000)

    page.goto(target_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)


def _ui_pick_receipt_method(page, option_text: str):
    # tenta select nativo primeiro
    native = page.locator("xpath=(//*[contains(normalize-space(),'Forma de recebimento')]/following::select[1])[1]").first
    if native.count():
        try:
            native.select_option(label=option_text)
            return
        except Exception:
            pass

    # fallback combobox custom
    combo = page.locator("xpath=(//*[contains(normalize-space(),'Forma de recebimento')]/following::*[@role='combobox' or self::input][1])[1]").first
    if not combo.count():
        raise RuntimeError("Campo 'Forma de recebimento' não encontrado na UI do Olist.")

    combo.click()
    page.wait_for_timeout(500)

    option = page.get_by_role("option", name=re.compile(re.escape(option_text), re.I)).first
    if option.count():
        option.click()
        page.wait_for_timeout(700)
        return

    # fallback por texto simples
    page.get_by_text(option_text, exact=False).first.click()
    page.wait_for_timeout(700)


def _olist_fix_link_pagamento_ui(
    tiny_order_id: int,
    tiny_order_number: str = "",
    client_name: str = "",
    due_date_br: str = "",
) -> Dict[str, Any]:
    order_ref = str(tiny_order_number or "").strip()
    client_name = str(client_name or "").strip()
    due_date_br = str(due_date_br or "").strip()

    if not order_ref:
        raise RuntimeError("Número comercial do pedido não informado para localizar conta.")
    if not client_name:
        raise RuntimeError("Nome do cliente não informado para localizar conta.")
    if not due_date_br:
        raise RuntimeError("Vencimento da parcela não informado para localizar conta.")

    # valor da 1ª parcela esperado a partir do pedido
    try:
        pedido_raw = tiny.obter_pedido(int(tiny_order_id))
        pedido_dbg = _extract_tiny_order_debug(pedido_raw)
    except Exception as e:
        raise RuntimeError(f"Falha ao obter pedido para identificar parcela: {e}")

    parcelas = (pedido_dbg or {}).get("parcelas") or []
    if not parcelas:
        raise RuntimeError("Pedido sem parcelas no retorno do Tiny.")

    expected_amount = round(float(parcelas[0].get("valor") or 0), 2)
    expected_due = str(parcelas[0].get("data_vencimento") or "").strip() or due_date_br

    try:
        base_due = dt.datetime.strptime(expected_due, "%d/%m/%Y")
    except Exception:
        try:
            base_due = dt.datetime.strptime(due_date_br, "%d/%m/%Y")
        except Exception:
            base_due = dt.datetime.now()

    ini = (base_due - dt.timedelta(days=3)).strftime("%d/%m/%Y")
    fim = (base_due + dt.timedelta(days=3)).strftime("%d/%m/%Y")

    candidates = []
    scanned = []

    for pagina in range(1, 6):
        try:
            search = tiny.pesquisar_contas_receber(
                nome_cliente=client_name,
                data_ini_vencimento=ini,
                data_fim_vencimento=fim,
                situacao="aberto",
                pagina=pagina,
            )
        except Exception as e:
            print("OLIST_LINK_UI_SEARCH_PAGE_ERROR:", json.dumps({"pagina": pagina, "error": str(e)}, ensure_ascii=False))
            continue

        contas = search.get("contas") or []
        if not contas:
            continue

        for item in contas:
            conta = item.get("conta", item) if isinstance(item, dict) else {}
            historico = str(conta.get("historico") or "").strip()
            nome_cliente_item = str(conta.get("nome_cliente") or "").strip()
            venc_item = str(conta.get("data_vencimento") or "").strip()
            numero_doc_item = str(conta.get("numero_doc") or "").strip()
            situacao_item = str(conta.get("situacao") or "").strip().lower()

            try:
                valor_item = round(float(str(conta.get("valor") or "0").replace(",", ".")), 2)
            except Exception:
                valor_item = 0.0

            scanned.append({
                "pagina": pagina,
                "historico": historico,
                "nome_cliente": nome_cliente_item,
                "data_vencimento": venc_item,
                "valor": valor_item,
                "situacao": situacao_item,
                "numero_doc": numero_doc_item,
            })

            historico_ok = (
                f"pedido de venda nº {order_ref}".lower() in historico.lower()
                or f"pedido de venda n° {order_ref}".lower() in historico.lower()
                or f"pedido de venda no {order_ref}".lower() in historico.lower()
            )
            cliente_ok = nome_cliente_item.strip().lower() == client_name.strip().lower()
            venc_ok = venc_item == expected_due
            valor_ok = abs(valor_item - expected_amount) < 0.01
            situacao_ok = situacao_item in ("aberto", "open", "")

            if historico_ok and cliente_ok and venc_ok and valor_ok and situacao_ok:
                candidates.append(conta)

    print("OLIST_LINK_UI_SEARCH:", json.dumps({
        "tiny_order_id": tiny_order_id,
        "tiny_order_number": order_ref,
        "client_name": client_name,
        "expected_due": expected_due,
        "expected_amount": expected_amount,
        "range_ini": ini,
        "range_fim": fim,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "scanned_count": len(scanned),
        "scanned_sample": scanned[:30],
    }, ensure_ascii=False))

    if len(candidates) != 1:
        raise RuntimeError(f"Identificação insegura da conta: encontrados {len(candidates)} matches para o pedido {order_ref}.")

    conta = candidates[0]
    numero_doc = str(conta.get("numero_doc") or "").strip()
    if not numero_doc:
        raise RuntimeError(f"Conta identificada sem numero_doc para o pedido {order_ref}.")

    target_url = "https://erp.olist.com/contas_receber"
    browser = _get_pdf_browser()
    context = browser.new_context()
    page = context.new_page()

    try:
        _olist_login_if_needed(page, target_url)

        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        search_input = page.locator('input[placeholder*="Pesquise por cliente"], input[placeholder*="nº doc"], input[placeholder*="no banco"]').first
        if not search_input.count():
            raise RuntimeError("Campo de busca de Contas a Receber não encontrado.")

        search_input.fill(numero_doc)
        page.wait_for_timeout(1200)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)

        row_link = page.locator('a[href*="contas_receber#edit/"]').first
        if not row_link.count():
            raise RuntimeError(f"Nenhuma conta encontrada na UI para o nº doc {numero_doc}.")
        href = row_link.get_attribute("href") or ""
        account_url = href if href.startswith("http") else f"https://erp.olist.com{href}"

        print("OLIST_LINK_UI_ACCOUNT_URL:", account_url)

        page.goto(account_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        body_text = page.locator("body").inner_text()

        if client_name.lower() not in body_text.lower():
            raise RuntimeError(f"Validação falhou: cliente '{client_name}' não encontrado na conta.")
        if f"pedido de venda nº {order_ref}".lower() not in body_text.lower() and f"pedido de venda n° {order_ref}".lower() not in body_text.lower():
            raise RuntimeError(f"Validação falhou: referência do pedido {order_ref} não encontrada na conta.")
        if numero_doc not in body_text:
            raise RuntimeError(f"Validação falhou: numero_doc {numero_doc} não encontrado na conta.")

        edit_btn = page.get_by_role("button", name=re.compile("editar", re.I)).first
        if not edit_btn.count():
            raise RuntimeError("Botão Editar não encontrado na conta a receber.")
        edit_btn.click()
        page.wait_for_timeout(1500)

        _ui_pick_receipt_method(page, "Pix")
        page.mouse.click(5, 5)
        page.wait_for_timeout(500)
        _ui_pick_receipt_method(page, "Link de pagamento")

        save_btn = page.get_by_role("button", name=re.compile("salvar", re.I)).first
        if not save_btn.count():
            raise RuntimeError("Botão Salvar não encontrado na conta a receber.")
        save_btn.click()
        page.wait_for_timeout(2500)

        return {
            "ok": True,
            "target_url": target_url,
            "account_url": account_url,
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": order_ref,
            "client_name": client_name,
            "numero_doc": numero_doc,
            "expected_due": expected_due,
            "expected_amount": expected_amount,
            "action": "safe_match_then_edit_pix_link_save",
        }
    finally:
        try:
            context.close()
        except Exception:
            pass

@app.post("/quotes/{quote_id}/create-order")
def create_order_from_quote(quote_id: str):
    quote = _bq_get_quote(quote_id)
    if quote.get("tiny_order_id"):
        tiny_id = quote["tiny_order_id"]
        return {
            "status": "OK",
            "message": "Pedido já havia sido criado.",
            "tiny_order_id": tiny_id,
            "tiny_order_number": quote.get("tiny_order_number"),
            "open_url": f"{ERP_BASE_URL}#edit/{tiny_id}",
        }

    items = _bq_get_quote_items(quote_id)
    if not items:
        raise HTTPException(status_code=400, detail="Orçamento não possui itens.")

    stock_errors = []

    for it in items:
        product_id = it.get("product_id")
        qty = float(it.get("qty") or 0)

        if not product_id or qty <= 0:
            continue

        try:
            stock_resp = tiny.obter_estoque_produto(int(product_id))
            stock_raw = stock_resp.get("produto") or stock_resp.get("estoque") or stock_resp or {}

            saldo = float(stock_raw.get("saldo") or 0)
            reservado = float(
                stock_raw.get("saldoReservado")
                or stock_raw.get("saldo_reservado")
                or 0
            )
            saldo_disponivel_raw = (
                stock_raw.get("saldoDisponivel")
                or stock_raw.get("saldo_disponivel")
                or stock_raw.get("saldo_disponível")
            )

            if saldo_disponivel_raw is not None and str(saldo_disponivel_raw).strip() != "":
                disponivel = float(saldo_disponivel_raw)
            else:
                disponivel = max(0.0, saldo - reservado)

            if qty > disponivel:
                stock_errors.append(
                    f'{it.get("name_snapshot") or f"Produto {product_id}"} '
                    f'(qtd: {qty:g}, estoque: {disponivel:g})'
                )

        except TinyAPIError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Erro ao validar estoque do produto {product_id}: {e}",
            )

    if stock_errors:
        raise HTTPException(
            status_code=400,
            detail="Estoque insuficiente para criar o pedido: " + "; ".join(stock_errors),
        )

    client_raw = _from_json(quote.get("client_snapshot")) or {}
    client_name = (client_raw.get("nome") or "").strip()
    if not client_name:
        raise HTTPException(status_code=400, detail="Cliente sem nome no snapshot.")

    def _parse_iso_date(s: str):
        try:
            return dt.datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None

    def _build_parcelas(total_value: float, payment_code: Optional[str], meio_txt: Optional[str], portador_txt: Optional[str]) -> List[Dict[str, Any]]:
        payload_saved = _from_json(quote.get("payload")) or {}
        installments = payload_saved.get("payment_installments") or []
        quote_due_date = _parse_iso_date(str(quote.get("payment_due_date") or "").strip())
        base_date = quote_due_date or dt.datetime.utcnow().date()
        parcelas_payload: List[Dict[str, Any]] = []

        if isinstance(installments, list) and installments:
            for p in installments:
                if not isinstance(p, dict):
                    continue

                due = str(p.get("due_date") or "").strip()
                val = p.get("amount") or 0

                try:
                    valf = float(val)
                except Exception:
                    valf = 0.0

                if valf <= 0:
                    continue

                due_date = _parse_iso_date(due)
                dias = 0
                data_txt = None

                if due_date:
                    dias = max(0, (due_date - base_date).days)
                    data_txt = due_date.strftime("%d/%m/%Y")

                parcela = {
                    "dias": int(dias),
                    "valor": round(valf, 2),
                    "destino": "Contas a Receber",
                }

                if data_txt:
                    parcela["data"] = data_txt

                if payment_code:
                    parcela["forma_pagamento"] = payment_code

                if meio_txt:
                    parcela["meio_pagamento"] = meio_txt
                if portador_txt:
                    parcela["portador"] = portador_txt

                parcelas_payload.append({"parcela": parcela})

        if not parcelas_payload and total_value > 0:
            parcela = {
                "dias": 0,
                "valor": round(float(total_value), 2),
                "data": base_date.strftime("%d/%m/%Y"),
                "destino": "Contas a Receber",
            }

            if payment_code:
                parcela["forma_pagamento"] = payment_code

            if meio_txt:
                parcela["meio_pagamento"] = meio_txt
            if portador_txt:
                parcela["portador"] = portador_txt

            parcelas_payload.append({"parcela": parcela})

        return parcelas_payload

    itens_payload = []
    total_pedido = 0.0

    for it in items:
        qty = float(it.get("qty") or 0)
        unit_disc = float(it.get("unit_price_disc") or 0)
        if qty <= 0 or unit_disc <= 0:
            continue

        sku = it.get("sku_snapshot") or ""
        name = it.get("name_snapshot") or ""
        product_id = int(it.get("product_id")) if it.get("product_id") is not None else None

        line_total = round(qty * unit_disc, 2)
        total_pedido = round(total_pedido + line_total, 2)

        itens_payload.append({
            "item": {
                "id_produto": product_id,
                "codigo": sku,
                "descricao": name,
                "unidade": "Un",
                "quantidade": qty,
                "valor_unitario": round(unit_disc, 2),
            }
        })

    if not itens_payload:
        raise HTTPException(status_code=400, detail="Nenhum item válido para criar pedido.")

    forma_envio = (quote.get("shipping_method_name") or "").strip()
    forma_frete = (quote.get("freight_method_name") or "").strip()

    payload_saved = _from_json(quote.get("payload")) or {}
    freight_paid_client = float(payload_saved.get("freight_paid_client") or 0)
    freight_paid_company = float(payload_saved.get("freight_paid_company") or 0)

    payment_code = _map_payment_code_for_tiny(quote.get("payment_method_code"))
    meio_txt = _resolve_meio_pagamento_tiny(quote.get("payment_meio"), quote.get("payment_conta"))
    portador_txt = _resolve_portador_nome(quote.get("payment_conta"))

    if payment_code == "link_pagamento":
        portador_txt = None

    parcelas_payload = _build_parcelas(total_pedido, payment_code or None, meio_txt, portador_txt)

    cliente_payload = {
        "nome": client_name,
        "atualizar_cliente": "N",
    }

    cpf_cnpj = _pick_first_nonempty(client_raw, "cpf_cnpj")
    email = _pick_first_nonempty(client_raw, "email")
    fone = _pick_first_nonempty(client_raw, "fone", "telefone")
    tipo_pessoa = _pick_first_nonempty(client_raw, "tipo_pessoa")
    ie = _pick_first_nonempty(client_raw, "ie")
    rg = _pick_first_nonempty(client_raw, "rg")
    endereco = _pick_first_nonempty(client_raw, "endereco")
    numero = _pick_first_nonempty(client_raw, "numero")
    complemento = _pick_first_nonempty(client_raw, "complemento")
    bairro = _pick_first_nonempty(client_raw, "bairro")
    cep = _pick_first_nonempty(client_raw, "cep")
    cidade = _pick_first_nonempty(client_raw, "cidade")
    uf = _pick_first_nonempty(client_raw, "uf")
    pais = _pick_first_nonempty(client_raw, "pais", "nome_pais")

    if cpf_cnpj:
        cliente_payload["cpf_cnpj"] = cpf_cnpj
    if email:
        cliente_payload["email"] = email
    if fone:
        cliente_payload["fone"] = fone
    if tipo_pessoa:
        cliente_payload["tipo_pessoa"] = tipo_pessoa
    if ie:
        cliente_payload["ie"] = ie
    if rg:
        cliente_payload["rg"] = rg
    if endereco:
        cliente_payload["endereco"] = endereco
    if numero:
        cliente_payload["numero"] = numero
    if complemento:
        cliente_payload["complemento"] = complemento
    if bairro:
        cliente_payload["bairro"] = bairro
    if cep:
        cliente_payload["cep"] = cep
    if cidade:
        cliente_payload["cidade"] = cidade
    if uf:
        cliente_payload["uf"] = uf
    if pais:
        cliente_payload["pais"] = pais

    pedido_payload = {
        "pedido": {
            "id_vendedor": int(quote.get("seller_id") or 0),
            "data_pedido": dt.datetime.now().strftime("%d/%m/%Y"),
            "cliente": cliente_payload,
            "itens": itens_payload,
            "obs": (quote.get("notes") or "").strip(),
            "situacao": "aberto",
            **({"forma_pagamento": payment_code} if payment_code else {}),
            **({"meio_pagamento": meio_txt} if meio_txt else {}),
            **({"portador": portador_txt} if portador_txt else {}),
            **({"parcelas": parcelas_payload} if parcelas_payload else {}),
            **({"forma_envio": forma_envio} if forma_envio else {}),
            **({"forma_frete": forma_frete} if forma_frete else {}),
            **({"valor_frete": round(freight_paid_client, 2)} if freight_paid_client > 0 else {}),
            **({"outras_despesas": round(freight_paid_company, 2)} if freight_paid_company > 0 else {}),
        }
    }

    print("QUOTE payment_method_code:", quote.get("payment_method_code"))
    print("QUOTE payment_meio:", quote.get("payment_meio"))
    print("QUOTE payment_conta:", quote.get("payment_conta"))
    print("QUOTE payload raw:", quote.get("payload"))
    print("LINK_DEBUG quote_id:", quote_id)
    print("LINK_DEBUG payment_code:", payment_code)
    print("LINK_DEBUG meio_txt:", meio_txt)
    print("LINK_DEBUG portador_txt:", portador_txt)
    print("LINK_DEBUG parcelas_payload:", json.dumps(parcelas_payload, ensure_ascii=False))
    print("TINY create-order payload:", json.dumps(pedido_payload, ensure_ascii=False))

    try:
        resp = tiny.criar_pedido(pedido_payload)
        print("TINY criar_pedido response:", json.dumps(resp, ensure_ascii=False))
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    reg = ((resp.get("registros") or {}).get("registro") or {})
    tiny_id = reg.get("id")
    tiny_num = reg.get("numero")

    if not tiny_id:
        raise HTTPException(
            status_code=502,
            detail=f"Pedido não retornou id no Tiny. Resposta: {resp}",
        )

    tiny_order_raw = None
    tiny_order_debug = None
    try:
        tiny_order_raw = tiny.obter_pedido(int(tiny_id))
        print("TINY pedido.obter response:", json.dumps(tiny_order_raw, ensure_ascii=False))
        tiny_order_debug = _extract_tiny_order_debug(tiny_order_raw)
        print("TINY pedido.obter summary:", json.dumps(tiny_order_debug, ensure_ascii=False))
    except TinyAPIError as e:
        print(f"TINY pedido.obter error: {e}")

    link_ui_fix = None
    if payment_code == "link_pagamento":
        if ENABLE_OLIST_LINK_UI_FIX:
            try:
                order_number_ref = str(
                    (tiny_order_debug or {}).get("numero")
                    or tiny_num
                    or ""
                ).strip()

                due_date_ref = str(
                    (((tiny_order_debug or {}).get("parcelas") or [{}])[0].get("data_vencimento"))
                    or ((((quote.get("payload") and json.loads(quote.get("payload"))) or {}).get("payment_installments")) or [{}])[0].get("due_date")
                    or (quote.get("payment_due_date") or "")
                ).strip()

                client_name_ref = str(
                    (client_raw.get("nome") or client_name or "")
                ).strip()

                print("OLIST_LINK_UI_ORDER_REF:", order_number_ref)
                print("OLIST_LINK_UI_DUE_REF:", due_date_ref)
                print("OLIST_LINK_UI_CLIENT_REF:", client_name_ref)

                link_ui_fix = _olist_fix_link_pagamento_ui(
                    int(tiny_id),
                    order_number_ref,
                    client_name_ref,
                    due_date_ref,
                )
                print("OLIST_LINK_UI_FIX:", json.dumps(link_ui_fix, ensure_ascii=False))
            except Exception as e:
                link_ui_fix = {"ok": False, "error": str(e), "tiny_order_id": int(tiny_id)}
                print("OLIST_LINK_UI_FIX_ERROR:", str(e))
        else:
            link_ui_fix = {"ok": False, "skipped": True, "reason": "disabled", "tiny_order_id": int(tiny_id)}
            print("OLIST_LINK_UI_FIX_SKIPPED:", json.dumps(link_ui_fix, ensure_ascii=False))

    upd_sql = f"""
    UPDATE {_table('quotes')}
    SET status='ordered',
        tiny_order_id=@tid,
        tiny_order_number=@tnum,
        internal_status='Em Aberto',
        updated_at=@u
    WHERE quote_id=@id
    """
    bq.query(
        upd_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("tid", "INT64", int(tiny_id)),
            bigquery.ScalarQueryParameter("tnum", "STRING", str(tiny_num) if tiny_num else None),
            bigquery.ScalarQueryParameter("u", "TIMESTAMP", _now_utc()),
            bigquery.ScalarQueryParameter("id", "STRING", quote_id),
        ])
    ).result()

    open_url = f"{ERP_BASE_URL}#edit/{tiny_id}"

    return {
        "status": "OK",
        "quote_id": quote_id,
        "quote_status": "ordered",
        "internal_status": "Em Aberto",
        "tiny_order_id": int(tiny_id),
        "tiny_order_number": str(tiny_num) if tiny_num else None,
        "open_url": open_url,
        "sent_payload": pedido_payload,
        "tiny_response": resp,
        "tiny_order_debug": tiny_order_debug,
        "link_ui_fix": link_ui_fix,
    }


@app.post("/quotes/{quote_id}/cancel-order")
def cancel_order_from_quote(quote_id: str, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem cancelar pedidos.")

    quote = _bq_get_quote(quote_id)

    tiny_order_id = quote.get("tiny_order_id")
    if not tiny_order_id:
        raise HTTPException(status_code=400, detail="Pedido ainda não foi criado para este orçamento.")

    current_internal = str(quote.get("internal_status") or "").strip()
    if current_internal == "Cancelado":
        return {
            "status": "OK",
            "message": "Pedido já estava cancelado.",
            "quote_id": quote_id,
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": quote.get("tiny_order_number"),
            "internal_status": "Cancelado",
        }

    _tiny_sync_and_verify_status(
        int(tiny_order_id),
        "cancelado",
        "cancel-order",
    )

    now_ts = _now_utc()

    upd_sql = f"""
    UPDATE {_table('quotes')}
    SET internal_status='Cancelado',
        updated_at=@u
    WHERE quote_id=@id
    """
    bq.query(
        upd_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "TIMESTAMP", now_ts),
            bigquery.ScalarQueryParameter("id", "STRING", quote_id),
        ])
    ).result()

    sep_upd_sql = f"""
    UPDATE {_table('separation_orders')}
    SET status='Cancelado',
        updated_at=@u
    WHERE tiny_order_id=@tiny_order_id
    """
    bq.query(
        sep_upd_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "TIMESTAMP", now_ts),
            bigquery.ScalarQueryParameter("tiny_order_id", "INT64", int(tiny_order_id)),
        ])
    ).result()

    return {
        "status": "OK",
        "message": "Pedido cancelado com sucesso.",
        "quote_id": quote_id,
        "tiny_order_id": int(tiny_order_id),
        "tiny_order_number": quote.get("tiny_order_number"),
        "internal_status": "Cancelado",
    }


@app.post("/quotes/{quote_id}/approve-order")
def approve_order_from_quote(quote_id: str, request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem aprovar pedidos.")

    quote = _bq_get_quote(quote_id)

    tiny_order_id = quote.get("tiny_order_id")
    if not tiny_order_id:
        raise HTTPException(status_code=400, detail="Pedido ainda não foi criado para este orçamento.")

    current_internal = str(quote.get("internal_status") or "").strip()
    if current_internal == "Aprovado":
        return {
            "status": "OK",
            "message": "Pedido já estava aprovado.",
            "quote_id": quote_id,
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": quote.get("tiny_order_number"),
            "internal_status": "Aprovado",
        }

    if ENABLE_TINY_STATUS_SYNC:
        before_resp = tiny.obter_pedido(int(tiny_order_id))
        before_status_raw = _tiny_order_status_text(before_resp)
        before_status = _norm_text(before_status_raw)

        if before_status != "aprovado":
            sync_resp = _tiny_change_order_status(int(tiny_order_id), "aprovado")
            print("[TINY_STATUS_SYNC] approve-order response:", json.dumps(sync_resp, ensure_ascii=False))

            after_resp = tiny.obter_pedido(int(tiny_order_id))
            after_status_raw = _tiny_order_status_text(after_resp)
            after_status = _norm_text(after_status_raw)

            print("[TINY_STATUS_SYNC] approve-order verify:", json.dumps({
                "tiny_order_id": int(tiny_order_id),
                "before_status_raw": before_status_raw,
                "before_status_norm": before_status,
                "after_status_raw": after_status_raw,
                "after_status_norm": after_status,
            }, ensure_ascii=False))

            if after_status != "aprovado":
                raise HTTPException(
                    status_code=502,
                    detail=f"Pedido não ficou aprovado no Tiny. Status atual: {after_status_raw or 'desconhecido'}"
                )

    now_approved = _now_utc()

    payload_saved = _from_json(quote.get("payload")) or {}
    payload_saved["approved_at"] = now_approved.isoformat()

    upd_sql = f"""
    UPDATE {_table('quotes')}
    SET internal_status='Aprovado',
        updated_at=@u,
        payload=@payload
    WHERE quote_id=@id
    """
    bq.query(
        upd_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "TIMESTAMP", now_approved),
            bigquery.ScalarQueryParameter("payload", "STRING", _to_json(payload_saved)),
            bigquery.ScalarQueryParameter("id", "STRING", quote_id),
        ])
    ).result()

    client_raw = _from_json(quote.get("client_snapshot")) or {}
    client_name = (client_raw.get("nome") or quote.get("client_name") or "").strip()

    try:
        _upsert_separation_order(
            tiny_order_id=int(tiny_order_id),
            tiny_order_number=str(quote.get("tiny_order_number")) if quote.get("tiny_order_number") else None,
            quote_id=quote_id,
            quote_number=quote.get("quote_number"),
            client_name=client_name or None,
            seller_name=quote.get("seller_name") or None,
            status=_separation_status_default(),
            printed=False,
        )
    except Exception as e:
        print("[APPROVE_ORDER] separation upsert failed after local+tiny approval:", str(e))

    return {
        "status": "OK",
        "message": "Pedido aprovado com sucesso.",
        "quote_id": quote_id,
        "tiny_order_id": int(tiny_order_id),
        "tiny_order_number": quote.get("tiny_order_number"),
        "internal_status": "Aprovado",
    }


@app.post("/quotes/{quote_id}/mark-invoiced")
def mark_quote_as_invoiced(quote_id: str):
    quote = _bq_get_quote(quote_id)

    tiny_order_id = quote.get("tiny_order_id")
    if not tiny_order_id:
        raise HTTPException(status_code=400, detail="Pedido ainda não foi criado para este orçamento.")

    current_internal = str(quote.get("internal_status") or "").strip()
    if current_internal == "Faturado":
        return {
            "status": "OK",
            "message": "Pedido já estava faturado.",
            "quote_id": quote_id,
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": quote.get("tiny_order_number"),
            "internal_status": "Faturado",
        }

    now_ts = _now_utc()

    upd_sql = f"""
    UPDATE {_table('quotes')}
    SET internal_status='Faturado',
        updated_at=@u
    WHERE quote_id=@id
    """
    bq.query(
        upd_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "TIMESTAMP", now_ts),
            bigquery.ScalarQueryParameter("id", "STRING", quote_id),
        ])
    ).result()

    sep_upd_sql = f"""
    UPDATE {_table('separation_orders')}
    SET status='Entregue',
        updated_at=@u
    WHERE tiny_order_id=@tiny_order_id
    """
    bq.query(
        sep_upd_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "TIMESTAMP", now_ts),
            bigquery.ScalarQueryParameter("tiny_order_id", "INT64", int(tiny_order_id)),
        ])
    ).result()

    if ENABLE_TINY_STATUS_SYNC:
        _tiny_sync_and_verify_status(
            int(tiny_order_id),
            "faturado",
            "mark-invoiced",
        )

    return {
        "status": "OK",
        "message": "Pedido marcado como faturado.",
        "quote_id": quote_id,
        "tiny_order_id": int(tiny_order_id),
        "tiny_order_number": quote.get("tiny_order_number"),
        "internal_status": "Faturado",
    }



class SeparationStatusIn(BaseModel):
    status: Optional[str] = None
    printed: Optional[bool] = None
    assigned_to: Optional[str] = None
    notes: Optional[str] = None
    packaging_boxes: Optional[int] = None
    packaging_bags: Optional[int] = None
    packaging_weight_kg: Optional[float] = None
    packaging_height_cm: Optional[float] = None
    packaging_width_cm: Optional[float] = None
    packaging_length_cm: Optional[float] = None
    packaging_volumes: Optional[int] = None
    internal_status: Optional[str] = None


SEPARATION_STATUSES = {"A separar", "Separando", "Separado", "Conferido"}


@app.get("/separation/orders")
def list_separation_orders(
    request: Request,
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if not _can_access_separation(request):
        raise HTTPException(status_code=403, detail="Acesso negado à área de separação.")

    derived_status_sql = """
    CASE
      WHEN LOWER(COALESCE(s.status, '')) = 'cancelado' THEN 'Cancelado'
      WHEN LOWER(COALESCE(q.internal_status, '')) = 'cancelado' THEN 'Cancelado'
      WHEN LOWER(COALESCE(q.status, '')) IN ('cancelado', 'canceled', 'cancelled') THEN 'Cancelado'
      WHEN LOWER(COALESCE(q.internal_status, '')) = 'faturado' THEN 'Entregue'
      WHEN LOWER(COALESCE(q.internal_status, '')) = 'pronto para envio' THEN 'Separado'
      WHEN LOWER(COALESCE(q.internal_status, '')) = 'preparando envio' THEN 'Separando'
      ELSE COALESCE(s.status, 'A separar')
    END
    """

    where_parts = [
        "q.tiny_order_id IS NOT NULL"
    ]
    params = [
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
        bigquery.ScalarQueryParameter("offset", "INT64", offset),
    ]

    if status:
        where_parts.append(f"({derived_status_sql}) = @status")
        params.insert(0, bigquery.ScalarQueryParameter("status", "STRING", status))

    if q:
        where_parts.append("(CAST(q.tiny_order_number AS STRING) LIKE @q OR LOWER(COALESCE(JSON_EXTRACT_SCALAR(q.client_snapshot, '$.nome'), '')) LIKE @q OR LOWER(COALESCE(q.seller_name, '')) LIKE @q)")
        params.insert(0, bigquery.ScalarQueryParameter("q", "STRING", f"%{str(q).lower()}%"))

    where_sql = " AND ".join(where_parts)

    sql = f"""
    SELECT
      q.quote_id,
      q.quote_number,
      q.tiny_order_id,
      q.tiny_order_number,
      COALESCE(JSON_EXTRACT_SCALAR(q.client_snapshot, '$.nome'), JSON_EXTRACT_SCALAR(q.client_snapshot, '$.name')) AS client_name,
      q.seller_name,
      q.shipping_method_name,
      q.freight_method_name,
      q.internal_status,
      q.created_at,
      q.updated_at,
      {derived_status_sql} AS separation_status,
      COALESCE(s.printed, FALSE) AS printed,
      s.printed_at,
      s.started_at,
      s.separated_at,
      s.checked_at,
      s.assigned_to,
      s.notes,
      s.packaging_boxes,
      s.packaging_bags,
      s.packaging_weight_kg,
      s.packaging_height_cm,
      s.packaging_width_cm,
      s.packaging_length_cm,
      s.packaging_volumes
    FROM {_table('quotes')} q
    LEFT JOIN {_table('separation_orders')} s
      ON q.tiny_order_id = s.tiny_order_id
    WHERE {where_sql}
    ORDER BY q.created_at DESC
    LIMIT @limit OFFSET @offset
    """

    rows = [dict(r) for r in bq.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()]
    response = JSONResponse(content=jsonable_encoder({"items": rows, "limit": limit, "offset": offset, "status_filter": status, "q": q}))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/separation/orders/{tiny_order_id}")
def get_separation_order(tiny_order_id: int, request: Request):
    if not _can_access_separation(request):
        raise HTTPException(status_code=403, detail="Acesso negado à área de separação.")

    sql = f"""
    SELECT
      q.quote_id, q.quote_number, q.tiny_order_id, q.tiny_order_number, q.client_snapshot, q.seller_name,
      q.shipping_method_name, q.freight_method_name,
      q.payment_method_code, q.payment_method_name, q.payment_meio, q.payment_conta,
      q.payment_due_date, q.payment_category, q.totals, q.payload,
      q.notes, q.created_at, q.updated_at,
      CASE
        WHEN LOWER(COALESCE(q.internal_status, '')) = 'cancelado' THEN 'Cancelado'
        WHEN LOWER(COALESCE(q.internal_status, '')) = 'faturado' THEN 'Entregue'
        WHEN LOWER(COALESCE(q.internal_status, '')) = 'pronto para envio' THEN 'Separado'
        WHEN LOWER(COALESCE(q.internal_status, '')) = 'preparando envio' THEN 'Separando'
        ELSE COALESCE(s.status, 'A separar')
      END AS separation_status,
      COALESCE(s.printed, FALSE) AS printed,
      s.printed_at, s.started_at, s.separated_at, s.checked_at, s.assigned_to, s.notes AS separation_notes,
      s.packaging_boxes, s.packaging_bags,
      s.packaging_weight_kg, s.packaging_height_cm, s.packaging_width_cm, s.packaging_length_cm, s.packaging_volumes
    FROM {_table('quotes')} q
    LEFT JOIN {_table('separation_orders')} s
      ON q.tiny_order_id = s.tiny_order_id
    WHERE q.tiny_order_id = @tiny_order_id
    LIMIT 1
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("tiny_order_id", "INT64", tiny_order_id)])
    rows = [dict(r) for r in bq.query(sql, job_config=cfg).result()]
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido de separação não encontrado.")
    row = rows[0]
    items = _bq_get_quote_items(row["quote_id"])
    return {"order": row, "items": items}


@app.patch("/separation/orders/{tiny_order_id}")
def update_separation_order(tiny_order_id: int, payload: SeparationStatusIn, request: Request):
    if not _can_access_separation(request):
        raise HTTPException(status_code=403, detail="Acesso negado à área de separação.")

    status = payload.status
    if status is not None and status not in SEPARATION_STATUSES:
        raise HTTPException(status_code=400, detail="Status de separação inválido.")

    q_sql = f"SELECT quote_id, quote_number, tiny_order_number, JSON_EXTRACT_SCALAR(client_snapshot, '$.nome') AS client_name, seller_name FROM {_table('quotes')} WHERE tiny_order_id=@tid LIMIT 1"
    cfg = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("tid", "INT64", tiny_order_id)])
    rows = [dict(r) for r in bq.query(q_sql, job_config=cfg).result()]
    if not rows:
        raise HTTPException(status_code=404, detail="Pedido não encontrado na base local.")
    qrow = rows[0]

    now = _now_utc()
    _upsert_separation_order(
        tiny_order_id=tiny_order_id,
        tiny_order_number=qrow.get("tiny_order_number"),
        quote_id=qrow.get("quote_id"),
        quote_number=qrow.get("quote_number"),
        client_name=qrow.get("client_name"),
        seller_name=qrow.get("seller_name"),
        status=status,
        printed=payload.printed,
        assigned_to=payload.assigned_to,
        notes=payload.notes,
        packaging_boxes=payload.packaging_boxes,
        packaging_bags=payload.packaging_bags,
        packaging_weight_kg=payload.packaging_weight_kg,
        packaging_height_cm=payload.packaging_height_cm,
        packaging_width_cm=payload.packaging_width_cm,
        packaging_length_cm=payload.packaging_length_cm,
        packaging_volumes=payload.packaging_volumes,
    )

    extra_sets = []
    extra_params = [
        bigquery.ScalarQueryParameter("tid", "INT64", tiny_order_id),
        bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
    ]
    if status == "Separando":
        extra_sets.append("started_at = IFNULL(started_at, @now)")
    if status == "Separado":
        extra_sets.append("separated_at = IFNULL(separated_at, @now)")
    if status == "Conferido":
        extra_sets.append("checked_at = IFNULL(checked_at, @now)")
    if payload.printed is True:
        extra_sets.append("printed_at = IFNULL(printed_at, @now)")
    if extra_sets:
        sql = f"UPDATE {_table('separation_orders')} SET {', '.join(extra_sets)}, updated_at=@now WHERE tiny_order_id=@tid"
        bq.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=extra_params)).result()

    if payload.internal_status:
        q_upd_sql = f"""
        UPDATE {_table('quotes')}
        SET internal_status=@internal_status,
            updated_at=@now
        WHERE tiny_order_id=@tid
        """
        bq.query(
            q_upd_sql,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("tid", "INT64", tiny_order_id),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("internal_status", "STRING", payload.internal_status),
            ])
        ).result()

        # API antiga só fica como fallback quando a V3 de separação estiver desligada.
        if (
            ENABLE_TINY_STATUS_SYNC
            and not _tiny_v3_separation_sync_enabled()
            and _norm_text(payload.internal_status) == "preparando envio"
        ):
            _tiny_sync_and_verify_status(
                int(tiny_order_id),
                "preparando envio",
                "separation-preparing-shipment",
            )

    v3_separation_sync = None

    # Integração segura com Separação oficial Tiny/Olist V3.
    # Não quebra o fluxo local se a V3 falhar ou se não existir separação oficial.
    if status in ("Separando", "Separado"):
        target_v3_situacao = 4 if status == "Separando" else 2

        try:
            numero_pedido_v3 = qrow.get("tiny_order_number")
            if numero_pedido_v3:
                v3_separation_sync = _sync_tiny_v3_separation_by_order_number(
                    numero_pedido=int(numero_pedido_v3),
                    target_situacao=target_v3_situacao,
                    dry_run=False,
                    confirm=True,
                    max_pages=10,
                    updated_by=getattr(request.state, "user_email", "") or "separation-flow",
                )
            else:
                v3_separation_sync = {
                    "ok": False,
                    "erro": "Pedido local sem tiny_order_number; não foi possível sincronizar separação V3.",
                    "updated": False,
                }

            print("[TINY_V3_SEPARATION_SYNC]", json.dumps({
                "tiny_order_id": int(tiny_order_id),
                "tiny_order_number": qrow.get("tiny_order_number"),
                "local_status": status,
                "target_v3_situacao": target_v3_situacao,
                "result": v3_separation_sync,
            }, ensure_ascii=False, default=str))

        except Exception as e:
            v3_separation_sync = {
                "ok": False,
                "updated": False,
                "erro": str(e)[:1500],
                "observacao": "Falha na sincronização V3. Fluxo local foi preservado.",
            }
            print("[TINY_V3_SEPARATION_SYNC_ERROR]", json.dumps({
                "tiny_order_id": int(tiny_order_id),
                "tiny_order_number": qrow.get("tiny_order_number"),
                "local_status": status,
                "target_v3_situacao": target_v3_situacao,
                "error": str(e),
            }, ensure_ascii=False, default=str))

    if payload.status == "Separado":
        q_upd_sql = f"""
        UPDATE {_table('quotes')}
        SET internal_status='Pronto para Envio',
            updated_at=@now
        WHERE tiny_order_id=@tid
        """
        bq.query(
            q_upd_sql,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("tid", "INT64", tiny_order_id),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            ])
        ).result()

        # API antiga só fica como fallback quando a V3 de separação estiver desligada.
        if ENABLE_TINY_STATUS_SYNC and not _tiny_v3_separation_sync_enabled():
            _tiny_sync_and_verify_status(
                int(tiny_order_id),
                "pronto para envio",
                "separation-ready-to-ship",
            )

    return {
        "status": "OK",
        "tiny_order_id": tiny_order_id,
        "v3_separation_sync": v3_separation_sync,
    }


def _escape(s: Any) -> str:
    s = "" if s is None else str(s)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#039;")
    )


def _money(n: Any) -> str:
    try:
        v = float(n or 0)
    except Exception:
        v = 0.0
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _get_totals_net(quote: Dict[str, Any]) -> float:
    try:
        t = json.loads(quote.get("totals") or "{}")
        return float(t.get("net") or 0)
    except Exception:
        return 0.0


def _extract_condition_and_installments(quote: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
    condicao = ""
    parcelas: List[Dict[str, Any]] = []
    try:
        payload = json.loads(quote.get("payload") or "{}")
        condicao = (
            payload.get("payment_condition")
            or payload.get("condicao_pagamento")
            or payload.get("payment_terms")
            or ""
        )
        pi = payload.get("payment_installments")
        if isinstance(pi, list):
            parcelas = pi
    except Exception:
        pass
    return condicao, parcelas


def _installments_block(parcelas: List[Dict[str, Any]]) -> str:
    if not parcelas:
        return ""

    norm = []
    for i, p in enumerate(parcelas, start=1):
        if not isinstance(p, dict):
            continue
        n = p.get("n") or p.get("parcela") or p.get("index") or i
        due = p.get("due_date") or p.get("vencimento") or p.get("date") or ""
        val = p.get("amount") or p.get("valor") or p.get("value") or 0
        norm.append({"n": n, "due": str(due), "val": val})

    if not norm:
        return ""

    rows = ""
    for it in norm:
        rows += f"""
          <tr>
            <td class="td">{_escape(it["n"])}</td>
            <td class="td">{_escape(it["due"])}</td>
            <td class="td right">{_money(it["val"])}</td>
          </tr>
        """

    return f"""
      <div class="section" style="margin-top:12px;">
        <div class="section-title">Parcelas</div>
        <table>
          <thead>
            <tr>
              <th style="width:15%;">Parcela</th>
              <th style="width:55%;">Vencimento</th>
              <th style="width:30%;" class="right">Valor</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    """


def build_quote_pdf_html(quote: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
    client = {}
    try:
        client = json.loads(quote.get("client_snapshot") or "{}")
    except Exception:
        client = {}

    quote_number = quote.get("quote_number") or ""
    created = str(quote.get("created_at") or "")

    envio = (quote.get("shipping_method_name") or "").strip()
    frete = (quote.get("freight_method_name") or "").strip()
    pagamento = (quote.get("payment_method_name") or quote.get("payment_method_code") or "").strip()

    condicao, parcelas = _extract_condition_and_installments(quote)
    total_net = _get_totals_net(quote)

    rows_html = ""
    for it in items:
        line = it.get("line") or ""
        name = it.get("name_snapshot") or ""
        sku = it.get("sku_snapshot") or ""
        qty = it.get("qty") or 0
        unit = it.get("unit_price_disc") or 0
        total = it.get("line_total") or 0

        rows_html += f"""
        <tr>
          <td class="td">{_escape(line)}</td>
          <td class="td">
            <div class="pname">{_escape(name)}</div>
            <div class="psku">{_escape(sku)}</div>
          </td>
          <td class="td right">{_escape(qty)}</td>
          <td class="td right">{_money(unit)}</td>
          <td class="td right">{_money(total)}</td>
        </tr>
        """

    notes = (quote.get("notes") or "").strip()
    notes_block = ""
    if notes:
        notes_block = f"""
        <div class="section" style="margin-top:12px;">
          <div class="section-title">Observações</div>
          <div class="notes">{_escape(notes)}</div>
        </div>
        """

    parcelas_block = _installments_block(parcelas)

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Pré-venda {quote_number}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #111827; }}
    .topbar {{ display:flex; justify-content: space-between; align-items:flex-start; gap:16px; margin-bottom: 14px; }}
    .title {{ font-size: 18px; font-weight: 800; margin: 0; }}
    .muted {{ color:#6b7280; font-size:12px; margin-top: 2px; }}
    .card {{ border:1px solid #e5e7eb; border-radius: 12px; padding: 12px; background: #fff; }}
    .client-name {{ font-weight: 800; margin-top: 4px; }}
    .section {{ border:1px solid #e5e7eb; border-radius: 12px; padding: 12px; margin-top: 12px; }}
    .section-title {{ font-weight: 800; margin-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; font-size: 12px; color:#374151; padding: 8px; background: #fafafa; border-bottom: 1px solid #e5e7eb; }}
    .td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; font-size: 13px; vertical-align: top; }}
    .right {{ text-align: right; }}
    .pname {{ font-weight: 700; }}
    .psku {{ color:#6b7280; font-size: 12px; margin-top:2px; }}
    .notes {{ border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; white-space: pre-wrap; min-height: 70px; }}
    .totalbox {{ display:flex; justify-content:flex-end; margin-top: 12px; }}
    .totalcard {{ border:1px solid #e5e7eb; border-radius: 12px; padding: 12px 14px; min-width: 260px; font-weight: 900; font-size: 16px; display:flex; justify-content: space-between; gap: 10px; }}
  </style>
</head>
<body>
  <div class="topbar">
    <div>
      <div class="title">Pré-venda Nº {_escape(quote_number)}</div>
      <div class="muted">Data: {_escape(created)}</div>
      <div class="muted"><b>Envio:</b> {_escape(envio or "-")}</div>
      <div class="muted"><b>Frete:</b> {_escape(frete or "-")}</div>
      <div class="muted"><b>Pagamento:</b> {_escape(pagamento or "-")}</div>
      <div class="muted"><b>Condição:</b> {_escape(condicao or "-")}</div>
    </div>

    <div class="card" style="min-width: 360px;">
      <div style="font-weight:800;">Cliente</div>
      <div class="client-name">{_escape(client.get("nome") or "")}</div>
      <div class="muted">{_escape(client.get("cpf_cnpj") or "")}</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Itens</div>
    <table>
      <thead>
        <tr>
          <th style="width:6%;">Linha</th>
          <th style="width:54%;">Produto</th>
          <th style="width:10%;" class="right">Qtd</th>
          <th style="width:15%;" class="right">Preço venda</th>
          <th style="width:15%;" class="right">Total</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  {parcelas_block}

  {notes_block}

  <div class="totalbox">
    <div class="totalcard">
      <span>Total</span><span>{_money(total_net)}</span>
    </div>
  </div>
</body>
</html>
"""


def _slug_filename(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "cliente"

@app.get("/quotes/{quote_id}/pdf")
def quote_pdf(quote_id: str):
    quote = _bq_get_quote(quote_id)
    items = _bq_get_quote_items(quote_id)
    html = build_quote_pdf_html(quote, items)

    browser = _get_pdf_browser()
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.set_content(html, wait_until="load")
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            display_header_footer=False,
            prefer_css_page_size=True,
            margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
        )
    finally:
        page.close()

    def _slug_filename(s: str) -> str:
        import unicodedata
        s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
        s = s.lower().strip()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        s = re.sub(r"_+", "_", s).strip("_")
        return s or "cliente"

    client = _from_json(quote.get("client_snapshot")) or {}
    client_name = (client.get("nome") or "cliente").strip()
    client_slug = _slug_filename(client_name)
    quote_number = quote.get("quote_number") or quote_id

    filename = f"prevenda_{client_slug}_{quote_number}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

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


def _ops_tiny_status_to_api(v: str) -> str:
    s = _normalize_ops_tiny_status(v)
    mapping = {
        "Em Aberto": "Em aberto",
        "Aprovado": "Aprovado",
        "Preparando Envio": "Preparando envio",
        "Pronto para Envio": "Pronto para envio",
        "Faturado": "Faturado",
        "Cancelado": "Cancelado",
    }
    return mapping.get(s, "")


def _extract_ops_tiny_order_item(item):
    pedido = item.get("pedido", item) if isinstance(item, dict) else {}
    if not isinstance(pedido, dict):
        pedido = {}

    cliente = pedido.get("cliente") or {}
    if not isinstance(cliente, dict):
        cliente = {}

    vendedor = pedido.get("vendedor") or {}
    if not isinstance(vendedor, dict):
        vendedor = {}

    raw_status = (
        pedido.get("situacao")
        or pedido.get("situacao_nome")
        or pedido.get("descricao_situacao")
        or pedido.get("status")
        or ""
    )

    total = (
        pedido.get("valor_total")
        or pedido.get("total_pedido")
        or pedido.get("total")
        or pedido.get("valor")
        or 0
    )

    return {
        "tiny_order_id": pedido.get("id"),
        "tiny_order_number": pedido.get("numero"),
        "status_tiny": _normalize_ops_tiny_status(raw_status),
        "status_tiny_raw": raw_status,
        "created_at": (
            pedido.get("data_pedido")
            or pedido.get("data")
            or pedido.get("dataPedido")
            or ""
        ),
        "client_name": (
            cliente.get("nome")
            or pedido.get("nome")
            or pedido.get("nome_cliente")
            or pedido.get("cliente_nome")
            or ""
        ),
        "client_cpf_cnpj": (
            cliente.get("cpf_cnpj")
            or cliente.get("cpfCnpj")
            or pedido.get("cpf_cnpj")
            or ""
        ),
        "seller_name": (
            vendedor.get("nome")
            or pedido.get("nome_vendedor")
            or pedido.get("seller_name")
            or ""
        ),
        "shipping_method_name": (
            pedido.get("forma_envio")
            or pedido.get("nome_forma_envio")
            or pedido.get("shipping_method_name")
            or ""
        ),
        "freight_method_name": (
            pedido.get("forma_frete")
            or pedido.get("nome_forma_frete")
            or pedido.get("freight_method_name")
            or ""
        ),
        "total": total,
        "raw": pedido,
    }


@app.get("/ops/tiny-orders")
def ops_tiny_orders(
    request: Request,
    status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=30),
    search: str = Query(default=""),
    remote_pages: int = Query(default=1, ge=1, le=5),
    days: int = Query(default=30, ge=1, le=365),
):
    sync_key = os.getenv("OPS_SYNC_KEY", "").strip()
    supplied_sync_key = (
        request.headers.get("x-ops-sync-key")
        or request.query_params.get("key")
        or ""
    ).strip()

    is_internal_cron = bool(
        sync_key and supplied_sync_key and secrets.compare_digest(sync_key, supplied_sync_key)
    )

    if not (_is_admin(request) or is_internal_cron):
        raise HTTPException(status_code=403, detail="Apenas administradores podem visualizar pedidos Tiny nesta rota.")

    requested_status = _normalize_ops_tiny_status(status)
    requested_status_api = _ops_tiny_status_to_api(requested_status)
    wanted_pages = max(int(remote_pages or 1), 1)

    date_fim = datetime.now().strftime("%d/%m/%Y")
    date_ini = (datetime.now() - timedelta(days=max(int(days or 30) - 1, 0))).strftime("%d/%m/%Y")

    all_items = []
    seen_ids = set()

    app_page = max(int(page or 1), 1)
    app_per_page = max(int(per_page or 20), 1)
    start_idx = (app_page - 1) * app_per_page
    end_idx = start_idx + app_per_page + 1  # +1 para sinalizar próxima página

    cache_key = json.dumps({
        "status": requested_status,
        "page": app_page,
        "per_page": app_per_page,
        "search": str(search or "").strip(),
        "remote_pages": wanted_pages,
        "days": days,
    }, sort_keys=True, ensure_ascii=False)

    cached = _ops_tiny_cache_get(cache_key)
    if cached is not None:
        response = JSONResponse(content=jsonable_encoder(cached))
        response.headers["X-Ops-Tiny-Cache"] = "HIT"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    try:
        # paginação do Tiny sempre começa da 1ª página;
        # acumulamos até conseguir preencher a página da grade solicitada
        for pagina in range(1, wanted_pages + 1):
            try:
                resp = tiny.pesquisar_pedidos(
                    pesquisa=str(search or "").strip(),
                    pagina=pagina,
                    situacao=requested_status_api,
                    data_ini_emissao=date_ini,
                    data_fim_emissao=date_fim,
                )
            except TinyAPIError as e:
                msg = _norm_text(str(e))
                if "pagina" in msg and " de " in msg:
                    break
                if "consulta nao retornou registros" in msg:
                    break
                raise

            pedidos = resp.get("pedidos") or []
            if isinstance(pedidos, dict):
                pedidos = [pedidos]

            if not pedidos:
                break

            page_added = 0
            for row in pedidos:
                item = _extract_ops_tiny_order_item(row)
                try:
                    tid = int(item.get("tiny_order_id"))
                except Exception:
                    continue

                if tid in seen_ids:
                    continue
                seen_ids.add(tid)

                if requested_status and item.get("status_tiny") != requested_status:
                    continue

                all_items.append(item)
                page_added += 1

                # já acumulamos o suficiente para a página pedida da grade
                if len(all_items) >= end_idx:
                    break

            if page_added == 0:
                break

            if len(all_items) >= end_idx:
                break

        tiny_ids = [int(x["tiny_order_id"]) for x in all_items if x.get("tiny_order_id") is not None]

        local_map = {}
        if tiny_ids:
            sql = f"""
            SELECT
              q.tiny_order_id,
              q.quote_id,
              q.quote_number,
              q.internal_status,
              q.shipping_method_name,
              q.freight_method_name,
              q.created_at,
              q.updated_at,
              COALESCE(fi.cost_total_products, 0) AS cost_total_products,
              COALESCE(fi.sale_total_products, 0) AS sale_total_products,
              COALESCE(fi.profit_total_products, 0) AS profit_total_products,
              COALESCE(fi.markup_total_order, 0) AS markup_total_order
            FROM {_table("quotes")} q
            LEFT JOIN (
              SELECT
                qi.quote_id,
                ROUND(SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)), 2) AS cost_total_products,
                ROUND(SUM(COALESCE(CAST(qi.line_total AS FLOAT64), 0)), 2) AS sale_total_products,
                ROUND(
                  SUM(COALESCE(CAST(qi.line_total AS FLOAT64), 0)) -
                  SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)),
                  2
                ) AS profit_total_products,
                ROUND(
                  SAFE_DIVIDE(
                    SUM(COALESCE(CAST(qi.line_total AS FLOAT64), 0)) -
                    SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)),
                    NULLIF(SUM(COALESCE(CAST(qi.qty AS FLOAT64), 0) * COALESCE(SAFE_CAST(JSON_EXTRACT_SCALAR(qi.raw, '$.product_raw.preco_custo') AS FLOAT64), 0)), 0)
                  ) * 100,
                  2
                ) AS markup_total_order
              FROM {_table("quote_items")} qi
              GROUP BY qi.quote_id
            ) fi
              ON fi.quote_id = q.quote_id
            WHERE q.tiny_order_id IN UNNEST(@tiny_ids)
            """
            cfg = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("tiny_ids", "INT64", tiny_ids)
                ]
            )
            rows = [dict(r) for r in bq.query(sql, job_config=cfg).result()]
            local_map = {int(r["tiny_order_id"]): r for r in rows if r.get("tiny_order_id") is not None}

        enriched_items = []
        for it in all_items:
            tid = int(it["tiny_order_id"])
            loc = local_map.get(tid) or {}
            enriched_items.append({
                **it,
                "quote_id": loc.get("quote_id"),
                "quote_number": loc.get("quote_number"),
                "internal_status_local": loc.get("internal_status"),
                "shipping_method_name": it.get("shipping_method_name") or loc.get("shipping_method_name") or "",
                "freight_method_name": it.get("freight_method_name") or loc.get("freight_method_name") or "",
                "cost_total_products": loc.get("cost_total_products") or 0,
                "sale_total_products": loc.get("sale_total_products") or 0,
                "profit_total_products": loc.get("profit_total_products") or 0,
                "markup_total_order": loc.get("markup_total_order") or 0,
                "has_local_quote": bool(loc.get("quote_id")),
            })

        page_items = enriched_items[start_idx:start_idx + app_per_page]
        has_next = len(enriched_items) > (start_idx + app_per_page)

        counts = {}
        for st in ["Em Aberto", "Aprovado", "Preparando Envio", "Pronto para Envio", "Faturado"]:
            counts[st] = sum(1 for x in enriched_items if x.get("status_tiny") == st)

        resp = {
            "source": "tiny_direct",
            "read_only": True,
            "items": page_items,
            "total_items": len(enriched_items),
            "has_next": has_next,
            "counts": counts,
            "params": {
                "status": requested_status,
                "page": app_page,
                "per_page": app_per_page,
                "search": search,
                "remote_pages": wanted_pages,
                "days": days,
                "date_ini": date_ini,
                "date_fim": date_fim,
            },
        }

        _ops_tiny_cache_set(cache_key, resp)

        response = JSONResponse(content=jsonable_encoder(resp))
        response.headers["X-Ops-Tiny-Cache"] = "MISS"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _count_ops_tiny_status(requested_status: str, days: int = 30, remote_pages: int = 15, search: str = "") -> int:
    requested_status = _normalize_ops_tiny_status(requested_status)
    requested_status_api = _ops_tiny_status_to_api(requested_status)
    wanted_pages = max(int(remote_pages or 1), 1)

    date_fim = datetime.now().strftime("%d/%m/%Y")
    date_ini = (datetime.now() - timedelta(days=max(int(days or 30) - 1, 0))).strftime("%d/%m/%Y")

    total = 0
    seen_ids = set()

    for pagina in range(1, wanted_pages + 1):
        try:
            resp = tiny.pesquisar_pedidos(
                pesquisa=str(search or "").strip(),
                pagina=pagina,
                situacao=requested_status_api,
                data_ini_emissao=date_ini,
                data_fim_emissao=date_fim,
            )
        except TinyAPIError as e:
            msg = _norm_text(str(e))
            if "pagina" in msg and " de " in msg:
                break
            if "consulta nao retornou registros" in msg:
                break
            raise

        pedidos = resp.get("pedidos") or []
        if isinstance(pedidos, dict):
            pedidos = [pedidos]

        if not pedidos:
            break

        page_new = 0
        for row in pedidos:
            item = _extract_ops_tiny_order_item(row)
            try:
                tid = int(item.get("tiny_order_id"))
            except Exception:
                continue

            if tid in seen_ids:
                continue
            seen_ids.add(tid)

            if requested_status and item.get("status_tiny") != requested_status:
                continue

            total += 1
            page_new += 1

        if page_new == 0:
            break

    return total


@app.get("/ops/tiny-orders-summary")
def ops_tiny_orders_summary(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    remote_pages: int = Query(default=3, ge=1, le=20),
    search: str = Query(default=""),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem visualizar o resumo de pedidos Tiny.")

    statuses = ["Em Aberto", "Aprovado", "Preparando Envio", "Pronto para Envio", "Faturado"]
    counts = {}

    cache_key = json.dumps({
        "days": days,
        "remote_pages": remote_pages,
        "search": str(search or "").strip(),
    }, sort_keys=True, ensure_ascii=False)

    cached = _ops_tiny_summary_cache_get(cache_key)
    if cached is not None:
        resp = JSONResponse(content=jsonable_encoder(cached))
        resp.headers["X-Ops-Tiny-Summary-Cache"] = "HIT"
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    try:
        for st in statuses:
            counts[st] = _count_ops_tiny_status(
                requested_status=st,
                days=days,
                remote_pages=remote_pages,
                search=search,
            )

        response = {
            "source": "tiny_direct_summary",
            "read_only": True,
            "counts": counts,
            "params": {
                "days": days,
                "remote_pages": remote_pages,
                "search": search,
            },
        }

        _ops_tiny_summary_cache_set(cache_key, response)

        resp = JSONResponse(content=jsonable_encoder(response))
        resp.headers["X-Ops-Tiny-Summary-Cache"] = "MISS"
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    except TinyAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _ops_tiny_mirror_table_ref():
    dataset_id = os.getenv("BQ_DATASET_ID", "").strip() or "tiny_orcamento_beta"
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or os.getenv("GCP_PROJECT", "").strip() or "projetotrml"
    return f"{project_id}.{dataset_id}.{OPS_TINY_MIRROR_TABLE}"


def _parse_tiny_date_for_sort(value: str):
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _ops_enrich_mirror_rows(items):
    local_map = {}
    try:
        ids = [int(x.get("tiny_order_id")) for x in items if x.get("tiny_order_id")]
        if ids:
            local_map = _load_local_quote_map_by_tiny_ids(ids)
    except Exception:
        local_map = {}

    enriched = []
    for it in items:
        try:
            tid = int(it.get("tiny_order_id"))
        except Exception:
            continue

        loc = local_map.get(tid) or {}
        enriched.append({
            **it,
            "quote_id": loc.get("quote_id"),
            "quote_number": loc.get("quote_number"),
            "internal_status_local": loc.get("internal_status"),
            "shipping_method_name": it.get("shipping_method_name") or loc.get("shipping_method_name") or "",
            "freight_method_name": it.get("freight_method_name") or loc.get("freight_method_name") or "",
            "cost_total_products": float(loc.get("cost_total_products") or 0),
            "sale_total_products": float(loc.get("sale_total_products") or 0),
            "profit_total_products": float(loc.get("profit_total_products") or 0),
            "markup_total_order": float(loc.get("markup_total_order") or 0),
            "has_local_quote": bool(loc.get("quote_id")),
        })
    return enriched


def _upsert_ops_tiny_mirror_batch(rows):
    if not rows:
        return {"written": 0}

    client = bigquery.Client()
    table_ref = _ops_tiny_mirror_table_ref()

    payload = []
    for row in rows:
        created_at_sort = _parse_tiny_date_for_sort(row.get("created_at"))
        payload.append({
            "tiny_order_id": int(row.get("tiny_order_id")),
            "tiny_order_number": str(row.get("tiny_order_number") or ""),
            "status_tiny": str(row.get("status_tiny") or ""),
            "status_tiny_raw": str(row.get("status_tiny_raw") or ""),
            "created_at": str(row.get("created_at") or ""),
            "created_at_sort": created_at_sort.isoformat() if created_at_sort else None,
            "client_name": str(row.get("client_name") or ""),
            "client_cpf_cnpj": str(row.get("client_cpf_cnpj") or ""),
            "seller_name": str(row.get("seller_name") or ""),
            "shipping_method_name": str(row.get("shipping_method_name") or ""),
            "freight_method_name": str(row.get("freight_method_name") or ""),
            "total": float(row.get("total") or 0),
            "quote_id": str(row.get("quote_id") or ""),
            "quote_number": str(row.get("quote_number") or ""),
            "internal_status_local": str(row.get("internal_status_local") or ""),
            "cost_total_products": float(row.get("cost_total_products") or 0),
            "sale_total_products": float(row.get("sale_total_products") or 0),
            "profit_total_products": float(row.get("profit_total_products") or 0),
            "markup_total_order": float(row.get("markup_total_order") or 0),
            "has_local_quote": bool(row.get("has_local_quote")),
            "raw_json": json.dumps(row.get("raw") or {}, ensure_ascii=False),
            "sync_source": "tiny_sync",
            "synced_at": datetime.utcnow().isoformat(),
        })

    job_config = LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
    )

    job = client.load_table_from_json(payload, table_ref, job_config=job_config)
    job.result()

    return {"written": len(rows)}



def _upsert_ops_tiny_mirror(rows, batch_size: int = 150):
    if not rows:
        return {"written": 0}

    result = _upsert_ops_tiny_mirror_batch(rows)
    return {
        "written": result.get("written", len(rows)),
        "batches": 1,
        "batch_size": len(rows),
    }


@app.post("/ops/sync-tiny-orders")
def ops_sync_tiny_orders(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    remote_pages: int = Query(default=10, ge=1, le=50),
):
    sync_key = os.getenv("OPS_SYNC_KEY", "").strip()
    supplied_sync_key = (
        request.headers.get("x-ops-sync-key")
        or request.query_params.get("key")
        or ""
    ).strip()

    is_internal_cron = bool(
        sync_key and supplied_sync_key and secrets.compare_digest(sync_key, supplied_sync_key)
    )

    if not (_is_admin(request) or is_internal_cron):
        raise HTTPException(status_code=403, detail="Apenas administradores podem sincronizar pedidos Tiny.")

    statuses = ["Em Aberto", "Aprovado", "Preparando Envio", "Pronto para Envio", "Faturado"]
    all_seen = {}
    sync_counts = {}

    for st in statuses:
        try:
            resp = ops_tiny_orders(
                request=request,
                status=st,
                page=1,
                per_page=1000,
                search="",
                remote_pages=remote_pages,
                days=days,
            )
            payload = json.loads(resp.body.decode("utf-8"))
            items = payload.get("items") or []
            sync_counts[st] = len(items)
            for item in items:
                tid = item.get("tiny_order_id")
                if tid:
                    all_seen[str(tid)] = item
        except Exception as e:
            sync_counts[st] = f"erro: {e}"

    rows = _ops_enrich_mirror_rows(list(all_seen.values()))
    existing_index = _load_existing_mirror_index()

    new_count = 0
    changed_count = 0
    financial_pending_count = 0

    for row in rows:
        tid = str(row.get("tiny_order_id") or "")
        existing = existing_index.get(tid)

        is_new = existing is None
        is_changed = False
        if existing:
            is_changed = (
                str(existing.get("status_tiny") or "") != str(row.get("status_tiny") or "")
                or str(existing.get("tiny_order_number") or "") != str(row.get("tiny_order_number") or "")
            )

        financial_pending = (
            not bool(row.get("has_local_quote"))
            and (
                existing is None
                or float(existing.get("cost_total_products") or 0) == 0
            )
        )

        row["_is_new"] = is_new
        row["_is_changed"] = is_changed
        row["_financial_pending"] = financial_pending

        if is_new:
            new_count += 1
        if is_changed:
            changed_count += 1
        if financial_pending:
            financial_pending_count += 1

    financial_enriched_count = 0
    financial_error_count = 0

    # substituição atômica do espelho via WRITE_TRUNCATE
    write_result = _upsert_ops_tiny_mirror(rows)

    return {
        "ok": True,
        "days": days,
        "remote_pages": remote_pages,
        "statuses": sync_counts,
        "unique_items": len(all_seen),
        "new_count": new_count,
        "changed_count": changed_count,
        "financial_pending_count": financial_pending_count,
        "financial_enriched_count": financial_enriched_count,
        "financial_error_count": financial_error_count,
        "write_result": write_result,
        "table": _ops_tiny_mirror_table_ref(),
    }


def _ops_fast_table_ref():
    dataset_id = os.getenv("BQ_DATASET_ID", "").strip() or "tiny_orcamento_beta"
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or os.getenv("GCP_PROJECT", "").strip() or "projetotrml"
    return f"{project_id}.{dataset_id}.ops_tiny_orders_mirror"


@app.get("/ops/orders-fast")
def ops_orders_fast(
    request: Request,
    status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem visualizar operações.")

    client = bigquery.Client()
    table_ref = _ops_fast_table_ref()

    status_norm = str(status or "").strip()
    q = str(search or "").strip().lower()
    offset = (page - 1) * per_page

    where = ["1=1"]
    params = []

    if status_norm:
        where.append("status_tiny = @status")
        params.append(bigquery.ScalarQueryParameter("status", "STRING", status_norm))

    if q:
        where.append("""
        (
          LOWER(client_name) LIKE CONCAT('%', @q, '%')
          OR LOWER(seller_name) LIKE CONCAT('%', @q, '%')
          OR LOWER(tiny_order_number) LIKE CONCAT('%', @q, '%')
          OR LOWER(tiny_order_id) LIKE CONCAT('%', @q, '%')
        )
        """)
        params.append(bigquery.ScalarQueryParameter("q", "STRING", q))

    where_sql = " AND ".join(where)

    count_sql = f"""
    SELECT COUNT(*) AS total
    FROM `{table_ref}`
    WHERE {where_sql}
    """

    count_job = client.query(
        count_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=params),
    )
    total_items = list(count_job.result())[0]["total"]

    data_sql = f"""
    SELECT
      tiny_order_id,
      tiny_order_number,
      status_tiny,
      status_tiny_raw,
      created_at,
      client_name,
      client_cpf_cnpj,
      seller_name,
      shipping_method_name,
      freight_method_name,
      total,
      quote_id,
      quote_number,
      internal_status_local,
      cost_total_products,
      sale_total_products,
      profit_total_products,
      markup_total_order,
      has_local_quote,
      raw_json,
      synced_at
    FROM `{table_ref}`
    WHERE {where_sql}
    ORDER BY created_at_sort DESC NULLS LAST, tiny_order_id DESC
    LIMIT @limit OFFSET @offset
    """

    data_params = params + [
        bigquery.ScalarQueryParameter("limit", "INT64", per_page),
        bigquery.ScalarQueryParameter("offset", "INT64", offset),
    ]

    rows = client.query(
        data_sql,
        job_config=bigquery.QueryJobConfig(query_parameters=data_params),
    ).result()

    items = []
    for r in rows:
        items.append({
            "tiny_order_id": str(r["tiny_order_id"] or ""),
            "tiny_order_number": str(r["tiny_order_number"] or ""),
            "status_tiny": str(r["status_tiny"] or ""),
            "status_tiny_raw": str(r["status_tiny_raw"] or ""),
            "created_at": str(r["created_at"] or ""),
            "client_name": str(r["client_name"] or ""),
            "client_cpf_cnpj": str(r["client_cpf_cnpj"] or ""),
            "seller_name": str(r["seller_name"] or ""),
            "shipping_method_name": str(r["shipping_method_name"] or ""),
            "freight_method_name": str(r["freight_method_name"] or ""),
            "total": float(r["total"] or 0),
            "quote_id": str(r["quote_id"] or ""),
            "quote_number": str(r["quote_number"] or ""),
            "internal_status_local": str(r["internal_status_local"] or ""),
            "cost_total_products": float(r["cost_total_products"] or 0),
            "sale_total_products": float(r["sale_total_products"] or 0),
            "profit_total_products": float(r["profit_total_products"] or 0),
            "markup_total_order": float(r["markup_total_order"] or 0),
            "has_local_quote": bool(r["has_local_quote"]),
            "raw": json.loads(r["raw_json"] or "{}"),
            "sync_source": "mirror",
            "synced_at": str(r["synced_at"] or ""),
        })

    return {
        "source": "mirror_local",
        "read_only": True,
        "items": items,
        "total_items": int(total_items),
        "has_next": (offset + per_page) < total_items,
        "params": {
            "status": status_norm,
            "page": page,
            "per_page": per_page,
            "search": search,
        },
    }


@app.get("/ops/orders-fast-summary")
def ops_orders_fast_summary(
    request: Request,
    search: str = Query(default=""),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem visualizar operações.")

    client = bigquery.Client()
    table_ref = _ops_fast_table_ref()
    q = str(search or "").strip().lower()

    where = ["1=1"]
    params = []

    if q:
        where.append("""
        (
          LOWER(client_name) LIKE CONCAT('%', @q, '%')
          OR LOWER(seller_name) LIKE CONCAT('%', @q, '%')
          OR LOWER(tiny_order_number) LIKE CONCAT('%', @q, '%')
          OR LOWER(CAST(tiny_order_id AS STRING)) LIKE CONCAT('%', @q, '%')
        )
        """)
        params.append(bigquery.ScalarQueryParameter("q", "STRING", q))

    where_sql = " AND ".join(where)

    sql = f"""
    SELECT
      status_tiny,
      COUNT(*) AS qtd
    FROM `{table_ref}`
    WHERE {where_sql}
    GROUP BY status_tiny
    """

    rows = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(query_parameters=params),
    ).result()

    counts = {
        "Em Aberto": 0,
        "Aprovado": 0,
        "Preparando Envio": 0,
        "Pronto para Envio": 0,
        "Faturado": 0,
    }

    for r in rows:
        st = str(r["status_tiny"] or "")
        if st in counts:
            counts[st] = int(r["qtd"] or 0)

    return {
        "source": "mirror_local_summary",
        "read_only": True,
        "counts": counts,
        "params": {
            "search": search,
        },
    }


@app.get("/ops/sync-status")
def ops_sync_status(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas administradores podem visualizar o status do sync.")

    client = bigquery.Client()
    table_ref = _ops_fast_table_ref()

    sql = f"""
    SELECT
      MAX(synced_at) AS last_sync,
      COUNT(*) AS total_rows
    FROM `{table_ref}`
    """
    rows = list(client.query(sql).result())
    row = rows[0] if rows else {}

    return {
        "source": "mirror_local",
        "last_sync": str(row.get("last_sync") or ""),
        "total_rows": int(row.get("total_rows") or 0),
    }


def _load_existing_mirror_index():
    client = bigquery.Client()
    table_ref = _ops_fast_table_ref()

    sql = f"""
    SELECT
      tiny_order_id,
      tiny_order_number,
      status_tiny,
      cost_total_products,
      sale_total_products,
      profit_total_products,
      markup_total_order,
      has_local_quote
    FROM `{table_ref}`
    """
    rows = client.query(sql).result()

    out = {}
    for r in rows:
        tid = str(r["tiny_order_id"])
        out[tid] = {
            "tiny_order_number": str(r["tiny_order_number"] or ""),
            "status_tiny": str(r["status_tiny"] or ""),
            "cost_total_products": float(r["cost_total_products"] or 0),
            "sale_total_products": float(r["sale_total_products"] or 0),
            "profit_total_products": float(r["profit_total_products"] or 0),
            "markup_total_order": float(r["markup_total_order"] or 0),
            "has_local_quote": bool(r["has_local_quote"]),
        }
    return out


def _extract_tiny_product_cost(prod_resp: Dict[str, Any]) -> float:
    produto = prod_resp.get("produto") or prod_resp or {}
    candidates = [
        produto.get("preco_custo"),
        produto.get("precoCusto"),
        produto.get("custo"),
        produto.get("valor_custo"),
    ]
    for c in candidates:
        try:
            if c is not None and str(c).strip() != "":
                return float(str(c).replace(",", "."))
        except Exception:
            pass
    return 0.0


def _extract_tiny_order_items_for_financials(order_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    pedido = order_resp.get("pedido") or {}
    itens = (
        pedido.get("itens")
        or pedido.get("itens_pedido")
        or pedido.get("itensPedido")
        or []
    )
    if isinstance(itens, dict):
        itens = [itens]

    out = []
    for raw in itens:
        item = raw.get("item", raw) if isinstance(raw, dict) else {}
        if not isinstance(item, dict):
            continue

        produto = item.get("produto") or {}
        if not isinstance(produto, dict):
            produto = {}

        product_id = (
            item.get("id_produto")
            or item.get("idProduto")
            or item.get("produto_id")
            or produto.get("id")
            or produto.get("id_produto")
        )

        qty = (
            item.get("quantidade")
            or item.get("qtde")
            or item.get("qtd")
            or item.get("qty")
            or 0
        )

        unit_price = (
            item.get("valor_unitario")
            or item.get("valorUnitario")
            or item.get("preco_unitario")
            or item.get("preco")
            or item.get("valor")
            or 0
        )

        line_total = (
            item.get("valor_total")
            or item.get("total")
            or item.get("subtotal")
            or 0
        )

        try:
            qty_f = float(str(qty).replace(",", "."))
        except Exception:
            qty_f = 0.0

        try:
            unit_f = float(str(unit_price).replace(",", "."))
        except Exception:
            unit_f = 0.0

        try:
            line_f = float(str(line_total).replace(",", "."))
        except Exception:
            line_f = 0.0

        if line_f <= 0 and qty_f > 0 and unit_f > 0:
            line_f = qty_f * unit_f

        try:
            product_id = int(product_id) if product_id is not None and str(product_id).strip() != "" else None
        except Exception:
            product_id = None

        out.append({
            "product_id": product_id,
            "qty": qty_f,
            "unit_price": unit_f,
            "line_total": line_f,
        })

    return out


def _enrich_tiny_only_financials(rows: List[Dict[str, Any]], existing_index: Dict[str, Dict[str, Any]]):
    product_cost_cache: Dict[int, float] = {}
    enriched_count = 0
    error_count = 0

    for row in rows:
        tid = str(row.get("tiny_order_id") or "")
        existing = existing_index.get(tid) or {}

        # com orçamento local -> mantém o financeiro local
        if bool(row.get("has_local_quote")):
            continue

        # se não está pendente, preserva o que já existe
        if not bool(row.get("_financial_pending")):
            row["cost_total_products"] = float(existing.get("cost_total_products") or 0)
            row["sale_total_products"] = float(existing.get("sale_total_products") or 0)
            row["profit_total_products"] = float(existing.get("profit_total_products") or 0)
            row["markup_total_order"] = float(existing.get("markup_total_order") or 0)
            continue

        try:
            order_raw = tiny.obter_pedido(int(tid))
            order_items = _extract_tiny_order_items_for_financials(order_raw)

            sale_total = 0.0
            cost_total = 0.0

            for it in order_items:
                sale_total += float(it.get("line_total") or 0)
                qty = float(it.get("qty") or 0)
                product_id = it.get("product_id")

                cost_unit = 0.0
                if product_id:
                    if product_id not in product_cost_cache:
                        try:
                            prod_raw = tiny.obter_produto(int(product_id))
                            product_cost_cache[product_id] = _extract_tiny_product_cost(prod_raw)
                        except Exception:
                            product_cost_cache[product_id] = 0.0
                    cost_unit = product_cost_cache.get(product_id, 0.0)

                cost_total += qty * cost_unit

            sale_total = round(float(sale_total or 0), 2)
            cost_total = round(float(cost_total or 0), 2)
            profit_total = round(sale_total - cost_total, 2)

            markup_total = round((profit_total / cost_total) * 100, 2) if cost_total > 0 else 0.0

            row["cost_total_products"] = cost_total
            row["sale_total_products"] = sale_total
            row["profit_total_products"] = profit_total
            row["markup_total_order"] = markup_total

            enriched_count += 1

        except Exception as e:
            row["cost_total_products"] = float(existing.get("cost_total_products") or 0)
            row["sale_total_products"] = float(existing.get("sale_total_products") or 0)
            row["profit_total_products"] = float(existing.get("profit_total_products") or 0)
            row["markup_total_order"] = float(existing.get("markup_total_order") or 0)
            row["_financial_error"] = str(e)
            error_count += 1

    return rows, enriched_count, error_count



def _load_full_mirror_rows():
    client = bigquery.Client()
    table_ref = _ops_fast_table_ref()

    sql = f"""
    SELECT
      tiny_order_id,
      tiny_order_number,
      status_tiny,
      status_tiny_raw,
      created_at,
      client_name,
      client_cpf_cnpj,
      seller_name,
      shipping_method_name,
      freight_method_name,
      total,
      quote_id,
      quote_number,
      internal_status_local,
      cost_total_products,
      sale_total_products,
      profit_total_products,
      markup_total_order,
      has_local_quote,
      raw_json,
      synced_at
    FROM `{table_ref}`
    """
    rows = client.query(sql).result()

    items = []
    for r in rows:
        items.append({
            "tiny_order_id": str(r["tiny_order_id"] or ""),
            "tiny_order_number": str(r["tiny_order_number"] or ""),
            "status_tiny": str(r["status_tiny"] or ""),
            "status_tiny_raw": str(r["status_tiny_raw"] or ""),
            "created_at": str(r["created_at"] or ""),
            "client_name": str(r["client_name"] or ""),
            "client_cpf_cnpj": str(r["client_cpf_cnpj"] or ""),
            "seller_name": str(r["seller_name"] or ""),
            "shipping_method_name": str(r["shipping_method_name"] or ""),
            "freight_method_name": str(r["freight_method_name"] or ""),
            "total": float(r["total"] or 0),
            "quote_id": str(r["quote_id"] or ""),
            "quote_number": str(r["quote_number"] or ""),
            "internal_status_local": str(r["internal_status_local"] or ""),
            "cost_total_products": float(r["cost_total_products"] or 0),
            "sale_total_products": float(r["sale_total_products"] or 0),
            "profit_total_products": float(r["profit_total_products"] or 0),
            "markup_total_order": float(r["markup_total_order"] or 0),
            "has_local_quote": bool(r["has_local_quote"]),
            "raw": json.loads(r["raw_json"] or "{}"),
            "sync_source": "mirror_local",
            "synced_at": str(r["synced_at"] or ""),
        })
    return items



_OPS_SYNC_PROGRESS = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "updated_total": 0,
    "checked_total": 0,
    "rounds_completed": 0,
    "last_error": "",
    "last_result": None,
}
_OPS_SYNC_PROGRESS_LOCK = threading.Lock()


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
        })


def _extract_tiny_status_from_order_obter(order_resp: Dict[str, Any]) -> tuple[str, str]:
    pedido = order_resp.get("pedido") or {}
    raw_status = (
        pedido.get("situacao")
        or pedido.get("situacao_nome")
        or pedido.get("descricao_situacao")
        or pedido.get("status")
        or ""
    )
    normalized = _normalize_ops_tiny_status(raw_status)
    return normalized, str(raw_status or "")


def _touch_ops_quote_status_checked(quote_id: str, now=None):
    if not quote_id:
        return
    now = now or _now_utc()
    bq.query(
        f"""
        UPDATE {_table('quotes')}
        SET updated_at = @now
        WHERE quote_id = @quote_id
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("quote_id", "STRING", str(quote_id)),
            ]
        ),
    ).result()


def _run_ops_sync_one_local_order_status(row: Dict[str, Any]):
    allowed_statuses = {
        "Em Aberto",
        "Aprovado",
        "Preparando Envio",
        "Pronto para Envio",
        "Faturado",
        "Cancelado",
    }

    quote_id = row.get("quote_id")
    tiny_order_id = row.get("tiny_order_id")
    current_status = _normalize_ops_tiny_status(row.get("internal_status"))

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
        new_status, raw_status = _extract_tiny_status_from_order_obter(raw)

        if new_status not in allowed_statuses:
            _touch_ops_quote_status_checked(quote_id)
            return {
                "ok": True,
                "updated": False,
                "skipped": True,
                "quote_id": quote_id,
                "tiny_order_id": int(tiny_order_id),
                "tiny_order_number": row.get("tiny_order_number"),
                "from": current_status or "",
                "to": new_status,
                "tiny_status_raw": raw_status,
                "reason": "Status Tiny não mapeado para fluxo local.",
            }

    except TinyAPIError as e:
        if _tiny_error_looks_missing(e):
            new_status = "Cancelado"
            raw_status = "missing_in_tiny"
        else:
            return {
                "ok": False,
                "updated": False,
                "error": str(e),
                "quote_id": quote_id,
                "tiny_order_id": tiny_order_id,
            }
    except Exception as e:
        return {
            "ok": False,
            "updated": False,
            "error": str(e),
            "quote_id": quote_id,
            "tiny_order_id": tiny_order_id,
        }

    now = _now_utc()

    if new_status == current_status:
        _touch_ops_quote_status_checked(quote_id, now=now)
        return {
            "ok": True,
            "updated": False,
            "unchanged": True,
            "quote_id": quote_id,
            "quote_number": row.get("quote_number"),
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": row.get("tiny_order_number"),
            "from": current_status or "",
            "to": new_status,
            "tiny_status_raw": raw_status,
        }

    bq.query(
        f"""
        UPDATE {_table('quotes')}
        SET internal_status = @internal_status,
            updated_at = @now
        WHERE quote_id = @quote_id
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("internal_status", "STRING", new_status),
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("quote_id", "STRING", quote_id),
            ]
        ),
    ).result()

    sep_status = None
    if new_status == "Faturado":
        sep_status = "Entregue"
    elif new_status == "Cancelado":
        sep_status = "Cancelado"

    if sep_status:
        bq.query(
            f"""
            UPDATE {_table('separation_orders')}
            SET status = @sep_status,
                updated_at = @now
            WHERE tiny_order_id = @tiny_order_id
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("sep_status", "STRING", sep_status),
                    bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                    bigquery.ScalarQueryParameter("tiny_order_id", "INT64", int(tiny_order_id)),
                ]
            ),
        ).result()

    return {
        "ok": True,
        "updated": True,
        "quote_id": quote_id,
        "quote_number": row.get("quote_number"),
        "tiny_order_id": int(tiny_order_id),
        "tiny_order_number": row.get("tiny_order_number"),
        "from": current_status or "",
        "to": new_status,
        "tiny_status_raw": raw_status,
    }


def _run_ops_sync_local_order_statuses_batch(limit: int = 5):
    candidate_limit = min(max(int(limit) * 8, 40), 250)

    sql = f"""
    SELECT
      q.quote_id,
      q.quote_number,
      q.tiny_order_id,
      q.tiny_order_number,
      q.internal_status
    FROM {_table('quotes')} q
    WHERE q.status = 'ordered'
      AND q.tiny_order_id IS NOT NULL
      AND LOWER(COALESCE(q.internal_status, '')) != 'faturado'
    ORDER BY q.updated_at ASC, q.created_at ASC
    LIMIT @candidate_limit
    """

    rows = [dict(r) for r in bq.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("candidate_limit", "INT64", int(candidate_limit)),
            ]
        ),
    ).result()]

    allowed_statuses = {
        "Em Aberto",
        "Aprovado",
        "Preparando Envio",
        "Pronto para Envio",
        "Faturado",
        "Cancelado",
    }

    updated = []
    unchanged = 0
    skipped = 0
    errors = []

    for row in rows:
        if len(updated) >= int(limit):
            break

        quote_id = row.get("quote_id")
        tiny_order_id = row.get("tiny_order_id")
        current_status = _normalize_ops_tiny_status(row.get("internal_status"))

        try:
            raw = tiny.obter_pedido(int(tiny_order_id))
            new_status, raw_status = _extract_tiny_status_from_order_obter(raw)

            if new_status not in allowed_statuses:
                skipped += 1
                _touch_ops_quote_status_checked(quote_id)
                continue

        except TinyAPIError as e:
            if _tiny_error_looks_missing(e):
                new_status = "Cancelado"
                raw_status = "missing_in_tiny"
            else:
                errors.append({
                    "quote_id": quote_id,
                    "tiny_order_id": tiny_order_id,
                    "error": str(e),
                })
                continue
        except Exception as e:
            errors.append({
                "quote_id": quote_id,
                "tiny_order_id": tiny_order_id,
                "error": str(e),
            })
            continue

        if new_status == current_status:
            unchanged += 1
            _touch_ops_quote_status_checked(quote_id)
            continue

        now = _now_utc()

        upd_sql = f"""
        UPDATE {_table('quotes')}
        SET internal_status = @internal_status,
            updated_at = @now
        WHERE quote_id = @quote_id
        """
        bq.query(
            upd_sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("internal_status", "STRING", new_status),
                    bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                    bigquery.ScalarQueryParameter("quote_id", "STRING", quote_id),
                ]
            ),
        ).result()

        sep_status = None
        if new_status == "Faturado":
            sep_status = "Entregue"
        elif new_status == "Cancelado":
            sep_status = "Cancelado"

        if sep_status:
            sep_sql = f"""
            UPDATE {_table('separation_orders')}
            SET status = @sep_status,
                updated_at = @now
            WHERE tiny_order_id = @tiny_order_id
            """
            bq.query(
                sep_sql,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("sep_status", "STRING", sep_status),
                        bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
                        bigquery.ScalarQueryParameter("tiny_order_id", "INT64", int(tiny_order_id)),
                    ]
                ),
            ).result()

        updated.append({
            "quote_id": quote_id,
            "quote_number": row.get("quote_number"),
            "tiny_order_id": int(tiny_order_id),
            "tiny_order_number": row.get("tiny_order_number"),
            "from": current_status or "",
            "to": new_status,
            "tiny_status_raw": raw_status,
        })

    return {
        "ok": True,
        "checked": len(rows),
        "candidate_limit": int(candidate_limit),
        "updated_count": len(updated),
        "unchanged_count": unchanged,
        "skipped_count": skipped,
        "error_count": len(errors),
        "updated": updated,
        "errors": errors[:20],
    }


@app.post("/ops/sync-local-order-statuses")
def ops_sync_local_order_statuses(
    request: Request,
    limit: int = Query(default=5, ge=1, le=200),
):
    if not (_is_admin(request) or _is_allowed_user(request)):
        raise HTTPException(status_code=403, detail="Acesso negado à sincronização local do Tiny.")

    if _is_expedition(request) and not _is_admin(request):
        raise HTTPException(status_code=403, detail="Usuário de expedição sem acesso a esta sincronização.")

    return _run_ops_sync_local_order_statuses_batch(limit=limit)


def _ops_sync_local_order_statuses_worker():
    try:
        _ops_sync_progress_update(
            running=True,
            started_at=_now_utc().isoformat(),
            finished_at=None,
            updated_total=0,
            checked_total=0,
            rounds_completed=0,
            last_error="",
            last_result=None,
        )

        for _ in range(30):
            result = _run_ops_sync_local_order_statuses_batch(limit=10)

            updated_total = int(_ops_sync_progress_snapshot().get("updated_total") or 0) + int(result.get("updated_count") or 0)
            checked_total = int(_ops_sync_progress_snapshot().get("checked_total") or 0) + int(result.get("checked") or 0)
            rounds_completed = int(_ops_sync_progress_snapshot().get("rounds_completed") or 0) + 1

            _ops_sync_progress_update(
                updated_total=updated_total,
                checked_total=checked_total,
                rounds_completed=rounds_completed,
                last_result=result,
            )

            if int(result.get("checked") or 0) <= 0:
                break

            time.sleep(0.3)

        _ops_sync_progress_update(
            running=False,
            finished_at=_now_utc().isoformat(),
        )
    except Exception as e:
        _ops_sync_progress_update(
            running=False,
            finished_at=_now_utc().isoformat(),
            last_error=str(e),
        )


@app.post("/ops/sync-local-order-status")
def ops_sync_local_order_status(
    request: Request,
    q: str = Query(default=""),
):
    if not (_is_admin(request) or _is_allowed_user(request)):
        raise HTTPException(status_code=403, detail="Acesso negado à sincronização local do Tiny.")

    if _is_expedition(request) and not _is_admin(request):
        raise HTTPException(status_code=403, detail="Usuário de expedição sem acesso a esta sincronização.")

    q_norm = str(q or "").strip()
    if not q_norm:
        raise HTTPException(status_code=400, detail="Informe o número ou ID do pedido.")

    sql = f"""
    SELECT
      q.quote_id,
      q.quote_number,
      q.tiny_order_id,
      q.tiny_order_number,
      q.internal_status
    FROM {_table('quotes')} q
    WHERE q.status = 'ordered'
      AND q.tiny_order_id IS NOT NULL
      AND (
        CAST(q.tiny_order_id AS STRING) = @q
        OR CAST(q.tiny_order_number AS STRING) = @q
        OR CAST(q.quote_number AS STRING) = @q
        OR CAST(q.quote_id AS STRING) = @q
      )
    ORDER BY q.updated_at DESC, q.created_at DESC
    LIMIT 1
    """

    rows = [dict(r) for r in bq.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("q", "STRING", q_norm),
            ]
        ),
    ).result()]

    if not rows:
        return {
            "ok": True,
            "found": False,
            "updated_count": 0,
            "message": "Pedido não encontrado na base local.",
            "search": q_norm,
        }

    result = _run_ops_sync_one_local_order_status(rows[0])

    return {
        "ok": bool(result.get("ok", False)),
        "found": True,
        "updated_count": 1 if result.get("updated") else 0,
        "result": result,
        "search": q_norm,
    }


@app.post("/ops/start-sync-local-order-statuses")
def ops_start_sync_local_order_statuses(request: Request):
    if not (_is_admin(request) or _is_allowed_user(request)):
        raise HTTPException(status_code=403, detail="Acesso negado à sincronização local do Tiny.")

    if _is_expedition(request) and not _is_admin(request):
        raise HTTPException(status_code=403, detail="Usuário de expedição sem acesso a esta sincronização.")

    snapshot = _ops_sync_progress_snapshot()
    if snapshot.get("running"):
        return {
            "ok": True,
            "started": False,
            "message": "Sincronização já está em andamento.",
            "progress": snapshot,
        }

    thread = threading.Thread(target=_ops_sync_local_order_statuses_worker, daemon=True)
    thread.start()

    return {
        "ok": True,
        "started": True,
        "message": "Sincronização iniciada em segundo plano.",
        "progress": _ops_sync_progress_snapshot(),
    }


@app.get("/ops/sync-local-order-statuses-progress")
def ops_sync_local_order_statuses_progress(request: Request):
    if not (_is_admin(request) or _is_allowed_user(request)):
        raise HTTPException(status_code=403, detail="Acesso negado à sincronização local do Tiny.")

    if _is_expedition(request) and not _is_admin(request):
        raise HTTPException(status_code=403, detail="Usuário de expedição sem acesso a esta sincronização.")

    return {
        "ok": True,
        "progress": _ops_sync_progress_snapshot(),
    }


@app.post("/ops/enrich-tiny-financials")
def ops_enrich_tiny_financials(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
):
    sync_key = os.getenv("OPS_SYNC_KEY", "").strip()
    supplied_sync_key = (
        request.headers.get("x-ops-sync-key")
        or request.query_params.get("key")
        or ""
    ).strip()

    is_internal_cron = bool(
        sync_key and supplied_sync_key and secrets.compare_digest(sync_key, supplied_sync_key)
    )

    if not (_is_admin(request) or is_internal_cron):
        raise HTTPException(status_code=403, detail="Apenas administradores podem enriquecer financeiros Tiny.")

    full_rows = _load_full_mirror_rows()
    existing_index = _load_existing_mirror_index()

    pending_rows = []
    for row in full_rows:
        if bool(row.get("has_local_quote")):
            continue
        if float(row.get("cost_total_products") or 0) > 0:
            continue
        row["_financial_pending"] = True
        pending_rows.append(row)

    pending_rows = pending_rows[:limit]
    if not pending_rows:
        return {
            "ok": True,
            "limit": limit,
            "pending_found": 0,
            "financial_enriched_count": 0,
            "financial_error_count": 0,
            "write_result": {"written": 0, "batches": 0},
        }

    enriched_rows, enriched_count, error_count = _enrich_tiny_only_financials(pending_rows, existing_index)
    enriched_map = {str(r.get("tiny_order_id")): r for r in enriched_rows}

    rewritten_rows = []
    for row in full_rows:
        tid = str(row.get("tiny_order_id") or "")
        if tid in enriched_map:
            rewritten_rows.append(enriched_map[tid])
        else:
            rewritten_rows.append(row)

    write_result = _upsert_ops_tiny_mirror(rewritten_rows)

    return {
        "ok": True,
        "limit": limit,
        "pending_found": len(pending_rows),
        "financial_enriched_count": enriched_count,
        "financial_error_count": error_count,
        "write_result": write_result,
        "table": _ops_tiny_mirror_table_ref(),
    }


# =========================
# Tiny Client Wallet Cache
# =========================

def _client_wallet_cache_table_ref():
    import os
    project_id = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or "projetotrml"
    )
    dataset_id = os.getenv("BQ_DATASET_ID", "tiny_orcamento_beta").strip() or "tiny_orcamento_beta"
    return f"{project_id}.{dataset_id}.tiny_client_wallet_cache"


def _client_wallet_cache_bq():
    from google.cloud import bigquery
    return bigquery.Client(project=(
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or "projetotrml"
    ))


def _client_wallet_cache_parse_date(value):
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def _client_wallet_cache_safe_float(value):
    try:
        return float(str(value or 0).replace(",", "."))
    except Exception:
        return 0.0


def _client_wallet_cache_fetch_orders_for_contact(nome: str, cpf_cnpj: str):
    pedidos_all = []
    pagina = 1

    while True:
        try:
            if cpf_cnpj:
                resp = tiny.pesquisar_pedidos(
                    cpf_cnpj=cpf_cnpj,
                    pagina=pagina,
                    sort="DESC",
                )
            else:
                resp = tiny.pesquisar_pedidos(
                    cliente=nome,
                    pagina=pagina,
                    sort="DESC",
                )
        except TinyAPIError as e:
            msg = str(e).lower()
            if "não retornou registros" in msg or "nao retornou registros" in msg:
                break
            if "consulta nao retornou registros" in msg:
                break
            raise

        pedidos = resp.get("pedidos") or []
        if isinstance(pedidos, dict):
            pedidos = [pedidos]
        if not pedidos:
            break

        for row in pedidos:
            pedidos_all.append(row.get("pedido", row))

        try:
            numero_paginas = int(resp.get("numero_paginas") or pagina)
        except Exception:
            numero_paginas = pagina

        if pagina >= numero_paginas:
            break

        pagina += 1

    return pedidos_all


def _build_client_wallet_cache_rows():
    rows = []
    pagina = 1
    now_ts = datetime.utcnow().isoformat()

    while True:
        try:
            resp = tiny.pesquisar_contatos(pesquisa="", pagina=pagina)
        except TinyAPIError as e:
            msg = str(e).lower()
            if "não retornou registros" in msg or "nao retornou registros" in msg:
                break
            raise

        contatos = resp.get("contatos") or []
        if not contatos:
            break

        for it in contatos:
            c = it.get("contato", it)
            if not c.get("id"):
                continue

            nome = str(c.get("nome") or "").strip()
            cpf_cnpj = str(c.get("cpf_cnpj") or "").strip()

            pedidos = _client_wallet_cache_fetch_orders_for_contact(
                nome=nome,
                cpf_cnpj=cpf_cnpj,
            )

            orders_count = len(pedidos)
            orders_total = 0.0
            last_order_date = None

            for pedido in pedidos:
                orders_total += _client_wallet_cache_safe_float(pedido.get("valor"))
                dt = _client_wallet_cache_parse_date(pedido.get("data_pedido"))
                if dt and (last_order_date is None or dt > last_order_date):
                    last_order_date = dt

            days_without_order = None
            if last_order_date:
                days_without_order = (datetime.utcnow().date() - last_order_date).days

            rows.append({
                "client_id": str(c.get("id") or ""),
                "client_name": nome,
                "client_doc": cpf_cnpj,
                "city": str(c.get("cidade") or ""),
                "uf": str(c.get("uf") or ""),
                "email": str(c.get("email") or ""),
                "phone": str(c.get("fone") or ""),
                "seller_id": str(c.get("id_vendedor") or c.get("idVendedor") or ""),
                "seller_name": str(c.get("nome_vendedor") or c.get("nomeVendedor") or ""),
                "orders_count": int(orders_count or 0),
                "orders_total": float(orders_total or 0),
                "last_order_date": str(last_order_date) if last_order_date else None,
                "days_without_order": int(days_without_order) if days_without_order is not None else None,
                "source_updated_at": now_ts,
                "cache_updated_at": now_ts,
            })

        try:
            numero_paginas = int(resp.get("numero_paginas") or pagina)
        except Exception:
            numero_paginas = pagina

        if pagina >= numero_paginas:
            break

        pagina += 1

    return rows


@app.post("/api/ops/refresh-client-wallet-cache")
@app.post("/ops/refresh-client-wallet-cache")
def refresh_client_wallet_cache(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Apenas admin pode atualizar o cache da carteira.")

    started_at = datetime.utcnow().isoformat()

    rows = _build_client_wallet_cache_rows()

    bq = _client_wallet_cache_bq()
    table_ref = _client_wallet_cache_table_ref()

    from google.cloud import bigquery
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        schema=[
            bigquery.SchemaField("client_id", "STRING"),
            bigquery.SchemaField("client_name", "STRING"),
            bigquery.SchemaField("client_doc", "STRING"),
            bigquery.SchemaField("city", "STRING"),
            bigquery.SchemaField("uf", "STRING"),
            bigquery.SchemaField("email", "STRING"),
            bigquery.SchemaField("phone", "STRING"),
            bigquery.SchemaField("seller_id", "STRING"),
            bigquery.SchemaField("seller_name", "STRING"),
            bigquery.SchemaField("orders_count", "INT64"),
            bigquery.SchemaField("orders_total", "NUMERIC"),
            bigquery.SchemaField("last_order_date", "DATE"),
            bigquery.SchemaField("days_without_order", "INT64"),
            bigquery.SchemaField("source_updated_at", "TIMESTAMP"),
            bigquery.SchemaField("cache_updated_at", "TIMESTAMP"),
        ],
    )

    load_job = bq.load_table_from_json(rows, table_ref, job_config=job_config)
    load_job.result()

    finished_at = datetime.utcnow().isoformat()

    return {
        "status": "ok",
        "rows_written": len(rows),
        "started_at": started_at,
        "finished_at": finished_at,
        "table": table_ref,
    }


@app.get("/api/tiny/client-wallet-cached")
@app.get("/tiny/client-wallet-cached")
def tiny_client_wallet_cached(
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    seller_id: str = Query(default=""),
):
    from google.cloud import bigquery

    bq = _client_wallet_cache_bq()
    table_ref = _client_wallet_cache_table_ref()

    offset = (page - 1) * page_size

    where = []
    params = []

    if q:
        where.append("(LOWER(client_name) LIKE LOWER(@q) OR client_doc LIKE @q_exact)")
        params.append(bigquery.ScalarQueryParameter("q", "STRING", f"%{q}%"))
        params.append(bigquery.ScalarQueryParameter("q_exact", "STRING", f"%{q}%"))

    if seller_id:
        where.append("seller_id = @seller_id")
        params.append(bigquery.ScalarQueryParameter("seller_id", "STRING", str(seller_id)))

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    sql = f"""
      SELECT
        client_id,
        client_name,
        client_doc,
        city,
        uf,
        email,
        phone,
        seller_id,
        seller_name,
        orders_count,
        orders_total,
        last_order_date,
        days_without_order,
        cache_updated_at
      FROM `{table_ref}`
      {where_sql}
      ORDER BY client_name
      LIMIT @limit_plus_one
      OFFSET @offset
    """

    params.append(bigquery.ScalarQueryParameter("limit_plus_one", "INT64", page_size + 1))
    params.append(bigquery.ScalarQueryParameter("offset", "INT64", offset))

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(bq.query(sql, job_config=job_config).result())

    has_more = len(rows) > page_size
    rows = rows[:page_size]

    items = []
    cache_updated_at = None

    for r in rows:
        cache_updated_at = cache_updated_at or getattr(r, "cache_updated_at", None)
        items.append({
            "id": r.client_id,
            "nome": r.client_name,
            "cpf_cnpj": r.client_doc,
            "cidade": r.city,
            "uf": r.uf,
            "email": r.email,
            "fone": r.phone,
            "seller_id": r.seller_id,
            "nome_vendedor": r.seller_name,
            "qtd_pedidos": r.orders_count,
            "total_pedidos": float(r.orders_total or 0),
            "ultimo_pedido": str(r.last_order_date) if r.last_order_date else "",
            "dias_sem_pedido": r.days_without_order,
        })

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "cache_updated_at": str(cache_updated_at) if cache_updated_at else None,
    }



@app.get("/api/tiny/client-wallet-cached-sellers")
@app.get("/tiny/client-wallet-cached-sellers")
def tiny_client_wallet_cached_sellers():
    bq = _client_wallet_cache_bq()
    table_ref = _client_wallet_cache_table_ref()

    sql = f"""
      SELECT DISTINCT
        seller_id,
        seller_name
      FROM `{table_ref}`
      WHERE seller_id IS NOT NULL
        AND seller_id != ""
        AND seller_name IS NOT NULL
        AND seller_name != ""
      ORDER BY seller_name
    """

    rows = list(bq.query(sql).result())

    items = []
    for r in rows:
        items.append({
            "seller_id": str(r.seller_id or ""),
            "seller_name": str(r.seller_name or ""),
        })

    return {"items": items}
