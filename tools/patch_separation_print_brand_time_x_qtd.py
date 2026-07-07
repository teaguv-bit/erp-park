from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

old = '''function getProductMeta(item) {
  const raw = safeJsonParse(item?.raw, {});
  const productRaw = raw?.product_raw || {};

  return {
    brand: pick(productRaw, "marca", "brand") || "—",
    category: pick(productRaw, "categoria", "category", "nome_categoria") || "—",
    location: pick(productRaw, "localizacao", "deposito", "warehouse_location", "local") || "—",
  };
}
'''

new = '''function getProductMeta(item) {
  const raw = safeJsonParse(item?.raw, {});
  const productRaw = raw?.product_raw || raw?.produto || raw?.product || raw || {};
  const productSnapshot = item?.product_snapshot || item?.product || {};

  return {
    brand:
      pick(item, "brand_snapshot", "marca_snapshot", "brand", "marca") ||
      pick(productSnapshot, "brand", "marca") ||
      pick(productRaw, "marca", "brand", "nome_marca") ||
      "—",
    category:
      pick(item, "category_snapshot", "categoria_snapshot", "category", "categoria") ||
      pick(productSnapshot, "categoria", "category", "nome_categoria") ||
      pick(productRaw, "categoria", "category", "nome_categoria") ||
      "—",
    location:
      pick(item, "location_snapshot", "localizacao_snapshot", "localizacao", "location") ||
      pick(productSnapshot, "localizacao", "deposito", "warehouse_location", "local") ||
      pick(productRaw, "localizacao", "deposito", "warehouse_location", "local") ||
      "—",
  };
}
'''

if old not in txt:
    raise SystemExit("ERRO: bloco getProductMeta atual nao encontrado.")
txt = txt.replace(old, new, 1)

txt = txt.replace(
    'const approvedAt = payload?.approved_at || null;',
    'const approvedAt = order?.approved_at || order?.approvedAt || payload?.approved_at || payload?.approvedAt || null;',
    1
)

txt = txt.replace(
    '<div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}</div></div>',
    '<div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}${approvedTime && approvedTime !== "—" && approvedTime !== "-" ? ` - aprovado às ${escapeHtml(String(approvedTime))}` : ""}</div></div>',
    1
)

txt = txt.replace(
    '<div class="check"><span class="square">${invoiceProfile === "A" ? "✓" : ""}</span><span>A</span></div>',
    '<div class="check"><span class="square">${invoiceProfile === "A" ? "X" : ""}</span><span>A</span></div>',
    1
)

txt = txt.replace(
    '<div class="check"><span class="square">${invoiceProfile === "B" ? "✓" : ""}</span><span>B</span></div>',
    '<div class="check"><span class="square">${invoiceProfile === "B" ? "X" : ""}</span><span>B</span></div>',
    1
)

txt = txt.replace(
    '.square { width:16px; height:16px; border:1px solid #111827; display:inline-flex; align-items:center; justify-content:center; font-size:12px; font-weight:900; }',
    '.square { width:16px; height:16px; border:1px solid #111827; display:inline-flex; align-items:center; justify-content:center; font-size:13px; font-weight:900; line-height:1; }',
    1
)

txt = txt.replace(
    '<th style="width:44%;">Produto</th>',
    '<th style="width:42%;">Produto</th>',
    1
)

txt = txt.replace(
    '<th style="width:6%;" class="center">Qtd</th>',
    '<th style="width:8%;" class="center">Qtd</th>',
    1
)

txt = txt.replace(
    '<td class="td center item-row" style="font-weight:900;font-size:14px;">${qty}</td>',
    '<td class="td center item-row" style="font-weight:900;font-size:15px;white-space:nowrap;">${qty}</td>',
    1
)

path.write_text(txt, encoding="utf-8")
print("OK - folha de separacao ajustada: marca, hora, X e QTD.")
