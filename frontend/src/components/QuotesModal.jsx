import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import { openQuotePrintWindow } from "../utils/quotePrint";
import { Button, StatusPill, EmptyState, Spinner } from "../ui";

const OPERATIONS_PAGE_SIZE = 20;
const OPERATIONS_LIGHT_AUTO_REFRESH_MS = 5 * 60 * 1000;

function fmtDate(s) {
  try {
    const d = new Date(s);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const yy = d.getFullYear();
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${dd}/${mm}/${yy} ${hh}:${mi}`;
  } catch {
    return s || "";
  }
}

function money(n) {
  const v = Number(n || 0);
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function formatSyncStatusSummary(source = {}) {
  const checked = Number(source?.checked ?? source?.checked_total ?? source?.total_verificado ?? source?.rounds_completed ?? 0);
  const updated = Number(source?.updated_count ?? source?.updated_total ?? source?.total_atualizado ?? 0);
  const skipped = Number(source?.skipped_count ?? 0);

  if (checked <= 0) {
    return "Sincronização concluída: nenhum pedido pendente para verificar.";
  }
  if (updated <= 0) {
    return `Sincronização concluída: ${checked} verificados, nenhuma mudança.`;
  }

  const unchanged = skipped > 0 ? skipped : Math.max(checked - updated, 0);
  return `Sincronização concluída: ${checked} verificados, ${updated} atualizados${unchanged > 0 ? `, ${unchanged} sem alteração` : ""}.`;
}

function formatPct(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return `${v.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

function safeJson(s) {
  try {
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}

function normalizeInternalStatus(v) {
  const s = String(v || "").trim().toLowerCase();
  if (s === "aprovado") return "Aprovado";
  if (s === "em aberto") return "Em Aberto";
  if (s === "preparando envio") return "Preparando Envio";
  if (s === "pronto para envio") return "Pronto para Envio";
  if (s === "faturado") return "Faturado";
  if (s === "cancelado") return "Cancelado";
  if (s === "aguardando aprovação") return "Aguardando Aprovação";
  return v || "";
}

function normalizeSeparationStatus(v) {
  const s = String(v || "").trim().toLowerCase();
  if (s === "a separar") return "A separar";
  if (s === "separando") return "Separando";
  if (s === "separado") return "Separado";
  if (s === "entregue") return "Entregue";
  return v || "";
}

function getCommercialStatus(item) {
  const internal = normalizeInternalStatus(item?.internal_status);
  const separation = normalizeSeparationStatus(
    item?.separation_status || item?.status_separacao || item?.separationStatus
  );

  if (internal === "Cancelado") return "Cancelado";
  if (internal === "Faturado") return "Faturado";
  if (separation === "Entregue") return "Faturado";
  if (separation === "Separado") return "Pronto para Envio";
  if (separation === "Separando") return "Preparando Envio";

  return internal;
}

const TAB_THEME = {
  draft: {
    accent: "rgba(148,163,184,0.95)",
    soft: "rgba(148,163,184,0.10)",
    border: "rgba(148,163,184,0.35)",
  },
  open: {
    accent: "rgba(234,179,8,0.98)",
    soft: "rgba(234,179,8,0.12)",
    border: "rgba(234,179,8,0.38)",
  },
  approved: {
    accent: "rgba(34,197,94,0.98)",
    soft: "rgba(34,197,94,0.12)",
    border: "rgba(34,197,94,0.38)",
  },
  preparing: {
    accent: "rgba(59,130,246,0.98)",
    soft: "rgba(59,130,246,0.12)",
    border: "rgba(59,130,246,0.38)",
  },
  ready: {
    accent: "rgba(249,115,22,0.98)",
    soft: "rgba(249,115,22,0.12)",
    border: "rgba(249,115,22,0.38)",
  },
  invoiced: {
    accent: "rgba(168,85,247,0.98)",
    soft: "rgba(168,85,247,0.12)",
    border: "rgba(168,85,247,0.38)",
  },
  cancelled: {
    accent: "rgba(239,68,68,0.98)",
    soft: "rgba(239,68,68,0.12)",
    border: "rgba(239,68,68,0.38)",
  },
};

function ActionIconButton({ title, onClick, disabled = false, children }) {
  const { isMobile } = getViewportFlags();
  const dim = isMobile ? 40 : 36;
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      style={{
        width: dim,
        height: dim,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 0,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "var(--surface-2)",
        color: "var(--text)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 0.96,
        boxShadow: "0 8px 18px rgba(0,0,0,0.10)",
        transition: "background .15s ease, border-color .15s ease, transform .06s ease",
      }}
    >
      {children}
    </button>
  );
}

function EyeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.9"/>
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14 4h6v6" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M10 14 20 4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M20 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function ReportIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M9 13h6" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/>
      <path d="M9 17h4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/>
    </svg>
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

function todayLocalISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function shiftDaysLocalISO(baseISO, days) {
  const base = baseISO ? new Date(`${baseISO}T12:00:00`) : new Date();
  if (Number.isNaN(base.getTime())) return "";
  base.setDate(base.getDate() + days);
  const y = base.getFullYear();
  const m = String(base.getMonth() + 1).padStart(2, "0");
  const day = String(base.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function monthStartLocalISO(baseISO) {
  const base = baseISO ? new Date(`${baseISO}T12:00:00`) : new Date();
  if (Number.isNaN(base.getTime())) return "";
  const y = base.getFullYear();
  const m = String(base.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}-01`;
}

function toLocalISODate(value) {
  if (!value) return "";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  } catch {
    return "";
  }
}

export default function QuotesModal({ open, onClose, onOpenPreview, onEditQuote, embedded = false }) {
  const { isMobile, isTablet } = getViewportFlags();
  const isBetaEnv =
    typeof window !== "undefined" &&
    window.location.hostname === "beta-projetotrml.web.app";
  const isVisible = embedded || open;

  const [loading, setLoading] = useState(false);
  const [orderedLoading, setOrderedLoading] = useState(false);
  const [draftItems, setDraftItems] = useState([]);
  const [orderedItems, setOrderedItems] = useState([]);
  const [selectedIds, setSelectedIds] = useState({});
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [datePreset, setDatePreset] = useState("none");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [working, setWorking] = useState(false);
  const [orderResult, setOrderResult] = useState(null);
  const [uiLoading, setUiLoading] = useState(false);
  const [uiLoadingLabel, setUiLoadingLabel] = useState("");
  const [manualSyncRunning, setManualSyncRunning] = useState(false);
  const [syncStatusMessage, setSyncStatusMessage] = useState("");
  const [syncStatusError, setSyncStatusError] = useState("");
  const [autoSyncRunning, setAutoSyncRunning] = useState(false);
  const autoSyncRunningRef = useRef(false);
  const manualSyncRunningRef = useRef(false);
  const syncProgressPollRef = useRef(null);

  const [tab, setTab] = useState("draft");
  const [draftSubtab, setDraftSubtab] = useState("draft");
  const [currentPage, setCurrentPage] = useState(1);
  const [me, setMe] = useState(null);
  const isAdmin = !!me?.is_admin;

  useEffect(() => {
    if (!isVisible) return;
    (async () => {
      try {
        const r = await api.me();
        setMe(r);
      } catch {
        setMe({ is_admin: false });
      }
    })();
  }, [isVisible]);

  // Modal de resultado da criação de pedido: some sozinho após 5 segundos.
  useEffect(() => {
    if (!orderResult) return;
    const timer = setTimeout(() => setOrderResult(null), 5000);
    return () => clearTimeout(timer);
  }, [orderResult]);

  async function runWithLoading(label, fn) {
    setUiLoadingLabel(label || "Carregando...");
    setUiLoading(true);
    try {
      return await fn();
    } finally {
      setUiLoading(false);
      setUiLoadingLabel("");
    }
  }

  async function refreshDraft({ preserveSelection = false } = {}) {
    setError("");
    setLoading(true);
    try {
      const r = await api.listQuotes({ status: "draft", limit: 200, offset: 0 });
      setDraftItems(r.items || []);
      if (!preserveSelection) setSelectedIds({});
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  async function refreshOrdered({ preserveSelection = false } = {}) {
    setError("");
    setOrderedLoading(true);
    try {
      const all = [];
      let offset = 0;
      const limit = 200;
      const maxPages = 20; // teto seguro: até 4000 pedidos ordered

      for (let page = 0; page < maxPages; page += 1) {
        const r = await api.listQuotes({ status: "ordered", limit, offset });
        const items = Array.isArray(r?.items) ? r.items : [];
        all.push(...items);

        if (!r?.has_more || !r?.next_offset || items.length === 0) break;
        offset = r.next_offset;
      }

      setOrderedItems(all);
      if (!preserveSelection) setSelectedIds({});
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setOrderedLoading(false);
    }
  }

  async function refreshCurrent() {
    if (manualSyncRunningRef.current || autoSyncRunningRef.current) return;

    manualSyncRunningRef.current = true;
    setManualSyncRunning(true);
    setError("");
    setSyncStatusError("");
    setSyncStatusMessage("Sincronizando status no Tiny...");

    try {
      const searchText = String(search || "").trim();
      const numericSearch = /^\d{3,}$/.test(searchText);

      if (numericSearch) {
        const one = await api.syncLocalOrderStatus(searchText);
        await refreshDraft({ preserveSelection: true });
        await refreshOrdered({ preserveSelection: true });

        manualSyncRunningRef.current = false;
        setManualSyncRunning(false);

        if (!one?.found) {
          setSyncStatusError("Pedido não encontrado na base local para sincronização.");
          setSyncStatusMessage("");
        } else if (!one?.updated) {
          const to = one?.internal_status || one?.result?.to || "";
          setSyncStatusError("");
          setSyncStatusMessage(to ? `Pedido conferido no Tiny. Status atual: ${to}.` : "Pedido conferido no Tiny, sem alteração de status.");
        } else {
          setSyncStatusError("");
          setSyncStatusMessage("Pedido sincronizado com alteração de status.");
        }
        return;
      }

      const start = await api.startSyncLocalOrderStatuses();
      if (start?.busy) {
        manualSyncRunningRef.current = false;
        setManualSyncRunning(false);
        setSyncStatusError("Já existe uma sincronização de status em andamento.");
        setSyncStatusMessage("");
        return;
      }
      if (!start?.ok) {
        throw new Error("Não foi possível iniciar a sincronização.");
      }

      if (syncProgressPollRef.current) {
        clearInterval(syncProgressPollRef.current);
        syncProgressPollRef.current = null;
      }

      const poll = async () => {
        try {
          const resp = await api.getSyncLocalOrderStatusesProgress();
          const progress = resp?.progress || {};
          const updatedTotal = Number(progress?.updated_total || 0);
          const running = !!progress?.running;
          const lastError = String(progress?.last_error || "");
          const checkedTotal = Number(progress?.checked_total || progress?.rounds_completed || 0);

          await refreshDraft({ preserveSelection: true });
          await refreshOrdered({ preserveSelection: true });

          if (!running) {
            if (syncProgressPollRef.current) {
              clearInterval(syncProgressPollRef.current);
              syncProgressPollRef.current = null;
            }

            manualSyncRunningRef.current = false;
            setManualSyncRunning(false);

            if (lastError) {
              setSyncStatusError("A sincronização terminou com erro. Verifique novamente em alguns segundos.");
              setSyncStatusMessage("");
            } else if (updatedTotal <= 0) {
              setSyncStatusError("");
              setSyncStatusMessage(formatSyncStatusSummary(progress));
            } else {
              setSyncStatusError("");
              setSyncStatusMessage(formatSyncStatusSummary(progress));
            }
          } else if (checkedTotal > 0) {
            setSyncStatusError("");
            setSyncStatusMessage(`Sincronizando status no Tiny... ${checkedTotal} verificados.`);
          }
        } catch (e) {
          if (syncProgressPollRef.current) {
            clearInterval(syncProgressPollRef.current);
            syncProgressPollRef.current = null;
          }
          manualSyncRunningRef.current = false;
          setManualSyncRunning(false);
          setSyncStatusError("Não foi possível acompanhar o progresso da sincronização agora.");
          setSyncStatusMessage("");
        }
      };

      await poll();
      if (manualSyncRunningRef.current) {
        syncProgressPollRef.current = setInterval(poll, 2000);
      }
    } catch (e) {
      manualSyncRunningRef.current = false;
      setManualSyncRunning(false);
      if (e?.status === 409) {
        setSyncStatusError("Já existe uma sincronização de status em andamento.");
      } else {
        setSyncStatusError(e?.message || "Não foi possível sincronizar os status agora.");
      }
      setSyncStatusMessage("");
    }
  }

  async function refreshCurrentAutoLight() {
    if (!isVisible || autoSyncRunningRef.current || manualSyncRunningRef.current || syncProgressPollRef.current) return;
    if (loading || orderedLoading || working) return;
    if (typeof document !== "undefined" && document.hidden) return;

    autoSyncRunningRef.current = true;
    setAutoSyncRunning(true);
    try {
      const result = await api.syncLocalOrderStatuses(5);
      const updated = Number(result?.updated_count ?? result?.total_atualizado ?? 0);

      if (updated > 0) {
        await refreshOrdered({ preserveSelection: true });
      }

      setSyncStatusError("");
      setSyncStatusMessage(formatSyncStatusSummary(result).replace(/^Sincronização concluída:/, "Verificação automática:"));
    } catch (e) {
      if (e?.status === 409) {
        setSyncStatusError("");
        setSyncStatusMessage("Sincronização já estava em andamento.");
      } else {
        setSyncStatusError("Não foi possível atualizar automaticamente agora.");
        setSyncStatusMessage("");
      }
    } finally {
      autoSyncRunningRef.current = false;
      setAutoSyncRunning(false);
    }
  }

  useEffect(() => {
    if (!isVisible) return;
    refreshDraft();
    refreshOrdered();
  }, [isVisible]);

  useEffect(() => {
    if (!isVisible) return undefined;

    // Autoatualização leve: não reintroduzir sync pesado com reload completo de Draft + Ordered.
    const timer = setInterval(() => {
      refreshCurrentAutoLight();
    }, OPERATIONS_LIGHT_AUTO_REFRESH_MS);

    return () => clearInterval(timer);
  }, [isVisible, loading, orderedLoading, working, manualSyncRunning]);

  useEffect(() => {
    if (!isVisible) return undefined;

    return () => {
      if (syncProgressPollRef.current) {
        clearInterval(syncProgressPollRef.current);
        syncProgressPollRef.current = null;
      }
    };
  }, [isVisible]);

  const approvedDraftItems = useMemo(
    () => orderedItems.filter((x) => !!(x?.tiny_order_id || x?.tiny_order_number || x?.status === "ordered")),
    [orderedItems]
  );

  const tabItems = useMemo(() => {
    if (tab === "draft") return draftSubtab === "approved" ? approvedDraftItems : draftItems;
    if (tab === "open") return orderedItems.filter((x) => getCommercialStatus(x) === "Em Aberto");
    if (tab === "approved") return orderedItems.filter((x) => getCommercialStatus(x) === "Aprovado");
    if (tab === "preparing") return orderedItems.filter((x) => getCommercialStatus(x) === "Preparando Envio");
    if (tab === "ready") return orderedItems.filter((x) => getCommercialStatus(x) === "Pronto para Envio");
    if (tab === "invoiced") return orderedItems.filter((x) => getCommercialStatus(x) === "Faturado");
    if (tab === "cancelled") return orderedItems.filter((x) => getCommercialStatus(x) === "Cancelado");
    return [];
  }, [tab, draftSubtab, draftItems, approvedDraftItems, orderedItems]);

  const filtered = useMemo(() => {
    const q = (search || "").trim().toLowerCase();

    return tabItems.filter((x) => {
      const itemDate = toLocalISODate(x?.created_at);

      if (dateFrom && (!itemDate || itemDate < dateFrom)) return false;
      if (dateTo && (!itemDate || itemDate > dateTo)) return false;

      if (!q) return true;

      const c = String(x?.client_snapshot || "");
      const cid = String(x?.client_id || "");
      const num = String(x?.quote_number || "");
      const id = String(x?.quote_id || "");
      const seller = String(x?.seller_name || "");
      const internal = String(getCommercialStatus(x) || "");
      const tinyNum = String(x?.tiny_order_number || "");
      return (
        c.toLowerCase().includes(q) ||
        cid.includes(q) ||
        num.includes(q) ||
        id.includes(q) ||
        seller.toLowerCase().includes(q) ||
        internal.toLowerCase().includes(q) ||
        tinyNum.includes(q)
      );
    });
  }, [tabItems, search, dateFrom, dateTo]);

  function applyDatePreset(preset) {
    const today = todayLocalISO();

    if (preset === "none") {
      setDatePreset("none");
      setDateFrom("");
      setDateTo("");
      return;
    }

    if (preset === "today") {
      setDatePreset("today");
      setDateFrom(today);
      setDateTo(today);
      return;
    }

    if (preset === "last7") {
      setDatePreset("last7");
      setDateFrom(shiftDaysLocalISO(today, -6));
      setDateTo(today);
      return;
    }

    if (preset === "last30") {
      setDatePreset("last30");
      setDateFrom(shiftDaysLocalISO(today, -29));
      setDateTo(today);
      return;
    }

    if (preset === "month") {
      setDatePreset("month");
      setDateFrom(monthStartLocalISO(today));
      setDateTo(today);
      return;
    }

    setDatePreset("custom");
  }

  const totalPages = Math.max(1, Math.ceil(filtered.length / OPERATIONS_PAGE_SIZE));

  useEffect(() => {
    setCurrentPage(1);
  }, [tab, draftSubtab, search, dateFrom, dateTo]);

  useEffect(() => {
    setCurrentPage((prev) => Math.min(Math.max(prev, 1), totalPages));
  }, [totalPages]);

  const paginatedItems = useMemo(() => {
    const safePage = Math.min(Math.max(currentPage, 1), totalPages);
    const start = (safePage - 1) * OPERATIONS_PAGE_SIZE;
    return filtered.slice(start, start + OPERATIONS_PAGE_SIZE);
  }, [filtered, currentPage, totalPages]);

  const pageStart = filtered.length ? (Math.min(Math.max(currentPage, 1), totalPages) - 1) * OPERATIONS_PAGE_SIZE + 1 : 0;
  const pageEnd = filtered.length ? Math.min(pageStart + paginatedItems.length - 1, filtered.length) : 0;

  const selectedList = useMemo(
    () => Object.keys(selectedIds).filter((id) => !!selectedIds[id]),
    [selectedIds]
  );

  useEffect(() => {
    setSelectedIds({});
  }, [tab, draftSubtab]);

  const counts = useMemo(() => {
    const openCount = orderedItems.filter((x) => getCommercialStatus(x) === "Em Aberto").length;
    const approvedCount = orderedItems.filter((x) => getCommercialStatus(x) === "Aprovado").length;
    const preparingCount = orderedItems.filter((x) => getCommercialStatus(x) === "Preparando Envio").length;
    const readyCount = orderedItems.filter((x) => getCommercialStatus(x) === "Pronto para Envio").length;
    const invoicedCount = orderedItems.filter((x) => getCommercialStatus(x) === "Faturado").length;
    const cancelledCount = orderedItems.filter((x) => getCommercialStatus(x) === "Cancelado").length;

    return {
      draft: draftItems.length,
      open: openCount,
      approved: approvedCount,
      preparing: preparingCount,
      ready: readyCount,
      invoiced: invoicedCount,
      cancelled: cancelledCount,
    };
  }, [draftItems, orderedItems]);

  function toggle(id, checked) {
    setSelectedIds((prev) => ({ ...prev, [id]: checked }));
  }

  async function openPdf(quoteId) {
    setError("");
    try {
      if (!quoteId) throw new Error("ID do orçamento não informado.");

      const detail = await api.getQuote(quoteId);
      if (!detail || !detail.quote) {
        throw new Error("Detalhe do orçamento não encontrado.");
      }

      openQuotePrintWindow({
        quote: detail.quote,
        items: Array.isArray(detail.items) ? detail.items : [],
      });
    } catch (e) {
      setError(e?.message || String(e));
    }
  }

  async function openDetails(item) {
    setError("");
    try {
      await runWithLoading("Carregando detalhes...", async () => {
        if (!item) throw new Error("Pedido não informado.");

        if (item?.tiny_order_id) {
          const detail = await api.getSeparationOrder(item.tiny_order_id);
          if (!detail || !detail.order) {
            throw new Error("Detalhe completo do pedido não encontrado.");
          }
          onOpenPreview?.({ kind: "separation", ...detail });
          return;
        }

        const quoteId = item?.quote_id || item;
        if (!quoteId) throw new Error("ID do orçamento não informado.");

        const detail = await api.getQuote(quoteId);
        if (!detail || !detail.quote) {
          throw new Error("Detalhe do orçamento não encontrado.");
        }

        onOpenPreview?.({ kind: "quote", ...detail });
      });
    } catch (e) {
      setError(e?.message || String(e));
    }
  }

  function openTinyOrder(item) {
    const tinyId = item?.tiny_order_id;
    if (!tinyId) {
      setError("ID do pedido Tiny não informado.");
      return;
    }
    const url = `https://erp.olist.com/vendas#edit/${encodeURIComponent(tinyId)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  async function createOrdersSelected() {
    if (isBetaEnv) {
      setError("Criação de pedido no Tiny está bloqueada no ambiente beta.");
      return;
    }

    if (!selectedList.length) return;
    const ok = window.confirm(`Criar pedido no Tiny para ${selectedList.length} orçamento(s)?`);
    if (!ok) return;

    setWorking(true);
    setError("");

    const results = [];
    for (const id of selectedList) {
      try {
        const resp = await api.createOrderFromQuote(id);
        results.push({
          quote_id: id,
          ok: true,
          title: resp?.title || "Pedido criado",
          message: resp?.message || "Pedido criado",
          code: resp?.code || "",
          hash: resp?.hash || "",
        });
      } catch (e) {
        const detail = e?.data?.detail;
        const d = detail && typeof detail === "object" ? detail : null;
        results.push({
          quote_id: id,
          ok: false,
          title: d?.title || "PEDIDO NÃO CRIADO",
          message: d?.message || e?.message || "Erro ao criar pedido.",
          code: d?.code || "",
          hash: d?.hash || "",
        });
      }
    }

    try {
      await refreshDraft();
      await refreshOrdered();
      if (results.some((r) => r.ok)) setTab("open");
    } catch {
      // falha apenas ao recarregar listas: não invalida o resultado já obtido.
    }

    setWorking(false);
    if (results.length) setOrderResult(results);
  }

  async function approveSelectedOrders() {
    if (!isAdmin) return;
    if (!selectedList.length) return;

    const ok = window.confirm(`Aprovar ${selectedList.length} pedido(s) selecionado(s)?`);
    if (!ok) return;

    setWorking(true);
    setError("");

    const approvedIds = [];
    const failedIds = [];

    try {
      for (const id of selectedList) {
        try {
          await api.approveOrder(id);
          approvedIds.push(id);
        } catch {
          failedIds.push(id);
        }
      }

      if (approvedIds.length) {
        setOrderedItems((prev) =>
          prev.map((item) =>
            approvedIds.includes(item?.quote_id)
              ? {
                  ...item,
                  internal_status: "Aprovado",
                }
              : item
          )
        );
      }

      setSelectedIds({});
      setTab("approved");

      if (failedIds.length) {
        setError(
          `Alguns pedidos não puderam ser aprovados. Sucesso: ${approvedIds.length}. Falha: ${failedIds.length}.`
        );
      }
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  async function approveSelectedOrders() {
    if (!isAdmin) return;
    if (!selectedList.length) return;

    const ok = window.confirm(`Aprovar ${selectedList.length} pedido(s) selecionado(s)?`);
    if (!ok) return;

    setWorking(true);
    setError("");

    const approvedIds = [];
    const failedIds = [];

    try {
      for (const id of selectedList) {
        try {
          await api.approveOrder(id);
          approvedIds.push(id);
        } catch {
          failedIds.push(id);
        }
      }

      if (approvedIds.length) {
        setOrderedItems((prev) =>
          prev.map((item) =>
            approvedIds.includes(item?.quote_id)
              ? {
                  ...item,
                  internal_status: "Aprovado",
                }
              : item
          )
        );
      }

      setSelectedIds({});
      setTab("approved");

      if (failedIds.length) {
        setError(
          `Alguns pedidos não puderam ser aprovados. Sucesso: ${approvedIds.length}. Falha: ${failedIds.length}.`
        );
      }
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  async function cancelOrder(quoteId) {
    if (!isAdmin) return;
    const ok = window.confirm("Cancelar este pedido no Tiny e no sistema?");
    if (!ok) return;

    setWorking(true);
    setError("");
    try {
      await api.cancelOrder(quoteId);

      setOrderedItems((prev) =>
        prev.map((item) =>
          item?.quote_id === quoteId
            ? {
                ...item,
                internal_status: "Cancelado",
              }
            : item
        )
      );

      setTab("cancelled");
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  async function approveOrder(quoteId) {
    const ok = window.confirm("Aprovar este pedido?");
    if (!ok) return;

    setWorking(true);
    setError("");
    try {
      await api.approveOrder(quoteId);

      setOrderedItems((prev) =>
        prev.map((item) =>
          item?.quote_id === quoteId
            ? {
                ...item,
                internal_status: "Aprovado",
              }
            : item
        )
      );

      setTab("approved");
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  async function cloneQuote(quoteId) {
    if (!isAdmin) {
      setError("Apenas administradores podem clonar orçamentos.");
      return;
    }

    const ok = window.confirm("Clonar este orçamento?");
    if (!ok) return;

    setWorking(true);
    setError("");
    try {
      await api.cloneQuote(quoteId);
      await refreshDraft();
      setTab("draft");
      setDraftSubtab("draft");
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  async function markAsInvoiced(quoteId) {
    const ok = window.confirm("Marcar este pedido como faturado?");
    if (!ok) return;

    setWorking(true);
    setError("");
    try {
      await api.markInvoiced(quoteId);

      setOrderedItems((prev) =>
        prev.map((item) =>
          item?.quote_id === quoteId
            ? {
                ...item,
                internal_status: "Faturado",
              }
            : item
        )
      );

      setTab("invoiced");
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  async function markSelectedAsInvoiced() {
    if (tab !== "ready") return;
    if (!selectedList.length) return;

    const ok = window.confirm(`Faturar ${selectedList.length} pedido(s) selecionado(s)?`);
    if (!ok) return;

    setWorking(true);
    setError("");

    const invoicedIds = [];
    const failedIds = [];

    try {
      for (const id of selectedList) {
        try {
          await api.markInvoiced(id);
          invoicedIds.push(id);
        } catch {
          failedIds.push(id);
        }
      }

      if (invoicedIds.length) {
        setOrderedItems((prev) =>
          prev.map((item) =>
            invoicedIds.includes(item?.quote_id)
              ? {
                  ...item,
                  internal_status: "Faturado",
                }
              : item
          )
        );
      }

      setSelectedIds({});
      setTab("invoiced");

      if (failedIds.length) {
        setError(
          `Alguns pedidos não puderam ser faturados. Sucesso: ${invoicedIds.length}. Falha: ${failedIds.length}.`
        );
      }
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  async function deleteQuoteOne(quoteId) {
    if (!isAdmin) return;
    const ok = window.confirm("Excluir este orçamento? Essa ação não pode ser desfeita.");
    if (!ok) return;

    setWorking(true);
    setError("");
    try {
      await api.deleteQuote(quoteId);

      setDraftItems((prev) => prev.filter((item) => item?.quote_id !== quoteId));
      setOrderedItems((prev) => prev.filter((item) => item?.quote_id !== quoteId));
      setSelectedIds((prev) => {
        const next = { ...prev };
        delete next[quoteId];
        return next;
      });
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setWorking(false);
    }
  }

  if (!isVisible) return null;

  const loadingCurrent = tab === "draft" ? loading : orderedLoading;
  const draftSubtabCountDraft = draftItems.length;
  const draftSubtabCountApproved = approvedDraftItems.length;
  const showCheckbox =
    (tab === "draft" && draftSubtab === "draft") ||
    (tab === "open" && isAdmin) ||
    tab === "ready";
  const showAdminFinancials = isAdmin && tab === "open";

  const COLS =
    (showCheckbox ? "34px " : "0px ") +
    "126px 110px minmax(240px,1.9fr) minmax(120px,1fr) minmax(120px,1fr) minmax(130px,1fr)" +
    (showAdminFinancials ? " 118px 118px 108px 108px" : " 108px") +
    " 250px" +
    (isAdmin ? " 95px" : "");

  const headerCell = {
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    minWidth: 0,
  };

  const cellEllipsis = {
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    minWidth: 0,
  };

  const topTabsWrap = {
    display: "flex",
    gap: isMobile ? 10 : 12,
    flexWrap: isMobile ? "nowrap" : "wrap",
    alignItems: "flex-end",
    borderBottom: "1px solid var(--border)",
    paddingBottom: isMobile ? 6 : 10,
    overflowX: isMobile ? "auto" : "visible",
    scrollbarWidth: "thin",
  };

  const topTab = {
    background: "rgba(8,16,31,0.34)",
    border: "1px solid rgba(148,163,184,0.18)",
    cursor: "pointer",
    padding: isMobile ? "9px 10px 10px" : "10px 12px 11px",
    minWidth: isMobile ? 98 : 118,
    textAlign: "left",
    color: "var(--muted)",
    borderRadius: 16,
    boxShadow: "0 8px 18px rgba(0,0,0,0.08)",
    flex: "0 0 auto",
  };

  const topTabLabel = {
    fontSize: 13,
    lineHeight: 1.2,
    fontWeight: 900,
    display: "flex",
    alignItems: "center",
    gap: 9,
  };

  const topTabCount = {
    fontSize: 12,
    opacity: 0.9,
    marginTop: 5,
    fontWeight: 800,
  };

  const modalContent = (
    <div
      style={{
        position: embedded ? "relative" : "fixed",
        inset: embedded ? "auto" : 0,
        background: embedded ? "transparent" : "rgba(2,6,23,0.72)",
        display: "flex",
        alignItems: embedded ? "stretch" : "center",
        justifyContent: "center",
        padding: embedded ? 0 : (isMobile ? 0 : 16),
        zIndex: embedded ? "auto" : 9999,
        width: "100%",
        minHeight: embedded ? "100%" : "auto",
      }}
      onMouseDown={(e) => {
        if (!embedded && e.target === e.currentTarget) onClose?.();
      }}
    >
      <div
        style={{
          width: "100%",
          height: embedded
            ? "calc(100vh - 24px)"
            : (isMobile ? "100vh" : "min(820px, 92vh)"),
          background: "var(--card)",
          borderRadius: 24,
          border: embedded ? "none" : (isMobile ? "none" : "1px solid var(--border)"),
          overflow: "hidden",
          display: "grid",
          gridTemplateRows: "auto auto auto minmax(0, 1fr)",
          color: "var(--text)",
          boxShadow: embedded ? "none" : "0 28px 60px rgba(0,0,0,0.30)",
          minHeight: 0,
        }}
      >
        <div
          style={{
            padding: isMobile ? 12 : 16,
            borderBottom: "1px solid var(--border)",
            display: "flex",
            justifyContent: "space-between",
            gap: 10,
            alignItems: isMobile ? "flex-start" : "center",
            flexWrap: "wrap",
            background: "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))",
          }}
        >
          <div>
            <div style={{ fontSize: 18, lineHeight: 1.2, fontWeight: 900, letterSpacing: "-0.03em" }}>Operações</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
              Orçamentos e pedidos em todo o fluxo comercial
              {isAdmin ? " • (Admin: pode excluir)" : ""}
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Button
              variant="secondary"
              onClick={refreshCurrent}
              disabled={loadingCurrent || working || manualSyncRunning || autoSyncRunning}
              loading={manualSyncRunning || autoSyncRunning}
            >
              {manualSyncRunning || autoSyncRunning ? "Atualizando..." : "Atualizar"}
            </Button>

            {syncStatusMessage || syncStatusError ? (
              <div
                aria-live="polite"
                style={{
                  maxWidth: isMobile ? "100%" : 360,
                  padding: "7px 10px",
                  borderRadius: 10,
                  border: `1px solid ${syncStatusError ? "rgba(248,113,113,0.36)" : "rgba(34,197,94,0.28)"}`,
                  background: syncStatusError ? "rgba(248,113,113,0.10)" : "rgba(34,197,94,0.10)",
                  color: syncStatusError ? "#fecaca" : "var(--muted)",
                  fontSize: 12,
                  fontWeight: 800,
                  lineHeight: 1.25,
                }}
              >
                {syncStatusError || syncStatusMessage}
              </div>
            ) : null}

            {tab === "draft" ? (
              (() => {
                const createDisabled = isBetaEnv || !selectedList.length || working;

                return (
                  <Button
                    variant="primary"
                    onClick={createOrdersSelected}
                    disabled={createDisabled}
                    loading={working}
                    title={isBetaEnv ? "Bloqueado no ambiente beta" : ""}
                  >
                    {isBetaEnv ? "Tiny bloqueado no beta" : "Criar pedido(s)"}
                  </Button>
                );
              })()
            ) : null}

            {tab === "open" && isAdmin ? (
              <Button
                variant="primary"
                onClick={approveSelectedOrders}
                disabled={!selectedList.length || working}
                loading={working}
              >
                Aprovar selecionados
              </Button>
            ) : null}

            {tab === "ready" ? (
              <Button
                variant="primary"
                onClick={markSelectedAsInvoiced}
                disabled={!selectedList.length || working}
                loading={working}
              >
                Faturar selecionados
              </Button>
            ) : null}

            {!embedded ? (
              <Button variant="secondary" onClick={onClose}>
                Fechar
              </Button>
            ) : null}
          </div>
        </div>

        <div style={{ padding: isMobile ? "10px 10px 8px" : "14px 16px 10px", borderBottom: "1px solid var(--border)" }}>
          <div style={topTabsWrap}>
            {[
              { key: "draft", label: "Orçamentos", count: counts.draft },
              { key: "open", label: "Em Aberto", count: counts.open },
              { key: "approved", label: "Aprovado", count: counts.approved },
              { key: "preparing", label: "Preparando Envio", count: counts.preparing },
              { key: "ready", label: "Pronto para Envio", count: counts.ready },
              { key: "invoiced", label: "Faturado", count: counts.invoiced },
              { key: "cancelled", label: "Cancelado", count: counts.cancelled },
            ].map((t) => {
              const active = tab === t.key;
              const theme = TAB_THEME[t.key] || TAB_THEME.draft;

              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => {
                    setTab(t.key);
                    setSelectedIds({});
                  }}
                  style={{
                    ...topTab,
                    color: active ? theme.accent : "var(--muted)",
                    background: active ? theme.soft : "transparent",
                    borderColor: active ? theme.border : "transparent",
                    boxShadow: active ? `0 0 0 1px ${theme.border} inset, 0 12px 22px ${theme.soft}` : "0 8px 18px rgba(0,0,0,0.08)",
                  }}
                >
                  <div style={topTabLabel}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 999,
                        background: theme.accent,
                        display: "inline-block",
                        flex: "0 0 auto",
                        boxShadow: active ? `0 0 0 3px ${theme.soft}` : "none",
                      }}
                    />
                    <span>{t.label}</span>
                  </div>
                  <div style={{ ...topTabCount, color: active ? theme.accent : "var(--muted)" }}>
                    {t.count}
                  </div>
                </button>
              );
            })}
          </div>

          {tab === "draft" ? (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8, paddingLeft: isMobile ? 0 : 6 }}>
              <button
                type="button"
                onClick={() => {
                  setDraftSubtab("draft");
                  setSelectedIds({});
                }}
                style={{
                  padding: "6px 10px",
                  fontSize: 12,
                  lineHeight: 1.15,
                  borderRadius: 999,
                  border: "1px solid var(--border)",
                  background: draftSubtab === "draft" ? "rgba(79,140,255,0.12)" : "rgba(8,16,31,0.28)",
                  color: draftSubtab === "draft" ? "var(--text)" : "var(--muted)",
                  cursor: "pointer",
                  fontWeight: 800,
                }}
              >
                Orçamentos ({draftSubtabCountDraft})
              </button>

              <button
                type="button"
                onClick={() => {
                  setDraftSubtab("approved");
                  setSelectedIds({});
                }}
                style={{
                  padding: "6px 10px",
                  fontSize: 12,
                  lineHeight: 1.15,
                  borderRadius: 999,
                  border: "1px solid rgba(34,197,94,0.28)",
                  background: draftSubtab === "approved" ? "rgba(34,197,94,0.12)" : "rgba(8,16,31,0.28)",
                  color: draftSubtab === "approved" ? "rgba(34,197,94,0.98)" : "var(--muted)",
                  cursor: "pointer",
                  fontWeight: 800,
                }}
              >
                Orçamentos Aprovados ({draftSubtabCountApproved})
              </button>
            </div>
          ) : null}
        </div>

        <div style={{ padding: isMobile ? "10px" : "12px 16px", borderBottom: "1px solid var(--border)" }}>
          <div
              style={{
                display: "grid",
                gridTemplateColumns: isMobile ? "1fr" : "minmax(180px, 220px) minmax(170px, 210px) minmax(170px, 210px) minmax(0, 1fr)",
                gap: 10,
                alignItems: "center",
            }}
          >
            <select
              value={datePreset}
              onChange={(e) => applyDatePreset(e.target.value)}
              style={{
                width: "100%",
                height: 42,
                padding: "0 12px",
                borderRadius: 12,
                border: "1px solid var(--border)",
                outline: "none",
                background: "var(--panel)",
                color: "var(--text)",
                boxSizing: "border-box",
              }}
            >
              <option value="none">Sem filtro de data</option>
              <option value="today">Hoje</option>
              <option value="last7">Últimos 7 dias</option>
              <option value="last30">Últimos 30 dias</option>
              <option value="month">Este mês</option>
              <option value="custom">Personalizado</option>
            </select>

            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDatePreset("custom");
                setDateFrom(e.target.value);
              }}
              style={{
                width: "100%",
                height: 42,
                padding: "0 12px",
                borderRadius: 12,
                border: "1px solid var(--border)",
                outline: "none",
                background: "var(--panel)",
                color: "var(--text)",
                boxSizing: "border-box",
              }}
            />

            <input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDatePreset("custom");
                setDateTo(e.target.value);
              }}
              style={{
                width: "100%",
                height: 42,
                padding: "0 12px",
                borderRadius: 12,
                border: "1px solid var(--border)",
                outline: "none",
                background: "var(--panel)",
                color: "var(--text)",
                boxSizing: "border-box",
              }}
            />

            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar por cliente, número, ID, vendedor ou número Tiny..."
              style={{
                width: "100%",
                height: 42,
                padding: "0 12px",
                borderRadius: 12,
                border: "1px solid var(--border)",
                outline: "none",
                background: "var(--panel)",
                color: "var(--text)",
                boxSizing: "border-box",
              }}
            />
          </div>
        </div>

        <div
          key={`ops-table-${tab}-${draftSubtab}`}
          style={{ position: "relative", overflowY: "auto", overflowX: "auto", background: "var(--bg)", minHeight: 0, maxHeight: "100%", scrollbarWidth: "thin", scrollbarGutter: "stable both-edges" }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: COLS,
              gap: 12,
              padding: "12px 16px",
              minWidth: "max-content",
              position: "sticky",
              top: 0,
              background: "var(--panel)",
              borderBottom: "1px solid var(--border)",
              zIndex: 2,
              fontSize: 12,
              color: "var(--muted)",
              fontWeight: 900,
              alignItems: "center",
              boxShadow: "0 10px 18px rgba(0,0,0,0.04)",
            }}
          >
            <div />
            <div style={headerCell}>Criado em</div>
            <div style={headerCell}>NÂº</div>
            <div style={headerCell}>Cliente / Vendedor</div>
            <div style={headerCell}>Envio</div>
            <div style={headerCell}>Frete</div>
            <div style={headerCell}>Status</div>
            {showAdminFinancials ? (
              <>
                <div style={{ ...headerCell, textAlign: "right" }}>Custo total</div>
                <div style={{ ...headerCell, textAlign: "right" }}>Venda produtos</div>
                <div style={{ ...headerCell, textAlign: "right" }}>Lucro</div>
                <div style={{ ...headerCell, textAlign: "right" }}>Markup total</div>
              </>
            ) : (
              <div style={{ ...headerCell, textAlign: "right" }}>Total</div>
            )}
            <div style={{ ...headerCell, textAlign: "right" }}>PDF / Ações</div>
            {isAdmin ? <div style={{ ...headerCell, textAlign: "right" }}>Admin</div> : null}
          </div>

          {error ? <div style={{ padding: 12, color: "var(--danger)" }}>{error}</div> : null}
          {loadingCurrent ? (
            <div style={{ padding: 12, color: "var(--muted)", display: "flex", alignItems: "center", gap: 8 }}>
              <Spinner size={16} /> Carregando...
            </div>
          ) : null}

          {uiLoading ? (
            <div
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(8,15,33,0.12)",
                backdropFilter: "blur(2px)",
                WebkitBackdropFilter: "blur(2px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 9999,
                pointerEvents: "all",
              }}
            >
              <Spinner size={52} label={uiLoadingLabel || "Carregando"} />
            </div>
          ) : null}

          {orderResult ? (() => {
            const list = Array.isArray(orderResult) ? orderResult : [orderResult];
            const allOk = list.length > 0 && list.every((r) => r.ok);
            const anyOk = list.some((r) => r.ok);
            const multi = list.length > 1;
            const headerTitle = !multi
              ? list[0]?.title
              : allOk
                ? "Pedido criado"
                : anyOk
                  ? "Pedidos processados"
                  : "PEDIDO NÃO CRIADO";

            return (
              <div
                onMouseDown={(e) => {
                  if (e.target === e.currentTarget) setOrderResult(null);
                }}
                style={{
                  position: "fixed",
                  inset: 0,
                  background: "rgba(2,6,23,0.72)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  zIndex: 10000,
                  padding: 16,
                }}
              >
                <div
                  role="dialog"
                  aria-live="assertive"
                  style={{
                    width: "100%",
                    maxWidth: 460,
                    maxHeight: "82vh",
                    overflowY: "auto",
                    background: "var(--card)",
                    borderRadius: 18,
                    border: `1px solid ${allOk ? "rgba(34,197,94,0.45)" : "rgba(248,113,113,0.45)"}`,
                    boxShadow: "0 28px 60px rgba(0,0,0,0.35)",
                    color: "var(--text)",
                  }}
                >
                  <div
                    style={{
                      padding: "14px 18px",
                      background: allOk ? "rgba(34,197,94,0.12)" : "rgba(248,113,113,0.12)",
                      borderBottom: "1px solid var(--border)",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 10,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 18,
                        fontWeight: 900,
                        letterSpacing: "-0.02em",
                        color: allOk ? "#22c55e" : "#ef4444",
                      }}
                    >
                      {headerTitle}
                    </div>
                    <button
                      onClick={() => setOrderResult(null)}
                      aria-label="Fechar"
                      style={{
                        border: "none",
                        background: "transparent",
                        color: "var(--muted)",
                        cursor: "pointer",
                        fontSize: 20,
                        fontWeight: 900,
                        lineHeight: 1,
                      }}
                    >
                      ×
                    </button>
                  </div>

                  <div style={{ padding: 18, display: "grid", gap: 12 }}>
                    {list.map((r, i) => (
                      <div
                        key={i}
                        style={{
                          display: "grid",
                          gap: 6,
                          padding: multi ? 12 : 0,
                          borderRadius: 12,
                          border: multi
                            ? `1px solid ${r.ok ? "rgba(34,197,94,0.3)" : "rgba(248,113,113,0.3)"}`
                            : "none",
                          background: multi
                            ? r.ok
                              ? "rgba(34,197,94,0.06)"
                              : "rgba(248,113,113,0.06)"
                            : "transparent",
                        }}
                      >
                        {multi ? (
                          <div style={{ fontWeight: 900, color: r.ok ? "#22c55e" : "#ef4444" }}>
                            {r.title}
                          </div>
                        ) : null}
                        <div style={{ fontSize: 14, lineHeight: 1.4 }}>{r.message}</div>
                        {r.code ? (
                          <div style={{ fontSize: 12, color: "var(--muted)", fontFamily: "monospace" }}>
                            Código:{" "}
                            <strong style={{ color: "var(--text)" }}>{r.code}</strong>
                          </div>
                        ) : null}
                        {r.hash ? (
                          <div
                            style={{
                              fontSize: 11,
                              color: "var(--muted)",
                              fontFamily: "monospace",
                              wordBreak: "break-all",
                            }}
                          >
                            Hash: {r.hash}
                          </div>
                        ) : null}
                      </div>
                    ))}
                    <div style={{ fontSize: 11, color: "var(--muted)", textAlign: "right" }}>
                      Esta janela fecha automaticamente em 5s.
                    </div>
                  </div>
                </div>
              </div>
            );
          })() : null}

          {paginatedItems.map((q, idx) => {
            const totals = (q.totals && typeof q.totals === "object") ? q.totals : (safeJson(q.totals) || {});
            const payload = (q.payload && typeof q.payload === "object") ? q.payload : (safeJson(q.payload) || {});
            const rowTotal = Number(
              q.total ??
              q.total_net ??
              q.valor_total ??
              q.total_amount ??
              q.amount_total ??
              q.net ??
              totals?.net ??
              totals?.total ??
              totals?.items ??
              payload?.total ??
              payload?.total_net ??
              payload?.items_total ??
              q.sale_total_products ??
              q.items_total ??
              0
            );
            const checked = !!selectedIds[q.quote_id];
            const clientSnap = safeJson(q.client_snapshot) || {};
            const clientName = clientSnap?.nome || q.client_name || "";
            const internalStatus = getCommercialStatus(q) || "—";
            const costTotalProducts = Number(q.cost_total_products || 0);
            const saleTotalProducts = Number(q.sale_total_products || 0);
            const profitTotalProducts = Number(q.profit_total_products || 0);
            const markupTotalOrder = q.markup_total_order;

            return (
              <div
                key={`ops-row-${tab}-${draftSubtab}-${q.quote_id || q.tiny_order_id || q.tiny_order_number || "sem-id"}-${idx}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: COLS,
                  gap: 12,
                  padding: "12px 16px",
                  minWidth: "max-content",
                  borderBottom: "1px solid var(--border)",
                  fontSize: 13,
                  alignItems: "center",
                  background: idx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)",
                }}
              >
                <div>
                  {showCheckbox ? (
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => toggle(q.quote_id, e.target.checked)}
                      style={{
                        width: 20,
                        height: 20,
                        cursor: "pointer",
                        accentColor: "var(--primary)",
                        transform: "translateY(1px)",
                        boxShadow: checked ? "0 0 0 3px rgba(59,130,246,0.14)" : "none",
                      }}
                    />
                  ) : null}
                </div>

                <div style={{ fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap" }}>
                  {fmtDate(q.created_at)}
                </div>

                <div
                  style={{ fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}
                  title={`${q.quote_number}${q.tiny_order_number ? ` • Tiny ${q.tiny_order_number}` : ""}`}
                >
                  {q.quote_number}
                  {q.tiny_order_number ? (
                    <div style={{ fontSize: 11, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis" }}>
                      Tiny {q.tiny_order_number}
                    </div>
                  ) : null}
                </div>

                <div
                  style={{ minWidth: 0, maxWidth: 240, overflow: "hidden" }}
                  title={`${clientName || "-"}${q.seller_name ? ` • Vendedor: ${q.seller_name}` : ""}`}
                >
                  <div style={{ ...cellEllipsis, fontWeight: 700, whiteSpace: "nowrap" }}>
                    {clientName || "-"}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--muted)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      minWidth: 0,
                      marginTop: 2,
                    }}
                  >
                    Vendedor: {q.seller_name || "—"}
                  </div>
                </div>

                <div style={cellEllipsis} title={q.shipping_method_name || ""}>
                  {q.shipping_method_name || "-"}
                </div>

                <div style={cellEllipsis} title={q.freight_method_name || ""}>
                  {q.freight_method_name || "-"}
                </div>

                <div style={cellEllipsis} title={internalStatus}>
                  <StatusPill
                    status={
                      tab === "draft" && draftSubtab === "draft"
                        ? "Orçamento"
                        : internalStatus
                    }
                  />
                </div>

                {showAdminFinancials ? (
                  <>
                    <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>{money(costTotalProducts)}</div>
                    <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>{money(saleTotalProducts)}</div>
                    <div
                      style={{
                        textAlign: "right",
                        whiteSpace: "nowrap",
                        color: profitTotalProducts < 0 ? "#f87171" : "var(--text)",
                        fontWeight: 800,
                      }}
                    >
                      {money(profitTotalProducts)}
                    </div>
                    <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>{formatPct(markupTotalOrder)}</div>
                  </>
                ) : (
                  <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {money(rowTotal)}
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "nowrap", alignItems: "center" }}>
                  {tab === "draft" && draftSubtab === "draft" ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => onEditQuote?.(q.quote_id)}
                      disabled={working}
                    >
                      Editar
                    </Button>
                  ) : null}

                  {tab === "draft" && draftSubtab === "approved" && isAdmin ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => cloneQuote(q.quote_id)}
                      disabled={working}
                    >
                      Clonar orçamento
                    </Button>
                  ) : null}

                  {tab === "open" && isAdmin ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => approveOrder(q.quote_id)}
                      disabled={working}
                    >
                      Aprovar Pedido
                    </Button>
                  ) : null}

                  {tab !== "draft" && tab !== "cancelled" && isAdmin ? (
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => cancelOrder(q.quote_id)}
                      disabled={working}
                    >
                      Cancelar
                    </Button>
                  ) : null}

                  {tab === "ready" ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => markAsInvoiced(q.quote_id)}
                      disabled={working}
                    >
                      Faturar
                    </Button>
                  ) : null}

                  {!(tab === "draft" && draftSubtab === "draft") ? (
                    <ActionIconButton
                      title="Ver detalhes"
                      onClick={() => openDetails(q)}
                      disabled={working}
                    >
                      <EyeIcon />
                    </ActionIconButton>
                  ) : null}

                  {!(tab === "draft" && draftSubtab === "draft") ? (
                    <ActionIconButton
                      title={!q.tiny_order_id ? "Pedido ainda sem ID Tiny" : "Abrir pedido no Tiny"}
                      onClick={() => openTinyOrder(q)}
                      disabled={working || !q.tiny_order_id}
                    >
                      <ExternalLinkIcon />
                    </ActionIconButton>
                  ) : null}

                  <ActionIconButton
                    title="Ver PDF"
                    onClick={() => openPdf(q.quote_id)}
                    disabled={working}
                  >
                    <ReportIcon />
                  </ActionIconButton>
                </div>

                {isAdmin ? (
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => deleteQuoteOne(q.quote_id)}
                      disabled={working}
                    >
                      Excluir
                    </Button>
                  </div>
                ) : null}
              </div>
            );
          })}

          {!filtered.length && !loadingCurrent ? (
            <EmptyState
              title="Nenhum item encontrado."
              message="Ajuste os filtros ou a busca para ver resultados."
            />
          ) : null}
        </div>

        {!loadingCurrent ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              padding: "12px 16px",
              marginTop: 12,
              border: "1px solid var(--border)",
              borderRadius: 16,
              background: "rgba(8,16,31,0.30)",
              color: "var(--muted)",
              fontSize: 12,
              flexWrap: "wrap",
            }}
          >
            <div>
              {filtered.length > 0
                ? `Mostrando ${pageStart}-${pageEnd} de ${filtered.length} registros`
                : "Nenhum registro nesta aba/filtro."}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <Button
                variant="secondary"
                size="sm"
                type="button"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
              >
                Anterior
              </Button>

              <span style={{ color: "var(--text)", fontWeight: 900, whiteSpace: "nowrap" }}>
                Página {Math.min(Math.max(currentPage, 1), totalPages)} de {totalPages}
              </span>

              <Button
                variant="secondary"
                size="sm"
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages}
              >
                Próxima
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );

  return embedded ? modalContent : createPortal(modalContent, document.body);
}


