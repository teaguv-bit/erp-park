import { useEffect, useMemo, useRef, useState } from "react";
import { jsPDF } from "jspdf";
import { api } from "../api";
import { Card, PageHeader, Toolbar, Field, Table, Spinner, EmptyState, Button } from "../ui";
import "./ExecutiveDashboard.css";

/* ---- Ícones minimalistas (fill=currentColor, estilo App.jsx) ---- */
function IconMoney() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm.9 15.3v1.2h-1.6v-1.2c-1.3-.2-2.4-.9-2.5-2.4h1.6c.1.7.6 1.1 1.7 1.1 1 0 1.5-.4 1.5-1 0-.5-.3-.8-1.6-1.1-1.9-.4-3-.9-3-2.5 0-1.2.9-2 2.3-2.2V5.5h1.6v1.2c1.3.2 2.1 1 2.2 2.2h-1.6c-.1-.6-.5-1-1.4-1-.9 0-1.4.4-1.4.9 0 .5.4.8 1.7 1 1.9.4 2.9 1 2.9 2.6 0 1.2-.9 2-2.4 2.2z"
      />
    </svg>
  );
}

function IconTicket() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M6 2h12a1 1 0 0 1 1 1v18l-2.5-1.5L14 21l-2-1.5L10 21l-2.5-1.5L5 21V3a1 1 0 0 1 1-1zm2 5v2h8V7H8zm0 4v2h8v-2H8z"
      />
    </svg>
  );
}

function IconTarget() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 3a7 7 0 1 1 0 14 7 7 0 0 1 0-14zm0 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm0 2.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3z"
      />
    </svg>
  );
}

function IconTrophy() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M18 2H6v2H3v3a4 4 0 0 0 4 4c.4 1.5 1.6 2.7 3 3v3H7v2h10v-2h-3v-3c1.4-.3 2.6-1.5 3-3a4 4 0 0 0 4-4V4h-3V2zM5 6h1v3a2 2 0 0 1-1-1.7V6zm14 1.3A2 2 0 0 1 18 9V6h1v1.3z"
      />
    </svg>
  );
}

function IconMedal() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10zm0 2a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM7.8 13.4l-1.8 8.1 6-3 6 3-1.8-8.1a7 7 0 0 1-8.4 0z"
      />
    </svg>
  );
}

/* ---- Formatadores (padrão Home.jsx) ---- */
const currencyFormatter = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});

const integerFormatter = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 0,
});

const DASHBOARD_PERIOD_OPTIONS = [
  { value: "current_month", label: "Mês atual" },
  { value: "previous_month", label: "Mês anterior" },
  { value: "last_7_days", label: "Últimos 7 dias" },
  { value: "today", label: "Hoje" },
  { value: "custom", label: "Personalizado" },
];

const DONUT_COLORS = [
  "var(--accent)",
  "var(--info)",
  "var(--success)",
  "var(--warning)",
  "var(--danger)",
  "var(--neutral)",
];

function normalizeCompanyKey(company) {
  return String(company || "parton").trim().toLowerCase() || "parton";
}

function metricNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function firstName(text) {
  return String(text || "").trim().split(/\s+/)[0] || "";
}

function formatCurrency(value) {
  return currencyFormatter.format(metricNumber(value));
}

function formatInteger(value) {
  return integerFormatter.format(metricNumber(value));
}

function formatPercent(value) {
  return `${metricNumber(value).toLocaleString("pt-BR", {
    maximumFractionDigits: 1,
  })}%`;
}

function formatAxisShort(value) {
  const number = metricNumber(value);
  if (Math.abs(number) >= 1000) return `R$ ${Math.round(number / 1000)}k`;
  return `R$ ${Math.round(number)}`;
}

// Teto "bonito" para o eixo: 1/2/2.5/5 × 10^n imediatamente ≥ ao maior valor.
function niceMax(values) {
  const list = Array.isArray(values) ? values : [];
  const max = Math.max(0, ...list.map(metricNumber));
  if (max <= 0) return 0;
  const exponent = Math.floor(Math.log10(max));
  const base = 10 ** exponent;
  const fraction = max / base;
  let nice;
  if (fraction <= 1) nice = 1;
  else if (fraction <= 2) nice = 2;
  else if (fraction <= 2.5) nice = 2.5;
  else if (fraction <= 5) nice = 5;
  else nice = 10;
  return nice * base;
}

function joinNames(names) {
  const list = names.filter(Boolean);
  if (list.length <= 1) return list[0] || "";
  return `${list.slice(0, -1).join(", ")} e ${list[list.length - 1]}`;
}

// Insights automáticos com null-guards; retorna apenas as caixas com conteúdo real.
function buildInsights(data) {
  const sellers = Array.isArray(data?.sellers) ? data.sellers : [];
  const meta = data?.meta || {};
  const highlights = data?.highlights || {};
  const topSeller = data?.top_seller || null;
  const metaAvailable = meta?.available === true;
  const insights = [];

  const withMeta = sellers.filter((seller) => seller?.has_meta && seller?.meta_attainment_percent != null);

  // success — quem bateu a meta
  const achieved = withMeta.filter((seller) => metricNumber(seller.meta_attainment_percent) >= 100);
  let successText;
  if (!metaAvailable || withMeta.length === 0) {
    successText = "Defina metas mensais em Administração → Metas para acompanhar o atingimento.";
  } else if (achieved.length) {
    const names = achieved.map((seller) => `«${seller.seller_name}» (${formatPercent(seller.meta_attainment_percent)})`);
    successText = `${joinNames(names)} ${achieved.length > 1 ? "superaram suas metas." : "superou sua meta."}`;
  } else {
    successText = "Nenhum vendedor atingiu a meta até agora.";
  }
  insights.push({ tone: "success", title: "Metas atingidas", text: successText });

  // warning — abaixo de 95% da meta (só quando há metas aplicáveis)
  if (metaAvailable) {
    const below = withMeta.filter((seller) => metricNumber(seller.meta_attainment_percent) < 95);
    let warningText;
    if (withMeta.length === 0) {
      warningText = "Sem metas cadastradas para este mês.";
    } else if (below.length === 1) {
      warningText = `«${below[0].seller_name}» está abaixo de 95% da meta (${formatPercent(below[0].meta_attainment_percent)}).`;
    } else if (below.length > 1) {
      const names = below.map((seller) => `«${seller.seller_name}» (${formatPercent(seller.meta_attainment_percent)})`);
      warningText = `${joinNames(names)} estão abaixo de 95% da meta.`;
    } else {
      warningText = "Toda a equipe com meta está acima de 95%.";
    }
    insights.push({ tone: "warning", title: "Atenção necessária", text: warningText });
  }

  // info — concentração de faturamento no topo
  if (topSeller) {
    insights.push({
      tone: "info",
      title: "Concentração de faturamento",
      text: `«${topSeller.seller_name}» responde por ${formatPercent(topSeller.share_percent)} do faturamento do período.`,
    });
  }

  // accent — eficiência (melhor conversão / melhor ticket)
  const bestConversion = highlights?.best_conversion || null;
  const bestTicket = highlights?.best_average_ticket || null;
  if (bestConversion || bestTicket) {
    const parts = [];
    if (bestConversion) parts.push(`Melhor conversão: «${bestConversion.seller_name}» (${formatPercent(bestConversion.conversion_rate)})`);
    if (bestTicket) parts.push(`Melhor ticket: «${bestTicket.seller_name}» (${formatCurrency(bestTicket.average_ticket)})`);
    insights.push({ tone: "accent", title: "Eficiência operacional", text: `${parts.join(" · ")}.` });
  }

  return insights;
}

// Top 6 vendedores por faturamento + agregado "Outros"; inclui o bucket "Sem vendedor".
function buildDonutSlices(sellers) {
  const positives = (Array.isArray(sellers) ? sellers : []).filter((seller) => metricNumber(seller?.amount) > 0);
  const total = positives.reduce((sum, seller) => sum + metricNumber(seller.amount), 0);
  if (total <= 0) return { slices: [], total: 0 };

  const sorted = [...positives].sort((a, b) => metricNumber(b.amount) - metricNumber(a.amount));
  const top = sorted.slice(0, 6);
  const rest = sorted.slice(6);
  const restAmount = rest.reduce((sum, seller) => sum + metricNumber(seller.amount), 0);

  const items = top.map((seller) => ({ label: seller.seller_name, amount: metricNumber(seller.amount) }));
  if (restAmount > 0) items.push({ label: "Outros", amount: restAmount });

  // `offset` = participação acumulada antes desta fatia (para o strokeDashoffset).
  let cumulative = 0;
  const slices = items.map((item, index) => {
    const share = (item.amount / total) * 100;
    const slice = {
      ...item,
      color: DONUT_COLORS[index % DONUT_COLORS.length],
      share,
      offset: cumulative,
    };
    cumulative += share;
    return slice;
  });
  return { slices, total };
}

/* ---- PDF helpers (padrão Catalog.jsx) ---- */
function todayISO() {
  // Data LOCAL (não UTC): evita que o filename saia com o dia seguinte após ~21h BRT.
  const date = new Date();
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function withTimeout(promise, timeoutMs, message) {
  let timeoutId;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(message)), timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => window.clearTimeout(timeoutId));
}

function resolveCaptureBackground(node) {
  try {
    const nodeBg = window.getComputedStyle(node).backgroundColor;
    if (nodeBg && nodeBg !== "transparent" && nodeBg !== "rgba(0, 0, 0, 0)") return nodeBg;
  } catch {
    /* ignora falhas de leitura de estilo */
  }
  try {
    const rootBg = window.getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    if (rootBg) return rootBg;
  } catch {
    /* ignora falhas de leitura de token */
  }
  return "#ffffff";
}

/* ---- Badge de atingimento de meta (modelo visual .ui-pill) ---- */
function metaBadgeTone(seller) {
  if (seller?.meta_attainment_percent == null) return "neutral";
  const number = metricNumber(seller.meta_attainment_percent);
  if (number >= 100) return "success";
  if (number >= 95) return "warning";
  return "danger";
}

function MetaBadge({ seller }) {
  const tone = metaBadgeTone(seller);
  let label;
  if (seller?.meta_attainment_percent != null) {
    label = formatPercent(seller.meta_attainment_percent);
  } else {
    label = seller?.seller_id == null ? "—" : "Sem meta";
  }
  return <span className={`execBadge execBadge--${tone}`}>{label}</span>;
}

/* ---- Gráfico Meta vs Realizado por vendedor (barras CSS agrupadas) ---- */
function MetaVsRealizadoChart({ sellers, metaAvailable }) {
  const withMeta = (Array.isArray(sellers) ? sellers : []).filter((seller) => seller?.has_meta);

  if (!withMeta.length) {
    const message = metaAvailable === false
      ? "Metas não se aplicam a períodos que cruzam meses."
      : "Nenhuma meta definida para este período. Defina em Administração → Metas.";
    return <EmptyState message={message} />;
  }

  const maxValue = niceMax(withMeta.flatMap((seller) => [metricNumber(seller.meta_amount), metricNumber(seller.amount)]));
  const levels = [0, 1, 2, 3, 4].map((step) => ({ ratio: step / 4, value: (maxValue * step) / 4 }));
  const columns = `repeat(${withMeta.length}, minmax(0, 1fr))`;

  return (
    <div className="execMetaChart">
      <div className="execMetaLegend">
        <span className="execMetaLegendItem">
          <span className="execMetaDot execMetaDot--meta" aria-hidden="true" />Meta
        </span>
        <span className="execMetaLegendItem">
          <span className="execMetaDot execMetaDot--real" aria-hidden="true" />Realizado
        </span>
      </div>

      <div className="execMetaPlotRow">
        <div className="execMetaYAxis" aria-hidden="true">
          {levels.map((level) => (
            <span className="execMetaYLabel" key={level.ratio} style={{ bottom: `${level.ratio * 100}%` }}>
              {formatAxisShort(level.value)}
            </span>
          ))}
        </div>

        <div className="execMetaPlot">
          <div className="execMetaGrid" aria-hidden="true">
            {levels.map((level) => (
              <div className="execMetaGridLine" key={level.ratio} style={{ bottom: `${level.ratio * 100}%` }} />
            ))}
          </div>

          <div className="execMetaBars" style={{ gridTemplateColumns: columns }}>
            {withMeta.map((seller) => {
              const metaValue = metricNumber(seller.meta_amount);
              const realValue = metricNumber(seller.amount);
              const metaHeight = maxValue ? Math.min(100, (metaValue / maxValue) * 100) : 0;
              const realHeight = maxValue ? Math.min(100, (realValue / maxValue) * 100) : 0;
              return (
                <div className="execMetaCol" key={seller.seller_id || seller.seller_name}>
                  <div
                    className="execMetaBar execMetaBar--meta"
                    style={{ height: `${metaHeight}%` }}
                    title={`Meta: ${formatCurrency(metaValue)}`}
                  />
                  <div
                    className="execMetaBar execMetaBar--real"
                    style={{ height: `${realValue > 0 ? Math.max(2, realHeight) : 0}%` }}
                    title={`Realizado: ${formatCurrency(realValue)}`}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="execMetaNamesRow">
        <div className="execMetaYAxisSpacer" aria-hidden="true" />
        <div className="execMetaNames" style={{ gridTemplateColumns: columns }}>
          {withMeta.map((seller) => (
            <div className="execMetaName" key={seller.seller_id || seller.seller_name} title={seller.seller_name}>
              {firstName(seller.seller_name)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---- Rosca de participação no faturamento ---- */
function DonutChart({ sellers }) {
  const { slices, total } = useMemo(() => buildDonutSlices(sellers), [sellers]);

  if (!total) {
    return <EmptyState message="Sem faturamento no período para compor a participação." />;
  }

  const radius = 48;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="execDonut">
      <div className="execDonutChart">
        <svg viewBox="0 0 120 120" className="execDonutSvg" role="img" aria-label="Participação no faturamento por vendedor">
          <g transform="rotate(-90 60 60)">
            {slices.map((slice, index) => {
              const length = (slice.share / 100) * circumference;
              const dashArray = `${length} ${circumference - length}`;
              const dashOffset = -((slice.offset / 100) * circumference);
              return (
                <circle
                  key={`${slice.label}-${index}`}
                  cx="60"
                  cy="60"
                  r={radius}
                  fill="none"
                  strokeWidth="16"
                  strokeDasharray={dashArray}
                  strokeDashoffset={dashOffset}
                  style={{ stroke: slice.color }}
                >
                  <title>{`${slice.label}: ${formatCurrency(slice.amount)} · ${formatPercent(slice.share)}`}</title>
                </circle>
              );
            })}
          </g>
        </svg>
        <div className="execDonutCenter">
          <span className="execDonutCenterLabel">Total</span>
          <span className="execDonutCenterValue">{formatCurrency(total)}</span>
        </div>
      </div>

      <div className="execDonutLegend">
        {slices.map((slice, index) => (
          <div className="execDonutLegendItem" key={`${slice.label}-legend-${index}`}>
            <span className="execDonutDot" style={{ background: slice.color }} aria-hidden="true" />
            <span className="execDonutLegendText">{`${slice.label} — ${formatPercent(slice.share)}`}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ExecutiveDashboard() {
  const [activeCompanyKey, setActiveCompanyKey] = useState(() => normalizeCompanyKey(api.getCurrentCompany?.()));
  const [dashboardPeriod, setDashboardPeriod] = useState("current_month");
  const [customDateFrom, setCustomDateFrom] = useState("");
  const [customDateTo, setCustomDateTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  const exportRef = useRef(null);

  useEffect(() => {
    function handleCompanyChanged(event) {
      setActiveCompanyKey(normalizeCompanyKey(event?.detail?.company || api.getCurrentCompany?.() || "parton"));
    }

    window.addEventListener("trml-company-changed", handleCompanyChanged);

    return () => {
      window.removeEventListener("trml-company-changed", handleCompanyChanged);
    };
  }, []);

  const periodParams = useMemo(() => {
    if (!dashboardPeriod) return {};
    if (dashboardPeriod !== "custom") return { period: dashboardPeriod };
    if (!customDateFrom || !customDateTo) return {};
    return { period: "custom", date_from: customDateFrom, date_to: customDateTo };
  }, [dashboardPeriod, customDateFrom, customDateTo]);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        setLoading(true);
        setError("");
        const response = await api.adminSalesPerformance({ company: activeCompanyKey, ...periodParams });
        if (!cancelled) setData(response || null);
      } catch (e) {
        if (!cancelled) {
          setData(null);
          setError(
            e?.status === 403
              ? "Acesso restrito à administração."
              : e?.status === 400
                ? e?.message || "Período inválido. Confira as datas informadas."
                : "Não foi possível carregar os indicadores agora."
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [activeCompanyKey, periodParams]);

  const sellers = useMemo(() => (Array.isArray(data?.sellers) ? data.sellers : []), [data]);
  const totals = data?.totals || {};
  const meta = data?.meta || {};
  const topSeller = data?.top_seller || null;
  const highlights = data?.highlights || {};

  const activeSellers = useMemo(
    () => sellers.filter((seller) => seller?.seller_id != null && metricNumber(seller.amount) > 0).length,
    [sellers]
  );

  const insights = useMemo(() => buildInsights(data), [data]);

  async function handleExportPdf() {
    if (!exportRef.current || exporting) return;
    setExporting(true);
    setExportError("");
    try {
      const node = exportRef.current;
      const [{ default: html2canvas }] = await withTimeout(
        Promise.all([import("html2canvas")]),
        10000,
        "Tempo limite ao carregar o gerador de PDF."
      );
      if (document.fonts?.ready) {
        await withTimeout(document.fonts.ready, 5000, "Tempo limite ao carregar fontes do PDF.").catch(() => undefined);
      }

      const backgroundColor = resolveCaptureBackground(node);
      const canvas = await withTimeout(
        html2canvas(node, {
          scale: 1.5,
          useCORS: true,
          allowTaint: true,
          backgroundColor,
          scrollX: 0,
          scrollY: 0,
          windowWidth: node.scrollWidth || node.offsetWidth,
          windowHeight: node.scrollHeight || node.offsetHeight,
          onclone(clonedDoc) {
            const captureRoot = clonedDoc.querySelector(".execDashCapture");
            if (!captureRoot) return;
            const origEls = Array.from(node.querySelectorAll("*"));
            const cloneEls = Array.from(captureRoot.querySelectorAll("*"));
            if (origEls.length !== cloneEls.length) return;
            const svgTags = new Set(["circle", "path", "text", "rect", "ellipse", "line", "polyline", "polygon", "use", "g", "svg"]);
            const transparent = "rgba(0, 0, 0, 0)";
            origEls.forEach((orig, idx) => {
              const clone = cloneEls[idx];
              const cs = window.getComputedStyle(orig);
              if (svgTags.has(orig.tagName.toLowerCase())) {
                const stroke = cs.stroke;
                const fill = cs.fill;
                if (stroke && stroke !== "none") clone.style.stroke = stroke;
                if (fill && fill !== "none") clone.style.fill = fill;
              }
              const bg = cs.backgroundColor;
              if (bg && bg !== transparent) clone.style.backgroundColor = bg;
              const color = cs.color;
              if (color) clone.style.color = color;
              const borderColor = cs.borderColor;
              if (borderColor) clone.style.borderColor = borderColor;
            });
          },
        }),
        30000,
        "Tempo limite ao gerar o PDF."
      );

      const pdf = new jsPDF("l", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const ratio = canvas.height / canvas.width;

      let renderWidth = pageWidth;
      let renderHeight = pageWidth * ratio;
      if (renderHeight > pageHeight) {
        renderHeight = pageHeight;
        renderWidth = pageHeight / ratio;
      }
      const offsetX = (pageWidth - renderWidth) / 2;
      const offsetY = (pageHeight - renderHeight) / 2;

      const imgData = canvas.toDataURL("image/jpeg", 0.95);
      pdf.addImage(imgData, "JPEG", offsetX, offsetY, renderWidth, renderHeight, undefined, "FAST");

      const companySlug = activeCompanyKey === "park" ? "informatica" : "suprimentos";
      pdf.save(`dashboard-executivo-${companySlug}-${todayISO()}.pdf`);
    } catch (e) {
      console.error("Erro ao exportar PDF do dashboard executivo", e);
      setExportError("Não foi possível gerar o PDF. Tente novamente.");
    } finally {
      setExporting(false);
    }
  }

  const metaKpiValue = totals?.meta_attainment_percent != null ? formatPercent(totals.meta_attainment_percent) : "—";
  const filterLabel = data?.filter?.label || "Filtro de período aplicado";

  return (
    <div className="execDash">
      <PageHeader
        title="Dashboard Executivo de Vendas"
        actions={
          <Button
            variant="secondary"
            loading={exporting}
            disabled={loading || !sellers.length}
            onClick={handleExportPdf}
          >
            Exportar PDF
          </Button>
        }
      />
      <p className="execSubtitle">Visão consolidada da equipe · dados locais do ERP</p>

      <div className="execFilterRow">
        <Toolbar className="execFilterControls">
          <Field label="Período">
            <div style={{ minWidth: 180 }}>
              <select
                value={dashboardPeriod}
                onChange={(event) => setDashboardPeriod(event.target.value || "current_month")}
              >
                {DASHBOARD_PERIOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </Field>

          {dashboardPeriod === "custom" ? (
            <>
              <Field label="Data inicial">
                <div style={{ minWidth: 150 }}>
                  <input
                    type="date"
                    value={customDateFrom}
                    onChange={(event) => setCustomDateFrom(event.target.value)}
                  />
                </div>
              </Field>
              <Field label="Data final">
                <div style={{ minWidth: 150 }}>
                  <input
                    type="date"
                    value={customDateTo}
                    onChange={(event) => setCustomDateTo(event.target.value)}
                  />
                </div>
              </Field>
            </>
          ) : null}
        </Toolbar>
        <div className="execFilterMeta">
          <span>{filterLabel}</span>
          {dashboardPeriod === "custom" && (!customDateFrom || !customDateTo) ? (
            <span>Informe data inicial e final para aplicar o período personalizado.</span>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="execLoading">
          <Spinner size={18} label="Carregando indicadores..." />
          <span>Carregando indicadores...</span>
        </div>
      ) : error ? (
        <EmptyState title="Indicadores indisponíveis" message={error} />
      ) : (
        <div ref={exportRef} className="execDashCapture">
          {sellers.length ? (
            <>
              <section className="execKpiGrid">
                <Card padding="sm" className="execKpiCard">
                  <div className="execKpiRow">
                    <div className="execKpiText">
                      <div className="execKpiLabel">Total Vendido</div>
                      <div className="execKpiValue">{formatCurrency(totals.amount)}</div>
                      <div className="execKpiNote">{formatInteger(activeSellers)} {activeSellers === 1 ? "vendedor ativo" : "vendedores ativos"}</div>
                    </div>
                    <span className="execKpiIcon" aria-hidden="true"><IconMoney /></span>
                  </div>
                </Card>

                <Card padding="sm" className="execKpiCard">
                  <div className="execKpiRow">
                    <div className="execKpiText">
                      <div className="execKpiLabel">Ticket Médio Geral</div>
                      <div className="execKpiValue">{formatCurrency(totals.average_ticket)}</div>
                      <div className="execKpiNote">Base: pedidos do período</div>
                    </div>
                    <span className="execKpiIcon" aria-hidden="true"><IconTicket /></span>
                  </div>
                </Card>

                <Card padding="sm" className="execKpiCard">
                  <div className="execKpiRow">
                    <div className="execKpiText">
                      <div className="execKpiLabel">% Atingimento Meta Geral</div>
                      <div className="execKpiValue">{metaKpiValue}</div>
                      {meta?.available === false ? (
                        <div className="execKpiNote">Metas indisponíveis para períodos que cruzam meses</div>
                      ) : meta?.meta_total ? (
                        <div className="execKpiNote">
                          <span className="execBadge execBadge--accent">Meta: {formatCurrency(meta.meta_total)}</span>
                        </div>
                      ) : (
                        <div className="execKpiNote">Sem metas definidas para o mês</div>
                      )}
                    </div>
                    <span className="execKpiIcon" aria-hidden="true"><IconTarget /></span>
                  </div>
                </Card>

                <Card padding="sm" className="execKpiCard">
                  <div className="execKpiRow">
                    <div className="execKpiText">
                      <div className="execKpiLabel">Top Vendedor(a)</div>
                      <div className="execKpiValue">{topSeller?.seller_name || "—"}</div>
                      <div className="execKpiNote">
                        {topSeller
                          ? `${formatCurrency(topSeller.amount)} · ${formatPercent(topSeller.share_percent)} do total`
                          : "Sem vendas no período"}
                      </div>
                    </div>
                    <span className="execKpiIcon" aria-hidden="true"><IconTrophy /></span>
                  </div>
                </Card>
              </section>

              <section className="execHighlightGrid">
                <Card padding="sm" className="execHighlight execHighlight--success">
                  <div className="execHighlightHead">
                    <span className="execHighlightIcon" aria-hidden="true"><IconMedal /></span>
                    <span className="execHighlightTitle">Melhor Conversão</span>
                  </div>
                  {highlights?.best_conversion ? (
                    <>
                      <div className="execHighlightName">{highlights.best_conversion.seller_name}</div>
                      <div className="execHighlightPrimary">{formatPercent(highlights.best_conversion.conversion_rate)} de taxa de conversão</div>
                      <div className="execHighlightSecondary">
                        {formatInteger(highlights.best_conversion.quotes_created)} orçamentos → {formatInteger(highlights.best_conversion.orders)} vendas
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="execHighlightName">—</div>
                      <div className="execHighlightSecondary">Sem dados no período</div>
                    </>
                  )}
                </Card>

                <Card padding="sm" className="execHighlight execHighlight--accent">
                  <div className="execHighlightHead">
                    <span className="execHighlightIcon" aria-hidden="true"><IconMoney /></span>
                    <span className="execHighlightTitle">Melhor Ticket Médio</span>
                  </div>
                  {highlights?.best_average_ticket ? (
                    <>
                      <div className="execHighlightName">{highlights.best_average_ticket.seller_name}</div>
                      <div className="execHighlightPrimary">{formatCurrency(highlights.best_average_ticket.average_ticket)} por venda</div>
                      <div className="execHighlightSecondary">{formatInteger(highlights.best_average_ticket.orders)} vendas no período</div>
                    </>
                  ) : (
                    <>
                      <div className="execHighlightName">—</div>
                      <div className="execHighlightSecondary">Sem dados no período</div>
                    </>
                  )}
                </Card>

                <Card padding="sm" className="execHighlight execHighlight--warning">
                  <div className="execHighlightHead">
                    <span className="execHighlightIcon" aria-hidden="true"><IconTicket /></span>
                    <span className="execHighlightTitle">Maior Volume de Orçamentos</span>
                  </div>
                  {highlights?.most_quotes ? (
                    <>
                      <div className="execHighlightName">{highlights.most_quotes.seller_name}</div>
                      <div className="execHighlightPrimary">{formatInteger(highlights.most_quotes.quotes_created)} orçamentos emitidos</div>
                      <div className="execHighlightSecondary">{formatInteger(highlights.most_quotes.orders)} viraram vendas</div>
                    </>
                  ) : (
                    <>
                      <div className="execHighlightName">—</div>
                      <div className="execHighlightSecondary">Sem dados no período</div>
                    </>
                  )}
                </Card>
              </section>

              <section className="execChartsRow">
                <Card title="Meta vs Realizado por Vendedor" padding="md" className="execChartCard">
                  <MetaVsRealizadoChart sellers={sellers} metaAvailable={meta?.available} />
                </Card>
                <Card title="Participação no Faturamento" padding="md" className="execChartCard">
                  <DonutChart sellers={sellers} />
                </Card>
              </section>

              <Card
                title="Ranking de Vendedores"
                padding="md"
                className="execRankingCard"
                actions={<span className="execRankingHint">Ordenado por faturamento</span>}
              >
                <Table zebra className="execTable">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Vendedor</th>
                      <th data-numeric>Vendas</th>
                      <th data-numeric>Meta</th>
                      <th className="execCellCenter">% Meta</th>
                      <th data-numeric className="execHideSm">Orçamentos</th>
                      <th data-numeric className="execHideMd">Conversão</th>
                      <th data-numeric className="execHideMd">Ticket Médio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sellers.map((seller, index) => (
                      <tr key={seller.seller_id || `sem-vendedor-${index}`}>
                        <td className="execRankNum">{index + 1}</td>
                        <td className="execRankName">{seller.seller_name}</td>
                        <td data-numeric className="execRankSales">{formatCurrency(seller.amount)}</td>
                        <td data-numeric>
                          {seller.meta_amount != null ? formatCurrency(seller.meta_amount) : <span className="execMuted">Sem meta</span>}
                        </td>
                        <td className="execCellCenter"><MetaBadge seller={seller} /></td>
                        <td data-numeric className="execHideSm">{formatInteger(seller.quotes_created)}</td>
                        <td data-numeric className="execHideMd">{formatPercent(seller.conversion_rate)}</td>
                        <td data-numeric className="execHideMd">{formatCurrency(seller.average_ticket)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>

              <Card title="Insights Automáticos" padding="md" className="execInsightsCard">
                {insights.length ? (
                  <div className="execInsightGrid">
                    {insights.map((insight, index) => (
                      <div className={`execInsight execInsight--${insight.tone}`} key={`${insight.tone}-${index}`}>
                        <div className="execInsightTitle">{insight.title}</div>
                        <div className="execInsightText">{insight.text}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState message="Sem insights para o período selecionado." />
                )}
              </Card>
            </>
          ) : (
            <EmptyState message="Sem dados no período selecionado." />
          )}
        </div>
      )}

      {exportError ? <div className="execExportError">{exportError}</div> : null}
    </div>
  );
}
