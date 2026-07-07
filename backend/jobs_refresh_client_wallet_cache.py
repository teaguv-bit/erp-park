import os
import json
from datetime import datetime
from google.cloud import bigquery

from tiny_client import TinyClient, TinyConfig


def table_ref():
    project_id = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or "projetotrml"
    )
    dataset_id = os.getenv("BQ_DATASET_ID", "tiny_orcamento_beta").strip() or "tiny_orcamento_beta"
    return f"{project_id}.{dataset_id}.tiny_client_wallet_cache"


def parse_date(value):
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


def safe_float(value):
    try:
        return float(str(value or 0).replace(",", "."))
    except Exception:
        return 0.0


def norm_text(value):
    return " ".join(str(value or "").strip().lower().split())


def contact_key(nome, seller_id="", seller_name=""):
    sid = str(seller_id or "").strip()
    sname = norm_text(seller_name)
    if sid:
        return f"{norm_text(nome)}|{sid}"
    return f"{norm_text(nome)}|{sname}"


def fetch_all_contacts(tiny: TinyClient):
    contatos_all = []
    pagina = 1

    while True:
        resp = tiny.pesquisar_contatos(pesquisa="", pagina=pagina)
        contatos = resp.get("contatos") or []
        if not contatos:
            break

        for row in contatos:
            contatos_all.append(row.get("contato", row))

        try:
            numero_paginas = int(resp.get("numero_paginas") or pagina)
        except Exception:
            numero_paginas = pagina

        if pagina >= numero_paginas:
            break

        pagina += 1

    return contatos_all


def fetch_all_orders(tiny: TinyClient):
    pedidos_all = []
    pagina = 1
    today = datetime.utcnow().strftime("%d/%m/%Y")

    while True:
        resp = tiny.pesquisar_pedidos(
            dataInicial="01/01/2010",
            dataFinal=today,
            pagina=pagina,
            sort="DESC",
        )

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


def aggregate_orders_by_contact(pedidos):
    agg = {}

    for pedido in pedidos:
        nome = str(pedido.get("nome") or "").strip()
        if not nome:
            continue

        seller_id = str(pedido.get("id_vendedor") or "")
        seller_name = str(pedido.get("nome_vendedor") or "")
        key = contact_key(nome, seller_id=seller_id, seller_name=seller_name)

        bucket = agg.setdefault(key, {
            "orders_count": 0,
            "orders_total": 0.0,
            "last_order_date": None,
        })

        bucket["orders_count"] += 1
        bucket["orders_total"] += safe_float(pedido.get("valor"))

        dt = parse_date(pedido.get("data_pedido"))
        if dt and (bucket["last_order_date"] is None or dt > bucket["last_order_date"]):
            bucket["last_order_date"] = dt

    return agg


def build_rows(tiny: TinyClient):
    contatos = fetch_all_contacts(tiny)
    pedidos = fetch_all_orders(tiny)
    agg = aggregate_orders_by_contact(pedidos)

    now_ts = datetime.utcnow().isoformat()
    rows = []

    for c in contatos:
        if not c.get("id"):
            continue

        nome = str(c.get("nome") or "").strip()
        seller_id = str(c.get("id_vendedor") or c.get("idVendedor") or "")
        seller_name = str(c.get("nome_vendedor") or c.get("nomeVendedor") or "")

        key = contact_key(nome, seller_id=seller_id, seller_name=seller_name)
        metrics = agg.get(key, {})

        orders_count = int(metrics.get("orders_count") or 0)
        orders_total = float(metrics.get("orders_total") or 0.0)
        last_order_date = metrics.get("last_order_date")
        days_without_order = None

        if last_order_date:
            days_without_order = (datetime.utcnow().date() - last_order_date).days

        rows.append({
            "client_id": str(c.get("id") or ""),
            "client_name": nome,
            "client_doc": str(c.get("cpf_cnpj") or ""),
            "city": str(c.get("cidade") or ""),
            "uf": str(c.get("uf") or ""),
            "email": str(c.get("email") or ""),
            "phone": str(c.get("fone") or ""),
            "seller_id": seller_id,
            "seller_name": seller_name,
            "orders_count": orders_count,
            "orders_total": orders_total,
            "last_order_date": str(last_order_date) if last_order_date else None,
            "days_without_order": int(days_without_order) if days_without_order is not None else None,
            "source_updated_at": now_ts,
            "cache_updated_at": now_ts,
        })

    return rows


def main():
    token = os.getenv("TINY_TOKEN", "").strip()
    if not token:
        raise SystemExit("TINY_TOKEN está vazio.")

    tiny = TinyClient(TinyConfig(token=token))

    rows = build_rows(tiny)

    bq = bigquery.Client(project=(
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or "projetotrml"
    ))

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

    table = table_ref()
    load_job = bq.load_table_from_json(rows, table, job_config=job_config)
    load_job.result()

    print(json.dumps({
        "status": "ok",
        "rows_written": len(rows),
        "table": table,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
