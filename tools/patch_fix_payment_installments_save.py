from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

old = '''    payment_due_date: Optional[str] = None
    payment_category: Optional[str] = None
    payment_notify: Optional[bool] = None
    freight_paid_client: Optional[float] = 0
'''

new = '''    payment_due_date: Optional[str] = None
    payment_category: Optional[str] = None
    payment_notify: Optional[bool] = None
    payment_condition: Optional[str] = None
    payment_installments: Optional[List[Dict[str, Any]]] = None
    payment_card_brand: Optional[str] = None
    freight_paid_client: Optional[float] = 0
'''

if old not in txt:
    raise SystemExit("ERRO: bloco de campos de pagamento no QuoteCreateIn nao encontrado.")

txt = txt.replace(old, new, 1)

path.write_text(txt, encoding="utf-8")
print("OK - QuoteCreateIn agora aceita payment_condition, payment_installments e payment_card_brand.")
