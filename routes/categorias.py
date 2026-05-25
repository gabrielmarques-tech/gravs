"""
routes/categorias.py — Gerenciamento de categorias do usuário.

Permite criar, editar e excluir categorias personalizadas,
além das categorias padrão criadas no cadastro.
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from flask_login import current_user, login_required
from routes.helpers import get_services

logger = logging.getLogger(__name__)
categorias_bp = Blueprint("categorias", __name__, url_prefix="/categorias")

ICONES_DISPONIVEIS = [
    "💰","💸","🏠","🍕","🚗","❤️","🎮","📚","👕","📱","✈️","🐾",
    "🎵","🏋️","🍺","☕","🛒","💊","🎁","🏖️","📦","🔧","💡","🎯",
    "💼","💻","📈","🐷","👛","🏦","💳","🎓","🏥","🌱","🔑","⚡",
]

@categorias_bp.route("/")
@login_required
def lista():
    svc = get_services()
    cats = svc.categorias_repo.listar_por_usuario(current_user.id)
    receitas = [c for c in cats if c["tipo"] == "receita"]
    despesas = [c for c in cats if c["tipo"] == "despesa"]
    return render_template(
        "categorias/lista.html",
        receitas=receitas,
        despesas=despesas,
        icones=ICONES_DISPONIVEIS,
    )

@categorias_bp.route("/nova", methods=["POST"])
@login_required
def nova():
    nome     = request.form.get("nome", "").strip()
    tipo     = request.form.get("tipo", "despesa")
    icone    = request.form.get("icone", "💸")
    cor      = request.form.get("cor", "#7c3aed")

    if not nome:
        return redirect(url_for("categorias.lista"))

    if tipo not in ("receita", "despesa"):
        return redirect(url_for("categorias.lista"))

    svc = get_services()
    try:
        with svc.categorias_repo._db.get_write_conn() as conn:
            conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id, icone, cor) VALUES (?, ?, ?, ?, ?)",
                (nome, tipo, current_user.id, icone, cor)
            )
        logger.info("Categoria criada: %s (%s) user_id=%d", nome, tipo, current_user.id)
    except Exception as e:
        if "UNIQUE" in str(e):
            pass  # ignora duplicata silenciosamente

    return redirect(url_for("categorias.lista"))

@categorias_bp.route("/editar/<int:cat_id>", methods=["POST"])
@login_required
def editar(cat_id: int):
    nome  = request.form.get("nome", "").strip()
    icone = request.form.get("icone", "💸")
    cor   = request.form.get("cor", "#7c3aed")

    if not nome:
        return redirect(url_for("categorias.lista"))

    svc = get_services()
    with svc.categorias_repo._db.get_write_conn() as conn:
        conn.execute(
            """UPDATE categorias SET nome=?, icone=?, cor=?
               WHERE id=? AND usuario_id=?""",
            (nome, icone, cor, cat_id, current_user.id)
        )
    return redirect(url_for("categorias.lista"))

@categorias_bp.route("/deletar/<int:cat_id>", methods=["POST"])
@login_required
def deletar(cat_id: int):
    svc = get_services()
    # Verifica se tem transações vinculadas
    with svc.categorias_repo._db.get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM transacoes WHERE categoria_id=? AND usuario_id=? AND deletado=0",
            (cat_id, current_user.id)
        ).fetchone()[0]

    if count > 0:
        # Não deleta — tem transações vinculadas
        return redirect(url_for("categorias.lista") + "?erro=tem_transacoes")

    with svc.categorias_repo._db.get_write_conn() as conn:
        conn.execute(
            "DELETE FROM categorias WHERE id=? AND usuario_id=?",
            (cat_id, current_user.id)
        )
    return redirect(url_for("categorias.lista"))

@categorias_bp.route("/api/listar")
@login_required
def api_listar():
    svc = get_services()
    cats = svc.categorias_repo.listar_por_usuario(current_user.id)
    return jsonify({"categorias": cats})