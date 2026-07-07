from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

def replace_js_function(src, name, replacement):
    start = src.find(f"function {name}")
    if start < 0:
        raise SystemExit(f"ERRO: function {name} nao encontrada.")
    brace = src.find("{", start)
    if brace < 0:
        raise SystemExit(f"ERRO: abertura da function {name} nao encontrada.")
    depth = 0
    end = None
    for i in range(brace, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit(f"ERRO: fechamento da function {name} nao encontrado.")
    return src[:start] + replacement + src[end:]

# Base GCloud, com fallback extra para o formato local/PostgreSQL.
new_get_product_meta = '''function getProductMeta(item) {
  const raw = safeJsonParse(item?.raw, {});
  const productRaw = raw?.product_raw || raw?.produto || raw?.product || raw || {};
  const productSnapshot = safeJsonParse(item?.product_snapshot, item?.product_snapshot || {});

  return {
    brand:
      pick(productRaw, "marca", "brand") ||
      pick(productSnapshot, "marca", "brand") ||
      pick(item, "marca", "brand", "marca_snapshot", "brand_snapshot") ||
      "-",
    category:
      pick(productRaw, "categoria", "category", "nome_categoria") ||
      pick(productSnapshot, "categoria", "category", "nome_categoria") ||
      pick(item, "categoria", "category", "categoria_snapshot", "category_snapshot") ||
      "-",
    location:
      pick(productRaw, "localizacao", "deposito", "warehouse_location", "local") ||
      pick(productSnapshot, "localizacao", "deposito", "warehouse_location", "local") ||
      pick(item, "localizacao", "location", "localizacao_snapshot", "location_snapshot") ||
      "-",
  };
}'''

txt = replace_js_function(txt, "getProductMeta", new_get_product_meta)

# Hora aprovada: usa payload igual ao GCloud, mas aceita order.approved_at tambem.
txt = re.sub(
    r'const approvedAt\s*=\s*.*?;',
    'const approvedAt = order?.approved_at || order?.approvedAt || payload?.approved_at || payload?.approvedAt || null;',
    txt,
    count=1,
)

# Linha da data igual ao GCloud: data + hora ao lado.
date_pattern = re.compile(
    r'<div class="kv"><div class="k">Data</div><div class="v">.*?</div></div>',
    re.S
)
new_date = '<div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}${approvedAt ? ` \\u2022 ${escapeHtml(String(approvedTime))}` : ""}</div></div>'
txt = date_pattern.sub(lambda m: new_date, txt, count=1)

# A/B com X.
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

# Caixa A/B mais limpa.
txt = re.sub(
    r'\.square\s*\{[^}]*\}',
    '.square { width:16px; height:16px; border:1px solid #111827; display:inline-flex; align-items:center; justify-content:center; font-size:13px; font-weight:900; line-height:1; }',
    txt,
    count=1,
    flags=re.S,
)

# Apenas ajuste de largura QTD.
txt = txt.replace('<th style="width:44%;">Produto</th>', '<th style="width:42%;">Produto</th>', 1)
txt = txt.replace('<th style="width:6%;" class="center">Qtd</th>', '<th style="width:8%;" class="center">Qtd</th>', 1)
txt = txt.replace(
    '<td class="td center item-row" style="font-weight:900;font-size:14px;">${qty}</td>',
    '<td class="td center item-row" style="font-weight:900;font-size:15px;white-space:nowrap;">${qty}</td>',
    1,
)

path.write_text(txt, encoding="utf-8")
print("OK - folha ajustada com base no GCloud: marca, hora, X e QTD.")
