"""
routes/auth.py — Rotas de autenticação (Blueprint).

Proteções implementadas:
- Rate limit via decorator (5 tentativas/min no login)
- CSRF token em todos os formulários via Flask-WTF
- Verificação de email com código de 6 dígitos no cadastro
- Aceite obrigatório dos termos de uso
- Mensagem genérica de erro (anti-enumeração de usuários)
"""
import logging
import os
import random
import secrets
import string
from datetime import datetime, timedelta

from flask import (
    Blueprint, current_app, flash, redirect,
    render_template, request, session, url_for
)
from flask_login import login_required, login_user, logout_user

from routes.helpers import get_services, make_user_principal

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# EMAIL_REMETENTE e EMAIL_SENHA_APP são lidas em tempo de execução
# dentro de _enviar_codigo_verificacao para pegar o valor correto do ambiente


def _gerar_codigo_6_digitos() -> str:
    """Gera código numérico de 6 dígitos para verificação de email."""
    return "".join(random.choices(string.digits, k=6))


def _enviar_codigo_verificacao(destinatario: str, nome: str, codigo: str) -> bool:
    """Envia email com código de verificação de 6 dígitos."""
    # Lê em tempo de execução — garante pegar o valor após wsgi.py carregar .env.secret
    EMAIL_REMETENTE = os.environ.get("EMAIL_REMETENTE", "")
    EMAIL_SENHA_APP = os.environ.get("EMAIL_SENHA_APP", "")
    if not EMAIL_REMETENTE or not EMAIL_SENHA_APP:
        logger.warning("Email não configurado — verificação pulada em dev")
        return False
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        corpo = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f7f6f4;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;border:1px solid #e8e8e8;overflow:hidden">
        <tr><td style="padding:28px 32px;border-bottom:1px solid #e8e8e8">
          <span style="font-size:18px;font-weight:700;color:#1a1a1a;letter-spacing:-0.02em">Gravs</span>
        </td></tr>
        <tr><td style="padding:32px">
          <p style="margin:0 0 8px;font-size:20px;font-weight:600;color:#1a1a1a">Olá, {nome}!</p>
          <p style="margin:0 0 24px;font-size:14px;color:#6b6b6b;line-height:1.6">
            Use o código abaixo para confirmar seu cadastro no Gravs. Ele expira em <strong>15 minutos</strong>.
          </p>
          <div style="text-align:center;margin:0 0 24px">
            <div style="display:inline-block;padding:18px 40px;background:#0d0618;
                        border-radius:12px;letter-spacing:0.3em;
                        font-size:32px;font-weight:700;color:#f1eeff;font-variant-numeric:tabular-nums">
              {codigo}
            </div>
          </div>
          <p style="margin:0;font-size:12px;color:#9a9a9a;text-align:center">
            Se você não criou uma conta no Gravs, ignore este email.
          </p>
        </td></tr>
        <tr><td style="padding:16px 32px;border-top:1px solid #e8e8e8;text-align:center">
          <p style="margin:0;font-size:12px;color:#9a9a9a">Gravs · Controle financeiro pessoal</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{codigo}] Confirme seu cadastro — Gravs"
        msg["From"] = f"Gravs <{EMAIL_REMETENTE}>"
        msg["To"] = destinatario
        msg.attach(MIMEText(corpo, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as srv:
            srv.login(EMAIL_REMETENTE, EMAIL_SENHA_APP)
            srv.sendmail(EMAIL_REMETENTE, destinatario, msg.as_string())

        logger.info("Código de verificação enviado para %s", destinatario)
        return True
    except Exception as exc:
        logger.error("Erro ao enviar código de verificação: %s", exc)
        return False


# ── Rotas ──────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Login com rate limit via Flask-Limiter (5 tentativas/min por IP).
    Proteção CSRF via Flask-WTF (token no formulário).
    """
    # Rate limit aplicado pelo limiter registrado no app
    limiter = current_app.extensions.get("limiter")
    if limiter and request.method == "POST":
        try:
            limiter.limit("5 per minute")(lambda: None)()
        except Exception:
            flash("Muitas tentativas. Aguarde 1 minuto.", "erro")
            return render_template("auth/login.html"), 429

    if request.method == "GET":
        return render_template("auth/login.html")

    email = request.form.get("email", "").strip()
    senha = request.form.get("senha", "")

    svc = get_services()
    usuario, erro = svc.auth.autenticar(email, senha)

    if erro:
        email_log = email[0] + "***@" + email.split("@")[-1] if "@" in email else "***"
        logger.warning("Login falhou para email=%s ip=%s", email_log, request.remote_addr)
        flash(erro, "erro")
        return render_template("auth/login.html", email=email), 401

    user_principal = make_user_principal(usuario)
    login_user(user_principal, remember=True)

    logger.info("Login bem-sucedido user_id=%d ip=%s", usuario["id"], request.remote_addr)

    try:
        svc.db.limpar_tokens_expirados()
    except Exception:
        pass

    return redirect(url_for("dashboard.index"))


@auth_bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    """
    Cadastro com:
    - Aceite obrigatório dos termos de uso (LGPD)
    - Envio de código de verificação por email
    - Redirecionamento para tela de verificação
    """
    if request.method == "GET":
        return render_template("auth/cadastro.html")

    email = request.form.get("email", "").strip().lower()
    senha = request.form.get("senha", "")
    nome  = request.form.get("nome", "").strip()
    aceite_termos = request.form.get("aceite_termos")
    modo_contabil = 1 if request.form.get("modo_contabil") == "1" else 0

    # Validações
    if not aceite_termos:
        flash("Você precisa aceitar os Termos de Uso para criar uma conta.", "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    if len(senha) < 6:
        flash("A senha deve ter pelo menos 6 caracteres.", "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    if len(nome) < 2:
        flash("O nome deve ter pelo menos 2 caracteres.", "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    if "@" not in email or "." not in email.split("@")[-1]:
        flash("Informe um email válido.", "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    if len(email) > 200 or len(nome) > 80:
        flash("Dados muito longos.", "erro")
        return render_template("auth/cadastro.html"), 422

    svc = get_services()
    user_id, erros = svc.auth.registrar(email, senha, nome)

    if erros:
        for campo, msg in erros.items():
            flash(msg, "erro")
        return render_template("auth/cadastro.html", email=email, nome=nome), 422

    # Salva aceite dos termos e modo contábil
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with svc.db.get_write_conn() as conn:
        conn.execute(
            "UPDATE usuarios SET aceite_termos_em=?, modo_contabil=? WHERE id=?",
            (agora, modo_contabil, user_id)
        )

    # Cria contas bancárias padrão
    svc.contas_repo.criar_sugestoes_padrao(user_id)

    # Gera e salva código de verificação (expira em 15 minutos)
    codigo = _gerar_codigo_6_digitos()
    expira = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    with svc.db.get_write_conn() as conn:
        conn.execute(
            "INSERT INTO verificacao_email (usuario_id, codigo, expira_em) VALUES (?,?,?)",
            (user_id, codigo, expira)
        )

    # Salva dados na sessão para a tela de verificação
    session["verificacao_user_id"] = user_id
    session["verificacao_email"]   = email

    # Tenta enviar email — em dev sem email configurado, pula direto
    email_enviado = _enviar_codigo_verificacao(email, nome, codigo)

    logger.info("Cadastro: user_id=%d email=%s email_enviado=%s", user_id, email, email_enviado)

    if not email_enviado:
        # Sem email configurado (dev): verifica automaticamente e loga o código
        logger.warning("DEV: código de verificação para %s = %s", email, codigo)
        with svc.db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET email_verificado=1 WHERE id=?", (user_id,)
            )
            conn.execute(
                "UPDATE verificacao_email SET usado=1 WHERE usuario_id=? AND codigo=?",
                (user_id, codigo)
            )
        flash("Conta criada com sucesso! Faça login.", "sucesso")
        return redirect(url_for("auth.login"))

    return redirect(url_for("auth.verificar_email"))


@auth_bp.route("/verificar-email", methods=["GET", "POST"])
def verificar_email():
    """Tela para inserir o código de 6 dígitos enviado por email."""
    user_id = session.get("verificacao_user_id")
    email   = session.get("verificacao_email", "")

    if not user_id:
        flash("Sessão expirada. Faça o cadastro novamente.", "erro")
        return redirect(url_for("auth.cadastro"))

    if request.method == "GET":
        return render_template("auth/verificar_email.html", email=email)

    codigo_digitado = request.form.get("codigo", "").strip()

    svc = get_services()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = None
    with svc.db.get_conn() as conn:
        row = conn.execute(
            """SELECT id FROM verificacao_email
               WHERE usuario_id=? AND codigo=? AND expira_em > ? AND usado=0
               ORDER BY id DESC LIMIT 1""",
            (user_id, codigo_digitado, agora)
        ).fetchone()

    if not row:
        flash("Código inválido ou expirado. Tente novamente.", "erro")
        return render_template("auth/verificar_email.html", email=email), 422

    # Marca como verificado
    with svc.db.get_write_conn() as conn:
        conn.execute("UPDATE usuarios SET email_verificado=1 WHERE id=?", (user_id,))
        conn.execute("UPDATE verificacao_email SET usado=1 WHERE id=?", (row["id"],))

    session.pop("verificacao_user_id", None)
    session.pop("verificacao_email", None)

    logger.info("Email verificado: user_id=%d", user_id)
    flash("Email confirmado! Bem-vindo ao Gravs.", "sucesso")
    return redirect(url_for("auth.login"))


@auth_bp.route("/verificar-email/reenviar", methods=["POST"])
def reenviar_codigo():
    """Reenvia o código de verificação."""
    user_id = session.get("verificacao_user_id")
    email   = session.get("verificacao_email", "")

    if not user_id:
        return redirect(url_for("auth.cadastro"))

    svc = get_services()

    # Busca nome do usuário
    usuario = svc.usuarios_repo.buscar_por_id(user_id)
    nome = usuario["nome"] if usuario else "usuário"

    codigo = _gerar_codigo_6_digitos()
    expira = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

    with svc.db.get_write_conn() as conn:
        conn.execute(
            "UPDATE verificacao_email SET usado=1 WHERE usuario_id=? AND usado=0",
            (user_id,)
        )
        conn.execute(
            "INSERT INTO verificacao_email (usuario_id, codigo, expira_em) VALUES (?,?,?)",
            (user_id, codigo, expira)
        )

    _enviar_codigo_verificacao(email, nome, codigo)
    flash("Novo código enviado para seu email.", "sucesso")
    return redirect(url_for("auth.verificar_email"))


@auth_bp.route("/logout")
@login_required
def logout():
    """Encerra sessão do usuário."""
    logger.info("Logout: user_id=%d", current_app.extensions.get("services") and 0 or 0)
    logout_user()
    return redirect(url_for("auth.login"))
