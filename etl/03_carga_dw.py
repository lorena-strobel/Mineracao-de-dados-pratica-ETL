#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 3 — CARGA NO ESQUEMA ESTRELA

Grãos declarados formalmente (Princípio 5 / RDT-11):
    "Uma linha de dw.fato_pedido representa a transação de um pedido de compra
     individual emitido por um cliente em uma data e canal específicos."
    "Uma linha de dw.fato_item_pedido representa a ocorrência de um produto
     comercializado (linha de item) dentro de um determinado pedido."

Execução no ambiente de contêiner:
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
    print(f"dim_tempo: {len(df)} datas carregadas.")
    return len(df)


def carrega_dimensoes(qa):
    """
    Carrega as dimensões do esquema estrela e insere sentinelas de integridade:
    - Inserção do cliente sentinela 'DESCONHECIDO' (cliente_sk = -1) em dw.dim_cliente (RDT-12)
    - Carga dos 6 mapeamentos de canal em dw.dim_canal
    - Criação de índices estratégicos para acelerar junções relacionais
    """
    print("-> Carregando dimensões e chaves sentinela...", flush=True)
    engine = eng_dw()

    with engine.begin() as cx:
        # 1. Cliente sentinela DESCONHECIDO (RDT-12)
        cx.execute(text("""
            INSERT INTO dw.dim_cliente (
                cliente_sk, cpf_normalizado, cpf_valido, nome_padronizado,
                cidade, uf, dt_primeiro_cadastro, id_legado, id_ecommerce,
                origem_unificacao, regra_pareamento
            )
            VALUES (
                -1, NULL, NULL, 'CLIENTE DESCONHECIDO',
                NULL, NULL, NULL, NULL, NULL,
                'AMBOS', 'SENTINELA_DESCONHECIDO'
            )
            ON CONFLICT (cliente_sk) DO NOTHING;
        """))

        # 2. Carga dos canais conformados em dw.dim_canal
        cx.execute(text("TRUNCATE TABLE dw.dim_canal RESTART IDENTITY CASCADE;"))
        cx.execute(text("""
            INSERT INTO dw.dim_canal (canal_origem, canal_conformado, sistema) VALUES
            ('LOJA', 'FISICO', 'LEGADO'),
            ('SITE', 'ONLINE_PROPRIO', 'LEGADO'),
            ('TELEVENDAS', 'TELEVENDAS', 'LEGADO'),
            ('app', 'ONLINE_PROPRIO', 'ECOM'),
            ('web', 'ONLINE_PROPRIO', 'ECOM'),
            ('marketplace', 'MARKETPLACE', 'ECOM');
        """))

        # 3. Índices parciais de aceleração para junções dimensionais
        cx.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_dim_cliente_legado ON dw.dim_cliente (id_legado) WHERE id_legado IS NOT NULL;
            CREATE INDEX IF NOT EXISTS ix_dim_cliente_ecom ON dw.dim_cliente (id_ecommerce) WHERE id_ecommerce IS NOT NULL;
            CREATE INDEX IF NOT EXISTS ix_dim_produto_sku ON dw.dim_produto (sku) WHERE sku IS NOT NULL;
            CREATE INDEX IF NOT EXISTS ix_dim_produto_legado ON dw.dim_produto (id_legado) WHERE id_legado IS NOT NULL;
        """))

    # Asserções de qualidade da camada dimensional
    df_canal = pd.read_sql("SELECT * FROM dw.dim_canal", engine)
    qa.igual("total canais dim_canal", len(df_canal), 6, "Total de mapeamentos de canal deve ser 6")
    qa.sem_nulos("canal_conformado preenchido", df_canal["canal_conformado"], "canal_conformado não pode conter nulos")

    df_sentinela = pd.read_sql("SELECT * FROM dw.dim_cliente WHERE cliente_sk = -1", engine)
    qa.igual("cliente sentinela desconhecido presente", len(df_sentinela), 1, "Cliente sentinela -1 deve existir em dim_cliente")
    print("-> Dimensões estruturadas com sucesso.", flush=True)


def carrega_fato_pedido(qa):
    """
    Carga da tabela dw.fato_pedido (grão da transação de compra individual):
    - Mapeia surrogate keys (cliente_sk, data_pedido_sk, data_entrega_sk, canal_sk, status_sk)
    - Trata pedidos sem cliente associando-os ao cliente sentinela 'DESCONHECIDO' (-1) (RDT-12)
    - Garante integridade referencial estrita e reconciliação financeira corporativa em +-0,1%
    """
    print("-> Carregando dw.fato_pedido...", flush=True)
    engine = eng_dw()

    with engine.begin() as cx:
        cx.execute(text("TRUNCATE TABLE dw.fato_pedido CASCADE;"))

        # Carga transacional do ERP Legado
        cx.execute(text("""
            INSERT INTO dw.fato_pedido (
                id_origem,
                sistema_origem,
                cliente_sk,
                data_pedido_sk,
                data_entrega_sk,
                canal_sk,
                status_sk,
                qtd_itens,
                valor_mercadoria,
                valor_frete,
                valor_desconto,
                valor_total,
                dias_entrega
            )
            SELECT 
                p.id_origem,
                p.sistema_origem,
                COALESCE(c.cliente_sk, -1) AS cliente_sk,
                p.dt_pedido_conformada::date AS data_pedido_sk,
                p.dt_entrega_conformada::date AS data_entrega_sk,
                cn.canal_sk,
                st.status_sk,
                p.qtd_itens,
                p.valor_mercadoria,
                p.valor_frete,
                p.valor_desconto,
                p.valor_total,
                ROUND(p.dias_entrega)::int AS dias_entrega
            FROM stg.pedidos_valores_conformados p
            LEFT JOIN dw.dim_cliente c ON c.id_legado = p.id_cliente_origem
            JOIN dw.dim_canal cn ON cn.canal_origem = p.canal_origem AND cn.sistema = p.sistema_origem
            JOIN dw.dim_status st ON st.status_origem = p.status_origem AND st.sistema = 'LEGADO'
            WHERE p.sistema_origem = 'LEGADO';
        """))

        # Carga transacional da Plataforma E-commerce
        cx.execute(text("""
            INSERT INTO dw.fato_pedido (
                id_origem,
                sistema_origem,
                cliente_sk,
                data_pedido_sk,
                data_entrega_sk,
                canal_sk,
                status_sk,
                qtd_itens,
                valor_mercadoria,
                valor_frete,
                valor_desconto,
                valor_total,
                dias_entrega
            )
            SELECT 
                p.id_origem,
                p.sistema_origem,
                COALESCE(c.cliente_sk, -1) AS cliente_sk,
                p.dt_pedido_conformada::date AS data_pedido_sk,
                p.dt_entrega_conformada::date AS data_entrega_sk,
                cn.canal_sk,
                st.status_sk,
                p.qtd_itens,
                p.valor_mercadoria,
                p.valor_frete,
                p.valor_desconto,
                p.valor_total,
                ROUND(p.dias_entrega)::int AS dias_entrega
            FROM stg.pedidos_valores_conformados p
            LEFT JOIN dw.dim_cliente c ON c.id_ecommerce = p.id_cliente_origem
            JOIN dw.dim_canal cn ON cn.canal_origem = p.canal_origem AND cn.sistema = p.sistema_origem
            JOIN dw.dim_status st ON st.status_origem = p.status_origem AND st.sistema = 'ECOMMERCE'
            WHERE p.sistema_origem = 'ECOM';
        """))

    print("-> dw.fato_pedido carregada com sucesso. Executando asserções...", flush=True)

    # Asserções de integridade estrutural e contábil
    res_totais = pd.read_sql("""
        SELECT 
            sistema_origem,
            COUNT(*) AS total_pedidos,
            COUNT(CASE WHEN cliente_sk = -1 THEN 1 END) AS pedidos_desconhecido,
            ROUND(SUM(valor_total)::numeric, 2) AS soma_valor_total,
            COUNT(CASE WHEN cliente_sk IS NULL THEN 1 END) AS nulos_cliente_sk,
            COUNT(CASE WHEN data_pedido_sk IS NULL THEN 1 END) AS nulos_data_pedido_sk,
            COUNT(CASE WHEN canal_sk IS NULL THEN 1 END) AS nulos_canal_sk,
            COUNT(CASE WHEN status_sk IS NULL THEN 1 END) AS nulos_status_sk,
            COUNT(CASE WHEN dias_entrega < 0 THEN 1 END) AS dias_entrega_negativos
        FROM dw.fato_pedido
        GROUP BY sistema_origem;
    """, engine).set_index("sistema_origem")

    tot_leg = int(res_totais.loc["LEGADO", "total_pedidos"])
    tot_ecom = int(res_totais.loc["ECOM", "total_pedidos"])
    desc_leg = int(res_totais.loc["LEGADO", "pedidos_desconhecido"])
    desc_ecom = int(res_totais.loc["ECOM", "pedidos_desconhecido"])

    qa.igual("total pedidos legado fato_pedido", tot_leg, 130_000, "Pedidos legado deve ser 130.000")
    qa.igual("total pedidos ecommerce fato_pedido", tot_ecom, 280_000, "Pedidos e-commerce deve ser 280.000")
    qa.igual("total fato_pedido consolidado", tot_leg + tot_ecom, 410_000, "Total de pedidos deve ser 410.000")

    qa.igual("pedidos cliente desconhecido legado", desc_leg, 16_183, "Pedidos com cliente sentinela legado deve ser 16.183")
    qa.igual("pedidos cliente desconhecido ecommerce", desc_ecom, 22_516, "Pedidos com cliente sentinela e-commerce deve ser 22.516")
    qa.igual("pedidos cliente desconhecido consolidado", desc_leg + desc_ecom, 38_699, "Total sentinela deve ser 38.699")

    nulos_fk = int(res_totais["nulos_cliente_sk"].sum() + res_totais["nulos_data_pedido_sk"].sum() +
                   res_totais["nulos_canal_sk"].sum() + res_totais["nulos_status_sk"].sum())
    qa.igual("chaves estrangeiras orfas em fato_pedido", nulos_fk, 0, "Nenhuma FK pode ser nula em fato_pedido")

    dias_neg = int(res_totais["dias_entrega_negativos"].sum())
    qa.igual("pedidos com dias_entrega negativo", dias_neg, 0, "Nenhum pedido pode ter dias_entrega negativo")

    # Reconciliação Financeira Corporativa de Ralph Kimball (tolerância +-0,1%)
    soma_dw_leg = float(res_totais.loc["LEGADO", "soma_valor_total"])
    soma_dw_ecom = float(res_totais.loc["ECOM", "soma_valor_total"])

    origens = pd.read_sql("""
        SELECT 
            'LEGADO' AS sistema,
            ROUND(SUM(\"VALOR_TOTAL\")::numeric, 2) AS total_origem
        FROM stg.legado_pedidos
        UNION ALL
        SELECT 
            'ECOM' AS sistema,
            ROUND(SUM(total_amount + freight_amount)::numeric, 2) AS total_origem
        FROM stg.ecommerce_orders;
    """, engine).set_index("sistema")

    orig_leg = float(origens.loc["LEGADO", "total_origem"])
    orig_ecom = float(origens.loc["ECOM", "total_origem"])

    dif_pct_leg = abs(soma_dw_leg - orig_leg) / orig_leg * 100.0
    dif_pct_ecom = abs(soma_dw_ecom - orig_ecom) / orig_ecom * 100.0

    qa.entre("reconciliacao financeira legado +-0.1%", dif_pct_leg, 0.0, 0.1,
             f"Desvio legado ({dif_pct_leg:.4f}%) deve estar dentro de 0,1%")
    qa.entre("reconciliacao financeira ecommerce +-0.1%", dif_pct_ecom, 0.0, 0.1,
             f"Desvio ecommerce ({dif_pct_ecom:.4f}%) deve estar dentro de 0,1%")


def carrega_fato_item(qa):
    """TODO 3.3 (Lorena / RDT-10) — Tratamento e carga dos itens órfãos."""
    pass


def carrega_fatos_auxiliares(qa):
    """TODO 3.4 (Mateus / RDT-13) — Carga de fato_atendimento e fato_avaliacao."""
    pass


if __name__ == "__main__":
    dw = eng_dw()
    qa = Suite(etapa="03_carga_dw")

    carrega_dim_tempo(dw)
    carrega_dimensoes(qa)
    carrega_fato_pedido(qa)
    carrega_fato_item(qa)
    carrega_fatos_auxiliares(qa)

    qa.registrar(dw)
    qa.imprimir()
