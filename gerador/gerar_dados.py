#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador determinístico de dados para o Laboratório de ETL — Mercatto Varejo.

Produz quatro fontes heterogêneas com defeitos e ambiguidades plantados:
  1. MySQL  (loja_legado)     -> CSVs em dados/_carga/legado_*.csv
  2. Postgres (ecommerce)     -> CSVs em dados/_carga/ecom_*.csv
  3. CSV do SAC               -> dados/atendimentos_sac.csv     (latin-1, ';', vírgula decimal)
  4. JSON de avaliações       -> dados/avaliacoes_marketplace.json (NDJSON, UTF-8)

Semente fixa: todos os alunos recebem exatamente o mesmo problema.
"""

import csv
import json
import os
import random
import sys
import unicodedata
from datetime import datetime, timedelta, date

import numpy as np

SEED = 20262
rng = np.random.default_rng(SEED)
random.seed(SEED)

SAIDA = os.environ.get("DIR_DADOS", "./dados")
CARGA = os.path.join(SAIDA, "_carga")
os.makedirs(CARGA, exist_ok=True)

# Escala: 1.0 = volume padrão (~1,9 milhão de registros).
ESCALA = float(os.environ.get("ESCALA", "1.0"))

N_CLI_LEG = int(45_000 * ESCALA)
N_CLI_ECO = int(85_000 * ESCALA)
N_PROD_LEG = int(3_000 * ESCALA)
N_PROD_ECO = int(12_000 * ESCALA)
N_PED_LEG = int(130_000 * ESCALA)
N_PED_ECO = int(280_000 * ESCALA)
N_SAC = int(95_000 * ESCALA)
N_AVAL = int(160_000 * ESCALA)

# Cerca de 1/3 dos clientes do legado também existe no e-commerce.
N_SOBREPOSTOS = int(N_CLI_LEG * 0.33)

DT_INI = date(2023, 1, 1)
DT_FIM = date(2025, 12, 31)
DIAS = (DT_FIM - DT_INI).days

# --------------------------------------------------------------------------
# Vocabulário
# --------------------------------------------------------------------------
PRENOMES = """Ana Antônio Bruno Carla Carlos Cláudia Daniel Débora Eduardo Elaine
Fábio Fernanda Gabriel Gisele Gustavo Helena Igor Isabela João Joana José Júlia
Larissa Leonardo Letícia Lucas Luciana Marcelo Márcia Marcos Maria Mariana Mateus
Natália Otávio Patrícia Paulo Rafael Raquel Renata Ricardo Roberto Rodrigo Sandra
Sérgio Simone Tatiane Thiago Vanessa Vinícius Vitória Wagner Wesley Yuri Adriana
Alessandra Alexandre André Beatriz Camila César Cristiane Diego Edson Elisângela""".split()

SOBRENOMES = """Silva Santos Oliveira Souza Rodrigues Ferreira Alves Pereira Lima
Gomes Costa Ribeiro Martins Carvalho Almeida Lopes Soares Fernandes Vieira Barbosa
Rocha Dias Nascimento Andrade Moreira Nunes Marques Machado Mendes Freitas Cardoso
Ramos Gonçalves Santana Teixeira Araújo Correia Cavalcanti Monteiro Moura Batista
Bezerra Pinto Campos Cunha Duarte Fonseca Guimarães Maciel Peixoto Queiroz""".split()

CIDADES = [
    ("Cuiabá", "MT"), ("Várzea Grande", "MT"), ("Rondonópolis", "MT"), ("Sinop", "MT"),
    ("Goiânia", "GO"), ("Brasília", "DF"), ("Campo Grande", "MS"), ("São Paulo", "SP"),
    ("Campinas", "SP"), ("Ribeirão Preto", "SP"), ("Curitiba", "PR"), ("Londrina", "PR"),
    ("Porto Alegre", "RS"), ("Belo Horizonte", "MG"), ("Uberlândia", "MG"),
    ("Salvador", "BA"), ("Recife", "PE"), ("Fortaleza", "CE"), ("Belém", "PA"),
    ("Manaus", "AM"), ("Palmas", "TO"), ("Vitória", "ES"), ("Florianópolis", "SC"),
]

# Taxonomia controlada do e-commerce (id, nome, id_pai)
CATEGORIAS = [
    (1, "Eletrodomésticos", None),
    (2, "Eletroportáteis", 1),
    (3, "Linha Branca", 1),
    (4, "Informática", None),
    (5, "Notebooks", 4),
    (6, "Periféricos", 4),
    (7, "Componentes", 4),
    (8, "Games", None),
    (9, "Consoles", 8),
    (10, "Jogos", 8),
    (11, "Telefonia", None),
    (12, "Smartphones", 11),
    (13, "Acessórios de Telefonia", 11),
    (14, "Casa e Decoração", None),
    (15, "Móveis", 14),
    (16, "Cama, Mesa e Banho", 14),
    (17, "Esporte e Lazer", None),
    (18, "Ferramentas", None),
    (19, "Áudio e TV", None),
    (20, "Televisores", 19),
    (21, "Áudio", 19),
]
CAT_FOLHAS = [c[0] for c in CATEGORIAS if c[2] is not None] + [17, 18]

# Texto livre do legado -> algumas variantes mapeiam limpo, outras são ambíguas.
CATEGORIA_LEGADO = [
    "ELETRO", "Eletro", "eletrodomesticos", "ELETRODOMÉSTICOS", "Eletro-domesticos",
    "INFORMATICA", "Informática", "informatica e games", "INFO",
    "TELEFONIA", "Celulares", "CELULAR/SMARTPHONE",
    "CASA", "Casa e decoracao", "MOVEIS",
    "TV E SOM", "AUDIO/VIDEO", "Televisores",
    "ESPORTE", "Esportes e lazer", "FERRAMENTAS", "Ferramentas e construcao",
    "GAMES", "Games e consoles", "DIVERSOS", "OUTROS", "",
]

SUBSTANTIVOS_PROD = """Geladeira Fogão Micro-ondas Liquidificador Batedeira Cafeteira
Notebook Desktop Monitor Teclado Mouse Headset Impressora Roteador SSD Memória
Smartphone Fone Carregador Capa Smartwatch Televisor Soundbar Caixa Receiver
Sofá Cadeira Mesa Estante Colchão Jogo Lençol Toalha Bicicleta Esteira Halter
Furadeira Parafusadeira Serra Console Controle Headphone Cooler Fonte
Ventilador Ar-condicionado Lavadora Secadora Aspirador Purificador""".split()

MARCAS = """Volt Nexa Brava Zentro Kairo Lumix Orbis Vertex Nordic Saga Primo
Astra Veloce Mirante Kubo Trilha Aurora Delta Onix Pratic""".split()

MOTIVOS_SAC = [
    "Atraso na entrega", "ATRASO NA ENTREGA", "atraso entrega",
    "Produto avariado", "PRODUTO AVARIADO", "Produto com defeito",
    "Cancelamento a pedido do cliente", "CANCELAMENTO CLIENTE",
    "Troca de produto", "TROCA", "Devolução", "DEVOLUCAO",
    "Dúvida sobre pagamento", "Estorno não realizado", "Cobrança indevida",
    "Endereço incorreto", "Produto não recebido", "Elogio",
]

CANAIS_SAC = ["TELEFONE", "CHAT", "EMAIL", "WHATSAPP", "telefone", "chat"]

# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------
def cpf_digitos(base9):
    """Calcula os dois dígitos verificadores de um CPF a partir de 9 dígitos."""
    s = sum((10 - i) * base9[i] for i in range(9))
    d1 = 11 - s % 11
    d1 = 0 if d1 >= 10 else d1
    b10 = base9 + [d1]
    s = sum((11 - i) * b10[i] for i in range(10))
    d2 = 11 - s % 11
    d2 = 0 if d2 >= 10 else d2
    return d1, d2


def gera_cpf(valido=True):
    base = [int(x) for x in rng.integers(0, 10, 9)]
    d1, d2 = cpf_digitos(base)
    if not valido:
        # quebra o primeiro dígito verificador de forma determinística
        d1 = (d1 + 1) % 10
    return "".join(map(str, base)) + f"{d1}{d2}"


def mascara_cpf(cpf):
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def sem_acento(txt):
    return "".join(c for c in unicodedata.normalize("NFD", txt)
                   if unicodedata.category(c) != "Mn")


def nome_aleatorio():
    n = f"{random.choice(PRENOMES)} {random.choice(SOBRENOMES)} {random.choice(SOBRENOMES)}"
    return n


def data_aleatoria(n):
    """n datas uniformes no período, como array de date."""
    offs = rng.integers(0, DIAS, n)
    return [DT_INI + timedelta(days=int(o)) for o in offs]


def escreve_csv(caminho, cabecalho, linhas, encoding="utf-8", sep=",", fim_linha="\n"):
    """fim_linha='\\n' para os arquivos de carga (LOAD DATA / COPY esperam LF).
    O CSV do SAC usa '\\r\\n', como uma exportação manual de planilha faria."""
    with open(caminho, "w", newline="", encoding=encoding, errors="replace") as f:
        w = csv.writer(f, delimiter=sep, quoting=csv.QUOTE_MINIMAL,
                       lineterminator=fim_linha)
        w.writerow(cabecalho)
        w.writerows(linhas)
    return len(linhas)


def log(msg):
    print(f"[gerador] {msg}", flush=True)


# ==========================================================================
# 1. Identidades compartilhadas (a ponte entre os dois sistemas)
# ==========================================================================
log("gerando identidades...")

# Pessoas "reais". As primeiras N_SOBREPOSTOS aparecem nos dois sistemas.
N_PESSOAS = N_CLI_LEG + N_CLI_ECO - N_SOBREPOSTOS
pessoas_nome = [nome_aleatorio() for _ in range(N_PESSOAS)]
pessoas_cidade_idx = rng.integers(0, len(CIDADES), N_PESSOAS)

# ~9% das pessoas recebem CPF inválido (erro de digitação na origem)
cpf_invalido_flag = rng.random(N_PESSOAS) < 0.09
pessoas_cpf = [gera_cpf(valido=not bool(inv)) for inv in cpf_invalido_flag]

# Índices: legado usa [0 : N_CLI_LEG]; ecommerce usa os sobrepostos + novos
idx_legado = list(range(N_CLI_LEG))
idx_ecom = list(range(N_SOBREPOSTOS)) + list(range(N_CLI_LEG, N_PESSOAS))
assert len(idx_ecom) == N_CLI_ECO

# ==========================================================================
# 2. MySQL — loja_legado (latin-1, caixa alta, CPF mascarado)
# ==========================================================================
log(f"legado: {N_CLI_LEG} clientes...")

leg_clientes = []
leg_cpf_por_id = {}
dt_cad = data_aleatoria(N_CLI_LEG)
for i, p in enumerate(idx_legado):
    cid, uf = CIDADES[pessoas_cidade_idx[p]]
    nome = pessoas_nome[p].upper()
    r = rng.random()
    if r < 0.08:
        cpf_txt = ""                       # D4: CPF ausente
    elif r < 0.12:
        cpf_txt = pessoas_cpf[p]           # sem máscara (inconsistência interna)
    else:
        cpf_txt = mascara_cpf(pessoas_cpf[p])
    cidade = "N/A" if rng.random() < 0.02 else cid   # D6: sentinela textual
    email = f"{sem_acento(pessoas_nome[p].split()[0]).lower()}{i}@exemplo.com.br"
    leg_clientes.append([
        i + 1, nome, cpf_txt, email, dt_cad[i].isoformat(), cidade, uf,
        f"({rng.integers(11,99)}) 9{rng.integers(1000,9999)}-{rng.integers(1000,9999)}",
    ])
    leg_cpf_por_id[i + 1] = pessoas_cpf[p]

# D5: duplicatas exatas (2%) e near-duplicates (3%)
n_dup_exata = int(N_CLI_LEG * 0.02)
n_dup_prox = int(N_CLI_LEG * 0.03)
prox_id = N_CLI_LEG + 1
amostra_dup = rng.choice(N_CLI_LEG, n_dup_exata + n_dup_prox, replace=False)
for k, j in enumerate(amostra_dup):
    orig = leg_clientes[int(j)]
    novo = list(orig)
    novo[0] = prox_id
    if k >= n_dup_exata:                                   # near-duplicate
        novo[1] = sem_acento(novo[1]).replace("  ", " ") + " "
        if rng.random() < 0.5 and novo[2]:
            novo[2] = novo[2].replace(".", "").replace("-", "")
        else:
            novo[2] = ""
    leg_clientes.append(novo)
    leg_cpf_por_id[prox_id] = leg_cpf_por_id[int(j) + 1]
    prox_id += 1

escreve_csv(os.path.join(CARGA, "legado_clientes.csv"),
            ["ID_CLIENTE", "NOME", "CPF", "EMAIL", "DT_CADASTRO", "CIDADE", "UF", "TELEFONE"],
            leg_clientes, encoding="latin-1")
N_CLI_LEG_TOTAL = len(leg_clientes)

log(f"legado: {N_PROD_LEG} produtos...")
leg_produtos = []
for i in range(N_PROD_LEG):
    desc = f"{random.choice(SUBSTANTIVOS_PROD)} {random.choice(MARCAS)} {rng.integers(100,999)}"
    preco = round(float(rng.gamma(2.2, 160)) + 29.9, 2)
    if rng.random() < 0.0015:               # D7: outlier por erro de digitação
        preco = round(preco * 10, 2)
    leg_produtos.append([
        i + 1, desc.upper(), random.choice(CATEGORIA_LEGADO), f"{preco:.2f}",
        "S" if rng.random() < 0.88 else "N",
    ])
escreve_csv(os.path.join(CARGA, "legado_produtos.csv"),
            ["ID_PRODUTO", "DESCRICAO", "CATEGORIA", "PRECO_TABELA", "ATIVO"],
            leg_produtos, encoding="latin-1")

log(f"legado: {N_PED_LEG} pedidos...")
STATUS_LEG = np.array(["ENTREGUE", "CANCELADO", "EM TRANSITO", "SEPARACAO"])
p_status_leg = [0.78, 0.12, 0.06, 0.04]
CANAL_LEG = np.array(["LOJA", "TELEVENDAS", "SITE"])

ped_cli = rng.integers(1, N_CLI_LEG_TOTAL + 1, N_PED_LEG)
ped_dt = data_aleatoria(N_PED_LEG)
ped_status = rng.choice(STATUS_LEG, N_PED_LEG, p=p_status_leg)
ped_canal = rng.choice(CANAL_LEG, N_PED_LEG, p=[0.45, 0.20, 0.35])

leg_pedidos = []
leg_itens = []
id_item = 1
for i in range(N_PED_LEG):
    pid = i + 1
    dt = ped_dt[i]
    st = ped_status[i]
    hora = timedelta(hours=int(rng.integers(8, 22)), minutes=int(rng.integers(0, 60)))
    dt_ped = datetime.combine(dt, datetime.min.time()) + hora

    if st == "ENTREGUE":
        dt_ent = dt_ped + timedelta(days=int(rng.integers(1, 21)))
        if rng.random() < 0.008:                       # D2: entrega antes do pedido
            dt_ent = dt_ped - timedelta(days=int(rng.integers(1, 5)))
        dt_ent_txt = dt_ent.strftime("%Y-%m-%d %H:%M:%S")
        if rng.random() < 0.010:                       # D6: data-sentinela
            dt_ent_txt = "1900-01-01 00:00:00"
    else:
        dt_ent_txt = ""

    n_itens = int(rng.integers(1, 6))
    soma = 0.0
    for _ in range(n_itens):
        prod = int(rng.integers(1, N_PROD_LEG + 1))
        qtd = int(rng.integers(1, 4))
        vl = float(leg_produtos[prod - 1][3])
        vl = round(vl * float(rng.uniform(0.92, 1.05)), 2)
        desc_v = round(vl * qtd * float(rng.uniform(0, 0.12)), 2)
        if rng.random() < 0.010:
            desc_v = -1.0                              # D6: sentinela numérica
        leg_itens.append([id_item, pid, prod, qtd, f"{vl:.2f}", f"{desc_v:.2f}"])
        id_item += 1
        soma += vl * qtd - max(desc_v, 0)

    frete = round(float(rng.uniform(0, 89)), 2)
    if rng.random() < 0.003:
        frete = round(-frete, 2)                       # D3: frete negativo
    total = round(soma + frete, 2)                     # AMBIGUIDADE: inclui frete

    leg_pedidos.append([
        pid, int(ped_cli[i]), dt_ped.strftime("%Y-%m-%d %H:%M:%S"), dt_ent_txt,
        st, f"{total:.2f}", f"{frete:.2f}", ped_canal[i],
    ])

# D1: itens órfãos (~1,5%)
n_orf = int(len(leg_itens) * 0.015)
for _ in range(n_orf):
    leg_itens.append([id_item, N_PED_LEG + int(rng.integers(1, 9999)),
                      int(rng.integers(1, N_PROD_LEG + 1)), 1, "99.90", "0.00"])
    id_item += 1

escreve_csv(os.path.join(CARGA, "legado_pedidos.csv"),
            ["ID_PEDIDO", "ID_CLIENTE", "DT_PEDIDO", "DT_ENTREGA", "STATUS",
             "VALOR_TOTAL", "VALOR_FRETE", "CANAL"], leg_pedidos, encoding="latin-1")
escreve_csv(os.path.join(CARGA, "legado_itens.csv"),
            ["ID_ITEM", "ID_PEDIDO", "ID_PRODUTO", "QTD", "VL_UNITARIO", "VL_DESCONTO"],
            leg_itens, encoding="latin-1")

# ==========================================================================
# 3. PostgreSQL — ecommerce (UTF-8, taxonomia controlada, CPF limpo)
# ==========================================================================
log(f"ecommerce: {N_CLI_ECO} clientes...")

escreve_csv(os.path.join(CARGA, "ecom_category.csv"),
            ["category_id", "name", "parent_id"],
            [[c[0], c[1], "" if c[2] is None else c[2]] for c in CATEGORIAS])

eco_clientes = []
eco_cpf_por_id = {}
dt_cad_e = data_aleatoria(N_CLI_ECO)
for i, p in enumerate(idx_ecom):
    cid, uf = CIDADES[pessoas_cidade_idx[p]]
    r = rng.random()
    tax = "" if r < 0.08 else pessoas_cpf[p]            # limpo, sem máscara
    eco_clientes.append([
        i + 1, pessoas_nome[p], tax,
        f"cliente{i}@correio.com.br",
        datetime.combine(dt_cad_e[i], datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S-03"),
        cid, uf, f"+5566{rng.integers(900000000, 999999999)}",
    ])
    eco_cpf_por_id[i + 1] = pessoas_cpf[p]
escreve_csv(os.path.join(CARGA, "ecom_customer.csv"),
            ["customer_id", "full_name", "tax_id", "email", "created_at",
             "city", "state", "phone"], eco_clientes)

log(f"ecommerce: {N_PROD_ECO} produtos...")
eco_produtos = []
for i in range(N_PROD_ECO):
    titulo = f"{random.choice(SUBSTANTIVOS_PROD)} {random.choice(MARCAS)} {rng.integers(100,999)}"
    preco = round(float(rng.gamma(2.2, 170)) + 39.9, 2)
    if rng.random() < 0.0015:
        preco = round(preco * 10, 2)                   # D7
    eco_produtos.append([
        i + 1, f"SKU-{100000 + i}", titulo,
        int(random.choice(CAT_FOLHAS)), f"{preco:.2f}",
        "true" if rng.random() < 0.92 else "false",
    ])
escreve_csv(os.path.join(CARGA, "ecom_product.csv"),
            ["product_id", "sku", "title", "category_id", "list_price", "active"],
            eco_produtos)

log(f"ecommerce: {N_PED_ECO} pedidos...")
STATUS_ECO = np.array(["delivered", "canceled", "payment_declined", "shipped", "processing"])
p_status_eco = [0.74, 0.08, 0.05, 0.08, 0.05]
CANAL_ECO = np.array(["web", "app", "marketplace"])

eco_ped_cli = rng.integers(1, N_CLI_ECO + 1, N_PED_ECO)
eco_ped_dt = data_aleatoria(N_PED_ECO)
eco_status = rng.choice(STATUS_ECO, N_PED_ECO, p=p_status_eco)
eco_canal = rng.choice(CANAL_ECO, N_PED_ECO, p=[0.42, 0.40, 0.18])

eco_pedidos = []
eco_itens = []
id_item_e = 1
for i in range(N_PED_ECO):
    oid = i + 1
    hora = timedelta(hours=int(rng.integers(0, 24)), minutes=int(rng.integers(0, 60)))
    dt_ped = datetime.combine(eco_ped_dt[i], datetime.min.time()) + hora
    st = eco_status[i]

    if st == "delivered":
        dt_ent = dt_ped + timedelta(days=int(rng.integers(1, 15)))
        if rng.random() < 0.008:
            dt_ent = dt_ped - timedelta(days=int(rng.integers(1, 4)))   # D2
        dt_ent_txt = dt_ent.strftime("%Y-%m-%d %H:%M:%S-03")
    else:
        dt_ent_txt = ""

    n_itens = int(rng.integers(1, 7))
    soma = 0.0
    for _ in range(n_itens):
        prod = int(rng.integers(1, N_PROD_ECO + 1))
        qtd = int(rng.integers(1, 4))
        vl = round(float(eco_produtos[prod - 1][4]) * float(rng.uniform(0.90, 1.03)), 2)
        desc_v = round(vl * qtd * float(rng.uniform(0, 0.15)), 2)
        eco_itens.append([id_item_e, oid, prod, qtd, f"{vl:.2f}", f"{desc_v:.2f}"])
        id_item_e += 1
        soma += vl * qtd - desc_v

    frete = round(float(rng.uniform(0, 79)), 2)
    if rng.random() < 0.003:
        frete = round(-frete, 2)                       # D3
    total = round(soma, 2)                             # AMBIGUIDADE: NÃO inclui frete

    eco_pedidos.append([
        oid, int(eco_ped_cli[i]), dt_ped.strftime("%Y-%m-%d %H:%M:%S-03"), dt_ent_txt,
        st, f"{total:.2f}", f"{frete:.2f}", eco_canal[i],
    ])

n_orf_e = int(len(eco_itens) * 0.015)                  # D1
for _ in range(n_orf_e):
    eco_itens.append([id_item_e, N_PED_ECO + int(rng.integers(1, 9999)),
                      int(rng.integers(1, N_PROD_ECO + 1)), 1, "149.90", "0.00"])
    id_item_e += 1

escreve_csv(os.path.join(CARGA, "ecom_orders.csv"),
            ["order_id", "customer_id", "placed_at", "delivered_at", "status",
             "total_amount", "freight_amount", "channel"], eco_pedidos)
escreve_csv(os.path.join(CARGA, "ecom_order_item.csv"),
            ["order_item_id", "order_id", "product_id", "quantity",
             "unit_price", "discount"], eco_itens)

# ==========================================================================
# 4. CSV do SAC (latin-1, ';', vírgula decimal, dd/mm/aaaa)
# ==========================================================================
log(f"SAC: {N_SAC} atendimentos...")

sac = []
for i in range(N_SAC):
    do_legado = rng.random() < 0.38
    if do_legado:
        origem, ref = "LEGADO", int(rng.integers(1, N_PED_LEG + 1))
        cpf_src = leg_cpf_por_id.get(int(rng.integers(1, N_CLI_LEG_TOTAL + 1)), "")
    else:
        origem, ref = "ECOM", int(rng.integers(1, N_PED_ECO + 1))
        cpf_src = eco_cpf_por_id.get(int(rng.integers(1, N_CLI_ECO + 1)), "")

    ab = DT_INI + timedelta(days=int(rng.integers(0, DIAS)))
    dur_h = float(rng.gamma(2.0, 9.0))
    fe = ab + timedelta(days=int(dur_h // 24))
    if rng.random() < 0.06:
        fe_txt = ""                                    # atendimento em aberto
    else:
        fe_txt = fe.strftime("%d/%m/%Y")

    if rng.random() < 0.004:
        dur_h = -dur_h                                 # D3 (variante): duração negativa

    nota = int(rng.integers(1, 6))
    r = rng.random()
    nota_txt = "" if r < 0.09 else ("0" if r < 0.12 else str(nota))   # 0 é inválido

    motivo = random.choice(MOTIVOS_SAC)
    if rng.random() < 0.015:                           # D10: quebra de linha no campo
        motivo = motivo + "\nobs: cliente reiterou o contato"

    sac.append([
        f"P{2023000000 + i}", origem, ref,
        mascara_cpf(cpf_src) if (cpf_src and rng.random() < 0.6) else cpf_src,
        ab.strftime("%d/%m/%Y"), fe_txt,
        random.choice(CANAIS_SAC), motivo, nota_txt,
        f"{dur_h:.2f}".replace(".", ","),              # vírgula decimal
    ])

n_dup_sac = int(N_SAC * 0.012)                          # D8: linhas repetidas
for j in rng.choice(N_SAC, n_dup_sac, replace=False):
    sac.append(list(sac[int(j)]))

escreve_csv(
    os.path.join(SAIDA, "atendimentos_sac.csv"),
    ["protocolo", "origem_sistema", "id_pedido_origem", "cpf_cliente",
     "data_abertura", "data_fechamento", "canal", "motivo",
     "nota_satisfacao", "tempo_resolucao_horas"],
    sac, encoding="latin-1", sep=";", fim_linha="\r\n",
)

# ==========================================================================
# 5. JSON de avaliações do marketplace (NDJSON, UTF-8, esquema irregular)
# ==========================================================================
log(f"avaliações: {N_AVAL} registros...")

TITULOS = ["Muito bom", "Recomendo", "Deixou a desejar", "Excelente custo-benefício",
           "Não era o que eu esperava", "Chegou antes do prazo", "Produto de qualidade",
           "Veio com defeito", "Atendeu às expectativas", "Péssimo"]
COMENTARIOS = ["Entrega rápida e produto conforme o anúncio.",
               "O produto é bom, mas a embalagem chegou amassada.",
               "Já é a segunda vez que compro, sempre satisfeito.",
               "Demorou mais do que o informado no site.",
               "Custo-benefício excelente para o que eu precisava.",
               "Não recomendo, apresentou problema em uma semana."]

with open(os.path.join(SAIDA, "avaliacoes_marketplace.json"), "w", encoding="utf-8") as f:
    for i in range(N_AVAL):
        do_legado = rng.random() < 0.25
        if do_legado:
            ref = f"LEG-{int(rng.integers(1, N_PED_LEG + 1))}"
            sku = f"LEG-{int(rng.integers(1, N_PROD_LEG + 1))}"
        else:
            ref = f"ECOM-{int(rng.integers(1, N_PED_ECO + 1))}"
            sku = f"SKU-{100000 + int(rng.integers(0, N_PROD_ECO))}"

        dt = datetime.combine(DT_INI + timedelta(days=int(rng.integers(0, DIAS))),
                              datetime.min.time()) + timedelta(
                                  hours=int(rng.integers(0, 24)),
                                  minutes=int(rng.integers(0, 60)))
        # D: timestamp ora com fuso, ora sem
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S-03:00") if rng.random() < 0.8 \
            else dt.strftime("%Y-%m-%dT%H:%M:%S")

        reg = {
            "review_id": f"RV{900000 + i}",
            "order": {"ref": ref, "channel": "marketplace"},
            "product": {"sku": sku},
            "submitted_at": ts,
        }
        r = rng.random()
        if r < 0.10:
            reg["rating"] = str(int(rng.integers(1, 6)))   # D11: nota como string
        elif r < 0.13:
            pass                                           # nota ausente (chave omitida)
        else:
            reg["rating"] = int(rng.integers(1, 6))

        if rng.random() < 0.85:
            reg["title"] = random.choice(TITULOS)
        if rng.random() < 0.70:
            reg["comment"] = random.choice(COMENTARIOS)
        if rng.random() < 0.90:
            reg["verified_purchase"] = bool(rng.random() < 0.8)
        if rng.random() < 0.55:
            reg["helpful_votes"] = int(rng.integers(0, 40))

        f.write(json.dumps(reg, ensure_ascii=False) + "\n")

# ==========================================================================
# Resumo
# ==========================================================================
resumo = {
    "semente": SEED,
    "escala": ESCALA,
    "legado_clientes": N_CLI_LEG_TOTAL,
    "legado_produtos": len(leg_produtos),
    "legado_pedidos": len(leg_pedidos),
    "legado_itens": len(leg_itens),
    "ecom_clientes": len(eco_clientes),
    "ecom_produtos": len(eco_produtos),
    "ecom_pedidos": len(eco_pedidos),
    "ecom_itens": len(eco_itens),
    "sac_linhas": len(sac),
    "avaliacoes": N_AVAL,
    "clientes_sobrepostos": N_SOBREPOSTOS,
}
resumo["total_registros"] = sum(v for k, v in resumo.items()
                                if k not in ("semente", "escala", "clientes_sobrepostos"))
with open(os.path.join(SAIDA, "_resumo_geracao.json"), "w", encoding="utf-8") as f:
    json.dump(resumo, f, ensure_ascii=False, indent=2)

log("concluído:")
for k, v in resumo.items():
    log(f"  {k:24s} {v}")
