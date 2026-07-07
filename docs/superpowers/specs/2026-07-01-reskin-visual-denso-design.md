# Reskin Visual Denso — P&P ERP (Parton/Park)

**Data:** 2026-07-01
**Autor:** parkecom developers
**Status:** Spec revisada — ajustes 1–6 aplicados; pronta para plano de implementação
**Revisão:** 2026-07-01 — revisor aplicou: (1) estratégia de rename/alias de tokens, (2) `data-company` como fiação nova + fonte de verdade, (3) mapa de status→cor explícito e `--info` fixo, (4) nota de páginas órfãs (`QuotesList`/`TinySyncPreview`; não existe `Operations.jsx`), (5) reconciliação com `CLAUDE.md`, (6) `npm ci` na validação. Pendente: hex oficiais de accent Park/Parton.
**Escopo:** Frontend (`frontend/`) — React 19 + Vite, JSX puro
**Entrega:** Um único Pull Request ao final. Nunca merge/push na `main`, deploy ou restart.

---

## 1. Objetivo

Dar ao P&P ERP uma nova identidade visual **densa e produtiva**, consistente e responsiva,
**sem alterar estrutura de telas, fluxos, lógica de negócio, permissões ou API**. É um
*reskin*: muda a apresentação, preserva o comportamento.

O redesign deve resolver as quatro dores levantadas:

1. **Inconsistência visual** — botões, cores, espaçamentos e cards variam entre telas.
2. **Aproveitamento de tela** — muito scroll, pouca informação visível, espaço desperdiçado.
3. **Legibilidade/hierarquia** — difícil achar rápido números, status e ações.
4. **Estados e feedback** — loading, erro, vazio e resultado de ações inconsistentes.

## 2. Decisões de design (fixas)

| Tema | Decisão |
|---|---|
| Escopo | Reskin — mantém estrutura e fluxos, restila apresentação |
| Estética | Enterprise denso e produtivo (velocidade e densidade útil) |
| Responsivo | Total — denso no desktop, utilizável no mobile (toque) |
| Tema claro/escuro | Auto (segue o SO) + override manual persistido, **um** sistema de tokens |
| Cor/marca | Base neutra compartilhada + **accent por empresa** (Parton/Park) |
| Abordagem | Tokens + kit enxuto de componentes React (sem dependências novas) |
| Entrega | Um PR único ao concluir; execução interna em fases |

## 3. Não-objetivos (fora de escopo)

- Nenhuma mudança em `backend/` (nem `local_api.py`, nem `api.py`).
- Nenhuma alteração de regras/transições de status, permissões, auth ou API.
- Nenhuma nova dependência npm (mantém React 19 + Vite puro).
- Nenhuma reestruturação de navegação, rotas ou fluxos de tela.
- Campos admin-only (`custo`, `resultado_bruto`, `margem`, `cobertura`) permanecem
  protegidos no backend — o reskin nunca os expõe a vendedores.

---

## 4. Fundação — sistema de tokens

Fonte única de verdade em `src/styles/tokens.css`. Todas as cores, espaçamentos,
tipografia, raios e sombras viram variáveis CSS. Valores calibrados para densidade.

### 4.1 Neutros (base compartilhada)

| Token | Claro | Escuro |
|---|---|---|
| `--bg` (fundo do app) | `#f6f7f9` | `#0d1117` |
| `--surface` (cards/painéis) | `#ffffff` | `#151b23` |
| `--surface-2` (hover/raised) | `#f1f3f5` | `#1c232d` |
| `--border` | `#e3e6ea` | `#262d38` |
| `--border-strong` | `#d1d6dc` | `#333c49` |
| `--text` | `#10151b` | `#e6edf3` |
| `--text-muted` | `#5b6472` | `#9aa4b2` |
| `--text-subtle` | `#8a929e` | `#6b7482` |

> **Migração de nomes (ajuste 1):** os tokens de hoje se chamam `--bg`, `--card`, `--panel`
> (ver `index.css`). A base nova mantém `--bg` e renomeia `--card`/`--panel` →
> `--surface`/`--surface-2`. Para não reescrever todo o CSS de uma vez, `tokens.css` mantém
> **aliases de compatibilidade** (`--card: var(--surface)`; `--panel: var(--surface)`)
> durante o rollout. Cada fase que restila uma tela troca as referências antigas pelas novas;
> os aliases só são removidos na última fase, quando nenhuma regra os usa mais.

### 4.2 Accent por empresa

Base neutra idêntica; só o accent muda conforme a empresa ativa. Valores default,
ajustáveis ao hex exato da marca (podem ser extraídos dos logos em `assets/catalog/`).

| Empresa | Accent | Accent (hover/strong) |
|---|---|---|
| Park (informática) | `#2563eb` (azul) | `#1d4ed8` |
| Parton (suprimentos) | `#0d9488` (verde-azulado) | `#0f766e` |

Aplicado via `[data-company="park"]` / `[data-company="parton"]` no `<html>`. **Essa fiação é
nova (ajuste 2):** hoje o `companySwitcherDom.js` monta o switcher mas não escreve
`data-company` no root. Um helper pequeno passa a setar `data-company` no `documentElement`
lendo a **empresa ativa da mesma fonte de verdade que o switcher já consome** (a confirmar no
plano: estado em `App.jsx` vs `api.js`). Define `--accent`, `--accent-strong`,
`--accent-contrast` e `--accent-soft` (fundo suave para chips/hover).

### 4.3 Cores semânticas (status)

Fonte única, consumida pelo `StatusPill` e por realces:

| Token | Claro | Escuro |
|---|---|---|
| `--success` | `#16a34a` | `#22c55e` |
| `--danger` | `#dc2626` | `#ef4444` |
| `--warning` | `#d97706` | `#f59e0b` |
| `--info` | `#0ea5e9` | `#38bdf8` |
| `--neutral` (status sem carga semântica) | `#6b7280` | `#9aa4b2` |

Os status de orçamento/separação mapeiam para essa paleta em **um único lugar** (mapa de
status do `StatusPill`), eliminando a coloração espalhada de hoje. Mapa explícito (ajuste 3),
definido aqui porque há ~6 status para poucas cores — proposta a validar contra os status
reais do backend na Fase 2:

| Status | Token |
|---|---|
| aberto | `--info` |
| em separação | `--warning` |
| aprovado | `--success` |
| faturado | `--accent` |
| conferido | `--neutral` |
| cancelado | `--danger` |

Regra: dois status de significado próximo nunca usam a mesma cor exata — faltando cor
semântica, usa-se `--neutral` ou variação de tom, preservando a distinção. `--info` agora é
um azul próprio (não mais `= --accent`), para não colidir com a cor de marca.

### 4.4 Escalas

- **Espaçamento** (base 4px, densa): `--space-1:4` · `2:8` · `3:12` · `4:16` · `5:20` · `6:24` · `7:32`.
- **Tipografia** (densa; mantém Inter, já carregada): `--text-xs:11` · `sm:12` · `base:13`
  · `md:14` · `lg:16` · `xl:20` · `2xl:24`. `line-height` 1.35–1.45. `font-variant-numeric:
  tabular-nums` em dinheiro e colunas numéricas.
- **Raios:** `--radius-sm:4` · `md:6` · `lg:8` (menor que os 12–16px atuais, que "engordam" o layout).
- **Sombras:** discretas (`--shadow-sm/md/lg`). No denso, a **borda** separa mais que a sombra;
  sombra reservada a modais/popovers.
- **Z-index:** escala nomeada (`--z-base`, `--z-dropdown`, `--z-sticky`, `--z-modal`, `--z-toast`).

### 4.5 Mecânica de tema (elimina a duplicação atual)

Hoje o dark mode existe em `@media (prefers-color-scheme)` **e** em `[data-theme]` ao mesmo
tempo, se sobrepondo. O novo modelo tem **uma** definição de tokens:

1. `:root` define os tokens do tema claro.
2. `@media (prefers-color-scheme: dark)` sobrescreve **os mesmos tokens** (auto = segue o SO).
3. `[data-theme="light"]` / `[data-theme="dark"]` no `<html>` permitem override manual que
   **vence** o media query, persistido em `localStorage`.

A seção de login duplicada no `index.css` (redefinida em "LOGIN visual refresh") é unificada.

---

## 5. Arquitetura de arquivos

```
src/styles/
  tokens.css      // cores, espaço, tipo, raio, sombra, z-index + temas + accent por empresa
  base.css        // reset, defaults de elemento, tipografia base, focus ring
  utilities.css   // poucos helpers (truncate, visually-hidden, stack/cluster)
src/ui/           // componentes de apresentação (Seção 6)
  Button.jsx  Button.css
  Card.jsx    Card.css
  Table.jsx   Table.css
  StatusPill.jsx  StatusPill.css
  Field.jsx   Field.css
  Toolbar.jsx Toolbar.css
  PageHeader.jsx  PageHeader.css
  EmptyState.jsx  EmptyState.css
  Spinner.jsx  Skeleton.jsx  feedback.css
  Toast.jsx   toast context  Toast.css
  index.js    // barrel de exportação
```

O `App.css` (60 KB) é **decomposto**: regras globais migram para `tokens.css`/`base.css`;
regras específicas de página permanecem, mas passam a referenciar tokens em vez de valores
literais. Nenhuma regra de layout de tela é removida sem substituição equivalente.

O toggle de tema e o `data-company` são setados no `documentElement` por um helper pequeno
(sem framework de estado novo), lendo o estado de empresa já existente e o `localStorage`.

---

## 6. Kit de componentes (`src/ui/`)

Componentes de apresentação, pequenos e de propósito único. Cada um é a **única** forma de
renderizar aquele elemento — é isso que garante a consistência. Todos em JSX + CSS próprio,
referenciando tokens. Sem dependências externas.

| Componente | Responsabilidade | API resumida |
|---|---|---|
| `Button` | Único botão do sistema | `variant` (primary/secondary/ghost/danger) · `size` (sm/md) · `loading` · `icon` |
| `Card`/`Panel` | Contêiner de conteúdo | `title` · `actions` · densidade de padding |
| `Table`/`DataTable` | Tabela densa | header fixo · zebra opcional · números à direita (`tabular-nums`) · scroll horizontal no mobile |
| `StatusPill` | Badge de status | mapeia status de orçamento/separação → cor (fonte única) |
| `Field` | Rótulo + input/select/textarea + erro | `label` · `error` · `help` · focus ring padrão |
| `Toolbar` | Barra de filtros/ações das listas | slots de filtro + ações à direita |
| `PageHeader` | Cabeçalho de tela | título · caminho · ação primária (consistente em todas as telas) |
| `EmptyState` | Lista vazia / erro | ícone · mensagem · ação |
| `Spinner`/`Skeleton` | Loading consistente | substitui o `globalLoading` ad-hoc |
| `Toast` | Feedback de ação | success/error/info — resolve "estados e feedback" |

Cada componente pode ser entendido e usado sem ler seu interior; a marcação atual das telas
passa a consumi-los progressivamente (Seção 8).

---

## 7. Densidade, responsivo e estados

### 7.1 Breakpoints

`640 / 768 / 1024 / 1280`. Desktop = denso multi-coluna. **≤768px** = layout empilhado,
alvos de toque **≥40px**, tabelas viram cards empilhados ou ganham scroll horizontal
controlado. Atende ao requisito "tudo responsivo".

### 7.2 Modelo de estados (padrão em toda tela)

- Toda lista/tabela tem: **loading** (Skeleton) · **vazio** (EmptyState) · **erro** (inline com retry).
- Toda ação assíncrona: botão em estado `loading` + **Toast** de resultado (success/error).

Esse padrão único ataca de frente as quatro dores: consistência (kit único), aproveitamento
de tela (densidade calibrada), hierarquia (PageHeader + escala tipográfica) e estados/feedback
(Toast + loading/empty/erro padronizados).

---

## 8. Rollout (execução interna em fases; entrega em um PR)

Execução em fases para reduzir risco e permitir teste incremental. **Todas as fases vivem no
branch `feat/reskin-visual-denso` e são entregues juntas em um único PR ao final.**

| Fase | Escopo |
|---|---|
| **0 — Fundação** | `tokens.css`, `base.css`, `utilities.css`, mecânica de tema+empresa, dedup do login |
| **1 — Shell + Login** | topbar, sidebar, switcher de empresa, toggle de tema, tela de login |
| **2 — Operacional** | `SavedQuotes`, `QuotesModal`, `NewQuote` (uso diário) |
| **3 — Dashboard** | `Home` (respeitando campos admin-only: custo/resultado/margem/cobertura) |
| **4 — Restante** | `ClientWallet`, `Separation` (foco mobile), `Catalog`, `Products`, `Compras`, `AdminUsers`, `AdminSettings`, `TinySyncPreview` |

> O fluxo real passa por `QuotesModal.jsx` + `SavedQuotes.jsx` (e `NewQuote.jsx`). **Não
> existe `Operations.jsx`** no repo (ajuste 4). Quem existe e **não tem import estático no
> `App.jsx` nem aparece em nenhuma fase** é `QuotesList.jsx` (`pages/`) — e possivelmente
> `TinySyncPreview.jsx`. **Confirmar se estão ativos ou órfãos antes de restilar.** Páginas
> órfãs não entram no rollout.

---

## 9. Validação (por fase, antes do PR)

- `npm ci` e depois `npm run build` — instala do lockfile e roda o build de produção sem erros (ajuste 6).
- `eslint .` — barra = **nenhum problema NOVO** (o baseline do eslint já é sujo; não regredir).
- Conferência visual manual: claro/escuro (auto + override), Parton e Park, desktop e mobile.
- Verificação de que nenhuma string em português perdeu acento e nenhum campo admin-only
  passou a aparecer para vendedor.

Sem testes automatizados no projeto — validação é manual (rodar e observar).

---

## 10. Restrições de entrega

- **Só PR, nunca subir.** Sem merge/push na `main`, sem deploy, sem restart do ERP local.
- **Zero dependências novas.** React 19 + Vite puro.
- **Nada de lógica/permissão/API/status.** Reskin é só apresentação; proteções de campo
  admin-only continuam no backend.
- Strings em português preservadas (acentos intactos — não normalizar display strings).
- Commits com identidade git local (`parkecom developers` / `parkecomdevelopers@gmail.com`).
- Um único PR ao final, com resumo das telas restiladas e checklist de validação.
- **Reconciliar com `CLAUDE.md` (ajuste 5):** a seção "No Git Workflow" do `CLAUDE.md`
  proíbe branches/commits/PRs sem pedido explícito. Esta spec (PR único + commits por fase)
  é a direção atual autorizada — atualizar o `CLAUDE.md` para refletir o fluxo PR-only e
  evitar conflito de instrução na execução.

---

## 11. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Regressão visual ao decompor `App.css` e renomear tokens (`--card`/`--panel`→`--surface`) | Aliases de compatibilidade em `tokens.css` durante o rollout (removidos só na última fase); migração tela por tela; regra global só sai com substituição equivalente |
| Densidade excessiva prejudicar legibilidade | Tipografia base 13px com `line-height` folgado; alvos ≥40px no mobile |
| Accent por empresa quebrar contraste em algum estado | Tokens `--accent-contrast`/`--accent-soft` testados nos dois temas |
| Toggle de tema conflitar com auto (SO) | `[data-theme]` sempre vence o media query; um único ponto de definição |
| PR grande (um só) dificultar revisão | Commits organizados por fase; descrição do PR mapeia telas por fase |
