import math

import pytest

from mcp_server.precificacao import avaliar_preco, calcular_cenarios, calcular_preco_minimo


def aprox(a: float, b: float, tol: float = 1e-6) -> bool:
    return math.isclose(a, b, abs_tol=tol)


def test_preco_minimo_bate_com_formula_do_enunciado():
    cmv = 18.0
    assert aprox(calcular_preco_minimo(cmv), cmv / 0.90)


def test_cenarios_geram_3_opcoes_com_lucro_crescente():
    resultado = calcular_cenarios("Feijoada simplificada", cmv_total=20.0, porcoes=1)
    assert resultado.prato == "Feijoada simplificada"
    assert len(resultado.cenarios) == 3
    lucros = [c.lucro_dona_maria for c in resultado.cenarios]
    assert lucros == sorted(lucros)
    assert all(l > 0 for l in lucros)


def test_cada_cenario_respeita_o_piso_e_a_formula_de_lucro():
    cmv = 20.0
    resultado = calcular_cenarios("Feijoada simplificada", cmv_total=cmv, porcoes=1)
    for cenario in resultado.cenarios:
        assert cenario.preco >= resultado.preco_minimo
        lucro_esperado = 0.90 * cenario.preco - cmv
        assert aprox(cenario.lucro_dona_maria, lucro_esperado)
        lucro_alvo_esperado = cmv * cenario.lucro_alvo_pct
        assert aprox(cenario.lucro_dona_maria, lucro_alvo_esperado)


def test_cada_cenario_expoe_a_taxa_da_plataforma_em_reais():
    # Cada cenário já vem com a taxa da plataforma pronta em R$, pra
    # ninguém precisar recalcular preco*0.10 por fora da tool.
    resultado = calcular_cenarios("Feijoada simplificada", cmv_total=20.0, porcoes=1)
    for cenario in resultado.cenarios:
        assert aprox(cenario.taxa_plataforma, cenario.preco * 0.10)


def test_cmv_zero_preco_minimo_zero_e_cenarios_todos_zero():
    resultado = calcular_cenarios("Água com gelo", cmv_total=0.0, porcoes=1)
    assert resultado.preco_minimo == 0.0
    assert all(c.preco == 0.0 for c in resultado.cenarios)


def test_cmv_negativo_rejeitado():
    with pytest.raises(ValueError):
        calcular_cenarios("Prato inválido", cmv_total=-1.0, porcoes=1)


def test_porcoes_zero_ou_negativo_rejeitado_em_cenarios():
    with pytest.raises(ValueError):
        calcular_cenarios("Prato", cmv_total=20.0, porcoes=0)
    with pytest.raises(ValueError):
        calcular_cenarios("Prato", cmv_total=20.0, porcoes=-2)


def test_cenarios_dividem_cmv_pelas_porcoes_antes_de_precificar():
    # Receita custou R$50 no total e rende 4 porções -- o preço/piso tem
    # que ser calculado sobre R$12,50 (por porção), nunca sobre os R$50
    # do lote inteiro.
    resultado = calcular_cenarios("Espaguete à bolonhesa", cmv_total=50.0, porcoes=4)
    assert resultado.cmv_total == 50.0
    assert resultado.porcoes == 4
    assert aprox(resultado.cmv_por_porcao, 12.5)
    assert aprox(resultado.preco_minimo, 12.5 / 0.90)
    # nenhum cenário pode usar o CMV do lote inteiro por engano
    for cenario in resultado.cenarios:
        assert cenario.preco < 50.0 / 0.90
        lucro_alvo_esperado = 12.5 * cenario.lucro_alvo_pct
        assert aprox(cenario.lucro_dona_maria, lucro_alvo_esperado)


def test_cenarios_com_porcoes_1_bate_com_cmv_total_direto():
    # Caso degenerado (lote = 1 porção) tem que reproduzir a matemática
    # antiga (cmv_por_porcao == cmv_total).
    resultado = calcular_cenarios("Prato individual", cmv_total=20.0, porcoes=1)
    assert aprox(resultado.cmv_por_porcao, 20.0)
    assert aprox(resultado.preco_minimo, 20.0 / 0.90)


def test_avaliar_preco_acima_do_minimo_da_lucro_positivo():
    cmv = 20.0
    resultado = avaliar_preco("Feijoada simplificada", preco_proposto=30.0, cmv_total=cmv, porcoes=1)
    assert resultado.preco_proposto == 30.0
    assert aprox(resultado.preco_minimo, cmv / 0.90)
    assert aprox(resultado.taxa_plataforma, 3.0)
    assert aprox(resultado.receita_liquida, 27.0)
    assert aprox(resultado.resultado_financeiro, 27.0 - cmv)
    assert resultado.resultado_financeiro > 0
    assert resultado.abaixo_do_minimo is False


def test_avaliar_preco_abaixo_do_minimo_sinaliza_prejuizo():
    cmv = 20.0
    preco_minimo = calcular_preco_minimo(cmv)
    resultado = avaliar_preco("Feijoada simplificada", preco_proposto=15.0, cmv_total=cmv, porcoes=1)
    assert preco_minimo > 15.0  # garante que o preço escolhido no teste é mesmo abaixo do piso
    assert resultado.abaixo_do_minimo is True
    assert resultado.resultado_financeiro < 0
    assert aprox(resultado.resultado_financeiro, 0.90 * 15.0 - cmv)


def test_avaliar_preco_exatamente_no_minimo_nao_e_prejuizo():
    cmv = 18.0
    preco_minimo = calcular_preco_minimo(cmv)
    resultado = avaliar_preco("Prato", preco_proposto=preco_minimo, cmv_total=cmv, porcoes=1)
    assert resultado.abaixo_do_minimo is False
    assert aprox(resultado.resultado_financeiro, 0.0)


def test_avaliar_preco_zero_ou_negativo_rejeitado():
    with pytest.raises(ValueError):
        avaliar_preco("Prato", preco_proposto=0.0, cmv_total=10.0, porcoes=1)
    with pytest.raises(ValueError):
        avaliar_preco("Prato", preco_proposto=-5.0, cmv_total=10.0, porcoes=1)


def test_avaliar_preco_cmv_negativo_rejeitado():
    with pytest.raises(ValueError):
        avaliar_preco("Prato", preco_proposto=10.0, cmv_total=-1.0, porcoes=1)


def test_avaliar_preco_porcoes_zero_ou_negativo_rejeitado():
    with pytest.raises(ValueError):
        avaliar_preco("Prato", preco_proposto=10.0, cmv_total=20.0, porcoes=0)
    with pytest.raises(ValueError):
        avaliar_preco("Prato", preco_proposto=10.0, cmv_total=20.0, porcoes=-1)


def test_avaliar_preco_usa_cmv_por_porcao_no_resultado_financeiro():
    # Um preço de R$15 por porção contra CMV de R$50/4 porções
    # (=R$12,50/porção) precisa dar LUCRO (15*0.9=13.5 > 12.5) -- se
    # comparasse contra o CMV do lote inteiro (R$50), pareceria um
    # prejuízo enorme.
    resultado = avaliar_preco("Espaguete à bolonhesa", preco_proposto=15.0, cmv_total=50.0, porcoes=4)
    assert aprox(resultado.cmv_por_porcao, 12.5)
    assert resultado.abaixo_do_minimo is False
    assert aprox(resultado.resultado_financeiro, 0.90 * 15.0 - 12.5)
    assert resultado.resultado_financeiro > 0
