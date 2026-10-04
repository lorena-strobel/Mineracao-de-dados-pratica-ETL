# -*- coding: utf-8 -*-
"""
Mini-framework de asserções de qualidade (princípio 6 do referencial).

Cada etapa do pipeline deve declarar o que espera ANTES de executar, e a
execução registra o resultado em qa.execucao_assercao. Uma asserção que falha
não interrompe o pipeline por padrão: ela fica registrada, porque o objetivo é
saber ONDE o problema entrou, e não apenas que ele existe.

Uso:

    from qualidade.assercoes import Suite

    qa = Suite(etapa="02_transformacao")
    qa.igual("itens sem pedido", n_orfaos, 0,
             "nenhum item deve ficar sem pedido depois da conformação")
    qa.entre("taxa de pareamento por CPF", taxa, 0.25, 0.45)
    qa.cardinalidade_preservada("junção pedido x cliente", antes, depois)
    qa.registrar(engine_dw)
    qa.imprimir()
"""

from dataclasses import dataclass, field
from typing import Optional, List

from sqlalchemy import text


@dataclass
class Resultado:
    nome: str
    descricao: str
    valor_obtido: Optional[float]
    valor_esperado: str
    aprovado: bool


@dataclass
class Suite:
    etapa: str
    resultados: List[Resultado] = field(default_factory=list)

    # -- verificações -------------------------------------------------------
    def igual(self, nome, obtido, esperado, descricao=""):
        ok = obtido == esperado
        self.resultados.append(Resultado(nome, descricao, _num(obtido),
                                         f"= {esperado}", ok))
        return ok

    def maior_igual(self, nome, obtido, minimo, descricao=""):
        ok = obtido >= minimo
        self.resultados.append(Resultado(nome, descricao, _num(obtido),
                                         f">= {minimo}", ok))
        return ok

    def entre(self, nome, obtido, minimo, maximo, descricao=""):
        ok = minimo <= obtido <= maximo
        self.resultados.append(Resultado(nome, descricao, _num(obtido),
                                         f"[{minimo}, {maximo}]", ok))
        return ok

    def sem_nulos(self, nome, serie, descricao=""):
        n = int(serie.isna().sum())
        ok = n == 0
        self.resultados.append(Resultado(nome, descricao, n, "= 0 nulos", ok))
        return ok

    def unico(self, nome, serie, descricao=""):
        n = int(serie.duplicated().sum())
        ok = n == 0
        self.resultados.append(Resultado(nome, descricao, n, "= 0 duplicados", ok))
        return ok

    def dominio(self, nome, serie, valores_permitidos, descricao=""):
        fora = int((~serie.isin(valores_permitidos)).sum())
        ok = fora == 0
        self.resultados.append(Resultado(nome, descricao, fora,
                                         f"todos em {sorted(valores_permitidos)}", ok))
        return ok

    def cardinalidade_preservada(self, nome, linhas_antes, linhas_depois,
                                 descricao="junção não pode multiplicar linhas"):
        """A armadilha mais comum: uma junção que vira produto cartesiano."""
        ok = linhas_depois <= linhas_antes
        self.resultados.append(Resultado(nome, descricao, linhas_depois,
                                         f"<= {linhas_antes}", ok))
        return ok

    def sem_orfaos(self, nome, filhos, pais, descricao="chaves órfãs"):
        orfaos = int((~filhos.isin(pais)).sum())
        ok = orfaos == 0
        self.resultados.append(Resultado(nome, descricao, orfaos, "= 0 órfãos", ok))
        return ok

    # -- persistência e relato ---------------------------------------------
    def registrar(self, engine):
        sql = text("""
            INSERT INTO qa.execucao_assercao
                (etapa, nome, descricao, valor_obtido, valor_esperado, aprovado)
            VALUES (:etapa, :nome, :descricao, :valor, :esperado, :ok)
        """)
        with engine.begin() as cx:
            for r in self.resultados:
                cx.execute(sql, dict(etapa=self.etapa, nome=r.nome,
                                     descricao=r.descricao, valor=r.valor_obtido,
                                     esperado=r.valor_esperado, ok=r.aprovado))

    def imprimir(self):
        largura = max((len(r.nome) for r in self.resultados), default=10)
        print(f"\n=== asserções · {self.etapa} " + "=" * 30)
        for r in self.resultados:
            marca = "OK  " if r.aprovado else "FALHA"
            print(f"  [{marca}] {r.nome:<{largura}}  obtido={r.valor_obtido}"
                  f"  esperado {r.valor_esperado}")
            if not r.aprovado and r.descricao:
                print(f"           -> {r.descricao}")
        n_falhas = sum(1 for r in self.resultados if not r.aprovado)
        print(f"  {len(self.resultados)} asserções, {n_falhas} falha(s)\n")
        return n_falhas

    def falhou(self):
        return any(not r.aprovado for r in self.resultados)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
