"""
services/container.py — Container de dependências (Service Locator simplificado).

Por que um container de dependências?
----------------------------------------
No código original, `SistemaFinanceiro` era um Singleton que criava
todos os objetos internamente. O problema:
1. Impossível trocar implementações para testes
2. Dependências ocultas — você não sabe o que cada classe precisa
3. Um único ponto de falha para todo o sistema

O container expõe as dependências explicitamente.
Routes recebem os services prontos via `get_services()`.
Tests criam seus próprios services com repositórios mockados.

Por que não usar Flask-Injector ou similar?
--------------------------------------------
Para este projeto, a complexidade de um framework DI completo não
compensa. Um container simples atende às necessidades com muito
menos overhead de aprendizado e configuração.
"""

from __future__ import annotations

from database.manager import DatabaseManager
from database.repositories import (
    BuscaRepository,
    CategoriaRepository,
    ContaBancariaRepository,
    MetaRepository,
    RecorrenteRepository,
    SaldoContaRepository,
    LimiteCategoriaRepository,
    TransacaoRepository,
    TransferenciaRepository,
    UsuarioRepository,
)
from services.auth_service import AuthService
from services.dashboard_service import DashboardService
from services.recorrente_service import RecorrenteService
from services.transacao_service import TransacaoService
from utils.calendario import CalendarioUtil


class ServiceContainer:
    """
    Constrói e expõe todos os services da aplicação.

    Instância única criada no startup do Flask e armazenada em app.extensions.
    Routes acessam via `current_app.extensions['services']`.
    """

    def __init__(self, db_path: str = "financas.db") -> None:
        # ── Infraestrutura ────────────────────────────────────────────────────
        self.db = DatabaseManager(db_path)
        self.db.init_schema()

        # ── Repositórios ──────────────────────────────────────────────────────
        self.usuarios_repo = UsuarioRepository(self.db)
        self.categorias_repo = CategoriaRepository(self.db)
        self.transacoes_repo = TransacaoRepository(self.db)
        self.recorrentes_repo = RecorrenteRepository(self.db)
        self.metas_repo = MetaRepository(self.db)
        self.contas_repo = ContaBancariaRepository(self.db)
        self.busca_repo = BuscaRepository(self.db)
        self.saldo_conta_repo = SaldoContaRepository(self.db)
        self.limites_repo = LimiteCategoriaRepository(self.db)
        self.transferencias_repo = TransferenciaRepository(self.db)
        self.metas_repo = MetaRepository(self.db)

        # ── Utilitários ───────────────────────────────────────────────────────
        self.calendario = CalendarioUtil()

        # ── Services (compostos com repositórios e utilitários) ───────────────
        self.auth = AuthService(self.usuarios_repo, self.categorias_repo)

        self.transacoes = TransacaoService(self.transacoes_repo)

        self.recorrentes = RecorrenteService(
            recorrente_repo=self.recorrentes_repo,
            transacao_service=self.transacoes,
            calendario=self.calendario,
        )

        self.dashboard = DashboardService(self.transacoes_repo)

    @classmethod
    def create_for_testing(cls, db_path: str = ":memory:") -> "ServiceContainer":
        """
        Fábrica para testes.

        Usa banco em memória, isolado por instância.
        Não há estado compartilhado entre testes.
        """
        return cls(db_path)