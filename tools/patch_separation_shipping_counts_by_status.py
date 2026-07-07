from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

old = r'''  const shippingTabs = useMemo(() => {
    const map = new Map();
    map.set("Todos", items.length);

    for (const item of items) {
      const envio = item?.shipping_method_name || "Sem envio";
      const frete = item?.freight_method_name || "Sem frete";
      const label = `${envio} -¢ ${frete}`;
      map.set(label, (map.get(label) || 0) + 1);
    }

    return Array.from(map.entries()).map(([label, count]) => ({ label, count }));
  }, [items]);'''

new = r'''  const shippingTabs = useMemo(() => {
    const statusFilteredItems =
      activeStatusTab === "Todos"
        ? items
        : items.filter((item) => normalizeSeparationStatus(item) === activeStatusTab);

    const map = new Map();
    map.set("Todos", statusFilteredItems.length);

    for (const item of statusFilteredItems) {
      const envio = item?.shipping_method_name || "Sem envio";
      const frete = item?.freight_method_name || "Sem frete";
      const label = `${envio} -¢ ${frete}`;
      map.set(label, (map.get(label) || 0) + 1);
    }

    return Array.from(map.entries()).map(([label, count]) => ({ label, count }));
  }, [items, activeStatusTab]);'''

if old not in txt:
    # fallback mais flexível, preservando o separador atual do arquivo, seja "•" ou mojibake "-¢"
    pattern = re.compile(
        r'''  const shippingTabs = useMemo\(\(\) => \{\s*
    const map = new Map\(\);\s*
    map\.set\("Todos", items\.length\);\s*

    for \(const item of items\) \{\s*
      const envio = item\?\.shipping_method_name \|\| "Sem envio";\s*
      const frete = item\?\.freight_method_name \|\| "Sem frete";\s*
      const label = `\$\{envio\} (?P<sep>.*?) \$\{frete\}`;\s*
      map\.set\(label, \(map\.get\(label\) \|\| 0\) \+ 1\);\s*
    \}\s*

    return Array\.from\(map\.entries\(\)\)\.map\(\(\[label, count\]\) => \(\{ label, count \}\)\);\s*
  \}, \[items\]\);''',
        re.S
    )
    m = pattern.search(txt)
    if not m:
        print("ERRO: bloco shippingTabs não encontrado.")
        raise SystemExit(1)

    sep = m.group("sep")
    new = f'''  const shippingTabs = useMemo(() => {{
    const statusFilteredItems =
      activeStatusTab === "Todos"
        ? items
        : items.filter((item) => normalizeSeparationStatus(item) === activeStatusTab);

    const map = new Map();
    map.set("Todos", statusFilteredItems.length);

    for (const item of statusFilteredItems) {{
      const envio = item?.shipping_method_name || "Sem envio";
      const frete = item?.freight_method_name || "Sem frete";
      const label = `${{envio}} {sep} ${{frete}}`;
      map.set(label, (map.get(label) || 0) + 1);
    }}

    return Array.from(map.entries()).map(([label, count]) => ({{ label, count }}));
  }}, [items, activeStatusTab]);'''
    txt = pattern.sub(new, txt, count=1)
else:
    txt = txt.replace(old, new, 1)

path.write_text(txt, encoding="utf-8")
print("OK - filtros Envio/Frete agora contam conforme o Status ativo.")
print("Backup:", r"C:\TRML_LOCAL\ERP\backups\before-separation-shipping-counts-by-status-$TS")
