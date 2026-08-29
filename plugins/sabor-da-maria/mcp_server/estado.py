"""Estado da sessão: despensa + orçamento restante, em memória de processo.

Reset a cada novo `hermes` é comportamento intencional (fotografia do
início da sessão), não persistência entre execuções.

Regra de design: `registrar_prato_aceito` é o ÚNICO ponto de mutação, e ele
mesmo recalcula a viabilidade (via `verificar_viabilidade`) em vez de
confiar num custo_complementar que o agente já teria calculado antes — isso
fecha a porta pra qualquer drift entre "o que foi checado" e "o que foi de
fato debitado", sem depender de o agente passar o número certo.
"""

from mcp_server.conversao_unidades import converter
from mcp_server.modelos import (
    Cardapio,
    IngredienteReceita,
    ItemCardapio,
    ItemConsumido,
    ItemFaltante,
    PerfilOperacional,
    PratoAceito,
    ResultadoAvaliacaoPreco,
    ResultadoViabilidade,
)
from mcp_server.planilha import carregar_despensa
from mcp_server.precificacao import avaliar_preco

ORCAMENTO_INICIAL = 80.00


class IngredienteNaoEncontradoError(ValueError):
    """`nome_despensa` informado pelo agente não existe no estado atual."""


class PrecoNaoInformadoError(ValueError):
    """Ingrediente fora da despensa sem `preco_estimado_por_unidade` —
    a tool nunca busca preço sozinha nem assume um valor."""


class PratoNaoAceitoError(ValueError):
    """`calcular_precificacao` chamado para um prato que ainda não passou
    por `registrar_prato_aceito` nesta sessão — não há cmv_total confiável
    pra usar."""


def _mesclar_confirmados(atuais: list[str], novos: list[str] | None) -> list[str]:
    """Acrescenta itens novos à lista cumulativa, sem duplicar (comparação
    case-insensitive, mas preserva a grafia original de quem chegou primeiro)."""
    if not novos:
        return atuais
    vistos = {item.strip().lower() for item in atuais}
    for novo in novos:
        chave = novo.strip().lower()
        if chave and chave not in vistos:
            atuais.append(novo.strip())
            vistos.add(chave)
    return atuais


def _itens_nao_confirmados(necessarios: list[str] | None, confirmados: list[str]) -> list[str]:
    """Dos itens que a receita exige, quais ainda não estão na lista
    confirmada — comparação case-insensitive, preservando a grafia de
    `necessarios` no retorno (é o que o agente vai reperguntar pra ela)."""
    if not necessarios:
        return []
    confirmados_norm = {c.strip().lower() for c in confirmados}
    return [n for n in necessarios if n.strip().lower() not in confirmados_norm]


class EstadoSessao:
    def __init__(self, caminho_xlsx: str):
        self.despensa = carregar_despensa(caminho_xlsx)
        self.orcamento_restante = ORCAMENTO_INICIAL
        self.pratos_aceitos: list[PratoAceito] = []
        self.perfil_operacional = PerfilOperacional()

    def atualizar_perfil_operacional(
        self,
        utensilios: list[str] | None = None,
        tecnicas: list[str] | None = None,
        restricoes: list[str] | None = None,
        restricoes_perguntadas: bool = False,
    ) -> PerfilOperacional:
        """Acrescenta fatos confirmados ao perfil cumulativo da sessão.
        Chamar sem nenhum argumento serve como leitura do estado atual.

        `restricoes_perguntadas=True` sinaliza que a Dona Maria deu uma
        resposta explícita à pergunta sobre restrições operacionais nesta
        sessão — mesmo que a resposta tenha sido "nenhuma" (nesse caso,
        `restricoes` continua vazia, mas o flag vai a True mesmo assim).
        Nunca passe True só porque a pergunta foi feita na mensagem — só
        depois que ela responder de fato. Uma vez True, fica True pelo
        resto da sessão (sticky, como os outros campos cumulativos)."""
        self.perfil_operacional.utensilios_confirmados = _mesclar_confirmados(
            self.perfil_operacional.utensilios_confirmados, utensilios
        )
        self.perfil_operacional.tecnicas_confirmadas = _mesclar_confirmados(
            self.perfil_operacional.tecnicas_confirmadas, tecnicas
        )
        self.perfil_operacional.restricoes_operacionais = _mesclar_confirmados(
            self.perfil_operacional.restricoes_operacionais, restricoes
        )
        if restricoes_perguntadas:
            self.perfil_operacional.restricoes_perguntadas = True
        return self.perfil_operacional

    def _avaliar(
        self,
        ingredientes: list[IngredienteReceita],
        utensilios_necessarios: list[str] | None = None,
        tecnicas_necessarias: list[str] | None = None,
        porcoes: int | None = None,
    ) -> tuple[ResultadoViabilidade, dict[str, float]]:
        """Núcleo compartilhado por verificar_viabilidade e registrar_prato_aceito.

        Retorna o resultado de viabilidade + um dict nome_despensa ->
        quantidade_base_necessaria, pra quem for mutar o estado não
        precisar refazer a conta.
        """
        itens_faltantes: list[ItemFaltante] = []
        itens_nao_calculaveis: list[str] = []
        quantidades_necessarias: dict[str, float] = {}
        cmv_total = 0.0

        # 1ª passada: converte e ACUMULA por item da despensa (nunca decide
        # OK/faltante ainda) — uma receita pode citar o mesmo item em mais
        # de uma entrada e a demanda real é a soma das duas, não a última lida.
        for ing in ingredientes:
            if ing.nome_despensa is not None:
                item = self.despensa.get(ing.nome_despensa)
                if item is None:
                    raise IngredienteNaoEncontradoError(
                        f"'{ing.nome_despensa}' não existe na despensa atual — "
                        "confira consultar_despensa() antes de chamar esta tool."
                    )

                resultado_conv = converter(item.nome, ing.quantidade, ing.unidade, item.unidade_base)
                if not resultado_conv.sucesso:
                    itens_nao_calculaveis.append(f"{ing.nome_original}: {resultado_conv.motivo}")
                    continue

                quantidade_necessaria = resultado_conv.quantidade_base
                quantidades_necessarias[item.nome] = (
                    quantidades_necessarias.get(item.nome, 0.0) + quantidade_necessaria
                )
                # CMV conta o custo de TODO o ingrediente usado (já possuído
                # ou comprado agora) — diferente de custo_complementar_total,
                # que só soma o que falta comprar (ver ItemFaltante abaixo).
                cmv_total += quantidade_necessaria * item.custo_unitario
            else:
                if ing.preco_estimado_por_unidade is None:
                    raise PrecoNaoInformadoError(
                        f"'{ing.nome_original}' não está na despensa e não veio "
                        "preco_estimado_por_unidade — busque via web_search e confirme "
                        "o valor com a Dona Maria antes de chamar esta tool."
                    )
                custo_ingrediente = ing.quantidade * ing.preco_estimado_por_unidade
                cmv_total += custo_ingrediente
                itens_faltantes.append(
                    ItemFaltante(
                        nome=ing.nome_original,
                        quantidade_faltante=ing.quantidade,
                        unidade_base=ing.unidade,
                        custo=custo_ingrediente,
                        origem="nao_encontrado_na_despensa",
                    )
                )

        # 2ª passada: decide OK/faltante UMA VEZ por item da despensa, já
        # com a demanda total somada — checar entrada por entrada deixaria
        # passar um estouro que só aparece ao combinar duas entradas do
        # mesmo item (cada uma cabendo sozinha, juntas não).
        itens_ok: list[str] = []
        for nome_item, quantidade_necessaria in quantidades_necessarias.items():
            item = self.despensa[nome_item]
            if item.quantidade_disponivel >= quantidade_necessaria:
                itens_ok.append(nome_item)
            else:
                faltante = quantidade_necessaria - item.quantidade_disponivel
                itens_faltantes.append(
                    ItemFaltante(
                        nome=nome_item,
                        quantidade_faltante=faltante,
                        unidade_base=item.unidade_base,
                        custo=faltante * item.custo_unitario,
                        origem="despensa_insuficiente",
                    )
                )

        custo_complementar_total = sum(f.custo for f in itens_faltantes)
        orcamento_restante_apos = self.orcamento_restante - custo_complementar_total
        orcamento_suficiente = (
            custo_complementar_total <= self.orcamento_restante and not itens_nao_calculaveis
        )

        utensilios_faltantes = _itens_nao_confirmados(
            utensilios_necessarios, self.perfil_operacional.utensilios_confirmados
        )
        tecnicas_faltantes = _itens_nao_confirmados(
            tecnicas_necessarias, self.perfil_operacional.tecnicas_confirmadas
        )
        restricao_operacional_pendente = not self.perfil_operacional.restricoes_perguntadas

        if porcoes is not None and porcoes <= 0:
            raise ValueError(
                "porcoes deve ser maior que zero — sem saber quantas porções "
                "a receita rende não dá pra calcular o preço por porção."
            )
        cmv_por_porcao = (cmv_total / porcoes) if porcoes else None

        resultado = ResultadoViabilidade(
            prato="",  # preenchido pelo chamador
            itens_ok=itens_ok,
            itens_faltantes=itens_faltantes,
            custo_complementar_total=custo_complementar_total,
            orcamento_suficiente=orcamento_suficiente,
            orcamento_restante_apos=orcamento_restante_apos,
            itens_nao_calculaveis=itens_nao_calculaveis,
            utensilios_faltantes=utensilios_faltantes,
            tecnicas_faltantes=tecnicas_faltantes,
            restricao_operacional_pendente=restricao_operacional_pendente,
            pronto_para_aceitar=(
                orcamento_suficiente
                and not utensilios_faltantes
                and not tecnicas_faltantes
                and not restricao_operacional_pendente
            ),
            cmv_total=cmv_total,
            porcoes=porcoes,
            cmv_por_porcao=cmv_por_porcao,
        )
        return resultado, quantidades_necessarias

    def verificar_viabilidade(
        self,
        prato: str,
        ingredientes: list[IngredienteReceita],
        utensilios_necessarios: list[str] | None = None,
        tecnicas_necessarias: list[str] | None = None,
        porcoes: int | None = None,
    ) -> ResultadoViabilidade:
        resultado, _ = self._avaliar(ingredientes, utensilios_necessarios, tecnicas_necessarias, porcoes)
        resultado.prato = prato
        return resultado

    def registrar_prato_aceito(
        self,
        prato: str,
        ingredientes: list[IngredienteReceita],
        porcoes: int,
        utensilios_necessarios: list[str] | None = None,
        tecnicas_necessarias: list[str] | None = None,
        fonte_url: str | None = None,
    ) -> ResultadoViabilidade:
        """Único ponto de mutação: recalcula viabilidade E pré-requisitos
        operacionais e, se ambos couberem, decrementa despensa + orçamento e
        registra no histórico. Recusa a mutação (levanta erro) se o
        orçamento não fechar OU se algum utensílio/técnica listado em
        `utensilios_necessarios`/`tecnicas_necessarias` ainda não tiver sido
        confirmado via `atualizar_perfil_operacional` — nunca aceita um
        custo_complementar vindo pronto do agente, e nunca aceita a palavra
        do agente sozinha de que ela "tem tudo que precisa" sem essa
        confirmação já ter sido registrada no perfil.

        `porcoes` é obrigatório (quantas porções a receita rende) — a
        Dona Maria vende porção a porção, não o lote inteiro, então o
        preço final precisa ser calculado sobre cmv_total/porcoes, nunca
        sobre o CMV do lote.

        `fonte_url` é opcional: a URL da receita original, se houver, só
        pra ficar disponível depois via `consultar_cardapio` — nunca
        usada em nenhum cálculo."""
        if porcoes is None or porcoes <= 0:
            raise ValueError(
                "porcoes é obrigatório e deve ser maior que zero — sem "
                "saber quantas porções a receita rende não dá pra calcular "
                "o preço por porção que a Dona Maria vai vender."
            )
        resultado, quantidades_necessarias = self._avaliar(
            ingredientes, utensilios_necessarios, tecnicas_necessarias, porcoes
        )
        resultado.prato = prato

        if not resultado.pronto_para_aceitar:
            raise ValueError(
                f"Prato '{prato}' não está pronto para ser aceito "
                f"(orcamento_restante={self.orcamento_restante:.2f}, "
                f"custo_complementar_total={resultado.custo_complementar_total:.2f}, "
                f"itens_nao_calculaveis={resultado.itens_nao_calculaveis}, "
                f"utensilios_faltantes={resultado.utensilios_faltantes}, "
                f"tecnicas_faltantes={resultado.tecnicas_faltantes}, "
                f"restricao_operacional_pendente={resultado.restricao_operacional_pendente}). "
                "Nada foi debitado. Se for pré-requisito operacional, confirme "
                "com a Dona Maria e chame atualizar_perfil_operacional antes "
                "de tentar novamente (restricoes_perguntadas=True só depois "
                "dela responder de fato à pergunta sobre restrições)."
            )

        itens_consumidos: list[ItemConsumido] = []
        for nome_item, quantidade_necessaria in quantidades_necessarias.items():
            item = self.despensa[nome_item]
            item.quantidade_disponivel = max(0.0, item.quantidade_disponivel - quantidade_necessaria)
            itens_consumidos.append(
                ItemConsumido(
                    nome_despensa=nome_item,
                    quantidade_usada=quantidade_necessaria,
                    unidade_base=item.unidade_base,
                )
            )

        self.orcamento_restante = resultado.orcamento_restante_apos
        self.pratos_aceitos.append(
            PratoAceito(
                prato=prato,
                custo_complementar=resultado.custo_complementar_total,
                cmv_total=resultado.cmv_total,
                porcoes=porcoes,
                cmv_por_porcao=resultado.cmv_por_porcao,
                itens_consumidos=itens_consumidos,
                fonte_url=fonte_url,
            )
        )
        return resultado

    def confirmar_preco_final(self, prato: str, preco: float) -> ResultadoAvaliacaoPreco:
        """Único ponto de mutação do preço de venda: recalcula o resultado
        financeiro do zero (nunca confia num valor pré-calculado pelo
        agente — mesmo padrão de `registrar_prato_aceito`) e só então grava
        `preco` como `preco_confirmado` no `PratoAceito` correspondente, pra
        aparecer depois em `consultar_cardapio`. Não bloqueia preço abaixo
        do mínimo — a decisão final de preço é sempre dela; quem avisa do
        prejuízo é o agente, usando o `resultado_financeiro` retornado
        aqui."""
        prato_aceito = self.obter_prato_aceito(prato)
        resultado = avaliar_preco(prato, preco, prato_aceito.cmv_total, prato_aceito.porcoes)
        prato_aceito.preco_confirmado = preco
        return resultado

    def consultar_cardapio(self) -> Cardapio:
        """Lista todos os pratos aceitos nesta sessão (nome, porções,
        cmv_por_porcao, preço confirmado quando houver, e a URL da receita
        quando informada) — fonte determinística pra qualquer pergunta
        sobre o cardápio de lançamento montado até agora."""
        return Cardapio(
            pratos=[
                ItemCardapio(
                    nome=p.prato,
                    porcoes=p.porcoes,
                    cmv_por_porcao=p.cmv_por_porcao,
                    preco_confirmado=p.preco_confirmado,
                    fonte_url=p.fonte_url,
                )
                for p in self.pratos_aceitos
            ]
        )

    def obter_prato_aceito(self, prato: str) -> PratoAceito:
        """Busca o registro completo (cmv_total, porcoes, cmv_por_porcao)
        já travado no momento do aceite (a última vez que `prato` foi
        registrado nesta sessão) — nunca recalculado aqui, nunca informado
        pelo agente."""
        for registrado in reversed(self.pratos_aceitos):
            if registrado.prato == prato:
                return registrado
        raise PratoNaoAceitoError(
            f"'{prato}' ainda não foi aceito nesta sessão — chame "
            "registrar_prato_aceito antes de calcular_precificacao."
        )

    def obter_cmv_prato_aceito(self, prato: str) -> float:
        """Atalho pra `obter_prato_aceito(prato).cmv_total`."""
        return self.obter_prato_aceito(prato).cmv_total
