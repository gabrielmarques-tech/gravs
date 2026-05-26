"""
database/manager.py — Gerenciador central de banco de dados.

Por que separar isso do resto?
--------------------------------
No código original, a classe `Banco` ficava misturada com as entidades em
`financeiro.py`. Isso viola o Princípio de Responsabilidade Única (SRP):
Banco gerencia conexão e schema; entidades gerenciam dados. Separar permite
trocar o banco (SQLite → PostgreSQL) sem tocar nas entidades.

Padrão usado: Connection Pool via context manager.
O `@contextmanager` garante que a conexão SEMPRE seja fechada e o
rollback SEMPRE aconteça em caso de erro — sem vazar conexões.

Por que WAL mode?
------------------
WAL (Write-Ahead Logging) permite leituras concorrentes enquanto uma escrita
acontece. Fundamental para apps web com múltiplas requisições simultâneas.
"""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

# Lock global para serializar escritas concorrentes ao SQLite.
# O SQLite suporta múltiplos leitores simultâneos, mas apenas um escritor.
# O lock no nível Python evita o erro "database is locked" em condições de corrida.
_write_lock = threading.Lock()


class DatabaseManager:
    """
    Responsável exclusivamente por:
    - Fornecer conexões configuradas
    - Inicializar o schema (CREATE TABLE IF NOT EXISTS)
    - Executar migrations futuras

    NÃO contém lógica de negócio. NÃO conhece entidades.
    """

    def __init__(self, db_path: str = "financas.db") -> None:
        self.db_path = db_path
        self._initialized = False

    @contextmanager
    def get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager que entrega uma conexão configurada.

        Configurações aplicadas:
        - journal_mode=WAL: leituras concorrentes sem bloquear escritas
        - foreign_keys=ON: integridade referencial real (FK enforcement)
        - synchronous=NORMAL: equilíbrio entre durabilidade e performance
        - busy_timeout=5000: aguarda 5s antes de lançar "database is locked"
        - row_factory=sqlite3.Row: permite acesso por nome (row['campo'])
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=20.0,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA cache_size = -8000")   # 8MB de cache em memória
        conn.execute("PRAGMA temp_store = MEMORY")  # tabelas temporárias em RAM
        conn.execute("PRAGMA mmap_size = 268435456") # 256MB memory-mapped I/O
        conn.row_factory = sqlite3.Row

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def get_write_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager para operações de escrita com lock thread-safe.

        Por que lock separado para escrita?
        -------------------------------------
        SQLite tem lock no nível de arquivo. Em aplicações web com múltiplas
        threads, duas escritas simultâneas causam "database is locked". O lock
        do Python garante serialização no nível da aplicação, antes de chegar
        ao banco.
        """
        with _write_lock:
            with self.get_conn() as conn:
                yield conn

    def init_schema(self) -> None:
        """
        Cria todas as tabelas e índices caso não existam.

        Por que `CREATE TABLE IF NOT EXISTS`?
        ----------------------------------------
        Idempotente: pode ser chamado múltiplas vezes sem erro.
        Essencial para o startup do servidor e para os testes.

        Por que índices explícitos?
        ----------------------------
        SQLite não cria índices automaticamente em FK columns.
        Queries como `WHERE usuario_id = ?` sem índice fazem full-table-scan,
        que piora exponencialmente com o crescimento dos dados.
        """
        with _write_lock:
            with self.get_conn() as conn:
                self._criar_tabela_usuarios(conn)
                self._criar_tabela_categorias(conn)
                self._criar_tabela_transacoes(conn)
                self._criar_tabela_recorrentes(conn)
                self._criar_tabela_metas(conn)
                self._criar_tabela_notificacoes(conn)
                self._aplicar_migrations(conn)
        self._initialized = True
        logger.info("Schema inicializado com sucesso: %s", self.db_path)

    # ── Criação de tabelas ────────────────────────────────────────────────────

    def _criar_tabela_usuarios(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                senha_hash  TEXT    NOT NULL,
                nome        TEXT    NOT NULL,
                criado_em   TEXT    DEFAULT CURRENT_TIMESTAMP,
                ativo       INTEGER DEFAULT 1 CHECK(ativo IN (0,1))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)"
        )

    def _criar_tabela_categorias(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nome        TEXT    NOT NULL,
                tipo        TEXT    NOT NULL CHECK(tipo IN ('receita','despesa')),
                usuario_id  INTEGER NOT NULL,
                icone       TEXT    DEFAULT '💰',
                cor         TEXT    DEFAULT '#a855f7',
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
                UNIQUE(nome, usuario_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_categorias_user ON categorias(usuario_id)"
        )

    def _criar_tabela_transacoes(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transacoes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid            TEXT    UNIQUE NOT NULL,
                descricao       TEXT    NOT NULL,
                valor           REAL    NOT NULL CHECK(valor > 0),
                tipo            TEXT    NOT NULL CHECK(tipo IN ('receita','despesa')),
                categoria_id    INTEGER,
                data            TEXT    NOT NULL,
                usuario_id      INTEGER NOT NULL,
                criado_em       TEXT    DEFAULT CURRENT_TIMESTAMP,
                deletado        INTEGER DEFAULT 0 CHECK(deletado IN (0,1)),
                recorrente_uuid TEXT,
                grupo_parcela   TEXT,
                FOREIGN KEY (categoria_id) REFERENCES categorias(id),
                FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_user_data ON transacoes(usuario_id, data DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_user_tipo ON transacoes(usuario_id, tipo)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_deletado ON transacoes(deletado)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_uuid ON transacoes(uuid)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_grupo ON transacoes(grupo_parcela)"
        )

    def _criar_tabela_recorrentes(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recorrentes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid            TEXT    UNIQUE NOT NULL,
                descricao       TEXT    NOT NULL,
                valor           REAL    NOT NULL CHECK(valor > 0),
                tipo            TEXT    NOT NULL CHECK(tipo IN ('receita','despesa')),
                categoria_id    INTEGER,
                dia_vencimento  INTEGER NOT NULL CHECK(
                    (dia_vencimento BETWEEN 1 AND 28) OR
                    (dia_vencimento BETWEEN -31 AND -1)
                ),
                ativo           INTEGER DEFAULT 1 CHECK(ativo IN (0,1)),
                usuario_id      INTEGER NOT NULL,
                criado_em       TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (categoria_id) REFERENCES categorias(id),
                FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_recorrentes_user ON recorrentes(usuario_id, ativo)"
        )

    def _criar_tabela_metas(self, conn: sqlite3.Connection) -> None:
        """
        Tabela de metas financeiras.

        Por que estava ausente no código original?
        --------------------------------------------
        O sistema mencionava metas como funcionalidade, mas não havia schema.
        Isso é dívida técnica: funcionalidade prometida sem estrutura de dados.
        Criamos agora para não ter breaking change futuro.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metas (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid         TEXT    UNIQUE NOT NULL,
                titulo       TEXT    NOT NULL,
                descricao    TEXT,
                valor_alvo   REAL    NOT NULL CHECK(valor_alvo > 0),
                valor_atual  REAL    NOT NULL DEFAULT 0 CHECK(valor_atual >= 0),
                data_inicio  TEXT    NOT NULL,
                data_fim     TEXT,
                categoria_id INTEGER,
                usuario_id   INTEGER NOT NULL,
                ativa        INTEGER DEFAULT 1 CHECK(ativa IN (0,1)),
                criado_em    TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE,
                FOREIGN KEY (categoria_id) REFERENCES categorias(id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metas_user ON metas(usuario_id, ativa)"
        )

    def _criar_tabela_notificacoes(self, conn: sqlite3.Connection) -> None:
        """Notificações futuras (alertas de vencimento, metas próximas, etc.)."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notificacoes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid        TEXT    UNIQUE NOT NULL,
                usuario_id  INTEGER NOT NULL,
                titulo      TEXT    NOT NULL,
                mensagem    TEXT    NOT NULL,
                tipo        TEXT    NOT NULL DEFAULT 'info'
                                CHECK(tipo IN ('info','alerta','sucesso','erro')),
                lida        INTEGER DEFAULT 0 CHECK(lida IN (0,1)),
                criado_em   TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notif_user ON notificacoes(usuario_id, lida)"
        )

    def _aplicar_migrations(self, conn: sqlite3.Connection) -> None:
        """
        Ponto de extensão para migrations futuras.

        Por que não usar Alembic agora?
        ---------------------------------
        Para SQLite simples, migrations manuais são suficientes.
        Quando migrar para PostgreSQL, substitua este método por
        `flask db upgrade` com Flask-Migrate + Alembic.

        Padrão: adicionar colunas ausentes sem recriar tabelas.
        """
        # Exemplo: adicionar coluna grupo_parcela se a tabela for antiga
        self._add_column_if_missing(conn, "transacoes", "grupo_parcela", "TEXT")
        self._add_column_if_missing(conn, "usuarios", "ativo", "INTEGER DEFAULT 1")
        self._add_column_if_missing(conn, "usuarios", "modo_contabil", "INTEGER DEFAULT 0")
        self._add_column_if_missing(conn, "transacoes", "conta_debito", "TEXT")
        self._add_column_if_missing(conn, "transacoes", "conta_credito", "TEXT")
        self._add_column_if_missing(conn, "transacoes", "conta_id", "INTEGER")
        self._add_column_if_missing(conn, "recorrentes", "conta_id", "INTEGER")
        self._add_column_if_missing(conn, "usuarios", "onboarding_completo", "INTEGER DEFAULT 0")
        self._criar_tabela_limites_categoria(conn)
        self._criar_tabela_contas_bancarias(conn)
        self._criar_tabela_tokens_recuperacao(conn)
        self._criar_tabela_verificacao_email(conn)
        self._add_column_if_missing(conn, "usuarios", "email_verificado", "INTEGER DEFAULT 0")
        self._add_column_if_missing(conn, "usuarios", "aceite_termos_em", "TEXT")
        self._add_column_if_missing(conn, "usuarios", "excluido_em", "TEXT")
        self._anonimizar_emails_excluidos(conn)
        self._criar_tabela_transferencias(conn)
        self._migrar_categorias_pix(conn)


    def limpar_tokens_expirados(self) -> int:
        """
        Remove tokens de recuperação expirados ou já usados.
        Chamar periodicamente para não acumular lixo no banco.
        Retorna quantos tokens foram removidos.
        """
        from datetime import datetime
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_write_conn() as conn:
            cur = conn.execute(
                "DELETE FROM tokens_recuperacao WHERE expira_em < ? OR usado = 1",
                (agora,)
            )
        return cur.rowcount

    def _criar_tabela_limites_categoria(self, conn) -> None:
        """Limites de gasto mensais por categoria."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS limites_categoria (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id   INTEGER NOT NULL,
                categoria_id INTEGER NOT NULL,
                limite       REAL    NOT NULL CHECK(limite > 0),
                criado_em    TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE,
                FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE,
                UNIQUE(usuario_id, categoria_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_limites_user ON limites_categoria(usuario_id)"
        )

    def _criar_tabela_tokens_recuperacao(self, conn) -> None:
        """Cria tabela de tokens para recuperação de senha."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tokens_recuperacao (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                token      TEXT    NOT NULL UNIQUE,
                expira_em  TEXT    NOT NULL,
                usado      INTEGER DEFAULT 0,
                criado_em  TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tokens_usuario ON tokens_recuperacao(usuario_id, usado)"
        )

    def _criar_tabela_verificacao_email(self, conn) -> None:
        """Códigos de verificação de email para novos cadastros."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verificacao_email (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                codigo     TEXT    NOT NULL,
                expira_em  TEXT    NOT NULL,
                usado      INTEGER DEFAULT 0,
                criado_em  TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_verif_usuario ON verificacao_email(usuario_id, usado)"
        )

    def _criar_tabela_contas_bancarias(self, conn) -> None:
        """Cria tabela de contas bancarias e cartoes se nao existir."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contas_bancarias (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id  INTEGER NOT NULL,
                nome        TEXT    NOT NULL,
                tipo        TEXT    NOT NULL DEFAULT 'conta',
                icone       TEXT    NOT NULL DEFAULT '🏦',
                ativo       INTEGER DEFAULT 1,
                criado_em   TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
                UNIQUE(usuario_id, nome)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contas_usuario ON contas_bancarias(usuario_id)"
        )
        # Índice para busca por recorrente_uuid (lançamentos automáticos)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_recorrente ON transacoes(recorrente_uuid) WHERE recorrente_uuid IS NOT NULL"
        )
        # Índice para contas bancárias ativas
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contas_ativo ON contas_bancarias(usuario_id, ativo)"
        )

    def _migrar_categorias_pix(self, conn) -> None:
        """
        Migration: adiciona Transferências PIX e Receita PIX para usuários
        que criaram conta antes dessas categorias existirem no padrão.
        """
        usuarios = conn.execute("SELECT id FROM usuarios WHERE ativo=1").fetchall()
        for u in usuarios:
            uid = u["id"]
            # Transferências PIX
            existe = conn.execute(
                "SELECT 1 FROM categorias WHERE usuario_id=? AND nome='Transferências PIX'",
                (uid,)
            ).fetchone()
            if not existe:
                try:
                    conn.execute(
                        "INSERT INTO categorias (nome, tipo, usuario_id, icone, cor) VALUES (?,?,?,?,?)",
                        ("Transferências PIX", "despesa", uid, "🔄", "#6b7280")
                    )
                except Exception:
                    pass
            # Receita PIX
            existe2 = conn.execute(
                "SELECT 1 FROM categorias WHERE usuario_id=? AND nome='Receita PIX'",
                (uid,)
            ).fetchone()
            if not existe2:
                try:
                    conn.execute(
                        "INSERT INTO categorias (nome, tipo, usuario_id, icone, cor) VALUES (?,?,?,?,?)",
                        ("Receita PIX", "receita", uid, "💸", "#10b981")
                    )
                except Exception:
                    pass

    def _criar_tabela_transferencias(self, conn) -> None:
        """
        Transferências entre contas do próprio usuário.

        Uma transferência NÃO é receita nem despesa — é movimentação interna.
        Exemplos: pagar fatura do cartão, PIX entre contas próprias,
        transferir da corrente para poupança.

        Modelo: debita conta_origem e credita conta_destino pelo mesmo valor.
        O saldo total do usuário não muda — apenas redistribui entre contas.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transferencias (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid            TEXT    UNIQUE NOT NULL,
                descricao       TEXT    NOT NULL,
                valor           REAL    NOT NULL CHECK(valor > 0),
                conta_origem_id INTEGER NOT NULL,
                conta_destino_id INTEGER NOT NULL,
                data            TEXT    NOT NULL,
                usuario_id      INTEGER NOT NULL,
                criado_em       TEXT    DEFAULT CURRENT_TIMESTAMP,
                deletado        INTEGER DEFAULT 0 CHECK(deletado IN (0,1)),
                CHECK(conta_origem_id != conta_destino_id),
                FOREIGN KEY (conta_origem_id)  REFERENCES contas_bancarias(id),
                FOREIGN KEY (conta_destino_id) REFERENCES contas_bancarias(id),
                FOREIGN KEY (usuario_id)       REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transf_user ON transferencias(usuario_id, data DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transf_uuid ON transferencias(uuid)"
        )

    def _anonimizar_emails_excluidos(self, conn: sqlite3.Connection) -> None:
        """
        Migration de segurança — roda automaticamente no startup.

        Problema: contas excluídas antes do fix v6 tinham ativo=0
        mas mantinham o email real na tabela, bloqueando novo cadastro
        com o mesmo endereço (violação da constraint UNIQUE).

        Solução: anonimiza todos os emails de contas inativas que ainda
        não foram anonimizados (não contêm "@excluido.gravs").

        Idempotente: pode rodar múltiplas vezes sem efeito colateral.
        """
        import time
        try:
            rows = conn.execute(
                """SELECT id FROM usuarios
                   WHERE ativo = 0
                   AND email NOT LIKE '%@excluido.gravs'"""
            ).fetchall()

            for row in rows:
                uid = row[0]
                email_anonimo = f"deleted_{uid}_{int(time.time())}@excluido.gravs"
                conn.execute(
                    "UPDATE usuarios SET email = ? WHERE id = ?",
                    (email_anonimo, uid)
                )
                logger.info("Migration: email anonimizado para usuario_id=%d", uid)

            if rows:
                logger.info(
                    "Migration _anonimizar_emails_excluidos: %d conta(s) corrigida(s)",
                    len(rows)
                )
        except Exception as exc:
            logger.warning("Migration anonimizar_emails falhou: %s", exc)

    @staticmethod
    def _add_column_if_missing(
        conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        """Adiciona coluna à tabela apenas se ela ainda não existir."""
        try:
            columns = [
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
                logger.info("Migration: coluna '%s' adicionada em '%s'", column, table)
        except Exception as exc:
            logger.warning("Migration falhou (%s.%s): %s", table, column, exc)

    def drop_all(self) -> None:
        """
        Destrói todas as tabelas. USE APENAS EM TESTES.

        Por que existir este método?
        ------------------------------
        Testes de integração precisam de um banco limpo a cada execução.
        Em produção, este método jamais deve ser chamado.
        """
        with _write_lock:
            with self.get_conn() as conn:
                conn.execute("PRAGMA foreign_keys = OFF")
                for table in [
                    "notificacoes", "metas", "transacoes",
                    "recorrentes", "categorias", "usuarios"
                ]:
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.execute("PRAGMA foreign_keys = ON")
        self._initialized = False
        logger.warning("Todas as tabelas foram removidas.")# Método adicionado para migração — adiciona colunas novas sem quebrar banco existente