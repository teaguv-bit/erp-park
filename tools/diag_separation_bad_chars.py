from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

targets = ["â", "€", "\ufffd"]
for t in targets:
    print("TARGET", repr(t), "COUNT", txt.count(t))
    idx = txt.find(t)
    if idx >= 0:
        start = max(0, idx - 120)
        end = min(len(txt), idx + 120)
        print(txt[start:end].encode("unicode_escape").decode("ascii"))
        print("---")
