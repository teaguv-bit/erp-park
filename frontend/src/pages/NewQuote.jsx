import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { api } from "../api";
import QuotesModal from "../components/QuotesModal";
import { auth } from "../firebase";
import { openQuotePrintWindow } from "../utils/quotePrint";
import { withGlobalLoading } from "../utils/globalLoading";
import { PageHeader, Button, Card } from "../ui";

const MAX_DISCOUNT_PCT = 33.33;
const PRODUCT_SEARCH_LIMIT = 20;

function formatBRL(n) {
  const v = Number(n || 0);
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
function formatDateBR(s) {
  if (!s) return "";
  try {
    const d = new Date(s);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const yy = d.getFullYear();
    return `${dd}/${mm}/${yy}`;
  } catch {
    return "";
  }
}
function toNum(x) {
  if (x === null || x === undefined || x === "") return 0;
  const s = String(x).replace(",", ".");
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}
function clamp(n, a, b) {
  return Math.max(a, Math.min(b, n));
}
function useDebounced(value, delayMs = 350) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}
function getDraftStorageKey() {
  const user = auth?.currentUser;
  const ident = user?.email || user?.uid || "anon";
  const company = api?.getCurrentCompany?.() || "parton";
  return `prevenda:newquote:draft:${String(company).toLowerCase()}:${ident}`;
}

function getLegacyDraftStorageKey() {
  const user = auth?.currentUser;
  const ident = user?.email || user?.uid || "anon";
  return `prevenda:newquote:draft:${ident}`;
}

function safeJsonParse(raw, fallback) {
  try {
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}


function extractStockInfo(payload) {
  const r = payload || {};
  const raw = r?.raw || {};
  const saldoDisponivel = toNum(
    r?.saldoDisponivel ??
      raw?.saldoDisponivel ??
      raw?.saldo_disponivel ??
      raw?.["saldo_disponivel"] ??
      raw?.["saldo disponível"] ??
      raw?.["saldo_disponível"] ??
      0
  );

  const deposito =
    raw?.deposito_nome ??
    raw?.deposito ??
    raw?.nomeDeposito ??
    raw?.nome_deposito ??
    raw?.descricaoDeposito ??
    "";

  return {
    saldoDisponivel,
    disponivel: saldoDisponivel,
    deposito: String(deposito || ""),
  };
}

function extractCostPrice(product) {
  const p = product || {};
  const raw = p?.raw || {};

  const candidates = [
    p?.preco_custo,
    p?.precoCusto,
    p?.custo,
    p?.custo_unitario,
    p?.custoUnitario,
    p?.preco_custo_medio,
    p?.precoCustoMedio,

    raw?.preco_custo,
    raw?.precoCusto,
    raw?.custo,
    raw?.custo_unitario,
    raw?.custoUnitario,
    raw?.preco_custo_medio,
    raw?.precoCustoMedio,

    raw?.produto?.preco_custo,
    raw?.produto?.precoCusto,
    raw?.produto?.custo,
    raw?.produto?.custo_unitario,
    raw?.produto?.custoUnitario,
    raw?.produto?.preco_custo_medio,
    raw?.produto?.precoCustoMedio,
  ];

  for (const value of candidates) {
    const n = toNum(value);
    if (n > 0) return n;
  }
  return 0;
}

function formatPct(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return `${v.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

function calcMarkupPct(unitPrice, costPrice) {
  const venda = toNum(unitPrice);
  const custo = toNum(costPrice);
  if (custo <= 0) return null;
  return ((venda - custo) / custo) * 100;
}

function normalizePaymentKind(method) {
  const normalize = (v) =>
    String(v || "")
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");

  const code = normalize(method?.code || method || "");
  const name = normalize(method?.name || "");

  const text = `${code} ${name}`;

  if (text.includes("link") && text.includes("pag")) return "link_pagamento";
  if (text.includes("pix")) return "pix";
  if (text.includes("boleto")) return "boleto";
  if (text.includes("cart") && text.includes("cred")) return "cartao_credito";
  if (text.includes("credito")) return "cartao_credito";
  if (text.includes("cart") && text.includes("deb")) return "cartao_debito";
  if (text.includes("debito")) return "cartao_debito";
  if (text.includes("dinheiro")) return "dinheiro";
  if (text.includes("vale") && text.includes("troca")) return "vale_troca";
  if (text.includes("mult") || text.includes("multipl")) return "multiplas";
  if (text.includes("credi")) return "crediario";
  return code;
}

const styles = {
  page: {
    minHeight: "100vh",
    background: "var(--bg)",
    fontFamily: "Inter, system-ui, Arial, sans-serif",
    color: "var(--text)",
  },
  container: {
    maxWidth: 1540,
    width: "calc(100vw - 280px)",
    margin: "0 auto",
    padding: "20px 16px 44px",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    marginBottom: 18,
    minHeight: 28,
    padding: "18px 20px",
    border: "1px solid var(--border)",
    borderRadius: 22,
    background: "var(--card)",
    boxShadow: "0 16px 36px rgba(0,0,0,0.14)",
  },

  title: {
    margin: 0,
    fontSize: 30,
    fontWeight: 900,
    letterSpacing: "-0.04em",
    lineHeight: 1.1,
  },
  button: {
    minHeight: 42,
    padding: "0 14px",
    borderRadius: 12,
    border: "1px solid var(--border)",
    background: "var(--input-bg-soft)",
    cursor: "pointer",
    fontWeight: 800,
    fontSize: 13,
    color: "var(--text)",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "background .15s ease, border-color .15s ease, opacity .15s ease, transform .06s ease, box-shadow .15s ease",
    boxShadow: "0 8px 18px rgba(0,0,0,0.10)",
  },
  primaryBtn: {
    width: "100%",
    minHeight: 44,
    padding: "0 16px",
    boxSizing: "border-box",
    borderRadius: 12,
    border: "1px solid rgba(147,197,253,0.58)",
    background: "linear-gradient(180deg, var(--primary), var(--primary-strong))",
    color: "#fff",
    cursor: "pointer",
    fontWeight: 900,
    fontSize: 14,
    letterSpacing: ".01em",
    boxShadow: "0 12px 24px rgba(47,109,246,0.20)",
  },
  alertErr: {
    background: "rgba(239,68,68,.10)",
    border: "1px solid rgba(239,68,68,.28)",
    color: "#fda4af",
    padding: "11px 14px",
    borderRadius: 16,
    marginBottom: 12,
    fontSize: 13,
    fontWeight: 700,
  },
  alertOk: {
    background: "rgba(34,197,94,.10)",
    border: "1px solid rgba(34,197,94,.24)",
    color: "#86efac",
    padding: "11px 14px",
    borderRadius: 16,
    marginBottom: 12,
    fontSize: 13,
    fontWeight: 700,
  },
  section: {
    border: "1px solid var(--border)",
    borderRadius: 20,
    padding: "16px",
    marginBottom: 0,
    background: "var(--card)",
    boxShadow: "0 14px 30px rgba(0,0,0,0.10)",
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: 900,
    margin: 0,
    letterSpacing: ".14em",
    textTransform: "uppercase",
    color: "var(--muted)",
  },
  input: {
    width: "100%",
    height: 42,
    padding: "0 12px",
    borderRadius: 12,
    border: "1px solid var(--border)",
    outline: "none",
    boxSizing: "border-box",
    background: "var(--input-bg)",
    color: "var(--text)",
    fontSize: 14,
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)",
    transition: "border-color .15s ease, background .15s ease, box-shadow .15s ease",
  },
  select: {
    width: "100%",
    height: 42,
    padding: "0 12px",
    borderRadius: 12,
    border: "1px solid var(--border)",
    background: "var(--input-bg)",
    outline: "none",
    boxSizing: "border-box",
    color: "var(--text)",
    fontSize: 14,
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)",
    transition: "border-color .15s ease, background .15s ease, box-shadow .15s ease",
  },
  small: {
    fontSize: 12,
    color: "var(--muted)",
    lineHeight: 1.35,
  },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    minWidth: 0,
    flexWrap: "wrap",
  },
  listBox: {
    border: "1px solid var(--border)",
    borderRadius: 16,
    overflow: "hidden",
    maxHeight: 260,
    overflowY: "auto",
    marginTop: 8,
    background: "var(--card)",
  },
  listItem: {
    padding: 12,
    borderTop: "1px solid rgba(148,163,184,0.10)",
  },
  tableWrap: {
    border: "1px solid var(--border)",
    borderRadius: 18,
    overflow: "hidden",
    overflowX: "auto",
    marginTop: 8,
    background: "var(--card)",
    boxShadow: "0 14px 30px rgba(0,0,0,0.10)",
  },
  tableHeader: {
    display: "grid",
    gridTemplateColumns: "40px minmax(430px, 1fr) 64px 96px 72px 104px 84px 92px 40px",
    gap: 8,
    padding: "12px 12px",
    background: "var(--table-header)",
    borderBottom: "1px solid var(--border)",
    fontWeight: 900,
    fontSize: 11,
    letterSpacing: ".08em",
    color: "var(--text)",
    alignItems: "center",
    textTransform: "uppercase",
  },
  tableRow: {
    display: "grid",
    gridTemplateColumns: "40px minmax(430px, 1fr) 64px 96px 72px 104px 84px 92px 40px",
    gap: 8,
    padding: "12px 12px",
    borderBottom: "1px solid var(--border)",
    alignItems: "center",
    minHeight: 64,
  },
  numInput: {
    width: "100%",
    height: 38,
    padding: "0 10px",
    borderRadius: 12,
    border: "1px solid var(--border)",
    boxSizing: "border-box",
    background: "var(--input-bg)",
    color: "var(--text)",
    fontSize: 14,
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)",
    transition: "border-color .15s ease, background .15s ease, box-shadow .15s ease",
  },
  textarea: {
    width: "100%",
    padding: 12,
    borderRadius: 12,
    border: "1px solid var(--border)",
    resize: "vertical",
    minHeight: 110,
    boxSizing: "border-box",
    background: "var(--input-bg)",
    color: "var(--text)",
    fontSize: 14,
    lineHeight: 1.45,
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)",
    transition: "border-color .15s ease, background .15s ease, box-shadow .15s ease",
  },
  summaryBox: {
    border: "1px solid var(--border)",
    borderRadius: 18,
    padding: "14px 16px",
    background: "var(--card)",
    boxShadow: "0 12px 28px rgba(0,0,0,0.10)",
  },
  summaryLine: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    padding: "2px 0",
    fontWeight: 900,
    fontSize: 15,
  },
  ellipsis: {
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    minWidth: 0,
  },
};

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


// âœ… Modal de consulta de estoque (somente leitura)
function StockModal({ open, onClose, api, preloadStockForProducts, stockById, formatBRL }) {
  const [q, setQ] = useState("");
  const debQ = useDebounced(q, 300);

  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [err, setErr] = useState("");

  const PAGE_SIZE = 10;
  const [page, setPage] = useState(1);

  const isSearching = (debQ || "").trim().length >= 2;
  const qTrim = (debQ || "").trim();

  // ao abrir: reset
  useEffect(() => {
    if (!open) return;
    setQ("");
    setResults([]);
    setErr("");
    setPage(1);
  }, [open]);

  // se mudou o termo, volta pra página 1
  useEffect(() => {
    if (!open) return;
    setPage(1);
  }, [qTrim, open]);

  // carrega lista (modo inicial) ou busca (modo pesquisa) + paginação
  useEffect(() => {
    let cancelled = false;

    async function run() {
      if (!open) return;

      setLoading(true);
      setErr("");

      try {
        let r;

        if (isSearching) {
          // modo busca (paginado)
          r = await api.tinyProducts(qTrim, page);
        } else {
          // modo inicial (paginado) â€” query vazia => /tiny/products?page=N
          r = await api.tinyProducts("", page);
        }

        if (cancelled) return;

        const list = (r?.items || [])
          .slice()
          .sort((a, b) =>
            String(a?.nome || "").localeCompare(String(b?.nome || ""), "pt-BR")
          );

        setResults(list);
        preloadStockForProducts(list, PAGE_SIZE, 2);
      } catch (e) {
        if (!cancelled) setErr(e?.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    run();
    return () => {
      cancelled = true;
    };
  }, [open, isSearching, qTrim, page, api, preloadStockForProducts]);

  if (!open) return null;

  const canPrev = page > 1 && !loading;
  const canNext = !loading; // âœ… não trava mais por tamanho

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        zIndex: 70,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: "min(980px, 96vw)",
          height: "min(760px, 92vh)",
          background: "var(--card)",
          borderRadius: 22,
          border: "1px solid var(--border)",
          overflow: "hidden",
          display: "grid",
          gridTemplateRows: "auto auto 1fr",
          color: "var(--text)",
          boxShadow: "0 24px 54px rgba(0,0,0,0.24)",
        }}
      >
        <div
          style={{
            padding: 12,
            borderBottom: "1px solid var(--border)",
            display: "flex",
            justifyContent: "space-between",
            gap: 10,
          }}
        >
          <div>
            <div style={{ fontWeight: 900, fontSize: 16 }}>Consulta de Estoque</div>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              {isSearching ? `Pesquisando: "${qTrim}"` : "Lista geral (A-Z)"} • página {page}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              padding: "9px 12px",
              borderRadius: 12,
              border: "1px solid var(--border)",
              background: "var(--input-bg-soft)",
              fontWeight: 900,
              color: "var(--text)",
              cursor: "pointer",
            }}
          >
            Fechar
          </button>
        </div>

        <div style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar produto (nome ou SKU)…"
            style={{
              width: "100%",
              height: 42,
              padding: "0 12px",
              borderRadius: 12,
              border: "1px solid var(--border)",
              outline: "none",
              background: "var(--input-bg)",
              color: "var(--text)",
              boxSizing: "border-box",
            }}
          />

          {loading ? (
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>Carregando…</div>
          ) : null}
          {err ? (
            <div style={{ fontSize: 12, color: "#ef4444", marginTop: 8 }}>Erro: {err}</div>
          ) : null}

          {/* paginação */}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={!canPrev}
              style={{
                padding: "7px 10px",
                borderRadius: 12,
                border: "1px solid var(--border)",
                background: "var(--input-bg-soft)",
                cursor: canPrev ? "pointer" : "not-allowed",
                fontWeight: 900,
                color: "var(--text)",
                opacity: canPrev ? 1 : 0.5,
              }}
            >
              Anterior
            </button>

            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={!canNext}
              style={{
                padding: "7px 10px",
                borderRadius: 12,
                border: "1px solid var(--border)",
                background: "var(--input-bg-soft)",
                cursor: canNext ? "pointer" : "not-allowed",
                fontWeight: 900,
                color: "var(--text)",
                opacity: canNext ? 1 : 0.5,
              }}
            >
              Próxima
            </button>
          </div>
        </div>

        <div style={{ padding: 12, overflow: "auto" }}>
          {!results.length && !loading ? (
            <div style={{ fontSize: 12, color: "var(--muted)" }}>(nenhum resultado)</div>
          ) : null}

          {results.map((p) => {
            const estoque =
              stockById[p.id]?.saldoDisponivel ??
              p.saldoDisponivel ??
              p.raw?.saldoDisponivel ??
              0;

            return (
              <div
                key={p.id}
                style={{
                  padding: 12,
                  border: "1px solid var(--border)",
                  borderRadius: 14,
                  marginBottom: 10,
                  background: "var(--card)",
                }}
              >
                <div style={{ fontWeight: 900, marginBottom: 4 }}>{p.nome}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>
                  {p.codigo || ""} • {formatBRL(p.preco || 0)} • estoque disponível: <b>{estoque}</b>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// -------- Parcelas --------
function addDays(date, days) {
  const d = new Date(date.getTime());
  d.setDate(d.getDate() + days);
  return d;
}
function addMonths(date, months) {
  const d = new Date(date.getTime());
  const day = d.getDate();
  d.setMonth(d.getMonth() + months);
  if (d.getDate() !== day) d.setDate(0);
  return d;
}
function toISODate(d) {
  const x = new Date(d);
  const y = x.getFullYear();
  const m = String(x.getMonth() + 1).padStart(2, "0");
  const dd = String(x.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function todayLocalISODate() {
  return toISODate(new Date());
}
function clampNotPastISODate(value) {
  const today = todayLocalISODate();
  const raw = String(value || "").trim();
  if (!raw) return today;
  return raw < today ? today : raw;
}
function round2(n) {
  return Math.round((Number(n) + Number.EPSILON) * 100) / 100;
}
function splitEven(total, n) {
  const t = round2(total);
  if (n <= 1) return [t];
  const base = round2(t / n);
  const arr = Array.from({ length: n }, () => base);
  const sum = round2(arr.reduce((a, b) => a + b, 0));
  const diff = round2(t - sum);
  arr[n - 1] = round2(arr[n - 1] + diff);
  return arr;
}
function parsePaymentCondition(raw) {
  const s = String(raw || "").trim().toLowerCase();
  if (!s || s === "0" || s === "avista" || s === "à  vista" || s === "a vista")
    return { kind: "avista" };

  const m = s.match(/(\d{1,2})\s*x/);
  if (m) {
    const n = clamp(parseInt(m[1], 10) || 1, 1, 24);
    return { kind: "nx", n };
  }

  const nums = s
    .replaceAll(",", " ")
    .replaceAll("/", " ")
    .split(/\s+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => parseInt(x, 10))
    .filter((x) => Number.isFinite(x) && x >= 0 && x <= 3650);

  if (nums.length) {
    if (nums.length === 1 && nums[0] === 0) return { kind: "avista" };
    const days = Array.from(new Set(nums)).sort((a, b) => a - b);
    return { kind: "days", days };
  }

  return { kind: "avista" };
}

function getViewportFlags() {
  if (typeof window === "undefined") return { isMobile: false, isTablet: false };
  const w = window.innerWidth || 1400;
  return {
    isMobile: w <= 820,
    isTablet: w <= 1180,
  };
}

function hasSuprimentoDeposit(stockInfo) {
  const deposits = Array.isArray(stockInfo?.deposits) ? stockInfo.deposits : [];
  if (!deposits.length) return false;

  const allowedDeposits = deposits.filter((d) => {
    const name = String(d?.name || "").toLowerCase();
    return (
      name.includes("suprimento") &&
      !name.includes("rma") &&
      !name.includes("informat")
    );
  });

  if (!allowedDeposits.length) return false;

  return allowedDeposits.some((d) => Number(d?.available || 0) >= 0);
}

export default function NewQuote({
  forceOpenQuotes,
  onForceOpenQuotesHandled,
  forceOpenStock,
  onForceOpenStockHandled,
  forceOpenPreview,
  onForceOpenPreviewHandled,
  forceEditQuoteId,
  onForceEditQuoteHandled,
} = {}) {

  const { isMobile, isTablet } = getViewportFlags();

  // âœ… edição
  const [editingQuote, setEditingQuote] = useState(null);

  // vendedor
  const [sellerQuery, setSellerQuery] = useState("");
  const debSellerQuery = useDebounced(sellerQuery);
  const [sellerResults, setSellerResults] = useState([]);
  const [sellerLoading, setSellerLoading] = useState(false);
  const [selectedSeller, setSelectedSeller] = useState(null);
  const [currentCompany, setCurrentCompany] = useState(() => api?.getCurrentCompany?.() || "parton");
  const [userContext, setUserContext] = useState(null);

  // cliente
  const [clientQuery, setClientQuery] = useState("");
  const debClientQuery = useDebounced(clientQuery);
  const [clientResults, setClientResults] = useState([]);
  const [clientLoading, setClientLoading] = useState(false);
  const [selectedClient, setSelectedClient] = useState(null);

  // produtos
  const [productQuery, setProductQuery] = useState("");
  const debProductQuery = useDebounced(productQuery);
  const [productResults, setProductResults] = useState([]);
  const [productLoading, setProductLoading] = useState(false);
  const [showProductResults, setShowProductResults] = useState(false);
  const productBoxRef = useRef(null);

  // envio/frete Tiny
  const [shippingMethods, setShippingMethods] = useState([]);
  const [shippingLoading, setShippingLoading] = useState(false);
  const [selectedShippingId, setSelectedShippingId] = useState("");

  const [freightMethods, setFreightMethods] = useState([]);
  const [freightLoading, setFreightLoading] = useState(false);
  const [selectedFreightId, setSelectedFreightId] = useState("");
  const pendingFreightIdRef = useRef("");

  // pagamento Tiny
  const [paymentMethods, setPaymentMethods] = useState([]);
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [selectedPaymentCode, setSelectedPaymentCode] = useState("");

  const PAYMENT_MEIOS = [
    { code: "banco", name: "Banco" },
    { code: "gateway", name: "Gateway" },
  ];
  const PAYMENT_CONTAS = [
    { code: "nao_definida", name: "Não definida" },
    { code: "suprimento_parton_olist", name: "(Suprimento)Parton - Olist" },
    { code: "suprimento_parton_stone", name: "(Suprimento)Parton - Stone" },
    { code: "park_olist", name: "(Informática)Park - Olist" },
  ];
  const PAYMENT_CATEGORIES = [
    "VENDAS INTERNAS",
    "VENDAS DE MERCADO",
    "VALE TRANSPORTE",
    "Despesas Comerciais - Suprl",
    "CERTIFICADO DIGITAL",
    "COMBUSTIVEL",
    "DESPESAS COM VIAGENS",
    "FRETE",
    "MATERIAL PARA EMBALAGEM",
    "PEDàGIO",
    "REEMBOLSO",
    "TARIFA DE ENVIOS",
    "TARIFA DE VENDA",
    "Fornecedores - Suprl",
    "COMPRA DE INSUMOS",
    "COMPRA DE MERCADORIAS",
    "Impostos - Suprl",
    "FGTS",
    "INSS",
    "SIMPLES NACIONAL",
  ];

  const [selectedPaymentMeio, setSelectedPaymentMeio] = useState("banco");
  const [selectedPaymentConta, setSelectedPaymentConta] = useState("nao_definida");
  const [selectedCardBrand, setSelectedCardBrand] = useState("");
  const CARD_BRANDS = [
    { code: "", name: "Selecione" },
    { code: "visa", name: "Visa" },
    { code: "mastercard", name: "Mastercard" },
    { code: "elo", name: "Elo" },
  ];
  const [paymentDueDate, setPaymentDueDate] = useState(() => todayLocalISODate());
  const [paymentCategory, setPaymentCategory] = useState("VENDAS INTERNAS");

  const paymentNotify = false;

  const [paymentCondition, setPaymentCondition] = useState("");
  const [installments, setInstallments] = useState([]);

  // orçamento
  const [notes, setNotes] = useState("");
  const [freightPaidClient, setFreightPaidClient] = useState("");
  const [freightPaidCompany, setFreightPaidCompany] = useState("");
  const [internalNotes, setInternalNotes] = useState("");
  const [invoiceProfile, setInvoiceProfile] = useState("A");
  const [items, setItems] = useState([
    { product: null, qty: 1, list_price: 0, discount_pct: 0, unit_price_disc: 0, stock: null },
  ]);

  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [error, setError] = useState("");

  const [quotesModalOpen, setQuotesModalOpen] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const isAdminUser = useMemo(() => {
    return Boolean(userContext?.is_admin) || String(userContext?.role || "").trim().toLowerCase() === "admin";
  }, [userContext]);

  const linkedSeller = useMemo(() => {
    if (isAdminUser) return null;
    const companyKey = String(currentCompany || api?.getCurrentCompany?.() || "parton").trim().toLowerCase();
    const link = userContext?.seller_links?.[companyKey] || null;
    const tinySellerId = String(link?.tiny_seller_id || "").trim();
    const tinySellerName = String(link?.tiny_seller_name || "").trim();
    if (!tinySellerId || !tinySellerName) return null;
    const numericSellerId = Number(tinySellerId);
    if (!Number.isFinite(numericSellerId)) return null;
    return {
      id: numericSellerId,
      nome: tinySellerName,
      name: tinySellerName,
      seller_id: numericSellerId,
      seller_name: tinySellerName,
    };
  }, [currentCompany, isAdminUser, userContext]);

  const sellerLocked = Boolean(linkedSeller);
  const sellerLinkMissing = Boolean(userContext) && !isAdminUser && !linkedSeller;

  useEffect(() => {
    if (!saveResult) return;
    const t = setTimeout(() => setSaveResult(null), 5000);
    return () => clearTimeout(t);
  }, [saveResult]);

  useEffect(() => {
    let cancelled = false;
    async function loadUserContext() {
      try {
        const me = await api.me();
        if (!cancelled) setUserContext(me || null);
      } catch {
        if (!cancelled) setUserContext(null);
      }
    }
    loadUserContext();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!linkedSeller) return;
    setSelectedSeller((prev) => {
      if (String(prev?.id || "") === String(linkedSeller.id || "") && (prev?.nome || prev?.name) === linkedSeller.nome) {
        return prev;
      }
      return linkedSeller;
    });
    setSellerQuery("");
    setSellerResults([]);
  }, [linkedSeller, selectedSeller?.id, selectedSeller?.nome, selectedSeller?.name]);

  // âœ… novo modal de consulta de estoque
  const [stockModalOpen, setStockModalOpen] = useState(false);

  useEffect(() => {
    if (!forceOpenQuotes) return;
    setQuotesModalOpen(true);
    onForceOpenQuotesHandled?.();
  }, [forceOpenQuotes, onForceOpenQuotesHandled]);

  useEffect(() => {
    if (!forceEditQuoteId) return;
    startEditQuote(forceEditQuoteId);
    onForceEditQuoteHandled?.();
  }, [forceEditQuoteId, onForceEditQuoteHandled]);

  useEffect(() => {
    if (!forceOpenStock) return;
    setStockModalOpen(true);
    onForceOpenStockHandled?.();
  }, [forceOpenStock, onForceOpenStockHandled]);

  useEffect(() => {
    if (!forceOpenPreview) return;
    if (previewData?.quote) {
      openQuotePrintWindow({
        quote: previewData.quote,
        items: previewData.items || [],
      });
    } else {
      alert("Ainda não há relatório carregado.");
    }
    onForceOpenPreviewHandled?.();
  }, [forceOpenPreview, onForceOpenPreviewHandled, previewData]);

  const [stockById, setStockById] = useState({});
  const [lastPriceByKey, setLastPriceByKey] = useState({});
  const [productLastSaleByKey, setProductLastSaleByKey] = useState({});
  const autosaveHydratedRef = useRef(false);
  const autosaveRestoringRef = useRef(false);

  const clearDraft = useCallback(() => {
    try {
      localStorage.removeItem(getDraftStorageKey());
      localStorage.removeItem(getLegacyDraftStorageKey());
    } catch {}
  }, []);

  const resetQuoteForm = useCallback(() => {
    pendingFreightIdRef.current = "";
    autosaveRestoringRef.current = true;

    setEditingQuote(null);
    setSaveResult(null);
    setError("");
    setPreviewData(null);
    setPreviewOpen(false);

    setSelectedSeller(null);
    setSellerQuery("");
    setSellerResults([]);

    setSelectedClient(null);
    setClientQuery("");
    setClientResults([]);

    setProductQuery("");
    setProductResults([]);
    setStockById({});
    setLastPriceByKey({});
    setProductLastSaleByKey({});

    setSelectedShippingId("");
    setSelectedFreightId("");
    setFreightMethods([]);

    setSelectedPaymentCode("");
    setSelectedPaymentMeio("banco");
    setSelectedPaymentConta("nao_definida");
    setSelectedCardBrand("");
    setPaymentDueDate(todayLocalISODate());
    setPaymentCategory("VENDAS INTERNAS");
    setPaymentCondition("");
    setInstallments([]);

    setNotes("");
    setFreightPaidClient("");
    setFreightPaidCompany("");
    setInternalNotes("");
    setInvoiceProfile("A");
    setItems([{ product: null, qty: 1, list_price: 0, discount_pct: 0, unit_price_disc: 0, stock: null }]);

    setTimeout(() => {
      autosaveRestoringRef.current = false;
    }, 0);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onCompanyChanged = () => {
      setCurrentCompany(api?.getCurrentCompany?.() || "parton");
      clearDraft();
      resetQuoteForm();
    };
    window.addEventListener("trml-company-changed", onCompanyChanged);
    return () => window.removeEventListener("trml-company-changed", onCompanyChanged);
  }, [clearDraft, resetQuoteForm]);


  // helper: pega saldo disponível do item da linha
  function getAvail(it) {
    const v = it?.stock?.saldoDisponivel;
    if (v === null || v === undefined) return null; // desconhecido
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function lastPriceKey(clientId, productId) {
    return `${clientId}:${productId}`;
  }

  function productLastSaleKey(product) {
    return String(product?.id || product?.codigo || product?.nome || "");
  }

  function productLastSaleLabel(ref) {
    if (!ref) return "";
    if (ref.loading) return "Último valor de venda: carregando...";
    if (!ref.found) return "Último valor de venda: sem histórico para este cliente";
    const price = formatBRL(ref.last_unit_price ?? ref.unit_price_disc ?? 0);
    const date = formatDateBR(ref.last_sale_date || ref.created_at);
    const order = ref.order_number || ref.tiny_order_number || ref.quote_number;
    return `Último valor de venda: ${price}${date ? ` · ${date}` : ""}${order ? ` · Pedido #${order}` : ""}`;
  }

  function lastPriceOriginLabel(ref) {
    if (!ref?.found) return "";
    if (ref.tiny_order_number) return `Pedido #${ref.tiny_order_number}`;
    if (ref.quote_number) return `Orçamento #${ref.quote_number}`;
    return ref.status === "ordered" ? "Pedido" : "Orçamento";
  }

  const fetchLastPriceReference = useCallback(async (clientId, productId) => {
    if (!clientId || !productId) return;
    const key = lastPriceKey(clientId, productId);

    let shouldFetch = false;
    setLastPriceByKey((prev) => {
      if (Object.prototype.hasOwnProperty.call(prev, key)) return prev;
      shouldFetch = true;
      return { ...prev, [key]: { loading: true, found: false } };
    });
    if (!shouldFetch) return;

    try {
      const token = await auth?.currentUser?.getIdToken?.();
      const company = api?.getCurrentCompany?.() || "parton";
      const resp = await fetch(`/api/clients/${clientId}/products/${productId}/last-price?company=${encodeURIComponent(company)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      let data = null;
      try {
        data = await resp.json();
      } catch {
        data = null;
      }

      if (!resp.ok) {
        throw new Error(data?.detail || "Erro ao buscar último preço do cliente.");
      }

      setLastPriceByKey((prev) => ({ ...prev, [key]: { loading: false, ...(data || { found: false }) } }));
    } catch (e) {
      setLastPriceByKey((prev) => ({
        ...prev,
        [key]: { loading: false, found: false, error: e?.message || String(e) },
      }));
    }
  }, []);

  const fetchProductLastSales = useCallback(async (products) => {
    const visibleProducts = (products || []).slice(0, PRODUCT_SEARCH_LIMIT).filter((p) => productLastSaleKey(p));
    if (!selectedClient?.id || !visibleProducts.length) {
      setProductLastSaleByKey({});
      return;
    }

    const loadingMap = {};
    for (const p of visibleProducts) {
      loadingMap[productLastSaleKey(p)] = { loading: true, found: false };
    }
    setProductLastSaleByKey(loadingMap);

    try {
      const company = api?.getCurrentCompany?.() || "parton";
      const result = await api.clientWalletProductLastSalesBatch({
        company,
        client: {
          client_id: selectedClient.id,
          tiny_client_id: selectedClient.id,
          cpf_cnpj: selectedClient.cpf_cnpj || selectedClient.cpfCnpj || "",
          name: selectedClient.nome || selectedClient.name || "",
        },
        products: visibleProducts.map((p) => ({
          key: productLastSaleKey(p),
          product_id: p.id,
          tiny_product_id: p.id,
          sku: p.codigo || p.sku || "",
          name: p.nome || p.name || "",
        })),
      });
      setProductLastSaleByKey(result?.items || {});
    } catch (e) {
      const errorMap = {};
      for (const p of visibleProducts) {
        errorMap[productLastSaleKey(p)] = {
          loading: false,
          found: false,
          error: e?.message || "Erro ao consultar histórico local.",
        };
      }
      setProductLastSaleByKey(errorMap);
    }
  }, [selectedClient]);

  useEffect(() => {
    const clientId = Number(selectedClient?.id || 0);
    if (!clientId) return;

    for (const it of items) {
      const productId = Number(it?.product?.id || 0);
      if (productId) fetchLastPriceReference(clientId, productId);
    }
  }, [selectedClient, items, fetchLastPriceReference]);

  const preloadStockForProducts = useCallback(
    async (products, maxItems = 20, concurrency = 3) => {
      const ids = (products || [])
        .slice(0, maxItems)
        .map((p) => p?.id)
        .filter(Boolean);
      const toFetch = ids.filter((id) => stockById[id] === undefined);
      if (toFetch.length === 0) return;

      let idx = 0;
      async function worker() {
        while (idx < toFetch.length) {
          const my = toFetch[idx++];
          try {
            const r = await api.tinyStock(my);
            const info = extractStockInfo(r);
            setStockById((prev) => ({ ...prev, [my]: info }));
          } catch {
            setStockById((prev) => ({ ...prev, [my]: null }));
          }
        }
      }
      await Promise.all(Array.from({ length: concurrency }, () => worker()));
    },
    [stockById]
  );

  useEffect(() => {
    if (autosaveHydratedRef.current) return;

    autosaveRestoringRef.current = true;
    try {
      const draft = safeJsonParse(localStorage.getItem(getDraftStorageKey()), null);
      if (draft) {
        if (draft.selectedSeller) setSelectedSeller(draft.selectedSeller);
        if (typeof draft.sellerQuery === "string") setSellerQuery(draft.sellerQuery);

        if (draft.selectedClient) setSelectedClient(draft.selectedClient);
        if (typeof draft.clientQuery === "string") setClientQuery(draft.clientQuery);

        if (typeof draft.productQuery === "string") setProductQuery(draft.productQuery);

        if (typeof draft.selectedPaymentMeio === "string") setSelectedPaymentMeio(draft.selectedPaymentMeio);
        if (typeof draft.selectedPaymentConta === "string") setSelectedPaymentConta(draft.selectedPaymentConta);
        if (typeof draft.selectedCardBrand === "string") setSelectedCardBrand(draft.selectedCardBrand);
        if (typeof draft.paymentDueDate === "string") setPaymentDueDate(clampNotPastISODate(draft.paymentDueDate));
        if (typeof draft.paymentCategory === "string") setPaymentCategory(draft.paymentCategory);
        if (typeof draft.paymentCondition === "string") setPaymentCondition(draft.paymentCondition);
        if (Array.isArray(draft.installments)) setInstallments(draft.installments);
        if (typeof draft.notes === "string") setNotes(draft.notes);
        if (draft.freight_paid_client !== undefined) setFreightPaidClient(String(draft.freight_paid_client ?? ""));
        if (draft.freight_paid_company !== undefined) setFreightPaidCompany(String(draft.freight_paid_company ?? ""));
        if (typeof draft.internal_notes === "string") setInternalNotes(draft.internal_notes);
        else if (typeof draft.internalNotes === "string") setInternalNotes(draft.internalNotes);
        if (Array.isArray(draft.items) && draft.items.length) setItems(draft.items);
      }
    } catch {} finally {
      autosaveHydratedRef.current = true;
      setTimeout(() => {
        autosaveRestoringRef.current = false;
      }, 0);
    }
  }, []);

  useEffect(() => {
    if (!autosaveHydratedRef.current || autosaveRestoringRef.current) return;
    if (editingQuote?.quote_id) return;

    const draft = {
      selectedSeller,
      sellerQuery,
      selectedClient,
      clientQuery,
      productQuery,
      selectedShippingId,
      selectedFreightId,
      selectedPaymentCode,
      selectedPaymentMeio,
      selectedPaymentConta,
      selectedCardBrand,
      paymentDueDate,
      paymentCategory,
      paymentCondition,
      installments,
      notes,
      items,
      savedAt: new Date().toISOString(),
    };

    try {
      localStorage.setItem(getDraftStorageKey(), JSON.stringify(draft));
    } catch {}
  }, [
    editingQuote,
    selectedSeller,
    sellerQuery,
    selectedClient,
    clientQuery,
    productQuery,
    selectedShippingId,
    selectedFreightId,
    selectedPaymentCode,
    selectedPaymentMeio,
    selectedPaymentConta,
    selectedCardBrand,
    paymentDueDate,
    paymentCategory,
    paymentCondition,
    installments,
    notes,
    items,
  ]);

  const totals = useMemo(() => {
    let net = 0;
    for (const it of items) {
      const qty = toNum(it.qty);
      const unitDisc = toNum(it.unit_price_disc);
      net += qty * unitDisc;
    }
    return { net: round2(net) };
  }, [items]);

  useEffect(() => {
    setInstallments([]);
  }, [totals.net]);

  // âœ… setItem agora aplica a regra do estoque (clampa qty)
  function setItem(idx, patch) {
    setItems((prev) =>
      prev.map((it, i) => {
        if (i !== idx) return it;
        const next = { ...it, ...patch };

        if (patch && Object.prototype.hasOwnProperty.call(patch, "qty")) {
          next.qty = Math.max(0, Math.floor(toNum(next.qty)));
        }

        return next;
      })
    );
  }

  function recalcFromDiscountPct(listPrice, discountPct) {
    const lp = toNum(listPrice);
    const pct = clamp(toNum(discountPct), 0, MAX_DISCOUNT_PCT);
    const unit = lp * (1 - pct / 100);
    return { discount_pct: pct, unit_price_disc: Number(unit.toFixed(6)) };
  }

  function recalcFromUnitDiscount(listPrice, unitDisc) {
    const lp = toNum(listPrice);
    const ud = toNum(unitDisc);
    if (lp <= 0) return { discount_pct: 0, unit_price_disc: ud };

    const minUnit = lp * (1 - MAX_DISCOUNT_PCT / 100);
    const fixedUd = Math.max(ud, minUnit);

    const pct = (1 - fixedUd / lp) * 100;
    return {
      discount_pct: clamp(Number(pct.toFixed(4)), 0, MAX_DISCOUNT_PCT),
      unit_price_disc: Number(fixedUd.toFixed(6)),
    };
  }

  async function pickProductIntoLine(idx, p) {
    const listPrice = toNum(p.preco || 0);
    const { discount_pct, unit_price_disc } = recalcFromDiscountPct(
      listPrice,
      items[idx]?.discount_pct || 0
    );

    // seta produto
    setItem(idx, { product: p, list_price: listPrice, discount_pct, unit_price_disc, stock: null });

    const cached = stockById[p.id];
    if (cached !== undefined) {
      // aplica estoque em linha
      setItems((prev) =>
        prev.map((it, i) => {
          if (i !== idx) return it;
          return { ...it, stock: cached };
        })
      );
      return;
    }

    try {
      const r = await api.tinyStock(p.id);
      const info = extractStockInfo(r);
      setItems((prev) =>
        prev.map((it, i) => {
          if (i !== idx) return it;
          return { ...it, stock: info };
        })
      );
      setStockById((prev) => ({ ...prev, [p.id]: info }));
    } catch {
      setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, stock: null } : it)));
      setStockById((prev) => ({ ...prev, [p.id]: null }));
    }
  }

  function addLine() {
    setItems((prev) => [
      ...prev,
      { product: null, qty: 1, list_price: 0, discount_pct: 0, unit_price_disc: 0, stock: null },
    ]);
  }

  function removeLine(idx) {
    setItems((prev) => {
      if (prev.length <= 1) {
        return [
          { product: null, qty: 1, list_price: 0, discount_pct: 0, unit_price_disc: 0, stock: null },
        ];
      }
      return prev.filter((_, i) => i !== idx);
    });
  }

  async function addProductSmart(p) {
    const emptyIdx = items.findIndex((it) => !it.product);
    if (emptyIdx >= 0) {
      await pickProductIntoLine(emptyIdx, p);
    } else {
      const newIdx = items.length;
      addLine();
      setTimeout(() => pickProductIntoLine(newIdx, p), 0);
    }

    setProductQuery("");
    setProductResults([]);
    setShowProductResults(false);
  }

  // âœ… Shipping methods
  useEffect(() => {
    let cancelled = false;
    async function run() {
      setShippingLoading(true);
      try {
        const r = await api.tinyShippingMethods();
        if (cancelled) return;
        const list = r.items || [];
        setShippingMethods(list);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setShippingLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // payment methods
  useEffect(() => {
    let cancelled = false;
    async function run() {
      setPaymentLoading(true);
      try {
        const r = await api.tinyPaymentMethods({ company: currentCompany });
        if (cancelled) return;
        const list = r.items || [];
        setPaymentMethods(list);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setPaymentLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [currentCompany]); // eslint-disable-line react-hooks/exhaustive-deps

  // freight depends on shipping
  useEffect(() => {
    let cancelled = false;
    async function run() {
      setFreightMethods([]);

      const pendingFreightId = pendingFreightIdRef.current;
      if (!pendingFreightId) {
        setSelectedFreightId("");
      }

      if (!selectedShippingId) return;

      setFreightLoading(true);
      try {
        const r = await api.tinyFreightMethods(selectedShippingId);
        if (cancelled) return;
        const list = r.items || [];
        setFreightMethods(list);

        if (pendingFreightId) {
          const exists = list.some((f) => String(f.id) === String(pendingFreightId));
          if (exists) {
            setSelectedFreightId(String(pendingFreightId));
          }
          pendingFreightIdRef.current = "";
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setFreightLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [selectedShippingId]);

  // fetch vendedores
  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (sellerLocked) {
        setSellerResults([]);
        setSellerLoading(false);
        return;
      }
      if (!debSellerQuery || debSellerQuery.trim().length < 2) {
        setSellerResults([]);
        return;
      }
      setSellerLoading(true);
      try {
        const r = await api.tinyVendors(debSellerQuery.trim(), 1);
        if (!cancelled) setSellerResults(r.items || []);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setSellerLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [debSellerQuery, sellerLocked]);

  // fetch clientes
  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!debClientQuery || debClientQuery.trim().length < 2) {
        setClientResults([]);
        return;
      }
      setClientLoading(true);
      try {
        const r = await api.tinyClients(debClientQuery.trim(), 1);
        if (!cancelled) setClientResults(r.items || []);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setClientLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [debClientQuery]);

  // fetch produtos (para adicionar)
  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!debProductQuery || debProductQuery.trim().length < 2) {
        setProductResults([]);
        return;
      }
      setProductLoading(true);
      try {
        const r = await api.tinyProducts(debProductQuery.trim(), 1);
        if (!cancelled) {
          const list = r.items || [];
          setProductResults(list);
          preloadStockForProducts(list, 20, 3);
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setProductLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [debProductQuery, preloadStockForProducts]);

  useEffect(() => {
    if (!productResults.length) {
      setProductLastSaleByKey({});
      return;
    }
    fetchProductLastSales(productResults);
  }, [productResults, fetchProductLastSales]);

  // Fecha a lista de produtos apenas ao clicar de fato fora da caixa de busca.
  // (Antes usava onBlur+setTimeout, que fechava a lista em qualquer perda de
  // foco e não reabria sem redigitar.)
  useEffect(() => {
    function onDocMouseDown(e) {
      if (productBoxRef.current && !productBoxRef.current.contains(e.target)) {
        setShowProductResults(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  const paymentSelected = useMemo(() => {
    const m = paymentMethods.find((x) => String(x.code) === String(selectedPaymentCode));
    return m || null;
  }, [paymentMethods, selectedPaymentCode]);

  const paymentKind = useMemo(
    () => normalizePaymentKind(paymentSelected || selectedPaymentCode),
    [paymentSelected, selectedPaymentCode]
  );

  const showPaymentCondition = useMemo(() => {
    return ["boleto", "multiplas", "cartao_credito", "link_pagamento"].includes(paymentKind);
  }, [paymentKind]);

  const commonConditions = useMemo(() => {
    const arr = [{ label: "à  vista", value: "0" }];
    for (let i = 1; i <= 12; i++) arr.push({ label: `parcelado em ${i}x`, value: `parcelado em ${i}x` });
    return arr;
  }, []);

  function generateInstallments() {
    const parsed = parsePaymentCondition(paymentCondition);
    const baseDate = paymentDueDate ? new Date(`${paymentDueDate}T00:00:00`) : new Date();
    const total = round2(totals.net);
    const isCartaoCredito = paymentKind === "cartao_credito";

    if (total <= 0) {
      setInstallments([]);
      setError("Total do orçamento é 0.");


<div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>

  {isEditing && (
    <button
      onClick={() => setEditingId(null)}
      style={{
        background: 'transparent',
        border: '1px solid var(--border)',
        color: 'var(--text)',
        padding: '10px 14px',
        cursor: 'pointer'
      }}
    >
      Cancelar edição
    </button>
  )}

  <button
    onClick={() => {
      if (!confirm('Tem certeza que deseja limpar todo o orçamento?')) return

      try {
        setClient && setClient(null)
        setItems && setItems([])
        setNotes && setNotes('')
        setShippingMethod && setShippingMethod(null)
        setPaymentMethod && setPaymentMethod(null)
      } catch (e) {}

      localStorage.removeItem('newQuoteDraft')
    }}
    style={{
      background: '#444',
      border: '1px solid var(--border)',
      color: '#fff',
      padding: '10px 14px',
      cursor: 'pointer'
    }}
  >
    Limpar
  </button>

</div>

      return;
    }

    if (parsed.kind === "avista") {
      const dueDate = isCartaoCredito ? addDays(baseDate, 30) : baseDate;
      setInstallments([{ n: 1, due_date: toISODate(dueDate), amount: total }]);
      return;
    }
    if (parsed.kind === "nx") {
      const values = splitEven(total, parsed.n);
      setInstallments(
        values.map((amount, i) => ({
          n: i + 1,
          due_date: toISODate(isCartaoCredito ? addDays(baseDate, 30 * (i + 1)) : addMonths(baseDate, i)),
          amount,
        }))
      );
      return;
    }
    if (parsed.kind === "days") {
      const values = splitEven(total, parsed.days.length);
      setInstallments(values.map((amount, i) => ({ n: i + 1, due_date: toISODate(addDays(baseDate, parsed.days[i])), amount })));
      return;
    }
    const fallbackDate = isCartaoCredito ? addDays(baseDate, 30) : baseDate;
    setInstallments([{ n: 1, due_date: toISODate(fallbackDate), amount: total }]);
  }

  // âœ… carregar orçamento no formulário (edição)
  async function startEditQuote(quoteId) {
    setError("");
    setSaveResult(null);

    try {
      const detail = await withGlobalLoading("Carregando orçamento...", () => api.getQuote(quoteId));
      const q = detail?.quote || {};
      const its = detail?.items || [];

      let clientSnap = {};
      try {
        clientSnap = q.client_snapshot ? JSON.parse(q.client_snapshot) : {};
      } catch {
        clientSnap = {};
      }

      setSelectedSeller({
        id: Number(q.seller_id),
        nome: q.seller_name || `Vendedor #${q.seller_id}`,
      });
      setSellerQuery("");
      setSellerResults([]);

      setSelectedClient({
        id: Number(q.client_id),
        nome: clientSnap?.nome || clientSnap?.name || q.client_name || q.cliente_nome || q.customer_name || `Cliente #${q.client_id}`,
        cpf_cnpj: clientSnap?.cpf_cnpj || clientSnap?.cpfCnpj || "",
        raw: clientSnap,
      });
      setClientQuery("");
      setClientResults([]);

      const freightIdToRestore = q.freight_method_id || q.freight_id || payloadSaved.freight_method_id || payloadSaved.freight_id || "";
      pendingFreightIdRef.current = freightIdToRestore ? String(freightIdToRestore) : "";

      setSelectedShippingId(q.shipping_method_id ? String(q.shipping_method_id) : "");
      setSelectedFreightId(freightIdToRestore ? String(freightIdToRestore) : "");

      setSelectedPaymentCode(String(q.payment_method_code || ""));
      setSelectedPaymentMeio(String(q.payment_meio || "banco"));
      setSelectedPaymentConta(String(q.payment_conta || "nao_definida"));
      setPaymentDueDate(
        clampNotPastISODate(
          q.payment_due_date
            ? String(q.payment_due_date)
            : todayLocalISODate()
        )
      );
      setPaymentCategory(String(q.payment_category || "VENDAS INTERNAS"));

      let payloadSaved = {};
      try {
        payloadSaved = q.payload ? JSON.parse(q.payload) : {};
      } catch {
        payloadSaved = {};
      }
      setSelectedCardBrand(String(payloadSaved.payment_card_brand || ""));
      setPaymentCondition(String(payloadSaved.payment_condition || ""));
      setInstallments(
        Array.isArray(payloadSaved.payment_installments)
          ? payloadSaved.payment_installments
          : []
      );

      const mapped = its.map((it) => {
        const rawSaved = safeJsonParse(it.raw, {});
        const productRaw = rawSaved?.product_raw || {};

        return {
          product: {
            id: Number(it.product_id),
            nome: it.name_snapshot || "",
            codigo: it.sku_snapshot || "",
            raw: productRaw,
            preco_custo:
              productRaw?.preco_custo ??
              productRaw?.precoCusto ??
              productRaw?.custo ??
              productRaw?.custo_unitario ??
              productRaw?.custoUnitario ??
              productRaw?.preco_custo_medio ??
              productRaw?.precoCustoMedio ??
              0,
          },
          qty: toNum(it.qty || 1),
          list_price: toNum(it.list_price || 0),
          discount_pct: toNum(it.discount_pct || 0),
          unit_price_disc: toNum(it.unit_price_disc || 0),
          stock: null,
        };
      });
      setItems(
        mapped.length
          ? mapped
          : [{ product: null, qty: 1, list_price: 0, discount_pct: 0, unit_price_disc: 0, stock: null }]
      );

      setNotes(String(q.notes || ""));
      setFreightPaidClient(String(q.freight_paid_client ?? payloadSaved.freight_paid_client ?? ""));
      setFreightPaidCompany(String(q.freight_paid_company ?? payloadSaved.freight_paid_company ?? ""));
      setInternalNotes(String(q.internal_notes || payloadSaved.internal_notes || payloadSaved.internalNotes || ""));
      setInvoiceProfile(String(payloadSaved.invoice_profile || "A"));

      clearDraft();
      setEditingQuote({ quote_id: q.quote_id, quote_number: q.quote_number });

      setQuotesModalOpen(false);
      setPreviewData(detail);
    } catch (e) {
      setError(e?.message || String(e));
    }
  }

  function cancelEditing() {
    const ok = window.confirm("Cancelar edição e iniciar um novo orçamento?");
    if (!ok) return;

    clearDraft();

    setEditingQuote(null);
    setSaveResult(null);
    setError("");

    setSelectedSeller(null);
    setSellerQuery("");
    setSellerResults([]);

    setSelectedClient(null);
    setClientQuery("");
    setClientResults([]);

    setNotes("");
    setFreightPaidClient("");
    setFreightPaidCompany("");
    setInternalNotes("");

    setItems([{ product: null, qty: 1, list_price: 0, discount_pct: 0, unit_price_disc: 0, stock: null }]);

    setPaymentCondition("");
    setInstallments([]);
    setSelectedCardBrand("");
    setPaymentDueDate(todayLocalISODate());
  }

  // âœ… REGRAS POR FORMA DE RECEBIMENTO (Tiny/Olist)
  const paymentRule = useMemo(() => {
    const code = String(paymentKind || "").toLowerCase();
    const companyKey = String(currentCompany || api?.getCurrentCompany?.() || "parton").trim().toLowerCase();
    const pixConta = companyKey === "park" ? "park_olist" : "suprimento_parton_olist";
    const boletoConta = pixConta;
    const stoneConta = companyKey === "park" ? "park_olist" : "suprimento_parton_stone";
    const companyContas = PAYMENT_CONTAS.filter(
      (c) => c.code === "nao_definida" ||
        (companyKey === "park" ? c.code.startsWith("park_") : c.code.startsWith("suprimento_parton_"))
    );

    const base = {
      showMeio: true,
      meioLocked: false,
      meioFixed: null,
      showConta: true,
      contaLabel: "Conta bancária",
      contas: PAYMENT_CONTAS,
      preferredConta: "nao_definida",
    };

    if (["dinheiro", "vale_troca", "crediario", "outros"].includes(code)) {
      return { ...base, showMeio: false, showConta: false };
    }

    if (code === "pix") {
      return {
        ...base,
        showMeio: true,
        meioLocked: true,
        meioFixed: "banco",
        contaLabel: "Banco ou Gateway",
        contas: PAYMENT_CONTAS.filter((c) => c.code === pixConta),
        preferredConta: pixConta,
      };
    }

    if (code === "boleto") {
      return {
        ...base,
        showMeio: true,
        meioLocked: true,
        meioFixed: "banco",
        contaLabel: "Banco ou Gateway",
        contas: PAYMENT_CONTAS.filter((c) => c.code === boletoConta),
        preferredConta: boletoConta,
      };
    }

    if (code === "cartao_credito") {
      return {
        ...base,
        showMeio: true,
        meioLocked: true,
        meioFixed: "gateway",
        contaLabel: "Gateway",
        contas: PAYMENT_CONTAS.filter((c) => c.code === stoneConta),
        preferredConta: stoneConta,
      };
    }

    if (code === "cartao_debito") {
      return {
        ...base,
        showMeio: true,
        meioLocked: true,
        meioFixed: "gateway",
        contaLabel: "Gateway",
        contas: companyContas.filter((c) => c.code !== "nao_definida"),
        preferredConta: stoneConta,
      };
    }

    if (code === "link_pagamento") {
      return {
        ...base,
        showMeio: true,
        meioLocked: true,
        meioFixed: "gateway",
        contaLabel: "Gateway",
        contas: PAYMENT_CONTAS.filter((c) => c.code === pixConta),
        preferredConta: pixConta,
      };
    }

    return base;
  }, [currentCompany, paymentKind]);

  useEffect(() => {
    if (!selectedPaymentCode) return;

    if (paymentRule.meioFixed) {
      setSelectedPaymentMeio(paymentRule.meioFixed);
    }

    if (!paymentRule.showConta) {
      setSelectedPaymentConta("nao_definida");
      return;
    }

    const contas = paymentRule.contas || PAYMENT_CONTAS;

    const currentOk = contas.some((c) => c.code === selectedPaymentConta);
    if (currentOk) return;

    const preferredOk = contas.some((c) => c.code === paymentRule.preferredConta);
    if (preferredOk) {
      setSelectedPaymentConta(paymentRule.preferredConta);
      return;
    }

    if (contas.length) setSelectedPaymentConta(contas[0].code);
  }, [selectedPaymentCode, paymentRule]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onSave() {
    setError("");
    setSaveResult(null);

    if (sellerLinkMissing) return setError("Usuário sem vendedor Tiny vinculado para esta empresa.");
    if (!selectedSeller) return setError("Selecione um vendedor.");
    if (!selectedClient) return setError("Selecione um cliente.");
    if (!selectedShippingId) return setError("Selecione uma forma de envio.");
    if (!selectedFreightId) return setError("Selecione uma forma de frete.");
    if (!selectedPaymentCode) return setError("Selecione uma forma de pagamento.");

    if (paymentRule.showMeio && !selectedPaymentMeio) return setError("Selecione o meio de pagamento.");
    if (paymentRule.showConta && !selectedPaymentConta) return setError("Selecione a conta bancária.");
    if (paymentKind === "cartao_credito" && !selectedCardBrand) return setError("Selecione a bandeira do cartão.");

    if (!paymentDueDate) return setError("Informe o vencimento.");
    if (!paymentCategory) return setError("Selecione a categoria.");

    if (showPaymentCondition) {
      if (!String(paymentCondition || "").trim()) {
        return setError("Informe a condição de pagamento.");
      }
      const parsed = parsePaymentCondition(paymentCondition);
      if (parsed.kind !== "avista" && !installments.length)
        return setError('Clique em "Gerar parcelas" antes de salvar.');
    }

    // Regra final: não deixa salvar se qty > estoque (quando conhecido)
    const cleanItems = items
      .filter((it) => it.product && toNum(it.qty) > 0 && toNum(it.unit_price_disc) > 0)
      .map((it) => {
        const lp = toNum(it.list_price);
        const minUnit = lp * (1 - MAX_DISCOUNT_PCT / 100);
        return {
          product_id: it.product.id,
          qty: Math.max(0, Math.floor(toNum(it.qty))),
          list_price: lp,
          discount_pct: clamp(toNum(it.discount_pct), 0, MAX_DISCOUNT_PCT),
          unit_price_disc: Math.max(toNum(it.unit_price_disc), minUnit),
        };
      });

    if (!cleanItems.length) return setError("Adicione pelo menos 1 item válido.");
    if (cleanItems.some((it) => !it.product_id || toNum(it.qty) <= 0 || toNum(it.unit_price_disc) <= 0)) {
      return setError("Preencha corretamente todos os itens do orçamento.");
    }

    setSaving(true);
    try {
      const payload = {
        client_id: selectedClient.id,
        seller_id: selectedSeller.id,
        seller_name: selectedSeller.name || selectedSeller.nome || "",
        shipping_method_id: Number(selectedShippingId),
        freight_method_id: selectedFreightId ? Number(selectedFreightId) : null,

        payment_method_code: String(selectedPaymentCode),

        payment_meio: paymentRule.showMeio ? String(selectedPaymentMeio || "") : "",
        payment_conta: paymentRule.showConta ? String(selectedPaymentConta || "") : "",
        payment_card_brand: paymentKind === "cartao_credito" ? String(selectedCardBrand || "") : "",

        payment_due_date: String(clampNotPastISODate(paymentDueDate || "")),
        payment_category: String(paymentCategory || ""),
        payment_notify: paymentNotify,

        payment_condition: String(paymentCondition || ""),
        payment_installments: installments,

        notes,
        internal_notes: String(internalNotes || ""),
        invoice_profile: String(invoiceProfile || "A"),
        freight_paid_client: toNum(freightPaidClient),
        freight_paid_company: toNum(freightPaidCompany),
        items: cleanItems,
      };

      const r = await withGlobalLoading(
        editingQuote?.quote_id ? "Atualizando pré-venda..." : "Salvando pré-venda...",
        () =>
          editingQuote?.quote_id
            ? api.updateQuote(editingQuote.quote_id, payload)
            : api.createQuote(payload)
      );

      const savedQuote = r?.quote || r || {};

      const editingQuoteId =
        editingQuote?.quote_id ||
        editingQuote?.id ||
        "";

      const editingQuoteNumber =
        editingQuote?.quote_number ||
        editingQuote?.number ||
        "";

      const savedId =
        editingQuoteId ||
        savedQuote?.quote_id ||
        savedQuote?.id ||
        r?.quote_id ||
        r?.id ||
        "";

      const savedNumber =
        editingQuoteNumber ||
        savedQuote?.quote_number ||
        savedQuote?.number ||
        r?.quote_number ||
        r?.number ||
        "";

      setSaveResult({
        quote_id: savedId,
        quote_number: savedNumber,
      });
      clearDraft();

      try {
        console.log("[PREVIEW_DEBUG] save ok, savedId =", savedId, "savedNumber =", savedNumber);

        if (savedId) {
          const detail = await withGlobalLoading("Carregando preview...", () => api.getQuote(savedId));
          console.log("[PREVIEW_DEBUG] getQuote detail =", detail);

          const normalizedDetail =
            detail?.quote
              ? detail
              : detail
                ? {
                    quote: detail,
                    items: detail?.items || detail?.quote_items || [],
                  }
                : null;

          console.log("[PREVIEW_DEBUG] normalizedDetail =", normalizedDetail);

          if (normalizedDetail?.quote) {
            console.log("[PREVIEW_DEBUG] chamando setPreviewData/setPreviewOpen");
            setPreviewData(normalizedDetail);
            setPreviewOpen(true);
          } else {
            console.warn("[PREVIEW_DEBUG] normalizedDetail sem quote");
          }
        } else {
          console.warn("[PREVIEW_DEBUG] savedId vazio");
        }
      } catch (err) {
        console.error("[PREVIEW_DEBUG] erro ao abrir preview:", err);
        alert("O orçamento salvou, mas houve erro ao carregar o preview. Veja o console.");
      }

      if (editingQuote?.quote_id) {
        setEditingQuote((prev) => ({
          quote_id: savedId || prev?.quote_id,
          quote_number: savedNumber || prev?.quote_number,
        }));
      } else {
        setEditingQuote({
          quote_id: savedId,
          quote_number: savedNumber,
        });
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={styles.page}>
      <div
        style={{
          ...styles.container,
          width: "100%",
          maxWidth: isMobile ? "100%" : styles.container.maxWidth,
          padding: isMobile ? "12px 8px 28px" : isTablet ? "16px 10px 36px" : styles.container.padding,
        }}
      >
        <PageHeader title={editingQuote ? "Editar pré-venda" : "Nova pré-venda"} />

        {error ? <div style={styles.alertErr}>Erro: {error}</div> : null}
        {saveResult ? (
          <div
            style={{
              position: "fixed",
              right: 20,
              bottom: 20,
              zIndex: 9999,
              background: "rgba(34,197,94,.96)",
              border: "1px solid rgba(34,197,94,.28)",
              color: "#fff",
              padding: "12px 14px",
              borderRadius: 14,
              fontSize: 13,
              fontWeight: 700,
              boxShadow: "0 10px 30px rgba(0,0,0,.22)",
            }}
          >
            {editingQuote ? "Atualizado." : "Salvo."} Pré-venda NÂº {saveResult.quote_number}.
          </div>
        ) : null}

        {/* Vendedor */}
        <Card
          title="Vendedor (obrigatório)"
          actions={
            selectedSeller && !sellerLocked ? (
              <Button variant="ghost" size="sm" onClick={() => setSelectedSeller(null)}>
                Trocar
              </Button>
            ) : null
          }
        >
          {selectedSeller ? (
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 800, ...styles.ellipsis }}>{selectedSeller.nome}</div>
              <div style={styles.small}>id: {selectedSeller.id}</div>
              {sellerLocked ? (
                <div style={{ ...styles.small, marginTop: 6, color: "var(--muted)" }}>
                  Vendedor definido pelo vínculo do usuário.
                </div>
              ) : null}
            </div>
          ) : (
            <>
              <input
                style={styles.input}
                placeholder="Buscar vendedor por nome ou código"
                value={sellerQuery}
                onChange={(e) => setSellerQuery(e.target.value)}
              />
              {sellerLoading ? <div style={{ ...styles.small, marginTop: 8 }}>Buscando...</div> : null}
              {sellerResults.length ? (
                <div style={styles.listBox}>
                  {sellerResults.slice(0, 10).map((v) => (
                    <div
                      key={v.id}
                      style={{ ...styles.listItem, cursor: "pointer" }}
                      onClick={() => {
                        setSelectedSeller(v);
                        setSellerResults([]);
                        setSellerQuery("");
                      }}
                    >
                      <div style={{ fontWeight: 800, ...styles.ellipsis }}>{v.nome}</div>
                      <div style={styles.small}>id: {v.id}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          )}
          {sellerLinkMissing ? (
            <div style={{ ...styles.small, marginTop: 8, color: "var(--danger, #dc2626)" }}>
              Usuário sem vendedor Tiny vinculado para esta empresa.
            </div>
          ) : null}
        </Card>

        {/* Cliente */}
        <Card
          title="Cliente (obrigatório)"
          actions={
            selectedClient ? (
              <Button variant="ghost" size="sm" onClick={() => setSelectedClient(null)}>
                Trocar
              </Button>
            ) : null
          }
        >
          {selectedClient ? (
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 800, ...styles.ellipsis }}>{selectedClient.nome}</div>
              <div style={styles.small}>{selectedClient.cpf_cnpj || ""}</div>
            </div>
          ) : (
            <>
              <input
                style={styles.input}
                placeholder="Buscar cliente por nome, CPF ou CNPJ"
                value={clientQuery}
                onChange={(e) => setClientQuery(e.target.value)}
              />
              {clientLoading ? <div style={{ ...styles.small, marginTop: 8 }}>Buscando...</div> : null}
              {clientResults.length ? (
                <div style={styles.listBox}>
                  {clientResults.slice(0, 10).map((c) => (
                    <div
                      key={c.id}
                      style={{ ...styles.listItem, cursor: "pointer" }}
                      onClick={() => {
                        setSelectedClient(c);
                        setClientResults([]);
                        setClientQuery("");
                      }}
                    >
                      <div style={{ fontWeight: 800, ...styles.ellipsis }}>{c.nome}</div>
                      <div style={styles.small}>{c.cpf_cnpj || ""}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </Card>

        {/* Itens */}
        <Card
          title="Itens"
          actions={
            <Button variant="secondary" size="sm" onClick={addLine}>
              +
            </Button>
          }
        >
          <div style={{ marginBottom: 10 }} ref={productBoxRef}>
            <div style={{ fontSize: 12, fontWeight: 900, color: "var(--muted)", marginBottom: 6 }}>
              Buscar produto
            </div>

            <input
              style={styles.input}
              placeholder="Buscar produto por nome ou SKU"
              value={productQuery}
              onChange={(e) => {
                setProductQuery(e.target.value);
                setShowProductResults(true);
              }}
              onFocus={() => setShowProductResults(true)}
            />

            {showProductResults && productLoading ? (
              <div style={{ ...styles.small, marginTop: 8 }}>Buscando...</div>
            ) : null}

            {showProductResults && productResults.length ? (
              <div style={styles.listBox}>
                {productResults.slice(0, PRODUCT_SEARCH_LIMIT)
                  .map((p) => {
                    const estoque =
                      stockById[p.id]?.saldoDisponivel ??
                      p.saldoDisponivel ??
                      p.raw?.saldoDisponivel ??
                      0;
                    const lastSaleRef = selectedClient
                      ? productLastSaleByKey[productLastSaleKey(p)]
                      : null;
                    return (
                      <div key={p.id} style={styles.listItem}>
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            gap: 12,
                            alignItems: "center",
                            minWidth: 0,
                          }}
                        >
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ fontWeight: 800, ...styles.ellipsis }}>{p.nome}</div>
                            <div style={{ ...styles.small, ...styles.ellipsis }}>
                              {p.codigo || ""} • {formatBRL(p.preco || 0)} • estoque disponível: {estoque}
                            </div>
                            <div style={{ ...styles.small, color: "var(--accent, #2563eb)", marginTop: 4 }}>
                              {selectedClient
                                ? productLastSaleLabel(lastSaleRef || { found: false })
                                : "Selecione um cliente para ver histórico de venda"}
                            </div>
                          </div>

                          <button
                            onClick={() => addProductSmart(p)}
                            style={{
                              ...styles.button,
                              width: 40,
                              height: 36,
                              padding: 0,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                            title="Adicionar ao orçamento"
                          >
                            +
                          </button>
                        </div>
                      </div>
                    );
                  })}
              </div>
            ) : null}
          </div>

          <div style={styles.tableWrap}>
            <div style={styles.tableHeader}>
              <div>Linha</div>
              <div>Produto</div>
              <div>Qtd</div>
              <div>Preço lista</div>
              <div>Desc. %</div>
              <div>Preço venda</div>
              <div>Markup</div>
              <div>Total</div>
              <div></div>
            </div>

            {items.map((it, idx) => {
              const qty = toNum(it.qty);
              const unitDisc = toNum(it.unit_price_disc);
              const total = qty * unitDisc;
              const costPrice = extractCostPrice(it.product);
              const markupPct = calcMarkupPct(unitDisc, costPrice);

              const avail = getAvail(it);
              const maxHint = avail !== null ? ` (estoque: ${avail})` : "";
              const lastPriceRef =
                selectedClient?.id && it.product?.id
                  ? lastPriceByKey[lastPriceKey(selectedClient.id, it.product.id)]
                  : null;

              return (
                <div key={idx} style={styles.tableRow}>
                  <div style={{ fontWeight: 900, color: "var(--muted)", fontSize: 22, lineHeight: 1 }}>{idx + 1}</div>

                  <div style={{ minWidth: 0 }}>
                    {it.product ? (
                      <>
                        <div
                          style={{
                            fontWeight: 800,
                            fontSize: 13,
                            whiteSpace: "normal",
                            overflow: "visible",
                            textOverflow: "unset",
                            wordBreak: "normal",
                            overflowWrap: "break-word",
                            lineHeight: 1.25,
                          }}
                          title={it.product.nome}
                        >
                          {it.product.nome}
                        </div>
                        <div
                          style={{
                            ...styles.small,
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            wordBreak: "normal",
                            lineHeight: 1.2,
                            marginTop: 4,
                          }}
                          title={
                            lastPriceRef?.loading
                              ? `${it.product.codigo || ""}${maxHint} • Último preço: carregando...`
                              : lastPriceRef?.found
                                ? `${it.product.codigo || ""}${maxHint} • Último preço: ${formatBRL(lastPriceRef.unit_price_disc)} • ${formatDateBR(lastPriceRef.created_at)} • ${lastPriceOriginLabel(lastPriceRef)}`
                                : `${it.product.codigo || ""}${maxHint} • Último preço: sem histórico`
                          }
                        >
                          {it.product.codigo || ""}{maxHint}
                          {" • "}
                          {lastPriceRef?.loading
                            ? "Último preço: carregando..."
                            : lastPriceRef?.found
                              ? `Último preço: ${formatBRL(lastPriceRef.unit_price_disc)}`
                              : "Último preço: sem histórico"}
                        </div>
                      </>
                    ) : (
                      <span style={{ color: "var(--muted)" }}>Selecione um produto acima</span>
                    )}
                  </div>

                  <input
                    style={styles.numInput}
                    type="number"
                    value={it.qty}
                    min="0"
                    step="1"
                    onChange={(e) => setItem(idx, { qty: e.target.value })}
                    disabled={!it.product}
                  />
                  <input style={{ ...styles.numInput, opacity: 0.7 }} type="number" value={it.list_price} readOnly />

                  <input
                    style={styles.numInput}
                    type="number"
                    value={it.discount_pct}
                    min="0"
                    max={MAX_DISCOUNT_PCT}
                    step="0.01"
                    onChange={(e) => {
                      const r = recalcFromDiscountPct(it.list_price, e.target.value);
                      setItem(idx, { discount_pct: e.target.value, ...r });
                    }}
                    disabled={!it.product}
                  />

                  <input
                    style={styles.numInput}
                    type="number"
                    value={it.unit_price_disc}
                    min="0"
                    step="0.01"
                    onChange={(e) => {
                      const newUnit = toNum(e.target.value);
                      const r = recalcFromUnitDiscount(it.list_price, newUnit);
                      setItem(idx, { unit_price_disc: e.target.value, discount_pct: r.discount_pct });
                    }}
                    disabled={!it.product}
                  />

                  <div style={{ fontWeight: 900, color: markupPct !== null && markupPct < 0 ? "var(--danger)" : "var(--text)" }}>
                    {markupPct === null ? "—" : formatPct(markupPct)}
                  </div>

                  <div style={{ fontWeight: 900 }}>{formatBRL(total)}</div>

                  <button style={styles.button} onClick={() => removeLine(idx)} title="Remover">
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Envio/Frete */}
        <Card title="Envio e Frete (Tiny)">
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 10 }}>
            <div>
              <div style={styles.small}>Forma de envio <span style={{ color: "crimson", fontWeight: 900 }}>*</span></div>
              <select
                style={styles.select}
                value={selectedShippingId}
                onChange={(e) => setSelectedShippingId(e.target.value)}
                disabled={shippingLoading}
              >
                {shippingLoading ? <option value="">Carregando...</option> : <option value="">(selecione)</option>}
                {!shippingLoading && !shippingMethods.length ? <option value="">(sem formas cadastradas)</option> : null}
                {shippingMethods.map((m) => (
                  <option key={m.id} value={String(m.id)}>
                    {m.nome}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div style={styles.small}>Forma de frete <span style={{ color: "crimson", fontWeight: 900 }}>*</span></div>
              <select
                style={styles.select}
                value={selectedFreightId}
                onChange={(e) => setSelectedFreightId(e.target.value)}
                disabled={freightLoading || !selectedShippingId || !freightMethods.length}
              >
                {freightLoading ? <option value="">Carregando...</option> : <option value="">(selecione)</option>}
                {!freightLoading && !freightMethods.length ? <option value="">(nenhuma forma de frete)</option> : null}
                {freightMethods.map((f) => (
                  <option key={f.id} value={String(f.id)}>
                    {f.descricao}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </Card>

        {/* Pagamento */}
        <Card title="Pagamento (Tiny)">

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile
                ? "1fr"
                : isTablet
                  ? "repeat(2, minmax(0, 1fr))"
                  : "repeat(4, minmax(0, 1fr))",
              gap: 10,
            }}
          >
            <div>
              <div style={styles.small}>
                Forma de recebimento <span style={{ color: "crimson", fontWeight: 900 }}>*</span>
              </div>
              <select
                style={styles.select}
                value={selectedPaymentCode}
                onChange={(e) => {
                  setSelectedPaymentCode(e.target.value);
                  setInstallments([]);
                  setSelectedCardBrand("");
                }}
                disabled={paymentLoading}
              >
                {paymentLoading ? <option value="">Carregando...</option> : <option value="">(selecione)</option>}
                {!paymentLoading && !paymentMethods.length ? <option value="">(sem formas cadastradas)</option> : null}
                {paymentMethods.map((m) => (
                  <option key={m.code} value={String(m.code)}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>

            {paymentRule.showMeio ? (
              <div>
                <div style={styles.small}>Meio</div>
                <select
                  style={styles.select}
                  value={selectedPaymentMeio}
                  onChange={(e) => setSelectedPaymentMeio(e.target.value)}
                  disabled={paymentRule.meioLocked}
                >
                  {PAYMENT_MEIOS.map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div />
            )}

            {paymentRule.showConta ? (
              <div>
                <div style={styles.small}>{paymentRule.contaLabel}</div>
                <select
                  style={styles.select}
                  value={selectedPaymentConta}
                  onChange={(e) => setSelectedPaymentConta(e.target.value)}
                >
                  {(paymentRule.contas || PAYMENT_CONTAS).map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div />
            )}

            <div>
              <div style={styles.small}>
                Vencimento <span style={{ color: "crimson", fontWeight: 900 }}>*</span>
              </div>
              <input
                type="date"
                style={styles.input}
                value={paymentDueDate}
                min={todayLocalISODate()}
                onChange={(e) => setPaymentDueDate(clampNotPastISODate(e.target.value))}
              />
            </div>
          </div>

          {paymentKind === "cartao_credito" ? (
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "320px 1fr", gap: 10, marginTop: 12 }}>
              <div>
                <div style={styles.small}>
                  Bandeira <span style={{ color: "crimson", fontWeight: 900 }}>*</span>
                </div>
                <select
                  style={styles.select}
                  value={selectedCardBrand}
                  onChange={(e) => setSelectedCardBrand(e.target.value)}
                >
                  {CARD_BRANDS.map((b) => (
                    <option key={b.code} value={b.code}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <div style={styles.small}>
                  Categoria <span style={{ color: "crimson", fontWeight: 900 }}>*</span>
                </div>
                <select
                  style={styles.select}
                  value={paymentCategory}
                  onChange={(e) => setPaymentCategory(e.target.value)}
                >
                  {PAYMENT_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "320px 1fr", gap: 10, marginTop: 12 }}>
              <div>
                <div style={styles.small}>
                  Categoria <span style={{ color: "crimson", fontWeight: 900 }}>*</span>
                </div>
                <select
                  style={styles.select}
                  value={paymentCategory}
                  onChange={(e) => setPaymentCategory(e.target.value)}
                >
                  {PAYMENT_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div />
            </div>
          )}

          {showPaymentCondition ? (
            <div style={{ marginTop: 12 }}>
              <div>
                <div style={styles.small}>
                  Condição de pagamento <span style={{ color: "crimson", fontWeight: 900 }}>*</span>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: isMobile ? "1fr" : "1fr auto",
                    gap: 10,
                    alignItems: "center",
                  }}
                >
                  <input
                    style={styles.input}
                    value={paymentCondition}
                    onChange={(e) => {
                      setPaymentCondition(e.target.value);
                      setInstallments([]);
                    }}
                    placeholder='Ex.: "parcelado em 3x" ou "30 60 90" (0 = à  vista)'
                    list="condicoes-pagto"
                  />

                  <Button variant="secondary" onClick={generateInstallments}>
                    Gerar parcelas
                  </Button>
                </div>

                <datalist id="condicoes-pagto">
                  {commonConditions.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </datalist>

                <div style={{ ...styles.small, marginTop: 6 }}>
                  Dica: selecione "parcelado em 1x..12x" ou digite os dias (ex.: 30 60 90). 0/blank = à vista.
                </div>
              </div>

              {installments.length ? (
                <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 0, overflow: "hidden" }}>
                  <div
                    style={{
                      padding: 10,
                      background: "rgba(0,0,0,0.03)",
                      borderBottom: "1px solid var(--border)",
                      fontWeight: 900,
                      fontSize: 12,
                      color: "var(--muted)",
                    }}
                  >
                    Parcelas geradas
                  </div>
                  <div style={{ padding: 10, display: "grid", gridTemplateColumns: "80px 1fr 1fr", gap: 10, fontSize: 12 }}>
                    <div style={{ fontWeight: 900, color: "var(--muted)" }}>Parcela</div>
                    <div style={{ fontWeight: 900, color: "var(--muted)" }}>Vencimento</div>
                    <div style={{ fontWeight: 900, color: "var(--muted)", textAlign: "right" }}>Valor</div>

                    {installments.map((pag) => (
                      <div key={pag.n} style={{ display: "contents" }}>
                        <div>{pag.n}</div>
                        <div>{pag.due_date}</div>
                        <div style={{ textAlign: "right", fontWeight: 900 }}>{formatBRL(pag.amount)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </Card>

        <Card title="Nota Fiscal">
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <Button
              type="button"
              variant={invoiceProfile === "A" ? "primary" : "secondary"}
              onClick={() => setInvoiceProfile("A")}
              style={{ minWidth: 130 }}
            >
              A = Com NF
            </Button>

            <Button
              type="button"
              variant={invoiceProfile === "B" ? "primary" : "secondary"}
              onClick={() => setInvoiceProfile("B")}
              style={{ minWidth: 130 }}
            >
              B = Sem NF
            </Button>
          </div>
        </Card>

        <Card title="Fretes">
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 12 }}>
            <div>
              <div style={{ ...styles.small, marginBottom: 6 }}>Frete pago pelo Cliente</div>
              <input
                style={styles.input}
                value={freightPaidClient}
                onChange={(e) => setFreightPaidClient(e.target.value)}
                placeholder="0,00"
                inputMode="decimal"
              />
            </div>
            <div>
              <div style={{ ...styles.small, marginBottom: 6 }}>Frete pago pela Empresa</div>
              <input
                style={styles.input}
                value={freightPaidCompany}
                onChange={(e) => setFreightPaidCompany(e.target.value)}
                placeholder="0,00"
                inputMode="decimal"
              />
            </div>
          </div>
        </Card>

        {/* Observações */}
        <Card
          title="Observações"
          actions={
            <span style={{ color: "#ef4444", fontSize: 12, fontWeight: 900 }}>
              Aparece na NF.
            </span>
          }
        >
          <textarea
            style={styles.textarea}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Observações comerciais, condições combinadas, observações do cliente..."
          />
        </Card>

        <Card
          title="OBS Interna"
          actions={
            <span style={{ color: "#ef4444", fontSize: 12, fontWeight: 900 }}>
              Aparece somente na folha do pedido.
            </span>
          }
        >
          <textarea
            style={styles.textarea}
            value={internalNotes}
            onChange={(e) => setInternalNotes(e.target.value)}
            placeholder="Observações internas da equipe, instruções internas, informações que não devem aparecer ao cliente..."
          />
        </Card>

        {/* Resumo */}
        <div style={styles.summaryBox}>
          <div style={styles.summaryLine}>
            <span>Total</span>
            <span>{formatBRL(totals.net)}</span>
          </div>

          
<div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', alignItems: 'center', marginTop: 6 }}>

  {editingQuote && (
    <Button variant="ghost" onClick={cancelEditing}>
      Cancelar edição
    </Button>
  )}

  <Button
    variant="secondary"
    onClick={() => {
      if (!confirm('Tem certeza que deseja limpar todo o orçamento?')) return;

      clearDraft();

      setSelectedSeller(null);
      setSellerQuery("");
      setSelectedClient(null);
      setClientQuery("");

      setItems([
        { product: null, qty: 1, list_price: 0, discount_pct: 0, unit_price_disc: 0, stock: null }
      ]);

      setNotes("");
      setFreightPaidClient("");
      setFreightPaidCompany("");
      setInternalNotes("");
      setInvoiceProfile("A");
      setPaymentCondition("");
      setInstallments([]);
      setSelectedCardBrand("");
      setPaymentDueDate(todayLocalISODate());
    }}
  >
    Limpar
  </Button>

  <Button variant="primary" loading={saving} onClick={onSave}>
    {saving ? "Salvando..." : editingQuote ? "Atualizar Pré-venda" : "Salvar Pré-venda"}
  </Button>

</div>

        </div>
      </div>


            {previewOpen && (previewData?.quote || previewData) ? (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
            zIndex: 9999,
          }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setPreviewOpen(false);
          }}
        >
          <div
            style={{
              width: "min(1180px, 98vw)",
              maxHeight: "92vh",
              overflow: "auto",
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: 22,
              padding: 20,
              boxShadow: "0 24px 54px rgba(0,0,0,0.28)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 12,
                marginBottom: 14,
                flexWrap: "wrap",
              }}
            >
              <div>
                <div style={{ fontSize: 16, fontWeight: 900 }}>Pré-venda salva com sucesso</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>
                  Confira os dados antes de imprimir.
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  type="button"
                  style={styles.button}
                  onClick={() => {
                    openQuotePrintWindow({
                      quote: previewData.quote,
                      items: previewData.items || [],
                    });
                  }}
                >
                  Ver PDF
                </button>
                <button
                  type="button"
                  style={styles.button}
                  onClick={() => setPreviewOpen(false)}
                >
                  Fechar
                </button>
              </div>
            </div>

            <div style={{ ...styles.section, marginBottom: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 12 }} >
                <div>
                  <div style={styles.small}>Número</div>
                  <div style={{ fontWeight: 800 }}>{previewData.quote?.quote_number || "—"}</div>
                </div>
                <div>
                  <div style={styles.small}>Cliente</div>
                  <div style={{ fontWeight: 800 }}>
                    {previewData.quote?.client_name ||
                      previewData.quote?.client_snapshot?.nome ||
                      previewData.quote?.client_snapshot?.name ||
                      selectedClient?.name ||
                      selectedClient?.nome ||
                      editingQuote?.client_name ||
                      "—"}
                  </div>
                </div>
                <div>
                  <div style={styles.small}>Vendedor</div>
                  <div style={{ fontWeight: 800 }}>{previewData.quote?.seller_name || "—"}</div>
                </div>
                <div>
                  <div style={styles.small}>Status</div>
                  <div style={{ fontWeight: 800 }}>{previewData.quote?.internal_status || previewData.quote?.status || "Orçamento"}</div>
                </div>
                <div>
                  <div style={styles.small}>Envio</div>
                  <div style={{ fontWeight: 800 }}>
                    {previewData.quote?.shipping_method_name || previewData.quote?.shipping_method || "—"}
                  </div>
                </div>
                <div>
                  <div style={styles.small}>Pagamento</div>
                  <div style={{ fontWeight: 800 }}>
                    {previewData.quote?.payment_method_name || previewData.quote?.payment_method_code || "—"}
                  </div>
                </div>
              </div>
            </div>

            <div style={styles.tableWrap}>
              <div style={styles.tableHeader}>
                <div>Linha</div>
                <div>Produto</div>
                <div>Qtd</div>
                <div>Unitário</div>
                <div>Total</div>
                <div></div>
                <div></div>
                <div></div>
                <div></div>
              </div>

              {(previewData.items || []).map((item, idx) => (
                <div key={idx} style={styles.tableRow}>
                  <div>{idx + 1}</div>
                  <div>{item?.name_snapshot || item?.descricao || item?.product_description || item?.sku || "—"}</div>
                  <div>{item?.qty ?? item?.quantidade ?? "—"}</div>
                  <div>{formatBRL(item?.unit_price_disc ?? item?.unitario ?? 0)}</div>
                  <div>{formatBRL(item?.line_total ?? item?.total ?? 0)}</div>
                  <div></div>
                  <div></div>
                  <div></div>
                  <div></div>
                </div>
              ))}
            </div>

            <div
              style={{
                ...styles.summaryBox,
                marginTop: 16,
                padding: 14,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontSize: 16,
                fontWeight: 900,
              }}
            >
              <span>Total da pré-venda</span>
              <span>{formatBRL(
                previewData.quote?.totals?.net ||
                previewData.quote?.totals?.total ||
                (previewData.items || []).reduce((acc, item) => {
                  const qty = Number(item?.qty ?? item?.quantity ?? 0) || 0;
                  const direct =
                    Number(item?.line_total ?? item?.total ?? 0) || 0;
                  const unit =
                    Number(item?.unit_effective ?? item?.unit_price ?? item?.price ?? 0) || 0;
                  return acc + (direct || (qty * unit));
                }, 0)
              )}</span>
            </div>
          </div>
        </div>
      ) : null}
      <QuotesModal
        open={quotesModalOpen}
        onClose={() => setQuotesModalOpen(false)}
        onOpenPreview={(detail) => {
          const normalizedDetail =
            detail?.quote
              ? detail
              : detail
                ? {
                    quote: detail,
                    items: detail?.items || detail?.quote_items || [],
                  }
                : null;

          if (!normalizedDetail?.quote) return;
          setPreviewData(normalizedDetail);
          setPreviewOpen(true);
        }}
        onEditQuote={(quoteId) => startEditQuote(quoteId)}
      />

      <StockModal
        open={stockModalOpen}
        onClose={() => setStockModalOpen(false)}
        api={api}
        preloadStockForProducts={preloadStockForProducts}
        stockById={stockById}
        formatBRL={formatBRL}
      />
    </div>
  );
}








