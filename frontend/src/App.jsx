import { useEffect, useState } from "react";

import { api, clearAuthSession, getAuthSession, setCurrentCompany } from "./api";
import { mountCompanySwitcher } from "./companySwitcherDom";
import Login from "./Login";
import NewQuote from "./pages/NewQuote";
import Separation from "./pages/Separation";
import SavedQuotes from "./pages/SavedQuotes";
import Home from "./pages/Home";
import ExecutiveDashboard from "./pages/ExecutiveDashboard";
import ClientWallet from "./pages/ClientWallet";
import AdminSettings from "./pages/AdminSettings";
import Catalog from "./pages/Catalog";
import Products from "./pages/Products";
import Compras from "./pages/Compras";
import partonLogo from "./assets/catalog/parton-logo.png";

import "./App.css";
import { subscribeGlobalLoading } from "./utils/globalLoading";
import { getStoredTheme, setStoredTheme, cycleTheme, initCompanyAttr } from "./ui/theme";
import { Button, Spinner } from "./ui";

/* Ãcones do menu (mantive como estava no fixo) */
function IconFolder() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M10 4l2 2h8a2 2 0 0 1 2 2v2H2V6a2 2 0 0 1 2-2h6zm12 8v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-8h20z"
      />
    </svg>
  );
}

function IconBox() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M21 7.5l-9-5-9 5V18l9 5 9-5V7.5zM12 4.7l6.5 3.6L12 12 5.5 8.3 12 4.7zm-7 5.6l6 3.3v7.2l-6-3.3v-7.2zm14 7.2l-6 3.3v-7.2l6-3.3v7.2z"
      />
    </svg>
  );
}

function IconTruck() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M3 6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2h2.5a2 2 0 0 1 1.6.8l1.9 2.5c.26.35.4.78.4 1.22V17a2 2 0 0 1-2 2h-1.2a3 3 0 0 1-5.6 0H9.8a3 3 0 0 1-5.6 0H3V6zm2 0v11h.2a3 3 0 0 1 5.6 0H15V6H5zm14 4v3h3.5l-1.5-2h-2z"
      />
    </svg>
  );
}

function IconDoc() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M6 2h9l5 5v15a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1.5V8h4.5L14 3.5zM7 12h10v2H7v-2zm0 4h10v2H7v-2z"
      />
    </svg>
  );
}

function IconClipboard() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M9 2h6a2 2 0 0 1 2 2h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2-2zm0 2v2h6V4H9zm-2 4v2h10V8H7zm0 4v2h10v-2H7zm0 4v2h7v-2H7z"
      />
    </svg>
  );
}


function IconContacts() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M7 4a3 3 0 1 1 0 6 3 3 0 0 1 0-6zm10 1a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM7 12c2.8 0 5 1.6 5 3.5V18H2v-2.5C2 13.6 4.2 12 7 12zm10 0c2.8 0 5 1.4 5 3.2V18h-8v-1.8c0-1.1-.4-2-1.1-2.8.9-.9 2.4-1.4 4.1-1.4z"
      />
    </svg>
  );
}

function IconShoppingCart() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M7 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm10 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM1 2h2l3.6 7.59-1.35 2.44A2 2 0 0 0 7 15h11v-2H7.42l1.06-1.9H17a2 2 0 0 0 1.75-1.03l3.24-5.88A1 1 0 0 0 21.1 3H5.21L4.27 1H1v1z"
      />
    </svg>
  );
}

function IconGear() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M19.4 13.5c.1-.5.1-1 .1-1.5s0-1-.1-1.5l2-1.5-2-3.5-2.4 1a7.7 7.7 0 0 0-2.6-1.5L14 2h-4l-.4 3a7.7 7.7 0 0 0-2.6 1.5l-2.4-1-2 3.5 2 1.5A8.8 8.8 0 0 0 4.5 12c0 .5 0 1 .1 1.5l-2 1.5 2 3.5 2.4-1a7.7 7.7 0 0 0 2.6 1.5l.4 3h4l.4-3a7.7 7.7 0 0 0 2.6-1.5l2.4 1 2-3.5-2-1.5zM12 15.5A3.5 3.5 0 1 1 12 8a3.5 3.5 0 0 1 0 7.5z"
      />
    </svg>
  );
}

function IconMoon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M20.3 14.9A8.9 8.9 0 0 1 9.1 3.7a1 1 0 0 0-1.1-1.3A10.9 10.9 0 1 0 21.6 16a1 1 0 0 0-1.3-1.1z"
      />
    </svg>
  );
}

function IconSun() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 5a1 1 0 0 1 1-1V2a1 1 0 0 0-2 0v2a1 1 0 0 1 1 1zm0 14a1 1 0 0 1 1 1v2a1 1 0 0 1-2 0v-2a1 1 0 0 1 1-1zm7-7a1 1 0 0 1 1-1h2a1 1 0 0 1 0 2h-2a1 1 0 0 1-1-1zM2 12a1 1 0 0 1 1-1h2a1 1 0 0 1 0 2H3a1 1 0 0 1-1-1zm15.95-5.54a1 1 0 0 1 1.41 0l1.42 1.41a1 1 0 0 1-1.42 1.42l-1.41-1.42a1 1 0 0 1 0-1.41zM4.66 18.36a1 1 0 0 1 1.41 0l1.42 1.41a1 1 0 1 1-1.42 1.42l-1.41-1.42a1 1 0 0 1 0-1.41zm13.29 3.83a1 1 0 0 1 0-1.41l1.41-1.42a1 1 0 1 1 1.42 1.42l-1.42 1.41a1 1 0 0 1-1.41 0zM4.66 5.64a1 1 0 0 1 0-1.41L6.07 2.8a1 1 0 1 1 1.42 1.42L6.07 5.64a1 1 0 0 1-1.41 0zM12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10z"
      />
    </svg>
  );
}

function IconAuto() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
      <path fill="currentColor" d="M12 4a8 8 0 0 1 0 16z" />
    </svg>
  );
}

function getInitialActiveView() {
  if (typeof window === "undefined") return "home";
  if (window.location.pathname === "/separation") return "separation";
  if (window.location.pathname === "/catalogo" || window.location.pathname === "/catalog") return "catalog";
  return "home";
}

export default function App() {
  const [sessionReady, setSessionReady] = useState(false);
  const [user, setUser] = useState(null);
  const [authMsg, setAuthMsg] = useState("");
  const [checkingAccess, setCheckingAccess] = useState(false);
  const [profile, setProfile] = useState(null);
  const [theme, setTheme] = useState(getStoredTheme); // "light" | "dark" | null (null = automático)

  const isBetaEnv =
    typeof window !== "undefined" &&
    window.location.hostname === "beta-projetotrml.web.app";

  const currentCompany = String(api.getCurrentCompany?.() || "").toLowerCase();
  const systemLabel =
    currentCompany === "parton" ? "SUPRIMENTOS" : currentCompany === "park" ? "INFORMÁTICA" : "EMPRESA";
  const systemThemeClass = "systemThemeSup";

  const [openQuotes, setOpenQuotes] = useState(false);
  const [openStock, setOpenStock] = useState(false);
  const [openPreview, setOpenPreview] = useState(false);
  const [forceEditQuoteId, setForceEditQuoteId] = useState(null);
  const [activeView, setActiveView] = useState(getInitialActiveView);
  const [globalLoadingOpen, setGlobalLoadingOpen] = useState(false);
  const [globalLoadingLabel, setGlobalLoadingLabel] = useState("Carregando...");

  useEffect(() => {
    setStoredTheme(theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      setCheckingAccess(true);
      setAuthMsg("");
      try {
        const session = getAuthSession();
        if (!session) {
          if (!cancelled) {
            setUser(null);
            setProfile(null);
          }
          return;
        }

        const me = await api.me();
        if (cancelled) return;
        setUser(me);
        setProfile(me);
        const fallbackCompany = api.getCurrentCompany?.() || me?.company || me?.company_key || me?.companies?.[0] || "parton";
        setCurrentCompany(fallbackCompany);
      } catch (e) {
        clearAuthSession();
        if (!cancelled) {
          setUser(null);
          setProfile(null);
          setAuthMsg(e?.status === 401 ? "" : (e?.message || "Erro ao validar acesso."));
        }
      } finally {
        if (!cancelled) {
          setCheckingAccess(false);
          setSessionReady(true);
        }
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionReady || !user) return;
    return mountCompanySwitcher(api);
  }, [sessionReady, user]);

  useEffect(() => {
    if (sessionReady && user) initCompanyAttr();
  }, [sessionReady, user]);

  useEffect(() => {
    return subscribeGlobalLoading((detail) => {
      setGlobalLoadingOpen(!!detail?.open);
      setGlobalLoadingLabel(detail?.label || "Carregando...");
    });
  }, []);

  async function safeSignOut() {
    const logoutRequest = api.logout().catch(() => {
      clearAuthSession();
    });

    clearAuthSession();
    setUser(null);
    setProfile(null);
    setAuthMsg("");
    setCheckingAccess(false);
    setSessionReady(true);
    setActiveView("home");
    setGlobalLoadingOpen(false);

    await logoutRequest;
  }

  if (!sessionReady || checkingAccess) return <div style={{ padding: 20 }}>Validando acesso…</div>;
  if (!user) return <Login externalError={authMsg} onLogin={async (payload) => {
    const nextUser = payload?.user || payload;
    setUser(nextUser);
    setProfile(nextUser);
    setCurrentCompany(api.getCurrentCompany?.() || nextUser?.company || nextUser?.company_key || nextUser?.companies?.[0] || "parton");
    setAuthMsg("");
    setSessionReady(true);
    setActiveView(getInitialActiveView() === "separation" || nextUser?.role === "separacao" ? "separation" : "home");
  }} />;

  const role = String(profile?.role || "").toLowerCase();
  const isAdmin = !!profile?.is_admin || role === "admin";

  const canAccessQuotes =
    typeof profile?.can_access_quotes === "boolean"
      ? profile.can_access_quotes
      : (isAdmin || role === "seller" || role === "allowed" || !role);

  const canAccessSeparation =
    typeof profile?.can_access_separation === "boolean"
      ? profile.can_access_separation
      : (isAdmin || role === "expedition");

  const expeditionOnly = role === "expedition" && !isAdmin;

  const themeLabel =
    theme === "dark"
      ? "Tema escuro (clique para tema claro)"
      : theme === "light"
      ? "Tema claro (clique para tema automático)"
      : "Tema automático — segue o sistema (clique para tema escuro)";

  const activeKey = activeView;
  const displayName = user.displayName || user.display_name || "Usuário";
  const email = user.email || user.login || user.uid;
  const photoURL = user.photoURL || "";

  return (
    <div className="appShell">
      {isBetaEnv ? (
        <div
          style={{
            background: "linear-gradient(90deg, #7c3aed, #2563eb)",
            color: "#fff",
            padding: "10px 16px",
            fontWeight: 900,
            fontSize: 13,
            letterSpacing: ".04em",
            textTransform: "uppercase",
            textAlign: "center",
            borderBottom: "1px solid rgba(255,255,255,.18)",
          }}
        >
          Ambiente Beta • Testes e homologação • Não usar para operação oficial
        </div>
      ) : null}

      <div className={`systemEnvBanner ${systemThemeClass}`}>
        Sistema ativo: {systemLabel}
      </div>
      <div className="appBodyNoTopFixed">
        <aside className="appSidebar">
          <div className="sideUserRow">
            {photoURL ? (
              <img
                src={photoURL}
                alt={displayName}
                className="sideAvatarSmall"
                referrerPolicy="no-referrer"
              />
            ) : (
              <div className="sideAvatarSmallFallback" aria-hidden="true">
                {String(displayName || "U").trim().slice(0, 1).toUpperCase()}
              </div>
            )}

            <div className="sideUserCompactText">
              <div className="sideUserCompactName" title={displayName}>
                {displayName}
              </div>
              <div className="sideUserCompactEmail" title={email}>
                {email}
              </div>
            </div>

            <button
              className="sideThemeBtn"
              type="button"
              onClick={() => setTheme((current) => cycleTheme(current))}
              aria-label={themeLabel}
              title={themeLabel}
            >
              {theme === "dark" ? <IconMoon /> : theme === "light" ? <IconSun /> : <IconAuto />}
            </button>

            <Button variant="ghost" size="sm" onClick={safeSignOut}>
              Sair
            </Button>
          </div>

          <div className="sideBrandBlock sideBrandBlockPlain">
            <img
              src={partonLogo}
              className="sideBrandBigLogo"
              alt="Parton"
              onError={(event) => {
                event.currentTarget.style.display = "none";
              }}
            />
            <div className="sideBrandBigTitle">
              {expeditionOnly ? "Separação" : (canAccessSeparation && !canAccessQuotes ? "Separação" : "Pré-venda")}
            </div>
            <div className={`sideSystemBadge ${systemThemeClass}`}>
              {systemLabel}
            </div>
          </div>

          <div className="sideSectionTitle">Menu</div>

          {!expeditionOnly && canAccessQuotes ? (
            <>
              <a
                className={`sideItem ${activeKey === "home" ? "sideItemActive" : ""}`}
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setActiveView("home");
                }}
              >
                <span className="sideIcon" aria-hidden="true"><IconDoc /></span>
                <span className="sideText">Início</span>
              </a>

              {isAdmin ? (
                <>
                  <a
                    className={`sideItem ${activeKey === "adminSettings" ? "sideItemActive" : ""}`}
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setActiveView("adminSettings");
                    }}
                  >
                    <span className="sideIcon" aria-hidden="true"><IconGear /></span>
                    <span className="sideText">Administração</span>
                  </a>
                  <a
                    className={`sideItem ${activeKey === "catalog" ? "sideItemActive" : ""}`}
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setActiveView("catalog");
                    }}
                  >
                    <span className="sideIcon" aria-hidden="true"><IconBox /></span>
                    <span className="sideText">Catálogo</span>
                  </a>
                </>
              ) : null}

              <a
                className={`sideItem ${activeKey === "quotes" ? "sideItemActive" : ""}`}
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setActiveView("quotes");
                }}
              >
                <span className="sideIcon" aria-hidden="true"><IconClipboard /></span>
                <span className="sideText">Novo Orçamento</span>
              </a>

              <a
                className={`sideItem ${activeKey === "savedQuotes" ? "sideItemActive" : ""}`}
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setActiveView("savedQuotes");
                }}
              >
                <span className="sideIcon" aria-hidden="true"><IconFolder /></span>
                <span className="sideText">Operações</span>
              </a>

              <a
                className={`sideItem ${activeKey === "clientWallet" ? "sideItemActive" : ""}`}
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setActiveView("clientWallet");
                }}
              >
                <span className="sideIcon" aria-hidden="true"><IconContacts /></span>
                <span className="sideText">Carteira de Clientes</span>
              </a>

              {isAdmin ? (
                <>
                  <a
                    className={`sideItem ${activeKey === "products" ? "sideItemActive" : ""}`}
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setActiveView("products");
                    }}
                  >
                    <span className="sideIcon" aria-hidden="true"><IconBox /></span>
                    <span className="sideText">Produtos</span>
                  </a>
                  <a
                    className={`sideItem ${activeKey === "compras" ? "sideItemActive" : ""}`}
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setActiveView("compras");
                    }}
                  >
                    <span className="sideIcon" aria-hidden="true"><IconShoppingCart /></span>
                    <span className="sideText">Compras</span>
                  </a>
                </>
              ) : (
                <a
                  className={`sideItem ${activeKey === "stock" ? "sideItemActive" : ""}`}
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    setActiveView("quotes");
                    setOpenStock(true);
                  }}
                >
                  <span className="sideIcon" aria-hidden="true"><IconBox /></span>
                  <span className="sideText">Estoque</span>
                </a>
              )}
            </>
          ) : null}

          {expeditionOnly ? (
            <a
              className={`sideItem ${activeKey === "stock" ? "sideItemActive" : ""}`}
              href="#"
              onClick={(e) => {
                e.preventDefault();
                setActiveView("stock");
                setOpenStock(true);
              }}
            >
              <span className="sideIcon" aria-hidden="true"><IconBox /></span>
              <span className="sideText">Estoque</span>
            </a>
          ) : null}

          {canAccessSeparation ? (
            <a
              className={`sideItem ${activeKey === "separation" ? "sideItemActive" : ""}`}
              href="#"
              onClick={(e) => {
                e.preventDefault();
                setActiveView("separation");
              }}
            >
              <span className="sideIcon" aria-hidden="true"><IconTruck /></span>
              <span className="sideText">Separação</span>
            </a>
          ) : null}

          <div className="sideBottomInfo">
            <div className="sideSectionTitle">Info</div>
            <div className="sideInfoText">
              {expeditionOnly
                ? "Acesso configurado para expedição: separação e estoque."
                : (canAccessSeparation && !canAccessQuotes
                    ? "Acesso configurado para a operação de separação."
                    : "Os atalhos ficam no menu para manter a tela limpa.")}
            </div>
          </div>
        </aside>

        <main className="appMain">

          {activeView === "separation" && canAccessSeparation ? (
            <Separation />
          ) : activeView === "stock" && expeditionOnly ? (
            <NewQuote
              forceOpenQuotes={false}
              onForceOpenQuotesHandled={() => setOpenQuotes(false)}
              forceOpenStock={openStock}
              onForceOpenStockHandled={() => setOpenStock(false)}
              forceOpenPreview={false}
              onForceOpenPreviewHandled={() => setOpenPreview(false)}
              forceEditQuoteId={null}
              onForceEditQuoteHandled={() => setForceEditQuoteId(null)}
            />
          ) : activeView === "home" && canAccessQuotes && !expeditionOnly ? (
            isAdmin ? <ExecutiveDashboard user={user} profile={profile} /> : <Home user={user} profile={profile} />
          ) : activeView === "clientWallet" && canAccessQuotes && !expeditionOnly ? (
            <ClientWallet />
          ) : activeView === "savedQuotes" && canAccessQuotes && !expeditionOnly ? (
            <SavedQuotes
              onEditQuote={(quoteId) => {
                setForceEditQuoteId(quoteId);
                setActiveView("quotes");
              }}
            />
          ) : activeView === "adminSettings" && isAdmin ? (
            <AdminSettings />
          ) : activeView === "products" && isAdmin ? (
            <Products />
          ) : activeView === "compras" && isAdmin ? (
            <Compras />
          ) : activeView === "catalog" && isAdmin ? (
            <Catalog />
          ) : activeView === "catalog" ? (
            <div className="pageShell">
              <div className="card">
                <h2>Acesso restrito</h2>
                <p>O Catálogo está disponível somente para usuários administradores.</p>
              </div>
            </div>
          ) : canAccessQuotes && !expeditionOnly ? (
            <NewQuote
              forceOpenQuotes={openQuotes}
              onForceOpenQuotesHandled={() => setOpenQuotes(false)}
              forceOpenStock={openStock}
              onForceOpenStockHandled={() => setOpenStock(false)}
              forceOpenPreview={openPreview}
              onForceOpenPreviewHandled={() => setOpenPreview(false)}
              forceEditQuoteId={forceEditQuoteId}
              onForceEditQuoteHandled={() => setForceEditQuoteId(null)}
            />
          ) : canAccessSeparation ? (
            <Separation />
          ) : (
            <div style={{ padding: 24 }}>Sem acesso liberado para este usuário.</div>
          )}
        </main>
      
      </div>

      {globalLoadingOpen ? (
        <div className="appGlobalLoading">
          <Spinner size={40} label={globalLoadingLabel || "Carregando"} />
        </div>
      ) : null}
    </div>
  );
}






