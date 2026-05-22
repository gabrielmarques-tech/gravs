"""
tests/test_financeiro.py — Testes automatizados do Gravs.

Como rodar:
    pytest tests/ -v
    pytest tests/ -v --cov=financeiro --cov-report=term-missing

Filosofia dos testes:
    - Cada teste tem um propósito claro e testável.
    - Fixtures criam banco em memória — zero estado residual entre testes.
    - Testa comportamento, não implementação.
    - Nomes descrevem o que DEVE acontecer, não o que o código faz.
"""

import pytest
from datetime import date, timedelta
from financeiro import Banco, CalendarioUtil, Usuario, Categoria, Transacao, Recorrente


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def banco():
    """Banco SQLite em memória — isolado por teste, sem arquivos no disco."""
    b = Banco(":memory:")
    b.init_schema()
    return b


@pytest.fixture
def calendario():
    return CalendarioUtil()


@pytest.fixture
def usuario_repo(banco):
    return Usuario(banco)


@pytest.fixture
def categoria_repo(banco):
    return Categoria(banco)


@pytest.fixture
def transacao_repo(banco, calendario):
    return Transacao(banco, calendario)


@pytest.fixture
def recorrente_repo(banco, calendario):
    return Recorrente(banco, calendario)


@pytest.fixture
def usuario_id(usuario_repo, categoria_repo):
    """Cria um usuário padrão e suas categorias para os testes."""
    uid = usuario_repo.criar_usuario("teste@exemplo.com", "senha123", "Teste")
    categoria_repo.criar_padrao(uid)
    return uid


@pytest.fixture
def categoria_id(categoria_repo, usuario_id):
    """Retorna o ID de uma categoria de despesa existente."""
    cats = categoria_repo.listar_por_usuario(usuario_id)
    despesas = [c for c in cats if c["tipo"] == "despesa"]
    return despesas[0]["id"]


# ── Testes: Usuario ──────────────────────────────────────────────────────────

class TestUsuario:
    def test_criar_usuario_retorna_id_inteiro(self, usuario_repo):
        uid = usuario_repo.criar_usuario("novo@email.com", "senha123", "Novo")
        assert isinstance(uid, int)
        assert uid > 0

    def test_criar_usuario_normaliza_email(self, usuario_repo):
        usuario_repo.criar_usuario("USUARIO@EMAIL.COM", "senha123", "User")
        row = usuario_repo.buscar_por_email("usuario@email.com")
        assert row is not None

    def test_email_duplicado_levanta_value_error(self, usuario_repo):
        usuario_repo.criar_usuario("dup@email.com", "senha123", "Dup")
        with pytest.raises(ValueError, match="já está cadastrado"):
            usuario_repo.criar_usuario("dup@email.com", "outrasenha", "Dup2")

    def test_senha_curta_levanta_value_error(self, usuario_repo):
        with pytest.raises(ValueError, match="6 caracteres"):
            usuario_repo.criar_usuario("x@x.com", "123", "X")

    def test_email_invalido_levanta_value_error(self, usuario_repo):
        with pytest.raises(ValueError, match="Email inválido"):
            usuario_repo.criar_usuario("naoehemail", "senha123", "X")

    def test_nome_vazio_levanta_value_error(self, usuario_repo):
        with pytest.raises(ValueError, match="Nome"):
            usuario_repo.criar_usuario("a@b.com", "senha123", "  ")

    def test_verificar_senha_correta_retorna_row(self, usuario_repo):
        usuario_repo.criar_usuario("auth@test.com", "minhasenha", "Auth")
        row = usuario_repo.verificar_senha("auth@test.com", "minhasenha")
        assert row is not None
        assert row["email"] == "auth@test.com"

    def test_verificar_senha_errada_retorna_none(self, usuario_repo):
        usuario_repo.criar_usuario("auth2@test.com", "correta", "Auth2")
        assert usuario_repo.verificar_senha("auth2@test.com", "errada") is None

    def test_verificar_senha_usuario_inexistente_retorna_none(self, usuario_repo):
        assert usuario_repo.verificar_senha("naoexiste@test.com", "qualquer") is None

    def test_buscar_por_id_retorna_usuario(self, usuario_repo):
        uid = usuario_repo.criar_usuario("id@test.com", "senha123", "ID")
        row = usuario_repo.buscar_por_id(uid)
        assert row is not None
        assert row["id"] == uid

    def test_buscar_por_id_inexistente_retorna_none(self, usuario_repo):
        assert usuario_repo.buscar_por_id(99999) is None


# ── Testes: Categoria ─────────────────────────────────────────────────────────

class TestCategoria:
    def test_criar_padrao_insere_categorias(self, categoria_repo, usuario_id):
        cats = categoria_repo.listar_por_usuario(usuario_id)
        assert len(cats) > 0

    def test_categorias_tem_receitas_e_despesas(self, categoria_repo, usuario_id):
        cats = categoria_repo.listar_por_usuario(usuario_id)
        tipos = {c["tipo"] for c in cats}
        assert "receita" in tipos
        assert "despesa" in tipos

    def test_criar_padrao_idempotente(self, categoria_repo, usuario_id):
        """Chamar criar_padrao duas vezes não duplica categorias."""
        n1 = len(categoria_repo.listar_por_usuario(usuario_id))
        categoria_repo.criar_padrao(usuario_id)
        n2 = len(categoria_repo.listar_por_usuario(usuario_id))
        assert n1 == n2

    def test_categorias_isoladas_por_usuario(self, categoria_repo, usuario_repo):
        uid1 = usuario_repo.criar_usuario("u1@t.com", "senha123", "U1")
        uid2 = usuario_repo.criar_usuario("u2@t.com", "senha123", "U2")
        categoria_repo.criar_padrao(uid1)
        # uid2 sem categorias
        cats2 = categoria_repo.listar_por_usuario(uid2)
        assert len(cats2) == 0


# ── Testes: Transacao ─────────────────────────────────────────────────────────

class TestTransacao:
    def test_adicionar_retorna_id(self, transacao_repo, usuario_id, categoria_id):
        tid = transacao_repo.adicionar("Salário", 5000.0, "receita", categoria_id, usuario_id)
        assert isinstance(tid, int) and tid > 0

    def test_valor_negativo_levanta_erro(self, transacao_repo, usuario_id, categoria_id):
        with pytest.raises(ValueError, match="maior que zero"):
            transacao_repo.adicionar("Teste", -100.0, "despesa", categoria_id, usuario_id)

    def test_tipo_invalido_levanta_erro(self, transacao_repo, usuario_id, categoria_id):
        with pytest.raises(ValueError, match="receita.*despesa"):
            transacao_repo.adicionar("Teste", 100.0, "transferencia", categoria_id, usuario_id)

    def test_descricao_vazia_levanta_erro(self, transacao_repo, usuario_id, categoria_id):
        with pytest.raises(ValueError, match="Descrição"):
            transacao_repo.adicionar("  ", 100.0, "despesa", categoria_id, usuario_id)

    def test_data_invalida_levanta_erro(self, transacao_repo, usuario_id, categoria_id):
        with pytest.raises(ValueError, match="Data inválida"):
            transacao_repo.adicionar("Teste", 100.0, "despesa", categoria_id, usuario_id, "31-12-2024")

    def test_resumo_mes_saldo_correto(self, transacao_repo, usuario_id, categoria_id):
        transacao_repo.adicionar("Receita", 3000.0, "receita", categoria_id, usuario_id, "2024-06-10")
        transacao_repo.adicionar("Despesa", 1200.0, "despesa", categoria_id, usuario_id, "2024-06-15")
        receitas, despesas, saldo = transacao_repo.resumo_mes(2024, 6, usuario_id)
        assert receitas == pytest.approx(3000.0)
        assert despesas == pytest.approx(1200.0)
        assert saldo == pytest.approx(1800.0)

    def test_resumo_mes_vazio_retorna_zeros(self, transacao_repo, usuario_id):
        receitas, despesas, saldo = transacao_repo.resumo_mes(2099, 1, usuario_id)
        assert receitas == 0.0
        assert despesas == 0.0
        assert saldo == 0.0

    def test_saldo_total_acumulado(self, transacao_repo, usuario_id, categoria_id):
        transacao_repo.adicionar("R1", 1000.0, "receita", categoria_id, usuario_id, "2024-01-10")
        transacao_repo.adicionar("D1", 300.0,  "despesa", categoria_id, usuario_id, "2024-02-10")
        assert transacao_repo.saldo_total(usuario_id) == pytest.approx(700.0)

    def test_deletar_logico_nao_aparece_no_resumo(self, transacao_repo, usuario_id, categoria_id):
        tid = transacao_repo.adicionar("Despesa", 500.0, "despesa", categoria_id, usuario_id, "2024-03-10")
        transacao_repo.deletar(tid, usuario_id)
        _, despesas, _ = transacao_repo.resumo_mes(2024, 3, usuario_id)
        assert despesas == 0.0

    def test_restaurar_reaparece_no_resumo(self, transacao_repo, usuario_id, categoria_id):
        tid = transacao_repo.adicionar("Despesa", 500.0, "despesa", categoria_id, usuario_id, "2024-04-10")
        transacao_repo.deletar(tid, usuario_id)
        transacao_repo.restaurar(tid, usuario_id)
        _, despesas, _ = transacao_repo.resumo_mes(2024, 4, usuario_id)
        assert despesas == pytest.approx(500.0)

    def test_isolamento_entre_usuarios(self, transacao_repo, usuario_repo, categoria_repo, categoria_id, usuario_id):
        uid2 = usuario_repo.criar_usuario("outro@t.com", "senha123", "Outro")
        categoria_repo.criar_padrao(uid2)
        cats2 = categoria_repo.listar_por_usuario(uid2)
        cat2 = [c for c in cats2 if c["tipo"] == "receita"][0]["id"]

        transacao_repo.adicionar("Receita U1", 9999.0, "receita", categoria_id, usuario_id, "2024-07-01")
        transacao_repo.adicionar("Receita U2", 1.0, "receita", cat2, uid2, "2024-07-01")

        r1, _, _ = transacao_repo.resumo_mes(2024, 7, usuario_id)
        r2, _, _ = transacao_repo.resumo_mes(2024, 7, uid2)
        assert r1 == pytest.approx(9999.0)
        assert r2 == pytest.approx(1.0)

    def test_editar_transacao(self, transacao_repo, usuario_id, categoria_id):
        tid = transacao_repo.adicionar("Original", 100.0, "despesa", categoria_id, usuario_id, "2024-05-01")
        ok = transacao_repo.editar(tid, usuario_id, descricao="Editada", valor=200.0)
        assert ok
        t = transacao_repo.buscar_por_uuid(
            # busca pelo id via listar
            transacao_repo.listar_por_periodo("2024-05-01", "2024-05-01", usuario_id)[0]["uuid"],
            usuario_id
        )
        assert t["descricao"] == "Editada"
        assert t["valor"] == pytest.approx(200.0)

    def test_editar_sem_campos_retorna_false(self, transacao_repo, usuario_id, categoria_id):
        tid = transacao_repo.adicionar("Sem edição", 100.0, "despesa", categoria_id, usuario_id)
        assert transacao_repo.editar(tid, usuario_id) is False


# ── Testes: Parcelamento ──────────────────────────────────────────────────────

class TestParcelamento:
    def test_parcelamento_cria_n_transacoes(self, transacao_repo, usuario_id, categoria_id):
        ids = transacao_repo.adicionar_parcelado(
            "Notebook", 3000.0, "despesa", categoria_id, usuario_id, 3, "2024-01-15"
        )
        assert len(ids) == 3

    def test_soma_parcelas_sem_juros_igual_total(self, transacao_repo):
        valores = transacao_repo.calcular_preview_parcelas(100.0, 3, "sem", 0)
        assert sum(valores) == pytest.approx(100.0, abs=0.01)

    def test_primeira_parcela_absorve_arredondamento(self, transacao_repo):
        # 100 / 3 = 33.333... → [33.34, 33.33, 33.33]
        valores = transacao_repo.calcular_preview_parcelas(100.0, 3, "sem", 0)
        assert valores[0] == pytest.approx(33.34)
        assert valores[1] == pytest.approx(33.33)

    def test_parcelas_com_juros_price_tem_valor_maior(self, transacao_repo):
        sem_juros = transacao_repo.calcular_preview_parcelas(1200.0, 12, "sem", 0)
        com_juros = transacao_repo.calcular_preview_parcelas(1200.0, 12, "price", 2.0)
        assert com_juros[0] > sem_juros[0]

    def test_parcelamento_menos_de_2_levanta_erro(self, transacao_repo, usuario_id, categoria_id):
        with pytest.raises(ValueError, match="2 e 60"):
            transacao_repo.adicionar_parcelado(
                "Teste", 100.0, "despesa", categoria_id, usuario_id, 1
            )

    def test_parcelamento_mais_de_60_levanta_erro(self, transacao_repo, usuario_id, categoria_id):
        with pytest.raises(ValueError, match="2 e 60"):
            transacao_repo.adicionar_parcelado(
                "Teste", 100.0, "despesa", categoria_id, usuario_id, 61
            )

    def test_datas_das_parcelas_avancam_mensalmente(self, transacao_repo, usuario_id, categoria_id):
        ids = transacao_repo.adicionar_parcelado(
            "Mensal", 300.0, "despesa", categoria_id, usuario_id, 3, "2024-01-31"
        )
        # Jan 31, Fev 29 (2024 é bissexto), Mar 31
        rows = transacao_repo.listar_por_periodo("2024-01-01", "2024-12-31", usuario_id)
        datas = sorted([r["data"] for r in rows])
        assert datas[0] == "2024-01-31"
        assert datas[1] == "2024-02-29"  # fevereiro tem 29 dias em 2024
        assert datas[2] == "2024-03-31"

    def test_descricao_parcela_contem_numeracao(self, transacao_repo, usuario_id, categoria_id):
        transacao_repo.adicionar_parcelado(
            "TV", 1000.0, "despesa", categoria_id, usuario_id, 2, "2024-06-01"
        )
        rows = transacao_repo.listar_por_periodo("2024-06-01", "2024-07-31", usuario_id)
        descricoes = [r["descricao"] for r in rows]
        assert any("1/2" in d for d in descricoes)
        assert any("2/2" in d for d in descricoes)


# ── Testes: Recorrente ────────────────────────────────────────────────────────

class TestRecorrente:
    def test_adicionar_recorrente_retorna_id(self, recorrente_repo, usuario_id, categoria_id):
        rid = recorrente_repo.adicionar("Aluguel", 1500.0, "despesa", categoria_id, 5, usuario_id)
        assert isinstance(rid, int) and rid > 0

    def test_dia_invalido_levanta_erro(self, recorrente_repo, usuario_id, categoria_id):
        with pytest.raises(ValueError, match="Dia deve ser"):
            recorrente_repo.adicionar("Teste", 100.0, "despesa", categoria_id, 29, usuario_id)

    def test_dia_util_negativo_valido(self, recorrente_repo, usuario_id, categoria_id):
        # -1 = 1º dia útil
        rid = recorrente_repo.adicionar("Salário", 5000.0, "receita", categoria_id, -1, usuario_id)
        assert rid > 0

    def test_desativar_remove_da_listagem(self, recorrente_repo, usuario_id, categoria_id):
        rid = recorrente_repo.adicionar("Agua", 80.0, "despesa", categoria_id, 10, usuario_id)
        row = recorrente_repo.buscar_por_uuid(
            recorrente_repo.listar_todos(usuario_id)[0]["uuid"], usuario_id
        )
        uuid_rec = row["uuid"]
        recorrente_repo.desativar(uuid_rec, usuario_id)
        assert recorrente_repo.buscar_por_uuid(uuid_rec, usuario_id) is None

    def test_gerar_transacoes_cria_lancamentos(
        self, recorrente_repo, transacao_repo, usuario_id, categoria_id
    ):
        # Vencimento no dia 1 — com certeza já passou para qualquer mês atual
        recorrente_repo.adicionar("Conta Fixa", 200.0, "despesa", categoria_id, 1, usuario_id)
        hoje = date.today()
        geradas = recorrente_repo.gerar_transacoes_mes(hoje.year, hoje.month, usuario_id, transacao_repo)
        assert geradas >= 1

    def test_gerar_transacoes_nao_duplica(
        self, recorrente_repo, transacao_repo, usuario_id, categoria_id
    ):
        recorrente_repo.adicionar("Conta", 100.0, "despesa", categoria_id, 1, usuario_id)
        hoje = date.today()
        geradas1 = recorrente_repo.gerar_transacoes_mes(hoje.year, hoje.month, usuario_id, transacao_repo)
        geradas2 = recorrente_repo.gerar_transacoes_mes(hoje.year, hoje.month, usuario_id, transacao_repo)
        assert geradas1 >= 1
        assert geradas2 == 0  # segunda chamada não gera nada

    def test_listar_proximos_ordenados_por_data(
        self, recorrente_repo, usuario_id, categoria_id
    ):
        recorrente_repo.adicionar("C", 100.0, "despesa", categoria_id, 20, usuario_id)
        recorrente_repo.adicionar("A", 100.0, "despesa", categoria_id, 5,  usuario_id)
        recorrente_repo.adicionar("B", 100.0, "despesa", categoria_id, 10, usuario_id)
        hoje = date.today()
        lista = recorrente_repo.listar_proximos_do_mes(hoje.year, hoje.month, usuario_id)
        datas = [item["data_obj"] for item in lista]
        assert datas == sorted(datas)


# ── Testes: CalendarioUtil ────────────────────────────────────────────────────

class TestCalendario:
    def test_sabado_nao_e_dia_util(self, calendario):
        sabado = date(2024, 6, 1)  # sábado
        assert not calendario.eh_dia_util(sabado)

    def test_domingo_nao_e_dia_util(self, calendario):
        domingo = date(2024, 6, 2)  # domingo
        assert not calendario.eh_dia_util(domingo)

    def test_segunda_feira_e_dia_util(self, calendario):
        segunda = date(2024, 6, 3)  # segunda
        assert calendario.eh_dia_util(segunda)

    def test_natal_nao_e_dia_util(self, calendario):
        natal = date(2024, 12, 25)
        assert not calendario.eh_dia_util(natal)

    def test_proximo_dia_util_passa_de_fim_de_semana(self, calendario):
        sabado = date(2024, 6, 1)
        util = calendario.proximo_dia_util(sabado)
        assert util == date(2024, 6, 3)  # segunda

    def test_primeiro_dia_util_de_janeiro_2024(self, calendario):
        # 01/01/2024 = feriado (Ano Novo), dia útil = 02/01 (terça)
        primeiro_util = calendario.dia_util_do_mes(2024, 1, 1)
        assert primeiro_util == date(2024, 1, 2)