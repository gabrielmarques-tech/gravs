"""
routes/perfil.py — Perfil do usuário: troca de nome e senha.
"""

import logging
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from routes.helpers import get_services

logger = logging.getLogger(__name__)

perfil_bp = Blueprint("perfil", __name__, url_prefix="/perfil")


@perfil_bp.route("/", methods=["GET"])
@login_required
def index():
    return render_template("perfil/index.html")


@perfil_bp.route("/nome", methods=["POST"])
@login_required
def atualizar_nome():
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

    current_user.nome = novo_nome
    flash("✓ Nome atualizado com sucesso!", "sucesso")
    return redirect(url_for("perfil.index"))


@perfil_bp.route("/senha", methods=["POST"])
@login_required
def atualizar_senha():
    senha_atual = request.form.get("senha_atual", "")
    nova_senha  = request.form.get("nova_senha", "")
    confirmacao = request.form.get("confirmacao", "")

    if not senha_atual or not nova_senha or not confirmacao:
        flash("Preencha todos os campos.", "erro")
        return redirect(url_for("perfil.index"))

    if nova_senha != confirmacao:
        flash("A nova senha e a confirmação não coincidem.", "erro")
        return redirect(url_for("perfil.index"))

    if len(nova_senha) < 6:
        flash("A nova senha deve ter pelo menos 6 caracteres.", "erro")
        return redirect(url_for("perfil.index"))

    svc = get_services()
    usuario = svc.usuarios_repo.buscar_por_id(current_user.id)
    if not usuario or not check_password_hash(usuario["senha_hash"], senha_atual):
        flash("Senha atual incorreta.", "erro")
        return redirect(url_for("perfil.index"))

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
    svc = get_services()

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


@perfil_bp.route("/excluir-conta", methods=["POST"])
@login_required
def excluir_conta():
    """
    Exclusão de conta conforme LGPD.
    Anonimiza o email, desativa a conta e desloga o usuário.
    Exige confirmação da senha atual.
    """
    senha_confirmacao = request.form.get("senha_confirmacao", "")

    if not senha_confirmacao:
        flash("Informe sua senha para confirmar a exclusão.", "erro")
        return redirect(url_for("perfil.index"))

    svc = get_services()
    usuario = svc.usuarios_repo.buscar_por_id(current_user.id)

    if not usuario or not check_password_hash(usuario["senha_hash"], senha_confirmacao):
        flash("Senha incorreta. Exclusão cancelada.", "erro")
        logger.warning("Tentativa de exclusão com senha errada: user_id=%d", current_user.id)
        return redirect(url_for("perfil.index"))

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uid = current_user.id

    with svc.db.get_write_conn() as conn:
        conn.execute(
            "UPDATE usuarios SET excluido_em=? WHERE id=?",
            (agora, uid)
        )

    svc.usuarios_repo.anonimizar_email(uid)

    logger.warning("AUDITORIA: conta_excluida user_id=%d ip=%s em=%s",
                   uid, request.remote_addr, agora)

    logout_user()
    flash("Sua conta foi excluída. Sentiremos sua falta!", "sucesso")
    return redirect(url_for("auth.login"))