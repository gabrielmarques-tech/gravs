"""routes/contas.py — Gerenciamento de contas bancárias e cartões."""

import logging
from flask import Blueprint, jsonify, redirect, render_template, request, url_for, flash
from flask_login import login_required, current_user
from routes.helpers import get_services

logger = logging.getLogger(__name__)

contas_bp = Blueprint("contas", __name__, url_prefix="/contas")

TIPOS = [
    ("conta",        "🏦", "Conta Corrente/Poupança"),
    ("cartao",       "💳", "Cartão de Crédito"),
    ("carteira",     "👛", "Carteira/Dinheiro"),
    ("poupanca",     "🐷", "Poupança"),
    ("investimento", "📈", "Investimento"),
]


@contas_bp.route("/")
@login_required
def lista():
    svc = get_services()
    contas = svc.contas_repo.listar(current_user.id)
    return render_template("contas/lista.html", contas=contas, tipos=TIPOS)


@contas_bp.route("/adicionar", methods=["POST"])
@login_required
def adicionar():
    svc = get_services()
    nome = request.form.get("nome", "").strip()
    tipo = request.form.get("tipo", "conta")

    conta_id, erro = svc.contas_repo.adicionar(nome, tipo, current_user.id)
    if erro:
        flash(erro, "erro")
    else:
        flash(f"✓ Conta '{nome}' cadastrada!", "sucesso")

    return redirect(url_for("contas.lista"))


@contas_bp.route("/deletar/<int:conta_id>", methods=["POST"])
@login_required
def deletar(conta_id: int):
    svc = get_services()
    svc.contas_repo.deletar(conta_id, current_user.id)
    return redirect(url_for("contas.lista"))


@contas_bp.route("/api/listar")
@login_required
def api_listar():
    """Retorna contas do usuário em JSON — usado pelos selects das transações."""
    svc = get_services()
    contas = svc.contas_repo.listar(current_user.id)
    return jsonify({"contas": contas})
