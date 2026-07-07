// frontend/src/ui/theme.js
import { getCurrentCompany } from "../api";

const THEME_KEY = "trml_theme"; // mesma chave já usada em App.jsx

export function getStoredTheme() {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(THEME_KEY);
  return v === "light" || v === "dark" ? v : null; // null = auto (segue o SO)
}

export function setStoredTheme(mode) {
  if (typeof window === "undefined") return;
  const root = document.documentElement;
  if (mode === "light" || mode === "dark") {
    window.localStorage.setItem(THEME_KEY, mode);
    root.setAttribute("data-theme", mode);
    root.style.colorScheme = mode;
  } else {
    // auto: remove override, deixa o @media(prefers-color-scheme) decidir
    window.localStorage.removeItem(THEME_KEY);
    root.removeAttribute("data-theme");
    root.style.removeProperty("color-scheme");
  }
}

export function cycleTheme(current) {
  // auto -> dark -> light -> auto
  if (current === null) return "dark";
  if (current === "dark") return "light";
  return null;
}

export function applyStoredTheme() {
  setStoredTheme(getStoredTheme());
}

function companyTone(key) {
  return String(key || "").toLowerCase() === "park" ? "park" : "parton";
}

export function initCompanyAttr() {
  if (typeof document === "undefined") return;
  const tone = companyTone(getCurrentCompany?.());
  document.documentElement.setAttribute("data-company", tone);
}
