from pathlib import Path

path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\Separation.jsx")
txt = path.read_text(encoding="utf-8", errors="replace")

pairs = [
    (b"Separa\xc3\xa7\xc3\xa3o".decode("latin1"), "Separa\u00e7\u00e3o"),
    (b"separa\xc3\xa7\xc3\xa3o".decode("latin1"), "separa\u00e7\u00e3o"),
    (b"separa\xc3\xa7\xc3\xb5es".decode("latin1"), "separa\u00e7\u00f5es"),
    (b"Pr\xc3\xa9-venda".decode("latin1"), "Pr\u00e9-venda"),
    (b"Pr\xc3\xa9-pedido".decode("latin1"), "Pr\u00e9-pedido"),
    (b"Respons\xc3\xa1vel".decode("latin1"), "Respons\u00e1vel"),
    (b"Endere\xc3\xa7o".decode("latin1"), "Endere\u00e7o"),
    (b"Localiza\xc3\xa7\xc3\xa3o".decode("latin1"), "Localiza\u00e7\u00e3o"),
    (b"Confer\xc3\xaancia".decode("latin1"), "Confer\u00eancia"),
    (b"Observa\xc3\xa7\xc3\xb5es".decode("latin1"), "Observa\u00e7\u00f5es"),
    (b"Informa\xc3\xa7\xc3\xb5es".decode("latin1"), "Informa\u00e7\u00f5es"),
    (b"Atualiza\xc3\xa7\xc3\xa3o".decode("latin1"), "Atualiza\u00e7\u00e3o"),
    (b"or\xc3\xa7amento".decode("latin1"), "or\u00e7amento"),
    (b"Or\xc3\xa7amento".decode("latin1"), "Or\u00e7amento"),
    (b"N\xc3\xa3o".decode("latin1"), "N\u00e3o"),
    (b"n\xc3\xa3o".decode("latin1"), "n\u00e3o"),
    (b"Impress\xc3\xa3o".decode("latin1"), "Impress\u00e3o"),
    (b"A\xc3\xa7\xc3\xb5es".decode("latin1"), "A\u00e7\u00f5es"),
    (b"Descri\xc3\xa7\xc3\xa3o".decode("latin1"), "Descri\u00e7\u00e3o"),
    (b"Situa\xc3\xa7\xc3\xa3o".decode("latin1"), "Situa\u00e7\u00e3o"),
    (b"\xc3\xa9".decode("latin1"), "\u00e9"),
    (b"\xc3\xa1".decode("latin1"), "\u00e1"),
    (b"\xc3\xad".decode("latin1"), "\u00ed"),
    (b"\xc3\xb3".decode("latin1"), "\u00f3"),
    (b"\xc3\xba".decode("latin1"), "\u00fa"),
    (b"\xc3\xa7".decode("latin1"), "\u00e7"),
    (b"\xc3\xa3".decode("latin1"), "\u00e3"),
    (b"\xc3\xb5".decode("latin1"), "\u00f5"),
    (b"\xc3\xaa".decode("latin1"), "\u00ea"),
    (b"\xc3\xb4".decode("latin1"), "\u00f4"),
    (b"\xe2\x80\x94".decode("latin1"), "-"),
    (b"\xe2\x80\x93".decode("latin1"), "-"),
    (b"\xe2\x80\x9c".decode("latin1"), '"'),
    (b"\xe2\x80\x9d".decode("latin1"), '"'),
    (b"\xe2\x80\x98".decode("latin1"), "'"),
    (b"\xe2\x80\x99".decode("latin1"), "'"),
]

for old, new in pairs:
    txt = txt.replace(old, new)

path.write_text(txt, encoding="utf-8")
print("OK - Separation.jsx corrigido")
