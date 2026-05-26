"""
routes/metas.py — Metas financeiras do usuário.

Uma meta é um objetivo financeiro com valor alvo e prazo.
Exemplos: "Juntar R$ 5.000 até dezembro", "Quitar dívida de R$ 2.000"

O progresso é atualizado manualmente pelo usuário.
"""

import logging
import uuid as uuid_lib
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from routes.helpers import get_services

logger = logging.getLogger(__name__)

metas_bp = Blueprint("metas", __name__, url_prefix="/metas")


@metas_bp.route("/", methods=["GET"])
@login_required
def lista():
    svc = get_services()
    metas = svc.metas_repo.listar(current_user.id)
    return render_template("metas/lista.html", metas=metas)


@metas_bp.route("/nova", methods=["POST"])
@login_required
def nova():
    svc = get_services()

    titulo    = request.form.get("titulo", "").strip()
    valor_str = request.form.get("valor_alvo", "0").replace(",", ".")
    data_fim  = request.form.get("data_fim", "") or None
    descricao = request.form.get("descricao", "").strip()

    if not titulo or len(titulo) < 2:
        flash("Título deve ter pelo menos 2 caracteres.", "erro")
        return redirect(url_for("metas.lista"))

    try:
        valor_alvo = float(valor_str)
        if valor_alvo <= 0:
            raise ValueError
    except ValueError:
        flash("Valor inválido.", "erro")
        return redirect(url_for("metas.lista"))

    uid = str(uuid_lib.uuid4())
    svc.metas_repo.criar(
        uuid=uid,
        titulo=titulo,
        valor_alvo=valor_alvo,
        data_fim=data_fim,
        usuario_id=current_user.id,
        descricao=descricao,
    )

    flash(f"✓ Meta '{titulo}' criada!", "sucesso")
    return redirect(url_for("metas.lista"))


@metas_bp.route("/progresso/<uuid>", methods=["POST"])
@login_required
def atualizar_progresso(uuid: str):
    svc = get_services()

    valor_str = request.form.get("valor_atual", "0").replace(",", ".")
    try:
        valor_atual = float(valor_str)
        if valor_atual < 0:
            raise ValueError
    except ValueError:
        flash("Valor inválido.", "erro")
        return redirect(url_for("metas.lista"))

    ok = svc.metas_repo.atualizar_progresso(uuid, valor_atual, current_user.id)
    if ok:
        flash("✓ Progresso atualizado!", "sucesso")
    else:
        flash("Meta não encontrada.", "erro")

    return redirect(url_for("metas.lista"))


@metas_bp.route("/deletar/<uuid>", methods=["POST"])
@login_required
def deletar(uuid: str):
    svc = get_services()
    ok = svc.metas_repo.deletar(uuid, current_user.id)
    if ok:
        flash("Meta removida.", "sucesso")
    else:
        flash("Meta não encontrada.", "erro")
    return redirect(url_for("metas.lista"))


@metas_bp.route("/api/listar")
@login_required
def api_listar():
    svc = get_services()
    metas = svc.metas_repo.listar(current_user.id)
    return jsonify({"metas": metas, "count": len(metas)})
