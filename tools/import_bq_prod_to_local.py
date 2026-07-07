import argparse
import gzip
import json
import zipfile
from pathlib import Path
from datetime import datetime
from decimal import Decimal

import psycopg2
import psycopg2.extras


DATASET_COMPANY = {
    "tiny_orcamento": "parton",
    "tiny_orcamento_informatica": "park",
}

IMPORT_TABLES = [
    "quotes",
    "quote_items",
    "separation_orders",
    "clients",
    "client_wallet_assignments",
    "products",
]

SKIP_TABLES = {
    "tiny_v3_oauth_tokens",
    "app_users",
    "app_user_audit",
    "app_settings",
    "app_settings_audit",
    "sync_runs",
    "product_stock_daily",
}


def adapt_value(v):
    if isinstance(v, (dict, list)):
        return psycopg2.extras.Json(v)
    return v


def table_columns(cur, table_name):
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='erp' AND table_name=%s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    return [r[0] for r in cur.fetchall()]


def table_exists(cur, table_name):
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1
          FROM information_schema.tables
          WHERE table_schema='erp' AND table_name=%s
        )
        """,
        (table_name,),
    )
    return bool(cur.fetchone()[0])


def iter_zip_jsonl(zip_path, dataset, table):
    suffix = f"/data/{dataset}.{table}.jsonl.gz"
    with zipfile.ZipFile(zip_path, "r") as z:
        names = [n for n in z.namelist() if n.endswith(suffix)]
        if not names:
            return
        name = names[0]
        with z.open(name, "r") as raw:
            with gzip.GzipFile(fileobj=raw, mode="rb") as gz:
                for line in gz:
                    if line.strip():
                        yield json.loads(line.decode("utf-8"))


def count_zip_jsonl(zip_path, dataset, table):
    return sum(1 for _ in iter_zip_jsonl(zip_path, dataset, table))


def ensure_import_columns(cur):
    # Colunas que o ERP local usa e que podem não existir dependendo do checkpoint.
    cur.execute("""
    ALTER TABLE erp.quotes ADD COLUMN IF NOT EXISTS company_key TEXT;
    ALTER TABLE erp.separation_orders ADD COLUMN IF NOT EXISTS company_key TEXT;
    """)


def reset_production_data(cur):
    print("Limpando dados locais de quotes/itens/separação/clientes/produtos/carteira para parton/park...")

    # Itens dependem de quotes.
    cur.execute("""
        DELETE FROM erp.quote_items qi
        USING erp.quotes q
        WHERE qi.quote_id = q.quote_id
          AND q.company_key IN ('parton', 'park')
    """)

    cur.execute("""
        DELETE FROM erp.separation_orders
        WHERE company_key IN ('parton', 'park')
           OR company_key IS NULL
    """)

    cur.execute("""
        DELETE FROM erp.quotes
        WHERE company_key IN ('parton', 'park')
           OR company_key IS NULL
    """)

    # Se as tabelas existirem, limpar bases espelho. Não mexe em users.
    for t in ["clients", "products", "client_wallet_assignments"]:
        if table_exists(cur, t):
            cur.execute(f"DELETE FROM erp.{t}")


def normalize_quote(row, company_key):
    row = dict(row)
    row["company_key"] = company_key

    # Os datasets cloud não tinham company_key em quotes.
    # Mantém payload/totals/snapshots como JSONB quando a coluna local for JSONB.
    return row


def normalize_quote_item(row, company_key):
    # quote_items não precisa company_key se a tabela local não tiver.
    return dict(row)


def normalize_separation(row, company_key):
    row = dict(row)
    row["company_key"] = company_key
    return row


def normalize_generic(row, company_key=None):
    return dict(row)


def upsert_row(cur, table, row, conflict_cols):
    cols_existing = set(table_columns(cur, table))
    row = {k: v for k, v in row.items() if k in cols_existing}

    if not row:
        return False

    cols = list(row.keys())
    values = [adapt_value(row[c]) for c in cols]

    col_sql = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))

    update_cols = [c for c in cols if c not in conflict_cols]
    if update_cols:
        update_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
        sql = f"""
            INSERT INTO erp.{table} ({col_sql})
            VALUES ({placeholders})
            ON CONFLICT ({", ".join(conflict_cols)})
            DO UPDATE SET {update_sql}
        """
    else:
        sql = f"""
            INSERT INTO erp.{table} ({col_sql})
            VALUES ({placeholders})
            ON CONFLICT ({", ".join(conflict_cols)})
            DO NOTHING
        """

    cur.execute(sql, values)
    return True


def import_table(cur, zip_path, dataset, table):
    company_key = DATASET_COMPANY[dataset]

    if not table_exists(cur, table):
        print(f"[SKIP] erp.{table} não existe no banco local.")
        return 0

    if table == "quotes":
        conflict = ["quote_id"]
        normalizer = normalize_quote
    elif table == "quote_items":
        conflict = ["quote_id", "line"]
        normalizer = normalize_quote_item
    elif table == "separation_orders":
        conflict = ["tiny_order_id"]
        normalizer = normalize_separation
    elif table == "clients":
        conflict = ["client_id"]
        normalizer = normalize_generic
    elif table == "products":
        conflict = ["product_id"] if "product_id" in table_columns(cur, "products") else ["id"]
        normalizer = normalize_generic
    elif table == "client_wallet_assignments":
        cols = table_columns(cur, table)
        if "client_id" in cols and "seller_id" in cols:
            conflict = ["client_id", "seller_id"]
        else:
            print(f"[SKIP] erp.{table} não tem chave esperada.")
            return 0
        normalizer = normalize_generic
    else:
        return 0

    total = 0
    for row in iter_zip_jsonl(zip_path, dataset, table):
        new_row = normalizer(row, company_key)
        if upsert_row(cur, table, new_row, conflict):
            total += 1

    return total


def dry_run(zip_path):
    print("=== DRY RUN DO ZIP ===")
    for dataset in DATASET_COMPANY:
        print(f"\nDataset: {dataset} => company_key={DATASET_COMPANY[dataset]}")
        for table in IMPORT_TABLES:
            c = count_zip_jsonl(zip_path, dataset, table)
            print(f"  {table}: {c} linhas no ZIP")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reset-production-data", action="store_true")
    args = ap.parse_args()

    zip_path = Path(args.zip)
    if not zip_path.exists():
        raise SystemExit(f"ZIP não encontrado: {zip_path}")

    dry_run(zip_path)

    if not args.apply:
        print("\nDRY RUN concluído. Nada foi importado.")
        print("Para importar de verdade, rode novamente com --apply --reset-production-data.")
        return

    conn = psycopg2.connect(
        host="127.0.0.1",
        port="5432",
        dbname="trml_erp",
        user="postgres",
        password=os.environ.get("PGPASSWORD", ""),
    )

    try:
        with conn:
            with conn.cursor() as cur:
                ensure_import_columns(cur)

                if args.reset_production_data:
                    reset_production_data(cur)

                print("\n=== IMPORTANDO ===")
                totals = {}
                for dataset in DATASET_COMPANY:
                    for table in IMPORT_TABLES:
                        key = f"{dataset}.{table}"
                        n = import_table(cur, zip_path, dataset, table)
                        totals[key] = n
                        print(f"{key}: {n}")

                print("\n=== RESUMO IMPORTAÇÃO ===")
                print(json.dumps(totals, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    import os
    main()
