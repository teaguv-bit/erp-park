from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\NewQuote.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

replacements = [
    # Fundo geral e header
    (
        'background:\n      "radial-gradient(circle at top left, rgba(79,140,255,0.10), transparent 26%), radial-gradient(circle at top right, rgba(34,197,94,0.06), transparent 24%), var(--bg)",',
        'background: "var(--bg)",'
    ),
    (
        'background:\n      "radial-gradient(circle at top left, rgba(79,140,255,0.12), transparent 32%), linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))",',
        'background: "var(--card)",'
    ),

    # Botão neutro padrão
    ('background: "rgba(8,16,31,0.38)",', 'background: "var(--input-bg-soft)",'),

    # Sections
    (
        'background:\n      "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))",',
        'background: "var(--card)",'
    ),

    # Inputs/selects/list/tabela/total
    ('background: "rgba(8,16,31,0.48)",', 'background: "var(--input-bg)",'),
    ('background: "rgba(8,16,31,0.34)",', 'background: "var(--card)",'),
    ('background: "rgba(8,16,31,0.32)",', 'background: "var(--card)",'),
    ('background: "rgba(10,18,33,0.98)",', 'background: "var(--table-header)",'),

    # Cores de header de tabela mais temáticas
    ('color: "rgba(218,230,248,0.94)",', 'color: "var(--text)",'),

    # Bordas de linhas
    ('borderBottom: "1px solid rgba(148,163,184,0.10)",', 'borderBottom: "1px solid var(--border)",'),

    # Botão NF inativo
    ('background: invoiceProfile === "A" ? "linear-gradient(180deg, var(--primary), var(--primary-strong))" : "rgba(8,16,31,0.42)",',
     'background: invoiceProfile === "A" ? "linear-gradient(180deg, var(--primary), var(--primary-strong))" : "var(--input-bg-soft)",'),
    ('background: invoiceProfile === "B" ? "linear-gradient(180deg, var(--primary), var(--primary-strong))" : "rgba(8,16,31,0.42)",',
     'background: invoiceProfile === "B" ? "linear-gradient(180deg, var(--primary), var(--primary-strong))" : "var(--input-bg-soft)",'),

    # Botões pequenos/modais com fundo antigo
    ('background: "rgba(8,16,31,0.46)",', 'background: "var(--input-bg)",'),
    ('background: "rgba(8,16,31,0.26)",', 'background: "var(--card)",'),
]

changed = 0
for old, new in replacements:
    c = txt.count(old)
    if c:
        txt = txt.replace(old, new)
        changed += c
        print(f"OK {c}x: {old[:80].replace(chr(10),' ')}")
    else:
        print(f"NAO ENCONTRADO: {old[:80].replace(chr(10),' ')}")

path.write_text(txt, encoding="utf-8")
print(f"Concluido. Substituicoes aplicadas: {changed}")
