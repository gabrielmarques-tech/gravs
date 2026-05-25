"""
routes/publico.py — Páginas públicas (termos, privacidade).
Acessíveis sem login.
"""
from flask import Blueprint, render_template

publico_bp = Blueprint("publico", __name__)


@publico_bp.route("/termos")
def termos():
    return render_template("publico/termos.html")


@publico_bp.route("/privacidade")
def privacidade():
    return render_template("publico/privacidade.html")
