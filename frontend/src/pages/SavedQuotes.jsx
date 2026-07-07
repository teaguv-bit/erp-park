import { useMemo, useState } from "react";
import QuotesModal from "../components/QuotesModal";
import { Button, Card, Table, StatusPill, EmptyState } from "../ui";

function money(n) {
  const v = Number(n || 0);
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtDateTime(s) {
  if (!s) return "—";
  try {
    const d = new Date(s);
    return d.toLocaleString("pt-BR");
  } catch {
    return s || "—";
  }
}

function fmtDate(s) {
  if (!s) return "—";
  try {
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(s))) {
      const [y, m, d] = String(s).split("-");
      return `${d}/${m}/${y}`;
    }
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return s || "—";
    return d.toLocaleDateString("pt-BR");
  } catch {
    return s || "—";
  }
}

function safeJsonParse(value, fallback = {}) {
  if (!value) return fallback;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function pick(obj, ...keys) {
  for (const k of keys) {
    const v = obj?.[k];
    if (v !== undefined && v !== null && String(v).trim() !== "") return String(v).trim();
  }
  return "";
}

function buildClientAddress(client) {
  const endereco = pick(client, "endereco", "address");
  const numero = pick(client, "numero", "number");
  const complemento = pick(client, "complemento", "address2");
  const bairro = pick(client, "bairro", "district");
  const cidade = pick(client, "cidade", "city");
  const uf = pick(client, "uf", "state");
  const cep = pick(client, "cep", "zipcode");

  const linha1 = [endereco, numero].filter(Boolean).join(", ");
  const linha2 = [complemento, bairro].filter(Boolean).join(" • ");
  const linha3 = [cidade, uf, cep].filter(Boolean).join(" - ");

  return [linha1, linha2, linha3].filter(Boolean).join(" | ");
}

function getProductMeta(item) {
  const raw = safeJsonParse(item?.raw, {});
  const productRaw = raw?.product_raw || {};

  return {
    brand: pick(productRaw, "marca", "brand") || "—",
    category: pick(productRaw, "categoria", "category", "nome_categoria") || "—",
    location: pick(productRaw, "localizacao", "deposito", "warehouse_location", "local") || "—",
  };
}

function InfoBlock({ title, rows }) {
  return (
    <div
      style={{
        background: "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))",
        border: "1px solid var(--border)",
        borderRadius: 20,
        padding: 16,
        boxShadow: "0 14px 30px rgba(0,0,0,0.10)",
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 900,
          color: "var(--muted)",
          marginBottom: 10,
          textTransform: "uppercase",
          letterSpacing: ".14em",
        }}
      >
        {title}
      </div>

      <div style={{ display: "grid", gap: 10 }}>
        {rows.map((row) => (
          <div
            key={row.label}
            style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr",
              gap: 10,
              alignItems: "start",
            }}
          >
            <div style={{ color: "var(--muted)", fontSize: 12, fontWeight: 800 }}>
              {row.label}
            </div>
            <div style={{ color: "var(--text)", fontSize: 14, wordBreak: "break-word" }}>
              {row.value || "—"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SavedQuotes({ onEditQuote } = {}) {
  const [previewDetail, setPreviewDetail] = useState(null);

  const isSeparationDetail = !!previewDetail?.order;
  const detailOrder = previewDetail?.order || null;
  const detailItems = Array.isArray(previewDetail?.items) ? previewDetail.items : [];

  const quote = previewDetail?.quote || null;
  const quoteItems = Array.isArray(previewDetail?.items) ? previewDetail.items : [];

  const detailPayload = useMemo(
    () => safeJsonParse(detailOrder?.payload, {}),
    [detailOrder]
  );
  const approvedAt = detailOrder?.approved_at || detailOrder?.approvedAt || detailPayload?.approved_at || detailPayload?.approvedAt;

  const client = useMemo(() => {
    if (detailOrder?.client_snapshot) return safeJsonParse(detailOrder.client_snapshot, {});
    if (quote?.client_snapshot) return safeJsonParse(quote.client_snapshot, {});
    return {};
  }, [detailOrder, quote]);

  const simpleClientName = useMemo(() => {
    if (isSeparationDetail) {
      return pick(client, "nome", "name") || detailOrder?.client_name || "Consumidor Final";
    }

    const snap = quote?.client_snapshot;
    if (!snap) return quote?.client_name || "—";
    try {
      const obj = typeof snap === "string" ? JSON.parse(snap) : snap;
      return obj?.nome || quote?.client_name || "—";
    } catch {
      return quote?.client_name || "—";
    }
  }, [client, detailOrder, isSeparationDetail, quote]);

  const totals = useMemo(() => {
    const source = isSeparationDetail ? detailItems : quoteItems;
    const qtyTotal = source.reduce((acc, item) => acc + Number(item?.qty || item?.quantity || item?.quantidade || 0), 0);
    const grossTotal = source.reduce(
      (acc, item) =>
        acc + Number(item?.line_total || item?.total || (Number(item?.qty || item?.quantity || item?.quantidade || 0) * Number(item?.unit_price || item?.price || item?.valor_unitario || 0)) || 0),
      0
    );
    return { qtyTotal, grossTotal };
  }, [detailItems, quoteItems, isSeparationDetail]);

  const financialSummary = useMemo(() => {
    const source = detailItems || [];
    let grossBeforeDiscount = 0;
    let netAfterDiscount = 0;

    for (const item of source) {
      const qty = Number(item?.qty || 0);
      const listPrice = Number(item?.list_price || 0);
      const lineTotal = Number(item?.line_total || (qty * Number(item?.unit_price_disc || 0)) || 0);

      grossBeforeDiscount += qty * listPrice;
      netAfterDiscount += lineTotal;
    }

    const discountTotal = Math.max(0, grossBeforeDiscount - netAfterDiscount);

    return {
      grossBeforeDiscount,
      discountTotal,
      netAfterDiscount,
    };
  }, [detailItems]);

  const paymentCondition = useMemo(() => {
    return (
      detailPayload?.payment_condition ||
      detailPayload?.condicao_pagamento ||
      detailPayload?.payment_terms ||
      "—"
    );
  }, [detailPayload]);

  const paymentInstallments = useMemo(() => {
    const arr = Array.isArray(detailPayload?.payment_installments)
      ? detailPayload.payment_installments
      : [];

    return arr
      .map((p, idx) => {
        if (!p || typeof p !== "object") return null;
        return {
          n: p?.n || p?.parcela || idx + 1,
          due_date: p?.due_date || p?.vencimento || p?.date || "",
          amount: Number(p?.amount || p?.valor || p?.value || 0),
        };
      })
      .filter(Boolean);
  }, [detailPayload]);

  return (
    <>
      <QuotesModal
        embedded
        open
        onEditQuote={onEditQuote}
        onOpenPreview={setPreviewDetail}
      />

      {previewDetail ? (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(2,6,23,0.74)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
            zIndex: 10000,
          }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setPreviewDetail(null);
          }}
        >
          <div
            style={{
              width: "min(1400px, 96vw)",
              maxHeight: "92vh",
              overflowY: "auto",
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: 24,
              padding: 18,
              boxShadow: "0 28px 60px rgba(0,0,0,0.30)",
              color: "var(--text)",
            }}
          >
            <div
              style={{
                position: "sticky",
                top: -18,
                zIndex: 5,
                background: "var(--card)",
                paddingTop: 16,
                paddingBottom: 12,
                marginBottom: 16,
                borderBottom: "1px solid var(--border)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 16,
                flexWrap: "wrap",
              }}
            >
              <div>
                <div style={{ fontSize: 22, fontWeight: 900, color: "var(--text)" }}>
                  {isSeparationDetail ? "Detalhe completo do pedido" : "Detalhes do pedido / orçamento"}
                </div>
                <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>
                  {isSeparationDetail
                    ? "Consulta detalhada no padrão da separação."
                    : "Consulta rápida para conferência."}
                </div>
              </div>

              <Button variant="secondary" size="sm" onClick={() => setPreviewDetail(null)}>
                Fechar
              </Button>
            </div>

            {isSeparationDetail ? (
              <>
                <div style={{ marginBottom: 16 }}>
                  <Card padding="sm">
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(4, minmax(180px, 1fr))",
                        gap: 12,
                      }}
                    >
                      <div>
                        <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>Pedido Tiny</div>
                        <div style={{ fontWeight: 900, marginTop: 4 }}>
                          #{detailOrder?.tiny_order_number || detailOrder?.tiny_order_id || "—"}
                        </div>
                      </div>

                      <div>
                        <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>Orçamento</div>
                        <div style={{ fontWeight: 900, marginTop: 4 }}>
                          {detailOrder?.quote_number || "—"}
                        </div>
                      </div>

                      <div>
                        <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>Status da separação</div>
                        <div style={{ marginTop: 4 }}>
                          {detailOrder?.separation_status ? (
                            <StatusPill status={detailOrder.separation_status} />
                          ) : (
                            "—"
                          )}
                        </div>
                      </div>

                      <div>
                        <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>Impresso</div>
                        <div style={{ fontWeight: 900, marginTop: 4 }}>
                          {detailOrder?.printed ? "Sim" : "Não"}
                        </div>
                      </div>
                    </div>
                  </Card>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                    gap: 16,
                    marginBottom: 16,
                  }}
                >
                  <InfoBlock
                    title="Cliente"
                    rows={[
                      { label: "Nome", value: pick(client, "nome", "name") || "Consumidor Final" },
                      { label: "CNPJ / CPF", value: pick(client, "cpf_cnpj", "cpfCnpj", "documento") },
                      { label: "Telefone", value: pick(client, "fone", "telefone", "phone") },
                      { label: "E-mail", value: pick(client, "email") },
                      { label: "Endereço", value: buildClientAddress(client) },
                    ]}
                  />

                  <InfoBlock
                    title="Comercial / envio"
                    rows={[
                      { label: "Vendedor", value: detailOrder?.seller_name },
                      { label: "Forma de envio", value: detailOrder?.shipping_method_name },
                      { label: "Forma de frete", value: detailOrder?.freight_method_name },
                      { label: "Criado em", value: fmtDateTime(detailOrder?.created_at) },
                      { label: "Aprovado em", value: fmtDateTime(approvedAt) },
                      { label: "Atualizado em", value: fmtDateTime(detailOrder?.updated_at) },
                    ]}
                  />
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                    gap: 16,
                    marginBottom: 16,
                  }}
                >
                  <InfoBlock
                    title="Pagamento"
                    rows={[
                      { label: "Forma", value: detailOrder?.payment_method_name || detailOrder?.payment_method_code || "—" },
                      { label: "Condição", value: paymentCondition },
                      { label: "Meio", value: detailOrder?.payment_meio || "—" },
                      { label: "Conta", value: detailOrder?.payment_conta || "—" },
                      { label: "Vencimento base", value: fmtDate(detailOrder?.payment_due_date) },
                      { label: "Categoria", value: detailOrder?.payment_category || "—" },
                    ]}
                  />

                  <InfoBlock
                    title="Resumo financeiro"
                    rows={[
                      { label: "Bruto tabela", value: money(financialSummary.grossBeforeDiscount) },
                      { label: "Desconto total", value: money(financialSummary.discountTotal) },
                      { label: "Total final", value: money(financialSummary.netAfterDiscount) },
                    ]}
                  />
                </div>

                {paymentInstallments.length ? (
                  <div style={{ marginBottom: 16 }}>
                    <Card padding="sm" title="Parcelas">
                      <Table>
                        <thead>
                          <tr>
                            <th>Parcela</th>
                            <th>Vencimento</th>
                            <th data-numeric>Valor</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paymentInstallments.map((p, idx) => (
                            <tr key={`${p.n}-${idx}`}>
                              <td>{p.n}</td>
                              <td>{fmtDate(p.due_date)}</td>
                              <td data-numeric style={{ fontWeight: 800 }}>{money(p.amount)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    </Card>
                  </div>
                ) : null}

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                    gap: 16,
                    marginBottom: 16,
                  }}
                >
                  <InfoBlock
                    title="Controle operacional"
                    rows={[
                      { label: "Status", value: detailOrder?.separation_status ? <StatusPill status={detailOrder.separation_status} /> : "—" },
                      { label: "Responsável", value: detailOrder?.assigned_to || "—" },
                      { label: "Caixas", value: String(detailOrder?.packaging_boxes ?? 0) },
                      { label: "Sacolas", value: String(detailOrder?.packaging_bags ?? 0) },
                      { label: "Impresso", value: detailOrder?.printed ? "Sim" : "Não" },
                      { label: "Observações", value: detailOrder?.separation_notes || "—" },
                    ]}
                  />

                  <InfoBlock
                    title="Marcos da separação"
                    rows={[
                      { label: "Iniciado em", value: fmtDateTime(detailOrder?.started_at) },
                      { label: "Impresso em", value: fmtDateTime(detailOrder?.printed_at) },
                      { label: "Separado em", value: fmtDateTime(detailOrder?.separated_at) },
                      { label: "Notas do orçamento", value: detailOrder?.notes || "—" },
                    ]}
                  />
                </div>

                <Card padding="sm">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 12, flexWrap: "wrap" }}>
                    <div>
                      <div
                        style={{
                          fontSize: 12,
                          fontWeight: 800,
                          color: "var(--muted)",
                          marginBottom: 4,
                          textTransform: "uppercase",
                          letterSpacing: ".03em",
                        }}
                      >
                        Itens do pedido
                      </div>
                      <div style={{ color: "var(--muted)", fontSize: 13 }}>
                        Quantidade total: <strong>{totals.qtyTotal}</strong> • Total final: <strong>{money(financialSummary.netAfterDiscount)}</strong> • Desconto total: <strong>{money(financialSummary.discountTotal)}</strong>
                      </div>
                    </div>
                  </div>

                  <Table>
                    <thead>
                      <tr>
                        <th>Linha</th>
                        <th>SKU</th>
                        <th>Produto</th>
                        <th>Marca</th>
                        <th>Categoria</th>
                        <th>Localização</th>
                        <th data-numeric>Qtd</th>
                        <th data-numeric>Preço lista</th>
                        <th data-numeric>Desc. %</th>
                        <th data-numeric>Desconto</th>
                        <th data-numeric>Preço venda</th>
                        <th data-numeric>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailItems.length === 0 ? (
                        <tr>
                          <td colSpan={12}>
                            <EmptyState message="Nenhum item encontrado para este pedido." />
                          </td>
                        </tr>
                      ) : null}

                      {detailItems.map((item, idx) => {
                        const meta = getProductMeta(item);
                        const qty = Number(item?.qty || 0);
                        const listPrice = Number(item?.list_price || 0);
                        const unitSale = Number(item?.unit_price_disc || 0);
                        const lineTotal = Number(item?.line_total || 0);
                        const discountPct = Number(item?.discount_pct || 0);
                        const discountValue = Math.max(0, (qty * listPrice) - lineTotal);

                        return (
                          <tr key={`${item?.quote_id || "q"}-${item?.line || idx}`}>
                            <td>{item?.line ?? idx + 1}</td>
                            <td>{item?.sku_snapshot || "—"}</td>
                            <td>
                              <div style={{ fontWeight: 700 }}>{item?.name_snapshot || "—"}</div>
                              <div style={{ color: "var(--muted)", fontSize: 12 }}>
                                Produto ID: {item?.product_id || "—"}
                              </div>
                            </td>
                            <td>{meta.brand}</td>
                            <td>{meta.category}</td>
                            <td>{meta.location}</td>
                            <td data-numeric>{qty}</td>
                            <td data-numeric>{money(listPrice)}</td>
                            <td data-numeric>{discountPct.toFixed(2)}%</td>
                            <td data-numeric>{money(discountValue)}</td>
                            <td data-numeric>{money(unitSale)}</td>
                            <td data-numeric>{money(lineTotal)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </Table>
                </Card>
              </>
            ) : (
              <div style={{ padding: 16, display: "grid", gap: 16 }}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(4, minmax(180px, 1fr))",
                    gap: 12,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Número</div>
                    <div style={{ marginTop: 4 }}>{quote?.quote_number || quote?.quote_id || "—"}</div>
                  </div>

                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Tiny</div>
                    <div style={{ marginTop: 4 }}>{quote?.tiny_order_number || quote?.tiny_order_id || "—"}</div>
                  </div>

                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Criado em</div>
                    <div style={{ marginTop: 4 }}>{fmtDateTime(quote?.created_at)}</div>
                  </div>

                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Status</div>
                    <div style={{ marginTop: 4 }}>
                      {quote?.internal_status || quote?.status ? (
                        <StatusPill status={quote?.internal_status || quote?.status} />
                      ) : (
                        "—"
                      )}
                    </div>
                  </div>

                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Cliente</div>
                    <div style={{ marginTop: 4 }}>{simpleClientName}</div>
                  </div>

                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Vendedor</div>
                    <div style={{ marginTop: 4 }}>{quote?.seller_name || "—"}</div>
                  </div>

                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Forma de envio</div>
                    <div style={{ marginTop: 4 }}>{quote?.shipping_method_name || "—"}</div>
                  </div>

                  <div>
                    <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 900 }}>Frete</div>
                    <div style={{ marginTop: 4 }}>{quote?.freight_method_name || "—"}</div>
                  </div>
                </div>

                <Table>
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Produto</th>
                      <th data-numeric>Qtd</th>
                      <th data-numeric>Unitário</th>
                      <th data-numeric>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quoteItems.length ? (
                      quoteItems.map((item, idx) => {
                        const qty = Number(item?.qty || item?.quantity || item?.quantidade || 0);
                        const unit = Number(item?.unit_price || item?.price || item?.valor_unitario || 0);
                        const total = Number(item?.line_total || item?.total || qty * unit || 0);

                        return (
                          <tr key={item?.quote_item_id || item?.id || idx}>
                            <td>{item?.sku || "—"}</td>
                            <td>{item?.name || item?.descricao || "—"}</td>
                            <td data-numeric>{qty}</td>
                            <td data-numeric>{money(unit)}</td>
                            <td data-numeric style={{ fontWeight: 900 }}>{money(total)}</td>
                          </tr>
                        );
                      })
                    ) : (
                      <tr>
                        <td colSpan={5}>
                          <EmptyState message="Nenhum item encontrado." />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </Table>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
