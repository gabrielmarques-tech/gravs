"""routes/recorrentes.py — Rotas de lançamentos recorrentes/fixos."""

import logging
from datetime import datetime

from flask import (
    Blueprint, current_user, jsonify,
    redirect, render_template, request, url_for
)
from flask_login import login_required

from routes.helpers import get_services
from utils.formatters import parse_valor_monetario

logger = logging.getLogger(__name__)

recorrentes_bp = Blueprint("recorrentes", __name__)


@recorrentes_bp.route("/fixas", methods=["GET", "POST"])
@login_required
def fixas():
    svc = get_services()

    if request.method == "POST":
        try:
            valor = parse_valor_monetario(request.form.get("valor", "0"))
            id_rec, erros = svc.recorrentes.adicionar(
                descricao=request.form.get("descricao", ""),
                valor=valor,
                tipo=request.form.get("tipo", "despesa"),
                categoria_id=int(request.form.get("categoria_id", 0)),
                dia_vencimento=int(request.form.get("dia_vencimento", 5)),
                usuario_id=current_user.id,
            )
            if erros:
                logger.warning("Erros ao criar recorrente: %s", erros)
        except (ValueError, TypeError) as exc:
            logger.error("Erro em /fixas POST: %s", exc, exc_info=True)

        return redirect(url_for("recorrentes.fixas"))

    hoje = datetime.now()
    recorrentes = svc.recorrentes.listar(current_user.id)
    proximos = svc.recorrentes.listar_proximos_do_mes(
        hoje.year, hoje.month, current_user.id
    )
    categorias = svc.categorias_repo.listar_por_usuario(current_user.id)

    return render_template(
        "recorrentes/lista.html",
        recorrentes=recorrentes,
        proximos=proximos,
        categorias=categorias,
        usuario=current_user,
    )


@recorrentes_bp.route("/fixas/editar/<uuid_rec>", methods=["POST"])
@login_required
def editar_fixo(uuid_rec: str):
    svc = get_services()
    try:
        valor = parse_valor_monetario(request.form.get("valor", "0"))
        ok, erros = svc.recorrentes.editar(
            uuid_rec,
            usuario_id=current_user.id,
            descricao=request.form.get("descricao"),
            valor=valor,
            tipo=request.form.get("tipo"),
            categoria_id=int(request.form.get("categoria_id", 0)),
            dia_vencimento=int(request.form.get("dia_vencimento", 5)),
        )
        if not ok or erros:
            logger.warning("Falha ao editar recorrente %s: %s", uuid_rec, erros)
    except (ValueError, TypeError) as exc:
        logger.error("Erro ao editar recorrente %s: %s", uuid_rec, exc)

    return redirect(url_for("recorrentes.fixas"))


@recorrentes_bp.route("/api/fixo/<uuid_rec>", methods=["DELETE"])
@login_required
def api_deletar_fixo(uuid_rec: str):
    svc = get_services()
    ok = svc.recorrentes.desativar(uuid_rec, current_user.id)
    return jsonify({"success": ok})