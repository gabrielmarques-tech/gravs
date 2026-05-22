<div align="center">

  <img src="docs/tela_login.png" alt="Gravs" width="220" />

  # 🌀 Gravs — Controle Financeiro Pessoal

  > *"Você sabe quanto ganhou esse mês. Mas sabe onde foi parar cada centavo?"*

  ![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
  ![Flask](https://img.shields.io/badge/Flask-3.x-black?style=flat-square&logo=flask)
  ![SQLite](https://img.shields.io/badge/SQLite-WAL-blue?style=flat-square&logo=sqlite)
  ![Tests](https://img.shields.io/badge/Testes-76%20passing-green?style=flat-square)
  ![License](https://img.shields.io/badge/Licença-Privada-red?style=flat-square)

</div>

---

## 💡 Motivação

A maioria das pessoas chega ao fim do mês sem entender onde o dinheiro foi parar. Salário entrou, contas saíram, e sobrou menos do que deveria. O **Gravs** foi criado para mudar isso — dar visibilidade total sobre receitas, despesas, contas fixas e parcelamentos de forma simples e visual, no celular ou no computador.

---

## 📸 Preview

### Login
<img src="docs/tela_login.png" alt="Login" width="100%" />

### Dashboard
<img src="docs/dashboard.png" alt="Dashboard" width="100%" />

<details>
<summary>Ver mais screenshots</summary>

### Menu e Navegação
<img src="docs/menu.png" alt="Menu" width="100%" />

### Transações
<img src="docs/transacoes.png" alt="Transações" width="100%" />

### Exportar para Excel
<img src="docs/exel.png" alt="Exportar Excel" width="100%" />

</details>

---

## ✨ Funcionalidades

### Controle completo
- **Transações avulsas** — registre receitas e despesas com categoria, data e conta bancária
- **Leitura de comprovante** — envie um PNG ou PDF e o app extrai valor, descrição e data automaticamente
- **Contas fixas** — cadastre salário, aluguel, assinaturas e receba lembretes automáticos de vencimento
- **Compras parceladas** — acompanhe o progresso de cada parcelamento com barra visual
- **Contas bancárias e cartões** — saiba de qual conta saiu cada gasto

### Dashboard inteligente
- Resumo do mês: receitas, despesas e saldo
- Card de economia com percentual guardado
- Gráfico de evolução dos últimos 6 meses (com tooltip interativo no PC e celular)
- Saldo atual por conta bancária
- Gastos por categoria com barras de progresso
- Lembretes de contas que vencem hoje

### Busca e filtros
- Busca em tempo real por descrição
- Filtro por tipo (receita/despesa) e por conta bancária
- Filtro por período com atalhos

### Exportação e contabilidade
- Exportar transações para Excel com totais e cores
- Modo contábil com lançamentos em partida dobrada (débito/crédito)

### Experiência
- Tema claro e escuro com um clique
- Totalmente responsivo — funciona igual no celular e no computador
- Instalável como app (PWA) na tela inicial do celular
- Widget na sidebar com resumo de fixas e lançamentos recentes
- Recuperação de senha por email

### Segurança
- Cada usuário vê só os próprios dados (isolamento total por usuario_id)
- Hash bcrypt nas senhas
- Rate limiting no login (5 tentativas por minuto por IP)
- Recuperação de senha com tokens de expiração de 1 hora
- Headers de segurança HTTP em todas as respostas
- Cookies seguros (HttpOnly, SameSite, Secure em produção)
- SQL 100% parametrizado — sem SQL injection

---

## 🛠 Tecnologias

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11 + Flask 3.x |
| Autenticação | Flask-Login + Werkzeug (bcrypt) |
| Banco de dados | SQLite com WAL mode + índices otimizados |
| Frontend | HTML5 + CSS3 + JavaScript puro |
| OCR | Tesseract.js (roda no browser, sem servidor) |
| Tipografia | Inter + Syne (Google Fonts) |
| Excel | openpyxl |
| Testes | pytest — 76 testes automatizados |
| Deploy | PythonAnywhere |

---

## 🏗 Arquitetura

```
gravs/
├── app.py                    # Application Factory (create_app)
├── config.py                 # Configurações por ambiente
├── wsgi.py                   # Entry point para produção
│
├── database/
│   ├── manager.py            # Gerenciador SQLite + migrations automáticas
│   └── repositories.py       # Repositórios de dados — padrão Repository
│
├── services/
│   ├── container.py          # Service Container (injeção de dependência)
│   ├── auth_service.py       # Autenticação e registro
│   ├── transacao_service.py  # Lógica de transações e parcelamentos
│   ├── recorrente_service.py # Lógica de contas fixas e lembretes
│   └── dashboard_service.py  # Agregação de dados para o dashboard
│
├── routes/                   # Blueprints Flask por domínio
├── templates/                # Jinja2 — mobile-first
├── static/                   # Ícones PWA + manifest.json
├── utils/                    # Formatadores, validadores, calendário BR
├── docs/                     # Screenshots do projeto
└── tests/                    # 76 testes automatizados
```

**Padrões adotados:** Application Factory · Repository Pattern · Service Container · Blueprints · Soft Delete · Migrations automáticas

---

## 🚀 Rodando localmente

```bash
git clone https://github.com/gabrielmarques-tech/gravs.git
cd gravs
pip install -r requirements.txt
cp .env.secret.example .env.secret
# Edite o .env.secret com seus valores
flask --app app:create_app run --debug
```

Acesse `http://127.0.0.1:5000`

---

## 🧪 Testes

```bash
python -m pytest tests/test_sistema.py -v
```

76 testes cobrindo autenticação, transações, parcelamentos, recorrentes, isolamento entre usuários, contas bancárias, busca e soft delete.

---

## ⚙️ Variáveis de ambiente

| Variável | Descrição |
|----------|-----------|
| `SECRET_KEY` | Chave secreta do Flask |
| `DATABASE_URL` | Caminho do banco SQLite |
| `EMAIL_REMETENTE` | Gmail para recuperação de senha |
| `EMAIL_SENHA_APP` | Senha de app do Google |

Consulte `.env.secret.example` para o modelo completo.

---

<div align="center">
  <sub>Feito com dedicação para quem quer saber para onde o dinheiro vai.</sub>
</div>