"""
routes/transacoes.py — Rotas de transações (avulsas e parceladas).

Princípio de segurança nas rotas:
- Nunca confiar no ID vindo da URL sem verificar `usuario_id`
- O service garante isolamento, mas a route deve passar `current_user.id`
- Erros de validação retornam 422 (Unprocessable Entity), não 500
"""

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

transacoes_bp = Blueprint("transacoes", __name__)


# ── Lançamento rápido ──────────────────────────────────────────────────────────

@transacoes_bp.route("/rapido", methods=["GET", "POST"])
@login_required
def rapido():
    svc = get_services()

    if request.method == "POST":
        try:
            valor = parse_valor_monetario(request.form.get("valor", "0"))
            desc = request.form.get("descricao", "").strip()
            tipo = request.form.get("tipo", "despesa")
            data = request.form.get("data") or datetime.now().strftime("%Y-%m-%d")

            # Busca categoria padrão do tipo (sem necessitar que usuário escolha)
            cat = svc.categorias_repo.buscar_padrao_por_tipo(current_user.id, tipo)
            cat_id = cat["id"] if cat else 1

            id_t, erros = svc.transacoes.adicionar(
                descricao=desc, valor=valor, tipo=tipo,
                categoria_id=cat_id, usuario_id=current_user.id, data=data,
            )
            if erros:
                logger.warning("Erros em /rapido POST: %s", erros)
        except ValueError as exc:
            logger.error("Erro de valor em /rapido: %s", exc)

        return redirect(url_for("dashboard.index"))

    data_hoje = datetime.now().strftime("%Y-%m-%d")
    return render_template("transacoes/rapido.html", data_hoje=data_hoje)


# ── Novo lançamento completo ───────────────────────────────────────────────────

@transacoes_bp.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    svc = get_services()

    if request.method == "POST":
        try:
            valor = parse_valor_monetario(request.form.get("valor", "0"))
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

        return redirect(url_for("dashboard.index"))

    categorias = svc.categorias_repo.listar_por_usuario(current_user.id)
    return render_template(
        "transacoes/novo.html",
        categorias=categorias,
        valor_sugerido=request.args.get("valor", ""),
        data_sugerida=request.args.get("data", datetime.now().strftime("%Y-%m-%d")),
        desc_sugerida=request.args.get("desc", ""),
    )


# ── Lançamento parcelado ───────────────────────────────────────────────────────

@transacoes_bp.route("/parcelado", methods=["GET", "POST"])
@login_required
def parcelado():
    svc = get_services()

    if request.method == "POST":
        try:
            valor = parse_valor_monetario(request.form.get("valor", "0"))
            parcelas = int(request.form.get("parcelas", 2))
            taxa = float(request.form.get("taxa_juros", "0") or "0")

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
                logger.warning("Erros em /parcelado: %s", erros)
        except (ValueError, TypeError) as exc:
            logger.error("Erro em /parcelado POST: %s", exc, exc_info=True)

        return redirect(url_for("dashboard.index"))

    categorias = svc.categorias_repo.listar_por_usuario(current_user.id)
    return render_template(
        "transacoes/parcelado.html",
        categorias=categorias,
        data_hoje=datetime.now().strftime("%Y-%m-%d"),
    )


# ── Lista de transações ────────────────────────────────────────────────────────

@transacoes_bp.route("/todas")
@login_required
def todas():
    svc = get_services()
    hoje = datetime.now()
    ano, mes = hoje.year, hoje.month
    uid = current_user.id

    data_inicio = f"{ano}-{mes:02d}-01"
    import calendar as cal
    ultimo_dia = cal.monthrange(ano, mes)[1]
    data_fim = f"{ano}-{mes:02d}-{ultimo_dia:02d}"

    transacoes = svc.transacoes.listar_por_periodo(data_inicio, data_fim, uid)
    categorias = svc.categorias_repo.listar_por_usuario(uid)

    return render_template(
        "transacoes/lista.html",
        transacoes=transacoes,
        categorias=categorias,
        usuario=current_user,
    )


# ── Edição ─────────────────────────────────────────────────────────────────────

@transacoes_bp.route("/editar/<int:id_transacao>", methods=["POST"])
@login_required
def editar(id_transacao: int):
    svc = get_services()
    try:
        valor = parse_valor_monetario(request.form.get("valor", "0"))
        svc.transacoes.editar(
            id_transacao,
            usuario_id=current_user.id,
            descricao=request.form.get("descricao"),
            valor=valor,
            tipo=request.form.get("tipo"),
            categoria_id=request.form.get("categoria_id"),
            data=request.form.get("data"),
        )
    except (ValueError, TypeError) as exc:
        logger.error("Erro ao editar transação %d: %s", id_transacao, exc)

    return redirect(url_for("transacoes.todas"))


# ── API JSON ───────────────────────────────────────────────────────────────────

@transacoes_bp.route("/api/transacao/<uuid_transacao>", methods=["GET"])
@login_required
def api_get_transacao(uuid_transacao: str):
    svc = get_services()
    transacao = svc.transacoes.buscar_por_uuid(uuid_transacao, current_user.id)
    if not transacao:
        return jsonify({"error": "Não encontrada"}), 404

    categorias = svc.categorias_repo.listar_por_usuario(current_user.id)
    return jsonify({
        "transacao": transacao,
        "categorias": categorias,
    })


@transacoes_bp.route("/api/transacao/<uuid_transacao>", methods=["DELETE"])
@login_required
def api_deletar_transacao(uuid_transacao: str):
    svc = get_services()
    transacao = svc.transacoes.buscar_por_uuid(uuid_transacao, current_user.id)
    if not transacao:
        return jsonify({"error": "Não encontrada"}), 404

    ok = svc.transacoes.deletar(transacao["id"], current_user.id)
    return jsonify({"success": ok})


@transacoes_bp.route("/api/transacao/<int:id_transacao>/restaurar", methods=["POST"])
@login_required
def api_restaurar_transacao(id_transacao: int):
    svc = get_services()
    ok = svc.transacoes.restaurar(id_transacao, current_user.id)
    return jsonify({"success": ok})


@transacoes_bp.route("/api/preview_parcelas", methods=["POST"])
@login_required
def api_preview_parcelas():
    """Retorna preview de parcelas sem salvar no banco."""
    svc = get_services()
    try:
        valor = parse_valor_monetario(request.json.get("valor", "0"))
        parcelas = int(request.json.get("parcelas", 2))
        tipo_juros = request.json.get("tipo_juros", "sem")
        taxa = float(request.json.get("taxa_juros", 0) or 0)

        valores = svc.transacoes.calcular_preview_parcelas(
            valor, parcelas, tipo_juros, taxa
        )
        return jsonify({"parcelas": valores, "total": sum(valores)})
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 422