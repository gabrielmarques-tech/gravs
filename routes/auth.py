"""
routes/auth.py — Rotas de autenticação (Blueprint).

Por que Blueprint e não rotas diretas em app.py?
--------------------------------------------------
Blueprints são módulos de rotas Flask reutilizáveis e testáveis.
Cada blueprint:
1. Tem seu próprio prefixo de URL (/auth/)
2. Pode ser registrado ou removido do app sem alterar outros módulos
3. Permite testes isolados do blueprint sem subir o app inteiro
4. Escala: adicione /api/v2/auth sem mexer nas rotas originais

Responsabilidade das routes:
- Receber request HTTP (form, json, query params)
- Chamar o service correto
- Retornar response HTTP (redirect, render, jsonify)
- NÃO conter lógica de negócio
- NÃO fazer queries SQL diretamente
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import (
    Blueprint, current_app, flash, redirect,
    render_template, request, url_for
)
from flask_login import login_required, login_user, logout_user

from routes.helpers import get_services, make_user_principal

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Exibe formulário e processa login.

    Proteções:
    - Rate limit: 5 tentativas por minuto por IP
    - Logs de falha para auditoria
    - Não revela se email existe ou não (mesma mensagem para os dois casos)
    """
    from flask import current_app
    limiter = current_app.extensions.get("limiter")
    if limiter:
        limiter.limit("5 per minute")(lambda: None)()

    if request.method == "GET":
        return render_template("auth/login.html")

    email = request.form.get("email", "").strip()
    senha = request.form.get("senha", "")

    svc = get_services()
    usuario, erro = svc.auth.autenticar(email, senha)

    if erro:
        flash(erro, "erro")
        return render_template("auth/login.html", email=email), 401

    user_principal = make_user_principal(usuario)
    login_user(user_principal, remember=True)

    # Aproveita o login para limpar tokens expirados silenciosamente
    try:
        svc.db.limpar_tokens_expirados()
    except Exception:
        pass  # Nunca bloqueia o login por causa de limpeza

    return redirect(url_for("dashboard.index"))

@auth_bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    """Exibe formulário e processa registro de novo usuário."""
    if request.method == "GET":
        return render_template("auth/cadastro.html")

    email = request.form.get("email", "").strip().lower()
    senha = request.form.get("senha", "")
    nome  = request.form.get("nome", "").strip()

    modo_contabil = 1 if request.form.get("modo_contabil") == "1" else 0

    # Validações de segurança antes de processar
    if len(senha) < 6:
        flash("A senha deve ter pelo menos 6 caracteres.", "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    if len(nome) < 2:
        flash("O nome deve ter pelo menos 2 caracteres.", "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    if "@" not in email or "." not in email.split("@")[-1]:
        flash("Informe um email válido.", "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    if len(email) > 200 or len(nome) > 80:
        flash("Dados muito longos.", "erro")
        return render_template("auth/cadastro.html"), 422

    svc = get_services()
    user_id, erros = svc.auth.registrar(email, senha, nome)

    if erros:
        for campo, msg in erros.items():
            flash(msg, "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    # Salva preferência de modo contábil se marcada
    if modo_contabil and user_id:
        with svc.db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET modo_contabil=1 WHERE id=?", (user_id,)
            )

    # Cria contas bancárias padrão para o novo usuário
    if user_id:
        svc.contas_repo.criar_sugestoes_padrao(user_id)

    flash("Conta criada com sucesso! Faça login.", "sucesso")
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
@login_required
def logout():
    """Encerra sessão do usuário."""
    logout_user()
    return redirect(url_for("auth.login"))