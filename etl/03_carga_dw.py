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
            ROUND(SUM("VALOR_TOTAL")::numeric, 2) AS total_origem
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
    print("-> Carregando dw.fato_item_pedido (RDT-10)...", flush=True)
    dw = eng_dw()

    # 1. Carrega dados da staging e do DW
    df_itens = pd.read_sql("SELECT * FROM stg.itens_valores_conformados", dw)
    df_pedidos_dw = pd.read_sql("SELECT pedido_sk, id_origem, sistema_origem FROM dw.fato_pedido", dw)
    df_produtos_dw = pd.read_sql("SELECT produto_sk, id_legado, id_ecommerce, origem FROM dw.dim_produto", dw)

    # 2. Cruza itens com pedidos para identificar o pedido_sk
    df_itens = df_itens.merge(
        df_pedidos_dw[["pedido_sk", "id_origem", "sistema_origem"]],
        left_on=["id_pedido_origem", "sistema_origem"],
        right_on=["id_origem", "sistema_origem"],
        how="left"
    )

    # 3. Descarta os itens órfãos (conforme RDT-10)
    total_itens_original = len(df_itens)
    df_validos = df_itens[df_itens["pedido_sk"].notna()].copy()
    itens_orfaos = total_itens_original - len(df_validos)
    taxa_orfaos = (itens_orfaos / total_itens_original) * 100
    print(f"   Itens válidos: {len(df_validos)}")
    print(f"   Itens órfãos descartados: {itens_orfaos} ({taxa_orfaos:.2f}%)")

    # 4. Cruza produtos para identificar o produto_sk
    mapa_prod_leg = df_produtos_dw.dropna(subset=["id_legado"]).set_index(df_produtos_dw["id_legado"].dropna().astype("int64"))["produto_sk"]
    mapa_prod_ecom = df_produtos_dw.dropna(subset=["id_ecommerce"]).set_index(df_produtos_dw["id_ecommerce"].dropna().astype("int64"))["produto_sk"]

    df_validos["produto_sk"] = None
    df_validos.loc[df_validos["sistema_origem"] == "LEGADO", "produto_sk"] = df_validos["id_produto_origem"].map(mapa_prod_leg)
    df_validos.loc[df_validos["sistema_origem"] == "ECOM", "produto_sk"] = df_validos["id_produto_origem"].map(mapa_prod_ecom)

    # 5. Grava no DW
    colunas_item = ["pedido_sk", "produto_sk", "quantidade", "valor_unitario", "valor_desconto", "valor_linha"]
    df_fato_item = df_validos[colunas_item]

    with dw.begin() as conn:
        conn.execute(text("TRUNCATE dw.fato_item_pedido RESTART IDENTITY CASCADE;"))
    df_fato_item.to_sql("fato_item_pedido", dw, schema="dw", if_exists="append", index=False, chunksize=10_000)
    print(f"-> fato_item_pedido carregada com sucesso: {len(df_fato_item)} itens.", flush=True)

    # 6. Asserções de qualidade da RDT-10
    qa.igual("total itens carregados fato_item_pedido", len(df_fato_item), 1371876,
             "1.371.876 itens vinculados a pedidos existentes carregados")
    qa.igual("total itens orfaos descartados rdt10", itens_orfaos, 20577,
             "Exatamente 20.577 itens órfãos descartados conforme RDT-10")
    qa.sem_nulos("pedido_sk sem nulos em fato_item_pedido", df_fato_item["pedido_sk"],
                 "Nenhum item pode ter pedido_sk nulo")
    qa.sem_nulos("produto_sk sem nulos em fato_item_pedido", df_fato_item["produto_sk"],
                 "Nenhum item pode ter produto_sk nulo")


def carrega_fatos_auxiliares(qa):
    """Carga dos fatos auxiliares: dw.fato_atendimento e dw.fato_avaliacao (RDT-13)."""
    engine = eng_dw()

    with engine.begin() as cx:
        print("-> Truncando dw.fato_atendimento e dw.fato_avaliacao...", flush=True)
        cx.execute(text("TRUNCATE TABLE dw.fato_atendimento RESTART IDENTITY CASCADE;"))
        cx.execute(text("TRUNCATE TABLE dw.fato_avaliacao RESTART IDENTITY CASCADE;"))

        # Carga de dw.fato_atendimento
        # Deduplicação sintática de 1.140 protocolos duplicados na extração bruta (95.000 únicos).
        # Resolução de cliente_sk com fallback para fp.cliente_sk para os 5.918 atendimentos sem CPF cadastrado.
        print("-> Carregando dw.fato_atendimento (SAC)...", flush=True)
        cx.execute(text("""
            WITH sac_dedup AS (
                SELECT DISTINCT ON (protocolo)
                    protocolo,
                    origem_sistema,
                    id_pedido_origem,
                    cpf_cliente,
                    TO_DATE(data_abertura, 'DD/MM/YYYY') AS data_abertura_sk,
                    CASE 
                        WHEN NULLIF(TRIM(data_fechamento), '') IS NOT NULL 
                        THEN TO_DATE(data_fechamento, 'DD/MM/YYYY') 
                        ELSE NULL 
                    END AS data_fechamento_sk,
                    UPPER(TRIM(canal)) AS canal,
                    TRIM(motivo) AS motivo_conformado,
                    NULLIF(TRIM(nota_satisfacao), '')::int AS nota_satisfacao,
                    NULLIF(REPLACE(TRIM(tempo_resolucao_horas), ',', '.'), '')::numeric(10,2) AS horas_resolucao,
                    CASE 
                        WHEN origem_sistema = 'ECOM' THEN 'ECOM-' || id_pedido_origem 
                        ELSE 'LEG-' || id_pedido_origem 
                    END AS id_pedido_formatado
                FROM stg.sac_atendimentos
                ORDER BY protocolo
            )
            INSERT INTO dw.fato_atendimento (
                protocolo,
                cliente_sk,
                pedido_sk,
                data_abertura_sk,
                data_fechamento_sk,
                canal,
                motivo_conformado,
                nota_satisfacao,
                horas_resolucao
            )
            SELECT 
                s.protocolo,
                COALESCE(c.cliente_sk, fp.cliente_sk) AS cliente_sk,
                fp.pedido_sk,
                s.data_abertura_sk,
                s.data_fechamento_sk,
                s.canal,
                s.motivo_conformado,
                s.nota_satisfacao,
                s.horas_resolucao
            FROM sac_dedup s
            LEFT JOIN dw.fato_pedido fp ON fp.id_origem = s.id_pedido_formatado
            LEFT JOIN dw.dim_cliente c ON c.cpf_normalizado = REGEXP_REPLACE(s.cpf_cliente, '\\D', '', 'g');
        """))

        # Carga de dw.fato_avaliacao
        # Resolução sintática hibrida de SKUs de produtos:
        # - E-commerce (119.984 avaliações): match direto por dp.sku = a.product_sku
        # - Legado físico (40.016 avaliações): desambiguação sintática SUBSTRING(a.product_sku FROM 5)::int = dp.id_legado
        print("-> Carregando dw.fato_avaliacao (Marketplace)...", flush=True)
        cx.execute(text("""
            INSERT INTO dw.fato_avaliacao (
                review_id,
                pedido_sk,
                produto_sk,
                data_sk,
                nota,
                compra_verificada,
                votos_uteis
            )
            SELECT 
                a.review_id,
                fp.pedido_sk,
                dp.produto_sk,
                SUBSTRING(a.submitted_at FROM 1 FOR 10)::date AS data_sk,
                ROUND(NULLIF(TRIM(a.rating), '')::numeric)::int AS nota,
                CASE 
                    WHEN a.verified_purchase = 1 THEN TRUE 
                    WHEN a.verified_purchase = 0 THEN FALSE 
                    ELSE NULL 
                END AS compra_verificada,
                ROUND(a.helpful_votes)::int AS votos_uteis
            FROM stg.marketplace_avaliacoes a
            JOIN dw.fato_pedido fp ON fp.id_origem = a.order_ref
            JOIN dw.dim_produto dp ON dp.sku = a.product_sku
            WHERE a.product_sku NOT LIKE 'LEG-%'
            UNION ALL
            SELECT 
                a.review_id,
                fp.pedido_sk,
                dp.produto_sk,
                SUBSTRING(a.submitted_at FROM 1 FOR 10)::date AS data_sk,
                ROUND(NULLIF(TRIM(a.rating), '')::numeric)::int AS nota,
                CASE 
                    WHEN a.verified_purchase = 1 THEN TRUE 
                    WHEN a.verified_purchase = 0 THEN FALSE 
                    ELSE NULL 
                END AS compra_verificada,
                ROUND(a.helpful_votes)::int AS votos_uteis
            FROM stg.marketplace_avaliacoes a
            JOIN dw.fato_pedido fp ON fp.id_origem = a.order_ref
            JOIN dw.dim_produto dp ON dp.id_legado = SUBSTRING(a.product_sku FROM 5)::int
            WHERE a.product_sku LIKE 'LEG-%';
        """))

        # Criação de índices b-tree para acelerar junções de análise e ABT
        cx.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_fato_atendimento_cli ON dw.fato_atendimento (cliente_sk);
            CREATE INDEX IF NOT EXISTS ix_fato_atendimento_ped ON dw.fato_atendimento (pedido_sk);
            CREATE INDEX IF NOT EXISTS ix_fato_atendimento_data ON dw.fato_atendimento (data_abertura_sk);
            CREATE INDEX IF NOT EXISTS ix_fato_avaliacao_ped ON dw.fato_avaliacao (pedido_sk);
            CREATE INDEX IF NOT EXISTS ix_fato_avaliacao_prod ON dw.fato_avaliacao (produto_sk);
            CREATE INDEX IF NOT EXISTS ix_fato_avaliacao_data ON dw.fato_avaliacao (data_sk);
        """))

    print("-> Fatos auxiliares carregados com sucesso. Executando asserções...", flush=True)

    # Asserções de integridade para dw.fato_atendimento
    df_sac = pd.read_sql("""
        SELECT 
            COUNT(*) AS total_atendimentos,
            COUNT(pedido_sk) AS com_pedido,
            COUNT(cliente_sk) AS com_cliente,
            COUNT(CASE WHEN cliente_sk = -1 THEN 1 END) AS cliente_sentinela,
            COUNT(CASE WHEN cliente_sk IS NULL THEN 1 END) AS nulos_cliente_sk,
            COUNT(CASE WHEN pedido_sk IS NULL THEN 1 END) AS nulos_pedido_sk,
            COUNT(CASE WHEN data_abertura_sk IS NULL THEN 1 END) AS nulos_data_abertura_sk,
            COUNT(DISTINCT protocolo) AS protocolos_distintos
        FROM dw.fato_atendimento;
    """, engine).iloc[0]

    qa.igual("total fato_atendimento", int(df_sac["total_atendimentos"]), 95_000,
             "Total de atendimentos unicos pos-deduplicacao deve ser 95.000")
    qa.igual("protocolos unicos fato_atendimento", int(df_sac["protocolos_distintos"]), 95_000,
             "Cada protocolo deve ser estritamente unico")
    qa.igual("atendimentos com pedido_sk", int(df_sac["com_pedido"]), 95_000,
             "100% dos atendimentos devem possuir pedido vinculado")
    qa.igual("atendimentos com cliente_sk", int(df_sac["com_cliente"]), 95_000,
             "100% dos atendimentos devem possuir cliente_sk (direto ou inferido via pedido)")
    qa.igual("nulos pedido_sk em fato_atendimento", int(df_sac["nulos_pedido_sk"]), 0,
             "Nenhum atendimento pode ter pedido_sk nulo")
    qa.igual("nulos cliente_sk em fato_atendimento", int(df_sac["nulos_cliente_sk"]), 0,
             "Nenhum atendimento pode ter cliente_sk nulo")
    qa.igual("nulos data_abertura_sk em fato_atendimento", int(df_sac["nulos_data_abertura_sk"]), 0,
             "Nenhum atendimento pode ter data_abertura_sk nula")

    # Asserções de integridade para dw.fato_avaliacao
    df_aval = pd.read_sql("""
        SELECT 
            COUNT(*) AS total_avaliacoes,
            COUNT(pedido_sk) AS com_pedido,
            COUNT(produto_sk) AS com_produto,
            COUNT(CASE WHEN pedido_sk IS NULL THEN 1 END) AS nulos_pedido_sk,
            COUNT(CASE WHEN produto_sk IS NULL THEN 1 END) AS nulos_produto_sk,
            COUNT(CASE WHEN data_sk IS NULL THEN 1 END) AS nulos_data_sk,
            COUNT(DISTINCT review_id) AS reviews_distintos
        FROM dw.fato_avaliacao;
    """, engine).iloc[0]

    qa.igual("total fato_avaliacao", int(df_aval["total_avaliacoes"]), 160_000,
             "Total de avaliacoes deve ser exatamente 160.000")
    qa.igual("reviews unicos fato_avaliacao", int(df_aval["reviews_distintos"]), 160_000,
             "Cada review_id deve ser estritamente unico")
    qa.igual("avaliacoes com pedido_sk", int(df_aval["com_pedido"]), 160_000,
             "100% das avaliacoes devem possuir pedido vinculado")
    qa.igual("avaliacoes com produto_sk", int(df_aval["com_produto"]), 160_000,
             "100% das avaliacoes devem possuir produto vinculado")
    qa.igual("nulos pedido_sk em fato_avaliacao", int(df_aval["nulos_pedido_sk"]), 0,
             "Nenhuma avaliacao pode ter pedido_sk nulo")
    qa.igual("nulos produto_sk em fato_avaliacao", int(df_aval["nulos_produto_sk"]), 0,
             "Nenhuma avaliacao pode ter produto_sk nulo")
    qa.igual("nulos data_sk em fato_avaliacao", int(df_aval["nulos_data_sk"]), 0,
             "Nenhuma avaliacao pode ter data_sk nula")

    # Validação de desambiguação sintática de produtos legados vs ecommerce
    df_sub = pd.read_sql("""
        SELECT 
            COUNT(CASE WHEN p.origem = 'LEGADO' THEN 1 END) AS aval_legado,
            COUNT(CASE WHEN p.origem = 'ECOM' THEN 1 END) AS aval_ecom
        FROM dw.fato_avaliacao fa
        JOIN dw.dim_produto p ON p.produto_sk = fa.produto_sk;
    """, engine).iloc[0]

    qa.igual("avaliacoes produtos legado conectadas", int(df_sub["aval_legado"]), 40_016,
             "40.016 avaliacoes sob mascara LEG-{id_legado} devem estar conectadas a produtos legados")
    qa.igual("avaliacoes produtos ecommerce conectadas", int(df_sub["aval_ecom"]), 119_984,
             "119.984 avaliacoes sob SKU de ecommerce devem estar conectadas a produtos ecommerce")


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
