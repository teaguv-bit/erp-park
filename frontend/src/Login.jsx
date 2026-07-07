import { useEffect, useState } from "react";
import { api } from "./api";
import { Button, Field } from "./ui";

export default function Login({ externalError = "", onLogin }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setErr(externalError || "");
  }, [externalError]);

  async function entrar(e) {
    e?.preventDefault?.();
    setErr("");
    setLoading(true);
    try {
      const data = await api.login(login, password);
      if (typeof onLogin === "function") {
        onLogin(data);
      }
    } catch (e) {
      setErr(e?.message || "Falha no login");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="loginWrap">
      <div className="loginPage">
        <form className="loginCard" onSubmit={entrar}>
          <div className="loginBrand">
            <img className="loginLogo" src="/logo.png" alt="Logo" />
            <div className="loginTitle">Acesso local</div>
          </div>

          <div className="loginSubtitle">Entre com login e senha do ERP.</div>

          <Field label="Login" id="loginInput">
            <input
              id="loginInput"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              autoComplete="username"
              className="loginInput"
              placeholder="Seu login"
            />
          </Field>

          <Field label="Senha" id="loginPassword">
            <input
              id="loginPassword"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              type="password"
              className="loginInput"
              placeholder="Sua senha"
            />
          </Field>

          <Button
            variant="primary"
            loading={loading}
            type="submit"
            style={{ width: "100%" }}
          >
            {loading ? "Entrando..." : "Entrar"}
          </Button>

          {err ? <div className="loginErr">{err}</div> : null}

          <div className="loginFoot">Acesso restrito | ERP local</div>
        </form>
      </div>
    </div>
  );
}
