#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 0 — PERFILAMENTO DAS FONTES (data profiling)

Este script está COMPLETO e serve de modelo. Rode-o antes de escrever
qualquer linha de transformação: ele produz o retrato inicial das quatro
fontes, que é o insumo do Relatório de Diagnóstico da Semana 1.

    docker compose exec etl python 00_perfilamento.py

Saída: /saida/perfilamento_<fonte>.md e um resumo no terminal.

O que ele NÃO faz: julgar. Perfilar é descrever o que existe. Decidir o que
fazer com o que existe é a etapa seguinte, e é sua.
"""

import json
import os
import re
from collections import Counter

import pandas as pd
from sqlalchemy import text

from config import (ARQ_AVALIACOES, ARQ_SAC, DIR_SAIDA,
                    eng_mysql, eng_origem)

os.makedirs(DIR_SAIDA, exist_ok=True)
pd.set_option("display.width", 160)


def secao(titulo):
    print("\n" + "=" * 72)
    print(titulo)
    print("=" * 72)


def perfil_coluna(serie):
    """Retrato de uma coluna: preenchimento, cardinalidade, extremos."""
    n = len(serie)
    nulos = int(serie.isna().sum())
    vazios = int((serie.astype(str).str.strip() == "").sum()) if serie.dtype == object else 0
    d = {
        "linhas": n,
        "nulos": nulos,
        "%_nulos": round(100 * nulos / n, 2) if n else 0,
        "vazios": vazios,
        "distintos": int(serie.nunique(dropna=True)),
    }
    if pd.api.types.is_numeric_dtype(serie):
        d["min"] = serie.min()
        d["max"] = serie.max()
        d["media"] = round(float(serie.mean()), 2) if n else None
        d["negativos"] = int((serie < 0).sum())
    else:
        top = serie.dropna().astype(str).value_counts().head(3)
        d["mais_frequentes"] = "; ".join(f"{k} ({v})" for k, v in top.items())
        comp = serie.dropna().astype(str).str.len()
        d["tam_min"] = int(comp.min()) if len(comp) else None
        d["tam_max"] = int(comp.max()) if len(comp) else None
    return d


def perfila_dataframe(df, nome):
    linhas = []
    for col in df.columns:
        p = perfil_coluna(df[col])
        p["coluna"] = col
        p["tipo"] = str(df[col].dtype)
        linhas.append(p)
    perfil = pd.DataFrame(linhas).set_index("coluna")
    print(f"\n--- {nome} ({len(df)} linhas) ---")
    print(perfil.to_string())
    return perfil


def salva(nome, blocos):
    caminho = os.path.join(DIR_SAIDA, f"perfilamento_{nome}.md")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(f"# Perfilamento — {nome}\n\n")
        for titulo, df in blocos:
            f.write(f"## {titulo}\n\n")
            f.write(df.to_markdown())
            f.write("\n\n")
    print(f"\n>> gravado em {caminho}")


# ===========================================================================
# 1. MySQL legado
# ===========================================================================
secao("FONTE 1 — MySQL · loja_legado")
eng = eng_mysql()
blocos = []
with eng.connect() as cx:
    for tabela in ["CLIENTES", "PRODUTOS", "PEDIDOS", "ITENS_PEDIDO"]:
        # amostra grande o suficiente para o perfil, pequena o bastante para a RAM
        df = pd.read_sql(text(f"SELECT * FROM {tabela} LIMIT 200000"), cx)
        blocos.append((tabela, perfila_dataframe(df, f"legado.{tabela}")))

    print("\n· distribuição de STATUS:")
    print(pd.read_sql(text(
        "SELECT STATUS, COUNT(*) n FROM PEDIDOS GROUP BY STATUS ORDER BY n DESC"),
        cx).to_string(index=False))

    print("\n· valores distintos de CATEGORIA (texto livre):")
    print(pd.read_sql(text(
        "SELECT CATEGORIA, COUNT(*) n FROM PRODUTOS GROUP BY CATEGORIA "
        "ORDER BY n DESC"), cx).to_string(index=False))

    print("\n· formatos de CPF encontrados:")
    print(pd.read_sql(text("""
        SELECT CASE
                 WHEN CPF IS NULL OR CPF = ''        THEN 'ausente'
                 WHEN CPF LIKE '%.%'                 THEN 'com máscara'
                 ELSE 'somente dígitos'
               END AS formato,
               COUNT(*) n
        FROM CLIENTES GROUP BY formato"""), cx).to_string(index=False))
salva("legado", blocos)

# ===========================================================================
# 2. PostgreSQL e-commerce
# ===========================================================================
secao("FONTE 2 — PostgreSQL · shop")
engo = eng_origem()
blocos = []
with engo.connect() as cx:
    for tabela in ["customer", "product", "orders", "order_item"]:
        df = pd.read_sql(text(f"SELECT * FROM shop.{tabela} LIMIT 200000"), cx)
        blocos.append((tabela, perfila_dataframe(df, f"shop.{tabela}")))

    print("\n· distribuição de status:")
    print(pd.read_sql(text(
        "SELECT status, COUNT(*) n FROM shop.orders GROUP BY status ORDER BY n DESC"),
        cx).to_string(index=False))

    print("\n· taxonomia de categorias:")
    print(pd.read_sql(text("""
        SELECT c.category_id, c.name, p.name AS pai
        FROM shop.category c LEFT JOIN shop.category p ON p.category_id = c.parent_id
        ORDER BY COALESCE(c.parent_id, c.category_id), c.category_id"""),
        cx).to_string(index=False))
salva("ecommerce", blocos)

# ===========================================================================
# 3. CSV do SAC
# ===========================================================================
secao("FONTE 3 — CSV · atendimentos_sac.csv")
print("Dica: tente ler com encoding='utf-8' e observe o erro. Depois leia certo.")
sac = pd.read_csv(ARQ_SAC, sep=";", encoding="latin-1", dtype=str)
perfil_sac = perfila_dataframe(sac, "SAC")
print("\n· origem_sistema:", dict(Counter(sac["origem_sistema"])))
print("· linhas idênticas repetidas:", int(sac.duplicated().sum()))
print("· notas fora do domínio 1..5:",
      int((~sac["nota_satisfacao"].fillna("").isin(list("12345") + [""])).sum()))
print("· campos com quebra de linha interna:",
      int(sac["motivo"].fillna("").str.contains("\n").sum()))
print("· motivos distintos (texto livre):", sac["motivo"].nunique())
salva("sac", [("atendimentos_sac.csv", perfil_sac)])

# ===========================================================================
# 4. NDJSON de avaliações
# ===========================================================================
secao("FONTE 4 — NDJSON · avaliacoes_marketplace.json")
chaves = Counter()
tipos_rating = Counter()
prefixos = Counter()
com_fuso = sem_fuso = 0
total = 0
with open(ARQ_AVALIACOES, encoding="utf-8") as f:
    for linha in f:
        o = json.loads(linha)
        total += 1
        chaves.update(o.keys())
        tipos_rating[type(o.get("rating")).__name__] += 1
        prefixos[o["order"]["ref"].split("-")[0]] += 1
        if re.search(r"(Z|[+-]\d{2}:\d{2})$", o["submitted_at"]):
            com_fuso += 1
        else:
            sem_fuso += 1

print(f"registros: {total}")
print("\n· presença de cada chave de primeiro nível:")
for k, v in chaves.most_common():
    print(f"    {k:20s} {v:>8} ({100*v/total:5.1f}%)")
print("\n· tipo do campo rating:", dict(tipos_rating))
print("· prefixo de order.ref:", dict(prefixos))
print(f"· submitted_at com fuso: {com_fuso} | sem fuso: {sem_fuso}")

secao("PRÓXIMO PASSO")
print("""
Com este retrato em mãos, o Relatório de Diagnóstico deve responder:

  1. Quais campos são candidatos a chave de junção entre as fontes?
     Qual a cobertura real de cada candidato?
  2. Onde há heterogeneidade SEMÂNTICA — o mesmo rótulo com significados
     diferentes? Liste ao menos três casos com evidência numérica.
  3. VALOR_TOTAL no legado e total_amount no e-commerce medem a mesma coisa?
     Prove sua resposta comparando com a soma dos itens.
  4. Quais anomalias você consegue quantificar agora, e quais só aparecerão
     depois da integração?
""")
