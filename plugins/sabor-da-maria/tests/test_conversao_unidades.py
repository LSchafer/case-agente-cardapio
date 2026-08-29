import math

from mcp_server.conversao_unidades import converter


def aprox(a: float, b: float, tol: float = 1e-6) -> bool:
    return math.isclose(a, b, abs_tol=tol)


class TestUnidadeSimplesCompativel:
    def test_kg_para_g(self):
        r = converter("Arroz branco tipo 1", 1.5, "kg", "g")
        assert r.sucesso
        assert aprox(r.quantidade_base, 1500.0)
        assert r.unidade_base == "g"

    def test_un_para_un(self):
        r = converter("Ovos", 3, "un", "un")
        assert r.sucesso
        assert aprox(r.quantidade_base, 3.0)


class TestUnidadeSimplesIncompativel:
    def test_g_pedido_mas_despensa_em_un(self):
        r = converter("Ovos", 50, "g", "un")
        assert not r.sucesso
        assert r.motivo is not None


class TestGramasDiretasPorUnidadeCulinaria:
    def test_pitada_sal(self):
        r = converter("Sal", 2, "pitada", "g")
        assert r.sucesso
        assert aprox(r.quantidade_base, 1.0)

    def test_dente_alho(self):
        r = converter("Alho", 4, "dente", "g")
        assert r.sucesso
        assert aprox(r.quantidade_base, 12.0)

    def test_pitada_de_ingrediente_nao_coberto_cai_pra_falha_ou_outra_regra(self):
        r = converter("Bacon", 1, "pitada", "g")
        assert not r.sucesso

    def test_a_gosto_sal_equivale_a_pitada(self):
        r = converter("Sal", 2, "a gosto", "g")
        assert r.sucesso
        assert aprox(r.quantidade_base, 1.0)

    def test_a_gosto_canela(self):
        r = converter("Canela em pó", 1, "a gosto", "g")
        assert r.sucesso
        assert aprox(r.quantidade_base, 0.5)

    def test_a_gosto_de_ingrediente_nao_curado_cai_pra_falha(self):
        r = converter("Caldo de carne (tempero)", 1, "a gosto", "g")
        assert not r.sucesso


class TestVolumeParaMl:
    def test_xicara_direto_pra_despensa_em_ml(self):
        r = converter("Leite integral", 1, "xícara", "ml")
        assert r.sucesso
        assert aprox(r.quantidade_base, 240.0)
        assert r.unidade_base == "ml"

    def test_colher_de_sopa_com_densidade_pra_gramas(self):
        r = converter("Farinha de trigo", 2, "colher de sopa", "g")
        assert r.sucesso
        assert aprox(r.quantidade_base, 2 * 15.0 * 0.53)

    def test_xicara_sem_densidade_conhecida_falha_explicitamente(self):
        r = converter("Bacon", 1, "xícara", "g")
        assert not r.sucesso
        assert r.motivo is not None

    def test_volume_pra_despensa_em_un_falha(self):
        r = converter("Ovos", 1, "xícara", "un")
        assert not r.sucesso


class TestUnidadeDesconhecidaFalhaExplicita:
    def test_unidade_totalmente_fora_da_tabela(self):
        r = converter("Sal", 1, "punhado", "g")
        assert not r.sucesso
        assert r.motivo is not None
