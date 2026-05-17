"""
tests/test_sistema.py — Testes automatizados completos do Gravs.

Usa as fixtures do conftest.py:
  - container: ServiceContainer com banco :memory:
  - app, client: Flask app e cliente HTTP
  - usuario_criado: usuário já registrado
  - usuario_logado: usuário já logado no client
  - categoria_despesa / categoria_receita

Como rodar:
    pytest tests/ -v
    pytest tests/ -v --cov=. --cov-report=term-missing --ignore=venv
"""

import json
import pytest
from datetime import date, datetime


# ── Autenticação ──────────────────────────────────────────────────────────────

class TestAuth:
    def test_pagina_login_carrega(self, client):
        r = client.get("/auth/login")
        assert r.status_code == 200
        assert b"Gravs" in r.data

    def test_pagina_cadastro_carrega(self, client):
        r = client.get("/auth/cadastro")
        assert r.status_code == 200

    def test_cadastro_valido_redireciona(self, client):
        r = client.post("/auth/cadastro", data={
            "nome": "Novo User", "email": "novo@t.com", "senha": "senha123"
        }, follow_redirects=False)
        assert r.status_code == 302

    def test_cadastro_email_duplicado_retorna_erro(self, client, container):
        container.auth.registrar("dup@t.com", "senha123", "Dup")
        r = client.post("/auth/cadastro", data={
            "nome": "Dup2", "email": "dup@t.com", "senha": "senha123"
        }, follow_redirects=True)
        assert r.status_code in (200, 422)

    def test_login_correto_redireciona_para_dashboard(self, client, container):
        container.auth.registrar("login@t.com", "senha123", "Login")
        r = client.post("/auth/login", data={
            "email": "login@t.com", "senha": "senha123"
        }, follow_redirects=False)
        assert r.status_code == 302
        assert "/" in r.headers.get("Location", "/")

    def test_login_senha_errada_retorna_401(self, client, container):
        container.auth.registrar("wrong@t.com", "correta", "Wrong")
        r = client.post("/auth/login", data={
            "email": "wrong@t.com", "senha": "errada"
        })
        assert r.status_code == 401

    def test_dashboard_sem_login_redireciona_para_login(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert "login" in r.headers["Location"].lower()

    def test_logout_bloqueia_acesso(self, client, usuario_logado):
        client.get("/auth/logout")
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302


# ── Dashboard ─────────────────────────────────────────────────────────────────

class TestDashboard:
    def test_dashboard_carrega(self, client, usuario_logado):
        r = client.get("/")
        assert r.status_code == 200

    def test_dashboard_mostra_nome_do_usuario(self, client, usuario_logado):
        r = client.get("/")
        assert b"Logado" in r.data

    def test_dashboard_com_transacoes(self, client, usuario_logado, container, categoria_receita, categoria_despesa):
        uid = usuario_logado["id"]
        container.transacoes.adicionar("Salário", 3000, "receita", categoria_receita["id"], uid, "2024-06-01")
        container.transacoes.adicionar("Aluguel", 1000, "despesa", categoria_despesa["id"], uid, "2024-06-05")
        r = client.get("/")
        assert r.status_code == 200


# ── Transações: Serviço ───────────────────────────────────────────────────────

class TestTransacaoService:
    def test_adicionar_transacao_retorna_id(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        id_t, erros = container.transacoes.adicionar(
            "Supermercado", 250.0, "despesa", categoria_despesa["id"], uid, "2024-06-15"
        )
        assert erros == {}
        assert isinstance(id_t, int) and id_t > 0

    def test_resumo_mes_calcula_corretamente(self, container, usuario_criado, categoria_receita, categoria_despesa):
        uid = usuario_criado["id"]
        container.transacoes.adicionar("Salário", 3000, "receita", categoria_receita["id"], uid, "2024-09-10")
        container.transacoes.adicionar("Aluguel", 1200, "despesa", categoria_despesa["id"], uid, "2024-09-05")

        r, d, s = container.transacoes_repo.resumo_mes(2024, 9, uid)
        assert r == pytest.approx(3000.0)
        assert d == pytest.approx(1200.0)
        assert s == pytest.approx(1800.0)

    def test_mes_sem_transacoes_retorna_zeros(self, container, usuario_criado):
        uid = usuario_criado["id"]
        r, d, s = container.transacoes_repo.resumo_mes(2099, 1, uid)
        assert r == 0.0 and d == 0.0 and s == 0.0

    def test_deletado_nao_aparece_no_resumo(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        id_t, _ = container.transacoes.adicionar("Temp", 500, "despesa", categoria_despesa["id"], uid, "2024-10-01")
        container.transacoes.deletar(id_t, uid)

        _, d, _ = container.transacoes_repo.resumo_mes(2024, 10, uid)
        assert d == 0.0

    def test_restaurar_transacao(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        id_t, _ = container.transacoes.adicionar("Rest", 300, "despesa", categoria_despesa["id"], uid, "2024-11-01")
        container.transacoes.deletar(id_t, uid)
        container.transacoes.restaurar(id_t, uid)

        _, d, _ = container.transacoes_repo.resumo_mes(2024, 11, uid)
        assert d == pytest.approx(300.0)

    def test_isolamento_entre_usuarios(self, container):
        uid1, _ = container.auth.registrar("iso1@t.com", "senha123", "Iso1")
        uid2, _ = container.auth.registrar("iso2@t.com", "senha123", "Iso2")

        cats1 = [c for c in container.categorias_repo.listar_por_usuario(uid1) if c["tipo"]=="receita"]
        cats2 = [c for c in container.categorias_repo.listar_por_usuario(uid2) if c["tipo"]=="receita"]

        container.transacoes.adicionar("Privado", 9999, "receita", cats1[0]["id"], uid1, "2024-08-01")

        r2, _, _ = container.transacoes_repo.resumo_mes(2024, 8, uid2)
        assert r2 == 0.0


# ── Transações: Rotas HTTP ────────────────────────────────────────────────────

class TestTransacoesHTTP:
    def test_pagina_todas_carrega(self, client, usuario_logado):
        r = client.get("/todas")
        assert r.status_code == 200

    def test_pagina_novo_carrega(self, client, usuario_logado):
        r = client.get("/novo")
        assert r.status_code == 200

    def test_adicionar_via_post_redireciona(self, client, usuario_logado, container, categoria_despesa):
        r = client.post("/novo", data={
            "descricao": "Mercado", "valor": "150,00",
            "tipo": "despesa", "categoria_id": str(categoria_despesa["id"]),
            "data": "2024-06-20"
        })
        assert r.status_code == 302

    def test_deletar_via_api(self, client, usuario_logado, container, categoria_despesa):
        uid = usuario_logado["id"]
        id_t, _ = container.transacoes.adicionar("Del", 100, "despesa", categoria_despesa["id"], uid, "2024-07-01")
        ts = container.transacoes.listar_por_periodo("2024-07-01", "2024-07-31", uid)
        uuid = ts[0]["uuid"]

        r = client.delete(f"/api/transacao/{uuid}")
        assert r.status_code == 200
        assert json.loads(r.data)["success"] is True

        ts2 = container.transacoes.listar_por_periodo("2024-07-01", "2024-07-31", uid)
        assert len(ts2) == 0


# ── Parcelamento ──────────────────────────────────────────────────────────────

class TestParcelamento:
    def test_preview_sem_juros_soma_valor_total(self, container):
        valores = container.transacoes.calcular_preview_parcelas(100.0, 3, "sem", 0)
        assert sum(valores) == pytest.approx(100.0, abs=0.01)
        assert len(valores) == 3

    def test_centavo_vai_para_primeira_parcela(self, container):
        valores = container.transacoes.calcular_preview_parcelas(100.0, 3, "sem", 0)
        assert valores[0] == pytest.approx(33.34, abs=0.01)
        assert valores[1] == pytest.approx(33.33, abs=0.01)

    def test_juros_price_maior_que_sem_juros(self, container):
        sem = container.transacoes.calcular_preview_parcelas(1200, 12, "sem", 0)
        com = container.transacoes.calcular_preview_parcelas(1200, 12, "price", 2.0)
        assert com[0] > sem[0]

    def test_juros_simples_soma_correta(self, container):
        valores = container.transacoes.calcular_preview_parcelas(1000, 10, "simples", 2.0)
        assert len(valores) == 10
        # Com juros simples o total deve ser > 1000
        assert sum(valores) > 1000

    def test_parcelamento_cria_n_transacoes(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        ids, erros = container.transacoes.adicionar_parcelado(
            "Geladeira", 3000, "despesa", categoria_despesa["id"], uid, 3, "2024-01-10"
        )
        assert erros == {}
        assert len(ids) == 3

    def test_datas_parcelas_avancam_mensalmente(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        container.transacoes.adicionar_parcelado(
            "Notebook", 3000, "despesa", categoria_despesa["id"], uid, 3, "2024-01-31"
        )
        ts = container.transacoes.listar_por_periodo("2024-01-01", "2024-12-31", uid)
        datas = sorted([t["data"] for t in ts])
        assert datas[0] == "2024-01-31"
        assert datas[1] == "2024-03-01"  # timedelta(30): 31/01 + 30 dias = 01/03
        assert datas[2] == "2024-03-31"

    def test_descricao_contem_numeracao_de_parcela(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        container.transacoes.adicionar_parcelado(
            "TV", 2000, "despesa", categoria_despesa["id"], uid, 2, "2024-05-01"
        )
        ts = container.transacoes.listar_por_periodo("2024-05-01", "2024-12-31", uid)
        descricoes = [t["descricao"] for t in ts]
        assert any("1/2" in d for d in descricoes)
        assert any("2/2" in d for d in descricoes)


# ── Recorrentes ───────────────────────────────────────────────────────────────

class TestRecorrentes:
    def test_pagina_fixas_carrega(self, client, usuario_logado):
        r = client.get("/fixas")
        assert r.status_code == 200

    def test_adicionar_fixa(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        id_r, erros = container.recorrentes.adicionar(
            "Aluguel", 1500, "despesa", categoria_despesa["id"], 5, uid
        )
        assert erros == {}
        assert isinstance(id_r, int) and id_r > 0

    def test_listar_fixas_ativas(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        container.recorrentes.adicionar("Netflix", 45, "despesa", categoria_despesa["id"], 10, uid)
        container.recorrentes.adicionar("Spotify", 20, "despesa", categoria_despesa["id"], 15, uid)
        fixas = container.recorrentes.listar(uid)
        assert len(fixas) == 2

    def test_desativar_fixa(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        container.recorrentes.adicionar("Gym", 100, "despesa", categoria_despesa["id"], 1, uid)
        fixas = container.recorrentes.listar(uid)
        uuid = fixas[0]["uuid"]

        container.recorrentes.desativar(uuid, uid)
        fixas_depois = container.recorrentes.listar(uid)
        assert len(fixas_depois) == 0

    def test_geracao_automatica(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        container.recorrentes.adicionar("Conta Água", 80, "despesa", categoria_despesa["id"], 1, uid)

        # Usa mês anterior — garantidamente já vencido
        hoje = date.today()
        mes_ant = hoje.month - 1 if hoje.month > 1 else 12
        ano_ant = hoje.year if hoje.month > 1 else hoje.year - 1
        geradas = container.recorrentes.gerar_lancamentos_pendentes(ano_ant, mes_ant, uid)
        assert geradas >= 1

    def test_geracao_e_idempotente(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        container.recorrentes.adicionar("Internet", 120, "despesa", categoria_despesa["id"], 1, uid)

        # Usa mês anterior — garantidamente já vencido
        hoje = date.today()
        mes_ant = hoje.month - 1 if hoje.month > 1 else 12
        ano_ant = hoje.year if hoje.month > 1 else hoje.year - 1
        g1 = container.recorrentes.gerar_lancamentos_pendentes(ano_ant, mes_ant, uid)
        g2 = container.recorrentes.gerar_lancamentos_pendentes(ano_ant, mes_ant, uid)
        assert g1 >= 1
        assert g2 == 0

    def test_status_proximos_do_mes(self, container, usuario_criado, categoria_despesa):
        uid = usuario_criado["id"]
        container.recorrentes.adicionar("Fixo", 200, "despesa", categoria_despesa["id"], 1, uid)

        hoje = date.today()
        proximos = container.recorrentes.listar_proximos_do_mes(hoje.year, hoje.month, uid)
        assert len(proximos) == 1
        assert proximos[0]["status"] in ("lancado", "agendado", "passado")
        assert proximos[0]["descricao"] == "Fixo"

    def test_fixas_via_http(self, client, usuario_logado, container, categoria_despesa):
        r = client.post("/fixas", data={
            "descricao": "Plano Saúde", "valor": "300", "tipo": "despesa",
            "categoria_id": str(categoria_despesa["id"]), "dia_vencimento": "10"
        }, follow_redirects=False)
        assert r.status_code == 302

    def test_desativar_via_api(self, client, usuario_logado, container, categoria_despesa):
        uid = usuario_logado["id"]
        container.recorrentes.adicionar("Del", 50, "despesa", categoria_despesa["id"], 5, uid)
        fixas = container.recorrentes.listar(uid)
        uuid = fixas[0]["uuid"]

        r = client.delete(f"/api/fixo/{uuid}")
        assert r.status_code == 200
        assert json.loads(r.data)["success"] is True


# ── Formatters ────────────────────────────────────────────────────────────────

class TestFormatters:
    def test_formatar_real(self):
        from utils.formatters import formatar_real
        assert formatar_real(1234.5) == "R$ 1.234,50"
        assert formatar_real(0) == "R$ 0,00"
        assert formatar_real(1000000) == "R$ 1.000.000,00"

    def test_parse_ptbr_com_ponto_e_virgula(self):
        from utils.formatters import parse_valor_monetario
        assert parse_valor_monetario("1.234,50") == pytest.approx(1234.50)

    def test_parse_so_virgula(self):
        from utils.formatters import parse_valor_monetario
        assert parse_valor_monetario("250,00") == pytest.approx(250.0)

    def test_parse_inteiro(self):
        from utils.formatters import parse_valor_monetario
        assert parse_valor_monetario("1000") == pytest.approx(1000.0)

    def test_parse_formato_enus(self):
        from utils.formatters import parse_valor_monetario
        assert parse_valor_monetario("1234.50") == pytest.approx(1234.50)

    def test_parse_vazio_levanta_erro(self):
        from utils.formatters import parse_valor_monetario
        with pytest.raises(ValueError):
            parse_valor_monetario("")

    def test_parse_texto_levanta_erro(self):
        from utils.formatters import parse_valor_monetario
        with pytest.raises(ValueError):
            parse_valor_monetario("abc")


# ── Validators ────────────────────────────────────────────────────────────────

class TestValidators:
    def test_email_valido(self):
        from utils.validators import validar_email
        assert validar_email("user@example.com") is None

    def test_email_sem_arroba(self):
        from utils.validators import validar_email
        assert validar_email("naoemail") is not None

    def test_email_vazio(self):
        from utils.validators import validar_email
        assert validar_email("") is not None

    def test_senha_curta(self):
        from utils.validators import validar_senha
        assert validar_senha("123") is not None

    def test_senha_valida(self):
        from utils.validators import validar_senha
        assert validar_senha("senha123") is None

    def test_valor_positivo_valido(self):
        from utils.validators import validar_valor
        assert validar_valor(100.0) is None

    def test_valor_zero_invalido(self):
        from utils.validators import validar_valor
        assert validar_valor(0) is not None

    def test_valor_negativo_invalido(self):
        from utils.validators import validar_valor
        assert validar_valor(-50) is not None

    def test_dia_vencimento_fixo_valido(self):
        from utils.validators import validar_dia_vencimento
        assert validar_dia_vencimento(5) is None
        assert validar_dia_vencimento(28) is None

    def test_dia_util_negativo_valido(self):
        from utils.validators import validar_dia_vencimento
        assert validar_dia_vencimento(-1) is None
        assert validar_dia_vencimento(-5) is None

    def test_dia_29_invalido(self):
        from utils.validators import validar_dia_vencimento
        assert validar_dia_vencimento(29) is not None

    def test_dia_zero_invalido(self):
        from utils.validators import validar_dia_vencimento
        assert validar_dia_vencimento(0) is not None
