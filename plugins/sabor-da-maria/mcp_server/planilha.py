"""Leitura do xlsx (abas Despensa + Precos) e normalização de unidade.

6 dos 37 ingredientes vêm com o peso/volume real embutido no texto da
unidade (ex: "un 500g"), não numa coluna separada. Esta normalização
precisa acontecer antes de qualquer divisão preço÷quantidade, senão o
custo unitário sai errado por ordem de grandeza silenciosamente.
"""

import re
from pathlib import Path

import openpyxl

from mcp_server.modelos import ItemDespensa

_UNIDADE_SIMPLES = {
    "kg": ("g", 1000.0),
    "g": ("g", 1.0),
    "l": ("ml", 1000.0),
    "ml": ("ml", 1.0),
    "un": ("un", 1.0),
}

_PADRAO_COMPOSTO = re.compile(
    r"^(?:un|balde)\s+(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)$", re.IGNORECASE
)


class UnidadeDesconhecidaError(ValueError):
    """Unidade fora dos padrões conhecidos (simples ou composta) — falha rápida,
    nunca aplicar a fórmula genérica silenciosamente para um caso não mapeado."""


def normalizar_unidade(unidade: str) -> tuple[str, float]:
    """Retorna (unidade_base, fator_multiplicador) tal que
    quantidade_base = quantidade_na_planilha * fator_multiplicador.

    Para unidades compostas (ex: "un 500g"), o fator já embute o peso/volume
    real por unidade de compra — 1 "un 500g" vira fator 500 (unidade_base "g").
    """
    unidade_norm = unidade.strip().lower()

    if unidade_norm in _UNIDADE_SIMPLES:
        return _UNIDADE_SIMPLES[unidade_norm]

    m = _PADRAO_COMPOSTO.match(unidade_norm)
    if m:
        valor_embutido = float(m.group(1).replace(",", "."))
        unidade_embutida = m.group(2).lower()
        unidade_base, fator_embutido = _UNIDADE_SIMPLES[unidade_embutida]
        return unidade_base, valor_embutido * fator_embutido

    raise UnidadeDesconhecidaError(
        f"Unidade '{unidade}' não reconhecida (nem simples nem composta conhecida). "
        "Normalização é uma lista curada, não um parser genérico."
    )


def _ler_aba(caminho: Path, nome_aba: str) -> list[dict]:
    wb = openpyxl.load_workbook(caminho, data_only=True)
    ws = wb[nome_aba]
    linhas = list(ws.iter_rows(values_only=True))
    cabecalho = linhas[0]
    return [dict(zip(cabecalho, linha)) for linha in linhas[1:] if linha[0] is not None]


def carregar_despensa(caminho_xlsx: str | Path) -> dict[str, ItemDespensa]:
    """Lê Despensa + Precos, cruza por nome de ingrediente, normaliza unidade
    e calcula custo unitário. Retorna dict chaveado pelo nome original do
    ingrediente (como aparece na planilha) -> ItemDespensa.
    """
    caminho = Path(caminho_xlsx)
    despensa_rows = _ler_aba(caminho, "Despensa")
    precos_rows = _ler_aba(caminho, "Precos")

    precos_por_nome = {row["Ingrediente"]: row for row in precos_rows}

    despensa: dict[str, ItemDespensa] = {}
    for row in despensa_rows:
        nome = row["Ingrediente"]
        preco_row = precos_por_nome.get(nome)
        if preco_row is None:
            raise ValueError(
                f"Ingrediente '{nome}' está em Despensa mas não em Precos — "
                "impossível derivar custo unitário sem preço pago."
            )

        unidade_base_estoque, fator_estoque = normalizar_unidade(row["Unidade"])
        unidade_base_precos, fator_precos = normalizar_unidade(preco_row["Unidade"])
        if unidade_base_estoque != unidade_base_precos:
            raise ValueError(
                f"'{nome}': unidade de estoque ({row['Unidade']}) e de preço "
                f"({preco_row['Unidade']}) normalizam para bases diferentes "
                f"({unidade_base_estoque} vs {unidade_base_precos})."
            )

        quantidade_disponivel_base = row["Quantidade em estoque"] * fator_estoque
        quantidade_comprada_base = preco_row["Quantidade comprada"] * fator_precos
        custo_unitario = preco_row["Preço total pago (R$)"] / quantidade_comprada_base

        despensa[nome] = ItemDespensa(
            nome=nome,
            quantidade_disponivel=quantidade_disponivel_base,
            unidade_base=unidade_base_estoque,
            custo_unitario=custo_unitario,
        )

    return despensa
