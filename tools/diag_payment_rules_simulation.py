import sys
sys.path.insert(0, r"C:\TRML_LOCAL\ERP\backend")

from local_api import (
    _apply_payment_business_rules,
    _map_payment_code_for_tiny,
    _resolve_meio_pagamento_tiny,
    _resolve_portador_nome,
)

cases = [
    ("pix", "banco", "suprimento_parton_olist"),
    ("boleto", "banco", "suprimento_parton_olist"),
    ("cartao_credito", "", ""),
    ("cartao_debito", "", ""),
    ("link_pagamento", "", ""),
    ("link_pagamento", "gateway", "suprimento_parton_olist"),
]

print("=== SIMULACAO REGRAS PAGAMENTO LOCAL ===")
for method, meio, conta in cases:
    code_rule, meio_rule, conta_rule = _apply_payment_business_rules(method, meio, conta)
    code_tiny = _map_payment_code_for_tiny(code_rule)
    meio_txt = _resolve_meio_pagamento_tiny(meio_rule, conta_rule)
    portador_txt = _resolve_portador_nome(conta_rule)

    if code_tiny == "link_pagamento":
        portador_txt_final = None
    else:
        portador_txt_final = portador_txt

    print("")
    print("ENTRADA:", {"method": method, "meio": meio, "conta": conta})
    print("REGRA:", {"code_rule": code_rule, "meio_rule": meio_rule, "conta_rule": conta_rule})
    print("PEDIDO:", {
        "forma_pagamento": code_tiny,
        "meio_pagamento": meio_txt,
        "portador": portador_txt_final,
    })
