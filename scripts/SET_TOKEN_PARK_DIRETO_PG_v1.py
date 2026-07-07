import os
import psycopg2

token = os.getenv("TINY_TOKEN_TEMP_PARK", "").strip()
if not token:
    raise SystemExit("ERRO: token park vazio.")

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "127.0.0.1"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "trml_erp"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", ""),
)
conn.autocommit = True

with conn.cursor() as cur:
    cur.execute("""
        INSERT INTO erp.companies (
            company_key, company_name, tiny_base_url, tiny_token, active, updated_at
        )
        VALUES (
            'park', 'Informática / Park', 'https://api.tiny.com.br/api2', %s, TRUE, now()
        )
        ON CONFLICT (company_key) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            tiny_base_url = EXCLUDED.tiny_base_url,
            tiny_token = EXCLUDED.tiny_token,
            active = TRUE,
            updated_at = now()
    """, (token,))

    cur.execute("""
        SELECT company_key, company_name, active,
               CASE WHEN COALESCE(tiny_token, '') <> '' THEN TRUE ELSE FALSE END AS has_db_token
        FROM erp.companies
        WHERE company_key = 'park'
    """)
    print(cur.fetchone())

conn.close()
print("OK: token da park gravado direto no PostgreSQL.")
