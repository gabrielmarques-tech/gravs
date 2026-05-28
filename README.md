<div align="center">

  <img src="static/icon-192.png" alt="Gravs" width="72" />

  # Gravs

  **Controle financeiro pessoal — simples, rápido, seu.**

  [![Python](https://img.shields.io/badge/Python-3.11+-3572A5?style=flat-square&logo=python&logoColor=white)](https://python.org)
  [![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat-square&logo=flask)](https://flask.palletsprojects.com)
  [![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?style=flat-square&logo=sqlite)](https://sqlite.org)
  [![Testes](https://img.shields.io/badge/Testes-495%20passing-22c55e?style=flat-square)](#testes)
  [![Deploy](https://img.shields.io/badge/Deploy-PythonAnywhere-blue?style=flat-square)](https://gravs.pythonanywhere.com)

</div>

---

A maioria das pessoas termina o mês sem saber onde o dinheiro foi parar. O Gravs resolve isso — visibilidade total sobre receitas, despesas, contas fixas, parcelamentos, metas e transferências, em uma interface limpa e responsiva.

---

## Screenshots

### Dashboard
![Dashboard do Gravs](docs/dashboard.png)

### Menu lateral
![Menu](docs/menu.png)

### Transações
![Lista de transações](docs/transacoes.png)

### Login
![Tela de login](docs/tela_login.png)

---

## Funcionalidades

### Transações
- Registre **receitas e despesas** com categoria, conta e data
- **Parcelamentos** — distribui automaticamente nos meses corretos, com ou sem juros
- **Transação rápida** — registro em um clique direto da tela inicial
- **Busca e filtros** em tempo real por tipo, conta, termo e período
- **Soft-delete** — transações deletadas podem ser restauradas
- Paginação de 50 itens por página com navegação entre páginas

### Contas fixas e recorrentes
- Cadastre salário, aluguel, assinaturas com **geração automática de lançamentos**
- Confirme pagamentos ou edite valores diretamente na lista
- Widget na sidebar com fixas do mês e status de pagamento

### Transferências entre contas
- Mova saldo sem criar despesa duplicada
- Pague fatura de cartão registrando como transferência (corrente → cartão)
- Funciona com múltiplos cartões e contas

### Metas financeiras
- Defina objetivos com valor alvo e prazo
- Acompanhe o progresso com barra visual
- Widget no dashboard mostra as metas ativas

### Dashboard
- Saldo do mês com comparação ao mês anterior
- Cards de Receitas, Despesas e Taxa de Poupança (meta: 30%)
- Gastos por categoria com barras e **limites configuráveis**
- Saldo por conta considerando transferências
- Próximos vencimentos de contas fixas
- Gráfico de evolução dos últimos 6 meses
- Dicas automáticas baseadas nos dados reais

### Importação CSV Bradesco
- Upload do extrato bancário em CSV
- Classifica automaticamente PIX recebido → Receita PIX
- PIX enviado e QR Code → Transferências PIX
- Revisão antes de confirmar a importação

### Exportação Excel
- Planilha completa com cores por tipo (receita/despesa)
- Filtro por período com atalhos (este mês, trimestre, ano, tudo)
- Totais de receitas, despesas e saldo no rodapé

### Modo contábil
- Lançamentos em **partida dobrada** (débito/crédito)
- Exportação separada do livro contábil
- Acesso restrito — ative nas configurações de perfil

### Segurança
- CSRF em todos os formulários e chamadas AJAX
- HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy
- Rate limiting no login — 5 tentativas por minuto por IP
- Senhas com hash bcrypt
- Isolamento total por `usuario_id` em todas as queries
- Logs de auditoria com emails anonimizados

### Conta e LGPD
- Verificação de email por código de 6 dígitos (expira em 15 min)
- Aceite obrigatório dos Termos de Uso no cadastro
- Recuperação de senha por email com token de 1 hora
- Exclusão de conta com anonimização de email (direito ao esquecimento)

### UX e acessibilidade
- Tema claro e escuro com persistência entre sessões
- PWA — instalável no celular como app nativo
- Bottom navigation no mobile
- Skip link para navegação por teclado
- Atalhos de teclado: `N` nova transação · `B` busca · `G` dashboard · `?` ajuda
- Filtros de transações persistentes via sessionStorage
- Modal de confirmação próprio (sem `window.confirm()` nativo)
- Resumo mensal por email automático todo dia 28

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11+ · Flask 3.x |
| Autenticação | Flask-Login · Werkzeug bcrypt |
| Segurança | Flask-WTF (CSRF) · Flask-Limiter |
| Performance | Flask-Compress (gzip) · SQLite WAL · índices compostos |
| Banco | SQLite com cache 8MB · mmap 128MB · temp_store MEMORY |
| Frontend | HTML5 · CSS3 · JavaScript puro — sem frameworks |
| Design | Inter (Google Fonts) · design tokens CSS · tema claro/escuro |
| Excel | openpyxl |
| Email | Gmail SMTP · APScheduler |
| Testes | pytest — 495 testes automatizados |
| Deploy | PythonAnywhere |

---

## Arquitetura

```
gravs/
├── app.py                     # Application Factory
├── config.py                  # Configurações por ambiente
├── wsgi.py                    # Entry point produção (PythonAnywhere)
│
├── database/
│   ├── manager.py             # SQLite + migrations automáticas + índices
│   └── repositories.py        # Repository Pattern — isolamento por usuario_id
│
├── services/
│   ├── container.py           # Service Container (injeção de dependência)
│   ├── auth_service.py        # Registro, login, verificação de email
│   ├── transacao_service.py   # CRUD, parcelamento, soft-delete
│   ├── recorrente_service.py  # Geração automática de lançamentos
│   ├── dashboard_service.py   # Agregações e insights
│   ├── email_service.py       # Envio de emails (verificação, recuperação, resumo)
│   └── scheduler.py           # APScheduler — resumo mensal dia 28
│
├── routes/                    # Blueprints por domínio
│   ├── auth.py                # Login, cadastro, verificação, logout
│   ├── dashboard.py           # Dashboard + APIs de limites e onboarding
│   ├── transacoes.py          # CRUD + busca + parcelamento + APIs
│   ├── recorrentes.py         # Contas fixas + APIs sidebar/lembretes
│   ├── transferencias.py      # Transferências entre contas
│   ├── metas.py               # Metas financeiras
│   ├── categorias.py          # Categorias + limites mensais
│   ├── contas.py              # Contas bancárias e cartões
│   ├── importacao.py          # Importação CSV Bradesco
│   ├── contabil.py            # Partida dobrada + exportação
│   ├── perfil.py              # Nome, senha, modo contábil, exclusão
│   ├── recuperacao.py         # Recuperação de senha por email
│   └── publico.py             # Termos de uso, privacidade
│
├── templates/                 # Jinja2 — mobile-first
│   ├── base.html              # Layout base — design system completo
│   ├── dashboard/
│   ├── transacoes/
│   ├── metas/
│   └── ...
│
├── utils/
│   ├── formatters.py          # Filtros Jinja2 (real, data, percentual)
│   ├── validators.py          # Validações de entrada
│   └── calendario.py          # Feriados e dias úteis (fuso Brasília)
│
├── static/                    # Assets estáticos
│   ├── manifest.json          # PWA manifest
│   ├── icon-192.png
│   └── icon-512.png
│
└── tests/                     # 495 testes automatizados
    ├── conftest.py            # Fixtures compartilhadas
    ├── test_sistema.py        # 395 testes unitários e de integração
    ├── test_auth.py           # Testes de autenticação
    └── test_jornada_usuario.py # 100 testes de jornada completa do usuário
```

**Padrões:** Application Factory · Repository Pattern · Service Container · Blueprints · Soft Delete · Migrations automáticas · CSRF global · Design Tokens CSS

---

## Rodando localmente

```bash
git clone https://github.com/gabrielmarques-tech/gravs.git
cd gravs
pip install -r requirements.txt
```

Crie o arquivo `.env.secret` na raiz:

```env
SECRET_KEY=qualquer-string-aleatoria-longa
DATABASE_URL=sqlite:///financas_dev.db
EMAIL_REMETENTE=
EMAIL_SENHA_APP=
```

Inicie o servidor:

```bash
# Windows
python app.py

# Linux / Mac
FLASK_ENV=development python app.py
```

Acesse `http://127.0.0.1:5000`

> Sem `EMAIL_REMETENTE` configurado, o código de verificação de email é exibido no terminal — você não precisa de email real para desenvolver.

---

## Testes

```bash
# Suite completa
python -m pytest tests/ -v

# Só a jornada do usuário (100 testes em sequência)
python -m pytest tests/test_jornada_usuario.py -v

# Com relatório de cobertura
python -m pytest tests/ --cov=. --cov-report=term-missing
```

### O que é testado — 495 testes

**`test_sistema.py`** — 395 testes unitários e de integração:
- Autenticação completa (login, cadastro, CSRF, rate limiting, LGPD)
- Todas as APIs do dashboard
- Transações, parcelamentos, recorrentes, transferências
- Metas financeiras
- Importação CSV com classificação automática de PIX
- Exportação Excel
- Perfil (nome, senha, modo contábil, exclusão de conta)
- Segurança (headers HTTP, isolamento de dados, logs anonimizados)
- Performance (queries com BETWEEN vs strftime, índices)
- Design system (tokens CSS, sombras, tipografia, acessibilidade)
- Meta tags OG, PWA manifest, skip link

**`test_jornada_usuario.py`** — 100 testes de jornada completa:

Simula um usuário real fazendo **absolutamente tudo** no app, do cadastro à exclusão de conta. Em sequência:

1. Páginas públicas sem login
2. Cadastro e verificação de email
3. Login (senha errada e correta)
4. Dashboard e todas as APIs
5. Criar, editar, definir limite e deletar categorias
6. Criar contas bancárias
7. Criar receita, criar despesa, listar com filtros de período, paginação, busca por tipo/termo/conta, editar, deletar, restaurar
8. Transação rápida e preview de parcelas
9. Parcelamento 12x, listar, excluir grupo inteiro
10. Conta fixa, editar, confirmar pagamento, desativar
11. Transferência entre contas, listar, deletar
12. Importação CSV Bradesco (arquivo inválido e válido), confirmar
13. Criar metas, atualizar progresso, deletar
14. Exportação Excel por mês, ano e tudo
15. Ativar modo contábil, partida dobrada, novo lançamento, exportar, desativar
16. Perfil — alterar nome, senha, validações de erro
17. Deletar categorias e conta bancária
18. Recuperação de senha (solicitar, token inválido, redefinir via token real)
19. Logout e relogin
20. Excluir conta e verificar que login falha depois

---

## Variáveis de ambiente

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `SECRET_KEY` | Produção | Chave secreta Flask para sessões e CSRF |
| `DATABASE_URL` | Sim | Caminho do banco: `sqlite:////home/Gravs/gravs/financas.db` |
| `EMAIL_REMETENTE` | Email | Gmail para envio de verificação e resumo mensal |
| `EMAIL_SENHA_APP` | Email | Senha de app Google (não a senha da conta) |
| `FLASK_ENV` | Não | `development`, `testing` ou `production` |

---

## Como funciona o cartão de crédito

O Gravs usa transferências para evitar dupla contagem:

```
1. Compra no cartão
   → Despesa na conta "Cartão Nubank": -R$ 500
   Saldo Nubank: -R$ 500

2. Pagamento da fatura
   → Transferência: Conta Corrente → Cartão Nubank: R$ 500
   Saldo Corrente: -R$ 500
   Saldo Nubank:    R$ 0
   Despesas do mês: sem alteração (já foram contadas na compra)
```

Funciona com qualquer número de cartões e bancos.

---

## Deploy — PythonAnywhere

```bash
# No bash do PythonAnywhere
cd ~/gravs
git fetch origin
git reset --hard origin/main
pip install -r requirements.txt --user
# Web → Reload
```

O arquivo `wsgi.py` carrega automaticamente as variáveis de ambiente do `.env.secret` antes de iniciar a aplicação.

---

<div align="center">
  <sub>Feito para quem quer saber para onde o dinheiro vai.</sub>
</div>
