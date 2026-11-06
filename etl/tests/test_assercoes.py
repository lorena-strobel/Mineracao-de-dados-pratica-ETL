# -*- coding: utf-8 -*-
"""Testes unitários para o framework de qualidade (Suite)."""

import pandas as pd
import pytest

from qualidade.assercoes import Suite, Resultado


class TestSuiteAssercoes:
    def test_igual(self):
        qa = Suite(etapa="teste")
        assert qa.igual("teste_ok", 10, 10) is True
        assert qa.igual("teste_fail", 10, 20) is False
        assert len(qa.resultados) == 2
        assert qa.falhou() is True

    def test_entre(self):
        qa = Suite(etapa="teste")
        assert qa.entre("faixa_ok", 0.35, 0.20, 0.50) is True
        assert qa.entre("faixa_abaixo", 0.10, 0.20, 0.50) is False
        assert qa.entre("faixa_acima", 0.60, 0.20, 0.50) is False

    def test_sem_nulos(self):
        qa = Suite(etapa="teste")
        s_sem_nulos = pd.Series([1, 2, 3])
        s_com_nulos = pd.Series([1, None, 3])
        assert qa.sem_nulos("sem_nulos", s_sem_nulos) is True
        assert qa.sem_nulos("com_nulos", s_com_nulos) is False

    def test_unico(self):
        qa = Suite(etapa="teste")
        s_unicos = pd.Series(["A", "B", "C"])
        s_dups = pd.Series(["A", "B", "A"])
        assert qa.unico("unicos", s_unicos) is True
        assert qa.unico("dups", s_dups) is False

    def test_dominio(self):
        qa = Suite(etapa="teste")
        s_valida = pd.Series(["A", "B", "A"])
        s_invalida = pd.Series(["A", "C", "B"])
        assert qa.dominio("valido", s_valida, {"A", "B"}) is True
        assert qa.dominio("invalido", s_invalida, {"A", "B"}) is False

    def test_cardinalidade_preservada(self):
        qa = Suite(etapa="teste")
        assert qa.cardinalidade_preservada("ok", 100, 100) is True
        assert qa.cardinalidade_preservada("reduzido", 100, 90) is True
        assert qa.cardinalidade_preservada("explodiu", 100, 150) is False

    def test_imprimir(self, capsys):
        qa = Suite(etapa="teste_print")
        qa.igual("ok", 1, 1)
        qa.igual("falha", 1, 2, "descricao do erro")
        n_falhas = qa.imprimir()
        assert n_falhas == 1
        captured = capsys.readouterr()
        assert "[OK  ]" in captured.out
        assert "[FALHA]" in captured.out
        assert "descricao do erro" in captured.out
