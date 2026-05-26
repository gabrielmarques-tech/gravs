<div align="center">

  <img src="static/icon-192.png" alt="Gravs" width="80" style="border-radius:18px" />

  # Gravs — Controle Financeiro Pessoal

  > *Clareza total sobre onde seu dinheiro vai.*

  ![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
  ![Flask](https://img.shields.io/badge/Flask-3.x-black?style=flat-square&logo=flask)
  ![SQLite](https://img.shields.io/badge/SQLite-WAL-blue?style=flat-square&logo=sqlite)
  ![Tests](https://img.shields.io/badge/Testes-289%20passing-green?style=flat-square)
  ![License](https://img.shields.io/badge/Licença-Privada-red?style=flat-square)

</div>

---

## Motivação

A maioria das pessoas termina o mês sem saber onde o dinheiro foi parar. O Gravs foi criado para mudar isso — visibilidade total sobre receitas, despesas, contas fixas, parcelamentos, transferências entre contas e metas financeiras, de forma simples e visual.

---

## Funcionalidades

### Controle financeiro
- **Transações** — registre receitas e despesas com categoria, data e conta
- **Parcelamentos** — acompanhe o progresso de cada compra parcelada
- **Contas fixas** — salário, aluguel, assinaturas com geração automática de lançamentos
- **Transferências entre contas** — pague fatura do cartão, transfira para poupança sem criar despesa duplicada
- **Metas financeiras** — defina objetivos com valor alvo e prazo, acompanhe o progresso
- **Importação CSV Bradesco** — classifica automaticamente PIX recebido/enviado, QR Code e categorias

### Dashboard
- Saldo do mês com comparação ao mês anterior
- Cards de Receitas, Despesas e Taxa de Poupança (meta de 30%)
- Gastos por categoria com barras e limites configuráveis
- Saldo por conta bancária (considera transferências)
- Próximos vencimentos e metas na coluna lateral
- Evolução dos últimos 6 meses
- Dicas automáticas baseadas nos dados reais

### Exportação e modo contábil
- Excel com totais, cores e filtros por período
- Modo contábil com lançamentos em partida dobrada (débito/crédito)

### Segurança
- CSRF em todos os formulários e chamadas fetch/AJAX
- HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy
- Rate limiting no login (5/min por IP)
- Senhas com hash bcrypt
- Isolamento total por `usuario_id`
- Logs de auditoria com emails anonimizados

### Conta e LGPD
- Verificação de email por código de 6 dígitos (expira em 15 min)
- Aceite obrigatório dos Termos de Uso no cadastro
- Exclusão de conta com anonimização de email (direito ao esquecimento)
- Recuperação de senha por email com token de 1 hora

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11+ + Flask 3.x |
| Autenticação | Flask-Login + Werkzeug (bcrypt) |
| Segurança | Flask-WTF (CSRF) + Flask-Limiter |
| Compressão | Flask-Compress (gzip automático) |
| Banco | SQLite WAL + índices otimizados |
| Frontend | HTML5 + CSS3 + JS puro (sem frameworks) |
| Tipografia | Inter (Google Fonts) |
| Excel | openpyxl |
| Email | Gmail SMTP |
| Testes | pytest — 289 testes automatizados |
| Deploy | PythonAnywhere |

---

## Arquitetura

```
gravs/
├── app.py                    # Application Factory
├── config.py                 # Configurações por ambiente
├── wsgi.py                   # Entry point produção
│
├── database/
│   ├── manager.py            # SQLite + migrations + índices
│   └── repositories.py       # Repository Pattern
│
├── services/
│   ├── container.py          # Service Container (DI)
│   ├── auth_service.py
│   ├── transacao_service.py
│   ├── recorrente_service.py
│   ├── dashboard_service.py
│   └── email_service.py
│
├── routes/                   # Blueprints por domínio
│   ├── auth.py
│   ├── dashboard.py
│   ├── transacoes.py
│   ├── recorrentes.py
│   ├── transferencias.py
│   ├── metas.py
│   ├── importacao.py
│   ├── contabil.py
│   ├── perfil.py
│   └── ...
│
├── templates/                # Jinja2 — mobile-first
│   ├── base.html             # Layout base + tema claro/escuro
│   ├── dashboard/
│   ├── transacoes/
│   ├── metas/
│   └── ...
│
└── tests/                    # 289 testes automatizados
```

**Padrões:** Application Factory · Repository Pattern · Service Container · Blueprints · Soft Delete · Migrations automáticas · CSRF global

---

## Rodando localmente

```bash
git clone https://github.com/gabrielmarques-tech/gravs.git
cd gravs
pip install -r requirements.txt

# Criar .env.secret
cp .env.secret.example .env.secret
# Editar com seus valores

# Windows
set FLASK_ENV=development
flask --app app run --debug

# Linux/Mac
FLASK_ENV=development flask --app app run --debug
```

Acesse `http://127.0.0.1:5000`

Sem `EMAIL_REMETENTE` configurado, o código de verificação aparece no log do terminal.

---

## Testes

```bash
python -m pytest tests/ -v
```

**289 testes** cobrindo: autenticação, CSRF, LGPD, transações, parcelamentos, recorrentes, transferências, metas, importação CSV, exportação Excel, dashboard APIs, perfil, contábil, segurança e performance das queries.

---

## Variáveis de ambiente

| Variável | Descrição |
|----------|-----------|
| `SECRET_KEY` | Chave secreta Flask (obrigatório em produção) |
| `DATABASE_URL` | Caminho do banco SQLite |
| `EMAIL_REMETENTE` | Gmail para envio de emails |
| `EMAIL_SENHA_APP` | Senha de app do Google |
| `FLASK_ENV` | `development`, `testing` ou `production` |

---

## Como usar cartão de crédito

```
1. Compra no cartão → Despesa na conta "Cartão Nubank"
   Saldo Nubank: -R$ 500

2. Paga fatura → Transferência: Corrente → Cartão Nubank
   Saldo Corrente: -R$ 500
   Saldo Nubank:    R$ 0
   Despesas do mês: sem alteração (já contadas)
```

Funciona com múltiplos cartões pagos pelo mesmo banco.

---

<div align="center">
  <sub>Feito para quem quer saber para onde o dinheiro vai.</sub>
</div>
