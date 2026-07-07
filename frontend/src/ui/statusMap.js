// Mapa central de status -> tom visual do StatusPill.
// Fica em arquivo separado do componente para preservar o React Fast Refresh
// (o .jsx exporta somente o componente).
//
// Validado na Fase 2 contra os status REAIS renderizados no fluxo:
//   - Comercial (QuotesModal.jsx / SavedQuotes.jsx / Home.jsx):
//       Orçamento, Em Aberto, Aguardando Aprovação, Aprovado,
//       Preparando Envio, Pronto para Envio, Faturado, Cancelado, Pedido.
//   - Separação (Separation.jsx / detalhe do pedido em SavedQuotes.jsx):
//       A separar, Separando, Separado, Entregue, Cancelado.
//   - Compras (Compras.jsx):
//       Em aberto, Aprovado, Em andamento, Parcialmente recebido,
//       Recebido, Cancelado.
//
// norm() apenas faz trim()+toLowerCase() (NÃO remove acento), por isso cada
// rótulo com acento tem também a variante sem acento. Tons disponíveis no
// StatusPill: info | warning | success | danger | neutral | accent.
//
// Regra de cor: estados ADJACENTES no fluxo (ou de significado próximo) nunca
// compartilham tom. Como o pipeline comercial tem 7 estados e o StatusPill só
// oferece 6 tons, a única reutilização é "success" entre Aprovado e Faturado —
// dois marcos positivos, distantes no fluxo e nunca confundíveis pelo texto.
export const TONE_BY_STATUS = {
  // ---- Inicial / rascunho / pedido criado ----
  "orcamento": "neutral",
  "orçamento": "neutral",
  "rascunho": "neutral",
  "draft": "neutral",
  "pedido": "neutral",
  "pedido criado": "neutral",
  "ordered": "neutral",

  // ---- Pendente / aguardando ação ----
  "aberto": "warning",
  "em aberto": "warning",
  "open": "warning",
  "aguardando aprovacao": "info",
  "aguardando aprovação": "info",

  // ---- Aprovado ----
  "aprovado": "success",
  "approved": "success",

  // ---- Preparo / envio (comercial) ----
  "preparando envio": "info",
  "preparing": "info",
  "pronto para envio": "accent",
  "ready": "accent",

  // ---- Faturado (marco final positivo) ----
  "faturado": "success",
  "invoiced": "success",

  // ---- Cancelado ----
  "cancelado": "danger",
  "cancelled": "danger",

  // ---- Separação (Separation.jsx) ----
  "a separar": "warning",
  "separando": "info",
  "em separacao": "info",
  "em separação": "info",
  "separado": "success",
  "entregue": "accent",
  "conferido": "neutral",

  // ---- Compras (Compras.jsx) ----
  "em andamento": "info",
  "em_andamento": "info",
  "parcialmente recebido": "warning",
  "parcialmente_recebido": "warning",
  "parcial": "warning",
  "recebido": "success",
};

function norm(s) { return String(s || "").trim().toLowerCase(); }

export function statusTone(status) {
  return TONE_BY_STATUS[norm(status)] || "neutral";
}
