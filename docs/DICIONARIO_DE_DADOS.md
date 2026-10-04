# Dicionário de dados — Mercatto Varejo

> **Aviso.** Este documento foi herdado das equipes de TI das duas empresas e
> está incompleto. Campos marcados com `?` não têm definição registrada; campos
> sem marcação têm definição registrada, o que não garante que ela esteja
> correta. Onde o dicionário falha, a definição precisa ser reconstruída a
> partir do próprio dado — e a reconstrução deve ir para o RDT.

## Contexto

A Mercatto Comércio S.A. operava uma rede de lojas físicas com um ERP próprio
desde 2016. Em março de 2024 adquiriu a Commerce Br, uma operação nativamente
digital, e desde então mantém os dois sistemas rodando em paralelo. Há clientes
que compram nos dois. A diretoria quer um repositório único para responder,
entre outras coisas, quem tende a comprar de novo nos próximos três meses.

---

## Fonte 1 — MySQL · `loja_legado` (ERP Mercatto)

Charset da base: `latin1`. Sem integridade referencial declarada.

### `CLIENTES`

| Campo | Tipo | Definição registrada |
|---|---|---|
| `ID_CLIENTE` | INT | Identificador interno do ERP. |
| `NOME` | VARCHAR(160) | Nome do cliente. Gravado em caixa alta pela tela de cadastro. |
| `CPF` | VARCHAR(14) | ? Formato não padronizado entre versões do sistema. |
| `EMAIL` | VARCHAR(160) | Contato principal. |
| `DT_CADASTRO` | DATE | Data do primeiro cadastro. |
| `CIDADE` | VARCHAR(80) | ? Campo de digitação livre. |
| `UF` | CHAR(2) | Unidade federativa. |
| `TELEFONE` | VARCHAR(30) | Contato. |

### `PRODUTOS`

| Campo | Tipo | Definição registrada |
|---|---|---|
| `ID_PRODUTO` | INT | Identificador interno. |
| `DESCRICAO` | VARCHAR(200) | Descrição comercial. |
| `CATEGORIA` | VARCHAR(80) | ? Digitação livre; nunca houve lista controlada. |
| `PRECO_TABELA` | DECIMAL(10,2) | Preço de tabela vigente. |
| `ATIVO` | CHAR(1) | `S` ativo, `N` inativo. |

### `PEDIDOS`

| Campo | Tipo | Definição registrada |
|---|---|---|
| `ID_PEDIDO` | INT | Identificador do pedido. |
| `ID_CLIENTE` | INT | Referência a `CLIENTES`. Sem FK. |
| `DT_PEDIDO` | DATETIME | Data e hora do fechamento do pedido. Sem fuso. |
| `DT_ENTREGA` | DATETIME | ? Preenchido pela logística. |
| `STATUS` | VARCHAR(20) | `ENTREGUE`, `CANCELADO`, `EM TRANSITO`, `SEPARACAO`. |
| `VALOR_TOTAL` | DECIMAL(10,2) | ? "Valor do pedido". |
| `VALOR_FRETE` | DECIMAL(10,2) | Valor do frete. |
| `CANAL` | VARCHAR(20) | `LOJA`, `TELEVENDAS`, `SITE`. |

> Observação deixada por um analista em 2021, sem contexto:
> *"cuidado com o VALOR_TOTAL, não é o que parece"*.

### `ITENS_PEDIDO`

| Campo | Tipo | Definição registrada |
|---|---|---|
| `ID_ITEM` | INT | Identificador da linha. |
| `ID_PEDIDO` | INT | Referência a `PEDIDOS`. Sem FK. |
| `ID_PRODUTO` | INT | Referência a `PRODUTOS`. Sem FK. |
| `QTD` | INT | Quantidade. |
| `VL_UNITARIO` | DECIMAL(10,2) | Preço praticado na venda. |
| `VL_DESCONTO` | DECIMAL(10,2) | ? Desconto da linha. |

---

## Fonte 2 — PostgreSQL · `shop` (Commerce Br)

Encoding `UTF-8`. Taxonomia de categorias controlada em `category`.

| Tabela | Campo | Definição registrada |
|---|---|---|
| `customer` | `customer_id` | Identificador da plataforma. |
| | `tax_id` | CPF, somente dígitos, sem máscara. Opcional no cadastro. |
| | `created_at` | `TIMESTAMPTZ` do cadastro. |
| `category` | `category_id`, `name`, `parent_id` | Taxonomia de dois níveis. `parent_id` nulo = nó raiz. |
| `product` | `sku` | Código único no formato `SKU-<n>`. |
| | `list_price` | Preço de tabela. |
| `orders` | `status` | `delivered`, `canceled`, `payment_declined`, `shipped`, `processing`. |
| | `total_amount` | Valor do pedido. |
| | `freight_amount` | Frete. |
| | `channel` | `web`, `app`, `marketplace`. |
| `order_item` | `discount` | Desconto aplicado na linha. |

> A definição de `total_amount` **não** está registrada. A equipe original da
> Commerce Br não trabalha mais na empresa.

---

## Fonte 3 — `atendimentos_sac.csv`

Exportação manual do sistema de atendimento, feita mensalmente e concatenada.

| Campo | Definição registrada |
|---|---|
| `protocolo` | Número do protocolo. |
| `origem_sistema` | `LEGADO` ou `ECOM`: a qual sistema pertence `id_pedido_origem`. |
| `id_pedido_origem` | Identificador do pedido **no sistema indicado na coluna anterior**. |
| `cpf_cliente` | ? Formato variável. |
| `data_abertura` | Data de abertura. |
| `data_fechamento` | ? |
| `canal` | Canal do atendimento. |
| `motivo` | ? Digitação livre do atendente. |
| `nota_satisfacao` | Pesquisa pós-atendimento, escala de 1 a 5. |
| `tempo_resolucao_horas` | ? Horas até a resolução. |

---

## Fonte 4 — `avaliacoes_marketplace.json`

Retorno da API de avaliações do marketplace, um objeto JSON por linha (NDJSON).

```json
{"review_id":"RV900001","order":{"ref":"ECOM-18442","channel":"marketplace"},
 "product":{"sku":"SKU-103871"},"submitted_at":"2024-08-19T14:03:11-03:00",
 "rating":4,"title":"Recomendo","verified_purchase":true,"helpful_votes":2}
```

| Caminho | Definição registrada |
|---|---|
| `review_id` | Identificador da avaliação. |
| `order.ref` | ? Referência ao pedido. |
| `product.sku` | ? Referência ao produto. |
| `submitted_at` | Momento do envio. |
| `rating` | ? Nota de 1 a 5. |
| `title`, `comment` | Campos textuais opcionais. |
| `verified_purchase` | Compra verificada pelo marketplace. |
| `helpful_votes` | Votos de utilidade. |

> A documentação da API menciona que "campos opcionais podem ser omitidos".
> Não diz quais são opcionais.
