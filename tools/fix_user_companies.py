import os
import psycopg2
import psycopg2.extras

TARGETS = ["Alessandra", "Diego", "Fernanda"]
COMPANIES = ["parton", "park"]

conn = psycopg2.connect(
    host="127.0.0.1",
    port="5432",
    dbname="trml_erp",
    user="postgres",
    password=os.getenv("PGPASSWORD", ""),
)

with conn:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for login in TARGETS:
            cur.execute("""
                SELECT id, login
                FROM erp.users
                WHERE lower(login) = lower(%s)
                LIMIT 1
            """, (login,))
            user = cur.fetchone()

            if not user:
                print(f"USUÁRIO NÃO ENCONTRADO: {login}")
                continue

            user_id = user["id"]
            print(f"Ajustando empresas: {login} / {user_id}")

            cur.execute("""
                DELETE FROM erp.user_companies
                WHERE user_id = %s
            """, (user_id,))

            for company in COMPANIES:
                cur.execute("""
                    INSERT INTO erp.user_companies (user_id, company_key)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id, company_key) DO NOTHING
                """, (user_id, company))

        print("OK: empresas ajustadas.")

conn.close()
