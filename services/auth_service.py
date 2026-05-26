"""
services/auth_service.py — Regras de negócio de autenticação.

O que é um Service?
---------------------
Services orquestram operações de negócio que envolvem múltiplos
repositórios ou regras que não pertencem a uma entidade só.

AuthService é responsável por:
- Validar dados de entrada (delegando a validators)
- Criar usuário com hash seguro de senha
- Autenticar usuário (verificar credenciais)
- NÃO gerencia sessões Flask — isso é responsabilidade das routes

Por que hashing aqui e não no repositório?
-------------------------------------------
Hashing de senha é regra de SEGURANÇA, não de persistência.
O repositório só salva dados. O service decide COMO salvar.
"""

import logging

from werkzeug.security import check_password_hash, generate_password_hash

from database.repositories import CategoriaRepository, UsuarioRepository
from utils.validators import (
    coletar_erros,
    validar_email,
    validar_nome,
    validar_senha,
)

logger = logging.getLogger(__name__)


def _anonimizar_email_log(email: str) -> str:
    """
    Retorna email parcialmente anonimizado para logs.
    Ex: gabrielmarques4167@gmail.com → g***@gmail.com

    Protege privacidade nos logs sem perder utilidade de debug.
    """
    try:
        local, dominio = email.split("@", 1)
        return f"{local[0]}***@{dominio}"
    except Exception:
        return "***@***"


class AuthService:
    """
    Serviço de autenticação e registro de usuários.

    Recebe repositórios via injeção de dependência.
    Isso permite substituir repositórios por mocks nos testes.
    """

    def __init__(
        self,
        usuario_repo: UsuarioRepository,
        categoria_repo: CategoriaRepository,
    ) -> None:
        self._usuarios = usuario_repo
        self._categorias = categoria_repo

    def registrar(
        self, email: str, senha: str, nome: str
    ) -> tuple[int | None, dict[str, str]]:
        """
        Registra novo usuário.

        Retorna: (user_id, erros)
        - Se sucesso: (id, {})
        - Se falha de validação: (None, {'campo': 'erro'})
        - Se email duplicado: (None, {'email': 'Email já cadastrado'})

        Por que retornar (id, erros) em vez de levantar exceção?
        ----------------------------------------------------------
        Erros de validação são fluxo esperado, não exceções.
        O route controller decide como apresentar erros ao usuário.
        Exceções devem ser reservadas para falhas inesperadas do sistema.
        """
        erros = coletar_erros(
            email=validar_email(email),
            senha=validar_senha(senha),
            nome=validar_nome(nome),
        )
        if erros:
            return None, erros

        senha_hash = generate_password_hash(senha)
        user_id = self._usuarios.criar(email, senha_hash, nome)

        if user_id is None:
            return None, {"email": "Este email já está cadastrado"}

        # Cria categorias padrão para o novo usuário
        try:
            self._categorias.criar_categorias_padrao(user_id)
        except Exception as exc:
            # Falha ao criar categorias não deve reverter o cadastro
            logger.error("Erro ao criar categorias padrão para user %d: %s", user_id, exc)

        logger.info("Novo usuário registrado: id=%d email=%s", user_id, _anonimizar_email_log(email))
        return user_id, {}

    def autenticar(
        self, email: str, senha: str
    ) -> tuple[dict | None, str | None]:
        """
        Autentica usuário por email e senha.

        Retorna: (dados_usuario, erro)
        - Se sucesso: ({'id':..., 'email':..., 'nome':...}, None)
        - Se falha: (None, 'mensagem de erro')

        Por que sempre a mesma mensagem de erro para email/senha inválidos?
        ----------------------------------------------------------------------
        "Email não encontrado" vs "Senha incorreta" revela quais emails
        existem no sistema (enumeração de usuários). A mensagem genérica
        "Credenciais inválidas" é mais segura.
        """
        if not email or not senha:
            return None, "Credenciais inválidas"

        usuario = self._usuarios.buscar_por_email(email)
        if usuario is None:
            logger.warning("Tentativa de login com email não cadastrado: %s", _anonimizar_email_log(email))
            return None, "Credenciais inválidas"

        if not check_password_hash(usuario["senha_hash"], senha):
            logger.warning("Senha incorreta para usuário: %s", _anonimizar_email_log(email))
            return None, "Credenciais inválidas"

        logger.info("Login bem-sucedido: user_id=%d", usuario["id"])
        return {
            "id": usuario["id"],
            "email": usuario["email"],
            "nome": usuario["nome"],
        }, None