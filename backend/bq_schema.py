import os
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "").strip()
DATASET_ID = os.getenv("BQ_DATASET_ID", "tiny_orcamento").strip()
BQ_LOCATION = os.getenv("BQ_LOCATION", "US").strip() or "US"


def get_bq_client() -> bigquery.Client:
    if not PROJECT_ID:
        raise ValueError("Defina GCP_PROJECT_ID no .env")
    return bigquery.Client(project=PROJECT_ID)


def ensure_dataset(client: bigquery.Client, project_id: str, dataset_id: str, location: str):
    ds_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    ds_ref.location = location
    try:
        client.get_dataset(ds_ref)
        return
    except Exception:
        client.create_dataset(ds_ref)


def ensure_table(client: bigquery.Client, table_id: str, schema: list[bigquery.SchemaField]):
    try:
        client.get_table(table_id)
        return
    except Exception:
        tbl = bigquery.Table(table_id, schema=schema)
        client.create_table(tbl)


def add_column_if_missing(client: bigquery.Client, table_id: str, col_name: str, col_type: str):
    sql = f"ALTER TABLE `{table_id}` ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
    client.query(sql).result()


def bootstrap():
    client = get_bq_client()
    ensure_dataset(client, PROJECT_ID, DATASET_ID, BQ_LOCATION)

    quotes_table = f"{PROJECT_ID}.{DATASET_ID}.quotes"
    quote_items_table = f"{PROJECT_ID}.{DATASET_ID}.quote_items"
    separation_orders_table = f"{PROJECT_ID}.{DATASET_ID}.separation_orders"

    ensure_table(
        client,
        quotes_table,
        schema=[
            bigquery.SchemaField("quote_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("quote_number", "INT64"),  # ✅ número da pré-venda
            bigquery.SchemaField("tiny_order_id", "INT64"),
            bigquery.SchemaField("tiny_order_number", "STRING"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED"),  # draft | ordered

            bigquery.SchemaField("client_id", "INT64", mode="REQUIRED"),
            bigquery.SchemaField("client_snapshot", "STRING"),

            bigquery.SchemaField("seller_id", "INT64"),
            bigquery.SchemaField("seller_name", "STRING"),
            bigquery.SchemaField("seller_snapshot", "STRING"),

            # ✅ envio/frete do Tiny
            bigquery.SchemaField("shipping_method_id", "INT64"),
            bigquery.SchemaField("shipping_method_name", "STRING"),
            bigquery.SchemaField("freight_method_id", "INT64"),
            bigquery.SchemaField("freight_method_name", "STRING"),

            # ✅ forma de pagamento (Tiny)
            bigquery.SchemaField("payment_method_code", "STRING"),
            bigquery.SchemaField("payment_method_name", "STRING"),
            bigquery.SchemaField("payment_meio", "STRING"),
            bigquery.SchemaField("payment_conta", "STRING"),
            # ✅ campos adicionais (tela de Pagamento do Tiny)
            bigquery.SchemaField("payment_due_date", "STRING"),
            bigquery.SchemaField("payment_category", "STRING"),
            bigquery.SchemaField("payment_notify", "BOOL"),

            # ✅ status interno (somente nosso)
            bigquery.SchemaField("internal_status", "STRING"),  # Aguardando Aprovação | Aprovado

            bigquery.SchemaField("totals", "STRING"),
            bigquery.SchemaField("notes", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("updated_at", "TIMESTAMP"),
            bigquery.SchemaField("payload", "STRING"),
        ],
    )

    ensure_table(
        client,
        quote_items_table,
        schema=[
            bigquery.SchemaField("quote_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("line", "INT64", mode="REQUIRED"),  # ✅ número da linha
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED"),
            bigquery.SchemaField("sku_snapshot", "STRING"),
            bigquery.SchemaField("name_snapshot", "STRING"),
            bigquery.SchemaField("qty", "FLOAT64"),
            bigquery.SchemaField("list_price", "FLOAT64"),
            bigquery.SchemaField("discount_pct", "FLOAT64"),
            bigquery.SchemaField("unit_price_disc", "FLOAT64"),
            bigquery.SchemaField("line_total", "FLOAT64"),
            bigquery.SchemaField("raw", "STRING"),
        ],
    )

    ensure_table(
        client,
        separation_orders_table,
        schema=[
            bigquery.SchemaField("tiny_order_id", "INT64", mode="REQUIRED"),
            bigquery.SchemaField("tiny_order_number", "STRING"),
            bigquery.SchemaField("quote_id", "STRING"),
            bigquery.SchemaField("quote_number", "INT64"),
            bigquery.SchemaField("client_name", "STRING"),
            bigquery.SchemaField("seller_name", "STRING"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("printed", "BOOL"),
            bigquery.SchemaField("printed_at", "TIMESTAMP"),
            bigquery.SchemaField("separated_at", "TIMESTAMP"),
            bigquery.SchemaField("checked_at", "TIMESTAMP"),
            bigquery.SchemaField("assigned_to", "STRING"),
            bigquery.SchemaField("notes", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("updated_at", "TIMESTAMP"),
            bigquery.SchemaField("packaging_boxes", "INT64"),
            bigquery.SchemaField("packaging_bags", "INT64"),
            bigquery.SchemaField("packaging_weight_kg", "FLOAT64"),
            bigquery.SchemaField("packaging_height_cm", "FLOAT64"),
            bigquery.SchemaField("packaging_width_cm", "FLOAT64"),
            bigquery.SchemaField("packaging_length_cm", "FLOAT64"),
            bigquery.SchemaField("packaging_volumes", "INT64"),
        ],
    )

    # upgrades seguros
    add_column_if_missing(client, quotes_table, "quote_number", "INT64")

    add_column_if_missing(client, quotes_table, "shipping_method_id", "INT64")
    add_column_if_missing(client, quotes_table, "shipping_method_name", "STRING")
    add_column_if_missing(client, quotes_table, "freight_method_id", "INT64")
    add_column_if_missing(client, quotes_table, "freight_method_name", "STRING")

    # pagamento (campos adicionais)
    add_column_if_missing(client, quotes_table, "payment_due_date", "STRING")
    add_column_if_missing(client, quotes_table, "payment_category", "STRING")
    add_column_if_missing(client, quotes_table, "payment_notify", "BOOL")

    add_column_if_missing(client, quotes_table, "internal_status", "STRING")

    add_column_if_missing(client, separation_orders_table, "tiny_order_number", "STRING")
    add_column_if_missing(client, separation_orders_table, "quote_id", "STRING")
    add_column_if_missing(client, separation_orders_table, "quote_number", "INT64")
    add_column_if_missing(client, separation_orders_table, "client_name", "STRING")
    add_column_if_missing(client, separation_orders_table, "seller_name", "STRING")
    add_column_if_missing(client, separation_orders_table, "status", "STRING")
    add_column_if_missing(client, separation_orders_table, "printed", "BOOL")
    add_column_if_missing(client, separation_orders_table, "printed_at", "TIMESTAMP")
    add_column_if_missing(client, separation_orders_table, "separated_at", "TIMESTAMP")
    add_column_if_missing(client, separation_orders_table, "checked_at", "TIMESTAMP")
    add_column_if_missing(client, separation_orders_table, "assigned_to", "STRING")
    add_column_if_missing(client, separation_orders_table, "notes", "STRING")
    add_column_if_missing(client, separation_orders_table, "updated_at", "TIMESTAMP")
    add_column_if_missing(client, separation_orders_table, "packaging_boxes", "INT64")
    add_column_if_missing(client, separation_orders_table, "packaging_bags", "INT64")
    add_column_if_missing(client, separation_orders_table, "packaging_weight_kg", "FLOAT64")
    add_column_if_missing(client, separation_orders_table, "packaging_height_cm", "FLOAT64")
    add_column_if_missing(client, separation_orders_table, "packaging_width_cm", "FLOAT64")
    add_column_if_missing(client, separation_orders_table, "packaging_length_cm", "FLOAT64")
    add_column_if_missing(client, separation_orders_table, "packaging_volumes", "INT64")

    print(f"OK: {PROJECT_ID}.{DATASET_ID} -> tables quotes, quote_items, separation_orders")


if __name__ == "__main__":
    bootstrap()