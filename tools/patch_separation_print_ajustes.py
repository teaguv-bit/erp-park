from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8")

replacements = [
    (
        'const approvedAt = payload?.approved_at || null;',
        'const approvedAt = order?.approved_at || order?.approvedAt || payload?.approved_at || payload?.approvedAt || null;'
    ),
    (
        '.square { width:16px; height:16px; border:1px solid #111827; display:inline-flex; align-items:center; justify-content:center; font-size:12px; font-weight:900; }',
        '.square { width:16px; height:16px; border:1px solid #111827; display:inline-flex; align-items:center; justify-content:center; font-size:13px; font-weight:900; line-height:1; }'
    ),
    (
        '.totals { display:flex; justify-content:flex-end; margin-top:10px; font-size:13px; font-weight:800; }',
        '.qty-col { white-space: nowrap; min-width: 54px; }\\n  .totals { display:flex; justify-content:flex-end; margin-top:10px; font-size:13px; font-weight:800; }'
    ),
    (
        '<div class="check"><span class="square">${invoiceProfile === "A" ? "✓" : ""}</span><span>A</span></div>',
        '<div class="check"><span class="square">${invoiceProfile === "A" ? "X" : ""}</span><span>A</span></div>'
    ),
    (
        '<div class="check"><span class="square">${invoiceProfile === "B" ? "✓" : ""}</span><span>B</span></div>',
        '<div class="check"><span class="square">${invoiceProfile === "B" ? "X" : ""}</span><span>B</span></div>'
    ),
    (
        '<div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}${approvedAt ? ` • ${escapeHtml(String(approvedTime))}` : ""}</div></div>',
        '<div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}${approvedTime !== "—" ? ` • aprovado às ${escapeHtml(String(approvedTime))}` : ""}</div></div>'
    ),
    (
        '<th style="width:44%;">Produto</th>',
        '<th style="width:42%;">Produto</th>'
    ),
    (
        '<th style="width:6%;" class="center">Qtd</th>',
        '<th style="width:8%;" class="center qty-col">Qtd</th>'
    ),
    (
        '<td class="td center item-row" style="font-weight:900;font-size:14px;">${qty}</td>',
        '<td class="td center item-row qty-col" style="font-weight:900;font-size:15px;">${qty}</td>'
    ),
]

for old, new in replacements:
    if old not in txt:
        print("TRECHO NÃO ENCONTRADO:")
        print(old)
        raise SystemExit(1)
    txt = txt.replace(old, new, 1)

path.write_text(txt, encoding="utf-8")
print("OK - patch aplicado com sucesso em Separation.jsx")
