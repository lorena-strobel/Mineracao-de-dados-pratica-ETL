#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 1 — EXTRAÇÃO  (esqueleto: vocês completam)

Objetivo: trazer as quatro fontes para o esquema `stg` do DW, SEM transformar
significado. Renomear, converter tipo e decidir o que é nulo vem depois.

Regra da camada stg (seção 2.3 do referencial):
  · nomes de coluna espelham a origem;
  · nenhum valor é descartado, corrigido ou reinterpretado;
  · acrescente apenas metadados de procedência:
        _fonte           de onde veio
        _extraido_em     quando
        _linha_origem    posição na origem, quando fizer sentido

Decisão obrigatória a registrar no RDT antes de codificar:
  carga completa ou incremental? Justifique com base no que as origens oferecem.

    docker compose exec etl python 01_extracao.py
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from config import (ARQ_AVALIACOES, ARQ_SAC, eng_dw, eng_mysql, eng_origem)
from qualidade.assercoes import Suite

AGORA = datetime.now(timezone.utc)
LOTE = 50_000          # leia em blocos: a base não cabe confortavelmente na RAM


def grava_stg(df, tabela, engine, primeiro_bloco):
    df["_fonte"] = tabela.split("_")[0]
    df["_extraido_em"] = AGORA
    df.to_sql(tabela, engine, schema="stg",
              if_exists="replace" if primeiro_bloco else "append",
              index=False, method="multi", chunksize=5_000)


def extrai_mysql(qa):
    eng, dw = eng_mysql(), eng_dw()
    # TODO 1.1 — para cada tabela do legado, leia em blocos de LOTE linhas
    #            e grave em stg.legado_<tabela>.
    #            Cuidado: a conexão já vem com charset=latin1 (ver config.py).
    #            Confira se os acentos chegam corretos; se não chegarem,
    #            o problema está na sua leitura, não no dado.
    tabelas = ["CLIENTES", "PEDIDOS", "ITENS_PEDIDO", "PRODUTOS"]

    for tab in tabelas:
        primeiro_bloco = True
        query = f"SELECT * FROM {tab}"
        for df_chunk in pd.read_sql(query, eng, chunksize=LOTE):
            grava_stg(df_chunk, f"legado_{tab.lower()}", dw, primeiro_bloco)
            primeiro_bloco = False


def extrai_postgres(qa):
    # TODO 1.2 — mesma ideia para shop.customer / product / orders / order_item.
    #            Atenção: placed_at e delivered_at são TIMESTAMPTZ.
    #            Em qual fuso você vai padronizar? Registre a decisão.
    eng, dw = eng_origem(), eng_dw()

    tabelas = ["category", "customer", "orders", "order_item", "product"]

    for tab in tabelas:
        primeiro_bloco = True
        # As colunas de data/hora (created_at, placed_at, delivered_at)
        # são nativamente de timestampz preservando o fuso e o timestamp em UTC
        # logo o SELECT é realizado diretamente para preservar o significado do STG
        query = f"SELECT * FROM shop.{tab}"
        for df_chunk in pd.read_sql(query, eng, chunksize=LOTE):
            grava_stg(df_chunk, f"ecommerce_{tab}", dw, primeiro_bloco)
            primeiro_bloco = False


def extrai_sac(qa):
    # TODO 1.3 — leia o CSV do SAC.
    #   · encoding e separador: descubra no perfilamento, não chute;
    #   · leia TUDO como texto (dtype=str) — conversão é transformação;
    #   · o arquivo tem campos com quebra de linha interna: o parser do pandas
    #     resolve isso sozinho SE você não tentar ler o arquivo linha a linha.
    dw = eng_dw()
    primeiro_bloco = True

    for df_chunk in pd.read_csv(ARQ_SAC, sep=';', encoding='latin1', dtype=str, chunksize=LOTE):
        grava_stg(df_chunk, "sac_atendimentos", dw, primeiro_bloco)
        primeiro_bloco = False


def extrai_avaliacoes(qa):
    # TODO 1.4 — leia o NDJSON.
    #   · o esquema é irregular: chaves faltando NÃO são o mesmo que nulas;
    #   · preserve o aninhamento em colunas explícitas (order_ref, product_sku);
    #   · rating vem ora como número, ora como texto: na stg, guarde como texto.
    dw = eng_dw()
    primeiro_bloco = True

    for chunk in pd.read_json(ARQ_AVALIACOES, lines=True, chunksize=LOTE):
        chunk['order_ref'] = chunk['order'].apply(lambda x: x.get('ref') if isinstance(x, dict) else None)
        chunk['order_channel'] = chunk['order'].apply(lambda x: x.get('channel') if isinstance(x, dict) else None)
        chunk['product_sku'] = chunk['product'].apply(lambda x: x.get('sku') if isinstance(x, dict) else None)
        
        chunk['rating'] = chunk['rating'].apply(lambda x: str(x) if pd.notna(x) else None)

        grava_stg(chunk, "marketplace_avaliacoes", dw, primeiro_bloco)
        primeiro_bloco = False


if __name__ == "__main__":
    qa = Suite(etapa="01_extracao")
    extrai_mysql(qa)
    extrai_postgres(qa)
    extrai_sac(qa)
    extrai_avaliacoes(qa)

    dw = eng_dw()

    # TODO 1.5 — asserções mínimas desta etapa:
    #   qa.igual("linhas legado.PEDIDOS", lidas, esperadas_na_origem, ...)
    #   qa.sem_nulos("protocolo do SAC", stg_sac["protocolo"])
    #   qa.unico("review_id", stg_aval["review_id"])
    # A contagem esperada vem de um SELECT COUNT(*) na própria origem:
    # extração que perde linha silenciosamente é o defeito mais caro do pipeline.

    # 1. qa.igual para testar o MySQL
    with eng_mysql().connect() as conn:
        esp_mysql = conn.execute(text("SELECT COUNT(*) FROM PEDIDOS")).scalar()
    df_mysql_stg = pd.read_sql("SELECT COUNT(*) as qtd FROM stg.legado_pedidos", dw)
    qa.igual("linhas legado.PEDIDOS", df_mysql_stg['qtd'].iloc[0], esp_mysql, "Pedidos do MySQL divergente")

    # 2. qa.igual para testar o Postgres
    with eng_origem().connect() as conn:
        esp_pg = conn.execute(text("SELECT COUNT(*) FROM shop.orders")).scalar()
    df_pg_stg = pd.read_sql("SELECT COUNT(*) as qtd FROM stg.ecommerce_orders", dw)
    qa.igual("linhas ecommerce.orders", df_pg_stg['qtd'].iloc[0], esp_pg, "Orders do Postgres divergente")

    # 3. qa.sem_nulos para o SAC
    df_sac_stg = pd.read_sql("SELECT protocolo FROM stg.sac_atendimentos", dw)
    qa.sem_nulos("protocolo do SAC", df_sac_stg["protocolo"], "O campo protocolo do SAC não pode conter nulos")

    # 4. qa.unico para as Avaliações
    df_aval_stg = pd.read_sql("SELECT review_id FROM stg.marketplace_avaliacoes", dw)
    qa.unico("review_id", df_aval_stg["review_id"], "O review_id das avaliações deve ser único")

    qa.registrar(dw)
    qa.imprimir()