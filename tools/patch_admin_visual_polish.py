from pathlib import Path

base = Path(r"C:\TRML_LOCAL\ERP\frontend\src")
admin_settings = base / "pages" / "AdminSettings.jsx"
admin_users = base / "pages" / "AdminUsers.jsx"
app_css = base / "App.css"

# 1) Remove titulo duplicado do AdminSettings e deixa ele ser apenas o container visual.
admin_settings.write_text(
'''import AdminUsers from "./AdminUsers";

export default function AdminSettings() {
  return (
    <div className="adminSettingsShell">
      <AdminUsers />
    </div>
  );
}
''',
encoding="utf-8"
)

# 2) Ajustes leves no AdminUsers: classes visuais e titulo mais correto.
txt = admin_users.read_text(encoding="utf-8", errors="replace")

txt = txt.replace(
'''  const editing = Boolean(form.id);
  const selectedCompanies = useMemo(() => new Set(form.companies), [form.companies]);
''',
'''  const editing = Boolean(form.id);
  const selectedCompanies = useMemo(() => new Set(form.companies), [form.companies]);

  const stats = useMemo(() => {
    const active = users.filter((u) => u.active !== false).length;
    const admins = users.filter((u) => u.active !== false && String(u.role || "").toLowerCase() === "admin").length;
    const sellers = users.filter((u) => u.active !== false && ["vendedor", "seller", "allowed"].includes(String(u.role || "").toLowerCase())).length;
    const expedition = users.filter((u) => u.active !== false && ["separacao", "expedition"].includes(String(u.role || "").toLowerCase())).length;
    return { active, admins, sellers, expedition };
  }, [users]);
'''
)

txt = txt.replace(
'''    <div style={{ padding: 20, maxWidth: 1400 }}>''',
'''    <div className="adminUsersPage">'''
)

txt = txt.replace(
'''      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 16 }}>''',
'''      <div className="adminUsersHeader">'''
)

txt = txt.replace(
'''          <h2 style={{ margin: 0 }}>Administração</h2>
          <p style={{ margin: "4px 0 0", color: "#666" }}>Gerencie usuários, senha, perfil, empresas e status.</p>''',
'''          <p className="adminEyebrow">Painel administrativo</p>
          <h2>Usuários e permissões</h2>
          <p>Gerencie logins, senhas, perfis, empresas permitidas e status dos usuários do ERP local.</p>'''
)

txt = txt.replace(
'''        <button type="button" onClick={resetForm}>
          Novo usuário
        </button>''',
'''        <button type="button" className="adminPrimaryBtn" onClick={resetForm}>
          Novo usuário
        </button>''',
1
)

txt = txt.replace(
'''      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>''',
'''      <div className="adminTabs">'''
)

txt = txt.replace(
'''        <button type="button" onClick={() => setActiveTab("users")} style={{ fontWeight: activeTab === "users" ? 700 : 400 }}>
          Usuários
        </button>''',
'''        <button type="button" onClick={() => setActiveTab("users")} className={activeTab === "users" ? "adminTab active" : "adminTab"}>
          Usuários
        </button>'''
)

txt = txt.replace(
'''        <button type="button" onClick={() => setActiveTab("audit")} style={{ fontWeight: activeTab === "audit" ? 700 : 400 }}>
          Histórico de alterações
        </button>''',
'''        <button type="button" onClick={() => setActiveTab("audit")} className={activeTab === "audit" ? "adminTab active" : "adminTab"}>
          Histórico de alterações
        </button>'''
)

txt = txt.replace(
'''      {message ? <div style={{ marginBottom: 12, color: "#0a7a2f" }}>{message}</div> : null}
      {error ? <div style={{ marginBottom: 12, color: "#b00020" }}>{error}</div> : null}''',
'''      <div className="adminSummaryGrid">
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
      {error ? <div className="adminAlert error">{error}</div> : null}'''
)

txt = txt.replace(
'''          <form onSubmit={handleSubmit} style={{ display: "grid", gap: 12, marginBottom: 20, padding: 16, border: "1px solid #ddd", borderRadius: 8 }}>''',
'''          <form onSubmit={handleSubmit} className="adminUserForm">'''
)

txt = txt.replace(
'''            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>''',
'''            <div className="adminFormGrid">'''
)

txt = txt.replace(
'''              <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>''',
'''              <div className="adminCheckGrid">''',
1
)

txt = txt.replace(
'''            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>''',
'''            <div className="adminCheckGrid compact">''',
1
)

txt = txt.replace(
'''            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>''',
'''            <div className="adminFormActions">''',
1
)

txt = txt.replace(
'''              <button type="submit" disabled={saving}>''',
'''              <button type="submit" className="adminPrimaryBtn" disabled={saving}>''',
1
)

txt = txt.replace(
'''                <button type="button" onClick={resetForm}>''',
'''                <button type="button" className="adminSecondaryBtn" onClick={resetForm}>''',
1
)

txt = txt.replace(
'''          <div style={{ overflowX: "auto" }}>''',
'''          <div className="adminTableWrap">''',
1
)

txt = txt.replace(
'''        <div style={{ overflowX: "auto" }}>''',
'''        <div className="adminTableWrap">''',
1
)

txt = txt.replace(
'''<table style={{ width: "100%", borderCollapse: "collapse" }}>''',
'''<table className="adminUsersTable">'''
)

txt = txt.replace(
'''<td>{boolLabel(user.active)}</td>''',
'''<td><span className={user.active ? "adminStatusPill active" : "adminStatusPill inactive"}>{boolLabel(user.active)}</span></td>'''
)

txt = txt.replace(
'''<td>{boolLabel(user.must_change_password)}</td>''',
'''<td><span className={user.must_change_password ? "adminStatusPill warning" : "adminStatusPill neutral"}>{boolLabel(user.must_change_password)}</span></td>'''
)

txt = txt.replace(
'''<div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>''',
'''<div className="adminRowActions">'''
)

admin_users.write_text(txt, encoding="utf-8")

# 3) CSS visual da tela Admin.
css = r'''

/* =========================================================
   ADMINISTRACAO / USUARIOS - visual polish local
   ========================================================= */

.adminSettingsShell{
  width: 100%;
  max-width: 1500px;
  margin: 0 auto;
  padding: 18px 24px 34px;
}

.adminUsersPage{
  width: 100%;
  max-width: 1460px;
  margin: 0 auto;
}

.adminUsersHeader{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  margin-bottom: 18px;
  padding: 20px 22px;
  border: 1px solid rgba(148,163,184,.18);
  background:
    radial-gradient(circle at top left, rgba(59,130,246,.13), transparent 32%),
    linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.015));
  box-shadow: 0 18px 40px rgba(0,0,0,.18);
}

.adminUsersHeader h2{
  margin: 2px 0 0;
  font-size: 26px;
  line-height: 1.1;
  letter-spacing: -.03em;
  color: var(--text);
}

.adminUsersHeader p{
  margin: 8px 0 0;
  max-width: 820px;
  color: var(--muted);
  line-height: 1.45;
}

.adminEyebrow{
  margin: 0 !important;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: rgba(96,165,250,.95) !important;
}

.adminTabs{
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding: 4px;
  width: fit-content;
  border: 1px solid rgba(148,163,184,.16);
  background: rgba(15,23,42,.18);
}

.adminTab,
.adminUsersPage button{
  min-height: 34px;
  border: 1px solid rgba(148,163,184,.22);
  background: rgba(15,23,42,.28);
  color: var(--text);
  font-weight: 900;
  font-size: 12px;
  padding: 0 12px;
  cursor: pointer;
  transition: transform .06s ease, background .12s ease, border-color .12s ease, box-shadow .12s ease;
}

.adminUsersPage button:hover{
  background: rgba(59,130,246,.16);
  border-color: rgba(96,165,250,.45);
}

.adminUsersPage button:active{
  transform: translateY(1px);
}

.adminTab.active{
  background: rgba(37,99,235,.92);
  border-color: rgba(96,165,250,.60);
  color: #fff;
  box-shadow: 0 10px 22px rgba(37,99,235,.24);
}

.adminPrimaryBtn{
  background: linear-gradient(180deg, rgba(59,130,246,1), rgba(37,99,235,1)) !important;
  border-color: rgba(147,197,253,.55) !important;
  color: #fff !important;
  box-shadow: 0 12px 24px rgba(37,99,235,.20);
}

.adminSecondaryBtn{
  background: rgba(15,23,42,.30) !important;
}

.adminSummaryGrid{
  display: grid;
  grid-template-columns: repeat(4, minmax(130px, 1fr));
  gap: 12px;
  margin: 0 0 18px;
}

.adminSummaryCard{
  padding: 15px 16px;
  border: 1px solid rgba(148,163,184,.18);
  background:
    linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.015));
}

.adminSummaryCard span{
  display: block;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
}

.adminSummaryCard strong{
  display: block;
  margin-top: 6px;
  font-size: 28px;
  line-height: 1;
  color: #fff;
}

.adminAlert{
  margin: 0 0 14px;
  padding: 11px 13px;
  border: 1px solid transparent;
  font-weight: 800;
  font-size: 13px;
}

.adminAlert.success{
  color: #22c55e;
  border-color: rgba(34,197,94,.26);
  background: rgba(34,197,94,.08);
}

.adminAlert.error{
  color: #fb7185;
  border-color: rgba(251,113,133,.28);
  background: rgba(251,113,133,.08);
}

.adminUserForm{
  display: grid !important;
  gap: 16px !important;
  margin-bottom: 20px !important;
  padding: 18px !important;
  border: 1px solid rgba(148,163,184,.20) !important;
  background:
    radial-gradient(circle at top right, rgba(245,158,11,.08), transparent 30%),
    rgba(2,6,23,.22) !important;
  border-radius: 0 !important;
}

.adminFormGrid{
  display: grid !important;
  grid-template-columns: repeat(5, minmax(160px, 1fr)) !important;
  gap: 14px !important;
}

.adminUsersPage label{
  color: var(--text);
  font-size: 12px;
  font-weight: 900;
}

.adminUsersPage label > div{
  margin-bottom: 6px;
  color: rgba(191,219,254,.86);
  font-size: 11px;
  letter-spacing: .02em;
}

.adminUsersPage input,
.adminUsersPage select{
  width: 100%;
  height: 38px;
  border: 1px solid rgba(148,163,184,.25);
  background: rgba(15,23,42,.62);
  color: var(--text);
  padding: 0 10px;
  outline: none;
  box-sizing: border-box;
}

.adminUsersPage input:focus,
.adminUsersPage select:focus{
  border-color: rgba(96,165,250,.75);
  box-shadow: 0 0 0 3px rgba(59,130,246,.12);
}

.adminUsersPage input[type="checkbox"]{
  width: 16px;
  height: 16px;
  accent-color: #3b82f6;
  box-shadow: none;
}

.adminCheckGrid{
  display: flex !important;
  gap: 10px !important;
  flex-wrap: wrap !important;
}

.adminCheckGrid label{
  min-height: 34px;
  display: inline-flex !important;
  align-items: center !important;
  gap: 8px !important;
  padding: 0 12px;
  border: 1px solid rgba(148,163,184,.18);
  background: rgba(15,23,42,.28);
}

.adminCheckGrid.compact label{
  background: rgba(15,23,42,.18);
}

.adminFormActions,
.adminRowActions{
  display: flex !important;
  gap: 8px !important;
  flex-wrap: wrap !important;
  align-items: center;
}

.adminTableWrap{
  overflow: auto !important;
  border: 1px solid rgba(148,163,184,.18);
  background: rgba(2,6,23,.18);
  max-height: calc(100vh - 390px);
}

.adminUsersTable{
  width: 100%;
  min-width: 1060px;
  border-collapse: separate !important;
  border-spacing: 0 !important;
  font-size: 12px;
}

.adminUsersTable thead th{
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 12px 12px;
  border-bottom: 1px solid rgba(148,163,184,.22);
  background: rgba(15,23,42,.96);
  color: rgba(191,219,254,.92);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: .05em;
  text-transform: uppercase;
  white-space: nowrap;
}

.adminUsersTable tbody td{
  padding: 10px 12px;
  border-bottom: 1px solid rgba(148,163,184,.10);
  color: var(--text);
  vertical-align: middle;
}

.adminUsersTable tbody tr:hover td{
  background: rgba(59,130,246,.065);
}

.adminStatusPill{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  height: 24px;
  padding: 0 9px;
  border: 1px solid rgba(148,163,184,.20);
  font-size: 11px;
  font-weight: 900;
}

.adminStatusPill.active{
  color: #22c55e;
  background: rgba(34,197,94,.10);
  border-color: rgba(34,197,94,.28);
}

.adminStatusPill.inactive{
  color: #fb7185;
  background: rgba(251,113,133,.08);
  border-color: rgba(251,113,133,.28);
}

.adminStatusPill.warning{
  color: #f59e0b;
  background: rgba(245,158,11,.10);
  border-color: rgba(245,158,11,.28);
}

.adminStatusPill.neutral{
  color: #94a3b8;
  background: rgba(148,163,184,.08);
}

.adminRowActions button{
  min-height: 30px;
  padding: 0 10px;
  background: rgba(15,23,42,.42);
}

.adminRowActions button:last-child{
  border-color: rgba(251,113,133,.35);
  color: #fb7185;
}

@media (max-width: 1100px){
  .adminSettingsShell{
    padding: 14px 12px 24px;
  }

  .adminFormGrid{
    grid-template-columns: repeat(2, minmax(180px, 1fr)) !important;
  }

  .adminSummaryGrid{
    grid-template-columns: repeat(2, minmax(130px, 1fr));
  }

  .adminUsersHeader{
    flex-direction: column;
  }
}
'''

current_css = app_css.read_text(encoding="utf-8", errors="replace")
if "ADMINISTRACAO / USUARIOS - visual polish local" not in current_css:
    app_css.write_text(current_css.rstrip() + "\n" + css + "\n", encoding="utf-8")

print("OK - visual da administracao aplicado")
