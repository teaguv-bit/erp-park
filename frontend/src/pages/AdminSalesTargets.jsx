import React, { useEffect, useRef, useState } from "react";
import api from "../api";
import { Button, EmptyState, Field, Table, useToast } from "../ui";

const COMPANY_LABELS = { parton: "Suprimentos / Parton", park: "Informática / Park" };
const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

function parseBRL(raw) {
  if (raw == null || raw === "") return null;
  const clean = String(raw).replace(/[^\d.,]/g, "").trim();
  if (!clean) return null;
  let normalized;
  if (clean.includes(",")) {
    normalized = clean.replace(/\./g, "").replace(",", ".");
  } else if (/^\d{1,3}(\.\d{3})+$/.test(clean)) {
    // Milhar pt-BR sem vírgula (ex.: "1.500", "12.345.678") → pontos são separadores
    normalized = clean.replace(/\./g, "");
  } else {
    normalized = clean;
  }
  const n = parseFloat(normalized);
  return isNaN(n) ? null : n;
}

function numToInput(num) {
  if (num == null) return "";
  // Convert server float to Brazilian decimal string
  return String(num).replace(".", ",");
}

function fmtDate(dateStr) {
  if (!dateStr) return null;
  try {
    return new Date(dateStr).toLocaleString("pt-BR");
  } catch {
    return dateStr;
  }
}

function defaultYearMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function AdminSalesTargets() {
  const { toast } = useToast();
  const [company, setCompany] = useState(() => api.getCurrentCompany?.() || "parton");
  const [month, setMonth] = useState(defaultYearMonth);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [rowErrors, setRowErrors] = useState({});
  const [inputValues, setInputValues] = useState({});
  const [reloadTick, setReloadTick] = useState(0);
  const loadedRef = useRef({});
  // Refs com o valor mais recente para o listener de troca de empresa (registrado uma vez).
  const hasDirtyRef = useRef(false);
  const companyRef = useRef(company);

  // Load metas whenever company, month, or reloadTick change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setRowErrors({});

    api
      .adminListSellerMetas({ company, year_month: month })
      .then((res) => {
        if (cancelled) return;
        const its = res?.items || [];
        setItems(its);
        const initInputs = {};
        const initLoaded = {};
        for (const item of its) {
          initInputs[item.seller_id] = numToInput(item.meta_amount);
          initLoaded[item.seller_id] = item.meta_amount ?? null;
        }
        setInputValues(initInputs);
        loadedRef.current = initLoaded;
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Erro ao carregar metas.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [company, month, reloadTick]);

  // Listen for global company changes
  useEffect(() => {
    function handleCompanyChanged(e) {
      const nextCompany = e?.detail?.company || api.getCurrentCompany?.() || "parton";
      const prevCompany = companyRef.current;
      // Ignora eventos que não mudam a empresa (inclui a restauração abaixo → evita loop).
      if (nextCompany === prevCompany) return;
      if (
        hasDirtyRef.current &&
        !window.confirm("Há alterações de metas não salvas. Descartar e trocar de empresa?")
      ) {
        // Cancelou: restaura a seleção global para a empresa anterior.
        api.setCurrentCompany?.(prevCompany);
        return;
      }
      setSaveError("");
      setRowErrors({});
      setCompany(nextCompany);
    }
    window.addEventListener("trml-company-changed", handleCompanyChanged);
    return () => window.removeEventListener("trml-company-changed", handleCompanyChanged);
  }, []);

  // Dirty detection: compare current input (parsed) vs loaded value
  const dirtyIds = items
    .filter((item) => {
      const parsed = parseBRL(inputValues[item.seller_id]);
      const loaded = loadedRef.current[item.seller_id] ?? null;
      return parsed !== loaded;
    })
    .map((item) => item.seller_id);
  const hasDirty = dirtyIds.length > 0;

  // Mantém os refs sincronizados para o listener de troca de empresa (registrado uma vez).
  hasDirtyRef.current = hasDirty;
  companyRef.current = company;

  // Client-side total of all filled inputs
  const totalMetas = items.reduce((sum, item) => {
    return sum + (parseBRL(inputValues[item.seller_id]) ?? 0);
  }, 0);

  async function handleSave() {
    if (!dirtyIds.length) return;

    // Camada 2: validação bloqueante — nenhum request se houver linha inválida
    const newErrors = {};
    for (const sellerId of dirtyIds) {
      const texto = (inputValues[sellerId] ?? "").trim();
      if (texto !== "") {
        const parsed = parseBRL(texto);
        if (parsed === null || parsed < 0) {
          newErrors[sellerId] = "Valor inválido";
        }
      }
    }
    if (Object.keys(newErrors).length > 0) {
      setRowErrors(newErrors);
      setSaveError("Corrija os valores inválidos antes de salvar.");
      return;
    }
    setRowErrors({});

    // Camada 3: confirmação para remoções (linhas sujas com texto vazio que tinham meta)
    const toDelete = dirtyIds.filter((sellerId) => {
      const texto = (inputValues[sellerId] ?? "").trim();
      const loaded = loadedRef.current[sellerId] ?? null;
      return texto === "" && loaded != null;
    });
    if (toDelete.length > 0) {
      const names = toDelete.map((id) => {
        const it = items.find((i) => i.seller_id === id);
        return it?.seller_name || id;
      });
      if (!window.confirm(`Remover a meta de: ${names.join(", ")}?`)) {
        return;
      }
    }

    setSaving(true);
    setSaveError("");
    try {
      await Promise.all(
        dirtyIds.map((sellerId) => {
          const parsed = parseBRL(inputValues[sellerId]);
          const loaded = loadedRef.current[sellerId] ?? null;
          const item = items.find((i) => i.seller_id === sellerId);
          if (parsed != null) {
            // Upsert
            return api.adminSaveSellerMeta(company, month, sellerId, {
              meta_amount: parsed,
              seller_name: item?.seller_name || "",
            });
          } else if (loaded != null) {
            // Had a meta, now cleared → delete
            return api.adminDeleteSellerMeta(company, month, sellerId);
          }
          return Promise.resolve();
        })
      );
      toast({ type: "success", message: "Metas salvas com sucesso." });
    } catch (e) {
      const errMsg = e?.message || "Erro ao salvar metas. Verifique e tente novamente.";
      setSaveError(errMsg);
      toast({ type: "error", message: errMsg });
    } finally {
      setSaving(false);
      setReloadTick((t) => t + 1);
    }
  }

  return (
    <div>
      {/* Header row: title + month picker */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
          marginBottom: 12,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700 }}>Metas mensais de vendas por vendedor</div>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>
            Empresa: <strong>{COMPANY_LABELS[company] || company}</strong>
          </div>
        </div>
        <Field label="Mês" id="targets-month">
          <input
            id="targets-month"
            type="month"
            value={month}
            onChange={(e) => {
              // Input controlado: se cancelar, não atualiza o estado → mantém o mês anterior.
              if (
                hasDirty &&
                !window.confirm("Há alterações de metas não salvas. Descartar e trocar de mês?")
              ) {
                return;
              }
              setSaveError("");
              setRowErrors({});
              setMonth(e.target.value);
            }}
          />
        </Field>
      </div>

      {error ? <div className="adminAlert error">{error}</div> : null}
      {saveError ? <div className="adminAlert error">{saveError}</div> : null}

      {loading ? (
        <div style={{ padding: 16, color: "var(--muted)" }}>Carregando...</div>
      ) : items.length === 0 ? (
        <EmptyState message="Nenhum vendedor Tiny encontrado para esta empresa." />
      ) : (
        <>
          <Table zebra>
            <thead>
              <tr>
                <th align="left">Vendedor</th>
                <th align="left">Meta (R$)</th>
                <th align="left">Última atualização</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const isDirty = dirtyIds.includes(item.seller_id);
                return (
                  <tr
                    key={item.seller_id}
                    style={isDirty ? { background: "var(--accent-soft)" } : undefined}
                  >
                    <td>
                      <div>{item.seller_name || item.seller_id}</div>
                      <div style={{ color: "var(--muted)", fontSize: 11 }}>
                        {item.seller_id}
                        {!item.linked ? (
                          <span style={{ marginLeft: 6, fontStyle: "italic" }}>
                            não vinculado
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <input
                        type="text"
                        inputMode="decimal"
                        value={inputValues[item.seller_id] ?? ""}
                        placeholder="Sem meta"
                        style={{
                          width: 140,
                          padding: "4px 8px",
                          borderRadius: 6,
                          border: rowErrors[item.seller_id]
                            ? "1px solid var(--danger)"
                            : "1px solid var(--border)",
                          background: "var(--surface)",
                          color: "inherit",
                        }}
                        onChange={(e) => {
                          const raw = e.target.value.replace(/[^\d.,]/g, "");
                          setInputValues((prev) => ({ ...prev, [item.seller_id]: raw }));
                          if (rowErrors[item.seller_id]) {
                            setRowErrors((prev) => {
                              const next = { ...prev };
                              delete next[item.seller_id];
                              return next;
                            });
                          }
                        }}
                      />
                      {rowErrors[item.seller_id] ? (
                        <div style={{ color: "var(--danger)", fontSize: 11, marginTop: 2 }}>
                          {rowErrors[item.seller_id]}
                        </div>
                      ) : null}
                    </td>
                    <td style={{ color: "var(--muted)", fontSize: 12 }}>
                      {item.updated_at ? (
                        <>
                          {fmtDate(item.updated_at)}
                          {item.updated_by ? (
                            <span>
                              {" "}
                              por <strong>{item.updated_by}</strong>
                            </span>
                          ) : null}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>

          {/* Footer: total + save */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginTop: 14,
              flexWrap: "wrap",
              gap: 12,
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 14 }}>
              Total das metas:{" "}
              <span style={{ color: "var(--accent)" }}>{BRL.format(totalMetas)}</span>
            </div>
            <Button
              type="button"
              variant="primary"
              loading={saving}
              disabled={!hasDirty}
              onClick={handleSave}
            >
              Salvar metas
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
