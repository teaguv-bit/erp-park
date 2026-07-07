from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

txt = re.sub(
    r'const approvedAt\s*=\s*.*?;',
    'const approvedAt = order?.approved_at || order?.approvedAt || payload?.approved_at || payload?.approvedAt || null;',
    txt,
    count=1,
)

txt = re.sub(
    r'<div class="kv"><div class="k">Data</div><div class="v">.*?</div></div>',
    '<div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}${approvedAt ? ` • ${escapeHtml(String(approvedTime))}` : ""}</div></div>',
    txt,
    count=1,
    flags=re.S,
)

txt = re.sub(
    r'\$\{invoiceProfile === "A" \? ".*?" : ""\}',
    '${invoiceProfile === "A" ? "X" : ""}',
    txt,
    count=1,
)

txt = re.sub(
    r'\$\{invoiceProfile === "B" \? ".*?" : ""\}',
    '${invoiceProfile === "B" ? "X" : ""}',
    txt,
    count=1,
)

txt = txt.replace(
    '<th style="width:44%;">Produto</th>',
    '<th style="width:42%;">Produto</th>',
    1,
)

txt = txt.replace(
    '<th style="width:6%;" class="center">Qtd</th>',
    '<th style="width:8%;" class="center">Qtd</th>',
    1,
)

txt = txt.replace(
    '<td class="td center item-row" style="font-weight:900;font-size:14px;">${qty}</td>',
    '<td class="td center item-row" style="font-weight:900;font-size:15px;white-space:nowrap;">${qty}</td>',
    1,
)

path.write_text(txt, encoding="utf-8")
print("OK - data/hora, X em A/B e largura QTD ajustados.")
