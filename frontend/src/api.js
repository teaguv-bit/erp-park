// Local auth session is handled with token storage in this file.

// Em produÃ§Ã£o (Firebase Hosting), SEMPRE use /api (rewrite -> Cloud Run).
// Em dev local, tambÃ©m funciona com Vite proxy se vocÃª usar /api.
const API_BASE = "/api";

const COMPANY_STORAGE_KEY = "trml_current_company";
const AUTH_TOKEN_KEY = "trml_auth_token";
const AUTH_USER_KEY = "trml_auth_user";

function safeJsonParse(value, fallback = null) {
  try {
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function normalizeCompany(company) {
  const normalized = String(company || "").trim().toLowerCase();
  if (normalized === "park" || normalized === "informatica" || normalized === "informÃ¡tica") return "park";
  if (normalized === "parton" || normalized === "suprimentos" || normalized === "suprimento") return "parton";
  return normalized;
}

export function getAuthToken() {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function getAuthUser() {
  try {
    return safeJsonParse(localStorage.getItem(AUTH_USER_KEY), null);
  } catch {
    return null;
  }
}

function isCompanyAllowed(company, user = getAuthUser()) {
  const normalized = normalizeCompany(company);
  const companies = Array.isArray(user?.companies) ? user.companies.map(normalizeCompany) : [];
  return companies.includes(normalized);
}

export function saveAuthSession(token, user) {
  const finalToken = String(token || "").trim();
  const finalUser = user || null;
  try {
    if (finalToken) localStorage.setItem(AUTH_TOKEN_KEY, finalToken);
    else localStorage.removeItem(AUTH_TOKEN_KEY);
    if (finalUser) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(finalUser));
    else localStorage.removeItem(AUTH_USER_KEY);
  } catch {}

  if (finalUser?.companies?.length) {
    const current = getCurrentCompany();
    if (!finalUser.companies.includes(current)) {
      setCurrentCompany(finalUser.companies[0]);
    }
  }
}

export function clearAuthSession() {
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
  } catch {}
}

export function getAuthSession() {
  const token = getAuthToken();
  const user = getAuthUser();
  if (!token || !user) return null;
  return { token, user };
}

export function getCurrentCompany() {
  const user = getAuthUser();
  try {
    const value = localStorage.getItem(COMPANY_STORAGE_KEY);
    const normalized = normalizeCompany(value || "");
    if (normalized && isCompanyAllowed(normalized, user)) return normalized;
  } catch {}
  return normalizeCompany(user?.companies?.[0] || "parton") || "parton";
}

export function setCurrentCompanyLegacy(company) {
  const normalized = normalizeCompany(company || "parton");
  const finalValue = normalized === "park"
    ? "park"
    : "parton";

  try {
    localStorage.setItem(COMPANY_STORAGE_KEY, finalValue);
    window.dispatchEvent(new CustomEvent("trml-company-changed", { detail: { company: finalValue } }));
  } catch {}

  return finalValue;
}

export function setCurrentCompany(company) {
  const normalized = normalizeCompany(company || "parton");
  const user = getAuthUser();
  const finalValue = isCompanyAllowed(normalized, user)
    ? normalized
    : normalizeCompany(user?.companies?.[0] || "parton");

  try {
    localStorage.setItem(COMPANY_STORAGE_KEY, finalValue);
    window.dispatchEvent(new CustomEvent("trml-company-changed", { detail: { company: finalValue } }));
  } catch {}

  return finalValue;
}

function shouldAppendCompany(path) {
  const p = String(path || "");
  return (
    p.startsWith("/tiny/") ||
    p.startsWith("/quotes") ||
    p.startsWith("/clients/") ||
    p.startsWith("/separation/") ||
    p.startsWith("/ops/") ||
    p.startsWith("/seller/") ||
    p.startsWith("/company/")
  );
}

function appendCompanyParam(path) {
  if (!shouldAppendCompany(path)) return path;
  if (/[?&]company=/.test(path)) return path;

  const company = getCurrentCompany();
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}company=${encodeURIComponent(company)}`;
}



function buildUrl(path) {
  if (!path.startsWith("/")) path = "/" + path;
  path = appendCompanyParam(path);
  return `${API_BASE}${path}`;
}

async function getTokenSafe() {
  const token = getAuthToken();
  return token || null;
}

function formatApiErrorMessage(value, fallback = "Erro inesperado.") {
  const one = (v) => {
    if (v == null) return "";
    if (typeof v === "string") return v;
    if (typeof v === "number" || typeof v === "boolean") return String(v);

    if (Array.isArray(v)) {
      const txt = v
        .map((item) => one(item))
        .filter(Boolean)
        .join(" | ");
      return txt || JSON.stringify(v);
    }

    if (typeof v === "object") {
      if (typeof v.message === "string" && v.message.trim()) return v.message;
      if (typeof v.detail === "string" && v.detail.trim()) return v.detail;
      if (typeof v.erro === "string" && v.erro.trim()) return v.erro;
      if (typeof v.error === "string" && v.error.trim()) return v.error;

      const parts = [
        v.codigo,
        v.descricao,
        v.descricao_erro,
        v.mensagem,
        v.motivo,
        v.campo,
        v.loc && Array.isArray(v.loc) ? v.loc.join(".") : "",
        v.msg,
        v.type,
      ]
        .filter((x) => x !== undefined && x !== null && String(x).trim())
        .map((x) => String(x).trim());

      if (parts.length) return parts.join(" - ");

      try {
        return JSON.stringify(v);
      } catch {
        return String(v);
      }
    }

    return String(v);
  };

  const text = one(value).trim();
  return text || fallback;
}

// Detecta páginas HTML de erro de gateway/proxy (ex.: Cloudflare 502/504),
// que chegam como corpo HTML em vez de JSON do backend.
function _looksLikeHtml(text) {
  if (typeof text !== "string") return false;
  const head = text.slice(0, 200).toLowerCase();
  return head.includes("<!doctype") || head.includes("<html");
}

// Mensagem amigável para erros de gateway/infraestrutura, para nunca expor
// o HTML cru da página de erro ao usuário.
function gatewayErrorMessage(status) {
  if (status === 502)
    return "Servidor temporariamente indisponível (502). Tente novamente em alguns segundos.";
  if (status === 503)
    return "Serviço temporariamente indisponível (503). Tente novamente em alguns segundos.";
  if (status === 504)
    return "Tempo de resposta do servidor esgotado (504). Tente novamente em alguns segundos.";
  return `Erro de comunicação com o servidor (HTTP ${status}). Tente novamente.`;
}

async function http(path, options = {}) {
  const url = buildUrl(path);

  const headers = new Headers(options.headers || {});
  const hasBody = options.body !== undefined;

  if (hasBody && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = await getTokenSafe();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(url, { cache: "no-store", ...options, headers });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    // O corpo pode ser JSON (erro tratado do backend) ou texto/HTML (página de
    // erro de gateway, ex.: Cloudflare 502). Nunca exibir HTML cru ao usuário.
    const bodyIsObject = data !== null && typeof data === "object";
    let raw;
    if (bodyIsObject) {
      raw = data.detail ?? data.message ?? data ?? `HTTP ${res.status}`;
    } else if (typeof data === "string" && _looksLikeHtml(data)) {
      raw = gatewayErrorMessage(res.status);
    } else {
      raw = data ?? `HTTP ${res.status}`;
    }
    const msg = formatApiErrorMessage(raw, `HTTP ${res.status}`);
    if (res.status === 401) {
      clearAuthSession();
    }
    const err = new Error(msg);
    err.status = res.status;
    // Só propaga corpo estruturado; nunca o HTML cru de uma página de gateway.
    err.data = bodyIsObject ? data : null;
    throw err;
  }

  return data;
}

function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  // ---- empresa atual ----
  getCurrentCompany,
  setCurrentCompany,
  companyContext: () => http("/company/context"),
  adminListCompanies: () => http("/admin/companies"),
  adminSaveCompany: (payload) =>
    http("/admin/companies", { method: "POST", body: JSON.stringify(payload) }),

  // ---- auth/profile ----
  login: async (login, password) => {
    const data = await http("/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    });
    if (data?.token && data?.user) {
      saveAuthSession(data.token, data.user);
    }
    return data;
  },

  logout: async () => {
    try {
      await http("/auth/logout", { method: "POST" });
    } finally {
      clearAuthSession();
    }
    return { ok: true };
  },

  me: () => http("/me"),
  sellerContext: () => http("/seller/context"),
  homeDashboard: ({ company, seller_id, period, date_from, date_to } = {}) =>
    http(`/home/dashboard${qs({ company, seller_id, period, date_from, date_to })}`),
  homeDashboardHourly: ({ company, date, seller_id } = {}) => http(`/home/dashboard/hourly${qs({ company, date, seller_id })}`),
  sellerClientWallet: (limit = 300) => http(`/seller/client-wallet${qs({ limit })}`),
  sellerOrderWallet: ({ start_date, end_date, limit = 500 } = {}) => http(`/seller/order-wallet${qs({ start_date, end_date, limit })}`),
  sellerTinyWalletLive: ({ q, page_num = 1 } = {}) => http(`/seller/tiny-wallet-live${qs({ q, page_num })}`),

  // ---- administraÃ§Ã£o ----
  adminListUsers: () => http("/admin/users"),

  adminListSettings: () => http("/admin/settings"),

  adminListSettingsAudit: (limit = 120) => http(`/admin/settings/audit${qs({ limit })}`),

  adminSaveSetting: (payload) =>
    http("/admin/settings", { method: "POST", body: JSON.stringify(payload) }),

  adminCatalogProducts: ({ company, search = "", status = "", image = "", featured, category = "", situation = "", limit = 50, offset = 0 } = {}) =>
    http(`/admin/catalog/products${qs({ company, search, status, image, featured, category, situation, limit, offset })}`),

  adminCatalogSyncLocal: ({ company, limit = 1000 } = {}) =>
    http(`/admin/catalog/products/sync-local${qs({ company, limit })}`, { method: "POST" }),

  adminTinyV3Products: ({ company, q = "", field = "nome", situation = "A", limit = 50, offset = 0 } = {}) =>
    http(`/admin/tiny-v3/products${qs({ company, q, field, situation, limit, offset })}`),

  adminCatalogSyncStock: (payload) =>
    http("/admin/catalog/products/sync-stock", { method: "POST", body: JSON.stringify(payload) }),

  adminCatalogBulkUpdateProducts: (payload) =>
    http("/admin/catalog/products/bulk-update", { method: "PUT", body: JSON.stringify(payload) }),

  adminUploadCatalogImage: (file) => {
    const form = new FormData();
    form.append("file", file);
    return http("/admin/catalog/images/upload", { method: "POST", body: form });
  },

  adminListCatalogImages: () => http("/admin/catalog/images"),

  adminCatalogUpdateProduct: (id, payload) =>
    http(`/admin/catalog/products/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),

  adminCatalogPriceTables: ({ company } = {}) =>
    http(`/admin/catalog/price-tables${qs({ company })}`),

  adminCatalogCreatePriceTable: (payload) =>
    http("/admin/catalog/price-tables", { method: "POST", body: JSON.stringify(payload) }),

  adminCatalogUpdatePriceTable: (id, payload) =>
    http(`/admin/catalog/price-tables/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),

  adminCatalogApplyPriceTable: (payload) =>
    http("/admin/catalog/products/apply-price-table", { method: "POST", body: JSON.stringify(payload) }),

  adminCatalogCampaigns: ({ company } = {}) =>
    http(`/admin/catalog/campaigns${qs({ company })}`),

  adminCatalogCreateCampaign: (payload) =>
    http("/admin/catalog/campaigns", { method: "POST", body: JSON.stringify(payload) }),

  adminCatalogUpdateCampaign: (id, payload) =>
    http(`/admin/catalog/campaigns/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),

  adminCatalogCampaignItems: (id, { company } = {}) =>
    http(`/admin/catalog/campaigns/${encodeURIComponent(id)}/items${qs({ company })}`),

  adminCatalogSaveCampaignItems: (id, payload) =>
    http(`/admin/catalog/campaigns/${encodeURIComponent(id)}/items`, { method: "PUT", body: JSON.stringify(payload) }),

  adminCatalogLayouts: ({ company } = {}) =>
    http(`/admin/catalog/layouts${qs({ company })}`),

  adminCatalogLayout: (id) =>
    http(`/admin/catalog/layouts/${encodeURIComponent(id)}`),

  adminCreateCatalogLayout: (payload) =>
    http("/admin/catalog/layouts", { method: "POST", body: JSON.stringify(payload) }),

  adminUpdateCatalogLayout: (id, payload) =>
    http(`/admin/catalog/layouts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),

  adminSaveCatalogLayoutItems: (id, payload) =>
    http(`/admin/catalog/layouts/${encodeURIComponent(id)}/items`, { method: "PUT", body: JSON.stringify(payload) }),

  adminCatalogLayoutPreview: (id) =>
    http(`/admin/catalog/layouts/${encodeURIComponent(id)}/preview`),

  adminListUserAudit: (limit = 80) => http(`/admin/users/audit${qs({ limit })}`),

  adminSaveUser: (payload) =>
    http("/admin/users", { method: "POST", body: JSON.stringify(payload) }),

  adminUpdateUser: (user_id, payload) =>
    http(`/admin/users/${encodeURIComponent(user_id)}`, { method: "PATCH", body: JSON.stringify(payload) }),

  adminResetPassword: (user_id, payload = {}) =>
    http(`/admin/users/${encodeURIComponent(user_id)}/reset-password`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  adminSetUserCompanies: (user_id, payload) =>
    http(`/admin/users/${encodeURIComponent(user_id)}/set-companies`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  adminListSellers: ({ company } = {}) =>
    http(`/admin/sellers${qs({ company })}`),

  adminCompanySellers: ({ company } = {}) =>
    http(`/admin/company-sellers${qs({ company })}`),

  adminGetUserSellerLinks: (user_id) =>
    http(`/admin/users/${encodeURIComponent(user_id)}/seller-links`),

  adminSaveUserSellerLink: (user_id, company_key, payload) =>
    http(`/admin/users/${encodeURIComponent(user_id)}/seller-links/${encodeURIComponent(company_key)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  adminDeleteUserSellerLink: (user_id, company_key) =>
    http(`/admin/users/${encodeURIComponent(user_id)}/seller-links/${encodeURIComponent(company_key)}`, {
      method: "DELETE",
    }),

  // ---- Dashboard executivo de vendas + metas mensais por vendedor ----
  adminSalesPerformance: ({ company, period, date_from, date_to, year_month } = {}) =>
    http(`/admin/dashboard/sales-performance${qs({ company, period, date_from, date_to, year_month })}`),

  adminListSellerMetas: ({ company, year_month } = {}) =>
    http(`/admin/seller-metas${qs({ company, year_month })}`),

  adminSaveSellerMeta: (companyKey, yearMonth, sellerId, payload) =>
    http(`/admin/seller-metas/${encodeURIComponent(companyKey)}/${encodeURIComponent(yearMonth)}/${encodeURIComponent(sellerId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  adminDeleteSellerMeta: (companyKey, yearMonth, sellerId) =>
    http(`/admin/seller-metas/${encodeURIComponent(companyKey)}/${encodeURIComponent(yearMonth)}/${encodeURIComponent(sellerId)}`, {
      method: "DELETE",
    }),

  adminV3Status: ({ company } = {}) =>
    http(`/admin/v3-status${qs({ company })}`),

  adminSaveV3Token: (payload) =>
    http("/admin/v3-token", { method: "POST", body: JSON.stringify(payload) }),

  adminSaveV3Credentials: (payload) =>
    http("/admin/tiny-v3/credentials", { method: "POST", body: JSON.stringify(payload) }),

  adminV3AuthUrl: ({ company } = {}) =>
    http(`/admin/tiny-v3/auth-url${qs({ company })}`),

  adminDisableUser: (email) =>
    http(`/admin/users/${encodeURIComponent(email)}`, { method: "DELETE" }),

  // health
  health: () => http("/health"),

  // ---- Tiny dropdowns ----
  tinyShippingMethods: () => http("/tiny/shipping-methods"),

  // /tiny/shipping-methods/{shipping_id}/freight-methods
  tinyFreightMethods: (shipping_id) => {
    if (!shipping_id) throw new Error("shipping_id Ã© obrigatÃ³rio");
    return http(`/tiny/shipping-methods/${encodeURIComponent(shipping_id)}/freight-methods`);
  },

  tinyPaymentMethods: ({ company } = {}) => http(`/tiny/payment-methods${qs({ company })}`),
  tinyClients: (q, page = 1) => http(`/tiny/clients${qs({ q, page })}`),

  clientWalletList: ({ company, q = "", uf = "", seller = "", active = true, has_email, has_phone, limit = 50, offset = 0 } = {}) =>
    http(`/client-wallet${qs({ company, q, uf, seller, active, has_email, has_phone, limit, offset })}`),

  clientWalletSellers: ({ company } = {}) =>
    http(`/client-wallet/sellers${qs({ company })}`),

  clientWalletDetail: ({ company, tiny_client_id } = {}) =>
    http(`/client-wallet/${encodeURIComponent(tiny_client_id)}${qs({ company })}`),

  clientWalletLastPurchases: ({ company, tiny_client_id, limit = 3 } = {}) =>
    http(`/client-wallet/${encodeURIComponent(tiny_client_id)}/last-purchases${qs({ company, limit })}`),

  clientWalletProductLastSalesBatch: ({ company, client, products } = {}) =>
    http(`/client-wallet/product-last-sales/batch`, { method: "POST", body: JSON.stringify({ company, client, products }) }),

  clientWalletSyncStatus: ({ company } = {}) =>
    http(`/client-wallet/sync/status${qs({ company })}`),

  clientWalletSyncNext: ({ company, page_size = 50 } = {}) =>
    http(`/client-wallet/sync/next${qs({ company, page_size })}`, { method: "POST" }),

  clientWalletSyncReset: ({ company, page_size = 50 } = {}) =>
    http(`/client-wallet/sync/reset${qs({ company, page_size })}`, { method: "POST" }),

  clientWalletCreate: ({ company, payload } = {}) =>
    http(`/client-wallet${qs({ company })}`, { method: "POST", body: JSON.stringify(payload || {}) }),

  clientWalletUpdate: ({ company, tiny_client_id, payload } = {}) =>
    http(`/client-wallet/${encodeURIComponent(tiny_client_id)}${qs({ company })}`, {
      method: "PATCH",
      body: JSON.stringify(payload || {}),
    }),

  // Reenvia ao Tiny um cliente local ainda não sincronizado (por id local).
  clientWalletResync: ({ company, id } = {}) =>
    http(`/client-wallet/${encodeURIComponent(id)}/resync${qs({ company })}`, { method: "POST" }),

  tinyClientWalletCached: ({ q = "", page = 1, page_size = 10, seller_id = "" } = {}) =>
    http(`/client-wallet${qs({ q, limit: page_size, offset: Math.max(0, (page - 1) * page_size), seller_id })}`),

  tinyClientWalletCachedSellers: () =>
    Promise.resolve({ ok: true, items: [] }),

  refreshClientWalletCache: () =>
    http(`/client-wallet/sync/next`, { method: "POST" }),
  tinyClientWalletLive: ({ q = "", page = 1, page_size = 10, seller_id = "" } = {}) => http(`/tiny/client-wallet-live${qs({ q, page, page_size, seller_id })}`),
  tinyProducts: (q, page = 1) => http(`/tiny/products${qs({ q, page })}`),
  tinyStock: (product_id) => http(`/tiny/products/${encodeURIComponent(product_id)}/stock`),
  tinyVendors: (q, page = 1) => http(`/tiny/vendors${qs({ q, page })}`),

  // ---- Quotes ----
  listQuotes: ({ status, q, limit = 200, offset = 0 } = {}) =>
    http(`/quotes${qs({ status, q, limit, offset })}`),

  getQuote: (quote_id) => http(`/quotes/${encodeURIComponent(quote_id)}`),

  createQuote: (payload) =>
    http("/quotes", { method: "POST", body: JSON.stringify(payload) }),

  updateQuote: (quote_id, payload) =>
    http(`/quotes/${encodeURIComponent(quote_id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  createOrderFromQuote: (quote_id) =>
    http(`/quotes/${encodeURIComponent(quote_id)}/order`, { method: "POST" }),

  approveOrder: (quote_id) =>
    http(`/quotes/${encodeURIComponent(quote_id)}/approve-order`, { method: "POST" }),

  cancelOrder: (quote_id) =>
    http(`/quotes/${encodeURIComponent(quote_id)}/cancel-order`, { method: "POST" }),

  cloneQuote: (quote_id) =>
    http(`/quotes/${encodeURIComponent(quote_id)}/clone`, { method: "POST" }),


  markInvoiced: (quote_id) =>
    http(`/quotes/${encodeURIComponent(quote_id)}/mark-invoiced`, { method: "POST" }),

  deleteQuote: (quote_id, company) =>
    http(`/quotes/${encodeURIComponent(quote_id)}${qs({ company })}`, { method: "DELETE" }),

  // ---- Separation ----
  listSeparationOrders: ({ status, q, limit = 100, offset = 0, ...extra } = {}) =>
    http(`/separation/orders${qs({ status, q, limit, offset, ...extra })}`),

  tinySyncPreview: ({ local_limit = 20, include_remote = true, remote_pages = 1, remote_search = "" } = {}) =>
    http(`/ops/tiny-sync-preview${qs({ local_limit, include_remote, remote_pages, remote_search })}`),

  tinyOrders: ({ status = "", page = 1, per_page = 100, search = "", remote_pages = 15 } = {}) =>
    http(`/ops/tiny-orders${qs({ status, page, per_page, search, remote_pages })}`),

  syncLocalOrderStatuses: (limit = 5) =>
    http(`/ops/sync-local-order-statuses${qs({ limit })}`, { method: "POST" }),

  syncLocalOrderStatus: (q) =>
    http(`/ops/sync-local-order-status${qs({ q })}`, { method: "POST" }),
  startSyncLocalOrderStatuses: () =>
    http(`/ops/start-sync-local-order-statuses`, { method: "POST" }),
  getSyncLocalOrderStatusesProgress: () =>
    http(`/ops/sync-local-order-statuses-progress`),

  getSeparationOrder: (tiny_order_id, company) =>
    http(`/separation/orders/${encodeURIComponent(tiny_order_id)}${qs({ company })}`),

  // Aceita e repassa qualquer campo do payload, inclusive os campos opcionais
  // da conferência: awaiting_conference, separation_photo_url,
  // conference_photo_url e checked_at. No fluxo OFF esses campos não são enviados.
  updateSeparationOrder: (tiny_order_id, payload, company) =>
    http(`/separation/orders/${encodeURIComponent(tiny_order_id)}${qs({ company })}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  // Upload da foto de separação/conferência. Espelha adminUploadCatalogImage,
  // porém usa um endpoint próprio liberado ao operador de separação
  // (admin OU is_separacao), e não o de catálogo (admin-only -> 403).
  // Backend deferido: enquanto o endpoint não existir, o front fica em OFF e
  // este método não é chamado.
  uploadSeparationPhoto: (file) => {
    const form = new FormData();
    form.append("file", file);
    return http("/separation/photos/upload", { method: "POST", body: form });
  },

  // Busca a foto protegida (rota autenticada, restrita a separacao/admin) e
  // devolve um object URL para usar em <img>. <img> não envia o header
  // Authorization — por isso buscamos via fetch com o token e criamos um blob.
  getSeparationPhotoObjectUrl: async (value) => {
    const raw = String(value || "").trim();
    if (!raw) return "";
    if (raw.startsWith("blob:") || raw.startsWith("data:")) return raw;
    const filename = raw.split("?")[0].split("/").filter(Boolean).pop();
    if (!filename) return "";
    const token = await getTokenSafe();
    const res = await fetch(buildUrl(`/separation/photos/${encodeURIComponent(filename)}`), {
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error("Falha ao carregar a foto.");
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },

  // ---- Conferência da separação: toggle runtime (admin) ----
  getConferenciaSetting: () => http("/admin/settings/conferencia"),
  setConferenciaSetting: (mode) =>
    http("/admin/settings/conferencia", { method: "PUT", body: JSON.stringify({ mode }) }),

  // ---- Produtos local-first ----
  adminListProducts: ({ company, q = "", sync_status = "", limit = 50, offset = 0 } = {}) =>
    http(`/admin/products${qs({ company, q, sync_status, limit, offset })}`),

  adminCreateProduct: ({ company, ...payload } = {}) =>
    http(`/admin/products${qs({ company })}`, { method: "POST", body: JSON.stringify(payload) }),

  adminImportTinyProducts: ({ company, q = "", field = "nome", situacao = "A", limit = 20, offset = 0, dry_run = true, import_details = true } = {}) =>
    http(`/admin/products/import-tiny${qs({ company })}`, {
      method: "POST",
      body: JSON.stringify({ company, q, field, situacao, limit, offset, dry_run, import_details }),
    }),

  adminImportTinyProductsAll: ({
    company,
    q = "",
    field = "nome",
    situacao = "A",
    limit = 20,
    offset_start = 0,
    max_pages = 1,
    dry_run = true,
    import_details = true,
    sleep_ms = 1500,
  } = {}) =>
    http(`/admin/products/import-tiny-all${qs({ company })}`, {
      method: "POST",
      body: JSON.stringify({ company, q, field, situacao, limit, offset_start, max_pages, dry_run, import_details, sleep_ms }),
    }),

  adminRefreshTinyProductDetails: ({
    company,
    limit = 5,
    offset = 0,
    after_id = null,
    sleep_ms = 3000,
    dry_run = true,
    only_missing = true,
    retry_429 = true,
    retry_after_ms = 5000,
    max_retries = 1,
  } = {}) =>
    http(`/admin/products/refresh-tiny-details${qs({ company })}`, {
      method: "POST",
      body: JSON.stringify({
        company,
        limit,
        offset,
        after_id,
        sleep_ms,
        dry_run,
        only_missing,
        retry_429,
        retry_after_ms,
        max_retries,
      }),
    }),

  adminGetProduct: (id, { company } = {}) =>
    http(`/admin/products/${encodeURIComponent(id)}${qs({ company })}`),

  adminProductStats: ({ company } = {}) =>
    http(`/admin/products/stats${qs({ company })}`),

  // ---- Controle de estoque local (Fase 1) ----
  adminGetProductStock: (productId, { company } = {}) =>
    http(`/admin/products/${encodeURIComponent(productId)}/stock${qs({ company })}`),

  adminCreateProductStockMovement: (productId, payload = {}) =>
    http(`/admin/products/${encodeURIComponent(productId)}/stock/movements${qs({ company: payload?.company })}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  adminReverseProductStockMovement: (productId, movementId, payload = {}) =>
    http(
      `/admin/products/${encodeURIComponent(productId)}/stock/movements/${encodeURIComponent(movementId)}/reverse${qs({ company: payload?.company })}`,
      { method: "POST", body: JSON.stringify(payload) }
    ),

  // ---- Relatório/auditoria de movimentações (Fase 3, somente leitura) ----
  adminListProductStockMovements: ({
    company,
    product_id,
    sku,
    q,
    movement_type,
    date_from,
    date_to,
    include_reversed,
    only_reversed,
    only_reversals,
    limit,
    offset,
  } = {}) =>
    http(
      `/admin/products/stock-movements${qs({
        company,
        product_id,
        sku,
        q,
        movement_type,
        date_from,
        date_to,
        include_reversed,
        only_reversed,
        only_reversals,
        limit,
        offset,
      })}`
    ),

  // ---- Posição atual de estoque local (somente leitura) ----
  adminProductStockPosition: ({ company, q, stock_status, min_stock, limit, offset } = {}) =>
    http(
      `/admin/products/stock-position${qs({
        company,
        q,
        stock_status,
        min_stock,
        limit,
        offset,
      })}`
    ),

  // ---- Importação/conferência de ajustes de estoque local em lote ----
  adminPreviewProductStockBulk: (payload = {}) =>
    http(`/admin/products/stock-bulk/preview${qs({ company: payload?.company })}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  adminCommitProductStockBulk: (payload = {}) =>
    http(`/admin/products/stock-bulk/commit${qs({ company: payload?.company })}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ---- Importar cadastros Tiny para SKUs não encontrados na conferência ----
  adminImportMissingProductSkusFromTiny: (payload = {}) =>
    http(`/admin/products/import-missing-skus-from-tiny${qs({ company: payload?.company })}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ---- Marco de controle automático local de estoque (config/baseline) ----
  adminStockAutoControlStatus: ({ company } = {}) =>
    http(`/admin/stock-auto-control/status${qs({ company })}`),

  adminConfigureStockAutoControl: (payload = {}) =>
    http(`/admin/stock-auto-control/configure${qs({ company: payload?.company })}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  adminProductStockSyncStatus: ({ company } = {}) =>
    http(`/admin/products/stock-sync/status${qs({ company })}`),

  adminRunProductStockSync: ({
    company,
    dry_run = true,
    limit = 20,
    sleep_ms = 1000,
    after_id = null,
    force = false,
    only_with_tiny_product_id = true,
    max_errors = 10,
    update_payload = true,
  } = {}) =>
    http(`/admin/products/stock-sync/run${qs({ company })}`, {
      method: "POST",
      body: JSON.stringify({ company, dry_run, limit, sleep_ms, after_id, force, only_with_tiny_product_id, max_errors, update_payload }),
    }),

  adminProductSkuConflicts: ({ company, limit = 100, include_tiny_probe = false, tiny_limit = 100, max_pages = 10, sleep_ms = 500 } = {}) =>
    http(`/admin/products/sku-conflicts${qs({ company, limit, include_tiny_probe, tiny_limit, max_pages, sleep_ms })}`),

  adminProductConflictDecisions: ({ company, sku = "", status = "active" } = {}) =>
    http(`/admin/products/conflict-decisions${qs({ company, sku, status })}`),

  adminSaveProductConflictDecision: (payload = {}) =>
    http(`/admin/products/conflict-decisions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ---- Compras — Pedidos de Compra e Estoque (Tiny V2) ----
  get: (path) => http(path),

  adminListCompras: ({ company, pagina = 1, situacao = "", data_inicial = "", data_final = "", fornecedor = "", pesquisa = "", numero = "", marketplace = "" } = {}) =>
    http(`/admin/compras${qs({ company, pagina, situacao, data_inicial, data_final, fornecedor, pesquisa, numero, marketplace })}`),

  adminGetCompra: ({ company, id } = {}) =>
    http(`/admin/compras/${id}${qs({ company })}`),

  adminListEstoqueAtualizacoes: ({ company, pagina = 1, pesquisa = "", data_inicial = "", data_final = "", id_produto = null, marketplace = "" } = {}) =>
    http(`/admin/estoque/atualizacoes${qs({ company, pagina, pesquisa, data_inicial, data_final, id_produto, marketplace })}`),

  adminListComprasFornecedores: ({ company, pesquisa = "", pagina = 1 } = {}) =>
    http(`/admin/compras/fornecedores${qs({ company, pesquisa, pagina })}`),
};

export default api;

// Centraliza a empresa ativa em uma Ãºnica chave e mantÃ©m compatibilidade com chaves antigas.
// Em produÃ§Ã£o, o frontend deve ler e gravar apenas `trml_company_key`.
// REMOVIDO DUPLICADO: const COMPANY_STORAGE_KEY = "trml_company_key";
const COMPANY_STORAGE_ALIASES = ["erp_company_key", "company_key", "current_company_key", "selected_company_key"];
const COMPANY_STORAGE_REGEX = /company/i;

function _company_storage_read() {
  try {
    const direct = window.localStorage.getItem(COMPANY_STORAGE_KEY);
    if (direct) return direct;
    for (const alias of COMPANY_STORAGE_ALIASES) {
      const value = window.localStorage.getItem(alias);
      if (value) return value;
    }
  } catch {
    return null;
  }
  return null;
}

function _company_storage_write(value) {
  try {
    if (value) {
      window.localStorage.setItem(COMPANY_STORAGE_KEY, value);
      for (const alias of COMPANY_STORAGE_ALIASES) {
        window.localStorage.setItem(alias, value);
      }
    } else {
      window.localStorage.removeItem(COMPANY_STORAGE_KEY);
      for (const alias of COMPANY_STORAGE_ALIASES) {
        window.localStorage.removeItem(alias);
      }
    }
  } catch {
    // ignore storage failures
  }
}

if (typeof window !== "undefined" && !window.__trmlCompanyStoragePatched) {
  window.__trmlCompanyStoragePatched = true;
  const originalGetItem = window.localStorage.getItem.bind(window.localStorage);
  const originalSetItem = window.localStorage.setItem.bind(window.localStorage);
  const originalRemoveItem = window.localStorage.removeItem.bind(window.localStorage);

  window.localStorage.getItem = function patchedGetItem(key) {
    if (key === COMPANY_STORAGE_KEY || (typeof key === "string" && COMPANY_STORAGE_REGEX.test(key))) {
      const stored = originalGetItem(COMPANY_STORAGE_KEY);
      if (stored) return stored;
      for (const alias of COMPANY_STORAGE_ALIASES) {
        const value = originalGetItem(alias);
        if (value) return value;
      }
      return null;
    }
    if (COMPANY_STORAGE_ALIASES.includes(key) || (typeof key === "string" && COMPANY_STORAGE_REGEX.test(key))) {
      const mainValue = originalGetItem(COMPANY_STORAGE_KEY);
      if (mainValue) return mainValue;
    }
    return originalGetItem(key);
  };

  window.localStorage.setItem = function patchedSetItem(key, value) {
    originalSetItem(key, value);
    if (key === COMPANY_STORAGE_KEY || COMPANY_STORAGE_ALIASES.includes(key) || (typeof key === "string" && COMPANY_STORAGE_REGEX.test(key))) {
      originalSetItem(COMPANY_STORAGE_KEY, value);
      for (const alias of COMPANY_STORAGE_ALIASES) {
        originalSetItem(alias, value);
      }
      window.dispatchEvent(new CustomEvent("trml-company-change", { detail: { companyKey: value } }));
    }
  };

  window.localStorage.removeItem = function patchedRemoveItem(key) {
    originalRemoveItem(key);
    if (key === COMPANY_STORAGE_KEY || COMPANY_STORAGE_ALIASES.includes(key) || (typeof key === "string" && COMPANY_STORAGE_REGEX.test(key))) {
      originalRemoveItem(COMPANY_STORAGE_KEY);
      for (const alias of COMPANY_STORAGE_ALIASES) {
        originalRemoveItem(alias);
      }
      window.dispatchEvent(new CustomEvent("trml-company-change", { detail: { companyKey: null } }));
    }
  };
}

export function getCurrentCompanyKey() {
  return _company_storage_read();
}

export function setCurrentCompanyKey(companyKey) {
  _company_storage_write(companyKey);
}
