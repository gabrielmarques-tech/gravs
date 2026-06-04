<div align="center">

  <img src="static/icon-192.png" alt="Gravs" width="72" />

  # Gravs

  **Controle financeiro pessoal — simples, rápido, seu.**

  [![Python](https://img.shields.io/badge/Python-3.11+-3572A5?style=flat-square&logo=python&logoColor=white)](https://python.org)
  [![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat-square&logo=flask)](https://flask.palletsprojects.com)
  [![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?style=flat-square&logo=sqlite)](https://sqlite.org)
  [![Testes](https://img.shields.io/badge/Testes-569%20passing-22c55e?style=flat-square)](#testes)
  [![Deploy](https://img.shields.io/badge/Deploy-PythonAnywhere-blue?style=flat-square)](https://gravs.pythonanywhere.com)
  [![LGPD](https://img.shields.io/badge/LGPD-ready-7c3aed?style=flat-square)](#conta-e-lgpd)

</div>

---

A maioria das pessoas termina o mês sem saber onde o dinheiro foi parar. O Gravs resolve isso — visibilidade total sobre receitas, despesas, contas fixas, parcelamentos, metas e transferências, em uma interface limpa e responsiva.

Com suporte a **partidas dobradas** (modo contábil), você pode evoluir de um simples extrato financeiro para uma contabilidade pessoal completa.

---

## Screenshots

### Dashboard
![Dashboard do Gravs](docs/dashboard.png)

### Menu lateral
![Menu](docs/menu.png)

### Transações
![Lista de transações](docs/transacoes.png)

### Nova transação
![Nova transação](docs/nova_transacao.png)

### Login
![Tela de login](docs/tela_login.png)

---

## Funcionalidades

### Transações
- Registre **receitas e despesas** com categoria, conta e data
- **Parcelamentos** — distribui automaticamente nos meses corretos, com ou sem juros
- Suporta Sistema Price (tabela SAC), juros simples e sem juros
- **Transação rápida** — registro em um clique direto da tela inicial
- **Busca e filtros** em tempo real por tipo, conta, termo e período
- **Soft-delete** — transações deletadas podem ser restauradas
- Paginação de 50 itens por página com navegação entre páginas

### Contas fixas e recorrentes
- Cadastre salário, aluguel, assinaturas com **geração automática de lançamentos**
- Suporte a **dias úteis** (dia -1 = primeiro dia útil do mês)
- Confirme pagamentos ou edite valores diretamente na lista
- Widget na sidebar com fixas do mês e status de pagamento

### Transferências entre contas
- Mova saldo sem criar despesa duplicada
- Pague fatura de cartão registrando como transferência (corrente → cartão)
- Funciona com múltiplos cartões e contas

### Cartão de crédito
- Modelagem correta: cartão é **passivo**, não ativo
- Compra no cartão → aumenta a dívida (passivo)
- Pagamento da fatura → reduz a dívida e diminui o saldo da conta
- Sem dupla contagem de despesas

### Metas financeiras
- Defina objetivos com valor alvo e prazo
- Acompanhe o progresso com barra visual
- Widget no dashboard mostra as metas ativas

### Dashboard
- Saldo do mês com comparação ao mês anterior
- Cards de Receitas, Despesas e **Taxa de Poupança** (meta: 30%)
- Gastos por categoria com barras e **limites configuráveis**
- Saldo por conta considerando transferências
- Próximos vencimentos de contas fixas
- Gráfico de evolução dos últimos 6 meses
- Dicas automáticas baseadas nos dados reais

### Importação CSV
- Upload do extrato bancário em CSV (formato Bradesco e similares)
- Classifica automaticamente PIX recebido → Receita PIX
- PIX enviado e QR Code → Transferências PIX
- Revisão antes de confirmar a importação

### Exportação Excel
- Planilha completa com cores por tipo (receita/despesa)
- Filtro por período com atalhos (este mês, trimestre, ano, tudo)
- Totais de receitas, despesas e saldo no rodapé

### Modo contábil (partidas dobradas)
- **Lançamentos em partida dobrada** (débito/crédito) — ative nas configurações de perfil
- Plano de Contas hierárquico (5 níveis) com tipos: ativo, passivo, PL, receita, despesa, redutora
- Lançamento atômico: transação financeira + lançamento contábil em uma única transação SQL
- Exportação separada do livro contábil
- Acesso restrito — ative nas configurações de perfil

  **Exemplos de partidas:**
  | Operação | Débito | Crédito |
  |---|---|---|
  | Receita (salário) | Conta Financeira (Ativo) | Receita (Resultado) |
  | Despesa (alimentação) | Despesa (Resultado) | Conta Financeira (Ativo) |
  | Transferência | Conta Destino (Ativo) | Conta Origem (Ativo) |
  | Compra no cartão | Despesa (Resultado) | Passivo Cartão (Passivo) |
  | Pagamento de fatura | Passivo Cartão (Passivo) | Banco (Ativo) |
  | Investimento | Investimento (Ativo) | Banco (Ativo) |

### Segurança
- CSRF em todos os formulários e chamadas AJAX
- HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy
- Rate limiting no login — 5 tentativas por minuto por IP
- Senhas com hash bcrypt (Werkzeug)
- Isolamento total por `usuario_id` em todas as queries
- Logs de auditoria com emails anonimizados
- `ON DELETE RESTRICT` nas FKs contábeis — impede exclusão de contas com movimentação

### Conta e LGPD
- Verificação de email por código de 6 dígitos (expira em 15 min)
- Aceite obrigatório dos Termos de Uso no cadastro
- Recuperação de senha por email com token de 1 hora
- Exclusão de conta com anonimização de email (direito ao esquecimento)
- Dados preservados em soft-delete — recuperação judicial possível

### UX e acessibilidade
- Tema claro e escuro com persistência entre sessões
- **PWA** — instalável no celular como app nativo
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
| Performance | Flask-Compress (gzip) · SQLite WAL · índices compostos · mmap 128MB |
| Banco | SQLite com cache 8MB · temp_store MEMORY · WAL mode |
| Frontend | HTML5 · CSS3 · JavaScript puro — sem frameworks |
| Design | Inter (Google Fonts) · design tokens CSS · tema claro/escuro |
| Excel | openpyxl |
| Email | SMTP (Gmail) · APScheduler (agendador) |
| Testes | pytest — 569 testes automatizados |
| Deploy | PythonAnywhere · Gunicorn |

---

## Arquitetura

### Padrões Arquiteturais

| Padrão | Onde | Descrição |
|--------|------|-----------|
| **Application Factory** | `app.py` → `create_app()` | Flask é instanciado dentro de função — permite criar apps diferentes para dev, test e prod |
| **Service Container** | `services/container.py` → `ServiceContainer` | Único ponto de construção de dependências; armazenado em `app.extensions["services"]` |
| **Repository Pattern** | `database/repositories.py` → 13 repositórios | Cada entidade tem seu repositório com métodos específicos de consulta e persistência |
| **Service Layer** | `services/` → 7 serviços | Lógica de negócio orquestrando múltiplos repositórios |
| **Blueprint Pattern** | `routes/` → 14 blueprints | Separação de rotas por domínio (auth, transações, contábil, etc.) |
| **Partida Dobrada** | `services/contabil_service.py` | Débito/crédito atômico em transação SQL — transação financeira + lançamento contábil |
| **Soft Delete** | `transacoes.deletado`, `transferencias.deletado` | Registros são marcados como deletados (`deletado=1`) sem remoção física |
| **Application-Level Lock** | `database/manager.py` → `_write_lock` | `threading.Lock()` serializa escritas concorrentes ao SQLite |

### Estrutura de Diretórios

```
📁 gravs/
├── app.py                      # Application Factory — 14 blueprints registrados
├── config.py                   # 3 ambientes: Development, Testing, Production
├── wsgi.py                     # Entry point PythonAnywhere
├── conftest.py                 # Hook pytest para descoberta de módulos
├── requirements.txt            # Dependências Python
├── .env.secret.example         # Template de variáveis de ambiente
├── manifest.json               # Manifest PWA (instalável como app)
│
├── 📁 database/
│   ├── manager.py              # DatabaseManager — schema, migrations, WAL, write lock
│   └── repositories.py         # 13 repositórios (Usuario, Categoria, Transacao, etc.)
│
├── 📁 services/
│   ├── container.py            # ServiceContainer — fábrica de dependências
│   ├── auth_service.py         # AuthService — registro, login, verificação de email
│   ├── transacao_service.py    # TransacaoService — CRUD transações + parcelamentos
│   ├── recorrente_service.py   # RecorrenteService — geração automática de lançamentos
│   ├── contabil_service.py     # ContabilService — partidas dobradas, saldo contábil
│   ├── dashboard_service.py    # DashboardService — métricas do dashboard
│   ├── email_service.py        # EmailService — envio com retry + fallback para terminal
│   └── scheduler.py            # APScheduler — resumo mensal automático dia 28
│
├── 📁 routes/
│   ├── auth.py                 # auth_bp — login, registro, logout, verificar email
│   ├── dashboard.py            # dashboard_bp — página inicial com métricas e gráficos
│   ├── transacoes.py           # transacoes_bp — CRUD transações + parcelado + API
│   ├── recorrentes.py          # recorrentes_bp — CRUD contas fixas/recorrentes
│   ├── contabil.py             # contabil_bp — partidas dobradas, exportação, plano de contas
│   ├── contas.py               # contas_bp — CRUD contas bancárias e cartões
│   ├── categorias.py           # categorias_bp — CRUD categorias de receita/despesa
│   ├── transferencias.py       # transferencias_bp — CRUD transferências entre contas
│   ├── metas.py                # metas_bp — CRUD metas financeiras
│   ├── perfil.py               # perfil_bp — configurações de perfil, modo contábil, tema
│   ├── importacao.py           # importacao_bp — upload CSV, classificação automática
│   ├── publico.py              # publico_bp — Páginas públicas (início, termos, LGPD)
│   ├── recuperacao.py          # recuperacao_bp — Recuperação de senha por email
│   ├── health.py               # health_bp — Health check para monitoramento
│   └── helpers.py              # UserPrincipal, make_user_principal, get_services
│
├── 📁 templates/               # Jinja2 templates (responsivos, tema claro/escuro)
│   ├── base.html               # Layout base com sidebar, header, PWA, atalhos
│   ├── dashboard.html          # Dashboard principal com cards e gráficos
│   ├── transacoes/             # Templates de transações
│   ├── recorrentes/            # Templates de contas fixas
│   ├── contabil/               # Templates de partidas dobradas e plano de contas
│   ├── contas/                 # Templates de contas bancárias
│   ├── metas/                  # Templates de metas financeiras
│   ├── erros/                  # Páginas 404, 403, 500 personalizadas
│   └── ...                     # Demais templates organizados por domínio
│
├── 📁 static/
│   ├── style.css               # Design tokens CSS, tema claro/escuro, responsivo
│   ├── script.js               # JavaScript puro (sem frameworks) — modais, fetch, CSRF
│   ├── sw.js                   # Service Worker para PWA (cache offline básico)
│   ├── icon-192.png            # Ícone PWA 192x192
│   ├── icon-512.png            # Ícone PWA 512x512
│   └── fonts/                  # Fonte Inter (Google Fonts) self-hosted
│
├── 📁 utils/
│   ├── metrics.py              # Observabilidade — contagem de chamadas, tempos, consultas BD
│   ├── calendario.py           # CalendarioUtil — dias úteis, primeiro dia útil do mês
│   └── formatters.py           # Formatadores (moeda, data, etc.)
│
├── 📁 tests/
│   ├── conftest.py             # Fixtures: app de teste, DB em memória, client autenticado
│   ├── test_sistema.py         # 395 testes — funcionalidades completas
│   ├── test_auth.py            # 20 testes — autenticação, registro, verificação
│   ├── test_contabil_service.py # 58 testes — partidas dobradas, plano de contas
│   ├── test_integridade_referencial.py # 8 testes — FKs, ON DELETE RESTRICT
│   ├── test_jornada_usuario.py # 88 testes — jornadas completas de usuário
│   └── test_benchmark.py       # Testes de performance e benchmark
│
└── 📁 docs/                    # Screenshots para o README
    ├── dashboard.png
    ├── menu.png
    ├── transacoes.png
    ├── transacoes_filtro.png
    ├── nova_transacao.png
    ├── tela_login.png
    └── exel.png
```

### Fluxo de Request

```
Usuário → Browser → HTTPS → Flask (Gunicorn)
                              │
                              ▼
                         Security Headers (CSP, HSTS, X-Frame-Options)
                              │
                              ▼
                         CSRF Protection (Flask-WTF)
                              │
                              ▼
                         Rate Limiting (Flask-Limiter) → login: 5/min por IP
                              │
                              ▼
                         Blueprint dispatch (14 blueprints)
                              │
                              ▼
                         Flask-Login (user_loader → UsuarioRepository)
                              │
                              ▼
                         Service Layer (via get_services() do container)
                              │
                              ▼
                         Repository Layer (13 repositórios)
                              │
                              ▼
                         DatabaseManager (SQLite WAL, write lock)
                              │
                              ▼
                         SQLite (8MB cache, 256MB mmap, temp MEMORY)
                              │
                              ▼
                         Response → Gzip (Flask-Compress) → JSON/HTML
```

### Diagrama de Dependências

```
app.py
  ├── auth_bp ──────────────► AuthService ──────► UsuarioRepository
  │                                               └── CategoriaRepository
  ├── dashboard_bp ─────────► DashboardService ──► TransacaoRepository
  ├── transacoes_bp ────────► TransacaoService ──► TransacaoRepository
  ├── recorrentes_bp ───────► RecorrenteService ──► RecorrenteRepository
  │                                               └── TransacaoService
  │                                               └── CalendarioUtil
  ├── contabil_bp ──────────► ContabilService ────► DatabaseManager
  │                                               ├── PlanoContasRepository
  │                                               ├── LancamentoContabilRepository
  │                                               └── TransacaoRepository
  ├── contas_bp ────────────► ContaBancariaRepository
  ├── categorias_bp ────────► CategoriaRepository
  ├── transferencias_bp ────► TransferenciaRepository
  ├── metas_bp ─────────────► MetaRepository
  ├── perfil_bp ────────────► UsuarioRepository
  ├── importacao_bp ────────► TransacaoRepository + CategoriaRepository
  ├── publico_bp
  ├── recuperacao_bp ───────► AuthService
  ├── health_bp
  │
  └── ServiceContainer (app.extensions["services"])
        └── DatabaseManager (compartilhado por todos os repositórios)
```

### Modelo de Dados

#### Tabelas (15 no total)

| Tabela | Finalidade | Chave Estrangeira |
|--------|-----------|-------------------|
| `usuarios` | Usuários do sistema | — |
| `categorias` | Categorias de receita/despesa | `usuario_id` → `usuarios(id)` ON DELETE CASCADE |
| `transacoes` | Transações financeiras (receitas, despesas) | `usuario_id` → `usuarios(id)`, `categoria_id` → `categorias(id)` |
| `recorrentes` | Contas fixas e recorrentes | `usuario_id` → `usuarios(id)`, `categoria_id` → `categorias(id)` |
| `metas` | Metas financeiras | `usuario_id` → `usuarios(id)` ON DELETE CASCADE |
| `notificacoes` | Notificações do sistema | `usuario_id` → `usuarios(id)` ON DELETE CASCADE |
| `contas_bancarias` | Contas bancárias e cartões | `usuario_id` → `usuarios(id)` ON DELETE CASCADE |
| `transferencias` | Transferências entre contas | `usuario_id` → `usuarios(id)`, `conta_origem_id`/`conta_destino_id` → `contas_bancarias(id)` |
| `plano_contas` | Plano de Contas contábil (5 níveis) | `usuario_id` → `usuarios(id)` ON DELETE CASCADE, `conta_pai_id` → `plano_contas(id)` ON DELETE RESTRICT |
| `lancamentos_contabeis` | Lançamentos em partida dobrada | `usuario_id` → `usuarios(id)`, `debito_id`/`credito_id` → `plano_contas(id)` ON DELETE RESTRICT |
| `limites_categoria` | Limites mensais por categoria | `usuario_id` → `usuarios(id)`, `categoria_id` → `categorias(id)` ON DELETE CASCADE |
| `tokens_recuperacao` | Tokens para recuperação de senha | `usuario_id` → `usuarios(id)` ON DELETE CASCADE |
| `verificacao_email` | Códigos de verificação de email | `usuario_id` → `usuarios(id)` ON DELETE CASCADE |
| `saldo_conta` | Snapshots de saldo (cache) | `usuario_id` → `usuarios(id)`, `conta_id` → `contas_bancarias(id)` |

#### Índices de Performance

| Índice | Tabela | Colunas | Finalidade |
|--------|--------|---------|------------|
| `idx_trans_user_data` | transacoes | `(usuario_id, data DESC)` | Listagem de transações por data |
| `idx_trans_user_tipo` | transacoes | `(usuario_id, tipo)` | Filtro por tipo (receita/despesa) |
| `idx_trans_mes` | transacoes | `(usuario_id, strftime('%Y-%m', data))` | Agregação mensal (dashboard) |
| `idx_trans_categoria` | transacoes | `(usuario_id, categoria_id)` | Gastos por categoria |
| `idx_lanc_saldo_debito` | lancamentos_contabeis | `(usuario_id, debito_id, data)` | Cálculo de saldo contábil |
| `idx_lanc_saldo_credito` | lancamentos_contabeis | `(usuario_id, credito_id, data)` | Cálculo de saldo contábil |
| `idx_contas_ativo` | contas_bancarias | `(usuario_id, ativo)` | Listagem de contas ativas |
| `idx_recorrentes_dia` | recorrentes | `(usuario_id, dia_vencimento)` | Geração automática por dia |

#### Configurações do SQLite (WAL mode)

```sql
PRAGMA journal_mode = WAL;           -- Leituras concorrentes sem bloquear escritas
PRAGMA foreign_keys = ON;            -- Integridade referencial real
PRAGMA synchronous = NORMAL;         -- Equilíbrio durabilidade/performance
PRAGMA busy_timeout = 5000;          -- Aguarda 5s antes de "database is locked"
PRAGMA cache_size = -8000;           -- 8MB de cache em memória
PRAGMA mmap_size = 268435456;        -- 256MB memory-mapped I/O
PRAGMA temp_store = MEMORY;          -- Tabelas temporárias em RAM
```

### Integrações e Fluxos Críticos

#### Fluxo de Parcelamento
```
TransacaoService.adicionar_parcelado()
  ├── Valida: MAX_PARCELAS=420, MIN_PARCELAS=2
  ├── Calcula parcelas (Price, juros simples ou sem juros)
  ├── Cria N transacoes com mesmo grupo_parcela (UUID)
  └── Retorna preview com resumo das parcelas
```

#### Fluxo de Geração Automática (Recorrentes)
```
RecorrenteService.gerar_lancamentos_pendentes()
  ├── Busca recorrentes ativos do mês
  ├── Calcula dia de vencimento (suporta dia -1 = primeiro dia útil)
  ├── Verifica duplicidade por recorrente_uuid + mês
  ├── Cria transação para cada recorrente pendente
  └── Retorna contagem de lançamentos gerados
```

#### Fluxo de Partida Dobrada (Contábil)
```
ContabilService.criar_lancamento_completo()
  ├── 1. Valida conta de débito (existe? pertence ao usuário? aceita lançamentos?)
  ├── 2. Valida conta de crédito (mesmas verificações)
  ├── 3. Verifica débito != crédito
  ├── 4. Transação SQL atômica:
  │     ├── INSERT INTO transacoes (transação financeira)
  │     └── INSERT INTO lancamentos_contabeis (lançamento contábil)
  └── Retorna {transacao_id, lancamento} em caso de sucesso
```

#### Fluxo de Importação CSV
```
ImportacaoBP.importar
  ├── Upload do arquivo CSV (max 2MB)
  ├── Parse com detecção de encoding e separador
  ├── Classificação automática:
  │     ├── PIX recebido → Receita PIX
  │     ├── PIX enviado → Transferência PIX
  │     └── Outros → despesa genérica
  ├── Preview em tela para revisão do usuário
  └── Confirmação → persistência em lote
```

#### Fluxo de Segurança
```
Request → CSRF Protection (Flask-WTF)
       → Rate Limiting (5 tentativas/min no login)
       → Flask-Login (sessão com SESSION_COOKIE_SECURE=True em produção)
       → SQL (isolamento total por usuario_id em TODAS as queries)
       → Logs (emails anonimizados nos logs)
       → Headers HTTP (CSP, HSTS, X-Frame-Options, etc.)
```

### Gaps Arquiteturais Conhecidos (v1)

Os seguintes gaps foram identificados durante a auditoria de arquitetura e estão documentados para planejamento futuro:

1. **`contas_bancarias.conta_contabil_id` — FK faltando**
   Sem esta coluna, o ContabilService não sabe qual conta do plano_contas debitar/creditar automaticamente.

2. **`categorias.conta_resultado_id` — FK faltando**
   Sem esta coluna, o ContabilService não sabe qual conta de resultado (receita/despesa) usar.

3. **`TransacaoService` não chama `ContabilService.criar_lancamento_completo()`**
   Fluxo financeiro e contábil estão totalmente desacoplados. O usuário precisa criar a partida dobrada manualmente.

4. **Parcelamentos e recorrentes não geram lançamentos contábeis**
   `adicionar_parcelado()` e `gerar_lancamentos_pendentes()` criam transações mas nunca chegam ao módulo contábil.

5. **Soft-delete de transação não estorna lançamento contábil**
   Deletar uma transação (`deletado=1`) não gera estorno no `lancamentos_contabeis` correspondente.

6. **Edição de transação não corrige lançamento contábil**
   Editar valor/descrição não propaga para partida dobrada.

---

## Testes

O Gravs possui **569 testes automatizados** cobrindo todas as camadas da aplicação:

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `test_sistema.py` | 395 | Funcionalidades completas: transações, parcelamentos, contas, categorias, metas, dashboard, autenticação, perfil |
| `test_jornada_usuario.py` | 88 | Jornadas completas: registro → verificação → onboarding → transações → metas → dashboard |
| `test_contabil_service.py` | 58 | Partidas dobradas: criação, validação, saldo, plano de contas, exclusão, exportação |
| `test_auth.py` | 20 | Autenticação: registro, login, logout, verificação de email, tentativas inválidas |
| `test_integridade_referencial.py` | 8 | FKs contábeis: ON DELETE RESTRICT, integridade referencial, violações |

### Executar os testes

```bash
# Todos os testes
pytest -v

# Com cobertura
pytest --cov=. --cov-report=term-missing

# Testes específicos
pytest tests/test_contabil_service.py -v
pytest tests/test_auth.py -v
```

---

## Deploy

### PythonAnywhere

#### 1. Clone no bash do PythonAnywhere

```bash
cd ~
git clone https://github.com/SEU_USUARIO/gravs.git
cd gravs
```

#### 2. Configure o ambiente virtual

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 3. Configure as variáveis de ambiente

```bash
cp .env.secret.example .env.secret
# Edite .env.secret com seus valores reais:
#   SECRET_KEY=uma-chave-segura-aqui
#   DATABASE_URL=sqlite:////home/SEU_USUARIO/gravs/financas.db
#   EMAIL_REMETENTE=seu-email@gmail.com
#   EMAIL_SENHA=sua-senha-de-app
```

#### 4. Configurar o Web App no PythonAnywhere

Vá até a aba **Web** no painel do PythonAnywhere:

1. **Add a new web app** → Manual configuration → Python 3.11
2. **Source code**: `/home/SEU_USUARIO/gravs`
3. **Working directory**: `/home/SEU_USUARIO/gravs`
4. **Virtual environment**: `/home/SEU_USUARIO/gravs/venv`
5. **WSGI file**: substitua o conteúdo pelo arquivo `wsgi.py` (já configurado)
6. **Static files**:
   - URL: `/static/` → Path: `/home/SEU_USUARIO/gravs/static/`

#### 5. Ajuste o `wsgi.py` com seu usuário

Edite `wsgi.py` e altere o path para:

```python
path = '/home/SEU_USUARIO/gravs'
```

#### 6. Variáveis de ambiente no PythonAnywhere

Na aba **Web** → **Environment variables**, adicione:

```
FLASK_ENV → production
SECRET_KEY → <mesma do .env.secret>
```

#### 7. Recarregue o web app

Clique em **Reload** na aba Web.

---

## Variáveis de Ambiente

| Variável | Obrigatória | Padrão | Descrição |
|----------|-------------|--------|-----------|
| `SECRET_KEY` | ✅ Produção | `dev-insecure-key...` | Chave secreta para sessões Flask |
| `DATABASE_URL` | ❌ | `sqlite:///financas.db` | URL do banco de dados |
| `FLASK_ENV` | ❌ | `development` | Ambiente: `development`, `testing`, `production` |
| `FLASK_HOST` | ❌ | `0.0.0.0` | Host do servidor |
| `FLASK_PORT` | ❌ | `5000` | Porta do servidor |
| `EMAIL_REMETENTE` | ❌ | — | Email para envio de mensagens |
| `EMAIL_SENHA` | ❌ | — | Senha de app do email (Gmail: senha de 16 dígitos) |

---

## Solução de Problemas

| Problema | Causa | Solução |
|----------|-------|---------|
| `SECRET_KEY` não definida | Produção sem variável de ambiente | Defina `SECRET_KEY` no .env.secret ou nas variáveis de ambiente do PythonAnywhere |
| Erro 500 ao registrar | Email já cadastrado | Use um email diferente ou recupere a senha |
| Código de verificação não chega | Sem servidor SMTP configurado | O código aparece no terminal. Copie e cole manualmente |
| `pytest` não encontra módulos | `conftest.py` não está inserindo `sys.path` | Verifique se `conftest.py` existe na raiz do projeto |
| Banco de dados corrompido | Queda durante escrita | Delete o arquivo `.db` e reinicie. O schema será recriado |
| Tema escuro não persiste | localStorage bloqueado | Verifique permissões do navegador para localStorage |

---

## Licença

MIT License — use, modifique, distribua. Mantenha apenas os créditos originais.

---

<div align="center">

  Feito com ☕ e código limpo.

  [← Voltar ao topo](#gravs)

</div>