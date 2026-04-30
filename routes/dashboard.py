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

from datetime import datetime

from flask import render_template
from flask_login import current_user, login_required

from routes.helpers import get_services

from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    hoje = datetime.now()
    ano, mes = hoje.year, hoje.month
    uid = current_user.id

    svc = get_services()

    # Gera lançamentos de recorrentes pendentes (idempotente)
    svc.recorrentes.gerar_lancamentos_pendentes(ano, mes, uid)

    resumo = svc.dashboard.obter_resumo(ano, mes, uid)
    categorias = svc.categorias_repo.listar_por_usuario(uid)

    return render_template(
        "dashboard/index.html",
        resumo=resumo,
        categorias=categorias,
        usuario=current_user,
    )