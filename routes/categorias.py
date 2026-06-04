"""
routes/categorias.py — Gerenciamento de categorias do usuário.

Permite criar, editar e excluir categorias personalizadas,
além das categorias padrão criadas no cadastro.
"""

import logging
"""
routes/categorias.py — Gerenciamento de categorias do usuário.

Permite criar, editar e excluir categorias personalizadas,
além das categorias padrão criadas no cadastro.

NENHUM SQL cru — tudo via CategoriaRepository.
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

    if not nome or tipo not in ("receita", "despesa"):
        return redirect(url_for("categorias.lista"))

    svc = get_services()
    criada = svc.categorias_repo.criar_categoria(nome, tipo, current_user.id, icone, cor)
    if criada:
        logger.info("Categoria criada: %s (%s) user_id=%d", nome, tipo, current_user.id)
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
    svc.categorias_repo.atualizar(cat_id, current_user.id, nome, icone, cor)
    return redirect(url_for("categorias.lista"))


@categorias_bp.route("/deletar/<int:cat_id>", methods=["POST"])
@login_required
def deletar(cat_id: int):
    svc = get_services()

    count = svc.categorias_repo.contar_transacoes_vinculadas(cat_id, current_user.id)
    if count > 0:
        return redirect(url_for("categorias.lista") + "?erro=tem_transacoes")

    svc.categorias_repo.deletar(cat_id, current_user.id)
    return redirect(url_for("categorias.lista"))

@categorias_bp.route("/api/listar")
@login_required
def api_listar():
    svc = get_services()
    cats = svc.categorias_repo.listar_por_usuario(current_user.id)
    return jsonify({"categorias": cats})
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

    if not nome or tipo not in ("receita", "despesa"):
        return redirect(url_for("categorias.lista"))

    svc = get_services()
    criada = svc.categorias_repo.criar_categoria(nome, tipo, current_user.id, icone, cor)
    if criada:
        logger.info("Categoria criada: %s (%s) user_id=%d", nome, tipo, current_user.id)
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
    svc.categorias_repo.atualizar(cat_id, current_user.id, nome, icone, cor)
    return redirect(url_for("categorias.lista"))

@categorias_bp.route("/deletar/<int:cat_id>", methods=["POST"])
@login_required
def deletar(cat_id: int):
    svc = get_services()
    # Verifica se tem transações vinculadas
    count = svc.categorias_repo.contar_transacoes_vinculadas(cat_id, current_user.id)
    if count > 0:
        # Não deleta — tem transações vinculadas
        return redirect(url_for("categorias.lista") + "?erro=tem_transacoes")

    svc.categorias_repo.deletar(cat_id, current_user.id)
    return redirect(url_for("categorias.lista"))

@categorias_bp.route("/api/listar")
@login_required
def api_listar():
    svc = get_services()
    cats = svc.categorias_repo.listar_por_usuario(current_user.id)
    return jsonify({"categorias": cats})