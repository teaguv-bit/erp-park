import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { withGlobalLoading } from "../utils/globalLoading";
import { Card, PageHeader, Toolbar, Field, Spinner, EmptyState, Button } from "../ui";

function firstName(text) {
  return String(text || "").trim().split(/\s+/)[0] || "Vendedor(a)";
}

function companyLabel(company) {
  const normalized = String(company || "").trim().toLowerCase();
  if (normalized === "park") return "Informática";
  return "Suprimentos";
}

function roleLabel(role, isAdmin) {
  if (isAdmin) return "Administração";
  const normalized = String(role || "").trim().toLowerCase();
  if (normalized === "seller") return "Vendas";
  if (normalized === "expedition" || normalized === "separacao") return "Separação";
  return normalized || "Operacional";
}

function sourceLabel(source) {
  const value = String(source || "").trim();
  if (!value) return "API local";
  if (value === "local_postgresql") return "PostgreSQL local";
  return value;
}

const currencyFormatter = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});

const integerFormatter = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 0,
});

function normalizeCompanyKey(company) {
  return String(company || "parton").trim().toLowerCase() || "parton";
}

function metricNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
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

function metricCard(label, value, note = "") {
  return { label, value, note };
}

const DASHBOARD_PERIOD_OPTIONS = [
  { value: "current_month", label: "Mês atual" },
  { value: "previous_month", label: "Mês anterior" },
  { value: "last_7_days", label: "Últimos 7 dias" },
  { value: "today", label: "Hoje" },
  { value: "custom", label: "Personalizado" },
];

function DashboardMetricCard({ card }) {
  return (
    <Card padding="sm" className="homeDashboardMetricCard">
      <div className="homeMetricLabel">{card.label}</div>
      <div className="homeMetricValue">{card.value}</div>
      {card.note ? <div className="homeMetricNote">{card.note}</div> : null}
    </Card>
  );
}

function Last7DaysChart({ items, onDayClick }) {
  const safeItems = Array.isArray(items) ? items : [];
  const maxAmount = Math.max(0, ...safeItems.map((item) => metricNumber(item?.amount)));

  return (
    <Card padding="md">
      <div className="homeChartHeader">
        <div>
          <div className="homeSectionTitle">Últimos 7 dias</div>
          <div className="homeChartSubtitle">Valor vendido por dia · Clique em um dia para ver horários</div>
        </div>
      </div>

      {safeItems.length ? (
        <div className="homeBarChart" aria-label="Valor vendido nos últimos 7 dias">
          {safeItems.map((item) => {
            const amount = metricNumber(item?.amount);
            const height = maxAmount ? Math.max(8, Math.round((amount / maxAmount) * 100)) : 0;
            return (
              <button
                type="button"
                className="homeBarItem homeBarItem--clickable"
                key={item?.date || item?.label}
                onClick={() => onDayClick?.(item)}
                title={`Ver detalhes por hora de ${item?.label || ""}`}
                aria-label={`Ver detalhes por hora de ${item?.label || ""}`}
              >
                <div className="homeBarValue">{formatCurrency(amount)}</div>
                <div className="homeBarTrack">
                  <div
                    className="homeBarFill"
                    style={{ "--home-bar-height": `${height}%` }}
                    title={`${item?.label || ""}: ${formatCurrency(amount)}`}
                  />
                </div>
                <div className="homeBarLabel">{item?.label || "-"}</div>
                <div className="homeBarMeta">{formatInteger(item?.orders)} ped.</div>
              </button>
            );
          })}
        </div>
      ) : (
        <EmptyState message="Sem série disponível para o período." />
      )}
    </Card>
  );
}

function StatusFunnel({ data }) {
  const rows = [
    ["draft", "Draft"],
    ["open", "Em aberto"],
    ["approved", "Aprovado"],
    ["ordered", "Pedido"],
    ["invoiced", "Faturado"],
    ["cancelled", "Cancelado"],
  ].map(([key, label]) => ({ key, label, value: metricNumber(data?.[key]) }));
  const maxValue = Math.max(0, ...rows.map((row) => row.value));

  return (
    <Card padding="md">
      <div className="homeChartHeader">
        <div>
          <div className="homeSectionTitle">Funil comercial</div>
          <div className="homeChartSubtitle">Distribuição local por status</div>
        </div>
      </div>

      <div className="homeFunnelList">
        {rows.map((row) => {
          const width = maxValue ? Math.max(6, Math.round((row.value / maxValue) * 100)) : 0;
          return (
            <div className="homeFunnelRow" key={row.key}>
              <div className="homeFunnelLabel">{row.label}</div>
              <div className="homeFunnelTrack">
                <div
                  className={`homeFunnelFill homeFunnelFill--${row.key}`}
                  style={{ "--home-funnel-width": `${width}%` }}
                />
              </div>
              <div className="homeFunnelValue">{formatInteger(row.value)}</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function ConversionPanel({ cards }) {
  return (
    <Card padding="md">
      <div className="homeDashboardGroupHeader">
        <div>
          <div className="homeSectionTitle">Conversão</div>
          <div className="homeChartSubtitle">Percentuais mensais retornados pelo backend</div>
        </div>
      </div>

      <div className="homeConversionGrid">
        {cards.map((card) => (
          <Card padding="sm" className="homeConversionCard" key={card.label}>
            <div className="homeMetricLabel">{card.label}</div>
            <div className="homeMetricValue">{card.value}</div>
            {card.note ? <div className="homeMetricNote">{card.note}</div> : null}
            <div className="homeProgressTrack" aria-hidden="true">
              <div
                className="homeProgressFill"
                style={{ "--home-progress-width": `${Math.min(100, metricNumber(card.raw))}%` }}
              />
            </div>
          </Card>
        ))}
      </div>
    </Card>
  );
}

function PeriodSummary({ rows }) {
  return (
    <Card padding="md" className="homePeriodSummary">
      <div className="homePeriodGrid" role="table" aria-label="Resumo por período">
        <div className="homePeriodCell homePeriodCell--head" role="columnheader">Indicador</div>
        <div className="homePeriodCell homePeriodCell--head" role="columnheader">Hoje</div>
        <div className="homePeriodCell homePeriodCell--head" role="columnheader">Semana</div>
        <div className="homePeriodCell homePeriodCell--head" role="columnheader">Mês</div>
        {rows.map((row) => (
          <div className="homePeriodRow" role="row" key={row.label}>
            <div className="homePeriodCell homePeriodCell--label" role="rowheader">{row.label}</div>
            <div className="homePeriodCell" role="cell" data-numeric>{row.today}</div>
            <div className="homePeriodCell" role="cell" data-numeric>{row.week}</div>
            <div className="homePeriodCell" role="cell" data-numeric>{row.month}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function AdminResultPanel({ result }) {
  const missingCostItems = metricNumber(result?.missing_cost_items_month);

  return (
    <Card padding="md" className="homeResultPanel">
      <div className="homeDashboardGroupHeader">
        <div>
          <div className="homeSectionTitle">Resultado bruto estimado</div>
          <div className="homeChartSubtitle">Visível somente para administração</div>
        </div>
      </div>

      <div className="homeResultGrid">
        <DashboardMetricCard card={metricCard("Valor vendido no mês", formatCurrency(result?.items_sales_amount_month ?? result?.sales_amount_month), "Itens vendidos")} />
        <DashboardMetricCard card={metricCard("Custo total mensal", formatCurrency(result?.cost_total_month), "Custo estimado")} />
        <DashboardMetricCard card={metricCard("Resultado bruto do mês", formatCurrency(result?.gross_result_month), "Antes de deduções")} />
        <DashboardMetricCard card={metricCard("Margem bruta estimada", formatPercent(result?.gross_margin_month), "Cobertura: " + formatPercent(result?.cost_coverage_percent_month))} />
      </div>

      <div className="homeResultNotes">
        <div>Valor bruto estimado, sem descontar taxas, impostos, fretes, comissões e outras despesas.</div>
        <div>Não representa lucro líquido.</div>
        {missingCostItems > 0 ? (
          <div className="homeResultWarning">Há itens sem custo cadastrado; o resultado pode estar parcial.</div>
        ) : null}
      </div>
    </Card>
  );
}

function SelectedPeriodPanel({ selectedPeriod, isAdmin }) {
  if (!selectedPeriod) return null;

  const conversion = selectedPeriod?.conversion || {};
  const result = isAdmin && selectedPeriod?.result?.visible === true ? selectedPeriod.result : null;
  const cards = [
    metricCard("Vendas no período", formatInteger(selectedPeriod?.orders), "Pedidos locais"),
    metricCard("Valor vendido", formatCurrency(selectedPeriod?.amount), "Total filtrado"),
    metricCard("Ticket médio", formatCurrency(selectedPeriod?.average_ticket), "Valor / vendas"),
    metricCard("Orçamentos criados", formatInteger(selectedPeriod?.quotes_created), "Criados no período"),
    metricCard("Conversão em pedido", formatPercent(conversion?.quote_to_order_rate), "Pedidos / orçamentos"),
    metricCard("Cancelamento", formatPercent(conversion?.cancel_rate), "Cancelados / vendas"),
  ];

  if (result) {
    cards.push(
      metricCard("Custo no período", formatCurrency(result?.cost_total), "Admin"),
      metricCard("Resultado bruto estimado", formatCurrency(result?.gross_result), "Admin"),
      metricCard("Margem bruta", formatPercent(result?.gross_margin), "Admin"),
      metricCard("Cobertura de custo", formatPercent(result?.cost_coverage_percent), "Admin")
    );
  }

  return (
    <Card padding="md" className="homeSelectedPeriodPanel">
      <div className="homeDashboardGroupHeader">
        <div>
          <div className="homeSectionTitle">Período selecionado</div>
          <div className="homeChartSubtitle">{selectedPeriod?.filter?.label || "Filtro aplicado"}</div>
        </div>
      </div>

      <div className="homeMetricGrid homeDashboardMetricGrid homeSelectedPeriodGrid">
        {cards.map((card) => (
          <DashboardMetricCard card={card} key={card.label} />
        ))}
      </div>
    </Card>
  );
}

function HourlyDetailModal({ day, data, loading, error, onClose }) {
  const hours = Array.isArray(data?.hours) ? data.hours : [];
  const maxAmount = Math.max(0, ...hours.map((item) => metricNumber(item?.amount)));
  const peakHour = data?.summary?.peak_hour || null;
  const hasSales = metricNumber(data?.summary?.orders) > 0 || metricNumber(data?.summary?.amount) > 0;

  return (
    <div className="homeHourlyOverlay" onClick={onClose} role="presentation">
      <section className="homeHourlyModal" role="dialog" aria-modal="true" aria-label="Detalhe por hora" onClick={(event) => event.stopPropagation()}>
        <div className="homeHourlyHeader">
          <div>
            <div className="homeSectionTitle">Detalhe por hora — {day?.label || data?.date || "-"}</div>
            <div className="homeChartSubtitle">Vendas locais por horário, com base na data do pedido Tiny.</div>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose} aria-label="Fechar detalhe por hora">×</Button>
        </div>

        {loading ? (
          <div className="homeEmptyState" style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "var(--space-2)" }}>
            <Spinner size={18} label="Carregando detalhe por hora..." />
            <span>Carregando detalhe por hora...</span>
          </div>
        ) : null}
        {error ? <EmptyState title="Não foi possível carregar" message={error} /> : null}

        {!loading && !error && data ? (
          <>
            <div className="homeHourlySummary">
              <DashboardMetricCard card={metricCard("Total vendido no dia", formatCurrency(data?.summary?.amount), "Dados locais")} />
              <DashboardMetricCard card={metricCard("Pedidos no dia", formatInteger(data?.summary?.orders), "Vendas geradas")} />
              <DashboardMetricCard card={metricCard("Ticket médio", formatCurrency(data?.summary?.average_ticket), "Média do dia")} />
              <DashboardMetricCard card={metricCard("Horário de pico", peakHour ? `${peakHour.label}` : "-", peakHour ? `${formatCurrency(peakHour.amount)} · ${formatInteger(peakHour.orders)} ped.` : "Sem vendas")} />
            </div>

            {hasSales ? null : <EmptyState message="Sem vendas neste dia." />}

            <div className="homeHourlyChart" aria-label="Vendas por hora">
              {hours.map((item) => {
                const amount = metricNumber(item?.amount);
                const height = maxAmount ? Math.max(6, Math.round((amount / maxAmount) * 100)) : 0;
                const isPeak = peakHour && item?.hour === peakHour.hour;
                return (
                  <div className={`homeHourlyBarItem${isPeak ? " homeHourlyBarItem--peak" : ""}`} key={item?.hour}>
                    <div className="homeHourlyBarValue">{amount ? formatCurrency(amount) : "-"}</div>
                    <div className="homeHourlyBarTrack" title={`${item?.label}: ${formatCurrency(amount)} · ${formatInteger(item?.orders)} pedidos`}>
                      <div className="homeHourlyBarFill" style={{ "--home-hourly-height": `${height}%` }} />
                    </div>
                    <div className="homeHourlyBarLabel">{item?.label}</div>
                    <div className="homeHourlyBarMeta">{formatInteger(item?.orders)}</div>
                  </div>
                );
              })}
            </div>

            <div className="homeResultNotes">
              {peakHour ? <div>Pico: {peakHour.label} — {formatCurrency(peakHour.amount)} — {formatInteger(peakHour.orders)} pedidos.</div> : null}
              <div>Fonte: dados locais do ERP.</div>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}

export default function Home({ user, profile }) {
  const [ctx, setCtx] = useState(null);
  const [error, setError] = useState("");
  const [currentCompany, setCurrentCompany] = useState(() => normalizeCompanyKey(api.getCurrentCompany?.() || "parton"));
  const [dashboard, setDashboard] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState("");
  const [selectedDashboardSellerId, setSelectedDashboardSellerId] = useState("all");
  const [dashboardSellerOptions, setDashboardSellerOptions] = useState([]);
  const [dashboardSellerError, setDashboardSellerError] = useState("");
  const [dashboardPeriod, setDashboardPeriod] = useState("current_month");
  const [periodDateFrom, setPeriodDateFrom] = useState("");
  const [periodDateTo, setPeriodDateTo] = useState("");
  const [selectedHourlyDay, setSelectedHourlyDay] = useState(null);
  const [hourlyLoading, setHourlyLoading] = useState(false);
  const [hourlyError, setHourlyError] = useState("");
  const [hourlyData, setHourlyData] = useState(null);
  const [isHourlyModalOpen, setIsHourlyModalOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        setError("");
        const r = await withGlobalLoading("Carregando início...", () => api.sellerContext());
        if (!cancelled) {
          setCtx(r);
          setCurrentCompany(normalizeCompanyKey(r?.company_key || r?.company || api.getCurrentCompany?.() || "parton"));
        }
      } catch (e) {
        if (!cancelled) setError(e?.message || "Erro ao carregar a página inicial.");
      }
    }

    function handleCompanyChanged(event) {
      setCurrentCompany(normalizeCompanyKey(event?.detail?.company || api.getCurrentCompany?.() || "parton"));
      setSelectedDashboardSellerId("all");
      run();
    }

    run();
    window.addEventListener("trml-company-changed", handleCompanyChanged);

    return () => {
      cancelled = true;
      window.removeEventListener("trml-company-changed", handleCompanyChanged);
    };
  }, []);

  const displayName = useMemo(() => {
    return firstName(user?.displayName || profile?.email || user?.email || "");
  }, [user, profile]);

  const sellerNames = useMemo(() => {
    const links = ctx?.seller_links && typeof ctx.seller_links === "object" ? ctx.seller_links : {};
    return Object.values(links)
      .map((link) => link?.tiny_seller_name)
      .filter(Boolean);
  }, [ctx]);

  const activeCompanyKey = useMemo(() => {
    return normalizeCompanyKey(currentCompany || ctx?.company_key || ctx?.company || "parton");
  }, [ctx, currentCompany]);

  const isAdmin = useMemo(() => {
    return Boolean(ctx?.is_admin) || Boolean(profile?.is_admin) || String(ctx?.role || profile?.role || "").trim().toLowerCase() === "admin";
  }, [ctx, profile]);

  const dashboardPeriodParams = useMemo(() => {
    if (!dashboardPeriod) return {};
    if (dashboardPeriod !== "custom") return { period: dashboardPeriod };
    if (!periodDateFrom || !periodDateTo) return {};
    return { period: "custom", date_from: periodDateFrom, date_to: periodDateTo };
  }, [dashboardPeriod, periodDateFrom, periodDateTo]);

  useEffect(() => {
    setSelectedDashboardSellerId("all");
  }, [activeCompanyKey]);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      if (!isAdmin) {
        setDashboardSellerOptions([]);
        setDashboardSellerError("");
        return;
      }

      try {
        setDashboardSellerError("");
        const response = await api.adminListUsers();
        if (cancelled) return;

        const map = new Map();
        const users = Array.isArray(response?.items) ? response.items : Array.isArray(response?.users) ? response.users : [];
        for (const item of users) {
          const links = item?.seller_links && typeof item.seller_links === "object" ? item.seller_links : {};
          const link = links?.[activeCompanyKey];
          const id = String(link?.tiny_seller_id || "").trim();
          const name = String(link?.tiny_seller_name || "").trim();
          if (id && name && !map.has(id)) {
            map.set(id, { seller_id: id, seller_name: name });
          }
        }

        const options = Array.from(map.values()).sort((a, b) => a.seller_name.localeCompare(b.seller_name, "pt-BR"));
        setDashboardSellerOptions(options);
        setSelectedDashboardSellerId((current) => (
          current !== "all" && !options.some((option) => option.seller_id === current) ? "all" : current
        ));
      } catch (e) {
        if (!cancelled) {
          setDashboardSellerOptions([]);
          setDashboardSellerError("Não foi possível carregar os vendedores. Exibindo visão geral.");
          setSelectedDashboardSellerId("all");
        }
      }
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [activeCompanyKey, isAdmin]);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        setDashboardLoading(true);
        setDashboardError("");
        const sellerId = isAdmin && selectedDashboardSellerId !== "all" ? selectedDashboardSellerId : "";
        const r = await api.homeDashboard({ company: activeCompanyKey, seller_id: sellerId, ...dashboardPeriodParams });
        if (!cancelled) setDashboard(r || {});
      } catch (e) {
        if (!cancelled) {
          if (e?.status !== 400) setDashboard(null);
          setDashboardError(
            e?.status === 403
              ? "Usuário sem vendedor Tiny vinculado para esta empresa."
              : e?.status === 400
                ? e?.message || "Período inválido. Confira as datas informadas."
              : "Não foi possível carregar as métricas agora."
          );
        }
      } finally {
        if (!cancelled) setDashboardLoading(false);
      }
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [activeCompanyKey, dashboardPeriodParams, isAdmin, selectedDashboardSellerId]);

  const activeCompany = useMemo(() => {
    return companyLabel(activeCompanyKey);
  }, [activeCompanyKey]);

  const activeSellerLink = useMemo(() => {
    const links = ctx?.seller_links && typeof ctx.seller_links === "object" ? ctx.seller_links : {};
    return links?.[activeCompanyKey] || null;
  }, [activeCompanyKey, ctx]);

  const roleText = useMemo(() => {
    return roleLabel(ctx?.role || profile?.role, !!ctx?.is_admin || !!profile?.is_admin);
  }, [ctx, profile]);

  const systemSource = useMemo(() => {
    return sourceLabel(ctx?.mapping_source);
  }, [ctx]);

  const statusCards = useMemo(() => [
    {
      label: "Empresa ativa",
      value: activeCompany,
      note: "Contexto usado nas consultas do ERP",
    },
    {
      label: "Perfil de acesso",
      value: roleText,
      note: "Permissões preservadas pelo login atual",
    },
    {
      label: "Vendedores vinculados",
      value: String(sellerNames.length),
      note: sellerNames.length ? "Mapeamento disponível" : "Sem vínculo informado",
    },
    {
      label: "Base operacional",
      value: systemSource,
      note: "Ambiente local conectado",
    },
  ].map((card) => {
    if (card.label !== "Vendedores vinculados" || isAdmin) return card;
    return {
      label: "Vendedor vinculado",
      value: activeSellerLink?.tiny_seller_name || "Sem vínculo",
      note: activeSellerLink?.tiny_seller_name ? `Definido para ${activeCompany}` : "Procure um administrador",
    };
  }).filter((card) => isAdmin || card.label !== "Base operacional"), [activeCompany, activeSellerLink, isAdmin, roleText, sellerNames.length, systemSource]);

  const dashboardLayout = useMemo(() => {
    const periods = dashboard?.periods || {};
    const today = periods?.today || {};
    const week = periods?.week || {};
    const month = periods?.month || {};
    const orders = dashboard?.orders || {};
    const result = isAdmin && dashboard?.result?.visible === true ? dashboard.result : null;

    const summaryCards = [
      metricCard("Vendas hoje", formatInteger(today?.orders), "Pedidos no dia"),
      metricCard("Vendas na semana", formatInteger(week?.orders), "Pedidos na semana"),
      metricCard("Vendas no mês", formatInteger(month?.orders), "Pedidos no mês"),
      metricCard("Valor vendido no mês", formatCurrency(month?.amount), "Total do mês"),
    ];

    if (result) {
      summaryCards.push(
        metricCard("Custo total mensal", formatCurrency(result?.cost_total_month), "Admin"),
        metricCard("Resultado bruto estimado", formatCurrency(result?.gross_result_month), "Admin")
      );
    }

    return {
      summaryCards,
      periodRows: [
        { label: "Vendas", today: formatInteger(today?.orders), week: formatInteger(week?.orders), month: formatInteger(month?.orders) },
        { label: "Valor vendido", today: formatCurrency(today?.amount), week: formatCurrency(week?.amount), month: formatCurrency(month?.amount) },
        { label: "Ticket médio", today: formatCurrency(today?.average_ticket), week: formatCurrency(week?.average_ticket), month: formatCurrency(month?.average_ticket) },
        { label: "Orçamentos criados", today: formatInteger(today?.quotes_created), week: formatInteger(week?.quotes_created), month: formatInteger(month?.quotes_created) },
        { label: "Orçamentos aprovados", today: formatInteger(today?.quotes_approved), week: formatInteger(week?.quotes_approved), month: formatInteger(month?.quotes_approved) },
      ],
      bottomCards: [
        metricCard("Pedidos em aberto", formatInteger(orders?.open), "Status local aberto"),
        metricCard("Pedidos aprovados", formatInteger(orders?.approved), "Status local aprovado"),
        metricCard("Faturados no mês", formatInteger(orders?.invoiced_month), "Status local faturado"),
        metricCard("Cancelados no mês", formatInteger(orders?.cancelled_month), "Status local cancelado"),
      ],
      result,
    };
  }, [dashboard, isAdmin]);

  const seriesLast7Days = useMemo(() => {
    return Array.isArray(dashboard?.series?.last_7_days) ? dashboard.series.last_7_days : [];
  }, [dashboard]);

  const conversionCards = useMemo(() => {
    const conversion = dashboard?.conversion || {};
    const cards = [
      { label: "Conversão em pedido", value: formatPercent(conversion?.month_quote_to_order_rate), raw: metricNumber(conversion?.month_quote_to_order_rate) },
      { label: "Taxa de aprovação", value: formatPercent(conversion?.month_approval_rate), raw: metricNumber(conversion?.month_approval_rate) },
      { label: "Cancelamento", value: formatPercent(conversion?.month_cancel_rate), raw: metricNumber(conversion?.month_cancel_rate) },
    ];
    return cards
      .filter((card) => !card.label.toLowerCase().includes("aprova"))
      .map((card) => {
        if (card.label.toLowerCase().includes("pedido")) {
          return { ...card, note: "Pedidos gerados sobre orçamentos criados no mês." };
        }
        if (card.label.toLowerCase().includes("cancel")) {
          return { ...card, note: "Cancelados no mês conforme status local." };
        }
        return card;
      });
  }, [dashboard]);

  const dashboardSellerStatus = useMemo(() => {
    if (selectedDashboardSellerId === "all") return "Visualização geral da empresa";
    const option = dashboardSellerOptions.find((item) => item.seller_id === selectedDashboardSellerId);
    return `Visualizando vendedor: ${option?.seller_name || selectedDashboardSellerId}`;
  }, [dashboardSellerOptions, selectedDashboardSellerId]);

  async function handleHourlyDayClick(item) {
    const date = String(item?.date || "").trim();
    if (!date) return;

    setSelectedHourlyDay(item);
    setIsHourlyModalOpen(true);
    setHourlyLoading(true);
    setHourlyError("");
    setHourlyData(null);

    try {
      const sellerId = isAdmin && selectedDashboardSellerId !== "all" ? selectedDashboardSellerId : "";
      const response = await api.homeDashboardHourly({ company: activeCompanyKey, date, seller_id: sellerId });
      setHourlyData(response || null);
    } catch (e) {
      setHourlyError(e?.status === 403 ? "Usuário sem vendedor Tiny vinculado para esta empresa." : "Não foi possível carregar os detalhes desse dia.");
    } finally {
      setHourlyLoading(false);
    }
  }

  function closeHourlyModal() {
    setIsHourlyModalOpen(false);
  }

  return (
    <div className="homePage">
      <section className="homeHero">
        <PageHeader
          crumb="Início do ERP"
          title={`Olá, ${displayName}. Bem-vindo(a)!`}
          actions={
            <div className="homeStatusBadge">
              <span className="homeStatusDot" aria-hidden="true" />
              Operação local
            </div>
          }
        />
        <p className="homeLead">
          Painel inicial do ProjetoTRML para acompanhar o contexto operacional atual.
        </p>

        <div className="homeMetricGrid">
          {statusCards.map((card) => (
            <Card padding="sm" key={card.label}>
              <div className="homeMetricLabel">{card.label}</div>
              <div className="homeMetricValue">{card.value}</div>
              <div className="homeMetricNote">{card.note}</div>
            </Card>
          ))}
        </div>

        <Card padding="md" className="homeSection">
          <div className="homeSectionTitle">Métricas comerciais</div>

          <div className="homeChartSubtitle">Dados locais do ERP, sem consulta ao Tiny</div>

          <div className="homeDashboardFilterRow">
            <Toolbar className="homeDashboardFilterControls">
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
                        value={periodDateFrom}
                        onChange={(event) => setPeriodDateFrom(event.target.value)}
                      />
                    </div>
                  </Field>
                  <Field label="Data final">
                    <div style={{ minWidth: 150 }}>
                      <input
                        type="date"
                        value={periodDateTo}
                        onChange={(event) => setPeriodDateTo(event.target.value)}
                      />
                    </div>
                  </Field>
                </>
              ) : null}

              {isAdmin ? (
              <Field label="Filtro de vendedor">
                <div style={{ minWidth: 220 }}>
                  <select
                    value={selectedDashboardSellerId}
                    onChange={(event) => setSelectedDashboardSellerId(event.target.value || "all")}
                  >
                    <option value="all">Todos os vendedores</option>
                    {dashboardSellerOptions.map((seller) => (
                      <option key={seller.seller_id} value={seller.seller_id}>
                        {seller.seller_name}
                      </option>
                    ))}
                  </select>
                </div>
              </Field>
              ) : null}
            </Toolbar>
            <div className="homeDashboardFilterMeta">
              <span>{isAdmin ? dashboardSellerStatus : "Filtro de período aplicado ao seu vendedor vinculado"}</span>
              {dashboardPeriod === "custom" && (!periodDateFrom || !periodDateTo) ? (
                <span>Informe data inicial e final para aplicar o período personalizado.</span>
              ) : null}
              {dashboardSellerError ? <span>{dashboardSellerError}</span> : null}
            </div>
          </div>

          {dashboardLoading ? (
            <div className="homeMetricNote" style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
              <Spinner size={16} label="Carregando métricas..." />
              <span>Carregando métricas...</span>
            </div>
          ) : null}

          {dashboardError ? (
            <EmptyState title="Métricas indisponíveis" message={dashboardError} />
          ) : null}

          {!dashboardLoading && !dashboardError ? (
            <div className="homeDashboardStack">
              <div className="homeMetricGrid homeDashboardMetricGrid">
                {dashboardLayout.summaryCards.map((card) => (
                  <DashboardMetricCard card={card} key={card.label} />
                ))}
              </div>

              <SelectedPeriodPanel selectedPeriod={dashboard?.selected_period} isAdmin={isAdmin} />

              <div className="homeDashboardMainGrid">
                <div className="homeDashboardPrimary">
                  <Last7DaysChart items={seriesLast7Days} onDayClick={handleHourlyDayClick} />
                  <PeriodSummary rows={dashboardLayout.periodRows} />
                </div>
                <div className="homeDashboardSide">
                  <StatusFunnel data={dashboard?.status_breakdown || {}} />
                  <ConversionPanel cards={conversionCards} />
                </div>
              </div>

              {dashboardLayout.result ? <AdminResultPanel result={dashboardLayout.result} /> : null}

              <div className="homeMetricGrid homeDashboardMetricGrid homeDashboardBottomGrid">
                {dashboardLayout.bottomCards.map((card) => (
                  <DashboardMetricCard card={card} key={card.label} />
                ))}
              </div>
            </div>
          ) : null}
        </Card>

        {sellerNames.length ? (
          <Card padding="md" className="homeSection">
            <div className="homeSectionTitle">Vendedores vinculados ao seu acesso</div>
            <div className="homeSellerGrid">
              {sellerNames.map((name) => (
                <span
                  key={name}
                  className="homeSellerChip"
                >
                  {name}
                </span>
              ))}
            </div>
          </Card>
        ) : null}

        {error ? (
          <EmptyState title="Erro ao carregar" message={error} />
        ) : null}
      </section>
      {isHourlyModalOpen ? (
        <HourlyDetailModal
          day={selectedHourlyDay}
          data={hourlyData}
          loading={hourlyLoading}
          error={hourlyError}
          onClose={closeHourlyModal}
        />
      ) : null}
    </div>
  );
}
