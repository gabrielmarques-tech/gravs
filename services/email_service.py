"""
services/email_service.py — Envio de emails do Gravs.

Responsabilidades:
- Envio de email de recuperação de senha (já existia, centralizado aqui)
- Envio do resumo mensal no dia 28 de cada mês
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _enviar_email(remetente: str, senha_app: str, destinatario: str,
                  assunto: str, corpo_html: str) -> bool:
    """Envia um email via Gmail SMTP. Retorna True se enviou com sucesso."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"]    = f"Gravs <{remetente}>"
        msg["To"]      = destinatario
        msg.attach(MIMEText(corpo_html, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as srv:
            srv.login(remetente, senha_app)
            srv.sendmail(remetente, destinatario, msg.as_string())

        logger.info("Email enviado para %s — %s", destinatario, assunto)
        return True

    except Exception as exc:
        logger.error("Erro ao enviar email para %s: %s", destinatario, exc)
        return False


def enviar_resumo_mensal(remetente: str, senha_app: str,
                          destinatario: str, nome: str,
                          resumo: dict) -> bool:
    """
    Envia o resumo mensal do dia 28.

    resumo deve conter:
        mes_nome, ano, receitas, despesas, saldo,
        dias_restantes, gastos_por_categoria
    """
    receitas  = resumo.get("receitas", 0)
    despesas  = resumo.get("despesas", 0)
    saldo     = resumo.get("saldo", 0)
    mes_nome  = resumo.get("mes_nome", "")
    ano       = resumo.get("ano", "")
    dias      = resumo.get("dias_restantes", 3)
    cats      = resumo.get("gastos_por_categoria", [])

    def fmt(v):
        return f"R$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    cor_saldo = "#16a34a" if saldo >= 0 else "#dc2626"
    emoji_saldo = "📈" if saldo >= 0 else "📉"

    # Linhas de categorias
    cats_html = ""
    for c in cats[:5]:
        pct = round(c["total"] / despesas * 100, 1) if despesas > 0 else 0
        cats_html += f"""
        <tr>
          <td style="padding:6px 0;color:#6b7280;font-size:14px">{c.get('nome','')}</td>
          <td style="padding:6px 0;text-align:right;font-weight:600;font-size:14px;color:#1a1a1a">{fmt(c['total'])}</td>
          <td style="padding:6px 0;text-align:right;color:#9a9a9a;font-size:13px">{pct}%</td>
        </tr>"""

    corpo = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f7f6f4;font-family:'Inter',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;border:1px solid #e8e8e8;overflow:hidden">

        <!-- Header -->
        <tr>
          <td style="padding:28px 32px;border-bottom:1px solid #e8e8e8">
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-right:10px">
                  <img src="https://gravs.pythonanywhere.com/static/icon-192.png"
                       width="32" height="32" alt="Gravs"
                       style="border-radius:8px;display:block"/>
                </td>
                <td style="font-size:18px;font-weight:600;color:#1a1a1a;letter-spacing:-0.02em">Gravs</td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Saudação -->
        <tr>
          <td style="padding:28px 32px 0">
            <p style="margin:0 0 6px;font-size:22px;font-weight:600;color:#1a1a1a;letter-spacing:-0.02em">
              Olá, {nome}! {emoji_saldo}
            </p>
            <p style="margin:0;font-size:14px;color:#6b6b6b;line-height:1.6">
              Faltam <strong>{dias} dias</strong> para fechar {mes_nome} de {ano}.
              Aqui está como você está indo este mês.
            </p>
          </td>
        </tr>

        <!-- Cards de resumo -->
        <tr>
          <td style="padding:20px 32px">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="32%" style="padding:16px;background:#f0fdf4;border-radius:8px;text-align:center">
                  <div style="font-size:11px;color:#6b6b6b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Receitas</div>
                  <div style="font-size:20px;font-weight:600;color:#16a34a">{fmt(receitas)}</div>
                </td>
                <td width="4%"></td>
                <td width="32%" style="padding:16px;background:#fef2f2;border-radius:8px;text-align:center">
                  <div style="font-size:11px;color:#6b6b6b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Despesas</div>
                  <div style="font-size:20px;font-weight:600;color:#dc2626">{fmt(despesas)}</div>
                </td>
                <td width="4%"></td>
                <td width="32%" style="padding:16px;background:#f8f8f8;border-radius:8px;text-align:center">
                  <div style="font-size:11px;color:#6b6b6b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Saldo</div>
                  <div style="font-size:20px;font-weight:600;color:{cor_saldo}">{fmt(saldo)}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Top categorias -->
        {'<tr><td style="padding:0 32px 20px"><p style="margin:0 0 12px;font-size:13px;font-weight:600;color:#1a1a1a;text-transform:uppercase;letter-spacing:0.06em">Top gastos</p><table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e8e8e8">' + cats_html + '</table></td></tr>' if cats_html else ''}

        <!-- CTA -->
        <tr>
          <td style="padding:0 32px 28px;text-align:center">
            <a href="https://gravs.pythonanywhere.com"
               style="display:inline-block;padding:12px 28px;background:#1a1a1a;color:#ffffff;
                      text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">
              Ver dashboard completo →
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px 32px;border-top:1px solid #e8e8e8;text-align:center">
            <p style="margin:0;font-size:12px;color:#9a9a9a">
              Gravs · Controle financeiro pessoal<br/>
              Você recebe este email todo dia 28.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    assunto = f"📊 Seu resumo de {mes_nome} — Gravs"
    return _enviar_email(remetente, senha_app, destinatario, assunto, corpo)