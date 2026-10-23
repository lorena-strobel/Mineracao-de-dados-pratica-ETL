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
    # TODO 3.2 — dw.fato_pedido.
    #            Atenção especial às chaves: como mapear id_origem para as SKs?
    #            E o que fazer com os pedidos que referenciam clientes que não
    #            estão na dimensão (se houver)? Ver RDT-12.
    #
    # Dica RDT-12: o que significa, conceitualmente, um pedido cujo
    #            ID_CLIENTE não existe em CLIENTES? Um cliente "DESCONHECIDO"
    #            na dimensão é a solução clássica. Adote-a ou justifique outra.

    print("-> Carregando dw.fato_pedido...")
    dw = eng_dw()
    
    # Carrega pedidos da staging
    df_pedidos = pd.read_sql("SELECT * FROM stg.pedidos_valores_conformados", dw)
    
    # Carrega as tabelas de dimensão
    df_status = pd.read_sql("SELECT status_sk, status_origem, sistema FROM dw.dim_status", dw)
    df_canal = pd.read_sql("SELECT canal_sk, canal_origem, sistema FROM dw.dim_canal", dw)
    df_cliente = pd.read_sql("SELECT cliente_sk, id_legado, id_ecommerce FROM dw.dim_cliente", dw)
    
    # Cruzamento de Status e Canal (padronizando 'ECOMMERCE' para 'ECOM')
    df_status["sistema_origem"] = df_status["sistema"].replace({"ECOMMERCE": "ECOM"})
    df_canal["sistema_origem"] = df_canal["sistema"].replace({"ECOMMERCE": "ECOM"})
    
    df_pedidos = df_pedidos.merge(
        df_status[["status_sk", "status_origem", "sistema_origem"]],
        on=["status_origem", "sistema_origem"],
        how="left"
    )
    df_pedidos = df_pedidos.merge(
        df_canal[["canal_sk", "canal_origem", "sistema_origem"]],
        on=["canal_origem", "sistema_origem"],
        how="left"
    )
    
    # Cruzamento de Cliente (Legado e E-commerce) via mapa direto
    mapa_leg = df_cliente.dropna(subset=["id_legado"]).set_index(df_cliente["id_legado"].dropna().astype("int64"))["cliente_sk"]
    mapa_ecom = df_cliente.dropna(subset=["id_ecommerce"]).set_index(df_cliente["id_ecommerce"].dropna().astype("int64"))["cliente_sk"]
    
    df_pedidos["cliente_sk"] = None
    df_pedidos.loc[df_pedidos["sistema_origem"] == "LEGADO", "cliente_sk"] = df_pedidos["id_cliente_origem"].map(mapa_leg)
    df_pedidos.loc[df_pedidos["sistema_origem"] == "ECOM", "cliente_sk"] = df_pedidos["id_cliente_origem"].map(mapa_ecom)
    
    # Cliente sentinela para pedidos sem cliente (RDT-12)
    with dw.connect() as cx:
        res = cx.execute(text("SELECT cliente_sk FROM dw.dim_cliente WHERE nome_padronizado = 'CLIENTE DESCONHECIDO'")).fetchone()
        sk_desconhecido = res[0] if res else None
        
    if sk_desconhecido is not None:
        df_pedidos["cliente_sk"] = df_pedidos["cliente_sk"].infer_objects(copy=False).fillna(sk_desconhecido).astype("int64")
    else:
        print("   [INFO] 'CLIENTE DESCONHECIDO' ainda não cadastrado em dw.dim_cliente (aguardando RDT-12 do colega).")

    # Formatação de datas e prazos de entrega
    df_pedidos["data_pedido_sk"] = pd.to_datetime(df_pedidos["dt_pedido_conformada"]).dt.date
    df_pedidos["data_entrega_sk"] = pd.to_datetime(df_pedidos["dt_entrega_conformada"]).dt.date
    df_pedidos["dias_entrega"] = df_pedidos["dias_entrega"].round().astype("Int64")
    
    # Seleção das colunas exatas e gravação no DW
    colunas_fato = [
        "id_origem", "sistema_origem", "cliente_sk", "data_pedido_sk", 
        "data_entrega_sk", "canal_sk", "status_sk", "qtd_itens", 
        "valor_mercadoria", "valor_frete", "valor_desconto", "valor_total", "dias_entrega"
    ]
    df_fato = df_pedidos[colunas_fato]
    
    with dw.begin() as conn:
        conn.execute(text("TRUNCATE dw.fato_pedido RESTART IDENTITY CASCADE;"))
    
    df_fato.to_sql("fato_pedido", dw, schema="dw", if_exists="append", index=False, chunksize=10_000)
    print(f"-> fato_pedido carregada com sucesso: {len(df_fato)} pedidos.")


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

    # TODO 3.5 — asserções obrigatórias:
    #   · nenhuma FK órfã em fato_pedido (cliente_sk, data_pedido_sk, canal_sk);
    #   · contagem de fato_pedido == pedidos válidos nas duas origens somados;
    #   · SUM(valor_total) por sistema_origem dentro de ±0,1% do total da origem
    #     (reconciliação financeira: é assim que se prova que a carga não mentiu);
    #   · nenhum pedido com dias_entrega negativo depois do tratamento.

    df_fato = pd.read_sql("SELECT * FROM dw.fato_pedido", dw)
    df_stg = pd.read_sql("SELECT sistema_origem, valor_total FROM stg.pedidos_valores_conformados", dw)

    # Contagem do Grão (len do DataFrame)
    qa.igual("contagem fato_pedido", len(df_fato), 410_000, "Exatamente 410.000 pedidos carregados")

    # Nenhuma FK órfã / nula (usando qa.sem_nulos nativo com Series do Pandas)
    qa.sem_nulos("cliente_sk sem nulos", df_fato["cliente_sk"])
    qa.igual("pedidos cliente desconhecido consolidado", int((df_fato["cliente_sk"] == -1).sum()), 38_699, "Total sentinela deve ser 38.699 (RDT-12)")
    qa.sem_nulos("data_pedido_sk sem nulos", df_fato["data_pedido_sk"])
    qa.sem_nulos("canal_sk sem nulos", df_fato["canal_sk"])
    qa.sem_nulos("status_sk sem nulos", df_fato["status_sk"])

    # Reconciliação Financeira (groupby e sum direto no Pandas)
    soma_dw = df_fato.groupby("sistema_origem")["valor_total"].sum()
    soma_stg = df_stg.groupby("sistema_origem")["valor_total"].sum()
    desvio_leg = abs(soma_dw["LEGADO"] - soma_stg["LEGADO"]) / soma_stg["LEGADO"] * 100
    desvio_ecom = abs(soma_dw["ECOM"] - soma_stg["ECOM"]) / soma_stg["ECOM"] * 100
    qa.entre("reconciliacao legado", float(desvio_leg), 0.0, 0.1, "desvio <= 0,1%")
    qa.entre("reconciliacao ecom", float(desvio_ecom), 0.0, 0.1, "desvio <= 0,1%")

    # Prazos de entrega válidos (dropna e min no Pandas)
    menor_prazo = df_fato["dias_entrega"].dropna().min()
    qa.maior_igual("menor dias_entrega", float(menor_prazo), 0.0, "nenhum prazo de entrega negativo")
    qa.registrar(dw)
    qa.imprimir()
