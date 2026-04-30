"""
tests/conftest.py — Configuração e fixtures compartilhadas do pytest.

Por que conftest.py?
----------------------
O pytest descobre automaticamente este arquivo e disponibiliza suas
fixtures para todos os testes no diretório. Não precisa de import.

Estratégia de isolamento:
--------------------------
Cada teste recebe um banco NOVO em memória (SQLite :memory:).
Isso garante que:
1. Testes não interferem entre si
2. Ordem de execução não importa
3. Dados de um teste não "vazam" para outro

Por que não usar mocks/stubs para o banco?
--------------------------------------------
Mocks de banco testam apenas que você chamou os métodos corretos,
não que a integração funciona de verdade. Banco em memória é rápido
(< 1ms para criar) e testa o comportamento real.

Fixtures de escopo:
- function (padrão): nova instância para cada test — máximo isolamento
- module: compartilhada no módulo — use para dados read-only
- session: compartilhada em toda a execução — evite para dados mutáveis
"""

import pytest

from config import TestingConfig
from services.container import ServiceContainer


@pytest.fixture
def container() -> ServiceContainer:
    """
    Container de services com banco em memória.
    Recriado para cada teste — isolamento garantido.
    """
    return ServiceContainer.create_for_testing(db_path=":memory:")


@pytest.fixture
def app(container):
    """
    Flask app para testes de integração de routes.
    Usa o mesmo container com banco em memória.
    """
    from app import create_app
    flask_app = create_app(config_class=TestingConfig, db_path=":memory:")
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


@pytest.fixture
def client(app):
    """Cliente de teste HTTP do Flask."""
    return app.test_client()


@pytest.fixture
def usuario_criado(container) -> dict:
    """Fixture que cria e retorna um usuário de teste."""
    user_id, erros = container.auth.registrar(
        email="teste@exemplo.com",
        senha="senha123",
        nome="Usuário Teste",
    )
    assert not erros, f"Erro ao criar usuário de teste: {erros}"
    return {
        "id": user_id,
        "email": "teste@exemplo.com",
        "senha": "senha123",
        "nome": "Usuário Teste",
    }


@pytest.fixture
def usuario_logado(client, container):
    """
    Fixture que cria usuário e faz login no cliente de teste.
    Retorna o dict do usuário criado.
    """
    # Cria usuário diretamente pelo service (sem passar pelo HTTP)
    user_id, _ = container.auth.registrar(
        email="logado@exemplo.com", senha="senha123", nome="Logado"
    )
    # Faz login via HTTP para popular a sessão Flask
    client.post("/auth/login", data={"email": "logado@exemplo.com", "senha": "senha123"})
    return {"id": user_id, "email": "logado@exemplo.com"}


@pytest.fixture
def categoria_despesa(container, usuario_criado) -> dict:
    """Retorna a primeira categoria de despesa do usuário de teste."""
    cats = container.categorias_repo.listar_por_usuario(usuario_criado["id"])
    despesas = [c for c in cats if c["tipo"] == "despesa"]
    assert despesas, "Nenhuma categoria de despesa encontrada"
    return despesas[0]


@pytest.fixture
def categoria_receita(container, usuario_criado) -> dict:
    """Retorna a primeira categoria de receita do usuário de teste."""
    cats = container.categorias_repo.listar_por_usuario(usuario_criado["id"])
    receitas = [c for c in cats if c["tipo"] == "receita"]
    assert receitas, "Nenhuma categoria de receita encontrada"
    return receitas[0]