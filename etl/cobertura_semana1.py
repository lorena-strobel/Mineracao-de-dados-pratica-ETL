
import json
import re
import pandas as pd

from config import eng_mysql, eng_origem, ARQ_SAC, ARQ_AVALIACOES


def normaliza_digitos(coluna):
    """Remove pontuação e deixa apenas dígitos; vazios viram ausentes."""
    resultado = (
        coluna.fillna("")
        .astype(str)
        .str.replace(r"\D", "", regex=True)
        .replace("", pd.NA)
    )
    return resultado.astype("string")


def normaliza_id(coluna):
    """Padroniza IDs numéricos para facilitar a comparação."""
    return (
        pd.to_numeric(coluna, errors="coerce")
        .astype("Int64")
        .astype("string")
    )


def cobertura(nome, origem, destino):
    """Conta registros e chaves distintas que encontram correspondência."""
    origem = origem.astype("string").str.strip().replace("", pd.NA)
    destino = destino.astype("string").str.strip().replace("", pd.NA)

    chaves_destino = set(destino.dropna().tolist())
    preenchidos = origem.dropna()
    encontrados = preenchidos[preenchidos.isin(chaves_destino)]

    chaves_origem = set(preenchidos.tolist())
    chaves_distintas_encontradas = chaves_origem & chaves_destino

    total = len(origem)
    total_preenchido = len(preenchidos)
    total_encontrado = len(encontrados)

    print(f"\n{nome}")
    print(f"  Registros de origem: {total}")
    print(f"  Registros com chave preenchida: {total_preenchido}")
    print(f"  Registros correspondentes: {total_encontrado}")
    print(
        f"  Cobertura sobre todos os registros: "
        f"{100 * total_encontrado / total:.2f}%"
        if total else "  Sem registros de origem"
    )
    print(
        f"  Cobertura entre chaves preenchidas: "
        f"{100 * total_encontrado / total_preenchido:.2f}%"
        if total_preenchido else "  Nenhuma chave preenchida"
    )
    print(
        f"  Chaves distintas encontradas: "
        f"{len(chaves_distintas_encontradas)}/{len(chaves_origem)}"
    )


# Lê as tabelas completas, sem LIMIT de amostragem.
with eng_mysql().connect() as cx:
    clientes_leg = pd.read_sql(
        "SELECT ID_CLIENTE, CPF FROM CLIENTES", cx
    )
    pedidos_leg = pd.read_sql(
        "SELECT ID_PEDIDO, ID_CLIENTE FROM PEDIDOS", cx
    )
    produtos_leg = pd.read_sql(
        "SELECT ID_PRODUTO FROM PRODUTOS", cx
    )
    itens_leg = pd.read_sql(
        "SELECT ID_PEDIDO, ID_PRODUTO FROM ITENS_PEDIDO", cx
    )

with eng_origem().connect() as cx:
    clientes_ecom = pd.read_sql(
        "SELECT customer_id, tax_id FROM shop.customer", cx
    )
    pedidos_ecom = pd.read_sql(
        "SELECT order_id, customer_id FROM shop.orders", cx
    )
    produtos_ecom = pd.read_sql(
        "SELECT product_id, sku FROM shop.product", cx
    )
    itens_ecom = pd.read_sql(
        "SELECT order_id, product_id FROM shop.order_item", cx
    )


print("\n=== 1. IDENTIDADE DO CLIENTE ===")

cpf_leg = normaliza_digitos(clientes_leg["CPF"])
cpf_ecom = normaliza_digitos(clientes_ecom["tax_id"])

cobertura("CPF legado -> tax_id e-commerce", cpf_leg, cpf_ecom)
cobertura("tax_id e-commerce -> CPF legado", cpf_ecom, cpf_leg)


print("\n=== 2. RELAÇÕES INTERNAS DO LEGADO ===")

cobertura(
    "Pedidos -> clientes do legado",
    normaliza_id(pedidos_leg["ID_CLIENTE"]),
    normaliza_id(clientes_leg["ID_CLIENTE"]),
)
cobertura(
    "Itens -> pedidos do legado",
    normaliza_id(itens_leg["ID_PEDIDO"]),
    normaliza_id(pedidos_leg["ID_PEDIDO"]),
)
cobertura(
    "Itens -> produtos do legado",
    normaliza_id(itens_leg["ID_PRODUTO"]),
    normaliza_id(produtos_leg["ID_PRODUTO"]),
)


print("\n=== 3. RELAÇÕES INTERNAS DO E-COMMERCE ===")

cobertura(
    "Pedidos -> clientes do e-commerce",
    normaliza_id(pedidos_ecom["customer_id"]),
    normaliza_id(clientes_ecom["customer_id"]),
)
cobertura(
    "Itens -> pedidos do e-commerce",
    normaliza_id(itens_ecom["order_id"]),
    normaliza_id(pedidos_ecom["order_id"]),
)
cobertura(
    "Itens -> produtos do e-commerce",
    normaliza_id(itens_ecom["product_id"]),
    normaliza_id(produtos_ecom["product_id"]),
)


print("\n=== 4. ATENDIMENTOS DO SAC -> PEDIDOS ===")

sac = pd.read_csv(
    ARQ_SAC, sep=";", encoding="latin-1", dtype=str
)
sac_id = normaliza_id(sac["id_pedido_origem"])
origem = sac["origem_sistema"].str.strip().str.upper()

cobertura(
    "SAC LEGADO -> pedidos do legado",
    sac_id[origem == "LEGADO"],
    normaliza_id(pedidos_leg["ID_PEDIDO"]),
)
cobertura(
    "SAC ECOM -> pedidos do e-commerce",
    sac_id[origem == "ECOM"],
    normaliza_id(pedidos_ecom["order_id"]),
)


print("\n=== 5. AVALIAÇÕES -> PEDIDOS E PRODUTOS ===")

avaliacoes = []
with open(ARQ_AVALIACOES, encoding="utf-8") as arquivo:
    for linha in arquivo:
        obj = json.loads(linha)
        ref_pedido = obj.get("order", {}).get("ref", "")
        sku = obj.get("product", {}).get("sku", "")

        match = re.fullmatch(r"(LEG|ECOM)-(\d+)", ref_pedido)
        prefixo = match.group(1) if match else None
        id_pedido = match.group(2) if match else None

        avaliacoes.append({
            "prefixo": prefixo,
            "id_pedido": id_pedido,
            "sku": sku,
        })

rev = pd.DataFrame(avaliacoes)

cobertura(
    "Avaliações LEG -> pedidos do legado",
    normaliza_id(rev.loc[rev["prefixo"] == "LEG", "id_pedido"]),
    normaliza_id(pedidos_leg["ID_PEDIDO"]),
)
cobertura(
    "Avaliações ECOM -> pedidos do e-commerce",
    normaliza_id(rev.loc[rev["prefixo"] == "ECOM", "id_pedido"]),
    normaliza_id(pedidos_ecom["order_id"]),
)

sku_leg = rev["sku"].str.extract(r"^LEG-(\d+)$")[0]
sku_ecom = rev.loc[rev["sku"].str.startswith("SKU-", na=False), "sku"]

cobertura(
    "Avaliações LEG -> produtos do legado",
    normaliza_id(sku_leg.dropna()),
    normaliza_id(produtos_leg["ID_PRODUTO"]),
)
cobertura(
    "Avaliações ECOM -> SKU do e-commerce",
    sku_ecom,
    produtos_ecom["sku"],
)