"""Conversão determinística de unidade de receita -> unidade-base da despensa.

O LLM só faz o de-para de *nome* do ingrediente; toda aritmética de
conversão (xícara/colher/pitada -> g/ml) mora aqui. Tabela curada só para
os padrões plausíveis dado os 37 ingredientes reais da despensa —
qualquer combinação fora dela retorna `sucesso=False`, nunca um número
inventado.
"""

from mcp_server.modelos import ConversaoResultado
from mcp_server.planilha import UnidadeDesconhecidaError, normalizar_unidade

# unidade de receita -> ml (independe do ingrediente)
VOLUME_ML: dict[str, float] = {
    "xícara": 240.0,
    "xicara": 240.0,
    "colher de sopa": 15.0,
    "colher de chá": 5.0,
    "colher de cha": 5.0,
    "colher de chá rasa": 5.0,
    "colher de sopa rasa": 15.0,
}

# (unidade de receita, nome do ingrediente em minúsculo) -> gramas diretas
#
# "a gosto" mapeia pro mesmo valor curado de "pitada", só pros 3 temperos que
# já tinham entrada aqui: receitas reais raramente escrevem "1 pitada de sal",
# escrevem "sal a gosto"; sem o alias, isso caía em item_nao_calculavel e
# forçava perguntar a ela quantas gramas é "a gosto" pra um item cujo custo é
# irrelevante (< R$0,01/uso). Nenhum ingrediente novo foi adicionado aqui —
# só um nome alternativo pros 3 que já passavam por julgamento curado.
GRAMAS_POR_UNIDADE_CULINARIA: dict[tuple[str, str], float] = {
    ("pitada", "sal"): 0.5,
    ("a gosto", "sal"): 0.5,
    ("pitada", "canela em pó"): 0.5,
    ("a gosto", "canela em pó"): 0.5,
    ("pitada", "açafrão em pó (cúrcuma)"): 0.3,
    ("a gosto", "açafrão em pó (cúrcuma)"): 0.3,
    ("dente", "alho"): 3.0,
}

# nome do ingrediente em minúsculo -> densidade g/ml, só onde plausível
DENSIDADE_G_POR_ML: dict[str, float] = {
    "farinha de trigo": 0.53,
    "açúcar": 0.83,
    "sal": 1.2,
    "óleo de soja": 0.92,
    "manteiga": 0.96,
    "leite integral": 1.03,
}


def converter(
    nome_despensa: str, quantidade: float, unidade_receita: str, unidade_base_despensa: str
) -> ConversaoResultado:
    unidade_receita_norm = unidade_receita.strip().lower()
    ingrediente_norm = nome_despensa.strip().lower()

    # 1. unidade "simples" já conhecida da planilha (kg/g/L/ml/un) — não
    #    depende do ingrediente, só precisa bater com a base da despensa.
    try:
        unidade_base_receita, fator = normalizar_unidade(unidade_receita_norm)
    except UnidadeDesconhecidaError:
        unidade_base_receita, fator = None, None

    if unidade_base_receita is not None:
        if unidade_base_receita == unidade_base_despensa:
            return ConversaoResultado(
                sucesso=True,
                quantidade_base=quantidade * fator,
                unidade_base=unidade_base_despensa,
            )
        return ConversaoResultado(
            sucesso=False,
            motivo=(
                f"Unidade '{unidade_receita}' normaliza para '{unidade_base_receita}', "
                f"incompatível com a unidade-base da despensa ('{unidade_base_despensa}') "
                f"para '{nome_despensa}'."
            ),
        )

    # 2. gramas diretas por unidade culinária + ingrediente específico (pitada, dente, ...)
    chave_direta = (unidade_receita_norm, ingrediente_norm)
    if chave_direta in GRAMAS_POR_UNIDADE_CULINARIA:
        if unidade_base_despensa != "g":
            return ConversaoResultado(
                sucesso=False,
                motivo=(
                    f"'{unidade_receita}' de '{nome_despensa}' converte pra gramas, "
                    f"mas a despensa mede esse item em '{unidade_base_despensa}'."
                ),
            )
        return ConversaoResultado(
            sucesso=True,
            quantidade_base=quantidade * GRAMAS_POR_UNIDADE_CULINARIA[chave_direta],
            unidade_base="g",
        )

    # 3. unidade de volume culinária (xícara, colher...) — precisa de densidade
    #    se a despensa mede o item em massa.
    if unidade_receita_norm in VOLUME_ML:
        volume_ml_total = quantidade * VOLUME_ML[unidade_receita_norm]

        if unidade_base_despensa == "ml":
            return ConversaoResultado(sucesso=True, quantidade_base=volume_ml_total, unidade_base="ml")

        if unidade_base_despensa == "g":
            densidade = DENSIDADE_G_POR_ML.get(ingrediente_norm)
            if densidade is None:
                return ConversaoResultado(
                    sucesso=False,
                    motivo=(
                        f"Sem densidade conhecida pra converter '{unidade_receita}' "
                        f"de '{nome_despensa}' em gramas."
                    ),
                )
            return ConversaoResultado(
                sucesso=True, quantidade_base=volume_ml_total * densidade, unidade_base="g"
            )

        return ConversaoResultado(
            sucesso=False,
            motivo=(
                f"Não dá pra converter unidade de volume ('{unidade_receita}') pra "
                f"unidade-base '{unidade_base_despensa}' (contável em unidades, não volume)."
            ),
        )

    return ConversaoResultado(
        sucesso=False,
        motivo=f"Unidade '{unidade_receita}' não está na tabela de conversão conhecida.",
    )
