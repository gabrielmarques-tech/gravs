"""
financeiro.py — Camada de dados e regras de negócio do Gravs.

Estrutura de classes:
    Banco           → Conexão SQLite, schema e migrations
    CalendarioUtil  → Lógica de dias úteis (feriados BR via `holidays`)
    Usuario         → CRUD de usuários
    Categoria       → CRUD de categorias por usuário
    Transacao       → Lançamentos avulsos e parcelados
    Recorrente      → Lançamentos recorrentes (fixos mensais)
    SistemaFinanceiro → Singleton que agrega todas as classes acima

Convenções importantes:
    - Todos os métodos recebem `usuario_id` para garantir isolamento entre contas.
    - Deleção é sempre lógica (campo `deletado = 1`), nunca física.
    - Dias negativos em recorrentes representam "N-ésimo dia útil" (ex.: -1 = 1º dia útil).
    - Valores monetários são armazenados como REAL e arredondados em 2 casas.
"""

import calendar
from datetime import date, datetime, timedelta
import sqlite3
import uuid
from contextlib import contextmanager
from werkzeug.security import generate_password_hash
import threading
import holidays

# Lock global para serializar escritas concorrentes ao banco.
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------

class Banco:
    def __init__(self, db_path: str = 'financas.db'):
        self.db_path = db_path

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=20.0, check_same_thread=False)
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

    def init_schema(self):
        with _lock:
            with self.get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS usuarios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        senha_hash TEXT NOT NULL,
                        nome TEXT NOT NULL,
                        criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
                        ativo INTEGER DEFAULT 1
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS categorias (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT NOT NULL,
                        tipo TEXT NOT NULL CHECK(tipo IN ('receita', 'despesa')),
                        usuario_id INTEGER NOT NULL,
                        icone TEXT DEFAULT '💰',
                        cor TEXT DEFAULT '#a855f7',
                        FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE,
                        UNIQUE(nome, usuario_id)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_categorias_user ON categorias(usuario_id)")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS transacoes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uuid TEXT UNIQUE NOT NULL,
                        descricao TEXT NOT NULL,
                        valor REAL NOT NULL CHECK(valor > 0),
                        tipo TEXT NOT NULL CHECK(tipo IN ('receita', 'despesa')),
                        categoria_id INTEGER,
                        data TEXT NOT NULL,
                        usuario_id INTEGER NOT NULL,
                        criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
                        deletado INTEGER DEFAULT 0,
                        recorrente_uuid TEXT,
                        FOREIGN KEY (categoria_id) REFERENCES categorias (id),
                        FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trans_user_data ON transacoes(usuario_id, data DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trans_user_tipo ON transacoes(usuario_id, tipo)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trans_deletado ON transacoes(deletado)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trans_uuid ON transacoes(uuid)")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS recorrentes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uuid TEXT UNIQUE NOT NULL,
                        descricao TEXT NOT NULL,
                        valor REAL NOT NULL CHECK(valor > 0),
                        tipo TEXT NOT NULL CHECK(tipo IN ('receita', 'despesa')),
                        categoria_id INTEGER,
                        dia_vencimento INTEGER NOT NULL CHECK(
                            (dia_vencimento BETWEEN 1 AND 28) OR
                            (dia_vencimento BETWEEN -31 AND -1)
                        ),
                        ativo INTEGER DEFAULT 1,
                        usuario_id INTEGER NOT NULL,
                        criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (categoria_id) REFERENCES categorias (id),
                        FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_recorrentes_user ON recorrentes(usuario_id, ativo)")


# ---------------------------------------------------------------------------
# Utilitários de calendário
# ---------------------------------------------------------------------------

class CalendarioUtil:
    def __init__(self):
        self.br_holidays = holidays.Brazil()

    def eh_dia_util(self, data: date) -> bool:
        if data.weekday() >= 5:
            return False
        if data in self.br_holidays:
            return False
        return True

    def proximo_dia_util(self, data: date) -> date:
        while not self.eh_dia_util(data):
            data += timedelta(days=1)
        return data

    def dia_util_do_mes(self, ano: int, mes: int, n: int) -> date:
        """Retorna o N-ésimo dia útil do mês."""
        data = date(ano, mes, 1)
        contagem = 0
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        while data.day <= ultimo_dia:
            if self.eh_dia_util(data):
                contagem += 1
                if contagem == n:
                    return data
            data += timedelta(days=1)
        # Se N > dias úteis no mês, retorna o último dia útil
        data = date(ano, mes, ultimo_dia)
        while not self.eh_dia_util(data):
            data -= timedelta(days=1)
        return data


# ---------------------------------------------------------------------------
# Usuário
# ---------------------------------------------------------------------------

class Usuario:
    def __init__(self, banco: Banco):
        self.banco = banco

    def criar_usuario(self, email: str, senha: str, nome: str) -> int | None:
        if len(senha) < 6:
            raise ValueError("Senha deve ter ao menos 6 caracteres")
        if not email or '@' not in email:
            raise ValueError("Email inválido")
        nome = nome.strip()
        if not nome:
            raise ValueError("Nome não pode ser vazio")

        senha_hash = generate_password_hash(senha)
        try:
            with self.banco.get_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                    (email.lower().strip(), senha_hash, nome)
                )
                return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def buscar_por_email(self, email: str):
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, email, senha_hash, nome FROM usuarios WHERE email = ? AND ativo = 1",
                (email.lower().strip(),)
            )
            return cur.fetchone()

    def buscar_por_id(self, user_id: int):
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, email, senha_hash, nome FROM usuarios WHERE id = ? AND ativo = 1",
                (int(user_id),)
            )
            return cur.fetchone()


# ---------------------------------------------------------------------------
# Categoria
# ---------------------------------------------------------------------------

class Categoria:
    CATEGORIAS_PADRAO = [
        ('Salário', 'receita', '💼', '#22c55e'),
        ('Freelance', 'receita', '💻', '#06b6d4'),
        ('Outros', 'receita', '💰', '#a855f7'),
        ('Moradia', 'despesa', '🏠', '#ef4444'),
        ('Alimentação', 'despesa', '🍕', '#f97316'),
        ('Transporte', 'despesa', '🚗', '#eab308'),
        ('Saúde', 'despesa', '❤️', '#ec4899'),
        ('Lazer', 'despesa', '🎮', '#8b5cf6'),
        ('Educação', 'despesa', '📚', '#06b6d4'),
        ('Vestuário', 'despesa', '👕', '#14b8a6'),
        ('Assinaturas', 'despesa', '📱', '#6366f1'),
        ('Outros', 'despesa', '💸', '#6b7280'),
    ]

    def __init__(self, banco: Banco):
        self.banco = banco

    def criar_padrao(self, usuario_id: int) -> None:
        with self.banco.get_conn() as conn:
            for nome, tipo, icone, cor in self.CATEGORIAS_PADRAO:
                try:
                    conn.execute(
                        "INSERT INTO categorias (nome, tipo, usuario_id, icone, cor) VALUES (?, ?, ?, ?, ?)",
                        (nome, tipo, usuario_id, icone, cor)
                    )
                except sqlite3.IntegrityError:
                    pass

    def listar_por_usuario(self, usuario_id: int) -> list:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, nome, tipo, icone, cor FROM categorias WHERE usuario_id = ? ORDER BY tipo, nome",
                (usuario_id,)
            )
            return cur.fetchall()

    def listar_todas(self, usuario_id: int) -> list:
        return self.listar_por_usuario(usuario_id)


# ---------------------------------------------------------------------------
# Transação
# ---------------------------------------------------------------------------

class Transacao:
    def __init__(self, banco: Banco, calendario: CalendarioUtil):
        self.banco = banco
        self.calendario = calendario

    def adicionar(self, descricao: str, valor: float, tipo: str,
                  categoria_id: int, usuario_id: int, data: str = None,
                  recorrente_uuid: str = None) -> int:
        if valor <= 0:
            raise ValueError("Valor deve ser maior que zero")
        if tipo not in ('receita', 'despesa'):
            raise ValueError("Tipo deve ser 'receita' ou 'despesa'")
        if not descricao or not descricao.strip():
            raise ValueError("Descrição não pode ser vazia")

        data = data or date.today().strftime("%Y-%m-%d")
        uid = str(uuid.uuid4())

        with _lock:
            with self.banco.get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO transacoes
                       (uuid, descricao, valor, tipo, categoria_id, data, usuario_id, recorrente_uuid)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (uid, descricao.strip(), round(valor, 2), tipo,
                     categoria_id, data, usuario_id, recorrente_uuid)
                )
                return cur.lastrowid

    def adicionar_parcelado(self, descricao: str, valor_total: float, tipo: str,
                             categoria_id: int, usuario_id: int, parcelas: int,
                             data_inicial: str = None, tipo_juros: str = 'sem',
                             taxa_juros_mensal: float = 0) -> list[int]:
        if parcelas < 2 or parcelas > 60:
            raise ValueError("Parcelas deve ser entre 2 e 60")

        valores = self.calcular_preview_parcelas(valor_total, parcelas, tipo_juros, taxa_juros_mensal)

        if data_inicial:
            data_base = datetime.strptime(data_inicial, "%Y-%m-%d")
        else:
            data_base = datetime.now()

        ids = []
        for i, valor_parcela in enumerate(valores):
            data_parcela = data_base + timedelta(days=30 * i)
            desc_parcela = f"{descricao} ({i+1}/{parcelas})"
            id_transacao = self.adicionar(
                desc_parcela, valor_parcela, tipo,
                categoria_id, usuario_id,
                data_parcela.strftime("%Y-%m-%d")
            )
            ids.append(id_transacao)
        return ids

    def calcular_preview_parcelas(self, valor_total: float, parcelas: int,
                                   tipo_juros: str, taxa_mensal: float) -> list[float]:
        if tipo_juros == 'sem' or taxa_mensal == 0:
            base = round(valor_total / parcelas, 2)
            valores = [base] * parcelas
            diff = round(valor_total - base * parcelas, 2)
            valores[0] = round(valores[0] + diff, 2)
        elif tipo_juros == 'simples':
            total = valor_total * (1 + (taxa_mensal / 100) * parcelas)
            base = round(total / parcelas, 2)
            valores = [base] * parcelas
        else:  # price
            taxa = taxa_mensal / 100
            if taxa == 0:
                base = round(valor_total / parcelas, 2)
                valores = [base] * parcelas
            else:
                pmt = valor_total * (taxa * (1 + taxa) ** parcelas) / ((1 + taxa) ** parcelas - 1)
                valores = [round(pmt, 2)] * parcelas
        return valores

    def resumo_mes(self, ano: int, mes: int, usuario_id: int) -> tuple[float, float, float]:
        with self.banco.get_conn() as conn:
            cur = conn.execute("""
                SELECT tipo, SUM(valor) FROM transacoes
                WHERE usuario_id = ? AND strftime('%Y-%m', data) = ? AND deletado = 0
                GROUP BY tipo
            """, (usuario_id, f"{ano}-{mes:02d}"))
            totais = {row[0]: row[1] for row in cur.fetchall()}
        receitas = totais.get('receita', 0)
        despesas = totais.get('despesa', 0)
        return receitas, despesas, receitas - despesas

    def gastos_por_categoria(self, ano: int, mes: int, usuario_id: int) -> list[tuple]:
        with self.banco.get_conn() as conn:
            cur = conn.execute("""
                SELECT c.nome, SUM(t.valor), c.cor
                FROM transacoes t
                LEFT JOIN categorias c ON t.categoria_id = c.id
                WHERE t.usuario_id = ? AND strftime('%Y-%m', t.data) = ?
                  AND t.tipo = 'despesa' AND t.deletado = 0
                GROUP BY c.nome, c.cor
                ORDER BY SUM(t.valor) DESC
            """, (usuario_id, f"{ano}-{mes:02d}"))
            return cur.fetchall()

    def evolucao_saldo_mes(self, ano: int, mes: int, usuario_id: int) -> list[tuple]:
        with self.banco.get_conn() as conn:
            cur = conn.execute("""
                SELECT strftime('%d', data) as dia,
                       SUM(CASE WHEN tipo='receita' THEN valor ELSE -valor END) as saldo_dia
                FROM transacoes
                WHERE usuario_id = ? AND strftime('%Y-%m', data) = ? AND deletado = 0
                GROUP BY dia ORDER BY dia
            """, (usuario_id, f"{ano}-{mes:02d}"))
            return [(int(row[0]), row[1]) for row in cur.fetchall()]

    def listar_por_periodo(self, data_inicio: str, data_fim: str, usuario_id: int) -> list:
        with self.banco.get_conn() as conn:
            cur = conn.execute("""
                SELECT t.id, t.descricao, t.valor, t.tipo, c.nome, t.data,
                       COALESCE(c.icone, '💰'), t.recorrente_uuid, t.uuid,
                       COALESCE(t.categoria_id, 0)
                FROM transacoes t
                LEFT JOIN categorias c ON t.categoria_id = c.id
                WHERE t.usuario_id = ? AND t.data BETWEEN ? AND ? AND t.deletado = 0
                ORDER BY t.data DESC, t.criado_em DESC
            """, (usuario_id, data_inicio, data_fim))
            return cur.fetchall()

    def buscar_por_uuid(self, uuid_transacao: str, usuario_id: int) -> dict | None:
        with self.banco.get_conn() as conn:
            cur = conn.execute("""
                SELECT t.id, t.uuid, t.descricao, t.valor, t.tipo,
                       t.categoria_id, t.data, c.nome as categoria_nome
                FROM transacoes t
                LEFT JOIN categorias c ON t.categoria_id = c.id
                WHERE t.uuid = ? AND t.usuario_id = ? AND t.deletado = 0
            """, (uuid_transacao, usuario_id))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def editar(self, id_transacao: int, usuario_id: int, **kwargs) -> bool:
        sets, params = [], []
        mapa = {
            'descricao': ('descricao', lambda v: v.strip()),
            'valor': ('valor', lambda v: round(float(v), 2)),
            'tipo': ('tipo', lambda v: v),
            'categoria_id': ('categoria_id', int),
            'data': ('data', lambda v: v),
        }
        for chave, (coluna, transform) in mapa.items():
            if chave in kwargs and kwargs[chave] is not None:
                sets.append(f"{coluna} = ?")
                params.append(transform(kwargs[chave]))

        if not sets:
            return False

        params.extend([id_transacao, usuario_id])
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                f"UPDATE transacoes SET {', '.join(sets)} WHERE id = ? AND usuario_id = ? AND deletado = 0",
                params
            )
            return cur.rowcount > 0

    def deletar(self, id_transacao: int, usuario_id: int) -> bool:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "UPDATE transacoes SET deletado = 1 WHERE id = ? AND usuario_id = ?",
                (id_transacao, usuario_id)
            )
            return cur.rowcount > 0

    def restaurar(self, id_transacao: int, usuario_id: int) -> bool:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "UPDATE transacoes SET deletado = 0 WHERE id = ? AND usuario_id = ?",
                (id_transacao, usuario_id)
            )
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Recorrente
# ---------------------------------------------------------------------------

class Recorrente:
    def __init__(self, banco: Banco, calendario: CalendarioUtil):
        self.banco = banco
        self.calendario = calendario

    def _validar_dia(self, dia: int) -> None:
        if not (1 <= dia <= 28 or -31 <= dia <= -1):
            raise ValueError("Dia deve ser entre 1-28 (fixo) ou -1 a -31 (dia útil)")

    def adicionar(self, descricao: str, valor: float, tipo: str,
                  categoria_id: int, dia_vencimento: int, usuario_id: int) -> int:
        self._validar_dia(dia_vencimento)
        if valor <= 0:
            raise ValueError("Valor deve ser maior que zero")

        uid = str(uuid.uuid4())
        with _lock:
            with self.banco.get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO recorrentes
                       (uuid, descricao, valor, tipo, categoria_id, dia_vencimento, usuario_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (uid, descricao.strip(), round(valor, 2), tipo,
                     categoria_id, dia_vencimento, usuario_id)
                )
                return cur.lastrowid

    def listar_todos(self, usuario_id: int) -> list:
        with self.banco.get_conn() as conn:
            cur = conn.execute("""
                SELECT r.id, r.descricao, r.valor, r.tipo,
                       COALESCE(c.nome, 'Sem categoria'), r.dia_vencimento,
                       r.uuid, r.ativo, COALESCE(r.categoria_id, 0)
                FROM recorrentes r
                LEFT JOIN categorias c ON r.categoria_id = c.id
                WHERE r.usuario_id = ? AND r.ativo = 1
                ORDER BY r.dia_vencimento
            """, (usuario_id,))
            return cur.fetchall()

    def buscar_por_uuid(self, uuid_rec: str, usuario_id: int):
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT id, descricao, valor, tipo, categoria_id, dia_vencimento, uuid
                   FROM recorrentes WHERE uuid = ? AND usuario_id = ? AND ativo = 1""",
                (uuid_rec, usuario_id)
            )
            return cur.fetchone()

    def editar(self, uuid_recorrente: str, usuario_id: int, **kwargs) -> bool:
        sets, params = [], []

        if 'descricao' in kwargs and kwargs['descricao']:
            sets.append("descricao = ?")
            params.append(kwargs['descricao'].strip())
        if 'valor' in kwargs and kwargs['valor'] is not None:
            if kwargs['valor'] <= 0:
                raise ValueError("Valor deve ser maior que zero")
            sets.append("valor = ?")
            params.append(round(kwargs['valor'], 2))
        if 'tipo' in kwargs and kwargs['tipo']:
            sets.append("tipo = ?")
            params.append(kwargs['tipo'])
        if 'categoria_id' in kwargs and kwargs['categoria_id'] is not None:
            sets.append("categoria_id = ?")
            params.append(kwargs['categoria_id'])
        if 'dia_vencimento' in kwargs and kwargs['dia_vencimento'] is not None:
            self._validar_dia(kwargs['dia_vencimento'])
            sets.append("dia_vencimento = ?")
            params.append(kwargs['dia_vencimento'])

        if not sets:
            return False

        params.extend([uuid_recorrente, usuario_id])
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                f"UPDATE recorrentes SET {', '.join(sets)} WHERE uuid = ? AND usuario_id = ? AND ativo = 1",
                params
            )
            return cur.rowcount > 0

    def desativar(self, uuid_recorrente: str, usuario_id: int) -> bool:
        with self.banco.get_conn() as conn:
            cur = conn.execute(
                "UPDATE recorrentes SET ativo = 0 WHERE uuid = ? AND usuario_id = ?",
                (uuid_recorrente, usuario_id)
            )
            return cur.rowcount > 0

    def _calcular_data_vencimento(self, ano: int, mes: int, dia: int) -> date:
        if dia < 0:
            return self.calendario.dia_util_do_mes(ano, mes, abs(dia))
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        data = date(ano, mes, min(dia, ultimo_dia))
        return self.calendario.proximo_dia_util(data)

    def listar_proximos_do_mes(self, ano: int, mes: int, usuario_id: int,
                                calendario: CalendarioUtil) -> list[dict]:
        hoje = date.today()
        todos = []

        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT uuid, descricao, valor, tipo, categoria_id, dia_vencimento
                   FROM recorrentes WHERE usuario_id = ? AND ativo = 1""",
                (usuario_id,)
            )
            recorrentes = cur.fetchall()

            for rec_uuid, desc, valor, tipo, cat_id, dia in recorrentes:
                data_venc = self._calcular_data_vencimento(ano, mes, dia)

                cur_check = conn.execute("""
                    SELECT COUNT(*) FROM transacoes
                    WHERE recorrente_uuid = ?
                      AND strftime('%Y-%m', data) = ?
                      AND deletado = 0
                """, (rec_uuid, f"{ano}-{mes:02d}"))
                ja_lancado = cur_check.fetchone()[0] > 0

                if ja_lancado:
                    status = 'lancado'
                elif data_venc >= hoje:
                    status = 'agendado'
                else:
                    status = 'passado'

                todos.append({
                    'uuid': rec_uuid,
                    'descricao': desc,
                    'valor': valor,
                    'tipo': tipo,
                    'categoria_id': cat_id,
                    'data': data_venc.strftime("%d/%m/%Y"),
                    'dia_original': dia,
                    'status': status,
                })

        return sorted(todos, key=lambda x: x['data'])

    def gerar_transacoes_mes(self, ano: int, mes: int, usuario_id: int,
                              transacao_obj: 'Transacao') -> None:
        hoje = date.today()

        with self.banco.get_conn() as conn:
            cur = conn.execute(
                """SELECT uuid, descricao, valor, tipo, categoria_id, dia_vencimento
                   FROM recorrentes WHERE usuario_id = ? AND ativo = 1""",
                (usuario_id,)
            )
            recorrentes = cur.fetchall()

            for rec_uuid, desc, valor, tipo, cat_id, dia in recorrentes:
                data_venc = self._calcular_data_vencimento(ano, mes, dia)

                if data_venc > hoje:
                    continue

                cur_check = conn.execute("""
                    SELECT COUNT(*) FROM transacoes
                    WHERE recorrente_uuid = ?
                      AND strftime('%Y-%m', data) = ?
                      AND deletado = 0
                """, (rec_uuid, f"{ano}-{mes:02d}"))

                if cur_check.fetchone()[0] == 0:
                    transacao_obj.adicionar(
                        desc, valor, tipo, cat_id, usuario_id,
                        data_venc.strftime("%Y-%m-%d"),
                        recorrente_uuid=rec_uuid
                    )


# ---------------------------------------------------------------------------
# Sistema Financeiro (Singleton)
# ---------------------------------------------------------------------------

class SistemaFinanceiro:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, db_path: str = 'financas.db'):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance.banco = Banco(db_path)
                    instance.banco.init_schema()
                    instance.calendario = CalendarioUtil()
                    instance.usuario = Usuario(instance.banco)
                    instance.categoria = Categoria(instance.banco)
                    instance.transacao = Transacao(instance.banco, instance.calendario)
                    instance.recorrente = Recorrente(instance.banco, instance.calendario)
                    cls._instance = instance
        return cls._instance