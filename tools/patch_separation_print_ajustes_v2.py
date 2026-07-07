from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

# 1) Aprovacao: tenta usar campo direto do pedido e depois payload.
txt = txt.replace(
    'const approvedAt = payload?.approved_at || null;',
    'const approvedAt = order?.approved_at || order?.approvedAt || payload?.approved_at || payload?.approvedAt || null;',
    1
)

# 2) Ajuste visual da caixa A/B.
txt = re.sub(
    r'\.square\s*\{[^}]*\}',
    '.square { width:16px; height:16px; border:1px solid #111827; display:inline-flex; align-items:center; justify-content:center; font-size:13px; font-weight:900; line-height:1; }',
    txt,
    count=1,
    flags=re.S
)

# 3) Garante classe da coluna QTD.
if ".qty-col" not in txt:
    txt = txt.replace(
        '.totals { display:flex; justify-content:flex-end; margin-top:10px; font-size:13px; font-weight:800; }',
        '.qty-col { white-space: nowrap; min-width: 54px; }\\n  .totals { display:flex; justify-content:flex-end; margin-top:10px; font-size:13px; font-weight:800; }',
        1
    )

# 4) Troca qualquer marcador atual da caixa A/B por X.
txt = re.sub(
    r'\$\{invoiceProfile === "A" \? ".*?" : ""\}',
    '${invoiceProfile === "A" ? "X" : ""}',
    txt,
    count=1
)
txt = re.sub(
    r'\$\{invoiceProfile === "B" \? ".*?" : ""\}',
    '${invoiceProfile === "B" ? "X" : ""}',
    txt,
    count=1
)

# 5) Data + horario de aprovacao.
old_data = re.compile(
    r'<div class="kv"><div class="k">Data</div><div class="v">.*?</div></div>',
    re.S
)
new_data = '<div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}${approvedTime !== "\\u2014" && approvedTime !== "-" ? ` - aprovado \\u00e0s ${escapeHtml(String(approvedTime))}` : ""}</div></div>'
txt = old_data.sub(new_data, txt, count=1)

# 6) Aumenta QTD e tira um pouco do Produto.
txt = txt.replace('<th style="width:44%;">Produto</th>', '<th style="width:42%;">Produto</th>', 1)
txt = txt.replace('<th style="width:6%;" class="center">Qtd</th>', '<th style="width:8%;" class="center qty-col">Qtd</th>', 1)
txt = txt.replace(
    '<td class="td center item-row" style="font-weight:900;font-size:14px;">${qty}</td>',
    '<td class="td center item-row qty-col" style="font-weight:900;font-size:15px;">${qty}</td>',
    1
)

path.write_text(txt, encoding="utf-8")
print("OK - patch v2 aplicado em Separation.jsx")
