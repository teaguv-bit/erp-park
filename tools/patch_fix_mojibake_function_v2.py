from pathlib import Path
import re

path = Path(r"C:\TRML_LOCAL\ERP\backend\local_api.py")
txt = path.read_text(encoding="utf-8", errors="replace")

new_func = '''
def _fix_mojibake_text(value):
    s = _clean_str(value)
    if not s:
        return ""

    # Corrige textos UTF-8 que ficaram armazenados/interpretados como Latin-1/Windows-1252.
    # Exemplo: "Ros" + "Ã¡" + "rio" vira "Rosário".
    markers = [
        chr(0x00C3),  # Ã
        chr(0x00C2),  # Â
        chr(0x00E2),  # â
    ]

    if any(m in s for m in markers):
        for enc in ("latin1", "cp1252"):
            try:
                fixed = s.encode(enc).decode("utf-8")
                if fixed and fixed != s:
                    return fixed
            except Exception:
                pass

    return s


'''

pattern = r'def _fix_mojibake_text\(value\):.*?(?=\ndef _client_dict_from_snapshot\(snap\):)'

if not re.search(pattern, txt, flags=re.S):
    raise SystemExit("ERRO: funcao _fix_mojibake_text nao encontrada antes de _client_dict_from_snapshot.")

txt2 = re.sub(pattern, new_func.rstrip() + "\n\n", txt, count=1, flags=re.S)

path.write_text(txt2, encoding="utf-8")
print("OK - _fix_mojibake_text substituida")
