from pathlib import Path
import re

api_path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\api.js")
newquote_path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\NewQuote.jsx")

api = api_path.read_text(encoding="utf-8")

# 1) Insere helpers de empresa depois do API_BASE.
needle = 'const API_BASE = "/api";\n'
insert = r'''
const COMPANY_STORAGE_KEY = "trml_current_company";

export function getCurrentCompany() {
  try {
    const value = localStorage.getItem(COMPANY_STORAGE_KEY);
    return value || "parton";
  } catch {
    return "parton";
  }
}

export function setCurrentCompany(company) {
  const normalized = String(company || "parton").trim().toLowerCase();
  const finalValue = normalized === "park" || normalized === "informatica" || normalized === "informática"
    ? "park"
    : "parton";

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
    p.startsWith("/ops/")
  );
}

function appendCompanyParam(path) {
  if (!shouldAppendCompany(path)) return path;
  if (/[?&]company=/.test(path)) return path;

  const company = getCurrentCompany();
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}company=${encodeURIComponent(company)}`;
}

'''
if insert.strip() not in api:
    api = api.replace(needle, needle + insert + "\n")

# 2) Faz buildUrl aplicar company automaticamente.
old = '''function buildUrl(path) {
  if (!path.startsWith("/")) path = "/" + path;
  return `${API_BASE}${path}`;
}
'''
new = '''function buildUrl(path) {
  if (!path.startsWith("/")) path = "/" + path;
  path = appendCompanyParam(path);
  return `${API_BASE}${path}`;
}
'''
if old in api:
    api = api.replace(old, new)
else:
    raise SystemExit("Não encontrei buildUrl esperado em api.js")

# 3) Expõe métodos no objeto api.
old_marker = '''export const api = {
  // ---- auth/profile ----
'''
new_marker = '''export const api = {
  // ---- empresa atual ----
  getCurrentCompany,
  setCurrentCompany,
  companyContext: () => http("/company/context"),
  adminListCompanies: () => http("/admin/companies"),
  adminSaveCompany: (payload) =>
    http("/admin/companies", { method: "POST", body: JSON.stringify(payload) }),

  // ---- auth/profile ----
'''
if new_marker.strip() not in api:
    api = api.replace(old_marker, new_marker)

api_path.write_text(api, encoding="utf-8")

# 4) Corrige fetch direto do último preço no NewQuote.jsx.
nq = newquote_path.read_text(encoding="utf-8")

old_fetch = '''      const resp = await fetch(`/api/clients/${clientId}/products/${productId}/last-price`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
'''
new_fetch = '''      const company = api?.getCurrentCompany?.() || "parton";
      const resp = await fetch(`/api/clients/${clientId}/products/${productId}/last-price?company=${encodeURIComponent(company)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
'''
if old_fetch in nq:
    nq = nq.replace(old_fetch, new_fetch)
else:
    print("AVISO: fetch direto de last-price não encontrado no formato esperado. Nada alterado nessa parte.")

newquote_path.write_text(nq, encoding="utf-8")

print("OK: patch de empresa aplicado em api.js e NewQuote.jsx")
