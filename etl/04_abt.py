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

import pandas as pd
from sqlalchemy import text

from config import DATA_CORTE, DATA_FIM_ALVO, eng_dw
from qualidade.assercoes import Suite


# ---------------------------------------------------------------------------
# ALVO — este está pronto, e é o único ponto do pipeline em que é legítimo
# olhar para o futuro, porque é exatamente isso que se quer prever.
# ---------------------------------------------------------------------------
SQL_ALVO = f"""
WITH base AS (
    SELECT DISTINCT c.cliente_sk
    FROM dw.dim_cliente c
    JOIN dw.fato_pedido p ON p.cliente_sk = c.cliente_sk
    WHERE p.data_pedido_sk <= DATE '{DATA_CORTE}'
),
compras_na_janela AS (
    SELECT DISTINCT p.cliente_sk
    FROM dw.fato_pedido p
    JOIN dw.dim_status s ON s.status_sk = p.status_sk
    WHERE p.data_pedido_sk >  DATE '{DATA_CORTE}'
      AND p.data_pedido_sk <= DATE '{DATA_FIM_ALVO}'
      AND s.status_conformado <> 'CANCELADO'   -- ajuste ao SEU mapeamento
)
SELECT b.cliente_sk,
       DATE '{DATA_CORTE}' AS data_corte,
       CASE WHEN j.cliente_sk IS NOT NULL THEN 1 ELSE 0 END AS alvo_recompra_90d
FROM base b
LEFT JOIN compras_na_janela j ON j.cliente_sk = b.cliente_sk
"""


def monta_atributos_corretos(dw):
    """
    TODO 4.1 — atributos preditivos. Todo agregado tem de ter, no WHERE,
    a cláusula   p.data_pedido_sk <= DATE '{corte}'.

    Sugestões (desenhem as suas, estas são só ponto de partida):
      recencia_dias          dias entre a última compra e a data de corte
      frequencia_pedidos     nº de pedidos não cancelados até o corte
      valor_monetario        soma de valor_total até o corte
      ticket_medio           valor_monetario / frequencia_pedidos
      prazo_medio_entrega    média de dias_entrega dos pedidos entregues
      taxa_cancelamento      cancelados / total
      categorias_distintas   nº de categorias nivel1 compradas
      canal_predominante     canal com mais pedidos
      qtd_atendimentos_sac   atendimentos abertos até o corte
      nota_media_avaliacoes  média das avaliações submetidas até o corte
      tempo_como_cliente     dias entre o primeiro pedido e o corte

    Cuidado com dois detalhes fáceis de errar:
      · clientes sem pedidos no período geram NaN em médias — decidam o
        tratamento e registrem (NaN não é zero);
      · atributo derivado de dim_cliente pode carregar informação atualizada
        depois do corte. Verifiquem antes de usar.
    """
    raise NotImplementedError


def monta_atributos_com_vazamento(dw):
    """
    TODO 4.2 — reproduza os MESMOS atributos, removendo o filtro de data em
    pelo menos dois deles (por exemplo recencia_dias e frequencia_pedidos),
    de modo que passem a enxergar a janela do alvo.

    Acrescente um terceiro vazamento mais sutil: normalize (z-score) um
    atributo numérico usando média e desvio calculados sobre TODAS as linhas,
    antes de qualquer partição treino/teste.

    Documente no RDT qual vazamento você introduziu em cada coluna.
    """
    raise NotImplementedError


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

    # TODO 4.3 — na versão CORRETA, acrescente uma asserção que verifique,
    # por amostragem, que nenhum atributo usa dado posterior ao corte.
    # Uma forma prática: recalcule um atributo restringindo a data e compare.

    grava(abt, dw, "correta" if args.correta else "vazamento")
    qa.registrar(dw)
    qa.imprimir()
