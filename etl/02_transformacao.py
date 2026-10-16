#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 2 — TRANSFORMAÇÃO E CONFORMAÇÃO  (esqueleto: vocês completam)

Esta é a etapa epistemicamente densa. Cada bloco abaixo corresponde a uma
decisão que NÃO tem resposta única. Para cada uma, o RDT deve trazer:
    (a) as alternativas consideradas;
    (b) a escolhida e por quê;
    (c) o que se perde com ela;
    (d) o número de registros afetados.

Uma decisão sem (c) e (d) não conta como decisão registrada.

    docker compose exec etl python 02_transformacao.py
"""

import re
import unicodedata

import pandas as pd
from sqlalchemy import text

from config import eng_dw
from qualidade.assercoes import Suite


# ---------------------------------------------------------------------------
# Utilitários que vocês vão precisar — estes estão prontos.
# ---------------------------------------------------------------------------
def so_digitos(txt):
    return re.sub(r"\D", "", txt or "")


def cpf_valido(cpf):
    """Valida os dois dígitos verificadores. Retorna None se não tiver 11 dígitos."""
    c = so_digitos(cpf)
    if len(c) != 11 or len(set(c)) == 1:
        return None if len(c) != 11 else False
    b = [int(x) for x in c]
    s = sum((10 - i) * b[i] for i in range(9))
    d1 = 0 if (11 - s % 11) >= 10 else (11 - s % 11)
    s = sum((11 - i) * (b[:9] + [d1])[i] for i in range(10))
    d2 = 0 if (11 - s % 11) >= 10 else (11 - s % 11)
    return b[9] == d1 and b[10] == d2


def normaliza_nome(nome):
    """MAIÚSCULAS sem acento, espaços colapsados. Base para pareamento aproximado."""
    n = unicodedata.normalize("NFD", (nome or "").strip().upper())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", n)


# ===========================================================================
# DECISÃO 1 — IDENTIDADE DO CLIENTE ENTRE OS DOIS SISTEMAS
# ===========================================================================
def unifica_clientes(qa):
    """
    O CPF é a única ponte direta entre legado e e-commerce, mas:
      · parte dos CPFs está ausente nas duas origens;
      · parte tem dígito verificador inválido;
      · no legado ele aparece ora com máscara, ora sem;
      · o legado ainda contém duplicatas exatas e aproximadas do mesmo cliente.

    Perguntas que sua regra precisa responder — e o RDT, justificar:
      a) CPF com dígito verificador inválido serve para parear? Ele identifica
         de forma tão estável quanto um válido, mesmo estando errado?
      b) Sem CPF, você pareia por nome normalizado + cidade + UF? Qual a taxa
         de falsos positivos que isso introduz? Estime-a.
      c) Qual erro é mais grave aqui: fundir dois clientes distintos, ou manter
         duplicado um mesmo cliente? A resposta muda conforme o uso do dado.
      d) Como você trata as duplicatas INTERNAS do legado antes de cruzar?

    Preencha dim_cliente com o rastro: id_legado, id_ecommerce,
    origem_unificacao e regra_pareamento (que regra uniu cada par).
    """
    print("-> Unifica Clientes...", flush=True)
    dw = eng_dw()
    
    clientes_legado = pd.read_sql("SELECT * FROM stg.legado_clientes", dw)
    clientes_ecom = pd.read_sql("SELECT * FROM stg.ecommerce_customer", dw)

    clientes_legado.columns = [c.lower() for c in clientes_legado.columns]
    clientes_ecom.columns = [c.lower() for c in clientes_ecom.columns]

    # Renomeia com os nomes REAIS das colunas da staging
    clientes_legado = clientes_legado.rename(columns={
        'id_cliente': 'id_legado',
        'nome': 'nome_cliente'
    })
    clientes_ecom = clientes_ecom.rename(columns={
        'customer_id': 'id_ecommerce',
        'full_name': 'nome_cliente',
        'city': 'cidade',
        'state': 'uf'
    })

    # ratamento de CPF e nomes
    clientes_legado["cpf_limpo"] = clientes_legado["cpf"].apply(so_digitos)
    clientes_legado["cpf_valido"] = clientes_legado["cpf_limpo"].apply(cpf_valido)
    clientes_legado["nome_normalizado"] = clientes_legado["nome_cliente"].apply(normaliza_nome)
    
    clientes_ecom["cpf_limpo"] = clientes_ecom["tax_id"].apply(so_digitos)
    clientes_ecom["cpf_valido"] = clientes_ecom["cpf_limpo"].apply(cpf_valido)
    clientes_ecom["nome_normalizado"] = clientes_ecom["nome_cliente"].apply(normaliza_nome)

    # Tratamento de datas de cadastro para pegar a primeira
    clientes_legado["dt_cadastro"] = pd.to_datetime(clientes_legado["dt_cadastro"], errors="coerce")
    clientes_ecom["dt_cadastro"] = pd.to_datetime(clientes_ecom["created_at"], errors="coerce").dt.tz_localize(None)

    # Tratamento das duplicatas internas do legado (ordem decrescente de cadastro)
    clientes_legado = clientes_legado.sort_values(by="dt_cadastro", ascending=False)
    duplicatas_legado = clientes_legado.duplicated(subset=["cpf_limpo"]).sum()

    # Consideranod clientes com CPF de 11 dígitos (válidos e com dígito com erro propagado)
    legado_val = clientes_legado[clientes_legado["cpf_limpo"].str.len() == 11].drop_duplicates(subset=["cpf_limpo"], keep="first")
    ecom_val = clientes_ecom[clientes_ecom["cpf_limpo"].str.len() == 11].drop_duplicates(subset=["cpf_limpo"], keep="first")

    # Cruzamento por CPF
    cruzamento_cpf = pd.merge(
        legado_val, ecom_val, 
        on="cpf_limpo", how="outer", suffixes=('_leg', '_ecom')
    )

    # Define a procedência do cliente
    def define_origem(row):
        tem_l = pd.notna(row.get('id_legado'))
        tem_e = pd.notna(row.get('id_ecommerce'))
        if tem_l and tem_e:
            return 'AMBOS'
        elif tem_l:
            return 'LEGADO'
        else:
            return 'ECOM'

    cruzamento_cpf['origem_unificacao'] = cruzamento_cpf.apply(define_origem, axis=1)

    # Regra de pareamento: se o dígito verificador confere em ambos/um deles
    cruzamento_cpf['cpf_valido'] = (cruzamento_cpf['cpf_valido_ecom'] == True) | (cruzamento_cpf['cpf_valido_leg'] == True)
    cruzamento_cpf['regra_pareamento'] = cruzamento_cpf['cpf_valido'].apply(
        lambda v: 'CPF_VALIDO' if v else 'CPF_DIGITO_INVALIDO'
    )

    # Consolida nome, cidade, uf e primeira data de cadastro
    cruzamento_cpf['nome_padronizado'] = cruzamento_cpf['nome_normalizado_ecom'].fillna(
        cruzamento_cpf['nome_normalizado_leg']
    ).fillna('DESCONHECIDO')
    
    cruzamento_cpf['cidade'] = cruzamento_cpf['cidade_ecom'].fillna(cruzamento_cpf['cidade_leg'])
    cruzamento_cpf['uf'] = cruzamento_cpf['uf_ecom'].fillna(cruzamento_cpf['uf_leg'])
    
    # Menor data de cadastro entre os dois sistemas
    cruzamento_cpf['dt_primeiro_cadastro'] = cruzamento_cpf[['dt_cadastro_leg', 'dt_cadastro_ecom']].min(axis=1).dt.date

    # Montagem do DataFrame contemplando todas as colunas
    dim_cliente = pd.DataFrame({
        'id_legado': cruzamento_cpf['id_legado'],
        'id_ecommerce': cruzamento_cpf['id_ecommerce'],
        'cpf_normalizado': cruzamento_cpf['cpf_limpo'],
        'cpf_valido': cruzamento_cpf['cpf_valido'],
        'nome_padronizado': cruzamento_cpf['nome_padronizado'],
        'cidade': cruzamento_cpf['cidade'],
        'uf': cruzamento_cpf['uf'],
        'dt_primeiro_cadastro': cruzamento_cpf['dt_primeiro_cadastro'],
        'origem_unificacao': cruzamento_cpf['origem_unificacao'],
        'regra_pareamento': cruzamento_cpf['regra_pareamento']
    })

    # Remove linhas sem CPF
    dim_cliente = dim_cliente.dropna(subset=['cpf_normalizado'])
    dim_cliente = dim_cliente[dim_cliente['cpf_normalizado'] != ""]

    print(f"-> Total de clientes unificados estruturados: {len(dim_cliente)}")
    print("-> Gravando dw.dim_cliente...")

    # Grava na staging temporária
    dim_cliente.to_sql(
        "temp_dim_cliente", 
        dw, 
        schema="dw", 
        if_exists="replace", 
        index=False
    )

    # Atualizando e inserindo todas as colunas
    upsert_sql = text("""
        UPDATE dw.dim_cliente AS dest
        SET 
            id_legado = NULLIF(src.id_legado::text, '')::integer,
            id_ecommerce = NULLIF(src.id_ecommerce::text, '')::bigint,
            cpf_valido = src.cpf_valido::boolean,
            nome_padronizado = src.nome_padronizado,
            cidade = src.cidade,
            uf = src.uf,
            dt_primeiro_cadastro = src.dt_primeiro_cadastro::date,
            origem_unificacao = src.origem_unificacao,
            regra_pareamento = src.regra_pareamento
        FROM dw.temp_dim_cliente AS src
        WHERE dest.cpf_normalizado = src.cpf_normalizado;

        INSERT INTO dw.dim_cliente (
            id_legado, 
            id_ecommerce, 
            cpf_normalizado,
            cpf_valido, 
            nome_padronizado,
            cidade,
            uf,
            dt_primeiro_cadastro,
            origem_unificacao, 
            regra_pareamento
        )
        SELECT 
            NULLIF(id_legado::text, '')::integer, 
            NULLIF(id_ecommerce::text, '')::bigint, 
            src.cpf_normalizado,
            src.cpf_valido::boolean,
            src.nome_padronizado,
            src.cidade,
            src.uf,
            src.dt_primeiro_cadastro::date,
            src.origem_unificacao, 
            src.regra_pareamento
        FROM dw.temp_dim_cliente AS src
        WHERE NOT EXISTS (
            SELECT 1 FROM dw.dim_cliente dest 
            WHERE dest.cpf_normalizado = src.cpf_normalizado
        );

        DROP TABLE IF EXISTS dw.temp_dim_cliente;
    """)

    with dw.begin() as conn:
        conn.execute(upsert_sql)

    # Asserções obrigatórias
    qa.sem_nulos("nome_padronizado preenchido", dim_cliente["nome_padronizado"])
    qa.dominio("origem_unificacao valida", dim_cliente["origem_unificacao"], {"LEGADO", "ECOM", "AMBOS"})

    # Resumo
    df_resumo = pd.read_sql("""
        SELECT origem_unificacao, regra_pareamento, COUNT(*) as total 
        FROM dw.dim_cliente 
        GROUP BY origem_unificacao, regra_pareamento
        ORDER BY origem_unificacao, regra_pareamento
    """, dw)
    print("\nResumo da unificação:")
    print(df_resumo)
    print(f"-> Duplicatas internas removidas no legado: {duplicatas_legado}")

# ===========================================================================
# DECISÃO 2 — CONFORMAÇÃO DE STATUS
# ===========================================================================
def conforma_status(qa):
    """
    Legado:      ENTREGUE · CANCELADO · EM TRANSITO · SEPARACAO
    E-commerce:  delivered · canceled · payment_declined · shipped · processing

    O legado agrega em CANCELADO duas situações que o e-commerce separa:
    cancelamento pelo cliente e recusa de pagamento.

    Alternativas, todas defensáveis:
      (i)   mapear payment_declined -> CANCELADO. Simples; perde a distinção
            justamente onde ela existe.
      (ii)  criar CANCELADO_CLIENTE e CANCELADO_PAGAMENTO, deixando o legado
            com motivo NULL. Preserva a informação; cria assimetria que precisa
            ser tratada por qualquer análise posterior.
      (iii) criar um nível hierárquico: status_conformado = CANCELADO e
            motivo_cancelamento preenchido apenas quando conhecido.

    Escolha e preencha dw.dim_status. Registre quantos pedidos caem em cada
    célula do mapeamento — esse número é parte da justificativa.
    """
    print("-> Conforma Status...", flush=True)
    dw = eng_dw()

    dados_status = [

        # Legado
        {"status_origem": "ENTREGUE", "sistema": "LEGADO", "status_conformado": "ENTREGUE", "motivo_cancelamento": None},
        {"status_origem": "EM TRANSITO", "sistema": "LEGADO", "status_conformado": "EM_TRANSITO", "motivo_cancelamento": None},
        {"status_origem": "SEPARACAO", "sistema": "LEGADO", "status_conformado": "PROCESSAMENTO", "motivo_cancelamento": None},
        {"status_origem": "CANCELADO", "sistema": "LEGADO", "status_conformado": "CANCELADO", "motivo_cancelamento": None},

        # E-commerce
        {"status_origem": "delivered", "sistema": "ECOMMERCE", "status_conformado": "ENTREGUE", "motivo_cancelamento": None},
        {"status_origem": "shipped", "sistema": "ECOMMERCE", "status_conformado": "EM_TRANSITO", "motivo_cancelamento": None},
        {"status_origem": "processing", "sistema": "ECOMMERCE", "status_conformado": "PROCESSAMENTO", "motivo_cancelamento": None},
        {"status_origem": "canceled", "sistema": "ECOMMERCE", "status_conformado": "CANCELADO", "motivo_cancelamento": "DESISTENCIA_CLIENTE"},
        {"status_origem": "payment_declined", "sistema": "ECOMMERCE", "status_conformado": "CANCELADO", "motivo_cancelamento": "RECUSA_PAGAMENTO"}
    ]
    
    df_status = pd.DataFrame(dados_status)

    # Gravação na dimensão
    with dw.begin() as conn:
        conn.execute(text("TRUNCATE dw.dim_status RESTART IDENTITY CASCADE;"))
    
    df_status.to_sql("dim_status", dw, schema="dw", if_exists="append", index=False)
    print("-> Gravando dw.dim_status...")

    # Contagem de pedidos por status para subsidiar o RDT-04
    pedidos_leg = pd.read_sql('SELECT "STATUS" as status_origem, COUNT(*) as qtd_pedidos FROM stg.legado_pedidos GROUP BY "STATUS"', dw)
    pedidos_leg["sistema"] = "LEGADO"
    pedidos_ecom = pd.read_sql("SELECT status as status_origem, COUNT(*) as qtd_pedidos FROM stg.ecommerce_orders GROUP BY status", dw)
    pedidos_ecom["sistema"] = "ECOMMERCE"
    df_qtd = pd.concat([pedidos_leg, pedidos_ecom], ignore_index=True)
    resumo = pd.merge(df_status, df_qtd, on=["status_origem", "sistema"], how="left")
    
    print("\nResumo da conformação de status:")
    print(resumo[["sistema", "status_origem", "status_conformado", "motivo_cancelamento", "qtd_pedidos"]])
    # Asserções de Qualidade
    qa.sem_nulos("status_conformado preenchido", df_status["status_conformado"])
    qa.dominio("status_conformado valido", df_status["status_conformado"], {"ENTREGUE", "CANCELADO", "EM_TRANSITO", "PROCESSAMENTO"})
    qa.igual("total de regras dim_status", len(df_status), 9)



# ===========================================================================
# DECISÃO 3 — SEMÂNTICA DOS VALORES MONETÁRIOS
# ===========================================================================
def conforma_valores(qa):
    print("-> Conformando semântica de valores monetários (Decisão 3 / RDT-05 & RDT-06)...", flush=True)
    dw = eng_dw()

    with dw.begin() as conn:
        # 1. Conformação dos itens de pedidos
        conn.execute(text("""
            DROP TABLE IF EXISTS stg.itens_valores_conformados CASCADE;
            CREATE TABLE stg.itens_valores_conformados AS
            SELECT 
                'LEG-' || "ID_ITEM"::text as id_item_origem,
                'LEG-' || "ID_PEDIDO"::text as id_pedido_origem,
                'LEGADO' as sistema_origem,
                "ID_PRODUTO" as id_produto_origem,
                "QTD"::int as quantidade,
                "VL_UNITARIO"::numeric(12,2) as valor_unitario,
                (CASE WHEN "VL_DESCONTO" = -1 THEN 0 ELSE "VL_DESCONTO" END)::numeric(12,2) as valor_desconto,
                (("VL_UNITARIO" * "QTD") - CASE WHEN "VL_DESCONTO" = -1 THEN 0 ELSE "VL_DESCONTO" END)::numeric(12,2) as valor_linha,
                ("VL_DESCONTO" = -1) as flag_desconto_sentinela
            FROM stg.legado_itens_pedido
            UNION ALL
            SELECT 
                'ECOM-' || order_item_id::text as id_item_origem,
                'ECOM-' || order_id::text as id_pedido_origem,
                'ECOM' as sistema_origem,
                product_id as id_produto_origem,
                quantity::int as quantidade,
                unit_price::numeric(12,2) as valor_unitario,
                discount::numeric(12,2) as valor_desconto,
                ((unit_price * quantity) - discount)::numeric(12,2) as valor_linha,
                false as flag_desconto_sentinela
            FROM stg.ecommerce_order_item;

            CREATE INDEX IF NOT EXISTS ix_item_conf_ped ON stg.itens_valores_conformados (id_pedido_origem, sistema_origem);
        """))

        # 2. Conformação dos cabeçalhos de pedidos com medidas canônicas
        conn.execute(text("""
            DROP TABLE IF EXISTS stg.pedidos_valores_conformados CASCADE;
            CREATE TABLE stg.pedidos_valores_conformados AS
            WITH itens_leg AS (
                SELECT 
                    "ID_PEDIDO",
                    COUNT(*)::int as qtd_itens,
                    SUM("VL_UNITARIO" * "QTD")::numeric(12,2) as valor_mercadoria,
                    SUM(CASE WHEN "VL_DESCONTO" = -1 THEN 0 ELSE "VL_DESCONTO" END)::numeric(12,2) as valor_desconto,
                    BOOL_OR("VL_DESCONTO" = -1) as flag_desconto_sentinela
                FROM stg.legado_itens_pedido
                GROUP BY "ID_PEDIDO"
            ),
            p_leg AS (
                SELECT 
                    'LEG-' || p."ID_PEDIDO"::text as id_origem,
                    'LEGADO' as sistema_origem,
                    p."ID_PEDIDO" as id_pedido_origem,
                    p."ID_CLIENTE" as id_cliente_origem,
                    (p."DT_PEDIDO" AT TIME ZONE 'America/Sao_Paulo') as dt_pedido_origem,
                    (CASE WHEN p."DT_ENTREGA" IS NOT NULL THEN p."DT_ENTREGA" AT TIME ZONE 'America/Sao_Paulo' ELSE NULL END) as dt_entrega_origem,
                    p."CANAL" as canal_origem,
                    p."STATUS" as status_origem,
                    COALESCE(i.qtd_itens, 0) as qtd_itens,
                    COALESCE(i.valor_mercadoria, 0.00) as valor_mercadoria,
                    GREATEST(0, p."VALOR_FRETE")::numeric(12,2) as valor_frete,
                    COALESCE(i.valor_desconto, 0.00) as valor_desconto,
                    (COALESCE(i.valor_mercadoria, 0.00) + GREATEST(0, p."VALOR_FRETE") - COALESCE(i.valor_desconto, 0.00))::numeric(12,2) as valor_total,
                    (p."VALOR_FRETE" < 0) as flag_frete_negativo,
                    COALESCE(i.flag_desconto_sentinela, false) as flag_desconto_sentinela
                FROM stg.legado_pedidos p
                LEFT JOIN itens_leg i ON p."ID_PEDIDO" = i."ID_PEDIDO"
            ),
            itens_ecom AS (
                SELECT 
                    order_id,
                    COUNT(*)::int as qtd_itens,
                    SUM(unit_price * quantity)::numeric(12,2) as valor_mercadoria,
                    SUM(discount)::numeric(12,2) as valor_desconto
                FROM stg.ecommerce_order_item
                GROUP BY order_id
            ),
            p_ecom AS (
                SELECT 
                    'ECOM-' || o.order_id::text as id_origem,
                    'ECOM' as sistema_origem,
                    o.order_id as id_pedido_origem,
                    o.customer_id as id_cliente_origem,
                    o.placed_at as dt_pedido_origem,
                    o.delivered_at as dt_entrega_origem,
                    o.channel as canal_origem,
                    o.status as status_origem,
                    COALESCE(i.qtd_itens, 0) as qtd_itens,
                    COALESCE(i.valor_mercadoria, 0.00) as valor_mercadoria,
                    GREATEST(0, o.freight_amount)::numeric(12,2) as valor_frete,
                    COALESCE(i.valor_desconto, 0.00) as valor_desconto,
                    (COALESCE(i.valor_mercadoria, 0.00) + GREATEST(0, o.freight_amount) - COALESCE(i.valor_desconto, 0.00))::numeric(12,2) as valor_total,
                    (o.freight_amount < 0) as flag_frete_negativo,
                    false as flag_desconto_sentinela
                FROM stg.ecommerce_orders o
                LEFT JOIN itens_ecom i ON o.order_id = i.order_id
            )
            SELECT * FROM p_leg
            UNION ALL
            SELECT * FROM p_ecom;

            CREATE INDEX IF NOT EXISTS ix_ped_conf_origem ON stg.pedidos_valores_conformados (id_origem, sistema_origem);
        """))

    # 3. Asserções de qualidade da Decisão 3 (RDT-05 e RDT-06)
    with dw.connect() as cx:
        df_contagens = pd.read_sql("""
            SELECT 
                sistema_origem,
                COUNT(*) as total_pedidos,
                SUM(CASE WHEN ABS(valor_total - (valor_mercadoria + valor_frete - valor_desconto)) > 0.01 THEN 1 ELSE 0 END) as divergencias_algebraicas,
                SUM(CASE WHEN valor_total IS NULL THEN 1 ELSE 0 END) as nulos_total,
                MIN(valor_total) as menor_total
            FROM stg.pedidos_valores_conformados
            GROUP BY sistema_origem
        """, cx)

        df_check_itens = pd.read_sql("""
            WITH agg_itens AS (
                SELECT 
                    id_pedido_origem,
                    sistema_origem,
                    SUM(quantidade * valor_unitario)::numeric(12,2) as soma_itens_mercadoria
                FROM stg.itens_valores_conformados
                GROUP BY id_pedido_origem, sistema_origem
            )
            SELECT 
                COUNT(*) as total_comparados,
                SUM(CASE WHEN ABS(p.valor_mercadoria - i.soma_itens_mercadoria) > 0.01 THEN 1 ELSE 0 END) as divergencias_itens
            FROM stg.pedidos_valores_conformados p
            JOIN agg_itens i ON p.id_origem = i.id_pedido_origem AND p.sistema_origem = i.sistema_origem
        """, cx)

        df_rdt06_pedidos = pd.read_sql("""
            SELECT 
                COUNT(*) as total_pedidos,
                MIN(valor_frete) as menor_frete,
                MIN(valor_desconto) as menor_desconto_pedido,
                SUM(CASE WHEN flag_frete_negativo THEN 1 ELSE 0 END) as total_frete_negativo,
                SUM(CASE WHEN sistema_origem = 'LEGADO' AND flag_frete_negativo THEN 1 ELSE 0 END) as frete_negativo_legado,
                SUM(CASE WHEN sistema_origem = 'ECOM' AND flag_frete_negativo THEN 1 ELSE 0 END) as frete_negativo_ecom,
                SUM(CASE WHEN flag_desconto_sentinela THEN 1 ELSE 0 END) as pedidos_com_sentinela
            FROM stg.pedidos_valores_conformados
        """, cx)

        df_rdt06_itens = pd.read_sql("""
            SELECT 
                COUNT(*) as total_itens,
                MIN(valor_desconto) as menor_desconto_item,
                SUM(CASE WHEN valor_desconto = -1 THEN 1 ELSE 0 END) as itens_com_menos_um,
                SUM(CASE WHEN flag_desconto_sentinela THEN 1 ELSE 0 END) as itens_flag_sentinela
            FROM stg.itens_valores_conformados
        """, cx)

    leg_row = df_contagens[df_contagens["sistema_origem"] == "LEGADO"].iloc[0]
    ecom_row = df_contagens[df_contagens["sistema_origem"] == "ECOM"].iloc[0]

    # Asserções RDT-05 (Decomposição Canônica e Aditividade)
    qa.igual("pedidos conformados legado", int(leg_row["total_pedidos"]), 130000, "130.000 pedidos do legado conformados")
    qa.igual("pedidos conformados ecommerce", int(ecom_row["total_pedidos"]), 280000, "280.000 pedidos do ecommerce conformados")
    qa.igual("identidade contábil valor_total", int(df_contagens["divergencias_algebraicas"].sum()), 0, "valor_total = mercadoria + frete - desconto para 100% dos pedidos")
    qa.igual("valor_total sem nulos", int(df_contagens["nulos_total"].sum()), 0, "Nenhum pedido pode ter valor_total nulo")
    qa.maior_igual("valor_total positivo", float(df_contagens["menor_total"].min()), 0.0, "Todos os pedidos devem ter valor_total positivo")
    qa.igual("soma de mercadoria bate com itens", int(df_check_itens["divergencias_itens"].iloc[0]), 0, "Soma de valor_mercadoria por pedido bate com a soma dos itens (±0,01)")

    # Asserções RDT-06 (Frete Negativo e Desconto Sentinela -1)
    qa.maior_igual("frete não negativo dw", float(df_rdt06_pedidos["menor_frete"].iloc[0]), 0.0, "Nenhum pedido no DW pode conter frete negativo")
    qa.maior_igual("desconto não negativo itens", float(df_rdt06_itens["menor_desconto_item"].iloc[0]), 0.0, "Nenhum item no DW pode conter desconto negativo")
    qa.igual("desconto sem sentinela menos um", int(df_rdt06_itens["itens_com_menos_um"].iloc[0]), 0, "Nenhum item pode conter o sentinela -1 como desconto")
    qa.igual("quantificacao frete negativo consolidado", int(df_rdt06_pedidos["total_frete_negativo"].iloc[0]), 1174, "Exatamente 1.174 pedidos com frete negativo truncado para 0.00")
    qa.igual("quantificacao frete negativo legado", int(df_rdt06_pedidos["frete_negativo_legado"].iloc[0]), 362, "Exatamente 362 pedidos do legado com frete negativo")
    qa.igual("quantificacao frete negativo ecom", int(df_rdt06_pedidos["frete_negativo_ecom"].iloc[0]), 812, "Exatamente 812 pedidos do e-commerce com frete negativo")
    qa.igual("quantificacao desconto sentinela itens", int(df_rdt06_itens["itens_flag_sentinela"].iloc[0]), 4056, "Exatamente 4.056 itens do legado marcados com flag_desconto_sentinela")
    qa.igual("quantificacao desconto sentinela pedidos", int(df_rdt06_pedidos["pedidos_com_sentinela"].iloc[0]), 4003, "Exatamente 4.003 pedidos do legado contêm itens com flag_desconto_sentinela")



# ===========================================================================
# DECISÃO 4 — TAXONOMIA DE PRODUTO
# ===========================================================================
def conforma_categorias(qa):
    print("-> Conformando taxonomia de categorias de produto (Decisão 4 / RDT-07)...", flush=True)
    dw = eng_dw()

    with dw.begin() as conn:
        conn.execute(text("TRUNCATE TABLE dw.dim_produto RESTART IDENTITY CASCADE;"))

        # 1. Inserção dos produtos conformados do E-commerce
        conn.execute(text("""
            INSERT INTO dw.dim_produto (
                sku,
                descricao,
                categoria_nivel1,
                categoria_nivel2,
                categoria_origem,
                preco_referencia,
                ativo,
                id_legado,
                id_ecommerce,
                origem
            )
            SELECT 
                pr.sku,
                pr.title as descricao,
                COALESCE(pai.name, c.name) as categoria_nivel1,
                CASE WHEN pai.name IS NOT NULL THEN c.name ELSE 'Geral' END as categoria_nivel2,
                c.name as categoria_origem,
                pr.list_price::numeric(12,2) as preco_referencia,
                pr.active as ativo,
                NULL::int as id_legado,
                pr.product_id as id_ecommerce,
                'ECOM' as origem
            FROM stg.ecommerce_product pr
            JOIN stg.ecommerce_category c ON pr.category_id = c.category_id
            LEFT JOIN stg.ecommerce_category pai ON c.parent_id = pai.category_id;
        """))

        # 2. Inserção dos produtos conformados do ERP Legado
        conn.execute(text("""
            INSERT INTO dw.dim_produto (
                sku,
                descricao,
                categoria_nivel1,
                categoria_nivel2,
                categoria_origem,
                preco_referencia,
                ativo,
                id_legado,
                id_ecommerce,
                origem
            )
            SELECT 
                NULL as sku,
                "DESCRICAO" as descricao,
                CASE 
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('GELADEIRA', 'FOGÃO', 'LAVADORA', 'SECADORA', 'MICRO-ONDAS', 'AR-CONDICIONADO') THEN 'Eletrodomésticos'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('LIQUIDIFICADOR', 'BATEDEIRA', 'CAFETEIRA', 'ASPIRADOR', 'VENTILADOR', 'PURIFICADOR') THEN 'Eletrodomésticos'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('NOTEBOOK', 'DESKTOP', 'MONITOR', 'TECLADO', 'MOUSE', 'HEADSET', 'IMPRESSORA', 'ROTEADOR', 'SSD', 'MEMÓRIA', 'COOLER', 'FONTE') THEN 'Informática'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('CONSOLE', 'CONTROLE', 'JOGO') THEN 'Games'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('SMARTPHONE', 'FONE', 'CARREGADOR', 'CAPA', 'SMARTWATCH') THEN 'Telefonia'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('SOFÁ', 'CADEIRA', 'MESA', 'ESTANTE', 'COLCHÃO', 'LENÇOL', 'TOALHA') THEN 'Casa e Decoração'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('BICICLETA', 'ESTEIRA', 'HALTER') THEN 'Esporte e Lazer'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('FURADEIRA', 'PARAFUSADEIRA', 'SERRA') THEN 'Ferramentas'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('TELEVISOR', 'SOUNDBAR', 'CAIXA', 'RECEIVER', 'HEADPHONE') THEN 'Áudio e TV'
                    ELSE 'Outros'
                END as categoria_nivel1,
                CASE 
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('GELADEIRA', 'FOGÃO', 'LAVADORA', 'SECADORA', 'MICRO-ONDAS', 'AR-CONDICIONADO') THEN 'Linha Branca'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('LIQUIDIFICADOR', 'BATEDEIRA', 'CAFETEIRA', 'ASPIRADOR', 'VENTILADOR', 'PURIFICADOR') THEN 'Eletroportáteis'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('NOTEBOOK') THEN 'Notebooks'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('MONITOR', 'TECLADO', 'MOUSE', 'HEADSET', 'IMPRESSORA', 'ROTEADOR') THEN 'Periféricos'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('DESKTOP', 'SSD', 'MEMÓRIA', 'COOLER', 'FONTE') THEN 'Componentes'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('CONSOLE', 'CONTROLE') THEN 'Consoles'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('JOGO') THEN 'Jogos'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('SMARTPHONE') THEN 'Smartphones'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('FONE', 'CARREGADOR', 'CAPA', 'SMARTWATCH') THEN 'Acessórios de Telefonia'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('SOFÁ', 'CADEIRA', 'MESA', 'ESTANTE') THEN 'Móveis'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('COLCHÃO', 'LENÇOL', 'TOALHA') THEN 'Cama, Mesa e Banho'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('BICICLETA', 'ESTEIRA', 'HALTER') THEN 'Geral'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('FURADEIRA', 'PARAFUSADEIRA', 'SERRA') THEN 'Geral'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('TELEVISOR') THEN 'Televisores'
                    WHEN SPLIT_PART(UPPER("DESCRICAO"), ' ', 1) IN ('SOUNDBAR', 'CAIXA', 'RECEIVER', 'HEADPHONE') THEN 'Áudio'
                    ELSE 'Geral'
                END as categoria_nivel2,
                COALESCE("CATEGORIA", '') as categoria_origem,
                "PRECO_TABELA"::numeric(12,2) as preco_referencia,
                ("ATIVO" = 'S') as ativo,
                "ID_PRODUTO" as id_legado,
                NULL::bigint as id_ecommerce,
                'LEGADO' as origem
            FROM stg.legado_produtos;
        """))

    # 3. Asserções de qualidade da Decisão 4 (RDT-07)
    with dw.connect() as cx:
        df_qa_prod = pd.read_sql("""
            SELECT 
                COUNT(*) as total_produtos,
                SUM(CASE WHEN origem = 'LEGADO' THEN 1 ELSE 0 END) as total_legado,
                SUM(CASE WHEN origem = 'ECOM' THEN 1 ELSE 0 END) as total_ecom,
                SUM(CASE WHEN categoria_nivel1 IS NULL OR TRIM(categoria_nivel1) = '' THEN 1 ELSE 0 END) as nulos_nivel1,
                SUM(CASE WHEN categoria_nivel2 IS NULL OR TRIM(categoria_nivel2) = '' THEN 1 ELSE 0 END) as nulos_nivel2,
                SUM(CASE WHEN categoria_origem IS NULL THEN 1 ELSE 0 END) as nulos_origem,
                COUNT(DISTINCT categoria_nivel1) as qtd_nivel1_distintos,
                COUNT(DISTINCT categoria_nivel2) as qtd_nivel2_distintos
            FROM dw.dim_produto
        """, cx)

        df_check_pares = pd.read_sql("""
            WITH pares_ecom AS (
                SELECT DISTINCT categoria_nivel1, categoria_nivel2
                FROM dw.dim_produto
                WHERE origem = 'ECOM'
            ),
            pares_leg AS (
                SELECT DISTINCT categoria_nivel1, categoria_nivel2
                FROM dw.dim_produto
                WHERE origem = 'LEGADO'
            )
            SELECT COUNT(*) as pares_legado_invalidos
            FROM pares_leg l
            LEFT JOIN pares_ecom e 
                ON l.categoria_nivel1 = e.categoria_nivel1 
               AND l.categoria_nivel2 = e.categoria_nivel2
            WHERE e.categoria_nivel1 IS NULL
        """, cx)

    total_prods = int(df_qa_prod["total_produtos"].iloc[0])
    total_leg = int(df_qa_prod["total_legado"].iloc[0])
    total_ecom = int(df_qa_prod["total_ecom"].iloc[0])
    nulos_n1 = int(df_qa_prod["nulos_nivel1"].iloc[0])
    nulos_n2 = int(df_qa_prod["nulos_nivel2"].iloc[0])
    nulos_orig = int(df_qa_prod["nulos_origem"].iloc[0])
    pares_invalidos = int(df_check_pares["pares_legado_invalidos"].iloc[0])

    qa.igual("total produtos dw", total_prods, 15000, "15.000 produtos no catálogo unificado de dw.dim_produto")
    qa.igual("produtos origem legado", total_leg, 3000, "3.000 produtos oriundos do ERP Legado")
    qa.igual("produtos origem ecom", total_ecom, 12000, "12.000 produtos oriundos do E-commerce")
    qa.igual("categoria_nivel1 sem nulos", nulos_n1, 0, "Nenhum produto pode ter categoria_nivel1 nula ou vazia")
    qa.igual("categoria_nivel2 sem nulos", nulos_n2, 0, "Nenhum produto pode ter categoria_nivel2 nula ou vazia")
    qa.igual("categoria_origem preservada", nulos_orig, 0, "Evidência de categoria_origem preservada em 100% dos produtos")
    qa.igual("taxonomia conforme ecommerce", pares_invalidos, 0, "Todos os pares taxonômicos do legado pertencem à taxonomia válida do e-commerce")


# ===========================================================================
# DECISÃO 5 — DATAS, AUSÊNCIAS E SENTINELAS
# ===========================================================================
def trata_datas_e_ausencias(qa):
    print("-> Tratando datas, ausências, sentinelas e fuso horário UTC (Decisão 5 / RDT-08 & RDT-09)...", flush=True)
    dw = eng_dw()

    with dw.begin() as conn:
        # 1. Enriquecimento da tabela de pedidos conformados com datas saneadas e flags de anomalia
        conn.execute(text("""
            ALTER TABLE stg.pedidos_valores_conformados 
                ADD COLUMN IF NOT EXISTS dt_pedido_conformada TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS dt_entrega_conformada TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS flag_entrega_sem_data BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS flag_entrega_inconsistente BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS dias_entrega NUMERIC(10,2);

            UPDATE stg.pedidos_valores_conformados
            SET 
                dt_pedido_conformada = dt_pedido_origem,
                flag_entrega_sem_data = (dt_entrega_origem IS NOT NULL AND dt_entrega_origem < '1950-01-01'),
                flag_entrega_inconsistente = (dt_entrega_origem IS NOT NULL AND dt_entrega_origem >= '1950-01-01' AND dt_entrega_origem < dt_pedido_origem),
                dt_entrega_conformada = CASE 
                    WHEN dt_entrega_origem IS NULL THEN NULL
                    WHEN dt_entrega_origem < '1950-01-01' THEN NULL
                    WHEN dt_entrega_origem < dt_pedido_origem THEN NULL
                    ELSE dt_entrega_origem
                END,
                dias_entrega = CASE 
                    WHEN dt_entrega_origem IS NOT NULL 
                     AND dt_entrega_origem >= '1950-01-01' 
                     AND dt_entrega_origem >= dt_pedido_origem 
                    THEN ROUND(EXTRACT(EPOCH FROM (dt_entrega_origem - dt_pedido_origem)) / 86400.0, 2)
                    ELSE NULL
                END;
        """))

    # 2. Asserções de qualidade da Decisão 5 (RDT-08 e RDT-09)
    with dw.connect() as cx:
        df_qa_datas = pd.read_sql("""
            SELECT 
                COUNT(*) as total_pedidos,
                SUM(CASE WHEN dt_pedido_conformada IS NULL THEN 1 ELSE 0 END) as nulos_dt_pedido,
                SUM(CASE WHEN dt_pedido_conformada <= '2025-06-30 23:59:59+00' THEN 1 ELSE 0 END) as pedidos_ate_corte,
                SUM(CASE WHEN dt_pedido_conformada > '2025-06-30 23:59:59+00' THEN 1 ELSE 0 END) as pedidos_pos_corte,
                SUM(CASE WHEN sistema_origem = 'LEGADO' AND dt_pedido_conformada <= '2025-06-30 23:59:59+00' THEN 1 ELSE 0 END) as leg_ate_corte,
                SUM(CASE WHEN sistema_origem = 'ECOM' AND dt_pedido_conformada <= '2025-06-30 23:59:59+00' THEN 1 ELSE 0 END) as ecom_ate_corte,
                SUM(CASE WHEN flag_entrega_sem_data THEN 1 ELSE 0 END) as sentinela_1900,
                SUM(CASE WHEN flag_entrega_inconsistente THEN 1 ELSE 0 END) as invertidas_total,
                SUM(CASE WHEN sistema_origem = 'LEGADO' AND flag_entrega_inconsistente THEN 1 ELSE 0 END) as invertidas_legado,
                SUM(CASE WHEN sistema_origem = 'ECOM' AND flag_entrega_inconsistente THEN 1 ELSE 0 END) as invertidas_ecom,
                SUM(CASE WHEN dt_entrega_conformada < '1950-01-01' THEN 1 ELSE 0 END) as sentinelas_remanescentes,
                SUM(CASE WHEN dt_entrega_conformada < dt_pedido_conformada THEN 1 ELSE 0 END) as invertidas_remanescentes,
                MIN(dias_entrega) as menor_prazo,
                MAX(dias_entrega) as maior_prazo,
                SUM(CASE WHEN dt_entrega_conformada IS NOT NULL AND status_origem NOT IN ('ENTREGUE', 'delivered') THEN 1 ELSE 0 END) as entregas_status_indevido
            FROM stg.pedidos_valores_conformados
        """, cx)

    tot_ped = int(df_qa_datas["total_pedidos"].iloc[0])
    nulos_dt_ped = int(df_qa_datas["nulos_dt_pedido"].iloc[0])
    ped_ate_corte = int(df_qa_datas["pedidos_ate_corte"].iloc[0])
    ped_pos_corte = int(df_qa_datas["pedidos_pos_corte"].iloc[0])
    leg_corte = int(df_qa_datas["leg_ate_corte"].iloc[0])
    ecom_corte = int(df_qa_datas["ecom_ate_corte"].iloc[0])
    sent_1900 = int(df_qa_datas["sentinela_1900"].iloc[0])
    inv_tot = int(df_qa_datas["invertidas_total"].iloc[0])
    inv_leg = int(df_qa_datas["invertidas_legado"].iloc[0])
    inv_ecom = int(df_qa_datas["invertidas_ecom"].iloc[0])
    sent_rem = int(df_qa_datas["sentinelas_remanescentes"].iloc[0])
    inv_rem = int(df_qa_datas["invertidas_remanescentes"].iloc[0])
    menor_p = float(df_qa_datas["menor_prazo"].iloc[0]) if df_qa_datas["menor_prazo"].iloc[0] is not None else 0.0
    status_indev = int(df_qa_datas["entregas_status_indevido"].iloc[0])

    # Asserções RDT-08 (Sentinela 1900, Inversão Temporal e Integridade de Ausências)
    qa.igual("sem sentinela 1900 dw", sent_rem, 0, "Nenhuma data de entrega no DW pode conter sentinela 1900-01-01")
    qa.igual("prazo entrega nao negativo", inv_rem, 0, "Nenhum pedido pode ter entrega anterior à compra")
    qa.igual("quantificacao sentinela 1900", sent_1900, 1025, "Exatamente 1.025 pedidos com sentinela 1900-01-01 marcados com flag")
    qa.igual("quantificacao inversao temporal total", inv_tot, 2458, "Exatamente 2.458 pedidos com inversão temporal marcados com flag")
    qa.igual("quantificacao inversao temporal legado", inv_leg, 775, "Exatamente 775 pedidos do legado com entrega invertida")
    qa.igual("quantificacao inversao temporal ecom", inv_ecom, 1683, "Exatamente 1.683 pedidos do e-commerce com entrega invertida")
    qa.maior_igual("menor prazo de entrega valido", menor_p, 0.0, "O menor prazo de entrega válido deve ser maior ou igual a zero")
    qa.igual("ausencias estruturais preservadas", status_indev, 0, "Pedidos não entregues não podem possuir data de entrega conformada")

    # Asserções RDT-09 (Padronização Temporal em UTC e Alinhamento do Corte Preditivo)
    qa.igual("dt_pedido sem nulos", nulos_dt_ped, 0, "100% dos pedidos devem possuir dt_pedido_conformada preenchida")
    qa.igual("pedidos conformados ate corte utc", ped_ate_corte, 341546, "Exatamente 341.546 pedidos até 2025-06-30 23:59:59 UTC (108.059 legado + 233.487 ecom)")
    qa.igual("pedidos conformados pos corte utc", ped_pos_corte, 68454, "Exatamente 68.454 pedidos pós corte temporal no DW (21.941 legado + 46.513 ecom)")
    qa.igual("alinhamento legado ate corte", leg_corte, 108059, "Exatamente 108.059 pedidos do legado até a data de corte UTC (11 pedidos noturnos realocados pós-corte)")



# ===========================================================================
# DECISÃO 6 — CHAVES DAS FONTES DE ARQUIVO
# ===========================================================================
def liga_sac_e_avaliacoes(qa):
    """
    SAC:        chave composta (origem_sistema, id_pedido_origem) + cpf_cliente
    Avaliações: order.ref no formato 'LEG-<id>' ou 'ECOM-<id>'

    Quantos atendimentos e avaliações conseguem ser ligados a um pedido do DW?
    O que fazer com os que não conseguem — descartar, ou manter com pedido_sk
    nulo? A resposta depende da pergunta analítica; a sua é a recompra.
    """
    # TODO 2.6
    raise NotImplementedError


if __name__ == "__main__":
    qa = Suite(etapa="02_transformacao")
    unifica_clientes(qa)
    conforma_status(qa)
    # conforma_valores(qa)
    # conforma_categorias(qa)
    # trata_datas_e_ausencias(qa)
    # liga_sac_e_avaliacoes(qa)

    # TODO 2.7 — asserções obrigatórias desta etapa:
    #   · dim_cliente sem cpf_normalizado duplicado entre linhas com CPF válido;
    #   · toda linha de dim_cliente tem origem_unificacao em {LEGADO,ECOM,AMBOS};
    #   · nenhuma junção multiplicou linhas (use qa.cardinalidade_preservada);
    #   · soma de valor_mercadoria por pedido bate com a soma dos itens (±0,01).

    # dim_cliente sem CPF dupplicado dentre os válidos
    dw = eng_dw()
    df_cpfs_validos = pd.read_sql("SELECT cpf_normalizado FROM dw.dim_cliente WHERE cpf_valido = true", dw)
    qa.unico("cpf valido unico em dim_cliente", df_cpfs_validos["cpf_normalizado"])

    status_mapeados = set(pd.read_sql("SELECT status_origem FROM dw.dim_status", dw)["status_origem"])
    status_pedidos_leg = set(pd.read_sql('SELECT DISTINCT "STATUS" FROM stg.legado_pedidos', dw)["STATUS"])
    status_pedidos_ecom = set(pd.read_sql("SELECT DISTINCT status FROM stg.ecommerce_orders", dw)["status"])
    status_sem_regra = (status_pedidos_leg | status_pedidos_ecom) - status_mapeados
    qa.igual("cobertura total de status dos pedidos", len(status_sem_regra), 0, "todos os status de pedidos devem ter regra mapeada")

    qa.registrar(eng_dw())

    if qa.imprimir():
        print("Há asserções em falha. Isso não impede seguir, mas precisa "
              "aparecer no RDT com explicação.")
