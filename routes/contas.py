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
    """
    Cria conta bancária e registra saldo inicial como transação.

    O saldo inicial é opcional. Se informado, cria uma receita
    vinculada à conta na data de hoje, categorizando como "Outros".
    Assim o saldo aparece corretamente no dashboard desde o início.
    """
    from datetime import date
    svc = get_services()
    nome          = request.form.get("nome", "").strip()
    tipo          = request.form.get("tipo", "conta")
    saldo_inicial = request.form.get("saldo_inicial", "").strip().replace(",", ".")

    conta_id, erro = svc.contas_repo.adicionar(nome, tipo, current_user.id)
    if erro:
        flash(erro, "erro")
        return redirect(url_for("contas.lista"))

    # Registrar saldo inicial como transação de receita
    if saldo_inicial:
        try:
            valor = float(saldo_inicial)
            if valor > 0:
                # Buscar categoria "Outros" ou a primeira disponível
                cats = svc.categorias_repo.listar_por_usuario(current_user.id)
                cat = next(
                    (c for c in cats if "outros" in c["nome"].lower() and c["tipo"] == "receita"),
                    cats[0] if cats else None
                )
                if cat:
                    svc.transacoes.adicionar(
                        descricao=f"Saldo inicial — {nome}",
                        valor=valor,
                        tipo="receita",
                        categoria_id=cat["id"],
                        usuario_id=current_user.id,
                        data=date.today().strftime("%Y-%m-%d"),
                        conta_id=conta_id,
                    )
                    flash(f"✓ Conta '{nome}' cadastrada com saldo inicial de R$ {valor:,.2f}!", "sucesso")
                else:
                    flash(f"✓ Conta '{nome}' cadastrada! Saldo inicial não registrado (sem categorias).", "sucesso")
            else:
                flash(f"✓ Conta '{nome}' cadastrada!", "sucesso")
        except ValueError:
            flash(f"✓ Conta '{nome}' cadastrada! Saldo inicial inválido — ignorado.", "sucesso")
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
