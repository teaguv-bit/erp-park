from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

# Apenas sequencias exatas de travessao/aspas quebradas.
# Nao troca "a" com acento, nao troca "â" generico, nao troca caractere replacement generico.
bad_dash = [
    bytes.fromhex("e28094").decode("latin1"),  # em dash quebrado
    bytes.fromhex("e28093").decode("latin1"),  # en dash quebrado
    bytes.fromhex("e28892").decode("latin1"),  # minus quebrado
]

before = {repr(x): txt.count(x) for x in bad_dash}

for bad in bad_dash:
    txt = txt.replace(bad, "-")

after = {repr(x): txt.count(x) for x in bad_dash}

path.write_text(txt, encoding="utf-8")

print("OK - troca segura aplicada")
print("ANTES:", before)
print("DEPOIS:", after)
print("Backup feito antes pelo PowerShell")
