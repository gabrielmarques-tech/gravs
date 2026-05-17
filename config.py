"""
config.py — Configurações centralizadas do Gravs.

Por que este arquivo existe?
------------------------------
Configurar o sistema via variáveis de ambiente (12-Factor App) é a prática
correta para qualquer sistema que vai a produção. Sem isso, você hardcoda
segredos no código, quebra deploys em ambientes diferentes, e precisa editar
código só para trocar uma URL de banco.

Três ambientes bem separados: Development, Testing, Production.
Cada um herda de Config e sobrescreve o que precisa.

Por que não usar .env direto em app.py?
---------------------------------------
Porque mistura configuração com código de aplicação. Aqui temos um único
ponto de verdade para todas as configurações. app.py só importa `get_config()`.
"""

import os
from datetime import timedelta


class Config:
    """Configurações base compartilhadas por todos os ambientes."""

    # ── Segurança ─────────────────────────────────────────────────────────────
    # NUNCA deixe sem definir em produção. Sessões serão invalidadas no restart.
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-insecure-key-TROQUE-em-producao")
    SESSION_LIFETIME: timedelta = timedelta(days=30)

    # ── Banco de dados ────────────────────────────────────────────────────────
    # SQLite por padrão (dev/test). Em produção, substitua pela URL do Postgres.
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///financas.db")

    # ── Servidor ──────────────────────────────────────────────────────────────
    HOST: str = os.environ.get("FLASK_HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("FLASK_PORT", "5000"))
    DEBUG: bool = False

    # ── Login ─────────────────────────────────────────────────────────────────
    LOGIN_VIEW: str = "auth.login"
    LOGIN_MESSAGE: str = "Faça login para acessar"

    # ── Limites de negócio ────────────────────────────────────────────────────
    MAX_PARCELAS: int = 420
    MIN_PARCELAS: int = 2
    MIN_SENHA_LEN: int = 6


class DevelopmentConfig(Config):
    """Ambiente local. Debug ativo, banco SQLite simples."""
    DEBUG = True
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///financas_dev.db")


class TestingConfig(Config):
    """
    Ambiente de testes automatizados.

    Por que banco em memória?
    --------------------------
    Testes devem ser isolados, rápidos e não deixar estado no disco.
    O SQLite :memory: é criado e destruído em cada sessão de testes,
    garantindo que cada teste comece com um estado limpo.
    """
    TESTING = True
    DATABASE_URL = "sqlite:///:memory:"
    # Desativa CSRF e proteções que complicam testes de integração
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """
    Produção (PythonAnywhere, Railway, etc).

    Por que exigir SECRET_KEY do ambiente?
    ----------------------------------------
    Em produção, segredos jamais devem estar no código-fonte (repositório).
    Se SECRET_KEY não estiver definida, levantamos erro imediatamente,
    em vez de silenciosamente usar uma chave fraca.
    """
    DEBUG = False

    # ── Segurança de cookies ──────────────────────────────────────────────────
    # SESSION_COOKIE_SECURE: cookie só enviado em HTTPS — evita interceptação
    SESSION_COOKIE_SECURE   = True
    # SESSION_COOKIE_HTTPONLY: JavaScript não consegue ler o cookie — evita XSS
    SESSION_COOKIE_HTTPONLY = True
    # SESSION_COOKIE_SAMESITE: cookie só enviado em requests do mesmo site — evita CSRF
    SESSION_COOKIE_SAMESITE = "Lax"

    @classmethod
    def validate(cls) -> None:
        """Levanta erro se variáveis críticas estiverem ausentes."""
        if cls.SECRET_KEY == "dev-insecure-key-TROQUE-em-producao":
            raise EnvironmentError(
                "SECRET_KEY não definida. Defina a variável de ambiente SECRET_KEY."
            )
        if "sqlite" in cls.DATABASE_URL and ":memory:" not in cls.DATABASE_URL:
            import logging
            logging.getLogger(__name__).warning(
                "Usando SQLite em produção. Considere PostgreSQL para maior robustez."
            )


# Mapeamento de nome de ambiente → classe de configuração
_ENV_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config() -> type[Config]:
    """
    Retorna a classe de configuração correta para o ambiente atual.

    Uso:
        from config import get_config
        app.config.from_object(get_config())
    """
    env = os.environ.get("FLASK_ENV", "development").lower()
    cfg = _ENV_MAP.get(env, DevelopmentConfig)
    if env == "production":
        cfg.validate()
    return cfg