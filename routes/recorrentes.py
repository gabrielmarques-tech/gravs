"""routes/recorrentes.py — Rotas de lançamentos recorrentes/fixos."""

import logging
from datetime import datetime, date

from flask import (
    Blueprint, jsonify,
    redirect, render_template, request, url_for, flash
)
from flask_login import login_required, current_user

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
            else:
                flash("✓ Conta fixa cadastrada!", "sucesso")
        except (ValueError, TypeError) as exc:
            logger.error("Erro em /fixas POST: %s", exc, exc_info=True)
            flash("Erro ao cadastrar. Verifique os dados.", "erro")

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
    """
    Exclui uma conta fixa e TODOS os lançamentos gerados por ela.

    Comportamento esperado: se o usuário exclui uma conta fixa,
    os lançamentos automáticos que ela gerou também devem sumir
    do dashboard e da lista de transações.
    """
    svc = get_services()

    # 1. Desativa a conta fixa (não gera mais lançamentos)
    ok = svc.recorrentes.desativar(uuid_rec, current_user.id)

    # 2. Deleta todos os lançamentos gerados por essa conta fixa
    if ok:
        deletados = svc.transacoes_repo.deletar_por_recorrente(
            uuid_rec, current_user.id
        )
        logger.info(
            "Conta fixa %s excluída — %d lançamento(s) removido(s) (user_id=%d)",
            uuid_rec, deletados, current_user.id
        )

    return jsonify({"success": ok})


@recorrentes_bp.route("/api/fixo/<uuid_rec>/confirmar", methods=["POST"])
@login_required
def api_confirmar_pagamento(uuid_rec: str):
    """
    Confirma pagamento de uma conta fixa — lança a transação do mês atual.

    Chamado quando o usuário clica em 'Sim, já paguei' no banner do dashboard.
    É idempotente: se já foi lançado no mês, não duplica.
    """
    svc = get_services()
    hoje = date.today()

    try:
        # Busca dados da recorrência
        rec = svc.recorrentes._repo.buscar_por_uuid(uuid_rec, current_user.id)
        if not rec:
            return jsonify({"success": False, "error": "Não encontrada"}), 404

        # Verifica se já foi lançada no mês
        ja_existe = svc.transacoes._repo.existe_recorrente_no_mes(
            uuid_rec, hoje.year, hoje.month
        )
        if ja_existe:
            return jsonify({"success": True, "msg": "Já lançada neste mês"})

        # Lança a transação
        id_t, erros = svc.transacoes.adicionar(
            descricao=rec["descricao"],
            valor=rec["valor"],
            tipo=rec["tipo"],
            categoria_id=rec["categoria_id"],
            usuario_id=current_user.id,
            data=hoje.strftime("%Y-%m-%d"),
            recorrente_uuid=uuid_rec,
        )

        if erros:
            return jsonify({"success": False, "error": str(erros)}), 422

        return jsonify({
            "success": True,
            "msg": f"✓ {rec['descricao']} marcada como paga!"
        })

    except Exception as exc:
        logger.error("Erro ao confirmar pagamento %s: %s", uuid_rec, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@recorrentes_bp.route("/api/fixas_sidebar")
@login_required
def api_fixas_sidebar():
    """Retorna todas as fixas do mês com status para o widget da sidebar."""
    svc = get_services()
    hoje = date.today()

    proximos = svc.recorrentes.listar_proximos_do_mes(
        hoje.year, hoje.month, current_user.id
    )

    return jsonify({
        "fixas": [
            {
                "uuid":      r["uuid"],
                "descricao": r["descricao"],
                "valor":     r["valor"],
                "tipo":      r["tipo"],
                "data":      r["data"],
                "status":    r["status"],
                "atrasada":  r["status"] == "passado",
            }
            for r in proximos
        ]
    })


@recorrentes_bp.route("/api/lembretes")
@login_required
def api_lembretes():
    """
    Retorna contas fixas que vencem hoje ou já venceram sem ser pagas.
    Usado pelo dashboard para montar o banner de lembretes.
    """
    svc = get_services()
    hoje = date.today()

    proximos = svc.recorrentes.listar_proximos_do_mes(
        hoje.year, hoje.month, current_user.id
    )

    # Filtra só as que vencem hoje ou já venceram e não foram pagas
    lembretes = []
    for r in proximos:
        if r["status"] in ("passado", "agendado") and r["tipo"] == "despesa":
            lembretes.append({
                "uuid":      r["uuid"],
                "descricao": r["descricao"],
                "valor":     r["valor"],
                "tipo":      r["tipo"],
                "data":      r["data"],
                "status":    r["status"],
                "atrasada":  r["status"] == "passado",
            })

    return jsonify({"lembretes": lembretes})