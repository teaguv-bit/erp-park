import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { withGlobalLoading } from "../utils/globalLoading";
import { Button, Card, Table, PageHeader, Toolbar, EmptyState, Spinner } from "../ui";

const COMPANIES = [
  { key: "parton", label: "Suprimentos" },
  { key: "park", label: "Informática" },
];

const PAGE_SIZE = 50;

const EMPTY_NEW_CLIENT_FORM = {
  nome: "", fantasia: "", cpf_cnpj: "", email: "",
  telefone: "", celular: "", cep: "", endereco: "",
  numero: "", bairro: "", cidade: "", uf: "",
  codigo: "", complemento: "", telefone2: "", website: "",
  email_nfe: "", contribuinte: "", inscricao_estadual: "",
  inscricao_municipal: "", tipo_contato: "cliente",
  codigo_regime_tributario: "", inscricao_suframa: "",
  data_nascimento: "", status_crm: "cliente", observacoes: "",
  vendedor_id: "", vendedor_nome: "",
};

function formatDate(value) {
  if (!value) return "Data não informada";
  const text = String(value || "").trim();
  if (!text) return "Data não informada";

  const brMatch = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/);
  const parsed = brMatch
    ? new Date(
        Number(brMatch[3]),
        Number(brMatch[2]) - 1,
        Number(brMatch[1]),
        Number(brMatch[4] || 0),
        Number(brMatch[5] || 0),
        Number(brMatch[6] || 0)
      )
    : new Date(text);

  if (Number.isNaN(parsed.getTime())) return "Data não informada";

  const hasTime = brMatch
    ? Boolean(brMatch[4])
    : /[T\s]\d{1,2}:\d{2}/.test(text);
  return parsed.toLocaleString("pt-BR", hasTime
    ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "2-digit", year: "numeric" });
}

function yesNo(value) {
  return value ? "Sim" : "Não";
}

function companyLabel(company) {
  return COMPANIES.find((item) => item.key === company)?.label || company;
}

function formatNumber(value) {
  const n = Number(value || 0);
  return n.toLocaleString("pt-BR");
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return `${Math.round(n)}%`;
}

function formatBRL(value) {
  const n = Number(value || 0);
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function purchaseBadge(client) {
  const level = client?.purchase_recency_level || "unknown";
  const days = client?.days_without_purchase;
  if (level === "unknown" || days === null || days === undefined) {
    return { text: "Sem compra", style: recencyBadgeStyles.unknown };
  }
  const text = Number(days) === 0 ? "Hoje" : `${days} dia${Number(days) === 1 ? "" : "s"}`;
  return { text, style: recencyBadgeStyles[level] || recencyBadgeStyles.unknown };
}

export default function ClientWallet() {
  const [company, setCompany] = useState(() => api.getCurrentCompany?.() || "parton");
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState(null);
  const [detail, setDetail] = useState(null);
  const [purchasesModal, setPurchasesModal] = useState({ open: false, client: null, loading: false, error: "", items: [] });
  const [newClientOpen, setNewClientOpen] = useState(false);
  const [newClientForm, setNewClientForm] = useState({ ...EMPTY_NEW_CLIENT_FORM });
  const [newClientSaving, setNewClientSaving] = useState(false);
  const [newClientError, setNewClientError] = useState("");
  const [activeCreateTab, setActiveCreateTab] = useState("geral");
  const [createClientSellers, setCreateClientSellers] = useState([]);
  const [createClientSellersLoading, setCreateClientSellersLoading] = useState(false);
  const [editClientMode, setEditClientMode] = useState(false);
  const [editingTinyClientId, setEditingTinyClientId] = useState(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);

  const [q, setQ] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [uf, setUf] = useState("");
  const [seller, setSeller] = useState("");
  const [sellers, setSellers] = useState([]);
  const [activeOnly, setActiveOnly] = useState(true);
  const [hasEmail, setHasEmail] = useState(false);
  const [hasPhone, setHasPhone] = useState(false);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  const loadStatus = useCallback(async (targetCompany = company) => {
    const result = await api.clientWalletSyncStatus({ company: targetCompany });
    setStatus(result || null);
    return result;
  }, [company]);

  const loadSellers = useCallback(async (targetCompany = company) => {
    const result = await api.clientWalletSellers({ company: targetCompany });
    setSellers(Array.isArray(result?.items) ? result.items : []);
    return result;
  }, [company]);

  const loadClients = useCallback(async ({
    targetCompany = company,
    search = appliedQ,
    sellerFilter = seller,
    nextOffset = offset,
  } = {}) => {
    const result = await api.clientWalletList({
      company: targetCompany,
      q: search,
      uf,
      seller: sellerFilter,
      active: activeOnly ? true : undefined,
      has_email: hasEmail ? true : undefined,
      has_phone: hasPhone ? true : undefined,
      limit: PAGE_SIZE,
      offset: nextOffset,
    });
    setItems(Array.isArray(result?.items) ? result.items : []);
    setTotal(Number(result?.total || 0));
    setOffset(nextOffset);
    return result;
  }, [activeOnly, appliedQ, company, hasEmail, hasPhone, offset, seller, uf]);

  const reload = useCallback(async (targetCompany = company, nextOffset = offset, options = {}) => {
    try {
      setLoading(true);
      setError("");
      const sellerFilter = options.sellerFilter ?? seller;
      await withGlobalLoading("Carregando carteira de clientes...", async () => {
        await loadStatus(targetCompany);
        await loadSellers(targetCompany);
        await loadClients({ targetCompany, nextOffset, sellerFilter });
      });
    } catch (e) {
      setError(e?.message || "Erro ao carregar carteira de clientes.");
    } finally {
      setLoading(false);
    }
  }, [company, loadClients, loadSellers, loadStatus, offset, seller]);

  useEffect(() => {
    async function init() {
      try {
        const me = await api.me();
        setIsAdmin(Boolean(me?.is_admin));
      } catch {
        setIsAdmin(false);
      }
      await reload(company, 0);
    }
    init();
  }, []);

  async function handleCompanyChange(nextCompany) {
    setCompany(nextCompany);
    setSeller("");
    setDetail(null);
    setOffset(0);
    setNewClientForm((f) => ({ ...f, vendedor_id: "", vendedor_nome: "" }));
    await reload(nextCompany, 0, { sellerFilter: "" });
  }

  async function handleApply() {
    const search = String(q || "").trim();
    setAppliedQ(search);
    setDetail(null);
    setOffset(0);
    try {
      setLoading(true);
      setError("");
      await withGlobalLoading("Filtrando clientes...", () =>
        loadClients({ targetCompany: company, search, sellerFilter: seller, nextOffset: 0 })
      );
    } catch (e) {
      setError(e?.message || "Erro ao filtrar clientes.");
    } finally {
      setLoading(false);
    }
  }

  async function handleImportNext() {
    try {
      setSyncing(true);
      setError("");
      await withGlobalLoading("Importando próximo lote do Tiny...", () =>
        api.clientWalletSyncNext({ company, page_size: PAGE_SIZE })
      );
      await reload(company, 0);
    } catch (e) {
      setError(e?.message || "Erro ao importar próximo lote.");
      await loadStatus(company).catch(() => null);
    } finally {
      setSyncing(false);
    }
  }

  async function handleReset() {
    if (!window.confirm(`Reiniciar importação de ${companyLabel(company)} a partir da página 1? Os clientes locais serão mantidos.`)) {
      return;
    }
    try {
      setSyncing(true);
      setError("");
      await withGlobalLoading("Reiniciando cursor de importação...", () =>
        api.clientWalletSyncReset({ company, page_size: PAGE_SIZE })
      );
      await reload(company, 0);
    } catch (e) {
      setError(e?.message || "Erro ao reiniciar importação.");
    } finally {
      setSyncing(false);
    }
  }

  async function openDetail(client) {
    try {
      setError("");
      const result = await withGlobalLoading("Abrindo cliente...", () =>
        api.clientWalletDetail({ company, tiny_client_id: client.tiny_client_id })
      );
      setDetail(result?.item || null);
      setDetailModalOpen(true);
    } catch (e) {
      setError(e?.message || "Erro ao abrir detalhes do cliente.");
    }
  }

  async function openPurchases(client) {
    setPurchasesModal({ open: true, client, loading: true, error: "", items: [] });
    try {
      const result = await withGlobalLoading("Carregando últimas compras...", () =>
        api.clientWalletLastPurchases({ company, tiny_client_id: client.tiny_client_id, limit: 3 })
      );
      setPurchasesModal({
        open: true,
        client,
        loading: false,
        error: "",
        items: Array.isArray(result?.items) ? result.items : [],
      });
      if (result?.updated_client?.tiny_client_id) {
        setItems((prev) => prev.map((item) =>
          String(item.tiny_client_id) === String(result.updated_client.tiny_client_id)
            ? { ...item, ...result.updated_client }
            : item
        ));
      }
    } catch (e) {
      setPurchasesModal({
        open: true,
        client,
        loading: false,
        error: e?.message || "Erro ao carregar últimas compras.",
        items: [],
      });
    }
  }

  async function goTo(nextOffset) {
    try {
      setLoading(true);
      setError("");
      await loadClients({ targetCompany: company, nextOffset });
    } catch (e) {
      setError(e?.message || "Erro ao paginar clientes.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateClient(e) {
    e.preventDefault();
    const nome = newClientForm.nome.trim();
    if (!nome) {
      setNewClientError("O campo 'nome' é obrigatório.");
      return;
    }
    setNewClientSaving(true);
    setNewClientError("");

    if (editClientMode) {
      // Modo edição: envia PATCH com todos os campos editáveis.
      const payload = { nome };
      const editableFields = [
        "fantasia", "cpf_cnpj", "email", "telefone", "celular", "cep", "endereco",
        "numero", "bairro", "cidade", "codigo", "complemento", "telefone2",
        "website", "email_nfe", "observacoes", "inscricao_estadual",
        "inscricao_municipal", "tipo_contato", "codigo_regime_tributario",
        "inscricao_suframa", "status_crm", "contribuinte", "data_nascimento",
        "uf", "vendedor_id", "vendedor_nome",
      ];
      for (const key of editableFields) {
        payload[key] = newClientForm[key] ?? "";
      }
      try {
        const result = await api.clientWalletUpdate({ company, tiny_client_id: editingTinyClientId, payload });
        await reload(company, 0);
        if (result?.tiny_sync_status === "error") {
          const syncErr = result?.tiny_sync_error || "Falha desconhecida ao sincronizar com o Tiny V3.";
          setNewClientError(`Cliente salvo localmente, mas houve erro ao atualizar no Tiny V3: ${syncErr}`);
          return;
        }
        // Recarrega o detalhe do cliente editado e reabre o modal de detalhes.
        try {
          const detailResult = await api.clientWalletDetail({ company, tiny_client_id: editingTinyClientId });
          setDetail(detailResult?.item || null);
          setDetailModalOpen(true);
        } catch {
          setDetail(null);
          setDetailModalOpen(false);
        }
        setNewClientOpen(false);
        setNewClientForm({ ...EMPTY_NEW_CLIENT_FORM });
        setNewClientError("");
        setEditClientMode(false);
        setEditingTinyClientId(null);
      } catch (err) {
        if (err?.status === 409) {
          const msg = err?.data?.detail?.message || err.message || "Já existe outro cliente com este CPF/CNPJ nesta empresa.";
          setNewClientError(msg);
        } else {
          setNewClientError(err?.message || "Erro ao salvar alterações.");
        }
      } finally {
        setNewClientSaving(false);
      }
      return;
    }

    // Modo criação: comportamento original.
    const payload = { nome };
    const optionals = [
      "fantasia", "cpf_cnpj", "email", "telefone", "celular", "cep", "endereco",
      "numero", "bairro", "cidade", "codigo", "complemento", "telefone2",
      "website", "email_nfe", "observacoes", "inscricao_estadual",
      "inscricao_municipal", "tipo_contato", "codigo_regime_tributario",
      "inscricao_suframa", "status_crm",
    ];
    for (const key of optionals) {
      const val = String(newClientForm[key] || "").trim();
      if (val) payload[key] = val;
    }
    const uf = String(newClientForm.uf || "").trim().toUpperCase();
    if (uf) payload.uf = uf;
    if (newClientForm.contribuinte) payload.contribuinte = newClientForm.contribuinte;
    if (newClientForm.data_nascimento) payload.data_nascimento = newClientForm.data_nascimento;
    if (isAdmin && newClientForm.vendedor_id) {
      payload.vendedor_id = newClientForm.vendedor_id;
      if (newClientForm.vendedor_nome) payload.vendedor_nome = newClientForm.vendedor_nome;
    }
    try {
      const result = await api.clientWalletCreate({ company, payload });
      await reload(company, 0);
      if (result?.tiny_sync_status === "synced") {
        setNewClientOpen(false);
        setNewClientForm({ ...EMPTY_NEW_CLIENT_FORM });
        setNewClientError("");
      } else {
        const syncErr = result?.tiny_sync_error || "Falha desconhecida ao sincronizar com o Tiny V3.";
        setNewClientError(`Cliente salvo localmente, mas houve erro ao enviar ao Tiny V3: ${syncErr}`);
      }
    } catch (err) {
      if (err?.status === 409) {
        setNewClientError(err.message || "Já existe um cliente com este CPF/CNPJ nesta empresa.");
      } else {
        setNewClientError(err?.message || "Erro ao cadastrar cliente.");
      }
    } finally {
      setNewClientSaving(false);
    }
  }

  function openEditClient(clientDetail) {
    const form = { ...EMPTY_NEW_CLIENT_FORM };
    for (const key of Object.keys(EMPTY_NEW_CLIENT_FORM)) {
      const val = clientDetail[key];
      if (val !== undefined && val !== null) {
        form[key] = String(val);
      }
    }
    setDetailModalOpen(false);
    setNewClientForm(form);
    setEditingTinyClientId(clientDetail.tiny_client_id);
    setEditClientMode(true);
    setNewClientError("");
    setActiveCreateTab("geral");
    setNewClientOpen(true);
  }

  function closeClientModal() {
    setNewClientOpen(false);
    setNewClientForm({ ...EMPTY_NEW_CLIENT_FORM });
    setNewClientError("");
    setEditClientMode(false);
    setEditingTinyClientId(null);
  }

  useEffect(() => {
    if (!newClientOpen || !isAdmin) {
      setCreateClientSellers([]);
      return;
    }
    let cancelled = false;
    setCreateClientSellersLoading(true);
    api.adminCompanySellers({ company })
      .then((res) => {
        if (!cancelled) setCreateClientSellers(Array.isArray(res?.sellers) ? res.sellers : []);
      })
      .catch(() => {
        if (!cancelled) setCreateClientSellers([]);
      })
      .finally(() => {
        if (!cancelled) setCreateClientSellersLoading(false);
      });
    return () => { cancelled = true; };
  }, [newClientOpen, isAdmin, company]);

  const syncState = useMemo(() => {
    if (status?.status) return status.status;
    if (status?.last_error) return "Erro";
    if (status?.finished) return "Finalizado";
    if (status?.last_run_at || status?.last_success_at) return "Em andamento";
    return "Não iniciado";
  }, [status]);

  const progressPercent = useMemo(() => {
    if (status?.finished) return 100;
    const n = Number(status?.progress_percent);
    if (!Number.isFinite(n)) return null;
    return Math.max(0, Math.min(100, n));
  }, [status]);

  const progressLabel = formatPercent(progressPercent);
  const totalLocal = Number(status?.total_local ?? total ?? 0);
  const totalRemote = Number(status?.total_remote || 0);
  const currentPage = status?.current_page || null;
  const totalPages = status?.total_pages || null;
  const nextPage = status?.next_page || 1;
  const isFinished = Boolean(status?.finished);
  const progressMainText = isFinished
    ? `${formatNumber(totalLocal)} clientes importados`
    : totalRemote
    ? `${formatNumber(totalLocal)} de ${formatNumber(totalRemote)} clientes`
    : `${formatNumber(totalLocal)} clientes importados · Página ${currentPage || nextPage} · Progresso estimado indisponível`;
  const progressPageText = isFinished
    ? `Página final: ${currentPage || nextPage}`
    : totalPages
    ? `Página ${currentPage || 0} de ${totalPages}`
    : `Próximo lote: Página ${nextPage}`;

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <PageHeader
          title="Carteira de Clientes"
          actions={
            <Button
              variant="primary"
              onClick={() => { setEditClientMode(false); setEditingTinyClientId(null); setNewClientForm({ ...EMPTY_NEW_CLIENT_FORM }); setNewClientError(""); setActiveCreateTab("geral"); setNewClientOpen(true); }}
            >
              + Novo cliente
            </Button>
          }
        />

        <Toolbar>
          {COMPANIES.map((item) => {
            const active = item.key === company;
            return (
              <Button
                key={item.key}
                variant={active ? "primary" : "secondary"}
                onClick={() => handleCompanyChange(item.key)}
              >
                {item.label}
              </Button>
            );
          })}
        </Toolbar>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(160px, 1fr))", gap: 10, marginBottom: 16 }}>
          <Card padding="sm">
            <div style={labelStyle}>Total local</div>
            <div style={valueStyle}>{formatNumber(totalLocal)}</div>
          </Card>
          <Card padding="sm">
            <div style={labelStyle}>Próximo lote</div>
            <div style={valueStyle}>Página {nextPage}</div>
          </Card>
          <Card padding="sm">
            <div style={labelStyle}>Status</div>
            <div style={valueStyle}>{syncState}</div>
          </Card>
          <Card padding="sm">
            <div style={labelStyle}>Último sync</div>
            <div style={{ fontWeight: 800 }}>{formatDate(status?.last_success_at)}</div>
          </Card>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 10 }}>
              <div>
                <div style={labelStyle}>Progresso da sincronização</div>
                <div style={{ fontSize: 18, fontWeight: 900 }}>{progressMainText}</div>
                <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 3 }}>
                  {progressPageText} · Último sync: {formatDate(status?.last_success_at)}
                </div>
              </div>
              <div
                style={{
                  padding: "7px 10px",
                  border: "1px solid var(--border)",
                  background: status?.finished ? "var(--success-soft)" : status?.last_error ? "var(--warning-soft)" : "var(--surface)",
                  color: status?.finished ? "var(--success)" : status?.last_error ? "var(--warning)" : "var(--text)",
                  fontWeight: 900,
                  whiteSpace: "nowrap",
                }}
              >
                {status?.finished ? "Sincronização concluída" : syncState}
              </div>
            </div>
            <div style={{ height: 10, background: "var(--surface-2)", border: "1px solid var(--border)", overflow: "hidden" }}>
              <div
                style={{
                  height: "100%",
                  width: `${progressPercent ?? 0}%`,
                  background: status?.finished ? "var(--success)" : "var(--accent)",
                  transition: "width 180ms ease",
                }}
              />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginTop: 8, color: "var(--muted)", fontSize: 13 }}>
              <span>{progressLabel ? `Progresso: ${progressLabel}` : "Progresso estimado indisponível"}</span>
              <span>{isFinished ? "Sincronização concluída" : totalRemote ? `Total Tiny: ${formatNumber(totalRemote)}` : "Importação em andamento"}</span>
            </div>
          </Card>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 90px 190px repeat(3, auto) auto auto", gap: 10, alignItems: "center" }}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleApply();
            }}
            placeholder="Buscar por nome, fantasia, CPF/CNPJ, e-mail ou telefone"
            style={inputStyle}
          />
          <input value={uf} onChange={(e) => setUf(e.target.value.toUpperCase())} placeholder="UF" maxLength={2} style={inputStyle} />
          <select value={seller} onChange={(e) => setSeller(e.target.value)} style={inputStyle}>
            <option value="">Todos os vendedores</option>
            {sellers.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <label style={checkStyle}><input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} /> Ativos</label>
          <label style={checkStyle}><input type="checkbox" checked={hasEmail} onChange={(e) => setHasEmail(e.target.checked)} /> Com e-mail</label>
          <label style={checkStyle}><input type="checkbox" checked={hasPhone} onChange={(e) => setHasPhone(e.target.checked)} /> Com telefone</label>
          <Button variant="primary" onClick={handleApply}>Aplicar</Button>
          {isAdmin ? (
            <Button onClick={handleImportNext} loading={syncing} disabled={syncing}>
              {syncing ? "Importando..." : "Importar próximo lote"}
            </Button>
          ) : null}
        </div>

        {isAdmin ? (
          <Toolbar>
            <Button onClick={handleReset} loading={syncing} disabled={syncing}>
              Reiniciar importação
            </Button>
          </Toolbar>
        ) : null}
      </div>

      {error ? <div style={errorStyle}>{error}</div> : null}
      {status?.last_error ? <div style={errorStyle}>Último erro de importação: {status.last_error}</div> : null}
      {loading ? (
        <div style={{ padding: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <Spinner /> Carregando clientes...
        </div>
      ) : null}

      {!loading ? (
        <div>
          <Table>
            <thead>
              <tr>
                {["Cliente", "CPF/CNPJ", "Contato", "Cidade/UF", "Vendedor", "Última compra", "Situação", "Última atualização", "Ações"].map((title) => (
                  <th key={title}>{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((client) => (
                <tr key={`${client.company_key}-${client.tiny_client_id}`}>
                  <td>
                    <div style={{ fontWeight: 900 }}>{client.nome || "-"}</div>
                    <div style={{ color: "var(--muted)", fontSize: 12 }}>{client.fantasia || `Tiny ${client.tiny_client_id}`}</div>
                  </td>
                  <td>{client.cpf_cnpj || "-"}</td>
                  <td>
                    <div>{client.email || "-"}</div>
                    <div style={{ color: "var(--muted)", fontSize: 12 }}>{client.telefone || client.celular || "-"}</div>
                  </td>
                  <td>{[client.cidade, client.uf].filter(Boolean).join(" / ") || "-"}</td>
                  <td>{client.vendedor_nome || "-"}</td>
                  <td>
                    <div style={{ fontWeight: 800 }}>{client.last_purchase_date ? formatDate(client.last_purchase_date) : "Sem compra"}</div>
                    <span style={{ ...recencyBadgeStyle, ...purchaseBadge(client).style }}>{purchaseBadge(client).text}</span>
                    {client.last_purchase_total ? (
                      <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>{formatBRL(client.last_purchase_total)}</div>
                    ) : null}
                  </td>
                  <td>{client.situacao || (client.ativo ? "Ativo" : "Inativo")}</td>
                  <td>{formatDate(client.updated_at || client.last_seen_at)}</td>
                  <td>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <Button size="sm" onClick={() => openDetail(client)}>Ver detalhes</Button>
                      <Button size="sm" onClick={() => openPurchases(client)}>Últimas compras</Button>
                    </div>
                  </td>
                </tr>
              ))}
              {!items.length ? (
                <tr>
                  <td colSpan={9}>
                    <EmptyState title="Nenhum cliente" message={`Nenhum cliente encontrado para ${companyLabel(company)}.`} />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </Table>

        </div>
      ) : null}

      <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
        <Button onClick={() => goTo(Math.max(0, offset - PAGE_SIZE))} disabled={!hasPrev || loading}>Anterior</Button>
        <div style={{ fontWeight: 800 }}>Página {page} de {Math.max(1, Math.ceil(total / PAGE_SIZE))}</div>
        <Button onClick={() => goTo(offset + PAGE_SIZE)} disabled={!hasNext || loading}>Próxima</Button>
        <div style={{ color: "var(--muted)", fontSize: 13 }}>{total} cliente(s)</div>
      </div>

      {purchasesModal.open ? (
        <div style={modalOverlayStyle}>
          <div style={modalStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 900 }}>Últimas compras</div>
                <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 3 }}>
                  {purchasesModal.client?.nome || "-"} · {companyLabel(company)}
                </div>
                <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 3 }}>
                  Fonte: histórico local do ERP
                </div>
              </div>
              <Button onClick={() => setPurchasesModal({ open: false, client: null, loading: false, error: "", items: [] })}>
                Fechar
              </Button>
            </div>

            {purchasesModal.loading ? (
              <div style={{ padding: 12, display: "flex", alignItems: "center", gap: 8 }}>
                <Spinner /> Carregando últimas compras...
              </div>
            ) : null}
            {purchasesModal.error ? <div style={errorStyle}>{purchasesModal.error}</div> : null}

            {!purchasesModal.loading && !purchasesModal.error && !purchasesModal.items.length ? (
              <EmptyState message="Nenhuma compra encontrada para este cliente nesta empresa." />
            ) : null}

            {!purchasesModal.loading && !purchasesModal.error && purchasesModal.items.map((purchase, idx) => (
              <div key={`${purchase.quote_id || purchase.tiny_order_id || purchase.order_number || idx}`} style={{ marginBottom: 12 }}>
                <Card padding="sm">
                  <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "start", marginBottom: 10 }}>
                    <div>
                      <div style={{ fontWeight: 900 }}>
                        Pedido #{purchase.order_number || purchase.tiny_order_number || purchase.quote_number || purchase.tiny_order_id || "-"}
                      </div>
                      <div style={{ color: "var(--muted)", fontSize: 13 }}>
                        ID Tiny: {purchase.tiny_order_id || "-"} · {purchase.status || "-"} · {formatDate(purchase.date)}
                      </div>
                      <div style={{ color: "var(--muted)", fontSize: 13 }}>
                        Vendedor: {purchase.seller_name || "-"} · Pagamento: {purchase.payment_name || "-"}
                      </div>
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 900 }}>{formatBRL(purchase.total_value)}</div>
                  </div>

                  {purchase.notes ? (
                    <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 10 }}>{purchase.notes}</div>
                  ) : null}

                  <Table>
                    <thead>
                      <tr>
                        {[["SKU"], ["Produto"], ["Qtd", true], ["Valor unit.", true], ["Desconto", true], ["Total", true]].map(([title, numeric]) => (
                          <th key={title} {...(numeric ? { "data-numeric": true } : {})}>{title}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(purchase.products || []).map((product, idx) => (
                        <tr key={`${product.sku || idx}-${idx}`}>
                          <td>{product.sku || "-"}</td>
                          <td>{product.name || "-"}</td>
                          <td data-numeric>{formatNumber(product.quantity)} {product.unit || ""}</td>
                          <td data-numeric>{formatBRL(product.unit_price)}</td>
                          <td data-numeric>{formatBRL(product.discount)}</td>
                          <td data-numeric>{formatBRL(product.total_price)}</td>
                        </tr>
                      ))}
                      {!(purchase.products || []).length ? (
                        <tr>
                          <td colSpan={6}>
                            <EmptyState message="Itens não disponíveis no histórico local." />
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </Table>
                </Card>
              </div>
            ))}

            {!purchasesModal.loading && !purchasesModal.error && purchasesModal.items.length ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>Exibindo as últimas 3 compras encontradas.</div>
            ) : null}
          </div>
        </div>
      ) : null}

      {detail && detailModalOpen ? (
        <div style={modalOverlayStyle}>
          <div style={{ ...modalStyle, width: "min(680px, 100%)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 900 }}>Detalhes do cliente</div>
                <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>
                  {companyLabel(detail.company_key)} · <strong>{detail.nome || "-"}</strong>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                {isAdmin ? (
                  <Button variant="primary" onClick={() => openEditClient(detail)}>
                    Editar
                  </Button>
                ) : null}
                <Button onClick={() => setDetailModalOpen(false)}>Fechar</Button>
              </div>
            </div>

            <div style={{ ...sectionHeaderStyle }}>Dados principais</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              <DetailRow label="Nome / Razão Social" value={detail.nome} />
              <DetailRow label="Fantasia" value={detail.fantasia} />
              <DetailRow label="CPF/CNPJ" value={detail.cpf_cnpj} />
              <DetailRow label="Tipo de contato" value={detail.tipo_contato} />
              <DetailRow label="Situação" value={detail.situacao || (detail.ativo != null ? yesNo(detail.ativo) : null)} />
              <DetailRow label="Vendedor" value={detail.vendedor_nome || detail.vendedor_id} />
              <DetailRow label="ID Tiny" value={detail.tiny_client_id} />
              <DetailRow label="Código" value={detail.codigo} />
            </div>

            <div style={{ ...sectionHeaderStyle, marginTop: 16 }}>Contato</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              <DetailRow label="E-mail" value={detail.email} />
              <DetailRow label="E-mail NFe" value={detail.email_nfe} />
              <DetailRow label="Telefone" value={detail.telefone} />
              <DetailRow label="Telefone adicional" value={detail.telefone2} />
              <DetailRow label="Celular" value={detail.celular} />
              <DetailRow label="Website" value={detail.website} />
            </div>

            <div style={{ ...sectionHeaderStyle, marginTop: 16 }}>Endereço</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              <DetailRow label="CEP" value={detail.cep} />
              <DetailRow label="Cidade / UF" value={[detail.cidade, detail.uf].filter(Boolean).join(" / ")} />
              <DetailRow label="Endereço" value={detail.endereco} />
              <DetailRow label="Número" value={detail.numero} />
              <DetailRow label="Bairro" value={detail.bairro} />
              <DetailRow label="Complemento" value={detail.complemento} />
            </div>

            <div style={{ ...sectionHeaderStyle, marginTop: 16 }}>Dados complementares</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              <DetailRow label="Contribuinte" value={detail.contribuinte} />
              <DetailRow label="Inscrição Estadual" value={detail.inscricao_estadual} />
              <DetailRow label="Inscrição Municipal" value={detail.inscricao_municipal} />
              <DetailRow label="Cód. regime tributário" value={detail.codigo_regime_tributario} />
              <DetailRow label="Inscrição Suframa" value={detail.inscricao_suframa} />
              <DetailRow label="Data nascimento" value={detail.data_nascimento ? formatDate(detail.data_nascimento) : null} />
              <DetailRow label="Status CRM" value={detail.status_crm} />
            </div>

            {detail.observacoes ? (
              <>
                <div style={{ ...sectionHeaderStyle, marginTop: 16 }}>Observações</div>
                <div style={{ padding: "10px 0", borderBottom: "1px solid var(--border)", fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {detail.observacoes}
                </div>
              </>
            ) : null}

            <div style={{ ...sectionHeaderStyle, marginTop: 16 }}>Sincronização</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
              <DetailRow label="Origem" value={detail.origin} />
              <DetailRow label="Status sync Tiny" value={detail.tiny_sync_status} />
              <DetailRow label="Sincronizado em" value={detail.tiny_synced_at ? formatDate(detail.tiny_synced_at) : null} />
              <DetailRow label="Atualizado em" value={formatDate(detail.updated_at)} />
            </div>
            {detail.tiny_sync_error ? (
              <div style={{ ...errorStyle, marginTop: 8, fontSize: 12 }}>
                Erro de sync: {detail.tiny_sync_error}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {newClientOpen ? (
        <div style={modalOverlayStyle}>
          <div style={{ ...modalStyle, width: "min(760px, 100%)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 900 }}>{editClientMode ? "Editar cliente" : "Novo cliente"}</div>
                <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>
                  Empresa: <strong>{companyLabel(company)}</strong>
                  {editClientMode
                    ? " · As alterações serão salvas no ERP Local."
                    : " · O cliente será salvo no ERP Local e enviado ao Tiny V3."}
                </div>
              </div>
              <Button
                type="button"
                onClick={closeClientModal}
                disabled={newClientSaving}
              >
                Fechar
              </Button>
            </div>

            {newClientError ? (
              <div style={{ ...errorStyle, marginBottom: 14 }}>{newClientError}</div>
            ) : null}

            <div style={{ display: "flex", gap: 0, marginBottom: 16, borderBottom: "2px solid var(--border)" }}>
              {[["geral", "Dados gerais"], ["complementar", "Dados complementares"], ["obs", "Observações"]].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveCreateTab(key)}
                  style={{
                    padding: "8px 14px",
                    border: "none",
                    borderBottom: activeCreateTab === key ? "2px solid var(--accent, #2563eb)" : "2px solid transparent",
                    background: "transparent",
                    color: activeCreateTab === key ? "var(--accent, #2563eb)" : "var(--muted)",
                    fontWeight: activeCreateTab === key ? 900 : 700,
                    cursor: "pointer",
                    marginBottom: -2,
                    fontSize: 13,
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            <form onSubmit={handleCreateClient} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {activeCreateTab === "geral" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                  <div>
                    <div style={{ ...labelStyle, textTransform: "uppercase", letterSpacing: ".07em", paddingBottom: 6, borderBottom: "1px solid var(--border)", marginBottom: 12 }}>Dados principais</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Nome / Razão Social <span style={{ color: "#ef4444" }}>*</span></span>
                        <input type="text" value={newClientForm.nome} onChange={(e) => setNewClientForm((f) => ({ ...f, nome: e.target.value }))} style={inputStyle} placeholder="Nome ou razão social" required autoFocus />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Fantasia</span>
                        <input type="text" value={newClientForm.fantasia} onChange={(e) => setNewClientForm((f) => ({ ...f, fantasia: e.target.value }))} style={inputStyle} placeholder="Nome fantasia" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Código</span>
                        <input type="text" value={newClientForm.codigo} onChange={(e) => setNewClientForm((f) => ({ ...f, codigo: e.target.value }))} style={inputStyle} placeholder="Código interno" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>CPF/CNPJ</span>
                        <input type="text" value={newClientForm.cpf_cnpj} onChange={(e) => setNewClientForm((f) => ({ ...f, cpf_cnpj: e.target.value }))} style={inputStyle} placeholder="000.000.000-00 ou 00.000.000/0000-00" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Contribuinte</span>
                        <select value={newClientForm.contribuinte} onChange={(e) => setNewClientForm((f) => ({ ...f, contribuinte: e.target.value }))} style={inputStyle}>
                          <option value="">Não informado</option>
                          <option value="S">Sim (contribuinte ICMS)</option>
                          <option value="N">Não contribuinte</option>
                          <option value="I">Isento</option>
                        </select>
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Tipo de contato</span>
                        <select value={newClientForm.tipo_contato} onChange={(e) => setNewClientForm((f) => ({ ...f, tipo_contato: e.target.value }))} style={inputStyle}>
                          <option value="cliente">Cliente</option>
                          <option value="fornecedor">Fornecedor</option>
                          <option value="ambos">Cliente e Fornecedor</option>
                          <option value="funcionario">Funcionário</option>
                          <option value="transportadora">Transportadora</option>
                        </select>
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Inscrição Estadual</span>
                        <input type="text" value={newClientForm.inscricao_estadual} onChange={(e) => setNewClientForm((f) => ({ ...f, inscricao_estadual: e.target.value }))} style={inputStyle} placeholder="Inscrição estadual" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Inscrição Municipal</span>
                        <input type="text" value={newClientForm.inscricao_municipal} onChange={(e) => setNewClientForm((f) => ({ ...f, inscricao_municipal: e.target.value }))} style={inputStyle} placeholder="Inscrição municipal" />
                      </label>
                      {isAdmin ? (
                        <label style={{ display: "flex", flexDirection: "column", gap: 4, gridColumn: "1 / -1" }}>
                          <span style={{ ...labelStyle, marginBottom: 0 }}>Vendedor</span>
                          <select
                            value={newClientForm.vendedor_id}
                            onChange={(e) => {
                              const sel = createClientSellers.find((s) => String(s.seller_id) === e.target.value);
                              setNewClientForm((f) => ({
                                ...f,
                                vendedor_id: e.target.value,
                                vendedor_nome: sel ? (sel.seller_name || String(sel.seller_id)) : "",
                              }));
                            }}
                            style={inputStyle}
                            disabled={createClientSellersLoading}
                          >
                            <option value="">Sem vendedor vinculado</option>
                            {createClientSellers.map((s) => (
                              <option key={s.seller_id} value={String(s.seller_id)}>
                                {s.seller_name || String(s.seller_id)}
                              </option>
                            ))}
                          </select>
                          <span style={{ color: "var(--muted)", fontSize: 11, marginTop: 2 }}>
                            Clientes sem vendedor ficam visíveis apenas para administradores.
                          </span>
                        </label>
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div style={{ ...labelStyle, textTransform: "uppercase", letterSpacing: ".07em", paddingBottom: 6, borderBottom: "1px solid var(--border)", marginBottom: 12 }}>Endereço</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>CEP</span>
                        <input type="text" value={newClientForm.cep} onChange={(e) => setNewClientForm((f) => ({ ...f, cep: e.target.value }))} style={inputStyle} placeholder="01310-100" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Cidade / Município</span>
                        <input type="text" value={newClientForm.cidade} onChange={(e) => setNewClientForm((f) => ({ ...f, cidade: e.target.value }))} style={inputStyle} placeholder="São Paulo" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>UF</span>
                        <input type="text" value={newClientForm.uf} onChange={(e) => setNewClientForm((f) => ({ ...f, uf: e.target.value.toUpperCase() }))} style={inputStyle} placeholder="SP" maxLength={2} />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Endereço</span>
                        <input type="text" value={newClientForm.endereco} onChange={(e) => setNewClientForm((f) => ({ ...f, endereco: e.target.value }))} style={inputStyle} placeholder="Rua, Av..." />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Bairro</span>
                        <input type="text" value={newClientForm.bairro} onChange={(e) => setNewClientForm((f) => ({ ...f, bairro: e.target.value }))} style={inputStyle} placeholder="Bairro" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Número</span>
                        <input type="text" value={newClientForm.numero} onChange={(e) => setNewClientForm((f) => ({ ...f, numero: e.target.value }))} style={inputStyle} placeholder="123" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4, gridColumn: "1 / -1" }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Complemento</span>
                        <input type="text" value={newClientForm.complemento} onChange={(e) => setNewClientForm((f) => ({ ...f, complemento: e.target.value }))} style={inputStyle} placeholder="Apto, sala, bloco..." />
                      </label>
                    </div>
                  </div>

                  <div>
                    <div style={{ ...labelStyle, textTransform: "uppercase", letterSpacing: ".07em", paddingBottom: 6, borderBottom: "1px solid var(--border)", marginBottom: 12 }}>Contato</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Telefone</span>
                        <input type="text" value={newClientForm.telefone} onChange={(e) => setNewClientForm((f) => ({ ...f, telefone: e.target.value }))} style={inputStyle} placeholder="(11) 1234-5678" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Telefone adicional</span>
                        <input type="text" value={newClientForm.telefone2} onChange={(e) => setNewClientForm((f) => ({ ...f, telefone2: e.target.value }))} style={inputStyle} placeholder="(11) 1234-5679" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Celular</span>
                        <input type="text" value={newClientForm.celular} onChange={(e) => setNewClientForm((f) => ({ ...f, celular: e.target.value }))} style={inputStyle} placeholder="(11) 91234-5678" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>Website</span>
                        <input type="text" value={newClientForm.website} onChange={(e) => setNewClientForm((f) => ({ ...f, website: e.target.value }))} style={inputStyle} placeholder="https://..." />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>E-mail</span>
                        <input type="email" value={newClientForm.email} onChange={(e) => setNewClientForm((f) => ({ ...f, email: e.target.value }))} style={inputStyle} placeholder="email@exemplo.com" />
                      </label>
                      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ ...labelStyle, marginBottom: 0 }}>E-mail para NFe</span>
                        <input type="email" value={newClientForm.email_nfe} onChange={(e) => setNewClientForm((f) => ({ ...f, email_nfe: e.target.value }))} style={inputStyle} placeholder="nfe@exemplo.com" />
                      </label>
                    </div>
                  </div>
                </div>
              ) : null}

              {activeCreateTab === "complementar" ? (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, padding: "4px 0" }}>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ ...labelStyle, marginBottom: 0 }}>Código de regime tributário</span>
                    <input type="text" value={newClientForm.codigo_regime_tributario} onChange={(e) => setNewClientForm((f) => ({ ...f, codigo_regime_tributario: e.target.value }))} style={inputStyle} placeholder="Ex: 1 — Simples Nacional" />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ ...labelStyle, marginBottom: 0 }}>Inscrição Suframa</span>
                    <input type="text" value={newClientForm.inscricao_suframa} onChange={(e) => setNewClientForm((f) => ({ ...f, inscricao_suframa: e.target.value }))} style={inputStyle} placeholder="Inscrição Suframa" />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ ...labelStyle, marginBottom: 0 }}>Data de nascimento</span>
                    <input type="date" value={newClientForm.data_nascimento} onChange={(e) => setNewClientForm((f) => ({ ...f, data_nascimento: e.target.value }))} style={inputStyle} />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ ...labelStyle, marginBottom: 0 }}>Status no CRM</span>
                    <select value={newClientForm.status_crm} onChange={(e) => setNewClientForm((f) => ({ ...f, status_crm: e.target.value }))} style={inputStyle}>
                      <option value="cliente">Cliente</option>
                      <option value="lead">Lead</option>
                      <option value="prospect">Prospect</option>
                      <option value="inativo">Inativo</option>
                    </select>
                  </label>
                  <div style={{ gridColumn: "1 / -1", color: "var(--muted)", fontSize: 12, marginTop: 4, lineHeight: 1.6 }}>
                    Vendedor específico, condição de pagamento, lista de preço e limite de crédito serão adicionados em fase futura.
                  </div>
                </div>
              ) : null}

              {activeCreateTab === "obs" ? (
                <div style={{ padding: "4px 0" }}>
                  <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <span style={{ ...labelStyle, marginBottom: 0 }}>Observações</span>
                    <textarea
                      value={newClientForm.observacoes}
                      onChange={(e) => setNewClientForm((f) => ({ ...f, observacoes: e.target.value }))}
                      style={{ ...inputStyle, minHeight: 140, resize: "vertical" }}
                      placeholder="Observações sobre o cliente..."
                    />
                  </label>
                </div>
              ) : null}

              <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
                <Button
                  type="button"
                  onClick={closeClientModal}
                  disabled={newClientSaving}
                >
                  Cancelar
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  loading={newClientSaving}
                  disabled={newClientSaving}
                >
                  {newClientSaving ? "Salvando..." : editClientMode ? "Salvar alterações" : "Cadastrar cliente"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function DetailRow({ label, value }) {
  return (
    <div style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
      <div style={labelStyle}>{label}</div>
      <div style={{ fontWeight: 700, wordBreak: "break-word" }}>{value || "-"}</div>
    </div>
  );
}

const labelStyle = {
  color: "var(--muted)",
  fontSize: 12,
  fontWeight: 800,
  marginBottom: 4,
};

const valueStyle = {
  fontSize: 20,
  fontWeight: 900,
};

const inputStyle = {
  width: "100%",
  padding: "11px 12px",
  border: "1px solid var(--border)",
  background: "var(--bg, #fff)",
  color: "var(--text)",
  outline: "none",
};

const checkStyle = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  color: "var(--text)",
  fontWeight: 700,
  whiteSpace: "nowrap",
};

const errorStyle = {
  border: "1px solid var(--danger)",
  background: "var(--danger-soft)",
  color: "var(--danger)",
  padding: 12,
  marginBottom: 12,
};

const recencyBadgeStyle = {
  display: "inline-flex",
  alignItems: "center",
  marginTop: 6,
  padding: "4px 9px",
  borderRadius: 999,
  fontSize: 12,
  fontWeight: 900,
  border: "1px solid transparent",
  whiteSpace: "nowrap",
};

const recencyBadgeStyles = {
  fresh: {
    background: "#dcfce7",
    color: "#166534",
    borderColor: "#86efac",
  },
  warning: {
    background: "#fef3c7",
    color: "#92400e",
    borderColor: "#fcd34d",
  },
  danger: {
    background: "#fee2e2",
    color: "#991b1b",
    borderColor: "#fca5a5",
  },
  unknown: {
    background: "var(--bg, #f3f4f6)",
    color: "var(--muted)",
    borderColor: "var(--border)",
  },
};

const modalOverlayStyle = {
  position: "fixed",
  inset: 0,
  background: "rgba(15, 23, 42, 0.45)",
  zIndex: 1000,
  display: "flex",
  justifyContent: "center",
  alignItems: "flex-start",
  padding: 24,
  overflow: "auto",
};

const modalStyle = {
  width: "min(1040px, 100%)",
  maxHeight: "calc(100vh - 48px)",
  overflow: "auto",
  border: "1px solid var(--border)",
  background: "var(--panel, #fff)",
  color: "var(--text)",
  padding: 16,
};

const sectionHeaderStyle = {
  fontSize: 11,
  fontWeight: 900,
  textTransform: "uppercase",
  letterSpacing: ".07em",
  color: "var(--muted)",
  paddingBottom: 6,
  borderBottom: "1px solid var(--border)",
  marginBottom: 4,
};
