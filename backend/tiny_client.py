import os
import time
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


class TinyAPIError(RuntimeError):
    pass


@dataclass
class TinyConfig:
    token: str
    base_url: str = "https://api.tiny.com.br/api2"
    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_backoff_seconds: float = 1.2


class TinyClient:
    def __init__(self, cfg: TinyConfig):
        if not cfg.token:
            raise ValueError("TinyConfig.token está vazio. Defina TINY_TOKEN.")
        self.cfg = cfg
        self.session = requests.Session()

    def _post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.cfg.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        payload: Dict[str, Any] = {"token": self.cfg.token, "formato": "JSON"}
        if data:
            payload.update(data)

        last_err: Optional[Exception] = None
        max_attempts = max(self.cfg.retry_attempts, 8)

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.post(url, data=payload, timeout=self.cfg.timeout_seconds)
                resp.raise_for_status()

                try:
                    parsed = resp.json()
                except Exception:
                    parsed = json.loads(resp.text)

                retorno = parsed.get("retorno", parsed)
                status = retorno.get("status")
                if status and str(status).upper() != "OK":
                    erros = retorno.get("erros") or retorno.get("erro") or retorno
                    erros_txt = json.dumps(erros, ensure_ascii=False)

                    if "API Bloqueada" in erros_txt or "Excedido o número de acessos" in erros_txt:
                        sleep_s = min(60.0, self.cfg.retry_backoff_seconds * (2 ** (attempt - 1)))
                        time.sleep(sleep_s)
                        continue

                    raise TinyAPIError(f"Tiny retornou status={status}. Detalhes: {erros}")

                return retorno

            except (requests.RequestException, TinyAPIError) as e:
                last_err = e
                if attempt < max_attempts:
                    time.sleep(self.cfg.retry_backoff_seconds * attempt)
                    continue
                raise TinyAPIError(f"Falha ao chamar Tiny endpoint={endpoint}: {e}") from e

        raise TinyAPIError(f"Falha inesperada: {last_err}")

    # ---------- Contatos ----------
    def pesquisar_contatos(
        self,
        pesquisa: str = "",
        pagina: int = 1,
        cpf_cnpj: str = "",
        id_vendedor: Optional[int] = None,
        nome_vendedor: str = "",
        situacao: str = "",
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"pesquisa": pesquisa, "pagina": int(pagina)}
        if cpf_cnpj:
            data["cpf_cnpj"] = str(cpf_cnpj)
        if id_vendedor is not None:
            data["idVendedor"] = int(id_vendedor)
        if nome_vendedor:
            data["nomeVendedor"] = str(nome_vendedor)
        if situacao:
            data["situacao"] = str(situacao)
        return self._post("contatos.pesquisa.php", data)

    def obter_contato(self, id_contato: int) -> Dict[str, Any]:
        return self._post("contato.obter.php", {"id": id_contato})

    # ---------- Produtos ----------
    def pesquisar_produtos(self, pesquisa: str = "", pagina: int = 1) -> Dict[str, Any]:
        return self._post("produtos.pesquisa.php", {"pesquisa": pesquisa, "pagina": pagina})

    def obter_produto(self, id_produto: int) -> Dict[str, Any]:
        return self._post("produto.obter.php", {"id": id_produto})

    def obter_estoque_produto(self, id_produto: int) -> Dict[str, Any]:
        return self._post("produto.obter.estoque.php", {"id": id_produto})

    # ---------- Vendedores ----------
    def pesquisar_vendedores(self, pesquisa: str = "", pagina: int = 1) -> Dict[str, Any]:
        return self._post("vendedores.pesquisa.php", {"pesquisa": pesquisa, "pagina": pagina})

    # ---------- Formas de Envio / Frete ----------
    def pesquisar_formas_envio(self, tipo_logistica: Optional[int] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if tipo_logistica is not None:
            data["tipoLogistica"] = int(tipo_logistica)
        return self._post("formas.envio.pesquisa.php", data)

    def obter_forma_envio(self, id_forma_envio: int) -> Dict[str, Any]:
        return self._post("formas.envio.obter.php", {"idFormaEnvio": int(id_forma_envio)})

    # ---------- Formas de Recebimento ----------
    def pesquisar_formas_recebimento(self) -> Dict[str, Any]:
        return self._post("formas.recebimento.pesquisa.php", {})

    # ---------- Contas a Receber ----------
    def pesquisar_contas_receber(
        self,
        numero_doc: str = "",
        nome_cliente: str = "",
        data_ini_vencimento: str = "",
        data_fim_vencimento: str = "",
        situacao: str = "",
        id_origem: str = "",
        pagina: int = 1,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"pagina": int(pagina)}
        if numero_doc:
            data["numero_doc"] = str(numero_doc)
        if nome_cliente:
            data["nome_cliente"] = str(nome_cliente)
        if data_ini_vencimento:
            data["data_ini_vencimento"] = str(data_ini_vencimento)
        if data_fim_vencimento:
            data["data_fim_vencimento"] = str(data_fim_vencimento)
        if situacao:
            data["situacao"] = str(situacao)
        if id_origem:
            data["id_origem"] = str(id_origem)
        return self._post("contas.receber.pesquisa.php", data)

    def obter_conta_receber(self, id_conta: int) -> Dict[str, Any]:
        return self._post("conta.receber.obter.php", {"id": int(id_conta)})

    # ---------- Pedidos de Compra ----------
    def pesquisar_pedidos_compra(
        self,
        pesquisa: str = "",
        pagina: int = 1,
        situacao: str = "",
        data_inicial: str = "",
        data_final: str = "",
        numero: str = "",
        fornecedor: str = "",
        id_fornecedor: Optional[int] = None,
        sort: str = "",
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"pagina": int(pagina)}
        if pesquisa:
            data["pesquisa"] = str(pesquisa)
        if situacao:
            data["situacao"] = str(situacao)
        if data_inicial:
            data["dataInicial"] = str(data_inicial)
        if data_final:
            data["dataFinal"] = str(data_final)
        if numero:
            data["numero"] = str(numero)
        if fornecedor:
            data["fornecedor"] = str(fornecedor)
        if id_fornecedor is not None:
            data["idFornecedor"] = int(id_fornecedor)
        if sort:
            data["sort"] = str(sort)
        return self._post("pedidosCompra.pesquisa.php", data)

    def obter_pedido_compra(self, id_pedido: int) -> Dict[str, Any]:
        return self._post("pedidoCompra.obter.php", {"id": int(id_pedido)})

    # ---------- Estoque (movimentos) ----------
    def pesquisar_atualizacoes_estoque(
        self,
        pesquisa: str = "",
        pagina: int = 1,
        data_inicial: str = "",
        data_final: str = "",
        id_produto: Optional[int] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"pagina": int(pagina)}
        if pesquisa:
            data["pesquisa"] = str(pesquisa)
        if data_inicial:
            data["dataInicial"] = str(data_inicial)
        if data_final:
            data["dataFinal"] = str(data_final)
        if id_produto is not None:
            data["idProduto"] = int(id_produto)
        return self._post("produto.atualizacoes.estoque.php", data)

    def pesquisar_fornecedores(self, pesquisa: str = "", pagina: int = 1) -> Dict[str, Any]:
        return self._post("contatos.pesquisa.php", {"pesquisa": pesquisa, "pagina": int(pagina), "tipo": "F"})

    # ---------- Pedidos ----------
    def criar_pedido(self, pedido_payload: Dict[str, Any]) -> Dict[str, Any]:
        pedido = (pedido_payload or {}).get("pedido") or {}
        pedido_json = json.dumps({"pedido": pedido}, ensure_ascii=False)
        return self._post("pedido.incluir.php", {"pedido": pedido_json})

    def pesquisar_pedidos(
        self,
        pesquisa: str = "",
        pagina: int = 1,
        numero: str = "",
        cliente: str = "",
        cpf_cnpj: str = "",
        situacao: str = "",
        data_inicial: str = "",
        data_final: str = "",
        data_atualizacao: str = "",
        numero_ecommerce: str = "",
        id_vendedor: str = "",
        nome_vendedor: str = "",
        marcador: str = "",
        data_inicial_ocorrencia: str = "",
        data_final_ocorrencia: str = "",
        situacao_ocorrencia: str = "",
        sort: str = "",
        dataInicial: str = "",
        dataFinal: str = "") -> Dict[str, Any]:
        data: Dict[str, Any] = {"pagina": int(pagina)}
        if pesquisa:
            data["pesquisa"] = str(pesquisa)
        if numero:
            data["numero"] = str(numero)
        if cliente:
            data["cliente"] = str(cliente)
        if cpf_cnpj:
            data["cpf_cnpj"] = str(cpf_cnpj)
        if situacao:
            data["situacao"] = str(situacao)
        if data_inicial:
            data["dataInicial"] = str(data_inicial)
        if data_final:
            data["dataFinal"] = str(data_final)
        if data_atualizacao:
            data["dataAtualizacao"] = str(data_atualizacao)
        if numero_ecommerce:
            data["numeroEcommerce"] = str(numero_ecommerce)
        if id_vendedor:
            data["idVendedor"] = str(id_vendedor)
        if nome_vendedor:
            data["nomeVendedor"] = str(nome_vendedor)
        if marcador:
            data["marcador"] = str(marcador)
        if data_inicial_ocorrencia:
            data["dataInicialOcorrencia"] = str(data_inicial_ocorrencia)
        if data_final_ocorrencia:
            data["dataFinalOcorrencia"] = str(data_final_ocorrencia)
        if situacao_ocorrencia:
            data["situacaoOcorrencia"] = str(situacao_ocorrencia)
        if sort:
            data["sort"] = str(sort)
        return self._post("pedidos.pesquisa.php", data)

    def obter_pedido(self, id_pedido: int) -> Dict[str, Any]:
        return self._post("pedido.obter.php", {"id": int(id_pedido)})

    def alterar_situacao_pedido(self, id_pedido: int, situacao: str) -> Dict[str, Any]:
        return self._post(
            "pedido.alterar.situacao.php",
            {
                "id": int(id_pedido),
                "situacao": str(situacao),
            },
        )

    def aprovar_pedido(self, id_pedido: int) -> Dict[str, Any]:
        return self.alterar_situacao_pedido(id_pedido, "aprovado")

    def cancelar_pedido(self, id_pedido: int) -> Dict[str, Any]:
        return self.alterar_situacao_pedido(id_pedido, "cancelado")

    def faturar_pedido(self, id_pedido: int) -> Dict[str, Any]:
        return self.alterar_situacao_pedido(id_pedido, "faturado")


def load_config_from_env() -> TinyConfig:
    token = os.getenv("TINY_TOKEN", "").strip()
    base_url = os.getenv("TINY_BASE_URL", "https://api.tiny.com.br/api2").strip()
    timeout = int(os.getenv("TINY_TIMEOUT_SECONDS", "30"))
    return TinyConfig(
        token=token,
        base_url=base_url,
        timeout_seconds=timeout,
    )


# ---------- Tiny/Olist API V3 ----------
@dataclass
class TinyV3Config:
    access_token: str
    base_url: str = "https://api.tiny.com.br/public-api/v3"
    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_backoff_seconds: float = 1.2


class TinyV3Client:
    def __init__(self, cfg: TinyV3Config):
        if not cfg.access_token:
            raise ValueError("TinyV3Config.access_token está vazio.")
        self.cfg = cfg
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.cfg.base_url.rstrip('/')}/{path.lstrip('/')}"
        last_err: Optional[Exception] = None

        for attempt in range(1, max(1, self.cfg.retry_attempts) + 1):
            try:
                resp = self.session.request(
                    method.upper(),
                    url,
                    headers=self._headers(),
                    params=params or None,
                    json=json_body if json_body is not None else None,
                    timeout=self.cfg.timeout_seconds,
                )

                text = resp.text or ""

                if resp.status_code == 204:
                    return {"ok": True, "status_code": resp.status_code, "data": None}

                try:
                    data = resp.json()
                except Exception:
                    data = {"raw_text": text[:4000]}

                if resp.status_code >= 400:
                    raise TinyAPIError(
                        f"Tiny V3 retornou HTTP {resp.status_code} em {method.upper()} {path}: "
                        f"{json.dumps(data, ensure_ascii=False)[:2000]}"
                    )

                return {"ok": True, "status_code": resp.status_code, "data": data}

            except (requests.RequestException, TinyAPIError) as e:
                last_err = e
                if attempt < max(1, self.cfg.retry_attempts):
                    time.sleep(self.cfg.retry_backoff_seconds * attempt)
                    continue
                raise TinyAPIError(f"Falha ao chamar Tiny V3 path={path}: {e}") from e

        raise TinyAPIError(f"Falha inesperada Tiny V3: {last_err}")

    def criar_contato(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "contatos", json_body=payload)

    def atualizar_contato(self, id_contato: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PUT", f"contatos/{int(id_contato)}", json_body=payload)

    def listar_produtos(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", "produtos", params=params or {})

    def obter_produto(self, id_produto: int) -> Dict[str, Any]:
        return self._request("GET", f"produtos/{int(id_produto)}")

    def obter_estoque_produto(self, id_produto: int) -> Dict[str, Any]:
        path_template = os.getenv("TINY_V3_STOCK_PATH_TEMPLATE", "estoque/{id_produto}").strip()
        path = path_template.format(id_produto=int(id_produto), id=int(id_produto))
        return self._request("GET", path)

    def obter_pedido(self, id_pedido: int) -> Dict[str, Any]:
        return self._request("GET", f"pedidos/{int(id_pedido)}")

    def listar_pedidos(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", "pedidos", params=params or {})

    def listar_separacoes(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", "separacao", params=params or {})

    def obter_separacao(self, id_separacao: int) -> Dict[str, Any]:
        return self._request("GET", f"separacao/{int(id_separacao)}")

    def alterar_situacao_separacao(self, id_separacao: int, situacao: int) -> Dict[str, Any]:
        return self._request(
            "PUT",
            f"separacao/{int(id_separacao)}/situacao",
            json_body={"situacao": int(situacao)},
        )


def load_v3_config_from_env(access_token: Optional[str] = None) -> TinyV3Config:
    token = (access_token or os.getenv("TINY_V3_ACCESS_TOKEN", "")).strip()
    base_url = os.getenv("TINY_V3_BASE_URL", "https://api.tiny.com.br/public-api/v3").strip()
    timeout = int(os.getenv("TINY_V3_TIMEOUT_SECONDS", "30"))
    return TinyV3Config(
        access_token=token,
        base_url=base_url,
        timeout_seconds=timeout,
    )
import unicodedata


def _tiny_normalize_text(value):
    text = "" if value is None else str(value)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").strip().lower()


def _tiny_extract_first_order(payload):
    if not isinstance(payload, dict):
        return None

    retorno = payload.get("retorno")
    if isinstance(retorno, dict):
        pedido = retorno.get("pedido")
        if isinstance(pedido, dict):
            return pedido

        pedidos = retorno.get("pedidos")
        if isinstance(pedidos, list):
            for item in pedidos:
                if isinstance(item, dict):
                    candidate = item.get("pedido") if isinstance(item.get("pedido"), dict) else item
                    if isinstance(candidate, dict):
                        return candidate

    pedido = payload.get("pedido")
    if isinstance(pedido, dict):
        return pedido

    pedidos = payload.get("pedidos")
    if isinstance(pedidos, list):
        for item in pedidos:
            if isinstance(item, dict):
                candidate = item.get("pedido") if isinstance(item.get("pedido"), dict) else item
                if isinstance(candidate, dict):
                    return candidate

    if any(key in payload for key in ("id", "situacao", "numero")):
        return payload

    return None


def _tiny_post_compat(self, endpoint, payload):
    if hasattr(self, "_post") and callable(getattr(self, "_post")):
        return self._post(endpoint, payload)
    if hasattr(self, "post") and callable(getattr(self, "post")):
        return self.post(endpoint, payload)
    raise TinyAPIError("Cliente Tiny sem método de postagem compatível.")


def buscar_pedido_por_numero(self, numero):
    numero_texto = "" if numero is None else str(numero).strip()
    if not numero_texto:
        raise TinyAPIError("Número do pedido Tiny vazio.")

    response = _tiny_post_compat(self, "pedidos.pesquisa.php", {"numero": numero_texto})
    pedido = _tiny_extract_first_order(response)
    if pedido is None:
        raise TinyAPIError("Pedido não localizado")
    return pedido


def _tiny_install_busca_numero_patch(attempt=0):
    if "TinyClient" in globals():
        try:
            if not hasattr(TinyClient, "buscar_pedido_por_numero"):
                TinyClient.buscar_pedido_por_numero = buscar_pedido_por_numero
            return
        except Exception:
            if attempt >= 5:
                return
    elif attempt >= 5:
        return

    import threading

    threading.Timer(0.25, lambda: _tiny_install_busca_numero_patch(attempt + 1)).start()


_tiny_install_busca_numero_patch()
