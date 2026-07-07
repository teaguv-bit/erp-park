import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { openQuotePrintWindow } from "../utils/quotePrint";

const styles = {
  wrap: {
    display: "grid",
    gap: 14,
  },

  toolbarCard: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 18,
    padding: 14,
    boxShadow: "0 10px 30px rgba(2,6,23,.18)",
  },

  searchRow: {
    display: "grid",
    gridTemplateColumns: "1fr auto",
    gap: 12,
    alignItems: "end",
  },

  label: {
    display: "block",
    fontSize: 12,
    color: "var(--muted)",
    marginBottom: 6,
  },

  input: {
    width: "100%",
    background: "var(--bg-elev)",
    color: "var(--text)",
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: "12px 14px",
    outline: "none",
    fontSize: 13,
  },

  btn: {
    border: "1px solid var(--border)",
    background: "var(--bg-elev)",
    color: "var(--text)",
    borderRadius: 12,
    padding: "10px 14px",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
  },

  btnPrimary: {
    border: "1px solid var(--primary)",
    background: "var(--primary)",
    color: "#fff",
    borderRadius: 12,
    padding: "10px 14px",
    cursor: "pointer",
    fontWeight: 800,
    fontSize: 13,
  },

  tabsWrap: {
    display: "flex",
    gap: 20,
    alignItems: "flex-end",
    flexWrap: "wrap",
    marginTop: 14,
    borderBottom: "1px solid var(--border)",
    paddingBottom: 6,
  },

  tab: {
    appearance: "none",
    background: "transparent",
    border: "none",
    color: "var(--muted)",
    cursor: "pointer",
    padding: "6px 0 10px",
    borderBottom: "2px solid transparent",
    fontWeight: 800,
    fontSize: 13,
  },

  tabActive: {
    color: "var(--text)",
    borderBottom: "2px solid var(--primary)",
  },

  tabCount: {
    display: "block",
    fontSize: 11,
    fontWeight: 600,
    marginTop: 4,
    opacity: 0.9,
  },

  tableCard: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 18,
    padding: 14,
    boxShadow: "0 10px 30px rgba(2,6,23,.18)",
  },

  tableWrap: {
    overflowX: "auto",
    border: "1px solid var(--border)",
    borderRadius: 14,
  },

  table: {
    width: "100%",
    borderCollapse: "collapse",
    minWidth: 980,
  },

  th: {
    textAlign: "left",
    fontSize: 12,
    fontWeight: 700,
    color: "var(--muted)",
    padding: "10px 10px",
    borderBottom: "1px solid var(--border)",
    background: "rgba(255,255,255,.02)",
  },

  td: {
    padding: "10px 10px",
    borderBottom: "1px solid var(--border)",
    verticalAlign: "middle",
  },

  detailCard: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 18,
    padding: 14,
    boxShadow: "0 10px 30px rgba(2,6,23,.18)",
  },

  actionRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap",
    marginBottom: 12,
  },

  chips: {
    display: "flex",
    gap: 8,
    flexWrap: "wrap",
    marginBottom: 12,
  },

  chip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 10px",
    borderRadius: 999,
    background: "rgba(59,130,246,.12)",
    color: "var(--text)",
    border: "1px solid rgba(59,130,246,.22)",
    fontSize: 12,
    fontWeight: 700,
  },

  metaGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0,1fr))",
    gap: 12,
    marginBottom: 14,
  },

  miniCard: {
    background: "var(--bg-elev)",
    border: "1px solid var(--border)",
    borderRadius: 14,
    padding: 12,
  },

  miniLabel: {
    color: "var(--muted)",
    fontSize: 12,
    marginBottom: 4,
  },

  miniValue: {
    fontWeight: 800,
  },

  muted: {
    color: "var(--muted)",
  },

  error: {
    color: "#ef4444",
    fontWeight: 700,
    marginBottom: 12,
  },

  success: {
    color: "#22c55e",
    fontWeight: 700,
    marginBottom: 12,
  },
};

function fmtDate(s) {
  try {
    const d = new Date(s);
    return d.toLocaleString("pt-BR");
  } catch {
    return s || "";
  }
}

function formatBRL(n) {
  const v = Number(n || 0);
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function safeJsonParse(v, fallback = null) {
  if (!v) return fallback;
  if (typeof v === "object") return v;
  try {
    return JSON.parse(v);
  } catch {
    return fallback;
  }
}

function quoteNumberOf(q) {
  return q?.quote_number || q?.numero || q?.number || "—";
}

function clientNameOf(q) {
  if (q?.client_name) return q.client_name;
  const parsed = safeJsonParse(q?.client_snapshot, {});
  return parsed?.nome || parsed?.name || "—";
}

function sellerNameOf(q) {
  if (q?.seller_name) return q.seller_name;
  const payload = safeJsonParse(q?.payload, {});
  return payload?.seller_name || "—";
}

function totalOfQuote(q) {
  const totals = safeJsonParse(q?.totals, {});
  if (Number(totals?.net || 0) > 0) return Number(totals.net);
  return Number(q?.total_net || 0);
}

function payloadOf(q) {
  return safeJsonParse(q?.payload, {});
}

function statusLabel(status) {
  const s = String(status || "").toLowerCase();
  if (s === "draft") return "Rascunho";
  if (s === "ordered") return "Pedido criado";
  if (s === "cancelled") return "Cancelado";
  return status || "—";
}

async function listQuotesSafe({ status = "draft", q = "", limit = 50, offset = 0 }) {
  if (typeof api.listQuotes === "function") {
    try {
      return await api.listQuotes({ status, q, limit, offset });
    } catch {
      return await api.listQuotes(status, limit, offset);
    }
  }

  if (typeof api.getQuotes === "function") {
    return await api.getQuotes({ status, q, limit, offset });
  }

  throw new Error("Função de listagem de orçamentos não encontrada no api.js.");
}

async function getQuoteSafe(id) {
  if (typeof api.getQuote === "function") return api.getQuote(id);
  throw new Error("Função getQuote não encontrada no api.js.");
}

async function createOrderSafe(id) {
  if (typeof api.createOrderFromQuote === "function") return api.createOrderFromQuote(id);
  if (typeof api.createOrder === "function") return api.createOrder(id);
  if (typeof api.quoteCreateOrder === "function") return api.quoteCreateOrder(id);
  throw new Error("Função de criar pedido não encontrada no api.js.");
}

export default function QuotesList({ onCreateNew }) {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState([]);

  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [error, setError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState("");

  const [search, setSearch] = useState("");
  const [statusTab, setStatusTab] = useState("draft");

  async function refresh(forceStatus = statusTab, forceSearch = search) {
    setError("");
    setLoading(true);
    try {
      const r = await listQuotesSafe({
        status: forceStatus,
        q: forceSearch,
        limit: 200,
        offset: 0,
      });
      setItems(r?.items || []);
    } catch (e) {
      setError(e.message || "Erro ao carregar orçamentos.");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh(statusTab, search);
  }, [statusTab]);

  async function onSearchSubmit(e) {
    e?.preventDefault?.();
    refresh(statusTab, search);
  }

  async function openQuote(quoteId) {
    if (!quoteId) return;
    setError("");
    setActionMessage("");
    setSelectedId(quoteId);
    setDetail(null);
    setDetailLoading(true);

    try {
      const r = await getQuoteSafe(quoteId);
      setDetail(r);
    } catch (e) {
      setError(e.message || "Erro ao abrir orçamento.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function createOrder() {
    if (!selectedId) return;
    setError("");
    setActionMessage("");
    setActionLoading(true);

    try {
      const r = await createOrderSafe(selectedId);

      const tinyNumber =
        r?.tiny_order_number ||
        r?.order_number ||
        r?.pedido?.numero ||
        r?.numero ||
        "";

      setActionMessage(
        tinyNumber
          ? `Pedido criado com sucesso no Tiny. Nº ${tinyNumber}`
          : "Pedido criado com sucesso no Tiny."
      );

      await refresh(statusTab, search);

      try {
        const d = await getQuoteSafe(selectedId);
        setDetail(d);
      } catch {}
    } catch (e) {
      setError(e.message || "Erro ao criar pedido.");
    } finally {
      setActionLoading(false);
    }
  }

  function handleViewPdf() {
    if (!detail?.quote) return;
    openQuotePrintWindow({
      quote: detail.quote,
      items: detail.items || [],
    });
  }

  const draftCount = useMemo(
    () => items.filter((x) => String(x?.status || "").toLowerCase() === "draft").length,
    [items]
  );

  const orderedCount = useMemo(
    () => items.filter((x) => String(x?.status || "").toLowerCase() === "ordered").length,
    [items]
  );

  const totals = (() => {
    try {
      return detail?.quote?.totals ? JSON.parse(detail.quote.totals) : null;
    } catch {
      return null;
    }
  })();

  return (
    <div style={styles.wrap}>
      <div style={styles.toolbarCard}>
        <form onSubmit={onSearchSubmit} style={styles.searchRow}>
          <div>
            <label style={styles.label}>Buscar</label>
            <input
              style={styles.input}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Número, cliente ou vendedor"
            />
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button type="submit" style={styles.btnPrimary}>
              Buscar
            </button>

            <button
              type="button"
              style={styles.btn}
              onClick={() => {
                setSearch("");
                refresh(statusTab, "");
              }}
            >
              Limpar
            </button>

            {typeof onCreateNew === "function" ? (
              <button type="button" style={styles.btn} onClick={onCreateNew}>
                + Novo orçamento
              </button>
            ) : null}
          </div>
        </form>

        <div style={styles.tabsWrap}>
          <button
            type="button"
            style={{
              ...styles.tab,
              ...(statusTab === "draft" ? styles.tabActive : {}),
            }}
            onClick={() => setStatusTab("draft")}
          >
            Rascunhos
            <span style={styles.tabCount}>{statusTab === "draft" ? items.length : draftCount}</span>
          </button>

          <button
            type="button"
            style={{
              ...styles.tab,
              ...(statusTab === "ordered" ? styles.tabActive : {}),
            }}
            onClick={() => setStatusTab("ordered")}
          >
            Pedidos criados
            <span style={styles.tabCount}>{statusTab === "ordered" ? items.length : orderedCount}</span>
          </button>
        </div>
      </div>

      <div style={styles.tableCard}>
        {error ? <div style={styles.error}>{error}</div> : null}

        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Pré-venda Nº</th>
                <th style={styles.th}>Cliente</th>
                <th style={styles.th}>Vendedor</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Data</th>
                <th style={styles.th}>Total</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {!loading && items.length === 0 ? (
                <tr>
                  <td style={styles.td} colSpan={7}>
                    <span style={styles.muted}>Nenhum orçamento encontrado.</span>
                  </td>
                </tr>
              ) : null}

              {items.map((q) => (
                <tr key={q?.id}>
                  <td style={styles.td}>
                    <strong>{quoteNumberOf(q)}</strong>
                  </td>
                  <td style={styles.td}>{clientNameOf(q)}</td>
                  <td style={styles.td}>{sellerNameOf(q)}</td>
                  <td style={styles.td}>{statusLabel(q?.status)}</td>
                  <td style={styles.td}>{fmtDate(q?.created_at)}</td>
                  <td style={styles.td}>
                    <strong>{formatBRL(totalOfQuote(q))}</strong>
                  </td>
                  <td style={styles.td}>
                    <button type="button" style={styles.btn} onClick={() => openQuote(q?.id)}>
                      Abrir
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selectedId ? (
        <div style={styles.detailCard}>
          <div style={styles.actionRow}>
            <div style={{ fontWeight: 900, fontSize: 16 }}>Detalhe do orçamento</div>

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                onClick={createOrder}
                disabled={actionLoading || detail?.quote?.status !== "draft"}
                style={{
                  ...styles.btnPrimary,
                  cursor: detail?.quote?.status === "draft" ? "pointer" : "not-allowed",
                  opacity: detail?.quote?.status === "draft" ? 1 : 0.65,
                }}
                title={
                  detail?.quote?.status !== "draft"
                    ? "Esse orçamento não está mais em rascunho."
                    : ""
                }
              >
                {actionLoading ? "Criando pedido no Tiny..." : "Criar pedido no Tiny"}
              </button>

              <button onClick={handleViewPdf} disabled={!detail?.quote} style={styles.btn}>
                Ver PDF
              </button>

              <button onClick={() => openQuote(selectedId)} disabled={!selectedId} style={styles.btn}>
                Recarregar
              </button>
            </div>
          </div>

          {actionMessage ? <div style={styles.success}>{actionMessage}</div> : null}
          {detailLoading ? <div style={styles.muted}>Carregando detalhe…</div> : null}

          {!detailLoading && detail?.quote ? (
            <>
              <div style={styles.chips}>
                <span style={styles.chip}>Pré-venda Nº {quoteNumberOf(detail.quote)}</span>
                <span style={styles.chip}>Status: {statusLabel(detail.quote?.status)}</span>
                <span style={styles.chip}>Cliente: {clientNameOf(detail.quote)}</span>
                <span style={styles.chip}>Vendedor: {sellerNameOf(detail.quote)}</span>
              </div>

              <div style={styles.metaGrid}>
                <div style={styles.miniCard}>
                  <div style={styles.miniLabel}>Forma de envio</div>
                  <div style={styles.miniValue}>{detail.quote?.shipping_method_name || "—"}</div>
                </div>

                <div style={styles.miniCard}>
                  <div style={styles.miniLabel}>Forma de frete</div>
                  <div style={styles.miniValue}>{detail.quote?.freight_method_name || "—"}</div>
                </div>

                <div style={styles.miniCard}>
                  <div style={styles.miniLabel}>Total</div>
                  <div style={{ ...styles.miniValue, fontSize: 18 }}>
                    {formatBRL(totals?.net || totalOfQuote(detail.quote))}
                  </div>
                </div>
              </div>

              <div style={styles.tableWrap}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Linha</th>
                      <th style={styles.th}>Produto</th>
                      <th style={styles.th}>SKU</th>
                      <th style={styles.th}>Qtd</th>
                      <th style={styles.th}>Preço venda</th>
                      <th style={styles.th}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!(detail.items || []).length ? (
                      <tr>
                        <td style={styles.td} colSpan={6}>
                          <span style={styles.muted}>Sem itens.</span>
                        </td>
                      </tr>
                    ) : null}

                    {(detail.items || []).map((it, idx) => (
                      <tr key={idx}>
                        <td style={styles.td}>{it?.line || idx + 1}</td>
                        <td style={styles.td}>{it?.name_snapshot || "—"}</td>
                        <td style={styles.td}>{it?.sku_snapshot || "—"}</td>
                        <td style={styles.td}>{it?.qty || 0}</td>
                        <td style={styles.td}>{formatBRL(it?.unit_price_disc || 0)}</td>
                        <td style={styles.td}>{formatBRL(it?.line_total || 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {detail.quote?.notes ? (
                <div style={{ marginTop: 14 }}>
                  <div style={{ fontWeight: 800, marginBottom: 6 }}>Observações</div>
                  <div
                    style={{
                      ...styles.miniCard,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {detail.quote.notes}
                  </div>
                </div>
              ) : null}

              {Array.isArray(payloadOf(detail.quote)?.payment_installments) &&
              payloadOf(detail.quote)?.payment_installments?.length ? (
                <div style={{ marginTop: 14 }}>
                  <div style={{ fontWeight: 800, marginBottom: 8 }}>Parcelas</div>
                  <div style={styles.tableWrap}>
                    <table style={styles.table}>
                      <thead>
                        <tr>
                          <th style={styles.th}>Parcela</th>
                          <th style={styles.th}>Vencimento</th>
                          <th style={styles.th}>Valor</th>
                        </tr>
                      </thead>
                      <tbody>
                        {payloadOf(detail.quote).payment_installments.map((p, idx) => (
                          <tr key={idx}>
                            <td style={styles.td}>{p?.n || idx + 1}</td>
                            <td style={styles.td}>{p?.due_date || "—"}</td>
                            <td style={styles.td}>{formatBRL(p?.amount || 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}