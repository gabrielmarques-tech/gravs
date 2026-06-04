"""
utils/metrics.py — Sistema de Observabilidade e Métricas.

Módulo que instrumenta toda a aplicação com:
- Tempo de execução de funções críticas
- Contagem e tempo de consultas ao banco
- Tracking de chamadas por operação

Uso como decorator:
    @metricas.medir('saldo_conta')
    def minha_funcao(...):

Uso como context manager:
    with metricas.tempo_consulta('buscar_lancamentos'):
        lancamentos = repo.listar(...)

Relatório:
    metricas.relatorio() -> str formatada com todas as métricas acumuladas

Filosofia:
    Sem métricas você nunca sabe onde está o gargalo.
    Se não medirmos, estamos apenas supondo.
"""

import time
import logging
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Metricas:
    """
    Coletor central de métricas da aplicação.

    Padrão Singleton — todas as chamadas convergem para a mesma instância.
    Thread-safe para leitura (dicionário padrão Python ok para Flask single-thread).
    """

    _instancia: 'Metricas | None' = None

    def __new__(cls) -> 'Metricas':
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializar()
        return cls._instancia

    def _inicializar(self) -> None:
        """Inicializa contadores e acumuladores."""
        # Tempo total de execução por operação (segundos)
        self._tempos: dict[str, float] = defaultdict(float)

        # Quantidade de chamadas por operação
        self._contagens: dict[str, int] = defaultdict(int)

        # Número de consultas ao banco por operação
        self._consultas_bd: dict[str, int] = defaultdict(int)

        # Tempo total gasto em consultas ao banco (segundos)
        self._tempo_consultas_bd: dict[str, float] = defaultdict(float)

        # Cache de última execução por operação
        self._ultimos_tempos: dict[str, float] = {}

        # Flag para habilitar/desabilitar métricas em tempo real
        self._ativo: bool = True

    # ── Decorator para medir funções ─────────────────────────────────────────

    def medir(self, nome_operacao: str | None = None) -> Callable:
        """
        Decorator que mede tempo de execução e conta chamadas.

        Uso:
            @metricas.medir('saldo_conta')
            def minha_funcao(...):

        Se nome_operacao for None, usa o nome da função.

        Args:
            nome_operacao: Nome amigável para a métrica.
                           Se None, usa function.__name__.

        Returns:
            Decorator que registra métricas automaticamente.
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if not self._ativo:
                    return func(*args, **kwargs)

                nome = nome_operacao or func.__name__
                inicio = time.perf_counter()

                try:
                    resultado = func(*args, **kwargs)
                    return resultado
                finally:
                    duracao = time.perf_counter() - inicio
                    self._tempos[nome] += duracao
                    self._contagens[nome] += 1
                    self._ultimos_tempos[nome] = duracao

                    # Log detalhado se for lento (>100ms)
                    if duracao > 0.1:
                        logger.debug(
                            "⏱️ [MÉTRICA] %s levou %.1f ms (chamada #%d)",
                            nome, duracao * 1000, self._contagens[nome],
                        )

            return wrapper
        return decorator

    # ── Context manager para consultas ao banco ──────────────────────────────

    @contextmanager
    def tempo_consulta(self, nome_operacao: str):
        """
        Context manager que mede o tempo de uma consulta ao banco.

        Uso:
            with metricas.tempo_consulta('buscar_lancamentos'):
                rows = conn.execute(...)

        Args:
            nome_operacao: Nome da operação associada à consulta.

        Yields:
            O contexto gerenciado.
        """
        if not self._ativo:
            yield
            return

        inicio = time.perf_counter()
        try:
            yield
        finally:
            duracao = time.perf_counter() - inicio
            self._consultas_bd[nome_operacao] += 1
            self._tempo_consultas_bd[nome_operacao] += duracao

    # ── Métodos auxiliares ──────────────────────────────────────────────────

    def registrar_chamada(self, nome_operacao: str, tempo_gasto: float) -> None:
        """
        Registra manualmente uma chamada e seu tempo.

        Útil para casos onde o decorator não pode ser aplicado
        (ex: funções em callbacks ou lambdas).

        Args:
            nome_operacao: Nome da operação.
            tempo_gasto: Tempo gasto em segundos.
        """
        if not self._ativo:
            return
        self._tempos[nome_operacao] += tempo_gasto
        self._contagens[nome_operacao] += 1
        self._ultimos_tempos[nome_operacao] = tempo_gasto

    def registrar_consulta(self, nome_operacao: str, tempo_gasto: float) -> None:
        """
        Registra manualmente uma consulta ao banco.

        Args:
            nome_operacao: Nome da operação associada.
            tempo_gasto: Tempo gasto em segundos.
        """
        if not self._ativo:
            return
        self._consultas_bd[nome_operacao] += 1
        self._tempo_consultas_bd[nome_operacao] += tempo_gasto

    def zerar(self) -> None:
        """Reseta todas as métricas acumuladas."""
        self._tempos.clear()
        self._contagens.clear()
        self._consultas_bd.clear()
        self._tempo_consultas_bd.clear()
        self._ultimos_tempos.clear()

    def ativar(self, ativo: bool = True) -> None:
        """Habilita ou desabilita a coleta de métricas em runtime."""
        self._ativo = ativo

    # ── Relatório formatado ─────────────────────────────────────────────────

    def relatorio(self) -> str:
        """
        Gera relatório formatado com todas as métricas acumuladas.

        Returns:
            String formatada para log ou console.
        """
        if not self._contagens:
            return "📊 Nenhuma métrica coletada ainda."

        linhas = [
            "=" * 80,
            "  📊 RELATÓRIO DE MÉTRICAS — GRAVS",
            "=" * 80,
            f"{'Operação':<40} {'Chamadas':<12} {'Tempo Total':<14} {'Tempo Médio':<14} {'Tempo BD':<14} {'Consultas BD':<14}",
            "-" * 108,
        ]

        for nome in sorted(self._contagens.keys()):
            chamadas = self._contagens[nome]
            tempo_total = self._tempos[nome]
            tempo_medio = tempo_total / chamadas if chamadas > 0 else 0
            consultas_bd = self._consultas_bd.get(nome, 0)
            tempo_bd = self._tempo_consultas_bd.get(nome, 0)

            linha = (
                f"{nome:<40} "
                f"{chamadas:<12} "
                f"{tempo_total*1000:<11.2f}ms  "
                f"{tempo_medio*1000:<11.2f}ms  "
                f"{tempo_bd*1000:<11.2f}ms  "
                f"{consultas_bd:<12}"
            )
            linhas.append(linha)

        # Totais
        total_chamadas = sum(self._contagens.values())
        total_tempo = sum(self._tempos.values())
        total_consultas_bd = sum(self._consultas_bd.values())
        total_tempo_bd = sum(self._tempo_consultas_bd.values())

        linhas.extend([
            "-" * 108,
            f"{'TOTAIS':<40} "
            f"{total_chamadas:<12} "
            f"{total_tempo*1000:<11.2f}ms  "
            f"{'':<14} "
            f"{total_tempo_bd*1000:<11.2f}ms  "
            f"{total_consultas_bd:<12}",
            "=" * 80,
        ])

        return "\n".join(linhas)

    def ultimo_tempo(self, nome_operacao: str) -> float | None:
        """
        Retorna o tempo da última execução de uma operação.

        Args:
            nome_operacao: Nome da operação.

        Returns:
            Tempo em segundos ou None se nunca executada.
        """
        return self._ultimos_tempos.get(nome_operacao)

    def contagem(self, nome_operacao: str) -> int:
        """
        Retorna o número de chamadas de uma operação.

        Args:
            nome_operacao: Nome da operação.

        Returns:
            Número de chamadas.
        """
        return self._contagens.get(nome_operacao, 0)

    def media_tempo(self, nome_operacao: str) -> float | None:
        """
        Retorna o tempo médio de execução de uma operação.

        Args:
            nome_operacao: Nome da operação.

        Returns:
            Tempo médio em segundos ou None se nunca executada.
        """
        chamadas = self._contagens.get(nome_operacao, 0)
        if chamadas == 0:
            return None
        return self._tempos[nome_operacao] / chamadas


# ── Instância global ──────────────────────────────────────────────────────────
metricas = Metricas()


# ── Decorator de compatibilidade (uso: @medir) ────────────────────────────────
def medir(nome_operacao: str | None = None) -> Callable:
    """Alias para métricas.medir()."""
    return metricas.medir(nome_operacao)


def tempo_consulta(nome_operacao: str):
    """Alias para métricas.tempo_consulta()."""
    return metricas.tempo_consulta(nome_operacao)