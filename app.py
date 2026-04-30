"""
app.py — Fábrica de aplicação Flask.

Por que Application Factory Pattern?
----------------------------------------
No código original, o Flask era instanciado no nível do módulo:
    app = Flask(__name__)

Isso causa problemas sérios:
1. Impossível criar instâncias diferentes para testes
2. Configuração não pode variar entre ambientes na mesma execução
3. Extensões são inicializadas antes da configuração ser carregada

Com `create_app()`:
1. Testes criam apps com banco em memória e configuração de test
2. Produção cria app com PostgreSQL e DEBUG=False
3. Extensões são inicializadas dentro da factory, com configuração correta

Como usar:
    # Desenvolvimento
    FLASK_ENV=development flask run

    # Produção com Gunicorn
    gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
"""

import logging
import os

from flask import Flask, jsonify
from flask_login import LoginManager

from config import get_config
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.helpers import UserPrincipal, get_services, make_user_principal
from routes.transacoes import transacoes_bp
from routes.recorrentes import recorrentes_bp
from services.container import ServiceContainer
from utils.formatters import formatar_real

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(config_class=None, db_path: str | None = None) -> Flask:
    """
    Fábrica de aplicação Flask.

    Args:
        config_class: Classe de configuração (usa get_config() se None)
        db_path: Caminho do banco (útil para testes com banco customizado)

    Returns:
        Flask app configurado e pronto para uso
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )

    # ── Configuração ──────────────────────────────────────────────────────────
    cfg = config_class or get_config()
    app.config.from_object(cfg)
    app.secret_key = cfg.SECRET_KEY
    app.permanent_session_lifetime = cfg.SESSION_LIFETIME

    # ── Container de dependências ─────────────────────────────────────────────
    banco = db_path or _db_path_from_config(cfg)
    container = ServiceContainer(db_path=banco)
    app.extensions["services"] = container

    # ── Flask-Login ───────────────────────────────────────────────────────────
    _configurar_login(app, container)

    # ── Template filters ──────────────────────────────────────────────────────
    app.jinja_env.filters["real"] = formatar_real

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(transacoes_bp)
    app.register_blueprint(recorrentes_bp)

    # ── Handlers de erro ──────────────────────────────────────────────────────
    _registrar_error_handlers(app)

    logger.info("App criado. Ambiente: %s | Banco: %s", os.environ.get("FLASK_ENV", "development"), banco)
    return app


def _db_path_from_config(cfg) -> str:
    """Extrai o path do banco da DATABASE_URL (suporta sqlite e futuro postgres)."""
    url = getattr(cfg, "DATABASE_URL", "sqlite:///financas.db")
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    if url == "sqlite:///:memory:":
        return ":memory:"
    # PostgreSQL e outros: retorna a URL completa
    # (DatabaseManager precisará suporte a SQLAlchemy para isso)
    return url


def _configurar_login(app: Flask, container: ServiceContainer) -> None:
    """Configura Flask-Login com user_loader integrado ao repositório."""
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id: str) -> UserPrincipal | None:
        """
        Recarrega usuário da sessão a cada request.

        Flask-Login chama isso em todo request autenticado.
        Deve ser eficiente — busca por ID é O(1) com índice.
        """
        dados = container.usuarios_repo.buscar_por_id(int(user_id))
        if dados:
            return make_user_principal(dados)
        return None


def _registrar_error_handlers(app: Flask) -> None:
    """
    Handlers centralizados de erro HTTP.

    Por que centralizar?
    ---------------------
    Sem handlers, Flask retorna HTML genérico para erros.
    Handlers personalizados retornam JSON para requisições de API
    e páginas amigáveis para navegador.
    """

    @app.errorhandler(404)
    def nao_encontrado(e):
        if _is_api_request():
            return jsonify({"error": "Recurso não encontrado"}), 404
        return "Página não encontrada", 404

    @app.errorhandler(403)
    def proibido(e):
        if _is_api_request():
            return jsonify({"error": "Acesso negado"}), 403
        return "Acesso negado", 403

    @app.errorhandler(500)
    def erro_interno(e):
        logger.error("Erro interno: %s", e, exc_info=True)
        if _is_api_request():
            return jsonify({"error": "Erro interno do servidor"}), 500
        return "Erro interno do servidor", 500


def _is_api_request() -> bool:
    """Detecta se a request é para a API (espera JSON)."""
    from flask import request
    return request.path.startswith("/api/") or "application/json" in request.headers.get("Accept", "")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    flask_app = create_app()
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    # Em produção: gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
    flask_app.run(host=host, port=port, debug=debug)