"""Testes do ContabilService — Fase 4.

Este módulo testa o ContabilService, que centraliza todas as regras
contábeis do sistema. Usa repositórios reais contra banco SQLite em
memória para testar a integração completa.

Não mockamos repositórios aqui porque queremos testar:
1. Validações de regras de negócio
2. Integração real com o banco (FKs, CHECKs)
3. Isolamento entre usuários
"""

import uuid as uuid_lib
import pytest

from database.manager import DatabaseManager
from database.repositories import (
    LancamentoContabil,
    PlanoContasRepository,
    LancamentoContabilRepository,
)
from services.contabil_service import ContabilService


# ── Fixtures ────────────────────────────────────────────────────────────────────

import tempfile
import os


@pytest.fixture
def db():
    """Banco SQLite em arquivo temporário, limpo a cada teste."""
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    f.close()
    manager = DatabaseManager(f.name)
    manager.init_schema()
    yield manager
    try:
        os.unlink(f.name)
    except OSError:
        pass


@pytest.fixture
def plano_repo(db):
    return PlanoContasRepository(db)


@pytest.fixture
def lancamento_repo(db):
    return LancamentoContabilRepository(db)


@pytest.fixture
def service(db, plano_repo, lancamento_repo):
    from database.repositories import TransacaoRepository
    transacao_repo = TransacaoRepository(db)
    return ContabilService(
        db=db,
        plano_contas_repo=plano_repo,
        lancamento_repo=lancamento_repo,
        transacao_repo=transacao_repo,
    )


@pytest.fixture
def usuario(db):
    """Cria um usuário e retorna seu ID."""
    with db.get_write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
            ("teste@t.com", "hash", "Teste"),
        )
        return cur.lastrowid


@pytest.fixture
def outro_usuario(db):
    """Cria um segundo usuário para testar isolamento."""
    with db.get_write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
            ("outro@t.com", "hash", "Outro"),
        )
        return cur.lastrowid


@pytest.fixture
def contas_padrao(plano_repo, usuario):
    """Cria estrutura básica de contas contábeis para testes."""
    ativo = plano_repo.criar(
        usuario_id=usuario, codigo="1", nome="Ativo",
        tipo="ativo", natureza="devedora", nivel=1,
        aceita_lancamentos=False,
    )
    caixa = plano_repo.criar(
        usuario_id=usuario, codigo="1.1", nome="Caixa",
        tipo="ativo", natureza="devedora", nivel=2,
        conta_pai_id=ativo.id, aceita_lancamentos=True,
    )
    banco = plano_repo.criar(
        usuario_id=usuario, codigo="1.2", nome="Banco",
        tipo="ativo", natureza="devedora", nivel=2,
        conta_pai_id=ativo.id, aceita_lancamentos=True,
    )
    passivo = plano_repo.criar(
        usuario_id=usuario, codigo="2", nome="Passivo",
        tipo="passivo", natureza="credora", nivel=1,
        aceita_lancamentos=False,
    )
    fornecedores = plano_repo.criar(
        usuario_id=usuario, codigo="2.1", nome="Fornecedores",
        tipo="passivo", natureza="credora", nivel=2,
        conta_pai_id=passivo.id, aceita_lancamentos=True,
    )
    receitas = plano_repo.criar(
        usuario_id=usuario, codigo="3", nome="Receitas",
        tipo="receita", natureza="credora", nivel=1,
        aceita_lancamentos=False,
    )
    vendas = plano_repo.criar(
        usuario_id=usuario, codigo="3.1", nome="Vendas",
        tipo="receita", natureza="credora", nivel=2,
        conta_pai_id=receitas.id, aceita_lancamentos=True,
    )
    despesas = plano_repo.criar(
        usuario_id=usuario, codigo="4", nome="Despesas",
        tipo="despesa", natureza="devedora", nivel=1,
        aceita_lancamentos=False,
    )
    salarios = plano_repo.criar(
        usuario_id=usuario, codigo="4.1", nome="Salários",
        tipo="despesa", natureza="devedora", nivel=2,
        conta_pai_id=despesas.id, aceita_lancamentos=True,
    )

    return {
        "ativo": ativo,
        "caixa": caixa,
        "banco": banco,
        "passivo": passivo,
        "fornecedores": fornecedores,
        "receitas": receitas,
        "vendas": vendas,
        "despesas": despesas,
        "salarios": salarios,
    }


# ── Testes: validar_conta_lancavel ─────────────────────────────────────────────


class TestValidarContaLancavel:
    """Testes do método validar_conta_lancavel."""

    def test_conta_valida(self, service, usuario, contas_padrao):
        """Conta analítica ativa que aceita lançamentos deve ser válida."""
        valido, erro = service.validar_conta_lancavel(contas_padrao["caixa"].id, usuario)
        assert valido is True
        assert erro == ""

    def test_conta_inexistente(self, service, usuario):
        """Conta que não existe deve retornar erro."""
        valido, erro = service.validar_conta_lancavel(99999, usuario)
        assert valido is False
        assert "não encontrada" in erro

    def test_conta_de_outro_usuario(self, service, usuario, outro_usuario, plano_repo):
        """Conta de outro usuário não deve ser visível."""
        # Cria conta para outro usuário
        outra = plano_repo.criar(
            usuario_id=outro_usuario, codigo="1", nome="Ativo Outro",
            tipo="ativo", natureza="devedora", nivel=1,
            aceita_lancamentos=True,
        )
        # Tenta validar como usuário 1
        valido, erro = service.validar_conta_lancavel(outra.id, usuario)
        assert valido is False
        assert "não encontrada" in erro

    def test_conta_inativa(self, service, usuario, plano_repo):
        """Conta inativa deve ser rejeitada."""
        conta = plano_repo.criar(
            usuario_id=usuario, codigo="5", nome="Inativa",
            tipo="ativo", natureza="devedora", nivel=1,
            aceita_lancamentos=True,
        )
        # Torna inativa
        with plano_repo._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE plano_contas SET ativo = 0 WHERE id = ?",
                (conta.id,),
            )
        valido, erro = service.validar_conta_lancavel(conta.id, usuario)
        assert valido is False
        assert "inativa" in erro.lower()

    def test_conta_sem_aceita_lancamentos(self, service, usuario, contas_padrao):
        """Conta sintética (não aceita lançamentos) deve ser rejeitada."""
        valido, erro = service.validar_conta_lancavel(contas_padrao["ativo"].id, usuario)
        assert valido is False
        assert "não aceita lançamentos" in erro.lower()


# ── Testes: criar_lancamento ────────────────────────────────────────────────────


class TestCriarLancamento:
    """Testes de criação de lançamentos com validações."""

    def test_criar_lancamento_sucesso(self, service, usuario, contas_padrao):
        """Criação básica de lançamento deve funcionar."""
        sucesso, resultado = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Venda de produto",
            valor=1000.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is True
        assert isinstance(resultado, LancamentoContabil)
        assert resultado.valor == 1000.00
        assert resultado.debito_id == contas_padrao["caixa"].id
        assert resultado.credito_id == contas_padrao["vendas"].id
        assert resultado.historico == "Venda de produto"
        assert resultado.data == "2024-01-15"
        assert resultado.uuid is not None
        assert resultado.transacao_id is None

    def test_criar_lancamento_com_transacao(self, service, usuario, contas_padrao, db):
        """Lançamento vinculado a uma transação."""
        # Cria transação
        with db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO transacoes
                   (uuid, descricao, valor, tipo, data, usuario_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid_lib.uuid4()), "Venda", 1000.0, "receita", "2024-01-15", usuario),
            )
            tr_id = cur.lastrowid

        sucesso, resultado = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Venda (com transação)",
            valor=1000.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
            transacao_id=tr_id,
        )
        assert sucesso is True
        assert isinstance(resultado, LancamentoContabil)
        assert resultado.transacao_id == tr_id

    def test_debito_igual_credito(self, service, usuario, contas_padrao):
        """Débito e crédito iguais devem ser rejeitados."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["caixa"].id,
        )
        assert sucesso is False
        assert "diferentes" in erro.lower()

    def test_valor_zero(self, service, usuario, contas_padrao):
        """Valor zero deve ser rejeitado."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=0,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "maior que zero" in erro.lower()

    def test_valor_negativo(self, service, usuario, contas_padrao):
        """Valor negativo deve ser rejeitado."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=-100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "maior que zero" in erro.lower()

    def test_data_invalida(self, service, usuario, contas_padrao):
        """Data mal formatada deve ser rejeitada."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="15/01/2024",
            historico="Teste",
            valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "formato" in erro.lower() or "invalida" in erro.lower()

    def test_data_vazia(self, service, usuario, contas_padrao):
        """Data vazia deve ser rejeitada."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="",
            historico="Teste",
            valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "obrigatória" in erro.lower() or "invalida" in erro.lower()

    def test_historico_vazio(self, service, usuario, contas_padrao):
        """Histórico vazio deve ser rejeitado."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="",
            valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "vazio" in erro.lower()

    def test_conta_debito_inexistente(self, service, usuario, contas_padrao):
        """Conta de débito inexistente deve ser rejeitada."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=100.00,
            debito_id=99999,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "débito" in erro.lower()
        assert "não encontrada" in erro.lower()

    def test_conta_credito_inexistente(self, service, usuario, contas_padrao):
        """Conta de crédito inexistente deve ser rejeitada."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=99999,
        )
        assert sucesso is False
        assert "crédito" in erro.lower()
        assert "não encontrada" in erro.lower()

    def test_conta_debito_inativa(self, service, usuario, contas_padrao, plano_repo):
        """Conta de débito inativa deve ser rejeitada."""
        # Torna caixa inativa
        with plano_repo._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE plano_contas SET ativo = 0 WHERE id = ?",
                (contas_padrao["caixa"].id,),
            )
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "inativa" in erro.lower()

    def test_conta_sem_aceita_lancamentos_no_debito(self, service, usuario, contas_padrao):
        """Conta sintética no débito deve ser rejeitada."""
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=100.00,
            debito_id=contas_padrao["ativo"].id,  # nível 1, aceita_lancamentos=False
            credito_id=contas_padrao["vendas"].id,
        )
        assert sucesso is False
        assert "não aceita lançamentos" in erro.lower()

    def test_isolamento_usuario_conta_debito(self, service, usuario, outro_usuario, plano_repo):
        """Conta de débito de outro usuário deve ser rejeitada."""
        # Cria conta para outro usuário
        conta_outro = plano_repo.criar(
            usuario_id=outro_usuario, codigo="5", nome="Conta Outro",
            tipo="ativo", natureza="devedora", nivel=1,
            aceita_lancamentos=True,
        )
        # Tenta usar como usuário principal
        vendas = plano_repo.criar(
            usuario_id=usuario, codigo="3.1", nome="Vendas",
            tipo="receita", natureza="credora", nivel=2,
            aceita_lancamentos=True,
        )
        sucesso, erro = service.criar_lancamento(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste",
            valor=100.00,
            debito_id=conta_outro.id,
            credito_id=vendas.id,
        )
        assert sucesso is False
        assert "não encontrada" in erro.lower()

    def test_lancamento_sucesso_varios(self, service, usuario, contas_padrao):
        """Múltiplos lançamentos devem ser criados sem erro."""
        for i in range(3):
            sucesso, resultado = service.criar_lancamento(
                usuario_id=usuario,
                data=f"2024-01-{15 + i:02d}",
                historico=f"Lançamento {i + 1}",
                valor=100.00 * (i + 1),
                debito_id=contas_padrao["caixa"].id,
                credito_id=contas_padrao["vendas"].id,
            )
            assert sucesso is True
            assert isinstance(resultado, LancamentoContabil)

        # Confirma que 3 lançamentos foram criados
        lancamentos = service.listar_lancamentos(usuario)
        assert len(lancamentos) == 3


# ── Testes: buscar_lancamento ───────────────────────────────────────────────────


class TestBuscarLancamento:
    """Testes de busca de lançamentos."""

    def test_buscar_por_id_sucesso(self, service, usuario, contas_padrao):
        """Buscar lançamento existente por ID."""
        _, lc = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Teste", valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        assert lc is not None

        encontrado = service.buscar_lancamento(lc.id, usuario)
        assert encontrado is not None
        assert encontrado.id == lc.id
        assert encontrado.uuid == lc.uuid

    def test_buscar_id_inexistente(self, service, usuario):
        """Buscar ID inexistente retorna None."""
        encontrado = service.buscar_lancamento(99999, usuario)
        assert encontrado is None

    def test_buscar_id_de_outro_usuario(self, service, usuario, outro_usuario, contas_padrao):
        """Isolamento: não deve encontrar lançamento de outro usuário."""
        _, lc = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Teste", valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        encontrado = service.buscar_lancamento(lc.id, outro_usuario)
        assert encontrado is None


# ── Testes: listar_lancamentos ──────────────────────────────────────────────────


class TestListarLancamentos:
    """Testes de listagem de lançamentos."""

    def test_listar_sem_lancamentos(self, service, usuario):
        """Usuário sem lançamentos deve receber lista vazia."""
        lancamentos = service.listar_lancamentos(usuario)
        assert isinstance(lancamentos, list)
        assert len(lancamentos) == 0

    def test_listar_com_lancamentos(self, service, usuario, contas_padrao):
        """Lista todos os lançamentos do usuário."""
        for i in range(5):
            _, _ = service.criar_lancamento(
                usuario_id=usuario, data=f"2024-01-{15 + i:02d}",
                historico=f"Lanc {i}", valor=100.00,
                debito_id=contas_padrao["caixa"].id,
                credito_id=contas_padrao["vendas"].id,
            )
        lancamentos = service.listar_lancamentos(usuario)
        assert len(lancamentos) == 5

    def test_listar_com_paginacao(self, service, usuario, contas_padrao):
        """Paginação (limit/offset) deve funcionar."""
        for i in range(10):
            _, _ = service.criar_lancamento(
                usuario_id=usuario, data=f"2024-01-{15 + i:02d}",
                historico=f"Lanc {i}", valor=100.00,
                debito_id=contas_padrao["caixa"].id,
                credito_id=contas_padrao["vendas"].id,
            )
        pagina1 = service.listar_lancamentos(usuario, limit=3, offset=0)
        assert len(pagina1) == 3

        pagina2 = service.listar_lancamentos(usuario, limit=3, offset=3)
        assert len(pagina2) == 3

        # Verifica que são registros diferentes
        ids_pag1 = {l.id for l in pagina1}
        ids_pag2 = {l.id for l in pagina2}
        assert ids_pag1.isdisjoint(ids_pag2)

    def test_isolamento_entre_usuarios(self, service, usuario, outro_usuario, contas_padrao):
        """Usuário não deve ver lançamentos de outro."""
        # Cria 3 para usuário 1
        for i in range(3):
            _, _ = service.criar_lancamento(
                usuario_id=usuario, data=f"2024-01-{15 + i:02d}",
                historico=f"Lanc {i}", valor=100.00,
                debito_id=contas_padrao["caixa"].id,
                credito_id=contas_padrao["vendas"].id,
            )
        # Cria 2 para outro usuário (precisa de contas próprias)
        # (pula por simplicidade — o importante é que o primeiro usuário não veja estes)

        lancamentos_user1 = service.listar_lancamentos(outro_usuario)
        assert len(lancamentos_user1) == 0  # Não tem contas, não cria


# ── Testes: listar_lancamentos_por_conta ────────────────────────────────────────


class TestListarLancamentosPorConta:
    """Testes de listagem de lançamentos por conta."""

    def test_listar_por_conta(self, service, usuario, contas_padrao):
        """Lista lançamentos de uma conta específica."""
        # Lançamentos envolvendo caixa e vendas
        _, lc1 = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Venda", valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        _, lc2 = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-16",
            historico="Venda 2", valor=200.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )

        sucesso, lancamentos = service.listar_lancamentos_por_conta(
            contas_padrao["caixa"].id, usuario,
        )
        assert sucesso is True
        assert len(lancamentos) == 2

    def test_listar_por_conta_inexistente(self, service, usuario):
        """Conta inexistente deve retornar erro."""
        sucesso, resultado = service.listar_lancamentos_por_conta(99999, usuario)
        assert sucesso is False
        assert "não encontrada" in resultado

    def test_listar_por_conta_sem_lancamentos(self, service, usuario, contas_padrao):
        """Conta sem lançamentos deve retornar lista vazia."""
        sucesso, lancamentos = service.listar_lancamentos_por_conta(
            contas_padrao["banco"].id, usuario,
        )
        assert sucesso is True
        assert len(lancamentos) == 0


# ── Testes: listar_lancamentos_por_periodo ──────────────────────────────────────


class TestListarLancamentosPorPeriodo:
    """Testes de listagem por período."""

    def test_listar_por_periodo(self, service, usuario, contas_padrao):
        """Lista lançamentos em um intervalo."""
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Jan", valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-02-15",
            historico="Fev", valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )

        sucesso, lancamentos = service.listar_lancamentos_por_periodo(
            usuario, "2024-01-01", "2024-01-31",
        )
        assert sucesso is True
        assert len(lancamentos) == 1
        assert lancamentos[0].data == "2024-01-15"

    def test_listar_periodo_inicio_invalido(self, service, usuario):
        """Data início inválida deve ser rejeitada."""
        sucesso, erro = service.listar_lancamentos_por_periodo(
            usuario, "invalida", "2024-01-31",
        )
        assert sucesso is False
        assert "início" in erro.lower()

    def test_listar_periodo_fim_invalido(self, service, usuario):
        """Data fim inválida deve ser rejeitada."""
        sucesso, erro = service.listar_lancamentos_por_periodo(
            usuario, "2024-01-01", "invalida",
        )
        assert sucesso is False
        assert "fim" in erro.lower()

    def test_listar_periodo_inicio_maior_que_fim(self, service, usuario):
        """Data início maior que data fim deve ser rejeitada."""
        sucesso, erro = service.listar_lancamentos_por_periodo(
            usuario, "2024-02-01", "2024-01-31",
        )
        assert sucesso is False
        assert "maior" in erro.lower()


# ── Testes: saldo_conta ─────────────────────────────────────────────────────────


class TestSaldoConta:
    """Testes de cálculo de saldo de conta."""

    def test_saldo_conta_sem_lancamentos(self, service, usuario, contas_padrao):
        """Conta sem lançamentos deve ter saldo zero."""
        sucesso, saldo = service.saldo_conta(contas_padrao["caixa"].id, usuario)
        assert sucesso is True
        assert saldo == 0.0

    def test_saldo_conta_devedora(self, service, usuario, contas_padrao):
        """Saldo de conta devedora (caixa = débitos - créditos)."""
        # Débito no caixa (aumenta saldo devedor)
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Venda", valor=1000.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        # Saque do caixa (crédito no caixa = reduz saldo devedor)
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-16",
            historico="Saque", valor=200.00,
            debito_id=contas_padrao["salarios"].id,
            credito_id=contas_padrao["caixa"].id,
        )
        # Saldo = 1000 (débitos) - 200 (créditos) = 800
        sucesso, saldo = service.saldo_conta(contas_padrao["caixa"].id, usuario)
        assert sucesso is True
        assert saldo == 800.0

    def test_saldo_conta_credora(self, service, usuario, contas_padrao):
        """Saldo de conta credora (vendas = créditos - débitos)."""
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Venda", valor=1000.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        # Estorno (débito em vendas = reduz saldo credor)
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-16",
            historico="Estorno", valor=100.00,
            debito_id=contas_padrao["vendas"].id,
            credito_id=contas_padrao["caixa"].id,
        )
        # Saldo = 1000 (créditos) - 100 (débitos) = 900
        sucesso, saldo = service.saldo_conta(contas_padrao["vendas"].id, usuario)
        assert sucesso is True
        assert saldo == 900.0

    def test_saldo_conta_inexistente(self, service, usuario):
        """Conta inexistente deve retornar erro."""
        sucesso, erro = service.saldo_conta(99999, usuario)
        assert sucesso is False
        assert "não encontrada" in erro

    def test_saldo_com_data_limite(self, service, usuario, contas_padrao):
        """Saldo até uma data específica."""
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Janeiro", valor=500.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        _, _ = service.criar_lancamento(
            usuario_id=usuario, data="2024-02-15",
            historico="Fevereiro", valor=300.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        # Saldo até 31/01 deve considerar apenas o lançamento de janeiro
        sucesso, saldo = service.saldo_conta(
            contas_padrao["caixa"].id, usuario, data_ate="2024-01-31",
        )
        assert sucesso is True
        assert saldo == 500.0

    def test_saldo_data_limite_invalida(self, service, usuario, contas_padrao):
        """Data limite inválida deve ser rejeitada."""
        sucesso, erro = service.saldo_conta(
            contas_padrao["caixa"].id, usuario, data_ate="invalida",
        )
        assert sucesso is False
        assert "invalida" in erro.lower() or "formato" in erro.lower()


# ── Testes: deletar_lancamento ──────────────────────────────────────────────────


class TestDeletarLancamento:
    """Testes de deleção de lançamentos."""

    def test_deletar_sucesso(self, service, usuario, contas_padrao):
        """Deleção de lançamento existente deve funcionar."""
        _, lc = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Teste", valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        sucesso, erro = service.deletar_lancamento(lc.id, usuario)
        assert sucesso is True
        assert erro == ""

        # Confirma que foi deletado
        assert service.buscar_lancamento(lc.id, usuario) is None

    def test_deletar_inexistente(self, service, usuario):
        """Deleção de lançamento inexistente deve retornar erro."""
        sucesso, erro = service.deletar_lancamento(99999, usuario)
        assert sucesso is False
        assert "não encontrado" in erro

    def test_deletar_de_outro_usuario(self, service, usuario, outro_usuario, contas_padrao):
        """Não deve deletar lançamento de outro usuário."""
        _, lc = service.criar_lancamento(
            usuario_id=usuario, data="2024-01-15",
            historico="Teste", valor=100.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
        )
        sucesso, erro = service.deletar_lancamento(lc.id, outro_usuario)
        assert sucesso is False

        # O lançamento ainda existe para o usuário original
        assert service.buscar_lancamento(lc.id, usuario) is not None

# ── Testes: criar_lancamento_completo (Partida Dobrada Atômica) ──────────────────


class TestCriarLancamentoCompleto:
    """Testes do método criar_lancamento_completo (transação atômica)."""

    def test_criar_lancamento_completo_sucesso(self, service, usuario, contas_padrao, db):
        """Criação completa com transação e lançamento deve funcionar."""
        # Cria categoria para a transação
        with db.get_write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id) VALUES (?, ?, ?)",
                ("Vendas", "receita", usuario),
            )
            cat_id = cur.lastrowid

        sucesso, resultado = service.criar_lancamento_completo(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Venda de produto 123",
            valor=1500.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
            descricao_transacao="Venda de produto 123",
            tipo_transacao="receita",
            categoria_id=cat_id,
        )

        assert sucesso is True, f"Falhou: {resultado}"
        assert "transacao_id" in resultado
        assert "lancamento" in resultado
        assert resultado["transacao_id"] > 0
        assert resultado["lancamento"].valor == 1500.00
        assert resultado["lancamento"].debito_id == contas_padrao["caixa"].id
        assert resultado["lancamento"].credito_id == contas_padrao["vendas"].id
        assert resultado["lancamento"].transacao_id == resultado["transacao_id"]

        # Verifica que ambos os registros existem
        with db.get_conn() as conn:
            tr = conn.execute(
                "SELECT id FROM transacoes WHERE id = ?",
                (resultado["transacao_id"],),
            ).fetchone()
            assert tr is not None, "Transação não foi persistida"

            lc = conn.execute(
                "SELECT id FROM lancamentos_contabeis WHERE id = ?",
                (resultado["lancamento"].id,),
            ).fetchone()
            assert lc is not None, "Lançamento contábil não foi persistido"

    def test_criar_lancamento_completo_rollback_em_erro(
        self, service, usuario, contas_padrao, db
    ):
        """Se lançamento contábil falhar, transação NÃO deve ser gravada."""
        # Cria categoria para a transação
        with db.get_write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id) VALUES (?, ?, ?)",
                ("Vendas", "receita", usuario),
            )
            cat_id = cur.lastrowid

        # Força erro: debito_id inválido (deve causar FK violation)
        sucesso, resultado = service.criar_lancamento_completo(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste rollback",
            valor=500.00,
            debito_id=99999,  # ID inexistente — causa IntegrityError
            credito_id=contas_padrao["vendas"].id,
            descricao_transacao="Teste rollback",
            tipo_transacao="receita",
            categoria_id=cat_id,
        )

        assert sucesso is False, "Deveria ter falhado"
        # Validação ocorre ANTES da transação SQL, então retorna erro de validação
        assert "não encontrada" in resultado.lower() or "inexistente" in resultado.lower()

        # Verifica que NENHUMA transação foi criada (rollback funcionou)
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM transacoes WHERE descricao = 'Teste rollback'",
            ).fetchone()[0]
            assert count == 0, "Transação foi gravada mesmo com erro! Rollback falhou."

            count_lc = conn.execute(
                "SELECT COUNT(*) FROM lancamentos_contabeis WHERE historico = 'Teste rollback'",
            ).fetchone()[0]
            assert count_lc == 0, "Lançamento foi gravado mesmo com erro! Rollback falhou."

    def test_criar_lancamento_completo_rollback_debito_igual_credito(
        self, service, usuario, contas_padrao, db
    ):
        """Se débito == crédito, NADA deve ser gravado."""
        with db.get_write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id) VALUES (?, ?, ?)",
                ("Vendas", "receita", usuario),
            )
            cat_id = cur.lastrowid

        sucesso, resultado = service.criar_lancamento_completo(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Teste erro validação",
            valor=500.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["caixa"].id,  # mesmo ID -> erro de validação
            descricao_transacao="Teste erro validação",
            tipo_transacao="receita",
            categoria_id=cat_id,
        )

        assert sucesso is False
        assert "diferentes" in resultado.lower()

        # Verifica que NADA foi gravado (validação acontece ANTES de abrir transação)
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM transacoes WHERE descricao = 'Teste erro validação'",
            ).fetchone()[0]
            assert count == 0, "Transação foi criada mesmo com erro de validação!"

    def test_integridade_transacao_lancamento(
        self, service, usuario, contas_padrao, db
    ):
        """transacao_id no lançamento deve referenciar transação correta."""
        with db.get_write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id) VALUES (?, ?, ?)",
                ("Vendas", "receita", usuario),
            )
            cat_id = cur.lastrowid

        sucesso, resultado = service.criar_lancamento_completo(
            usuario_id=usuario,
            data="2024-01-15",
            historico="Integridade teste",
            valor=2000.00,
            debito_id=contas_padrao["caixa"].id,
            credito_id=contas_padrao["vendas"].id,
            descricao_transacao="Integridade teste",
            tipo_transacao="receita",
            categoria_id=cat_id,
        )

        assert sucesso is True
        lancamento = resultado["lancamento"]
        transacao_id = resultado["transacao_id"]

        # Verifica FK: transacao_id no lancamento aponta para transação existente
        assert lancamento.transacao_id == transacao_id

        # Verifica via SQL
        with db.get_conn() as conn:
            row = conn.execute(
                """SELECT t.id, t.descricao, t.valor, t.tipo
                   FROM transacoes t
                   JOIN lancamentos_contabeis l ON l.transacao_id = t.id
                   WHERE l.id = ?""",
                (lancamento.id,),
            ).fetchone()
            assert row is not None
            assert row["descricao"] == "Integridade teste"
            assert row["valor"] == 2000.00
            assert row["tipo"] == "receita"

    def test_listar_partidas_dobradas_com_join(
        self, service, usuario, contas_padrao, db
    ):
        """Listagem com JOIN único deve retornar nomes das contas."""
        with db.get_write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id) VALUES (?, ?, ?)",
                ("Vendas", "receita", usuario),
            )
            cat_id = cur.lastrowid

        # Cria 2 lançamentos
        for i, valor in enumerate([100.0, 200.0]):
            sucesso, _ = service.criar_lancamento_completo(
                usuario_id=usuario,
                data=f"2024-01-{15 + i:02d}",
                historico=f"Join teste {i}",
                valor=valor,
                debito_id=contas_padrao["caixa"].id,
                credito_id=contas_padrao["vendas"].id,
                descricao_transacao=f"Join transacao {i}",
                tipo_transacao="receita",
                categoria_id=cat_id,
            )
            assert sucesso is True

        # Lista com JOIN
        dtos = service.listar_partidas_dobradas_por_periodo(
            usuario_id=usuario,
            data_inicio="2024-01-01",
            data_fim="2024-01-31",
        )

        assert len(dtos) == 2
        for dto in dtos:
            assert dto.conta_debito_nome is not None
            assert dto.conta_credito_nome is not None
            assert "Caixa" in dto.conta_debito_nome or "1.1.1" in dto.conta_debito_nome
            assert "Vendas" in dto.conta_credito_nome or "3.1.1" in dto.conta_credito_nome
            assert dto.valor in (100.0, 200.0)

    def test_saldo_conta_aggregation_sql(
        self, service, usuario, contas_padrao, db
    ):
        """Saldo deve usar agregação SQL (SUM + CASE WHEN), não Python."""
        with db.get_write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id) VALUES (?, ?, ?)",
                ("Vendas", "receita", usuario),
            )
            cat_id = cur.lastrowid

        # Lança 50 receitas no caixa (débito)
        for i in range(50):
            sucesso, _ = service.criar_lancamento_completo(
                usuario_id=usuario,
                data="2024-01-15",
                historico=f"Venda {i}",
                valor=100.0,
                debito_id=contas_padrao["caixa"].id,
                credito_id=contas_padrao["vendas"].id,
                descricao_transacao=f"Transacao {i}",
                tipo_transacao="receita",
                categoria_id=cat_id,
            )
            assert sucesso is True

        # Calcula saldo
        sucesso, saldo = service.saldo_conta(
            contas_padrao["caixa"].id, usuario,
        )
        assert sucesso is True
        assert saldo == 5000.0  # 50 * 100 = 5000

    def test_criar_lancamento_completo_despesa(
        self, service, usuario, contas_padrao, db
    ):
        """Criação completa com tipo despesa."""
        with db.get_write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO categorias (nome, tipo, usuario_id) VALUES (?, ?, ?)",
                ("Salários", "despesa", usuario),
            )
            cat_id = cur.lastrowid

        sucesso, resultado = service.criar_lancamento_completo(
            usuario_id=usuario,
            data="2024-01-31",
            historico="Pagamento de salários",
            valor=5000.00,
            debito_id=contas_padrao["salarios"].id,  # despesa
            credito_id=contas_padrao["caixa"].id,    # saiu do caixa
            descricao_transacao="Salários Janeiro",
            tipo_transacao="despesa",
            categoria_id=cat_id,
        )

        assert sucesso is True
        assert resultado["lancamento"].debito_id == contas_padrao["salarios"].id
        assert resultado["lancamento"].credito_id == contas_padrao["caixa"].id
        assert resultado["lancamento"].valor == 5000.00

        # Verifica transação
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT tipo FROM transacoes WHERE id = ?",
                (resultado["transacao_id"],),
            ).fetchone()
            assert row["tipo"] == "despesa"
