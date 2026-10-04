-- ---------------------------------------------------------------------------
-- Repositório analítico "Mercatto DW"  ·  PostgreSQL 16 · UTF-8
--
-- Três camadas, com responsabilidades distintas (ver seção 2.3 do referencial):
--   stg  staging   — cópia fiel das origens, sem transformação semântica
--   dw   integrado — esquema estrela conformado, conservador, sem perda
--   abt  analítico — tabela-base de análise, específica de UMA pergunta
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS abt;
CREATE SCHEMA IF NOT EXISTS qa;   -- resultados das asserções de qualidade

-- ===========================================================================
-- CAMADA stg — vocês criam. Regra: nomes e tipos espelham a origem.
-- Nada de renomear, nada de converter significado. Só trazer.
-- ===========================================================================

-- ===========================================================================
-- CAMADA dw — esquema estrela
-- ===========================================================================
DROP TABLE IF EXISTS dw.fato_item_pedido CASCADE;
DROP TABLE IF EXISTS dw.fato_pedido      CASCADE;
DROP TABLE IF EXISTS dw.dim_cliente      CASCADE;
DROP TABLE IF EXISTS dw.dim_produto      CASCADE;
DROP TABLE IF EXISTS dw.dim_tempo        CASCADE;
DROP TABLE IF EXISTS dw.dim_canal        CASCADE;
DROP TABLE IF EXISTS dw.dim_status       CASCADE;

-- GRÃO: um cliente unificado. Um mesmo indivíduo presente nos dois sistemas
-- de origem deve ocupar UMA linha, com rastro de ambas as origens.
CREATE TABLE dw.dim_cliente (
  cliente_sk        BIGSERIAL PRIMARY KEY,
  cpf_normalizado   CHAR(11)     NULL,   -- apenas dígitos; NULL quando ausente
  cpf_valido        BOOLEAN      NULL,   -- dígito verificador confere?
  nome_padronizado  TEXT         NOT NULL,
  cidade            TEXT         NULL,
  uf                CHAR(2)      NULL,
  dt_primeiro_cadastro DATE      NULL,
  id_legado         INT          NULL,   -- rastro de procedência
  id_ecommerce      BIGINT       NULL,   -- rastro de procedência
  origem_unificacao TEXT         NOT NULL,  -- 'LEGADO' | 'ECOM' | 'AMBOS'
  regra_pareamento  TEXT         NULL,   -- qual regra uniu os registros
  CONSTRAINT ck_origem CHECK (origem_unificacao IN ('LEGADO','ECOM','AMBOS'))
);
CREATE INDEX ix_dim_cliente_cpf ON dw.dim_cliente (cpf_normalizado);

-- GRÃO: um produto conformado.
CREATE TABLE dw.dim_produto (
  produto_sk       BIGSERIAL PRIMARY KEY,
  sku              TEXT        NULL,
  descricao        TEXT        NOT NULL,
  categoria_nivel1 TEXT        NULL,   -- taxonomia conformada
  categoria_nivel2 TEXT        NULL,
  categoria_origem TEXT        NULL,   -- valor bruto, preservado
  preco_referencia NUMERIC(12,2) NULL,
  ativo            BOOLEAN     NULL,
  id_legado        INT         NULL,
  id_ecommerce     BIGINT      NULL,
  origem           TEXT        NOT NULL
);

CREATE TABLE dw.dim_tempo (
  data_sk        DATE PRIMARY KEY,
  ano            INT  NOT NULL,
  trimestre      INT  NOT NULL,
  mes            INT  NOT NULL,
  dia            INT  NOT NULL,
  dia_semana     INT  NOT NULL,
  nome_mes       TEXT NOT NULL,
  eh_fim_semana  BOOLEAN NOT NULL
);

CREATE TABLE dw.dim_canal (
  canal_sk     SERIAL PRIMARY KEY,
  canal_origem TEXT NOT NULL,   -- valor bruto: LOJA, web, app...
  canal_conformado TEXT NOT NULL, -- FISICO | ONLINE_PROPRIO | MARKETPLACE | TELEVENDAS
  sistema      TEXT NOT NULL
);

-- Esta dimensão materializa a AMBIGUIDADE 2 do enunciado.
-- 'cancelado_conformado' é a decisão de vocês; documentem-na no RDT.
CREATE TABLE dw.dim_status (
  status_sk            SERIAL PRIMARY KEY,
  status_origem        TEXT NOT NULL,
  sistema              TEXT NOT NULL,
  status_conformado    TEXT NOT NULL,
  motivo_cancelamento  TEXT NULL,   -- NULL quando a origem não distingue
  UNIQUE (status_origem, sistema)
);

-- GRÃO: UM PEDIDO. Declarem isto no relatório antes de escrever a carga.
CREATE TABLE dw.fato_pedido (
  pedido_sk        BIGSERIAL PRIMARY KEY,
  id_origem        TEXT   NOT NULL,   -- 'LEG-123' | 'ECOM-456'
  sistema_origem   TEXT   NOT NULL,
  cliente_sk       BIGINT NOT NULL REFERENCES dw.dim_cliente (cliente_sk),
  data_pedido_sk   DATE   NOT NULL REFERENCES dw.dim_tempo (data_sk),
  data_entrega_sk  DATE   NULL     REFERENCES dw.dim_tempo (data_sk),
  canal_sk         INT    NOT NULL REFERENCES dw.dim_canal (canal_sk),
  status_sk        INT    NOT NULL REFERENCES dw.dim_status (status_sk),
  qtd_itens        INT    NOT NULL,
  valor_mercadoria NUMERIC(12,2) NOT NULL,  -- SEM frete, conformado
  valor_frete      NUMERIC(12,2) NOT NULL,
  valor_desconto   NUMERIC(12,2) NOT NULL,
  valor_total      NUMERIC(12,2) NOT NULL,  -- mercadoria + frete - desconto
  dias_entrega     INT    NULL,
  UNIQUE (id_origem, sistema_origem)
);
CREATE INDEX ix_fato_pedido_cli  ON dw.fato_pedido (cliente_sk);
CREATE INDEX ix_fato_pedido_data ON dw.fato_pedido (data_pedido_sk);

-- GRÃO: UM ITEM DE UM PEDIDO.
CREATE TABLE dw.fato_item_pedido (
  item_sk     BIGSERIAL PRIMARY KEY,
  pedido_sk   BIGINT NOT NULL REFERENCES dw.fato_pedido (pedido_sk),
  produto_sk  BIGINT NOT NULL REFERENCES dw.dim_produto (produto_sk),
  quantidade  INT    NOT NULL,
  valor_unitario NUMERIC(12,2) NOT NULL,
  valor_desconto NUMERIC(12,2) NOT NULL,
  valor_linha    NUMERIC(12,2) NOT NULL
);

-- Ponte para o atendimento e a avaliação: grão de UM atendimento / UMA avaliação.
CREATE TABLE IF NOT EXISTS dw.fato_atendimento (
  atendimento_sk  BIGSERIAL PRIMARY KEY,
  protocolo       TEXT   NOT NULL UNIQUE,
  cliente_sk      BIGINT NULL REFERENCES dw.dim_cliente (cliente_sk),
  pedido_sk       BIGINT NULL REFERENCES dw.fato_pedido (pedido_sk),
  data_abertura_sk  DATE NOT NULL REFERENCES dw.dim_tempo (data_sk),
  data_fechamento_sk DATE NULL   REFERENCES dw.dim_tempo (data_sk),
  canal           TEXT   NULL,
  motivo_conformado TEXT NULL,
  nota_satisfacao INT    NULL,
  horas_resolucao NUMERIC(10,2) NULL
);

CREATE TABLE IF NOT EXISTS dw.fato_avaliacao (
  avaliacao_sk BIGSERIAL PRIMARY KEY,
  review_id    TEXT   NOT NULL UNIQUE,
  pedido_sk    BIGINT NULL REFERENCES dw.fato_pedido (pedido_sk),
  produto_sk   BIGINT NULL REFERENCES dw.dim_produto (produto_sk),
  data_sk      DATE   NOT NULL REFERENCES dw.dim_tempo (data_sk),
  nota         INT    NULL,
  compra_verificada BOOLEAN NULL,
  votos_uteis  INT    NULL
);

-- ===========================================================================
-- CAMADA abt — tabela-base de análise
--
-- PERGUNTA: dado o comportamento do cliente ATÉ a data de corte,
--           ele fará uma nova compra nos 90 dias seguintes?
--
--   data_corte        = 2025-06-30
--   janela do alvo    = 2025-07-01 .. 2025-09-28
--
-- CONTRATO OBRIGATÓRIO: as três colunas abaixo, com estes nomes e tipos.
-- As demais colunas (atributos preditivos) são projeto de vocês.
-- REGRA INEGOCIÁVEL: nenhum atributo pode usar dado posterior a data_corte.
-- ===========================================================================
DROP TABLE IF EXISTS abt.recompra_90d CASCADE;
CREATE TABLE abt.recompra_90d (
  cliente_sk          BIGINT  NOT NULL REFERENCES dw.dim_cliente (cliente_sk),
  data_corte          DATE    NOT NULL,
  alvo_recompra_90d   SMALLINT NOT NULL CHECK (alvo_recompra_90d IN (0,1)),
  -- ------------------------------------------------------------------
  -- A PARTIR DAQUI: atributos preditivos desenhados por vocês.
  -- Exemplos do que é legítimo (calculado somente até data_corte):
  --   recencia_dias, frequencia_pedidos, valor_monetario_total,
  --   ticket_medio, prazo_medio_entrega, qtd_atendimentos_sac,
  --   nota_media_avaliacoes, categorias_distintas, canal_predominante
  -- ------------------------------------------------------------------
  PRIMARY KEY (cliente_sk, data_corte)
);

-- ===========================================================================
-- CAMADA qa — registro das asserções de qualidade (princípio 6)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS qa.execucao_assercao (
  id           BIGSERIAL PRIMARY KEY,
  executado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  etapa        TEXT NOT NULL,
  nome         TEXT NOT NULL,
  descricao    TEXT NULL,
  valor_obtido NUMERIC NULL,
  valor_esperado TEXT NULL,
  aprovado     BOOLEAN NOT NULL
);
