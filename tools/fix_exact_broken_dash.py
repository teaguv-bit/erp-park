from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

bad_values = [
    "\u00e2\u20ac\u201d",
    "\u00e2\u20ac\u201c",
    "\u00e2\u20ac\u2013",
    "\u00e2\u20ac",
]

print("ANTES:")
for bad in bad_values:
    print(repr(bad), txt.count(bad))

for bad in bad_values:
    txt = txt.replace(bad, "-")

print("DEPOIS:")
for bad in bad_values:
    print(repr(bad), txt.count(bad))

path.write_text(txt, encoding="utf-8")
print("OK - sequencias exatas corrigidas")
