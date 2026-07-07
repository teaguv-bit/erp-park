from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

# 1) Add GCloud-compatible payment helpers if missing.
if "def _map_payment_code_for_tiny" not in txt:
    payment_methods_re = re.compile(r'PAYMENT_METHODS\s*=\s*\{.*?\n\}', re.S)
    m = payment_methods_re.search(txt)
    if not m:
        raise SystemExit("ERRO: bloco PAYMENT_METHODS nao encontrado.")

    helpers = r'''

PAYMENT_CONTA_PORTADOR_MAP = {
    "suprimento_parton_olist": "(Suprimento)Parton - Olist",
    "suprimento_parton_stone": "(Suprimento)Parton - Stone",
}


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
'''
    txt = txt[:m.end()] + helpers + txt[m.end():]

# 2) Make installments use normalized payment fields.
old = '''        payment_code = _clean_str(quote.get("payment_method_code"))
        payment_meio = _clean_str(quote.get("payment_meio"))
        payment_conta = _clean_str(quote.get("payment_conta"))
'''
new = '''        payment_code = payment_code_tiny or ""
        payment_meio = meio_txt or ""
        payment_conta = portador_txt or ""
'''
if old not in txt:
    raise SystemExit("ERRO: bloco payment_code/payment_meio/payment_conta dentro de _build_parcelas nao encontrado.")
txt = txt.replace(old, new, 1)

# 3) In fallback installment, always send data like GCloud.
old = '''            parcela = {
                "dias": 0,
                "valor": round(total_value, 2),
                "destino": "Contas a Receber",
            }
            if quote_due_date:
                parcela["data"] = quote_due_date.strftime("%d/%m/%Y")
'''
new = '''            parcela = {
                "dias": 0,
                "valor": round(total_value, 2),
                "data": base_date.strftime("%d/%m/%Y"),
                "destino": "Contas a Receber",
            }
'''
if old not in txt:
    raise SystemExit("ERRO: bloco fallback parcela sem data fixa nao encontrado.")
txt = txt.replace(old, new, 1)

# 4) Compute payment fields using GCloud rules before building pedido.
old = '''    freight_paid_company = _safe_float(
        payload_saved.get("freight_paid_company"),
        _safe_float(totals.get("freight_paid_company"), 0.0),
    )

    pedido = {
'''
new = '''    freight_paid_company = _safe_float(
        payload_saved.get("freight_paid_company"),
        _safe_float(totals.get("freight_paid_company"), 0.0),
    )

    payment_code_rule, payment_meio_rule, payment_conta_rule = _apply_payment_business_rules(
        quote.get("payment_method_code"),
        quote.get("payment_meio"),
        quote.get("payment_conta"),
    )
    payment_code_tiny = _map_payment_code_for_tiny(payment_code_rule)
    meio_txt = _resolve_meio_pagamento_tiny(payment_meio_rule, payment_conta_rule)
    portador_txt = _resolve_portador_nome(payment_conta_rule)

    if payment_code_tiny == "link_pagamento":
        portador_txt = None

    pedido = {
'''
if old not in txt:
    raise SystemExit("ERRO: bloco freight_paid_company/pedido nao encontrado.")
txt = txt.replace(old, new, 1)

# 5) Top-level payment fields in pedido must use normalized GCloud-compatible values.
old = '''    if _clean_str(quote.get("payment_method_code")):
        pedido["forma_pagamento"] = _clean_str(quote.get("payment_method_code"))
    if _clean_str(quote.get("payment_meio")):
        pedido["meio_pagamento"] = _clean_str(quote.get("payment_meio"))
    if _clean_str(quote.get("payment_conta")):
        pedido["portador"] = _clean_str(quote.get("payment_conta"))
'''
new = '''    if payment_code_tiny:
        pedido["forma_pagamento"] = payment_code_tiny
    if meio_txt:
        pedido["meio_pagamento"] = meio_txt
    if portador_txt:
        pedido["portador"] = portador_txt
'''
if old not in txt:
    raise SystemExit("ERRO: bloco pedido forma_pagamento/meio/portador nao encontrado.")
txt = txt.replace(old, new, 1)

path.write_text(txt, encoding="utf-8")
print("OK - regras de pagamento do GCloud aplicadas ao create-order local.")
