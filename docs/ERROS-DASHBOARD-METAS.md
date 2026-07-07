# Contrato de erros — Dashboard Executivo e Metas de vendedor

Referência dos códigos e mensagens de erro dos 4 endpoints introduzidos no PR #12.
Cada linha abaixo corresponde a um caminho de código real em `backend/local_api.py`.

## Convenções gerais

- **Autenticação**: todos os endpoints exigem `Authorization: Bearer <token>`.
- **401 — autenticação**: sempre retornado pelo `auth_middleware` antes do handler.
  A mensagem em `detail` depende da causa:
  - Sem `Authorization`/sem `Bearer` (ou token vazio) → `{"detail": "Não autenticado."}`
    (o `_auth_user_from_request` retorna `None` e o middleware nega).
  - Token expirado ou com assinatura/formato inválido → `{"detail": "Token inválido ou expirado."}`
    (levantado por `_auth_decode_token` ao capturar `jwt.PyJWTError`).
  - Token válido mas com `sub` vazio → `{"detail": "Token inválido."}`.
  - Token válido cujo usuário não existe → `{"detail": "Usuário não encontrado."}`.
  - Token válido cujo usuário está inativo → `{"detail": "Usuário inativo."}`.
- **403 — apenas admin** (`{"detail": "Apenas admin."}`): dupla proteção (deny-by-default).
  1. No middleware, para os prefixos `/api/admin/dashboard`, `/admin/dashboard`,
     `/api/admin/seller-metas` e `/admin/seller-metas`, quando o papel do usuário não é `admin`.
  2. No handler, via `_admin_require_user` (defesa em profundidade). Mesma mensagem.
- **403 — empresa não permitida** (`{"detail": "Sem permissão para esta empresa."}`):
  `_auth_company_or_default` quando o usuário não tem acesso à empresa solicitada. No
  middleware isso é validado apenas para a empresa vinda do query param `company`; nos
  handlers, também para a empresa vinda do path (PUT/DELETE).
- **Sucesso**: sempre `{"ok": true, ...}`.
- Empresa (`company_key`) só é válida quando resolvida para `parton` ou `park`; caso
  contrário → **400** `{"detail": "Empresa inválida."}`.
- **Default de `company`**: no `GET /api/admin/dashboard/sales-performance` o default do
  parâmetro é o literal `parton` (paridade com `/home/dashboard`). Nos endpoints de
  seller-metas o `company` chega vazio por padrão e é resolvido para a empresa padrão do
  usuário via `_auth_company_or_default` (que retorna a primeira empresa do usuário, ou
  `parton` quando ele não tem nenhuma vinculada).

## `GET /api/admin/dashboard/sales-performance`

Também aceito em `GET /admin/dashboard/sales-performance`.
Query params: `company`, `period`, `date_from`, `date_to`, `year_month` (todos opcionais;
`period` assume `current_month` quando ausente).

| Status | Condição | `detail` |
|--------|----------|----------|
| 401 | Sem autenticação | `Não autenticado.` |
| 403 | Usuário não admin | `Apenas admin.` |
| 403 | Empresa não permitida ao usuário | `Sem permissão para esta empresa.` |
| 400 | `company` resolvida fora de `{parton, park}` | `Empresa inválida.` |
| 400 | `period` fora de `today, last_7_days, current_month, previous_month, custom` | `Período inválido. Use today, last_7_days, current_month, previous_month ou custom.` |
| 400 | `period=custom` sem `date_from` | `Informe date_from no formato YYYY-MM-DD.` |
| 400 | `period=custom` sem `date_to` | `Informe date_to no formato YYYY-MM-DD.` |
| 400 | `period=custom` com `date_from` em formato inválido | `date_from inválido. Use YYYY-MM-DD.` |
| 400 | `period=custom` com `date_to` em formato inválido | `date_to inválido. Use YYYY-MM-DD.` |
| 400 | `period=custom` com `date_from > date_to` | `date_from não pode ser maior que date_to.` |
| 400 | Intervalo com mais de 366 dias | `Período customizado não pode exceder 366 dias.` |
| 400 | `year_month` informado em formato inválido | `year_month inválido. Use YYYY-MM.` |

Observações:
- `year_month` é opcional aqui; quando ausente, as metas só são comparadas se o período
  couber em um único mês-calendário (senão o dashboard retorna `meta_available: false`).
- `period` só é validado quando não vazio; como o handler injeta `current_month` por
  padrão, um `period` ausente nunca dispara o 400 de período inválido.

## `GET /api/admin/seller-metas`

Também aceito em `GET /admin/seller-metas`.
Query params: `company`, `year_month`.

| Status | Condição | `detail` |
|--------|----------|----------|
| 401 | Sem autenticação | `Não autenticado.` |
| 403 | Usuário não admin | `Apenas admin.` |
| 403 | Empresa não permitida ao usuário | `Sem permissão para esta empresa.` |
| 400 | `company` resolvida fora de `{parton, park}` | `Empresa inválida.` |
| 400 | `year_month` ausente ou em formato inválido | `year_month inválido. Use YYYY-MM.` |

Observação: `year_month` é **obrigatório** — o valor padrão vazio (`""`) já reprova na
validação `_seller_metas_validate_year_month`, que exige o formato `YYYY-MM`.

## `PUT /api/admin/seller-metas/{company_key}/{year_month}/{seller_id}`

Também aceito em `PUT /admin/seller-metas/{company_key}/{year_month}/{seller_id}`.
Corpo JSON: `{ "meta_amount": <número>, "seller_name": "<opcional>" }`.

| Status | Condição | `detail` |
|--------|----------|----------|
| 401 | Sem autenticação | `Não autenticado.` |
| 403 | Usuário não admin | `Apenas admin.` |
| 403 | Empresa (do path) não permitida ao usuário | `Sem permissão para esta empresa.` |
| 400 | `company_key` (path) resolvida fora de `{parton, park}` | `Empresa inválida.` |
| 400 | `year_month` (path) em formato inválido | `year_month inválido. Use YYYY-MM.` |
| 400 | `seller_id` (path) vazio | `Vendedor obrigatório.` |
| 400 | Corpo não é JSON válido, ou não é um objeto JSON | `Corpo JSON inválido.` |
| 400 | `meta_amount` ausente/não numérico ou negativo | `meta_amount inválido. Informe um valor numérico maior ou igual a zero.` |
| 400 | `meta_amount` não-finito (NaN/Infinity) ou acima de `NUMERIC(14,2)` (> 999999999999.99) | `meta_amount inválido. Informe um valor numérico dentro do limite permitido.` |

Sucesso: `200` com `{"ok": true, "item": {...}}` (upsert; o `item` reflete o registro
gravado). A auditoria (`seller_meta_upsert`) grava o `before` real do registro quando é um
update, e `null` quando é uma inserção nova.

## `DELETE /api/admin/seller-metas/{company_key}/{year_month}/{seller_id}`

Também aceito em `DELETE /admin/seller-metas/{company_key}/{year_month}/{seller_id}`.

| Status | Condição | `detail` |
|--------|----------|----------|
| 401 | Sem autenticação | `Não autenticado.` |
| 403 | Usuário não admin | `Apenas admin.` |
| 403 | Empresa (do path) não permitida ao usuário | `Sem permissão para esta empresa.` |
| 400 | `company_key` (path) resolvida fora de `{parton, park}` | `Empresa inválida.` |
| 400 | `year_month` (path) em formato inválido | `year_month inválido. Use YYYY-MM.` |
| 400 | `seller_id` (path) vazio | `Vendedor obrigatório.` |

Sucesso: `200` com `{"ok": true, "item": {...}}` quando havia meta gravada (o `item` é o
registro removido). Quando **não** havia meta para o trio empresa/mês/vendedor, o retorno é
`200` com `{"ok": true, "item": null}` — **não** é `404`. A auditoria (`seller_meta_delete`)
só é gravada quando algo foi de fato removido.

## Sobre 500

Qualquer erro não tratado (ex.: banco de dados indisponível, falha inesperada em uma query)
resulta no `500 Internal Server Error` padrão do FastAPI/Starlette, sem contrato de `detail`
específico. A gravação de auditoria é resiliente e não derruba a operação principal
(`_auth_audit_log` apenas registra um aviso no console em caso de falha).

---

Validado contra `backend/local_api.py` em 2026-07-06, branch `feat/dashboard-executivo-vendas`
(inclui o 401 explícito `Token inválido ou expirado.` para token expirado/assinatura inválida).
