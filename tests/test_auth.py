"""
tests/test_auth.py — Testes do AuthService e rotas de autenticação.

Estrutura de cada teste:
- Arrange: prepara dados de entrada
- Act: executa a operação
- Assert: verifica o resultado esperado

Por que testes de unidade E de integração?
--------------------------------------------
- Testes de service (unidade): testam regras de negócio sem Flask
- Testes de route (integração): testam que o HTTP funciona corretamente
  e que service + route estão conectados

Se um teste de service passa mas o de route falha, o problema está
no blueprint. Isso facilita muito o diagnóstico.
"""

import pytest

from services.auth_service import AuthService


# ── Testes de unidade: AuthService ────────────────────────────────────────────

class TestRegistro:
    """Testes do fluxo de cadastro de usuários."""

    def test_registro_bem_sucedido(self, container):
        """Registro com dados válidos retorna ID positivo e sem erros."""
        user_id, erros = container.auth.registrar(
            email="novo@teste.com", senha="senha123", nome="Novo Usuário"
        )
        assert user_id is not None
        assert user_id > 0
        assert erros == {}

    def test_registro_cria_categorias_padrao(self, container):
        """Após registro, usuário deve ter categorias padrão."""
        user_id, _ = container.auth.registrar(
            email="cats@teste.com", senha="senha123", nome="Categorias"
        )
        cats = container.categorias_repo.listar_por_usuario(user_id)
        assert len(cats) > 0, "Nenhuma categoria criada para o novo usuário"
        tipos = {c["tipo"] for c in cats}
        assert "receita" in tipos, "Nenhuma categoria de receita criada"
        assert "despesa" in tipos, "Nenhuma categoria de despesa criada"

    def test_registro_email_duplicado(self, container):
        """Registrar o mesmo email duas vezes deve falhar."""
        container.auth.registrar("dup@teste.com", "senha123", "Primeiro")
        user_id, erros = container.auth.registrar("dup@teste.com", "senha456", "Segundo")

        assert user_id is None
        assert "email" in erros
        assert "cadastrado" in erros["email"].lower()

    def test_registro_email_case_insensitive(self, container):
        """Email deve ser tratado como case-insensitive."""
        container.auth.registrar("Case@Teste.COM", "senha123", "Case")
        user_id, erros = container.auth.registrar("case@teste.com", "outraSenha", "Case2")

        assert user_id is None, "Email duplicado (case diferente) não foi detectado"

    def test_registro_senha_curta_falha(self, container):
        """Senha menor que 6 caracteres deve ser rejeitada."""
        user_id, erros = container.auth.registrar("curta@teste.com", "123", "Curta")

        assert user_id is None
        assert "senha" in erros

    def test_registro_email_invalido_falha(self, container):
        """Email sem @ deve ser rejeitado."""
        user_id, erros = container.auth.registrar("emailsemarroba", "senha123", "Inválido")

        assert user_id is None
        assert "email" in erros

    def test_registro_nome_vazio_falha(self, container):
        """Nome vazio deve ser rejeitado."""
        user_id, erros = container.auth.registrar("nome@teste.com", "senha123", "  ")

        assert user_id is None
        assert "nome" in erros


class TestAutenticacao:
    """Testes do fluxo de login."""

    def test_autenticacao_bem_sucedida(self, container, usuario_criado):
        """Login com credenciais corretas retorna dados do usuário."""
        usuario, erro = container.auth.autenticar(
            usuario_criado["email"], usuario_criado["senha"]
        )
        assert erro is None
        assert usuario is not None
        assert usuario["id"] == usuario_criado["id"]
        assert usuario["email"] == usuario_criado["email"]
        assert "senha_hash" not in usuario, "Hash de senha não deve ser exposto"

    def test_autenticacao_senha_errada(self, container, usuario_criado):
        """Login com senha errada deve falhar."""
        usuario, erro = container.auth.autenticar(
            usuario_criado["email"], "senhaERRADA"
        )
        assert usuario is None
        assert erro is not None
        # Mensagem genérica — não revela qual campo está errado
        assert "inválid" in erro.lower() or "invalid" in erro.lower()

    def test_autenticacao_email_inexistente(self, container):
        """Login com email não cadastrado deve falhar."""
        usuario, erro = container.auth.autenticar("naoexiste@teste.com", "qualquer")

        assert usuario is None
        assert erro is not None

    def test_mensagem_erro_generica(self, container, usuario_criado):
        """
        Mensagem de erro deve ser IDÊNTICA para email errado e senha errada.
        Isso previne enumeração de usuários (security best practice).
        """
        _, erro_email = container.auth.autenticar("naoexiste@teste.com", "senha123")
        _, erro_senha = container.auth.autenticar(usuario_criado["email"], "errada")

        assert erro_email == erro_senha, (
            f"Mensagens diferentes revelam qual campo está errado!\n"
            f"  Email inexistente: '{erro_email}'\n"
            f"  Senha errada: '{erro_senha}'"
        )

    def test_autenticacao_email_case_insensitive(self, container, usuario_criado):
        """Email no login deve ser case-insensitive."""
        email_maiusculo = usuario_criado["email"].upper()
        usuario, erro = container.auth.autenticar(email_maiusculo, usuario_criado["senha"])

        assert usuario is not None, f"Login falhou com email em maiúsculo: {erro}"

    def test_hash_senha_nao_exposto(self, container, usuario_criado):
        """O hash da senha não deve aparecer nos dados retornados pelo login."""
        usuario, _ = container.auth.autenticar(
            usuario_criado["email"], usuario_criado["senha"]
        )
        assert "senha_hash" not in usuario
        assert "senha" not in usuario


# ── Testes de integração: Rotas HTTP ──────────────────────────────────────────

class TestRotasAuth:
    """Testes das rotas /auth/* via HTTP."""

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
        """Login com credenciais válidas deve redirecionar para o dashboard."""
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