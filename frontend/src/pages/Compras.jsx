import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Button, Card, Table, StatusPill, Field, Toolbar, PageHeader, EmptyState, Spinner } from "../ui";

const COMPANIES = [
  { key: "parton", label: "Suprimentos" },
  { key: "park", label: "Informática" },
];

const SITUACOES_COMPRA = [
  { value: "", label: "Todas as situações" },
  { value: "aberto", label: "Em aberto" },
  { value: "aprovado", label: "Aprovado" },
  { value: "em_andamento", label: "Em andamento" },
  { value: "parcialmente_recebido", label: "Parcialmente recebido" },
  { value: "recebido", label: "Recebido" },
  { value: "cancelado", label: "Cancelado" },
];

const MARKETPLACE_OPTIONS = [
  { value: "", label: "Todos os canais" },
  { value: "marketplace", label: "Marketplace / E-commerce" },
  { value: "direto", label: "Compra direta" },
];

const TIPO_ESTOQUE_LABEL = { E: "Entrada", S: "Saída", B: "Balanço", T: "Transferência" };

const PAGE_SIZE_OPTIONS = [20, 50, 100];

function formatBRL(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function formatDate(value) {
  if (!value) return "—";
  // value pode vir yyyy-mm-dd ou dd/mm/yyyy
  const iso = value.includes("/") ? value.split("/").reverse().join("-") : value;
  const parsed = new Date(iso + "T00:00:00");
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("pt-BR");
}

function formatQtd(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return Number.isInteger(n)
    ? n.toLocaleString("pt-BR")
    : n.toLocaleString("pt-BR", { maximumFractionDigits: 3 });
}

function situacaoBadge(situacao) {
  const s = String(situacao || "").toLowerCase();
  const map = {
    aberto: { label: "Em aberto", bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
    aprovado: { label: "Aprovado", bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
    em_andamento: { label: "Em andamento", bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
    parcialmente_recebido: { label: "Parcial", bg: "#fef3c7", color: "#78350f", border: "#fcd34d" },
    recebido: { label: "Recebido", bg: "#dcfce7", color: "#14532d", border: "#86efac" },
    cancelado: { label: "Cancelado", bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
  };
  return map[s] || { label: situacao || "—", bg: "rgba(148,163,184,.1)", color: "var(--muted)", border: "var(--border)" };
}

function tipoBadge(tipo) {
  const t = String(tipo || "").toUpperCase();
  const map = {
    E: { label: "Entrada", bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
    S: { label: "Saída", bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
    B: { label: "Balanço", bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
    T: { label: "Transferência", bg: "#faf5ff", color: "#6b21a8", border: "#e9d5ff" },
  };
  return map[t] || { label: tipo || "—", bg: "rgba(148,163,184,.1)", color: "var(--muted)", border: "var(--border)" };
}

function Badge({ label, bg, color, border }) {
  return (
    <span style={{ background: bg, color, border: `1px solid ${border}`, borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 800, whiteSpace: "nowrap" }}>
      {label}
    </span>
  );
}

const styles = {
  page: { display: "grid", gap: 16 },
  header: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" },
  title: { fontSize: 28, fontWeight: 950, letterSpacing: 0 },
  muted: { color: "var(--muted)", fontSize: 13 },
  tabs: { display: "flex", gap: 0, borderBottom: "2px solid var(--border)", marginBottom: 2 },
  tab: { padding: "10px 20px", fontWeight: 800, fontSize: 13, cursor: "pointer", border: "none", background: "none", color: "var(--muted)", borderBottom: "2px solid transparent", marginBottom: -2 },
  tabActive: { color: "var(--text)", borderBottom: "2px solid var(--accent)" },
  filters: { display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" },
  fieldLabel: { display: "grid", gap: 4, fontSize: 12, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".03em" },
  input: { border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 10px", boxSizing: "border-box", minWidth: 160 },
  select: { border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 10px", fontWeight: 800 },
  button: { border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 14px", fontWeight: 900, cursor: "pointer" },
  primary: { background: "#1d4ed8", color: "#fff", borderColor: "#1d4ed8" },
  tableWrap: { border: "1px solid var(--border)", background: "var(--panel, #fff)", overflow: "auto" },
  table: { width: "100%", borderCollapse: "collapse", minWidth: 900 },
  th: { textAlign: "left", padding: "10px 12px", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: 12, textTransform: "uppercase", whiteSpace: "nowrap" },
  td: { padding: "10px 12px", borderBottom: "1px solid var(--border)", verticalAlign: "middle" },
  trHover: { cursor: "pointer" },
  pagination: { display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end", flexWrap: "wrap" },
  errorBox: { background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b", padding: "12px 16px", borderRadius: 4 },
  emptyBox: { textAlign: "center", padding: 40, color: "var(--muted)" },
  modal: {
    position: "fixed", inset: 0, background: "rgba(8,15,33,0.45)", display: "flex", alignItems: "flex-start",
    justifyContent: "center", zIndex: 9998, padding: "40px 16px", overflowY: "auto",
  },
  modalBox: {
    background: "var(--panel, #fff)", border: "1px solid var(--border)", width: "100%", maxWidth: 860,
    maxHeight: "calc(100vh - 80px)", overflowY: "auto", position: "relative",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid var(--border)" },
  modalBody: { padding: 20 },
  closeBtn: { border: "1px solid var(--border)", background: "none", color: "var(--muted)", padding: "4px 10px", cursor: "pointer", fontWeight: 900, fontSize: 16 },
  grid2: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 },
  grid3: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 },
  detailItem: { display: "grid", gap: 2 },
  detailLabel: { fontSize: 11, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase" },
  detailValue: { fontSize: 14, fontWeight: 600 },
  sectionTitle: { fontSize: 12, fontWeight: 900, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".04em", marginTop: 16, marginBottom: 8, borderBottom: "1px solid var(--border)", paddingBottom: 4 },
};

function DetailItem({ label, value }) {
  return (
    <div style={styles.detailItem}>
      <div style={styles.detailLabel}>{label}</div>
      <div style={styles.detailValue}>{value || "—"}</div>
    </div>
  );
}

// ── Aba: Pedidos de Compra ─────────────────────────────────────────────────────
function PedidosCompra({ company }) {
  const [filters, setFilters] = useState({ situacao: "", marketplace: "", data_inicial: "", data_final: "", fornecedor: "", pesquisa: "" });
  const [pagina, setPagina] = useState(1);
  const [numPaginas, setNumPaginas] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pedidos, setPedidos] = useState([]);
  const [detalhe, setDetalhe] = useState(null);
  const [detalheLoading, setDetalheLoading] = useState(false);
  const [detalheError, setDetalheError] = useState("");

  const load = useCallback(async (pg = 1) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ company, pagina: pg, ...filters });
      const data = await api.get(`/admin/compras?${params}`);
      setPedidos(data.pedidos || []);
      setNumPaginas(data.numero_paginas || 1);
      setPagina(data.pagina || pg);
    } catch (e) {
      setError(e?.message || "Erro ao carregar pedidos de compra.");
      setPedidos([]);
    } finally {
      setLoading(false);
    }
  }, [company, filters]);

  useEffect(() => {
    setPagina(1);
    load(1);
  }, [company, filters, load]);

  async function abrirDetalhe(id) {
    setDetalhe({ id, loading: true });
    setDetalheLoading(true);
    setDetalheError("");
    try {
      const params = new URLSearchParams({ company });
      const data = await api.get(`/admin/compras/${id}?${params}`);
      setDetalhe(data.pedido || {});
    } catch (e) {
      setDetalheError(e?.message || "Erro ao carregar detalhe.");
      setDetalhe({});
    } finally {
      setDetalheLoading(false);
    }
  }

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div style={styles.page}>
      <Toolbar>
        <Field label="Situação">
          <select value={filters.situacao} onChange={(e) => setFilter("situacao", e.target.value)} style={{ minWidth: 180 }}>
            {SITUACOES_COMPRA.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </Field>
        <Field label="Canal">
          <select value={filters.marketplace} onChange={(e) => setFilter("marketplace", e.target.value)} style={{ minWidth: 180 }}>
            {MARKETPLACE_OPTIONS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </Field>
        <Field label="Data inicial">
          <input type="date" value={filters.data_inicial} onChange={(e) => setFilter("data_inicial", e.target.value)} style={{ minWidth: 150 }} />
        </Field>
        <Field label="Data final">
          <input type="date" value={filters.data_final} onChange={(e) => setFilter("data_final", e.target.value)} style={{ minWidth: 150 }} />
        </Field>
        <Field label="Fornecedor">
          <input type="text" placeholder="Nome ou CNPJ" value={filters.fornecedor} onChange={(e) => setFilter("fornecedor", e.target.value)} style={{ minWidth: 200 }} />
        </Field>
        <Field label="Pesquisa">
          <input type="text" placeholder="Número, observação…" value={filters.pesquisa} onChange={(e) => setFilter("pesquisa", e.target.value)} style={{ minWidth: 180 }} />
        </Field>
        <Button variant="primary" loading={loading} onClick={() => load(1)}>
          Buscar
        </Button>
      </Toolbar>

      <Table>
        <thead>
          <tr>
            <th>Nº Pedido</th>
            <th>Fornecedor</th>
            <th>Data Pedido</th>
            <th>Data Previsão</th>
            <th>Situação</th>
            <th data-numeric>Total Produtos</th>
            <th data-numeric>Total Pedido</th>
            <th>Pagamento</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr><td colSpan={8} style={{ textAlign: "center", padding: 24 }}><Spinner label="Carregando" /></td></tr>
          ) : error ? (
            <tr><td colSpan={8}><EmptyState title="Erro ao carregar" message={error} action={<Button variant="primary" onClick={() => load(1)}>Tentar novamente</Button>} /></td></tr>
          ) : pedidos.length === 0 ? (
            <tr><td colSpan={8}><EmptyState title="Nenhum pedido" message="Nenhum pedido de compra encontrado." /></td></tr>
          ) : pedidos.map((p) => (
            <tr
              key={p.id}
              style={styles.trHover}
              onClick={() => abrirDetalhe(p.id)}
              onMouseEnter={(e) => e.currentTarget.style.background = "var(--hover, rgba(148,163,184,.08))"}
              onMouseLeave={(e) => e.currentTarget.style.background = ""}
            >
              <td><strong>{p.numero || p.id}</strong></td>
              <td>{p.fornecedor_nome || "—"}</td>
              <td>{formatDate(p.data_pedido)}</td>
              <td>{formatDate(p.data_previsao)}</td>
              <td><StatusPill status={situacaoBadge(p.situacao).label} /></td>
              <td data-numeric>{formatBRL(p.total_produtos)}</td>
              <td data-numeric style={{ fontWeight: 700 }}>{formatBRL(p.total_pedido)}</td>
              <td style={{ color: "var(--muted)", fontSize: 12 }}>{p.forma_pagamento || "—"}</td>
            </tr>
          ))}
        </tbody>
      </Table>

      {numPaginas > 1 ? (
        <div style={styles.pagination}>
          <span style={{ color: "var(--muted)", fontSize: 13 }}>Página {pagina} de {numPaginas}</span>
          <Button variant="secondary" size="sm" disabled={pagina <= 1} onClick={() => load(pagina - 1)}>‹ Anterior</Button>
          <Button variant="secondary" size="sm" disabled={pagina >= numPaginas} onClick={() => load(pagina + 1)}>Próxima ›</Button>
        </div>
      ) : null}

      {detalhe !== null ? (
        <ModalDetalhePedido
          pedido={detalhe}
          loading={detalheLoading}
          error={detalheError}
          onClose={() => { setDetalhe(null); setDetalheError(""); }}
        />
      ) : null}
    </div>
  );
}

function ModalDetalhePedido({ pedido, loading, error, onClose }) {
  return (
    <div style={styles.modal} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={styles.modalBox}>
        <div style={styles.modalHeader}>
          <strong style={{ fontSize: 16 }}>
            Pedido de Compra {pedido?.numero ? `#${pedido.numero}` : ""}
          </strong>
          <Button variant="ghost" size="sm" onClick={onClose}>✕</Button>
        </div>
        <div style={styles.modalBody}>
          {loading ? (
            <div style={{ textAlign: "center", padding: 32 }}><Spinner label="Carregando" /></div>
          ) : error ? (
            <EmptyState title="Erro ao carregar detalhe" message={error} />
          ) : (
            <>
              <div style={styles.grid3}>
                <DetailItem label="Número" value={pedido.numero} />
                <DetailItem label="Situação" value={pedido?.situacao ? <StatusPill status={situacaoBadge(pedido.situacao).label} /> : pedido.situacao} />
                <DetailItem label="Frete" value={pedido.forma_frete} />
                <DetailItem label="Data do Pedido" value={formatDate(pedido.data_pedido)} />
                <DetailItem label="Previsão de Entrega" value={formatDate(pedido.data_previsao)} />
                <DetailItem label="Data de Chegada" value={formatDate(pedido.data_chegada) !== "—" ? formatDate(pedido.data_chegada) : null} />
              </div>

              <div style={styles.sectionTitle}>Fornecedor</div>
              <div style={styles.grid3}>
                <DetailItem label="Nome" value={pedido.fornecedor_nome} />
                <DetailItem label="CNPJ" value={pedido.fornecedor_cnpj} />
                <DetailItem label="Forma de Pagamento" value={pedido.forma_pagamento} />
              </div>

              <div style={styles.sectionTitle}>Valores</div>
              <div style={styles.grid3}>
                <DetailItem label="Total Produtos" value={formatBRL(pedido.total_produtos)} />
                <DetailItem label="Desconto" value={formatBRL(pedido.desconto)} />
                <DetailItem label="Frete (R$)" value={formatBRL(pedido.frete)} />
                <DetailItem label="Total do Pedido" value={<strong>{formatBRL(pedido.total_pedido)}</strong>} />
              </div>

              {pedido.obs ? (
                <>
                  <div style={styles.sectionTitle}>Observações</div>
                  <div style={{ fontSize: 13, color: "var(--muted)", whiteSpace: "pre-wrap" }}>{pedido.obs}</div>
                </>
              ) : null}

              {Array.isArray(pedido.itens) && pedido.itens.length > 0 ? (
                <>
                  <div style={styles.sectionTitle}>Itens ({pedido.itens.length})</div>
                  <Table>
                    <thead>
                      <tr>
                        <th>SKU</th>
                        <th>Descrição</th>
                        <th>Un.</th>
                        <th data-numeric>Qtd.</th>
                        <th data-numeric>Valor Un.</th>
                        <th data-numeric>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pedido.itens.map((item, idx) => (
                        <tr key={item.id || idx}>
                          <td><code style={{ fontSize: 12 }}>{item.codigo || "—"}</code></td>
                          <td>{item.descricao || "—"}</td>
                          <td>{item.unidade || "—"}</td>
                          <td data-numeric>{formatQtd(item.quantidade)}</td>
                          <td data-numeric>{formatBRL(item.valor_unitario)}</td>
                          <td data-numeric style={{ fontWeight: 700 }}>{formatBRL(item.valor_total)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Aba: Atualizações de Estoque ──────────────────────────────────────────────
function AtualizacoesEstoque({ company }) {
  const [filters, setFilters] = useState({ pesquisa: "", data_inicial: "", data_final: "", marketplace: "" });
  const [pagina, setPagina] = useState(1);
  const [numPaginas, setNumPaginas] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [atualizacoes, setAtualizacoes] = useState([]);

  const load = useCallback(async (pg = 1) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ company, pagina: pg, ...filters });
      const data = await api.get(`/admin/estoque/atualizacoes?${params}`);
      setAtualizacoes(data.atualizacoes || []);
      setNumPaginas(data.numero_paginas || 1);
      setPagina(data.pagina || pg);
    } catch (e) {
      setError(e?.message || "Erro ao carregar atualizações de estoque.");
      setAtualizacoes([]);
    } finally {
      setLoading(false);
    }
  }, [company, filters]);

  useEffect(() => {
    setPagina(1);
    load(1);
  }, [company, filters, load]);

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div style={styles.page}>
      <Toolbar>
        <Field label="Canal">
          <select value={filters.marketplace} onChange={(e) => setFilter("marketplace", e.target.value)} style={{ minWidth: 180 }}>
            {MARKETPLACE_OPTIONS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </Field>
        <Field label="Data inicial">
          <input type="date" value={filters.data_inicial} onChange={(e) => setFilter("data_inicial", e.target.value)} style={{ minWidth: 150 }} />
        </Field>
        <Field label="Data final">
          <input type="date" value={filters.data_final} onChange={(e) => setFilter("data_final", e.target.value)} style={{ minWidth: 150 }} />
        </Field>
        <Field label="Produto (SKU/nome)">
          <input type="text" placeholder="Buscar produto…" value={filters.pesquisa} onChange={(e) => setFilter("pesquisa", e.target.value)} style={{ minWidth: 200 }} />
        </Field>
        <Button variant="primary" loading={loading} onClick={() => load(1)}>
          Buscar
        </Button>
      </Toolbar>

      <Table>
        <thead>
          <tr>
            <th>Data / Hora</th>
            <th>SKU</th>
            <th>Produto</th>
            <th>Tipo</th>
            <th data-numeric>Qtd.</th>
            <th data-numeric>Saldo Ant.</th>
            <th data-numeric>Saldo Atual</th>
            <th data-numeric>Custo</th>
            <th>Origem</th>
            <th>Usuário</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr><td colSpan={10} style={{ textAlign: "center", padding: 24 }}><Spinner label="Carregando" /></td></tr>
          ) : error ? (
            <tr><td colSpan={10}><EmptyState title="Erro ao carregar" message={error} action={<Button variant="primary" onClick={() => load(1)}>Tentar novamente</Button>} /></td></tr>
          ) : atualizacoes.length === 0 ? (
            <tr><td colSpan={10}><EmptyState title="Nenhuma atualização" message="Nenhuma atualização de estoque encontrada." /></td></tr>
          ) : atualizacoes.map((a, idx) => (
            <tr key={a.id || idx}>
              <td style={{ whiteSpace: "nowrap", fontSize: 12 }}>
                {formatDate(a.data)}{a.hora ? ` ${a.hora.slice(0, 5)}` : ""}
              </td>
              <td><code style={{ fontSize: 12 }}>{a.codigo || "—"}</code></td>
              <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.nome || "—"}</td>
              <td><Badge {...tipoBadge(a.tipo)} /></td>
              <td data-numeric style={{ fontWeight: 700 }}>{formatQtd(a.quantidade)}</td>
              <td data-numeric style={{ color: "var(--muted)" }}>{formatQtd(a.saldo_anterior)}</td>
              <td data-numeric>{formatQtd(a.saldo_atual)}</td>
              <td data-numeric>{formatBRL(a.preco_custo)}</td>
              <td style={{ fontSize: 12, color: "var(--muted)" }}>{a.tipo_origem || a.id_origem || "—"}</td>
              <td style={{ fontSize: 12, color: "var(--muted)" }}>{a.usuario || "—"}</td>
            </tr>
          ))}
        </tbody>
      </Table>

      {numPaginas > 1 ? (
        <div style={styles.pagination}>
          <span style={{ color: "var(--muted)", fontSize: 13 }}>Página {pagina} de {numPaginas}</span>
          <Button variant="secondary" size="sm" disabled={pagina <= 1} onClick={() => load(pagina - 1)}>‹ Anterior</Button>
          <Button variant="secondary" size="sm" disabled={pagina >= numPaginas} onClick={() => load(pagina + 1)}>Próxima ›</Button>
        </div>
      ) : null}
    </div>
  );
}

// ── Componente principal ──────────────────────────────────────────────────────
export default function Compras() {
  const [tab, setTab] = useState("pedidos");
  const [company, setCompany] = useState(() => {
    try {
      return localStorage.getItem("trml_current_company") || "parton";
    } catch {
      return "parton";
    }
  });

  function companyLabel(key) {
    return COMPANIES.find((c) => c.key === key)?.label || key;
  }

  return (
    <div className="pageShell">
      <div style={styles.page}>
        <PageHeader
          title="Compras"
          actions={
            <Field label="Empresa">
              <select
                style={{ fontWeight: 900, minWidth: 180 }}
                value={company}
                onChange={(e) => setCompany(e.target.value)}
              >
                {COMPANIES.map((c) => (
                  <option key={c.key} value={c.key}>{c.label}</option>
                ))}
              </select>
            </Field>
          }
        />
        <div style={styles.muted}>Pedidos de compra e movimentações de estoque via Tiny ERP</div>

        <div style={styles.tabs}>
          <button
            style={{ ...styles.tab, ...(tab === "pedidos" ? styles.tabActive : {}) }}
            onClick={() => setTab("pedidos")}
          >
            Pedidos de Compra
          </button>
          <button
            style={{ ...styles.tab, ...(tab === "estoque" ? styles.tabActive : {}) }}
            onClick={() => setTab("estoque")}
          >
            Atualizações de Estoque
          </button>
        </div>

        <Card padding="sm">
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            Empresa ativa: <strong>{companyLabel(company)}</strong> · Dados em tempo real do Tiny ERP · Somente leitura
          </div>
        </Card>

        {tab === "pedidos" ? (
          <PedidosCompra company={company} />
        ) : (
          <AtualizacoesEstoque company={company} />
        )}
      </div>
    </div>
  );
}
