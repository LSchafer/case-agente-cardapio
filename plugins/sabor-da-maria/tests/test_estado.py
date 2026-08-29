import math
from pathlib import Path

import pytest

from mcp_server.estado import (
    ORCAMENTO_INICIAL,
    EstadoSessao,
    IngredienteNaoEncontradoError,
    PrecoNaoInformadoError,
    PratoNaoAceitoError,
)
from mcp_server.modelos import IngredienteReceita

XLSX_PATH = Path(__file__).parent.parent / "data" / "despensa_dona_maria.xlsx"


def aprox(a: float, b: float, tol: float = 1e-4) -> bool:
    return math.isclose(a, b, abs_tol=tol)


@pytest.fixture
def estado() -> EstadoSessao:
    return EstadoSessao(str(XLSX_PATH))


def test_estado_inicial(estado):
    assert aprox(estado.orcamento_restante, ORCAMENTO_INICIAL)
    assert len(estado.despensa) == 37
    assert estado.pratos_aceitos == []


def test_viabilidade_sem_faltante(estado):
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    resultado = estado.verificar_viabilidade("Arroz simples", ingredientes)
    assert resultado.itens_ok == ["Arroz branco tipo 1"]
    assert resultado.itens_faltantes == []
    assert resultado.custo_complementar_total == 0.0
    assert resultado.orcamento_suficiente
    assert aprox(resultado.orcamento_restante_apos, ORCAMENTO_INICIAL)
    # verificar_viabilidade não muta estado
    assert aprox(estado.despensa["Arroz branco tipo 1"].quantidade_disponivel, 5000.0)


def test_viabilidade_com_despensa_insuficiente(estado):
    # despensa tem 2kg de peito de frango; receita pede 3kg
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=3, unidade="kg", nome_despensa="Peito de frango")
    ]
    resultado = estado.verificar_viabilidade("Frango extra", ingredientes)
    assert resultado.itens_ok == []
    assert len(resultado.itens_faltantes) == 1
    faltante = resultado.itens_faltantes[0]
    assert faltante.origem == "despensa_insuficiente"
    assert aprox(faltante.quantidade_faltante, 1000.0)
    custo_unitario_frango = 28.0 / 2000.0
    assert aprox(faltante.custo, 1000.0 * custo_unitario_frango)
    assert resultado.orcamento_suficiente


def test_ingrediente_fora_da_despensa_com_preco_confirmado(estado):
    ingredientes = [
        IngredienteReceita(
            nome_original="manjericão fresco",
            quantidade=50,
            unidade="g",
            nome_despensa=None,
            preco_estimado_por_unidade=0.08,
        )
    ]
    resultado = estado.verificar_viabilidade("Molho pesto", ingredientes)
    assert len(resultado.itens_faltantes) == 1
    assert resultado.itens_faltantes[0].origem == "nao_encontrado_na_despensa"
    assert aprox(resultado.custo_complementar_total, 4.0)
    assert resultado.orcamento_suficiente


def test_ingrediente_fora_da_despensa_sem_preco_levanta_erro(estado):
    ingredientes = [
        IngredienteReceita(nome_original="manjericão fresco", quantidade=50, unidade="g", nome_despensa=None)
    ]
    with pytest.raises(PrecoNaoInformadoError):
        estado.verificar_viabilidade("Molho pesto", ingredientes)


def test_nome_despensa_invalido_levanta_erro(estado):
    ingredientes = [
        IngredienteReceita(nome_original="algo", quantidade=1, unidade="kg", nome_despensa="Ingrediente Inexistente")
    ]
    with pytest.raises(IngredienteNaoEncontradoError):
        estado.verificar_viabilidade("Prato qualquer", ingredientes)


def test_conversao_impossivel_bloqueia_orcamento_suficiente(estado):
    # "xícara" de Bacon não tem densidade conhecida -> não calculável
    ingredientes = [
        IngredienteReceita(nome_original="bacon", quantidade=1, unidade="xícara", nome_despensa="Bacon")
    ]
    resultado = estado.verificar_viabilidade("Prato com bacon", ingredientes)
    assert resultado.itens_nao_calculaveis
    assert not resultado.orcamento_suficiente


def test_registrar_prato_aceito_decrementa_estado(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=3, unidade="kg", nome_despensa="Peito de frango")
    ]
    resultado = estado.registrar_prato_aceito("Frango extra", ingredientes, porcoes=2)

    assert aprox(estado.despensa["Peito de frango"].quantidade_disponivel, 0.0)
    assert aprox(estado.orcamento_restante, ORCAMENTO_INICIAL - resultado.custo_complementar_total)
    assert len(estado.pratos_aceitos) == 1
    assert estado.pratos_aceitos[0].prato == "Frango extra"


def test_registrar_prato_aceito_recusa_quando_estoura_orcamento(estado):
    ingredientes = [
        IngredienteReceita(
            nome_original="trufa importada",
            quantidade=100,
            unidade="un",
            nome_despensa=None,
            preco_estimado_por_unidade=50.0,  # R$5000 total, muito acima dos R$80
        )
    ]
    with pytest.raises(ValueError):
        estado.registrar_prato_aceito("Prato inviável", ingredientes, porcoes=1)

    # nada deve ter mudado
    assert aprox(estado.orcamento_restante, ORCAMENTO_INICIAL)
    assert estado.pratos_aceitos == []


def test_orcamento_cumulativo_entre_pratos_aceitos(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ing1 = [IngredienteReceita(nome_original="frango", quantidade=3, unidade="kg", nome_despensa="Peito de frango")]
    ing2 = [
        IngredienteReceita(
            nome_original="manjericão fresco", quantidade=50, unidade="g", nome_despensa=None, preco_estimado_por_unidade=0.08
        )
    ]
    r1 = estado.registrar_prato_aceito("Frango extra", ing1, porcoes=2)
    orcamento_apos_1 = estado.orcamento_restante
    r2 = estado.registrar_prato_aceito("Molho pesto", ing2, porcoes=1)

    assert aprox(orcamento_apos_1, ORCAMENTO_INICIAL - r1.custo_complementar_total)
    assert aprox(estado.orcamento_restante, orcamento_apos_1 - r2.custo_complementar_total)
    assert len(estado.pratos_aceitos) == 2


def test_perfil_operacional_inicial_vazio(estado):
    perfil = estado.atualizar_perfil_operacional()
    assert perfil.utensilios_confirmados == []
    assert perfil.tecnicas_confirmadas == []
    assert perfil.restricoes_operacionais == []
    assert perfil.restricoes_perguntadas is False


def test_atualizar_perfil_operacional_acumula_sem_duplicar(estado):
    estado.atualizar_perfil_operacional(utensilios=["Batedeira"], tecnicas=["Ponto de neve"])
    perfil = estado.atualizar_perfil_operacional(
        utensilios=["batedeira", "Forma de bolo"], restricoes=["só fogão elétrico"]
    )

    assert perfil.utensilios_confirmados == ["Batedeira", "Forma de bolo"]
    assert perfil.tecnicas_confirmadas == ["Ponto de neve"]
    assert perfil.restricoes_operacionais == ["só fogão elétrico"]


def test_viabilidade_aponta_utensilio_e_tecnica_faltantes(estado):
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    resultado = estado.verificar_viabilidade(
        "Arroz de forno",
        ingredientes,
        utensilios_necessarios=["forma refratária"],
        tecnicas_necessarias=["gratinar"],
    )

    assert resultado.utensilios_faltantes == ["forma refratária"]
    assert resultado.tecnicas_faltantes == ["gratinar"]
    assert resultado.orcamento_suficiente
    assert not resultado.pronto_para_aceitar


def test_viabilidade_pronto_para_aceitar_apos_confirmar_perfil(estado):
    estado.atualizar_perfil_operacional(
        utensilios=["Forma refratária"], tecnicas=["Gratinar"], restricoes_perguntadas=True
    )
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    resultado = estado.verificar_viabilidade(
        "Arroz de forno",
        ingredientes,
        utensilios_necessarios=["forma refratária"],
        tecnicas_necessarias=["gratinar"],
    )

    assert resultado.utensilios_faltantes == []
    assert resultado.tecnicas_faltantes == []
    assert resultado.restricao_operacional_pendente is False
    assert resultado.pronto_para_aceitar


def test_viabilidade_restricao_pendente_bloqueia_pronto_para_aceitar(estado):
    # utensílio/técnica confirmados, mas ninguém perguntou sobre restrição ainda
    estado.atualizar_perfil_operacional(utensilios=["Forma refratária"], tecnicas=["Gratinar"])
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    resultado = estado.verificar_viabilidade(
        "Arroz de forno",
        ingredientes,
        utensilios_necessarios=["forma refratária"],
        tecnicas_necessarias=["gratinar"],
    )

    assert resultado.utensilios_faltantes == []
    assert resultado.tecnicas_faltantes == []
    assert resultado.restricao_operacional_pendente is True
    assert not resultado.pronto_para_aceitar


def test_restricoes_perguntadas_true_sem_nenhuma_restricao_listada(estado):
    # ela respondeu "nenhuma restrição" -- lista vazia, mas a pergunta foi
    # feita e respondida de verdade
    perfil = estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    assert perfil.restricoes_operacionais == []
    assert perfil.restricoes_perguntadas is True


def test_restricoes_perguntadas_e_sticky_entre_chamadas(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    # chamada seguinte sem passar o flag (default False) não deve resetar
    perfil = estado.atualizar_perfil_operacional(utensilios=["Faca"])
    assert perfil.restricoes_perguntadas is True


def test_registrar_prato_aceito_recusa_sem_restricoes_perguntadas(estado):
    estado.atualizar_perfil_operacional(utensilios=["forma refratária"], tecnicas=["gratinar"])
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    with pytest.raises(ValueError):
        estado.registrar_prato_aceito(
            "Arroz de forno",
            ingredientes,
            porcoes=1,
            utensilios_necessarios=["forma refratária"],
            tecnicas_necessarias=["gratinar"],
        )

    # nada deve ter mudado
    assert aprox(estado.despensa["Arroz branco tipo 1"].quantidade_disponivel, 5000.0)
    assert aprox(estado.orcamento_restante, ORCAMENTO_INICIAL)
    assert estado.pratos_aceitos == []


def test_registrar_prato_aceito_recusa_sem_utensilio_confirmado(estado):
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    with pytest.raises(ValueError):
        estado.registrar_prato_aceito(
            "Arroz de forno", ingredientes, porcoes=1, utensilios_necessarios=["forma refratária"]
        )

    # nada deve ter mudado: nem despensa, nem orçamento, nem histórico
    assert aprox(estado.despensa["Arroz branco tipo 1"].quantidade_disponivel, 5000.0)
    assert aprox(estado.orcamento_restante, ORCAMENTO_INICIAL)
    assert estado.pratos_aceitos == []


def test_cmv_total_conta_ingrediente_ja_na_despensa(estado):
    # frango já cabe todo na despensa -> custo_complementar_total é 0, mas
    # o CMV real do prato (custo de tudo que foi usado) não é zero.
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    resultado = estado.verificar_viabilidade("Frango simples", ingredientes)
    custo_unitario_frango = 28.0 / 2000.0
    assert resultado.custo_complementar_total == 0.0
    assert aprox(resultado.cmv_total, 1000.0 * custo_unitario_frango)


def test_cmv_total_conta_ingrediente_inteiro_com_despensa_insuficiente(estado):
    # despensa tem 2kg de frango, receita pede 3kg: custo_complementar_total
    # só cobre o 1kg que falta comprar, mas cmv_total precisa contar os 3kg
    # inteiros (o que já estava na despensa também tem custo real).
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=3, unidade="kg", nome_despensa="Peito de frango")
    ]
    resultado = estado.verificar_viabilidade("Frango extra", ingredientes)
    custo_unitario_frango = 28.0 / 2000.0
    assert aprox(resultado.custo_complementar_total, 1000.0 * custo_unitario_frango)
    assert aprox(resultado.cmv_total, 3000.0 * custo_unitario_frango)


def test_registrar_prato_aceito_persiste_cmv_total(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    resultado = estado.registrar_prato_aceito("Frango simples", ingredientes, porcoes=2)
    custo_unitario_frango = 28.0 / 2000.0

    assert aprox(resultado.cmv_total, 1000.0 * custo_unitario_frango)
    assert aprox(estado.obter_cmv_prato_aceito("Frango simples"), resultado.cmv_total)


def test_obter_cmv_prato_nao_aceito_levanta_erro(estado):
    with pytest.raises(PratoNaoAceitoError):
        estado.obter_cmv_prato_aceito("Prato que nunca foi registrado")


def test_obter_prato_aceito_nao_aceito_levanta_erro(estado):
    with pytest.raises(PratoNaoAceitoError):
        estado.obter_prato_aceito("Prato que nunca foi registrado")


def test_registrar_prato_aceito_aceita_apos_confirmar_perfil(estado):
    estado.atualizar_perfil_operacional(
        utensilios=["forma refratária"], tecnicas=["gratinar"], restricoes_perguntadas=True
    )
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    resultado = estado.registrar_prato_aceito(
        "Arroz de forno",
        ingredientes,
        porcoes=6,
        utensilios_necessarios=["forma refratária"],
        tecnicas_necessarias=["gratinar"],
    )

    assert resultado.pronto_para_aceitar
    assert len(estado.pratos_aceitos) == 1


def test_registrar_prato_aceito_exige_porcoes(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    with pytest.raises(ValueError):
        estado.registrar_prato_aceito("Frango simples", ingredientes, porcoes=None)

    # nada deve ter mudado
    assert aprox(estado.despensa["Peito de frango"].quantidade_disponivel, 2000.0)
    assert estado.pratos_aceitos == []


def test_registrar_prato_aceito_recusa_porcoes_zero_ou_negativo(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    with pytest.raises(ValueError):
        estado.registrar_prato_aceito("Frango simples", ingredientes, porcoes=0)
    with pytest.raises(ValueError):
        estado.registrar_prato_aceito("Frango simples", ingredientes, porcoes=-3)
    assert estado.pratos_aceitos == []


def test_registrar_prato_aceito_persiste_porcoes_e_cmv_por_porcao(estado):
    # Receita de R$50 rendendo 4 porções tem que travar
    # cmv_por_porcao=R$12,50, não deixar a precificação usar o CMV do
    # lote inteiro.
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(
            nome_original="ingrediente caro", quantidade=1, unidade="un", nome_despensa=None,
            preco_estimado_por_unidade=50.0,
        )
    ]
    resultado = estado.registrar_prato_aceito("Espaguete à bolonhesa", ingredientes, porcoes=4)

    assert aprox(resultado.cmv_total, 50.0)
    assert resultado.porcoes == 4
    assert aprox(resultado.cmv_por_porcao, 12.5)

    prato_aceito = estado.obter_prato_aceito("Espaguete à bolonhesa")
    assert prato_aceito.porcoes == 4
    assert aprox(prato_aceito.cmv_por_porcao, 12.5)
    assert aprox(prato_aceito.cmv_total, 50.0)


def test_consultar_cardapio_vazio_antes_de_qualquer_prato_aceito(estado):
    cardapio = estado.consultar_cardapio()
    assert cardapio.pratos == []


def test_registrar_prato_aceito_guarda_fonte_url(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    estado.registrar_prato_aceito(
        "Frango simples", ingredientes, porcoes=2, fonte_url="https://exemplo.com/receita"
    )
    prato_aceito = estado.obter_prato_aceito("Frango simples")
    assert prato_aceito.fonte_url == "https://exemplo.com/receita"


def test_registrar_prato_aceito_sem_fonte_url_fica_none(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    estado.registrar_prato_aceito("Frango simples", ingredientes, porcoes=2)
    assert estado.obter_prato_aceito("Frango simples").fonte_url is None


def test_prato_aceito_sem_preco_confirmado_ate_confirmar_preco_final(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    estado.registrar_prato_aceito("Frango simples", ingredientes, porcoes=2)
    assert estado.obter_prato_aceito("Frango simples").preco_confirmado is None

    cardapio = estado.consultar_cardapio()
    assert len(cardapio.pratos) == 1
    assert cardapio.pratos[0].preco_confirmado is None


def test_confirmar_preco_final_grava_preco_e_recalcula_do_zero(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")
    ]
    resultado_aceite = estado.registrar_prato_aceito("Frango simples", ingredientes, porcoes=2)

    resultado = estado.confirmar_preco_final("Frango simples", 10.0)
    assert aprox(resultado.preco_proposto, 10.0)
    assert aprox(resultado.cmv_total, resultado_aceite.cmv_total)
    assert aprox(resultado.resultado_financeiro, 0.90 * 10.0 - resultado_aceite.cmv_por_porcao)

    assert aprox(estado.obter_prato_aceito("Frango simples").preco_confirmado, 10.0)
    cardapio = estado.consultar_cardapio()
    assert aprox(cardapio.pratos[0].preco_confirmado, 10.0)


def test_confirmar_preco_final_nao_bloqueia_preco_abaixo_do_minimo(estado):
    # Preço final é sempre decisão dela -- confirmar_preco_final só avisa
    # via `abaixo_do_minimo`/`resultado_financeiro` negativo, nunca recusa.
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="frango", quantidade=3, unidade="kg", nome_despensa="Peito de frango")
    ]
    estado.registrar_prato_aceito("Frango extra", ingredientes, porcoes=2)

    resultado = estado.confirmar_preco_final("Frango extra", 0.01)
    assert resultado.abaixo_do_minimo is True
    assert resultado.resultado_financeiro < 0
    assert aprox(estado.obter_prato_aceito("Frango extra").preco_confirmado, 0.01)


def test_confirmar_preco_final_prato_nao_aceito_levanta_erro(estado):
    with pytest.raises(PratoNaoAceitoError):
        estado.confirmar_preco_final("Prato que nunca foi registrado", 10.0)


def test_consultar_cardapio_lista_multiplos_pratos_na_ordem_de_aceite(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ing1 = [IngredienteReceita(nome_original="frango", quantidade=1, unidade="kg", nome_despensa="Peito de frango")]
    ing2 = [
        IngredienteReceita(
            nome_original="manjericão fresco", quantidade=50, unidade="g", nome_despensa=None, preco_estimado_por_unidade=0.08
        )
    ]
    estado.registrar_prato_aceito("Frango simples", ing1, porcoes=2, fonte_url="https://exemplo.com/frango")
    estado.registrar_prato_aceito("Molho pesto", ing2, porcoes=1)
    estado.confirmar_preco_final("Frango simples", 15.0)

    cardapio = estado.consultar_cardapio()
    assert [p.nome for p in cardapio.pratos] == ["Frango simples", "Molho pesto"]
    assert cardapio.pratos[0].fonte_url == "https://exemplo.com/frango"
    assert aprox(cardapio.pratos[0].preco_confirmado, 15.0)
    assert cardapio.pratos[1].fonte_url is None
    assert cardapio.pratos[1].preco_confirmado is None


def test_ingrediente_repetido_soma_demanda_em_vez_de_sobrescrever(estado):
    # O mesmo item da despensa pode aparecer em duas entradas da receita
    # a demanda das duas precisa ser somada, não só a última considerada. 500g disponíveis,
    # pedindo 300g + 100g (400g no total, cabe).
    ingredientes = [
        IngredienteReceita(nome_original="manteiga do molho", quantidade=300, unidade="g", nome_despensa="Manteiga"),
        IngredienteReceita(nome_original="manteiga pra untar", quantidade=100, unidade="g", nome_despensa="Manteiga"),
    ]
    resultado = estado.verificar_viabilidade("Prato com manteiga repetida", ingredientes)

    assert resultado.itens_ok == ["Manteiga"]
    assert resultado.itens_faltantes == []
    # CMV já somava certo antes do fix -- confirma que continua certo.
    custo_unitario_manteiga = 20.0 / 500.0
    assert aprox(resultado.cmv_total, 400.0 * custo_unitario_manteiga)


def test_registrar_prato_aceito_debita_soma_de_ingrediente_repetido(estado):
    estado.atualizar_perfil_operacional(restricoes_perguntadas=True)
    ingredientes = [
        IngredienteReceita(nome_original="manteiga do molho", quantidade=300, unidade="g", nome_despensa="Manteiga"),
        IngredienteReceita(nome_original="manteiga pra untar", quantidade=100, unidade="g", nome_despensa="Manteiga"),
    ]
    estado.registrar_prato_aceito("Prato com manteiga repetida", ingredientes, porcoes=1)

    # Debita a demanda combinada das duas entradas (300g + 100g = 400g),
    # não só a última.
    assert aprox(estado.despensa["Manteiga"].quantidade_disponivel, 100.0)


def test_ingrediente_repetido_estoura_despensa_so_quando_somado(estado):
    # Cada entrada sozinha cabe nos 500g de manteiga (300g e 250g), mas
    # juntas (550g) estouram -- isso só é pego se a checagem soma primeiro.
    ingredientes = [
        IngredienteReceita(nome_original="manteiga do molho", quantidade=300, unidade="g", nome_despensa="Manteiga"),
        IngredienteReceita(nome_original="manteiga pra untar", quantidade=250, unidade="g", nome_despensa="Manteiga"),
    ]
    resultado = estado.verificar_viabilidade("Prato que estoura manteiga combinada", ingredientes)

    assert resultado.itens_ok == []
    assert len(resultado.itens_faltantes) == 1
    faltante = resultado.itens_faltantes[0]
    assert faltante.nome == "Manteiga"
    assert faltante.origem == "despensa_insuficiente"
    assert aprox(faltante.quantidade_faltante, 50.0)  # 550 pedido - 500 disponível
    custo_unitario_manteiga = 20.0 / 500.0
    assert aprox(faltante.custo, 50.0 * custo_unitario_manteiga)


def test_verificar_viabilidade_aceita_porcoes_opcional(estado):
    ingredientes = [
        IngredienteReceita(nome_original="arroz", quantidade=1, unidade="kg", nome_despensa="Arroz branco tipo 1")
    ]
    sem_porcoes = estado.verificar_viabilidade("Arroz simples", ingredientes)
    assert sem_porcoes.porcoes is None
    assert sem_porcoes.cmv_por_porcao is None

    com_porcoes = estado.verificar_viabilidade("Arroz simples", ingredientes, porcoes=5)
    assert com_porcoes.porcoes == 5
    assert aprox(com_porcoes.cmv_por_porcao, com_porcoes.cmv_total / 5)
