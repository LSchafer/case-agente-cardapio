"""Matemática de precificação — piso de preço e cenários de markup sobre o
CMV **por porção**, não pelo lote inteiro da receita.

Taxa de 10% da plataforma sobre o preço de venda P, Dona Maria recebe 0,90·P.
Piso: P >= CMV / 0,90. Lucro: 0,90·P - CMV.

Os cenários são definidos por lucro-alvo como % do CMV, não por food cost %
de mercado. Percentuais abaixo são ponto de partida, não validados com
dado real — documentado no README.

A Dona Maria vende porção a porção (ex: um prato de macarrão),
não a receita inteira de uma vez — `cmv_total` (custo de toda a receita)
precisa ser dividido por `porcoes` (quantas porções a receita rende) antes
de entrar em qualquer fórmula de preço/lucro/piso. Essa divisão é feita
aqui dentro, nunca pelo agente.
"""

from mcp_server.modelos import CenarioPreco, ResultadoAvaliacaoPreco, ResultadoPrecificacao

TAXA_PLATAFORMA = 0.10
REPASSE = 1 - TAXA_PLATAFORMA  # 0.90

LUCRO_ALVO_PCT_CMV = (0.30, 0.50, 0.80)


def calcular_preco_minimo(cmv: float) -> float:
    """P >= CMV / 0,90 — preço mínimo pra não perder dinheiro após a taxa.
    Genérica de propósito: quem chama decide se `cmv` é por porção ou não
    — `calcular_cenarios`/`avaliar_preco` sempre passam o valor por porção."""
    return cmv / REPASSE


def _validar_porcoes(porcoes: int) -> None:
    if porcoes <= 0:
        raise ValueError(
            "porcoes deve ser maior que zero — sem saber quantas porções a "
            "receita rende não dá pra calcular o preço por porção que a "
            "Dona Maria vai vender."
        )


def calcular_cenarios(prato: str, cmv_total: float, porcoes: int) -> ResultadoPrecificacao:
    if cmv_total < 0:
        raise ValueError("cmv_total não pode ser negativo.")
    _validar_porcoes(porcoes)

    cmv_por_porcao = cmv_total / porcoes
    preco_minimo = calcular_preco_minimo(cmv_por_porcao)

    cenarios = []
    for pct in LUCRO_ALVO_PCT_CMV:
        lucro_alvo = cmv_por_porcao * pct
        preco = (cmv_por_porcao + lucro_alvo) / REPASSE
        lucro_dona_maria = REPASSE * preco - cmv_por_porcao
        cmv_pct_do_preco = (cmv_por_porcao / preco) if preco > 0 else 0.0
        taxa_plataforma = preco * TAXA_PLATAFORMA
        cenarios.append(
            CenarioPreco(
                lucro_alvo_pct=pct,
                preco=preco,
                lucro_dona_maria=lucro_dona_maria,
                cmv_pct_do_preco=cmv_pct_do_preco,
                taxa_plataforma=taxa_plataforma,
            )
        )

    return ResultadoPrecificacao(
        prato=prato,
        cmv_total=cmv_total,
        porcoes=porcoes,
        cmv_por_porcao=cmv_por_porcao,
        preco_minimo=preco_minimo,
        cenarios=cenarios,
    )


def avaliar_preco(prato: str, preco_proposto: float, cmv_total: float, porcoes: int) -> ResultadoAvaliacaoPreco:
    """Avalia um preço específico **por porção** (opção A/B/C repetida ou
    valor livre da Dona Maria) contra o cmv_por_porcao (= cmv_total /
    porcoes) — nunca contra um cálculo do agente. `abaixo_do_minimo`/
    `resultado_financeiro` negativo são o sinal determinístico de prejuízo
    que o agente deve usar pra alertar e pedir confirmação explícita antes
    de tratar o preço como fechado."""
    if preco_proposto <= 0:
        raise ValueError("preco_proposto deve ser maior que zero.")
    if cmv_total < 0:
        raise ValueError("cmv_total não pode ser negativo.")
    _validar_porcoes(porcoes)

    cmv_por_porcao = cmv_total / porcoes
    preco_minimo = calcular_preco_minimo(cmv_por_porcao)
    taxa_plataforma = preco_proposto * TAXA_PLATAFORMA
    receita_liquida = preco_proposto * REPASSE
    resultado_financeiro = receita_liquida - cmv_por_porcao

    return ResultadoAvaliacaoPreco(
        prato=prato,
        preco_proposto=preco_proposto,
        cmv_total=cmv_total,
        porcoes=porcoes,
        cmv_por_porcao=cmv_por_porcao,
        preco_minimo=preco_minimo,
        taxa_plataforma=taxa_plataforma,
        receita_liquida=receita_liquida,
        resultado_financeiro=resultado_financeiro,
        abaixo_do_minimo=preco_proposto < preco_minimo,
    )
