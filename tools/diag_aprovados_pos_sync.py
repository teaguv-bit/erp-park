import os
import psycopg2
import psycopg2.extras
from pathlib import Path
from datetime import datetime

out = Path(r"C:\TRML_LOCAL\ERP\DIAG_pedidos_aprovados_pos_sync.txt")

conn = psycopg2.connect(
    host="127.0.0.1",
    port="5432",
    dbname="trml_erp",
    user="postgres",
    password=os.getenv("PGPASSWORD", ""),
)

with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    lines = []
    lines.append("DIAGNÓSTICO PEDIDOS APROVADOS PÓS-SYNC")
    lines.append(datetime.now().isoformat())
    lines.append("")

    lines.append("=== CONTAGEM POR EMPRESA E STATUS ===")
    cur.execute("""
        SELECT company_key, COALESCE(internal_status, 'SEM_STATUS') AS internal_status, COUNT(*) AS total
        FROM erp.quotes
        GROUP BY company_key, COALESCE(internal_status, 'SEM_STATUS')
        ORDER BY company_key, total DESC
    """)
    for r in cur.fetchall():
        lines.append(str(dict(r)))

    lines.append("")
    lines.append("=== AMOSTRA DE PEDIDOS AINDA APROVADOS ===")
    cur.execute("""
        SELECT
          quote_id,
          quote_number,
          company_key,
          tiny_order_id,
          tiny_order_number,
          status,
          internal_status,
          seller_name,
          created_at,
          updated_at
        FROM erp.quotes
        WHERE internal_status ILIKE 'Aprovado'
        ORDER BY company_key, updated_at DESC NULLS LAST, created_at DESC NULLS LAST
        LIMIT 100
    """)
    for r in cur.fetchall():
        lines.append(str(dict(r)))

conn.close()
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
