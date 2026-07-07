import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

function Pill({ children, tone = "default" }) {
  const styles = {
    default: {
      background: "rgba(148, 163, 184, 0.12)",
      border: "1px solid rgba(148, 163, 184, 0.22)",
      color: "var(--text)",
    },
    ok: {
      background: "rgba(34, 197, 94, 0.12)",
      border: "1px solid rgba(34, 197, 94, 0.22)",
      color: "#86efac",
    },
    warn: {
      background: "rgba(245, 158, 11, 0.12)",
      border: "1px solid rgba(245, 158, 11, 0.22)",
      color: "#fcd34d",
    },
    bad: {
      background: "rgba(239, 68, 68, 0.12)",
      border: "1px solid rgba(239, 68, 68, 0.22)",
      color: "#fca5a5",
    },
    info: {
      background: "rgba(59, 130, 246, 0.12)",
      border: "1px solid rgba(59, 130, 246, 0.22)",
      color: "#93c5fd",
    },
  };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "4px 8px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 800,
        whiteSpace: "nowrap",
        ...styles[tone],
      }}
    >
      {children}
    </span>
  );
}

function toneForState(state, tinyExists, tinyStatus, localStatus) {
  const tiny = String(tinyStatus || "").toLowerCase();
  const local = String(localStatus || "").toLowerCase();

  if (state === "ok") {
    if (tiny && local && tiny !== local) return "warn";
    return "ok";
  }
  if (state === "missing_in_tiny") return "bad";
  if (state === "tiny_error") return "bad";
  if (state === "invalid_local_tiny_order_id") return "bad";
  if (tinyExists === false) return "bad";
  return "info";
}

function statusLabel(item) {
  const state = item?.sync_state || "—";
  if (state === "ok") {
    const tiny = String(item?.tiny?.situacao || "").trim();
    const local = String(item?.internal_status || item?.status || "").trim();
    if (tiny && local && tiny.toLowerCase() !== local.toLowerCase()) {
      return "Divergente";
    }
    return "OK";
  }
  if (state === "missing_in_tiny") return "Ausente no Tiny";
  if (state === "tiny_error") return "Erro no Tiny";
  if (state === "invalid_local_tiny_order_id") return "ID inválido";
  return state || "—";
}

export default function TinySyncPreview() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [localLimit, setLocalLimit] = useState(20);
  const [remotePages, setRemotePages] = useState(1);
  const [remoteSearch, setRemoteSearch] = useState("");

  async function load() {
    try {
      setLoading(true);
      setError("");
      const r = await api.tinySyncPreview({
        local_limit: localLimit,
        include_remote: true,
        remote_pages: remotePages,
        remote_search: remoteSearch,
      });
      setData(r || null);
    } catch (e) {
      setError(e?.message || "Erro ao carregar preview de sincronização.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const items = useMemo(() => (Array.isArray(data?.items) ? data.items : []), [data]);
  const remoteOnly = useMemo(() => (Array.isArray(data?.remote_only) ? data.remote_only : []), [data]);

  const divergent = useMemo(() => {
    return items.filter((it) => {
      if (it?.sync_state !== "ok") return false;
      const tiny = String(it?.tiny?.situacao || "").trim().toLowerCase();
      const local = String(it?.internal_status || it?.status || "").trim().toLowerCase();
      return Boolean(tiny && local && tiny !== local);
    });
  }, [items]);

  const missing = useMemo(() => items.filter((it) => it?.sync_state === "missing_in_tiny"), [items]);
  const errors = useMemo(() => items.filter((it) => it?.sync_state === "tiny_error"), [items]);

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          border: "1px solid var(--border)",
          background: "var(--panel)",
          padding: 18,
          marginBottom: 16,
        }}
      >
        <div style={{ fontSize: 24, fontWeight: 900, marginBottom: 8 }}>
          Preview Sync Tiny
        </div>
        <div style={{ color: "var(--muted)", fontSize: 14, marginBottom: 14 }}>
          Visualização somente leitura. Não escreve no Tiny e não escreve no BigQuery.
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "140px 140px 1fr auto",
            gap: 10,
            alignItems: "end",
          }}
        >
          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>Locais</span>
            <input
              type="number"
              min="1"
              max="500"
              value={localLimit}
              onChange={(e) => setLocalLimit(Number(e.target.value || 20))}
              style={{
                width: "100%",
                padding: "12px 14px",
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text)",
              }}
            />
          </label>

          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>Páginas Tiny</span>
            <input
              type="number"
              min="1"
              max="10"
              value={remotePages}
              onChange={(e) => setRemotePages(Number(e.target.value || 1))}
              style={{
                width: "100%",
                padding: "12px 14px",
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text)",
              }}
            />
          </label>

          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>Busca remota</span>
            <input
              value={remoteSearch}
              onChange={(e) => setRemoteSearch(e.target.value)}
              placeholder="Opcional"
              style={{
                width: "100%",
                padding: "12px 14px",
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text)",
              }}
            />
          </label>

          <button
            onClick={load}
            disabled={loading}
            style={{
              padding: "12px 16px",
              border: "1px solid var(--border)",
              background: "var(--panel)",
              color: "var(--text)",
              cursor: "pointer",
              fontWeight: 800,
            }}
          >
            {loading ? "Carregando..." : "Atualizar"}
          </button>
        </div>
      </div>

      {error ? (
        <div
          style={{
            border: "1px solid rgba(239,68,68,0.3)",
            background: "rgba(239,68,68,0.08)",
            color: "#fca5a5",
            padding: 12,
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, minmax(180px, 1fr))",
          gap: 12,
          marginBottom: 16,
        }}
      >
        {[
          ["Locais conferidos", data?.stats?.local_checked ?? 0],
          ["Encontrados no Tiny", data?.stats?.tiny_found ?? 0],
          ["Ausentes no Tiny", data?.stats?.tiny_missing ?? 0],
          ["Erros Tiny", data?.stats?.tiny_errors ?? 0],
          ["Somente no Tiny", data?.stats?.remote_only_found ?? 0],
        ].map(([label, value]) => (
          <div
            key={label}
            style={{
              border: "1px solid var(--border)",
              background: "var(--panel)",
              padding: 14,
            }}
          >
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{label}</div>
            <div style={{ fontSize: 28, fontWeight: 900 }}>{value}</div>
          </div>
        ))}
      </div>

      <section style={{ border: "1px solid var(--border)", background: "var(--panel)", overflow: "auto", marginBottom: 16 }}>
        <div style={{ padding: 14, borderBottom: "1px solid var(--border)", fontWeight: 900 }}>
          Pedidos locais vs Tiny
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1400 }}>
          <thead>
            <tr>
              {[
                "Sync",
                "Pedido local",
                "Pedido Tiny",
                "Cliente",
                "Status local",
                "Status Tiny",
                "Existe no Tiny?",
                "Erro",
              ].map((h) => (
                <th
                  key={h}
                  style={{
                    textAlign: "left",
                    padding: 12,
                    borderBottom: "1px solid var(--border)",
                    color: "var(--muted)",
                    fontSize: 12,
                    fontWeight: 900,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((it, idx) => (
              <tr key={`${it?.quote_id || "x"}-${it?.tiny_order_id || idx}`}>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
                  <Pill tone={toneForState(it?.sync_state, it?.tiny_exists, it?.tiny?.situacao, it?.internal_status || it?.status)}>
                    {statusLabel(it)}
                  </Pill>
                </td>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)", fontWeight: 800 }}>
                  {it?.quote_number || it?.quote_id || "—"}
                </td>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
                  <div>{it?.tiny_order_number || "—"}</div>
                  <div style={{ color: "var(--muted)", fontSize: 12 }}>ID {it?.tiny_order_id || "—"}</div>
                </td>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
                  {it?.client_name || it?.tiny?.cliente_nome || "—"}
                </td>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
                  {it?.internal_status || it?.status || "—"}
                </td>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
                  {it?.tiny?.situacao || "—"}
                </td>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
                  {it?.tiny_exists === true ? (
                    <Pill tone="ok">Sim</Pill>
                  ) : it?.tiny_exists === false ? (
                    <Pill tone="bad">Não</Pill>
                  ) : (
                    <Pill tone="warn">Incerto</Pill>
                  )}
                </td>
                <td style={{ padding: 12, borderBottom: "1px solid var(--border)", color: "#fca5a5" }}>
                  {it?.tiny_error || "—"}
                </td>
              </tr>
            ))}

            {!items.length ? (
              <tr>
                <td colSpan={8} style={{ padding: 18, color: "var(--muted)" }}>
                  Nenhum item retornado.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <section style={{ border: "1px solid var(--border)", background: "var(--panel)", padding: 14 }}>
          <div style={{ fontWeight: 900, marginBottom: 10 }}>Divergentes</div>
          <div style={{ display: "grid", gap: 8 }}>
            {divergent.length ? divergent.map((it, idx) => (
              <div key={idx} style={{ border: "1px solid var(--border)", padding: 10 }}>
                <div style={{ fontWeight: 800 }}>{it?.client_name || "—"}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>
                  Local: {it?.internal_status || it?.status || "—"} | Tiny: {it?.tiny?.situacao || "—"}
                </div>
              </div>
            )) : <div style={{ color: "var(--muted)" }}>Nenhum divergente.</div>}
          </div>
        </section>

        <section style={{ border: "1px solid var(--border)", background: "var(--panel)", padding: 14 }}>
          <div style={{ fontWeight: 900, marginBottom: 10 }}>Ausentes no Tiny</div>
          <div style={{ display: "grid", gap: 8 }}>
            {missing.length ? missing.map((it, idx) => (
              <div key={idx} style={{ border: "1px solid var(--border)", padding: 10 }}>
                <div style={{ fontWeight: 800 }}>{it?.client_name || "—"}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>
                  Pedido Tiny ID: {it?.tiny_order_id || "—"}
                </div>
              </div>
            )) : <div style={{ color: "var(--muted)" }}>Nenhum ausente.</div>}
          </div>
        </section>

        <section style={{ border: "1px solid var(--border)", background: "var(--panel)", padding: 14 }}>
          <div style={{ fontWeight: 900, marginBottom: 10 }}>Somente no Tiny</div>
          <div style={{ display: "grid", gap: 8, maxHeight: 420, overflow: "auto" }}>
            {remoteOnly.length ? remoteOnly.map((it, idx) => (
              <div key={idx} style={{ border: "1px solid var(--border)", padding: 10 }}>
                <div style={{ fontWeight: 800 }}>{it?.client_name || "—"}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>
                  Pedido: {it?.tiny_order_number || "—"} | Status: {it?.tiny_status || "—"}
                </div>
              </div>
            )) : <div style={{ color: "var(--muted)" }}>Nenhum remoto isolado.</div>}
          </div>
        </section>
      </div>

      {errors.length ? (
        <section style={{ border: "1px solid var(--border)", background: "var(--panel)", padding: 14, marginTop: 16 }}>
          <div style={{ fontWeight: 900, marginBottom: 10 }}>Erros Tiny</div>
          <div style={{ display: "grid", gap: 8 }}>
            {errors.map((it, idx) => (
              <div key={idx} style={{ border: "1px solid var(--border)", padding: 10 }}>
                <div style={{ fontWeight: 800 }}>{it?.client_name || "—"}</div>
                <div style={{ fontSize: 12, color: "#fca5a5" }}>{it?.tiny_error || "—"}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
