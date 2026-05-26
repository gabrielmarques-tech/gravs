"""
routes/dashboard.py — Dashboard principal.

A route do dashboard agora é trivialmente simples:
1. Pega ano/mês atuais
2. Chama RecorrenteService para gerar pendentes
3. Chama DashboardService para obter resumo
4. Renderiza template

Toda a lógica de negócio (insight, comparação com mês anterior)
está no DashboardService, não aqui.
"""

from datetime import datetime, timezone, timedelta

from flask import render_template, jsonify, request
from flask_login import current_user, login_required

from routes.helpers import get_services

from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)

# Fuso horário de Brasília (UTC-3)
_BRASILIA = timezone(timedelta(hours=-3))


@dashboard_bp.route("/")
@login_required
def index():
    # Usa fuso de Brasília para evitar erro de mês no PythonAnywhere (UTC)
    hoje = datetime.now(_BRASILIA)
    ano, mes = hoje.year, hoje.month
    uid = current_user.id

    svc = get_services()

    # Gera lançamentos de recorrentes pendentes (idempotente)
    svc.recorrentes.gerar_lancamentos_pendentes(ano, mes, uid)

    resumo = svc.dashboard.obter_resumo(ano, mes, uid)
    categorias = svc.categorias_repo.listar_por_usuario(uid)

    usuario_dados = svc.usuarios_repo.buscar_por_id(uid)
    onboarding_completo = bool(usuario_dados.get("onboarding_completo", 0)) if usuario_dados else True
    limites = {l["categoria_id"]: l["limite"] for l in svc.limites_repo.listar(uid)}

    return render_template(
        "dashboard/index.html",
        resumo=resumo,
        categorias=categorias,
        usuario=current_user,
        onboarding_completo=onboarding_completo,
        limites=limites,
    )

@dashboard_bp.route("/api/limites", methods=["GET"])
@login_required
def api_limites_listar():
    """Retorna todos os limites de categoria do usuário."""
    svc = get_services()
    limites = svc.limites_repo.listar(current_user.id)
    return jsonify({"limites": limites})


@dashboard_bp.route("/api/limites", methods=["POST"])
@login_required
def api_limites_salvar():
    """Salva ou atualiza limite de uma categoria."""
    from flask import request
    dados = request.get_json()
    categoria_id = dados.get("categoria_id")
    limite = dados.get("limite")

    if not categoria_id or not limite:
        return jsonify({"success": False, "erro": "Dados inválidos"}), 400

    try:
        limite = float(str(limite).replace(",", "."))
        if limite <= 0:
            return jsonify({"success": False, "erro": "Limite deve ser maior que zero"}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "erro": "Valor inválido"}), 400

    svc = get_services()
    svc.limites_repo.salvar(current_user.id, int(categoria_id), limite)
    return jsonify({"success": True})


@dashboard_bp.route("/api/limites/<int:categoria_id>", methods=["DELETE"])
@login_required
def api_limites_remover(categoria_id: int):
    """Remove o limite de uma categoria."""
    svc = get_services()
    svc.limites_repo.remover(current_user.id, categoria_id)
    return jsonify({"success": True})


@dashboard_bp.route("/api/onboarding/completo", methods=["POST"])
@login_required
def api_onboarding_completo():
    """Marca onboarding como completo para o usuário."""
    svc = get_services()
    svc.usuarios_repo.marcar_onboarding_completo(current_user.id)
    return jsonify({"success": True})