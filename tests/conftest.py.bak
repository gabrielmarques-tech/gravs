"""
tests/conftest.py — Fixtures compartilhadas do pytest.

Estratégia de isolamento:
  Cada teste recebe um banco SQLite em arquivo temporário (não :memory:)
  porque Flask test_client e ServiceContainer precisam compartilhar o mesmo banco.
  O arquivo é apagado após cada teste.
"""

import os
import tempfile
import pytest

from config import TestingConfig
from services.container import ServiceContainer


@pytest.fixture
def db_file():
    """Cria um arquivo temporário de banco e o apaga após o teste."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def container(db_file):
    """
    ServiceContainer com banco em arquivo temporário.
    Compartilhado com o app Flask para que client e container usem o mesmo banco.
    """
    return ServiceContainer(db_path=db_file)


@pytest.fixture
def app(db_file):
    """Flask app apontando para o mesmo arquivo de banco do container."""
    from app import create_app
    flask_app = create_app(config_class=TestingConfig, db_path=db_file)
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def usuario_criado(container):
    """Cria e retorna um usuário de teste."""
    user_id, erros = container.auth.registrar(
        email="teste@exemplo.com", senha="senha123", nome="Usuário Teste"
    )
    assert not erros, f"Erro ao criar usuário: {erros}"
    return {"id": user_id, "email": "teste@exemplo.com", "senha": "senha123", "nome": "Usuário Teste"}


@pytest.fixture
def usuario_logado(client, container):
    """Cria usuário e faz login no client HTTP."""
    user_id, _ = container.auth.registrar(
        email="logado@exemplo.com", senha="senha123", nome="Logado"
    )
    client.post("/auth/login", data={"email": "logado@exemplo.com", "senha": "senha123"})
    return {"id": user_id, "email": "logado@exemplo.com"}


@pytest.fixture
def categoria_despesa(container, usuario_criado):
    cats = container.categorias_repo.listar_por_usuario(usuario_criado["id"])
    return next(c for c in cats if c["tipo"] == "despesa")


@pytest.fixture
def categoria_receita(container, usuario_criado):
    cats = container.categorias_repo.listar_por_usuario(usuario_criado["id"])
    return next(c for c in cats if c["tipo"] == "receita")
