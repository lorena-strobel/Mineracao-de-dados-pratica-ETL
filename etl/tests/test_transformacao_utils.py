# -*- coding: utf-8 -*-
"""Testes unitários para utilitários de transformação e formatação."""

import pandas as pd
import pytest

from importlib.machinery import SourceFileLoader
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
transf = SourceFileLoader("transf", os.path.join(BASE_DIR, "02_transformacao.py")).load_module()
export_orange = SourceFileLoader("export_orange", os.path.join(BASE_DIR, "05_exportar_orange.py")).load_module()

cpf_valido = transf.cpf_valido
so_digitos = transf.so_digitos
normaliza_nome = transf.normaliza_nome
tipo_orange = export_orange.tipo_orange


class TestCpfValido:
    def test_cpfs_validos(self):
        # CPFs com dígitos verificadores matematicamente válidos
        assert cpf_valido("52998224725") is True
        assert cpf_valido("529.982.247-25") is True
        assert cpf_valido("00000000191") is True

    def test_cpfs_invalidos(self):
        # Dígitos verificadores incorretos
        assert cpf_valido("52998224726") is False
        assert cpf_valido("12345678900") is False

    def test_cpfs_todos_digitos_iguais(self):
        # 11 dígitos iguais são matematicamente rejeitados na regra nacional
        assert cpf_valido("11111111111") is False
        assert cpf_valido("00000000000") is False

    def test_cpfs_tamanho_invalido(self):
        assert cpf_valido("123") is None
        assert cpf_valido("") is None
        assert cpf_valido(None) is None
        assert cpf_valido("1234567890123") is None


class TestSoDigitos:
    def test_extracao_digitos(self):
        assert so_digitos("123.456.789-00") == "12345678900"
        assert so_digitos("(66) 99999-1234") == "66999991234"
        assert so_digitos("SEM NUMERO") == ""
        assert so_digitos(None) == ""
        assert so_digitos("") == ""


class TestNormalizaNome:
    def test_remocao_acentos_e_caixa_alta(self):
        assert normaliza_nome("joão da silva") == "JOAO DA SILVA"
        assert normaliza_nome("Érico Veríssimo") == "ERICO VERISSIMO"
        assert normaliza_nome("  ANA   PAULA  ") == "ANA PAULA"
        assert normaliza_nome(None) == ""
        assert normaliza_nome("") == ""


class TestTipoOrange:
    def test_tipos_mapeados(self):
        s_bool = pd.Series([True, False, True])
        assert tipo_orange(s_bool) == "discrete"

        s_num = pd.Series([10.5, 20.0, 30.2])
        assert tipo_orange(s_num) == "continuous"

        s_int = pd.Series([1, 2, 3])
        assert tipo_orange(s_int) == "continuous"

        s_cat_pequena = pd.Series(["FISICO", "ONLINE", "MARKETPLACE"] * 10)
        assert tipo_orange(s_cat_pequena) == "discrete"

        s_str_grande = pd.Series([f"texto_{i}" for i in range(50)])
        assert tipo_orange(s_str_grande) == "string"
