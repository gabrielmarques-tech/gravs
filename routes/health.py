"""routes/health.py — Health Check endpoints para monitoramento.

Endpoints:
    GET /health        → status geral do serviço (lightweight)
    GET /health/db     → status da conexão com o banco de dados
"""

import logging
import time

from flask import Blueprint, jsonify

from routes.helpers import get_services

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__, url_prefix="/health")


@health_bp.route("", methods=["GET"])
def health():
    """
    Health check básico do serviço.

    Retorna status 200 com informações do serviço assim que a aplicação
    estiver rodando. Não faz consultas ao banco — leve e rápido.

    Uso: monitores (Kubernetes liveness probe, Load Balancer, uptime robot)
    """
    return jsonify({
        "status": "ok",
        "timestamp": time.time(),
        "app": "gravs-financas",
        "version": "1.0.0",
    }), 200


@health_bp.route("/db", methods=["GET"])
def health_db():
    """
    Health check do banco de dados.

    Executa uma consulta simples (SELECT 1) para verificar se a conexão
    com o banco está funcional.

    Retorna:
        200 com status "ok" se o banco responde
        503 com status "error" se a consulta falhar
    """
    services = None
    db = None

    try:
        services = get_services()
        db = services.db
    except Exception as exc:
        logger.error("Erro ao acessar serviços: %s", exc, exc_info=True)
        return jsonify({
            "status": "error",
            "detail": "servicos_indisponiveis",
            "error": str(exc),
            "timestamp": time.time(),
        }), 503

    inicio = time.perf_counter()
    try:
        with db.get_conn(operacao="health_check") as conn:
            conn.execute("SELECT 1").fetchone()
        duracao = time.perf_counter() - inicio

        return jsonify({
            "status": "ok",
            "detail": "conexao_ok",
            "database": db.db_path,
            "response_time_ms": round(duracao * 1000, 2),
            "timestamp": time.time(),
        }), 200

    except Exception as exc:
        duracao = time.perf_counter() - inicio
        logger.error("Health check DB falhou após %.1fms: %s", duracao * 1000, exc, exc_info=True)

        return jsonify({
            "status": "error",
            "detail": "conexao_falhou",
            "error": str(exc),
            "response_time_ms": round(duracao * 1000, 2),
            "timestamp": time.time(),
        }), 503