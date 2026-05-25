"""
routes/recuperacao.py — Recuperação de senha via email.

Fluxo:
  1. Usuário acessa /recuperar e informa o email
  2. Sistema gera token único e envia email com link
  3. Usuário clica no link (/recuperar/<token>)
  4. Sistema valida token e permite definir nova senha
  5. Token é marcado como usado e expira

Configuração de email:
  - Servidor: smtp.gmail.com:587
  - Remetente: configurado via EMAIL_REMETENTE no .env.secret
  - Senha de app: configurada no .env.secret
"""

import logging
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from werkzeug.security import generate_password_hash

from routes.helpers import get_services

logger = logging.getLogger(__name__)

recuperacao_bp = Blueprint("recuperacao", __name__, url_prefix="/recuperar")

# ── Configuração de email — 100% via variáveis de ambiente ───────────────────
# Configure no .env.secret do servidor:
#   EMAIL_REMETENTE=seu@gmail.com
#   EMAIL_SENHA_APP=xxxx xxxx xxxx xxxx  (senha de app do Google)
import os
EMAIL_REMETENTE    = os.environ.get("EMAIL_REMETENTE", "")
EMAIL_SENHA_APP    = os.environ.get("EMAIL_SENHA_APP", "")
EMAIL_NOME         = "Gravs — Controle Financeiro"
TOKEN_EXPIRA_HORAS = 1


def enviar_email_recuperacao(destinatario: str, nome: str, link: str) -> bool:
    """
    Envia email de recuperação de senha via Gmail SMTP.

    Retorna True se enviado com sucesso, False se falhou.
    """
    # Se email não configurado, loga aviso e retorna False
    if not EMAIL_REMETENTE or not EMAIL_SENHA_APP:
        logger.warning("Email de recuperação não configurado. Defina EMAIL_REMETENTE e EMAIL_SENHA_APP no .env.secret")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🔒 Recuperação de senha — Gravs"
        msg["From"]    = f"{EMAIL_NOME} <{EMAIL_REMETENTE}>"
        msg["To"]      = destinatario

        html = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head><meta charset="UTF-8"></head>
        <body style="font-family:'DM Sans',Arial,sans-serif;background:#0d0618;
                     color:#f1eeff;margin:0;padding:32px 16px">
          <div style="max-width:480px;margin:0 auto;
                      background:#130a24;border-radius:16px;
                      border:1px solid rgba(255,255,255,0.1);
                      padding:40px 32px">

            <!-- Logo -->
            <div style="text-align:center;margin-bottom:28px">
              <div style="font-size:2rem">🌀</div>
              <div style="font-family:Arial;font-size:1.4rem;font-weight:800;
                          color:#9f5fff;letter-spacing:-0.5px">Gravs</div>
            </div>

            <h1 style="font-size:1.2rem;font-weight:700;margin:0 0 8px;color:#f1eeff">
              Recuperação de senha
            </h1>
            <p style="color:#a89bc2;font-size:0.9rem;line-height:1.6;margin:0 0 24px">
              Olá, <strong style="color:#f1eeff">{nome}</strong>!<br>
              Recebemos uma solicitação para redefinir a senha da sua conta no Gravs.
            </p>

            <!-- Botão -->
            <div style="text-align:center;margin:28px 0">
              <a href="{link}"
                 style="display:inline-block;padding:14px 32px;
                        background:linear-gradient(135deg,#7c3aed,#9f5fff);
                        color:white;text-decoration:none;border-radius:10px;
                        font-weight:700;font-size:1rem;
                        box-shadow:0 4px 16px rgba(124,58,237,0.4)">
                🔒 Redefinir minha senha
              </a>
            </div>

            <p style="color:#6b5f82;font-size:0.78rem;line-height:1.6;margin:24px 0 0">
              Este link expira em <strong>1 hora</strong>.<br>
              Se você não solicitou a recuperação de senha, ignore este email.
              Sua senha não será alterada.
            </p>

            <hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:24px 0">
            <p style="color:#6b5f82;font-size:0.72rem;text-align:center;margin:0">
              Gravs — Controle Financeiro Pessoal
            </p>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_REMETENTE, EMAIL_SENHA_APP)
            smtp.sendmail(EMAIL_REMETENTE, destinatario, msg.as_string())

        logger.info("Email de recuperação enviado para %s", destinatario)
        return True

    except Exception as exc:
        logger.error("Erro ao enviar email de recuperação: %s", exc)
        return False


# ── Rotas ──────────────────────────────────────────────────────────────────────

@recuperacao_bp.route("/", methods=["GET", "POST"])
def solicitar():
    """
    Exibe formulário de recuperação e processa a solicitação.
    Sempre mostra mensagem genérica para não revelar emails cadastrados.
    """
    if request.method == "GET":
        return render_template("recuperacao/solicitar.html")

    email = request.form.get("email", "").strip().lower()

    if not email:
        flash("Informe seu email.", "erro")
        return render_template("recuperacao/solicitar.html")

    svc = get_services()

    # Busca usuário — mas não revela se existe ou não
    usuario = svc.usuarios_repo.buscar_por_email(email)

    if usuario:
        # Gera token seguro único
        token = secrets.token_urlsafe(32)
        expira = (datetime.now() + timedelta(hours=TOKEN_EXPIRA_HORAS)).strftime("%Y-%m-%d %H:%M:%S")

        # Salva token no banco
        with svc.db.get_write_conn() as conn:
            # Remove tokens antigos do mesmo usuário
            conn.execute(
                "DELETE FROM tokens_recuperacao WHERE usuario_id = ?",
                (usuario["id"],)
            )
            conn.execute(
                "INSERT INTO tokens_recuperacao (usuario_id, token, expira_em) VALUES (?, ?, ?)",
                (usuario["id"], token, expira)
            )

        # Monta link e envia email
        link = url_for("recuperacao.redefinir", token=token, _external=True)
        enviar_email_recuperacao(usuario["email"], usuario["nome"], link)

    # Sempre mostra a mesma mensagem (segurança)
    flash("Se esse email estiver cadastrado, você receberá as instruções em breve.", "sucesso")
    return redirect(url_for("recuperacao.solicitar"))


@recuperacao_bp.route("/<token>", methods=["GET", "POST"])
def redefinir(token: str):
    """Valida token e permite redefinir a senha."""
    svc = get_services()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Busca token válido
    with svc.db.get_conn() as conn:
        row = conn.execute("""
            SELECT t.id, t.usuario_id, t.expira_em, u.nome, u.email
            FROM tokens_recuperacao t
            JOIN usuarios u ON t.usuario_id = u.id
            WHERE t.token = ? AND t.usado = 0 AND t.expira_em > ?
        """, (token, agora)).fetchone()

    if not row:
        flash("Link inválido ou expirado. Solicite um novo.", "erro")
        return redirect(url_for("recuperacao.solicitar"))

    if request.method == "GET":
        return render_template("recuperacao/redefinir.html",
                               token=token, nome=row["nome"])

    # POST — processa nova senha
    nova_senha  = request.form.get("nova_senha", "")
    confirmacao = request.form.get("confirmacao", "")

    if len(nova_senha) < 6:
        flash("A senha deve ter pelo menos 6 caracteres.", "erro")
        return render_template("recuperacao/redefinir.html",
                               token=token, nome=row["nome"])

    if nova_senha != confirmacao:
        flash("As senhas não coincidem.", "erro")
        return render_template("recuperacao/redefinir.html",
                               token=token, nome=row["nome"])

    # Atualiza senha e marca token como usado
    novo_hash = generate_password_hash(nova_senha)
    with svc.db.get_write_conn() as conn:
        conn.execute(
            "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
            (novo_hash, row["usuario_id"])
        )
        conn.execute(
            "UPDATE tokens_recuperacao SET usado = 1 WHERE token = ?",
            (token,)
        )

    logger.info("Senha redefinida para user_id=%s", row["usuario_id"])
    flash("✓ Senha redefinida com sucesso! Faça login.", "sucesso")
    return redirect(url_for("auth.login"))
