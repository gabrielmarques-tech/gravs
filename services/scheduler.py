"""
services/scheduler.py — Tarefas agendadas do Gravs.

Usa APScheduler para rodar tarefas dentro do Flask sem servidor separado.
Tarefa principal: envio do resumo mensal no dia 28 de cada mês.
"""

import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = None

def _carregar_env_secret() -> None:
    """Carrega o .env.secret se as variáveis ainda não estiverem definidas."""
    import os
    if os.environ.get("EMAIL_REMETENTE"):
        return  # já carregado

    # Procura o .env.secret na raiz do projeto
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    secret_path = os.path.join(base, ".env.secret")

    if not os.path.exists(secret_path):
        return

    with open(secret_path, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            if "=" in linha:
                chave, _, valor = linha.partition("=")
                os.environ.setdefault(chave.strip(), valor.strip())



def iniciar_scheduler(app) -> None:
    """
    Inicia o scheduler e registra as tarefas.
    Deve ser chamado uma única vez no create_app().
    """
    global _scheduler

    if _scheduler is not None:
        return  # já iniciado

    _scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")

    # Roda todo dia 28 às 09:00 (horário de Brasília)
    _scheduler.add_job(
        func=lambda: _enviar_resumos_mensais(app),
        trigger=CronTrigger(day=28, hour=9, minute=0),
        id="resumo_mensal",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler iniciado — resumo mensal agendado para dia 28 às 09:00")


def _enviar_resumos_mensais(app) -> None:
    """
    Busca todos os usuários ativos e envia o resumo mensal para cada um.
    Roda dentro do contexto da aplicação Flask.
    """
    with app.app_context():
        try:
            from services.container import ServiceContainer
            from services.email_service import enviar_resumo_mensal

            import os

            # Garante que o .env.secret está carregado
            _carregar_env_secret()

            remetente = os.environ.get("EMAIL_REMETENTE", "")
            senha_app = os.environ.get("EMAIL_SENHA_APP", "")

            if not remetente or not senha_app:
                logger.warning("Email não configurado — resumo mensal não enviado")
                return

            # Pega o container do app ou cria um novo
            container = getattr(app, 'container', None)
            if container is None:
                from services.container import ServiceContainer
                import os
                db_url = os.environ.get("DATABASE_URL", "sqlite:///financas_dev.db")
                db_path = db_url.replace("sqlite:///", "").replace("sqlite:////", "/")
                container = ServiceContainer(db_path=db_path)
            hoje = date.today()
            ano  = hoje.year
            mes  = hoje.month

            meses_pt = [
                "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
            ]
            mes_nome = meses_pt[mes]

            # Calcula dias restantes no mês
            import calendar
            ultimo_dia = calendar.monthrange(ano, mes)[1]
            dias_restantes = ultimo_dia - hoje.day

            # Busca todos os usuários ativos
            with container.db.get_conn() as conn:
                usuarios = conn.execute(
                    "SELECT id, email, nome FROM usuarios WHERE ativo = 1"
                ).fetchall()

            enviados = 0
            for u in usuarios:
                try:
                    uid   = u["id"]
                    email = u["email"]
                    nome  = u["nome"]

                    # Busca resumo do mês atual
                    inicio = f"{ano}-{mes:02d}-01"
                    fim    = f"{ano}-{mes:02d}-{ultimo_dia:02d}"

                    resultados = container.busca_repo.buscar(
                        usuario_id=uid,
                        data_inicio=inicio,
                        data_fim=fim,
                    )

                    receitas  = sum(t["valor"] for t in resultados if t["tipo"] == "receita")
                    despesas  = sum(t["valor"] for t in resultados if t["tipo"] == "despesa")
                    saldo     = receitas - despesas

                    # Top categorias
                    cats = {}
                    for t in resultados:
                        if t["tipo"] == "despesa":
                            nome_cat = t.get("categoria_nome", "Outros")
                            cats[nome_cat] = cats.get(nome_cat, 0) + t["valor"]

                    gastos_por_categoria = [
                        {"nome": k, "total": v}
                        for k, v in sorted(cats.items(), key=lambda x: -x[1])
                    ]

                    resumo = {
                        "mes_nome":             mes_nome,
                        "ano":                  ano,
                        "receitas":             receitas,
                        "despesas":             despesas,
                        "saldo":                saldo,
                        "dias_restantes":       dias_restantes,
                        "gastos_por_categoria": gastos_por_categoria,
                    }

                    ok = enviar_resumo_mensal(remetente, senha_app, email, nome, resumo)
                    if ok:
                        enviados += 1

                except Exception as exc:
                    logger.error("Erro ao enviar resumo para user %d: %s", u["id"], exc)

            logger.info("Resumo mensal enviado para %d/%d usuários", enviados, len(usuarios))

        except Exception as exc:
            logger.error("Erro geral no envio de resumos: %s", exc)


def disparar_teste(app) -> None:
    """
    Dispara o envio imediatamente para testar sem esperar o dia 28.
    Use no console: from services.scheduler import disparar_teste
    """
    logger.info("Disparo manual do resumo mensal para teste")
    _enviar_resumos_mensais(app)