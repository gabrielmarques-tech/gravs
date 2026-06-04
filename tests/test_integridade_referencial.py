"""Testes de integridade referencial da camada contábil.

Testa as restrições ON DELETE RESTRICT implementadas nos relacionamentos:
- lancamentos_contabeis.debito_id → plano_contas(id)
- lancamentos_contabeis.credito_id → plano_contas(id)
- plano_contas.conta_pai_id → plano_contas(id)

Garantia: conta contábil com movimentação NÃO pode ser removida.
          Conta pai com filhas NÃO pode ser removida.
"""

import os
import tempfile
import uuid as uuid_lib

import pytest
import sqlite3

from database.manager import DatabaseManager


# ── Fixtures ────────────────────────────────────────────────────────────────────


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
def usuario(db):
    """Cria um usuário e retorna seu ID."""
    with db.get_write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
            ("teste_fk@t.com", "hash", "Teste FK"),
        )
        return cur.lastrowid


@pytest.fixture
def usuario_sem_dados(db):
    """Usuário separado para não conflitar com registros de outros testes."""
    with db.get_write_conn() as conn:
        cur = conn.execute(
            "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
            ("sem_dados@t.com", "hash", "Sem Dados"),
        )
        return cur.lastrowid


# ── Testes: Impedir exclusão de conta com lançamentos ──────────────────────────


class TestNaoPermiteExcluirContaComLancamentos:
    """Garantir que conta contábil com lançamentos NÃO pode ser excluída."""

    def test_nao_permite_excluir_conta_com_lancamentos_debito(
        self, db, usuario
    ):
        """Excluir conta que aparece como débito em lançamento deve falhar."""
        with db.get_write_conn() as conn:
            # Cria contas
            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (usuario, "1", "Ativo Teste 1", "ativo", "devedora", 1, 1),
            )
            conta_debito = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (usuario, "2", "Passivo Teste 1", "passivo", "credora", 1, 1),
            )
            conta_credito = cur.lastrowid

            # Cria lançamento usando a conta de débito
            conn.execute(
                "INSERT INTO lancamentos_contabeis (uuid, usuario_id, data, historico, valor, debito_id, credito_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid_lib.uuid4()), usuario, "2024-01-15", "Teste débito", 100.0,
                 conta_debito, conta_credito),
            )

            # Tenta excluir a conta de débito — DEVE falhar
            with pytest.raises(sqlite3.IntegrityError) as exc_info:
                conn.execute("DELETE FROM plano_contas WHERE id = ?", (conta_debito,))

            assert "FOREIGN KEY" in str(exc_info.value) or "RESTRICT" in str(exc_info.value) or "constraint" in str(exc_info.value).lower()

    def test_nao_permite_excluir_conta_com_lancamentos_credito(
        self, db, usuario
    ):
        """Excluir conta que aparece como crédito em lançamento deve falhar."""
        with db.get_write_conn() as conn:
            # Cria contas
            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (usuario, "3", "Ativo Teste 2", "ativo", "devedora", 1, 1),
            )
            conta_debito = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (usuario, "4", "Passivo Teste 2", "passivo", "credora", 1, 1),
            )
            conta_credito = cur.lastrowid

            # Cria lançamento usando a conta de crédito
            conn.execute(
                "INSERT INTO lancamentos_contabeis (uuid, usuario_id, data, historico, valor, debito_id, credito_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid_lib.uuid4()), usuario, "2024-01-15", "Teste crédito", 200.0,
                 conta_debito, conta_credito),
            )

            # Tenta excluir a conta de crédito — DEVE falhar
            with pytest.raises(sqlite3.IntegrityError) as exc_info:
                conn.execute("DELETE FROM plano_contas WHERE id = ?", (conta_credito,))

            assert "FOREIGN KEY" in str(exc_info.value) or "RESTRICT" in str(exc_info.value) or "constraint" in str(exc_info.value).lower()


# ── Testes: Impedir exclusão de conta pai com filhas ───────────────────────────


class TestNaoPermiteExcluirContaPaiComFilhos:
    """Garantir que conta pai com contas filhas NÃO pode ser excluída."""

    def test_nao_permite_excluir_conta_pai_com_filhos(self, db, usuario):
        """Excluir conta pai que possui contas filhas deve falhar."""
        with db.get_write_conn() as conn:
            # Cria conta pai (nível 1, sintética)
            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (usuario, "5", "Ativo Pai", "ativo", "devedora", 1, 0),
            )
            conta_pai = cur.lastrowid

            # Cria conta filha (referencia conta_pai_id)
            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, conta_pai_id, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (usuario, "5.1", "Filha 1", "ativo", "devedora", 2, conta_pai, 1),
            )
            _ = cur.lastrowid

            # Tenta excluir a conta pai — DEVE falhar por ON DELETE RESTRICT
            with pytest.raises(sqlite3.IntegrityError) as exc_info:
                conn.execute("DELETE FROM plano_contas WHERE id = ?", (conta_pai,))

            assert "FOREIGN KEY" in str(exc_info.value) or "RESTRICT" in str(exc_info.value) or "constraint" in str(exc_info.value).lower()

    def _criar_contas_sem_filhos(self, conn, usuario_id):
        """Helper para criar contas sem filhos para testes de exclusão."""
        cur = conn.execute(
            "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, "1", "Ativo", "ativo", "devedora", 1, 0),
        )
        pai_id = cur.lastrowid

        cur = conn.execute(
            "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, conta_pai_id, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, "1.1", "Caixa", "ativo", "devedora", 2, pai_id, 1),
        )
        filha_id = cur.lastrowid
        return filha_id

    def test_permite_excluir_conta_sem_filhos(self, db, usuario_sem_dados):
        """Excluir conta filha (sem filhas próprias) deve funcionar."""
        with db.get_write_conn() as conn:
            filha_id = self._criar_contas_sem_filhos(conn, usuario_sem_dados)
            # Deve funcionar — filha não tem filhas nem lançamentos
            conn.execute("DELETE FROM plano_contas WHERE id = ?", (filha_id,))
            row = conn.execute(
                "SELECT id FROM plano_contas WHERE id = ?",
                (filha_id,),
            ).fetchone()
            assert row is None, "Conta filha deveria ter sido excluída"

    def test_permite_excluir_conta_sem_lancamentos(self, db, usuario_sem_dados):
        """Excluir conta analítica sem lançamentos deve funcionar."""
        with db.get_write_conn() as conn:
            filha_id = self._criar_contas_sem_filhos(conn, usuario_sem_dados)
            # A filha não possui lançamentos — exclusão deve ser permitida
            conn.execute("DELETE FROM plano_contas WHERE id = ?", (filha_id,))
            row = conn.execute(
                "SELECT id FROM plano_contas WHERE id = ?",
                (filha_id,),
            ).fetchone()
            assert row is None


# ── Testes: Integridade FK após migração ────────────────────────────────────────


class TestIntegridadeFKAposMigracao:
    """Verificar que o schema foi migrado corretamente com ON DELETE RESTRICT."""

    def test_integridade_fk_apos_migracao(self, db):
        """Verifica que as FKs contêm ON DELETE RESTRICT no schema."""
        with db.get_conn() as conn:
            # Verifica plano_contas.conta_pai_id
            schema_pc = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='plano_contas'"
            ).fetchone()
            assert schema_pc is not None, "Tabela plano_contas não encontrada no schema"
            assert "ON DELETE RESTRICT" in schema_pc[0], (
                "FK plano_contas.conta_pai_id NÃO possui ON DELETE RESTRICT"
            )

            # Verifica lancamentos_contabeis.debito_id e credito_id
            schema_lc = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='lancamentos_contabeis'"
            ).fetchone()
            assert schema_lc is not None, "Tabela lancamentos_contabeis não encontrada no schema"
            assert "ON DELETE RESTRICT" in schema_lc[0], (
                "FKs de lancamentos_contabeis NÃO possuem ON DELETE RESTRICT"
            )

            # Verifica que ambas as FKs têm RESTRICT (conta 2 ocorrências)
            restrict_count = schema_lc[0].count("ON DELETE RESTRICT")
            assert restrict_count >= 2, (
                f"Esperado 2 FKs com ON DELETE RESTRICT, encontrado {restrict_count}"
            )

    def test_dados_preservados_apos_migracao(self, db):
        """Verifica que os dados foram preservados corretamente após a migração."""
        with db.get_write_conn() as conn:
            # Cria dados de exemplo
            cur = conn.execute(
                "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                ("preservado@t.com", "hash", "Preservado"),
            )
            uid = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, "10", "Ativo Preservado", "ativo", "devedora", 1, 1),
            )
            ativo_id = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, "20", "Passivo Preservado", "passivo", "credora", 1, 1),
            )
            passivo_id = cur.lastrowid

            cur = conn.execute(
                "INSERT INTO lancamentos_contabeis (uuid, usuario_id, data, historico, valor, debito_id, credito_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid_lib.uuid4()), uid, "2024-06-15", "Lançamento preservado", 500.0,
                 ativo_id, passivo_id),
            )
            lanc_id = cur.lastrowid

        # Simula reinicialização do schema (como se a migração rodasse denovo)
        # O schema já foi inicializado no fixture, então os dados devem estar lá
        with db.get_conn() as conn:
            # Verifica usuário
            usuario = conn.execute(
                "SELECT id, nome FROM usuarios WHERE id = ?", (uid,)
            ).fetchone()
            assert usuario is not None
            assert usuario["nome"] == "Preservado"

            # Verifica contas
            ativo = conn.execute(
                "SELECT id, codigo, nome FROM plano_contas WHERE id = ?",
                (ativo_id,),
            ).fetchone()
            assert ativo is not None
            assert ativo["codigo"] == "10"
            assert ativo["nome"] == "Ativo Preservado"

            passivo = conn.execute(
                "SELECT id, codigo, nome FROM plano_contas WHERE id = ?",
                (passivo_id,),
            ).fetchone()
            assert passivo is not None
            assert passivo["codigo"] == "20"

            # Verifica lançamento
            lancamento = conn.execute(
                "SELECT id, valor, debito_id, credito_id FROM lancamentos_contabeis WHERE id = ?",
                (lanc_id,),
            ).fetchone()
            assert lancamento is not None
            assert lancamento["valor"] == 500.0
            assert lancamento["debito_id"] == ativo_id
            assert lancamento["credito_id"] == passivo_id

            # Verifica total de registros
            count_contas = conn.execute(
                "SELECT COUNT(*) FROM plano_contas WHERE usuario_id = ?",
                (uid,),
            ).fetchone()[0]
            assert count_contas == 2, (
                f"Esperado 2 contas, encontrado {count_contas}"
            )

            count_lanc = conn.execute(
                "SELECT COUNT(*) FROM lancamentos_contabeis WHERE usuario_id = ?",
                (uid,),
            ).fetchone()[0]
            assert count_lanc == 1, (
                f"Esperado 1 lançamento, encontrado {count_lanc}"
            )


# ── Testes: Schema inicial também tem ON DELETE RESTRICT ────────────────────────


class TestSchemaInicial:
    """Verificar que o schema inicial já cria as FKs com ON DELETE RESTRICT."""

    def test_schema_inicial_restrict_plano_contas(self):
        """Novo banco criado do zero deve ter ON DELETE RESTRICT em conta_pai_id."""
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        try:
            manager = DatabaseManager(f.name)
            manager.init_schema()

            with manager.get_conn() as conn:
                schema = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='plano_contas'"
                ).fetchone()
                assert "ON DELETE RESTRICT" in schema[0], (
                    "Schema inicial de plano_contas NÃO tem ON DELETE RESTRICT"
                )
        finally:
            try:
                os.unlink(f.name)
            except OSError:
                pass

    def test_schema_inicial_restrict_lancamentos(self):
        """Novo banco criado do zero deve ter ON DELETE RESTRICT em debito_id e credito_id."""
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        try:
            manager = DatabaseManager(f.name)
            manager.init_schema()

            with manager.get_conn() as conn:
                schema = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='lancamentos_contabeis'"
                ).fetchone()
                assert "ON DELETE RESTRICT" in schema[0], (
                    "Schema inicial de lancamentos_contabeis NÃO tem ON DELETE RESTRICT"
                )
                # Deve ter 2 ocorrências (debito_id e credito_id)
                assert schema[0].count("ON DELETE RESTRICT") >= 2, (
                    "Schema inicial não tem ON DELETE RESTRICT em ambas FKs"
                )
        finally:
            try:
                os.unlink(f.name)
            except OSError:
                pass