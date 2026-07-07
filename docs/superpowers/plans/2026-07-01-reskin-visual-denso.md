# Reskin Visual Denso — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aplicar um reskin visual denso, consistente e responsivo ao frontend do P&P ERP (Parton/Park) sem alterar estrutura, fluxos, lógica, permissões ou API.

**Architecture:** Um sistema único de tokens CSS (`src/styles/`) + um kit enxuto de componentes de apresentação (`src/ui/`), aplicados tela por tela. Aliases de compatibilidade mantêm o CSS legado funcionando durante a migração e são removidos na última fase. Tema auto (segue o SO) com override manual persistido; accent trocado por empresa via `data-company` no `<html>`.

**Tech Stack:** React 19, Vite 7, JSX puro (sem TypeScript), CSS puro com custom properties. Sem novas dependências.

## Global Constraints

Todo task herda implicitamente estas regras (valores exatos da spec `docs/superpowers/specs/2026-07-01-reskin-visual-denso-design.md`):

- **Zero dependências novas.** React 19 + Vite puro. Não rodar `npm install <pkg>`.
- **Nada de lógica/permissão/API/status.** Reskin é só apresentação; nenhuma mudança em `backend/`, regras de status, auth ou contratos de API.
- **Campos admin-only nunca expostos a vendedor:** `custo`, `resultado_bruto`, `margem`, `cobertura`. Proteção é do backend; o reskin não pode passar a renderizá-los.
- **Strings PT com acento intactas.** Não normalizar display strings (`ã`, `é`, `ç`…).
- **Entrega:** um único PR ao final, no branch `feat/reskin-visual-denso`. Nunca merge/push na `main`, deploy ou restart do ERP local.
- **Identidade git local:** `parkecom developers` / `parkecomdevelopers@gmail.com` (já configurada no repo).
- **Validação por fase (o "test" deste projeto — não há suíte automatizada):**
  1. `cd frontend && npm ci` (instala do lockfile) e depois `npm run build` → build sem erros.
  2. `cd frontend && npx eslint .` → **nenhum problema NOVO** (o baseline do eslint já é sujo; comparar contagem antes/depois, não exigir zero).
  3. Conferência visual manual: tema claro/escuro (auto do SO + override), empresas Parton e Park, larguras desktop (≥1024px) e mobile (≤768px).
  4. Confirmar que nenhuma string perdeu acento e nenhum campo admin-only passou a aparecer para vendedor.
- **Aliases de compatibilidade** (`--card`, `--panel`, `--muted`, `--primary` → novos tokens) vivem durante o rollout e só são removidos na Fase 4.
- **Páginas órfãs fora do escopo:** `pages/QuotesList.jsx` e `pages/TinySyncPreview.jsx` (nenhum import estático no `src/` — confirmado). Não restilar.

**Convenção de commit por task:** cada task termina com um commit no branch `feat/reskin-visual-denso`. Mensagens em PT, prefixo por fase, ex.: `style(reskin-f0): cria tokens.css com sistema de design`.

---

## File Structure

**Criados:**
```
frontend/src/styles/tokens.css       // fonte única: cores, temas, accent/empresa, escalas, z-index, aliases
frontend/src/styles/base.css         // reset, tipografia base, focus ring, defaults de elemento
frontend/src/styles/utilities.css    // helpers mínimos (truncate, visually-hidden, stack/cluster, tabular)
frontend/src/ui/theme.js             // init de tema (auto+override) e data-company no documentElement
frontend/src/ui/Button.jsx  Button.css
frontend/src/ui/Card.jsx    Card.css
frontend/src/ui/Table.jsx   Table.css
frontend/src/ui/StatusPill.jsx  StatusPill.css
frontend/src/ui/Field.jsx   Field.css
frontend/src/ui/Toolbar.jsx Toolbar.css
frontend/src/ui/PageHeader.jsx  PageHeader.css
frontend/src/ui/EmptyState.jsx  EmptyState.css
frontend/src/ui/Feedback.jsx     Feedback.css   // Spinner + Skeleton
frontend/src/ui/Toast.jsx        Toast.css      // ToastProvider + useToast
frontend/src/ui/index.js         // barrel de exportação
```

**Modificados:**
```
frontend/src/main.jsx        // ordem de imports de CSS + ToastProvider
frontend/src/index.css       // remove bloco de tokens (migra p/ tokens.css) + dedup login
frontend/src/App.css         // decomposição gradual; regras passam a referenciar tokens
frontend/src/App.jsx         // usa theme.js; globalLoading → Spinner; kit no shell
frontend/src/Login.jsx       // aplica kit + tokens
frontend/src/pages/*.jsx     // aplica kit + tokens (fases 2–4)
CLAUDE.md                    // reconcilia "No Git Workflow" com fluxo PR-only (Fase 4)
```

---

## FASE 0 — Fundação (tokens, base, tema/empresa, dedup login)

Objetivo da fase: introduzir o sistema de tokens e a mecânica de tema/empresa sem regressão visual perceptível, deixando os aliases para o CSS legado continuar renderizando.

### Task 0.1: Criar `tokens.css` (sistema de design + temas + aliases)

**Files:**
- Create: `frontend/src/styles/tokens.css`

**Interfaces:**
- Produces: custom properties globais consumidas por todo o CSS novo e (via aliases) pelo legado: `--bg --surface --surface-2 --border --border-strong --text --text-muted --text-subtle --accent --accent-strong --accent-contrast --accent-soft --success --danger --warning --info --neutral --space-1..7 --radius-sm/md/lg --text-xs..2xl --font-sans --shadow-sm/md/lg --z-base/dropdown/sticky/modal/toast --control-h-sm/md --touch-min`. Aliases legados: `--card --panel --muted --primary --primary-contrast`.

- [ ] **Step 1: Escrever `tokens.css`**

```css
/* frontend/src/styles/tokens.css
   Fonte única de design tokens do reskin. Importado antes de base.css e do
   CSS legado. Aliases mantêm App.css/index.css funcionando durante o rollout. */

:root {
  color-scheme: light;

  /* ---- Neutros (tema claro) ---- */
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #f1f3f5;
  --border: #e3e6ea;
  --border-strong: #d1d6dc;
  --text: #10151b;
  --text-muted: #5b6472;
  --text-subtle: #8a929e;

  /* ---- Semânticas de status ---- */
  --success: #16a34a;
  --danger:  #dc2626;
  --warning: #d97706;
  --info:    #0ea5e9;
  --neutral: #6b7280;
  --success-soft: rgba(22,163,74,.12);
  --danger-soft:  rgba(220,38,38,.12);
  --warning-soft: rgba(217,119,6,.14);
  --info-soft:    rgba(14,165,233,.12);
  --neutral-soft: rgba(107,114,128,.14);

  /* ---- Accent default (Parton = suprimentos). Trocado por [data-company]. ---- */
  --accent: #0d9488;
  --accent-strong: #0f766e;
  --accent-contrast: #ffffff;
  --accent-soft: rgba(13,148,136,.10);

  /* ---- Escala de espaçamento (base 4px, densa) ---- */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-7: 32px;

  /* ---- Raios (menores = layout mais denso) ---- */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;

  /* ---- Tipografia (densa; Inter já carregada no index.css) ---- */
  --font-sans: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 24px;

  /* ---- Sombras (discretas) ---- */
  --shadow-sm: 0 1px 2px rgba(16,21,27,.06);
  --shadow-md: 0 4px 12px rgba(16,21,27,.10);
  --shadow-lg: 0 18px 45px rgba(16,21,27,.16);

  /* ---- Z-index ---- */
  --z-base: 0;
  --z-dropdown: 1000;
  --z-sticky: 1100;
  --z-modal: 1200;
  --z-toast: 1300;

  /* ---- Alturas de controle / toque ---- */
  --control-h-sm: 28px;
  --control-h-md: 32px;
  --touch-min: 40px;

  /* ---- Aliases de compatibilidade (removidos na Fase 4) ---- */
  --card: var(--surface);
  --panel: var(--surface);
  --muted: var(--text-muted);
  --primary: var(--accent);
  --primary-contrast: var(--accent-contrast);
}

/* ---- Tema escuro automático (segue o SO quando não há override) ---- */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #0d1117;
    --surface: #151b23;
    --surface-2: #1c232d;
    --border: #262d38;
    --border-strong: #333c49;
    --text: #e6edf3;
    --text-muted: #9aa4b2;
    --text-subtle: #6b7482;

    --success: #22c55e;
    --danger:  #ef4444;
    --warning: #f59e0b;
    --info:    #38bdf8;
    --neutral: #9aa4b2;
  }
}

/* ---- Override manual: dark vence o media query ---- */
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #0d1117;
  --surface: #151b23;
  --surface-2: #1c232d;
  --border: #262d38;
  --border-strong: #333c49;
  --text: #e6edf3;
  --text-muted: #9aa4b2;
  --text-subtle: #6b7482;

  --success: #22c55e;
  --danger:  #ef4444;
  --warning: #f59e0b;
  --info:    #38bdf8;
  --neutral: #9aa4b2;
}

/* ---- Override manual: light vence o media query ---- */
:root[data-theme="light"] {
  color-scheme: light;
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #f1f3f5;
  --border: #e3e6ea;
  --border-strong: #d1d6dc;
  --text: #10151b;
  --text-muted: #5b6472;
  --text-subtle: #8a929e;
}

/* ---- Accent por empresa (default acima = parton) ---- */
:root[data-company="park"] {
  --accent: #2563eb;
  --accent-strong: #1d4ed8;
  --accent-contrast: #ffffff;
  --accent-soft: rgba(37,99,235,.10);
}
:root[data-company="parton"] {
  --accent: #0d9488;
  --accent-strong: #0f766e;
  --accent-contrast: #ffffff;
  --accent-soft: rgba(13,148,136,.10);
}
```

> **Nota de accent (pendência aberta da spec):** `#2563eb`/`#0d9488` são placeholders. Se houver hex oficial de marca, substituir aqui. Fonte de fallback: `frontend/src/assets/catalog/parton-logo.png` (extrair a cor dominante) — task 0.1b opcional abaixo.

- [ ] **Step 2 (opcional): extrair accent do logo se não houver hex oficial**

Se o usuário não fornecer hex oficiais, abrir `frontend/src/assets/catalog/parton-logo.png`, identificar a cor dominante da marca e ajustar `--accent`/`--accent-strong` do bloco `[data-company="parton"]`. Documentar o hex escolhido em comentário. (Park permanece azul até haver logo/hex próprio.)

- [ ] **Step 3: Verificar build**

Run: `cd frontend && npm ci && npm run build`
Expected: build conclui sem erro. `tokens.css` ainda não está importado, então nada muda visualmente — este step só garante sintaxe CSS válida (o Vite não processa o arquivo até ser importado; validar manualmente que não há chaves não fechadas).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/tokens.css
git commit -m "style(reskin-f0): cria tokens.css com sistema de design e temas"
```

### Task 0.2: Importar tokens e remover bloco de tokens duplicado do `index.css`

**Files:**
- Modify: `frontend/src/main.jsx` (adicionar import de `tokens.css` como primeiro CSS)
- Modify: `frontend/src/index.css` (remover `:root{...}` de tokens e o `@media (prefers-color-scheme: dark){ :root{...} }`; manter reset, login e demais regras)

**Interfaces:**
- Consumes: tokens de `tokens.css` (Task 0.1).
- Produces: `tokens.css` autoritativo; `index.css` deixa de definir tokens.

- [ ] **Step 1: Ler a ordem de imports atual do `main.jsx`**

Run: `sed -n '1,20p' frontend/src/main.jsx` (ou abrir no editor). Identificar onde `index.css` é importado.

- [ ] **Step 2: Adicionar import de `tokens.css` ANTES de `index.css`/`App.css`**

Em `frontend/src/main.jsx`, no topo dos imports de CSS:

```jsx
import "./styles/tokens.css";
import "./index.css";
```

(Manter os demais imports existentes; `tokens.css` primeiro para ser a camada base; blocos `[data-theme]`/`[data-company]` têm especificidade maior que `:root`, então override funciona independentemente da ordem.)

- [ ] **Step 3: Remover de `index.css` o `:root{...}` de tokens (linhas do bloco "Tema base (ERP)") e o `@media (prefers-color-scheme: dark){ :root{ ...tokens... } }`**

Manter em `index.css`: o `@import` da fonte Inter, `html/body`, reset (`* { box-sizing }`), inputs/botões base e toda a seção de login. Remover apenas as **declarações de custom properties** que agora vivem em `tokens.css` (evita conflito de valores). Onde `index.css` referenciar `var(--x)`, mantém — os tokens vêm de `tokens.css`.

- [ ] **Step 4: Verificar build + visual**

Run: `cd frontend && npm run build`
Expected: build ok. Rodar `npm run dev` e confirmar que o app renderiza igual (aliases garantem que `--card`, `--muted`, `--primary` do CSS legado continuam resolvendo).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/main.jsx frontend/src/index.css
git commit -m "style(reskin-f0): tokens.css autoritativo; remove tokens duplicados do index.css"
```

### Task 0.3: Criar `base.css` (reset denso + tipografia base)

**Files:**
- Create: `frontend/src/styles/base.css`
- Modify: `frontend/src/main.jsx` (importar `base.css` após `tokens.css`)

**Interfaces:**
- Consumes: tokens de `tokens.css`.
- Produces: defaults de elemento (body, headings, focus ring) baseados em tokens.

- [ ] **Step 1: Escrever `base.css`**

```css
/* frontend/src/styles/base.css — defaults de elemento sobre os tokens */
html, body { height: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
* { box-sizing: border-box; }

h1 { font-size: var(--text-2xl); }
h2 { font-size: var(--text-xl); }
h3 { font-size: var(--text-lg); }
h1, h2, h3, h4 { line-height: 1.25; letter-spacing: -0.01em; margin: 0 0 var(--space-3); }

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Focus ring único e visível (acessibilidade) */
:where(a, button, input, select, textarea, [tabindex]):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Números tabulares onde importa (aplicado via .num utilitário e em tabelas) */
.num, [data-numeric] { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 2: Importar em `main.jsx` após `tokens.css` e antes de `index.css`**

```jsx
import "./styles/tokens.css";
import "./styles/base.css";
import "./index.css";
```

- [ ] **Step 3: Verificar build + visual**

Run: `cd frontend && npm run build` → ok. `npm run dev`: fonte base 13px, sem regressão de layout grave (App.css ainda domina componentes específicos).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/base.css frontend/src/main.jsx
git commit -m "style(reskin-f0): base.css com reset denso e tipografia"
```

### Task 0.4: Criar `utilities.css` (helpers mínimos)

**Files:**
- Create: `frontend/src/styles/utilities.css`
- Modify: `frontend/src/main.jsx` (importar após `base.css`)

- [ ] **Step 1: Escrever `utilities.css`**

```css
/* frontend/src/styles/utilities.css — helpers mínimos, sem framework */
.u-visually-hidden {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.u-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.u-stack { display: flex; flex-direction: column; gap: var(--space-3); }
.u-cluster { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; }
.u-spread { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.u-num { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 2: Importar em `main.jsx`**

```jsx
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/utilities.css";
import "./index.css";
```

- [ ] **Step 3: Verificar build**

Run: `cd frontend && npm run build` → ok.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/utilities.css frontend/src/main.jsx
git commit -m "style(reskin-f0): utilities.css com helpers minimos"
```

### Task 0.5: Criar `theme.js` (tema auto+override) e helper `data-company`

**Files:**
- Create: `frontend/src/ui/theme.js`
- Modify: `frontend/src/App.jsx` (usar `applyTheme`/`getStoredTheme`; init de `data-company`)

**Interfaces:**
- Consumes: `getCurrentCompany` de `../api`.
- Produces:
  - `getStoredTheme(): "light" | "dark" | null` (null = auto)
  - `setStoredTheme(mode: "light" | "dark" | null): void` — persiste em `localStorage["trml_theme"]` (mesma chave já usada) e aplica no `documentElement`
  - `cycleTheme(current: "light"|"dark"|null): "light"|"dark"|null` — alterna auto→dark→light→auto (ordem definida abaixo)
  - `applyStoredTheme(): void` — lê e aplica no `<html>` no boot
  - `initCompanyAttr(): void` — seta `data-company` no `<html>` a partir de `getCurrentCompany()`

- [ ] **Step 1: Escrever `theme.js`**

```js
// frontend/src/ui/theme.js
import { getCurrentCompany } from "../api";

const THEME_KEY = "trml_theme"; // mesma chave já usada em App.jsx

export function getStoredTheme() {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(THEME_KEY);
  return v === "light" || v === "dark" ? v : null; // null = auto (segue o SO)
}

export function setStoredTheme(mode) {
  if (typeof window === "undefined") return;
  const root = document.documentElement;
  if (mode === "light" || mode === "dark") {
    window.localStorage.setItem(THEME_KEY, mode);
    root.setAttribute("data-theme", mode);
    root.style.colorScheme = mode;
  } else {
    // auto: remove override, deixa o @media(prefers-color-scheme) decidir
    window.localStorage.removeItem(THEME_KEY);
    root.removeAttribute("data-theme");
    root.style.removeProperty("color-scheme");
  }
}

export function cycleTheme(current) {
  // auto -> dark -> light -> auto
  if (current === null) return "dark";
  if (current === "dark") return "light";
  return null;
}

export function applyStoredTheme() {
  setStoredTheme(getStoredTheme());
}

function companyTone(key) {
  return String(key || "").toLowerCase() === "park" ? "park" : "parton";
}

export function initCompanyAttr() {
  if (typeof document === "undefined") return;
  const tone = companyTone(getCurrentCompany?.());
  document.documentElement.setAttribute("data-company", tone);
}
```

- [ ] **Step 2: Refatorar `App.jsx` para usar `theme.js`**

Substituir `THEME_STORAGE_KEY`/`getInitialTheme` e o `useEffect` de tema atuais por:
- estado `theme` do tipo `"light" | "dark" | null` inicializado com `getStoredTheme()`;
- no `useEffect([theme])`, chamar `setStoredTheme(theme)`;
- botão de tema chama `setTheme((t) => cycleTheme(t))`;
- ícone: `null`(auto)→mostrar ícone de "auto"/sistema, `dark`→Sun, `light`→Moon (ou manter binário Sun/Moon e tratar `null` como aparência do SO — decidir na execução, sem quebrar o `aria-label`).
- adicionar, no boot (`useEffect([], …)` ou no effect de `sessionReady/user`), `initCompanyAttr()` para setar `data-company`. Como a troca de empresa dá `window.location.reload()`, basta setar uma vez após o login.

Exemplo do effect de tema:
```jsx
import { getStoredTheme, setStoredTheme, cycleTheme, initCompanyAttr } from "./ui/theme";
// ...
const [theme, setTheme] = useState(getStoredTheme); // "light" | "dark" | null
useEffect(() => { setStoredTheme(theme); }, [theme]);
useEffect(() => { if (sessionReady && user) initCompanyAttr(); }, [sessionReady, user]);
```

- [ ] **Step 3: Verificar build + comportamento de tema/empresa**

Run: `cd frontend && npm run build` → ok.
Manual: `npm run dev` →
- Sem override salvo: o app segue o tema do SO (mudar o SO claro/escuro reflete).
- Clicar no botão de tema alterna e persiste (recarregar mantém).
- `document.documentElement.dataset.company` é `park` ou `parton` conforme a empresa ativa; trocar empresa (reload) atualiza o accent.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/ui/theme.js frontend/src/App.jsx
git commit -m "style(reskin-f0): tema auto+override unico e data-company no root"
```

### Task 0.6: Deduplicar a seção de login no `index.css`

**Files:**
- Modify: `frontend/src/index.css` (remover a primeira definição de login superada pelo bloco "LOGIN visual refresh")

**Interfaces:**
- Nenhuma nova; consolida CSS existente.

- [ ] **Step 1: Identificar as duas definições de login**

O `index.css` define `.loginWrap/.loginCard/.loginBtn/...` na seção inicial e **redefine** as mesmas classes na seção "LOGIN visual refresh" (mais abaixo), que vence por ordem. Mapear quais propriedades da primeira seção ainda têm efeito (as não sobrescritas).

- [ ] **Step 2: Fundir numa única definição**

Manter a versão "LOGIN visual refresh" (a efetiva) e migrar suas cores hardcoded para tokens onde equivalente (`--surface`, `--border`, `--accent`, `--danger`). Remover a primeira definição morta. Preservar `[data-theme="light"]`/`[data-theme="dark"]` do login coerentes com o novo mecanismo.

- [ ] **Step 3: Verificar visual do login**

Run: `npm run dev`, deslogar, conferir tela de login em claro/escuro (auto + override) e mobile (≤520px). Sem regressão.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css
git commit -m "style(reskin-f0): dedup da secao de login no index.css"
```

**Gate da Fase 0:** rodar a checklist de validação global (build, eslint sem novos problemas, visual claro/escuro/Parton/Park/desktop/mobile). App visualmente equivalente, agora sobre o sistema de tokens.

---

## FASE 1 — Kit de componentes + Shell + Login

Objetivo: construir o kit `src/ui/` (a garantia de consistência) e aplicá-lo ao shell (sidebar, banners, loading global) e ao login. Cada componente é um task testável isoladamente via `npm run build` + inspeção no dev.

> **Padrão de todos os componentes do kit:** JSX puro + CSS próprio importado no topo do `.jsx`; classes prefixadas com o nome do componente (`ui-btn`, `ui-card`…); todas as cores/espaços vêm de tokens; sem dependências externas. Exportados no barrel `src/ui/index.js`.

### Task 1.1: `Button`

**Files:**
- Create: `frontend/src/ui/Button.jsx`, `frontend/src/ui/Button.css`

**Interfaces:**
- Produces: `<Button variant="primary|secondary|ghost|danger" size="sm|md" loading icon={<svg/>} {...buttonProps}>`

- [ ] **Step 1: Escrever `Button.jsx`**

```jsx
import "./Button.css";

export default function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon = null,
  disabled = false,
  className = "",
  children,
  ...rest
}) {
  return (
    <button
      className={`ui-btn ui-btn--${variant} ui-btn--${size} ${loading ? "is-loading" : ""} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <span className="ui-btn__spinner" aria-hidden="true" /> : icon ? <span className="ui-btn__icon" aria-hidden="true">{icon}</span> : null}
      <span className="ui-btn__label">{children}</span>
    </button>
  );
}
```

- [ ] **Step 2: Escrever `Button.css`**

```css
.ui-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2);
  font: inherit; font-weight: 600; cursor: pointer;
  border: 1px solid transparent; border-radius: var(--radius-md);
  height: var(--control-h-md); padding: 0 var(--space-3);
  transition: filter .12s ease, background-color .15s ease, border-color .15s ease;
}
.ui-btn--sm { height: var(--control-h-sm); padding: 0 var(--space-2); font-size: var(--text-sm); }
.ui-btn:disabled { opacity: .6; cursor: not-allowed; }
.ui-btn--primary { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
.ui-btn--primary:hover:not(:disabled) { filter: brightness(1.05); }
.ui-btn--secondary { background: var(--surface); color: var(--text); border-color: var(--border-strong); }
.ui-btn--secondary:hover:not(:disabled) { background: var(--surface-2); }
.ui-btn--ghost { background: transparent; color: var(--text-muted); }
.ui-btn--ghost:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.ui-btn--danger { background: var(--danger); color: #fff; border-color: var(--danger); }
.ui-btn--danger:hover:not(:disabled) { filter: brightness(1.05); }
.ui-btn__spinner {
  width: 14px; height: 14px; border-radius: 50%;
  border: 2px solid currentColor; border-top-color: transparent;
  animation: ui-spin .6s linear infinite;
}
@keyframes ui-spin { to { transform: rotate(360deg); } }
@media (max-width: 768px) { .ui-btn { min-height: var(--touch-min); } }
```

- [ ] **Step 3: Adicionar ao barrel** `frontend/src/ui/index.js`:

```js
export { default as Button } from "./Button";
```

- [ ] **Step 4: Verificar build** — `cd frontend && npm run build` → ok.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/ui/Button.jsx frontend/src/ui/Button.css frontend/src/ui/index.js
git commit -m "feat(reskin-f1): componente Button do kit"
```

### Task 1.2: `Card`

**Files:** Create `frontend/src/ui/Card.jsx`, `Card.css`; Modify barrel.

**Interfaces:** `<Card title? actions? padding="md|sm|none">children</Card>`

- [ ] **Step 1: `Card.jsx`**

```jsx
import "./Card.css";

export default function Card({ title, actions, padding = "md", className = "", children }) {
  return (
    <section className={`ui-card ui-card--pad-${padding} ${className}`}>
      {(title || actions) && (
        <header className="ui-card__head">
          {title ? <h3 className="ui-card__title">{title}</h3> : <span />}
          {actions ? <div className="ui-card__actions">{actions}</div> : null}
        </header>
      )}
      <div className="ui-card__body">{children}</div>
    </section>
  );
}
```

- [ ] **Step 2: `Card.css`**

```css
.ui-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm); }
.ui-card__head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border); }
.ui-card__title { margin: 0; font-size: var(--text-md); font-weight: 700; }
.ui-card__actions { display: flex; gap: var(--space-2); }
.ui-card--pad-md .ui-card__body { padding: var(--space-4); }
.ui-card--pad-sm .ui-card__body { padding: var(--space-3); }
.ui-card--pad-none .ui-card__body { padding: 0; }
```

- [ ] **Step 3: barrel** `export { default as Card } from "./Card";`
- [ ] **Step 4: build** → ok.
- [ ] **Step 5: Commit** `git commit -m "feat(reskin-f1): componente Card"`

### Task 1.3: `StatusPill` (com mapa de status central)

**Files:** Create `frontend/src/ui/StatusPill.jsx`, `StatusPill.css`; Modify barrel.

**Interfaces:**
- `<StatusPill status="aberto|em separação|aprovado|faturado|conferido|cancelado|…" />`
- Exporta também `statusTone(status): "info|warning|success|accent|neutral|danger"` para reuso.

- [ ] **Step 1: `StatusPill.jsx`** (mapa = proposta da spec §4.3; validar contra status reais na Fase 2)

```jsx
import "./StatusPill.css";

const TONE_BY_STATUS = {
  "aberto": "info",
  "em separacao": "warning",
  "em separação": "warning",
  "aprovado": "success",
  "faturado": "accent",
  "conferido": "neutral",
  "cancelado": "danger",
};

function norm(s) { return String(s || "").trim().toLowerCase(); }

export function statusTone(status) {
  return TONE_BY_STATUS[norm(status)] || "neutral";
}

export default function StatusPill({ status, className = "" }) {
  const tone = statusTone(status);
  return <span className={`ui-pill ui-pill--${tone} ${className}`}>{status}</span>;
}
```

- [ ] **Step 2: `StatusPill.css`**

```css
.ui-pill { display: inline-flex; align-items: center; gap: var(--space-1); height: 20px; padding: 0 var(--space-2); border-radius: 999px; font-size: var(--text-xs); font-weight: 700; letter-spacing: .02em; text-transform: uppercase; white-space: nowrap; }
.ui-pill--info    { background: var(--info-soft);    color: var(--info); }
.ui-pill--warning { background: var(--warning-soft); color: var(--warning); }
.ui-pill--success { background: var(--success-soft); color: var(--success); }
.ui-pill--danger  { background: var(--danger-soft);  color: var(--danger); }
.ui-pill--neutral { background: var(--neutral-soft); color: var(--neutral); }
.ui-pill--accent  { background: var(--accent-soft);  color: var(--accent-strong); }
```

- [ ] **Step 3: barrel** `export { default as StatusPill, statusTone } from "./StatusPill";`
- [ ] **Step 4: build** → ok.
- [ ] **Step 5: Commit** `git commit -m "feat(reskin-f1): StatusPill com mapa de status central"`

### Task 1.4: `Field` (label + controle + erro)

**Files:** Create `frontend/src/ui/Field.jsx`, `Field.css`; Modify barrel.

**Interfaces:** `<Field label id error? help?> <input/> </Field>` — envolve qualquer controle; associa label via `htmlFor`.

- [ ] **Step 1: `Field.jsx`**

```jsx
import "./Field.css";

export default function Field({ label, id, error, help, className = "", children }) {
  return (
    <div className={`ui-field ${error ? "is-error" : ""} ${className}`}>
      {label ? <label className="ui-field__label" htmlFor={id}>{label}</label> : null}
      <div className="ui-field__control">{children}</div>
      {help && !error ? <div className="ui-field__help">{help}</div> : null}
      {error ? <div className="ui-field__error">{error}</div> : null}
    </div>
  );
}
```

- [ ] **Step 2: `Field.css`**

```css
.ui-field { display: flex; flex-direction: column; gap: var(--space-1); margin-bottom: var(--space-3); }
.ui-field__label { font-size: var(--text-sm); font-weight: 600; color: var(--text); }
.ui-field__control :where(input, select, textarea) {
  width: 100%; height: var(--control-h-md); padding: 0 var(--space-2);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--radius-md);
}
.ui-field__control textarea { height: auto; padding: var(--space-2); min-height: 72px; }
.ui-field__control :where(input, select, textarea):focus { border-color: var(--accent); outline: none; box-shadow: 0 0 0 3px var(--accent-soft); }
.ui-field__help { font-size: var(--text-xs); color: var(--text-subtle); }
.ui-field__error { font-size: var(--text-xs); color: var(--danger); font-weight: 600; }
.ui-field.is-error .ui-field__control :where(input, select, textarea) { border-color: var(--danger); }
@media (max-width: 768px) { .ui-field__control :where(input, select, textarea) { min-height: var(--touch-min); } }
```

- [ ] **Step 3: barrel** `export { default as Field } from "./Field";`
- [ ] **Step 4: build** → ok.
- [ ] **Step 5: Commit** `git commit -m "feat(reskin-f1): Field com label e erro"`

### Task 1.5: `PageHeader` e `Toolbar`

**Files:** Create `PageHeader.jsx`/`.css`, `Toolbar.jsx`/`.css`; Modify barrel.

**Interfaces:**
- `<PageHeader title crumb? actions?/>`
- `<Toolbar> {filtros} <Toolbar.Spacer/> {ações} </Toolbar>` — barra de filtros/ações de listas.

- [ ] **Step 1: `PageHeader.jsx`**

```jsx
import "./PageHeader.css";

export default function PageHeader({ title, crumb, actions, className = "" }) {
  return (
    <header className={`ui-pagehead ${className}`}>
      <div className="ui-pagehead__titles">
        {crumb ? <div className="ui-pagehead__crumb">{crumb}</div> : null}
        <h1 className="ui-pagehead__title">{title}</h1>
      </div>
      {actions ? <div className="ui-pagehead__actions">{actions}</div> : null}
    </header>
  );
}
```

- [ ] **Step 2: `PageHeader.css`**

```css
.ui-pagehead { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-4); flex-wrap: wrap; }
.ui-pagehead__crumb { font-size: var(--text-xs); color: var(--text-subtle); text-transform: uppercase; letter-spacing: .04em; }
.ui-pagehead__title { margin: 0; font-size: var(--text-xl); font-weight: 800; }
.ui-pagehead__actions { display: flex; gap: var(--space-2); }
```

- [ ] **Step 3: `Toolbar.jsx`**

```jsx
import "./Toolbar.css";

export default function Toolbar({ className = "", children }) {
  return <div className={`ui-toolbar ${className}`}>{children}</div>;
}
Toolbar.Spacer = function Spacer() { return <div className="ui-toolbar__spacer" />; };
```

- [ ] **Step 4: `Toolbar.css`**

```css
.ui-toolbar { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; padding: var(--space-2) 0; margin-bottom: var(--space-3); }
.ui-toolbar__spacer { flex: 1 1 auto; }
@media (max-width: 768px) { .ui-toolbar > * { flex: 1 1 auto; } }
```

- [ ] **Step 5: barrel** (`PageHeader`, `Toolbar`), **build** → ok, **Commit** `git commit -m "feat(reskin-f1): PageHeader e Toolbar"`

### Task 1.6: `Feedback` (Spinner + Skeleton) e `EmptyState`

**Files:** Create `Feedback.jsx`/`Feedback.css`, `EmptyState.jsx`/`EmptyState.css`; Modify barrel.

**Interfaces:**
- `<Spinner size={number} label?/>`, `<Skeleton width height radius/>`, `<EmptyState icon? title message action?/>`

- [ ] **Step 1: `Feedback.jsx`**

```jsx
import "./Feedback.css";

export function Spinner({ size = 20, label = "Carregando" }) {
  return <span className="ui-spinner" style={{ width: size, height: size }} role="status" aria-label={label} />;
}

export function Skeleton({ width = "100%", height = 14, radius = "var(--radius-sm)" }) {
  return <span className="ui-skeleton" style={{ width, height, borderRadius: radius }} aria-hidden="true" />;
}
```

- [ ] **Step 2: `Feedback.css`**

```css
.ui-spinner { display: inline-block; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: ui-spin .6s linear infinite; }
.ui-skeleton { display: block; background: linear-gradient(90deg, var(--surface-2), var(--border), var(--surface-2)); background-size: 200% 100%; animation: ui-shimmer 1.2s ease-in-out infinite; }
@keyframes ui-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
```

(reusa `@keyframes ui-spin` de `Button.css`; se o kit for tree-shaken por CSS-per-componente, redeclarar `ui-spin` aqui para independência.)

- [ ] **Step 3: `EmptyState.jsx`**

```jsx
import "./EmptyState.css";

export default function EmptyState({ icon = null, title, message, action = null, className = "" }) {
  return (
    <div className={`ui-empty ${className}`}>
      {icon ? <div className="ui-empty__icon" aria-hidden="true">{icon}</div> : null}
      {title ? <div className="ui-empty__title">{title}</div> : null}
      {message ? <div className="ui-empty__msg">{message}</div> : null}
      {action ? <div className="ui-empty__action">{action}</div> : null}
    </div>
  );
}
```

- [ ] **Step 4: `EmptyState.css`**

```css
.ui-empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: var(--space-2); padding: var(--space-7) var(--space-4); color: var(--text-muted); }
.ui-empty__icon { color: var(--text-subtle); }
.ui-empty__title { font-size: var(--text-md); font-weight: 700; color: var(--text); }
.ui-empty__msg { font-size: var(--text-sm); max-width: 42ch; }
.ui-empty__action { margin-top: var(--space-2); }
```

- [ ] **Step 5: barrel** (`Spinner`, `Skeleton`, `EmptyState`), **build** → ok, **Commit** `git commit -m "feat(reskin-f1): Spinner, Skeleton e EmptyState"`

### Task 1.7: `Toast` (provider + hook)

**Files:** Create `Toast.jsx`/`Toast.css`; Modify barrel; Modify `main.jsx` (envolver `<App/>` com `<ToastProvider>`).

**Interfaces:**
- `<ToastProvider>` no root; `useToast()` → `{ toast: ({ type: "success|error|info", message, duration? }) => void }`

- [ ] **Step 1: `Toast.jsx`**

```jsx
import { createContext, useCallback, useContext, useRef, useState } from "react";
import "./Toast.css";

const ToastCtx = createContext(null);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const seq = useRef(0);

  const remove = useCallback((id) => setItems((xs) => xs.filter((t) => t.id !== id)), []);

  const toast = useCallback(({ type = "info", message, duration = 3500 }) => {
    const id = ++seq.current;
    setItems((xs) => [...xs, { id, type, message }]);
    if (duration > 0) setTimeout(() => remove(id), duration);
  }, [remove]);

  return (
    <ToastCtx.Provider value={{ toast }}>
      {children}
      <div className="ui-toasts" role="region" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`ui-toast ui-toast--${t.type}`} onClick={() => remove(t.id)}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  return ctx || { toast: () => {} };
}
```

- [ ] **Step 2: `Toast.css`**

```css
.ui-toasts { position: fixed; right: var(--space-4); bottom: var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); z-index: var(--z-toast); }
.ui-toast { min-width: 220px; max-width: 360px; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--surface); color: var(--text); border: 1px solid var(--border-strong); box-shadow: var(--shadow-md); font-size: var(--text-sm); cursor: pointer; border-left-width: 3px; }
.ui-toast--success { border-left-color: var(--success); }
.ui-toast--error   { border-left-color: var(--danger); }
.ui-toast--info    { border-left-color: var(--info); }
@media (max-width: 768px) { .ui-toasts { left: var(--space-3); right: var(--space-3); } .ui-toast { max-width: none; } }
```

- [ ] **Step 3: Envolver `<App/>` no `main.jsx`**

```jsx
import { ToastProvider } from "./ui/Toast";
// ...
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>
);
```

- [ ] **Step 4: barrel** (`ToastProvider`, `useToast`), **build** → ok.
- [ ] **Step 5: Commit** `git commit -m "feat(reskin-f1): Toast provider e useToast"`

### Task 1.8: `Table` (tabela densa responsiva)

**Files:** Create `Table.jsx`/`Table.css`; Modify barrel.

**Interfaces:** wrapper leve para tabelas densas — `<Table>` aplica header fixo, zebra e scroll horizontal no mobile; colunas numéricas usam `.u-num`. Uso: `<Table><thead>…</thead><tbody>…</tbody></Table>`.

- [ ] **Step 1: `Table.jsx`**

```jsx
import "./Table.css";

export default function Table({ zebra = true, className = "", children }) {
  return (
    <div className="ui-table__scroll">
      <table className={`ui-table ${zebra ? "ui-table--zebra" : ""} ${className}`}>{children}</table>
    </div>
  );
}
```

- [ ] **Step 2: `Table.css`**

```css
.ui-table__scroll { width: 100%; overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-lg); }
.ui-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
.ui-table thead th { position: sticky; top: 0; background: var(--surface-2); color: var(--text-muted); text-align: left; font-weight: 700; font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .03em; padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); white-space: nowrap; }
.ui-table tbody td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); color: var(--text); }
.ui-table--zebra tbody tr:nth-child(even) { background: color-mix(in srgb, var(--surface-2) 55%, transparent); }
.ui-table tbody tr:hover { background: var(--surface-2); }
.ui-table [data-numeric], .ui-table .u-num { text-align: right; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 3: barrel** `export { default as Table } from "./Table";`
- [ ] **Step 4: build** → ok.
- [ ] **Step 5: Commit** `git commit -m "feat(reskin-f1): Table densa responsiva"`

### Task 1.9: Aplicar kit ao Shell (`App.jsx`) e ao loading global

**Files:**
- Modify: `frontend/src/App.jsx` (banners, sidebar, botões, loading global → `Spinner`)
- Modify: `frontend/src/App.css` (regras do shell passam a usar tokens; remover valores literais equivalentes)

**Interfaces:**
- Consumes: `Button`, `Spinner` do kit; tokens.

- [ ] **Step 1: Substituir o overlay de loading global inline por `Spinner`**

Trocar o bloco `globalLoadingOpen ? (<div style={{…}}>…<div style={{spinner}}/>…</div>)` por um overlay com classe CSS + `<Spinner size={40} label={globalLoadingLabel} />`. Adicionar em `App.css`:

```css
.appGlobalLoading { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: color-mix(in srgb, var(--bg) 70%, transparent); backdrop-filter: blur(2px); z-index: var(--z-modal); }
```

- [ ] **Step 2: Migrar cores do shell para tokens em `App.css`**

Nas regras `.appShell/.appSidebar/.appMain/.sideItem/.sideItemActive/.systemEnvBanner/.sideThemeBtn/.sideLogoutBtn` etc., substituir cores/hardcodes por `var(--surface)`, `var(--border)`, `var(--text)`, `var(--text-muted)`, `var(--accent)`, `var(--accent-soft)`. Densificar espaçamentos com tokens `--space-*`. Não alterar estrutura JSX do menu nem a lógica de `activeView`.

- [ ] **Step 3: Trocar os `<button>` do topo/sidebar por `Button` onde fizer sentido** (ex.: "Sair" → `<Button variant="ghost" size="sm">`), preservando handlers (`safeSignOut`) e acessibilidade.

- [ ] **Step 4: Verificar visual do shell**

Run: `npm run dev`. Conferir sidebar/menu/banners densos, item ativo com accent, tema claro/escuro, Parton (verde-azulado) vs Park (azul), e responsivo (sidebar utilizável ≤768px).

- [ ] **Step 5: build + eslint + Commit**

```bash
cd frontend && npm run build && npx eslint src/App.jsx
git add frontend/src/App.jsx frontend/src/App.css
git commit -m "style(reskin-f1): shell denso com tokens e kit"
```

### Task 1.10: Aplicar kit ao Login (`Login.jsx`)

**Files:**
- Modify: `frontend/src/Login.jsx` (usar `Field`/`Button`; classes de login já tokenizadas na Task 0.6)

- [ ] **Step 1: Ler `Login.jsx`** e mapear inputs/botões atuais.
- [ ] **Step 2: Envolver campos com `Field` e trocar o botão principal por `Button variant="primary" loading`**, preservando o fluxo `onLogin`/`externalError` e strings PT.
- [ ] **Step 3: Verificar login em claro/escuro/mobile.**
- [ ] **Step 4: build + Commit** `git commit -m "style(reskin-f1): login com Field e Button"`

**Gate da Fase 1:** kit completo em `src/ui/`, shell e login restilados. Rodar checklist global.

---

## FASE 2 — Operacional (SavedQuotes, QuotesModal, NewQuote)

Objetivo: restilar o fluxo diário. **Antes de restilar, validar o mapa de status real** (spec §4.3) contra os status que essas telas exibem, ajustando `TONE_BY_STATUS` em `StatusPill.jsx` se necessário.

> Cada página segue a mesma **receita de aplicação**:
> 1. Envolver o topo da tela com `<PageHeader title=… actions=…/>`.
> 2. Filtros/ações de lista em `<Toolbar>`.
> 3. Blocos em `<Card>`; tabelas via `<Table>` com colunas numéricas `data-numeric`.
> 4. Status via `<StatusPill status=…/>` (remover coloração inline de status).
> 5. Estados: loading → `<Skeleton>`/`<Spinner>`; vazio/erro → `<EmptyState>` com ação de retry; ação assíncrona → `Button loading` + `useToast().toast(...)`.
> 6. Botões → `<Button>`; inputs → `<Field>`.
> 7. Trocar cores/hardcodes remanescentes por tokens; **não** alterar lógica, permissões ou chamadas de API.

### Task 2.0: Validar mapa de status real

**Files:** Read `frontend/src/pages/SavedQuotes.jsx`, `frontend/src/components/QuotesModal.jsx`.

- [ ] **Step 1:** Grep dos rótulos de status usados (`git grep -iE "aberto|separa|aprovad|faturad|conferid|cancelad"` em `frontend/src`). Listar os valores reais.
- [ ] **Step 2:** Ajustar `TONE_BY_STATUS` em `StatusPill.jsx` para cobrir 100% dos status reais (incluindo variações com/sem acento e maiúsculas — `norm()` já minúscula/trim). Garantir que status de significado próximo não colidam de cor (regra spec §4.3).
- [ ] **Step 3:** build + Commit `git commit -m "style(reskin-f2): mapa de status validado contra o backend"`

### Task 2.1: `SavedQuotes.jsx` (lista + toolbar + tabela + status)

**Files:** Modify `frontend/src/pages/SavedQuotes.jsx` (e CSS associado em `App.css` se houver).

**Interfaces:** Consumes `PageHeader, Toolbar, Card, Table, StatusPill, Button, EmptyState, Spinner, Skeleton, useToast`.

- [ ] **Step 1:** Ler a tela e identificar: cabeçalho, filtros, tabela/lista, badges de status, ações (editar, sync), estados de loading/vazio/erro.
- [ ] **Step 2:** Aplicar a receita acima. Exemplo de transformação de status:

```jsx
// antes: <span className="badgeStatus" style={{color: corDoStatus(s)}}>{s}</span>
// depois:
import { StatusPill } from "../ui";
<StatusPill status={s} />
```

- [ ] **Step 3:** Loading da lista com `Skeleton` (linhas), vazio com `EmptyState` (ex.: "Nenhum orçamento encontrado" + `Button` "Novo orçamento"), erro com `EmptyState` + retry.
- [ ] **Step 4:** Sync manual: `Button loading` + `toast({type, message})` no sucesso/erro (preservando a lógica de sync existente).
- [ ] **Step 5:** Verificar densidade/legibilidade/responsivo (tabela → scroll horizontal ≤768px). Confirmar que **nenhum campo admin-only** (custo/margem/resultado/cobertura) passou a aparecer para não-admin.
- [ ] **Step 6:** build + eslint + Commit `git commit -m "style(reskin-f2): SavedQuotes denso com kit"`

### Task 2.2: `QuotesModal.jsx` (modal operacional core)

**Files:** Modify `frontend/src/components/QuotesModal.jsx`.

- [ ] **Step 1:** Ler o modal; mapear cabeçalho, corpo (itens/tabela), rodapé de ações, estados.
- [ ] **Step 2:** Aplicar receita: cabeçalho consistente, `Table` para itens, `StatusPill`, `Button` nas ações, `Field` em inputs, `toast` nos resultados. **Preservar** toda a lógica de edição, sync e regras de negócio.
- [ ] **Step 3:** Atenção a densidade em telas pequenas (modal responsivo, alvos ≥40px).
- [ ] **Step 4:** Verificar; confirmar proteção de campos admin-only.
- [ ] **Step 5:** build + eslint + Commit `git commit -m "style(reskin-f2): QuotesModal denso com kit"`

### Task 2.3: `NewQuote.jsx` (criação de orçamento)

**Files:** Modify `frontend/src/pages/NewQuote.jsx`.

- [ ] **Step 1:** Ler a tela (é grande; inclui busca de produtos, estoque, preview). Mapear seções.
- [ ] **Step 2:** Aplicar receita seção por seção (PageHeader, Card por bloco, Field na busca, Button nas ações, Toast). **Não** tocar na lógica de busca/estoque/preview nem nos `forceOpen*` props.
- [ ] **Step 3:** Verificar; responsivo; sem regressão da busca de produtos (comportamento do PR #9 preservado).
- [ ] **Step 4:** build + eslint + Commit `git commit -m "style(reskin-f2): NewQuote denso com kit"`

**Gate da Fase 2:** fluxo diário restilado. Checklist global + teste manual de criar/editar/sincronizar um orçamento sem alteração de comportamento.

---

## FASE 3 — Dashboard (`Home.jsx`)

Objetivo: restilar o dashboard preservando **rigorosamente** a regra de acesso: métricas admin-only (custo/resultado_bruto/margem/cobertura) **nunca** para vendedor.

### Task 3.1: `Home.jsx` (cards de métricas + filtros + gráficos)

**Files:** Modify `frontend/src/pages/Home.jsx`.

**Interfaces:** Consumes `PageHeader, Toolbar, Card, StatusPill, Button, Field, Spinner, Skeleton, EmptyState`.

- [ ] **Step 1:** Ler `Home.jsx`; mapear: filtro de vendedor (admin-only), filtro de período, cards de métricas, gráfico 7 dias, popup horário, resultado bruto (admin-only).
- [ ] **Step 2:** Aplicar receita. Cards de métrica como `<Card>` densos; filtros em `<Toolbar>` com `<Field>`; loading com `Skeleton`. **Manter intactos** os `guards` que escondem métricas admin-only — não mover a checagem para CSS; a condição de render em JS permanece.
- [ ] **Step 3:** Gráficos: apenas restilar o contêiner/legenda (cores via tokens); **não** trocar a lib/lógica de gráfico.
- [ ] **Step 4:** Verificar como **admin** (vê tudo) e simular **não-admin** (não vê custo/margem/resultado). Responsivo: cards empilham ≤768px.
- [ ] **Step 5:** build + eslint + Commit `git commit -m "style(reskin-f3): Home denso preservando campos admin-only"`

**Gate da Fase 3:** dashboard restilado; verificação explícita de que vendedor não vê campos sensíveis.

---

## FASE 4 — Restante + limpeza + PR

Objetivo: restilar as telas restantes (não-órfãs), remover aliases de compatibilidade, reconciliar o `CLAUDE.md` e abrir o PR único.

> Telas desta fase (todas seguem a receita da Fase 2): `ClientWallet.jsx`, `Separation.jsx` (foco mobile/toque), `Catalog.jsx`, `Products.jsx`, `Compras.jsx`, `AdminUsers.jsx`, `AdminSettings.jsx`.
> **Fora do escopo (órfãs):** `QuotesList.jsx`, `TinySyncPreview.jsx`.

### Task 4.1: `ClientWallet.jsx`
- [ ] Aplicar receita; build + eslint; Commit `git commit -m "style(reskin-f4): ClientWallet"`

### Task 4.2: `Separation.jsx` (prioridade mobile)
- [ ] Aplicar receita com atenção extra a toque (alvos ≥40px, foto/conferência utilizável no celular). Não alterar o fluxo de conferência por foto.
- [ ] Verificar em largura de celular real (≤420px). build + eslint; Commit `git commit -m "style(reskin-f4): Separation mobile-first"`

### Task 4.3: `Catalog.jsx`, `Products.jsx`, `Compras.jsx` (admin)
- [ ] Aplicar receita em cada uma; build + eslint por tela; Commit por tela `git commit -m "style(reskin-f4): <tela>"`

### Task 4.4: `AdminUsers.jsx`, `AdminSettings.jsx`
- [ ] Aplicar receita; preservar vínculo ERP↔Tiny e selects de vendedor. build + eslint; Commit `git commit -m "style(reskin-f4): telas de administração"`

### Task 4.5: Remover aliases de compatibilidade

**Files:** Modify `frontend/src/styles/tokens.css`, e qualquer CSS que ainda use `--card/--panel/--muted/--primary`.

- [ ] **Step 1:** `git grep -nE "var\(--(card|panel|muted|primary)\)" frontend/src` → listar usos remanescentes.
- [ ] **Step 2:** Substituir cada uso pelo token novo equivalente (`--surface`, `--text-muted`, `--accent`, `--accent-contrast`).
- [ ] **Step 3:** Remover o bloco de aliases de `tokens.css`.
- [ ] **Step 4:** build + eslint + varredura visual rápida de todas as telas. Commit `git commit -m "style(reskin-f4): remove aliases de compatibilidade"`

### Task 4.6: Reconciliar `CLAUDE.md` com fluxo PR-only

**Files:** Modify `CLAUDE.md` (seção "No Git Workflow — Backup + Report Is the Control" e "Hard Constraints").

- [ ] **Step 1:** Atualizar a seção para refletir que, para este trabalho, o fluxo autorizado é **branch + commits por fase + um PR único** (sem merge/push/deploy). Deixar claro que continua proibido subir para `main`/deploy/restart sem autorização.
- [ ] **Step 2:** Commit `git commit -m "docs: reconcilia CLAUDE.md com fluxo PR-only do reskin"`

### Task 4.7: Validação final + abrir PR

- [ ] **Step 1:** `cd frontend && npm ci && npm run build` → sem erros.
- [ ] **Step 2:** `npx eslint .` → comparar contagem de problemas com o baseline da `main` (não pode haver **novos** problemas). Registrar antes/depois.
- [ ] **Step 3:** Varredura manual completa: cada tela em claro/escuro (auto+override), Parton e Park, desktop e mobile; acentos PT intactos; nenhum campo admin-only vazando.
- [ ] **Step 4:** `git push -u origin feat/reskin-visual-denso` e abrir o PR via `gh pr create` com corpo mapeando as fases/telas e a checklist de validação. **Parar aqui — não fazer merge.**

```bash
gh pr create --base main --head feat/reskin-visual-denso \
  --title "Reskin visual denso (Parton/Park)" \
  --body "Reskin de apresentação: tokens + kit de componentes, tema auto+override, accent por empresa, responsivo. Sem mudança de lógica/API/permissões. Ver docs/superpowers/specs e plans. Não fazer merge sem revisão."
```

**Gate da Fase 4 (final):** PR aberto, build/eslint/visual ok, aliases removidos, `CLAUDE.md` reconciliado. Fim do escopo.

---

## Self-Review (feito pelo autor do plano)

**Cobertura da spec:**
- §4.1 tokens neutros + rename/alias → Task 0.1 (aliases), 4.5 (remoção). ✔
- §4.2 accent por empresa + `data-company` (fiação nova, fonte = `api.getCurrentCompany()`) → Task 0.1 (accent), 0.5 (`initCompanyAttr`). ✔
- §4.3 mapa de status + `--info` fixo + `--neutral` → Task 1.3 (mapa), 2.0 (validação real). ✔
- §4.4 escalas → Task 0.1. ✔
- §4.5 mecânica de tema (auto+override, sem duplicação) → Task 0.1 (blocos `[data-theme]`), 0.5 (`theme.js`). ✔
- §5 arquitetura de arquivos → File Structure + Tasks 0.1–1.8. ✔
- §6 kit de componentes (10) → Tasks 1.1–1.8 (Button, Card, Table, StatusPill, Field, Toolbar, PageHeader, EmptyState, Spinner/Skeleton, Toast). ✔
- §7 densidade/responsivo/estados → tokens densos, breakpoints ≤768px em cada CSS, receita de estados (Fase 2+). ✔
- §8 rollout por fases + órfãs excluídas → Fases 0–4; `QuotesList`/`TinySyncPreview` fora (confirmado por grep). ✔
- §9 validação `npm ci`+build+eslint+manual → Global Constraints + gates. ✔
- §10 restrições de entrega + reconciliar CLAUDE.md → Global Constraints + Task 4.6 + 4.7. ✔
- §11 riscos (aliases, contraste, tema) → mitigados por aliases (0.1/4.5), `--accent-contrast`/`--accent-soft`, blocos `[data-theme]` autoritativos. ✔

**Consistência de tipos/nomes:** tokens usados nos CSS dos componentes (`--accent`, `--surface`, `--space-*`, `--control-h-md`, `--*-soft`, `--z-toast`) estão todos definidos na Task 0.1. `statusTone`/`TONE_BY_STATUS` consistentes entre Task 1.3 e 2.0. `useToast().toast({type,message})` idêntico entre 1.7 e usos nas fases 2–4.

**Sem placeholders de código:** foundation e kit têm código completo; tarefas de página são aplicação de receita documentada com exemplos reais (não reproduzem o arquivo inteiro por serem telas grandes — decisão explícita, não omissão).

**Pendência herdada da spec (não bloqueia o plano):** hex oficiais de accent Park/Parton — resolvida na Task 0.1 Step 2 (extrair do logo) se não houver hex oficial.
