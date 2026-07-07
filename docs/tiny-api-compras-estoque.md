# Tiny ERP API — Compras, Estoque e Integrações

Referência extraída da API Tiny V2 e V3 com foco em **Compras (Pedidos de Compra)**, **Estoque**, **Atualização de Estoque** e **Fornecedores**.

> **Versão do documento:** 2026-06-10  
> **Versões da API cobertas:** Tiny API V2 (funcional, sem novas atualizações) e Tiny API V3 (atual, OAuth 2.0)

---

## Índice

1. [Visão Geral das APIs](#visão-geral-das-apis)
2. [Autenticação](#autenticação)
   - [API V2 — Token](#api-v2--token)
   - [API V3 — OAuth 2.0](#api-v3--oauth-20)
3. [Convenções da API V2](#convenções-da-api-v2)
4. [Compras — Pedidos de Compra (V2)](#compras--pedidos-de-compra-v2)
   - [Pesquisar Pedidos de Compra](#pesquisar-pedidos-de-compra)
   - [Obter Pedido de Compra](#obter-pedido-de-compra)
   - [Incluir Pedido de Compra](#incluir-pedido-de-compra)
5. [Estoque (V2)](#estoque-v2)
   - [Obter Estoque do Produto](#obter-estoque-do-produto)
   - [Atualizar Estoque do Produto](#atualizar-estoque-do-produto)
   - [Obter Atualizações de Estoque](#obter-atualizações-de-estoque)
6. [Fornecedores / Contatos (V2)](#fornecedores--contatos-v2)
   - [Pesquisar Contatos](#pesquisar-contatos)
   - [Obter Contato](#obter-contato)
7. [Notas Fiscais de Entrada (V2)](#notas-fiscais-de-entrada-v2)
   - [Pesquisar Notas Fiscais](#pesquisar-notas-fiscais)
   - [Obter Nota Fiscal](#obter-nota-fiscal)
8. [API V3 — Produtos e Estoque](#api-v3--produtos-e-estoque)
   - [Listar Produtos](#listar-produtos-v3)
   - [Obter Produto](#obter-produto-v3)
   - [Obter Estoque do Produto (V3)](#obter-estoque-do-produto-v3)
9. [Códigos de Situação de Pedido de Compra](#códigos-de-situação-de-pedido-de-compra)
10. [Tipos de Movimento de Estoque](#tipos-de-movimento-de-estoque)
11. [Tratamento de Erros](#tratamento-de-erros)
12. [Rate Limiting e Boas Práticas](#rate-limiting-e-boas-práticas)
13. [Mapeamento com o ERP Local](#mapeamento-com-o-erp-local)

---

## Visão Geral das APIs

| Versão | Base URL | Autenticação | Status |
|--------|----------|-------------|--------|
| V2 | `https://api.tiny.com.br/api2` | Token no body (`POST`) | Funcional, sem novas features |
| V3 | `https://api.tiny.com.br/public-api/v3` | Bearer Token (OAuth 2.0) | Ativa, novos recursos |

A API V2 usa **form-data POST** com token e dados no body. A API V3 usa **REST** com Bearer Token no header.

---

## Autenticação

### API V2 — Token

Todas as chamadas V2 são `POST` com `Content-Type: application/x-www-form-urlencoded`.

```
POST https://api.tiny.com.br/api2/{endpoint}.php
Content-Type: application/x-www-form-urlencoded

token=SEU_TOKEN_AQUI&formato=JSON&{outros_parametros}
```

**Parâmetros obrigatórios em toda chamada V2:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `token` | string | Token de acesso gerado em Configurações > Integrações no Tiny |
| `formato` | string | Sempre `JSON` |

**Token por empresa no ERP Local:**
- `TINY_TOKEN_PARTON` — Empresa Parton (Suprimentos)
- `TINY_TOKEN_PARK` — Empresa Park (Informática)

### API V3 — OAuth 2.0

A V3 usa Bearer Token obtido via OAuth 2.0 Authorization Code Flow.

```
GET https://api.tiny.com.br/public-api/v3/{resource}
Authorization: Bearer {access_token}
Accept: application/json
```

**Renovação automática:** o ERP local armazena o `refresh_token` na tabela `erp.companies` e renova automaticamente quando o `access_token` expira. Configuração via `POST /api/admin/v3-token`.

---

## Convenções da API V2

### Resposta padrão

```json
{
  "retorno": {
    "status_processamento": "3",
    "status": "OK",
    "pagina": 1,
    "numero_paginas": 5,
    "registros": 10,
    "{recurso}s": [
      { "{recurso}": { ...campos } }
    ]
  }
}
```

- `status: "OK"` → sucesso
- `status: "Erro"` → falha, ver campo `erros`
- `status_processamento: "3"` → com registros; `"0"` → sem registros

### Paginação

- Parâmetro de envio: `pagina` (inteiro, começa em 1)
- Resposta: `pagina`, `numero_paginas`, `registros`
- Itens por página: geralmente 100 (V2)

---

## Compras — Pedidos de Compra (V2)

### Pesquisar Pedidos de Compra

**Endpoint:** `POST {base_url}/pedidosCompra.pesquisa.php`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token de autenticação |
| `formato` | string | Sim | `JSON` |
| `pesquisa` | string | Não | Busca geral (nome do fornecedor, número) |
| `pagina` | int | Não | Página (padrão: 1) |
| `situacao` | string | Não | Ver [Códigos de Situação](#códigos-de-situação-de-pedido-de-compra) |
| `dataInicial` | string | Não | Data inicial `dd/mm/aaaa` |
| `dataFinal` | string | Não | Data final `dd/mm/aaaa` |
| `numero` | string | Não | Número do pedido de compra |
| `fornecedor` | string | Não | Nome ou CNPJ do fornecedor |
| `idFornecedor` | int | Não | ID do fornecedor no Tiny |
| `sort` | string | Não | Campo para ordenação (ex: `data_pedido`, `numero`) |

**Exemplo de requisição:**

```http
POST https://api.tiny.com.br/api2/pedidosCompra.pesquisa.php
Content-Type: application/x-www-form-urlencoded

token=abc123&formato=JSON&situacao=aberto&dataInicial=01/06/2026&dataFinal=10/06/2026&pagina=1
```

**Resposta de sucesso:**

```json
{
  "retorno": {
    "status_processamento": "3",
    "status": "OK",
    "pagina": 1,
    "numero_paginas": 2,
    "registros": 15,
    "pedidosCompra": [
      {
        "pedidoCompra": {
          "id": 12345,
          "numero": "PC-001",
          "data_pedido": "10/06/2026",
          "data_previsao": "20/06/2026",
          "situacao": "aberto",
          "fornecedor": {
            "id": 9876,
            "nome": "Fornecedor ABC Ltda",
            "cpf_cnpj": "12.345.678/0001-99"
          },
          "total_produtos": 1500.00,
          "total_pedido": 1500.00,
          "obs": "Pedido gerado via integração",
          "forma_pagamento": "30 dias"
        }
      }
    ]
  }
}
```

**Campos do objeto `pedidoCompra` (resumo na listagem):**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | int | ID único do pedido de compra |
| `numero` | string | Número do pedido (ex: PC-001) |
| `data_pedido` | string | Data do pedido `dd/mm/aaaa` |
| `data_previsao` | string | Data prevista de entrega `dd/mm/aaaa` |
| `data_chegada` | string | Data real de chegada (quando recebido) |
| `situacao` | string | Status atual (ver tabela de situações) |
| `fornecedor.id` | int | ID do fornecedor |
| `fornecedor.nome` | string | Nome/razão social do fornecedor |
| `fornecedor.cpf_cnpj` | string | CPF/CNPJ do fornecedor |
| `total_produtos` | float | Total dos produtos sem frete/impostos |
| `total_pedido` | float | Total geral do pedido |
| `obs` | string | Observações gerais |
| `forma_pagamento` | string | Condição de pagamento negociada |

---

### Obter Pedido de Compra

**Endpoint:** `POST {base_url}/pedidoCompra.obter.php`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token de autenticação |
| `formato` | string | Sim | `JSON` |
| `id` | int | Sim | ID do pedido de compra |

**Exemplo:**

```http
POST https://api.tiny.com.br/api2/pedidoCompra.obter.php
Content-Type: application/x-www-form-urlencoded

token=abc123&formato=JSON&id=12345
```

**Resposta de sucesso (objeto completo):**

```json
{
  "retorno": {
    "status": "OK",
    "pedidoCompra": {
      "id": 12345,
      "numero": "PC-001",
      "data_pedido": "10/06/2026",
      "data_previsao": "20/06/2026",
      "data_chegada": "",
      "situacao": "aberto",
      "fornecedor": {
        "id": 9876,
        "nome": "Fornecedor ABC Ltda",
        "cpf_cnpj": "12.345.678/0001-99",
        "fone": "(11) 99999-0000",
        "email": "compras@fornecedor.com.br"
      },
      "itens": [
        {
          "item": {
            "id": 1,
            "codigo": "SKU-001",
            "descricao": "Produto X",
            "unidade": "UN",
            "quantidade": 10,
            "valor_unitario": 50.00,
            "valor_total": 500.00,
            "id_produto": 98765
          }
        }
      ],
      "parcelas": [
        {
          "parcela": {
            "numero": 1,
            "data_vencimento": "10/07/2026",
            "valor": 1500.00,
            "forma_pagamento": "Boleto"
          }
        }
      ],
      "total_produtos": 1500.00,
      "desconto": 0.00,
      "frete": 0.00,
      "outras_despesas": 0.00,
      "total_pedido": 1500.00,
      "obs": "",
      "obs_interna": "",
      "forma_frete": "CIF",
      "nota_fiscal": {
        "numero": "1234",
        "chave_acesso": "43260601234567...",
        "data_emissao": "10/06/2026"
      }
    }
  }
}
```

**Campos adicionais no detalhe:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `itens[].item.id_produto` | int | ID do produto no Tiny |
| `itens[].item.codigo` | string | SKU/código do produto |
| `itens[].item.quantidade` | float | Quantidade solicitada |
| `itens[].item.valor_unitario` | float | Preço unitário negociado |
| `parcelas` | array | Condições de pagamento parcelado |
| `desconto` | float | Desconto em R$ |
| `frete` | float | Valor do frete |
| `nota_fiscal.chave_acesso` | string | Chave de acesso da NF-e vinculada |
| `forma_frete` | string | `CIF` (fornecedor paga) ou `FOB` (comprador paga) |

---

### Incluir Pedido de Compra

**Endpoint:** `POST {base_url}/pedidoCompra.incluir.php`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `pedido` | string (JSON) | Sim | JSON do pedido serializado |

**Estrutura do JSON `pedido`:**

```json
{
  "pedido": {
    "id_contato": 9876,
    "data_pedido": "10/06/2026",
    "data_previsao": "20/06/2026",
    "situacao": "aberto",
    "obs": "Pedido urgente",
    "forma_frete": "CIF",
    "itens": [
      {
        "item": {
          "id_produto": 98765,
          "codigo": "SKU-001",
          "descricao": "Produto X",
          "quantidade": 10,
          "valor_unitario": 50.00
        }
      }
    ],
    "parcelas": [
      {
        "parcela": {
          "data_vencimento": "10/07/2026",
          "valor": 500.00,
          "forma_pagamento": "Boleto"
        }
      }
    ]
  }
}
```

**Resposta de sucesso:**

```json
{
  "retorno": {
    "status": "OK",
    "id": 12346,
    "numero": "PC-002",
    "sequencia": "PC-002"
  }
}
```

---

## Estoque (V2)

### Obter Estoque do Produto

**Endpoint:** `POST {base_url}/produto.obter.estoque.php`

> Já implementado em `TinyClient.obter_estoque_produto(id_produto)`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `id` | int | Sim | ID do produto no Tiny |

**Exemplo:**

```http
POST https://api.tiny.com.br/api2/produto.obter.estoque.php
Content-Type: application/x-www-form-urlencoded

token=abc123&formato=JSON&id=98765
```

**Resposta:**

```json
{
  "retorno": {
    "status": "OK",
    "produto": {
      "id": 98765,
      "nome": "Produto X",
      "codigo": "SKU-001",
      "saldo": 150,
      "saldoFisico": 150,
      "saldoFisicoTotal": 150,
      "saldoReservado": 10,
      "saldoDisponivel": 140,
      "depositos": [
        {
          "deposito": {
            "id": 1,
            "nome": "Principal",
            "saldo": 100,
            "saldoFisico": 100,
            "saldoReservado": 5
          }
        },
        {
          "deposito": {
            "id": 2,
            "nome": "Filial",
            "saldo": 50,
            "saldoFisico": 50,
            "saldoReservado": 5
          }
        }
      ]
    }
  }
}
```

**Campos de saldo:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `saldo` | float | Saldo total (físico + virtual) |
| `saldoFisico` | float | Saldo físico disponível |
| `saldoFisicoTotal` | float | Saldo físico total (todos depósitos) |
| `saldoReservado` | float | Quantidade reservada para pedidos |
| `saldoDisponivel` | float | Saldo físico - Reservado |
| `depositos[].deposito.id` | int | ID do depósito |
| `depositos[].deposito.nome` | string | Nome do depósito |

---

### Atualizar Estoque do Produto

**Endpoint:** `POST {base_url}/produto.atualizar.estoque.php`

> ⚠️ **Atenção:** Esta operação **grava no Tiny**. Requer autorização explícita.

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `id` | int | Sim | ID do produto no Tiny |
| `tipo` | string | Sim | `E` = Entrada, `S` = Saída, `B` = Balanço (define valor absoluto) |
| `quantidade` | float | Sim | Quantidade do movimento |
| `preco` | float | Não | Preço de custo da entrada |
| `observacoes` | string | Não | Motivo/observação do ajuste |
| `idDeposito` | int | Não | ID do depósito (padrão: principal) |
| `idOrigem` | string | Não | Código de origem para rastreio |

**Tipos de operação:**

| Tipo | Descrição | Exemplo |
|------|-----------|---------|
| `E` | Entrada — soma ao saldo | Recebimento de mercadoria |
| `S` | Saída — subtrai do saldo | Consumo ou perda |
| `B` | Balanço — define saldo absoluto | Inventário físico |

**Exemplo de entrada:**

```http
POST https://api.tiny.com.br/api2/produto.atualizar.estoque.php
Content-Type: application/x-www-form-urlencoded

token=abc123&formato=JSON&id=98765&tipo=E&quantidade=50&preco=45.00&observacoes=Recebimento NF 1234&idOrigem=PC-001
```

**Resposta:**

```json
{
  "retorno": {
    "status": "OK",
    "registros": [
      {
        "registro": {
          "id": 9999,
          "sequencia": 1,
          "status": "OK"
        }
      }
    ]
  }
}
```

---

### Obter Atualizações de Estoque

**Endpoint:** `POST {base_url}/produto.atualizacoes.estoque.php`

Retorna um **histórico de movimentações de estoque** registradas no Tiny.

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `pagina` | int | Não | Página (padrão: 1) |
| `pesquisa` | string | Não | Busca por nome ou código do produto |
| `dataInicial` | string | Não | Data inicial `dd/mm/aaaa` |
| `dataFinal` | string | Não | Data final `dd/mm/aaaa` |
| `idProduto` | int | Não | Filtrar por ID de produto específico |

**Exemplo:**

```http
POST https://api.tiny.com.br/api2/produto.atualizacoes.estoque.php
Content-Type: application/x-www-form-urlencoded

token=abc123&formato=JSON&pagina=1&dataInicial=01/06/2026&dataFinal=10/06/2026
```

**Resposta:**

```json
{
  "retorno": {
    "status": "OK",
    "status_processamento": "3",
    "pagina": 1,
    "numero_paginas": 3,
    "registros": 50,
    "atualizacoes": [
      {
        "atualizacao": {
          "id": 55001,
          "id_produto": 98765,
          "codigo": "SKU-001",
          "nome": "Produto X",
          "tipo": "E",
          "quantidade": 50,
          "saldo_anterior": 100,
          "saldo_atual": 150,
          "preco_custo": 45.00,
          "data": "10/06/2026",
          "hora": "14:32:00",
          "observacoes": "Recebimento NF 1234",
          "id_origem": "PC-001",
          "tipo_origem": "Pedido de Compra",
          "usuario": "João Silva"
        }
      }
    ]
  }
}
```

**Campos da atualização:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | int | ID da movimentação |
| `id_produto` | int | ID do produto no Tiny |
| `codigo` | string | SKU/código do produto |
| `nome` | string | Nome do produto |
| `tipo` | string | `E` (entrada) ou `S` (saída) ou `B` (balanço) |
| `quantidade` | float | Quantidade movimentada |
| `saldo_anterior` | float | Saldo antes do movimento |
| `saldo_atual` | float | Saldo após o movimento |
| `preco_custo` | float | Preço de custo na entrada |
| `data` | string | Data da movimentação `dd/mm/aaaa` |
| `hora` | string | Hora da movimentação `HH:MM:SS` |
| `observacoes` | string | Observações/motivo |
| `id_origem` | string | Código de origem (ex: número do pedido de compra) |
| `tipo_origem` | string | Tipo da origem (ex: "Pedido de Compra", "Venda", "Manual") |
| `usuario` | string | Usuário que realizou o movimento |

---

## Fornecedores / Contatos (V2)

No Tiny, fornecedores e clientes são **Contatos** com o campo `tipo` diferenciando-os.

### Pesquisar Contatos

**Endpoint:** `POST {base_url}/contatos.pesquisa.php`

> Já implementado em `TinyClient.pesquisar_contatos()`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `pesquisa` | string | Não | Nome, razão social ou CNPJ |
| `pagina` | int | Não | Página |
| `cpf_cnpj` | string | Não | Filtrar por CPF/CNPJ exato |
| `situacao` | string | Não | `A` = ativo, `I` = inativo |
| `tipo` | string | Não | `F` = fornecedor, `C` = cliente, `A` = ambos |

**Exemplo (busca de fornecedores):**

```http
POST https://api.tiny.com.br/api2/contatos.pesquisa.php
Content-Type: application/x-www-form-urlencoded

token=abc123&formato=JSON&tipo=F&situacao=A&pesquisa=distribuidora&pagina=1
```

**Resposta:**

```json
{
  "retorno": {
    "status": "OK",
    "pagina": 1,
    "numero_paginas": 1,
    "registros": 3,
    "contatos": [
      {
        "contato": {
          "id": 9876,
          "codigo": "F-001",
          "nome": "Distribuidora XYZ Ltda",
          "fantasia": "Distribuidora XYZ",
          "tipo_pessoa": "J",
          "cpf_cnpj": "12.345.678/0001-99",
          "ie": "123456789",
          "fone": "(11) 99999-0000",
          "email": "comercial@xyz.com.br",
          "situacao": "A",
          "tipo": "F",
          "endereco": "Rua das Flores, 100",
          "cidade": "São Paulo",
          "uf": "SP",
          "cep": "01310-100"
        }
      }
    ]
  }
}
```

---

### Obter Contato

**Endpoint:** `POST {base_url}/contato.obter.php`

> Já implementado em `TinyClient.obter_contato(id_contato)`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `id` | int | Sim | ID do contato |

**Campos adicionais no detalhe:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `contato.categorias` | array | Categorias/tags do contato |
| `contato.contatos_adicionais` | array | Contatos extras (e-mail, telefone) |
| `contato.enderecos` | array | Endereços de entrega cadastrados |
| `contato.dados_adicionais` | object | Dados customizados |
| `contato.pix` | string | Chave Pix |

---

## Notas Fiscais de Entrada (V2)

Notas de entrada (NF-e de compra) são gerenciadas pelo módulo de Notas Fiscais com `tipo=E`.

### Pesquisar Notas Fiscais

**Endpoint:** `POST {base_url}/notas.fiscais.pesquisa.php`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `pesquisa` | string | Não | Número NF, CNPJ emitente ou chave de acesso |
| `pagina` | int | Não | Página |
| `situacao` | string | Não | `A` = autorizada, `C` = cancelada, `D` = denegada |
| `tipo` | string | Não | `E` = entrada, `S` = saída |
| `dataInicial` | string | Não | Data inicial emissão `dd/mm/aaaa` |
| `dataFinal` | string | Não | Data final emissão `dd/mm/aaaa` |

**Exemplo (NFs de entrada):**

```http
POST https://api.tiny.com.br/api2/notas.fiscais.pesquisa.php
Content-Type: application/x-www-form-urlencoded

token=abc123&formato=JSON&tipo=E&situacao=A&dataInicial=01/06/2026&dataFinal=10/06/2026
```

**Resposta:**

```json
{
  "retorno": {
    "status": "OK",
    "pagina": 1,
    "numero_paginas": 1,
    "registros": 4,
    "notas_fiscais": [
      {
        "nota_fiscal": {
          "id": 77001,
          "numero": "1234",
          "serie": "1",
          "tipo": "E",
          "situacao": "A",
          "data_emissao": "08/06/2026",
          "data_entrada": "10/06/2026",
          "id_contato": 9876,
          "nome_contato": "Distribuidora XYZ Ltda",
          "cpf_cnpj_contato": "12.345.678/0001-99",
          "valor_nota": 1500.00,
          "chave_acesso": "43260612345678000199550010000012341234567890",
          "natureza_operacao": "Compra de mercadoria para revenda",
          "tipo_frete": "0",
          "id_pedido_compra": 12345
        }
      }
    ]
  }
}
```

---

### Obter Nota Fiscal

**Endpoint:** `POST {base_url}/nota.fiscal.obter.php`

**Parâmetros:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `token` | string | Sim | Token |
| `formato` | string | Sim | `JSON` |
| `id` | int | Sim | ID da nota fiscal |

**Campos do detalhe:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `nota_fiscal.itens` | array | Itens da NF com produto, quantidade, valores |
| `nota_fiscal.impostos` | object | ICMS, IPI, PIS, COFINS, etc. |
| `nota_fiscal.transporte` | object | Transportadora e volumes |
| `nota_fiscal.informacoes_adicionais` | string | Informações complementares |
| `nota_fiscal.xml` | string | XML completo da NF-e (se solicitado) |

---

## API V3 — Produtos e Estoque

### Listar Produtos (V3)

**Endpoint:** `GET {base_url_v3}/produtos`

> Já implementado em `TinyV3Client.listar_produtos(params)`

**Query Params:**

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `pesquisa` | string | Busca geral |
| `codigo` | string | Busca por SKU/código exato |
| `situacao` | string | `A` = ativo, `I` = inativo |
| `pagina` | int | Página (padrão: 1) |
| `limit` | int | Registros por página (padrão: 20, máx: 100) |
| `offset` | int | Deslocamento para paginação |

**Resposta V3:**

```json
{
  "itens": [
    {
      "id": 98765,
      "codigo": "SKU-001",
      "nome": "Produto X",
      "situacao": "A",
      "preco": 89.90,
      "precoCusto": 45.00,
      "unidade": "UN",
      "estoqueAtual": 150,
      "estoqueMinimo": 10
    }
  ],
  "paginacao": {
    "pagina": 1,
    "totalRegistros": 250,
    "registrosPorPagina": 20
  }
}
```

---

### Obter Produto (V3)

**Endpoint:** `GET {base_url_v3}/produtos/{id}`

> Já implementado em `TinyV3Client.obter_produto(id_produto)`

**Campos adicionais no detalhe V3:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `dimensoes` | object | Altura, largura, comprimento, peso |
| `tributacao` | object | NCM, CEST, origem, ICMS, PIS, COFINS |
| `fornecedores` | array | Fornecedores cadastrados para o produto |
| `seo` | object | Slug, título e descrição para e-commerce |
| `variacoes` | array | Grade de variações (cor, tamanho, etc.) |
| `kit` | array | Itens se o produto é um kit |
| `producao` | object | Ficha técnica de produção |
| `anexos` | array | Imagens e arquivos anexados |

---

### Obter Estoque do Produto (V3)

**Endpoint:** `GET {base_url_v3}/estoque/{id_produto}`

> Já implementado em `TinyV3Client.obter_estoque_produto(id_produto)`

**Resposta V3:**

```json
{
  "id": 98765,
  "saldoFisicoTotal": 150,
  "saldoVirtualTotal": 150,
  "depositos": [
    {
      "id": 1,
      "nome": "Principal",
      "saldo": 100,
      "saldoFisico": 100,
      "saldoReservado": 5,
      "saldoVirtual": 95
    }
  ]
}
```

---

## Códigos de Situação de Pedido de Compra

| Código | Descrição |
|--------|-----------|
| `aberto` | Pedido em aberto, aguardando envio ao fornecedor |
| `aprovado` | Pedido aprovado internamente, enviado ao fornecedor |
| `em_andamento` | Pedido em andamento (parcialmente recebido) |
| `recebido` | Pedido totalmente recebido |
| `cancelado` | Pedido cancelado |
| `parcialmente_recebido` | Parte dos itens foi recebida |

---

## Tipos de Movimento de Estoque

| Código | Tipo | Efeito |
|--------|------|--------|
| `E` | Entrada | Soma ao saldo físico (recebimento, devolução de venda) |
| `S` | Saída | Subtrai do saldo físico (venda, perda, consumo) |
| `B` | Balanço | Define o saldo absoluto (inventário físico) |
| `T` | Transferência | Move entre depósitos |

---

## Tratamento de Erros

### Estrutura de erro V2

```json
{
  "retorno": {
    "status": "Erro",
    "erros": [
      {
        "erro": {
          "codigo": "30",
          "descricao": "Token inválido"
        }
      }
    ]
  }
}
```

### Códigos de erro comuns V2

| Código | Descrição |
|--------|-----------|
| `1` | Parâmetro obrigatório não informado |
| `2` | Parâmetro inválido |
| `10` | Token não informado |
| `30` | Token inválido ou expirado |
| `36` | API bloqueada — número máximo de requisições atingido |
| `40` | Registro não encontrado |
| `45` | Operação não permitida |

### Rate Limiting — Resposta HTTP 429

```json
{
  "retorno": {
    "status": "Erro",
    "erros": [{ "erro": "Excedido o número de acessos permitidos" }]
  }
}
```

Quando `status: "Erro"` e a mensagem contém `"API Bloqueada"` ou `"Excedido o número de acessos"`, o `TinyClient` faz **retry automático** com backoff exponencial.

---

## Rate Limiting e Boas Práticas

| Limite | Valor recomendado |
|--------|------------------|
| Requisições por minuto (V2) | ≤ 30 req/min por token |
| Sleep entre chamadas | 1.5s–3s (usar `sleep_ms` nos endpoints de importação) |
| Máximo de páginas por execução | 10 páginas por lote |
| Retry em 429 | Backoff exponencial (1.2x base, máximo 8 tentativas) |

**Configurações de retry no `TinyClient`:**
- `retry_attempts` = 3 (padrão), 8 (mínimo forçado pelo código)
- `retry_backoff_seconds` = 1.2s (base, dobra a cada tentativa)
- Mensagens `"API Bloqueada"` e `"Excedido o número de acessos"` ativam retry automático

---

## Mapeamento com o ERP Local

### Tabelas relevantes

| Tabela | Descrição | Chave de relação com Tiny |
|--------|-----------|--------------------------|
| `erp.products` | Produtos locais (local-first) | `tiny_product_id` = `produto.id` |
| `erp.product_stock_movements` | Movimentos de estoque locais | `reference_id` = número do pedido/NF Tiny |
| `erp.quotes` | Orçamentos/Pedidos de venda | `tiny_order_id` = `pedido.id` |
| `erp.stock_auto_control_config` | Config de controle automático | `company_key` por empresa |

### Endpoints locais relacionados

| Endpoint ERP Local | Descrição | Tiny correspondente |
|-------------------|-----------|-------------------|
| `GET /api/admin/products` | Lista produtos locais | V3 `GET /produtos` |
| `GET /api/admin/products/{id}/stock` | Estoque local do produto | V2 `produto.obter.estoque.php` |
| `POST /api/admin/products/{id}/stock/movements` | Movimento de estoque local | V2 `produto.atualizar.estoque.php` |
| `GET /api/admin/products/stock-movements` | Relatório de movimentos locais | V2 `produto.atualizacoes.estoque.php` |
| `GET /api/admin/compras` | Lista pedidos de compra do Tiny | V2 `pedidosCompra.pesquisa.php` |
| `GET /api/admin/compras/{id}` | Detalhe do pedido de compra | V2 `pedidoCompra.obter.php` |
| `GET /api/admin/estoque/atualizacoes` | Histórico de estoque do Tiny | V2 `produto.atualizacoes.estoque.php` |

### Fluxo de atualização de estoque via Compra

```
Pedido de Compra Tiny
       │
       ▼ (recebimento)
NF de Entrada vinculada ao Pedido
       │
       ▼ (via POST /api/admin/products/{id}/stock/movements)
erp.product_stock_movements (tipo: manual_entry, reference_type: 'compra_tiny')
       │
       ▼ (via UPDATE erp.products)
stock_physical / stock_available atualizados
       │
       ▼ (opcional: sincronizar de volta ao Tiny)
produto.atualizar.estoque.php (tipo: E)
```

### Mapeamento de campos Tiny → ERP Local

| Campo Tiny (V2) | Campo Tiny (V3) | Campo ERP Local |
|----------------|----------------|----------------|
| `produto.id` | `id` | `erp.products.tiny_product_id` |
| `produto.codigo` | `codigo` | `erp.products.sku` |
| `produto.nome` | `nome` | `erp.products.nome` |
| `produto.preco` | `preco` | `erp.products.preco_venda` |
| `produto.precoCusto` | `precoCusto` | `erp.products.preco_custo` |
| `estoque.saldoFisico` | `saldoFisicoTotal` | `erp.products.stock_physical` |
| `estoque.saldoReservado` | `saldoReservado` | `erp.products.stock_reserved` |

---

*Documentação gerada em 2026-06-10 com base na API Tiny V2/V3 e integração ERP Park.*
