import os
import psycopg2
import psycopg2.extras

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "127.0.0.1"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "trml_erp"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", ""),
)

with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    print("\n=== QUOTES POR EMPRESA ===")
    cur.execute("""
        SELECT company_key, COUNT(*) AS total
        FROM erp.quotes
        GROUP BY company_key
        ORDER BY company_key
    """)
    print([dict(r) for r in cur.fetchall()])

    print("\n=== QUOTE_ITEMS POR EMPRESA ===")
    cur.execute("""
        SELECT q.company_key, COUNT(qi.*) AS total
        FROM erp.quote_items qi
        JOIN erp.quotes q ON q.quote_id = qi.quote_id
        GROUP BY q.company_key
        ORDER BY q.company_key
    """)
    print([dict(r) for r in cur.fetchall()])

    print("\n=== SEPARATION_ORDERS POR EMPRESA ===")
    cur.execute("""
        SELECT company_key, COUNT(*) AS total
        FROM erp.separation_orders
        GROUP BY company_key
        ORDER BY company_key
    """)
    print([dict(r) for r in cur.fetchall()])

    print("\n=== QUOTES POR STATUS ===")
    cur.execute("""
        SELECT company_key, COALESCE(internal_status, 'SEM_STATUS') AS internal_status, COUNT(*) AS total
        FROM erp.quotes
        GROUP BY company_key, COALESCE(internal_status, 'SEM_STATUS')
        ORDER BY company_key, total DESC
    """)
    for r in cur.fetchall():
        print(dict(r))

conn.close()
