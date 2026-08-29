"""Entry point do servidor MCP — expõe as tools determinísticas de despensa,
viabilidade, aceite de prato e precificação.

Roda via stdio, spawnado pelo Hermes como Agent Plugin deste profile. O
estado (despensa + orçamento) é carregado uma vez, na subida do processo,
e vive em memória enquanto o processo estiver de pé — reset intencional a
cada nova conversa iniciada.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_server.estado import EstadoSessao
from mcp_server.modelos import (
    Cardapio,
    DespensaAtual,
    IngredienteReceita,
    ItemDespensaResumo,
    PerfilOperacional,
    ResultadoAvaliacaoPreco,
    ResultadoPrecificacao,
    ResultadoViabilidade,
)
from mcp_server.precificacao import avaliar_preco, calcular_cenarios

XLSX_PATH = Path(__file__).resolve().parent.parent / "data" / "despensa_dona_maria.xlsx"

mcp = FastMCP("sabor-da-maria")
_estado = EstadoSessao(str(XLSX_PATH))


@mcp.tool()
def consultar_despensa() -> DespensaAtual:
    """Retorna a despensa atual (nome, quantidade disponível, unidade-base,
    custo unitário por unidade-base) e o orçamento restante em R$. Use isso
    pra casar o nome de cada ingrediente de uma receita com o nome exato de
    um item da despensa antes de chamar verificar_viabilidade — o de-para
    de nome é responsabilidade sua, não desta tool."""
    return DespensaAtual(
        despensa=[
            ItemDespensaResumo(
                nome=item.nome,
                quantidade_disponivel=item.quantidade_disponivel,
                unidade_base=item.unidade_base,
                custo_unitario=item.custo_unitario,
            )
            for item in _estado.despensa.values()
        ],
        orcamento_restante=_estado.orcamento_restante,
    )


@mcp.tool()
def atualizar_perfil_operacional(
    utensilios: list[str] | None = None,
    tecnicas: list[str] | None = None,
    restricoes: list[str] | None = None,
    restricoes_perguntadas: bool = False,
) -> PerfilOperacional:
    """Registra fatos que a Dona Maria confirmou sobre a própria cozinha:
    utensílios que ela tem, técnicas/habilidades que ela já sabe fazer, e
    restrições operacionais (ex: só tem fogão elétrico, não pode ficar mais
    de 1h cozinhando). É cumulativo e vale pro resto da sessão — chame
    sempre que ela confirmar algo novo, nunca guarde isso só na conversa.

    Chamar sem nenhum argumento serve como leitura do estado atual (útil
    antes de perguntar algo a ela, pra não repetir pergunta já respondida
    nesta sessão).

    Isso é o que alimenta o guardrail de `registrar_prato_aceito`: um
    utensílio/técnica só conta como "confirmado" para aquela tool depois de
    ter passado por aqui. O conteúdo de `restricoes` continua sendo
    orientação qualitativa pra Fase 2 (não há um checklist de "restrições
    necessárias" por receita, como existe pra utensílio/técnica) — mas o
    fato de a pergunta ter sido feita E respondida é validado por código:
    passe `restricoes_perguntadas=True` só depois que ela responder de
    verdade (mesmo que a resposta seja "nenhuma restrição"), nunca
    proativamente só porque a pergunta foi enviada. Sem isso,
    `registrar_prato_aceito` recusa o prato mesmo com tudo mais OK.
    """
    return _estado.atualizar_perfil_operacional(utensilios, tecnicas, restricoes, restricoes_perguntadas)


@mcp.tool()
def verificar_viabilidade(
    prato: str,
    ingredientes: list[IngredienteReceita],
    utensilios_necessarios: list[str] | None = None,
    tecnicas_necessarias: list[str] | None = None,
    porcoes: int | None = None,
) -> ResultadoViabilidade:
    """Verifica se um prato é viável: cruza os ingredientes da receita com a
    despensa atual, calcula o que falta comprar e o custo disso, checa se
    cabe no orçamento restante, E checa se os utensílios/técnicas exigidos
    já foram confirmados via `atualizar_perfil_operacional`. NÃO muta
    estado — pode ser chamada quantas vezes for preciso pra simular
    candidatas antes de qualquer compromisso.

    Para cada ingrediente:
    - Se ele existir na despensa: preencha `nome_despensa` com o nome EXATO
      retornado por consultar_despensa(). A conversão de unidade (xícara,
      colher, etc.) é feita internamente pela tool — nunca converta você
      mesmo.
    - Se ele NÃO existir na despensa: deixe `nome_despensa` nulo e informe
      `preco_estimado_por_unidade` (R$ por unidade de `quantidade`/
      `unidade`, já normalizada por você). Esse preço precisa ter vindo de
      busca na web E já ter sido confirmado com a Dona Maria antes desta
      chamada — nunca estimado sem checagem (ver SOUL.md).

    `utensilios_necessarios`/`tecnicas_necessarias` são o que a RECEITA
    exige (ex: ["batedeira"], ["ponto de neve"]) — passe a lista completa
    toda vez, a tool compara contra o que já está confirmado no perfil.
    Se vier algo em `utensilios_faltantes`/`tecnicas_faltantes`, pergunte a
    ela e chame `atualizar_perfil_operacional` antes de seguir.

    `porcoes` (quantas porções a receita rende) é opcional aqui — se você
    já souber (a maioria das receitas informa isso junto dos ingredientes),
    passe pra já ver `cmv_por_porcao` na simulação. Se ainda não souber,
    tudo bem chamar sem isso agora, mas `registrar_prato_aceito` VAI exigir
    — a Dona Maria vende porção a porção, não a receita inteira de uma vez.

    Se `itens_nao_calculaveis` vier não-vazio, `orcamento_suficiente` já
    vem forçado como False — trate isso como "não sei calcular ainda", não
    como "não cabe no orçamento", e resolva a lacuna (perguntar a ela, ou
    achar outra forma de medir o ingrediente) antes de prosseguir.

    `pronto_para_aceitar` resume tudo: só é True quando orçamento fecha,
    não há utensílio/técnica faltando, E a pergunta sobre restrições
    operacionais já foi feita e respondida (`restricao_operacional_pendente
    == False`) — é a mesma condição que `registrar_prato_aceito` vai
    exigir. Se `restricao_operacional_pendente` vier True, pergunte a ela
    sobre restrições e chame `atualizar_perfil_operacional` com
    `restricoes_perguntadas=True` antes de seguir.
    """
    return _estado.verificar_viabilidade(
        prato, ingredientes, utensilios_necessarios, tecnicas_necessarias, porcoes
    )


@mcp.tool()
def registrar_prato_aceito(
    prato: str,
    ingredientes: list[IngredienteReceita],
    porcoes: int,
    utensilios_necessarios: list[str] | None = None,
    tecnicas_necessarias: list[str] | None = None,
    fonte_url: str | None = None,
) -> ResultadoViabilidade:
    """Registra a aceitação definitiva de um prato: recalcula viabilidade E
    pré-requisitos operacionais na hora e, se ambos fecharem, decrementa
    despensa e orçamento restante de forma permanente pro resto da sessão
    (efeito cumulativo entre pratos).

    Só chame isso depois que a Dona Maria já confirmou explicitamente que
    gostou do prato. O checklist de utensílio/habilidade É validado por
    esta tool (não só por instrução de prompt): passe em
    `utensilios_necessarios`/`tecnicas_necessarias` tudo que a receita
    exige — a tool recusa e não muda nada se algum item aí ainda não tiver
    sido confirmado via `atualizar_perfil_operacional` (ver SOUL.md,
    "Elicitando utensílio/habilidade"). Isso garante que a sequência de elicitação
    realmente aconteceu antes do compromisso, ainda que a veracidade do que
    foi confirmado dependa da conversa (não existe uma "planilha de
    utensílios" pra checar contra, ao contrário da despensa).

    `porcoes` é OBRIGATÓRIO: quantas porções a receita rende (extraia da
    própria receita — a maioria informa isso junto dos ingredientes; se
    não informar, pergunte à Dona Maria em vez de estimar). A tool recusa
    e não muda nada se `porcoes` vier ausente ou <= 0 — sem isso não dá
    pra calcular o preço por porção que ela realmente vai vender, só o
    custo do lote inteiro.

    Levanta erro e não muda nada se a viabilidade recalculada não for
    positiva no momento do registro (ex: orçamento mudou desde a última
    verificação por causa de outro prato aceito antes), OU se
    utensílio/técnica necessários ainda não estiverem confirmados, OU se a
    pergunta sobre restrições operacionais ainda não tiver sido feita e
    respondida nesta sessão (`atualizar_perfil_operacional` com
    `restricoes_perguntadas=True`), OU se `porcoes` for inválido.

    O retorno traz `cmv_total` (custo de TODOS os ingredientes usados,
    já possuídos ou comprados agora — diferente de
    `custo_complementar_total`, que só soma o que foi comprado) e
    `cmv_por_porcao` (= cmv_total / porcoes). Esses são os números travados
    que `calcular_precificacao(prato)`/`avaliar_preco_final(prato, ...)`
    vão usar depois — você não precisa (e não deve) recalcular ou
    repassar nenhum deles.

    `fonte_url` é opcional: passe a URL da receita original se você tiver
    uma (da busca da Fase 2), só pra ficar disponível depois em
    `consultar_cardapio` — nunca entra em nenhum cálculo."""
    return _estado.registrar_prato_aceito(
        prato, ingredientes, porcoes, utensilios_necessarios, tecnicas_necessarias, fonte_url
    )


@mcp.tool()
def calcular_precificacao(prato: str) -> ResultadoPrecificacao:
    """Calcula o preço mínimo de venda **por porção** (cmv_por_porcao /
    0,90, considerando a taxa de 10% da plataforma) e 3 cenários de preço
    por porção com lucro-alvo de 30%/50%/80% sobre o cmv_por_porcao — nunca
    sobre o `cmv_total` do lote inteiro, já que a Dona Maria vende porção a
    porção. Usa o `cmv_total`/`porcoes` que já foram calculados e travados
    no momento de `registrar_prato_aceito` para este `prato` — você NUNCA
    informa nem soma nada. Cada cenário já vem com `taxa_plataforma` (o
    valor em R$ da taxa de 10% sobre aquele `preco`) pronto — nunca
    recalcule isso à parte (de cabeça ou com qualquer ferramenta). Levanta
    erro se `prato` ainda não tiver sido aceito nesta sessão. Apresente os
    3 cenários pra Dona Maria e deixe a escolha final com ela."""
    prato_aceito = _estado.obter_prato_aceito(prato)
    return calcular_cenarios(prato, prato_aceito.cmv_total, prato_aceito.porcoes)


@mcp.tool()
def avaliar_preco_final(prato: str, preco_proposto: float) -> ResultadoAvaliacaoPreco:
    """Avalia UM preço específico **por porção** contra o cmv_por_porcao
    travado de `prato` (= cmv_total / porcoes, nunca o CMV do lote inteiro)
    — use isso pra QUALQUER preço que a Dona Maria proponha na Fase 5, não
    só as opções A/B/C: ela pode preferir um valor livre, e o preço final
    não deve ficar travado nas 3 sugestões. Sempre chame esta tool antes de
    tratar um preço como "fechado" — nunca calcule lucro/prejuízo sozinho.

    Se `resultado_financeiro` vier negativo (ou `abaixo_do_minimo=True`),
    isso é prejuízo real: avise a Dona Maria explicitamente com o valor
    exato e só considere o preço confirmado depois que ela disser que quer
    seguir mesmo assim. Levanta erro se `prato` ainda não tiver sido
    aceito nesta sessão (mesma condição de `calcular_precificacao`).

    Esta tool só simula — pode chamar quantas vezes precisar, nada é
    gravado. Depois que ela confirmar de vez qual preço quer usar, chame
    `confirmar_preco_final(prato, preco)` pra esse valor aparecer em
    `consultar_cardapio`."""
    prato_aceito = _estado.obter_prato_aceito(prato)
    return avaliar_preco(prato, preco_proposto, prato_aceito.cmv_total, prato_aceito.porcoes)


@mcp.tool()
def confirmar_preco_final(prato: str, preco: float) -> ResultadoAvaliacaoPreco:
    """Grava de vez o preço que a Dona Maria escolheu pra `prato` — chame
    isso só depois que ela confirmar explicitamente qual preço quer usar
    (seja repetindo uma opção A/B/C ou um valor livre), nunca antes disso.
    Recalcula o resultado financeiro do zero internamente (mesmo cálculo
    de `avaliar_preco_final`) e só então persiste — você não informa nem
    recalcula nada. Sem isso, `consultar_cardapio` mostra o prato sem
    preço. Levanta erro se `prato` ainda não tiver sido aceito nesta
    sessão."""
    return _estado.confirmar_preco_final(prato, preco)


@mcp.tool()
def consultar_cardapio() -> Cardapio:
    """Lista todos os pratos já aceitos nesta sessão (nome, porções,
    cmv_por_porcao, preço confirmado — `None` se `confirmar_preco_final`
    ainda não foi chamado pra ele — e a URL da receita original, quando
    informada em `registrar_prato_aceito`). Use isso pra responder
    qualquer pergunta sobre o cardápio de lançamento montado até agora
    ("como ficou meu cardápio?", "quais pratos eu já fechei?") — nunca
    reconstrua essa lista de memória da conversa."""
    return _estado.consultar_cardapio()


if __name__ == "__main__":
    mcp.run()
