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

    clientes_legado = clientes_legado.rename(columns={
        'id': 'id_legado',
        'nome': 'nome_cliente'
    })

    # Tratamento de CPF e dos nomes dos clientes
    clientes_legado["cpf_limpo"] = clientes_legado["cpf"].apply(so_digitos)
    clientes_legado["cpf_valido"] = clientes_legado["cpf_limpo"].apply(cpf_valido)
    clientes_legado["nome_normalizado"] = clientes_legado["nome_cliente"].apply(normaliza_nome)
    
    clientes_ecom["cpf_limpo"] = clientes_ecom["tax_id"].apply(so_digitos)
    clientes_ecom["cpf_valido"] = clientes_ecom["cpf_limpo"].apply(cpf_valido)
    clientes_ecom["nome_normalizado"] = clientes_ecom["full_name"].apply(normaliza_nome)

    # Tratamento das duplicatas internas do legado (ordem decrescente de cadastro)
    clientes_legado = clientes_legado.sort_values(by="dt_cadastro", ascending=False)
    duplicatas_legado = clientes_legado.duplicated(subset=["cpf_limpo"]).sum()

    legado_val = clientes_legado[clientes_legado["cpf_valido"] == True].drop_duplicates(subset=["cpf_limpo"], keep="first")
    ecom_val = clientes_ecom[clientes_ecom["cpf_valido"] == True].drop_duplicates(subset=["cpf_limpo"], keep="first")

    # Cruzamento principal por CPF Válido
    cruzamento_cpf = pd.merge(
        legado_val, ecom_val, 
        on="cpf_limpo", how="outer", suffixes=('_leg', '_ecom')
    )

    def define_origem(row):
        id_l = row.get('id_legado')
        id_e = row.get('id_ecommerce')
        
        if pd.notna(id_l) and pd.notna(id_e):
            return 'AMBOS'
        elif pd.notna(id_l):
            return 'LEGADO'
        else:
            return 'ECOM'

    cruzamento_cpf['origem_unificacao'] = cruzamento_cpf.apply(define_origem, axis=1)
    cruzamento_cpf['regra_pareamento'] = 'CPF_VALIDO'

    # Resolução do nome padronizado (prioriza e-commerce, senão legado, senão fallback)
    cruzamento_cpf['nome_padronizado'] = cruzamento_cpf['nome_normalizado_ecom'].fillna(
        cruzamento_cpf['nome_normalizado_leg']
    ).fillna('DESCONHECIDO')

    # Montagem do DataFrame final da dimensão contemplando as colunas do DDL
    dim_cliente = pd.DataFrame({
        'id_legado': cruzamento_cpf.get('id_legado'),
        'id_ecommerce': cruzamento_cpf.get('id_ecommerce'),
        'cpf_normalizado': cruzamento_cpf['cpf_limpo'],
        'nome_padronizado': cruzamento_cpf['nome_padronizado'],
        'origem_unificacao': cruzamento_cpf['origem_unificacao'],
        'regra_pareamento': cruzamento_cpf['regra_pareamento']
    })

    # Remove linhas onde o CPF ficou nulo/vazio
    dim_cliente = dim_cliente.dropna(subset=['cpf_normalizado'])
    dim_cliente = dim_cliente[dim_cliente['cpf_normalizado'] != ""]

    print(f"-> Total de clientes unificados estruturados: {len(dim_cliente)}")

    print("-> Persistindo dim_cliente no DW de forma segura (Staging + UPSERT)...")

    # Grava na staging temporária do DW
    dim_cliente.to_sql(
        "temp_dim_cliente", 
        dw, 
        schema="dw", 
        if_exists="replace", 
        index=False
    )

    # Executa o UPDATE + INSERT (Anti-Join UPSERT) preservando as 15 FKs e o DDL intocado
    upsert_sql = text("""
        -- Atualiza registros existentes
        UPDATE dw.dim_cliente AS dest
        SET 
            id_legado = NULLIF(src.id_legado::text, '')::integer,
            id_ecommerce = NULLIF(src.id_ecommerce::text, '')::bigint,
            nome_padronizado = src.nome_padronizado,
            origem_unificacao = src.origem_unificacao,
            regra_pareamento = src.regra_pareamento
        FROM dw.temp_dim_cliente AS src
        WHERE dest.cpf_normalizado = src.cpf_normalizado;

        -- Insere registros novos
        INSERT INTO dw.dim_cliente (
            id_legado, 
            id_ecommerce, 
            cpf_normalizado, 
            nome_padronizado,
            origem_unificacao, 
            regra_pareamento
        )
        SELECT 
            NULLIF(id_legado::text, '')::integer, 
            NULLIF(id_ecommerce::text, '')::bigint, 
            src.cpf_normalizado, 
            src.nome_padronizado,
            src.origem_unificacao, 
            src.regra_pareamento
        FROM dw.temp_dim_cliente AS src
        WHERE NOT EXISTS (
            SELECT 1 FROM dw.dim_cliente dest 
            WHERE dest.cpf_normalizado = src.cpf_normalizado
        );

        -- Limpeza da tabela temporária de staging
        DROP TABLE IF EXISTS dw.temp_dim_cliente;
    """)

    with dw.begin() as conn:
        conn.execute(upsert_sql)

    # Bloco de validação
    print("-> Verificando dados gravados em dw.dim_cliente...")
    df_verificacao = pd.read_sql("SELECT * FROM dw.dim_cliente LIMIT 5", dw)
    print(df_verificacao)

    df_resumo = pd.read_sql("""
        SELECT origem_unificacao, regra_pareamento, COUNT(*) as total 
        FROM dw.dim_cliente 
        GROUP BY origem_unificacao, regra_pareamento
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
    # TODO 2.2
    raise NotImplementedErro



# ===========================================================================
# DECISÃO 3 — SEMÂNTICA DOS VALORES MONETÁRIOS
# ===========================================================================
def conforma_valores(qa):
    """
    VALOR_TOTAL (legado) e total_amount (e-commerce) NÃO medem a mesma coisa.
    Descubra a diferença comparando cada um com a soma dos itens do pedido —
    o dicionário de dados não diz, porque na vida real ele também não diria.

    Depois, preencha dw.fato_pedido com medidas explicitamente definidas:
        valor_mercadoria  (sem frete, sem desconto)
        valor_frete
        valor_desconto
        valor_total = mercadoria + frete - desconto

    Trate também:
      · frete negativo (o que é? estorno? erro? decida e registre);
      · desconto = -1 no legado (sentinela, não valor);
      · preços com magnitude 10x acima da mediana da categoria (digitação).
        Atenção: nem todo valor alto é erro. Qual é o seu critério?
    """
    # TODO 2.3
    raise NotImplementedError


# ===========================================================================
# DECISÃO 4 — TAXONOMIA DE PRODUTO
# ===========================================================================
def conforma_categorias(qa):
    """
    O legado guarda categoria como texto livre ('ELETRO', 'Eletro-domesticos',
    'informatica e games', 'DIVERSOS', ''); o e-commerce tem taxonomia de dois
    níveis. Construa o mapeamento.

    Casos que não têm solução limpa — e é esse o ponto:
      · 'informatica e games' cobre dois ramos distintos da taxonomia;
      · 'DIVERSOS', 'OUTROS' e '' não informam nada;
      · 'TV E SOM' cobre dois filhos de 'Áudio e TV'.

    Mantenha categoria_origem preenchida com o valor bruto. Conformar não
    autoriza apagar a evidência do que havia antes.
    """
    # TODO 2.4



# ===========================================================================
# DECISÃO 5 — DATAS, AUSÊNCIAS E SENTINELAS
# ===========================================================================
def trata_datas_e_ausencias(qa):
    """
    Antes de imputar qualquer coisa, classifique cada ausência:
      · não coletada          (o sistema nunca teve o dado)
      · não aplicável         (pedido cancelado não tem data de entrega)
      · sentinela             ('1900-01-01', 'N/A', -1)
    As três exigem tratamentos diferentes e NENHUMA delas é "preencher com a
    média". Documente a classificação de cada campo.

    Trate ainda:
      · DT_ENTREGA anterior a DT_PEDIDO;
      · TIMESTAMPTZ do e-commerce x DATETIME sem fuso do legado — padronize
        e diga em qual fuso;
      · data_fechamento vazia no SAC (atendimento em aberto x dado perdido).
    """
    # TODO 2.5
    raise NotImplementedError


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
    # conforma_status(qa)
    # conforma_valores(qa)
    # conforma_categorias(qa)
    # trata_datas_e_ausencias(qa)
    # liga_sac_e_avaliacoes(qa)

    # TODO 2.7 — asserções obrigatórias desta etapa:
    #   · dim_cliente sem cpf_normalizado duplicado entre linhas com CPF válido;
    #   · toda linha de dim_cliente tem origem_unificacao em {LEGADO,ECOM,AMBOS};
    #   · nenhuma junção multiplicou linhas (use qa.cardinalidade_preservada);
    #   · soma de valor_mercadoria por pedido bate com a soma dos itens (±0,01).

    qa.registrar(eng_dw())
    if qa.imprimir():
        print("Há asserções em falha. Isso não impede seguir, mas precisa "
              "aparecer no RDT com explicação.")
