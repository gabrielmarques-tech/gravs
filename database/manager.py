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
import time
from contextlib import contextmanager
from typing import Generator

from utils.metrics import metricas

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
    def get_conn(self, operacao: str = "db_query") -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager que entrega uma conexão configurada.

        Configurações aplicadas:
        - journal_mode=WAL: leituras concorrentes sem bloquear escritas
        - foreign_keys=ON: integridade referencial real (FK enforcement)
        - synchronous=NORMAL: equilíbrio entre durabilidade e performance
        - busy_timeout=5000: aguarda 5s antes de lançar "database is locked"
        - row_factory=sqlite3.Row: permite acesso por nome (row['campo'])

        Args:
            operacao: Nome opcional da operação para métricas.
                      Default: "db_query"
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
        conn.execute("PRAGMA mmap_size = 134217728") # 128MB de memory-mapped I/O
        conn.execute("PRAGMA temp_store = MEMORY")   # tabelas temporárias em memória
        conn.execute("PRAGMA cache_size = -8000")   # 8MB de cache em memória
        conn.execute("PRAGMA temp_store = MEMORY")  # tabelas temporárias em RAM
        conn.execute("PRAGMA mmap_size = 268435456") # 256MB memory-mapped I/O
        conn.row_factory = sqlite3.Row

        inicio = time.perf_counter()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            duracao = time.perf_counter() - inicio
            metricas.registrar_consulta(operacao, duracao)
            conn.close()

    @contextmanager
    def get_write_conn(self, operacao: str = "db_write") -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager para operações de escrita com lock thread-safe.

        Por que lock separado para escrita?
        -------------------------------------
        SQLite tem lock no nível de arquivo. Em aplicações web com múltiplas
        threads, duas escritas simultâneas causam "database is locked". O lock
        do Python garante serialização no nível da aplicação, antes de chegar
        ao banco.

        Args:
            operacao: Nome opcional da operação para métricas.
                      Default: "db_write"
        """
        inicio = time.perf_counter()
        try:
            with _write_lock:
                with self.get_conn(operacao=operacao) as conn:
                    yield conn
        finally:
            duracao = time.perf_counter() - inicio

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
                self._criar_tabela_transferencias(conn)
                self._criar_tabela_plano_contas(conn)
                self._criar_tabela_lancamentos_contabeis(conn)
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
        # self._criar_tabela_transferencias(conn) # Movido para init_schema
        self._migrar_categorias_pix(conn)
        self._migrar_fk_on_delete_restrict(conn)


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
        # Índice adicionado para buscas de limites por categoria
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_limites_cat ON limites_categoria(usuario_id, categoria_id)"
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

        # Índices de performance adicionais
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_categoria ON transacoes(usuario_id, categoria_id) WHERE deletado=0"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trans_mes ON transacoes(usuario_id, strftime('%Y-%m', data)) WHERE deletado=0"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_recorrentes_dia ON recorrentes(usuario_id, dia_vencimento) WHERE ativo=1"
        )
        # REMOVIDO: idx_limites_cat movido para _criar_tabela_limites_categoria

    def _criar_tabela_plano_contas(self, conn: sqlite3.Connection) -> None:
        """
        Plano de Contas Contábil — estrutura hierárquica para partidas dobradas.

        Hierarquia:
        - Nível 1: Grupos (Ativo, Passivo, PL, Receitas, Despesas)
        - Nível 2: Subgrupos (Circulante, Não Circulante, etc.)
        - Nível 3 a 5: Contas Analíticas e subdivisões

        Regras de integridade:
        - UNIQUE(usuario_id, codigo): código contábil é identificador único
        - nivel BETWEEN 1 AND 5: limita profundidade da árvore
        - FK com ON DELETE CASCADE: deletar usuário remove plano
        - não há UNIQUE no nome: permite contas com mesmo nome em naturezas diferentes

        Proteção contra ciclos:
        - Auto-referência detectada via TRIGGER (self-reference)
        - Ciclos indiretos detectados via validação no service
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plano_contas (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id        INTEGER NOT NULL,
                codigo            TEXT    NOT NULL,
                nome              TEXT    NOT NULL,
                tipo              TEXT    NOT NULL CHECK(tipo IN (
                    'ativo', 'passivo', 'patrimonio_liquido',
                    'receita', 'despesa', 'redutora'
                )),
                natureza          TEXT    NOT NULL CHECK(natureza IN ('devedora','credora')),
                nivel             INTEGER NOT NULL DEFAULT 1
                                  CHECK(nivel BETWEEN 1 AND 5),
                conta_pai_id      INTEGER,
                aceita_lancamentos INTEGER DEFAULT 1,
                ativo             INTEGER DEFAULT 1,
                criado_em         TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE,
                FOREIGN KEY (conta_pai_id) REFERENCES plano_contas(id) ON DELETE RESTRICT,
                UNIQUE(usuario_id, codigo)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_plano_contas_user ON plano_contas(usuario_id, ativo)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_plano_contas_pai ON plano_contas(conta_pai_id)"
        )

        # Trigger de proteção contra auto-referência no pai
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_plano_contas_no_self_ref
            BEFORE UPDATE OF conta_pai_id ON plano_contas
            BEGIN
                SELECT RAISE(ABORT, 'Auto-referência: conta não pode ser pai dela mesma')
                WHERE NEW.conta_pai_id IS NOT NULL
                  AND NEW.conta_pai_id = NEW.id;
            END
        """)

    def _criar_tabela_lancamentos_contabeis(self, conn: sqlite3.Connection) -> None:
        """
        Lançamentos em Partida Dobrada.

        TODO lançamento possui:
        - Data, histórico, valor
        - Conta de Débito (obrigatório, referência ao plano_contas)
        - Conta de Crédito (obrigatório, referência ao plano_contas)

        Proteção em duas camadas para débito != crédito:
        1. CHECK(debito_id != credito_id) no banco — rede de segurança
        2. Validação no service — feedback amigável ao usuário

        Relação com transacoes:
        - transacao_id é OPCIONAL — permite migração gradual
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lancamentos_contabeis (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid            TEXT    UNIQUE NOT NULL,
                usuario_id      INTEGER NOT NULL,
                data            TEXT    NOT NULL,
                historico       TEXT    NOT NULL,
                valor           REAL    NOT NULL CHECK(valor > 0),
                debito_id       INTEGER NOT NULL REFERENCES plano_contas(id) ON DELETE RESTRICT,
                credito_id      INTEGER NOT NULL REFERENCES plano_contas(id) ON DELETE RESTRICT,
                transacao_id    INTEGER REFERENCES transacoes(id),
                criado_em       TEXT    DEFAULT CURRENT_TIMESTAMP,
                CHECK(debito_id != credito_id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lanc_cont_user ON lancamentos_contabeis(usuario_id, data DESC)"
        )
        # Índices para cálculo de saldo por conta
        # O índice composto (usuario_id, debito_id, data) é usado pelas queries
        # de SUM em calcular_saldo_conta(), que filtram por usuario_id E debito_id
        # E opcionalmente por data. A ordenação por data no índice permite range scan
        # eficiente para o filtro "data <= ?".
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lanc_saldo_debito ON lancamentos_contabeis(usuario_id, debito_id, data)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lanc_saldo_credito ON lancamentos_contabeis(usuario_id, credito_id, data)"
        )
        # Índices legados mantidos para compatibilidade com outras queries
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lanc_cont_debito ON lancamentos_contabeis(usuario_id, debito_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lanc_cont_credito ON lancamentos_contabeis(usuario_id, credito_id)"
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

    def _migrar_fk_on_delete_restrict(self, conn: sqlite3.Connection) -> None:
        """
        Migration: aplica ON DELETE RESTRICT nas FKs que não possuem política
        explícita de exclusão.

        Tabelas afetadas:
        1. plano_contas.conta_pai_id → plano_contas(id)
        2. lancamentos_contabeis.debito_id → plano_contas(id)
        3. lancamentos_contabeis.credito_id → plano_contas(id)

        SQLite NÃO permite ALTER TABLE para modificar FKs. A solução é:
        - Criar tabela temporária com as novas constraints
        - Copiar todos os dados
        - Validar integridade
        - Remover tabela original
        - Renomear temporária para original
        - Recriar índices e triggers

        Idempotente: verifica se já foi aplicada antes de executar.
        """
        # Verifica se a migration já foi aplicada
        # Estratégia: verificar se a constraint ON DELETE RESTRICT já existe
        # no SQL da tabela plano_contas
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='plano_contas'"
        ).fetchone()

        if schema and 'ON DELETE RESTRICT' in schema[0]:
            logger.info("Migration FK_ON_DELETE_RESTRICT já aplicada. Pulando.")
            return

        logger.info("Iniciando migration: aplicando ON DELETE RESTRICT nas FKs contábeis...")
        conn.execute("PRAGMA foreign_keys = OFF")

        try:
            # ── 1. Migrar plano_contas ───────────────────────────────
            conn.execute("""
                CREATE TABLE plano_contas_temp (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id        INTEGER NOT NULL,
                    codigo            TEXT    NOT NULL,
                    nome              TEXT    NOT NULL,
                    tipo              TEXT    NOT NULL CHECK(tipo IN (
                        'ativo', 'passivo', 'patrimonio_liquido',
                        'receita', 'despesa', 'redutora'
                    )),
                    natureza          TEXT    NOT NULL CHECK(natureza IN ('devedora','credora')),
                    nivel             INTEGER NOT NULL DEFAULT 1
                                      CHECK(nivel BETWEEN 1 AND 5),
                    conta_pai_id      INTEGER,
                    aceita_lancamentos INTEGER DEFAULT 1,
                    ativo             INTEGER DEFAULT 1,
                    criado_em         TEXT    DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (conta_pai_id) REFERENCES plano_contas(id) ON DELETE RESTRICT,
                    UNIQUE(usuario_id, codigo)
                )
            """)

            # Copia dados
            conn.execute("""
                INSERT INTO plano_contas_temp
                SELECT id, usuario_id, codigo, nome, tipo, natureza, nivel,
                       conta_pai_id, aceita_lancamentos, ativo, criado_em
                FROM plano_contas
            """)

            # Valida integridade
            registros_origem = conn.execute(
                "SELECT COUNT(*) FROM plano_contas"
            ).fetchone()[0]
            registros_destino = conn.execute(
                "SELECT COUNT(*) FROM plano_contas_temp"
            ).fetchone()[0]

            if registros_origem != registros_destino:
                raise RuntimeError(
                    f"Migração falhou: {registros_origem} registros origem != "
                    f"{registros_destino} registros destino (plano_contas)"
                )

            # Remove tabela original
            conn.execute("DROP TRIGGER IF EXISTS trg_plano_contas_no_self_ref")
            conn.execute("DROP TABLE IF EXISTS plano_contas")

            # Renomeia temporária para original
            conn.execute("ALTER TABLE plano_contas_temp RENAME TO plano_contas")

            # Recria índices e triggers
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plano_contas_user ON plano_contas(usuario_id, ativo)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plano_contas_pai ON plano_contas(conta_pai_id)"
            )
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_plano_contas_no_self_ref
                BEFORE UPDATE OF conta_pai_id ON plano_contas
                BEGIN
                    SELECT RAISE(ABORT, 'Auto-referência: conta não pode ser pai dela mesma')
                    WHERE NEW.conta_pai_id IS NOT NULL
                      AND NEW.conta_pai_id = NEW.id;
                END
            """)

            # ── 2. Migrar lancamentos_contabeis ───────────────────────
            conn.execute("""
                CREATE TABLE lancamentos_contabeis_temp (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid            TEXT    UNIQUE NOT NULL,
                    usuario_id      INTEGER NOT NULL,
                    data            TEXT    NOT NULL,
                    historico       TEXT    NOT NULL,
                    valor           REAL    NOT NULL CHECK(valor > 0),
                    debito_id       INTEGER NOT NULL REFERENCES plano_contas(id) ON DELETE RESTRICT,
                    credito_id      INTEGER NOT NULL REFERENCES plano_contas(id) ON DELETE RESTRICT,
                    transacao_id    INTEGER REFERENCES transacoes(id),
                    criado_em       TEXT    DEFAULT CURRENT_TIMESTAMP,
                    CHECK(debito_id != credito_id),
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
                )
            """)

            # Copia dados
            conn.execute("""
                INSERT INTO lancamentos_contabeis_temp
                SELECT id, uuid, usuario_id, data, historico, valor,
                       debito_id, credito_id, transacao_id, criado_em
                FROM lancamentos_contabeis
            """)

            # Valida integridade
            registros_origem = conn.execute(
                "SELECT COUNT(*) FROM lancamentos_contabeis"
            ).fetchone()[0]
            registros_destino = conn.execute(
                "SELECT COUNT(*) FROM lancamentos_contabeis_temp"
            ).fetchone()[0]

            if registros_origem != registros_destino:
                raise RuntimeError(
                    f"Migração falhou: {registros_origem} registros origem != "
                    f"{registros_destino} registros destino (lancamentos_contabeis)"
                )

            # Remove tabela original
            conn.execute("DROP TABLE IF EXISTS lancamentos_contabeis")

            # Renomeia temporária para original
            conn.execute("ALTER TABLE lancamentos_contabeis_temp RENAME TO lancamentos_contabeis")

            # Recria índices
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lanc_cont_user ON lancamentos_contabeis(usuario_id, data DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lanc_saldo_debito ON lancamentos_contabeis(usuario_id, debito_id, data)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lanc_saldo_credito ON lancamentos_contabeis(usuario_id, credito_id, data)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lanc_cont_debito ON lancamentos_contabeis(usuario_id, debito_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lanc_cont_credito ON lancamentos_contabeis(usuario_id, credito_id)"
            )

            conn.execute("PRAGMA foreign_keys = ON")
            logger.info("Migration FK_ON_DELETE_RESTRICT concluída com sucesso.")

        except Exception as exc:
            conn.execute("PRAGMA foreign_keys = ON")
            logger.error("Migration FK_ON_DELETE_RESTRICT falhou: %s", exc)
            raise

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
                    "lancamentos_contabeis", "plano_contas", "transferencias",
                    "notificacoes", "metas", "transacoes",
                    "recorrentes", "categorias", "usuarios",
                    "limites_categoria", "tokens_recuperacao",
                    "verificacao_email", "contas_bancarias"
                ]:
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.execute("PRAGMA foreign_keys = ON")
        self._initialized = False
        logger.warning("Todas as tabelas foram removidas.")
