#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cria os esquemas das origens e carrega os CSVs gerados.
Executado UMA vez pelo serviço `seed` do docker compose.
"""

import os
import sys
import time

import pymysql
import psycopg2

DIR = os.environ.get("DIR_DADOS", "/dados")
CARGA = os.path.join(DIR, "_carga")
SQL = os.environ.get("DIR_SQL", "/sql")

MYSQL = dict(host=os.environ.get("MYSQL_HOST", "mysql_legado"),
             port=int(os.environ.get("MYSQL_PORT", 3306)),
             user=os.environ.get("MYSQL_USER", "root"),
             password=os.environ.get("MYSQL_PASSWORD", "root"),
             charset="latin1", local_infile=True, autocommit=True)

PG_ORIGEM = os.environ.get(
    "PG_ORIGEM_DSN",
    "host=pg_ecommerce port=5432 dbname=ecommerce user=postgres password=postgres")
PG_DW = os.environ.get(
    "PG_DW_DSN",
    "host=pg_dw port=5432 dbname=mercatto_dw user=postgres password=postgres")


def log(m):
    print(f"[carga] {m}", flush=True)


def espera(fn, nome, tentativas=60):
    for i in range(tentativas):
        try:
            fn()
            log(f"{nome} disponível")
            return
        except Exception as e:                       # noqa: BLE001
            if i == tentativas - 1:
                log(f"{nome} indisponível: {e}")
                raise
            time.sleep(2)


def executa_script(cur, caminho, separador=";"):
    with open(caminho, encoding="utf-8") as f:
        sql = f.read()
    # remove comentários de linha inteira antes de dividir
    linhas = [l for l in sql.splitlines() if not l.strip().startswith("--")]
    for cmd in "\n".join(linhas).split(separador):
        if cmd.strip():
            cur.execute(cmd)


# ---------------------------------------------------------------------------
# MySQL — sistema legado
# ---------------------------------------------------------------------------
def carrega_mysql():
    espera(lambda: pymysql.connect(**MYSQL).close(), "MySQL")
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor()
    log("criando esquema loja_legado...")
    executa_script(cur, os.path.join(SQL, "mysql", "01_schema_legado.sql"))
    cur.execute("USE loja_legado")

    tabelas = [
        ("CLIENTES", "legado_clientes.csv",
         "(ID_CLIENTE, NOME, CPF, EMAIL, @dt, CIDADE, UF, TELEFONE)",
         "SET DT_CADASTRO = NULLIF(@dt,'')"),
        ("PRODUTOS", "legado_produtos.csv",
         "(ID_PRODUTO, DESCRICAO, CATEGORIA, @pr, ATIVO)",
         "SET PRECO_TABELA = NULLIF(@pr,'')"),
        ("PEDIDOS", "legado_pedidos.csv",
         "(ID_PEDIDO, ID_CLIENTE, @dp, @de, STATUS, VALOR_TOTAL, VALOR_FRETE, CANAL)",
         "SET DT_PEDIDO = NULLIF(@dp,''), DT_ENTREGA = NULLIF(@de,'')"),
        ("ITENS_PEDIDO", "legado_itens.csv",
         "(ID_ITEM, ID_PEDIDO, ID_PRODUTO, QTD, VL_UNITARIO, VL_DESCONTO)", ""),
    ]
    for tabela, arquivo, colunas, setcl in tabelas:
        caminho = os.path.join(CARGA, arquivo)
        log(f"  LOAD DATA -> {tabela}")
        cur.execute(f"""
            LOAD DATA LOCAL INFILE '{caminho}'
            INTO TABLE {tabela}
            CHARACTER SET latin1
            FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
            LINES TERMINATED BY '\\n'
            IGNORE 1 LINES
            {colunas}
            {setcl}
        """)
        cur.execute(f"SELECT COUNT(*) FROM {tabela}")
        log(f"     {cur.fetchone()[0]} linhas")
    conn.close()


# ---------------------------------------------------------------------------
# PostgreSQL — plataforma de e-commerce
# ---------------------------------------------------------------------------
def carrega_pg_origem():
    espera(lambda: psycopg2.connect(PG_ORIGEM).close(), "PostgreSQL (origem)")
    conn = psycopg2.connect(PG_ORIGEM)
    conn.autocommit = True
    cur = conn.cursor()
    log("criando esquema shop...")
    with open(os.path.join(SQL, "postgres-origem", "01_schema_ecommerce.sql"),
              encoding="utf-8") as f:
        cur.execute(f.read())    # o script é idempotente

    ordem = [
        ("shop.category", "ecom_category.csv"),
        ("shop.customer", "ecom_customer.csv"),
        ("shop.product", "ecom_product.csv"),
        ("shop.orders", "ecom_orders.csv"),
        ("shop.order_item", "ecom_order_item.csv"),
    ]
    for tabela, arquivo in ordem:
        log(f"  COPY -> {tabela}")
        with open(os.path.join(CARGA, arquivo), encoding="utf-8") as f:
            cur.copy_expert(
                f"COPY {tabela} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')", f)
        cur.execute(f"SELECT COUNT(*) FROM {tabela}")
        log(f"     {cur.fetchone()[0]} linhas")
    cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA shop TO etl_ro")
    conn.close()


# ---------------------------------------------------------------------------
# PostgreSQL — destino analítico
# ---------------------------------------------------------------------------
def prepara_dw():
    espera(lambda: psycopg2.connect(PG_DW).close(), "PostgreSQL (DW)")
    conn = psycopg2.connect(PG_DW)
    conn.autocommit = True
    cur = conn.cursor()
    log("criando esquemas stg/dw/abt/qa...")
    with open(os.path.join(SQL, "postgres-dw", "01_schema_dw.sql"), encoding="utf-8") as f:
        cur.execute(f.read())
    conn.close()


if __name__ == "__main__":
    marcador = os.path.join(DIR, "_carga_concluida.txt")
    if os.path.exists(marcador) and "--forcar" not in sys.argv:
        log("carga já realizada; nada a fazer (use --forcar para repetir)")
        sys.exit(0)
    carrega_mysql()
    carrega_pg_origem()
    prepara_dw()
    with open(marcador, "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    log("ambiente pronto.")
