"""
routes/transacoes.py — Rotas de transações (avulsas e parceladas).
"""

import calendar as cal
import logging
from datetime import datetime, date, timezone, timedelta

# Fuso horário de Brasília (UTC-3)
_BRASILIA = timezone(timedelta(hours=-3))

def _hoje_brasilia() -> date:
    """Retorna data atual no fuso de Brasília (evita erro de dia/mês no PythonAnywhere)."""
    return datetime.now(_BRASILIA).date()

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
            data   = request.form.get("data") or _hoje_brasilia().strftime("%Y-%m-%d")
            cat    = svc.categorias_repo.buscar_padrao_por_tipo(current_user.id, tipo)
            cat_id = cat["id"] if cat else 1
            svc.transacoes.adicionar(descricao=desc, valor=valor, tipo=tipo,
                                     categoria_id=cat_id, usuario_id=current_user.id, data=data)
        except ValueError as exc:
            logger.error("Erro em /rapido: %s", exc)
        return redirect(url_for("dashboard.index"))

    return render_template("transacoes/rapido.html",
                           data_hoje=_hoje_brasilia().strftime("%Y-%m-%d"))


@transacoes_bp.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    svc = get_services()
    if request.method == "POST":
        try:
            valor    = parse_valor_monetario(request.form.get("valor", "0"))
            parcelas = request.form.get("parcelas", "").strip()
            conta_id_raw = request.form.get("conta_id", "").strip()
            conta_id = int(conta_id_raw) if conta_id_raw else None

            # Validações básicas
            descricao_raw = request.form.get("descricao", "").strip()
            if not descricao_raw:
                flash("Descrição é obrigatória.", "erro")
                return redirect(request.referrer or url_for("transacoes.novo"))
            if valor <= 0:
                flash("O valor deve ser maior que zero.", "erro")
                return redirect(request.referrer or url_for("transacoes.novo"))
            if len(descricao_raw) > 200:
                flash("Descrição muito longa. Máximo 200 caracteres.", "erro")
                return redirect(request.referrer or url_for("transacoes.novo"))

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
                    conta_id=conta_id,
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
        data_sugerida=request.args.get("data", _hoje_brasilia().strftime("%Y-%m-%d")),
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

            conta_id_parc = request.form.get("conta_id", "").strip()
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
                conta_id=int(conta_id_parc) if conta_id_parc else None,
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
        data_hoje=_hoje_brasilia().strftime("%Y-%m-%d"),
    )


@transacoes_bp.route("/todas")
@login_required
def todas():
    svc = get_services()
    uid  = current_user.id
    hoje = _hoje_brasilia()

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
        conta_id_edit = request.form.get("conta_id", "").strip()
        ok = svc.transacoes.editar(
            id_transacao,
            usuario_id=current_user.id,
            descricao=request.form.get("descricao"),
            valor=valor,
            tipo=request.form.get("tipo"),
            categoria_id=request.form.get("categoria_id"),
            data=request.form.get("data"),
            conta_id=int(conta_id_edit) if conta_id_edit else None,
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


@transacoes_bp.route("/parcelados")
@login_required
def parcelados():
    """Lista todos os parcelamentos agrupados por grupo_parcela."""
    svc = get_services()
    uid = current_user.id

    from datetime import date
    hoje_str = _hoje_brasilia().strftime("%Y-%m-%d")

    with svc.transacoes._repo._db.get_conn() as conn:
        rows = conn.execute("""
            SELECT
                t.grupo_parcela,
                t.tipo,
                MIN(t.descricao) as descricao_min,
                -- Total de parcelas no grupo
                COUNT(*) as total,
                -- Parcelas já vencidas (data <= hoje) = pagas/em aberto
                SUM(CASE WHEN t.data <= ? THEN 1 ELSE 0 END) as pagas,
                -- Parcelas futuras ainda não vencidas
                SUM(CASE WHEN t.data > ? THEN 1 ELSE 0 END) as futuras,
                MIN(t.valor) as valor_parcela,
                SUM(t.valor) as valor_total,
                MIN(t.data) as primeira_data,
                MAX(t.data) as ultima_data,
                COALESCE(c.nome, 'Sem categoria') as categoria_nome,
                COALESCE(c.icone, '💳') as categoria_icone,
                COALESCE(cb.nome, '') as conta_nome,
                COALESCE(cb.icone, '') as conta_icone
            FROM transacoes t
            LEFT JOIN categorias c ON t.categoria_id = c.id
            LEFT JOIN contas_bancarias cb ON t.conta_id = cb.id AND cb.ativo = 1
            WHERE t.usuario_id = ? AND t.grupo_parcela IS NOT NULL AND t.deletado = 0
            GROUP BY t.grupo_parcela
            ORDER BY primeira_data DESC
        """, (hoje_str, hoje_str, uid,)).fetchall()

    grupos = []
    for r in rows:
        desc = r["descricao_min"] or ""
        # Extrai nome base removendo " (X/Y)"
        nome = desc.rsplit(" (", 1)[0] if " (" in desc else desc
        total  = r["total"] or 1
        pagas  = r["pagas"] or 0
        futuras = r["futuras"] or 0
        grupos.append({
            "grupo_parcela": r["grupo_parcela"],
            "nome":          nome,
            "tipo":          r["tipo"],
            "pagas":         pagas,   # parcelas com data <= hoje
            "futuras":       futuras, # parcelas com data > hoje
            "total":         total,
            "valor_parcela": round(r["valor_parcela"], 2),
            "valor_total":   round(r["valor_total"], 2),
            "primeira_data": r["primeira_data"],
            "ultima_data":   r["ultima_data"],
            "categoria":     r["categoria_nome"],
            "icone":         r["categoria_icone"],
            "conta_nome":    r["conta_nome"],
            "conta_icone":   r["conta_icone"],
        })

    categorias = svc.categorias_repo.listar_por_usuario(uid)
    return render_template(
        "transacoes/parcelados.html",
        grupos=grupos,
        categorias=categorias,
    )


@transacoes_bp.route("/api/buscar")
@login_required
def api_buscar():
    """
    API de busca full-text nas transações.
    Suporta filtros: termo, conta_id, tipo, data_inicio, data_fim.
    """
    svc = get_services()
    termo      = request.args.get("q", "").strip()
    conta_id   = request.args.get("conta_id", "")
    tipo       = request.args.get("tipo", "")
    data_inicio = request.args.get("inicio", "")
    data_fim    = request.args.get("fim", "")

    resultados = svc.busca_repo.buscar(
        usuario_id=current_user.id,
        termo=termo,
        conta_id=int(conta_id) if conta_id else None,
        tipo=tipo if tipo in ("receita", "despesa") else None,
        data_inicio=data_inicio or None,
        data_fim=data_fim or None,
    )

    total_r = sum(t["valor"] for t in resultados if t["tipo"] == "receita")
    total_d = sum(t["valor"] for t in resultados if t["tipo"] == "despesa")

    return jsonify({
        "transacoes": resultados,
        "total_receitas": total_r,
        "total_despesas": total_d,
        "saldo": total_r - total_d,
        "count": len(resultados),
    })


@transacoes_bp.route("/api/saldo-contas")
@login_required
def api_saldo_contas():
    """Retorna saldo atual de cada conta bancária do usuário."""
    svc = get_services()
    saldos = svc.saldo_conta_repo.saldos_por_conta(current_user.id)
    return jsonify({"saldos": saldos})


@transacoes_bp.route("/api/resumo_sidebar")
@login_required
def api_resumo_sidebar():
    """Retorna últimas 5 transações do mês para o widget da sidebar."""
    svc = get_services()
    hoje = _hoje_brasilia()
    inicio = f"{hoje.year}-{hoje.month:02d}-01"
    fim = hoje.strftime("%Y-%m-%d")

    transacoes = svc.transacoes.listar_por_periodo(inicio, fim, current_user.id)
    ultimas = transacoes[:5]

    return jsonify({
        "transacoes": [
            {
                "descricao":    t["descricao"],
                "valor":        t["valor"],
                "tipo":         t["tipo"],
                "categoria":    t["categoria_nome"],
                "icone":        t["categoria_icone"],
                "data":         t["data"],
            }
            for t in ultimas
        ]
    })


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