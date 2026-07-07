function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBRL(n) {
  const v = Number(n || 0);
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function safeJsonParse(raw, fallback) {
  // O backend (GET /quotes/{id}) já devolve client_snapshot/payload/totals como
  // objetos JSON (parseados em _quote_row_public). Só aplicamos JSON.parse
  // quando o valor ainda vier como string; caso contrário, JSON.parse(objeto)
  // lançaria exceção e o cliente/condição sairiam vazios no PDF.
  if (raw && typeof raw === "object") return raw;
  try {
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function formatDate(value) {
  if (!value) return "";
  const s = String(value).trim();

  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const [y, m, d] = s.split("-");
    return `${d}/${m}/${y}`;
  }

  try {
    const dt = new Date(s);
    if (Number.isNaN(dt.getTime())) return s;
    const dd = String(dt.getDate()).padStart(2, "0");
    const mm = String(dt.getMonth() + 1).padStart(2, "0");
    const yy = dt.getFullYear();
    return `${dd}/${mm}/${yy}`;
  } catch {
    return s;
  }
}

function formatDateTime(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return String(value);
  }
}

function getInstallments(quote) {
  const payload = safeJsonParse(quote?.payload, {});
  const installments = Array.isArray(payload?.payment_installments)
    ? payload.payment_installments
    : [];

  return installments.map((it, idx) => ({
    n: it?.n ?? idx + 1,
    due_date: it?.due_date || "",
    amount: Number(it?.amount || 0),
  }));
}

export function buildQuotePrintableHTML({ quote, items }) {
  if (!quote) {
    throw new Error("Dados do orçamento não encontrados para impressão.");
  }

  const client = safeJsonParse(quote?.client_snapshot, {});
  const totals = safeJsonParse(quote?.totals, {});
  const payload = safeJsonParse(quote?.payload, {});
  const installments = getInstallments(quote);

  const totalNet = Number(totals?.net || quote?.total_net || 0);
  const created = quote?.created_at ? formatDateTime(quote.created_at) : "";
  const num = quote?.quote_number ?? "";
  const envio = quote?.shipping_method_name || "";
  const frete = quote?.freight_method_name || "";
  const pagamento = quote?.payment_method_name || quote?.payment_method_code || "";
  const vendedor = quote?.seller_name || payload?.seller_name || "";
  const condicao = payload?.payment_condition || quote?.payment_condition || "";
  const prazo = quote?.payment_due_date || payload?.payment_due_date || "";

  // Neste ERP, "nome" do cliente é a razão social; "fantasia" é o nome fantasia.
  const clientRazao =
    client?.razao_social ||
    client?.razaoSocial ||
    client?.nome ||
    client?.name ||
    quote?.client_name ||
    "";
  const clientFantasia =
    client?.fantasia || client?.nome_fantasia || client?.nomeFantasia || "";
  const clientDoc =
    client?.cpf_cnpj ||
    client?.cpfCnpj ||
    client?.cpf ||
    client?.cnpj ||
    client?.documento ||
    quote?.client_document ||
    "";

  const rows = (items || [])
    .map(
      (it) => `
      <tr>
        <td style="padding:8px;border-bottom:1px solid #e5e7eb;">${it.line ?? ""}</td>
        <td style="padding:8px;border-bottom:1px solid #e5e7eb;">
          <div style="font-weight:700;">${escapeHtml(it.name_snapshot || "")}</div>
          <div style="color:#6b7280;font-size:12px;">${escapeHtml(it.sku_snapshot || "")}</div>
        </td>
        <td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:right;">${Number(it.qty || 0)}</td>
        <td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:right;">${escapeHtml(formatBRL(it.unit_price_disc || 0))}</td>
        <td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:right;">${escapeHtml(formatBRL(it.line_total || 0))}</td>
      </tr>
    `
    )
    .join("");

  const installmentsRows = installments.length
    ? installments
        .map(
          (p) => `
          <tr>
            <td style="padding:8px;border-bottom:1px solid #e5e7eb;">${escapeHtml(String(p.n))}</td>
            <td style="padding:8px;border-bottom:1px solid #e5e7eb;">${escapeHtml(formatDate(p.due_date))}</td>
            <td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:right;">${escapeHtml(formatBRL(p.amount))}</td>
          </tr>
        `
        )
        .join("")
    : `
      <tr>
        <td colspan="3" style="padding:10px;color:#6b7280;">Sem parcelas cadastradas.</td>
      </tr>
    `;

  const notesBlock = quote?.notes
    ? `<div style="margin-top:12px;">
         <div style="font-weight:800;margin-bottom:6px;">Observações</div>
         <div style="white-space:pre-wrap;border:1px solid #e5e7eb;border-radius:10px;padding:10px;">
           ${escapeHtml(quote.notes)}
         </div>
       </div>`
    : "";

  return `
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Pré-venda ${escapeHtml(String(num))}</title>
<style>
  @page { size: auto; margin: 14mm; }
  body { font-family: Arial, sans-serif; margin: 0; color:#111827; }
  .page { padding: 6px; }
  .top { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
  .h1 { font-size: 18px; font-weight: 800; margin: 0; }
  .muted { color:#6b7280; font-size:12px; line-height:1.55; }
  .box { border:1px solid #e5e7eb; border-radius:12px; padding:12px; }
  table { width:100%; border-collapse: collapse; margin-top: 12px; }
  th { text-align:left; font-size:12px; color:#374151; padding:8px; border-bottom:1px solid #e5e7eb; background:#fafafa; }
  td { font-size: 13px; }
  .right { text-align:right; }
  .section-title { font-weight:800; margin-bottom:6px; }
  .two-cols { display:grid; grid-template-columns: 1fr 320px; gap:14px; }
  @media print {
    .page { padding: 0; }
  }
</style>
</head>
<body>
  <div class="page">
    <div class="top">
      <div>
        <h1 class="h1">Pré-venda Nº ${escapeHtml(String(num))}</h1>
        <div class="muted">Data: ${escapeHtml(created || "-")}</div>
        <div class="muted"><b>Vendedor:</b> ${escapeHtml(vendedor || "-")}</div>
        <div class="muted"><b>Envio:</b> ${escapeHtml(envio || "-")}</div>
        <div class="muted"><b>Frete:</b> ${escapeHtml(frete || "-")}</div>
        <div class="muted"><b>Pagamento:</b> ${escapeHtml(pagamento || "-")}</div>
        <div class="muted"><b>Condição:</b> ${escapeHtml(condicao || "-")}</div>
        <div class="muted"><b>Prazo:</b> ${escapeHtml(prazo ? formatDate(prazo) : "-")}</div>
      </div>
      <div class="box" style="min-width:360px;">
        <div class="section-title">Cliente</div>
        <div style="font-weight:700;">${escapeHtml(clientRazao || "-")}</div>
        ${
          clientFantasia && clientFantasia !== clientRazao
            ? `<div class="muted"><b>Nome fantasia:</b> ${escapeHtml(clientFantasia)}</div>`
            : ""
        }
        <div class="muted"><b>CPF/CNPJ:</b> ${escapeHtml(clientDoc || "-")}</div>
      </div>
    </div>

    <div class="box" style="margin-top:14px;">
      <div class="section-title">Itens</div>
      <table>
        <thead>
          <tr>
            <th style="width:6%;">Linha</th>
            <th style="width:54%;">Produto</th>
            <th class="right" style="width:10%;">Qtd</th>
            <th class="right" style="width:15%;">Preço venda</th>
            <th class="right" style="width:15%;">Total</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>

      ${notesBlock}
    </div>

    <div class="two-cols" style="margin-top:14px;">
      <div class="box">
        <div class="section-title">Parcelas</div>
        <table style="margin-top:0;">
          <thead>
            <tr>
              <th style="width:20%;">Parcela</th>
              <th style="width:45%;">Vencimento</th>
              <th class="right" style="width:35%;">Valor</th>
            </tr>
          </thead>
          <tbody>${installmentsRows}</tbody>
        </table>
      </div>

      <div class="box" style="align-self:start;">
        <div style="display:flex; justify-content:space-between; font-weight:900; font-size:16px;">
          <span>Total</span><span>${escapeHtml(formatBRL(totalNet))}</span>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
  `;
}

export function openQuotePrintWindow(data) {
  const html = buildQuotePrintableHTML(data || {});

  const win = window.open("", "_blank");
  if (!win) {
    throw new Error("Não foi possível abrir a janela de impressão.");
  }

  win.document.open();
  win.document.write(html);
  win.document.close();

  setTimeout(() => {
    try {
      win.focus();
      win.print();
    } catch {}
  }, 250);

  return win;
}
