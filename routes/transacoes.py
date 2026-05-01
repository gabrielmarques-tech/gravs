"""
routes/transacoes.py — Rotas de transações (avulsas e parceladas).
"""

import calendar as cal
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

transacoes_bp = Blueprint("transacoes", __name__)


@transacoes_bp.route("/rapido", methods=["GET", "POST"])
@login_required
def rapido():
    svc = get_services()
    if request.method == "POST":
        try:
            valor  = parse_valor_monetario(request.form.get("valor", "0"))
            desc   = request.form.get("descricao", "").strip()
            tipo   = request.form.get("tipo", "despesa")
            data   = request.form.get("data") or date.today().strftime("%Y-%m-%d")
            cat    = svc.categorias_repo.buscar_padrao_por_tipo(current_user.id, tipo)
            cat_id = cat["id"] if cat else 1
            svc.transacoes.adicionar(descricao=desc, valor=valor, tipo=tipo,
                                     categoria_id=cat_id, usuario_id=current_user.id, data=data)
        except ValueError as exc:
            logger.error("Erro em /rapido: %s", exc)
        return redirect(url_for("dashboard.index"))

    return render_template("transacoes/rapido.html",
                           data_hoje=date.today().strftime("%Y-%m-%d"))


@transacoes_bp.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    svc = get_services()
    if request.method == "POST":
        try:
            valor    = parse_valor_monetario(request.form.get("valor", "0"))
            parcelas = request.form.get("parcelas", "").strip()

            if parcelas and int(parcelas) >= 2:
                taxa = float(request.form.get("taxa_juros", "0") or "0")
                ids, erros = svc.transacoes.adicionar_parcelado(
                    descricao=request.form.get("descricao", ""),
                    valor_total=valor,
                    tipo=request.form.get("tipo", "despesa"),
                    categoria_id=int(request.form.get("categoria_id", 0)),
                    usuario_id=current_user.id,
                    parcelas=int(parcelas),
                    data_inicial=request.form.get("data"),
                    tipo_juros=request.form.get("tipo_juros", "sem"),
                    taxa_juros_mensal=taxa,
                )
                if erros:
                    logger.warning("Erros em /novo parcelado: %s", erros)
            else:
                id_t, erros = svc.transacoes.adicionar(
                    descricao=request.form.get("descricao", ""),
                    valor=valor,
                    tipo=request.form.get("tipo", "despesa"),
                    categoria_id=int(request.form.get("categoria_id", 0)),
                    usuario_id=current_user.id,
                    data=request.form.get("data"),
                )
                if erros:
                    logger.warning("Erros em /novo: %s", erros)
        except (ValueError, TypeError) as exc:
            logger.error("Erro em /novo POST: %s", exc, exc_info=True)

        return redirect(url_for("transacoes.todas"))

    categorias = svc.categorias_repo.listar_por_usuario(current_user.id)
    return render_template(
        "transacoes/novo.html",
        categorias=categorias,
        valor_sugerido=request.args.get("valor", ""),
        data_sugerida=request.args.get("data", date.today().strftime("%Y-%m-%d")),
        desc_sugerida=request.args.get("desc", ""),
    )


@transacoes_bp.route("/parcelado", methods=["GET", "POST"])
@login_required
def parcelado():
    svc = get_services()
    if request.method == "POST":
        try:
            valor    = parse_valor_monetario(request.form.get("valor", "0"))
            parcelas = int(request.form.get("parcelas", 2))
            taxa     = float(request.form.get("taxa_juros", "0") or "0")

            ids, erros = svc.transacoes.adicionar_parcelado(
                descricao=request.form.get("descricao", ""),
                valor_total=valor,
                tipo=request.form.get("tipo", "despesa"),
                categoria_id=int(request.form.get("categoria_id", 0)),
                usuario_id=current_user.id,
                parcelas=parcelas,
                data_inicial=request.form.get("data"),
                tipo_juros=request.form.get("tipo_juros", "sem"),
                taxa_juros_mensal=taxa,
            )
            if erros:
                flash("Erro ao criar parcelamento.", "erro")
            else:
                flash(f"✓ {len(ids)} parcelas criadas com sucesso!", "sucesso")
        except (ValueError, TypeError) as exc:
            logger.error("Erro em /parcelado POST: %s", exc, exc_info=True)
            flash("Erro ao processar. Verifique os dados.", "erro")

        return redirect(url_for("transacoes.todas"))

    categorias = svc.categorias_repo.listar_por_usuario(current_user.id)
    return render_template(
        "transacoes/parcelado.html",
        categorias=categorias,
        data_hoje=date.today().strftime("%Y-%m-%d"),
    )


@transacoes_bp.route("/todas")
@login_required
def todas():
    svc = get_services()
    uid  = current_user.id
    hoje = date.today()

    inicio_padrao = date(hoje.year - 1, 1, 1).strftime("%Y-%m-%d")
    fim_padrao    = hoje.strftime("%Y-%m-%d")

    data_inicio = request.args.get("inicio", inicio_padrao)
    data_fim    = request.args.get("fim",    fim_padrao)

    try:
        datetime.strptime(data_inicio, "%Y-%m-%d")
        datetime.strptime(data_fim,    "%Y-%m-%d")
    except ValueError:
        data_inicio = inicio_padrao
        data_fim    = fim_padrao

    transacoes     = svc.transacoes.listar_por_periodo(data_inicio, data_fim, uid)
    categorias     = svc.categorias_repo.listar_por_usuario(uid)
    total_receitas = sum(t["valor"] for t in transacoes if t["tipo"] == "receita")
    total_despesas = sum(t["valor"] for t in transacoes if t["tipo"] == "despesa")

    # Agrupa parcelamentos para mostrar botão de excluir grupo
    grupos = {}
    for t in transacoes:
        g = t.get("grupo_parcela")
        if g:
            if g not in grupos:
                grupos[g] = {"descricao": t["descricao"].rsplit(" (", 1)[0], "count": 0}
            grupos[g]["count"] += 1

    return render_template(
        "transacoes/lista.html",
        transacoes=transacoes,
        categorias=categorias,
        filtro_inicio=data_inicio,
        filtro_fim=data_fim,
        total_receitas=total_receitas,
        total_despesas=total_despesas,
        saldo=total_receitas - total_despesas,
        grupos=grupos,
        usuario=current_user,
    )


@transacoes_bp.route("/editar/<int:id_transacao>", methods=["POST"])
@login_required
def editar(id_transacao: int):
    svc = get_services()
    try:
        valor = parse_valor_monetario(request.form.get("valor", "0"))
        ok = svc.transacoes.editar(
            id_transacao,
            usuario_id=current_user.id,
            descricao=request.form.get("descricao"),
            valor=valor,
            tipo=request.form.get("tipo"),
            categoria_id=request.form.get("categoria_id"),
            data=request.form.get("data"),
        )
        if ok:
            flash("✓ Transação atualizada!", "sucesso")
        else:
            flash("Não foi possível atualizar.", "erro")
    except (ValueError, TypeError) as exc:
        logger.error("Erro ao editar transação %d: %s", id_transacao, exc)
        flash("Erro ao salvar. Verifique os dados.", "erro")

    return redirect(request.referrer or url_for("transacoes.todas"))


# ── API ────────────────────────────────────────────────────────────────────────

@transacoes_bp.route("/api/transacao/<uuid_transacao>", methods=["DELETE"])
@login_required
def api_deletar_transacao(uuid_transacao: str):
    svc = get_services()
    transacao = svc.transacoes.buscar_por_uuid(uuid_transacao, current_user.id)
    if not transacao:
        return jsonify({"error": "Não encontrada"}), 404
    ok = svc.transacoes.deletar(transacao["id"], current_user.id)
    return jsonify({"success": ok})


@transacoes_bp.route("/api/transacao/<uuid_transacao>", methods=["GET"])
@login_required
def api_get_transacao(uuid_transacao: str):
    svc = get_services()
    transacao = svc.transacoes.buscar_por_uuid(uuid_transacao, current_user.id)
    if not transacao:
        return jsonify({"error": "Não encontrada"}), 404
    return jsonify({"transacao": transacao})


@transacoes_bp.route("/api/transacao/<int:id_transacao>/restaurar", methods=["POST"])
@login_required
def api_restaurar_transacao(id_transacao: int):
    svc = get_services()
    ok = svc.transacoes.restaurar(id_transacao, current_user.id)
    return jsonify({"success": ok})


@transacoes_bp.route("/api/grupo/<grupo_uuid>", methods=["DELETE"])
@login_required
def api_deletar_grupo(grupo_uuid: str):
    """
    Deleta (soft-delete) todas as parcelas de um parcelamento.

    Segurança: passa usuario_id em todas as operações —
    nunca deleta parcelas de outro usuário mesmo que descubra o grupo_uuid.
    """
    svc = get_services()
    try:
        deletadas = svc.transacoes_repo.deletar_grupo(grupo_uuid, current_user.id)
        return jsonify({"success": True, "deletadas": deletadas})
    except Exception as exc:
        logger.error("Erro ao deletar grupo %s: %s", grupo_uuid, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@transacoes_bp.route("/api/preview_parcelas", methods=["POST"])
@login_required
def api_preview_parcelas():
    svc = get_services()
    try:
        valor      = parse_valor_monetario(request.json.get("valor", "0"))
        parcelas   = int(request.json.get("parcelas", 2))
        tipo_juros = request.json.get("tipo_juros", "sem")
        taxa       = float(request.json.get("taxa_juros", 0) or 0)
        valores    = svc.transacoes.calcular_preview_parcelas(valor, parcelas, tipo_juros, taxa)
        return jsonify({"parcelas": valores, "total": sum(valores)})
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 422