"""
routes/helpers.py — Funções auxiliares para os blueprints.

Por que separar helpers das routes?
--------------------------------------
Funções como `get_services()` e `make_user_principal()` seriam
duplicadas em cada blueprint. Centralizar evita duplicação e
facilita futuras mudanças (ex: trocar o mecanismo de DI).
"""

from flask import current_app
from flask_login import UserMixin

from services.container import ServiceContainer


def get_services() -> ServiceContainer:
    """
    Retorna o container de services do app atual.

    Por que via current_app.extensions?
    ---------------------------------------
    Flask armazena extensões por app instance. Isso permite múltiplos
    apps Flask no mesmo processo (útil em testes) sem estado global.
    """
    return current_app.extensions["services"]


class UserPrincipal(UserMixin):
    """
    Representação do usuário autenticado para Flask-Login.

    Por que não usar o dict do banco diretamente?
    -----------------------------------------------
    Flask-Login exige um objeto com o método `get_id()` e o atributo
    `is_authenticated`. UserMixin fornece implementação padrão.
    Usar um objeto tipado (vs dict) previne KeyError em templates.
    """

    def __init__(self, id: int, email: str, nome: str, modo_contabil: int = 0) -> None:
        self.id = id
        self.email = email
        self.nome = nome
        self.modo_contabil = modo_contabil  # 1 = ativo, 0 = inativo

    def __repr__(self) -> str:
        return f"<UserPrincipal id={self.id} email={self.email}>"


def make_user_principal(dados: dict) -> UserPrincipal:
    """Constrói UserPrincipal a partir do dict retornado pelo AuthService."""
    return UserPrincipal(
        id=dados["id"],
        email=dados["email"],
        nome=dados["nome"],
        modo_contabil=dados.get("modo_contabil", 0),
    )