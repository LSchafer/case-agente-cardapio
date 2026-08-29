"""Tipos compartilhados entre as camadas do servidor MCP.

Nenhuma lógica aqui — só estrutura de dados, pra evitar dict solto
circulando entre planilha/estado/precificacao/server.
"""

from dataclasses import dataclass, field


@dataclass
class ItemDespensa:
    nome: str
    quantidade_disponivel: float
    unidade_base: str  # "g" | "ml" | "un"
    custo_unitario: float  # R$ por unidade-base


@dataclass
class IngredienteReceita:
    """Um ingrediente de receita, como o agente envia pra verificar_viabilidade."""

    nome_original: str
    quantidade: float
    unidade: str  # unidade como veio da receita (kg, xícara, colher de sopa, un, ...)
    nome_despensa: str | None = None  # None = agente não achou correspondência na despensa
    preco_estimado_por_unidade: float | None = None  # obrigatório quando nome_despensa é None


@dataclass
class ItemFaltante:
    nome: str
    quantidade_faltante: float
    unidade_base: str
    custo: float
    origem: str  # "despensa_insuficiente" | "nao_encontrado_na_despensa"


@dataclass
class ResultadoViabilidade:
    prato: str
    itens_ok: list[str]
    itens_faltantes: list[ItemFaltante]
    custo_complementar_total: float
    orcamento_suficiente: bool
    orcamento_restante_apos: float
    itens_nao_calculaveis: list[str] = field(default_factory=list)
    utensilios_faltantes: list[str] = field(default_factory=list)
    tecnicas_faltantes: list[str] = field(default_factory=list)
    restricao_operacional_pendente: bool = False
    pronto_para_aceitar: bool = False
    cmv_total: float = 0.0
    # None quando `porcoes` não foi informado ainda (verificar_viabilidade
    # permite simular sem isso) — registrar_prato_aceito EXIGE porcoes.
    porcoes: int | None = None
    cmv_por_porcao: float | None = None


@dataclass
class ItemConsumido:
    nome_despensa: str
    quantidade_usada: float
    unidade_base: str


@dataclass
class PratoAceito:
    prato: str
    custo_complementar: float
    cmv_total: float
    porcoes: int
    cmv_por_porcao: float
    itens_consumidos: list[ItemConsumido] = field(default_factory=list)
    # URL da receita original (o agente já busca/cita isso na Fase 2) —
    # guardado só como referência re-buscável via web_extract, nunca como
    # fonte de "verdade" sobre o preparo em si.
    fonte_url: str | None = None
    # None até `confirmar_preco_final` ser chamado -- diferente de
    # `avaliar_preco_final`, que só simula e nunca grava aqui.
    preco_confirmado: float | None = None


@dataclass
class ConversaoResultado:
    sucesso: bool
    quantidade_base: float | None = None
    unidade_base: str | None = None
    motivo: str | None = None


@dataclass
class CenarioPreco:
    lucro_alvo_pct: float
    preco: float
    lucro_dona_maria: float
    cmv_pct_do_preco: float
    taxa_plataforma: float


@dataclass
class ResultadoPrecificacao:
    """`preco_minimo`/`cenarios` são sempre POR PORÇÃO — a Dona Maria vende
    porção a porção, não o lote inteiro da receita. `cmv_total`
    continua sendo o custo do lote inteiro, só pra referência/transparência
    na mensagem; `cmv_por_porcao` (= cmv_total / porcoes) é o que
    efetivamente entra no cálculo de `preco_minimo` e de cada `CenarioPreco`."""

    prato: str
    cmv_total: float
    porcoes: int
    cmv_por_porcao: float
    preco_minimo: float
    cenarios: list[CenarioPreco]


@dataclass
class ResultadoAvaliacaoPreco:
    """Resultado de avaliar um preço específico que a Dona Maria propôs —
    seja repetindo uma das opções A/B/C, seja um valor livre dela. Nunca
    calculado pelo agente. `preco_proposto` é por porção;
    `resultado_financeiro` é o lucro (ou prejuízo, se negativo) POR
    PORÇÃO vendida nesse preço, não do lote inteiro."""

    prato: str
    preco_proposto: float
    cmv_total: float
    porcoes: int
    cmv_por_porcao: float
    preco_minimo: float
    taxa_plataforma: float
    receita_liquida: float
    resultado_financeiro: float  # positivo = lucro, negativo = prejuízo (por porção)
    abaixo_do_minimo: bool


@dataclass
class ItemDespensaResumo:
    nome: str
    quantidade_disponivel: float
    unidade_base: str
    custo_unitario: float


@dataclass
class DespensaAtual:
    despensa: list[ItemDespensaResumo]
    orcamento_restante: float


@dataclass
class ItemCardapio:
    nome: str
    porcoes: int
    cmv_por_porcao: float
    preco_confirmado: float | None
    fonte_url: str | None


@dataclass
class Cardapio:
    pratos: list[ItemCardapio]


@dataclass
class PerfilOperacional:
    """Utensílios/técnicas/restrições que a Dona Maria já confirmou ter/saber
    nesta sessão. Cumulativo entre pratos.
    """

    utensilios_confirmados: list[str] = field(default_factory=list)
    tecnicas_confirmadas: list[str] = field(default_factory=list)
    restricoes_operacionais: list[str] = field(default_factory=list)
    # True só quando o agente sinaliza que ela deu uma resposta explícita à
    # pergunta sobre restrições operacionais — mesmo que a resposta seja
    # "nenhuma". Distinto de restricoes_operacionais estar vazia: lista
    # vazia por si só é ambígua (pode ser "ela não tem restrição" OU
    # "ninguém perguntou ainda"/"a resposta dela não cobriu isso").
    restricoes_perguntadas: bool = False
