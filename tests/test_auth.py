"""
tests/test_auth.py — Testes do AuthService e rotas de autenticação.
"""

import pytest

from services.auth_service import AuthService


class TestRegistro:

    def test_registro_bem_sucedido(self, container):
        user_id, erros = container.auth.registrar(
            email="novo@teste.com", senha="senha123", nome="Novo Usuário"
        )
        assert user_id is not None
        assert user_id > 0
        assert erros == {}

    def test_registro_cria_categorias_padrao(self, container):
        user_id, _ = container.auth.registrar(
            email="cats@teste.com", senha="senha123", nome="Categorias"
        )
        cats = container.categorias_repo.listar_por_usuario(user_id)
        assert len(cats) > 0
        tipos = {c["tipo"] for c in cats}
        assert "receita" in tipos
        assert "despesa" in tipos

    def test_registro_email_duplicado(self, container):
        container.auth.registrar("dup@teste.com", "senha123", "Primeiro")
        user_id, erros = container.auth.registrar("dup@teste.com", "senha456", "Segundo")
        assert user_id is None
        assert "email" in erros
        assert "cadastrado" in erros["email"].lower()

    def test_registro_email_case_insensitive(self, container):
        container.auth.registrar("Case@Teste.COM", "senha123", "Case")
        user_id, erros = container.auth.registrar("case@teste.com", "outraSenha", "Case2")
        assert user_id is None

    def test_registro_senha_curta_falha(self, container):
        user_id, erros = container.auth.registrar("curta@teste.com", "123", "Curta")
        assert user_id is None
        assert "senha" in erros

    def test_registro_email_invalido_falha(self, container):
        user_id, erros = container.auth.registrar("emailsemarroba", "senha123", "Inválido")
        assert user_id is None
        assert "email" in erros

    def test_registro_nome_vazio_falha(self, container):
        user_id, erros = container.auth.registrar("nome@teste.com", "senha123", "  ")
        assert user_id is None
        assert "nome" in erros


class TestAutenticacao:

    def test_autenticacao_bem_sucedida(self, container, usuario_criado):
        usuario, erro = container.auth.autenticar(
            usuario_criado["email"], usuario_criado["senha"]
        )
        assert erro is None
        assert usuario is not None
        assert usuario["id"] == usuario_criado["id"]
        assert "senha_hash" not in usuario

    def test_autenticacao_senha_errada(self, container, usuario_criado):
        usuario, erro = container.auth.autenticar(
            usuario_criado["email"], "senhaERRADA"
        )
        assert usuario is None
        assert erro is not None
        assert "inválid" in erro.lower() or "invalid" in erro.lower()

    def test_autenticacao_email_inexistente(self, container):
        usuario, erro = container.auth.autenticar("naoexiste@teste.com", "qualquer")
        assert usuario is None
        assert erro is not None

    def test_mensagem_erro_generica(self, container, usuario_criado):
        _, erro_email = container.auth.autenticar("naoexiste@teste.com", "senha123")
        _, erro_senha = container.auth.autenticar(usuario_criado["email"], "errada")
        assert erro_email == erro_senha

    def test_autenticacao_email_case_insensitive(self, container, usuario_criado):
        email_maiusculo = usuario_criado["email"].upper()
        usuario, erro = container.auth.autenticar(email_maiusculo, usuario_criado["senha"])
        assert usuario is not None

    def test_hash_senha_nao_exposto(self, container, usuario_criado):
        usuario, _ = container.auth.autenticar(
            usuario_criado["email"], usuario_criado["senha"]
        )
        assert "senha_hash" not in usuario
        assert "senha" not in usuario


class TestRotasAuth:

    def test_get_login_retorna_200(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_get_cadastro_retorna_200(self, client):
        resp = client.get("/auth/cadastro")
        assert resp.status_code == 200

    def test_post_cadastro_valido_redireciona(self, client):
        resp = client.post("/auth/cadastro", data={
            "email": "rota@teste.com",
            "senha": "senha123",
            "nome": "Rota Teste",
            "aceite_termos": "1",
        })
        assert resp.status_code in (302, 200)

    def test_post_login_valido_redireciona_dashboard(self, client, container):
        container.auth.registrar("login@route.com", "senha123", "Login Route")
        resp = client.post("/auth/login", data={
            "email": "login@route.com",
            "senha": "senha123",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "/" in resp.headers.get("Location", "")

    def test_post_login_invalido_retorna_401(self, client):
        resp = client.post("/auth/login", data={
            "email": "naoexiste@route.com",
            "senha": "qualquer",
        })
        assert resp.status_code == 401

    def test_logout_redireciona_para_login(self, client, usuario_logado):
        resp = client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302