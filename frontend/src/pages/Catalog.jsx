import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { jsPDF } from "jspdf";
import { useRef } from "react";
import { withGlobalLoading } from "../utils/globalLoading";
import partonLogo from "../assets/catalog/parton-logo.png";
import { PageHeader, Button, Card, Table, StatusPill, EmptyState, Spinner } from "../ui";

const COMPANIES = [
  { key: "parton", label: "Suprimentos" },
  { key: "park", label: "Informática" },
];

const PAGE_SIZE = 50;
const PARTON_LOGO_SRC = partonLogo;
const PDF_PRODUCTS_PER_PAGE = 36;

function formatBRL(value) {
  const number = Number(value || 0);
  return number.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function formatCatalogVisualPrice(value) {
  if (value === null || value === undefined || value === "") return "";
  const numeric = typeof value === "string"
    ? Number(value.replace(/[^\d,.-]/g, "").replace(/\./g, "").replace(",", "."))
    : Number(value);
  if (!Number.isFinite(numeric)) return "";
  return `%${Math.round(numeric * 100)}`;
}

function catalogImageUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw) || raw.startsWith("/")) return raw;
  if (raw.startsWith("catalog-images/")) return `/${raw.split("/").map(encodeURIComponent).join("/")}`;
  return `/catalog-images/${encodeURIComponent(raw)}`;
}

function imageCandidates(item) {
  const local = String(item?.catalog_image_path || item?.catalog_image_filename || "").trim();
  const variants = [];
  if (local) {
    variants.push(local);
    if (local.includes(" ")) variants.push(local.replace(/\s+/g, "-"));
    if (local.includes("-")) variants.push(local.replace(/-/g, " "));
  }
  variants.push(item?.catalog_image_url || "");
  variants.push(item?.image_url_tiny || "");
  return [...new Set(variants.map(catalogImageUrl).filter(Boolean))];
}

function imageFor(item) {
  return imageCandidates(item)[0] || "";
}

function CatalogImage({ item, alt = "", style, placeholderStyle }) {
  const candidates = imageCandidates(item);
  const [index, setIndex] = useState(0);
  const src = candidates[index] || "";
  if (!src) return <span style={placeholderStyle || styles.muted}>Sem imagem</span>;
  return (
    <img
      src={src}
      alt={alt}
      style={style}
      onError={() => {
        if (index + 1 < candidates.length) setIndex(index + 1);
        else setIndex(candidates.length);
      }}
    />
  );
}

function withTimeout(promise, timeoutMs, message) {
  let timeoutId;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(message)), timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => window.clearTimeout(timeoutId));
}

async function waitForImages(root, timeoutMs = 5000) {
  const images = Array.from(root?.querySelectorAll?.("img") || []);
  await withTimeout(
    Promise.all(images.map((img) => {
      if (img.complete) return Promise.resolve();
      return new Promise((resolve) => {
        const finish = () => resolve();
        img.addEventListener("load", finish, { once: true });
        img.addEventListener("error", finish, { once: true });
      });
    })),
    timeoutMs,
    "Tempo limite ao carregar imagens do PDF."
  ).catch(() => undefined);
}

function formatCatalogDateLabel(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const parts = text.slice(0, 10).split("-");
  if (parts.length !== 3) return text.slice(0, 10);
  return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

function chunkArray(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${number.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
}

function formatStock(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function todayISO(offsetDays = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

function defaultLayoutDraft(companyKey = "parton") {
  const companyLabel = companyKey === "park" ? "Informática" : "Suprimentos";
  return {
    id: null,
    company_key: companyKey,
    name: `Configuração ${companyLabel}`,
    title: `Catálogo ${companyLabel}`,
    subtitle: "",
    notes: "",
    valid_until: "",
    use_active_campaigns: true,
    show_full_price: true,
    show_billed_price: true,
    show_cash_price: true,
    show_sku: true,
    show_tags: false,
    show_stock: false,
    show_without_image: true,
    only_active_products: true,
    active: true,
  };
}

const styles = {
  page: { display: "grid", gap: 16 },
  header: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" },
  title: { fontSize: 28, fontWeight: 950, letterSpacing: 0 },
  muted: { color: "var(--muted)", fontSize: 13 },
  tabs: { display: "flex", gap: 8, flexWrap: "wrap" },
  tab: { border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 12px", fontWeight: 900, cursor: "pointer" },
  tabActive: { background: "#1d4ed8", color: "#fff", borderColor: "#1d4ed8" },
  button: { border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 12px", fontWeight: 900, cursor: "pointer" },
  primary: { background: "#1d4ed8", color: "#fff", borderColor: "#1d4ed8" },
  card: { border: "1px solid var(--border)", background: "var(--panel, #fff)", padding: 14 },
  input: { width: "100%", border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "9px 10px" },
  smallInput: { width: 78, border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: "7px 8px", fontWeight: 800 },
  tableWrap: { border: "1px solid var(--border)", background: "var(--panel, #fff)", overflow: "auto" },
  th: { textAlign: "left", padding: "10px 12px", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: 12, textTransform: "uppercase" },
  td: { padding: "10px 12px", borderBottom: "1px solid var(--border)", verticalAlign: "middle" },
  badge: { display: "inline-flex", padding: "4px 8px", border: "1px solid var(--border)", fontSize: 12, fontWeight: 900 },
  modalOverlay: { position: "fixed", inset: 0, background: "rgba(15,23,42,.45)", zIndex: 70, display: "grid", placeItems: "center", padding: 18 },
  modal: { width: "min(860px, 96vw)", maxHeight: "92vh", overflow: "auto", border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: 18 },
  galleryModal: { width: "min(1120px, 96vw)", maxHeight: "92vh", overflow: "auto", border: "1px solid var(--border)", background: "var(--panel, #fff)", color: "var(--text)", padding: 18 },
  galleryToolbar: { display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center" },
  galleryGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 },
  galleryItem: { border: "1px solid var(--border)", background: "var(--panel, #fff)", padding: 10, display: "grid", gap: 8, textAlign: "left", cursor: "pointer", color: "var(--text)" },
  galleryThumb: { width: "100%", aspectRatio: "1 / 1", objectFit: "contain", background: "#fff", border: "1px solid var(--border)", borderRadius: 8, padding: 8 },
  previewGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 14, alignItems: "stretch" },
  previewCard: { border: "1px solid #d8e6f5", borderRadius: 16, background: "#fff", overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 468, boxShadow: "0 10px 26px rgba(0,61,142,.08)" },
  previewImageWrap: { height: 226, background: "linear-gradient(180deg, #ffffff 0%, #f7fbff 100%)", display: "grid", placeItems: "center", borderBottom: "1px solid #e2edf8", position: "relative", padding: 12 },
  previewImage: { width: "100%", height: "100%", objectFit: "contain", background: "transparent" },
  previewPlaceholder: { width: 108, height: 108, display: "grid", placeItems: "center", color: "var(--muted)", fontWeight: 800, fontSize: 12, textAlign: "center", background: "rgba(148,163,184,.08)", border: "1px dashed rgba(148,163,184,.45)", borderRadius: 999, padding: 10 },
  previewBody: { flex: 1, padding: "12px 14px 8px", display: "grid", gap: 7, alignContent: "start" },
  previewSku: { color: "#2563aa", fontWeight: 850, fontSize: 10.5, letterSpacing: ".08em", lineHeight: 1.1, textTransform: "uppercase" },
  previewTitle: { fontSize: 15, fontWeight: 950, lineHeight: 1.22, color: "#0d1b2e", display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 3, overflow: "hidden", minHeight: 56 },
  previewTagLine: { color: "#64748b", fontSize: 12, lineHeight: 1.25, display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden" },
  previewPriceBlock: { marginTop: "auto", padding: "0 14px 15px", display: "grid", gap: 5, alignContent: "end" },
  previewPriceMain: { fontSize: 27, fontWeight: 950, lineHeight: 1.02, color: "#0047b6" },
  previewPriceSecondary: { color: "#64748b", fontSize: 12, fontWeight: 750, lineHeight: 1.2, wordBreak: "break-word" },
  previewBadgeGroup: { position: "absolute", top: 10, left: 10, display: "flex", gap: 6, flexWrap: "wrap", zIndex: 1 },
  previewIntro: { border: "1px solid #d8e6f5", borderRadius: 16, background: "linear-gradient(135deg, #ffffff 0%, #f7fbff 62%, #eaf5ff 100%)", padding: 16, display: "flex", justifyContent: "space-between", gap: 18, alignItems: "center", boxShadow: "0 10px 26px rgba(0,61,142,.07)" },
  previewBrand: { display: "flex", alignItems: "center", gap: 13, minWidth: 0 },
  previewLogoBox: { width: 92, height: 54, display: "grid", placeItems: "center", padding: 0, position: "relative", overflow: "hidden" },
  previewLogo: { width: "100%", height: "100%", objectFit: "contain", position: "relative", zIndex: 1 },
  previewIntroTitle: { fontWeight: 950, fontSize: 20, lineHeight: 1.1, color: "#083f91" },
  previewIntroMeta: { color: "#64748b", fontSize: 13, lineHeight: 1.35, fontWeight: 700 },
  pdfStage: { position: "absolute", left: "-10000px", top: 0, width: "794px", background: "#eef4fb", color: "#111827", pointerEvents: "none", fontFamily: "Inter, Arial, sans-serif" },
  pdfPage: { width: "794px", height: "1123px", boxSizing: "border-box", background: "linear-gradient(180deg, #f8fbff 0%, #ffffff 36%, #ffffff 100%)", padding: "18px 20px 16px", display: "flex", flexDirection: "column", gap: 8, pageBreakAfter: "always", overflow: "hidden", position: "relative" },
  pdfCoverPage: { width: "794px", height: "1123px", boxSizing: "border-box", background: "linear-gradient(135deg, #064796 0%, #0047a8 48%, #057ec7 100%)", color: "#fff", padding: "50px 54px 42px", display: "flex", flexDirection: "column", justifyContent: "space-between", pageBreakAfter: "always", overflow: "hidden", position: "relative" },
  pdfCoverGlow: { position: "absolute", width: 470, height: 470, borderRadius: 78, right: -135, top: -118, border: "46px solid rgba(255,255,255,.12)", transform: "rotate(30deg)" },
  pdfCoverMark: { position: "absolute", width: 335, height: 335, border: "30px solid rgba(255,255,255,.085)", borderRadius: 62, left: -118, bottom: 132, transform: "rotate(45deg)" },
  pdfCoverTop: { position: "relative", zIndex: 1, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24 },
  pdfCoverLogoBox: { width: 240, height: 142, display: "grid", placeItems: "center", padding: 0, position: "relative", overflow: "hidden", filter: "drop-shadow(0 24px 42px rgba(0,28,82,.28))" },
  pdfCoverLogo: { width: "100%", height: "100%", objectFit: "contain", position: "relative", zIndex: 1 },
  pdfCoverKicker: { textAlign: "right", textTransform: "uppercase", fontSize: 12, fontWeight: 950, letterSpacing: ".18em", color: "rgba(255,255,255,.78)" },
  pdfCoverHero: { position: "relative", zIndex: 1, display: "grid", gap: 18, maxWidth: 610 },
  pdfCoverCompany: { width: "fit-content", border: "1px solid rgba(255,255,255,.35)", background: "rgba(255,255,255,.14)", borderRadius: 999, padding: "9px 14px", fontSize: 13, fontWeight: 900, letterSpacing: ".04em", textTransform: "uppercase" },
  pdfCoverTitle: { fontSize: 62, lineHeight: .94, fontWeight: 950, letterSpacing: "-.035em", textTransform: "uppercase", textShadow: "0 18px 36px rgba(0,28,82,.22)" },
  pdfCoverSubtitle: { maxWidth: 570, fontSize: 19, lineHeight: 1.35, color: "rgba(255,255,255,.86)", fontWeight: 650 },
  pdfCoverMeta: { position: "relative", zIndex: 1, display: "grid", gridTemplateColumns: "1.35fr .65fr", gap: 18, alignItems: "end" },
  pdfCoverNoteBox: { border: "1px solid rgba(255,255,255,.28)", background: "rgba(255,255,255,.13)", borderRadius: 20, padding: "18px 20px", boxShadow: "0 18px 46px rgba(0,28,82,.16)" },
  pdfCoverNoteLabel: { fontSize: 11, textTransform: "uppercase", letterSpacing: ".16em", color: "rgba(255,255,255,.68)", fontWeight: 950, marginBottom: 8 },
  pdfCoverNoteText: { fontSize: 14, lineHeight: 1.45, color: "rgba(255,255,255,.9)", fontWeight: 650 },
  pdfCoverDateBox: { borderRadius: 20, background: "#ffffff", color: "#033b8b", padding: "18px 20px", textAlign: "right", boxShadow: "0 18px 46px rgba(0,28,82,.2)" },
  pdfCoverDateLabel: { fontSize: 11, textTransform: "uppercase", letterSpacing: ".16em", color: "#64748b", fontWeight: 950, marginBottom: 6 },
  pdfCoverDateValue: { fontSize: 18, fontWeight: 950, lineHeight: 1.15 },
  pdfWatermark: { position: "absolute", right: 26, bottom: 58, width: 150, opacity: .035, filter: "grayscale(1)" },
  pdfHeader: { border: "1px solid #d7e4f3", borderRadius: 16, padding: "10px 13px", background: "linear-gradient(135deg, #ffffff 0%, #f8fbff 54%, #eaf5ff 100%)", boxShadow: "0 10px 22px rgba(0,62,142,.07)", position: "relative", overflow: "hidden" },
  pdfHeaderAccent: { position: "absolute", left: 0, top: 0, bottom: 0, width: 7, background: "linear-gradient(180deg, #0047b6 0%, #08a9f0 100%)" },
  pdfHeaderTop: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" },
  pdfHeaderBrand: { display: "flex", alignItems: "center", gap: 11, minWidth: 0 },
  pdfHeaderLogoWrap: { width: 74, height: 38, display: "grid", placeItems: "center", padding: 0, position: "relative", overflow: "hidden" },
  pdfHeaderLogo: { width: "100%", height: "100%", objectFit: "contain", position: "relative", zIndex: 1 },
  pdfHeaderTitle: { fontSize: 20, fontWeight: 950, lineHeight: 1.05, color: "#083f91" },
  pdfHeaderSubtitle: { marginTop: 4, fontSize: 11.5, color: "#475569", lineHeight: 1.25, maxWidth: 500 },
  pdfHeaderMeta: { display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" },
  pdfHeaderChip: { border: "1px solid #cfe0f5", background: "#fff", borderRadius: 999, padding: "5px 8px", fontSize: 9.5, fontWeight: 850, color: "#0f4a99" },
  pdfBadge: { border: "1px solid rgba(255,255,255,.42)", background: "linear-gradient(135deg, #064fb4 0%, #09a8ef 100%)", borderRadius: 999, padding: "4px 6px", fontSize: 8.3, fontWeight: 900, color: "#fff", boxShadow: "0 8px 18px rgba(0,62,142,.16)" },
  pdfGrid: { display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 6, alignItems: "stretch", flex: 1, alignContent: "start", position: "relative", zIndex: 1 },
  pdfCard: { border: "1px solid #d5e4f3", borderRadius: 10, background: "#fff", overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 0, boxShadow: "0 6px 14px rgba(0,50,120,.065)" },
  pdfImageWrap: { height: 48, background: "linear-gradient(180deg, #ffffff 0%, #f7fbff 100%)", borderBottom: "1px solid #e2edf8", position: "relative", display: "flex", alignItems: "center", justifyContent: "center", padding: 4, marginBottom: 2, overflow: "hidden" },
  pdfImage: { width: "auto", height: "auto", maxWidth: "92%", maxHeight: 42, objectFit: "contain", background: "transparent", display: "block", margin: "0 auto" },
  pdfPlaceholder: { width: 36, height: 36, display: "grid", placeItems: "center", borderRadius: 999, background: "rgba(148,163,184,.08)", border: "1px dashed rgba(148,163,184,.42)", color: "#64748b", fontSize: 6.6, fontWeight: 900, textAlign: "center", padding: 4 },
  pdfBadgeGroup: { position: "absolute", top: 4, left: 4, display: "flex", gap: 3, flexWrap: "wrap", zIndex: 1 },
  pdfBody: { flex: 1, padding: "6px 6px 5px", display: "grid", gap: 3, alignContent: "start", minHeight: 0 },
  pdfSku: { color: "#2563aa", fontWeight: 850, fontSize: 7.2, letterSpacing: ".06em", lineHeight: 1.08, textTransform: "uppercase" },
  pdfTitle: { color: "#0d1b2e", fontSize: 9.1, fontWeight: 950, lineHeight: 1.1, display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 3, overflow: "hidden", minHeight: 31 },
  pdfTagLine: { color: "#64748b", fontSize: 7.5, lineHeight: 1.12, display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 1, overflow: "hidden" },
  pdfPriceBlock: { marginTop: "auto", padding: "0 6px 7px", display: "grid", gap: 2, alignContent: "end" },
  pdfPriceMain: { fontSize: 14.8, fontWeight: 950, lineHeight: 1.02, color: "#0047b6" },
  pdfPriceSecondary: { color: "#64748b", fontSize: 7.5, fontWeight: 750, lineHeight: 1.15, wordBreak: "break-word" },
  pdfFooter: { marginTop: "auto", display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", borderTop: "1px solid #dbe7f5", paddingTop: 7, color: "#64748b", fontSize: 10, fontWeight: 800 },
  pdfFooterBrand: { color: "#064fb4", fontWeight: 950, textTransform: "uppercase", letterSpacing: ".08em" },
  layoutShell: { display: "grid", gap: 14 },
  layoutTopbar: { display: "grid", gridTemplateColumns: "minmax(240px, 1.3fr) minmax(260px, 1fr) auto", gap: 10, alignItems: "stretch" },
  layoutPanel: { border: "1px solid var(--border)", background: "var(--panel, #fff)", padding: 14, boxShadow: "0 8px 24px rgba(15,23,42,.04)" },
  layoutSectionTitle: { fontSize: 15, fontWeight: 950, marginBottom: 3 },
  layoutSectionMeta: { color: "var(--muted)", fontSize: 13, lineHeight: 1.3 },
  layoutStats: { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 },
  layoutStatCard: { border: "1px solid var(--border)", background: "rgba(248,250,252,.92)", padding: 10, borderRadius: 10 },
  layoutStatLabel: { color: "var(--muted)", fontSize: 12, fontWeight: 800, textTransform: "uppercase", letterSpacing: ".03em" },
  layoutStatValue: { fontSize: 18, fontWeight: 950, lineHeight: 1.15 },
  layoutNotice: { border: "1px solid #fde68a", background: "#fffbeb", color: "#92400e", padding: "10px 12px", borderRadius: 10, fontSize: 13, fontWeight: 700 },
  layoutSuccess: { border: "1px solid #bbf7d0", background: "#f0fdf4", color: "#166534", padding: "10px 12px", borderRadius: 10, fontSize: 13, fontWeight: 700 },
  layoutTableRowSelected: { background: "rgba(29,78,216,.05)" },
  layoutToolbar: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-end", flexWrap: "wrap" },
  layoutButtonRow: { display: "flex", gap: 8, flexWrap: "wrap" },
  layoutTh: { textAlign: "left", padding: "8px 10px", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: ".03em" },
  layoutTd: { padding: "8px 10px", borderBottom: "1px solid var(--border)", verticalAlign: "middle" },
  layoutSectionHeader: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 10 },
};

export default function Catalog() {
  const [company, setCompany] = useState("parton");
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState({ total: 0, active: 0, featured: 0, without_image: 0 });
  const [filtersMeta, setFiltersMeta] = useState({ categories: [], situations: [] });
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [image, setImage] = useState("");
  const [featured, setFeatured] = useState("");
  const [category, setCategory] = useState("");
  const [situation, setSituation] = useState("");
  const [mode, setMode] = useState("management");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [stockSyncing, setStockSyncing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState({});
  const [imageUploading, setImageUploading] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [galleryError, setGalleryError] = useState("");
  const [gallerySearch, setGallerySearch] = useState("");
  const [galleryImages, setGalleryImages] = useState([]);
  const [dirtyRows, setDirtyRows] = useState({});
  const [managementView, setManagementView] = useState("products");
  const [priceTables, setPriceTables] = useState([]);
  const [bulkPriceMode, setBulkPriceMode] = useState("");
  const [campaigns, setCampaigns] = useState([]);
  const [priceTableDraft, setPriceTableDraft] = useState({
    name: "",
    mode: "percent",
    base_field: "price_tiny",
    full_price_percent: "",
    billed_price_percent: "",
    cash_price_percent: "",
    active: true,
    is_default: false,
  });
  const [editingPriceTable, setEditingPriceTable] = useState(null);
  const [campaignDraft, setCampaignDraft] = useState({
    name: "",
    description: "",
    start_date: todayISO(),
    end_date: todayISO(5),
    discount_percent: "",
    price_table_id: "",
    active: true,
  });
  const [editingCampaign, setEditingCampaign] = useState(null);
  const [campaignProductIds, setCampaignProductIds] = useState([]);
  const [layouts, setLayouts] = useState([]);
  const [layoutsLoading, setLayoutsLoading] = useState(false);
  const [selectedLayoutId, setSelectedLayoutId] = useState("");
  const [layoutDraft, setLayoutDraft] = useState(() => defaultLayoutDraft("parton"));
  const [layoutSaving, setLayoutSaving] = useState(false);
  const [layoutItemsSaving, setLayoutItemsSaving] = useState(false);
  const [layoutProductState, setLayoutProductState] = useState({});
  const [layoutPreview, setLayoutPreview] = useState([]);
  const [layoutPreviewLoading, setLayoutPreviewLoading] = useState(false);
  const [layoutPreviewError, setLayoutPreviewError] = useState("");
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [layoutSaveMessage, setLayoutSaveMessage] = useState("");
  const [pdfExporting, setPdfExporting] = useState(false);
  const previewExportRef = useRef(null);
  const catalogPdfRef = useRef(null);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const total = Number(summary?.filtered_total ?? 0);
  const selectedCompany = COMPANIES.find((item) => item.key === company)?.label || company;
  const effectiveStatus = mode === "preview" ? "active" : status;
  const selectedBulkPriceTable = priceTables.find((item) => String(item.id) === String(bulkPriceMode));
  const selectedLayout = layouts.find((item) => String(item.id) === String(selectedLayoutId));
  const selectedLayoutCount = Object.values(layoutProductState).filter((item) => item?.selected).length;
  const layoutPageSelectedCount = items.filter((item) => layoutProductState[item.id]?.selected).length;
  const layoutPendingLabel = layoutDirty ? "Há alterações pendentes" : "Tudo salvo";
  const pdfPages = useMemo(() => {
    const cards = items.map((item) => {
      const description = item.catalog_title || item.catalog_description || item.name_tiny || item.sku || "Produto sem descrição";
      const useCampaignPrices = Boolean(layoutDraft.use_active_campaigns && item.campaign_active);
      const priceValues = [
        layoutDraft.show_full_price ? (useCampaignPrices ? (item.campaign_full_price_value ?? item.final_full_price_value ?? item.full_price_value) : (item.final_full_price_value ?? item.full_price_value)) : null,
        layoutDraft.show_billed_price ? (useCampaignPrices ? (item.campaign_billed_price_value ?? item.final_billed_price_value ?? item.billed_price_value) : (item.final_billed_price_value ?? item.billed_price_value)) : null,
        layoutDraft.show_cash_price ? (useCampaignPrices ? (item.campaign_cash_price_value ?? item.final_cash_price_value ?? item.cash_price_value) : (item.final_cash_price_value ?? item.cash_price_value)) : null,
      ].filter((value) => value !== null && value !== undefined && value !== "");
      const primaryPrice = priceValues[0];
      const secondaryPrices = priceValues.slice(1);
      return {
        id: item.id,
        sku: item.sku || "",
        description,
        tagLine: String(item.catalog_tags || item.catalog_benefits || "")
          .split(/[,;\n]/)
          .map((value) => value.trim())
          .filter(Boolean)
          .slice(0, 3)
          .join(" · "),
        featured: Boolean(item.catalog_featured),
        campaign: useCampaignPrices,
        image: imageFor(item),
        placeholder: !imageFor(item),
        showSku: Boolean(layoutDraft.show_sku),
        showTags: Boolean(layoutDraft.show_tags),
        showStock: Boolean(layoutDraft.show_stock),
        stockLabel: formatStock(item.stock_available),
        primaryPrice,
        secondaryPrices,
      };
    });
    return chunkArray(cards, PDF_PRODUCTS_PER_PAGE).map((cardItems, index) => ({
      number: index + 1,
      cards: cardItems,
    }));
  }, [items, layoutDraft]);

  const params = useMemo(() => ({
    company,
    search,
    status: effectiveStatus,
    image,
    featured: featured === "" ? undefined : featured === "true",
    category,
    situation,
    limit: PAGE_SIZE,
    offset,
  }), [category, company, effectiveStatus, featured, image, offset, search, situation]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await withGlobalLoading("Carregando catálogo...", () => api.adminCatalogProducts(params));
      const nextItems = Array.isArray(result?.items) ? result.items : [];
      setItems(mode === "preview"
        ? [...nextItems].sort((a, b) => {
          if (Boolean(a.catalog_featured) !== Boolean(b.catalog_featured)) return a.catalog_featured ? -1 : 1;
          const orderA = a.catalog_order ?? 999999;
          const orderB = b.catalog_order ?? 999999;
          if (orderA !== orderB) return orderA - orderB;
          return String(a.catalog_title || a.name_tiny || a.sku || "").localeCompare(String(b.catalog_title || b.name_tiny || b.sku || ""), "pt-BR");
        })
        : nextItems);
      setSummary({ ...(result?.summary || {}), filtered_total: Number(result?.total || 0) });
      setFiltersMeta(result?.filters || { categories: [], situations: [] });
      setDirtyRows({});
    } catch (e) {
      setError(e?.message || "Erro ao carregar catálogo.");
    } finally {
      setLoading(false);
    }
  }, [mode, params]);

  useEffect(() => {
    load();
  }, [load]);

  function changeCompany(next) {
    setCompany(next);
    setOffset(0);
    setCategory("");
    setSituation("");
    setBulkPriceMode("");
    setEditing(null);
    setSelectedLayoutId("");
    setLayouts([]);
    setLayoutDraft(defaultLayoutDraft(next));
    setLayoutProductState({});
    setLayoutPreview([]);
    setLayoutPreviewError("");
    setLayoutDirty(false);
    setLayoutSaveMessage("");
  }

  function changeMode(next) {
    setMode(next);
    setOffset(0);
  }

  function layoutDraftFromItem(item) {
    return {
      id: item?.id ?? null,
      company_key: item?.company_key || company,
      name: item?.name || "",
      title: item?.title || "",
      subtitle: item?.subtitle || "",
      notes: item?.notes || "",
      valid_until: item?.valid_until ? String(item.valid_until).slice(0, 10) : "",
      use_active_campaigns: item?.use_active_campaigns !== false,
      show_full_price: item?.show_full_price !== false,
      show_billed_price: item?.show_billed_price !== false,
      show_cash_price: item?.show_cash_price !== false,
      show_sku: item?.show_sku !== false,
      show_tags: Boolean(item?.show_tags),
      show_stock: Boolean(item?.show_stock),
      show_without_image: item?.show_without_image !== false,
      only_active_products: item?.only_active_products !== false,
      active: item?.active !== false,
    };
  }

  async function loadLayouts() {
    setLayoutsLoading(true);
    setLayoutPreviewError("");
    try {
      const result = await api.adminCatalogLayouts({ company });
      const nextLayouts = Array.isArray(result?.items) ? result.items : [];
      setLayouts(nextLayouts);
      if (!selectedLayoutId && nextLayouts.length) {
        setSelectedLayoutId(String(nextLayouts[0].id));
      } else if (selectedLayoutId && !nextLayouts.some((item) => String(item.id) === String(selectedLayoutId))) {
        setSelectedLayoutId(nextLayouts.length ? String(nextLayouts[0].id) : "");
      }
      if (!nextLayouts.length) {
        setLayoutDraft(defaultLayoutDraft(company));
        setLayoutProductState({});
        setLayoutPreview([]);
        setLayoutDirty(false);
        setLayoutSaveMessage("");
      }
    } catch (e) {
      setError(e?.message || "Erro ao carregar montagens.");
    } finally {
      setLayoutsLoading(false);
    }
  }

  async function loadLayoutDetails(layoutId) {
    if (!layoutId) return;
    setLayoutPreviewLoading(true);
    setLayoutPreviewError("");
    try {
      const result = await api.adminCatalogLayout(layoutId);
      const layout = result?.item || {};
      setLayoutDraft(layoutDraftFromItem(layout));
      setSelectedLayoutId(String(layout.id || layoutId));
      const nextState = {};
      for (const row of result?.items || []) {
        nextState[row.product_catalog_id] = {
          selected: row.selected !== false,
          sort_order: row.sort_order ?? "",
        };
      }
      setLayoutProductState(nextState);
      const previewResult = await api.adminCatalogLayoutPreview(layoutId);
      setLayoutPreview(Array.isArray(previewResult?.items) ? previewResult.items : []);
      if (previewResult?.layout) {
        setLayoutDraft(layoutDraftFromItem(previewResult.layout));
      }
      setLayoutDirty(false);
    } catch (e) {
      setLayoutPreview([]);
      setLayoutPreviewError(e?.message || "Erro ao carregar configuração.");
    } finally {
      setLayoutPreviewLoading(false);
    }
  }

  async function refreshLayoutPreview() {
    if (!selectedLayoutId) return;
    setLayoutPreviewLoading(true);
    setLayoutPreviewError("");
    try {
      const result = await api.adminCatalogLayoutPreview(selectedLayoutId);
      setLayoutPreview(Array.isArray(result?.items) ? result.items : []);
      if (result?.layout) {
        setLayoutDraft(layoutDraftFromItem(result.layout));
      }
    } catch (e) {
      setLayoutPreviewError(e?.message || "Erro ao atualizar a prévia da configuração.");
    } finally {
      setLayoutPreviewLoading(false);
    }
  }

  async function saveLayout() {
    setLayoutSaving(true);
    setError("");
    setMessage("");
    try {
      const payload = {
        ...layoutDraft,
        company_key: company,
      };
      const result = layoutDraft.id
        ? await api.adminUpdateCatalogLayout(layoutDraft.id, payload)
        : await api.adminCreateCatalogLayout(payload);
      const saved = result?.item || {};
      const savedId = saved.id || layoutDraft.id;
      setMessage("Configuração salva.");
      setLayoutSaveMessage("Configuração salva com sucesso.");
      await loadLayouts();
      if (savedId) {
        setSelectedLayoutId(String(savedId));
        await loadLayoutDetails(savedId);
      }
    } catch (e) {
      setError(e?.message || "Erro ao salvar configuração.");
    } finally {
      setLayoutSaving(false);
    }
  }

  function updateLayoutState(productId, patch) {
    setLayoutDirty(true);
    setLayoutSaveMessage("");
    setLayoutProductState((current) => {
      const previous = current[productId] || { selected: false, sort_order: "" };
      return { ...current, [productId]: { ...previous, ...patch } };
    });
  }

  function selectLayoutPageRows(selected) {
    const next = {};
    items.forEach((item, index) => {
      const existing = layoutProductState[item.id] || {};
      next[item.id] = {
        selected,
        sort_order: existing.sort_order || index + 1,
      };
    });
    setLayoutProductState((current) => ({ ...current, ...next }));
    setLayoutDirty(true);
    setLayoutSaveMessage("");
  }

  function updateLayoutDraft(patch) {
    setLayoutDraft((current) => ({ ...current, ...patch }));
    setLayoutDirty(true);
    setLayoutSaveMessage("");
  }

  async function saveLayoutItems() {
    if (!selectedLayoutId) return;
    setLayoutItemsSaving(true);
    setError("");
    setMessage("");
    try {
      const payloadItems = items
        .map((item, index) => {
          const state = layoutProductState[item.id];
          if (!state) return null;
          return {
            product_catalog_id: item.id,
            selected: state.selected !== false,
            sort_order: state.sort_order === "" || state.sort_order === null || state.sort_order === undefined
              ? index + 1
              : Number(state.sort_order),
          };
        })
        .filter(Boolean);
      const result = await api.adminSaveCatalogLayoutItems(selectedLayoutId, {
        company_key: company,
        items: payloadItems,
      });
      setMessage(`Itens da configuração salvos (${result.saved || 0}).`);
      setLayoutSaveMessage(`Itens salvos: ${result.saved || 0}.`);
      await loadLayoutDetails(selectedLayoutId);
    } catch (e) {
      setError(e?.message || "Erro ao salvar itens da configuração.");
    } finally {
      setLayoutItemsSaving(false);
    }
  }

  function createNewLayout() {
    setSelectedLayoutId("");
    setLayoutDraft(defaultLayoutDraft(company));
    setLayoutProductState({});
    setLayoutPreview([]);
    setLayoutPreviewError("");
    setLayoutDirty(true);
    setLayoutSaveMessage("Nova configuração pronta para edição.");
  }

  async function handleExportCatalogPdf() {
    if (!catalogPdfRef.current || pdfExporting) return;
    setPdfExporting(true);
    setError("");
    setMessage("");
    try {
      const stageNode = catalogPdfRef.current;
      const [{ default: html2canvas }] = await withTimeout(
        Promise.all([import("html2canvas")]),
        10000,
        "Tempo limite ao carregar o gerador de PDF."
      );
      if (document.fonts?.ready) {
        await withTimeout(document.fonts.ready, 5000, "Tempo limite ao carregar fontes do PDF.").catch(() => undefined);
      }
      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const pages = Array.from(stageNode.querySelectorAll('[data-pdf-page="true"]'))
        .filter((pageNode) => pageNode instanceof HTMLElement && pageNode.offsetWidth > 0 && pageNode.offsetHeight > 0);
      if (!pages.length) {
        throw new Error("Nenhuma página do PDF foi encontrada.");
      }
      for (let index = 0; index < pages.length; index += 1) {
        const pageNode = pages[index];
        await waitForImages(pageNode, 5000);
        const canvas = await withTimeout(
          html2canvas(pageNode, {
            scale: 1.5,
            useCORS: true,
            allowTaint: true,
            backgroundColor: "#ffffff",
            scrollX: 0,
            scrollY: 0,
            windowWidth: pageNode.scrollWidth || 794,
            windowHeight: pageNode.scrollHeight || 1123,
          }),
          30000,
          `Tempo limite ao gerar a página ${index + 1} do PDF.`
        );
        const imgData = canvas.toDataURL("image/jpeg", 0.95);
        if (index > 0) pdf.addPage();
        pdf.addImage(imgData, "JPEG", 0, 0, pageWidth, pageHeight, undefined, "FAST");
      }
      const dateStamp = todayISO().replace(/-/g, "");
      const companySlug = company === "park" ? "informatica" : "suprimentos";
      pdf.save(`catalogo-${companySlug}-${dateStamp}.pdf`);
      setMessage("PDF gerado com sucesso.");
    } catch (e) {
      console.error("Erro ao exportar PDF do catálogo", e);
      setError("Não foi possível gerar o PDF. Tente novamente.");
    } finally {
      setPdfExporting(false);
    }
  }

  const commercialPrices = (item) => [
    { key: "full", label: "Valor Cheio", percent: item?.final_full_price_percent ?? item?.full_price_percent, value: item?.campaign_full_price_value ?? item?.final_full_price_value ?? item?.full_price_value, normalValue: item?.final_full_price_value ?? item?.full_price_value },
    { key: "billed", label: "Valor Faturado", percent: item?.final_billed_price_percent ?? item?.billed_price_percent, value: item?.campaign_billed_price_value ?? item?.final_billed_price_value ?? item?.billed_price_value, normalValue: item?.final_billed_price_value ?? item?.billed_price_value },
    { key: "cash", label: "Valor à Vista", percent: item?.final_cash_price_percent ?? item?.cash_price_percent, value: item?.campaign_cash_price_value ?? item?.final_cash_price_value ?? item?.cash_price_value, normalValue: item?.final_cash_price_value ?? item?.cash_price_value },
  ];

  const previewPriceTriplet = (item) => {
    const prices = commercialPrices(item);
    const full = prices.find((price) => price.key === "full")?.value || "";
    const billed = prices.find((price) => price.key === "billed")?.value || "";
    const cash = prices.find((price) => price.key === "cash")?.value || "";
    return { full, billed, cash };
  };

  const commercialValue = (value) => (value ? formatBRL(value) : "Sob consulta");

  const dirtyCount = Object.keys(dirtyRows).length;

  function numberOrNull(value) {
    if (value === "" || value === null || value === undefined) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function priceBaseFor(item) {
    const priceTiny = numberOrNull(item?.price_tiny);
    if (priceTiny !== null) return priceTiny;
    return numberOrNull(item?.average_cost);
  }

  function calculatedValue(item, percent) {
    const base = priceBaseFor(item);
    const pct = numberOrNull(percent);
    if (base === null || pct === null) return null;
    return Math.round((base * (1 + pct / 100)) * 100) / 100;
  }

  function rowValue(item, key) {
    return dirtyRows[item.id]?.[key] ?? item[key];
  }

  function rowFinalValue(item, key, finalKey) {
    return dirtyRows[item.id]?.[key] ?? item[finalKey] ?? item[key];
  }

  function updateRow(item, patch) {
    setDirtyRows((current) => {
      const previous = current[item.id] || {
        id: item.id,
        price_mode: item.price_mode || "custom",
        price_table_id: item.price_table_id || null,
        full_price_percent: item.full_price_percent ?? null,
        full_price_value: item.full_price_value ?? null,
        billed_price_percent: item.billed_price_percent ?? null,
        billed_price_value: item.billed_price_value ?? null,
        cash_price_percent: item.cash_price_percent ?? null,
        cash_price_value: item.cash_price_value ?? null,
        catalog_active: Boolean(item.catalog_active),
        catalog_featured: Boolean(item.catalog_featured),
      };
      return { ...current, [item.id]: { ...previous, ...patch } };
    });
  }

  function updatePercent(item, percentKey, valueKey, value) {
    const nextPercent = value === "" ? "" : value;
    const seedCurrentFinalPrices = dirtyRows[item.id] ? {} : {
      full_price_percent: item.final_full_price_percent ?? item.full_price_percent ?? null,
      full_price_value: item.final_full_price_value ?? item.full_price_value ?? null,
      billed_price_percent: item.final_billed_price_percent ?? item.billed_price_percent ?? null,
      billed_price_value: item.final_billed_price_value ?? item.billed_price_value ?? null,
      cash_price_percent: item.final_cash_price_percent ?? item.cash_price_percent ?? null,
      cash_price_value: item.final_cash_price_value ?? item.cash_price_value ?? null,
    };
    updateRow(item, {
      ...seedCurrentFinalPrices,
      price_mode: "custom",
      price_table_id: null,
      [percentKey]: nextPercent,
      [valueKey]: calculatedValue(item, nextPercent),
    });
  }

  async function savePageChanges() {
    const itemsToSave = Object.values(dirtyRows);
    if (!itemsToSave.length) return;
    setError("");
    setMessage("");
    try {
      const result = await api.adminCatalogBulkUpdateProducts({ company_key: company, items: itemsToSave });
      setMessage(`Produtos da página salvos (${result.updated || 0}).`);
      await load();
    } catch (e) {
      setError(e?.message || "Erro ao salvar alterações da página.");
    }
  }

  async function syncLocal() {
    setSyncing(true);
    setError("");
    setMessage("");
    try {
      const result = await withGlobalLoading("Sincronizando produtos locais...", () => api.adminCatalogSyncLocal({ company }));
      setMessage(`Sincronização local: ${result.created || 0} criados, ${result.updated || 0} atualizados, ${result.ignored || 0} ignorados.`);
      setOffset(0);
      await load();
    } catch (e) {
      setError(e?.message || "Erro ao sincronizar produtos locais.");
    } finally {
      setSyncing(false);
    }
  }

  const loadPriceTables = useCallback(async () => {
    try {
      const result = await api.adminCatalogPriceTables({ company });
      setPriceTables(Array.isArray(result?.items) ? result.items : []);
    } catch (e) {
      setError(e?.message || "Erro ao carregar tabelas de preço.");
    }
  }, [company]);

  useEffect(() => {
    loadPriceTables();
  }, [loadPriceTables]);

  const loadCampaigns = useCallback(async () => {
    try {
      const result = await api.adminCatalogCampaigns({ company });
      setCampaigns(Array.isArray(result?.items) ? result.items : []);
    } catch (e) {
      setError(e?.message || "Erro ao carregar campanhas.");
    }
  }, [company]);

  useEffect(() => {
    loadCampaigns();
  }, [loadCampaigns]);

  useEffect(() => {
    if (mode !== "layout" && !(mode === "management" && managementView === "options")) return;
    loadLayouts();
  }, [mode, company, managementView]);

  useEffect(() => {
    if (!(mode === "layout" || (mode === "management" && managementView === "options")) || !selectedLayoutId) return;
    loadLayoutDetails(selectedLayoutId);
  }, [mode, selectedLayoutId, managementView]);

  function resetPriceTableDraft() {
    setEditingPriceTable(null);
    setPriceTableDraft({
      name: "",
      mode: "percent",
      base_field: "price_tiny",
      full_price_percent: "",
      billed_price_percent: "",
      cash_price_percent: "",
      active: true,
      is_default: false,
    });
  }

  function editPriceTable(item) {
    setEditingPriceTable(item);
    setPriceTableDraft({
      name: item.name || "",
      mode: item.mode || "percent",
      base_field: item.base_field || "price_tiny",
      full_price_percent: item.full_price_percent ?? "",
      billed_price_percent: item.billed_price_percent ?? "",
      cash_price_percent: item.cash_price_percent ?? "",
      active: Boolean(item.active),
      is_default: Boolean(item.is_default),
    });
  }

  async function savePriceTable() {
    setError("");
    setMessage("");
    const payload = { ...priceTableDraft, company_key: company };
    try {
      if (editingPriceTable?.id) {
        await api.adminCatalogUpdatePriceTable(editingPriceTable.id, payload);
      } else {
        await api.adminCatalogCreatePriceTable(payload);
      }
      setMessage("Tabela de preço salva.");
      resetPriceTableDraft();
      await loadPriceTables();
      await load();
    } catch (e) {
      setError(e?.message || "Erro ao salvar tabela de preço.");
    }
  }

  function resetCampaignDraft() {
    setEditingCampaign(null);
    setCampaignProductIds([]);
    setCampaignDraft({
      name: "",
      description: "",
      start_date: todayISO(),
      end_date: todayISO(5),
      discount_percent: "",
      price_table_id: "",
      active: true,
    });
  }

  async function editCampaign(item) {
    setEditingCampaign(item);
    setCampaignDraft({
      name: item.name || "",
      description: item.description || "",
      start_date: String(item.start_date || todayISO()).slice(0, 10),
      end_date: String(item.end_date || todayISO(5)).slice(0, 10),
      discount_percent: item.discount_percent ?? "",
      price_table_id: item.price_table_id || "",
      active: Boolean(item.active),
    });
    try {
      const result = await api.adminCatalogCampaignItems(item.id, { company });
      setCampaignProductIds((result?.items || []).map((entry) => Number(entry.product_catalog_id)).filter(Boolean));
    } catch (e) {
      setError(e?.message || "Erro ao carregar produtos da campanha.");
    }
  }

  async function saveCampaign() {
    setError("");
    setMessage("");
    const payload = { ...campaignDraft, company_key: company };
    try {
      const result = editingCampaign?.id
        ? await api.adminCatalogUpdateCampaign(editingCampaign.id, payload)
        : await api.adminCatalogCreateCampaign(payload);
      const campaignId = editingCampaign?.id || result?.item?.id;
      if (campaignId) {
        await api.adminCatalogSaveCampaignItems(campaignId, { company_key: company, product_ids: campaignProductIds });
      }
      setMessage("Campanha salva.");
      resetCampaignDraft();
      await loadCampaigns();
      await load();
    } catch (e) {
      setError(e?.message || "Erro ao salvar campanha.");
    }
  }

  function toggleCampaignProduct(productId) {
    const id = Number(productId);
    setCampaignProductIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function applyBulkPriceMode() {
    const productIds = items.map((item) => Number(item.id)).filter(Boolean);
    if (!bulkPriceMode || !productIds.length) return;
    const isCustom = bulkPriceMode === "custom";
    const table = isCustom ? null : priceTables.find((item) => String(item.id) === String(bulkPriceMode));
    if (!isCustom && !table) {
      setError("Selecione uma tabela de preço válida.");
      return;
    }
    const confirmMessage = isCustom
      ? "Isso vai colocar os produtos da página em modo Custom. Os valores manuais salvos serão usados. Deseja continuar?"
      : "Isso vai alterar a tabela de preço dos produtos da página desta empresa. Os valores custom serão preservados, mas os produtos passarão a usar a tabela selecionada. Deseja continuar?";
    if (!window.confirm(confirmMessage)) return;
    setError("");
    setMessage("");
    try {
      const result = await api.adminCatalogApplyPriceTable({
        company_key: company,
        price_mode: isCustom ? "custom" : "table",
        price_table_id: isCustom ? null : table.id,
        product_ids: productIds,
      });
      setMessage(isCustom ? `Produtos alterados para Custom (${result.updated || 0}).` : `Tabela aplicada aos produtos (${result.updated || 0}).`);
      setBulkPriceMode("");
      await load();
    } catch (e) {
      setError(e?.message || "Erro ao aplicar tabela aos produtos.");
    }
  }

  async function syncTinyStock() {
    const productIds = items.map((item) => Number(item.id)).filter(Boolean);
    if (!productIds.length) return;
    setStockSyncing(true);
    setError("");
    setMessage("");
    try {
      const result = await api.adminCatalogSyncStock({ company_key: company, product_ids: productIds });
      setMessage(result.errors ? "Estoque atualizado parcialmente." : "Estoque Tiny atualizado.");
      await load();
    } catch (e) {
      setError(e?.message || "Erro ao atualizar estoque Tiny.");
    } finally {
      setStockSyncing(false);
    }
  }

  function openEdit(item) {
    setEditing(item);
    setGalleryOpen(false);
    setGalleryLoading(false);
    setGalleryError("");
    setGallerySearch("");
    setGalleryImages([]);
    setDraft({
      catalog_title: item.catalog_title || "",
      catalog_description: item.catalog_description || "",
      catalog_benefits: item.catalog_benefits || "",
      catalog_tags: item.catalog_tags || "",
      catalog_price: item.catalog_price ?? "",
      catalog_image_url: item.catalog_image_url || "",
      catalog_image_path: item.catalog_image_path || "",
      catalog_image_filename: item.catalog_image_filename || "",
      price_mode: item.price_mode || "custom",
      price_table_id: item.price_table_id || "",
      full_price_percent: item.full_price_percent ?? "",
      full_price_value: item.full_price_value ?? "",
      billed_price_percent: item.billed_price_percent ?? "",
      billed_price_value: item.billed_price_value ?? "",
      cash_price_percent: item.cash_price_percent ?? "",
      cash_price_value: item.cash_price_value ?? "",
      catalog_active: Boolean(item.catalog_active),
      catalog_featured: Boolean(item.catalog_featured),
      catalog_order: item.catalog_order ?? "",
      internal_notes: item.internal_notes || "",
    });
  }

  async function saveEdit() {
    if (!editing?.id) return;
    setError("");
    setMessage("");
    try {
      await withGlobalLoading("Salvando produto do catálogo...", () => api.adminCatalogUpdateProduct(editing.id, draft));
      setMessage("Produto de catálogo salvo.");
      setGalleryOpen(false);
      setEditing(null);
      await load();
    } catch (e) {
      setError(e?.message || "Erro ao salvar produto do catálogo.");
    }
  }

  async function uploadCatalogImage(file) {
    if (!file) return;
    setImageUploading(true);
    setError("");
    setMessage("");
    try {
      const result = await api.adminUploadCatalogImage(file);
      const filename = result?.filename || "";
      setDraft((current) => ({ ...current, catalog_image_filename: filename, catalog_image_path: filename }));
      setMessage("Imagem enviada.");
    } catch (e) {
      setError(e?.message || "Erro ao enviar imagem.");
    } finally {
      setImageUploading(false);
      const input = document.getElementById("catalog-image-upload-input");
      if (input) input.value = "";
    }
  }

  async function openGallery() {
    if (!editing?.id) return;
    setGalleryOpen(true);
    setGalleryLoading(true);
    setGalleryError("");
    setGallerySearch("");
    try {
      const result = await api.adminListCatalogImages();
      setGalleryImages(result?.items || []);
    } catch (e) {
      setGalleryImages([]);
      setGalleryError(e?.message || "Erro ao carregar a galeria.");
    } finally {
      setGalleryLoading(false);
    }
  }

  function selectGalleryImage(item) {
    const filename = String(item?.filename || "").trim();
    if (!filename) return;
    setDraft((current) => ({
      ...current,
      catalog_image_filename: filename,
      catalog_image_path: filename,
    }));
    setGalleryOpen(false);
    setMessage("Imagem selecionada da galeria.");
  }

  const filteredGalleryImages = useMemo(() => {
    const term = gallerySearch.trim().toLowerCase();
    if (!term) return galleryImages;
    return galleryImages.filter((item) => String(item?.filename || "").toLowerCase().includes(term));
  }, [galleryImages, gallerySearch]);

  async function quickToggle(item, field) {
    await api.adminCatalogUpdateProduct(item.id, {
      ...item,
      [field]: !item[field],
    });
    await load();
  }

  return (
    <div style={styles.page}>
      <PageHeader
        crumb="Administração"
        title="Catálogo"
        actions={mode === "management" ? (
          <Button variant="primary" onClick={syncLocal} loading={syncing}>
            Sincronizar produtos locais
          </Button>
        ) : null}
      />
      <div style={styles.muted}>Administre produtos e informações comerciais para futuros catálogos.</div>

      <div style={styles.tabs}>
        <Button variant={mode === "management" ? "primary" : "secondary"} onClick={() => changeMode("management")}>
          Gestão
        </Button>
        <Button variant={mode === "campaign" ? "primary" : "secondary"} onClick={() => changeMode("campaign")}>
          Campanha
        </Button>
        <Button variant={mode === "preview" ? "primary" : "secondary"} onClick={() => changeMode("preview")}>
          Prévia do catálogo
        </Button>
      </div>

      <div style={styles.tabs}>
        {COMPANIES.map((item) => (
          <Button key={item.key} variant={company === item.key ? "primary" : "secondary"} onClick={() => changeCompany(item.key)}>
            {item.label}
          </Button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(150px, 1fr))", gap: 10 }}>
        <Card padding="sm"><div style={styles.muted}>Total</div><div style={{ fontSize: 24, fontWeight: 950 }}>{summary.total || 0}</div></Card>
        <Card padding="sm"><div style={styles.muted}>Incluídos</div><div style={{ fontSize: 24, fontWeight: 950 }}>{summary.active || 0}</div></Card>
        <Card padding="sm"><div style={styles.muted}>Sem imagem</div><div style={{ fontSize: 24, fontWeight: 950 }}>{summary.without_image || 0}</div></Card>
        <Card padding="sm"><div style={styles.muted}>Destaques</div><div style={{ fontSize: 24, fontWeight: 950 }}>{summary.featured || 0}</div></Card>
      </div>

      <div style={{ ...styles.card, display: "grid", gridTemplateColumns: "1.4fr repeat(6, minmax(130px, .7fr)) auto", gap: 10, alignItems: "center" }}>
        <input style={styles.input} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por SKU, nome ou título" />
        <select style={styles.input} value={mode === "preview" ? "active" : status} onChange={(e) => setStatus(e.target.value)} disabled={mode === "preview"}>
          <option value="">Todos</option>
          <option value="active">Incluídos no catálogo</option>
          <option value="inactive">Fora do catálogo</option>
        </select>
        <select style={styles.input} value={image} onChange={(e) => setImage(e.target.value)}>
          <option value="">Imagem</option>
          <option value="with">Com imagem</option>
          <option value="without">Sem imagem</option>
        </select>
        <select style={styles.input} value={featured} onChange={(e) => setFeatured(e.target.value)}>
          <option value="">Destaques</option>
          <option value="true">Somente destaques</option>
          <option value="false">Sem destaque</option>
        </select>
        <select style={styles.input} value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Categoria</option>
          {(filtersMeta.categories || []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select style={styles.input} value={situation} onChange={(e) => setSituation(e.target.value)}>
          <option value="">Situação</option>
          {(filtersMeta.situations || []).map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        {mode === "management" && managementView === "products" ? (
          <select style={styles.input} value={bulkPriceMode} onChange={(e) => setBulkPriceMode(e.target.value)}>
            <option value="">Valores atuais / sem alteração</option>
            <option value="custom">Custom</option>
            {priceTables.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        ) : null}
        <Button onClick={() => { setOffset(0); load(); }}>Aplicar</Button>
        {mode === "management" && managementView === "products" ? (
          <Button variant="primary" disabled={!bulkPriceMode || !items.length} onClick={applyBulkPriceMode}>
            Aplicar aos produtos da página
          </Button>
        ) : null}
        {mode === "management" && managementView === "products" ? (
          <Button loading={stockSyncing} disabled={!items.length} onClick={syncTinyStock}>
            Atualizar estoque Tiny
          </Button>
        ) : null}
        {mode === "management" && managementView === "products" ? (
          <Button variant="primary" disabled={!dirtyCount} onClick={savePageChanges}>
            Salvar alterações{dirtyCount ? ` (${dirtyCount})` : ""}
          </Button>
        ) : null}
      </div>

      {error ? <div style={{ ...styles.card, borderColor: "var(--danger)", color: "var(--danger)" }}>{error}</div> : null}
      {message ? <div style={{ ...styles.card, borderColor: "var(--success)", color: "var(--success)" }}>{message}</div> : null}
      {mode === "management" && managementView === "products" && bulkPriceMode ? (
        <div style={{ ...styles.card, borderColor: "var(--accent)", color: "var(--accent-strong)" }}>
          {bulkPriceMode === "custom"
            ? "Custom selecionado. Clique em Aplicar aos produtos da página para alterar os produtos carregados."
            : `Tabela selecionada: ${selectedBulkPriceTable?.name || "Tabela"}. Clique em Aplicar aos produtos da página para gravar esta tabela nos produtos carregados.`}
        </div>
      ) : null}

      {mode === "management" ? (
        <div style={styles.tabs}>
          <Button variant={managementView === "products" ? "primary" : "secondary"} onClick={() => setManagementView("products")}>
            Produtos
          </Button>
          <Button variant={managementView === "priceTables" ? "primary" : "secondary"} onClick={() => setManagementView("priceTables")}>
            Tabelas de preço
          </Button>
          <Button variant={managementView === "options" ? "primary" : "secondary"} onClick={() => setManagementView("options")}>
            Opções do catálogo
          </Button>
        </div>
      ) : null}

      {mode === "campaign" ? (
        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ ...styles.card, display: "grid", gridTemplateColumns: "1fr 1fr 140px 140px 130px 170px 110px auto", gap: 10, alignItems: "center" }}>
            <input style={styles.input} placeholder="Nome da campanha" value={campaignDraft.name} onChange={(e) => setCampaignDraft({ ...campaignDraft, name: e.target.value })} />
            <input style={styles.input} placeholder="Descrição interna" value={campaignDraft.description} onChange={(e) => setCampaignDraft({ ...campaignDraft, description: e.target.value })} />
            <input style={styles.input} type="date" value={campaignDraft.start_date} onChange={(e) => setCampaignDraft({ ...campaignDraft, start_date: e.target.value })} />
            <input style={styles.input} type="date" value={campaignDraft.end_date} onChange={(e) => setCampaignDraft({ ...campaignDraft, end_date: e.target.value })} />
            <input style={styles.input} type="number" placeholder="% desconto" value={campaignDraft.discount_percent} onChange={(e) => setCampaignDraft({ ...campaignDraft, discount_percent: e.target.value })} />
            <select style={styles.input} value={campaignDraft.price_table_id || ""} onChange={(e) => setCampaignDraft({ ...campaignDraft, price_table_id: e.target.value })}>
              <option value="">Tabela opcional</option>
              {priceTables.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontWeight: 900 }}><input type="checkbox" checked={campaignDraft.active} onChange={(e) => setCampaignDraft({ ...campaignDraft, active: e.target.checked })} /> Ativa</label>
            <Button variant="primary" onClick={saveCampaign}>{editingCampaign ? "Salvar" : "Nova campanha"}</Button>
          </div>

          <Table>
            <thead>
              <tr>
                <th>Campanha</th>
                <th>Período</th>
                <th data-numeric>Desconto</th>
                <th>Status</th>
                <th data-numeric>Produtos</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {!campaigns.length ? <tr><td colSpan={6}>Nenhuma campanha cadastrada.</td></tr> : null}
              {campaigns.map((item) => (
                <tr key={item.id}>
                  <td><div style={{ fontWeight: 950 }}>{item.name}</div><div style={styles.muted}>{item.description || ""}</div></td>
                  <td>{String(item.start_date || "").slice(0, 10)} até {String(item.end_date || "").slice(0, 10)}</td>
                  <td data-numeric>{formatPercent(item.discount_percent)}</td>
                  <td><StatusPill status={item.status || (item.active ? "Ativa" : "Inativa")} /></td>
                  <td data-numeric>{item.product_count || 0}</td>
                  <td><Button size="sm" onClick={() => editCampaign(item)}>Editar produtos</Button></td>
                </tr>
              ))}
            </tbody>
          </Table>

          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 10 }}>
              <div>
                <div style={{ fontWeight: 950 }}>Produtos da campanha</div>
                <div style={styles.muted}>Use os filtros acima para localizar produtos. Selecione os produtos e salve a campanha.</div>
              </div>
              <Button onClick={resetCampaignDraft}>Limpar</Button>
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {items.map((item) => (
                <label key={item.id} style={{ display: "grid", gridTemplateColumns: "24px 80px 1fr auto", gap: 10, alignItems: "center", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                  <input type="checkbox" checked={campaignProductIds.includes(Number(item.id))} onChange={() => toggleCampaignProduct(item.id)} />
                  <span style={{ ...styles.muted, fontWeight: 900 }}>{item.sku || "-"}</span>
                  <span>{item.catalog_description || item.name_tiny || "-"}</span>
                      <StatusPill status={item.catalog_active ? "Incluído" : "Fora"} />
                </label>
              ))}
              {!items.length ? <EmptyState title="Sem produtos" message="Nenhum produto carregado para selecionar." /> : null}
            </div>
          </Card>
        </div>
      ) : mode === "layout" ? (
        <div style={styles.layoutShell}>
          <div style={styles.layoutPanel}>
            <div style={styles.layoutTopbar}>
              <div>
                <div style={styles.layoutSectionTitle}>Cabeçalho da configuração</div>
                <div style={styles.layoutSectionMeta}>A prévia usa automaticamente os produtos marcados em Gestão. Aqui ficam apenas os ajustes gerais do encarte.</div>
                <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
                  <div style={{ fontSize: 22, fontWeight: 950 }}>{selectedLayout?.name || layoutDraft.name || "Nova configuração"}</div>
                  <div style={styles.layoutSectionMeta}>
                    {selectedLayout?.title || layoutDraft.title || "Sem título"}{selectedLayout?.subtitle || layoutDraft.subtitle ? ` · ${selectedLayout?.subtitle || layoutDraft.subtitle}` : ""}
                  </div>
                </div>
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                <label>
                  <div style={styles.muted}>Configuração atual</div>
                  <select
                    style={styles.input}
                    value={selectedLayoutId}
                    onChange={(e) => {
                      const next = String(e.target.value || "");
                      if (!next) {
                        createNewLayout();
                        return;
                      }
                      setSelectedLayoutId(next);
                    }}
                  >
                    <option value="">Selecione uma configuração</option>
                    {layouts.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </select>
                </label>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Button onClick={createNewLayout}>Nova configuração</Button>
                  <Button variant="primary" onClick={saveLayout} loading={layoutSaving}>
                    Salvar configuração
                  </Button>
                  <Button onClick={() => changeMode("preview")}>
                    Atualizar prévia
                  </Button>
                </div>
              </div>
              <div style={{ display: "grid", gap: 10 }}>
                <div style={styles.layoutStatCard}>
                  <div style={styles.layoutStatLabel}>Fluxo simples</div>
                  <div style={styles.layoutStatValue}>Gestão define o catálogo</div>
                </div>
                <div style={layoutDirty ? styles.layoutNotice : styles.layoutSuccess}>
                  {layoutPendingLabel}
                </div>
              </div>
            </div>
            {layoutSaveMessage ? (
              <div style={{ marginTop: 12, ...styles.layoutSuccess }}>{layoutSaveMessage}</div>
            ) : null}
          </div>

          <div style={styles.layoutPanel}>
            <div style={styles.layoutSectionHeader}>
              <div>
                <div style={styles.layoutSectionTitle}>Configurações</div>
                <div style={styles.layoutSectionMeta}>Defina o título, subtítulo, validade e as opções gerais do catálogo final.</div>
              </div>
              <div style={{ color: "var(--muted)", fontSize: 13 }}>
                {selectedLayout?.active ? "Configuração ativa" : "Rascunho"}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr 180px", gap: 10, alignItems: "start" }}>
              <label>
                <div style={styles.muted}>Nome interno da configuração</div>
                <input style={styles.input} value={layoutDraft.name} onChange={(e) => updateLayoutDraft({ name: e.target.value })} />
              </label>
              <label>
                <div style={styles.muted}>Título</div>
                <input style={styles.input} value={layoutDraft.title} onChange={(e) => updateLayoutDraft({ title: e.target.value })} />
              </label>
              <label>
                <div style={styles.muted}>Subtítulo</div>
                <input style={styles.input} value={layoutDraft.subtitle} onChange={(e) => updateLayoutDraft({ subtitle: e.target.value })} />
              </label>
              <label>
                <div style={styles.muted}>Validade</div>
                <input style={styles.input} type="date" value={layoutDraft.valid_until || ""} onChange={(e) => updateLayoutDraft({ valid_until: e.target.value })} />
              </label>
              <label style={{ gridColumn: "1 / -1" }}>
                <div style={styles.muted}>Observações</div>
                <textarea style={{ ...styles.input, minHeight: 82 }} value={layoutDraft.notes} onChange={(e) => updateLayoutDraft({ notes: e.target.value })} />
              </label>
              <div style={{ gridColumn: "1 / -1", display: "flex", flexWrap: "wrap", gap: 12 }}>
                {[
                  ["Usar campanhas vigentes", "use_active_campaigns"],
                  ["Mostrar SKU", "show_sku"],
                  ["Mostrar tags/benefícios", "show_tags"],
                  ["Mostrar produtos sem imagem", "show_without_image"],
                  ["Somente produtos incluídos no catálogo", "only_active_products"],
                  ["Mostrar Valor Cheio", "show_full_price"],
                  ["Mostrar Valor Faturado", "show_billed_price"],
                  ["Mostrar Valor à Vista", "show_cash_price"],
                  ["Mostrar estoque", "show_stock"],
                  ["Ativa", "active"],
                ].map(([label, key]) => (
                  <label key={key} style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 900 }}>
                    <input
                      type="checkbox"
                      checked={Boolean(layoutDraft[key])}
                      onChange={(e) => updateLayoutDraft({ [key]: e.target.checked })}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div style={styles.layoutPanel}>
            <div style={styles.layoutSectionHeader}>
              <div>
                <div style={styles.layoutSectionTitle}>Como a prévia funciona</div>
                <div style={styles.layoutSectionMeta}>Não existe mais seleção manual de produtos aqui. O catálogo final usa os itens incluídos na aba Gestão e o visual de encarte da aba Prévia.</div>
              </div>
            </div>
            <div style={{ display: "grid", gap: 10 }}>
              <div style={styles.card}>
                Marque <strong>Incluir no catálogo</strong> na aba Gestão para definir quais produtos entram no catálogo final.
              </div>
              <div style={styles.card}>
                Ajuste título, subtítulo, validade e opções gerais nesta tela. A prévia completa fica na aba Prévia do catálogo.
              </div>
            </div>
          </div>

          <div style={styles.layoutPanel}>
            <div style={styles.layoutSectionHeader}>
              <div>
                <div style={styles.layoutSectionTitle}>Resumo da configuração</div>
                <div style={styles.layoutSectionMeta}>A prévia principal do catálogo fica na aba Prévia do catálogo. Esta área agora só confirma a lógica geral do fluxo.</div>
              </div>
            </div>
            <div style={{ display: "grid", gap: 10 }}>
              <div style={styles.card}>
                A seleção de produtos não é mais manual aqui. O produto entra no catálogo quando estiver com <strong>Incluir no catálogo</strong> marcado na aba Gestão.
              </div>
              <div style={styles.card}>
                O futuro PDF será gerado a partir da aba Prévia, mantendo o mesmo visual de encarte.
              </div>
            </div>
          </div>
        </div>
      ) : mode === "preview" ? (
        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ ...styles.card, display: "flex", justifyContent: "space-between", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <div style={{ ...styles.muted, textTransform: "uppercase", fontWeight: 900 }}>Prévia interna</div>
              <div style={{ fontSize: 24, fontWeight: 950 }}>Catálogo {selectedCompany}</div>
              <div style={styles.muted}>Somente produtos incluídos no catálogo entram nesta visualização. Produtos em destaque aparecem primeiro.</div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ ...styles.badge, borderColor: "var(--accent)", color: "var(--accent-strong)" }}>{total} produtos incluídos</div>
              <Button variant="primary" onClick={handleExportCatalogPdf} loading={pdfExporting} disabled={loading || !items.length}>
                Exportar PDF
              </Button>
            </div>
          </div>

          <div ref={previewExportRef} style={{ display: "grid", gap: 14, background: "#fff" }}>
            <div style={styles.previewIntro}>
                <div style={styles.previewBrand}>
                  <div style={styles.previewLogoBox}>
                  <img src={PARTON_LOGO_SRC} alt="Parton" style={styles.previewLogo} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                </div>
                <div>
                  <div style={styles.previewIntroTitle}>{layoutDraft.title || `Catálogo ${selectedCompany}`}</div>
                  {layoutDraft.subtitle ? <div style={styles.previewIntroMeta}>{layoutDraft.subtitle}</div> : null}
                  <div style={styles.previewIntroMeta}>
                    {selectedCompany}
                    {layoutDraft.valid_until ? ` · Válido até ${String(layoutDraft.valid_until).slice(8, 10)}/${String(layoutDraft.valid_until).slice(5, 7)}/${String(layoutDraft.valid_until).slice(0, 4)}` : ""}
                  </div>
                </div>
              </div>
              {layoutDraft.notes ? <div style={{ color: "#64748b", fontSize: 13, lineHeight: 1.35, maxWidth: 360, fontWeight: 700 }}>{layoutDraft.notes}</div> : null}
            </div>

            {loading ? <div style={{ ...styles.card, display: "flex", alignItems: "center", gap: 8 }}><Spinner size={16} /> Carregando prévia...</div> : null}
            {!loading && !items.length ? (
              <div style={styles.card}><EmptyState title="Catálogo vazio" message="Nenhum produto incluído no catálogo. Marque produtos como Incluir no catálogo na aba Gestão." /></div>
            ) : null}

            <div style={styles.previewGrid}>
              <div
                ref={catalogPdfRef}
                aria-hidden="true"
                style={{
                  position: "absolute",
                  left: "-10000px",
                  top: 0,
                  width: "794px",
                  background: "#f3f6fb",
                  pointerEvents: "none",
                }}
              >
                {(() => {
                  const pdfCompanyLabel =
                    layoutDraft.company_key === "parton"
                      ? "Suprimentos"
                      : layoutDraft.company_key === "park"
                        ? "Informática"
                        : layoutDraft.company_key || "Empresa atual";
                  const pdfTitle = String(layoutDraft.title || layoutDraft.name || "Catálogo").trim();
                  const pdfSubtitle = String(layoutDraft.subtitle || "").trim();
                  const pdfNotes = String(layoutDraft.notes || "").trim();
                  const pdfValidity = formatCatalogDateLabel(layoutDraft.valid_until || layoutDraft.validUntil || layoutDraft.validity || "");
                  return (
                    <>
                      <section data-pdf-page="true" style={styles.pdfCoverPage}>
                        <div style={styles.pdfCoverGlow} />
                        <div style={styles.pdfCoverMark} />
                        <div style={styles.pdfCoverTop}>
                          <div style={styles.pdfCoverLogoBox}>
                            <img src={PARTON_LOGO_SRC} alt="Parton" style={styles.pdfCoverLogo} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                          </div>
                          <div style={styles.pdfCoverKicker}>Catálogo comercial</div>
                        </div>

                        <div style={styles.pdfCoverHero}>
                          <div style={styles.pdfCoverCompany}>{pdfCompanyLabel}</div>
                          <div style={styles.pdfCoverTitle}>{pdfTitle}</div>
                          {pdfSubtitle ? <div style={styles.pdfCoverSubtitle}>{pdfSubtitle}</div> : null}
                        </div>

                        <div style={styles.pdfCoverMeta}>
                          <div style={styles.pdfCoverNoteBox}>
                            <div style={styles.pdfCoverNoteLabel}>Observações</div>
                            <div style={styles.pdfCoverNoteText}>
                              {pdfNotes || "Seleção comercial organizada para consulta rápida, com preços e condições conforme opções vigentes do catálogo."}
                            </div>
                          </div>
                          {pdfValidity ? (
                            <div style={styles.pdfCoverDateBox}>
                              <div style={styles.pdfCoverDateLabel}>Validade</div>
                              <div style={styles.pdfCoverDateValue}>{pdfValidity}</div>
                            </div>
                          ) : null}
                        </div>

                      </section>

                      {pdfPages.map((page, pageIndex) => {
                        const pageItems = Array.isArray(page)
                          ? page
                          : Array.isArray(page?.cards)
                            ? page.cards
                            : Array.isArray(page?.items)
                              ? page.items
                              : Array.isArray(page?.pageItems)
                                ? page.pageItems
                                : [];
                        const displayPage = pageIndex + 2;

                        return (
                          <section key={`pdf-page-${pageIndex}`} data-pdf-page="true" style={styles.pdfPage}>
                            <img src={PARTON_LOGO_SRC} alt="" style={styles.pdfWatermark} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                            <header style={styles.pdfHeader}>
                              <div style={styles.pdfHeaderAccent} />
                              <div style={styles.pdfHeaderTop}>
                                <div style={styles.pdfHeaderBrand}>
                                  <div style={styles.pdfHeaderLogoWrap}>
                                    <img src={PARTON_LOGO_SRC} alt="Parton" style={styles.pdfHeaderLogo} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                                  </div>
                                  <div>
                                    <div style={styles.pdfHeaderTitle}>{pdfTitle}</div>
                                    {pdfSubtitle ? <div style={styles.pdfHeaderSubtitle}>{pdfSubtitle}</div> : null}
                                  </div>
                                </div>
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
                                  <span style={styles.pdfHeaderChip}>{pdfCompanyLabel}</span>
                                  {pdfValidity ? <span style={styles.pdfHeaderChip}>Validade: {pdfValidity}</span> : null}
                                  <span style={styles.pdfHeaderChip}>Página {displayPage}</span>
                                </div>
                              </div>
                              {pdfNotes ? (
                                <div style={{ fontSize: 11.5, color: "#5b6b84", lineHeight: 1.35, maxWidth: 590, marginTop: 10, paddingLeft: 63 }}>
                                  {pdfNotes}
                                </div>
                              ) : null}
                            </header>

                            <div style={styles.pdfGrid}>
                              {pageItems.map((item) => {
                                const description = item.description || item.catalog_title || item.catalog_description || item.name_tiny || item.sku || "Produto sem descrição";
                                const useCampaignPrices = Boolean(layoutDraft.use_active_campaigns && (item.campaign_active || item.has_campaign || item.campaign_id || item.campaign));
                                const prices = [
                                  layoutDraft.show_full_price
                                    ? useCampaignPrices
                                      ? (item.campaign_full_price_value ?? item.final_full_price_value ?? item.full_price_value ?? item.primaryPrice)
                                      : (item.final_full_price_value ?? item.full_price_value ?? item.primaryPrice)
                                    : null,
                                  layoutDraft.show_billed_price
                                    ? useCampaignPrices
                                      ? (item.campaign_billed_price_value ?? item.final_billed_price_value ?? item.billed_price_value)
                                      : (item.final_billed_price_value ?? item.billed_price_value)
                                    : null,
                                  layoutDraft.show_cash_price
                                    ? useCampaignPrices
                                      ? (item.campaign_cash_price_value ?? item.final_cash_price_value ?? item.cash_price_value)
                                      : (item.final_cash_price_value ?? item.cash_price_value)
                                    : null,
                                ].filter((value) => value !== null && value !== undefined && value !== "");
                                const rawPrimaryPrice = item.primaryPrice ?? prices[0];
                                const rawSecondaryPrices = Array.isArray(item.secondaryPrices) ? item.secondaryPrices : prices.slice(1);
                                const primaryPrice = rawPrimaryPrice !== null && rawPrimaryPrice !== undefined && rawPrimaryPrice !== "" ? formatBRL(rawPrimaryPrice) : "";
                                const secondaryPrices = rawSecondaryPrices.map(formatCatalogVisualPrice).filter(Boolean);
                                const tagLine = String(item.tagLine || item.catalog_tags || item.catalog_benefits || "")
                                  .split(/[,;\n·]/)
                                  .map((value) => value.trim())
                                  .filter(Boolean)
                                  .slice(0, 3)
                                  .join(" · ");
                                const imageSrc = item.image || (typeof imageFor === "function" ? imageFor(item) : (item.catalog_image_url || item.catalog_image_path || ""));
                                const showSku = item.showSku ?? item.show_sku ?? layoutDraft.show_sku;
                                const showTags = item.showTags ?? item.show_tags ?? layoutDraft.show_tags;
                                const showStock = item.showStock ?? item.show_stock ?? layoutDraft.show_stock;
                                const stockText = item.stockLabel || item.stock_label || item.stock_text || item.stock || "";
                                const badges = [];
                                if (item.campaign || (item.campaign_active && layoutDraft.use_active_campaigns)) {
                                  badges.push("Campanha");
                                }
                                if (item.featured || item.catalog_featured) {
                                  badges.push("Destaque");
                                }

                                return (
                                  <article key={item.id} style={styles.pdfCard}>
                                    <div style={styles.pdfImageWrap}>
                                      {imageSrc ? (
                                        <img src={imageSrc} alt={description} style={styles.pdfImage} />
                                      ) : (
                                        <div style={styles.pdfPlaceholder}>Sem imagem</div>
                                      )}
                                      {badges.length ? (
                                        <div style={styles.pdfBadgeGroup}>
                                          {badges.slice(0, 2).map((badge) => (
                                            <span key={badge} style={styles.pdfBadge}>{badge}</span>
                                          ))}
                                        </div>
                                      ) : null}
                                    </div>

                                    <div style={styles.pdfBody}>
                                      {showSku && item.sku ? <div style={styles.pdfSku}>{item.sku}</div> : null}
                                      <div style={styles.pdfTitle}>{description}</div>
                                      {showTags && tagLine ? <div style={styles.pdfTagLine}>{tagLine}</div> : null}
                                      {showStock && stockText ? <div style={styles.pdfTagLine}>Estoque: {stockText}</div> : null}
                                      <div style={styles.pdfPriceBlock}>
                                        <div style={styles.pdfPriceMain}>{primaryPrice || "Sob consulta"}</div>
                                        {secondaryPrices.length ? (
                                          <div style={styles.pdfPriceSecondary}>{secondaryPrices.join("°")}</div>
                                        ) : null}
                                      </div>
                                    </div>
                                  </article>
                                );
                              })}
                            </div>

                            <div style={styles.pdfFooter}>
                              <span style={styles.pdfFooterBrand}>Parton</span>
                              <span>{pdfCompanyLabel}{pdfValidity ? ` • Validade: ${pdfValidity}` : ""}</span>
                              <span>Página {displayPage}</span>
                            </div>
                          </section>
                        );
                      })}
                    </>
                  );
                })()}
              </div>

             {items.map((item) => {
              const description = item.catalog_title || item.catalog_description || item.name_tiny || item.sku || "Produto sem descrição";
              const useCampaignPrices = Boolean(layoutDraft.use_active_campaigns && item.campaign_active);
              const priceValues = [
                layoutDraft.show_full_price ? (useCampaignPrices ? (item.campaign_full_price_value ?? item.final_full_price_value ?? item.full_price_value) : (item.final_full_price_value ?? item.full_price_value)) : null,
                layoutDraft.show_billed_price ? (useCampaignPrices ? (item.campaign_billed_price_value ?? item.final_billed_price_value ?? item.billed_price_value) : (item.final_billed_price_value ?? item.billed_price_value)) : null,
                layoutDraft.show_cash_price ? (useCampaignPrices ? (item.campaign_cash_price_value ?? item.final_cash_price_value ?? item.cash_price_value) : (item.final_cash_price_value ?? item.cash_price_value)) : null,
              ].filter((value) => value !== null && value !== undefined && value !== "");
              const primaryPrice = priceValues[0];
              const secondaryPrices = priceValues.slice(1);
              const tagLine = String(item.catalog_tags || item.catalog_benefits || "")
                .split(/[,;\n]/)
                .map((value) => value.trim())
                .filter(Boolean)
                .slice(0, 3)
                .join(" · ");
              return (
                <article key={item.id} style={styles.previewCard}>
                  <div style={styles.previewImageWrap}>
                    <div style={styles.previewBadgeGroup}>
                      {item.catalog_featured ? (
                        <span style={{ ...styles.badge, background: "#1d4ed8", color: "#fff", borderColor: "#1d4ed8", padding: "3px 7px", fontSize: 10 }}>Destaque</span>
                      ) : null}
                      {useCampaignPrices ? (
                        <span style={{ ...styles.badge, background: "#16a34a", color: "#fff", borderColor: "#16a34a", padding: "3px 7px", fontSize: 10 }}>Campanha</span>
                      ) : null}
                    </div>
                    <CatalogImage
                      item={item}
                      alt={description}
                      style={styles.previewImage}
                      placeholderStyle={{
                        width: 92,
                        height: 92,
                        display: "grid",
                        placeItems: "center",
                        color: "var(--muted)",
                        fontWeight: 800,
                        fontSize: 11,
                        textAlign: "center",
                        background: "rgba(148,163,184,.08)",
                        border: "1px dashed rgba(148,163,184,.45)",
                        borderRadius: 999,
                        padding: 10,
                      }}
                    />
                  </div>
                  <div style={styles.previewBody}>
                    {layoutDraft.show_sku ? <div style={styles.previewSku}>{item.sku || "-"}</div> : null}
                    <div
                      style={styles.previewTitle}
                    >
                      {description}
                    </div>
                    {layoutDraft.show_tags && tagLine ? <div style={styles.previewTagLine}>{tagLine}</div> : null}
                    {layoutDraft.show_stock ? <div style={{ color: "var(--muted)", fontSize: 12, fontWeight: 700 }}>Estoque: {formatStock(item.stock_available)}</div> : null}
                  </div>
                  <div style={styles.previewPriceBlock}>
                    <div style={{ ...styles.previewPriceMain, color: useCampaignPrices ? "#166534" : "#111827" }}>
                      {primaryPrice !== null && primaryPrice !== undefined && primaryPrice !== "" ? formatBRL(primaryPrice) : "Sob consulta"}
                    </div>
                    {secondaryPrices.length ? (
                      <div style={styles.previewPriceSecondary}>
                        {secondaryPrices.map(formatCatalogVisualPrice).filter(Boolean).join("°")}
                      </div>
                    ) : null}
                  </div>
                </article>
              );
            })}
            </div>
          </div>
        </div>
      ) : managementView === "options" ? (
        <div style={{ display: "grid", gap: 14 }}>
          <Card>
            <div style={{ fontWeight: 950, fontSize: 18 }}>Opções do catálogo</div>
            <div style={styles.muted}>Essas opções alimentam a Prévia do catálogo e o futuro PDF. A seleção de produtos continua na aba Gestão → Produtos.</div>
          </Card>
          <div style={styles.card}>
            <label style={{ display: "grid", gap: 6, marginBottom: 12 }}>
              <div style={styles.muted}>Nome da configuração</div>
              <input
                style={styles.input}
                value={layoutDraft.name}
                onChange={(e) => updateLayoutDraft({ name: e.target.value })}
                placeholder="Configuração Suprimentos"
              />
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr 180px", gap: 10, alignItems: "start" }}>
              <label>
                <div style={styles.muted}>Configuração ativa</div>
                <select
                  style={styles.input}
                  value={selectedLayoutId}
                  onChange={(e) => {
                    const next = String(e.target.value || "");
                    if (!next) {
                      createNewLayout();
                      return;
                    }
                    setSelectedLayoutId(next);
                  }}
                >
                  <option value="">Selecione uma configuração</option>
                  {layouts.map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </select>
              </label>
              <label>
                <div style={styles.muted}>Título do catálogo</div>
                <input style={styles.input} value={layoutDraft.title} onChange={(e) => updateLayoutDraft({ title: e.target.value })} />
              </label>
              <label>
                <div style={styles.muted}>Subtítulo</div>
                <input style={styles.input} value={layoutDraft.subtitle} onChange={(e) => updateLayoutDraft({ subtitle: e.target.value })} />
              </label>
              <label>
                <div style={styles.muted}>Validade</div>
                <input style={styles.input} type="date" value={layoutDraft.valid_until || ""} onChange={(e) => updateLayoutDraft({ valid_until: e.target.value })} />
              </label>
              <label style={{ gridColumn: "1 / -1" }}>
                <div style={styles.muted}>Observações</div>
                <textarea style={{ ...styles.input, minHeight: 82 }} value={layoutDraft.notes} onChange={(e) => updateLayoutDraft({ notes: e.target.value })} />
              </label>
              <div style={{ gridColumn: "1 / -1", display: "flex", flexWrap: "wrap", gap: 12 }}>
                {[
                  ["Usar campanhas vigentes", "use_active_campaigns"],
                  ["Mostrar SKU", "show_sku"],
                  ["Mostrar tags/benefícios", "show_tags"],
                  ["Mostrar produtos sem imagem", "show_without_image"],
                  ["Somente produtos incluídos no catálogo", "only_active_products"],
                  ["Mostrar Valor Cheio", "show_full_price"],
                  ["Mostrar Valor Faturado", "show_billed_price"],
                  ["Mostrar Valor à Vista", "show_cash_price"],
                  ["Mostrar estoque", "show_stock"],
                  ["Ativa", "active"],
                ].map(([label, key]) => (
                  <label key={key} style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 900 }}>
                    <input
                      type="checkbox"
                      checked={Boolean(layoutDraft[key])}
                      onChange={(e) => updateLayoutDraft({ [key]: e.target.checked })}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14 }}>
              <Button onClick={createNewLayout}>Nova configuração</Button>
              <Button variant="primary" onClick={saveLayout} loading={layoutSaving}>
                Salvar configuração
              </Button>
              <Button onClick={() => changeMode("preview")}>Atualizar prévia</Button>
            </div>
          </div>
          {layoutSaveMessage ? <div style={{ ...styles.card, borderColor: "var(--success)", color: "var(--success)" }}>{layoutSaveMessage}</div> : null}
        </div>
      ) : managementView === "priceTables" ? (
        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ ...styles.card, display: "grid", gridTemplateColumns: "1.2fr repeat(4, minmax(130px, .7fr)) repeat(2, minmax(110px, .5fr)) auto", gap: 10, alignItems: "center" }}>
            <input style={styles.input} placeholder="Nome da tabela" value={priceTableDraft.name} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, name: e.target.value })} />
            <select style={styles.input} value={priceTableDraft.mode} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, mode: e.target.value })}>
              <option value="percent">Percentual</option>
              <option value="custom">Custom</option>
            </select>
            <select style={styles.input} value={priceTableDraft.base_field} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, base_field: e.target.value })}>
              <option value="price_tiny">Base: Preço Tiny</option>
              <option value="average_cost">Base: Custo médio</option>
            </select>
            <input style={styles.input} type="number" placeholder="% Cheio" value={priceTableDraft.full_price_percent} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, full_price_percent: e.target.value })} />
            <input style={styles.input} type="number" placeholder="% Faturado" value={priceTableDraft.billed_price_percent} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, billed_price_percent: e.target.value })} />
            <input style={styles.input} type="number" placeholder="% à Vista" value={priceTableDraft.cash_price_percent} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, cash_price_percent: e.target.value })} />
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontWeight: 900 }}><input type="checkbox" checked={priceTableDraft.active} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, active: e.target.checked })} /> Ativa</label>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontWeight: 900 }}><input type="checkbox" checked={priceTableDraft.is_default} onChange={(e) => setPriceTableDraft({ ...priceTableDraft, is_default: e.target.checked })} /> Padrão</label>
            <Button variant="primary" onClick={savePriceTable}>{editingPriceTable ? "Salvar" : "Criar"}</Button>
          </div>
          <div style={styles.muted}>Base de cálculo atual: Preço Tiny. O campo Custo médio fica preparado para quando houver fonte local disponível.</div>
          <Table>
            <thead>
              <tr>
                <th>Nome</th>
                <th>Modo</th>
                <th>Base</th>
                <th data-numeric>% Cheio</th>
                <th data-numeric>% Faturado</th>
                <th data-numeric>% à Vista</th>
                <th>Status</th>
                <th>Padrão</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {!priceTables.length ? <tr><td colSpan={9}>Nenhuma tabela de preço cadastrada.</td></tr> : null}
              {priceTables.map((item) => (
                <tr key={item.id}>
                  <td>{item.name}</td>
                  <td>{item.mode === "custom" ? "Custom" : "Percentual"}</td>
                  <td>{item.base_field === "average_cost" ? "Custo médio" : "Preço Tiny"}</td>
                  <td data-numeric>{formatPercent(item.full_price_percent)}</td>
                  <td data-numeric>{formatPercent(item.billed_price_percent)}</td>
                  <td data-numeric>{formatPercent(item.cash_price_percent)}</td>
                  <td><StatusPill status={item.active ? "Ativa" : "Inativa"} /></td>
                  <td>{item.is_default ? <StatusPill status="Padrão" /> : "-"}</td>
                  <td><Button size="sm" onClick={() => editPriceTable(item)}>Editar</Button></td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : (
      <div style={styles.tableWrap}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1580 }}>
          <thead>
            <tr>
                  {["Imagem", "SKU", "Descrição", "Estoque", "Custo Médio", "Preço Tiny", "Tabela", "% Valor Cheio", "R$ Valor Cheio", "% Valor Faturado", "R$ Valor Faturado", "% Valor à Vista", "R$ Valor à Vista", "Ordem", "Catálogo", "Destaque", "Ações"].map((title) => (
                <th key={title} style={styles.th}>{title}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={17} style={{ ...styles.td, display: "flex", alignItems: "center", gap: 8 }}><Spinner size={16} /> Carregando...</td></tr>
            ) : null}
            {!loading && !items.length ? (
              <tr><td colSpan={17} style={styles.td}><EmptyState title="Sem produtos" message="Nenhum produto encontrado." /></td></tr>
            ) : null}
            {items.map((item) => {
              const dirty = dirtyRows[item.id] || {};
              const fullPercent = rowFinalValue(item, "full_price_percent", "final_full_price_percent");
              const billedPercent = rowFinalValue(item, "billed_price_percent", "final_billed_price_percent");
              const cashPercent = rowFinalValue(item, "cash_price_percent", "final_cash_price_percent");
              const fullValue = dirty.full_price_value ?? item.final_full_price_value ?? item.full_price_value;
              const billedValue = dirty.billed_price_value ?? item.final_billed_price_value ?? item.billed_price_value;
              const cashValue = dirty.cash_price_value ?? item.final_cash_price_value ?? item.cash_price_value;
              const catalogOrder = rowValue(item, "catalog_order");
              const active = rowValue(item, "catalog_active");
              const featuredRow = rowValue(item, "catalog_featured");
              return (
              <tr key={item.id} style={dirtyRows[item.id] ? { background: "rgba(29,78,216,.05)" } : undefined}>
                <td style={styles.td}>
                  <CatalogImage
                    item={item}
                    alt=""
                    style={{
                      width: 64,
                      height: 64,
                      objectFit: "contain",
                      background: "#fff",
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      padding: 4,
                    }}
                    placeholderStyle={{
                      width: 64,
                      height: 64,
                      display: "grid",
                      placeItems: "center",
                      background: "rgba(148,163,184,.10)",
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      color: "var(--muted)",
                      fontSize: 12,
                      fontWeight: 900,
                    }}
                  />
                </td>
                <td style={styles.td}>{item.sku || "-"}</td>
                <td style={styles.td}>
                  <div style={{ fontWeight: 900 }}>{item.catalog_description || item.name_tiny || "-"}</div>
                  <div style={styles.muted}>{item.category || item.situation || ""}</div>
                </td>
                <td style={styles.td}>{formatStock(item.stock_available)}</td>
                <td style={styles.td}>{item.average_cost ? formatBRL(item.average_cost) : "-"}</td>
                <td style={styles.td}>{formatBRL(item.price_tiny)}</td>
                <td style={styles.td}>
                  <span style={styles.badge}>{item.price_mode === "table" ? `Tabela: ${item.price_table_name || "Tabela"}` : "Custom"}</span>
                </td>
                <td style={styles.td}><input style={styles.smallInput} type="number" value={fullPercent ?? ""} onChange={(e) => updatePercent(item, "full_price_percent", "full_price_value", e.target.value)} /></td>
                <td style={styles.td}>{fullValue ? formatBRL(fullValue) : "-"}</td>
                <td style={styles.td}><input style={styles.smallInput} type="number" value={billedPercent ?? ""} onChange={(e) => updatePercent(item, "billed_price_percent", "billed_price_value", e.target.value)} /></td>
                <td style={styles.td}>{billedValue ? formatBRL(billedValue) : "-"}</td>
                <td style={styles.td}><input style={styles.smallInput} type="number" value={cashPercent ?? ""} onChange={(e) => updatePercent(item, "cash_price_percent", "cash_price_value", e.target.value)} /></td>
                <td style={styles.td}>{cashValue ? formatBRL(cashValue) : "-"}</td>
                <td style={styles.td}><input style={{ ...styles.smallInput, width: 70 }} type="number" value={catalogOrder ?? ""} onChange={(e) => updateRow(item, { catalog_order: e.target.value === "" ? "" : e.target.value })} /></td>
                <td style={styles.td}><input type="checkbox" checked={Boolean(active)} onChange={(e) => updateRow(item, { catalog_active: e.target.checked })} /></td>
                <td style={styles.td}><input type="checkbox" checked={Boolean(featuredRow)} onChange={(e) => updateRow(item, { catalog_featured: e.target.checked })} /></td>
                <td style={styles.td}><Button size="sm" onClick={() => openEdit(item)}>Editar catálogo</Button></td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button disabled={offset <= 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</Button>
        <span style={{ alignSelf: "center", color: "var(--muted)" }}>Página {page}</span>
        <Button disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Próxima</Button>
      </div>

      {editing ? (
        <div style={styles.modalOverlay}>
          <div style={styles.modal}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 22, fontWeight: 950 }}>Editar catálogo</div>
                <div style={styles.muted}>{editing.sku || "-"} · {editing.name_tiny || "-"}</div>
              </div>
              <Button onClick={() => setEditing(null)}>Cancelar</Button>
            </div>

            <div style={{ ...styles.card, marginBottom: 12 }}>
              <div><b>Empresa:</b> {COMPANIES.find((item) => item.key === editing.company_key)?.label || editing.company_key}</div>
              <div><b>Custo Médio:</b> {editing.average_cost ? formatBRL(editing.average_cost) : "-"} · <b>Preço Tiny:</b> {formatBRL(editing.price_tiny)} · <b>Situação:</b> {editing.situation || "-"} · <b>Categoria:</b> {editing.category || "-"}</div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <label style={{ gridColumn: "1 / -1" }}><div style={styles.muted}>Descrição comercial</div><textarea style={{ ...styles.input, minHeight: 90 }} value={draft.catalog_description} onChange={(e) => setDraft({ ...draft, catalog_description: e.target.value })} /></label>
              <label>
                <div style={styles.muted}>Imagem local (arquivo em storage/catalog-images)</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 8 }}>
                  <input style={styles.input} value={draft.catalog_image_filename} onChange={(e) => setDraft({ ...draft, catalog_image_filename: e.target.value, catalog_image_path: e.target.value })} />
                  <Button
                    type="button"
                    title="Abrir galeria"
                    disabled={imageUploading}
                    onClick={openGallery}
                  >
                    Galeria
                  </Button>
                  <Button
                    type="button"
                    title="Selecionar imagem"
                    disabled={imageUploading}
                    onClick={() => document.getElementById("catalog-image-upload-input")?.click()}
                  >
                    ...
                  </Button>
                </div>
                <input
                  id="catalog-image-upload-input"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  style={{ display: "none" }}
                  onChange={(e) => uploadCatalogImage(e.target.files?.[0])}
                />
                {(() => {
                  const previewSrc = catalogImageUrl(draft.catalog_image_path || draft.catalog_image_filename || draft.catalog_image_url);
                  if (!previewSrc) return null;
                  return (
                    <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
                      <div style={styles.muted}>Prévia</div>
                      <img
                        src={previewSrc}
                        alt="Prévia da imagem do catálogo"
                        style={{
                          width: 180,
                          maxWidth: "100%",
                          height: 180,
                          objectFit: "contain",
                          background: "#fff",
                          border: "1px solid var(--border)",
                          borderRadius: 10,
                          padding: 8,
                        }}
                      />
                    </div>
                  );
                })()}
              </label>
              <label><div style={styles.muted}>URL da imagem catálogo</div><input style={styles.input} value={draft.catalog_image_url} onChange={(e) => setDraft({ ...draft, catalog_image_url: e.target.value })} /></label>
              <div style={{ ...styles.card, gridColumn: "1 / -1", display: "grid", gap: 12 }}>
                <div style={{ fontWeight: 950 }}>Precificação</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <label><div style={styles.muted}>Modo de preço</div><select style={styles.input} value={draft.price_mode} onChange={(e) => setDraft({ ...draft, price_mode: e.target.value })}><option value="custom">Custom</option><option value="table">Tabela de preço</option></select></label>
                  <label><div style={styles.muted}>Tabela de preço</div><select style={styles.input} value={draft.price_table_id || ""} disabled={draft.price_mode !== "table"} onChange={(e) => setDraft({ ...draft, price_table_id: e.target.value })}><option value="">Selecione</option>{priceTables.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                </div>
                {draft.price_mode === "table" ? (
                  <div style={styles.muted}>Ao usar tabela, os valores finais são calculados pela regra percentual. Os valores Custom abaixo ficam preservados para uso futuro.</div>
                ) : null}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                  {commercialPrices(editing || {}).map((price) => (
                    <div key={price.key} style={styles.card}>
                      <div style={styles.muted}>{price.label} final</div>
                      <div style={{ fontWeight: 950 }}>{commercialValue(price.value)}</div>
                      <div style={styles.muted}>{formatPercent(price.percent)}</div>
                    </div>
                  ))}
                </div>
              </div>
              <label><div style={styles.muted}>% Valor Cheio Custom</div><input style={styles.input} type="number" disabled={draft.price_mode === "table"} value={draft.full_price_percent} onChange={(e) => setDraft({ ...draft, full_price_percent: e.target.value })} /></label>
              <label><div style={styles.muted}>R$ Valor Cheio Custom</div><input style={styles.input} type="number" disabled={draft.price_mode === "table"} value={draft.full_price_value} onChange={(e) => setDraft({ ...draft, full_price_value: e.target.value })} /></label>
              <label><div style={styles.muted}>% Valor Faturado Custom</div><input style={styles.input} type="number" disabled={draft.price_mode === "table"} value={draft.billed_price_percent} onChange={(e) => setDraft({ ...draft, billed_price_percent: e.target.value })} /></label>
              <label><div style={styles.muted}>R$ Valor Faturado Custom</div><input style={styles.input} type="number" disabled={draft.price_mode === "table"} value={draft.billed_price_value} onChange={(e) => setDraft({ ...draft, billed_price_value: e.target.value })} /></label>
              <label><div style={styles.muted}>% Valor à Vista Custom</div><input style={styles.input} type="number" disabled={draft.price_mode === "table"} value={draft.cash_price_percent} onChange={(e) => setDraft({ ...draft, cash_price_percent: e.target.value })} /></label>
              <label><div style={styles.muted}>R$ Valor à Vista Custom</div><input style={styles.input} type="number" disabled={draft.price_mode === "table"} value={draft.cash_price_value} onChange={(e) => setDraft({ ...draft, cash_price_value: e.target.value })} /></label>
              <label><div style={styles.muted}>Benefícios curtos</div><textarea style={{ ...styles.input, minHeight: 70 }} value={draft.catalog_benefits} onChange={(e) => setDraft({ ...draft, catalog_benefits: e.target.value })} /></label>
              <label><div style={styles.muted}>Tags</div><textarea style={{ ...styles.input, minHeight: 70 }} value={draft.catalog_tags} onChange={(e) => setDraft({ ...draft, catalog_tags: e.target.value })} /></label>
              <label><div style={styles.muted}>Título comercial opcional</div><input style={styles.input} value={draft.catalog_title} onChange={(e) => setDraft({ ...draft, catalog_title: e.target.value })} /></label>
              <label><div style={styles.muted}>Preço catálogo antigo</div><input style={styles.input} type="number" value={draft.catalog_price} onChange={(e) => setDraft({ ...draft, catalog_price: e.target.value })} /></label>
              <label><div style={styles.muted}>Ordem</div><input style={styles.input} type="number" value={draft.catalog_order} onChange={(e) => setDraft({ ...draft, catalog_order: e.target.value })} /></label>
              <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <label><input type="checkbox" checked={draft.catalog_active} onChange={(e) => setDraft({ ...draft, catalog_active: e.target.checked })} /> Incluir no catálogo</label>
                <label><input type="checkbox" checked={draft.catalog_featured} onChange={(e) => setDraft({ ...draft, catalog_featured: e.target.checked })} /> Destaque</label>
              </div>
              <label style={{ gridColumn: "1 / -1" }}><div style={styles.muted}>Observações internas</div><textarea style={{ ...styles.input, minHeight: 80 }} value={draft.internal_notes} onChange={(e) => setDraft({ ...draft, internal_notes: e.target.value })} /></label>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
              <Button onClick={() => { setGalleryOpen(false); setEditing(null); }}>Cancelar</Button>
              <Button variant="primary" onClick={saveEdit}>Salvar</Button>
            </div>

            {galleryOpen ? (
              <div style={styles.modalOverlay}>
                <div style={styles.galleryModal}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 14 }}>
                    <div>
                      <div style={{ fontSize: 22, fontWeight: 950 }}>Galeria de imagens</div>
                      <div style={styles.muted}>Selecione uma imagem existente de storage/catalog-images.</div>
                    </div>
                    <Button type="button" onClick={() => setGalleryOpen(false)}>Fechar</Button>
                  </div>

                  <div style={styles.galleryToolbar}>
                    <input
                      style={styles.input}
                      placeholder="Buscar por nome do arquivo"
                      value={gallerySearch}
                      onChange={(e) => setGallerySearch(e.target.value)}
                    />
                    <Button type="button" onClick={openGallery} loading={galleryLoading}>
                      Atualizar
                    </Button>
                  </div>

                  {galleryError ? <div style={{ ...styles.card, marginTop: 12, color: "var(--danger)" }}>{galleryError}</div> : null}
                  {galleryLoading ? <div style={{ ...styles.card, marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}><Spinner size={16} /> Carregando imagens...</div> : null}
                  {!galleryLoading && !filteredGalleryImages.length ? (
                    <div style={{ ...styles.card, marginTop: 12 }}><EmptyState title="Sem imagens" message="Nenhuma imagem encontrada." /></div>
                  ) : null}

                  {!galleryLoading && filteredGalleryImages.length ? (
                    <div style={{ ...styles.galleryGrid, marginTop: 12 }}>
                      {filteredGalleryImages.map((item) => (
                        <button
                          key={item.filename}
                          type="button"
                          style={styles.galleryItem}
                          onClick={() => selectGalleryImage(item)}
                          title={`Selecionar ${item.filename}`}
                        >
                          <img src={item.url} alt={item.filename} style={styles.galleryThumb} />
                          <div style={{ fontWeight: 900, wordBreak: "break-word" }}>{item.filename}</div>
                          <div style={styles.muted}>{item.size ? `${Math.max(1, Math.round(item.size / 1024))} KB` : "-"}</div>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
