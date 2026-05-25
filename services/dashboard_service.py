"""
services/dashboard_service.py — Dados para o dashboard.

Por que um service separado para o dashboard?
----------------------------------------------
O dashboard agrega dados de múltiplos repositórios (transações,
metas, notificações). Colocar essa lógica no route controller
viola o SRP. Um DashboardService:
1. Mantém as routes simples (apenas HTTP handling)
2. Permite testar a lógica de insights sem subir o Flask
3. Facilita cache futuro (basta cachear o resultado do service)
"""

import logging
from dataclasses import dataclass, field

from database.repositories import TransacaoRepository

logger = logging.getLogger(__name__)


@dataclass
class ResumoMes:
    """
    Dados estruturados do dashboard mensal.

    Por que dataclass e não dict?
    --------------------------------
    1. Atributos com nome explícito — sem erro de typo em chave de dict
    2. Type hints reais — IDEs e mypy verificam tipos
    3. Imutável por design — não é modificado após criação
    4. Documentação implícita — a estrutura é autodocumentada
    """
    receitas: float
    despesas: float
    saldo: float
    receitas_anterior: float
    despesas_anterior: float
    diferenca_despesas: float
    gastos_por_categoria: list[dict] = field(default_factory=list)
    evolucao_diaria: list[dict] = field(default_factory=list)

    @property
    def insight(self) -> dict:
        """Gera insight textual baseado na comparação com mês anterior."""
        d = self.diferenca_despesas
        if d > 50:
            return {
                "cor": "#ef4444",
                "titulo": "⚠️ Atenção",
                "mensagem": (
                    f"Você gastou mais esse mês em comparação ao anterior"
                ),
                "valor": d,
            }
        elif d < -50:
            return {
                "cor": "#22c55e",
                "titulo": "💰 Boa!",
                "mensagem": "Você economizou mais esse mês",
                "valor": abs(d),
            }
        return {
            "cor": "#22d3ee",
            "titulo": "📊 Estável",
            "mensagem": "Gastos parecidos com o mês passado",
            "valor": 0,
        }


class DashboardService:
    """Agrega dados de múltiplas fontes para o dashboard."""

    def __init__(self, transacao_repo: TransacaoRepository) -> None:
        self._transacoes = transacao_repo

    def obter_resumo(self, ano: int, mes: int, usuario_id: int) -> ResumoMes:
        """
        Calcula todos os dados necessários para o dashboard.

        Por que calcular mês anterior aqui?
        -------------------------------------
        O insight de comparação é lógica de negócio, não apresentação.
        O route controller não deveria calcular "mês anterior" — ele
        apenas exibe o que o service produz.
        """
        receitas, despesas, saldo = self._transacoes.resumo_mes(ano, mes, usuario_id)

        mes_ant = mes - 1 if mes > 1 else 12
        ano_ant = ano if mes > 1 else ano - 1
        rec_ant, desp_ant, _ = self._transacoes.resumo_mes(ano_ant, mes_ant, usuario_id)

        gastos_cat = self._transacoes.gastos_por_categoria(ano, mes, usuario_id)
        evolucao = self._transacoes.evolucao_saldo_mes(ano, mes, usuario_id)

        return ResumoMes(
            receitas=receitas,
            despesas=despesas,
            saldo=saldo,
            receitas_anterior=rec_ant,
            despesas_anterior=desp_ant,
            diferenca_despesas=despesas - desp_ant,
            gastos_por_categoria=gastos_cat,
            evolucao_diaria=evolucao,
        )