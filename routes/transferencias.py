"""
routes/transferencias.py — Transferências entre contas do próprio usuário.

Uma transferência é uma movimentação interna de dinheiro:
- Pagar fatura do cartão de crédito
- Transferir da conta corrente para poupança
- PIX entre contas próprias

NÃO gera receita nem despesa — apenas redistribui saldo entre contas.
O saldo total do usuário permanece o mesmo.
"""

import logging
import uuid as uuid_lib
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from routes.helpers import get_services

logger = logging.getLogger(__name__)

transferencias_bp = Blueprint("transferencias", __name__, url_prefix="/transferencias")


@transferencias_bp.route("/", methods=["GET"])
@login_required
def lista():
    """Lista transferências do mês atual."""
    svc = get_services()
    hoje = date.today()
    inicio = request.args.get("inicio", date(hoje.year, hoje.month, 1).strftime("%Y-%m-%d"))
    fim    = request.args.get("fim",    hoje.strftime("%Y-%m-%d"))

    transferencias = svc.transferencias_repo.listar_por_periodo(inicio, fim, current_user.id)
    contas = svc.contas_repo.listar(current_user.id)

    return render_template(
        "transferencias/lista.html",
        transferencias=transferencias,
        contas=contas,
        filtro_inicio=inicio,
        filtro_fim=fim,
    )


@transferencias_bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    """Registra nova transferência entre contas."""
    svc = get_services()
    contas = svc.contas_repo.listar(current_user.id)

    if request.method == "GET":
        return render_template("transferencias/nova.html", contas=contas)

    # Validações
    try:
        valor = float(request.form.get("valor", "0").replace(",", "."))
    except ValueError:
        flash("Valor inválido.", "erro")
        return render_template("transferencias/nova.html", contas=contas), 422

    conta_origem_id  = request.form.get("conta_origem_id", type=int)
    conta_destino_id = request.form.get("conta_destino_id", type=int)
    descricao        = request.form.get("descricao", "").strip() or "Transferência"
    data             = request.form.get("data", date.today().strftime("%Y-%m-%d"))

    if not conta_origem_id or not conta_destino_id:
        flash("Selecione as contas de origem e destino.", "erro")
        return render_template("transferencias/nova.html", contas=contas), 422

    if conta_origem_id == conta_destino_id:
        flash("A conta de origem e destino não podem ser a mesma.", "erro")
        return render_template("transferencias/nova.html", contas=contas), 422

    if valor <= 0:
        flash("O valor deve ser maior que zero.", "erro")
        return render_template("transferencias/nova.html", contas=contas), 422

    # Verifica se as contas pertencem ao usuário
    ids_contas = {c["id"] for c in contas}
    if conta_origem_id not in ids_contas or conta_destino_id not in ids_contas:
        flash("Conta inválida.", "erro")
        return render_template("transferencias/nova.html", contas=contas), 422

    uid = str(uuid_lib.uuid4())
    svc.transferencias_repo.inserir(
        uuid=uid,
        descricao=descricao,
        valor=valor,
        conta_origem_id=conta_origem_id,
        conta_destino_id=conta_destino_id,
        data=data,
        usuario_id=current_user.id,
    )

    logger.info(
        "Transferência registrada: user_id=%d valor=%.2f origem=%d destino=%d",
        current_user.id, valor, conta_origem_id, conta_destino_id
    )

    flash(f"✓ Transferência de R$ {valor:,.2f} registrada!", "sucesso")
    return redirect(url_for("transferencias.lista"))


@transferencias_bp.route("/deletar/<uuid>", methods=["POST"])
@login_required
def deletar(uuid: str):
    """Soft-delete de uma transferência."""
    svc = get_services()
    ok = svc.transferencias_repo.deletar_logico(uuid, current_user.id)
    if ok:
        flash("Transferência removida.", "sucesso")
    else:
        flash("Transferência não encontrada.", "erro")
    return redirect(url_for("transferencias.lista"))


@transferencias_bp.route("/api/listar")
@login_required
def api_listar():
    """API JSON para o dashboard e widgets."""
    svc = get_services()
    hoje = date.today()
    inicio = request.args.get("inicio", date(hoje.year, hoje.month, 1).strftime("%Y-%m-%d"))
    fim    = request.args.get("fim",    hoje.strftime("%Y-%m-%d"))

    transferencias = svc.transferencias_repo.listar_por_periodo(inicio, fim, current_user.id)
    return jsonify({"transferencias": transferencias, "count": len(transferencias)})
