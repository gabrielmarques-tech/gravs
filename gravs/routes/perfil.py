"""
routes/perfil.py — Perfil do usuário: troca de nome e senha.

Mantém separado de auth.py para manter cada blueprint focado
em uma responsabilidade única (SRP).
"""

import logging
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from routes.helpers import get_services

logger = logging.getLogger(__name__)

perfil_bp = Blueprint("perfil", __name__, url_prefix="/perfil")


@perfil_bp.route("/", methods=["GET"])
@login_required
def index():
    """Exibe a página de perfil do usuário."""
    return render_template("perfil/index.html")


@perfil_bp.route("/nome", methods=["POST"])
@login_required
def atualizar_nome():
    """Atualiza o nome do usuário."""
    novo_nome = request.form.get("nome", "").strip()

    if not novo_nome or len(novo_nome) < 2:
        flash("Nome deve ter pelo menos 2 caracteres.", "erro")
        return redirect(url_for("perfil.index"))

    if len(novo_nome) > 80:
        flash("Nome muito longo. Máximo 80 caracteres.", "erro")
        return redirect(url_for("perfil.index"))

    svc = get_services()
    with svc.db.get_write_conn() as conn:
        conn.execute(
            "UPDATE usuarios SET nome = ? WHERE id = ?",
            (novo_nome, current_user.id)
        )

    # Atualiza o nome na sessão atual
    current_user.nome = novo_nome
    flash("✓ Nome atualizado com sucesso!", "sucesso")
    return redirect(url_for("perfil.index"))


@perfil_bp.route("/senha", methods=["POST"])
@login_required
def atualizar_senha():
    """Atualiza a senha do usuário após verificar a senha atual."""
    senha_atual  = request.form.get("senha_atual", "")
    nova_senha   = request.form.get("nova_senha", "")
    confirmacao  = request.form.get("confirmacao", "")

    # Validações
    if not senha_atual or not nova_senha or not confirmacao:
        flash("Preencha todos os campos.", "erro")
        return redirect(url_for("perfil.index"))

    if nova_senha != confirmacao:
        flash("A nova senha e a confirmação não coincidem.", "erro")
        return redirect(url_for("perfil.index"))

    if len(nova_senha) < 6:
        flash("A nova senha deve ter pelo menos 6 caracteres.", "erro")
        return redirect(url_for("perfil.index"))

    # Verifica senha atual
    svc = get_services()
    usuario = svc.usuarios_repo.buscar_por_id(current_user.id)
    if not usuario or not check_password_hash(usuario["senha_hash"], senha_atual):
        flash("Senha atual incorreta.", "erro")
        return redirect(url_for("perfil.index"))

    # Salva nova senha com hash seguro
    novo_hash = generate_password_hash(nova_senha)
    with svc.db.get_write_conn() as conn:
        conn.execute(
            "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
            (novo_hash, current_user.id)
        )

    flash("✓ Senha alterada com sucesso!", "sucesso")
    return redirect(url_for("perfil.index"))


@perfil_bp.route("/contabil", methods=["POST"])
@login_required
def toggle_contabil():
    """Ativa ou desativa o modo contábil do usuário."""
    svc = get_services()

    # Busca estado atual
    with svc.db.get_conn() as conn:
        row = conn.execute(
            "SELECT modo_contabil FROM usuarios WHERE id = ?",
            (current_user.id,)
        ).fetchone()

    modo_atual = row["modo_contabil"] if row else 0
    novo_modo  = 0 if modo_atual else 1

    with svc.db.get_write_conn() as conn:
        conn.execute(
            "UPDATE usuarios SET modo_contabil = ? WHERE id = ?",
            (novo_modo, current_user.id)
        )

    if novo_modo:
        flash("✓ Modo contábil ativado! Acesse Exportar → Partida Dobrada.", "sucesso")
    else:
        flash("Modo contábil desativado.", "info")

    return redirect(url_for("perfil.index"))
