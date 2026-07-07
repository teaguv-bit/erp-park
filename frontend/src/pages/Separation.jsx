import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { withGlobalLoading } from "../utils/globalLoading";
import { PageHeader, Card, Table, StatusPill, Button, EmptyState, Spinner, Skeleton } from "../ui";

const STATUS_OPTIONS = ["A separar", "Separando", "Separado", "Entregue", "Cancelado"];
const SEPARATION_COMPANIES = ["parton", "park"];

function normalizeCompanyKey(value) {
  const key = String(value || "").trim().toLowerCase();
  return key === "park" ? "park" : "parton";
}

function getOrderCompany(item) {
  return normalizeCompanyKey(item?.company_key || item?.company || item?.companyKey);
}

function companyLabel(company) {
  return normalizeCompanyKey(company) === "park" ? "INFORMÁTICA" : "SUPRIMENTOS";
}

function readSeparationCompanyFromUrl() {
  if (typeof window === "undefined") return "";
  const raw = new URLSearchParams(window.location.search).get("sep_company");
  const key = String(raw || "").trim().toLowerCase();
  return key === "park" || key === "parton" ? key : "";
}

function getInitialSeparationCompany(fallbackCompany) {
  return readSeparationCompanyFromUrl() || normalizeCompanyKey(fallbackCompany || "parton");
}

function writeSeparationCompanyUrl(company, { replace = false } = {}) {
  if (typeof window === "undefined") return;
  const nextCompany = normalizeCompanyKey(company);
  const url = new URL(window.location.href);
  url.pathname = "/separation";
  url.searchParams.set("sep_company", nextCompany);

  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  if (replace) {
    window.history.replaceState(window.history.state, "", nextUrl);
  } else {
    window.history.pushState(window.history.state, "", nextUrl);
  }
}

function sameCompanyOrder(item, orderId, company) {
  return String(item?.tiny_order_id || "") === String(orderId || "") && getOrderCompany(item) === normalizeCompanyKey(company);
}

const styles = {
  page: { display: "flex", flexDirection: "column", gap: 18 },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 16,
    flexWrap: "wrap",
    padding: "16px",
    border: "1px solid var(--border)",
    borderRadius: 16,
    background: "var(--card)",
    boxShadow: "0 12px 26px rgba(0,0,0,0.08)",
  },
  titleWrap: { display: "flex", flexDirection: "column", gap: 6, minWidth: 0 },
  title: { fontSize: 28, fontWeight: 900, letterSpacing: "-0.04em", color: "var(--text)" },
  subtitle: { color: "var(--muted)", fontSize: 13, lineHeight: 1.5, maxWidth: 760 },

  card: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 16,
    padding: 16,
    boxShadow: "0 12px 26px rgba(0,0,0,0.08)",
  },

  filters: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1.5fr) 220px auto",
    gap: 14,
    alignItems: "end",
  },

  grid2: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 16,
  },

  grid4: {
    display: "grid",
    gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
    gap: 12,
  },

  sectionTitle: {
    fontSize: 11,
    fontWeight: 900,
    color: "var(--muted)",
    marginBottom: 10,
    textTransform: "uppercase",
    letterSpacing: ".12em",
  },

  label: {
    fontSize: 12,
    fontWeight: 800,
    color: "var(--muted)",
    marginBottom: 6,
  },

  input: {
    width: "100%",
    minHeight: 42,
    borderRadius: 12,
    border: "1px solid var(--border)",
    padding: "0 12px",
    background: "var(--panel)",
    color: "var(--text)",
    boxSizing: "border-box",
    transition: "border-color .15s ease, background .15s ease, box-shadow .15s ease",
  },

  textarea: {
    width: "100%",
    minHeight: 110,
    borderRadius: 12,
    border: "1px solid var(--border)",
    padding: 12,
    background: "var(--panel)",
    color: "var(--text)",
    resize: "vertical",
    fontFamily: "inherit",
    fontSize: 14,
    boxSizing: "border-box",
    transition: "border-color .15s ease, background .15s ease, box-shadow .15s ease",
  },

  button: {
    minHeight: 38,
    borderRadius: 12,
    border: "1px solid rgba(148,163,184,0.22)",
    padding: "0 14px",
    background: "var(--panel)",
    color: "var(--text)",
    cursor: "pointer",
    fontWeight: 800,
    boxShadow: "0 8px 18px rgba(0,0,0,0.10)",
    transition: "background .15s ease, border-color .15s ease, opacity .15s ease, transform .06s ease, box-shadow .15s ease",
  },

  primaryButton: {
    background: "linear-gradient(180deg, var(--primary), var(--primary-strong))",
    color: "#fff",
    border: "1px solid rgba(147,197,253,0.58)",
    boxShadow: "0 12px 24px rgba(47,109,246,0.20)",
  },

  subtleButton: {
    background: "var(--panel)",
  },

  companyTabsWrap: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
  },

  companyTab: {
    minHeight: 40,
    borderRadius: 999,
    padding: "0 16px",
    border: "1px solid var(--border)",
    background: "var(--panel)",
    color: "var(--text)",
    cursor: "pointer",
    fontWeight: 950,
    boxShadow: "0 8px 18px rgba(0,0,0,0.08)",
    transition: "background .15s ease, border-color .15s ease, box-shadow .15s ease, transform .06s ease",
  },

  companyTabParton: {
    borderColor: "rgba(245,158,11,.42)",
    boxShadow: "inset 0 -3px 0 rgba(245,158,11,.32), 0 8px 18px rgba(0,0,0,0.08)",
  },

  companyTabPark: {
    borderColor: "rgba(124,58,237,.42)",
    boxShadow: "inset 0 -3px 0 rgba(124,58,237,.32), 0 8px 18px rgba(0,0,0,0.08)",
  },

  companyTabActiveParton: {
    background: "linear-gradient(180deg, rgba(245,158,11,.24), rgba(245,158,11,.13))",
    borderColor: "rgba(245,158,11,.86)",
    boxShadow: "inset 0 -4px 0 rgba(245,158,11,.88), 0 14px 26px rgba(245,158,11,.18)",
  },

  companyTabActivePark: {
    background: "linear-gradient(180deg, rgba(124,58,237,.24), rgba(79,70,229,.13))",
    borderColor: "rgba(124,58,237,.86)",
    boxShadow: "inset 0 -4px 0 rgba(124,58,237,.88), 0 14px 26px rgba(124,58,237,.18)",
  },

  tableWrap: {
    overflowX: "auto",
    border: "1px solid var(--border)",
    borderRadius: 14,
    background: "var(--card)",
    boxShadow: "0 10px 22px rgba(0,0,0,0.06)",
  },
  table: { width: "100%", borderCollapse: "separate", borderSpacing: 0 },

  th: {
    textAlign: "left",
    fontSize: 11,
    color: "var(--muted)",
    padding: "12px 10px",
    borderBottom: "1px solid rgba(148,163,184,0.18)",
    whiteSpace: "nowrap",
    textTransform: "uppercase",
    letterSpacing: ".08em",
    background: "var(--panel)",
    fontWeight: 900,
  },

  td: {
    padding: "12px 10px",
    borderBottom: "1px solid rgba(148,163,184,0.10)",
    verticalAlign: "top",
    fontSize: 13,
    color: "var(--text)",
  },

  cancelledRow: {
    background: "rgba(220,38,38,0.10)",
    boxShadow: "inset 4px 0 0 rgba(220,38,38,0.95)",
  },

  cancelledText: {
    color: "#ef4444",
    fontWeight: 900,
  },

  cancelledBadge: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    border: "1px solid rgba(220,38,38,.70)",
    background: "rgba(220,38,38,.14)",
    color: "#ef4444",
    padding: "4px 8px",
    fontSize: 11,
    fontWeight: 950,
    textTransform: "uppercase",
    letterSpacing: ".04em",
  },

  disabledAction: {
    opacity: 0.45,
    cursor: "not-allowed",
    filter: "grayscale(0.35)",
  },

  badge: {
    display: "inline-flex",
    alignItems: "center",
    padding: "5px 10px",
    borderRadius: 999,
    background: "rgba(79,140,255,.12)",
    border: "1px solid rgba(79,140,255,.22)",
    fontSize: 12,
    fontWeight: 900,
  },

  companyBadge: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "fit-content",
    padding: "4px 8px",
    borderRadius: 999,
    fontSize: 10,
    fontWeight: 950,
    letterSpacing: ".04em",
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  },

  companyBadgeParton: {
    background: "rgba(245,158,11,.14)",
    border: "1px solid rgba(245,158,11,.30)",
    color: "#f59e0b",
  },

  companyBadgePark: {
    background: "rgba(124,58,237,.14)",
    border: "1px solid rgba(124,58,237,.30)",
    color: "#a78bfa",
  },

  dangerText: { color: "var(--danger)", fontSize: 13 },
  muted: { color: "var(--muted)" },
  empty: { padding: 20, textAlign: "center", color: "var(--muted)" },

  kvWrap: {
    display: "grid",
    gridTemplateColumns: "1fr",
    gap: 10,
  },

  kvRow: {
    display: "grid",
    gridTemplateColumns: "140px 1fr",
    gap: 10,
    alignItems: "start",
  },

  kvKey: {
    color: "var(--muted)",
    fontSize: 12,
    fontWeight: 700,
  },

  kvValue: {
    color: "var(--text)",
    fontSize: 14,
    wordBreak: "break-word",
  },

  detailHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    flexWrap: "wrap",
    marginBottom: 16,
  },

  detailTitle: {
    fontSize: 24,
    fontWeight: 900,
    color: "var(--text)",
    letterSpacing: "-0.03em",
  },

  detailSub: {
    color: "var(--muted)",
    fontSize: 13,
    marginTop: 4,
  },

  statsCard: {
    background: "var(--panel)",
    border: "1px solid var(--border)",
    borderRadius: 14,
    padding: "12px 14px",
    display: "flex",
    gap: 18,
    boxShadow: "0 8px 18px rgba(0,0,0,0.06)",
  },

  toolbar: {
    display: "flex",
    gap: 8,
    alignItems: "center",
    flexWrap: "wrap",
  },

  modalOverlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(2,6,23,0.74)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
    zIndex: 1000,
  },

  modalPanel: {
    width: "min(1280px, 96vw)",
    maxHeight: "92vh",
    overflowY: "auto",
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 22,
    padding: 18,
    boxShadow: "0 24px 60px rgba(0,0,0,0.30)",
  },

  modalHeaderSticky: {
    position: "sticky",
    top: -16,
    zIndex: 5,
    background: "var(--card)",
    paddingTop: 16,
    paddingBottom: 12,
    marginBottom: 16,
    borderBottom: "1px solid var(--border)",
  },

  topTabsWrap: {
    display: "flex",
    gap: 8,
    flexWrap: "wrap",
    alignItems: "flex-end",
    borderBottom: "1px solid var(--border)",
    paddingBottom: 12,
  },

  topTab: {
    background: "transparent",
    border: "1px solid transparent",
    borderRadius: 10,
    cursor: "pointer",
    padding: "9px 12px",
    minWidth: 96,
    textAlign: "left",
    color: "var(--muted)",
    boxShadow: "none",
  },

  topTabActive: {
    color: "var(--text)",
    background: "rgba(79,140,255,.08)",
    border: "1px solid var(--border)",
  },

  topTabLabel: {
    fontSize: 14,
    fontWeight: 900,
    lineHeight: 1.2,
  },

  topTabCount: {
    fontSize: 12,
    opacity: 0.8,
    marginTop: 4,
    fontWeight: 700,
  },

  subTabsWrap: {
    display: "flex",
    gap: 10,
    flexWrap: "wrap",
  },

  subTab: {
    border: "1px solid rgba(148,163,184,0.18)",
    background: "var(--panel)",
    color: "var(--text)",
    borderRadius: 999,
    padding: "8px 12px",
    cursor: "pointer",
    fontWeight: 800,
    fontSize: 13,
  },

  subTabActive: {
    background: "rgba(79,140,255,.08)",
    border: "1px solid var(--border)",
    fontWeight: 900,
  },
};

function safeJsonParse(value, fallback = {}) {
  if (!value) return fallback;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function money(v) {
  const n = Number(v || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function numberOrNull(value) {
  if (value === undefined || value === null || String(value).trim() === "") return null;
  const n = Number(String(value).replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function formatDecimal(value, suffix = "") {
  if (value === undefined || value === null || value === "") return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${n.toLocaleString("pt-BR", { maximumFractionDigits: 3 })}${suffix}`;
}

function formatDateTime(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("pt-BR");
}

function formatDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString("pt-BR");
}

function formatTime(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function pick(obj, ...keys) {
  for (const k of keys) {
    const v = obj?.[k];
    if (v !== undefined && v !== null && String(v).trim() !== "") return String(v).trim();
  }
  return "";
}

function buildClientAddress(client) {
  const endereco = pick(client, "endereco", "address");
  const numero = pick(client, "numero", "number");
  const complemento = pick(client, "complemento", "address2");
  const bairro = pick(client, "bairro", "district");
  const cidade = pick(client, "cidade", "city");
  const uf = pick(client, "uf", "state");
  const cep = pick(client, "cep", "zipcode");

  const linha1 = [endereco, numero].filter(Boolean).join(", ");
  const linha2 = [complemento, bairro].filter(Boolean).join(" -¢ ");
  const linha3 = [cidade, uf, cep].filter(Boolean).join(" - ");

  return [linha1, linha2, linha3].filter(Boolean).join("\n");
}

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getProductMeta(item) {
  const raw = safeJsonParse(item?.raw, {});
  const productRaw = raw?.product_raw || raw?.produto || raw?.product || raw || {};
  const productSnapshot = safeJsonParse(item?.product_snapshot, item?.product_snapshot || {});

  return {
    brand:
      pick(productRaw, "marca", "brand") ||
      pick(productSnapshot, "marca", "brand") ||
      pick(item, "marca", "brand", "marca_snapshot", "brand_snapshot") ||
      "-",
    category:
      pick(productRaw, "categoria", "category", "nome_categoria") ||
      pick(productSnapshot, "categoria", "category", "nome_categoria") ||
      pick(item, "categoria", "category", "categoria_snapshot", "category_snapshot") ||
      "-",
    location:
      pick(productRaw, "localizacao", "deposito", "warehouse_location", "local") ||
      pick(productSnapshot, "localizacao", "deposito", "warehouse_location", "local") ||
      pick(item, "localizacao", "location", "localizacao_snapshot", "location_snapshot") ||
      "-",
  };
}

function buildSeparationPrintHtml({ order, items, client }) {
  const payload = safeJsonParse(order?.payload, {});
  const invoiceProfile = String(payload?.invoice_profile || "A").toUpperCase() === "B" ? "B" : "A";
  const approvedAt = order?.approved_at || order?.approvedAt || payload?.approved_at || payload?.approvedAt || null;

  const clienteNome = pick(client, "nome", "name") || "Consumidor Final";
  const documento = pick(client, "cpf_cnpj", "cpfCnpj", "documento") || "-";
  const endereco = buildClientAddress(client) || "-";
  const vendedor = order?.seller_name || "-";
  const envio = order?.shipping_method_name || "-";
  const frete = order?.freight_method_name || "-";
  const pedidoTiny = order?.tiny_order_number || order?.tiny_order_id || "-";
  const prePedido = order?.quote_number || "-";
  const data = formatDate(order?.created_at);
  const approvedTime = formatTime(approvedAt);
  const status = order?.separation_status || "A separar";
  const responsavel = order?.assigned_to || "-";
  const observacoes = order?.separation_notes || order?.notes || payload?.notes || payload?.observacoes || "";
  const observacoesInternas =
    order?.internal_notes ||
    order?.internalNotes ||
    order?.observacoes_internas ||
    payload?.internal_notes ||
    payload?.internalNotes ||
    payload?.observacao_interna ||
    payload?.observacoes_internas ||
    "";
  const caixaPeso = formatDecimal(order?.packaging_weight_kg, " kg");
  const caixaAltura = formatDecimal(order?.packaging_height_cm, " cm");
  const caixaLargura = formatDecimal(order?.packaging_width_cm, " cm");
  const caixaComprimento = formatDecimal(order?.packaging_length_cm, " cm");
  const caixaVolumes = order?.packaging_volumes ?? order?.packaging_boxes ?? "-";

  const totalQty = (items || []).reduce((acc, item) => acc + Number(item.qty || 0), 0);

  const rows = (items || [])
    .map((item, idx) => {
      const sku = item?.sku_snapshot || "-";
      const name = item?.name_snapshot || "-";
      const qty = Number(item?.qty || 0);
      const meta = getProductMeta(item);

      return `
        <tr>
          <td class="td center item-row">${idx + 1}</td>
          <td class="td item-row">
            <div style="font-weight:900;font-size:14px;line-height:1.28;text-transform:uppercase;">${escapeHtml(name)}</div>
            <div style="color:#374151;font-size:10px;margin-top:4px;font-weight:700;">
              SKU: ${escapeHtml(sku)}
            </div>
            <div style="color:#6b7280;font-size:10px;margin-top:2px;">
              Categoria: ${escapeHtml(meta.category)}
            </div>
          </td>
          <td class="td item-row" style="font-weight:900;font-size:22px;text-transform:uppercase;line-height:1.05;">${escapeHtml(meta.brand)}</td>
          <td class="td item-row" style="font-size:12px;font-weight:700;">${escapeHtml(meta.location)}</td>
          <td class="td center item-row" style="font-weight:900;font-size:15px;white-space:nowrap;">${qty}</td>
          <td class="td fill item-row" style="height:52px;"></td>
          <td class="td fill item-row" style="height:52px;"></td>
        </tr>
      `;
    })
    .join("");

  const notesBlock = observacoes || observacoesInternas
    ? `
      <div class="notes-grid">
        <div class="box">
          <div class="box-title">Observações</div>
          <div class="notes">${escapeHtml(observacoes || "-")}</div>
        </div>
        <div class="box">
          <div class="box-title">Observação Interna</div>
          <div class="notes internal-notes">${escapeHtml(observacoesInternas || "-")}</div>
        </div>
      </div>
    `
    : "";

  return `
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Separação ${escapeHtml(String(pedidoTiny))}</title>
<style>
  @page { size: A4 portrait; margin: 8mm; }
  * { box-sizing: border-box; }
  body { font-family: Arial, sans-serif; color:#111827; margin:0; }
  .page { padding: 4px; }
  .top { display:flex; justify-content:space-between; gap:10px; margin-bottom:10px; align-items:flex-start; }
  .title { font-size: 20px; font-weight: 800; margin: 0 0 4px 0; }
  .muted { color:#6b7280; font-size:12px; line-height:1.5; }
  .box { border:1px solid #d1d5db; border-radius: 10px; padding: 8px 10px; margin-bottom: 8px; }
  .box-title { font-weight:800; margin-bottom:8px; font-size:15px; }
  .grid2 { display:grid; grid-template-columns: 1.1fr 0.9fr; gap: 10px; }
  .notes-grid { display:grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items:stretch; }
  .notes-grid .box { margin-bottom: 8px; }
  .internal-notes { font-weight:700; }
  .kv { display:grid; grid-template-columns: 95px 1fr; gap:6px; margin-bottom:4px; }
  .k { font-size:12px; color:#6b7280; font-weight:700; }
  .v { font-size:14px; font-weight:700; }
  .checks { display:flex; gap:18px; align-items:center; }
  .check { display:flex; gap:8px; align-items:center; font-size:13px; font-weight:800; }
  .square { width:16px; height:16px; border:1px solid #111827; display:inline-flex; align-items:center; justify-content:center; font-size:13px; font-weight:900; line-height:1; }
  table { width:100%; border-collapse: collapse; table-layout: fixed; }
  th { border:1px solid #d1d5db; background:#f9fafb; padding:8px 6px; font-size:12px; text-align:left; font-weight:800; }
  .td { border:1px solid #d1d5db; padding:9px 7px; font-size:12px; vertical-align:top; word-wrap: break-word; overflow-wrap: break-word; }
  .item-row { min-height: 46px; }
  .center { text-align:center; }
  .fill { height:52px; }
  .notes { white-space:pre-wrap; font-size:13px; min-height:50px; }
  .footer { display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-top:12px; }
  .sign { border-top:1px solid #111827; padding-top:6px; font-size:12px; text-align:center; margin-top:18px; }
  .totals { display:flex; justify-content:flex-end; margin-top:10px; font-size:13px; font-weight:800; }
</style>
</head>
<body>
  <div class="page">
    <div class="top">
      <div>
        <div class="title">Folha de Separação</div>
        <div class="muted">Gerado pelo sistema de pré-venda</div>
      </div>
      <div class="checks">
        <div class="check"><span class="square">${invoiceProfile === "A" ? "X" : ""}</span><span>A</span></div>
        <div class="check"><span class="square">${invoiceProfile === "B" ? "X" : ""}</span><span>B</span></div>
      </div>
    </div>

    <div class="grid2">
      <div class="box">
        <div class="box-title">Pedido</div>
        <div class="kv"><div class="k">Pré-pedido</div><div class="v" style="font-size:16px;font-weight:900;">${escapeHtml(String(prePedido))}</div></div>
        <div class="kv"><div class="k">Pedido Tiny</div><div class="v" style="font-size:18px;font-weight:900;">${escapeHtml(String(pedidoTiny))}</div></div>
        <div class="kv"><div class="k">Data</div><div class="v">${escapeHtml(String(data))}${approvedAt ? ` • ${escapeHtml(String(approvedTime))}` : ""}</div></div>
        <div class="kv"><div class="k">Status</div><div class="v">${escapeHtml(String(status))}</div></div>
        <div class="kv"><div class="k">Responsável</div><div class="v">${escapeHtml(String(responsavel))}</div></div>
      </div>

      <div class="box">
        <div class="box-title">Cliente / comercial</div>
        <div class="kv"><div class="k">Cliente</div><div class="v">${escapeHtml(clienteNome)}</div></div>
        <div class="kv"><div class="k">CNPJ/CPF</div><div class="v">${escapeHtml(documento)}</div></div>
        <div class="kv"><div class="k">Vendedor</div><div class="v">${escapeHtml(vendedor)}</div></div>
        <div class="kv"><div class="k">Envio</div><div class="v" style="font-size:18px;font-weight:900;line-height:1.1;">${escapeHtml(envio)}</div></div>
        <div class="kv"><div class="k">Frete</div><div class="v" style="font-size:18px;font-weight:900;line-height:1.1;">${escapeHtml(frete)}</div></div>
      </div>
    </div>

    <div class="box">
      <div class="box-title">Endereço</div>
      <div class="notes">${escapeHtml(endereco)}</div>
    </div>

    <div class="box">
      <div class="box-title">Dados da caixa / volume</div>
      <div class="grid2">
        <div>
          <div class="kv"><div class="k">Peso</div><div class="v">${escapeHtml(String(caixaPeso))}</div></div>
          <div class="kv"><div class="k">Volumes</div><div class="v">${escapeHtml(String(caixaVolumes))}</div></div>
        </div>
        <div>
          <div class="kv"><div class="k">Altura</div><div class="v">${escapeHtml(String(caixaAltura))}</div></div>
          <div class="kv"><div class="k">Largura</div><div class="v">${escapeHtml(String(caixaLargura))}</div></div>
          <div class="kv"><div class="k">Comprimento</div><div class="v">${escapeHtml(String(caixaComprimento))}</div></div>
        </div>
      </div>
    </div>

    <div class="box">
      <div class="box-title">Itens</div>
      <table>
        <thead>
          <tr>
            <th style="width:4%;">#</th>
            <th style="width:42%;">Produto</th>
            <th style="width:13%;">Marca</th>
            <th style="width:11%;">Localização</th>
            <th style="width:8%;" class="center">Qtd</th>
            <th style="width:11%;" class="center">Separação</th>
            <th style="width:11%;" class="center">Conferência</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
      <div class="totals">Quantidade total: ${totalQty}</div>
    </div>

    ${notesBlock}

    <div class="footer">
      <div class="sign">Separação</div>
      <div class="sign">Conferência</div>
    </div>
  </div>
</body>
</html>
  `;
}


function buildSeparationLabelPrintHtml({ order, client }) {
  const payload = safeJsonParse(order?.payload, {});

  const clienteNome =
    pick(client, "nome", "name") ||
    order?.client_name ||
    payload?.cliente?.nome ||
    payload?.client?.name ||
    "Consumidor Final";

  const endereco =
    buildClientAddress(client) ||
    order?.client_address ||
    payload?.client_address ||
    payload?.endereco ||
    "-";

  const pedidoTiny = order?.tiny_order_number || order?.tiny_order_id || "-";
  const prePedido = order?.quote_number || "-";
  const envio = order?.shipping_method_name || "-";
  const frete = order?.freight_method_name || "-";
  const vendedor = order?.seller_name || "-";
  const totalVolumes = Math.max(1, Math.floor(Number(order?.packaging_volumes || 0) || 0));
  const separador = order?.assigned_to || order?.operator_name || "—";
  const labelsHtml = Array.from({ length: totalVolumes }, (_, idx) => {
    const volumeNumber = idx + 1;
    return `
  <div class="label">
    <div class="tinyBox">
      <div class="tinyLabel">Pedido Tiny</div>
      <div class="tinyNumber">${escapeHtml(String(pedidoTiny))}</div>
    </div>

    <div class="section">
      <div class="sectionTitle">Cliente</div>
      <div class="client">${escapeHtml(clienteNome)}</div>
    </div>

    <div class="section">
      <div class="sectionTitle">Endereço</div>
      <div class="address">${escapeHtml(endereco)}</div>
    </div>

    <div class="metaGrid">
      <div class="meta">
        <div class="metaTitle">Envio</div>
        <div class="metaValue">${escapeHtml(envio)}</div>
      </div>
      <div class="meta">
        <div class="metaTitle">Frete</div>
        <div class="metaValue">${escapeHtml(frete)}</div>
      </div>
    </div>

    <div class="metaGrid">
      <div class="meta">
        <div class="metaTitle">Pré-pedido</div>
        <div class="metaValue">${escapeHtml(String(prePedido))}</div>
      </div>
      <div class="meta">
        <div class="metaTitle">Vendedor</div>
        <div class="metaValue">${escapeHtml(vendedor)}</div>
      </div>
    </div>

    <div class="metaGrid">
      <div class="meta">
        <div class="metaTitle">Separador</div>
        <div class="metaValue">${escapeHtml(separador)}</div>
      </div>
      <div class="meta">
        <div class="metaTitle">Volume</div>
        <div class="metaValue volumeValue">Volume ${volumeNumber}/${totalVolumes}</div>
      </div>
    </div>

    <div class="footer">
      <div>Conferência: __________</div>
      <div>Separador: ${escapeHtml(separador)}</div>
    </div>
  </div>`;
  }).join("");

  return `
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Etiqueta ${escapeHtml(String(pedidoTiny))}</title>
<style>
  @page { size: 100mm 150mm; margin: 0; }
  * { box-sizing: border-box; }
  html, body {
    width: 100mm;
    min-height: 150mm;
  }
  body {
    margin: 0;
    padding: 3mm 0 0 0;
    font-family: Arial, Helvetica, sans-serif;
    color: #000;
    background: #fff;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: flex-start;
  }
  .label {
    width: 91mm;
    height: 142mm;
    border: 2px solid #000;
    padding: 3.8mm;
    display: flex;
    flex-direction: column;
    gap: 2.8mm;
    overflow: hidden;
    page-break-after: always;
    break-after: page;
  }
  .label:last-child {
    page-break-after: auto;
    break-after: auto;
  }
  .tinyBox {
    border: 2px solid #000;
    padding: 3mm;
    text-align: center;
  }
  .tinyLabel {
    font-size: 7.0pt;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .tinyNumber {
    font-size: 23pt;
    font-weight: 900;
    line-height: 1;
    margin-top: 2mm;
  }
  .section {
    border-top: 1px solid #000;
    padding-top: 3mm;
  }
  .sectionTitle {
    font-size: 10pt;
    font-weight: 900;
    text-transform: uppercase;
    margin-bottom: 1.5mm;
  }
  .client {
    font-size: 12.8pt;
    font-weight: 900;
    line-height: 1.00;
    text-transform: uppercase;
    overflow-wrap: anywhere;
    word-break: normal;
  }
  .address {
    font-size: 11.8pt;
    font-weight: 900;
    line-height: 1.00;
    text-transform: uppercase;
    white-space: pre-line;
    overflow-wrap: anywhere;
    word-break: normal;
  }
    .metaGrid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.8mm;
  }
  .meta {
    border: 1px solid #000;
    padding: 1.2mm;
    min-height: 12.8mm;
  }
  .metaTitle {
    font-size: 6.2pt;
    font-weight: 900;
    text-transform: uppercase;
    margin-bottom: 1mm;
  }
    .metaValue {
    font-size: 5.6pt;
    font-weight: 900;
    line-height: 0.9;
    text-transform: uppercase;
    overflow-wrap: anywhere;
    word-break: break-word;
    letter-spacing: -0.02em;
  }
  .volumeValue {
    font-size: 12pt;
    line-height: 1;
  }
  .footer {
    margin-top: auto;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2.5mm;
    font-size: 6.5pt;
    font-weight: 900;
  }
  @media print {
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
</head>
<body>
  ${labelsHtml}
</body>
</html>
  `;
}


function openPrintWindow(html) {
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
}

function isCancelledStatus(status) {
  return String(status || "").trim().toLowerCase() === "cancelado";
}

function isCancelledOrder(item) {
  const internal = String(item?.internal_status || "").trim().toLowerCase();
  const sep = String(item?.separation_status || "").trim().toLowerCase();
  return internal === "cancelado" || sep === "cancelado";
}

function StatusBadge({ status }) {
  if (isCancelledStatus(status)) {
    return <StatusPill status="Cancelado" />;
  }
  return <StatusPill status={status || "A separar"} />;
}

function CompanyBadge({ company }) {
  const key = normalizeCompanyKey(company);
  return (
    <span
      style={{
        ...styles.companyBadge,
        ...(key === "park" ? styles.companyBadgePark : styles.companyBadgeParton),
      }}
    >
      {companyLabel(key)}
    </span>
  );
}

function normalizeSeparationStatus(item) {
  const raw = item?.separation_status || "A separar";
  const internal = String(item?.internal_status || "").trim().toLowerCase();

  if (internal === "em aberto") return "__hidden__";
  if (internal === "aguardando aprovação") return "__hidden__";
  if (internal === "cancelado") return "Cancelado";

  if (internal === "faturado") return "Entregue";
  if (internal === "pronto para envio") return "Separado";
  if (internal === "preparando envio") return "Separando";

  return raw || "A separar";
}

function totalProductQty(items = []) {
  return (items || []).reduce((acc, item) => {
    const qty = Number(item?.qty ?? item?.quantity ?? item?.quantidade ?? 0);
    return Number.isFinite(qty) && qty > 0 ? acc + qty : acc;
  }, 0);
}

function canPrintSeparationLabel(item) {
  const status = normalizeSeparationStatus(item);
  return status === "Separado" || status === "Entregue";
}

// ---------------------------------------------------------------------------
// Conferência + Foto (gated, aditivo). Em OFF nada disto altera o fluxo atual.
// ---------------------------------------------------------------------------

// As fotos de separação/conferência são servidas por rota AUTENTICADA (não-pública,
// podem conter PII). A resolução da src é feita no PhotoField via
// api.getSeparationPhotoObjectUrl (fetch com token -> object URL), pois <img>
// sozinho não envia o header Authorization.

// Lê o override de QA por dispositivo (escape hatch). Precedente de gate por
// ambiente: App.jsx isBetaEnv. NUNCA guarda foto — só o modo.
function readSepModeLocalOverride() {
  if (typeof window === "undefined") return "";
  try {
    const v = String(window.localStorage.getItem("sep_conferencia_mode") || "").trim().toLowerCase();
    return v === "off" || v === "soft" || v === "strict" ? v : "";
  } catch {
    return "";
  }
}

// Resolve o modo: 'off' | 'soft' | 'strict'. A coerção dura (passo 4) é a
// última e inegociável: sem a capability do backend, sempre 'off'.
function resolveSepMode(me) {
  // 1) modo base: prioriza o configurado no backend pelo admin (runtime); na
  //    ausência, cai para o env de build. Default 'off'.
  const backendMode = String(me?.features?.conferencia_mode || "").trim().toLowerCase();
  const envMode = String(import.meta.env?.VITE_SEP_CONFERENCIA_MODE || "off").trim().toLowerCase();
  const baseMode = ["off", "soft", "strict"].includes(backendMode) ? backendMode : envMode;
  let mode = baseMode === "soft" || baseMode === "strict" ? baseMode : "off";

  // 2) override por dispositivo (QA)
  const localOverride = readSepModeLocalOverride();
  if (localOverride) mode = localOverride;

  // 3) allowlist por operador -> SOFT default (STRICT continua opt-in via env/localStorage)
  const operators = String(import.meta.env?.VITE_SEP_CONFERENCIA_OPERATORS || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  const login = String(me?.login || "").trim().toLowerCase();
  if (mode === "off" && login && operators.includes(login)) mode = "soft";

  // 4) COERÇÃO DURA: sem capability -> OFF (ignora env/localStorage/allowlist).
  if (!me?.features?.conferencia) return "off";

  return mode;
}

// Status exibido na lista. Em OFF é idêntico a normalizeSeparationStatus.
// Fora do OFF, pedidos com awaiting_conference exibem "Conferência" (overlay
// do front; o interno permanece "Preparando Envio" = "Separando").
function getDisplayStatus(item, sepMode) {
  const base = normalizeSeparationStatus(item);
  if (sepMode !== "off" && item?.awaiting_conference === true && base === "Separando") {
    return "Conferência";
  }
  return base;
}

// Etiqueta por modo. OFF: inalterado (Separado/Entregue). SOFT: também em
// "Conferência" (mesmo timing de hoje). STRICT: só após a conferência.
function canPrintLabelForMode(item, sepMode) {
  if (canPrintSeparationLabel(item)) return true;
  if (sepMode === "soft" && getDisplayStatus(item, sepMode) === "Conferência") return true;
  return false;
}

// Comprime a imagem no cliente (canvas resize). Em qualquer falha, devolve o
// arquivo original — nunca bloqueia o upload.
function compressImageFile(file, { maxDimension = 1600, quality = 0.7 } = {}) {
  return new Promise((resolve) => {
    if (!file || !String(file.type || "").startsWith("image/") || typeof document === "undefined") {
      resolve(file);
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      try {
        const longest = Math.max(img.width || 1, img.height || 1);
        const scale = Math.min(1, maxDimension / longest);
        const w = Math.max(1, Math.round((img.width || 1) * scale));
        const h = Math.max(1, Math.round((img.height || 1) * scale));
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        canvas.toBlob(
          (blob) => {
            if (!blob) {
              resolve(file);
              return;
            }
            const name = `${String(file.name || "foto").replace(/\.[^.]+$/, "")}.jpg`;
            resolve(new File([blob], name, { type: "image/jpeg" }));
          },
          "image/jpeg",
          quality
        );
      } catch {
        URL.revokeObjectURL(url);
        resolve(file);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(file);
    };
    img.src = url;
  });
}

// Campo de foto inline. Upload imediato no momento da captura; guarda apenas a
// string retornada (filename/url), nunca blob/base64. Preview vive só em
// memória (createObjectURL) e é revogado após o upload. Em readOnly, exibe a
// partir da URL/filename persistido (fonte de verdade = servidor).
function PhotoField({ label, value, onChange, readOnly = false, disabled = false }) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");
  const [fetchedUrl, setFetchedUrl] = useState("");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  // A foto persistida é servida por rota autenticada (não-pública). Busca via
  // fetch com token e cria um object URL; <img> sozinho não autentica.
  useEffect(() => {
    let cancelled = false;
    let createdUrl = "";
    setFetchedUrl("");
    setLocalError("");
    const v = String(value || "").trim();
    if (!v) return undefined;
    (async () => {
      try {
        const objUrl = await api.getSeparationPhotoObjectUrl(v);
        if (cancelled) {
          if (objUrl && objUrl.startsWith("blob:")) URL.revokeObjectURL(objUrl);
          return;
        }
        if (objUrl && objUrl.startsWith("blob:")) createdUrl = objUrl;
        setFetchedUrl(objUrl || "");
      } catch {
        if (!cancelled) setLocalError("Não foi possível carregar a foto.");
      }
    })();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [value]);

  async function handleSelect(file) {
    if (!file) return;
    setLocalError("");
    const objectUrl = URL.createObjectURL(file);
    setPreviewUrl(objectUrl);
    setUploading(true);
    try {
      const compressed = await compressImageFile(file);
      const result = await api.uploadSeparationPhoto(compressed);
      const stored = String(result?.filename || result?.url || "").trim();
      if (!stored) throw new Error("O upload não retornou o arquivo da foto.");
      onChange?.(stored);
      URL.revokeObjectURL(objectUrl);
      setPreviewUrl("");
    } catch (e) {
      URL.revokeObjectURL(objectUrl);
      setPreviewUrl("");
      setLocalError(e?.message || "Erro ao enviar a foto.");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const displaySrc = previewUrl || fetchedUrl;

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {label ? <div style={styles.label}>{label}</div> : null}

      {displaySrc ? (
        <img
          src={displaySrc}
          alt={label || "Foto"}
          style={{
            maxWidth: "100%",
            maxHeight: 220,
            borderRadius: 12,
            border: "1px solid var(--border)",
            objectFit: "contain",
            background: "var(--panel)",
          }}
        />
      ) : (
        <div style={{ ...styles.muted, fontSize: 12 }}>
          {readOnly ? "Sem foto." : "Nenhuma foto adicionada."}
        </div>
      )}

      {!readOnly ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: "none" }}
            onChange={(e) => handleSelect(e.target.files?.[0])}
          />
          <button
            type="button"
            style={styles.button}
            disabled={disabled || uploading}
            onClick={() => inputRef.current?.click()}
          >
            {uploading ? "Enviando foto..." : value ? "📷 Trocar foto" : "📷 Foto"}
          </button>
          {value && !uploading ? (
            <button
              type="button"
              style={styles.button}
              disabled={disabled}
              onClick={() => onChange?.("")}
            >
              Remover
            </button>
          ) : null}
        </div>
      ) : null}

      {localError ? <div style={styles.dangerText}>{localError}</div> : null}
    </div>
  );
}

function InfoBlock({ title, rows }) {
  return (
    <div style={styles.card}>
      <div style={styles.sectionTitle}>{title}</div>
      <div style={styles.kvWrap}>
        {rows.map((row) => (
          <div key={row.label} style={styles.kvRow}>
            <div style={styles.kvKey}>{row.label}</div>
            <div style={styles.kvValue}>{row.value || "-"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function getViewportFlags() {
  if (typeof window === "undefined") return { isMobile: false, isTablet: false };
  const w = window.innerWidth || 1400;
  return {
    isMobile: w <= 820,
    isTablet: w <= 1180,
  };
}

export default function Separation() {
  const { isMobile, isTablet } = getViewportFlags();
  const [activeCompany, setActiveCompany] = useState(() => getInitialSeparationCompany(api.getCurrentCompany?.()));
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState({ q: "" });

  const [activeStatusTab, setActiveStatusTab] = useState("Todos");
  const [activeShippingTab, setActiveShippingTab] = useState("Todos");

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastRefreshAt, setLastRefreshAt] = useState(null);

  const [savingId, setSavingId] = useState(null);
  const [me, setMe] = useState(null);
  const isAdmin = !!me?.is_admin;
  // Modo da conferência ('off' | 'soft' | 'strict'). Em OFF nada muda.
  const sepMode = useMemo(() => resolveSepMode(me), [me]);

  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [selectedOrderId, setSelectedOrderId] = useState(null);
  const [selectedOrderCompany, setSelectedOrderCompany] = useState(null);
  const [detailMode, setDetailMode] = useState("detail");
  const [detail, setDetail] = useState(null);

  const [draftStatus, setDraftStatus] = useState("A separar");
  const [draftPrinted, setDraftPrinted] = useState(false);
  const [draftAssignedTo, setDraftAssignedTo] = useState("");
  const [draftNotes, setDraftNotes] = useState("");
  const [draftBoxes, setDraftBoxes] = useState(0);
  const [draftBags, setDraftBags] = useState(0);
  const [draftWeightKg, setDraftWeightKg] = useState("");
  const [draftHeightCm, setDraftHeightCm] = useState("");
  const [draftWidthCm, setDraftWidthCm] = useState("");
  const [draftLengthCm, setDraftLengthCm] = useState("");
  const [draftVolumes, setDraftVolumes] = useState("");
  const [draftSeparationPhoto, setDraftSeparationPhoto] = useState("");
  const [draftConferencePhoto, setDraftConferencePhoto] = useState("");
  const [savingDetail, setSavingDetail] = useState(false);

  async function load({ silent = false } = {}) {
    if (!silent) setLoading(true);
    setError("");
    try {
      const request = async () => {
        const company = normalizeCompanyKey(activeCompany);
        const res = await api.listSeparationOrders({
          company,
          q: query.q,
          limit: 500,
          offset: 0,
          _ts: Date.now(),
        });

        return (res?.items || []).map((item) => ({
            ...item,
            company_key: normalizeCompanyKey(item?.company_key || company),
          }));
      };

      const res = silent
        ? await request()
        : await withGlobalLoading("Carregando separação...", request);

      const mapped = (res || [])
        .map((item) => ({
          ...item,
          separation_status: normalizeSeparationStatus(item),
        }))
        .filter((item) => item.separation_status !== "__hidden__");

      const statusPriority = {
        "A separar": 1,
        "Separando": 2,
        "Conferência": 2.5,
        "Separado": 3,
        "Entregue": 8,
        "Cancelado": 9,
      };

      const sorted = [...mapped].sort((a, b) => {
        const pa = statusPriority[getDisplayStatus(a, sepMode)] ?? 5;
        const pb = statusPriority[getDisplayStatus(b, sepMode)] ?? 5;
        if (pa !== pb) return pa - pb;

        const da = new Date(a.updated_at || a.created_at || 0).getTime() || 0;
        const db = new Date(b.updated_at || b.created_at || 0).getTime() || 0;
        return db - da;
      });

      setItems(sorted);
      setLastRefreshAt(new Date());
    } catch (e) {
      setError(e?.message || "Erro ao carregar a fila de separação.");
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [query.q, activeCompany]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const modalOpen = !!detail;
      const busy = detailLoading || savingDetail || !!savingId;
      const hidden = typeof document !== "undefined" && document.hidden;

      if (modalOpen || busy || hidden) return;

      load({ silent: true });
      // Propaga em runtime o toggle de capability/modo feito pelo admin, sem
      // exigir reload manual. Fire-and-forget; em erro mantém o me() atual.
      api.me().then((r) => { if (r) setMe(r); }).catch(() => {});
    }, 15000);

    return () => window.clearInterval(interval);
  }, [selectedOrderId, selectedOrderCompany, detailMode, detail, loading, detailLoading, savingDetail, savingId, query.q, activeCompany]);


  useEffect(() => {
    (async () => {
      try {
        const r = await api.me();
        setMe(r);
      } catch {
        setMe({ is_admin: false });
      }
    })();
  }, []);

  useEffect(() => {
    writeSeparationCompanyUrl(activeCompany, { replace: true });

    const onPopState = () => {
      const nextCompany = getInitialSeparationCompany(activeCompany);
      setActiveCompany((current) => (current === nextCompany ? current : nextCompany));
    };

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function handleCompanyTabClick(company) {
    const nextCompany = normalizeCompanyKey(company);
    writeSeparationCompanyUrl(nextCompany);
    setActiveCompany(nextCompany);
    setSearch("");
    setQuery({ q: "" });
    setActiveStatusTab("Todos");
    setActiveShippingTab("Todos");
    setSelectedOrderId(null);
    setSelectedOrderCompany(null);
    setDetailMode("detail");
    setDetail(null);
    setDetailError("");
  }

  async function openDetails(tinyOrderId, company) {
    const orderCompany = normalizeCompanyKey(company);
    setDetailMode("detail");
    setSelectedOrderId(tinyOrderId);
    setSelectedOrderCompany(orderCompany);
    setDetailLoading(true);
    setDetailError("");
    try {
      const res = await withGlobalLoading("Carregando detalhes...", () => api.getSeparationOrder(tinyOrderId, orderCompany));
      setDetail({
        ...res,
        order: res?.order ? { ...res.order, company_key: normalizeCompanyKey(res.order.company_key || orderCompany) } : res?.order,
      });

      const order = { ...(res?.order || {}), company_key: orderCompany };
      setDraftStatus(normalizeSeparationStatus(order) || "A separar");
      setDraftPrinted(Boolean(order.printed));
      setDraftAssignedTo(order.assigned_to || "");
      setDraftNotes(order.separation_notes || "");
      setDraftBoxes(Number(order.packaging_boxes || 0));
      setDraftBags(Number(order.packaging_bags || 0));
      setDraftSeparationPhoto(order.separation_photo_url || "");
      setDraftConferencePhoto(order.conference_photo_url || "");
      hydratePackagingDraft(order);
    } catch (e) {
      setDetail(null);
      setDetailError(e?.message || "Erro ao carregar detalhes do pedido.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function printFromList(item) {
    if (isCancelledOrder(item)) {
      setError("Pedido cancelado não pode ser impresso para separação.");
      return;
    }
    const orderId = item?.tiny_order_id;
    const orderCompany = getOrderCompany(item);
    if (!orderId) return;

    setSavingId(orderId);
    setError("");
    try {
      const res = await withGlobalLoading("Abrindo separação...", () => api.getSeparationOrder(orderId, orderCompany));
      const order = { ...(res?.order || {}), company_key: orderCompany };
      const snapshotClient = safeJsonParse(order.client_snapshot, {}) || {};
      const listClientName =
        order.client_name ||
        order.cliente ||
        order.customer_name ||
        order.cliente_nome ||
        snapshotClient.nome ||
        snapshotClient.name ||
        snapshotClient.razao_social ||
        "";

      const clientData = {
        ...snapshotClient,
        nome: listClientName || snapshotClient.nome || snapshotClient.name || "",
        name: listClientName || snapshotClient.name || snapshotClient.nome || "",
        razao_social: listClientName || snapshotClient.razao_social || "",
        cpf_cnpj:
          order.client_document ||
          order.cpf_cnpj ||
          order.documento ||
          snapshotClient.cpf_cnpj ||
          snapshotClient.cpfCnpj ||
          snapshotClient.documento ||
          "",
        cpfCnpj:
          order.client_document ||
          order.cpf_cnpj ||
          order.documento ||
          snapshotClient.cpfCnpj ||
          snapshotClient.cpf_cnpj ||
          "",
        telefone:
          order.client_phone ||
          order.telefone ||
          order.phone ||
          snapshotClient.telefone ||
          snapshotClient.fone ||
          snapshotClient.phone ||
          "",
        fone:
          order.client_phone ||
          order.telefone ||
          order.phone ||
          snapshotClient.fone ||
          snapshotClient.telefone ||
          "",
        email:
          order.client_email ||
          order.email ||
          snapshotClient.email ||
          "",
        endereco:
          order.client_address ||
          order.endereco ||
          snapshotClient.endereco ||
          snapshotClient.logradouro ||
          "",
        logradouro:
          order.client_address ||
          snapshotClient.logradouro ||
          snapshotClient.endereco ||
          "",
      };
      const html = buildSeparationPrintHtml({
        order,
        items: res?.items || [],
        client: clientData,
      });

      openPrintWindow(html);

      await api.updateSeparationOrder(orderId, {
        printed: true,
        status: "Separando",
        internal_status: "Preparando Envio",
      }, orderCompany);

      const refreshed = await api.getSeparationOrder(orderId, orderCompany);
      const orderRef = refreshed?.order || {};

      setItems((prev) => {
        const current = prev.find((x) => sameCompanyOrder(x, orderId, orderCompany)) || {};
        const merged = {
          ...current,
          ...orderRef,
          company_key: orderCompany,
          tiny_order_id: orderId,
          tiny_order_number: orderRef.tiny_order_number ?? current.tiny_order_number,
          quote_id: orderRef.quote_id ?? current.quote_id,
          quote_number: orderRef.quote_number ?? current.quote_number,
          client_name: orderRef.client_name ?? current.client_name,
          seller_name: orderRef.seller_name ?? current.seller_name,
          shipping_method_name: orderRef.shipping_method_name ?? current.shipping_method_name,
          freight_method_name: orderRef.freight_method_name ?? current.freight_method_name,
          separation_status: orderRef.separation_status || "Separando",
          printed: true,
        };

        return [merged, ...prev.filter((x) => !sameCompanyOrder(x, orderId, orderCompany))];
      });

      setActiveStatusTab("Separando");
      setActiveShippingTab("Todos");
    } catch (e) {
      setError(e?.message || "Erro ao imprimir e mover para Separando.");
    } finally {
      setSavingId(null);
    }
  }

  async function openOperateFlow(item) {
    if (isCancelledOrder(item)) {
      setError("Pedido cancelado não pode ser separado.");
      return;
    }

    const orderId = item?.tiny_order_id;
    const orderCompany = getOrderCompany(item);
    if (!orderId) return;

    setSavingId(orderId);
    setDetailMode("operate");
    setDetailError("");
    setDetailLoading(true);
    setSelectedOrderId(orderId);
    setSelectedOrderCompany(orderCompany);

    setDetail({
      order: {
        company_key: orderCompany,
        tiny_order_id: orderId,
        tiny_order_number: item?.tiny_order_number,
        quote_id: item?.quote_id,
        quote_number: item?.quote_number,
        client_name: item?.client_name,
        seller_name: item?.seller_name,
        shipping_method_name: item?.shipping_method_name,
        freight_method_name: item?.freight_method_name,
        separation_status: "Separando",
        printed: Boolean(item?.printed),
        assigned_to: item?.assigned_to || "",
        separation_notes: item?.separation_notes || "",
        packaging_boxes: Number(item?.packaging_boxes || 0),
        packaging_bags: Number(item?.packaging_bags || 0),
        packaging_weight_kg: item?.packaging_weight_kg ?? null,
        packaging_height_cm: item?.packaging_height_cm ?? null,
        packaging_width_cm: item?.packaging_width_cm ?? null,
        packaging_length_cm: item?.packaging_length_cm ?? null,
        packaging_volumes: item?.packaging_volumes ?? null,
      },
      items: [],
    });

    setDraftStatus("Separando");
    setDraftPrinted(Boolean(item?.printed));
    setDraftAssignedTo(item?.assigned_to || "");
    setDraftNotes(item?.separation_notes || "");
    setDraftBoxes(Number(item?.packaging_boxes || 0));
    setDraftBags(Number(item?.packaging_bags || 0));
    setDraftSeparationPhoto(item?.separation_photo_url || "");
    setDraftConferencePhoto("");
      hydratePackagingDraft(item);

    try {
      const updatePromise = api.updateSeparationOrder(orderId, {
        status: "Separando",
        internal_status: "Preparando Envio",
      }, orderCompany);

      const detailPromise = api.getSeparationOrder(orderId, orderCompany);

      await updatePromise;

      setItems((prev) =>
        prev.map((x) =>
          sameCompanyOrder(x, orderId, orderCompany)
            ? {
                ...x,
                separation_status: "Separando",
              }
            : x
        )
      );

      const res = await detailPromise;
      setDetail({
        ...res,
        order: res?.order ? { ...res.order, company_key: normalizeCompanyKey(res.order.company_key || orderCompany) } : res?.order,
      });

      const order = { ...(res?.order || {}), company_key: orderCompany };
      setDraftStatus(normalizeSeparationStatus(order) || "Separando");
      setDraftPrinted(Boolean(order.printed));
      setDraftAssignedTo(order.assigned_to || "");
      setDraftNotes(order.separation_notes || "");
      setDraftBoxes(Number(order.packaging_boxes || 0));
      setDraftBags(Number(order.packaging_bags || 0));
      setDraftSeparationPhoto(order.separation_photo_url || item?.separation_photo_url || "");
      setDraftConferencePhoto("");
      hydratePackagingDraft(order);
    } catch (e) {
      setDetail(null);
      setDetailError(e?.message || "Erro ao abrir fluxo operacional.");
    } finally {
      setDetailLoading(false);
      setSavingId(null);
    }
  }

  function hydratePackagingDraft(order = {}) {
    setDraftWeightKg(order.packaging_weight_kg ?? "");
    setDraftHeightCm(order.packaging_height_cm ?? "");
    setDraftWidthCm(order.packaging_width_cm ?? "");
    setDraftLengthCm(order.packaging_length_cm ?? "");
    const savedVolumes = Number(order.packaging_volumes || 0);
    const suggestedPhysicalVolumes = Number(order.packaging_boxes || 0) + Number(order.packaging_bags || 0);
    setDraftVolumes(savedVolumes > 0 ? order.packaging_volumes : suggestedPhysicalVolumes || "");
  }

  function buildPackagingPayload() {
    return {
      packaging_weight_kg: numberOrNull(draftWeightKg),
      packaging_height_cm: numberOrNull(draftHeightCm),
      packaging_width_cm: numberOrNull(draftWidthCm),
      packaging_length_cm: numberOrNull(draftLengthCm),
      packaging_volumes: numberOrNull(draftVolumes),
    };
  }

  function currentPackagingValues() {
    return {
      packaging_weight_kg: numberOrNull(draftWeightKg),
      packaging_height_cm: numberOrNull(draftHeightCm),
      packaging_width_cm: numberOrNull(draftWidthCm),
      packaging_length_cm: numberOrNull(draftLengthCm),
      packaging_volumes: numberOrNull(draftVolumes),
    };
  }

  async function saveDetail() {
    if (isCancelledOrder(detail?.order)) {
      setDetailError("Pedido cancelado não permite alteração operacional.");
      return;
    }

    if (!selectedOrderId) return;

    const orderCompany = normalizeCompanyKey(selectedOrderCompany || detail?.order?.company_key);
    setSavingDetail(true);
    setDetailError("");
    try {
      await withGlobalLoading("Salvando separação...", () =>
        api.updateSeparationOrder(selectedOrderId, {
          // Na conferência o rascunho NÃO altera o status (mantém awaiting_conference
          // no backend). Em operate/detail o comportamento é idêntico ao de hoje.
          ...(detailMode !== "conferencia" ? { status: draftStatus } : {}),
          printed: draftPrinted,
          assigned_to: draftAssignedTo.trim() || null,
          notes: draftNotes.trim() || null,
          packaging_boxes: Number(draftBoxes || 0),
          packaging_bags: Number(draftBags || 0),
          ...buildPackagingPayload(),
        }, orderCompany)
      );

      setItems((prev) =>
        prev.map((x) =>
          sameCompanyOrder(x, selectedOrderId, orderCompany)
            ? {
                ...x,
                separation_status: draftStatus || "Separando",
                printed: draftPrinted,
                assigned_to: draftAssignedTo.trim() || null,
                separation_notes: draftNotes.trim() || null,
                packaging_boxes: Number(draftBoxes || 0),
                packaging_bags: Number(draftBags || 0),
                ...currentPackagingValues(),
              }
            : x
        )
      );

      setDetail((prev) =>
        prev?.order
          ? {
              ...prev,
              order: {
                ...prev.order,
                separation_status: draftStatus || "Separando",
                printed: draftPrinted,
                assigned_to: draftAssignedTo.trim() || null,
                separation_notes: draftNotes.trim() || null,
                packaging_boxes: Number(draftBoxes || 0),
                packaging_bags: Number(draftBags || 0),
                ...currentPackagingValues(),
              },
            }
          : prev
      );
    } catch (e) {
      setDetailError(e?.message || "Erro ao salvar dados operacionais.");
    } finally {
      setSavingDetail(false);
    }
  }

  async function finalizeSeparation() {
    if (!selectedOrderId) return;

    if (Number(draftVolumes || 0) < 1) {
      setDetailError("Informe o volume total físico antes de finalizar a separação.");
      return;
    }

    // Gate de foto obrigatória SOMENTE em STRICT (SOFT/OFF não bloqueiam).
    if (sepMode === "strict" && !String(draftSeparationPhoto || "").trim()) {
      setDetailError("Tire a foto da separação antes de finalizar (modo obrigatório).");
      return;
    }

    const orderCompany = normalizeCompanyKey(selectedOrderCompany || detail?.order?.company_key);

    // SOFT/STRICT: não envia "Separado". Entra em conferência, mantém o interno
    // "Preparando Envio" e NÃO dispara push ao Tiny.
    if (sepMode !== "off") {
      setSavingDetail(true);
      setDetailError("");
      try {
        const photo = String(draftSeparationPhoto || "").trim();
        await withGlobalLoading("Enviando para conferência...", () =>
          api.updateSeparationOrder(selectedOrderId, {
            awaiting_conference: true,
            printed: draftPrinted,
            assigned_to: draftAssignedTo.trim() || null,
            notes: draftNotes.trim() || null,
            packaging_boxes: Number(draftBoxes || 0),
            packaging_bags: Number(draftBags || 0),
            ...buildPackagingPayload(),
            ...(photo ? { separation_photo_url: photo } : {}),
          }, orderCompany)
        );

        setItems((prev) =>
          prev.map((x) =>
            sameCompanyOrder(x, selectedOrderId, orderCompany)
              ? {
                  ...x,
                  awaiting_conference: true,
                  printed: draftPrinted,
                  assigned_to: draftAssignedTo.trim() || null,
                  separation_notes: draftNotes.trim() || null,
                  separation_photo_url: photo || x.separation_photo_url || "",
                  packaging_boxes: Number(draftBoxes || 0),
                  packaging_bags: Number(draftBags || 0),
                  ...currentPackagingValues(),
                }
              : x
          )
        );

        setActiveStatusTab("Conferência");
        setActiveShippingTab("Todos");
        // Fecha o detalhe (padrão inline usado no restante do arquivo).
        setSelectedOrderId(null);
        setSelectedOrderCompany(null);
        setDetailMode("detail");
        setDetail(null);
        setDetailError("");
        setDraftSeparationPhoto("");
        setDraftConferencePhoto("");
        await load({ silent: true });
      } catch (e) {
        setDetailError(e?.message || "Erro ao enviar o pedido para conferência.");
      } finally {
        setSavingDetail(false);
      }
      return;
    }

    // OFF: comportamento legado inalterado (envia "Separado" -> push ao Tiny).
    setSavingDetail(true);
    setDetailError("");
    try {
      await withGlobalLoading("Finalizando separação...", () =>
        api.updateSeparationOrder(selectedOrderId, {
          status: "Separado",
          printed: draftPrinted,
          assigned_to: draftAssignedTo.trim() || null,
          notes: draftNotes.trim() || null,
          packaging_boxes: Number(draftBoxes || 0),
          packaging_bags: Number(draftBags || 0),
          ...buildPackagingPayload(),
        }, orderCompany)
      );

      setItems((prev) =>
        prev.map((x) =>
          sameCompanyOrder(x, selectedOrderId, orderCompany)
            ? {
                ...x,
                separation_status: "Separado",
                printed: draftPrinted,
                assigned_to: draftAssignedTo.trim() || null,
                separation_notes: draftNotes.trim() || null,
                packaging_boxes: Number(draftBoxes || 0),
                packaging_bags: Number(draftBags || 0),
                ...currentPackagingValues(),
              }
            : x
        )
      );

      setDetail((prev) =>
        prev?.order
          ? {
              ...prev,
              order: {
                ...prev.order,
                separation_status: "Separado",
                printed: draftPrinted,
                assigned_to: draftAssignedTo.trim() || null,
                separation_notes: draftNotes.trim() || null,
                packaging_boxes: Number(draftBoxes || 0),
                packaging_bags: Number(draftBags || 0),
                ...currentPackagingValues(),
              },
            }
          : prev
      );

      setDraftStatus("Separado");
      closeDetail();
      await load({ silent: true });
    } catch (e) {
      setDetailError(e?.message || "Erro ao finalizar a separação.");
    } finally {
      setSavingDetail(false);
    }
  }

  // Abre o fluxo de conferência (espelha openOperateFlow com detailMode
  // "conferencia"). NÃO altera o status no backend: o pedido permanece
  // awaiting_conference até a finalização da conferência.
  async function openConferenceFlow(item) {
    if (isCancelledOrder(item)) {
      setError("Pedido cancelado não pode ser conferido.");
      return;
    }

    const orderId = item?.tiny_order_id;
    const orderCompany = getOrderCompany(item);
    if (!orderId) return;

    setSavingId(orderId);
    setDetailMode("conferencia");
    setDetailError("");
    setDetailLoading(true);
    setSelectedOrderId(orderId);
    setSelectedOrderCompany(orderCompany);

    setDetail({
      order: {
        company_key: orderCompany,
        tiny_order_id: orderId,
        tiny_order_number: item?.tiny_order_number,
        quote_id: item?.quote_id,
        quote_number: item?.quote_number,
        client_name: item?.client_name,
        seller_name: item?.seller_name,
        shipping_method_name: item?.shipping_method_name,
        freight_method_name: item?.freight_method_name,
        separation_status: "Separando",
        awaiting_conference: true,
        printed: Boolean(item?.printed),
        assigned_to: item?.assigned_to || "",
        separation_notes: item?.separation_notes || "",
        separation_photo_url: item?.separation_photo_url || "",
        conference_photo_url: item?.conference_photo_url || "",
        packaging_boxes: Number(item?.packaging_boxes || 0),
        packaging_bags: Number(item?.packaging_bags || 0),
        packaging_weight_kg: item?.packaging_weight_kg ?? null,
        packaging_height_cm: item?.packaging_height_cm ?? null,
        packaging_width_cm: item?.packaging_width_cm ?? null,
        packaging_length_cm: item?.packaging_length_cm ?? null,
        packaging_volumes: item?.packaging_volumes ?? null,
      },
      items: [],
    });

    setDraftStatus("Separando");
    setDraftPrinted(Boolean(item?.printed));
    setDraftAssignedTo(item?.assigned_to || "");
    setDraftNotes(item?.separation_notes || "");
    setDraftBoxes(Number(item?.packaging_boxes || 0));
    setDraftBags(Number(item?.packaging_bags || 0));
    setDraftSeparationPhoto(item?.separation_photo_url || "");
    setDraftConferencePhoto(item?.conference_photo_url || "");
    hydratePackagingDraft(item);

    try {
      const res = await withGlobalLoading("Carregando conferência...", () => api.getSeparationOrder(orderId, orderCompany));
      setDetail({
        ...res,
        order: res?.order ? { ...res.order, company_key: normalizeCompanyKey(res.order.company_key || orderCompany) } : res?.order,
      });

      const order = { ...(res?.order || {}), company_key: orderCompany };
      setDraftPrinted(Boolean(order.printed));
      setDraftAssignedTo(order.assigned_to || "");
      setDraftNotes(order.separation_notes || "");
      setDraftBoxes(Number(order.packaging_boxes || 0));
      setDraftBags(Number(order.packaging_bags || 0));
      setDraftSeparationPhoto(order.separation_photo_url || item?.separation_photo_url || "");
      setDraftConferencePhoto(order.conference_photo_url || "");
      hydratePackagingDraft(order);
    } catch (e) {
      setDetail(null);
      setDetailError(e?.message || "Erro ao abrir a conferência.");
    } finally {
      setDetailLoading(false);
      setSavingId(null);
    }
  }

  // Finaliza a conferência: envia "Separado" + awaiting_conference:false +
  // checked_at. Reutiliza a transição existente -> "Pronto para Envio" + push
  // ao Tiny (é aqui, e só aqui no fluxo gated, que o push ocorre).
  async function finalizeConference() {
    if (!selectedOrderId) return;

    if (Number(draftVolumes || 0) < 1) {
      setDetailError("Informe o volume total físico antes de finalizar a conferência.");
      return;
    }

    const orderCompany = normalizeCompanyKey(selectedOrderCompany || detail?.order?.company_key);
    setSavingDetail(true);
    setDetailError("");
    try {
      const photo = String(draftConferencePhoto || "").trim();
      const checkedAt = new Date().toISOString();
      await withGlobalLoading("Finalizando conferência...", () =>
        api.updateSeparationOrder(selectedOrderId, {
          status: "Separado",
          awaiting_conference: false,
          checked_at: checkedAt,
          printed: draftPrinted,
          assigned_to: draftAssignedTo.trim() || null,
          notes: draftNotes.trim() || null,
          packaging_boxes: Number(draftBoxes || 0),
          packaging_bags: Number(draftBags || 0),
          ...buildPackagingPayload(),
          ...(photo ? { conference_photo_url: photo } : {}),
        }, orderCompany)
      );

      setItems((prev) =>
        prev.map((x) =>
          sameCompanyOrder(x, selectedOrderId, orderCompany)
            ? {
                ...x,
                separation_status: "Separado",
                awaiting_conference: false,
                checked_at: checkedAt,
                conference_photo_url: photo || x.conference_photo_url || "",
                printed: draftPrinted,
                assigned_to: draftAssignedTo.trim() || null,
                separation_notes: draftNotes.trim() || null,
                packaging_boxes: Number(draftBoxes || 0),
                packaging_bags: Number(draftBags || 0),
                ...currentPackagingValues(),
              }
            : x
        )
      );

      setDraftStatus("Separado");
      // Fecha o detalhe (padrão inline usado no restante do arquivo).
      setSelectedOrderId(null);
      setSelectedOrderCompany(null);
      setDetailMode("detail");
      setDetail(null);
      setDetailError("");
      setDraftSeparationPhoto("");
      setDraftConferencePhoto("");
      await load({ silent: true });
    } catch (e) {
      setDetailError(e?.message || "Erro ao finalizar a conferência.");
    } finally {
      setSavingDetail(false);
    }
  }

  async function deleteOrderLocal(item) {
    if (!isAdmin) return;
    if (!item?.quote_id) {
      setError("quote_id não encontrado para exclusão.");
      return;
    }

    const orderRef = item?.tiny_order_number || item?.tiny_order_id || item?.quote_number || item?.quote_id;
    const ok = window.confirm(
      `Excluir localmente este pedido/orçamento da fila?\n\nReferência: ${orderRef}\n\nEssa ação não pode ser desfeita.`
    );
    if (!ok) return;

    setSavingId(item.quote_id);
    setError("");
    try {
      await api.deleteQuote(item.quote_id, getOrderCompany(item));

      setItems((prev) => prev.filter((x) => x?.quote_id !== item.quote_id));

      if (selectedOrderId === item?.tiny_order_id && selectedOrderCompany === getOrderCompany(item)) {
        setSelectedOrderId(null);
        setSelectedOrderCompany(null);
        setDetailMode("detail");
        setDetail(null);
        setDetailError("");
      }
    } catch (e) {
      setError(e?.message || "Erro ao excluir pedido local.");
    } finally {
      setSavingId(null);
    }
  }

  async function handlePrint() {
    if (isCancelledOrder(detail?.order)) {
      setDetailError("Pedido cancelado não pode ser impresso para separação.");
      return;
    }

    if (!detail?.order) return;

    try {
      const orderId = detail?.order?.tiny_order_id;
      const orderCompany = normalizeCompanyKey(selectedOrderCompany || detail?.order?.company_key);
      const currentStatus = normalizeSeparationStatus(detail?.order) || "A separar";

      const orderForPrint = {
        ...detail.order,
        packaging_boxes: Number(draftBoxes || detail.order?.packaging_boxes || 0),
        packaging_bags: Number(draftBags || detail.order?.packaging_bags || 0),
        ...currentPackagingValues(),
      };

      const html = buildSeparationPrintHtml({
        order: orderForPrint,
        items: detail.items || [],
        client,
      });

      openPrintWindow(html);

      if (orderId) {
        const payload =
          currentStatus === "A separar"
            ? {
                printed: true,
                status: "Separando",
                internal_status: "Preparando Envio",
                packaging_boxes: Number(draftBoxes || 0),
                packaging_bags: Number(draftBags || 0),
                ...buildPackagingPayload(),
              }
            : {
                printed: true,
                packaging_boxes: Number(draftBoxes || 0),
                packaging_bags: Number(draftBags || 0),
                ...buildPackagingPayload(),
              };

        await api.updateSeparationOrder(orderId, payload, orderCompany);

        setItems((prev) =>
          prev.map((x) =>
            sameCompanyOrder(x, orderId, orderCompany)
              ? {
                  ...x,
                  printed: true,
                  separation_status:
                    currentStatus === "A separar"
                      ? "Separando"
                      : (x?.separation_status || currentStatus),
                }
              : x
          )
        );

        setDetail((prev) =>
          prev
            ? {
                ...prev,
                order: {
                  ...prev.order,
                  printed: true,
                  separation_status:
                    currentStatus === "A separar"
                      ? "Separando"
                      : (prev.order?.separation_status || currentStatus),
                },
              }
            : prev
        );

        if (currentStatus === "A separar") {
          setDraftStatus("Separando");
          setDraftPrinted(true);
          setActiveStatusTab("Separando");
          setActiveShippingTab("Todos");
        } else {
          setDraftPrinted(true);
        }
      }
    } catch (e) {
      setDetailError(e?.message || "Erro ao abrir impressão da separação.");
    }
  }


  async function printLabelFromList(item) {
    if (isCancelledOrder(item)) {
      setError("Pedido cancelado não permite imprimir etiqueta.");
      return;
    }
    if (!canPrintLabelForMode(item, sepMode)) {
      setError("A etiqueta só pode ser impressa após finalizar a separação.");
      return;
    }

    const orderId = item?.tiny_order_id;
    const orderCompany = getOrderCompany(item);
    if (!orderId) return;

    setSavingId(orderId);
    setError("");

    try {
      const res = await withGlobalLoading("Abrindo etiqueta...", () => api.getSeparationOrder(orderId, orderCompany));
      const order = { ...(res?.order || {}), company_key: orderCompany };
      const snapshotClient = safeJsonParse(order.client_snapshot, {}) || {};
      const listClientName =
        order.client_name ||
        order.cliente ||
        order.customer_name ||
        order.cliente_nome ||
        snapshotClient.nome ||
        snapshotClient.name ||
        snapshotClient.razao_social ||
        "";

      const clientData = {
        ...snapshotClient,
        nome: listClientName || snapshotClient.nome || snapshotClient.name || "",
        name: listClientName || snapshotClient.name || snapshotClient.nome || "",
        razao_social: listClientName || snapshotClient.razao_social || "",
        cpf_cnpj:
          order.client_document ||
          order.cpf_cnpj ||
          order.documento ||
          snapshotClient.cpf_cnpj ||
          snapshotClient.cpfCnpj ||
          snapshotClient.documento ||
          "",
        cpfCnpj:
          order.client_document ||
          order.cpf_cnpj ||
          order.documento ||
          snapshotClient.cpfCnpj ||
          snapshotClient.cpf_cnpj ||
          "",
        telefone:
          order.client_phone ||
          order.telefone ||
          order.phone ||
          snapshotClient.telefone ||
          snapshotClient.fone ||
          snapshotClient.phone ||
          "",
        fone:
          order.client_phone ||
          order.telefone ||
          order.phone ||
          snapshotClient.fone ||
          snapshotClient.telefone ||
          "",
        email:
          order.client_email ||
          order.email ||
          snapshotClient.email ||
          "",
        endereco:
          order.client_address ||
          order.endereco ||
          snapshotClient.endereco ||
          snapshotClient.logradouro ||
          "",
        logradouro:
          order.client_address ||
          snapshotClient.logradouro ||
          snapshotClient.endereco ||
          "",
      };
      const html = buildSeparationLabelPrintHtml({
        order,
        client: clientData,
      });

      openPrintWindow(html);
    } catch (e) {
      setError(e?.message || "Erro ao imprimir etiqueta.");
    } finally {
      setSavingId(null);
    }
  }

  async function handlePrintLabel() {
    if (isCancelledOrder(detail?.order)) {
      setDetailError("Pedido cancelado não permite imprimir etiqueta.");
      return;
    }
    if (!canPrintLabelForMode(detail?.order, sepMode)) {
      setDetailError("A etiqueta só pode ser impressa após finalizar a separação.");
      return;
    }

    if (!detail?.order) return;

    try {
      const orderForLabel = {
        ...detail.order,
        packaging_boxes: Number(draftBoxes || detail.order?.packaging_boxes || 0),
        packaging_bags: Number(draftBags || detail.order?.packaging_bags || 0),
        ...currentPackagingValues(),
      };

      const html = buildSeparationLabelPrintHtml({
        order: orderForLabel,
        client,
      });

      openPrintWindow(html);
    } catch (e) {
      setDetailError(e?.message || "Erro ao imprimir etiqueta.");
    }
  }


  const statusTabs = useMemo(() => {
    // STATUS_OPTIONS é preservado; a aba "Conferência" é montada aqui, só fora
    // do OFF (entre "Separando" e "Separado").
    const base = sepMode === "off"
      ? ["Todos", ...STATUS_OPTIONS]
      : ["Todos", ...STATUS_OPTIONS.flatMap((s) => (s === "Separando" ? [s, "Conferência"] : [s]))];
    const counts = {};
    for (const s of base) counts[s] = 0;

    for (const item of items) {
      counts["Todos"] += 1;
      const s = getDisplayStatus(item, sepMode);
      if (counts[s] === undefined) counts[s] = 0;
      counts[s] += 1;
    }

    return base.map((label) => ({ label, count: counts[label] || 0 }));
  }, [items, sepMode]);

  const shippingTabs = useMemo(() => {
    const statusFilteredItems =
      activeStatusTab === "Todos"
        ? items
        : items.filter((item) => getDisplayStatus(item, sepMode) === activeStatusTab);

    const map = new Map();
    map.set("Todos", statusFilteredItems.length);

    for (const item of statusFilteredItems) {
      const envio = item?.shipping_method_name || "Sem envio";
      const frete = item?.freight_method_name || "Sem frete";
      const label = `${envio} -¢ ${frete}`;
      map.set(label, (map.get(label) || 0) + 1);
    }

    return Array.from(map.entries()).map(([label, count]) => ({ label, count }));
  }, [items, activeStatusTab, sepMode]);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      const itemStatus = getDisplayStatus(item, sepMode);
      const itemShipping = `${item?.shipping_method_name || "Sem envio"} -¢ ${item?.freight_method_name || "Sem frete"}`;

      const okStatus =
        activeStatusTab === "Todos" ? true : itemStatus === activeStatusTab;

      const okShipping =
        activeShippingTab === "Todos" ? true : itemShipping === activeShippingTab;

      return okStatus && okShipping;
    });
  }, [items, activeStatusTab, activeShippingTab, sepMode]);

  const summary = useMemo(
    () => ({
      total: filteredItems.length,
      printed: filteredItems.filter((x) => x.printed).length,
      pending: filteredItems.filter((x) => {
        const s = normalizeSeparationStatus(x);
        return s !== "Separado" && s !== "Entregue" && s !== "Cancelado";
      }).length,
    }),
    [filteredItems]
  );

  const detailOrder = detail?.order || null;
  const detailItems = detail?.items || [];
  const normalizedDetailStatus = detailOrder ? getDisplayStatus(detailOrder, sepMode) : "A separar";
  const detailLabelAllowed = canPrintLabelForMode(detailOrder, sepMode);

  const client = useMemo(() => {
    if (!detailOrder) return {};

    const snapshot = safeJsonParse(detailOrder.client_snapshot, {}) || {};
    const clientName =
      detailOrder.client_name ||
      detailOrder.cliente ||
      detailOrder.customer_name ||
      detailOrder.cliente_nome ||
      snapshot.nome ||
      snapshot.name ||
      snapshot.razao_social ||
      snapshot.razaoSocial ||
      "";

    return {
      ...snapshot,
      nome: clientName || snapshot.nome || snapshot.name || "",
      name: clientName || snapshot.name || snapshot.nome || "",
      razao_social: clientName || snapshot.razao_social || "",
      cpf_cnpj:
        detailOrder.client_document ||
        detailOrder.cpf_cnpj ||
        detailOrder.documento ||
        snapshot.cpf_cnpj ||
        snapshot.cpfCnpj ||
        snapshot.documento ||
        "",
      cpfCnpj:
        detailOrder.client_document ||
        detailOrder.cpf_cnpj ||
        detailOrder.documento ||
        snapshot.cpfCnpj ||
        snapshot.cpf_cnpj ||
        "",
      telefone:
        detailOrder.client_phone ||
        detailOrder.telefone ||
        detailOrder.phone ||
        snapshot.telefone ||
        snapshot.fone ||
        snapshot.phone ||
        "",
      fone:
        detailOrder.client_phone ||
        detailOrder.telefone ||
        detailOrder.phone ||
        snapshot.fone ||
        snapshot.telefone ||
        "",
      email:
        detailOrder.client_email ||
        detailOrder.email ||
        snapshot.email ||
        "",
      endereco:
        detailOrder.client_address ||
        detailOrder.endereco ||
        snapshot.endereco ||
        snapshot.logradouro ||
        "",
      logradouro:
        detailOrder.client_address ||
        snapshot.logradouro ||
        snapshot.endereco ||
        "",
    };
  }, [detailOrder]);

  const totals = useMemo(() => {
    const qtyTotal = detailItems.reduce((acc, item) => acc + Number(item.qty || 0), 0);
    const grossTotal = detailItems.reduce((acc, item) => acc + Number(item.line_total || 0), 0);
    return { qtyTotal, grossTotal };
  }, [detailItems]);

  const hasStartedSeparation = Boolean(
    detailOrder?.started_at ||
    detailMode === "conferencia" ||
    ["Separando", "Separado", "Entregue"].includes(normalizedDetailStatus || "") ||
    (sepMode !== "off" && normalizedDetailStatus === "Conferência")
  );

  const modalOpen = !!detail;
  const busy = detailLoading || savingDetail || !!savingId;
  const autoRefreshPaused = modalOpen || busy;
  const lastRefreshText = lastRefreshAt
    ? lastRefreshAt.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "ainda não atualizado";

  return (
    <div className="separation-page" style={styles.page}>
      <div>
        <PageHeader
          title="Separação"
          actions={
            <div style={{ ...styles.statsCard, flexWrap: "wrap" }}>
              <div>
                <strong>{summary.total}</strong>
                <div style={styles.muted}>Pedidos</div>
              </div>
              <div>
                <strong>{summary.pending}</strong>
                <div style={styles.muted}>Pendentes</div>
              </div>
              <div>
                <strong>{summary.printed}</strong>
                <div style={styles.muted}>Impressos</div>
              </div>
            </div>
          }
        />
        <div style={styles.subtitle}>
          Fila operacional dos pedidos criados a partir do orçamento.
        </div>
      </div>

      <div
        style={{
          border: "1px solid var(--border)",
          background: "var(--card)",
          color: autoRefreshPaused ? "var(--muted)" : "var(--text)",
          padding: "9px 12px",
          fontSize: 12,
          fontWeight: 800,
          borderRadius: 12,
          boxShadow: "0 8px 18px rgba(0,0,0,0.05)",
        }}
      >
        {autoRefreshPaused
          ? "Atualização automática pausada enquanto pedido está aberto, carregando ou salvando."
          : `Atualização automática ativa a cada 15s · Última atualização: ${lastRefreshText}`}
      </div>

      <Card>
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div style={{ ...styles.label, marginBottom: 10 }}>Empresa da separação</div>
            <div style={styles.companyTabsWrap}>
              {SEPARATION_COMPANIES.map((company) => {
                const active = activeCompany === company;
                const isPark = company === "park";
                return (
                  <button
                    key={company}
                    type="button"
                    onClick={() => handleCompanyTabClick(company)}
                    aria-pressed={active}
                    style={{
                      ...styles.companyTab,
                      ...(isPark ? styles.companyTabPark : styles.companyTabParton),
                      ...(active
                        ? isPark
                          ? styles.companyTabActivePark
                          : styles.companyTabActiveParton
                        : {}),
                    }}
                  >
                    {isPark ? "Informática" : "Suprimentos"}
                  </button>
                );
              })}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr auto", gap: 12, alignItems: "end" }}>
            <div>
              <div style={styles.label}>Buscar</div>
              <input
                style={styles.input}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar por número do pedido, cliente ou vendedor"
              />
            </div>

            <Button
              variant="primary"
              onClick={() => setQuery({ q: search.trim() })}
            >
              Buscar
            </Button>
          </div>

          <div>
            <div style={{ ...styles.label, marginBottom: 10 }}>Status</div>
            <div style={styles.topTabsWrap}>
              {statusTabs.map((tab) => {
                const active = activeStatusTab === tab.label;
                return (
                  <button
                    key={tab.label}
                    type="button"
                    onClick={() => {
                      setActiveStatusTab(tab.label);
                      setActiveShippingTab("Todos");
                    }}
                    style={{
                      ...styles.topTab,
                      ...(active ? styles.topTabActive : {}),
                    }}
                  >
                    <div style={styles.topTabLabel}>{tab.label}</div>
                    <div style={styles.topTabCount}>{tab.count}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <div style={{ ...styles.label, marginBottom: 10 }}>Envio / frete</div>
            <div style={styles.subTabsWrap}>
              {shippingTabs.map((tab) => {
                const active = activeShippingTab === tab.label;
                return (
                  <button
                    key={tab.label}
                    type="button"
                    onClick={() => setActiveShippingTab(tab.label)}
                    style={{
                      ...styles.subTab,
                      ...(active ? styles.subTabActive : {}),
                    }}
                  >
                    {tab.label} ({tab.count})
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </Card>

      <Card>
        {error ? <div style={styles.dangerText}>{error}</div> : null}

        <Table>
            <thead>
              <tr>
                <th style={styles.th}>Pedido</th>
                <th style={styles.th}>Cliente</th>
                <th style={styles.th}>Vendedor</th>
                <th style={styles.th}>Envio / Frete</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Impresso</th>
                <th style={styles.th}>Ações</th>
                {isAdmin ? <th style={styles.th}>Admin</th> : null}
              </tr>
            </thead>
            <tbody>
              {loading && filteredItems.length === 0
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={`separation-skeleton-${i}`}>
                      <td style={styles.td} colSpan={isAdmin ? 8 : 7}>
                        <Skeleton height={18} />
                      </td>
                    </tr>
                  ))
                : null}

              {!loading && filteredItems.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 8 : 7} style={{ padding: 0 }}>
                    <EmptyState
                      title="Nenhum pedido na fila de separação."
                      message="Ajuste os filtros ou atualize a fila."
                      action={
                        <Button variant="secondary" onClick={() => load()}>
                          Atualizar
                        </Button>
                      }
                    />
                  </td>
                </tr>
              ) : null}

              {filteredItems.map((item) => {
                const itemCompany = getOrderCompany(item);
                const isSelected = selectedOrderId === item.tiny_order_id && selectedOrderCompany === itemCompany;
                const itemStatus = getDisplayStatus(item, sepMode);
                const cancelled = isCancelledOrder(item);
                const inProgress = itemStatus === "Separando" && !cancelled;
                const labelAllowed = canPrintLabelForMode(item, sepMode);

                return (
                  <tr
                    key={`${itemCompany}:${item.tiny_order_id}`}
                    className={inProgress ? "separation-row--in-progress" : undefined}
                    style={cancelled ? styles.cancelledRow : undefined}
                  >
                    <td style={styles.td}>
                      <div style={{ fontWeight: 800, ...(cancelled ? styles.cancelledText : {}) }}>
                        #{item.tiny_order_number || item.tiny_order_id}
                      </div>
                      <div style={{ marginTop: 6 }}>
                        <CompanyBadge company={itemCompany} />
                      </div>
                      <div style={cancelled ? styles.cancelledText : styles.muted}>
                        {cancelled ? "PEDIDO CANCELADO" : `Orçamento ${item.quote_number || "-"}`}
                      </div>
                    </td>

                    <td style={styles.td}>
                      <span style={cancelled ? styles.cancelledText : undefined}>{item.client_name || "-"}</span>
                    </td>

                    <td style={styles.td}>{item.seller_name || "-"}</td>

                    <td style={styles.td}>
                      <div>{item.shipping_method_name || "-"}</div>
                      <div style={styles.muted}>{item.freight_method_name || "-"}</div>
                    </td>

                    <td style={styles.td}>
                      <StatusBadge status={itemStatus} />
                    </td>

                    <td style={styles.td}>{item.printed ? "Sim" : "Não"}</td>

                    <td style={styles.td}>
                      <div style={styles.toolbar}>
                        <Button
                          variant={isSelected && detailMode === "detail" ? "primary" : "secondary"}
                          onClick={() => openDetails(item.tiny_order_id, itemCompany)}
                        >
                          {isSelected && detailMode === "detail" ? "Detalhe aberto" : "Ver detalhes"}
                        </Button>

                        {!cancelled && itemStatus === "A separar" ? (
                          <Button
                            variant="primary"
                            loading={savingId === item.tiny_order_id || savingId === item.quote_id}
                            onClick={() => printFromList(item)}
                          >
                            Imprimir
                          </Button>
                        ) : null}

                        <Button
                          variant="secondary"
                          disabled={!labelAllowed || savingId === item.tiny_order_id || savingId === item.quote_id}
                          title={!labelAllowed ? "A etiqueta só pode ser impressa após finalizar a separação." : ""}
                          onClick={() => printLabelFromList(item)}
                        >
                          Imprimir Etiqueta
                        </Button>

                        {!cancelled && itemStatus === "Separando" ? (
                          <Button
                            variant="primary"
                            loading={savingId === item.tiny_order_id || savingId === item.quote_id}
                            onClick={() => openOperateFlow(item)}
                          >
                            Iniciar Separação
                          </Button>
                        ) : null}

                        {!cancelled && itemStatus === "Conferência" ? (
                          <button
                            style={{ ...styles.button, ...styles.primaryButton }}
                            disabled={savingId === item.tiny_order_id || savingId === item.quote_id}
                            onClick={() => openConferenceFlow(item)}
                          >
                            Iniciar Conferência
                          </button>
                        ) : null}
                      </div>
                    </td>

                    {isAdmin ? (
                      <td style={styles.td}>
                        <Button
                          variant="danger"
                          loading={savingId === item.tiny_order_id || savingId === item.quote_id}
                          onClick={() => deleteOrderLocal(item)}
                        >
                          Excluir
                        </Button>
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
        </Table>
      </Card>

      {selectedOrderId ? (
        <div
          style={styles.modalOverlay}
          onClick={() => {
            setSelectedOrderId(null);
            setSelectedOrderCompany(null);
            setDetailMode("detail");
            setDetail(null);
            setDetailError("");
          }}
        >
          <div
            style={{
              ...styles.modalPanel,
              width: isMobile ? "100vw" : styles.modalPanel.width,
              maxHeight: isMobile ? "100vh" : styles.modalPanel.maxHeight,
              height: isMobile ? "100vh" : "auto",
              padding: isMobile ? 12 : styles.modalPanel.padding,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ ...styles.detailHeader, ...styles.modalHeaderSticky }}>
              <div>
                <div style={styles.detailTitle}>
                  {detailMode === "operate"
                    ? "Separando Pedido"
                    : detailMode === "conferencia"
                      ? "Conferindo Pedido"
                      : "Detalhe do pedido de separação"}
                </div>
                <div style={styles.detailSub}>
                  {isCancelledOrder(detailOrder)
                    ? "PEDIDO CANCELADO: não separar, não imprimir e devolver os itens para as prateleiras."
                    : detailMode === "operate"
                      ? "Fluxo operacional da separação para o operador de estoque."
                      : detailMode === "conferencia"
                        ? "Confira os itens, revise os dados e finalize a conferência."
                        : "Base operacional para conferência e consulta do pedido."}
                </div>
                {detailOrder ? (
                  <div style={{ marginTop: 8 }}>
                    <CompanyBadge company={detailOrder.company_key || selectedOrderCompany} />
                  </div>
                ) : null}

              </div>

              <div style={styles.toolbar}>
                {!isCancelledOrder(detailOrder) && (detailMode === "operate" || detailMode === "conferencia" || ["Separando", "Separado", "Entregue"].includes(normalizedDetailStatus)) ? (
                  <Button variant="primary" onClick={handlePrint}>
                    Imprimir separação
                  </Button>
                ) : null}

                <Button
                  variant="secondary"
                  disabled={!detailLabelAllowed}
                  title={!detailLabelAllowed ? "A etiqueta só pode ser impressa após finalizar a separação." : ""}
                  onClick={handlePrintLabel}
                >
                  Imprimir Etiqueta
                </Button>

                <Button variant="secondary" onClick={() => openDetails(selectedOrderId, selectedOrderCompany)}>
                  Atualizar detalhe
                </Button>

                <Button
                  variant="secondary"
                  onClick={() => {
                    setSelectedOrderId(null);
                    setSelectedOrderCompany(null);
                    setDetailMode("detail");
                    setDetail(null);
                    setDetailError("");
                  }}
                >
                  Fechar detalhe
                </Button>
              </div>
            </div>

            {detailLoading && !detailOrder ? (
              <div style={{ ...styles.muted, display: "flex", alignItems: "center", gap: 8 }}>
                <Spinner size={16} /> Carregando detalhe...
              </div>
            ) : null}
            {detailLoading && detailOrder ? (
              <div style={{ ...styles.muted, marginBottom: 12 }}>Atualizando detalhes...</div>
            ) : null}
            {detailError ? <div style={styles.dangerText}>{detailError}</div> : null}

            {detailOrder && isCancelledOrder(detailOrder) ? (
              <div style={{ ...styles.card, borderColor: "rgba(239,68,68,.40)", background: "rgba(239,68,68,.10)", color: "var(--danger)", marginBottom: 12 }}>
                <div style={{ fontWeight: 950, fontSize: 14 }}>PEDIDO CANCELADO</div>
                <div style={{ marginTop: 4, fontSize: 13 }}>
                  Não separar, não imprimir e devolver os itens para as prateleiras corretas.
                </div>
              </div>
            ) : null}

            {detailOrder ? (
              <>
                {detailMode === "detail" ? (
                  <>
                    <div style={{ ...styles.card, marginBottom: 16 }}>
                      <div style={{ ...styles.grid4, gridTemplateColumns: isMobile ? "1fr" : isTablet ? "repeat(2, minmax(0, 1fr))" : styles.grid4.gridTemplateColumns }}>
                        <div>
                          <div style={styles.label}>Pedido Tiny</div>
                          <div style={{ fontWeight: 900 }}>
                            #{detailOrder.tiny_order_number || detailOrder.tiny_order_id || "-"}
                          </div>
                        </div>

                        <div>
                          <div style={styles.label}>Orçamento</div>
                          <div style={{ fontWeight: 900 }}>{detailOrder.quote_number || "-"}</div>
                        </div>

                        <div>
                          <div style={styles.label}>Status da separação</div>
                          <StatusBadge status={normalizedDetailStatus} />
                        </div>

                        <div>
                          <div style={styles.label}>Impresso</div>
                          <div style={{ fontWeight: 900 }}>{detailOrder.printed ? "Sim" : "Não"}</div>
                        </div>
                      </div>
                    </div>

                    <div style={{ ...styles.grid2, gridTemplateColumns: isMobile ? "1fr" : styles.grid2.gridTemplateColumns, marginBottom: 16 }}>
                      <InfoBlock
                        title="Cliente"
                        rows={[
                          { label: "Nome", value: pick(client, "nome", "name") || "Consumidor Final" },
                          { label: "CNPJ / CPF", value: pick(client, "cpf_cnpj", "cpfCnpj", "documento") },
                          { label: "Telefone", value: pick(client, "fone", "telefone", "phone") },
                          { label: "E-mail", value: pick(client, "email") },
                          { label: "Endereço", value: buildClientAddress(client).replace(/\n/g, " | ") },
                        ]}
                      />

                      <InfoBlock
                        title="Comercial / envio"
                        rows={[
                          { label: "Vendedor", value: detailOrder.seller_name },
                          { label: "Forma de envio", value: detailOrder.shipping_method_name },
                          { label: "Forma de frete", value: detailOrder.freight_method_name },
                          { label: "Criado em", value: formatDateTime(detailOrder.created_at) },
                          { label: "Atualizado em", value: formatDateTime(detailOrder.updated_at) },
                        ]}
                      />
                    </div>
                  </>
                ) : null}

                {hasStartedSeparation ? (
                  <div style={{ ...styles.grid2, gridTemplateColumns: isMobile ? "1fr" : styles.grid2.gridTemplateColumns, marginBottom: 16 }}>
                    {(detailMode === "operate" || detailMode === "conferencia") ? (
                      <div style={styles.card}>
                        <div style={styles.sectionTitle}>Controle operacional</div>

                        <div style={{ display: "grid", gap: 12 }}>
                          <div>
                            <div style={styles.label}>Status atual</div>
                            <StatusPill status={normalizedDetailStatus || "Separando"} />
                          </div>

                          <div>
                            <div style={styles.label}>Responsável</div>
                            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                              <Button
                                type="button"
                                variant={draftAssignedTo === "Daiana" ? "primary" : "secondary"}
                                onClick={() => setDraftAssignedTo("Daiana")}
                              >
                                Daiana
                              </Button>

                              <Button
                                type="button"
                                variant={draftAssignedTo === "Josiel" ? "primary" : "secondary"}
                                onClick={() => setDraftAssignedTo("Josiel")}
                              >
                                Josiel
                              </Button>
                            </div>
                          </div>

                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                          <div>
                            <div style={styles.label}>Caixas</div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <Button
                                type="button"
                                variant="secondary"
                                onClick={() => setDraftBoxes((v) => Math.max(0, Number(v || 0) - 1))}
                              >
                                -
                              </Button>
                              <input
                                style={{ ...styles.input, textAlign: "center" }}
                                type="number"
                                min="0"
                                value={draftBoxes}
                                onChange={(e) => setDraftBoxes(Number(e.target.value || 0))}
                              />
                              <Button
                                type="button"
                                variant="secondary"
                                onClick={() => setDraftBoxes((v) => Number(v || 0) + 1)}
                              >
                                +
                              </Button>
                            </div>
                          </div>

                          <div>
                            <div style={styles.label}>Sacolas</div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <Button
                                type="button"
                                variant="secondary"
                                onClick={() => setDraftBags((v) => Math.max(0, Number(v || 0) - 1))}
                              >
                                -
                              </Button>
                              <input
                                style={{ ...styles.input, textAlign: "center" }}
                                type="number"
                                min="0"
                                value={draftBags}
                                onChange={(e) => setDraftBags(Number(e.target.value || 0))}
                              />
                              <Button
                                type="button"
                                variant="secondary"
                                onClick={() => setDraftBags((v) => Number(v || 0) + 1)}
                              >
                                +
                              </Button>
                            </div>
                          </div>
                          </div>

                          <div style={styles.card}>
                            <div style={styles.sectionTitle}>Dados da caixa / volume</div>
                            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(6, minmax(0, 1fr))", gap: 10 }}>
                              <div>
                                <div style={styles.label}>Total de produtos</div>
                                <input
                                  style={{ ...styles.input, opacity: 0.78 }}
                                  type="text"
                                  value={Number(totals.qtyTotal || 0).toLocaleString("pt-BR")}
                                  readOnly
                                />
                                <div style={{ ...styles.muted, marginTop: 4 }}>Soma automática dos itens.</div>
                              </div>
                              <div>
                                <div style={styles.label}>Peso (kg)</div>
                                <input
                                  style={styles.input}
                                  type="number"
                                  min="0"
                                  step="0.001"
                                  value={draftWeightKg}
                                  onChange={(e) => setDraftWeightKg(e.target.value)}
                                  placeholder="Ex.: 2,350"
                                />
                              </div>
                              <div>
                                <div style={styles.label}>Altura (cm)</div>
                                <input
                                  style={styles.input}
                                  type="number"
                                  min="0"
                                  step="0.1"
                                  value={draftHeightCm}
                                  onChange={(e) => setDraftHeightCm(e.target.value)}
                                  placeholder="Ex.: 30"
                                />
                              </div>
                              <div>
                                <div style={styles.label}>Largura (cm)</div>
                                <input
                                  style={styles.input}
                                  type="number"
                                  min="0"
                                  step="0.1"
                                  value={draftWidthCm}
                                  onChange={(e) => setDraftWidthCm(e.target.value)}
                                  placeholder="Ex.: 20"
                                />
                              </div>
                              <div>
                                <div style={styles.label}>Comprimento (cm)</div>
                                <input
                                  style={styles.input}
                                  type="number"
                                  min="0"
                                  step="0.1"
                                  value={draftLengthCm}
                                  onChange={(e) => setDraftLengthCm(e.target.value)}
                                  placeholder="Ex.: 40"
                                />
                              </div>
                              <div>
                                <div style={styles.label}>Volume total físico</div>
                                <input
                                  style={styles.input}
                                  type="number"
                                  min="0"
                                  step="1"
                                  value={draftVolumes}
                                  onChange={(e) => setDraftVolumes(e.target.value)}
                                  placeholder="Caixas/sacolas/pacotes"
                                />
                                <div style={{ ...styles.muted, marginTop: 4 }}>Usado para etiquetas 1/N.</div>
                              </div>
                            </div>
                          </div>

                          {sepMode !== "off" ? (
                            <div style={styles.card}>
                              <div style={styles.sectionTitle}>
                                {detailMode === "conferencia" ? "Fotos" : "Foto da separação"}
                              </div>
                              <div style={{ display: "grid", gridTemplateColumns: detailMode === "conferencia" && !isMobile ? "1fr 1fr" : "1fr", gap: 12 }}>
                                {detailMode === "conferencia" ? (
                                  <PhotoField
                                    label="Foto do separador"
                                    value={draftSeparationPhoto}
                                    readOnly
                                  />
                                ) : (
                                  <PhotoField
                                    label={sepMode === "strict" ? "Foto da separação (obrigatória)" : "Foto da separação (opcional)"}
                                    value={draftSeparationPhoto}
                                    onChange={setDraftSeparationPhoto}
                                    disabled={savingDetail || isCancelledOrder(detailOrder)}
                                  />
                                )}
                                {detailMode === "conferencia" ? (
                                  <PhotoField
                                    label="Foto da conferência (opcional)"
                                    value={draftConferencePhoto}
                                    onChange={setDraftConferencePhoto}
                                    disabled={savingDetail || isCancelledOrder(detailOrder)}
                                  />
                                ) : null}
                              </div>
                            </div>
                          ) : null}

                          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                              <input
                                type="checkbox"
                                checked={draftPrinted}
                                onChange={(e) => setDraftPrinted(e.target.checked)}
                              />
                              <span style={{ fontWeight: 700 }}>Marcar como impresso</span>
                            </label>

                            <Button
                              type="button"
                              variant="secondary"
                              onClick={() => setDraftPrinted((v) => !v)}
                            >
                              {draftPrinted ? "Desmarcar impresso" : "Marcar impresso"}
                            </Button>
                          </div>

                          <div>
                            <div style={styles.label}>Observações internas</div>
                            <textarea
                              style={styles.textarea}
                              value={draftNotes}
                              onChange={(e) => setDraftNotes(e.target.value)}
                              placeholder="Observações da operação, conferência, volumes, pendências ou recados internos..."
                            />
                          </div>

                          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                            <Button
                              variant="secondary"
                              loading={savingDetail}
                              onClick={saveDetail}
                              disabled={savingDetail || isCancelledOrder(detailOrder)}
                            >
                              {savingDetail ? "Salvando..." : "Salvar rascunho"}
                            </Button>

                            <Button
                              variant="primary"
                              loading={savingDetail}
                              onClick={detailMode === "conferencia" ? finalizeConference : finalizeSeparation}
                              disabled={savingDetail || isCancelledOrder(detailOrder)}
                            >
                              {savingDetail
                                ? "Finalizando..."
                                : detailMode === "conferencia"
                                  ? "Finalizar Conferência"
                                  : sepMode === "off"
                                    ? "Finalizar Separação"
                                    : "Enviar para Conferência"}
                            </Button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <InfoBlock
                        title="Controle operacional"
                        rows={[
                          { label: "Status", value: normalizedDetailStatus || "-" },
                          { label: "Responsável", value: detailOrder.assigned_to || "-" },
                          { label: "Caixas", value: String(detailOrder.packaging_boxes ?? 0) },
                          { label: "Sacolas", value: String(detailOrder.packaging_bags ?? 0) },
                          { label: "Peso", value: formatDecimal(detailOrder.packaging_weight_kg, " kg") },
                          { label: "Medidas", value: `${formatDecimal(detailOrder.packaging_length_cm, " cm")} x ${formatDecimal(detailOrder.packaging_width_cm, " cm")} x ${formatDecimal(detailOrder.packaging_height_cm, " cm")}` },
                          { label: "Volumes", value: String(detailOrder.packaging_volumes ?? "-") },
                          { label: "Impresso", value: detailOrder.printed ? "Sim" : "Não" },
                          { label: "Observações", value: detailOrder.separation_notes || "-" },
                        ]}
                      />
                    )}

                    <InfoBlock
                      title="Marcos da separação"
                      rows={[
                        { label: "Iniciado em", value: formatDateTime(detailOrder.started_at) },
                        { label: "Impresso em", value: formatDateTime(detailOrder.printed_at) },
                        { label: "Separado em", value: formatDateTime(detailOrder.separated_at) },
                        { label: "Caixas", value: String(detailOrder.packaging_boxes ?? 0) },
                        { label: "Sacolas", value: String(detailOrder.packaging_bags ?? 0) },
                        { label: "Peso", value: formatDecimal(detailOrder.packaging_weight_kg, " kg") },
                        { label: "Medidas", value: `${formatDecimal(detailOrder.packaging_length_cm, " cm")} x ${formatDecimal(detailOrder.packaging_width_cm, " cm")} x ${formatDecimal(detailOrder.packaging_height_cm, " cm")}` },
                        { label: "Volumes", value: String(detailOrder.packaging_volumes ?? "-") },
                        { label: "Notas do orçamento", value: detailOrder.notes || "-" },
                      ]}
                    />
                  </div>
                ) : null}

                {detailMode === "detail" ? (
                  <div style={styles.card}>
                    <div style={styles.detailHeader}>
                      <div>
                        <div style={{ ...styles.sectionTitle, marginBottom: 4 }}>
                          Itens do pedido
                        </div>
                        <div style={styles.muted}>
                          Quantidade total: <strong>{totals.qtyTotal}</strong> -¢ Valor total:{" "}
                          <strong>{money(totals.grossTotal)}</strong>
                        </div>
                      </div>
                    </div>

                    <Table>
                        <thead>
                          <tr>
                            <th style={styles.th}>Linha</th>
                            <th style={styles.th}>SKU</th>
                            <th style={styles.th}>Produto</th>
                            <th style={styles.th}>Marca</th>
                            <th style={styles.th}>Categoria</th>
                            <th style={styles.th}>Localização</th>
                            <th style={styles.th} data-numeric>Qtd</th>
                            <th style={styles.th} data-numeric>Unitário</th>
                            <th style={styles.th} data-numeric>Total</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detailItems.length === 0 ? (
                            <tr>
                              <td colSpan={9} style={{ padding: 0 }}>
                                <EmptyState title="Nenhum item encontrado para este pedido." />
                              </td>
                            </tr>
                          ) : null}

                          {detailItems.map((item, idx) => {
                            const meta = getProductMeta(item);

                            return (
                              <tr key={`${item.quote_id}-${item.line}-${idx}`}>
                                <td style={styles.td}>{item.line ?? idx + 1}</td>
                                <td style={styles.td}>{item.sku_snapshot || "-"}</td>
                                <td style={styles.td}>
                                  <div style={{ fontWeight: 700 }}>{item.name_snapshot || "-"}</div>
                                  <div style={styles.muted}>Produto ID: {item.product_id || "-"}</div>
                                </td>
                                <td style={styles.td}>{meta.brand}</td>
                                <td style={styles.td}>{meta.category}</td>
                                <td style={styles.td}>{meta.location}</td>
                                <td style={styles.td} data-numeric>{Number(item.qty || 0)}</td>
                                <td style={styles.td} data-numeric>{money(item.unit_price_disc || 0)}</td>
                                <td style={styles.td} data-numeric>{money(item.line_total || 0)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                    </Table>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
if (typeof window !== "undefined" && !window.__trmlSeparationDetailPatchInstalled) {
  window.__trmlSeparationDetailPatchInstalled = true;

  const TRML_SEPARATION_DETAIL_RE = /\/(api\/)?separation\/orders\/\d+/i;

  const normalizeText = (value) => {
    if (value === null || value === undefined) return "";
    return String(value).trim();
  };

  const firstNonEmpty = (...values) => {
    for (const value of values) {
      const text = normalizeText(value);
      if (text && text !== "-" && text.toLowerCase() !== "consumidor final") {
        return text;
      }
    }
    return "";
  };

  const getPath = (obj, path) => {
    let current = obj;
    for (const key of path) {
      if (!current || typeof current !== "object") return "";
      current = current[key];
    }
    return current == null ? "" : current;
  };

  const buildAddress = (sources) => {
    const source = sources.find((item) => item && typeof item === "object") || {};
    const street = firstNonEmpty(source.logradouro, source.endereco, source.street, source.address);
    const number = firstNonEmpty(source.numero, source.number);
    const complement = firstNonEmpty(source.complemento, source.complement);
    const neighborhood = firstNonEmpty(source.bairro, source.district);
    const city = firstNonEmpty(source.cidade, source.city);
    const uf = firstNonEmpty(source.uf, source.estado, source.state);
    const cep = firstNonEmpty(source.cep, source.zip_code, source.postal_code);

    const parts = [];
    if (street) {
      let line = street;
      if (number) line += `, ${number}`;
      if (complement) line += ` - ${complement}`;
      parts.push(line);
    }
    if (neighborhood) parts.push(neighborhood);
    if (city && uf) parts.push(`${city}/${uf}`);
    else if (city) parts.push(city);
    else if (uf) parts.push(uf);
    if (cep) parts.push(`CEP ${cep}`);
    return parts.join(" | ");
  };

  const enrichSeparationDetail = (payload) => {
    if (!payload || typeof payload !== "object") return payload;

    const topOrder = payload.order && typeof payload.order === "object" ? { ...payload.order } : null;
    const order = topOrder || { ...payload };
    const payloadClient = getPath(payload, ["payload", "cliente"]) || getPath(payload, ["payload", "customer"]) || {};
    const orderPayload = getPath(order, ["payload"]) || getPath(payload, ["payload"]) || {};
    const clientSnapshot = order.client_snapshot || payload.client_snapshot || {};
    const clientFromOrder = order.client || payload.client || {};
    const clientName = firstNonEmpty(
      getPath(clientSnapshot, ["name"]),
      getPath(clientSnapshot, ["nome"]),
      getPath(clientSnapshot, ["razao_social"]),
      getPath(payloadClient, ["nome"]),
      getPath(payloadClient, ["razao_social"]),
      getPath(orderPayload, ["cliente", "nome"]),
      getPath(orderPayload, ["cliente", "razao_social"]),
      getPath(orderPayload, ["customer", "name"]),
      getPath(clientFromOrder, ["name"]),
      getPath(clientFromOrder, ["nome"]),
      order.client_name,
      order.cliente,
      order.customer_name,
      payload.client_name,
      payload.cliente,
      payload.customer_name
    ) || "Consumidor Final";

    const clientDocument = firstNonEmpty(
      getPath(clientSnapshot, ["cpf_cnpj"]),
      getPath(clientSnapshot, ["cpf"]),
      getPath(clientSnapshot, ["cnpj"]),
      getPath(clientSnapshot, ["documento"]),
      getPath(payloadClient, ["cpf_cnpj"]),
      getPath(payloadClient, ["cpf"]),
      getPath(payloadClient, ["cnpj"]),
      getPath(payloadClient, ["documento"]),
      getPath(orderPayload, ["cliente", "cpf_cnpj"]),
      getPath(orderPayload, ["cliente", "cpf"]),
      getPath(orderPayload, ["cliente", "cnpj"]),
      getPath(orderPayload, ["cliente", "documento"]),
      order.client_document,
      order.document,
      order.cpf_cnpj,
      payload.client_document,
      payload.document,
      payload.cpf_cnpj
    );

    const clientPhone = firstNonEmpty(
      getPath(clientSnapshot, ["telefone"]),
      getPath(clientSnapshot, ["phone"]),
      getPath(clientSnapshot, ["celular"]),
      getPath(payloadClient, ["telefone"]),
      getPath(payloadClient, ["phone"]),
      getPath(payloadClient, ["celular"]),
      getPath(orderPayload, ["cliente", "telefone"]),
      getPath(orderPayload, ["cliente", "phone"]),
      getPath(orderPayload, ["cliente", "celular"]),
      order.client_phone,
      order.phone,
      payload.client_phone,
      payload.phone
    );

    const clientEmail = firstNonEmpty(
      getPath(clientSnapshot, ["email"]),
      getPath(payloadClient, ["email"]),
      getPath(orderPayload, ["cliente", "email"]),
      getPath(orderPayload, ["customer", "email"]),
      order.client_email,
      order.email,
      payload.client_email,
      payload.email
    );

    const clientAddress = firstNonEmpty(
      buildAddress([
        getPath(clientSnapshot, ["address"]),
        getPath(clientSnapshot, ["endereco"]),
        getPath(payloadClient, ["address"]),
        getPath(payloadClient, ["endereco"]),
        getPath(orderPayload, ["cliente", "address"]),
        getPath(orderPayload, ["cliente", "endereco"]),
        getPath(orderPayload, ["customer", "address"]),
        order.client_address,
        order.address,
        payload.client_address,
        payload.address,
      ]),
      order.client_address,
      order.address,
      payload.client_address,
      payload.address
    );

    const sellerName = firstNonEmpty(
      order.seller_name,
      order.salesperson_name,
      order.vendedor,
      payload.seller_name,
      payload.salesperson_name,
      payload.vendedor
    );
    const shippingMethodName = firstNonEmpty(
      order.shipping_method_name,
      order.shipping_method,
      order.envio,
      payload.shipping_method_name,
      payload.shipping_method,
      payload.envio
    );
    const freightMethodName = firstNonEmpty(
      order.freight_method_name,
      order.freight_method,
      order.frete,
      payload.freight_method_name,
      payload.freight_method,
      payload.frete,
      shippingMethodName
    );

    order.client_name = clientName;
    order.cliente = clientName;
    order.customer_name = clientName;
    order.client_document = clientDocument || "";
    order.document = clientDocument || "";
    order.cpf_cnpj = clientDocument || "";
    order.client_phone = clientPhone || "";
    order.phone = clientPhone || "";
    order.client_email = clientEmail || "";
    order.email = clientEmail || "";
    order.client_address = clientAddress || "";
    order.address = clientAddress || "";
    order.seller_name = sellerName || order.seller_name || "";
    order.shipping_method_name = shippingMethodName || order.shipping_method_name || "";
    order.freight_method_name = freightMethodName || order.freight_method_name || "";
    order.client_snapshot = clientSnapshot || order.client_snapshot || {};
    order.client = clientFromOrder || order.client || {};

    const nextPayload = topOrder ? { ...payload, order } : { ...order };
    nextPayload.client_name = order.client_name;
    nextPayload.cliente = order.cliente;
    nextPayload.customer_name = order.customer_name;
    nextPayload.client_document = order.client_document;
    nextPayload.document = order.document;
    nextPayload.cpf_cnpj = order.cpf_cnpj;
    nextPayload.client_phone = order.client_phone;
    nextPayload.phone = order.phone;
    nextPayload.client_email = order.client_email;
    nextPayload.email = order.email;
    nextPayload.client_address = order.client_address;
    nextPayload.address = order.address;
    nextPayload.seller_name = order.seller_name;
    nextPayload.shipping_method_name = order.shipping_method_name;
    nextPayload.freight_method_name = order.freight_method_name;
    nextPayload.client_snapshot = order.client_snapshot;
    nextPayload.client = order.client;
    return nextPayload;
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const [input, init] = args;
    const response = await originalFetch(...args);
    try {
      const url = typeof input === "string" ? input : input?.url || "";
      const method = (init?.method || (typeof input === "object" && input?.method) || "GET").toUpperCase();
      if (method === "GET" && TRML_SEPARATION_DETAIL_RE.test(url) && response.ok) {
        const clone = response.clone();
        const data = await clone.json().catch(() => null);
        if (data && typeof data === "object") {
          const enriched = enrichSeparationDetail(data);
          return new Response(JSON.stringify(enriched), {
            status: response.status,
            statusText: response.statusText,
            headers: response.headers,
          });
        }
      }
    } catch {
      // keep original response
    }
    return response;
  };
}

