# -*- coding: utf-8 -*-
"""Conexões e parâmetros do laboratório. Não altere sem registrar no RDT."""

import os
from sqlalchemy import create_engine

DIR_DADOS = os.environ.get("DIR_DADOS", "/dados")
DIR_SAIDA = os.environ.get("DIR_SAIDA", "/saida")

# Origem 1 — MySQL legado. Atenção ao charset: a base é latin1.
MYSQL_DSN = os.environ.get(
    "MYSQL_DSN",
    "mysql+pymysql://etl_ro:etl_ro@mysql_legado:3306/loja_legado?charset=latin1")

# Origem 2 — PostgreSQL da plataforma de e-commerce (somente leitura).
PG_ORIGEM_DSN = os.environ.get(
    "PG_ORIGEM_DSN",
    "postgresql+psycopg2://etl_ro:etl_ro@pg_ecommerce:5432/ecommerce")

# Destino — PostgreSQL analítico (leitura e escrita).
PG_DW_DSN = os.environ.get(
    "PG_DW_DSN",
    "postgresql+psycopg2://postgres:postgres@pg_dw:5432/mercatto_dw")

# Origem 3 — CSV do SAC. latin-1, separador ';', decimal ',', data dd/mm/aaaa.
ARQ_SAC = os.path.join(DIR_DADOS, "atendimentos_sac.csv")

# Origem 4 — NDJSON de avaliações do marketplace. UTF-8, um objeto por linha.
ARQ_AVALIACOES = os.path.join(DIR_DADOS, "avaliacoes_marketplace.json")

# ---------------------------------------------------------------------------
# Parâmetros analíticos — fixados pelo enunciado. NÃO alterem.
# ---------------------------------------------------------------------------
DATA_CORTE = "2025-06-30"      # todo atributo preditivo usa dados ATÉ esta data
JANELA_ALVO_DIAS = 90          # alvo: houve nova compra em 90 dias após o corte?
DATA_FIM_ALVO = "2025-09-28"   # DATA_CORTE + 90 dias


def eng_mysql():
    return create_engine(MYSQL_DSN, pool_pre_ping=True)


def eng_origem():
    return create_engine(PG_ORIGEM_DSN, pool_pre_ping=True)


def eng_dw():
    return create_engine(PG_DW_DSN, pool_pre_ping=True)
