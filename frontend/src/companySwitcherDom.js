import { getCurrentCompany, setCurrentCompany } from "./api";

function badge(key) {
  const k = String(key || "").toLowerCase();
  if (k === "parton") return "SUPRIMENTOS";
  if (k === "park") return "INFORMÁTICA";
  return String(key || "EMPRESA").toUpperCase();
}

function label(key, name) {
  const k = String(key || "").toLowerCase();
  if (k === "parton") return "Suprimentos";
  if (k === "park") return "Informática";
  return name || key || "Empresa";
}

function tone(key) {
  const k = String(key || "").toLowerCase();
  if (k === "park") return "park";
  return "parton";
}

export function mountCompanySwitcher(api) {
  if (typeof document === "undefined") return () => {};

  const old = document.getElementById("trml-company-switcher-root");
  if (old) old.remove();

  const root = document.createElement("div");
  root.id = "trml-company-switcher-root";
  root.className = "trml-company-switcher";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "trml-company-switcher__button";

  function renderButton() {
    const current = getCurrentCompany();
    btn.innerHTML =
      '<span class="trml-company-switcher__caption">Sistema ativo</span>' +
      '<span class="trml-company-switcher__pill trml-company-switcher__pill--' + tone(current) + '">' +
      badge(current) +
      '</span>' +
      '<span class="trml-company-switcher__chevron">⌄</span>';
  }
  renderButton();

  const panel = document.createElement("div");
  panel.className = "trml-company-switcher__panel";
  panel.style.display = "none";

  async function load() {
    panel.innerHTML =
      '<div class="trml-company-switcher__title">Selecionar empresa</div>' +
      '<div class="trml-company-switcher__loading">Carregando...</div>';

    try {
      const resp = await api.adminListCompanies();
      const items = Array.isArray(resp?.items) ? resp.items : [];
      const current = getCurrentCompany();

      panel.innerHTML = '<div class="trml-company-switcher__title">Selecionar empresa</div>';

      items.filter((x) => x.active !== false).forEach((x) => {
        const key = String(x.company_key || "").toLowerCase();
        const row = document.createElement("button");
        row.type = "button";
        row.className =
          "trml-company-switcher__option trml-company-switcher__option--" +
          tone(key) +
          (key === current ? " is-active" : "");
        row.innerHTML =
          '<span class="trml-company-switcher__option-main">' +
          '<span class="trml-company-switcher__dot"></span>' +
          '<span><b>' + label(key, x.company_name) + '</b>' +
          '<small>' + badge(key) + '</small></span>' +
          '</span>' +
          '<span class="trml-company-switcher__active-mark">' +
          (key === current ? "Ativa" : "") +
          '</span>';

        row.onclick = () => {
          const before = getCurrentCompany();
          setCurrentCompany(key);
          if (getCurrentCompany() !== before) window.location.reload();
        };

        panel.appendChild(row);
      });
    } catch (e) {
      panel.innerHTML = '<div class="trml-company-switcher__error">Erro ao carregar empresas.</div>';
    }
  }

  btn.onclick = async () => {
    const open = panel.style.display === "none";
    panel.style.display = open ? "block" : "none";
    if (open) await load();
  };

  document.addEventListener("click", (ev) => {
    if (!root.contains(ev.target)) panel.style.display = "none";
  });

  root.appendChild(btn);
  root.appendChild(panel);
  document.body.appendChild(root);

  return () => root.remove();
}
