import math
from pathlib import Path

import pytest

from mcp_server.planilha import UnidadeDesconhecidaError, carregar_despensa, normalizar_unidade

XLSX_PATH = Path(__file__).parent.parent / "data" / "despensa_dona_maria.xlsx"


def aprox(a: float, b: float, tol: float = 1e-4) -> bool:
    return math.isclose(a, b, abs_tol=tol)


class TestNormalizarUnidade:
    def test_unidades_simples(self):
        assert normalizar_unidade("kg") == ("g", 1000.0)
        assert normalizar_unidade("g") == ("g", 1.0)
        assert normalizar_unidade("L") == ("ml", 1000.0)
        assert normalizar_unidade("ml") == ("ml", 1.0)
        assert normalizar_unidade("un") == ("un", 1.0)

    def test_unidades_compostas(self):
        assert normalizar_unidade("balde 2kg") == ("g", 2000.0)
        assert normalizar_unidade("un 500g") == ("g", 500.0)
        assert normalizar_unidade("un 400g") == ("g", 400.0)
        assert normalizar_unidade("un 500ml") == ("ml", 500.0)
        assert normalizar_unidade("un 100ml") == ("ml", 100.0)

    def test_unidade_desconhecida_falha_rapido(self):
        with pytest.raises(UnidadeDesconhecidaError):
            normalizar_unidade("caixa 3un")


class TestCarregarDespensa:
    @classmethod
    @pytest.fixture(scope="class")
    def despensa(cls):
        return carregar_despensa(XLSX_PATH)

    def test_carrega_todos_os_37_ingredientes(self, despensa):
        assert len(despensa) == 37

    def test_custo_unitario_unidade_simples_kg(self, despensa):
        item = despensa["Arroz branco tipo 1"]
        assert item.unidade_base == "g"
        assert aprox(item.quantidade_disponivel, 5000.0)
        assert aprox(item.custo_unitario, 24.90 / 5000.0)

    def test_custo_unitario_unidade_simples_un(self, despensa):
        item = despensa["Ovos"]
        assert item.unidade_base == "un"
        assert aprox(item.quantidade_disponivel, 30.0)
        assert aprox(item.custo_unitario, 24.0 / 30.0)

    @pytest.mark.parametrize(
        "nome,unidade_base,quantidade_base_esperada,preco_total",
        [
            ("Alcaparras", "g", 2000.0, 82.0),
            ("Chantilly", "g", 500.0, 23.67),
            ("Leite ninho em pó", "g", 400.0, 15.18),
            ("Azeite de oliva extra virgem", "ml", 500.0, 30.99),
            ("Aceto balsâmico", "ml", 500.0, 12.99),
            ("Adoçante líquido", "ml", 100.0, 1.90),
        ],
    )
    def test_custo_unitario_unidade_composta(
        self, despensa, nome, unidade_base, quantidade_base_esperada, preco_total
    ):
        item = despensa[nome]
        assert item.unidade_base == unidade_base
        assert aprox(item.quantidade_disponivel, quantidade_base_esperada)
        assert aprox(item.custo_unitario, preco_total / quantidade_base_esperada)
