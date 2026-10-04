-- ---------------------------------------------------------------------------
-- Sistema legado "Mercatto ERP" (empresa adquirida em 2024)
-- MySQL 8 · charset latin1 · nomenclatura em português, caixa alta
-- ---------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS loja_legado
  CHARACTER SET latin1 COLLATE latin1_swedish_ci;

USE loja_legado;

DROP TABLE IF EXISTS ITENS_PEDIDO;
DROP TABLE IF EXISTS PEDIDOS;
DROP TABLE IF EXISTS PRODUTOS;
DROP TABLE IF EXISTS CLIENTES;

CREATE TABLE CLIENTES (
  ID_CLIENTE  INT          NOT NULL PRIMARY KEY,
  NOME        VARCHAR(160) NOT NULL,
  CPF         VARCHAR(14)  NULL,
  EMAIL       VARCHAR(160) NULL,
  DT_CADASTRO DATE         NULL,
  CIDADE      VARCHAR(80)  NULL,
  UF          CHAR(2)      NULL,
  TELEFONE    VARCHAR(30)  NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

CREATE TABLE PRODUTOS (
  ID_PRODUTO   INT           NOT NULL PRIMARY KEY,
  DESCRICAO    VARCHAR(200)  NOT NULL,
  CATEGORIA    VARCHAR(80)   NULL,   -- texto livre, sem taxonomia
  PRECO_TABELA DECIMAL(10,2) NULL,
  ATIVO        CHAR(1)       NULL    -- 'S' / 'N'
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Sem chave estrangeira: o sistema de origem nunca teve integridade referencial.
CREATE TABLE PEDIDOS (
  ID_PEDIDO   INT           NOT NULL PRIMARY KEY,
  ID_CLIENTE  INT           NULL,
  DT_PEDIDO   DATETIME      NULL,
  DT_ENTREGA  DATETIME      NULL,
  STATUS      VARCHAR(20)   NULL,    -- ENTREGUE / CANCELADO / EM TRANSITO / SEPARACAO
  VALOR_TOTAL DECIMAL(10,2) NULL,
  VALOR_FRETE DECIMAL(10,2) NULL,
  CANAL       VARCHAR(20)   NULL     -- LOJA / TELEVENDAS / SITE
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

CREATE TABLE ITENS_PEDIDO (
  ID_ITEM      INT           NOT NULL PRIMARY KEY,
  ID_PEDIDO    INT           NULL,
  ID_PRODUTO   INT           NULL,
  QTD          INT           NULL,
  VL_UNITARIO  DECIMAL(10,2) NULL,
  VL_DESCONTO  DECIMAL(10,2) NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

CREATE INDEX IX_PEDIDOS_CLIENTE ON PEDIDOS (ID_CLIENTE);
CREATE INDEX IX_PEDIDOS_DATA    ON PEDIDOS (DT_PEDIDO);
CREATE INDEX IX_ITENS_PEDIDO    ON ITENS_PEDIDO (ID_PEDIDO);

-- Usuário somente-leitura para o pipeline dos estudantes.
CREATE USER IF NOT EXISTS 'etl_ro'@'%' IDENTIFIED BY 'etl_ro';
GRANT SELECT ON loja_legado.* TO 'etl_ro'@'%';
FLUSH PRIVILEGES;
