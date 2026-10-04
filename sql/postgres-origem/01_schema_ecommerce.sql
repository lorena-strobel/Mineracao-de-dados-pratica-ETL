-- ---------------------------------------------------------------------------
-- Plataforma atual "Mercatto Commerce"
-- PostgreSQL 16 · UTF-8 · nomenclatura em inglês, taxonomia controlada
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS shop;
SET search_path TO shop, public;

DROP TABLE IF EXISTS order_item CASCADE;
DROP TABLE IF EXISTS orders     CASCADE;
DROP TABLE IF EXISTS product    CASCADE;
DROP TABLE IF EXISTS category   CASCADE;
DROP TABLE IF EXISTS customer   CASCADE;

CREATE TABLE category (
  category_id INT PRIMARY KEY,
  name        TEXT NOT NULL,
  parent_id   INT NULL REFERENCES category (category_id)
);

CREATE TABLE customer (
  customer_id BIGINT PRIMARY KEY,
  full_name   TEXT NOT NULL,
  tax_id      TEXT NULL,               -- CPF sem máscara, apenas dígitos
  email       TEXT NULL,
  created_at  TIMESTAMPTZ NULL,
  city        TEXT NULL,
  state       CHAR(2) NULL,
  phone       TEXT NULL
);

CREATE TABLE product (
  product_id  BIGINT PRIMARY KEY,
  sku         TEXT NOT NULL UNIQUE,
  title       TEXT NOT NULL,
  category_id INT NULL REFERENCES category (category_id),
  list_price  NUMERIC(12,2) NULL,
  active      BOOLEAN NULL
);

CREATE TABLE orders (
  order_id       BIGINT PRIMARY KEY,
  customer_id    BIGINT NULL REFERENCES customer (customer_id),
  placed_at      TIMESTAMPTZ NULL,
  delivered_at   TIMESTAMPTZ NULL,
  status         TEXT NULL,            -- delivered / canceled / payment_declined
                                       -- shipped / processing
  total_amount   NUMERIC(12,2) NULL,
  freight_amount NUMERIC(12,2) NULL,
  channel        TEXT NULL             -- web / app / marketplace
);

-- Sem FK para orders: a plataforma grava itens de forma assíncrona.
CREATE TABLE order_item (
  order_item_id BIGINT PRIMARY KEY,
  order_id      BIGINT NULL,
  product_id    BIGINT NULL,
  quantity      INT NULL,
  unit_price    NUMERIC(12,2) NULL,
  discount      NUMERIC(12,2) NULL
);

CREATE INDEX ix_orders_customer ON orders (customer_id);
CREATE INDEX ix_orders_placed   ON orders (placed_at);
CREATE INDEX ix_item_order      ON order_item (order_id);

-- Idempotente: o script pode ser reexecutado (docker compose run seed --forcar).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_ro') THEN
    CREATE ROLE etl_ro LOGIN PASSWORD 'etl_ro';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA shop TO etl_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA shop TO etl_ro;
