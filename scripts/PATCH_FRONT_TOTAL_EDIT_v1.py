from pathlib import Path

qm_path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\components\QuotesModal.jsx")
nq_path = Path(r"C:\TRML_LOCAL\ERP\frontend\src\pages\NewQuote.jsx")

qm = qm_path.read_text(encoding="utf-8")
nq = nq_path.read_text(encoding="utf-8")

# =========================
# QuotesModal: total robusto
# =========================
old = '''            const totals = safeJson(q.totals) || {};
            const checked = !!selectedIds[q.quote_id];
            const clientSnap = safeJson(q.client_snapshot) || {};
            const clientName = clientSnap?.nome || q.client_name || "";
            const internalStatus = getCommercialStatus(q) || "—";
            const costTotalProducts = Number(q.cost_total_products || 0);
            const saleTotalProducts = Number(q.sale_total_products || 0);
            const profitTotalProducts = Number(q.profit_total_products || 0);
            const markupTotalOrder = q.markup_total_order;
'''

new = '''            const totals = (q.totals && typeof q.totals === "object")
              ? q.totals
              : (safeJson(q.totals) || {});
            const payload = (q.payload && typeof q.payload === "object")
              ? q.payload
              : (safeJson(q.payload) || {});
            const checked = !!selectedIds[q.quote_id];
            const clientSnap = (q.client_snapshot && typeof q.client_snapshot === "object")
              ? q.client_snapshot
              : (safeJson(q.client_snapshot) || {});
            const clientName = clientSnap?.nome || clientSnap?.name || q.client_name || q.cliente_nome || q.customer_name || "";
            const internalStatus = getCommercialStatus(q) || "—";
            const rowTotal = Number(
              q.total ??
              q.total_net ??
              q.valor_total ??
              q.total_amount ??
              q.amount_total ??
              q.net ??
              totals?.net ??
              totals?.total ??
              totals?.items ??
              payload?.total ??
              payload?.total_net ??
              payload?.items_total ??
              q.sale_total_products ??
              q.items_total ??
              0
            );
            const costTotalProducts = Number(q.cost_total_products || 0);
            const saleTotalProducts = Number(q.sale_total_products || rowTotal || 0);
            const profitTotalProducts = Number(q.profit_total_products || 0);
            const markupTotalOrder = q.markup_total_order;
'''

if old not in qm:
    raise SystemExit("Bloco de cálculo da linha em QuotesModal.jsx não encontrado.")

qm = qm.replace(old, new)

old = '''                    {money(totals?.net || totals?.total || 0)}
'''

new = '''                    {money(rowTotal)}
'''

if old not in qm:
    raise SystemExit("Bloco de renderização do total em QuotesModal.jsx não encontrado.")

qm = qm.replace(old, new)

qm_path.write_text(qm, encoding="utf-8")


# =========================
# NewQuote: cliente usa q.client_name antes de Cliente #ID
# =========================
old = '''      setSelectedClient({
        id: Number(q.client_id),
        nome: clientSnap?.nome || clientSnap?.name || `Cliente #${q.client_id}`,
        cpf_cnpj: clientSnap?.cpf_cnpj || clientSnap?.cpfCnpj || "",
        raw: clientSnap,
      });
'''

new = '''      setSelectedClient({
        id: Number(q.client_id),
        nome: clientSnap?.nome || clientSnap?.name || q.client_name || q.cliente_nome || q.customer_name || `Cliente #${q.client_id}`,
        cpf_cnpj: clientSnap?.cpf_cnpj || clientSnap?.cpfCnpj || "",
        raw: clientSnap,
      });
'''

if old not in nq:
    raise SystemExit("Bloco setSelectedClient em NewQuote.jsx não encontrado.")

nq = nq.replace(old, new)


# =========================
# NewQuote: preservar frete ao editar enquanto carrega métodos
# =========================
old = '''  const [freightMethods, setFreightMethods] = useState([]);
  const [freightLoading, setFreightLoading] = useState(false);
  const [selectedFreightId, setSelectedFreightId] = useState("");
'''

new = '''  const [freightMethods, setFreightMethods] = useState([]);
  const [freightLoading, setFreightLoading] = useState(false);
  const [selectedFreightId, setSelectedFreightId] = useState("");
  const pendingFreightIdRef = useRef("");
'''

if old not in nq:
    raise SystemExit("Bloco de states de frete em NewQuote.jsx não encontrado.")

nq = nq.replace(old, new)

old = '''      setSelectedShippingId(q.shipping_method_id ? String(q.shipping_method_id) : "");
      setSelectedFreightId(q.freight_method_id ? String(q.freight_method_id) : "");
'''

new = '''      const freightIdToRestore = q.freight_method_id || q.freight_id || payloadSaved.freight_method_id || payloadSaved.freight_id || "";
      pendingFreightIdRef.current = freightIdToRestore ? String(freightIdToRestore) : "";

      setSelectedShippingId(q.shipping_method_id ? String(q.shipping_method_id) : "");
      setSelectedFreightId(freightIdToRestore ? String(freightIdToRestore) : "");
'''

if old not in nq:
    raise SystemExit("Bloco selectedShipping/selectedFreight em NewQuote.jsx não encontrado.")

nq = nq.replace(old, new)

old = '''  useEffect(() => {
    let cancelled = false;
    async function run() {
      setFreightMethods([]);
      setSelectedFreightId("");
      if (!selectedShippingId) return;

      setFreightLoading(true);
      try {
        const r = await api.tinyFreightMethods(selectedShippingId);
        if (cancelled) return;
        const list = r.items || [];
        setFreightMethods(list);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setFreightLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [selectedShippingId]);
'''

new = '''  useEffect(() => {
    let cancelled = false;
    async function run() {
      setFreightMethods([]);

      const pendingFreightId = pendingFreightIdRef.current;
      if (!pendingFreightId) {
        setSelectedFreightId("");
      }

      if (!selectedShippingId) return;

      setFreightLoading(true);
      try {
        const r = await api.tinyFreightMethods(selectedShippingId);
        if (cancelled) return;
        const list = r.items || [];
        setFreightMethods(list);

        if (pendingFreightId) {
          const exists = list.some((f) => String(f.id) === String(pendingFreightId));
          if (exists) {
            setSelectedFreightId(String(pendingFreightId));
          }
          pendingFreightIdRef.current = "";
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setFreightLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [selectedShippingId]);
'''

if old not in nq:
    raise SystemExit("Bloco useEffect de freightMethods em NewQuote.jsx não encontrado.")

nq = nq.replace(old, new)

nq_path.write_text(nq, encoding="utf-8")

print("OK: total em Operações, cliente e frete na edição corrigidos no frontend.")
