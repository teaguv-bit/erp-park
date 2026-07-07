import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { withGlobalLoading } from "../utils/globalLoading";
import { PageHeader, Toolbar, Card, Table, Button, Field, EmptyState, Skeleton } from "../ui";

const COMPANIES = [
  { key: "parton", label: "Suprimentos" },
  { key: "park", label: "Informática" },
];

const PAGE_SIZE = 50;

// Diagnóstico avançado de SKUs (duplicidades/conflitos e sonda Tiny) fica oculto da
// tela operacional para não confundir a operação. O modal e os endpoints permanecem
// intactos; basta colocar true para reexibir o botão (acesso técnico futuro).
const SHOW_SKU_DIAGNOSTIC = false;

const EMPTY_PRODUCT_FORM = {
  nome: "",
  sku: "",
  preco_venda: "",
  preco_custo: "",
  gtin: "",
  ncm: "",
  unidade: "",
  marca: "",
  observacoes: "",
  permitir_inclusao_vendas: true,
};

function companyLabel(company) {
  return COMPANIES.find((item) => item.key === company)?.label || company;
}

function formatBRL(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function formatStock(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  // Inteiro mostra sem casas; valor decimal mantém até 3 casas.
  return Number.isInteger(n)
    ? n.toLocaleString("pt-BR")
    : n.toLocaleString("pt-BR", { maximumFractionDigits: 3 });
}

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const SYNC_STATUS_LABEL = {
  pending: "Pendente",
  synced: "Sincronizado",
  error: "Erro",
  local: "Local",
};

function syncStatusBadge(status) {
  const key = String(status || "").toLowerCase();
  const label = SYNC_STATUS_LABEL[key] || (status ? String(status) : "—");
  const palette = {
    pending: { bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
    synced: { bg: "#f0fdf4", color: "#166534", border: "#bbf7d0" },
    error: { bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
    local: { bg: "rgba(148,163,184,.1)", color: "var(--muted)", border: "var(--border)" },
  };
  const tone = palette[key] || palette.local;
  return { label, tone };
}

const styles = {
  page: { display: "grid", gap: 16 },
  header: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" },
  title: { fontSize: 28, fontWeight: 950, letterSpacing: 0 },
  muted: { color: "var(--muted)", fontSize: 13 },
  toolbar: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-end", flexWrap: "wrap" },
  filters: { display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" },
  fieldLabel: { display: "grid", gap: 4, fontSize: 12, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".03em" },
  button: { border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 12px", fontWeight: 900, cursor: "pointer" },
  primary: { background: "#1d4ed8", color: "#fff", borderColor: "#1d4ed8" },
  card: { border: "1px solid var(--border)", background: "var(--panel, #fff)", padding: 14 },
  input: { width: "100%", border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 10px", boxSizing: "border-box" },
  select: { border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 10px", fontWeight: 800 },
  tableWrap: { border: "1px solid var(--border)", background: "var(--panel, #fff)", overflow: "auto" },
  table: { width: "100%", borderCollapse: "collapse", minWidth: 920 },
  th: { textAlign: "left", padding: "10px 12px", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: 12, textTransform: "uppercase", whiteSpace: "nowrap" },
  td: { padding: "10px 12px", borderBottom: "1px solid var(--border)", verticalAlign: "middle" },
  badge: { display: "inline-flex", padding: "4px 8px", border: "1px solid var(--border)", fontSize: 12, fontWeight: 900, borderRadius: 6 },
  empty: { padding: "32px 12px", textAlign: "center", color: "var(--muted)", fontWeight: 700 },
  errorBox: { border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b", padding: "10px 12px", borderRadius: 8, fontSize: 13, fontWeight: 700 },
  modalOverlay: { position: "fixed", inset: 0, background: "rgba(15,23,42,.45)", zIndex: 70, display: "grid", placeItems: "center", padding: 18 },
  modal: { width: "min(720px, 96vw)", maxHeight: "92vh", overflow: "auto", border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: 18 },
  modalHeader: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 14 },
  formGrid: { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 },
  fullRow: { gridColumn: "1 / -1" },
  checkboxRow: { display: "flex", gap: 8, alignItems: "center", fontWeight: 800, fontSize: 14 },
  modalFooter: { display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 },
  headerActions: { display: "flex", gap: 8, flexWrap: "wrap" },
  notice: { border: "1px solid #bfdbfe", background: "#eff6ff", color: "#1e3a8a", padding: "10px 12px", borderRadius: 8, fontSize: 13, fontWeight: 700 },
  statsGrid: { display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 },
  statCard: { border: "1px solid var(--border)", background: "rgba(248,250,252,.6)", padding: 10, borderRadius: 8 },
  statLabel: { color: "var(--muted)", fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: ".03em" },
  statValue: { fontSize: 20, fontWeight: 950, lineHeight: 1.1 },
  sectionTitle: { fontSize: 13, fontWeight: 900, marginTop: 14, marginBottom: 6 },
  listBox: { border: "1px solid var(--border)", borderRadius: 8, maxHeight: 220, overflow: "auto" },
  listRow: { padding: "7px 10px", borderBottom: "1px solid var(--border)", fontSize: 12.5, display: "flex", gap: 8, justifyContent: "space-between", alignItems: "center" },
};

const IMPORT_FIELD_OPTIONS = [
  { value: "nome", label: "Nome" },
  { value: "sku", label: "SKU / Código" },
  { value: "gtin", label: "GTIN" },
];

const IMPORT_SITUACAO_OPTIONS = [
  { value: "A", label: "Ativos" },
  { value: "I", label: "Inativos" },
  { value: "E", label: "Excluídos" },
];

const ACTION_LABEL = {
  create: { label: "Criar", color: "#166534" },
  update: { label: "Atualizar", color: "#1d4ed8" },
  conflict: { label: "Conflito", color: "#991b1b" },
};

const CONFLICT_DECISION_OPTIONS = [
  { value: "review_later", label: "Revisar depois" },
  { value: "needs_tiny_sku_fix", label: "Precisa corrigir SKU no Tiny" },
  { value: "ignore_duplicate_old_tiny", label: "Ignorar duplicado antigo do Tiny" },
  { value: "import_as_separate_local_later", label: "Importar futuramente como local separado" },
];

function conflictDecisionKey(conflict) {
  return [
    conflict?.sku || "",
    conflict?.local_product_id || "",
    conflict?.local_tiny_product_id || "",
    conflict?.conflict_tiny_product_id || conflict?.tiny_product_id || "",
  ].join("::");
}

const EMPTY_IMPORT_FORM = {
  q: "",
  field: "nome",
  situacao: "A",
  limit: 20,
  offset_start: 0,
  max_pages: 1,
  sleep_ms: 1500,
  import_details: true,
};

const STOPPED_REASON_LABEL = {
  max_pages: "Limite de páginas atingido",
  empty_page: "Página vazia (fim da base)",
  short_page: "Página incompleta (fim da base)",
  total_reached: "Total da base alcançado",
  tiny_error: "Erro do Tiny (interrompido)",
};

const EMPTY_REFRESH_FORM = {
  limit: 5,
  after_id: "",
  sleep_ms: 3000,
  only_missing: true,
  retry_429: true,
  retry_after_ms: 5000,
  max_retries: 1,
};

// ---- Controle de estoque local (Fase 1) ----
const EMPTY_STOCK_FORM = {
  movement_type: "manual_entry",
  quantity: "",
  new_stock_physical: "",
  reason: "",
  notes: "",
};

const STOCK_MOVEMENT_OPTIONS = [
  { value: "manual_entry", label: "Entrada manual" },
  { value: "manual_exit", label: "Saída manual" },
  { value: "manual_adjustment", label: "Ajuste manual" },
  { value: "reserve", label: "Reservar" },
  { value: "release_reserve", label: "Liberar reserva" },
  { value: "set_initial", label: "Definir estoque inicial" },
];

const STOCK_MOVEMENT_LABEL = Object.fromEntries(STOCK_MOVEMENT_OPTIONS.map((o) => [o.value, o.label]));

// Operação simplificada (usuário não trabalha com reservado por enquanto):
// o select do modal "Controle de estoque" só oferece entrada/saída/ajuste/inicial.
// reserve/release_reserve continuam no backend e no histórico/relatório (compatibilidade).
const STOCK_MOVEMENT_OPTIONS_SIMPLE = STOCK_MOVEMENT_OPTIONS.filter(
  (o) => o.value !== "reserve" && o.value !== "release_reserve"
);

// Tipos que usam "Novo estoque físico" em vez de "Quantidade".
const STOCK_TARGET_TYPES = new Set(["manual_adjustment", "set_initial"]);

// ---- Relatório/auditoria de movimentações (Fase 3, somente leitura) ----
const MOV_REPORT_PAGE_SIZE = 50;
const EMPTY_MOV_FILTERS = {
  q: "",
  movement_type: "",
  date_from: "",
  date_to: "",
  include_reversed: true,
  only_reversed: false,
  only_reversals: false,
};

// ---- Posição atual de estoque local (somente leitura) ----
const STOCK_POS_PAGE_SIZE = 50;
const EMPTY_STOCK_POS_FILTERS = {
  q: "",
  stock_status: "all",
  min_stock: 1,
};

const STOCK_POS_STATUS_OPTIONS = [
  { value: "all", label: "Todos" },
  { value: "positive", label: "Com estoque" },
  { value: "zero", label: "Zerados" },
  { value: "low", label: "Baixo estoque" },
  { value: "negative", label: "Negativos" },
];

const STOCK_POS_STATUS_BADGE = {
  positive: { label: "Com estoque", bg: "rgba(34,197,94,.10)", color: "#166534", border: "#bbf7d0" },
  zero: { label: "Zerado", bg: "rgba(148,163,184,.12)", color: "var(--muted)", border: "var(--border)" },
  low: { label: "Baixo", bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  negative: { label: "Negativo", bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
};

// ---- Importação/conferência de ajustes de estoque local em lote ----
const STOCK_BULK_MODE_OPTIONS = [
  { value: "manual_entry", label: "Entrada em lote" },
  { value: "manual_exit", label: "Saída em lote" },
  { value: "manual_adjustment", label: "Ajustar estoque final" },
];

const STOCK_BULK_STATUS_BADGE = {
  ok: { label: "OK", bg: "rgba(34,197,94,.10)", color: "#166534", border: "#bbf7d0" },
  not_found: { label: "Não encontrado", bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
  duplicate_sku: { label: "Duplicado", bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  error: { label: "Erro", bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
};

// Parser simples para "sku;qtd" (aceita ; tab ou , como separador; vírgula decimal BR).
// Ignora linhas vazias e cabeçalho (sku/qtd/quantidade/código). Não usa parser pesado.
function parseStockBulkText(text) {
  const lines = String(text || "").split(/\r?\n/);
  const rows = [];
  let lineNo = 0;
  for (const rawLine of lines) {
    const trimmed = String(rawLine || "").trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/[;\t,]/).map((p) => p.trim());
    const skuPart = parts[0] || "";
    const qtyPart = parts.length > 1 ? parts[parts.length - 1] : "";
    // Quantidade: vírgula decimal BR -> ponto (remove separador de milhar quando há vírgula).
    let qtyStr = qtyPart;
    if (qtyStr.includes(",")) qtyStr = qtyStr.replace(/\./g, "").replace(",", ".");
    const qtyNum = qtyStr === "" ? null : Number(qtyStr);
    const quantity = Number.isFinite(qtyNum) ? qtyNum : null;
    // Detecta/ignora cabeçalho (só na primeira linha de dados, quando a qtd não é número).
    if (rows.length === 0 && quantity === null && /sku|qtd|quant|c[oó]d/i.test(trimmed)) {
      continue;
    }
    lineNo += 1;
    rows.push({ line: lineNo, sku: skuPart, quantity, raw: trimmed });
  }
  return rows;
}

const EMPTY_STOCK_SYNC_FORM = {
  limit: 5,
  sleep_ms: 1000,
  after_id: "",
  force: false,
  only_with_tiny_product_id: true,
  max_errors: 10,
  update_payload: true,
};

const REFRESH_STOPPED_REASON_LABEL = {
  limit_reached: "Limite do lote atingido",
  short_batch: "Lote incompleto (fim da seleção)",
  empty_selection: "Nenhum produto pendente",
  auth_error: "Erro de autenticação Tiny (interrompido)",
};

const REFRESH_ACTION_LABEL = {
  would_update: { label: "Atualizar", color: "#1d4ed8" },
  updated: { label: "Atualizado", color: "#166534" },
  not_found: { label: "Não encontrado", color: "#92400e" },
  error: { label: "Erro", color: "#991b1b" },
};

export default function Products() {
  const [company, setCompany] = useState(() => api.getCurrentCompany?.() || "parton");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState("");

  const [q, setQ] = useState("");
  const [appliedQ, setAppliedQ] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_PRODUCT_FORM });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const [importOpen, setImportOpen] = useState(false);
  const [importForm, setImportForm] = useState({ ...EMPTY_IMPORT_FORM });
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState(null);
  const [importPhase, setImportPhase] = useState("idle"); // idle | preview | done

  const [refreshOpen, setRefreshOpen] = useState(false);
  const [refreshForm, setRefreshForm] = useState({ ...EMPTY_REFRESH_FORM });
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const [refreshResult, setRefreshResult] = useState(null);
  const [refreshPhase, setRefreshPhase] = useState("idle"); // idle | preview | done

  const [stockOpen, setStockOpen] = useState(false);
  const [stockForm, setStockForm] = useState({ ...EMPTY_STOCK_SYNC_FORM });
  const [stockStatus, setStockStatus] = useState(null);
  const [stockBusy, setStockBusy] = useState(false);
  const [stockError, setStockError] = useState("");
  const [stockResult, setStockResult] = useState(null);
  const [stockPhase, setStockPhase] = useState("idle"); // idle | preview | done

  const [diagOpen, setDiagOpen] = useState(false);
  const [diagBusy, setDiagBusy] = useState(false);
  const [diagError, setDiagError] = useState("");
  const [diagResult, setDiagResult] = useState(null);
  const [diagProbe, setDiagProbe] = useState(false); // sondar Tiny (somente leitura)

  // Controle de estoque local (Fase 1) — distinto do modal "Estoque Tiny" (stock*).
  const [stockCtrlOpen, setStockCtrlOpen] = useState(false);
  const [stockCtrlProduct, setStockCtrlProduct] = useState(null); // linha clicada (resumo)
  const [stockCtrlData, setStockCtrlData] = useState(null); // resposta do GET .../stock
  const [stockCtrlLoading, setStockCtrlLoading] = useState(false);
  const [stockCtrlBusy, setStockCtrlBusy] = useState(false);
  const [stockCtrlError, setStockCtrlError] = useState("");
  const [stockCtrlMsg, setStockCtrlMsg] = useState("");
  const [stockCtrlForm, setStockCtrlForm] = useState({ ...EMPTY_STOCK_FORM });
  // Estorno auditável (Fase 2): id do movimento em estorno + motivo + estado.
  const [reverseTargetId, setReverseTargetId] = useState(null);
  const [reverseReason, setReverseReason] = useState("");
  const [reverseBusy, setReverseBusy] = useState(false);
  const [reverseError, setReverseError] = useState("");
  // Relatório/auditoria de movimentações (Fase 3) — somente leitura.
  const [movReportOpen, setMovReportOpen] = useState(false);
  const [movReportData, setMovReportData] = useState(null);
  const [movReportLoading, setMovReportLoading] = useState(false);
  const [movReportError, setMovReportError] = useState("");
  const [movReportOffset, setMovReportOffset] = useState(0);
  const [movFilters, setMovFilters] = useState({ ...EMPTY_MOV_FILTERS });
  // Posição atual de estoque local — somente leitura.
  const [stockPosOpen, setStockPosOpen] = useState(false);
  const [stockPosData, setStockPosData] = useState(null);
  const [stockPosLoading, setStockPosLoading] = useState(false);
  const [stockPosError, setStockPosError] = useState("");
  const [stockPosOffset, setStockPosOffset] = useState(0);
  const [stockPosFilters, setStockPosFilters] = useState({ ...EMPTY_STOCK_POS_FILTERS });
  // Importação/conferência de ajustes de estoque em lote.
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkMode, setBulkMode] = useState("manual_entry");
  const [bulkText, setBulkText] = useState("");
  const [bulkReason, setBulkReason] = useState("");
  const [bulkNotes, setBulkNotes] = useState("");
  const [bulkOrigin, setBulkOrigin] = useState("text");
  const [bulkRows, setBulkRows] = useState([]); // editável: {line, sku, quantity, product_id}
  const [bulkPreview, setBulkPreview] = useState(null); // resposta do preview
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkCommitting, setBulkCommitting] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [bulkMsg, setBulkMsg] = useState("");
  // Importar cadastros Tiny para SKUs não encontrados na conferência.
  const [bulkMissingBusy, setBulkMissingBusy] = useState(false);
  const [bulkMissingResult, setBulkMissingResult] = useState(null);
  const [bulkMissingError, setBulkMissingError] = useState("");
  // Marco de controle automático local (config/baseline) — não reserva/baixa nada.
  const [scOpen, setScOpen] = useState(false);
  const [scStatus, setScStatus] = useState(null);
  const [scLoading, setScLoading] = useState(false);
  const [scBusy, setScBusy] = useState(false);
  const [scError, setScError] = useState("");
  const [scMsg, setScMsg] = useState("");
  const [scNotes, setScNotes] = useState("");
  const [decisionDrafts, setDecisionDrafts] = useState({});
  const [decisionSavingKey, setDecisionSavingKey] = useState("");
  const [decisionMessage, setDecisionMessage] = useState("");
  const [decisionError, setDecisionError] = useState("");

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => {
    const onCompanyChange = () => {
      const next = api.getCurrentCompany?.() || "parton";
      setCompany((current) => (current === next ? current : next));
    };
    window.addEventListener("trml-company-changed", onCompanyChange);
    window.addEventListener("trml-company-change", onCompanyChange);
    return () => {
      window.removeEventListener("trml-company-changed", onCompanyChange);
      window.removeEventListener("trml-company-change", onCompanyChange);
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.adminListProducts({ company, q: appliedQ, limit: PAGE_SIZE, offset });
      setItems(Array.isArray(data?.items) ? data.items : []);
      setTotal(Number(data?.total || 0));
    } catch (e) {
      setItems([]);
      setTotal(0);
      setError(e?.message || "Não foi possível carregar os produtos.");
    } finally {
      setLoading(false);
    }
  }, [company, appliedQ, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // Indicadores da base local-first (somente leitura). Recarrega ao trocar de empresa
  // e após cadastrar/importar/completar detalhes (chamado manualmente nesses fluxos).
  const loadStats = useCallback(async () => {
    setStatsError("");
    try {
      const data = await api.adminProductStats({ company });
      setStats(data && data.ok ? data : null);
    } catch (e) {
      setStats(null);
      setStatsError(e?.message || "Não foi possível carregar os indicadores.");
    }
  }, [company]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // Volta para a primeira página ao trocar empresa ou busca aplicada.
  useEffect(() => {
    setOffset(0);
  }, [company, appliedQ]);

  function submitSearch(e) {
    e.preventDefault();
    setAppliedQ(q.trim());
  }

  function openNewProduct() {
    setForm({ ...EMPTY_PRODUCT_FORM });
    setFormError("");
    setFormOpen(true);
  }

  function closeForm() {
    if (saving) return;
    setFormOpen(false);
    setFormError("");
  }

  function setField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function saveProduct(e) {
    e.preventDefault();
    if (saving) return;
    const nome = String(form.nome || "").trim();
    if (!nome) {
      setFormError("Informe o nome do produto.");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      const payload = {
        company,
        nome,
        sku: String(form.sku || "").trim() || undefined,
        preco_venda: form.preco_venda === "" ? undefined : form.preco_venda,
        preco_custo: form.preco_custo === "" ? undefined : form.preco_custo,
        gtin: String(form.gtin || "").trim() || undefined,
        ncm: String(form.ncm || "").trim() || undefined,
        unidade: String(form.unidade || "").trim() || undefined,
        marca: String(form.marca || "").trim() || undefined,
        observacoes: String(form.observacoes || "").trim() || undefined,
        permitir_inclusao_vendas: !!form.permitir_inclusao_vendas,
      };
      await withGlobalLoading("Salvando produto...", () => api.adminCreateProduct(payload));
      setFormOpen(false);
      setForm({ ...EMPTY_PRODUCT_FORM });
      // Recarrega a lista (volta para o início para o item recém-criado aparecer).
      if (offset !== 0) setOffset(0);
      else await load();
      loadStats();
    } catch (e2) {
      if (e2?.status === 409) {
        setFormError(e2?.message || "SKU já cadastrado para esta empresa.");
      } else {
        setFormError(e2?.message || "Não foi possível salvar o produto.");
      }
    } finally {
      setSaving(false);
    }
  }

  function openImport() {
    setImportForm({ ...EMPTY_IMPORT_FORM });
    setImportError("");
    setImportResult(null);
    setImportPhase("idle");
    setImportOpen(true);
  }

  function closeImport() {
    if (importBusy) return;
    setImportOpen(false);
  }

  // Alterar qualquer parâmetro invalida o dry run anterior: obriga simular de novo
  // antes de confirmar a importação real (evita importar algo diferente do resumo).
  function setImportField(key, value) {
    setImportForm((cur) => ({ ...cur, [key]: value }));
    setImportResult(null);
    setImportPhase("idle");
  }

  // Preenche offset_start com o próximo offset retornado e invalida a prévia:
  // obriga nova simulação antes de confirmar a importação real do novo lote.
  function continueFromNextOffset() {
    const next = Number(importSummary?.next_offset);
    if (!Number.isFinite(next)) return;
    setImportForm((cur) => ({ ...cur, offset_start: next }));
    setImportResult(null);
    setImportPhase("idle");
  }

  async function runImport(dryRun) {
    if (importBusy) return;
    setImportBusy(true);
    setImportError("");
    const limitNum = Math.min(100, Math.max(1, Number(importForm.limit) || 20));
    const offsetStartNum = Math.max(0, Number(importForm.offset_start) || 0);
    const maxPagesNum = Math.min(100, Math.max(1, Number(importForm.max_pages) || 1));
    const sleepMsNum = Math.min(5000, Math.max(0, Number(importForm.sleep_ms) || 0));
    try {
      const data = await withGlobalLoading(
        dryRun ? "Simulando importação do Tiny..." : "Importando do Tiny...",
        () =>
          api.adminImportTinyProductsAll({
            company,
            q: String(importForm.q || "").trim(),
            field: importForm.field,
            situacao: importForm.situacao,
            limit: limitNum,
            offset_start: offsetStartNum,
            max_pages: maxPagesNum,
            dry_run: dryRun,
            import_details: !!importForm.import_details,
            sleep_ms: sleepMsNum,
          })
      );
      setImportResult(data);
      setImportPhase(dryRun ? "preview" : "done");
      if (!dryRun) {
        // Recarrega a lista após importação real.
        if (offset !== 0) setOffset(0);
        else await load();
        loadStats();
      }
    } catch (e) {
      setImportError(e?.message || "Não foi possível importar do Tiny.");
    } finally {
      setImportBusy(false);
    }
  }

  // O endpoint paginado retorna detalhes por empresa em `companies[]`.
  // Como a importação aqui é sempre de uma empresa, usamos o primeiro resumo
  // para next_offset/expected_total/stopped_reason e os agregados do topo para contagens.
  const importSummary = useMemo(() => {
    if (!importResult) return null;
    const co = Array.isArray(importResult.companies) ? importResult.companies[0] : null;
    return {
      pages_processed: importResult.pages_processed ?? co?.pages_processed ?? 0,
      fetched_count: importResult.fetched_count ?? co?.fetched_count ?? 0,
      created_count: importResult.created_count ?? co?.created_count ?? 0,
      updated_count: importResult.updated_count ?? co?.updated_count ?? 0,
      skipped_count: importResult.skipped_count ?? co?.skipped_count ?? 0,
      conflicts: importResult.conflicts || co?.conflicts || [],
      errors: importResult.errors || co?.errors || [],
      sample: co?.sample || [],
      offset_start: co?.offset_start ?? importResult?.query?.offset_start ?? 0,
      next_offset: co?.next_offset,
      expected_total: co?.expected_total,
      stopped_reason: co?.stopped_reason,
    };
  }, [importResult]);

  function openRefresh() {
    setRefreshForm({ ...EMPTY_REFRESH_FORM });
    setRefreshError("");
    setRefreshResult(null);
    setRefreshPhase("idle");
    setRefreshOpen(true);
  }

  function closeRefresh() {
    if (refreshBusy) return;
    setRefreshOpen(false);
  }

  // Alterar qualquer parâmetro invalida o dry run anterior: obriga simular de novo
  // antes de confirmar a atualização real.
  function setRefreshField(key, value) {
    setRefreshForm((cur) => ({ ...cur, [key]: value }));
    setRefreshResult(null);
    setRefreshPhase("idle");
  }

  // Preenche after_id com o próximo ID retornado e invalida a prévia.
  function continueFromNextAfterId() {
    const next = Number(refreshSummary?.next_after_id);
    if (!Number.isFinite(next)) return;
    setRefreshForm((cur) => ({ ...cur, after_id: next }));
    setRefreshResult(null);
    setRefreshPhase("idle");
  }

  async function runRefresh(dryRun) {
    if (refreshBusy) return;
    setRefreshBusy(true);
    setRefreshError("");
    const limitNum = Math.min(30, Math.max(1, Number(refreshForm.limit) || 5));
    const afterIdRaw = String(refreshForm.after_id ?? "").trim();
    const afterIdNum = afterIdRaw === "" ? null : Math.max(0, Number(afterIdRaw) || 0);
    const sleepMsNum = Math.min(10000, Math.max(0, Number(refreshForm.sleep_ms) || 0));
    const retryAfterNum = Math.min(60000, Math.max(0, Number(refreshForm.retry_after_ms) || 0));
    const maxRetriesNum = Math.min(3, Math.max(0, Number(refreshForm.max_retries) || 0));
    try {
      const data = await withGlobalLoading(
        dryRun ? "Simulando atualização de detalhes..." : "Atualizando detalhes do Tiny...",
        () =>
          api.adminRefreshTinyProductDetails({
            company,
            limit: limitNum,
            offset: 0,
            after_id: afterIdNum,
            sleep_ms: sleepMsNum,
            dry_run: dryRun,
            only_missing: !!refreshForm.only_missing,
            retry_429: !!refreshForm.retry_429,
            retry_after_ms: retryAfterNum,
            max_retries: maxRetriesNum,
          })
      );
      setRefreshResult(data);
      setRefreshPhase(dryRun ? "preview" : "done");
      if (!dryRun) {
        // Recarrega a lista após atualização real.
        if (offset !== 0) setOffset(0);
        else await load();
        loadStats();
      }
    } catch (e) {
      setRefreshError(e?.message || "Não foi possível completar os detalhes do Tiny.");
    } finally {
      setRefreshBusy(false);
    }
  }

  // Detalhes por empresa em `companies[]`. Como a operação é sempre de uma empresa,
  // usamos o primeiro resumo para next_after_id/stopped_reason e os agregados do topo
  // para as contagens.
  const refreshSummary = useMemo(() => {
    if (!refreshResult) return null;
    const co = Array.isArray(refreshResult.companies) ? refreshResult.companies[0] : null;
    return {
      processed_count: refreshResult.processed_count ?? co?.processed_count ?? 0,
      updated_count: refreshResult.updated_count ?? co?.updated_count ?? 0,
      skipped_count: refreshResult.skipped_count ?? co?.skipped_count ?? 0,
      errors: refreshResult.errors || co?.errors || [],
      sample: refreshResult.sample || co?.sample || [],
      next_after_id: co?.next_after_id,
      stopped_reason: co?.stopped_reason || refreshResult.stopped_reason,
    };
  }, [refreshResult]);

  const refreshHas429 = useMemo(() => {
    if (!refreshSummary) return false;
    return (refreshSummary.errors || []).some((er) => String(er?.error || "").includes("429"));
  }, [refreshSummary]);

  async function loadStockStatus() {
    const data = await api.adminProductStockSyncStatus({ company });
    setStockStatus(data);
    return data;
  }

  async function openStockSync() {
    setStockForm({ ...EMPTY_STOCK_SYNC_FORM });
    setStockError("");
    setStockResult(null);
    setStockPhase("idle");
    setStockOpen(true);
    try {
      await loadStockStatus();
    } catch (e) {
      setStockError(e?.message || "Nao foi possivel carregar o status de estoque.");
    }
  }

  function closeStockSync() {
    if (stockBusy) return;
    setStockOpen(false);
  }

  function setStockField(key, value) {
    setStockForm((cur) => ({ ...cur, [key]: value }));
    setStockResult(null);
    setStockPhase("idle");
  }

  async function runStockSync(dryRun) {
    if (stockBusy) return;
    setStockBusy(true);
    setStockError("");
    const limitNum = Math.min(100, Math.max(1, Number(stockForm.limit) || 5));
    const sleepMsNum = Math.min(5000, Math.max(0, Number(stockForm.sleep_ms) || 0));
    const afterIdRaw = String(stockForm.after_id ?? "").trim();
    const afterIdNum = afterIdRaw === "" ? null : Math.max(0, Number(afterIdRaw) || 0);
    try {
      const data = await withGlobalLoading(
        dryRun ? "Simulando sincronizacao de estoque..." : "Sincronizando estoque Tiny...",
        () => api.adminRunProductStockSync({
          company,
          dry_run: dryRun,
          limit: limitNum,
          sleep_ms: sleepMsNum,
          after_id: afterIdNum,
          force: !!stockForm.force,
          only_with_tiny_product_id: !!stockForm.only_with_tiny_product_id,
          max_errors: Math.min(100, Math.max(1, Number(stockForm.max_errors) || 10)),
          update_payload: !!stockForm.update_payload,
        })
      );
      setStockResult(data);
      setStockPhase(dryRun ? "preview" : "done");
      await loadStockStatus();
      if (!dryRun) {
        if (offset !== 0) setOffset(0);
        else await load();
        loadStats();
      }
    } catch (e) {
      setStockError(e?.message || "Nao foi possivel sincronizar estoque.");
      try {
        await loadStockStatus();
      } catch {
        // Mantem o erro principal da execucao.
      }
    } finally {
      setStockBusy(false);
    }
  }

  const stockSummary = useMemo(() => {
    if (!stockResult) return null;
    const co = Array.isArray(stockResult.companies) ? stockResult.companies[0] : null;
    return {
      processed_count: stockResult.processed_count ?? co?.processed_count ?? 0,
      updated_count: stockResult.updated_count ?? co?.updated_count ?? 0,
      skipped_count: stockResult.skipped_count ?? co?.skipped_count ?? 0,
      errors: stockResult.errors || co?.errors || [],
      samples: stockResult.samples || co?.samples || [],
      next_after_id: stockResult.next_after_id ?? co?.next_after_id,
      stopped_reason: stockResult.stopped_reason ?? co?.stopped_reason,
      can_continue: Boolean(stockResult.can_continue ?? co?.can_continue),
    };
  }, [stockResult]);

  function openDiag() {
    setDiagError("");
    setDiagResult(null);
    setDiagProbe(false);
    setDecisionDrafts({});
    setDecisionMessage("");
    setDecisionError("");
    setDiagOpen(true);
  }

  function closeDiag() {
    if (diagBusy) return;
    setDiagOpen(false);
  }

  // Diagnóstico somente leitura: por padrão usa só a base local; com probe=true
  // sonda o Tiny (listar_produtos paginado, sem detalhes, sem gravar nada).
  async function runDiag(probe) {
    if (diagBusy) return;
    setDiagBusy(true);
    setDiagError("");
    setDecisionMessage("");
    setDecisionError("");
    try {
      const data = await withGlobalLoading(
        probe ? "Diagnosticando SKUs (com sonda Tiny)..." : "Diagnosticando SKUs locais...",
        () => api.adminProductSkuConflicts({ company, include_tiny_probe: !!probe })
      );
      setDiagResult(data);
    } catch (e) {
      setDiagError(e?.message || "Não foi possível executar o diagnóstico de SKUs.");
    } finally {
      setDiagBusy(false);
    }
  }

  // ---- Controle de estoque local (Fase 1) ----
  const loadStockCtrl = useCallback(
    async (productId) => {
      setStockCtrlLoading(true);
      setStockCtrlError("");
      try {
        const data = await api.adminGetProductStock(productId, { company });
        setStockCtrlData(data);
      } catch (e) {
        setStockCtrlData(null);
        setStockCtrlError(e?.message || "Não foi possível carregar o estoque do produto.");
      } finally {
        setStockCtrlLoading(false);
      }
    },
    [company]
  );

  function openStockCtrl(item) {
    setStockCtrlProduct(item);
    setStockCtrlData(null);
    setStockCtrlForm({ ...EMPTY_STOCK_FORM });
    setStockCtrlError("");
    setStockCtrlMsg("");
    setReverseTargetId(null);
    setReverseReason("");
    setReverseError("");
    setStockCtrlOpen(true);
    loadStockCtrl(item.id);
  }

  function closeStockCtrl() {
    if (stockCtrlBusy || reverseBusy) return;
    setStockCtrlOpen(false);
    setStockCtrlProduct(null);
    setStockCtrlData(null);
    setReverseTargetId(null);
    setReverseReason("");
    setReverseError("");
  }

  function setStockCtrlField(key, value) {
    setStockCtrlForm((cur) => ({ ...cur, [key]: value }));
    setStockCtrlMsg("");
  }

  async function submitStockMovement(e) {
    e.preventDefault();
    if (stockCtrlBusy || !stockCtrlProduct) return;
    const type = stockCtrlForm.movement_type;
    const usesTarget = STOCK_TARGET_TYPES.has(type);
    const payload = {
      company,
      movement_type: type,
      reason: String(stockCtrlForm.reason || "").trim() || undefined,
      notes: String(stockCtrlForm.notes || "").trim() || undefined,
    };
    if (usesTarget) {
      if (String(stockCtrlForm.new_stock_physical).trim() === "") {
        setStockCtrlError("Informe o novo estoque físico.");
        return;
      }
      payload.new_stock_physical = Number(stockCtrlForm.new_stock_physical);
    } else {
      const qty = Number(stockCtrlForm.quantity);
      if (!Number.isFinite(qty) || qty <= 0) {
        setStockCtrlError("Informe uma quantidade maior que zero.");
        return;
      }
      payload.quantity = qty;
    }
    setStockCtrlBusy(true);
    setStockCtrlError("");
    setStockCtrlMsg("");
    try {
      await withGlobalLoading("Registrando movimento de estoque...", () =>
        api.adminCreateProductStockMovement(stockCtrlProduct.id, payload)
      );
      setStockCtrlMsg("Movimento registrado com sucesso.");
      // Limpa campos de valor, mantém tipo/motivo para repetição rápida.
      setStockCtrlForm((cur) => ({ ...cur, quantity: "", new_stock_physical: "" }));
      await loadStockCtrl(stockCtrlProduct.id); // recarrega saldos + histórico no modal
      await load(); // recarrega a listagem principal
    } catch (e2) {
      setStockCtrlError(e2?.message || "Não foi possível registrar o movimento.");
    } finally {
      setStockCtrlBusy(false);
    }
  }

  // Abre/fecha o formulário inline de estorno de um movimento específico.
  function openReverse(movementId) {
    setReverseTargetId(movementId);
    setReverseReason("");
    setReverseError("");
    setStockCtrlMsg("");
  }

  function cancelReverse() {
    if (reverseBusy) return;
    setReverseTargetId(null);
    setReverseReason("");
    setReverseError("");
  }

  async function submitReversal(movementId) {
    if (reverseBusy || !stockCtrlProduct) return;
    const reason = String(reverseReason || "").trim();
    if (!reason) {
      setReverseError("Informe o motivo do estorno.");
      return;
    }
    setReverseBusy(true);
    setReverseError("");
    try {
      await withGlobalLoading("Estornando movimento...", () =>
        api.adminReverseProductStockMovement(stockCtrlProduct.id, movementId, { company, reason })
      );
      setReverseTargetId(null);
      setReverseReason("");
      setStockCtrlMsg("Movimento estornado com sucesso. O histórico original foi preservado.");
      await loadStockCtrl(stockCtrlProduct.id); // recarrega saldos + histórico
      await load(); // recarrega a listagem principal
    } catch (e2) {
      setReverseError(e2?.message || "Não foi possível estornar o movimento.");
    } finally {
      setReverseBusy(false);
    }
  }

  // ---- Relatório/auditoria de movimentações (Fase 3) — somente leitura ----
  async function loadMovReport(nextOffset = 0, filters = movFilters) {
    setMovReportLoading(true);
    setMovReportError("");
    try {
      const data = await api.adminListProductStockMovements({
        company,
        q: filters.q,
        movement_type: filters.movement_type,
        date_from: filters.date_from,
        date_to: filters.date_to,
        include_reversed: filters.include_reversed,
        only_reversed: filters.only_reversed,
        only_reversals: filters.only_reversals,
        limit: MOV_REPORT_PAGE_SIZE,
        offset: nextOffset,
      });
      setMovReportData(data);
      setMovReportOffset(nextOffset);
    } catch (e2) {
      setMovReportError(e2?.message || "Não foi possível carregar as movimentações.");
    } finally {
      setMovReportLoading(false);
    }
  }

  function openMovReport() {
    const fresh = { ...EMPTY_MOV_FILTERS };
    setMovFilters(fresh);
    setMovReportData(null);
    setMovReportError("");
    setMovReportOffset(0);
    setMovReportOpen(true);
    loadMovReport(0, fresh);
  }

  function closeMovReport() {
    if (movReportLoading) return;
    setMovReportOpen(false);
  }

  function setMovFilter(key, value) {
    setMovFilters((cur) => ({ ...cur, [key]: value }));
  }

  // ---- Posição atual de estoque local (somente leitura) ----
  async function loadStockPos(nextOffset = 0, filters = stockPosFilters) {
    setStockPosLoading(true);
    setStockPosError("");
    try {
      const minStockRaw = String(filters.min_stock ?? "").trim();
      const minStock = minStockRaw === "" ? 1 : Math.max(0, Number(minStockRaw) || 0);
      const data = await api.adminProductStockPosition({
        company,
        q: filters.q,
        stock_status: filters.stock_status,
        min_stock: minStock,
        limit: STOCK_POS_PAGE_SIZE,
        offset: nextOffset,
      });
      setStockPosData(data);
      setStockPosOffset(nextOffset);
    } catch (e2) {
      setStockPosError(e2?.message || "Não foi possível carregar a posição de estoque.");
    } finally {
      setStockPosLoading(false);
    }
  }

  function openStockPos() {
    const fresh = { ...EMPTY_STOCK_POS_FILTERS };
    setStockPosFilters(fresh);
    setStockPosData(null);
    setStockPosError("");
    setStockPosOffset(0);
    setStockPosOpen(true);
    loadStockPos(0, fresh);
  }

  function closeStockPos() {
    if (stockPosLoading) return;
    setStockPosOpen(false);
  }

  function setStockPosFilter(key, value) {
    setStockPosFilters((cur) => ({ ...cur, [key]: value }));
  }

  // ---- Importação/conferência de ajustes de estoque em lote ----
  function openBulk() {
    setBulkMode("manual_entry");
    setBulkText("");
    setBulkReason("");
    setBulkNotes("");
    setBulkOrigin("text");
    setBulkRows([]);
    setBulkPreview(null);
    setBulkError("");
    setBulkMsg("");
    setBulkOpen(true);
  }

  function closeBulk() {
    if (bulkLoading || bulkCommitting) return;
    setBulkOpen(false);
  }

  function changeBulkMode(value) {
    setBulkMode(value);
    setBulkPreview(null); // projeção depende do modo: força gerar prévia de novo
    setBulkMsg("");
  }

  async function handleBulkFile(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const name = String(file.name || "").toLowerCase();
    if (name.endsWith(".xlsx") || name.endsWith(".xls")) {
      setBulkError("Importação de Excel (.xlsx) não está disponível nesta fase. Use texto colado, .txt ou .csv.");
      e.target.value = "";
      return;
    }
    try {
      const text = await file.text();
      setBulkText(text);
      setBulkOrigin(name.endsWith(".csv") ? "csv" : "text");
      setBulkPreview(null);
      setBulkError("");
      setBulkMsg("");
    } catch {
      setBulkError("Não foi possível ler o arquivo.");
    }
    e.target.value = "";
  }

  async function runBulkPreview(rows) {
    setBulkLoading(true);
    setBulkError("");
    setBulkMsg("");
    setBulkMissingError("");
    try {
      const data = await api.adminPreviewProductStockBulk({
        company,
        mode: bulkMode,
        rows: rows.map((r) => ({
          line: r.line,
          sku: r.sku,
          quantity: r.quantity,
          product_id: r.product_id || undefined,
        })),
      });
      setBulkPreview(data);
    } catch (e2) {
      setBulkError(e2?.message || "Não foi possível gerar a prévia.");
    } finally {
      setBulkLoading(false);
    }
  }

  async function generateBulkPreview() {
    const parsed = parseStockBulkText(bulkText);
    if (!parsed.length) {
      setBulkError("Cole ou selecione um arquivo com linhas no formato sku;qtd.");
      return;
    }
    const editable = parsed.map((r) => ({ line: r.line, sku: r.sku, quantity: r.quantity, product_id: null }));
    setBulkRows(editable);
    await runBulkPreview(editable);
  }

  function setBulkRowField(line, key, value) {
    setBulkRows((cur) => cur.map((r) => (r.line === line ? { ...r, [key]: value } : r)));
  }

  async function revalidateBulk() {
    if (!bulkRows.length) return;
    await runBulkPreview(bulkRows);
  }

  async function commitBulk() {
    if (!bulkPreview || bulkCommitting) return;
    const s = bulkPreview.summary || {};
    const blocked = !s.total_rows || s.error_count > 0 || s.not_found_count > 0 || s.duplicate_count > 0;
    if (blocked) {
      setBulkError("Corrija as linhas pendentes antes de confirmar a importação.");
      return;
    }
    setBulkCommitting(true);
    setBulkError("");
    try {
      const items = (bulkPreview.items || []).map((it) => ({
        line: it.line,
        product_id: it.product_id,
        sku: it.resolved_sku || it.input_sku,
        quantity: it.quantity,
      }));
      const data = await withGlobalLoading("Importando ajustes de estoque...", () =>
        api.adminCommitProductStockBulk({
          company,
          mode: bulkMode,
          reason: bulkReason,
          notes: bulkNotes,
          origin: bulkOrigin,
          items,
        })
      );
      setBulkPreview(null);
      setBulkRows([]);
      setBulkText("");
      setBulkMsg(`Importação concluída. ${data?.processed_count ?? items.length} movimento(s) criado(s). O histórico foi preservado.`);
      await load(); // recarrega a listagem principal
      if (stockPosOpen) {
        await loadStockPos(stockPosOffset, stockPosFilters); // mantém posição de estoque coerente
      }
    } catch (e2) {
      setBulkError(e2?.message || "Não foi possível concluir a importação.");
    } finally {
      setBulkCommitting(false);
    }
  }

  async function importMissingFromTiny() {
    if (bulkMissingBusy || !bulkPreview) return;
    const skus = Array.from(
      new Set(
        (bulkPreview.items || [])
          .filter((it) => it.status === "not_found")
          .map((it) => String(it.input_sku || "").trim())
          .filter(Boolean)
      )
    );
    if (!skus.length) {
      setBulkMissingError("Nenhum SKU não encontrado para buscar no Tiny.");
      return;
    }
    setBulkMissingBusy(true);
    setBulkMissingError("");
    setBulkMissingResult(null);
    try {
      const data = await withGlobalLoading("Buscando/importando cadastros do Tiny...", () =>
        api.adminImportMissingProductSkusFromTiny({ company, skus, import_details: true })
      );
      setBulkMissingResult(data);
      // Se algo foi importado, revalida a prévia e recarrega a listagem principal.
      if ((data?.imported_count || 0) > 0) {
        await load();
        await runBulkPreview(bulkRows);
      }
    } catch (e2) {
      setBulkMissingError(e2?.message || "Não foi possível buscar/importar os SKUs no Tiny.");
    } finally {
      setBulkMissingBusy(false);
    }
  }

  // ---- Marco de controle automático local (config/baseline) ----
  async function loadScStatus() {
    setScLoading(true);
    setScError("");
    try {
      const data = await api.adminStockAutoControlStatus({ company });
      setScStatus(data);
    } catch (e2) {
      setScError(e2?.message || "Não foi possível carregar o status do controle automático.");
    } finally {
      setScLoading(false);
    }
  }

  function openSc() {
    setScStatus(null);
    setScError("");
    setScMsg("");
    setScNotes("");
    setScOpen(true);
    loadScStatus();
  }

  function closeSc() {
    if (scBusy) return;
    setScOpen(false);
  }

  async function activateSc() {
    if (scBusy) return;
    setScBusy(true);
    setScError("");
    setScMsg("");
    try {
      const lastBulk = scStatus?.last_bulk_import;
      const payload = {
        company,
        is_enabled: true,
        // started_at omitido de propósito: o backend usa "agora" (Ativar a partir de agora).
        baseline_reference_id: lastBulk?.reference_id || undefined,
        baseline_source: lastBulk?.reference_id ? "stock_bulk_import" : undefined,
        baseline_notes: scNotes || undefined,
      };
      await withGlobalLoading("Ativando marco do controle automático...", () =>
        api.adminConfigureStockAutoControl(payload)
      );
      setScMsg("Controle automático ativado a partir de agora. Nenhuma reserva ou baixa foi aplicada.");
      await loadScStatus();
    } catch (e2) {
      setScError(e2?.message || "Não foi possível ativar o controle automático.");
    } finally {
      setScBusy(false);
    }
  }

  async function deactivateSc() {
    if (scBusy) return;
    setScBusy(true);
    setScError("");
    setScMsg("");
    try {
      await withGlobalLoading("Desativando controle automático...", () =>
        api.adminConfigureStockAutoControl({ company, is_enabled: false })
      );
      setScMsg("Controle automático desativado. Nenhum saldo ou movimento foi alterado.");
      await loadScStatus();
    } catch (e2) {
      setScError(e2?.message || "Não foi possível desativar o controle automático.");
    } finally {
      setScBusy(false);
    }
  }

  async function saveConflictDecision(conflict) {
    const key = conflictDecisionKey(conflict);
    const existing = conflict?.decision || {};
    const draft = decisionDrafts[key] || {};
    const decision = draft.decision || existing.decision || "review_later";
    const notes = draft.notes ?? existing.notes ?? "";
    setDecisionSavingKey(key);
    setDecisionError("");
    setDecisionMessage("");
    try {
      const payload = {
        company,
        sku: conflict.sku,
        local_product_id: conflict.local_product_id,
        local_tiny_product_id: conflict.local_tiny_product_id,
        conflict_tiny_product_id: conflict.conflict_tiny_product_id || conflict.tiny_product_id,
        conflict_tiny_name: conflict.conflict_tiny_name || conflict.tiny_nome,
        decision,
        notes,
        raw_payload: conflict,
      };
      const saved = await withGlobalLoading(
        "Salvando decisao de conflito...",
        () => api.adminSaveProductConflictDecision(payload)
      );
      const savedItem = saved?.item;
      setDiagResult((current) => {
        if (!current) return current;
        const updated = (current.tiny_vs_local_conflicts || []).map((item) => {
          if (conflictDecisionKey(item) !== key) return item;
          return {
            ...item,
            decision: savedItem,
            decision_status: savedItem?.status,
            decision_value: savedItem?.decision,
          };
        });
        return { ...current, tiny_vs_local_conflicts: updated };
      });
      setDecisionDrafts((current) => ({ ...current, [key]: { decision, notes } }));
      setDecisionMessage(saved?.message || "Decisao registrada localmente.");
    } catch (e) {
      setDecisionError(e?.message || "Nao foi possivel salvar a decisao.");
    } finally {
      setDecisionSavingKey("");
    }
  }

  const rangeLabel = useMemo(() => {
    if (!total) return "0 produtos";
    const start = offset + 1;
    const end = Math.min(offset + items.length, total);
    return `${start}–${end} de ${total}`;
  }, [offset, items.length, total]);

  // Cards e faixa de diagnóstico da base local-first (somente leitura).
  const statsCards = stats
    ? [
        { label: "Total", value: stats.total },
        { label: "Tiny", value: stats.origin_tiny },
        { label: "Locais", value: stats.origin_local },
        { label: "Detalhes completos", value: stats.details_complete },
        { label: "Pendentes de detalhes", value: stats.details_pending },
        { label: "Erros de sync", value: stats.sync_error },
      ]
    : [];
  const statsTotal = Number(stats?.total || 0);
  const statsPending = Number(stats?.details_pending || 0);
  const statsMessage = !stats
    ? ""
    : statsTotal === 0
    ? "Sem produtos nesta empresa"
    : statsPending > 0
    ? `Há produtos pendentes de detalhes (${statsPending.toLocaleString("pt-BR")})`
    : "Detalhes completos";
  const statsBannerStyle = {
    padding: "8px 12px",
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 800,
    border: "1px solid",
    ...(statsTotal === 0
      ? { background: "rgba(148,163,184,.1)", color: "var(--muted)", borderColor: "var(--border)" }
      : statsPending > 0
      ? { background: "#fffbeb", color: "#92400e", borderColor: "#fde68a" }
      : { background: "#f0fdf4", color: "#166534", borderColor: "#bbf7d0" }),
  };

  return (
    <div className="pageShell">
      <div style={styles.page}>
        <PageHeader
          title="Produtos"
          crumb={`Cadastro local de produtos · ${companyLabel(company)}`}
          actions={
            <>
              <Button type="button" variant="secondary" onClick={openImport}>
                Importar do Tiny
              </Button>
              <Button type="button" variant="secondary" onClick={openRefresh}>
                Completar detalhes Tiny
              </Button>
              <Button type="button" variant="secondary" onClick={openStockSync}>
                Estoque Tiny
              </Button>
              <Button type="button" variant="secondary" onClick={openMovReport}>
                Movimentações
              </Button>
              <Button type="button" variant="secondary" onClick={openStockPos}>
                Posição de estoque
              </Button>
              <Button type="button" variant="secondary" onClick={openBulk}>
                Importar ajuste
              </Button>
              <Button type="button" variant="secondary" onClick={openSc}>
                Controle automático
              </Button>
              {SHOW_SKU_DIAGNOSTIC ? (
                <Button type="button" variant="secondary" onClick={openDiag}>
                  Diagnóstico de SKUs
                </Button>
              ) : null}
              <Button type="button" variant="primary" onClick={openNewProduct}>
                + Novo produto
              </Button>
            </>
          }
        />

        <Card padding="sm">
          <Toolbar>
            <form style={styles.filters} onSubmit={submitSearch}>
              <label style={styles.fieldLabel}>
                Buscar
                <input
                  style={{ ...styles.input, width: 280 }}
                  placeholder="Nome, SKU, GTIN ou marca"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
              </label>
              <Button type="submit" variant="secondary">Buscar</Button>
              {appliedQ ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setQ("");
                    setAppliedQ("");
                  }}
                >
                  Limpar
                </Button>
              ) : null}
            </form>
            <Toolbar.Spacer />
            <div style={styles.muted}>{rangeLabel}</div>
          </Toolbar>
        </Card>

        {stats ? (
          <Card>
            <div style={styles.statsGrid}>
              {statsCards.map((s) => (
                <div key={s.label} style={styles.statCard}>
                  <div style={styles.statLabel}>{s.label}</div>
                  <div style={styles.statValue}>{Number(s.value || 0).toLocaleString("pt-BR")}</div>
                </div>
              ))}
            </div>
            <div style={{ ...statsBannerStyle, marginTop: 10 }}>
              {statsMessage}
              {stats.last_tiny_synced_at ? (
                <span style={{ fontWeight: 700 }}>
                  {" · Última atualização Tiny: "}
                  {formatDate(stats.last_tiny_synced_at)}
                </span>
              ) : null}
            </div>
          </Card>
        ) : statsError ? (
          <EmptyState
            title="Indicadores indisponíveis"
            message={statsError}
            action={<Button variant="secondary" onClick={loadStats}>Tentar novamente</Button>}
          />
        ) : null}

        {error ? (
          <EmptyState
            title="Não foi possível carregar os produtos"
            message={error}
            action={<Button variant="secondary" onClick={load}>Tentar novamente</Button>}
          />
        ) : null}

        <Table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>SKU</th>
              <th data-numeric>Preço de venda</th>
              <th data-numeric>Est. físico</th>
              <th data-numeric>Custo médio</th>
              <th>Marca</th>
              <th>Status sync</th>
              <th>Origem</th>
              <th>Criado em</th>
              <th>Ações</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [0, 1, 2, 3, 4].map((r) => (
                <tr key={`sk-${r}`}>
                  <td colSpan={10}>
                    <Skeleton height={16} />
                  </td>
                </tr>
              ))
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={10} style={{ padding: 0 }}>
                  <EmptyState
                    title={appliedQ ? "Nenhum produto encontrado" : "Nenhum produto cadastrado"}
                    message={
                      appliedQ
                        ? "Nenhum produto encontrado para a busca."
                        : "Nenhum produto cadastrado ainda. Use “Novo produto” para começar."
                    }
                    action={
                      appliedQ ? null : (
                        <Button variant="primary" onClick={openNewProduct}>
                          + Novo produto
                        </Button>
                      )
                    }
                  />
                </td>
              </tr>
            ) : (
              items.map((item) => {
                const badge = syncStatusBadge(item.tiny_sync_status);
                return (
                  <tr key={item.id}>
                    <td>
                      <div style={{ fontWeight: 800 }}>{item.nome || "—"}</div>
                    </td>
                    <td>{item.sku || "—"}</td>
                    <td data-numeric>{formatBRL(item.preco_venda)}</td>
                    <td data-numeric>{formatStock(item.estoque_fisico)}</td>
                    <td data-numeric>{formatBRL(item.custo_medio)}</td>
                    <td>{item.marca || "—"}</td>
                    <td>
                      <span
                        style={{
                          ...styles.badge,
                          background: badge.tone.bg,
                          color: badge.tone.color,
                          borderColor: badge.tone.border,
                        }}
                      >
                        {badge.label}
                      </span>
                    </td>
                    <td>{item.origin || "—"}</td>
                    <td>{formatDate(item.created_at)}</td>
                    <td>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => openStockCtrl(item)}
                      >
                        Estoque
                      </Button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </Table>

        {total > PAGE_SIZE ? (
          <div style={{ ...styles.toolbar, justifyContent: "flex-end" }}>
            <div style={styles.muted}>Página {page} de {totalPages}</div>
            <Button
              type="button"
              variant="secondary"
              disabled={offset === 0 || loading}
              onClick={() => setOffset((cur) => Math.max(0, cur - PAGE_SIZE))}
            >
              Anterior
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={offset + PAGE_SIZE >= total || loading}
              onClick={() => setOffset((cur) => cur + PAGE_SIZE)}
            >
              Próxima
            </Button>
          </div>
        ) : null}
      </div>

      {formOpen ? (
        <div style={styles.modalOverlay} onClick={closeForm}>
          <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Novo produto</div>
                <div style={styles.muted}>Cadastro local · {companyLabel(company)}</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeForm} disabled={saving}>
                Fechar
              </Button>
            </div>

            <form onSubmit={saveProduct}>
              <div style={styles.formGrid}>
                <div style={styles.fullRow}>
                  <Field label="Nome *" id="np-nome">
                    <input
                      id="np-nome"
                      value={form.nome}
                      onChange={(e) => setField("nome", e.target.value)}
                      autoFocus
                      required
                    />
                  </Field>
                </div>

                <Field label="SKU / Código" id="np-sku">
                  <input id="np-sku" value={form.sku} onChange={(e) => setField("sku", e.target.value)} />
                </Field>
                <Field label="Marca" id="np-marca">
                  <input id="np-marca" value={form.marca} onChange={(e) => setField("marca", e.target.value)} />
                </Field>

                <Field label="Preço de venda" id="np-preco-venda">
                  <input
                    id="np-preco-venda"
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.preco_venda}
                    onChange={(e) => setField("preco_venda", e.target.value)}
                  />
                </Field>
                <Field label="Preço de custo" id="np-preco-custo">
                  <input
                    id="np-preco-custo"
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.preco_custo}
                    onChange={(e) => setField("preco_custo", e.target.value)}
                  />
                </Field>

                <Field label="GTIN" id="np-gtin">
                  <input id="np-gtin" value={form.gtin} onChange={(e) => setField("gtin", e.target.value)} />
                </Field>
                <Field label="NCM" id="np-ncm">
                  <input id="np-ncm" value={form.ncm} onChange={(e) => setField("ncm", e.target.value)} />
                </Field>

                <Field label="Unidade" id="np-unidade">
                  <input
                    id="np-unidade"
                    placeholder="UN, CX, KG…"
                    value={form.unidade}
                    onChange={(e) => setField("unidade", e.target.value)}
                  />
                </Field>
                <div style={{ ...styles.checkboxRow, alignSelf: "end", paddingBottom: 9 }}>
                  <input
                    id="permitir-inclusao-vendas"
                    type="checkbox"
                    checked={!!form.permitir_inclusao_vendas}
                    onChange={(e) => setField("permitir_inclusao_vendas", e.target.checked)}
                  />
                  <label htmlFor="permitir-inclusao-vendas">Permitir inclusão nas vendas</label>
                </div>

                <div style={styles.fullRow}>
                  <Field label="Observações" id="np-observacoes">
                    <textarea
                      id="np-observacoes"
                      style={{ minHeight: 80, resize: "vertical" }}
                      value={form.observacoes}
                      onChange={(e) => setField("observacoes", e.target.value)}
                    />
                  </Field>
                </div>
              </div>

              {formError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{formError}</div> : null}

              <div style={styles.modalFooter}>
                <Button type="button" variant="secondary" onClick={closeForm} disabled={saving}>
                  Cancelar
                </Button>
                <Button type="submit" variant="primary" loading={saving} disabled={saving}>
                  {saving ? "Salvando…" : "Salvar produto"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {importOpen ? (
        <div style={styles.modalOverlay} onClick={closeImport}>
          <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Importar do Tiny</div>
                <div style={styles.muted}>Importação para a base local · {companyLabel(company)}</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeImport} disabled={importBusy}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              A importação não altera produtos no Tiny; apenas traz dados do Tiny para a base local.
            </div>
            <div style={{ ...styles.notice, marginTop: 8, borderColor: "#fde68a", background: "#fffbeb", color: "#92400e" }}>
              Para evitar limite do Tiny, importe em lotes. Use o próximo offset retornado para continuar.
            </div>

            <div style={{ ...styles.formGrid, marginTop: 14 }}>
              <label style={styles.fieldLabel}>
                Limite por página (máx. 100)
                <input
                  style={styles.input}
                  type="number"
                  min="1"
                  max="100"
                  value={importForm.limit}
                  onChange={(e) => setImportField("limit", e.target.value)}
                />
              </label>
              <label style={styles.fieldLabel}>
                Offset inicial
                <input
                  style={styles.input}
                  type="number"
                  min="0"
                  value={importForm.offset_start}
                  onChange={(e) => setImportField("offset_start", e.target.value)}
                />
              </label>

              <label style={styles.fieldLabel}>
                Máx. de páginas (máx. 100)
                <input
                  style={styles.input}
                  type="number"
                  min="1"
                  max="100"
                  value={importForm.max_pages}
                  onChange={(e) => setImportField("max_pages", e.target.value)}
                />
              </label>
              <label style={styles.fieldLabel}>
                Pausa entre páginas (ms)
                <input
                  style={styles.input}
                  type="number"
                  min="0"
                  max="5000"
                  step="100"
                  value={importForm.sleep_ms}
                  onChange={(e) => setImportField("sleep_ms", e.target.value)}
                />
              </label>

              <label style={styles.fieldLabel}>
                Situação
                <select
                  style={styles.select}
                  value={importForm.situacao}
                  onChange={(e) => setImportField("situacao", e.target.value)}
                >
                  {IMPORT_SITUACAO_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>

              <label style={styles.fieldLabel}>
                Buscar (opcional)
                <input
                  style={styles.input}
                  value={importForm.q}
                  onChange={(e) => setImportField("q", e.target.value)}
                />
              </label>
              <label style={styles.fieldLabel}>
                Campo de busca
                <select
                  style={styles.select}
                  value={importForm.field}
                  onChange={(e) => setImportField("field", e.target.value)}
                >
                  {IMPORT_FIELD_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>

              <div style={{ ...styles.checkboxRow, ...styles.fullRow }}>
                <input
                  id="import-details"
                  type="checkbox"
                  checked={!!importForm.import_details}
                  onChange={(e) => setImportField("import_details", e.target.checked)}
                />
                <label htmlFor="import-details">Importar detalhes completos de cada produto</label>
              </div>
            </div>

            {importError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{importError}</div> : null}

            {importResult && importSummary ? (
              <div style={{ marginTop: 14 }}>
                <div style={{ ...styles.muted, marginBottom: 6 }}>
                  {importResult.dry_run ? "Resultado da simulação (nada foi gravado)" : "Resultado da importação real"}
                  {` · offset inicial: ${importSummary.offset_start}`}
                  {importSummary.expected_total != null ? ` · total Tiny: ${importSummary.expected_total}` : ""}
                </div>
                <div style={styles.statsGrid}>
                  {[
                    { label: "Buscados", value: importSummary.fetched_count },
                    { label: "Criar / Criados", value: importSummary.created_count },
                    { label: "Atualizar / Atualizados", value: importSummary.updated_count },
                    { label: "Ignorados", value: importSummary.skipped_count },
                    { label: "Conflitos", value: importSummary.conflicts.length },
                    { label: "Erros", value: importSummary.errors.length },
                    { label: "Páginas processadas", value: importSummary.pages_processed },
                    { label: "Próximo offset", value: importSummary.next_offset },
                  ].map((stat) => (
                    <div key={stat.label} style={styles.statCard}>
                      <div style={styles.statLabel}>{stat.label}</div>
                      <div style={styles.statValue}>{Number(stat.value || 0)}</div>
                    </div>
                  ))}
                </div>

                <div style={{ ...styles.muted, marginTop: 8 }}>
                  Parada: <strong>{STOPPED_REASON_LABEL[importSummary.stopped_reason] || importSummary.stopped_reason || "—"}</strong>
                </div>

                {importSummary.errors.length ? (
                  <div style={{ ...styles.notice, marginTop: 8, borderColor: "#fecaca", background: "#fef2f2", color: "#991b1b" }}>
                    Houve erros na importação (possível limite do Tiny / HTTP 429). Reduza o limite por página ou aumente a pausa entre páginas.
                  </div>
                ) : null}

                {(importSummary.conflicts || []).length ? (
                  <>
                    <div style={styles.sectionTitle}>Conflitos ({importSummary.conflicts.length})</div>
                    <div style={styles.listBox}>
                      {importSummary.conflicts.slice(0, 50).map((c, idx) => (
                        <div key={`conf-${idx}`} style={styles.listRow}>
                          <span>
                            SKU <strong>{c.sku || "—"}</strong>
                            {c.tiny_product_id ? ` · Tiny #${c.tiny_product_id}` : ""}
                          </span>
                          <span style={styles.muted}>
                            {c.reason === "sku_conflict" ? "SKU já existe localmente" : c.reason}
                            {c.local_product_id ? ` (local #${c.local_product_id})` : ""}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}

                {(importSummary.errors || []).length ? (
                  <>
                    <div style={styles.sectionTitle}>Erros ({importSummary.errors.length})</div>
                    <div style={styles.listBox}>
                      {importSummary.errors.slice(0, 50).map((er, idx) => (
                        <div key={`err-${idx}`} style={styles.listRow}>
                          <span>
                            {er.sku ? `SKU ${er.sku}` : er.tiny_product_id ? `Tiny #${er.tiny_product_id}` : "—"}
                          </span>
                          <span style={styles.muted}>{String(er.error || "").slice(0, 160)}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}

                {(importSummary.sample || []).length ? (
                  <>
                    <div style={styles.sectionTitle}>Amostra ({importSummary.sample.length})</div>
                    <div style={styles.listBox}>
                      {importSummary.sample.map((s, idx) => {
                        const act = ACTION_LABEL[s.action] || { label: s.action, color: "var(--muted)" };
                        return (
                          <div key={`sample-${idx}`} style={styles.listRow}>
                            <span style={{ minWidth: 0 }}>
                              <strong>{s.nome || s.sku || `Tiny #${s.tiny_product_id}`}</strong>
                              {s.sku ? ` · ${s.sku}` : ""}
                              {Number(s.variations_count) ? ` · ${s.variations_count} variações` : ""}
                            </span>
                            <span style={{ color: act.color, fontWeight: 900, whiteSpace: "nowrap" }}>{act.label}</span>
                          </div>
                        );
                      })}
                    </div>
                  </>
                ) : null}

                {Number.isFinite(Number(importSummary.next_offset)) ? (
                  <div style={{ marginTop: 14 }}>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={continueFromNextOffset}
                      disabled={importBusy}
                    >
                      Continuar do próximo offset ({importSummary.next_offset})
                    </Button>
                    <div style={{ ...styles.muted, marginTop: 6 }}>
                      Preenche o offset inicial com {importSummary.next_offset} e exige nova simulação antes da importação real.
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div style={styles.modalFooter}>
              <Button type="button" variant="secondary" onClick={closeImport} disabled={importBusy}>
                {importPhase === "done" ? "Fechar" : "Cancelar"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => runImport(true)}
                loading={importBusy}
                disabled={importBusy}
              >
                {importBusy ? "Processando…" : importPhase === "idle" ? "Simular importação" : "Simular novamente"}
              </Button>
              {importPhase === "preview" ? (
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => runImport(false)}
                  disabled={importBusy}
                >
                  Confirmar importação real
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {refreshOpen ? (
        <div style={styles.modalOverlay} onClick={closeRefresh}>
          <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Completar detalhes Tiny</div>
                <div style={styles.muted}>Atualização de detalhes na base local · {companyLabel(company)}</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeRefresh} disabled={refreshBusy}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              Busca detalhes no Tiny e atualiza apenas a base local. Não altera produtos no Tiny.
            </div>
            <div style={{ ...styles.notice, marginTop: 8, borderColor: "#fde68a", background: "#fffbeb", color: "#92400e" }}>
              Processo lento e em lotes pequenos para evitar o limite do Tiny. Use o próximo ID retornado para continuar.
            </div>

            <div style={{ ...styles.formGrid, marginTop: 14 }}>
              <label style={styles.fieldLabel}>
                Limite (máx. 30)
                <input
                  style={styles.input}
                  type="number"
                  min="1"
                  max="30"
                  value={refreshForm.limit}
                  onChange={(e) => setRefreshField("limit", e.target.value)}
                />
              </label>
              <label style={styles.fieldLabel}>
                After ID (opcional)
                <input
                  style={styles.input}
                  type="number"
                  min="0"
                  placeholder="A partir de qual ID local"
                  value={refreshForm.after_id}
                  onChange={(e) => setRefreshField("after_id", e.target.value)}
                />
              </label>

              <label style={styles.fieldLabel}>
                Pausa entre itens (ms)
                <input
                  style={styles.input}
                  type="number"
                  min="0"
                  max="10000"
                  step="100"
                  value={refreshForm.sleep_ms}
                  onChange={(e) => setRefreshField("sleep_ms", e.target.value)}
                />
              </label>
              <label style={styles.fieldLabel}>
                Pausa após 429 (ms)
                <input
                  style={styles.input}
                  type="number"
                  min="0"
                  max="60000"
                  step="500"
                  value={refreshForm.retry_after_ms}
                  onChange={(e) => setRefreshField("retry_after_ms", e.target.value)}
                />
              </label>

              <label style={styles.fieldLabel}>
                Máx. de tentativas (0–3)
                <input
                  style={styles.input}
                  type="number"
                  min="0"
                  max="3"
                  value={refreshForm.max_retries}
                  onChange={(e) => setRefreshField("max_retries", e.target.value)}
                />
              </label>

              <div style={{ display: "grid", gap: 8, alignSelf: "end", paddingBottom: 4 }}>
                <div style={styles.checkboxRow}>
                  <input
                    id="refresh-only-missing"
                    type="checkbox"
                    checked={!!refreshForm.only_missing}
                    onChange={(e) => setRefreshField("only_missing", e.target.checked)}
                  />
                  <label htmlFor="refresh-only-missing">Apenas produtos sem detalhes</label>
                </div>
                <div style={styles.checkboxRow}>
                  <input
                    id="refresh-retry-429"
                    type="checkbox"
                    checked={!!refreshForm.retry_429}
                    onChange={(e) => setRefreshField("retry_429", e.target.checked)}
                  />
                  <label htmlFor="refresh-retry-429">Tentar novamente em caso de 429</label>
                </div>
              </div>
            </div>

            {refreshError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{refreshError}</div> : null}

            {refreshResult && refreshSummary ? (
              <div style={{ marginTop: 14 }}>
                {refreshSummary.stopped_reason === "empty_selection" ? (
                  <div style={styles.notice}>
                    Nenhum produto pendente de detalhes conforme o critério atual.
                  </div>
                ) : (
                  <>
                    <div style={{ ...styles.muted, marginBottom: 6 }}>
                      {refreshResult.dry_run ? "Resultado da simulação (nada foi gravado)" : "Resultado da atualização real"}
                    </div>
                    <div style={styles.statsGrid}>
                      {[
                        { label: "Processados", value: refreshSummary.processed_count },
                        { label: "Atualizar / Atualizados", value: refreshSummary.updated_count },
                        { label: "Ignorados", value: refreshSummary.skipped_count },
                        { label: "Erros", value: refreshSummary.errors.length },
                        { label: "Próximo ID", value: refreshSummary.next_after_id },
                      ].map((stat) => (
                        <div key={stat.label} style={styles.statCard}>
                          <div style={styles.statLabel}>{stat.label}</div>
                          <div style={styles.statValue}>{Number(stat.value || 0)}</div>
                        </div>
                      ))}
                    </div>

                    <div style={{ ...styles.muted, marginTop: 8 }}>
                      Parada: <strong>{REFRESH_STOPPED_REASON_LABEL[refreshSummary.stopped_reason] || refreshSummary.stopped_reason || "—"}</strong>
                    </div>
                  </>
                )}

                {refreshHas429 ? (
                  <div style={{ ...styles.notice, marginTop: 8, borderColor: "#fecaca", background: "#fef2f2", color: "#991b1b" }}>
                    O Tiny retornou limite de requisições (HTTP 429). Aumente a pausa entre itens ou reduza o limite do lote.
                  </div>
                ) : null}

                {(refreshSummary.errors || []).length ? (
                  <>
                    <div style={styles.sectionTitle}>Erros ({refreshSummary.errors.length})</div>
                    <div style={styles.listBox}>
                      {refreshSummary.errors.slice(0, 50).map((er, idx) => (
                        <div key={`refresh-err-${idx}`} style={styles.listRow}>
                          <span>
                            {er.sku ? `SKU ${er.sku}` : er.tiny_product_id ? `Tiny #${er.tiny_product_id}` : er.id ? `Local #${er.id}` : "—"}
                          </span>
                          <span style={styles.muted}>{String(er.error || "").slice(0, 160)}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}

                {(refreshSummary.sample || []).length ? (
                  <>
                    <div style={styles.sectionTitle}>Amostra ({refreshSummary.sample.length})</div>
                    <div style={styles.listBox}>
                      {refreshSummary.sample.map((s, idx) => {
                        const act = REFRESH_ACTION_LABEL[s.action] || { label: s.action, color: "var(--muted)" };
                        return (
                          <div key={`refresh-sample-${idx}`} style={styles.listRow}>
                            <span style={{ minWidth: 0 }}>
                              <strong>{s.nome || s.sku || `Tiny #${s.tiny_product_id}`}</strong>
                              {s.sku ? ` · ${s.sku}` : ""}
                              {s.id ? ` · local #${s.id}` : ""}
                            </span>
                            <span style={{ color: act.color, fontWeight: 900, whiteSpace: "nowrap" }}>{act.label}</span>
                          </div>
                        );
                      })}
                    </div>
                  </>
                ) : null}

                {Number.isFinite(Number(refreshSummary.next_after_id)) ? (
                  <div style={{ marginTop: 14 }}>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={continueFromNextAfterId}
                      disabled={refreshBusy}
                    >
                      Continuar do próximo ID ({refreshSummary.next_after_id})
                    </Button>
                    <div style={{ ...styles.muted, marginTop: 6 }}>
                      Preenche o After ID com {refreshSummary.next_after_id} e exige nova simulação antes da atualização real.
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div style={styles.modalFooter}>
              <Button type="button" variant="secondary" onClick={closeRefresh} disabled={refreshBusy}>
                {refreshPhase === "done" ? "Fechar" : "Cancelar"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => runRefresh(true)}
                loading={refreshBusy}
                disabled={refreshBusy}
              >
                {refreshBusy ? "Processando…" : refreshPhase === "idle" ? "Simular" : "Simular novamente"}
              </Button>
              {refreshPhase === "preview" && refreshSummary?.stopped_reason !== "empty_selection" ? (
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => runRefresh(false)}
                  disabled={refreshBusy}
                >
                  Confirmar atualização real
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {stockOpen ? (
        <div style={styles.modalOverlay} onClick={closeStockSync}>
          <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Estoque Tiny</div>
                <div style={styles.muted}>Sincronizacao Tiny para ERP Local - {companyLabel(company)}</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeStockSync} disabled={stockBusy}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              Sincronizacao somente leitura Tiny para ERP Local. Nao altera produtos no Tiny, nao importa cadastro e nao mexe no catalogo antigo.
            </div>

            {stockError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{stockError}</div> : null}

            <div style={{ ...styles.card, marginTop: 12 }}>
              <div style={styles.sectionTitle}>Status diario</div>
              <div style={styles.statsGrid}>
                {[
                  { label: "Pode rodar hoje", value: stockStatus?.can_run_today ? "Sim" : "Nao" },
                  { label: "Execucoes reais hoje", value: stockStatus?.today_run_count ?? 0 },
                  { label: "Limite diario", value: stockStatus?.daily_limit ?? 1 },
                ].map((s) => (
                  <div key={s.label} style={styles.statCard}>
                    <div style={styles.statLabel}>{s.label}</div>
                    <div style={styles.statValue}>{s.value}</div>
                  </div>
                ))}
              </div>
              {stockStatus?.last_run ? (
                <div style={{ ...styles.muted, marginTop: 8 }}>
                  Ultima execucao: #{stockStatus.last_run.id} - {stockStatus.last_run.status} - {formatDate(stockStatus.last_run.started_at)}
                </div>
              ) : (
                <div style={{ ...styles.muted, marginTop: 8 }}>Sem execucao registrada para esta empresa.</div>
              )}
            </div>

            <div style={{ ...styles.formGrid, marginTop: 12 }}>
              <label style={styles.fieldLabel}>
                Limite
                <input style={styles.input} type="number" min="1" max="100" value={stockForm.limit} onChange={(e) => setStockField("limit", e.target.value)} />
              </label>
              <label style={styles.fieldLabel}>
                Pausa entre itens (ms)
                <input style={styles.input} type="number" min="0" max="5000" value={stockForm.sleep_ms} onChange={(e) => setStockField("sleep_ms", e.target.value)} />
              </label>
              <label style={styles.fieldLabel}>
                After ID
                <input style={styles.input} value={stockForm.after_id} onChange={(e) => setStockField("after_id", e.target.value)} placeholder="Opcional" />
              </label>
              <label style={styles.fieldLabel}>
                Max erros
                <input style={styles.input} type="number" min="1" max="100" value={stockForm.max_errors} onChange={(e) => setStockField("max_errors", e.target.value)} />
              </label>
              <label style={{ ...styles.checkboxRow, ...styles.fullRow }}>
                <input type="checkbox" checked={stockForm.only_with_tiny_product_id} onChange={(e) => setStockField("only_with_tiny_product_id", e.target.checked)} />
                Somente produtos com Tiny ID
              </label>
              <label style={{ ...styles.checkboxRow, ...styles.fullRow }}>
                <input type="checkbox" checked={stockForm.update_payload} onChange={(e) => setStockField("update_payload", e.target.checked)} />
                Salvar payload bruto de estoque
              </label>
              <label style={{ ...styles.checkboxRow, ...styles.fullRow }}>
                <input type="checkbox" checked={stockForm.force} onChange={(e) => setStockField("force", e.target.checked)} />
                Forcar execucao real mesmo se ja rodou hoje
              </label>
            </div>

            {stockForm.force ? (
              <div style={{ ...styles.errorBox, marginTop: 12 }}>
                Force deve ser usado apenas para continuacao/teste controlado no mesmo dia.
              </div>
            ) : null}

            {stockSummary ? (
              <div style={{ marginTop: 14 }}>
                <div style={styles.statsGrid}>
                  {[
                    { label: "Processados", value: stockSummary.processed_count },
                    { label: "Atualizados", value: stockSummary.updated_count },
                    { label: "Ignorados/erros", value: stockSummary.skipped_count },
                  ].map((s) => (
                    <div key={s.label} style={styles.statCard}>
                      <div style={styles.statLabel}>{s.label}</div>
                      <div style={styles.statValue}>{Number(s.value || 0).toLocaleString("pt-BR")}</div>
                    </div>
                  ))}
                </div>
                <div style={{ ...styles.muted, marginTop: 8 }}>
                  Parada: {stockSummary.stopped_reason || "-"}
                  {stockSummary.next_after_id ? ` - proximo after_id ${stockSummary.next_after_id}` : ""}
                </div>
                {(stockSummary.samples || []).length ? (
                  <div style={styles.listBox}>
                    {stockSummary.samples.slice(0, 20).map((s, idx) => (
                      <div key={`stock-sample-${idx}`} style={styles.listRow}>
                        <span>
                          #{s.id} {s.sku || ""} - fisico {formatStock(s.stock_physical)} - reservado {formatStock(s.stock_reserved)} - disponivel {formatStock(s.stock_available)}
                        </span>
                        <span style={{ color: s.action === "updated" ? "#166534" : "#1d4ed8", fontWeight: 900 }}>{s.action}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
                {(stockSummary.errors || []).length ? (
                  <div style={{ ...styles.errorBox, marginTop: 10 }}>
                    Erros: {stockSummary.errors.slice(0, 3).map((er) => er.error).join(" | ")}
                  </div>
                ) : null}
              </div>
            ) : null}

            <div style={styles.modalFooter}>
              <Button type="button" variant="secondary" onClick={closeStockSync} disabled={stockBusy}>
                {stockPhase === "done" ? "Fechar" : "Cancelar"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => runStockSync(true)} loading={stockBusy} disabled={stockBusy}>
                {stockBusy ? "Processando..." : stockPhase === "idle" ? "Simular" : "Simular novamente"}
              </Button>
              {stockPhase === "preview" ? (
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => runStockSync(false)}
                  disabled={stockBusy || (!stockStatus?.can_run_today && !stockForm.force)}
                >
                  Executar sincronizacao real
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {diagOpen ? (
        <div style={styles.modalOverlay} onClick={closeDiag}>
          <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Diagnóstico de SKUs</div>
                <div style={styles.muted}>Conflitos e duplicidades · {companyLabel(company)}</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeDiag} disabled={diagBusy}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              Somente leitura. Não altera produtos no Tiny nem na base local.
            </div>

            <div style={{ ...styles.checkboxRow, marginTop: 12 }}>
              <input
                id="diag-probe"
                type="checkbox"
                checked={diagProbe}
                onChange={(e) => setDiagProbe(e.target.checked)}
                disabled={diagBusy}
              />
              <label htmlFor="diag-probe">
                Sondar Tiny (somente leitura, paginado) — detecta SKUs duplicados no Tiny e conflitos Tiny↔local
              </label>
            </div>

            {diagError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{diagError}</div> : null}

            {diagResult ? (
              <div style={{ marginTop: 14 }}>
                <div style={styles.statsGrid}>
                  {[
                    { label: "SKUs duplicados (local)", value: diagResult.local_duplicate_skus_count },
                    { label: "Linhas duplicadas (local)", value: diagResult.local_duplicate_rows_count },
                    { label: "SKU → vários Tiny IDs", value: diagResult.known_import_conflicts?.count },
                  ].map((s) => (
                    <div key={s.label} style={styles.statCard}>
                      <div style={styles.statLabel}>{s.label}</div>
                      <div style={styles.statValue}>{Number(s.value || 0).toLocaleString("pt-BR")}</div>
                    </div>
                  ))}
                </div>

                {diagResult.notes ? (
                  <div style={{ ...styles.muted, marginTop: 8 }}>{diagResult.notes}</div>
                ) : null}

                {(diagResult.local_duplicates || []).length ? (
                  <>
                    <div style={styles.sectionTitle}>
                      Duplicidades locais ({diagResult.local_duplicates.length})
                    </div>
                    <div style={styles.listBox}>
                      {diagResult.local_duplicates.map((g, idx) => (
                        <div key={`dup-${idx}`} style={{ ...styles.listRow, display: "block" }}>
                          <div style={{ fontWeight: 900 }}>
                            SKU {g.sku} · {g.count} produtos
                          </div>
                          {(g.items || []).map((it, j) => (
                            <div key={`dup-${idx}-${j}`} style={{ ...styles.muted, marginTop: 3 }}>
                              local #{it.id}
                              {it.tiny_product_id ? ` · Tiny #${it.tiny_product_id}` : " · sem Tiny ID"}
                              {it.origin ? ` · ${it.origin}` : ""}
                              {it.tiny_sync_status ? ` · ${it.tiny_sync_status}` : ""}
                              {it.nome ? ` · ${it.nome}` : ""}
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}

                {(diagResult.known_import_conflicts?.items || []).length ? (
                  <>
                    <div style={styles.sectionTitle}>
                      SKU ligado a vários tiny_product_id ({diagResult.known_import_conflicts.items.length})
                    </div>
                    <div style={styles.listBox}>
                      {diagResult.known_import_conflicts.items.map((c, idx) => (
                        <div key={`kic-${idx}`} style={styles.listRow}>
                          <span><strong>{c.sku}</strong></span>
                          <span style={styles.muted}>
                            Tiny IDs: {(c.tiny_product_ids || []).join(", ")} · local: {(c.local_ids || []).join(", ")}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}

                {diagResult.include_tiny_probe ? (
                  <>
                    <div style={styles.sectionTitle}>Sonda Tiny (somente leitura)</div>
                    <div style={styles.statsGrid}>
                      {[
                        { label: "Itens lidos", value: diagResult.tiny_probe?.fetched_count },
                        { label: "Páginas", value: diagResult.tiny_probe?.pages_processed },
                        { label: "SKUs dup. no Tiny", value: diagResult.tiny_duplicate_skus_count },
                        { label: "Conflitos Tiny↔local", value: (diagResult.tiny_vs_local_conflicts || []).length },
                      ].map((s) => (
                        <div key={s.label} style={styles.statCard}>
                          <div style={styles.statLabel}>{s.label}</div>
                          <div style={styles.statValue}>{Number(s.value || 0).toLocaleString("pt-BR")}</div>
                        </div>
                      ))}
                    </div>
                    {(diagResult.tiny_probe?.errors || []).length ? (
                      <div style={{ ...styles.notice, marginTop: 8, borderColor: "#fecaca", background: "#fef2f2", color: "#991b1b" }}>
                        A sonda Tiny encontrou erros (possível limite HTTP 429). Reduza as páginas ou aumente a pausa.
                      </div>
                    ) : null}

                    {(diagResult.tiny_vs_local_conflicts || []).length ? (
                      <>
                        <div style={styles.sectionTitle}>
                          Conflitos Tiny↔local ({diagResult.tiny_vs_local_conflicts.length})
                        </div>
                        <div style={styles.listBox}>
                          {diagResult.tiny_vs_local_conflicts.map((c, idx) => (
                            <div key={`tvl-${idx}`} style={{ ...styles.listRow, display: "block" }}>
                              <div style={{ fontWeight: 900 }}>SKU {c.sku}</div>
                              <div style={{ ...styles.muted, marginTop: 3 }}>
                                Tiny novo #{c.tiny_product_id}
                                {c.tiny_nome ? ` (${c.tiny_nome})` : ""} · local #{c.local_product_id}
                                {c.local_tiny_product_id ? ` (Tiny #${c.local_tiny_product_id})` : ""}
                                {c.local_origin ? ` · ${c.local_origin}` : ""}
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : null}

                    {(diagResult.tiny_vs_local_conflicts || []).length ? (
                      <>
                        <div style={styles.sectionTitle}>Classificacao assistida de conflitos</div>
                        <div style={{ ...styles.notice, marginBottom: 8 }}>
                          Esta acao apenas registra a decisao no ERP Local. Nao altera produtos no Tiny, nao troca tiny_product_id e nao faz merge.
                        </div>
                        {decisionMessage ? <div style={{ ...styles.notice, marginBottom: 8 }}>{decisionMessage}</div> : null}
                        {decisionError ? <div style={{ ...styles.errorBox, marginBottom: 8 }}>{decisionError}</div> : null}
                        <div style={styles.listBox}>
                          {diagResult.tiny_vs_local_conflicts.map((c, idx) => {
                            const key = conflictDecisionKey(c);
                            const existing = c.decision || {};
                            const draft = decisionDrafts[key] || {};
                            const selectedDecision = draft.decision || existing.decision || "review_later";
                            const notes = draft.notes ?? existing.notes ?? "";
                            const saving = decisionSavingKey === key;
                            return (
                              <div key={`decision-${idx}`} style={{ ...styles.listRow, display: "block" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                                  <div style={{ fontWeight: 900 }}>SKU {c.sku}</div>
                                  {existing.decision ? (
                                    <span style={{ ...styles.badge, borderColor: "#bbf7d0", color: "#166534", background: "#f0fdf4" }}>
                                      {CONFLICT_DECISION_OPTIONS.find((opt) => opt.value === existing.decision)?.label || existing.decision}
                                    </span>
                                  ) : (
                                    <span style={{ ...styles.badge, color: "var(--muted)" }}>Sem decisao</span>
                                  )}
                                </div>
                                <div style={{ ...styles.muted, marginTop: 3 }}>
                                  Local #{c.local_product_id}
                                  {c.local_tiny_product_id ? ` - Tiny local #${c.local_tiny_product_id}` : ""}
                                  {" - "}Tiny conflitante #{c.tiny_product_id}
                                  {c.tiny_nome ? ` - ${c.tiny_nome}` : ""}
                                </div>
                                <div style={{ display: "grid", gridTemplateColumns: "minmax(180px, 260px) minmax(220px, 1fr) auto", gap: 8, alignItems: "end", marginTop: 8 }}>
                                  <label style={styles.fieldLabel}>
                                    Classificacao
                                    <select
                                      style={styles.select}
                                      value={selectedDecision}
                                      disabled={saving}
                                      onChange={(e) => setDecisionDrafts((current) => ({
                                        ...current,
                                        [key]: { decision: e.target.value, notes },
                                      }))}
                                    >
                                      {CONFLICT_DECISION_OPTIONS.map((opt) => (
                                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                                      ))}
                                    </select>
                                  </label>
                                  <label style={styles.fieldLabel}>
                                    Observacao
                                    <input
                                      style={styles.input}
                                      value={notes}
                                      disabled={saving}
                                      placeholder="Contexto da decisao"
                                      onChange={(e) => setDecisionDrafts((current) => ({
                                        ...current,
                                        [key]: { decision: selectedDecision, notes: e.target.value },
                                      }))}
                                    />
                                  </label>
                                  <Button
                                    type="button"
                                    variant="primary"
                                    style={{ whiteSpace: "nowrap" }}
                                    loading={saving}
                                    disabled={saving || diagBusy}
                                    onClick={() => saveConflictDecision(c)}
                                  >
                                    {saving ? "Salvando..." : "Salvar decisao"}
                                  </Button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </>
                    ) : null}

                    {(diagResult.tiny_duplicates || []).length ? (
                      <>
                        <div style={styles.sectionTitle}>
                          SKUs duplicados no Tiny ({diagResult.tiny_duplicates.length})
                        </div>
                        <div style={styles.listBox}>
                          {diagResult.tiny_duplicates.map((g, idx) => (
                            <div key={`tdup-${idx}`} style={{ ...styles.listRow, display: "block" }}>
                              <div style={{ fontWeight: 900 }}>SKU {g.sku} · {g.count} produtos Tiny</div>
                              {(g.items || []).map((it, j) => (
                                <div key={`tdup-${idx}-${j}`} style={{ ...styles.muted, marginTop: 3 }}>
                                  Tiny #{it.tiny_product_id}
                                  {it.nome ? ` · ${it.nome}` : ""}
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      </>
                    ) : null}
                  </>
                ) : null}
              </div>
            ) : null}

            <div style={styles.modalFooter}>
              <Button type="button" variant="secondary" onClick={closeDiag} disabled={diagBusy}>
                Fechar
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={() => runDiag(diagProbe)}
                loading={diagBusy}
                disabled={diagBusy}
              >
                {diagBusy ? "Processando…" : diagResult ? "Atualizar diagnóstico" : "Executar diagnóstico"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {stockCtrlOpen ? (
        <div style={styles.modalOverlay} onClick={closeStockCtrl}>
          <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Controle de estoque</div>
                <div style={styles.muted}>Estoque local do ERP · Não altera Tiny/Olist</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeStockCtrl} disabled={stockCtrlBusy}>
                Fechar
              </Button>
            </div>

            <div style={{ fontWeight: 800 }}>
              {stockCtrlProduct?.nome || stockCtrlData?.product?.nome || "—"}
            </div>
            <div style={{ ...styles.muted, marginTop: 2 }}>
              {(stockCtrlProduct?.sku || stockCtrlData?.product?.sku)
                ? `SKU ${stockCtrlProduct?.sku || stockCtrlData?.product?.sku}`
                : "Sem SKU"}
              {(stockCtrlProduct?.tiny_product_id || stockCtrlData?.product?.tiny_product_id)
                ? ` · Tiny #${stockCtrlProduct?.tiny_product_id || stockCtrlData?.product?.tiny_product_id}`
                : ""}
            </div>

            <div style={{ ...styles.notice, marginTop: 12 }}>
              Este movimento altera apenas o estoque local do ERP. Não altera o estoque no Tiny/Olist.
            </div>

            {stockCtrlLoading ? (
              <div style={{ ...styles.muted, marginTop: 12 }}>Carregando estoque…</div>
            ) : stockCtrlData?.stock ? (
              <>
                <div style={{ ...styles.statCard, marginTop: 12 }}>
                  <div style={styles.statLabel}>Estoque físico</div>
                  <div style={styles.statValue}>{formatStock(stockCtrlData.stock.stock_physical)}</div>
                </div>
                {/* Reservado/Disponível mantidos como info secundária discreta (usuário não opera reservado por enquanto). */}
                <div style={{ ...styles.muted, marginTop: 6 }}>
                  Reservado {formatStock(stockCtrlData.stock.stock_reserved)} · Disponível {formatStock(stockCtrlData.stock.stock_available)}
                </div>
                {stockCtrlData.stock.stock_synced_at ? (
                  <div style={{ ...styles.muted, marginTop: 8 }}>
                    Última sincronização Tiny: {formatDate(stockCtrlData.stock.stock_synced_at)}
                  </div>
                ) : null}
              </>
            ) : null}

            <form onSubmit={submitStockMovement} style={{ marginTop: 14 }}>
              <div style={styles.formGrid}>
                <label style={styles.fieldLabel}>
                  Tipo de movimento
                  <select
                    style={styles.select}
                    value={stockCtrlForm.movement_type}
                    onChange={(e) => setStockCtrlField("movement_type", e.target.value)}
                  >
                    {STOCK_MOVEMENT_OPTIONS_SIMPLE.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </label>

                {STOCK_TARGET_TYPES.has(stockCtrlForm.movement_type) ? (
                  <label style={styles.fieldLabel}>
                    Novo estoque físico
                    <input
                      style={styles.input}
                      type="number"
                      step="0.001"
                      min="0"
                      value={stockCtrlForm.new_stock_physical}
                      onChange={(e) => setStockCtrlField("new_stock_physical", e.target.value)}
                    />
                  </label>
                ) : (
                  <label style={styles.fieldLabel}>
                    Quantidade
                    <input
                      style={styles.input}
                      type="number"
                      step="0.001"
                      min="0"
                      value={stockCtrlForm.quantity}
                      onChange={(e) => setStockCtrlField("quantity", e.target.value)}
                    />
                  </label>
                )}

                <label style={{ ...styles.fieldLabel, ...styles.fullRow }}>
                  Motivo
                  <input
                    style={styles.input}
                    value={stockCtrlForm.reason}
                    onChange={(e) => setStockCtrlField("reason", e.target.value)}
                    placeholder="Ex.: Ajuste manual, inventário, devolução…"
                  />
                </label>

                <label style={{ ...styles.fieldLabel, ...styles.fullRow }}>
                  Observações
                  <textarea
                    style={{ ...styles.input, minHeight: 64, resize: "vertical" }}
                    value={stockCtrlForm.notes}
                    onChange={(e) => setStockCtrlField("notes", e.target.value)}
                  />
                </label>
              </div>

              {stockCtrlError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{stockCtrlError}</div> : null}
              {stockCtrlMsg ? (
                <div style={{ ...styles.notice, marginTop: 12, borderColor: "#bbf7d0", background: "#f0fdf4", color: "#166534" }}>
                  {stockCtrlMsg}
                </div>
              ) : null}

              <div style={styles.modalFooter}>
                <Button type="button" variant="secondary" onClick={closeStockCtrl} disabled={stockCtrlBusy}>
                  Cancelar
                </Button>
                <Button type="submit" variant="primary" loading={stockCtrlBusy} disabled={stockCtrlBusy}>
                  {stockCtrlBusy ? "Registrando…" : "Confirmar movimento"}
                </Button>
              </div>
            </form>

            {(stockCtrlData?.movements || []).length ? (
              <>
                <div style={styles.sectionTitle}>Últimos movimentos ({stockCtrlData.movements.length})</div>
                <div style={styles.listBox}>
                  {stockCtrlData.movements.map((m) => {
                    const isReversal = !!m.is_reversal;
                    const isReversed = !!m.reversed_at;
                    const canReverse = !isReversal && !isReversed;
                    const badge = isReversal
                      ? { label: "Estorno", bg: "#eff6ff", color: "#1e3a8a", border: "#bfdbfe" }
                      : isReversed
                      ? { label: "Estornado", bg: "rgba(148,163,184,.12)", color: "var(--muted)", border: "var(--border)" }
                      : null;
                    return (
                      <div key={m.id} style={{ ...styles.listRow, display: "block" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                          <div style={{ fontWeight: 900 }}>
                            {STOCK_MOVEMENT_LABEL[m.movement_type] || m.movement_type}
                            {" · qtd "}
                            {formatStock(m.quantity)}
                            {badge ? (
                              <span
                                style={{
                                  ...styles.badge,
                                  marginLeft: 8,
                                  background: badge.bg,
                                  color: badge.color,
                                  borderColor: badge.border,
                                }}
                              >
                                {badge.label}
                              </span>
                            ) : null}
                            <span style={{ ...styles.muted, fontWeight: 700 }}>{` · ${formatDate(m.created_at)}`}</span>
                          </div>
                          {canReverse ? (
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              style={{ whiteSpace: "nowrap" }}
                              onClick={() => openReverse(m.id)}
                              disabled={reverseBusy}
                            >
                              Estornar
                            </Button>
                          ) : null}
                        </div>
                        <div style={{ ...styles.muted, marginTop: 3 }}>
                          Físico {formatStock(m.new_physical)} · Reservado {formatStock(m.new_reserved)} · Disponível {formatStock(m.new_available)}
                          {m.reason ? ` · ${m.reason}` : ""}
                          {m.created_by ? ` · ${m.created_by}` : ""}
                          {isReversed && m.reversal_movement_id ? ` · estorno #${m.reversal_movement_id}` : ""}
                          {isReversal && m.reverses_movement_id ? ` · estorna #${m.reverses_movement_id}` : ""}
                        </div>
                        {reverseTargetId === m.id ? (
                          <div style={{ marginTop: 8, padding: 10, border: "1px solid var(--border)", borderRadius: 8 }}>
                            <div style={{ ...styles.muted, marginBottom: 8 }}>
                              O estorno não apaga o movimento original. Será criado um novo movimento inverso e os
                              saldos locais serão atualizados. Não altera Tiny/Olist.
                            </div>
                            <input
                              style={styles.input}
                              value={reverseReason}
                              onChange={(e) => {
                                setReverseReason(e.target.value);
                                setReverseError("");
                              }}
                              placeholder="Motivo do estorno (obrigatório)"
                              autoFocus
                            />
                            {reverseError ? (
                              <div style={{ ...styles.errorBox, marginTop: 8 }}>{reverseError}</div>
                            ) : null}
                            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
                              <Button type="button" variant="secondary" onClick={cancelReverse} disabled={reverseBusy}>
                                Cancelar
                              </Button>
                              <Button
                                type="button"
                                variant="primary"
                                onClick={() => submitReversal(m.id)}
                                loading={reverseBusy}
                                disabled={reverseBusy}
                              >
                                {reverseBusy ? "Estornando…" : "Confirmar estorno"}
                              </Button>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </>
            ) : stockCtrlData && !stockCtrlLoading ? (
              <div style={{ ...styles.muted, marginTop: 12 }}>Sem movimentos registrados ainda.</div>
            ) : null}
          </div>
        </div>
      ) : null}

      {movReportOpen ? (
        <div style={styles.modalOverlay} onClick={closeMovReport}>
          <div
            style={{ ...styles.modal, width: "min(980px, 96vw)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Movimentações de estoque</div>
                <div style={styles.muted}>
                  Auditoria do estoque local do ERP · {companyLabel(company)} · Não altera Tiny/Olist
                </div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeMovReport} disabled={movReportLoading}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              Esta consulta é somente leitura. Não altera estoque local nem Tiny/Olist.
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                loadMovReport(0, movFilters);
              }}
              style={{ marginTop: 12 }}
            >
              <div style={styles.formGrid}>
                <label style={{ ...styles.fieldLabel, ...styles.fullRow }}>
                  Buscar por produto/SKU
                  <input
                    style={styles.input}
                    value={movFilters.q}
                    onChange={(e) => setMovFilter("q", e.target.value)}
                    placeholder="Nome do produto ou SKU"
                  />
                </label>
                <label style={styles.fieldLabel}>
                  Tipo de movimento
                  <select
                    style={styles.input}
                    value={movFilters.movement_type}
                    onChange={(e) => setMovFilter("movement_type", e.target.value)}
                  >
                    <option value="">Todos</option>
                    {STOCK_MOVEMENT_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <label style={styles.fieldLabel}>
                    Data inicial
                    <input
                      type="date"
                      style={styles.input}
                      value={movFilters.date_from}
                      onChange={(e) => setMovFilter("date_from", e.target.value)}
                    />
                  </label>
                  <label style={styles.fieldLabel}>
                    Data final
                    <input
                      type="date"
                      style={styles.input}
                      value={movFilters.date_to}
                      onChange={(e) => setMovFilter("date_to", e.target.value)}
                    />
                  </label>
                </div>
                <div style={{ ...styles.fullRow, display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
                  <label style={styles.checkboxRow}>
                    <input
                      type="checkbox"
                      checked={!!movFilters.include_reversed}
                      onChange={(e) => setMovFilter("include_reversed", e.target.checked)}
                    />
                    Incluir estornados
                  </label>
                  <label style={styles.checkboxRow}>
                    <input
                      type="checkbox"
                      checked={!!movFilters.only_reversed}
                      onChange={(e) => setMovFilter("only_reversed", e.target.checked)}
                    />
                    Somente estornados
                  </label>
                  <label style={styles.checkboxRow}>
                    <input
                      type="checkbox"
                      checked={!!movFilters.only_reversals}
                      onChange={(e) => setMovFilter("only_reversals", e.target.checked)}
                    />
                    Somente estornos
                  </label>
                  <Button
                    type="submit"
                    variant="primary"
                    style={{ marginLeft: "auto" }}
                    loading={movReportLoading}
                    disabled={movReportLoading}
                  >
                    {movReportLoading ? "Filtrando…" : "Filtrar"}
                  </Button>
                </div>
              </div>
            </form>

            {movReportError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{movReportError}</div> : null}

            {movReportData?.summary ? (
              <div style={{ ...styles.muted, marginTop: 12, fontWeight: 700 }}>
                {`Entradas ${movReportData.summary.entries} · Saídas ${movReportData.summary.exits} · Ajustes ${movReportData.summary.adjustments} · Reservas ${movReportData.summary.reservations} · Liberações ${movReportData.summary.releases} · Estornos ${movReportData.summary.reversals} · Estornados ${movReportData.summary.reversed}`}
              </div>
            ) : null}

            {(movReportData?.items || []).length ? (
              <div style={{ ...styles.listBox, maxHeight: 380, marginTop: 12 }}>
                {movReportData.items.map((m) => {
                  const isReversal = !!m.is_reversal;
                  const isReversed = !!m.reversed_at;
                  const badge = isReversal
                    ? { label: "Estorno", bg: "#eff6ff", color: "#1e3a8a", border: "#bfdbfe" }
                    : isReversed
                    ? { label: "Estornado", bg: "rgba(148,163,184,.12)", color: "var(--muted)", border: "var(--border)" }
                    : { label: "Ativo", bg: "rgba(34,197,94,.10)", color: "#166534", border: "#bbf7d0" };
                  return (
                    <div key={m.id} style={{ ...styles.listRow, display: "block" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                        <div style={{ fontWeight: 900 }}>
                          {STOCK_MOVEMENT_LABEL[m.movement_type] || m.movement_type}
                          {" · qtd "}
                          {formatStock(m.quantity)}
                          <span
                            style={{
                              ...styles.badge,
                              marginLeft: 8,
                              background: badge.bg,
                              color: badge.color,
                              borderColor: badge.border,
                            }}
                          >
                            {badge.label}
                          </span>
                        </div>
                        <span style={{ ...styles.muted, fontWeight: 700 }}>{formatDate(m.created_at)}</span>
                      </div>
                      <div style={{ fontWeight: 800, marginTop: 2 }}>
                        {m.product_name || "(sem nome)"}
                        {m.sku ? <span style={{ ...styles.muted, fontWeight: 700 }}>{` · ${m.sku}`}</span> : null}
                      </div>
                      <div style={{ ...styles.muted, marginTop: 3 }}>
                        {`Físico ${formatStock(m.previous_physical)}→${formatStock(m.new_physical)}`}
                        {` · Reservado ${formatStock(m.previous_reserved)}→${formatStock(m.new_reserved)}`}
                        {` · Disponível ${formatStock(m.previous_available)}→${formatStock(m.new_available)}`}
                        {m.created_by ? ` · ${m.created_by}` : ""}
                        {m.reason ? ` · ${m.reason}` : ""}
                        {isReversed && m.reversal_movement_id ? ` · estorno #${m.reversal_movement_id}` : ""}
                        {isReversal && m.reverses_movement_id ? ` · estorna #${m.reverses_movement_id}` : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : movReportData && !movReportLoading ? (
              <div style={{ ...styles.muted, marginTop: 12 }}>Nenhuma movimentação encontrada com estes filtros.</div>
            ) : null}

            {movReportData ? (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginTop: 12 }}>
                <span style={styles.muted}>
                  {(() => {
                    const total = movReportData.total || 0;
                    const count = (movReportData.items || []).length;
                    const start = total ? movReportOffset + 1 : 0;
                    const end = movReportOffset + count;
                    return `${start}-${end} de ${total}`;
                  })()}
                </span>
                <div style={{ display: "flex", gap: 8 }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => loadMovReport(Math.max(0, movReportOffset - MOV_REPORT_PAGE_SIZE), movFilters)}
                    disabled={movReportLoading || movReportOffset <= 0}
                  >
                    Anterior
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => loadMovReport(movReportOffset + MOV_REPORT_PAGE_SIZE, movFilters)}
                    disabled={movReportLoading || movReportOffset + (movReportData.items || []).length >= (movReportData.total || 0)}
                  >
                    Próximo
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {stockPosOpen ? (
        <div style={styles.modalOverlay} onClick={closeStockPos}>
          <div
            style={{ ...styles.modal, width: "min(980px, 96vw)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Posição atual de estoque</div>
                <div style={styles.muted}>Estoque local do ERP · {companyLabel(company)} · Não altera Tiny/Olist</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeStockPos} disabled={stockPosLoading}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              Esta consulta é somente leitura. Não altera estoque local nem Tiny/Olist.
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                loadStockPos(0, stockPosFilters);
              }}
              style={{ marginTop: 12 }}
            >
              <div style={styles.formGrid}>
                <label style={{ ...styles.fieldLabel, ...styles.fullRow }}>
                  Buscar por produto/SKU
                  <input
                    style={styles.input}
                    value={stockPosFilters.q}
                    onChange={(e) => setStockPosFilter("q", e.target.value)}
                    placeholder="Nome do produto ou SKU"
                  />
                </label>
                <label style={styles.fieldLabel}>
                  Status do estoque
                  <select
                    style={styles.input}
                    value={stockPosFilters.stock_status}
                    onChange={(e) => setStockPosFilter("stock_status", e.target.value)}
                  >
                    {STOCK_POS_STATUS_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                  <label style={{ ...styles.fieldLabel, flex: 1 }}>
                    Estoque mínimo
                    <input
                      type="number"
                      step="1"
                      min="0"
                      style={styles.input}
                      value={stockPosFilters.min_stock}
                      onChange={(e) => setStockPosFilter("min_stock", e.target.value)}
                    />
                  </label>
                  <Button
                    type="submit"
                    variant="primary"
                    loading={stockPosLoading}
                    disabled={stockPosLoading}
                  >
                    {stockPosLoading ? "Filtrando…" : "Filtrar"}
                  </Button>
                </div>
              </div>
            </form>

            {stockPosError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{stockPosError}</div> : null}

            {stockPosData?.summary ? (
              <div style={{ ...styles.statsGrid, gridTemplateColumns: "repeat(3, minmax(0, 1fr))", marginTop: 12 }}>
                {[
                  { label: "Total de produtos", value: stockPosData.summary.products_total },
                  { label: "Com estoque", value: stockPosData.summary.positive_count },
                  { label: "Zerados", value: stockPosData.summary.zero_count },
                  { label: "Baixo estoque", value: stockPosData.summary.low_count },
                  { label: "Negativos", value: stockPosData.summary.negative_count },
                  { label: "Valor estimado", value: formatBRL(stockPosData.summary.estimated_stock_value) },
                ].map((s) => (
                  <div key={s.label} style={styles.statCard}>
                    <div style={styles.statLabel}>{s.label}</div>
                    <div style={styles.statValue}>{s.value}</div>
                  </div>
                ))}
              </div>
            ) : null}

            {(stockPosData?.items || []).length ? (
              <div style={{ ...styles.listBox, maxHeight: 360, marginTop: 12 }}>
                {stockPosData.items.map((it) => {
                  const badge = STOCK_POS_STATUS_BADGE[it.stock_status] || STOCK_POS_STATUS_BADGE.zero;
                  return (
                    <div key={it.id} style={{ ...styles.listRow, display: "block" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                        <div style={{ fontWeight: 900 }}>
                          {it.nome || "(sem nome)"}
                          {it.sku ? <span style={{ ...styles.muted, fontWeight: 700 }}>{` · ${it.sku}`}</span> : null}
                          <span
                            style={{
                              ...styles.badge,
                              marginLeft: 8,
                              background: badge.bg,
                              color: badge.color,
                              borderColor: badge.border,
                            }}
                          >
                            {badge.label}
                          </span>
                        </div>
                        <span style={{ fontWeight: 900 }}>Físico {formatStock(it.stock_physical)}</span>
                      </div>
                      <div style={{ ...styles.muted, marginTop: 3 }}>
                        {`Custo médio ${formatBRL(it.average_cost)} · Valor estimado ${formatBRL(it.stock_estimated_value)}`}
                        {it.origin ? ` · ${it.origin}` : ""}
                        {it.updated_at ? ` · atualizado ${formatDate(it.updated_at)}` : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : stockPosData && !stockPosLoading ? (
              <div style={{ ...styles.muted, marginTop: 12 }}>Nenhum produto encontrado com estes filtros.</div>
            ) : null}

            {stockPosData ? (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginTop: 12 }}>
                <span style={styles.muted}>
                  {(() => {
                    const total = stockPosData.total || 0;
                    const count = (stockPosData.items || []).length;
                    const start = total ? stockPosOffset + 1 : 0;
                    const end = stockPosOffset + count;
                    return `${start}-${end} de ${total}`;
                  })()}
                </span>
                <div style={{ display: "flex", gap: 8 }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => loadStockPos(Math.max(0, stockPosOffset - STOCK_POS_PAGE_SIZE), stockPosFilters)}
                    disabled={stockPosLoading || stockPosOffset <= 0}
                  >
                    Anterior
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => loadStockPos(stockPosOffset + STOCK_POS_PAGE_SIZE, stockPosFilters)}
                    disabled={stockPosLoading || stockPosOffset + (stockPosData.items || []).length >= (stockPosData.total || 0)}
                  >
                    Próximo
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {bulkOpen ? (
        <div style={styles.modalOverlay} onClick={closeBulk}>
          <div
            style={{ ...styles.modal, width: "min(1040px, 96vw)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Importar ajuste de estoque</div>
                <div style={styles.muted}>Estoque local do ERP · {companyLabel(company)} · Não altera Tiny/Olist</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeBulk} disabled={bulkLoading || bulkCommitting}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              Esta importação altera apenas o estoque local do ERP após confirmação. Não altera Tiny/Olist.
            </div>

            {bulkMsg ? <div style={{ ...styles.notice, marginTop: 10, borderColor: "#bbf7d0", background: "rgba(34,197,94,.10)", color: "#166534" }}>{bulkMsg}</div> : null}

            <div style={{ ...styles.formGrid, marginTop: 12 }}>
              <label style={styles.fieldLabel}>
                Modo
                <select
                  style={styles.input}
                  value={bulkMode}
                  onChange={(e) => changeBulkMode(e.target.value)}
                  disabled={bulkCommitting}
                >
                  {STOCK_BULK_MODE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={styles.fieldLabel}>
                Arquivo (.txt, .csv)
                <input
                  type="file"
                  accept=".txt,.csv,text/plain,text/csv"
                  style={styles.input}
                  onChange={handleBulkFile}
                  disabled={bulkCommitting}
                />
              </label>
              <label style={{ ...styles.fieldLabel, ...styles.fullRow }}>
                Dados (cole no formato sku;qtd)
                <textarea
                  style={{ ...styles.input, minHeight: 110, fontFamily: "monospace", resize: "vertical" }}
                  value={bulkText}
                  onChange={(e) => {
                    setBulkText(e.target.value);
                    setBulkPreview(null);
                    setBulkMsg("");
                  }}
                  placeholder={"sku;qtd\nHP662BK;10\nTESTE-LOCAL-001;5"}
                  disabled={bulkCommitting}
                />
              </label>
              <label style={styles.fieldLabel}>
                Motivo
                <input
                  style={styles.input}
                  value={bulkReason}
                  onChange={(e) => setBulkReason(e.target.value)}
                  placeholder="Ex.: Importação de ajuste de estoque"
                  disabled={bulkCommitting}
                />
              </label>
              <label style={styles.fieldLabel}>
                Observações
                <input
                  style={styles.input}
                  value={bulkNotes}
                  onChange={(e) => setBulkNotes(e.target.value)}
                  placeholder="Opcional"
                  disabled={bulkCommitting}
                />
              </label>
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Button
                type="button"
                variant="primary"
                onClick={generateBulkPreview}
                loading={bulkLoading}
                disabled={bulkLoading || bulkCommitting}
              >
                {bulkLoading ? "Gerando prévia…" : "Gerar prévia"}
              </Button>
            </div>

            {bulkError ? <div style={{ ...styles.errorBox, marginTop: 12 }}>{bulkError}</div> : null}

            {bulkPreview ? (
              <>
                <div style={styles.sectionTitle}>Conferência ({bulkPreview.summary?.total_rows || 0} linha(s))</div>
                <div style={{ ...styles.muted, fontWeight: 700, marginBottom: 6 }}>
                  {`OK ${bulkPreview.summary?.ok_count || 0} · Erros ${bulkPreview.summary?.error_count || 0} · Não encontrados ${bulkPreview.summary?.not_found_count || 0} · Duplicados ${bulkPreview.summary?.duplicate_count || 0}`}
                </div>

                {(bulkPreview.summary?.not_found_count || 0) > 0 ? (
                  <div style={{ border: "1px solid #fde68a", background: "#fffbeb", borderRadius: 8, padding: 10, marginBottom: 8 }}>
                    <div style={{ fontWeight: 900, marginBottom: 4 }}>SKUs não encontrados na base local</div>
                    <div style={{ ...styles.muted, marginBottom: 8 }}>
                      Esses SKUs existem no arquivo de estoque, mas não foram encontrados em Produtos locais. Você pode
                      tentar buscar/importar os cadastros do Tiny para a base local. Isso não altera estoque nem
                      Tiny/Olist.
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={importMissingFromTiny}
                      loading={bulkMissingBusy}
                      disabled={bulkMissingBusy || bulkLoading || bulkCommitting}
                    >
                      {bulkMissingBusy ? "Buscando no Tiny…" : "Buscar/importar não encontrados do Tiny"}
                    </Button>
                    {bulkMissingError ? <div style={{ ...styles.errorBox, marginTop: 8 }}>{bulkMissingError}</div> : null}
                    {bulkMissingResult ? (
                      <div style={{ ...styles.muted, marginTop: 8, fontWeight: 700 }}>
                        {`Importados ${bulkMissingResult.imported_count || 0} · Já existentes ${bulkMissingResult.already_exists_count || 0} · Não encontrados no Tiny ${bulkMissingResult.not_found_count || 0} · Conflitos ${bulkMissingResult.multiple_candidates_count || 0} · Erros ${(bulkMissingResult.errors || []).length}`}
                        {(bulkMissingResult.imported_count || 0) > 0 ? " · Prévia revalidada." : ""}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div style={{ ...styles.listBox, maxHeight: 320 }}>
                  {(bulkPreview.items || []).map((it) => {
                    const badge = STOCK_BULK_STATUS_BADGE[it.status] || STOCK_BULK_STATUS_BADGE.error;
                    const editRow = bulkRows.find((r) => r.line === it.line) || {};
                    return (
                      <div key={it.line} style={{ ...styles.listRow, display: "block" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                          <div style={{ fontWeight: 900 }}>
                            {`#${it.line} · qtd ${formatStock(it.quantity)}`}
                            <span
                              style={{
                                ...styles.badge,
                                marginLeft: 8,
                                background: badge.bg,
                                color: badge.color,
                                borderColor: badge.border,
                              }}
                            >
                              {badge.label}
                            </span>
                          </div>
                          {it.status === "ok" ? (
                            <span style={{ fontWeight: 800 }}>
                              {`Físico ${formatStock(it.current_stock_physical)} → ${formatStock(it.projected_stock_physical)}`}
                            </span>
                          ) : null}
                        </div>
                        <div style={{ fontWeight: 800, marginTop: 2 }}>
                          {it.product_name || "(produto não resolvido)"}
                          {it.resolved_sku ? <span style={{ ...styles.muted, fontWeight: 700 }}>{` · ${it.resolved_sku}`}</span> : null}
                        </div>
                        {it.message ? <div style={{ ...styles.muted, marginTop: 2, color: badge.color }}>{it.message}</div> : null}

                        {/* Correção manual: editar SKU + (se duplicado) escolher produto. */}
                        <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
                          <input
                            style={{ ...styles.input, maxWidth: 240 }}
                            value={editRow.sku ?? it.input_sku ?? ""}
                            onChange={(e) => setBulkRowField(it.line, "sku", e.target.value)}
                            placeholder="SKU"
                            disabled={bulkCommitting}
                          />
                          {it.status === "duplicate_sku" && (it.options || []).length ? (
                            <select
                              style={{ ...styles.input, maxWidth: 320 }}
                              value={editRow.product_id || ""}
                              onChange={(e) => setBulkRowField(it.line, "product_id", e.target.value ? Number(e.target.value) : null)}
                              disabled={bulkCommitting}
                            >
                              <option value="">Selecione o produto…</option>
                              {it.options.map((op) => (
                                <option key={op.product_id} value={op.product_id}>
                                  {`${op.product_name || "(sem nome)"} · ${op.sku || ""} · físico ${formatStock(op.current_stock_physical)}`}
                                </option>
                              ))}
                            </select>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
                  <Button type="button" variant="secondary" onClick={revalidateBulk} loading={bulkLoading} disabled={bulkLoading || bulkCommitting}>
                    {bulkLoading ? "Revalidando…" : "Revalidar prévia"}
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    onClick={commitBulk}
                    loading={bulkCommitting}
                    disabled={
                      bulkLoading ||
                      bulkCommitting ||
                      !bulkPreview.summary?.total_rows ||
                      (bulkPreview.summary?.error_count || 0) > 0 ||
                      (bulkPreview.summary?.not_found_count || 0) > 0 ||
                      (bulkPreview.summary?.duplicate_count || 0) > 0
                    }
                  >
                    {bulkCommitting ? "Importando…" : "Confirmar importação"}
                  </Button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {scOpen ? (
        <div style={styles.modalOverlay} onClick={closeSc}>
          <div style={{ ...styles.modal, width: "min(680px, 96vw)" }} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950 }}>Controle automático local</div>
                <div style={styles.muted}>Estoque local do ERP · {companyLabel(company)} · Não altera Tiny/Olist</div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={closeSc} disabled={scBusy}>
                Fechar
              </Button>
            </div>

            <div style={styles.notice}>
              Ativar esta configuração NÃO reserva nem baixa estoque agora. Ela apenas define o marco para
              pedidos novos em fases futuras.
            </div>

            {scMsg ? (
              <div style={{ ...styles.notice, marginTop: 10, borderColor: "#bbf7d0", background: "rgba(34,197,94,.10)", color: "#166534" }}>{scMsg}</div>
            ) : null}
            {scError ? <div style={{ ...styles.errorBox, marginTop: 10 }}>{scError}</div> : null}

            {scLoading && !scStatus ? (
              <div style={{ ...styles.muted, marginTop: 12 }}>Carregando status…</div>
            ) : scStatus ? (
              <>
                <div style={{ ...styles.statsGrid, gridTemplateColumns: "repeat(2, minmax(0, 1fr))", marginTop: 12 }}>
                  <div style={styles.statCard}>
                    <div style={styles.statLabel}>Situação</div>
                    <div style={styles.statValue}>{scStatus.config?.is_enabled ? "Ativo" : "Inativo"}</div>
                  </div>
                  <div style={styles.statCard}>
                    <div style={styles.statLabel}>Início do controle</div>
                    <div style={{ fontWeight: 800 }}>
                      {scStatus.config?.started_at ? formatDate(scStatus.config.started_at) : "—"}
                    </div>
                  </div>
                </div>

                <div style={{ ...styles.muted, marginTop: 10 }}>
                  {scStatus.last_bulk_import?.reference_id ? (
                    <>
                      Último lote de estoque sugerido: <b>{scStatus.last_bulk_import.reference_id}</b>
                      {scStatus.last_bulk_import.created_at ? ` · ${formatDate(scStatus.last_bulk_import.created_at)}` : ""}
                      {` · ${scStatus.last_bulk_import.movements_count || 0} movimento(s)`}
                    </>
                  ) : (
                    "Nenhum lote de importação em lote encontrado para sugerir como baseline."
                  )}
                </div>

                {scStatus.config?.baseline_reference_id ? (
                  <div style={{ ...styles.muted, marginTop: 4 }}>
                    Baseline atual: <b>{scStatus.config.baseline_reference_id}</b>
                    {scStatus.config.baseline_source ? ` · ${scStatus.config.baseline_source}` : ""}
                  </div>
                ) : null}
                {scStatus.config?.baseline_notes ? (
                  <div style={{ ...styles.muted, marginTop: 4 }}>Obs.: {scStatus.config.baseline_notes}</div>
                ) : null}

                <label style={{ ...styles.fieldLabel, marginTop: 12 }}>
                  Observação (ao ativar)
                  <input
                    style={styles.input}
                    value={scNotes}
                    onChange={(e) => setScNotes(e.target.value)}
                    placeholder="Ex.: Estoque ajustado a partir do PDF Olist exportado às 12:00."
                    disabled={scBusy}
                  />
                </label>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
                  <Button type="button" variant="secondary" onClick={deactivateSc} loading={scBusy} disabled={scBusy || !scStatus.config?.is_enabled}>
                    {scBusy ? "Processando…" : "Desativar"}
                  </Button>
                  <Button type="button" variant="primary" onClick={activateSc} loading={scBusy} disabled={scBusy}>
                    {scBusy ? "Processando…" : "Ativar a partir de agora"}
                  </Button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
