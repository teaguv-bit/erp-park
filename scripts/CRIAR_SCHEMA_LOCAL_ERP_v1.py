import os
import psycopg2

DB_HOST = os.getenv("PGHOST", "127.0.0.1")
DB_PORT = int(os.getenv("PGPORT", "5432"))
DB_NAME = os.getenv("PGDATABASE", "trml_erp")
DB_USER = os.getenv("PGUSER", "postgres")
DB_PASS = os.getenv("PGPASSWORD", "")

conn = psycopg2.connect(
    host=DB_HOST,
    port=DB_PORT,
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS,
)
conn.autocommit = True

sql = """
CREATE SCHEMA IF NOT EXISTS erp;

CREATE TABLE IF NOT EXISTS erp.companies (
    company_key TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    tiny_token TEXT,
    tiny_base_url TEXT DEFAULT 'https://api.tiny.com.br/api2',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS erp.quotes (
    quote_id TEXT PRIMARY KEY,
    quote_number BIGINT UNIQUE,
    company_key TEXT NOT NULL DEFAULT 'parton',
    tiny_order_id BIGINT,
    tiny_order_number TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    internal_status TEXT,

    client_id BIGINT NOT NULL,
    client_snapshot JSONB,

    seller_id BIGINT,
    seller_name TEXT,
    seller_snapshot JSONB,

    shipping_method_id BIGINT,
    shipping_method_name TEXT,
    freight_method_id BIGINT,
    freight_method_name TEXT,

    payment_method_code TEXT,
    payment_method_name TEXT,
    payment_meio TEXT,
    payment_conta TEXT,
    payment_due_date TEXT,
    payment_category TEXT,
    payment_notify BOOLEAN,

    totals JSONB,
    notes TEXT,
    payload JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS erp.quote_items (
    quote_id TEXT NOT NULL REFERENCES erp.quotes(quote_id) ON DELETE CASCADE,
    line INTEGER NOT NULL,
    product_id BIGINT NOT NULL,
    sku_snapshot TEXT,
    name_snapshot TEXT,
    qty NUMERIC,
    list_price NUMERIC,
    discount_pct NUMERIC,
    unit_price_disc NUMERIC,
    line_total NUMERIC,
    raw JSONB,
    PRIMARY KEY (quote_id, line)
);

CREATE TABLE IF NOT EXISTS erp.separation_orders (
    tiny_order_id BIGINT PRIMARY KEY,
    tiny_order_number TEXT,
    quote_id TEXT,
    quote_number BIGINT,
    company_key TEXT NOT NULL DEFAULT 'parton',
    client_name TEXT,
    seller_name TEXT,
    status TEXT DEFAULT 'A separar',
    printed BOOLEAN DEFAULT FALSE,
    printed_at TIMESTAMPTZ,
    separated_at TIMESTAMPTZ,
    checked_at TIMESTAMPTZ,
    assigned_to TEXT,
    notes TEXT,
    packaging_boxes INTEGER,
    packaging_bags INTEGER,
    packaging_weight_kg NUMERIC,
    packaging_height_cm NUMERIC,
    packaging_width_cm NUMERIC,
    packaging_length_cm NUMERIC,
    packaging_volumes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_erp_quotes_company_created
    ON erp.quotes(company_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_erp_quotes_status
    ON erp.quotes(company_key, status, internal_status);

CREATE INDEX IF NOT EXISTS idx_erp_quote_items_quote
    ON erp.quote_items(quote_id);
"""

with conn.cursor() as cur:
    cur.execute(sql)

print("OK: schema erp criado/validado no PostgreSQL.")
conn.close()
