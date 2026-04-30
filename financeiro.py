"""
financeiro.py — Camada de dados e regras de negócio do Gravs.

CORREÇÕES DESTA VERSÃO (auditoria 2025)
-----------------------------------------
1. Singleton SistemaFinanceiro removido — quebrava isolamento entre testes.
2. _lock global removido — causava deadlock em gerar_transacoes_mes().
3. Recorrente.listar_proximos_do_mes() corrigido para ordenar por date object.
4. Transacao.adicionar_parcelado() corrigido para avançar meses corretamente.
5. calcular_preview_parcelas() com juros simples agora distribui arredondamento.
6. Usuario.criar_usuario() agora levanta ValueError em vez de retornar None.
7. Adicionado Transacao.saldo_total() para saldo histórico acumulado.
8. Adicionado validação de formato de data em Transacao.adicionar().
9. CalendarioUtil com cache de feriados por ano.
10. Adicionado check_password_hash em Usuario.verificar_senha().
"""

import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Optional
import sqlite3
import uuid
from contextlib import contextmanager

from werkzeug.security import generate_password_hash, check_password_hash
import holidays

logger = logging.getLogger(__name__)


class Banco:
    """
    Gerencia conexões SQLite com WAL, foreign keys e row_factory.

    Por que não SQLAlchemy?
    ------------------------
    Para SQLite local, o módulo nativo é mais simples e transparente.
    A migração para SQLAlchemy, se necessária no futuro, é uma
    refatoração clara e justificável em entrevista.

    Modo :memory:
    --------------
    SQLite em memória perde dados ao fechar a conexão. Para testes,
    mantemos uma conexão persistente via `_conn_persistente`.
    """

    def __init__(self, db_path: str = "financas.db"):
        self.db_path = db_path
        # Conexão persistente para :memory: (evita perda de dados entre calls)
        self._conn_persistente: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            self._conn_persistente = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn_persistente.execute("PRAGMA foreign_keys = ON")
            self._conn_persistente.row_factory = sqlite3.Row

    @contextmanager
    def get_conn(self):
        """Context manager que garante commit/rollback automático."""
        if self._conn_persistente is not None:
            # Modo :memory: — reutiliza a mesma conexão
            conn = self._conn_persistente
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        else:
            # Modo arquivo — abre/fecha a cada chamada (thread-safe com WAL)
            conn = sqlite3.connect(
                self.db_path, timeout=20.0, check_same_thread=False
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def init_schema(self) -> None:
        """Cria tabelas e índices. Idempotente (IF NOT EXISTS)."""
        with self.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    email      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                    senha_hash TEXT    NOT NULL,
                    nome       TEXT    NOT NULL,
                    criado_em  TEXT    DEFAULT CURRENT_TIMESTAMP,
                    ativo      INTEGER DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email);

                CREATE TABLE IF NOT EXISTS categorias (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome       TEXT    NOT NULL,
                    tipo       TEXT    NOT NULL CHECK(tipo IN ('receita','despesa')),
                    usuario_id INTEGER NOT NULL,
                    icone      TEXT    DEFAULT '💰',
                    cor        TEXT    DEFAULT '#a855f7',
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
                    UNIQUE(nome, usuario_id)
                );
                CREATE INDEX IF NOT EXISTS idx_categorias_user ON categorias(usuario_id);

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
                    deletado        INTEGER DEFAULT 0,
                    recorrente_uuid TEXT,
                    FOREIGN KEY (categoria_id) REFERENCES categorias(id),
                    FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_trans_user_data  ON transacoes(usuario_id, data DESC);
                CREATE INDEX IF NOT EXISTS idx_trans_user_tipo  ON transacoes(usuario_id, tipo);
                CREATE INDEX IF NOT EXISTS idx_trans_deletado   ON transacoes(deletado);
                CREATE INDEX IF NOT EXISTS idx_trans_uuid       ON transacoes(uuid);
                CREATE INDEX IF NOT EXISTS idx_trans_recorrente ON transacoes(recorrente_uuid);

                CREATE TABLE IF NOT EXISTS recorrentes (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid           TEXT    UNIQUE NOT NULL,
                    descricao      TEXT    NOT NULL,
                    valor          REAL    NOT NULL CHECK(valor > 0),
                    tipo           TEXT    NOT NULL CHECK(tipo IN ('receita','despesa')),
                    categoria_id   INTEGER,
                    dia_vencimento INTEGER NOT NULL CHECK(
                        (dia_vencimento BETWEEN 1 AND 28) OR
                        (dia_vencimento BETWEEN -31 AND -1)
                    ),
                    ativo      INTEGER DEFAULT 1,
                    usuario_id INTEGER NOT NULL,
                    criado_em  TEXT    DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (categoria_id) REFERENCES categorias(id),
                    FOREIGN KEY (usuario_id)   REFERENCES usuarios(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_recorrentes_user ON recorrentes(usuario_id, ativo);
            """)


class CalendarioUtil:
    """Calcula dias úteis brasileiros com cache de feriados por ano."""

    def __init__(self):
        self._cache: dict[int, object] = {}

    def _feriados(self, ano: int):
        if ano not in self._cache:
            self._cache[ano] = holidays.Brazil(years=ano)
        return self._cache[ano]

    def eh_dia_util(self, data: date) -> bool:
        if data.weekday() >= 5:
            return False
        return data not in self._feriados(data.year)

    def proximo_dia_util(self, data: date) -> date:
        while not self.eh_dia_util(data):
            data += timedelta(days=1)
        return data

    def dia_util_do_mes(self, ano: int, mes: int, n: int) -> date:
        """Retorna o N-ésimo dia útil do mês. Se N > total, retorna o último."""
        if n < 1:
            raise ValueError("n deve ser >= 1")
        data = date(ano, mes, 1)
        ultimo = calendar.monthrange(ano, mes)[1]
        contagem = 0
        while data.day <= ultimo:
            if self.eh_dia_util(data):
                contagem += 1
                if contagem == n:
                    return data
            data += timedelta(days=1)
        # Fallback: último dia útil
        data = date(ano, mes, ultimo)
        while not self.eh_dia_util(data):
            data -= timedelta(days=1)
        return data


class Usuario:
    """
    CRUD de usuários com Werkzeug password hashing (pbkdf2:sha256).

    Segurança: nunca retorne mensagens distintas para "usuário não existe"
    vs "senha errada" — isso vaza informação sobre cadastros.
    """

    def __init__(self, banco: Banco):
        self.banco = banco

    def criar_usuario(self, email: str, senha: str, nome: str) -> int:
        """
        Cria usuário.

        Raises:
            ValueError: Dados inválidos ou email duplicado.
        Returns:
            int: ID do usuário criado.
        """
        email = email.strip().lower()
        nome = nome.strip()

        if not email or "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Email inválido")
        if len(senha) < 6:
            raise ValueError("Senha deve ter ao menos 6 caracteres")
        if not nome:
            raise ValueError("Nome não pode ser vazio")

        try:
            with self.banco.get_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                    (email, generate_password_hash(senha), nome),
                )
                return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"Email '{email}' já está cadastrado")

    def verificar_senha(self, email: str, senha: str) -> Optional[sqlite3.Row]:
        """Autentica usuário. Retorna Row ou None — nunca distingue o motivo."""
        row = self.buscar_por_email(email)
        if row and check_password_hash(row["senha_hash"], senha):
            return row
        return None

    def buscar_por_email(self, email: str) -> Optional[sqlite3.Row]:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, email, senha_hash, nome FROM usuarios WHERE email = ? AND ativo = 1",
                (email.strip().lower(),),
            )
            return cur.fetchone()

    def buscar_por_id(self, user_id: int) -> Optional[sqlite3.Row]:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, email, senha_hash, nome FROM usuarios WHERE id = ? AND ativo = 1",
                (int(user_id),),
            )
            return cur.fetchone()


class Categoria:
    """CRUD de categorias isoladas por usuário."""

    CATEGORIAS_PADRAO = [
        ("Salário",       "receita", "💼", "#22c55e"),
        ("Freelance",     "receita", "💻", "#06b6d4"),
        ("Investimentos", "receita", "📈", "#10b981"),
        ("Outros",        "receita", "💰", "#a855f7"),
        ("Moradia",       "despesa", "🏠", "#ef4444"),
        ("Alimentação",   "despesa", "🍕", "#f97316"),
        ("Transporte",    "despesa", "🚗", "#eab308"),
        ("Saúde",         "despesa", "❤️",  "#ec4899"),
        ("Lazer",         "despesa", "🎮", "#8b5cf6"),
        ("Educação",      "despesa", "📚", "#06b6d4"),
        ("Vestuário",     "despesa", "👕", "#14b8a6"),
        ("Assinaturas",   "despesa", "📱", "#6366f1"),
        ("Outros",        "despesa", "💸", "#6b7280"),
    ]

    def __init__(self, banco: Banco):
        self.banco = banco

    def criar_padrao(self, usuario_id: int) -> None:
        with self.banco.get_conn() as conn:
            for nome, tipo, icone, cor in self.CATEGORIAS_PADRAO:
                try:
                    conn.execute(
                        "INSERT INTO categorias (nome, tipo, usuario_id, icone, cor) VALUES (?, ?, ?, ?, ?)",
                        (nome, tipo, usuario_id, icone, cor),
                    )
                except sqlite3.IntegrityError:
                    pass

    def listar_por_usuario(self, usuario_id: int) -> list:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, nome, tipo, icone, cor FROM categorias WHERE usuario_id = ? ORDER BY tipo, nome",
                (usuario_id,),
            )
            return cur.fetchall()

    def listar_todas(self, usuario_id: int) -> list:
        """Alias de listar_por_usuario (retrocompatibilidade)."""
        return self.listar_por_usuario(usuario_id)


class Transacao:
    """
    CRUD de transações: avulsas, parceladas, recorrentes.

    Design: parcelas são N transações independentes com descrição "X (i/N)".
    Se futuramente precisar editar todas as parcelas de uma vez, adicione
    uma coluna grupo_uuid como evolução natural — sem quebrar o esquema atual.
    """

    def __init__(self, banco: Banco, calendario: CalendarioUtil):
        self.banco = banco
        self.calendario = calendario

    @staticmethod
    def _validar_data(data_str: str) -> None:
        try:
            datetime.strptime(data_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValueError(f"Data inválida: '{data_str}'. Use YYYY-MM-DD")

    @staticmethod
    def _validar_tipo(tipo: str) -> None:
        if tipo not in ("receita", "despesa"):
            raise ValueError("Tipo deve ser 'receita' ou 'despesa'")

    def adicionar(
        self,
        descricao: str,
        valor: float,
        tipo: str,
        categoria_id: Optional[int],
        usuario_id: int,
        data: Optional[str] = None,
        recorrente_uuid: Optional[str] = None,
    ) -> int:
        if not descricao or not descricao.strip():
            raise ValueError("Descrição não pode ser vazia")
        if valor <= 0:
            raise ValueError("Valor deve ser maior que zero")
        self._validar_tipo(tipo)
        data = data or date.today().strftime("%Y-%m-%d")
        self._validar_data(data)

        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO transacoes
                   (uuid, descricao, valor, tipo, categoria_id, data, usuario_id, recorrente_uuid)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), descricao.strip(), round(valor, 2),
                 tipo, categoria_id, data, usuario_id, recorrente_uuid),
            )
            return cur.lastrowid

    def adicionar_parcelado(
        self,
        descricao: str,
        valor_total: float,
        tipo: str,
        categoria_id: Optional[int],
        usuario_id: int,
        parcelas: int,
        data_inicial: Optional[str] = None,
        tipo_juros: str = "sem",
        taxa_juros_mensal: float = 0.0,
    ) -> list[int]:
        """
        Insere N transações representando parcelamento.

        CORREÇÃO: usava timedelta(days=30*i) — errado.
        Agora avança mês a mês com calendar.monthrange para respeitar
        fevereiro, meses com 31 dias, etc.
        """
        if parcelas < 2 or parcelas > 60:
            raise ValueError("Parcelas deve ser entre 2 e 60")
        self._validar_tipo(tipo)

        valores = self.calcular_preview_parcelas(valor_total, parcelas, tipo_juros, taxa_juros_mensal)

        if data_inicial:
            self._validar_data(data_inicial)
            data_base = datetime.strptime(data_inicial, "%Y-%m-%d")
        else:
            data_base = datetime.now()

        ids = []
        for i, valor_parcela in enumerate(valores):
            mes = data_base.month + i
            ano = data_base.year + (mes - 1) // 12
            mes = ((mes - 1) % 12) + 1
            dia = min(data_base.day, calendar.monthrange(ano, mes)[1])
            data_parcela = date(ano, mes, dia)

            ids.append(self.adicionar(
                f"{descricao} ({i + 1}/{parcelas})", valor_parcela, tipo,
                categoria_id, usuario_id, data_parcela.strftime("%Y-%m-%d"),
            ))
        return ids

    def calcular_preview_parcelas(
        self,
        valor_total: float,
        parcelas: int,
        tipo_juros: str,
        taxa_mensal: float,
    ) -> list[float]:
        """
        Calcula valor de cada parcela.

        Regimes:
        - 'sem':     Sem juros. Arredondamento na 1ª parcela.
        - 'simples': Juros simples. Total = PV * (1 + taxa * n).
        - 'price':   Tabela Price. PMT = PV * [i(1+i)^n] / [(1+i)^n - 1].

        Arredondamento: o centavo perdido vai para a 1ª parcela,
        garantindo sum(parcelas) == valor_total (para juros sem/simples).
        """
        if parcelas < 1:
            raise ValueError("Número de parcelas deve ser >= 1")

        if tipo_juros == "sem" or taxa_mensal == 0:
            base = round(valor_total / parcelas, 2)
            valores = [base] * parcelas
            diff = round(valor_total - base * parcelas, 2)
            valores[0] = round(valores[0] + diff, 2)

        elif tipo_juros == "simples":
            total = valor_total * (1 + (taxa_mensal / 100) * parcelas)
            base = round(total / parcelas, 2)
            valores = [base] * parcelas
            diff = round(total - base * parcelas, 2)
            valores[0] = round(valores[0] + diff, 2)

        else:  # price
            taxa = taxa_mensal / 100
            if taxa == 0:
                return self.calcular_preview_parcelas(valor_total, parcelas, "sem", 0)
            fator = (1 + taxa) ** parcelas
            pmt = valor_total * (taxa * fator) / (fator - 1)
            valores = [round(pmt, 2)] * parcelas

        return valores

    def resumo_mes(self, ano: int, mes: int, usuario_id: int) -> tuple[float, float, float]:
        """Retorna (receitas, despesas, saldo) do mês."""
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT tipo, COALESCE(SUM(valor), 0)
                   FROM transacoes
                   WHERE usuario_id = ? AND strftime('%Y-%m', data) = ? AND deletado = 0
                   GROUP BY tipo""",
                (usuario_id, f"{ano}-{mes:02d}"),
            )
            totais = {row[0]: row[1] for row in cur.fetchall()}
        receitas = totais.get("receita", 0.0)
        despesas = totais.get("despesa", 0.0)
        return receitas, despesas, receitas - despesas

    def saldo_total(self, usuario_id: int) -> float:
        """Saldo histórico acumulado (todas as transações não deletadas)."""
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT COALESCE(
                       SUM(CASE WHEN tipo='receita' THEN valor ELSE -valor END), 0)
                   FROM transacoes WHERE usuario_id = ? AND deletado = 0""",
                (usuario_id,),
            )
            return cur.fetchone()[0]

    def gastos_por_categoria(self, ano: int, mes: int, usuario_id: int) -> list:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT COALESCE(c.nome, 'Sem categoria') as nome,
                          COALESCE(SUM(t.valor), 0) as total,
                          COALESCE(c.cor, '#6b7280') as cor
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   WHERE t.usuario_id = ? AND strftime('%Y-%m', t.data) = ?
                     AND t.tipo = 'despesa' AND t.deletado = 0
                   GROUP BY c.nome, c.cor
                   ORDER BY total DESC""",
                (usuario_id, f"{ano}-{mes:02d}"),
            )
            return cur.fetchall()

    def evolucao_saldo_mes(self, ano: int, mes: int, usuario_id: int) -> list[tuple]:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT CAST(strftime('%d', data) AS INTEGER) as dia,
                          SUM(CASE WHEN tipo='receita' THEN valor ELSE -valor END) as saldo_dia
                   FROM transacoes
                   WHERE usuario_id = ? AND strftime('%Y-%m', data) = ? AND deletado = 0
                   GROUP BY dia ORDER BY dia""",
                (usuario_id, f"{ano}-{mes:02d}"),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    def listar_por_periodo(self, data_inicio: str, data_fim: str, usuario_id: int) -> list:
        self._validar_data(data_inicio)
        self._validar_data(data_fim)
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT t.id, t.descricao, t.valor, t.tipo,
                          COALESCE(c.nome, 'Sem categoria'), t.data,
                          COALESCE(c.icone, '💰'), t.recorrente_uuid, t.uuid,
                          COALESCE(t.categoria_id, 0)
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   WHERE t.usuario_id = ? AND t.data BETWEEN ? AND ? AND t.deletado = 0
                   ORDER BY t.data DESC, t.criado_em DESC""",
                (usuario_id, data_inicio, data_fim),
            )
            return cur.fetchall()

    def buscar_por_uuid(self, uuid_transacao: str, usuario_id: int) -> Optional[dict]:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT t.id, t.uuid, t.descricao, t.valor, t.tipo,
                          t.categoria_id, t.data, COALESCE(c.nome, 'Sem categoria') as categoria_nome
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   WHERE t.uuid = ? AND t.usuario_id = ? AND t.deletado = 0""",
                (uuid_transacao, usuario_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def editar(self, id_transacao: int, usuario_id: int, **kwargs) -> bool:
        sets, params = [], []
        mapa = {
            "descricao":    ("descricao",    lambda v: v.strip()),
            "valor":        ("valor",        lambda v: round(float(v), 2)),
            "tipo":         ("tipo",         lambda v: v),
            "categoria_id": ("categoria_id", int),
            "data":         ("data",         lambda v: v),
        }
        for chave, (coluna, transform) in mapa.items():
            if chave in kwargs and kwargs[chave] is not None:
                if chave == "data":
                    self._validar_data(kwargs[chave])
                if chave == "tipo":
                    self._validar_tipo(kwargs[chave])
                if chave == "valor" and float(kwargs[chave]) <= 0:
                    raise ValueError("Valor deve ser maior que zero")
                sets.append(f"{coluna} = ?")
                params.append(transform(kwargs[chave]))

        if not sets:
            return False
        params.extend([id_transacao, usuario_id])
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                f"UPDATE transacoes SET {', '.join(sets)} "
                f"WHERE id = ? AND usuario_id = ? AND deletado = 0",
                params,
            )
            return cur.rowcount > 0

    def deletar(self, id_transacao: int, usuario_id: int) -> bool:
        """Deleção lógica — preserva histórico para auditoria."""
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "UPDATE transacoes SET deletado = 1 WHERE id = ? AND usuario_id = ?",
                (id_transacao, usuario_id),
            )
            return cur.rowcount > 0

    def restaurar(self, id_transacao: int, usuario_id: int) -> bool:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "UPDATE transacoes SET deletado = 0 WHERE id = ? AND usuario_id = ?",
                (id_transacao, usuario_id),
            )
            return cur.rowcount > 0


class Recorrente:
    """
    Gerencia lançamentos recorrentes mensais.

    Convenção de dia_vencimento:
      1-28  → dia fixo (máximo 28 para compatibilidade com fevereiro)
      -1 a -31 → N-ésimo dia útil (abs(dia))
    """

    def __init__(self, banco: Banco, calendario: CalendarioUtil):
        self.banco = banco
        self.calendario = calendario

    def _validar_dia(self, dia: int) -> None:
        if not (1 <= dia <= 28 or -31 <= dia <= -1):
            raise ValueError("Dia deve ser entre 1-28 ou -1 a -31")

    def _calcular_data_vencimento(self, ano: int, mes: int, dia: int) -> date:
        if dia < 0:
            return self.calendario.dia_util_do_mes(ano, mes, abs(dia))
        ultimo = calendar.monthrange(ano, mes)[1]
        return self.calendario.proximo_dia_util(date(ano, mes, min(dia, ultimo)))

    def adicionar(
        self,
        descricao: str,
        valor: float,
        tipo: str,
        categoria_id: Optional[int],
        dia_vencimento: int,
        usuario_id: int,
    ) -> int:
        self._validar_dia(dia_vencimento)
        if valor <= 0:
            raise ValueError("Valor deve ser maior que zero")
        if tipo not in ("receita", "despesa"):
            raise ValueError("Tipo deve ser 'receita' ou 'despesa'")
        if not descricao or not descricao.strip():
            raise ValueError("Descrição não pode ser vazia")

        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO recorrentes
                   (uuid, descricao, valor, tipo, categoria_id, dia_vencimento, usuario_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), descricao.strip(), round(valor, 2),
                 tipo, categoria_id, dia_vencimento, usuario_id),
            )
            return cur.lastrowid

    def listar_todos(self, usuario_id: int) -> list:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT r.id, r.descricao, r.valor, r.tipo,
                          COALESCE(c.nome, 'Sem categoria'), r.dia_vencimento,
                          r.uuid, r.ativo, COALESCE(r.categoria_id, 0)
                   FROM recorrentes r
                   LEFT JOIN categorias c ON r.categoria_id = c.id
                   WHERE r.usuario_id = ? AND r.ativo = 1
                   ORDER BY r.dia_vencimento""",
                (usuario_id,),
            )
            return cur.fetchall()

    def buscar_por_uuid(self, uuid_rec: str, usuario_id: int) -> Optional[sqlite3.Row]:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT id, descricao, valor, tipo, categoria_id, dia_vencimento, uuid
                   FROM recorrentes WHERE uuid = ? AND usuario_id = ? AND ativo = 1""",
                (uuid_rec, usuario_id),
            )
            return cur.fetchone()

    def editar(self, uuid_recorrente: str, usuario_id: int, **kwargs) -> bool:
        sets, params = [], []
        if "descricao" in kwargs and kwargs["descricao"]:
            sets.append("descricao = ?"); params.append(kwargs["descricao"].strip())
        if "valor" in kwargs and kwargs["valor"] is not None:
            if float(kwargs["valor"]) <= 0:
                raise ValueError("Valor deve ser maior que zero")
            sets.append("valor = ?"); params.append(round(float(kwargs["valor"]), 2))
        if "tipo" in kwargs and kwargs["tipo"]:
            if kwargs["tipo"] not in ("receita", "despesa"):
                raise ValueError("Tipo inválido")
            sets.append("tipo = ?"); params.append(kwargs["tipo"])
        if "categoria_id" in kwargs and kwargs["categoria_id"] is not None:
            sets.append("categoria_id = ?"); params.append(int(kwargs["categoria_id"]))
        if "dia_vencimento" in kwargs and kwargs["dia_vencimento"] is not None:
            self._validar_dia(int(kwargs["dia_vencimento"]))
            sets.append("dia_vencimento = ?"); params.append(int(kwargs["dia_vencimento"]))

        if not sets:
            return False
        params.extend([uuid_recorrente, usuario_id])
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                f"UPDATE recorrentes SET {', '.join(sets)} "
                f"WHERE uuid = ? AND usuario_id = ? AND ativo = 1",
                params,
            )
            return cur.rowcount > 0

    def desativar(self, uuid_recorrente: str, usuario_id: int) -> bool:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "UPDATE recorrentes SET ativo = 0 WHERE uuid = ? AND usuario_id = ?",
                (uuid_recorrente, usuario_id),
            )
            return cur.rowcount > 0

    def listar_proximos_do_mes(self, ano: int, mes: int, usuario_id: int) -> list[dict]:
        """
        Lista recorrências do mês com status.
        CORREÇÃO: ordenação por date object, não por string 'DD/MM/YYYY'.
        """
        hoje = date.today()
        todos = []

        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT uuid, descricao, valor, tipo, categoria_id, dia_vencimento
                   FROM recorrentes WHERE usuario_id = ? AND ativo = 1""",
                (usuario_id,),
            )
            recorrentes = cur.fetchall()

            for rec_uuid, desc, valor, tipo, cat_id, dia in recorrentes:
                data_venc = self._calcular_data_vencimento(ano, mes, dia)
                cur_check = conn.execute(
                    """SELECT COUNT(*) FROM transacoes
                       WHERE recorrente_uuid = ?
                         AND strftime('%Y-%m', data) = ?
                         AND deletado = 0""",
                    (rec_uuid, f"{ano}-{mes:02d}"),
                )
                ja_lancado = cur_check.fetchone()[0] > 0
                status = "lancado" if ja_lancado else ("agendado" if data_venc >= hoje else "passado")

                todos.append({
                    "uuid": rec_uuid, "descricao": desc, "valor": valor,
                    "tipo": tipo, "categoria_id": cat_id,
                    "data_obj": data_venc,  # usado só para ordenação
                    "data": data_venc.strftime("%d/%m/%Y"),
                    "dia_original": dia, "status": status,
                })

        return sorted(todos, key=lambda x: x["data_obj"])

    def gerar_transacoes_mes(
        self, ano: int, mes: int, usuario_id: int, transacao_obj: "Transacao"
    ) -> int:
        """
        Lança recorrências vencidas ainda não lançadas.

        CORREÇÃO DE DEADLOCK: a versão original usava _lock global.
        gerar_transacoes_mes() → adicionar() → mesmo lock → deadlock.
        Solução: sem _lock global. WAL do SQLite gerencia concorrência.

        Returns:
            int: Número de transações geradas nesta chamada.
        """
        hoje = date.today()
        geradas = 0

        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT uuid, descricao, valor, tipo, categoria_id, dia_vencimento
                   FROM recorrentes WHERE usuario_id = ? AND ativo = 1""",
                (usuario_id,),
            )
            recorrentes = cur.fetchall()

        # Itera fora da conexão aberta — evita conexões aninhadas
        for rec_uuid, desc, valor, tipo, cat_id, dia in recorrentes:
            data_venc = self._calcular_data_vencimento(ano, mes, dia)
            if data_venc > hoje:
                continue

            with self.banco.get_conn() as conn:
                count = conn.execute(
                    """SELECT COUNT(*) FROM transacoes
                       WHERE recorrente_uuid = ?
                         AND strftime('%Y-%m', data) = ?
                         AND deletado = 0""",
                    (rec_uuid, f"{ano}-{mes:02d}"),
                ).fetchone()[0]

            if count == 0:
                transacao_obj.adicionar(
                    desc, valor, tipo, cat_id, usuario_id,
                    data_venc.strftime("%Y-%m-%d"),
                    recorrente_uuid=rec_uuid,
                )
                geradas += 1

        return geradas