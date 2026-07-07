from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

bad_values = [
    bytes.fromhex("e28094").decode("latin1"),
    bytes.fromhex("e28093").decode("latin1"),
    bytes.fromhex("e2809c").decode("latin1"),
    bytes.fromhex("e2809d").decode("latin1"),
    bytes.fromhex("e28098").decode("latin1"),
    bytes.fromhex("e28099").decode("latin1"),
    "â€",
    "â",
    "\ufffd",
]

for bad in bad_values:
    txt = txt.replace(bad, "-")

# Normaliza sobras comuns de valor vazio depois da troca.
txt = txt.replace("--", "-")
txt = txt.replace('"-"', '"-"')
txt = txt.replace("'-'", "'-'")

path.write_text(txt, encoding="utf-8")
print("OK - dash/mojibake fixed")
