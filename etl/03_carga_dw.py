#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 3 — CARGA NO ESQUEMA ESTRELA  (esqueleto: vocês completam)

Antes de escrever a primeira linha desta etapa, o relatório já deve conter
a DECLARAÇÃO DE GRÃO das duas tabelas-fato, na forma:

    "Uma linha de dw.fato_pedido representa ______________________________."
    "Uma linha de dw.fato_item_pedido representa _________________________."

Se a frase não couber sem um "e também", o grão está errado.

    docker compose exec etl python 03_carga_dw.py
"""

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from config import eng_dw
from qualidade.assercoes import Suite


def carrega_dim_tempo(engine, ini=date(2022, 12, 1), fim=date(2026, 3, 31)):
    """Esta dimensão está pronta — é a única sem decisão a tomar."""
    MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]
    linhas = []
    d = ini
    while d <= fim:
        linhas.append(dict(data_sk=d, ano=d.year, trimestre=(d.month - 1) // 3 + 1,
                           mes=d.month, dia=d.day, dia_semana=d.isoweekday(),
                           nome_mes=MESES[d.month - 1],
                           eh_fim_semana=d.isoweekday() >= 6))
        d += timedelta(days=1)
    df = pd.DataFrame(linhas)
    with engine.begin() as cx:
        cx.execute(text("TRUNCATE dw.dim_tempo CASCADE"))
    df.to_sql("dim_tempo", engine, schema="dw", if_exists="append", index=False)
    print(f"dim_tempo: {len(df)} datas")
    return len(df)


def carrega_dimensoes(qa):
    # TODO 3.1 — dim_cliente, dim_produto, dim_canal, dim_status
    #            a partir do resultado da etapa 2.
    #            Ordem importa: dimensões antes dos fatos, sempre.
    raise NotImplementedError


def carrega_fato_pedido(qa):
    # TODO 3.2 — substitua as chaves naturais pelas surrogate keys das dimensões.
    #            Todo pedido precisa de cliente_sk: o que fazer com pedidos cujo
    #            ID_CLIENTE não existe em CLIENTES? Um cliente "DESCONHECIDO"
    #            na dimensão é a solução clássica. Adote-a ou justifique outra.
    raise NotImplementedError


def carrega_fato_item(qa):
    # TODO 3.3 — os itens órfãos (~1,5% em cada origem) não têm pedido.
    #            Descartar? Criar pedido sintético? Registrar em quarentena?
    #            Qualquer caminho é aceitável; nenhum é aceitável sem registro.
    raise NotImplementedError


def carrega_fatos_auxiliares(qa):
    # TODO 3.4 — fato_atendimento e fato_avaliacao.
    raise NotImplementedError


if __name__ == "__main__":
    dw = eng_dw()
    qa = Suite(etapa="03_carga_dw")
    carrega_dim_tempo(dw)
    carrega_dimensoes(qa)
    carrega_fato_pedido(qa)
    carrega_fato_item(qa)
    carrega_fatos_auxiliares(qa)

    # TODO 3.5 — asserções obrigatórias:
    #   · nenhuma FK órfã em fato_pedido (cliente_sk, data_pedido_sk, canal_sk);
    #   · contagem de fato_pedido == pedidos válidos nas duas origens somados;
    #   · SUM(valor_total) por sistema_origem dentro de ±0,1% do total da origem
    #     (reconciliação financeira: é assim que se prova que a carga não mentiu);
    #   · nenhum pedido com dias_entrega negativo depois do tratamento.

    qa.registrar(dw)
    qa.imprimir()
