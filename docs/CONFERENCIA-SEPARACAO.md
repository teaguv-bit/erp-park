# Conferência da Separação + Foto

Etapa **opcional** de conferência embutida no fluxo de Separação, com foto. É
**aditiva e gated**: desligada, o comportamento é idêntico ao fluxo legado.

## Controle (runtime, pelo admin)

O liga/desliga em produção é feito pela tela **Admin → aba "Conferência"** — um
seletor `Desativada / soft / strict`. É persistido em `erp.app_settings`
(`sep_conferencia_mode`) e aplicado **sem reiniciar o ERP**. A tela de Separação
revalida `api.me()` ao abrir e no auto-refresh leve (~15s quando ociosa), então a
mudança propaga para os operadores em ~15s, sem reload manual.

| Camada | Controle | Default | Efeito |
|---|---|---|---|
| **Backend (runtime, admin)** | **Admin → aba "Conferência"** (`erp.app_settings`) | `off` | Fonte de verdade do modo. Alimenta `me().features.conferencia` + `conferencia_mode` e é o **kill-switch real**: com `off`, upload → 403 e o PATCH ignora os campos de conferência, mesmo para cliente autenticado. |
| Backend (default inicial) | env `ENABLE_SEP_CONFERENCIA` | `false` | Define o valor inicial **só enquanto não houver registro no banco**. Depois do primeiro toggle, o admin manda. |
| Frontend (fallback) | `VITE_SEP_CONFERENCIA_MODE` | `off` | Usado apenas se o backend não informar o modo (compatibilidade). |
| Frontend (allowlist) | `VITE_SEP_CONFERENCIA_OPERATORS` | vazio | logins (vírgula) que entram em `soft`. |
| Frontend (QA por device) | localStorage `sep_conferencia_mode` | — | override `off/soft/strict` por dispositivo. |

**Coerção dura:** sem `me().features.conferencia === true` (modo `off`), o front
força `off` e ignora fallback/allowlist/localStorage. **OFF é o default.**

### Modos
- **off** — fluxo legado (sem conferência, sem foto). Idêntico byte-a-byte.
- **soft** — piloto sem tablet: foto opcional; etiqueta no mesmo timing de hoje.
- **strict** — com tablet: foto da separação obrigatória; etiqueta só após a conferência.

## Plano de ativação (ramp)

1. **Deploy.** Tudo OFF por padrão (env `ENABLE_SEP_CONFERENCIA` ausente). É preciso
   **reiniciar o ERP uma vez** para criar colunas/tabelas e registrar as rotas novas.
2. **Piloto:** Admin → aba **Conferência** → **"Ativada — foto opcional (soft)"**.
   Sem restart; vale para todos no próximo load da Separação.
   (Opcional: `VITE_SEP_CONFERENCIA_OPERATORS=<logins>` para restringir o piloto.)
3. **Strict:** mesma tela → **"Ativada — foto obrigatória (strict)"**.

## Rollback

- **Desligar em runtime:** Admin → aba **Conferência** → **"Desativada"**. Sem restart;
  o front volta limpo ao legado no próximo load e o kill-switch backend passa a valer
  (upload → 403, PATCH ignora os campos de conferência).
- **Rollback no meio do voo:** pedidos que já estavam em `awaiting_conference=true`
  permanecem com status interno "Preparando Envio" (= "Separando") e **sem push ao
  Tiny** — o push só ocorre ao finalizar a conferência. Após o rollback, o operador
  **re-finaliza pelo fluxo legado** ("Separado"), que dispara a transição/push normal.
  Nenhum dado é perdido; os campos de conferência ficam dormentes no banco.

## Segurança / privacidade das fotos

- As fotos **não são públicas**. Servidas por `GET /separation/photos/{filename}`,
  **autenticada e restrita a `role` admin ou separacao**. (Não há mais StaticFiles
  público para `separation-photos`.)
- `<img>` não envia header de auth → o front busca via `fetch` com token e usa um
  object URL (`api.getSeparationPhotoObjectUrl`).
- Upload valida **magic bytes** (assinatura JPG/PNG/WEBP), não só extensão/content-type.

## Roteiro de teste manual

**OFF (regressão — obrigatório):**
- `ENABLE_SEP_CONFERENCIA` ausente/false. Abrir Separação: abas e fluxo idênticos ao
  legado; sem aba "Conferência"; sem campos de foto. Finalizar separação → "Separado"
  com push ao Tiny como antes.

**SOFT:**
- `ENABLE_SEP_CONFERENCIA=true` + `VITE_SEP_CONFERENCIA_MODE=soft`.
- Iniciar separação → "Enviar para conferência" (sem foto deve passar). Pedido aparece
  na aba "Conferência" (interno permanece "Preparando Envio", sem push).
- Abrir conferência → anexar foto (câmera no Android via `capture`) → "Finalizar
  conferência" → status "Separado" + push ao Tiny + `checked_at` gravado.

**STRICT:**
- `VITE_SEP_CONFERENCIA_MODE=strict`. Tentar enviar para conferência **sem** foto da
  separação → bloqueado. Com foto → segue. Finalização exige volume total ≥ 1.

**Segurança:**
- `GET /separation/photos/<arquivo>` sem token → 401; com token de `vendedor` → 403;
  com `separacao`/`admin` → 200.
- Upload com `ENABLE_SEP_CONFERENCIA=false` → 403.
- Upload de arquivo `.jpg` cujo conteúdo não é imagem (assinatura inválida) → 400.
- PATCH com campos de conferência por usuário sem papel admin/separacao → campos ignorados.

## Limitações conhecidas (baixa severidade)

Levantadas em revisão; não bloqueiam o piloto, mas ficam registradas:

- **iOS/HEIC:** a captura nativa do iPhone costuma gerar HEIC, que o navegador não
  decodifica para `<canvas>`; o arquivo original é enviado e o backend rejeita
  (400, "Envie uma imagem JPG/PNG/WEBP"). **A captura por câmera é suportada com
  segurança no Android.** No iOS, usar foto da galeria em JPG. (Aceitar HEIC exigiria
  conversão + sniff do brand ISO-BMFF.)
- **Remover foto não persiste:** o botão "Remover" limpa o rascunho, mas o envio só
  manda a foto quando há valor (`...(photo ? {url} : {})`); ao reabrir, a foto antiga
  reaparece. Para persistir a remoção é preciso enviar o campo vazio explicitamente.
- **Isolamento por empresa:** a foto é restrita por papel (admin/separacao), mas **não
  por empresa** — não há `company_key` ligado ao arquivo. Um usuário privilegiado de um
  tenant que adivinhe o nome (improvável: `token_hex(6)` aleatório) leria foto de outro
  tenant. Endurecer = subpasta/lookup por `company_key` validado no GET.
- **Desync do overlay:** se o sync do Tiny avançar `internal_status` enquanto
  `awaiting_conference=true`, o pedido sai da aba "Conferência" sem `finalizeConference`.
  Não há perda de dado (aparece em Separado/Entregue). Mitigação: limpar
  `awaiting_conference` no servidor ao avançar de "Preparando Envio", ou exibir
  "Conferência" sempre que `awaiting_conference` for true.
