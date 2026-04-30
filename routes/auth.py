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

from flask import (
    Blueprint, current_app, flash, redirect,
    render_template, request, url_for
)
from flask_login import login_required, login_user, logout_user

from routes.helpers import get_services, make_user_principal

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Exibe formulário e processa login."""
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
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    """Exibe formulário e processa registro de novo usuário."""
    if request.method == "GET":
        return render_template("auth/cadastro.html")

    email = request.form.get("email", "").strip()
    senha = request.form.get("senha", "")
    nome = request.form.get("nome", "").strip()

    svc = get_services()
    user_id, erros = svc.auth.registrar(email, senha, nome)

    if erros:
        for campo, msg in erros.items():
            flash(msg, "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    flash("Conta criada com sucesso! Faça login.", "sucesso")
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
@login_required
def logout():
    """Encerra sessão do usuário."""
    logout_user()
    return redirect(url_for("auth.login"))