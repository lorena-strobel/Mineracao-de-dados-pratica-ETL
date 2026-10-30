#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 4 — TABELA-BASE DE ANÁLISE (ABT) E O EXPERIMENTO DE VAZAMENTO

Pergunta analítica:
    dado o comportamento do cliente ATÉ 2025-06-30, ele comprará de novo
    entre 2025-07-01 e 2025-09-28?

Esta etapa produz DUAS versões da mesma tabela:

    --correta     todos os atributos calculados apenas com dados até a data
                  de corte. É a versão que vale.

    --vazamento   a mesma coisa, só que com dois ou três atributos calculados
                  sobre a base inteira. É a versão errada, que vocês vão
                  construir de propósito, rodar no Orange e comparar.

O objetivo do experimento não é ver um número maior. É medir a distância
entre um resultado que parece excelente e um resultado que é válido —
e descobrir que a diferença entre os dois cabe em uma linha de código.

    docker compose exec etl python 04_abt.py --correta
    docker compose exec etl python 04_abt.py --vazamento
"""

import argparse

import numpy as np
import pandas as pd
from sqlalchemy import text

from config import DATA_CORTE, DATA_FIM_ALVO, eng_dw
from qualidade.assercoes import Suite


# ---------------------------------------------------------------------------
# ALVO — este está pronto, e é o único ponto do pipeline em que é legítimo
# olhar para o futuro, porque é exatamente isso que se quer prever.
#
# Grão Declarado da ABT (Princípio 5 / RDT-14):
#   "Uma linha de abt.recompra_90d representa um cliente único identificado
#    (cliente_sk <> -1) em uma data de corte específica (2025-06-30), com seus
#    atributos comportamentais acumulados até essa data e o indicador binário
#    de recompra nos 90 dias subsequentes."
# ---------------------------------------------------------------------------
SQL_ALVO = f"""
WITH base AS (
    SELECT DISTINCT c.cliente_sk
    FROM dw.dim_cliente c
    JOIN dw.fato_pedido p ON p.cliente_sk = c.cliente_sk
    WHERE p.data_pedido_sk <= DATE '{DATA_CORTE}'
      AND c.cliente_sk <> -1
),
compras_na_janela AS (
    SELECT DISTINCT p.cliente_sk
    FROM dw.fato_pedido p
    JOIN dw.dim_status s ON s.status_sk = p.status_sk
    WHERE p.data_pedido_sk >  DATE '{DATA_CORTE}'
      AND p.data_pedido_sk <= DATE '{DATA_FIM_ALVO}'
      AND s.status_conformado <> 'CANCELADO'
      AND p.cliente_sk <> -1
)
SELECT b.cliente_sk,
       DATE '{DATA_CORTE}' AS data_corte,
       CASE WHEN j.cliente_sk IS NOT NULL THEN 1 ELSE 0 END AS alvo_recompra_90d
FROM base b
LEFT JOIN compras_na_janela j ON j.cliente_sk = b.cliente_sk
"""


def monta_atributos_corretos(dw):
    """
    RDT-14 — Engenharia de atributos preditivos da ABT Correta via Pandas.
    Todo evento e agregado respeita estritamente a barreira temporal
    data_pedido_sk <= DATE '{DATA_CORTE}' e exclui a chave sentinela (-1).
    """
    corte_ts = pd.to_datetime(DATA_CORTE)

    # 1. Pedidos emitidos até a data de corte (leitura em lotes de 50.000 linhas)
    sql_pedidos = text(f"""
        SELECT
            p.pedido_sk,
            p.cliente_sk,
            p.data_pedido_sk,
            p.data_entrega_sk,
            p.valor_total,
            p.dias_entrega,
            s.status_conformado,
            c.canal_conformado
        FROM dw.fato_pedido p
        JOIN dw.dim_status s ON s.status_sk = p.status_sk
        JOIN dw.dim_canal c ON c.canal_sk = p.canal_sk
        WHERE p.data_pedido_sk <= DATE '{DATA_CORTE}'
          AND p.cliente_sk <> -1
    """)
    df_ped = pd.concat(
        pd.read_sql(sql_pedidos, dw, chunksize=50_000),
        ignore_index=True
    )

    df_ped["dias_desde_pedido"] = (corte_ts - pd.to_datetime(df_ped["data_pedido_sk"])).dt.days
    df_ped["eh_valido"] = df_ped["status_conformado"] != "CANCELADO"
    df_ped["eh_cancelado"] = df_ped["status_conformado"] == "CANCELADO"
    df_ped["eh_online"] = df_ped["canal_conformado"].isin(["ONLINE_PROPRIO", "MARKETPLACE"])
    df_ped["valor_valido"] = np.where(df_ped["eh_valido"], df_ped["valor_total"].astype(float), 0.0)

    # Dupla trava temporal para entrega: o pedido deve estar ENTREGUE e a entrega
    # precisa ter ocorrido até a data de corte (entregas após 30/06 seriam futuro).
    entrega_ate_corte = (
        (df_ped["status_conformado"] == "ENTREGUE")
        & df_ped["data_entrega_sk"].notna()
        & (pd.to_datetime(df_ped["data_entrega_sk"]) <= corte_ts)
    )
    df_ped["prazo_valido"] = np.where(entrega_ate_corte, df_ped["dias_entrega"].astype(float), np.nan)

    ag_ped = df_ped.groupby("cliente_sk", as_index=False).agg(
        recencia_dias=("dias_desde_pedido", "min"),
        tempo_como_cliente_dias=("dias_desde_pedido", "max"),
        total_pedidos=("pedido_sk", "count"),
        frequencia_pedidos=("eh_valido", "sum"),
        qtd_cancelados=("eh_cancelado", "sum"),
        qtd_online=("eh_online", "sum"),
        valor_monetario_total=("valor_valido", "sum"),
        prazo_medio_entrega=("prazo_valido", "mean"),
    )

    ag_ped["recencia_dias"] = ag_ped["recencia_dias"].astype(int)
    ag_ped["tempo_como_cliente_dias"] = ag_ped["tempo_como_cliente_dias"].astype(int)
    ag_ped["frequencia_pedidos"] = ag_ped["frequencia_pedidos"].astype(int)
    ag_ped["valor_monetario_total"] = ag_ped["valor_monetario_total"].round(2)
    ag_ped["ticket_medio"] = np.where(
        ag_ped["frequencia_pedidos"] > 0,
        (ag_ped["valor_monetario_total"] / ag_ped["frequencia_pedidos"]).round(2),
        0.0
    )
    ag_ped["taxa_cancelamento"] = (ag_ped["qtd_cancelados"] / ag_ped["total_pedidos"]).round(4)
    ag_ped["propensao_online"] = (ag_ped["qtd_online"] / ag_ped["total_pedidos"]).round(4)
    ag_ped["prazo_medio_entrega"] = ag_ped["prazo_medio_entrega"].round(2)

    # Canal predominante (moda de canal_conformado por cliente, desempate alfabético)
    cont_canal = (
        df_ped.groupby(["cliente_sk", "canal_conformado"], as_index=False)["pedido_sk"]
        .count()
        .sort_values(["cliente_sk", "pedido_sk", "canal_conformado"], ascending=[True, False, True])
        .drop_duplicates(subset=["cliente_sk"], keep="first")
        .rename(columns={"canal_conformado": "canal_predominante"})[["cliente_sk", "canal_predominante"]]
    )
    ag_ped = ag_ped.merge(cont_canal, on="cliente_sk", how="left")

    # 2. Diversidade de sortimento (categorias_distintas em fato_item_pedido via chunks)
    sql_itens = text(f"""
        SELECT p.cliente_sk, pr.categoria_nivel1
        FROM dw.fato_item_pedido i
        JOIN dw.fato_pedido p ON p.pedido_sk = i.pedido_sk
        JOIN dw.dim_status s ON s.status_sk = p.status_sk
        JOIN dw.dim_produto pr ON pr.produto_sk = i.produto_sk
        WHERE p.data_pedido_sk <= DATE '{DATA_CORTE}'
          AND p.cliente_sk <> -1
          AND s.status_conformado <> 'CANCELADO'
    """)
    pares_cat = []
    for chunk in pd.read_sql(sql_itens, dw, chunksize=50_000):
        pares_cat.append(chunk.drop_duplicates())
    df_cat_unicos = pd.concat(pares_cat, ignore_index=True).drop_duplicates()
    ag_cat = (
        df_cat_unicos.groupby("cliente_sk", as_index=False)["categoria_nivel1"]
        .nunique()
        .rename(columns={"categoria_nivel1": "categorias_distintas"})
    )
    ag_ped = ag_ped.merge(ag_cat, on="cliente_sk", how="left")
    ag_ped["categorias_distintas"] = ag_ped["categorias_distintas"].fillna(0).astype(int)

    # 3. Fato auxiliar SAC (dupla trava temporal: abertura <= corte E pedido <= corte)
    sql_sac = text(f"""
        SELECT a.cliente_sk, a.atendimento_sk
        FROM dw.fato_atendimento a
        JOIN dw.fato_pedido p ON p.pedido_sk = a.pedido_sk
        WHERE a.data_abertura_sk <= DATE '{DATA_CORTE}'
          AND p.data_pedido_sk <= DATE '{DATA_CORTE}'
          AND a.cliente_sk <> -1
    """)
    df_sac = pd.concat(
        pd.read_sql(sql_sac, dw, chunksize=50_000),
        ignore_index=True
    )
    ag_sac = (
        df_sac.groupby("cliente_sk", as_index=False)["atendimento_sk"]
        .count()
        .rename(columns={"atendimento_sk": "qtd_atendimentos_sac"})
    )
    ag_ped = ag_ped.merge(ag_sac, on="cliente_sk", how="left")
    ag_ped["qtd_atendimentos_sac"] = ag_ped["qtd_atendimentos_sac"].fillna(0).astype(int)

    # 4. Fato auxiliar Avaliações (dupla trava temporal: review <= corte E pedido <= corte)
    sql_aval = text(f"""
        SELECT p.cliente_sk, av.nota
        FROM dw.fato_avaliacao av
        JOIN dw.fato_pedido p ON p.pedido_sk = av.pedido_sk
        WHERE av.data_sk <= DATE '{DATA_CORTE}'
          AND p.data_pedido_sk <= DATE '{DATA_CORTE}'
          AND p.cliente_sk <> -1
    """)
    df_aval = pd.concat(
        pd.read_sql(sql_aval, dw, chunksize=50_000),
        ignore_index=True
    )
    ag_aval = (
        df_aval.groupby("cliente_sk", as_index=False)["nota"]
        .mean()
        .rename(columns={"nota": "nota_media_avaliacoes"})
    )
    ag_aval["nota_media_avaliacoes"] = ag_aval["nota_media_avaliacoes"].round(2)
    ag_ped = ag_ped.merge(ag_aval, on="cliente_sk", how="left")

    colunas_contrato = [
        "cliente_sk",
        "recencia_dias",
        "frequencia_pedidos",
        "valor_monetario_total",
        "ticket_medio",
        "tempo_como_cliente_dias",
        "taxa_cancelamento",
        "prazo_medio_entrega",
        "categorias_distintas",
        "canal_predominante",
        "propensao_online",
        "qtd_atendimentos_sac",
        "nota_media_avaliacoes",
    ]
    return ag_ped[colunas_contrato]


def monta_atributos_com_vazamento(dw):
    """
    RDT-15 / TODO 4.2 — Engenharia de atributos com Vazamento Deliberado (Target Leakage).
    
    Vazamentos introduzidos de propósito:
    1. Vazamento Temporal Óbvio em 'recencia_dias' e 'frequencia_pedidos':
       Remove o filtro 'data_pedido_sk <= DATA_CORTE', permitindo enxergar os
       pedidos da janela do alvo (01/07/2025 a 28/09/2025). Compras após o corte
       produzem recencia_dias < 0 e frequencia inflada para os recompradores.
    2. Vazamento Metodológico Sutil em 'valor_monetario_total':
       Aplica padronização Z-score (x - media) / desvio calculada sobre as
       linhas da ABT antes da partição treino/teste, vazando a distribuição
       estatística do conjunto de teste para o treino.
    """
    corte_ts = pd.to_datetime(DATA_CORTE)

    # 1. Pedidos da base INTEIRA (sem o filtro data_pedido_sk <= DATA_CORTE)
    sql_pedidos = text("""
        SELECT
            p.pedido_sk,
            p.cliente_sk,
            p.data_pedido_sk,
            p.data_entrega_sk,
            p.valor_total,
            p.dias_entrega,
            s.status_conformado,
            c.canal_conformado
        FROM dw.fato_pedido p
        JOIN dw.dim_status s ON s.status_sk = p.status_sk
        JOIN dw.dim_canal c ON c.canal_sk = p.canal_sk
        WHERE p.cliente_sk <> -1
    """)
    df_ped = pd.concat(
        pd.read_sql(sql_pedidos, dw, chunksize=50_000),
        ignore_index=True
    )

    # Compras após o corte gerarão valores negativos (ex.: corte - 15/07 = -15 dias)
    df_ped["dias_desde_pedido"] = (corte_ts - pd.to_datetime(df_ped["data_pedido_sk"])).dt.days
    df_ped["eh_valido"] = df_ped["status_conformado"] != "CANCELADO"
    df_ped["eh_cancelado"] = df_ped["status_conformado"] == "CANCELADO"
    df_ped["eh_online"] = df_ped["canal_conformado"].isin(["ONLINE_PROPRIO", "MARKETPLACE"])
    df_ped["valor_valido"] = np.where(df_ped["eh_valido"], df_ped["valor_total"].astype(float), 0.0)

    # Prazo de entrega
    entrega_concluida = (
        (df_ped["status_conformado"] == "ENTREGUE")
        & df_ped["data_entrega_sk"].notna()
    )
    df_ped["prazo_valido"] = np.where(entrega_concluida, df_ped["dias_entrega"].astype(float), np.nan)

    ag_ped = df_ped.groupby("cliente_sk", as_index=False).agg(
        recencia_dias=("dias_desde_pedido", "min"),
        tempo_como_cliente_dias=("dias_desde_pedido", "max"),
        total_pedidos=("pedido_sk", "count"),
        frequencia_pedidos=("eh_valido", "sum"),
        qtd_cancelados=("eh_cancelado", "sum"),
        qtd_online=("eh_online", "sum"),
        valor_monetario_total=("valor_valido", "sum"),
        prazo_medio_entrega=("prazo_valido", "mean"),
    )

    ag_ped["recencia_dias"] = ag_ped["recencia_dias"].astype(int)
    ag_ped["tempo_como_cliente_dias"] = ag_ped["tempo_como_cliente_dias"].astype(int)
    ag_ped["frequencia_pedidos"] = ag_ped["frequencia_pedidos"].astype(int)
    ag_ped["ticket_medio"] = np.where(
        ag_ped["frequencia_pedidos"] > 0,
        (ag_ped["valor_monetario_total"] / ag_ped["frequencia_pedidos"]).round(2),
        0.0
    )
    ag_ped["taxa_cancelamento"] = (ag_ped["qtd_cancelados"] / ag_ped["total_pedidos"]).round(4)
    ag_ped["propensao_online"] = (ag_ped["qtd_online"] / ag_ped["total_pedidos"]).round(4)
    ag_ped["prazo_medio_entrega"] = ag_ped["prazo_medio_entrega"].round(2)

    # Vazamento sutil exigido no edital: Z-Score Global antes da partição
    # Padroniza valor_monetario_total usando a média e o desvio da base inteira
    media_global = ag_ped["valor_monetario_total"].mean()
    desvio_global = ag_ped["valor_monetario_total"].std()
    ag_ped["valor_monetario_total"] = (
        (ag_ped["valor_monetario_total"] - media_global) / desvio_global
    ).round(4)

    # Canal predominante
    cont_canal = (
        df_ped.groupby(["cliente_sk", "canal_conformado"], as_index=False)["pedido_sk"]
        .count()
        .sort_values(["cliente_sk", "pedido_sk", "canal_conformado"], ascending=[True, False, True])
        .drop_duplicates(subset=["cliente_sk"], keep="first")
        .rename(columns={"canal_conformado": "canal_predominante"})[["cliente_sk", "canal_predominante"]]
    )
    ag_ped = ag_ped.merge(cont_canal, on="cliente_sk", how="left")

    # 2. Diversidade de categorias (itens válidos da base)
    sql_itens = text("""
        SELECT p.cliente_sk, pr.categoria_nivel1
        FROM dw.fato_item_pedido i
        JOIN dw.fato_pedido p ON p.pedido_sk = i.pedido_sk
        JOIN dw.dim_status s ON s.status_sk = p.status_sk
        JOIN dw.dim_produto pr ON pr.produto_sk = i.produto_sk
        WHERE p.cliente_sk <> -1
          AND s.status_conformado <> 'CANCELADO'
    """)
    pares_cat = []
    for chunk in pd.read_sql(sql_itens, dw, chunksize=50_000):
        pares_cat.append(chunk.drop_duplicates())
    df_cat_unicos = pd.concat(pares_cat, ignore_index=True).drop_duplicates()
    ag_cat = (
        df_cat_unicos.groupby("cliente_sk", as_index=False)["categoria_nivel1"]
        .nunique()
        .rename(columns={"categoria_nivel1": "categorias_distintas"})
    )
    ag_ped = ag_ped.merge(ag_cat, on="cliente_sk", how="left")
    ag_ped["categorias_distintas"] = ag_ped["categorias_distintas"].fillna(0).astype(int)

    # 3. SAC (base inteira)
    sql_sac = text("""
        SELECT a.cliente_sk, a.atendimento_sk
        FROM dw.fato_atendimento a
        JOIN dw.fato_pedido p ON p.pedido_sk = a.pedido_sk
        WHERE a.cliente_sk <> -1
    """)
    df_sac = pd.concat(
        pd.read_sql(sql_sac, dw, chunksize=50_000),
        ignore_index=True
    )
    ag_sac = (
        df_sac.groupby("cliente_sk", as_index=False)["atendimento_sk"]
        .count()
        .rename(columns={"atendimento_sk": "qtd_atendimentos_sac"})
    )
    ag_ped = ag_ped.merge(ag_sac, on="cliente_sk", how="left")
    ag_ped["qtd_atendimentos_sac"] = ag_ped["qtd_atendimentos_sac"].fillna(0).astype(int)

    # 4. Avaliações (base inteira)
    sql_aval = text("""
        SELECT p.cliente_sk, av.nota
        FROM dw.fato_avaliacao av
        JOIN dw.fato_pedido p ON p.pedido_sk = av.pedido_sk
        WHERE p.cliente_sk <> -1
    """)
    df_aval = pd.concat(
        pd.read_sql(sql_aval, dw, chunksize=50_000),
        ignore_index=True
    )
    ag_aval = (
        df_aval.groupby("cliente_sk", as_index=False)["nota"]
        .mean()
        .rename(columns={"nota": "nota_media_avaliacoes"})
    )
    ag_aval["nota_media_avaliacoes"] = ag_aval["nota_media_avaliacoes"].round(2)
    ag_ped = ag_ped.merge(ag_aval, on="cliente_sk", how="left")

    colunas_contrato = [
        "cliente_sk",
        "recencia_dias",
        "frequencia_pedidos",
        "valor_monetario_total",
        "ticket_medio",
        "tempo_como_cliente_dias",
        "taxa_cancelamento",
        "prazo_medio_entrega",
        "categorias_distintas",
        "canal_predominante",
        "propensao_online",
        "qtd_atendimentos_sac",
        "nota_media_avaliacoes",
    ]
    return ag_ped[colunas_contrato]


def grava(df, dw, sufixo):
    tabela = "recompra_90d" if sufixo == "correta" else "recompra_90d_vazamento"
    df.to_sql(tabela, dw, schema="abt", if_exists="replace",
              index=False, method="multi", chunksize=5_000)
    print(f"abt.{tabela}: {len(df)} linhas, {df.shape[1]} colunas")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--correta", action="store_true")
    ap.add_argument("--vazamento", action="store_true")
    args = ap.parse_args()
    if not (args.correta or args.vazamento):
        ap.error("escolha --correta ou --vazamento")

    dw = eng_dw()
    alvo = pd.read_sql(text(SQL_ALVO), dw)
    print(f"alvo: {len(alvo)} clientes | taxa de recompra = "
          f"{alvo['alvo_recompra_90d'].mean():.3f}")

    qa = Suite(etapa="04_abt_" + ("correta" if args.correta else "vazamento"))
    qa.entre("taxa do alvo", float(alvo["alvo_recompra_90d"].mean()), 0.02, 0.60,
             "classe extremamente desbalanceada indica erro na janela")
    qa.unico("cliente_sk no alvo", alvo["cliente_sk"])

    atributos = (monta_atributos_corretos(dw) if args.correta
                 else monta_atributos_com_vazamento(dw))

    antes = len(alvo)
    abt = alvo.merge(atributos, on="cliente_sk", how="left")
    qa.cardinalidade_preservada("junção alvo x atributos", antes, len(abt))
    qa.igual("total clientes abt sem sentinela", len(abt), 99_749,
             "ABT deve conter exatamente os 99.749 clientes reais até o corte")
    qa.igual("ausencia cliente sentinela -1", int((abt["cliente_sk"] == -1).sum()), 0,
             "Chave sentinela -1 (RDT-12) nao deve integrar a ABT de clientes")

    if args.correta:
        qa.sem_nulos("recencia_dias sem nulos", abt["recencia_dias"])
        qa.sem_nulos("frequencia_pedidos sem nulos", abt["frequencia_pedidos"])
        qa.sem_nulos("valor_monetario_total sem nulos", abt["valor_monetario_total"])
        qa.sem_nulos("ticket_medio sem nulos", abt["ticket_medio"])
        qa.sem_nulos("tempo_como_cliente_dias sem nulos", abt["tempo_como_cliente_dias"])
        qa.sem_nulos("taxa_cancelamento sem nulos", abt["taxa_cancelamento"])
        qa.sem_nulos("categorias_distintas sem nulos", abt["categorias_distintas"])
        qa.sem_nulos("canal_predominante sem nulos", abt["canal_predominante"])
        qa.sem_nulos("propensao_online sem nulos", abt["propensao_online"])
        qa.sem_nulos("qtd_atendimentos_sac sem nulos", abt["qtd_atendimentos_sac"])
        qa.dominio(
            "dominio canal_predominante",
            abt["canal_predominante"],
            {"FISICO", "ONLINE_PROPRIO", "MARKETPLACE", "TELEVENDAS"},
            "canal_predominante deve pertencer aos 4 canais conformados do DW",
        )
        qa.igual(
            "nulos preservados prazo_medio_entrega",
            int(abt["prazo_medio_entrega"].isna().sum()),
            7_088,
            "Exatamente 7.088 clientes sem entrega concluida ate o corte devem preservar NaN",
        )
        qa.igual(
            "nulos preservados nota_media_avaliacoes",
            int(abt["nota_media_avaliacoes"].isna().sum()),
            42_974,
            "Exatamente 42.974 clientes sem avaliacoes ate o corte devem preservar NaN",
        )

        # Verificação por amostragem de contenção temporal (RDT-14):
        # Recalcula em SQL puro estritamente até DATA_CORTE para uma amostra de 1.000 clientes
        # e confere divergência zero contra os atributos calculados via Pandas.
        amostra_sks = tuple(abt["cliente_sk"].sample(n=1_000, random_state=20262).tolist())
        sql_auditoria_corte = text(f"""
            SELECT
                p.cliente_sk,
                (DATE '{DATA_CORTE}' - MAX(p.data_pedido_sk))::int AS rec_sql,
                COUNT(*) FILTER (WHERE s.status_conformado <> 'CANCELADO')::int AS freq_sql,
                COALESCE(ROUND(SUM(p.valor_total) FILTER (WHERE s.status_conformado <> 'CANCELADO'), 2), 0.0) AS val_sql
            FROM dw.fato_pedido p
            JOIN dw.dim_status s ON s.status_sk = p.status_sk
            WHERE p.data_pedido_sk <= DATE '{DATA_CORTE}'
              AND p.cliente_sk IN :sks
            GROUP BY p.cliente_sk
        """)
        df_aud = pd.read_sql(sql_auditoria_corte, dw, params={"sks": amostra_sks})
        comp = abt.merge(df_aud, on="cliente_sk", how="inner")
        divergencias_corte = int(
            (
                (comp["recencia_dias"] != comp["rec_sql"])
                | (comp["frequencia_pedidos"] != comp["freq_sql"])
                | ((comp["valor_monetario_total"] - comp["val_sql"]).abs() > 0.01)
            ).sum()
        )
        qa.igual(
            "teste_vazamento_amostragem",
            divergencias_corte,
            0,
            "Nenhum cliente amostrado pode divergir do calculo estrito ate a data de corte",
        )

    elif args.vazamento:
        qa.sem_nulos("recencia_dias sem nulos", abt["recencia_dias"])
        qa.sem_nulos("frequencia_pedidos sem nulos", abt["frequencia_pedidos"])
        qa.sem_nulos("valor_monetario_total sem nulos", abt["valor_monetario_total"])
        qa.sem_nulos("ticket_medio sem nulos", abt["ticket_medio"])
        qa.sem_nulos("tempo_como_cliente_dias sem nulos", abt["tempo_como_cliente_dias"])
        qa.sem_nulos("taxa_cancelamento sem nulos", abt["taxa_cancelamento"])
        qa.sem_nulos("categorias_distintas sem nulos", abt["categorias_distintas"])
        qa.sem_nulos("canal_predominante sem nulos", abt["canal_predominante"])
        qa.sem_nulos("propensao_online sem nulos", abt["propensao_online"])
        qa.sem_nulos("qtd_atendimentos_sac sem nulos", abt["qtd_atendimentos_sac"])
        qa.dominio(
            "dominio canal_predominante",
            abt["canal_predominante"],
            {"FISICO", "ONLINE_PROPRIO", "MARKETPLACE", "TELEVENDAS"},
            "canal_predominante deve pertencer aos 4 canais conformados do DW",
        )

        # Asserções comprobatórias de Target Leakage (TODO 4.2 / RDT-15):
        # 1. Vazamento temporal clássico: recências negativas por enxergar pedidos pós-corte
        recompra_futura = int((abt["recencia_dias"] < 0).sum())
        qa.maior_igual(
            "comprovacao_vazamento_recencia_negativa",
            recompra_futura,
            1,
            "Presença de recência negativa comprova inclusão de pedidos da janela do alvo",
        )

        # 2. Vazamento metodológico sutil: normalização Z-Score global sobre toda a base
        media_zscore = round(float(abt["valor_monetario_total"].mean()), 2)
        desvio_zscore = round(float(abt["valor_monetario_total"].std()), 2)
        qa.entre(
            "vazamento_zscore_media_zero",
            media_zscore,
            -0.05,
            0.05,
            "Média em torno de 0 comprova padronização Z-score global antes do split",
        )
        qa.entre(
            "vazamento_zscore_desvio_unitario",
            desvio_zscore,
            0.95,
            1.05,
            "Desvio padrão em torno de 1 comprova padronização Z-score global antes do split",
        )
        qa.maior_igual(
            "vazamento_zscore_valores_negativos",
            int((abt["valor_monetario_total"] < 0).sum()),
            1,
            "Presença de valores monetários negativos confirma padronização Z-score",
        )

        # 3. Auditoria por amostragem: na versão com vazamento, DEVE haver divergência
        amostra_sks = tuple(abt["cliente_sk"].sample(n=1_000, random_state=20262).tolist())
        sql_auditoria_corte = text(f"""
            SELECT
                p.cliente_sk,
                (DATE '{DATA_CORTE}' - MAX(p.data_pedido_sk))::int AS rec_sql,
                COUNT(*) FILTER (WHERE s.status_conformado <> 'CANCELADO')::int AS freq_sql,
                COALESCE(ROUND(SUM(p.valor_total) FILTER (WHERE s.status_conformado <> 'CANCELADO'), 2), 0.0) AS val_sql
            FROM dw.fato_pedido p
            JOIN dw.dim_status s ON s.status_sk = p.status_sk
            WHERE p.data_pedido_sk <= DATE '{DATA_CORTE}'
              AND p.cliente_sk IN :sks
            GROUP BY p.cliente_sk
        """)
        df_aud = pd.read_sql(sql_auditoria_corte, dw, params={"sks": amostra_sks})
        comp = abt.merge(df_aud, on="cliente_sk", how="inner")
        divergencias_corte = int(
            (
                (comp["recencia_dias"] != comp["rec_sql"])
                | (comp["frequencia_pedidos"] != comp["freq_sql"])
                | ((comp["valor_monetario_total"] - comp["val_sql"]).abs() > 0.01)
            ).sum()
        )
        qa.maior_igual(
            "confirmacao_divergencia_corte_amostragem",
            divergencias_corte,
            1,
            "ABT com vazamento deve divergir dos cálculos restritos à data de corte",
        )

    grava(abt, dw, "correta" if args.correta else "vazamento")
    qa.registrar(dw)
    qa.imprimir()
