import React, { useEffect, useMemo, useState } from "react";
import api from "../api";
import { PageHeader, Button, Table, Field, Card, Spinner, EmptyState } from "../ui";
import AdminSalesTargets from "./AdminSalesTargets";

const COMPANY_OPTIONS = [
  { key: "parton", label: "Suprimentos / parton" },
  { key: "park", label: "Informática / park" },
];

const ROLE_OPTIONS = [
  { value: "admin", label: "admin" },
  { value: "vendedor", label: "vendedor" },
  { value: "separacao", label: "separacao" },
];

function getToken() {
  try {
    if (typeof api.getAuthToken === "function") {
      const token = api.getAuthToken();
      if (token) return token;
    }
    if (typeof api.getAuthSession === "function") {
      const session = api.getAuthSession();
      if (session?.token) return session.token;
    }
    return (
      localStorage.getItem("erp_auth_token") ||
      localStorage.getItem("trml_auth_token") ||
      localStorage.getItem("auth_token") ||
      localStorage.getItem("token") ||
      ""
    );
  } catch {
    return "";
  }
}

async function authedJson(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || `HTTP ${response.status}`);
  }
  return payload;
}

function normalizeCompanies(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function companiesLabel(user) {
  const companies = normalizeCompanies(user.companies || user.company_keys || user.company_key_list);
  if (!companies.length) return "-";
  return companies
    .map((key) => COMPANY_OPTIONS.find((item) => item.key === key)?.label || key)
    .join(", ");
}

function boolLabel(value) {
  return value ? "Sim" : "Não";
}

function emptyForm() {
  return {
    id: "",
    login: "",
    display_name: "",
    role: "vendedor",
    active: true,
    must_change_password: true,
    password: "",
    confirmPassword: "",
    companies: ["parton", "park"],
  };
}

function emptySellerLinkForms() {
  return COMPANY_OPTIONS.reduce((acc, company) => {
    acc[company.key] = {
      id: null,
      tiny_seller_id: "",
      tiny_seller_name: "",
      active: false,
    };
    return acc;
  }, {});
}

function sellerLinkFormsFromItems(items) {
  const next = emptySellerLinkForms();
  for (const company of COMPANY_OPTIONS) {
    const link = (items || []).find((item) => item.company_key === company.key && item.active);
    if (link) {
      next[company.key] = {
        id: link.id || null,
        tiny_seller_id: link.tiny_seller_id || "",
        tiny_seller_name: link.tiny_seller_name || "",
        active: Boolean(link.active),
      };
    }
  }
  return next;
}

export default function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [audit, setAudit] = useState([]);
  const [activeTab, setActiveTab] = useState("users");
  const [form, setForm] = useState(emptyForm());
  const [sellerLinkForms, setSellerLinkForms] = useState(emptySellerLinkForms());
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [loadingSellerLinks, setLoadingSellerLinks] = useState(false);
  const [loadingLocalSellers, setLoadingLocalSellers] = useState(false);
  const [sellersByCompany, setSellersByCompany] = useState({ parton: [], park: [] });
  const [localSellersError, setLocalSellersError] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingSellerLink, setSavingSellerLink] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [v3Status, setV3Status] = useState({ parton: null, park: null });
  const [v3Loading, setV3Loading] = useState(false);
  const [v3Error, setV3Error] = useState("");
  const [v3Message, setV3Message] = useState("");
  const [v3FormOpen, setV3FormOpen] = useState(null);
  const [v3Saving, setV3Saving] = useState(false);
  const [v3Form, setV3Form] = useState({ company_key: "parton", access_token: "", refresh_token: "", expires_at: "" });
  const [v3CredFormOpen, setV3CredFormOpen] = useState(null);
  const [v3CredForm, setV3CredForm] = useState({ company_key: "parton", client_id: "", client_secret: "", redirect_uri: "" });
  const [v3CredSaving, setV3CredSaving] = useState(false);
  const [v3ConnectLoading, setV3ConnectLoading] = useState({});

  const [confMode, setConfMode] = useState(null);
  const [confLoading, setConfLoading] = useState(false);
  const [confSaving, setConfSaving] = useState(false);

  const editing = Boolean(form.id);
  const selectedCompanies = useMemo(() => new Set(form.companies), [form.companies]);

  const stats = useMemo(() => {
    const active = users.filter((u) => u.active !== false).length;
    const admins = users.filter((u) => u.active !== false && String(u.role || "").toLowerCase() === "admin").length;
    const sellers = users.filter((u) => u.active !== false && ["vendedor", "seller", "allowed"].includes(String(u.role || "").toLowerCase())).length;
    const expedition = users.filter((u) => u.active !== false && ["separacao", "expedition"].includes(String(u.role || "").toLowerCase())).length;
    return { active, admins, sellers, expedition };
  }, [users]);

  const loadUsers = async () => {
    setLoadingUsers(true);
    setError("");
    try {
      const response = typeof api.adminListUsers === "function"
        ? await api.adminListUsers()
        : await authedJson("/api/admin/users");
      setUsers(Array.isArray(response?.users) ? response.users : Array.isArray(response?.items) ? response.items : []);
    } catch (err) {
      setError(err.message || "Falha ao carregar usuários.");
    } finally {
      setLoadingUsers(false);
    }
  };

  const loadAudit = async () => {
    setLoadingAudit(true);
    setError("");
    try {
      const response = await authedJson("/api/admin/users/audit");
      setAudit(Array.isArray(response?.items) ? response.items : Array.isArray(response?.logs) ? response.logs : []);
    } catch {
      setAudit([]);
    } finally {
      setLoadingAudit(false);
    }
  };

  const loadAdminSellers = async () => {
    setLoadingLocalSellers(true);
    setLocalSellersError("");
    try {
      const entries = await Promise.all(
        COMPANY_OPTIONS.map(async (company) => {
          const response = typeof api.adminListSellers === "function"
            ? await api.adminListSellers({ company: company.key })
            : await authedJson(`/api/admin/sellers?company=${encodeURIComponent(company.key)}`);
          return [company.key, Array.isArray(response?.sellers) ? response.sellers : []];
        })
      );
      setSellersByCompany(Object.fromEntries(entries));
    } catch {
      setSellersByCompany({ parton: [], park: [] });
      setLocalSellersError("Não foi possível carregar vendedores locais. Use preenchimento manual.");
    } finally {
      setLoadingLocalSellers(false);
    }
  };

  const loadConferencia = async () => {
    setConfLoading(true);
    setError("");
    try {
      const r = typeof api.getConferenciaSetting === "function"
        ? await api.getConferenciaSetting()
        : await authedJson("/api/admin/settings/conferencia");
      setConfMode(String(r?.mode || "off"));
    } catch (err) {
      setError(err.message || "Falha ao carregar a configuração de conferência.");
    } finally {
      setConfLoading(false);
    }
  };

  const saveConferenciaMode = async (mode) => {
    setConfSaving(true);
    setError("");
    setMessage("");
    try {
      const r = typeof api.setConferenciaSetting === "function"
        ? await api.setConferenciaSetting(mode)
        : await authedJson("/api/admin/settings/conferencia", { method: "PUT", body: JSON.stringify({ mode }) });
      const saved = String(r?.mode || mode);
      setConfMode(saved);
      setMessage(saved === "off" ? "Conferência da separação desativada." : `Conferência da separação ativada (${saved}).`);
    } catch (err) {
      setError(err.message || "Falha ao salvar a configuração.");
    } finally {
      setConfSaving(false);
    }
  };

  useEffect(() => {
    loadUsers();
    loadAdminSellers();
  }, []);

  useEffect(() => {
    if (activeTab === "audit" && !audit.length && !loadingAudit) {
      loadAudit();
    }
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === "v3tokens" && !v3Status.parton && !v3Status.park && !v3Loading) {
      loadV3Status();
    }
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === "conferencia" && confMode === null && !confLoading) {
      loadConferencia();
    }
  }, [activeTab]);

  const resetForm = () => {
    setForm(emptyForm());
    setSellerLinkForms(emptySellerLinkForms());
    setLoadingSellerLinks(false);
    setSavingSellerLink("");
    setError("");
    setMessage("");
  };

  const loadUserSellerLinks = async (userId) => {
    if (!userId) {
      setSellerLinkForms(emptySellerLinkForms());
      return;
    }
    setLoadingSellerLinks(true);
    try {
      const response = typeof api.adminGetUserSellerLinks === "function"
        ? await api.adminGetUserSellerLinks(userId)
        : await authedJson(`/api/admin/users/${encodeURIComponent(userId)}/seller-links`);
      const items = Array.isArray(response?.items) ? response.items : [];
      setSellerLinkForms(sellerLinkFormsFromItems(items));
    } catch (err) {
      setSellerLinkForms(emptySellerLinkForms());
      setError(err.message || "Falha ao carregar vínculos de vendedor Tiny.");
    } finally {
      setLoadingSellerLinks(false);
    }
  };

  const startEdit = (user) => {
    setActiveTab("users");
    setForm({
      id: user.id || "",
      login: user.login || "",
      display_name: user.display_name || user.name || "",
      role: user.role || "vendedor",
      active: user.active !== false,
      must_change_password: Boolean(user.must_change_password),
      password: "",
      confirmPassword: "",
      companies: normalizeCompanies(user.companies || user.company_keys || user.company_key_list),
    });
    setError("");
    setMessage("");
    loadUserSellerLinks(user.id || "");
  };

  const toggleCompany = (companyKey) => {
    setForm((current) => {
      const next = new Set(current.companies);
      if (next.has(companyKey)) next.delete(companyKey);
      else next.add(companyKey);
      return { ...current, companies: Array.from(next) };
    });
  };

  const refreshAll = async () => {
    await loadUsers();
    if (activeTab === "audit") {
      await loadAudit();
    }
  };

  const loadV3Status = async () => {
    setV3Loading(true);
    setV3Error("");
    try {
      const [partonRes, parkRes] = await Promise.all([
        typeof api.adminV3Status === "function"
          ? api.adminV3Status({ company: "parton" })
          : authedJson("/api/admin/v3-status?company=parton"),
        typeof api.adminV3Status === "function"
          ? api.adminV3Status({ company: "park" })
          : authedJson("/api/admin/v3-status?company=park"),
      ]);
      setV3Status({ parton: partonRes || null, park: parkRes || null });
    } catch (err) {
      setV3Error(err.message || "Falha ao carregar status V3.");
    } finally {
      setV3Loading(false);
    }
  };

  const openV3Form = (companyKey) => {
    setV3FormOpen(companyKey);
    setV3Form({ company_key: companyKey, access_token: "", refresh_token: "", expires_at: "" });
    setV3Error("");
    setV3Message("");
    setV3CredFormOpen(null);
  };

  const handleSaveV3Token = async (event) => {
    event.preventDefault();
    if (!v3Form.access_token.trim()) {
      setV3Error("access_token é obrigatório.");
      return;
    }
    setV3Saving(true);
    setV3Error("");
    setV3Message("");
    try {
      const payload = {
        company_key: v3Form.company_key,
        access_token: v3Form.access_token.trim(),
      };
      if (v3Form.refresh_token.trim()) payload.refresh_token = v3Form.refresh_token.trim();
      if (v3Form.expires_at.trim()) payload.expires_at = v3Form.expires_at.trim();
      const response = typeof api.adminSaveV3Token === "function"
        ? await api.adminSaveV3Token(payload)
        : await authedJson("/api/admin/v3-token", { method: "POST", body: JSON.stringify(payload) });
      setV3Message(response?.message || `Token V3 salvo para ${v3Form.company_key}.`);
      setV3Form((f) => ({ ...f, access_token: "", refresh_token: "" }));
      setV3FormOpen(null);
      await loadV3Status();
    } catch (err) {
      setV3Error(err.message || "Falha ao salvar token V3.");
    } finally {
      setV3Saving(false);
    }
  };

  const openV3CredForm = (companyKey) => {
    setV3CredFormOpen(companyKey);
    setV3CredForm({ company_key: companyKey, client_id: "", client_secret: "", redirect_uri: "" });
    setV3Error("");
    setV3Message("");
    setV3FormOpen(null);
  };

  const handleSaveV3Credentials = async (event) => {
    event.preventDefault();
    const cid = v3CredForm.client_id.trim();
    const csec = v3CredForm.client_secret.trim();
    if (!cid || !csec) {
      setV3Error("client_id e client_secret são obrigatórios.");
      return;
    }
    setV3CredSaving(true);
    setV3Error("");
    setV3Message("");
    try {
      const payload = { company_key: v3CredForm.company_key, client_id: cid, client_secret: csec };
      if (v3CredForm.redirect_uri.trim()) payload.redirect_uri = v3CredForm.redirect_uri.trim();
      const response = typeof api.adminSaveV3Credentials === "function"
        ? await api.adminSaveV3Credentials(payload)
        : await authedJson("/api/admin/tiny-v3/credentials", { method: "POST", body: JSON.stringify(payload) });
      setV3Message(response?.message || `Credenciais OAuth salvas para ${v3CredForm.company_key}.`);
      setV3CredForm((f) => ({ ...f, client_id: "", client_secret: "", redirect_uri: "" }));
      setV3CredFormOpen(null);
      await loadV3Status();
    } catch (err) {
      setV3Error(err.message || "Falha ao salvar credenciais OAuth.");
    } finally {
      setV3CredSaving(false);
    }
  };

  const handleConnectTiny = async (companyKey) => {
    setV3ConnectLoading((prev) => ({ ...prev, [companyKey]: true }));
    setV3Error("");
    setV3Message("");
    try {
      const response = typeof api.adminV3AuthUrl === "function"
        ? await api.adminV3AuthUrl({ company: companyKey })
        : await authedJson(`/api/admin/tiny-v3/auth-url?company=${encodeURIComponent(companyKey)}`);
      const authUrl = response?.auth_url;
      if (!authUrl) throw new Error("URL de autorização não retornada pelo servidor.");
      window.open(authUrl, "_blank", "noopener,noreferrer");
      setV3Message("URL de autorização aberta em nova aba. Conclua a autorização no Tiny/Olist e aguarde o redirecionamento de volta.");
    } catch (err) {
      setV3Error(err.message || "Falha ao gerar URL de autorização.");
    } finally {
      setV3ConnectLoading((prev) => ({ ...prev, [companyKey]: false }));
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");

    if (form.password || form.confirmPassword) {
      if (form.password !== form.confirmPassword) {
        setSaving(false);
        setError("As senhas não conferem.");
        return;
      }
    }

    const payload = {
      login: form.login.trim(),
      display_name: form.display_name.trim(),
      role: form.role,
      active: Boolean(form.active),
      must_change_password: Boolean(form.must_change_password),
    };

    if (!editing || form.password.trim()) {
      payload.password = form.password.trim();
    }

    try {
      if (editing) {
        if (typeof api.adminUpdateUser === "function") {
          await api.adminUpdateUser(form.id, payload);
        } else {
          await authedJson(`/api/admin/users/${form.id}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          });
        }

        if (typeof api.adminSetUserCompanies === "function") {
          await api.adminSetUserCompanies(form.id, form.companies);
        } else {
          await authedJson(`/api/admin/users/${form.id}/set-companies`, {
            method: "POST",
            body: JSON.stringify({ companies: form.companies }),
          });
        }

        if (form.password.trim()) {
          const resetPayload = {
            password: form.password.trim(),
            must_change_password: Boolean(form.must_change_password),
          };
          if (typeof api.adminResetPassword === "function") {
            await api.adminResetPassword(form.id, resetPayload);
          } else {
            await authedJson(`/api/admin/users/${form.id}/reset-password`, {
              method: "POST",
              body: JSON.stringify(resetPayload),
            });
          }
        }

        setMessage("Usuário atualizado com sucesso.");
      } else {
        let created;
        if (typeof api.adminSaveUser === "function") {
          created = await api.adminSaveUser(payload);
        } else {
          created = await authedJson("/api/admin/users", {
            method: "POST",
            body: JSON.stringify(payload),
          });
        }

        const createdId = created?.user?.id || created?.id || created?.user_id;
        if (createdId) {
          if (typeof api.adminSetUserCompanies === "function") {
            await api.adminSetUserCompanies(createdId, form.companies);
          } else {
            await authedJson(`/api/admin/users/${createdId}/set-companies`, {
              method: "POST",
              body: JSON.stringify({ companies: form.companies }),
            });
          }
        }

        setMessage("Usuário criado com sucesso.");
      }

      resetForm();
      await refreshAll();
    } catch (err) {
      setError(err.message || "Falha ao salvar usuário.");
    } finally {
      setSaving(false);
    }
  };

  const handleResetPassword = async (user) => {
    const nextPassword = window.prompt(`Nova senha para ${user.login}:`);
    if (!nextPassword) return;
    const mustChange = window.confirm("Exigir troca de senha no próximo login?");

    try {
      const payload = {
        password: nextPassword,
        must_change_password: mustChange,
      };
      if (typeof api.adminResetPassword === "function") {
        await api.adminResetPassword(user.id, payload);
      } else {
        await authedJson(`/api/admin/users/${user.id}/reset-password`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      setMessage("Senha alterada com sucesso.");
      await refreshAll();
    } catch (err) {
      setError(err.message || "Falha ao alterar senha.");
    }
  };

  const handleToggleActive = async (user) => {
    try {
      const payload = {
        login: user.login,
        display_name: user.display_name || user.name || user.login,
        role: user.role,
        active: !user.active,
        must_change_password: Boolean(user.must_change_password),
      };
      if (typeof api.adminUpdateUser === "function") {
        await api.adminUpdateUser(user.id, payload);
      } else {
        await authedJson(`/api/admin/users/${user.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      }
      setMessage(user.active ? "Usuário desativado." : "Usuário ativado.");
      await refreshAll();
    } catch (err) {
      setError(err.message || "Falha ao alterar status do usuário.");
    }
  };

  const openCompanies = (user) => {
    startEdit(user);
    setMessage("Edite as empresas permitidas no formulário abaixo e salve.");
  };

  const updateSellerLinkField = (companyKey, field, value) => {
    setSellerLinkForms((current) => ({
      ...current,
      [companyKey]: {
        ...(current[companyKey] || emptySellerLinkForms()[companyKey]),
        [field]: value,
      },
    }));
  };

  const handleSelectLocalSeller = (companyKey, sellerId) => {
    const seller = (sellersByCompany[companyKey] || []).find((item) => String(item.seller_id || "") === String(sellerId || ""));
    if (!seller) return;
    setSellerLinkForms((current) => ({
      ...current,
      [companyKey]: {
        ...(current[companyKey] || emptySellerLinkForms()[companyKey]),
        tiny_seller_id: seller.seller_id || "",
        tiny_seller_name: seller.seller_name || seller.seller_id || "",
      },
    }));
  };

  const handleSaveSellerLink = async (companyKey) => {
    if (!form.id) {
      setError("Selecione um usuário antes de vincular vendedor Tiny.");
      return;
    }
    const link = sellerLinkForms[companyKey] || {};
    const payload = {
      tiny_seller_id: String(link.tiny_seller_id || "").trim(),
      tiny_seller_name: String(link.tiny_seller_name || "").trim(),
    };
    if (!payload.tiny_seller_id || !payload.tiny_seller_name) {
      setError("Informe ID e nome do vendedor Tiny antes de salvar.");
      return;
    }

    setSavingSellerLink(`save:${companyKey}`);
    setError("");
    setMessage("");
    try {
      if (typeof api.adminSaveUserSellerLink === "function") {
        await api.adminSaveUserSellerLink(form.id, companyKey, payload);
      } else {
        await authedJson(`/api/admin/users/${encodeURIComponent(form.id)}/seller-links/${encodeURIComponent(companyKey)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      }
      setMessage("Vínculo de vendedor Tiny salvo com sucesso.");
      await loadUserSellerLinks(form.id);
    } catch (err) {
      setError(err.message || "Falha ao salvar vínculo de vendedor Tiny.");
    } finally {
      setSavingSellerLink("");
    }
  };

  const handleDeleteSellerLink = async (companyKey) => {
    if (!form.id) {
      setError("Selecione um usuário antes de remover vínculo.");
      return;
    }

    setSavingSellerLink(`delete:${companyKey}`);
    setError("");
    setMessage("");
    try {
      if (typeof api.adminDeleteUserSellerLink === "function") {
        await api.adminDeleteUserSellerLink(form.id, companyKey);
      } else {
        await authedJson(`/api/admin/users/${encodeURIComponent(form.id)}/seller-links/${encodeURIComponent(companyKey)}`, {
          method: "DELETE",
        });
      }
      setMessage("Vínculo de vendedor Tiny removido.");
      await loadUserSellerLinks(form.id);
    } catch (err) {
      setError(err.message || "Falha ao remover vínculo de vendedor Tiny.");
    } finally {
      setSavingSellerLink("");
    }
  };

  return (
    <div className="adminUsersPage">
      <PageHeader
        crumb="Painel administrativo"
        title="Usuários e permissões"
        actions={
          <>
            <Button type="button" variant="secondary" onClick={refreshAll} loading={loadingUsers}>
              Atualizar
            </Button>
            <Button type="button" variant="primary" onClick={resetForm}>
              Novo usuário
            </Button>
          </>
        }
      />
      <p style={{ color: "var(--muted)", marginTop: 0, marginBottom: "var(--space-4)", fontSize: "var(--text-sm)" }}>
        Gerencie logins, senhas, perfis, empresas permitidas e status dos usuários do ERP local.
      </p>

      <div className="adminTabs">
        <button type="button" onClick={() => setActiveTab("users")} className={activeTab === "users" ? "adminTab active" : "adminTab"}>
          Usuários
        </button>
        <button type="button" onClick={() => setActiveTab("audit")} className={activeTab === "audit" ? "adminTab active" : "adminTab"}>
          Histórico de alterações
        </button>
        <button type="button" onClick={() => setActiveTab("v3tokens")} className={activeTab === "v3tokens" ? "adminTab active" : "adminTab"}>
          Tiny V3
        </button>
        <button type="button" onClick={() => setActiveTab("conferencia")} className={activeTab === "conferencia" ? "adminTab active" : "adminTab"}>
          Conferência
        </button>
        <button type="button" onClick={() => setActiveTab("metas")} className={activeTab === "metas" ? "adminTab active" : "adminTab"}>
          Metas
        </button>
      </div>

      <div className="adminSummaryGrid">
        <div className="adminSummaryCard">
          <span>Ativos</span>
          <strong>{stats.active}</strong>
        </div>
        <div className="adminSummaryCard">
          <span>Admins</span>
          <strong>{stats.admins}</strong>
        </div>
        <div className="adminSummaryCard">
          <span>Vendedores</span>
          <strong>{stats.sellers}</strong>
        </div>
        <div className="adminSummaryCard">
          <span>Separação</span>
          <strong>{stats.expedition}</strong>
        </div>
      </div>

      {message ? <div className="adminAlert success">{message}</div> : null}
      {error ? <div className="adminAlert error">{error}</div> : null}

      {activeTab === "conferencia" ? (
        <div style={{ display: "grid", gap: 14, maxWidth: 640 }}>
          <div style={{ color: "var(--muted)", fontSize: 12, fontWeight: 700, lineHeight: 1.6 }}>
            Liga/desliga a etapa de Conferência da separação (com foto) em produção,
            sem reiniciar o ERP. A mudança vale para todos no próximo carregamento da
            tela de Separação. <strong>soft</strong> = foto opcional; <strong>strict</strong> = foto obrigatória.
          </div>

          {confLoading && confMode === null ? (
            <div style={{ padding: 12, color: "var(--muted)" }}>Carregando...</div>
          ) : (
            <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 16, display: "grid", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontWeight: 700 }}>Conferência da separação + foto</div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>
                    Status:{" "}
                    <strong style={{ color: confMode && confMode !== "off" ? "#16a34a" : "#ef4444" }}>
                      {confMode === "off"
                        ? "Desativada"
                        : confMode === "strict"
                        ? "Ativada — foto obrigatória"
                        : confMode === "soft"
                        ? "Ativada — foto opcional"
                        : "—"}
                    </strong>
                  </div>
                </div>
                <select
                  value={confMode || "off"}
                  disabled={confSaving || confMode === null}
                  onChange={(e) => saveConferenciaMode(e.target.value)}
                  style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--card, rgba(255,255,255,0.04))", color: "inherit", fontWeight: 700 }}
                >
                  <option value="off">Desativada</option>
                  <option value="soft">Ativada — foto opcional (soft)</option>
                  <option value="strict">Ativada — foto obrigatória (strict)</option>
                </select>
              </div>
              {confSaving ? <div style={{ fontSize: 12, color: "var(--muted)" }}>Salvando...</div> : null}
            </div>
          )}
        </div>
      ) : activeTab === "users" ? (
        <>
          <div style={{ marginBottom: 10, color: "var(--muted)", fontSize: 12, fontWeight: 700 }}>
            Preencha os dados abaixo e use as ações da tabela para editar, resetar senha ou alternar o status.
          </div>
          <form onSubmit={handleSubmit} className="adminUserForm">
            <div className="adminFormGrid">
              <Field label="Login">
                <input value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} required />
              </Field>
              <Field label="Nome">
                <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
              </Field>
              <Field label="Perfil">
                <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  {ROLE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={`Senha ${editing ? "(opcional)" : ""}`}>
                <input
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder={editing ? "Deixe em branco para manter" : ""}
                />
              </Field>
              <Field label="Confirmar senha">
                <input
                  type="password"
                  value={form.confirmPassword}
                  onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })}
                  placeholder={editing ? "Confirme apenas se for alterar" : ""}
                />
              </Field>
            </div>

            <div>
              <div style={{ marginBottom: 8, fontSize: 12, fontWeight: 800, color: "var(--muted)", letterSpacing: ".08em", textTransform: "uppercase" }}>
                Empresas permitidas
              </div>
              <div className="adminCheckGrid">
                {COMPANY_OPTIONS.map((company) => (
                  <label key={company.key}>
                    <input type="checkbox" checked={selectedCompanies.has(company.key)} onChange={() => toggleCompany(company.key)} />
                    <span>{company.label}</span>
                  </label>
                ))}
              </div>
            </div>

            {editing ? (
              <div className="user-seller-links">
                <div className="user-seller-links__header">
                  <div>
                    <div className="user-seller-links__title">Vendedor Tiny vinculado</div>
                    <div className="user-seller-links__hint">
                      Configure manualmente o vendedor Tiny por empresa. Esta fase não aplica filtros em Home ou Carteira.
                    </div>
                  </div>
                  {loadingSellerLinks ? <span className="adminStatusPill neutral">Carregando...</span> : null}
                </div>

                <div className="user-seller-link-grid">
                  {COMPANY_OPTIONS.map((company) => {
                    const link = sellerLinkForms[company.key] || {};
                    const savingThis = savingSellerLink.endsWith(`:${company.key}`);
                    const localSellers = sellersByCompany[company.key] || [];
                    const selectedLocalSeller = localSellers.some((seller) => String(seller.seller_id || "") === String(link.tiny_seller_id || ""))
                      ? String(link.tiny_seller_id || "")
                      : "";
                    return (
                      <div className="user-seller-link-card" key={company.key}>
                        <div className="user-seller-link-card__top">
                          <strong>{company.key === "parton" ? "Suprimentos" : "Informática"}</strong>
                          <span className={link.active ? "adminStatusPill active" : "adminStatusPill neutral"}>
                            {link.active ? "Vinculado" : company.key}
                          </span>
                        </div>

                        <label>
                          <div>Selecionar vendedor local</div>
                          <select
                            value={selectedLocalSeller}
                            onChange={(e) => handleSelectLocalSeller(company.key, e.target.value)}
                            disabled={loadingLocalSellers || Boolean(savingSellerLink)}
                          >
                            <option value="">Selecionar vendedor...</option>
                            {localSellers.map((seller) => (
                              <option key={seller.seller_id} value={seller.seller_id}>
                                {seller.seller_name ? `${seller.seller_name} - ${seller.seller_id}` : seller.seller_id}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="user-seller-links__hint">
                          {loadingLocalSellers
                            ? "Carregando vendedores locais..."
                            : localSellersError || (localSellers.length ? "Você também pode preencher manualmente caso o vendedor não apareça na lista." : "Nenhum vendedor local encontrado. Use preenchimento manual.")}
                        </div>

                        <div className="user-seller-link-fields">
                          <label>
                            <div>ID vendedor Tiny</div>
                            <input
                              value={link.tiny_seller_id || ""}
                              onChange={(e) => updateSellerLinkField(company.key, "tiny_seller_id", e.target.value)}
                              placeholder="Ex.: 853678578"
                            />
                          </label>
                          <label>
                            <div>Nome vendedor Tiny</div>
                            <input
                              value={link.tiny_seller_name || ""}
                              onChange={(e) => updateSellerLinkField(company.key, "tiny_seller_name", e.target.value)}
                              placeholder="Ex.: Nome do Vendedor"
                            />
                          </label>
                        </div>

                        <div className="adminFormActions">
                          <Button
                            type="button"
                            variant="primary"
                            loading={savingThis && savingSellerLink.startsWith("save:")}
                            disabled={Boolean(savingSellerLink)}
                            onClick={() => handleSaveSellerLink(company.key)}
                          >
                            {savingThis && savingSellerLink.startsWith("save:") ? "Salvando..." : "Salvar vínculo"}
                          </Button>
                          {link.active ? (
                            <Button
                              type="button"
                              variant="secondary"
                              loading={savingThis && savingSellerLink.startsWith("delete:")}
                              disabled={Boolean(savingSellerLink)}
                              onClick={() => handleDeleteSellerLink(company.key)}
                            >
                              {savingThis && savingSellerLink.startsWith("delete:") ? "Removendo..." : "Remover vínculo"}
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}

            <div className="adminCheckGrid compact">
              <label>
                <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
                <span>Ativo</span>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={form.must_change_password}
                  onChange={(e) => setForm({ ...form, must_change_password: e.target.checked })}
                />
                <span>Troca senha obrigatória</span>
              </label>
            </div>

            <div className="adminFormActions">
              <Button type="submit" variant="primary" loading={saving} disabled={saving}>
                {saving ? "Salvando..." : editing ? "Salvar alterações" : "Criar usuário"}
              </Button>
              {editing ? (
                <Button type="button" variant="secondary" onClick={resetForm}>
                  Cancelar edição
                </Button>
              ) : null}
            </div>
          </form>

          <Table>
              <thead>
                <tr>
                  <th align="left">Login</th>
                  <th align="left">Nome</th>
                  <th align="left">Perfil</th>
                  <th align="left">Empresas permitidas</th>
                  <th align="left">Ativo</th>
                  <th align="left">Trocar senha obrigatória</th>
                  <th align="left">Ações</th>
                </tr>
              </thead>
              <tbody>
                {loadingUsers && !users.length ? (
                  <tr>
                    <td colSpan={7} style={{ padding: "var(--space-4)", textAlign: "center" }}>
                      <Spinner size={18} label="Carregando usuários" />
                    </td>
                  </tr>
                ) : null}
                {users.map((user) => (
                  <tr key={user.id || user.login}>
                    <td>{user.login}</td>
                    <td>{user.display_name || user.name}</td>
                    <td>
                      <span className="adminStatusPill neutral" style={{ textTransform: "capitalize" }}>
                        {user.role}
                      </span>
                    </td>
                    <td>{companiesLabel(user)}</td>
                    <td><span className={user.active ? "adminStatusPill active" : "adminStatusPill inactive"}>{boolLabel(user.active)}</span></td>
                    <td><span className={user.must_change_password ? "adminStatusPill warning" : "adminStatusPill neutral"}>{boolLabel(user.must_change_password)}</span></td>
                    <td>
                      <div className="adminRowActions">
                        <Button type="button" size="sm" variant="secondary" onClick={() => startEdit(user)}>
                          Editar
                        </Button>
                        <Button type="button" size="sm" variant="secondary" onClick={() => openCompanies(user)}>
                          Empresas
                        </Button>
                        <Button type="button" size="sm" variant="secondary" onClick={() => handleResetPassword(user)}>
                          Alterar senha
                        </Button>
                        <Button type="button" size="sm" variant="secondary" onClick={() => handleToggleActive(user)}>
                          {user.active ? "Desativar" : "Ativar"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!loadingUsers && !users.length ? (
                  <tr>
                    <td colSpan={7}>
                      <EmptyState
                        title="Nenhum usuário encontrado"
                        message="Crie um novo usuário para começar."
                        action={<Button type="button" variant="primary" size="sm" onClick={resetForm}>Novo usuário</Button>}
                      />
                    </td>
                  </tr>
                ) : null}
              </tbody>
          </Table>
        </>
      ) : activeTab === "v3tokens" ? (
        <>
          <div style={{ marginBottom: 10, color: "var(--muted)", fontSize: 12, fontWeight: 700 }}>
            Configure os tokens Tiny API V3 por empresa. Tokens ficam no banco local e serão usados pelos módulos V3.
          </div>
          <div style={{ marginBottom: 16, padding: "10px 14px", border: "1px solid var(--border)", background: "var(--info-soft)", color: "var(--muted)", fontSize: 12, lineHeight: 1.6 }}>
            Tokens e client_secret não são exibidos após salvar. Configure as credenciais OAuth (Client ID e Client Secret), depois clique em "Conectar com Tiny" para iniciar o fluxo OAuth. O token manual continua disponível como fallback.
          </div>

          {v3Message ? <div className="adminAlert success" style={{ marginBottom: 12 }}>{v3Message}</div> : null}
          {v3Error ? <div className="adminAlert error" style={{ marginBottom: 12 }}>{v3Error}</div> : null}

          {v3Loading && !v3Status.parton && !v3Status.park ? (
            <div style={{ padding: 12, color: "var(--muted)", display: "flex", alignItems: "center", gap: 8 }}>
              <Spinner size={16} label="Carregando status V3" /> Carregando status V3...
            </div>
          ) : null}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14, marginBottom: 16 }}>
            {COMPANY_OPTIONS.map((company) => {
              const st = v3Status[company.key];
              const isOpen = v3FormOpen === company.key;
              const isCredOpen = v3CredFormOpen === company.key;

              const badgeLabel = !st ? null
                : !st.has_access_token ? "sem token"
                : st.is_expired === true ? "expirado"
                : st.is_expired === false ? "válido"
                : "sem data de expiração";

              const badgeClass = badgeLabel === "válido" ? "active"
                : badgeLabel === "expirado" ? "inactive"
                : "neutral";

              return (
                <Card key={company.key} padding="md">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <div>
                      <div style={{ fontWeight: 900, fontSize: 15 }}>{company.label}</div>
                      <div style={{ color: "var(--muted)", fontSize: 12 }}>Tiny API V3</div>
                    </div>
                    {st && badgeLabel ? (
                      <span className={`adminStatusPill ${badgeClass}`} style={{ textTransform: "none" }}>{badgeLabel}</span>
                    ) : null}
                  </div>

                  {!st && !v3Loading ? (
                    <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 12 }}>Status indisponível.</div>
                  ) : st ? (
                    <>
                      <div style={{ fontSize: 11, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>OAuth</div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12, fontSize: 13 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "var(--muted)", minWidth: 120 }}>Client ID:</span>
                          {st.has_client_id ? (
                            <>
                              <span className="adminStatusPill active" style={{ fontSize: 11, padding: "2px 8px" }}>configurado</span>
                              {st.client_id_tail ? <span style={{ fontFamily: "monospace", opacity: 0.7, fontSize: 12 }}>{st.client_id_tail}</span> : null}
                            </>
                          ) : (
                            <span className="adminStatusPill neutral" style={{ fontSize: 11, padding: "2px 8px" }}>não configurado</span>
                          )}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "var(--muted)", minWidth: 120 }}>Client Secret:</span>
                          {st.has_client_secret ? (
                            <span className="adminStatusPill active" style={{ fontSize: 11, padding: "2px 8px" }}>configurado</span>
                          ) : (
                            <span className="adminStatusPill neutral" style={{ fontSize: 11, padding: "2px 8px" }}>não configurado</span>
                          )}
                        </div>
                        <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                          <span style={{ color: "var(--muted)", minWidth: 120 }}>Redirect URI:</span>
                          {st.redirect_uri ? (
                            <span style={{ fontFamily: "monospace", fontSize: 11, opacity: 0.8, wordBreak: "break-all" }}>{st.redirect_uri}</span>
                          ) : (
                            <span style={{ opacity: 0.5 }}>não informado</span>
                          )}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "var(--muted)", minWidth: 120 }}>Autorizado em:</span>
                          {st.authorized_at ? (
                            <span>{new Date(st.authorized_at).toLocaleString("pt-BR")}</span>
                          ) : (
                            <span style={{ opacity: 0.5 }}>ainda não autorizado</span>
                          )}
                        </div>
                        {st.oauth_state_pending ? (
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ color: "var(--muted)", minWidth: 120 }}>State pendente:</span>
                            <span className="adminStatusPill neutral" style={{ fontSize: 11, padding: "2px 8px" }}>sim</span>
                            {st.oauth_state_expires_at ? (
                              <span style={{ fontSize: 11, opacity: 0.6 }}>expira {new Date(st.oauth_state_expires_at).toLocaleTimeString("pt-BR")}</span>
                            ) : null}
                          </div>
                        ) : null}
                      </div>

                      <div style={{ borderTop: "1px solid var(--border)", margin: "8px 0 10px" }} />

                      <div style={{ fontSize: 11, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Token ativo</div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: 14, fontSize: 13 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "var(--muted)", minWidth: 120 }}>Access token:</span>
                          {st.has_access_token ? (
                            <>
                              <span className="adminStatusPill active" style={{ fontSize: 11, padding: "2px 8px" }}>configurado</span>
                              {st.access_token_tail ? <span style={{ fontFamily: "monospace", opacity: 0.7, fontSize: 12 }}>{st.access_token_tail}</span> : null}
                              {st.token_source ? <span style={{ color: "var(--muted)", fontSize: 11 }}>({st.token_source})</span> : null}
                            </>
                          ) : (
                            <span className="adminStatusPill neutral" style={{ fontSize: 11, padding: "2px 8px" }}>não configurado</span>
                          )}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "var(--muted)", minWidth: 120 }}>Refresh token:</span>
                          {st.has_refresh_token ? (
                            <>
                              <span className="adminStatusPill active" style={{ fontSize: 11, padding: "2px 8px" }}>configurado</span>
                              {st.refresh_token_tail ? <span style={{ fontFamily: "monospace", opacity: 0.7, fontSize: 12 }}>{st.refresh_token_tail}</span> : null}
                            </>
                          ) : (
                            <span className="adminStatusPill neutral" style={{ fontSize: 11, padding: "2px 8px" }}>não configurado</span>
                          )}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "var(--muted)", minWidth: 120 }}>Expira em:</span>
                          {st.expires_at
                            ? <span>{new Date(st.expires_at).toLocaleString("pt-BR")}</span>
                            : <span style={{ opacity: 0.5 }}>não informado</span>}
                        </div>
                      </div>
                    </>
                  ) : null}

                  {!isOpen && !isCredOpen ? (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => openV3CredForm(company.key)}
                        disabled={v3Loading || v3CredSaving || v3Saving}
                      >
                        Credenciais OAuth
                      </Button>
                      <Button
                        type="button"
                        variant="primary"
                        loading={!!v3ConnectLoading[company.key]}
                        onClick={() => handleConnectTiny(company.key)}
                        disabled={v3Loading || v3CredSaving || v3Saving || !!v3ConnectLoading[company.key] || !st?.has_client_id || !st?.has_client_secret}
                        title={!st?.has_client_id || !st?.has_client_secret ? "Configure as credenciais OAuth primeiro" : ""}
                      >
                        {v3ConnectLoading[company.key] ? "Aguarde..." : "Conectar com Tiny"}
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => openV3Form(company.key)}
                        disabled={v3Loading || v3Saving || v3CredSaving}
                        style={{ fontSize: 12 }}
                      >
                        Token manual
                      </Button>
                    </div>
                  ) : null}

                  {isCredOpen ? (
                    <form onSubmit={handleSaveV3Credentials} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <div style={{ fontSize: 12, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".07em" }}>
                        Credenciais OAuth — {company.label}
                      </div>
                      <Field label={<>Client ID <span style={{ color: "var(--danger)" }}>*</span></>}>
                        <input
                          type="text"
                          autoComplete="off"
                          value={v3CredForm.client_id}
                          onChange={(e) => setV3CredForm((f) => ({ ...f, client_id: e.target.value }))}
                          placeholder="Client ID do app Olist/Tiny"
                          required
                        />
                      </Field>
                      <Field label={<>Client Secret <span style={{ color: "var(--danger)" }}>*</span></>}>
                        <input
                          type="password"
                          autoComplete="new-password"
                          value={v3CredForm.client_secret}
                          onChange={(e) => setV3CredForm((f) => ({ ...f, client_secret: e.target.value }))}
                          placeholder="Client Secret do app Olist/Tiny"
                          required
                        />
                      </Field>
                      <Field label={<>Redirect URI <span style={{ fontWeight: 400, color: "var(--muted)" }}>(opcional)</span></>}>
                        <input
                          type="text"
                          value={v3CredForm.redirect_uri}
                          onChange={(e) => setV3CredForm((f) => ({ ...f, redirect_uri: e.target.value }))}
                          placeholder="https://seu-dominio.com/api/tiny-v3/oauth/callback"
                        />
                      </Field>
                      <div className="adminFormActions">
                        <Button type="submit" variant="primary" loading={v3CredSaving} disabled={v3CredSaving}>
                          {v3CredSaving ? "Salvando..." : "Salvar credenciais"}
                        </Button>
                        <Button
                          type="button"
                          variant="secondary"
                          disabled={v3CredSaving}
                          onClick={() => {
                            setV3CredFormOpen(null);
                            setV3CredForm((f) => ({ ...f, client_id: "", client_secret: "", redirect_uri: "" }));
                          }}
                        >
                          Cancelar
                        </Button>
                      </div>
                    </form>
                  ) : null}

                  {isOpen ? (
                    <form onSubmit={handleSaveV3Token} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <div style={{ fontSize: 12, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".07em" }}>
                        Token manual — {company.label}
                      </div>
                      <Field label={<>Access token <span style={{ color: "var(--danger)" }}>*</span></>}>
                        <input
                          type="password"
                          autoComplete="new-password"
                          value={v3Form.access_token}
                          onChange={(e) => setV3Form((f) => ({ ...f, access_token: e.target.value }))}
                          placeholder="Cole o access token aqui"
                          required
                        />
                      </Field>
                      <Field label={<>Refresh token <span style={{ fontWeight: 400, color: "var(--muted)" }}>(opcional)</span></>}>
                        <input
                          type="password"
                          autoComplete="new-password"
                          value={v3Form.refresh_token}
                          onChange={(e) => setV3Form((f) => ({ ...f, refresh_token: e.target.value }))}
                          placeholder="Cole o refresh token aqui (opcional)"
                        />
                      </Field>
                      <Field label={<>Expira em <span style={{ fontWeight: 400, color: "var(--muted)" }}>(opcional)</span></>}>
                        <input
                          type="text"
                          value={v3Form.expires_at}
                          onChange={(e) => setV3Form((f) => ({ ...f, expires_at: e.target.value }))}
                          placeholder="Ex: 2026-12-31T23:59:59Z"
                        />
                      </Field>
                      <div className="adminFormActions">
                        <Button type="submit" variant="primary" loading={v3Saving} disabled={v3Saving}>
                          {v3Saving ? "Salvando..." : "Salvar token"}
                        </Button>
                        <Button
                          type="button"
                          variant="secondary"
                          disabled={v3Saving}
                          onClick={() => {
                            setV3FormOpen(null);
                            setV3Form((f) => ({ ...f, access_token: "", refresh_token: "" }));
                          }}
                        >
                          Cancelar
                        </Button>
                      </div>
                    </form>
                  ) : null}
                </Card>
              );
            })}
          </div>

          <Button type="button" variant="secondary" onClick={loadV3Status} loading={v3Loading} disabled={v3Loading}>
            {v3Loading ? "Atualizando..." : "Atualizar status"}
          </Button>
        </>
      ) : activeTab === "metas" ? (
        <AdminSalesTargets />
      ) : (
        <>
          <div style={{ marginBottom: 10, color: "var(--muted)", fontSize: 12, fontWeight: 700 }}>
            O histórico mostra alterações administrativas e ajuda a auditar mudanças de acesso.
          </div>
        <Table>
            <thead>
              <tr>
                <th align="left">Data</th>
                <th align="left">Ação</th>
                <th align="left">Ator</th>
                <th align="left">Alvo</th>
              </tr>
            </thead>
            <tbody>
              {loadingAudit && !audit.length ? (
                <tr>
                  <td colSpan={4} style={{ padding: "var(--space-4)", textAlign: "center" }}>
                    <Spinner size={18} label="Carregando histórico" />
                  </td>
                </tr>
              ) : null}
              {audit.map((item) => (
                <tr key={item.id}>
                  <td>{item.created_at ? new Date(item.created_at).toLocaleString("pt-BR") : "-"}</td>
                  <td>{item.action || "-"}</td>
                  <td>{item.actor_login || "-"}</td>
                  <td>{item.target_login || "-"}</td>
                </tr>
              ))}
              {!loadingAudit && !audit.length ? (
                <tr>
                  <td colSpan={4}>
                    <EmptyState title="Nenhum registro encontrado" message="As alterações administrativas aparecerão aqui." />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </Table>
        </>
      )}
    </div>
  );
}
