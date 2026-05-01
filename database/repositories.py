"""
database/repositories.py — Repositórios de acesso a dados.

O padrão Repository (Martin Fowler) separa a lógica de consulta SQL
das regras de negócio. Benefícios:

1. Services não escrevem SQL — apenas chamam métodos semânticos
2. Trocar SQLite por PostgreSQL = reescrever apenas os repositórios
3. Testes de service podem usar repositórios falsos (mock/stub)
4. Queries complexas ficam em um só lugar, fáceis de otimizar

Convenções deste arquivo:
- Métodos de leitura: get_conn() sem lock (reads concorrentes são ok)
- Métodos de escrita: get_write_conn() com lock (SQLite single-writer)
- Retorno tipado: sempre dict | None para entidades, list[dict] para coleções
- Soft-delete: deletar = marcar deletado=1, nunca DELETE físico
"""

import logging
import sqlite3
from typing import Any

from database.manager import DatabaseManager

logger = logging.getLogger(__name__)


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Converte sqlite3.Row para dict padrão Python. Retorna None se row for None."""
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    """Converte lista de sqlite3.Row para lista de dicts."""
    return [dict(r) for r in rows]


# ── Repositório de Usuários ────────────────────────────────────────────────────

class UsuarioRepository:
    """
    Acesso a dados da tabela `usuarios`.

    Por que não colocar hashing de senha aqui?
    --------------------------------------------
    Hashing é regra de negócio/segurança, não persistência.
    O AuthService faz o hash antes de chamar criar().
    O repositório persiste dados já preparados pelo serviço.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def criar(self, email: str, senha_hash: str, nome: str) -> int | None:
        """Insere novo usuário. Retorna ID ou None se email duplicado."""
        try:
            with self._db.get_write_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                    (email.lower().strip(), senha_hash, nome.strip()),
                )
                return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def buscar_por_email(self, email: str) -> dict | None:
        """Retorna usuário ativo pelo email (case-insensitive)."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT id, email, senha_hash, nome FROM usuarios "
                "WHERE email = ? AND ativo = 1",
                (email.lower().strip(),),
            ).fetchone()
        return _row_to_dict(row)

    def buscar_por_id(self, user_id: int) -> dict | None:
        """Retorna usuário ativo pelo ID."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT id, email, senha_hash, nome FROM usuarios "
                "WHERE id = ? AND ativo = 1",
                (int(user_id),),
            ).fetchone()
        return _row_to_dict(row)


# ── Repositório de Categorias ──────────────────────────────────────────────────

class CategoriaRepository:
    """
    Acesso a dados da tabela `categorias`.

    Categorias são por usuário — cada conta tem seu próprio conjunto.
    Nunca listar categorias de outros usuários.
    """

    CATEGORIAS_PADRAO: list[tuple[str, str, str, str]] = [
        ("Salário",      "receita",  "💼", "#22c55e"),
        ("Freelance",    "receita",  "💻", "#06b6d4"),
        ("Outros",       "receita",  "💰", "#a855f7"),
        ("Moradia",      "despesa",  "🏠", "#ef4444"),
        ("Alimentação",  "despesa",  "🍕", "#f97316"),
        ("Transporte",   "despesa",  "🚗", "#eab308"),
        ("Saúde",        "despesa",  "❤️", "#ec4899"),
        ("Lazer",        "despesa",  "🎮", "#8b5cf6"),
        ("Educação",     "despesa",  "📚", "#06b6d4"),
        ("Vestuário",    "despesa",  "👕", "#14b8a6"),
        ("Assinaturas",  "despesa",  "📱", "#6366f1"),
        ("Outros",       "despesa",  "💸", "#6b7280"),
    ]

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def criar_categorias_padrao(self, usuario_id: int) -> None:
        """Insere categorias padrão para novo usuário. Ignora duplicatas."""
        with self._db.get_write_conn() as conn:
            for nome, tipo, icone, cor in self.CATEGORIAS_PADRAO:
                try:
                    conn.execute(
                        "INSERT INTO categorias (nome, tipo, usuario_id, icone, cor) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (nome, tipo, usuario_id, icone, cor),
                    )
                except sqlite3.IntegrityError:
                    pass  # Categoria já existe — ignora silenciosamente

    def listar_por_usuario(self, usuario_id: int) -> list[dict]:
        """Retorna todas as categorias do usuário, ordenadas por tipo e nome."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, nome, tipo, icone, cor FROM categorias "
                "WHERE usuario_id = ? ORDER BY tipo, nome",
                (usuario_id,),
            ).fetchall()
        return _rows_to_list(rows)

    def buscar_padrao_por_tipo(self, usuario_id: int, tipo: str) -> dict | None:
        """Retorna primeira categoria do tipo especificado. Útil para lançamento rápido."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT id, nome, tipo FROM categorias "
                "WHERE usuario_id = ? AND tipo = ? ORDER BY nome LIMIT 1",
                (usuario_id, tipo),
            ).fetchone()
        return _row_to_dict(row)


# ── Repositório de Transações ──────────────────────────────────────────────────

class TransacaoRepository:
    """
    Acesso a dados da tabela `transacoes`.

    Princípio de segurança crítico:
    ---------------------------------
    Todo método de busca/edição/delete inclui `AND usuario_id = ?`.
    Isso garante que um usuário nunca acesse dados de outro,
    mesmo que descubra o UUID ou ID de uma transação alheia.
    Esse isolamento deve ser testado explicitamente.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def inserir(
        self,
        uuid: str,
        descricao: str,
        valor: float,
        tipo: str,
        categoria_id: int,
        data: str,
        usuario_id: int,
        recorrente_uuid: str | None = None,
        grupo_parcela: str | None = None,
    ) -> int:
        """Insere transação e retorna ID gerado."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO transacoes
                   (uuid, descricao, valor, tipo, categoria_id, data,
                    usuario_id, recorrente_uuid, grupo_parcela)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid, descricao, round(valor, 2), tipo, categoria_id,
                 data, usuario_id, recorrente_uuid, grupo_parcela),
            )
            return cur.lastrowid

    def buscar_por_uuid(self, uuid: str, usuario_id: int) -> dict | None:
        """Busca transação por UUID garantindo isolamento de usuário."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                """SELECT t.id, t.uuid, t.descricao, t.valor, t.tipo,
                          t.categoria_id, t.data, t.grupo_parcela,
                          c.nome AS categoria_nome
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   WHERE t.uuid = ? AND t.usuario_id = ? AND t.deletado = 0""",
                (uuid, usuario_id),
            ).fetchone()
        return _row_to_dict(row)

    def listar_por_periodo(
        self, data_inicio: str, data_fim: str, usuario_id: int
    ) -> list[dict]:
        """Lista transações ativas em um intervalo de datas."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT t.id, t.uuid, t.descricao, t.valor, t.tipo,
                          t.data, t.recorrente_uuid, t.grupo_parcela,
                          COALESCE(c.nome, 'Sem categoria') AS categoria_nome,
                          COALESCE(c.icone, '💰') AS categoria_icone,
                          COALESCE(t.categoria_id, 0) AS categoria_id
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   WHERE t.usuario_id = ?
                     AND t.data BETWEEN ? AND ?
                     AND t.deletado = 0
                   ORDER BY t.data DESC, t.criado_em DESC""",
                (usuario_id, data_inicio, data_fim),
            ).fetchall()
        return _rows_to_list(rows)

    def resumo_mes(
        self, ano: int, mes: int, usuario_id: int
    ) -> tuple[float, float, float]:
        """
        Retorna (total_receitas, total_despesas, saldo) do mês.

        Por que uma única query com GROUP BY?
        ----------------------------------------
        No código original, isso poderia ser feito com duas queries separadas.
        Uma query com GROUP BY é mais eficiente: uma passagem na tabela,
        não duas. Com índice em (usuario_id, data), isso é muito rápido.
        """
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT tipo, COALESCE(SUM(valor), 0) AS total
                   FROM transacoes
                   WHERE usuario_id = ?
                     AND strftime('%Y-%m', data) = ?
                     AND deletado = 0
                   GROUP BY tipo""",
                (usuario_id, f"{ano}-{mes:02d}"),
            ).fetchall()
        totais = {row["tipo"]: row["total"] for row in rows}
        receitas = totais.get("receita", 0.0)
        despesas = totais.get("despesa", 0.0)
        return receitas, despesas, receitas - despesas

    def gastos_por_categoria(
        self, ano: int, mes: int, usuario_id: int
    ) -> list[dict]:
        """Agrupa despesas por categoria para o gráfico de pizza."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT COALESCE(c.nome, 'Sem categoria') AS nome,
                          COALESCE(SUM(t.valor), 0) AS total,
                          COALESCE(c.cor, '#6b7280') AS cor
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   WHERE t.usuario_id = ?
                     AND strftime('%Y-%m', t.data) = ?
                     AND t.tipo = 'despesa'
                     AND t.deletado = 0
                   GROUP BY c.nome, c.cor
                   ORDER BY total DESC""",
                (usuario_id, f"{ano}-{mes:02d}"),
            ).fetchall()
        return _rows_to_list(rows)

    def evolucao_saldo_mes(
        self, ano: int, mes: int, usuario_id: int
    ) -> list[dict]:
        """Retorna saldo acumulado por dia do mês (para gráfico de barras)."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT CAST(strftime('%d', data) AS INTEGER) AS dia,
                          SUM(CASE WHEN tipo='receita' THEN valor ELSE -valor END) AS saldo_dia
                   FROM transacoes
                   WHERE usuario_id = ?
                     AND strftime('%Y-%m', data) = ?
                     AND deletado = 0
                   GROUP BY dia
                   ORDER BY dia""",
                (usuario_id, f"{ano}-{mes:02d}"),
            ).fetchall()
        return _rows_to_list(rows)

    def atualizar(self, id_transacao: int, usuario_id: int, **campos: Any) -> bool:
        """
        Atualiza campos específicos de uma transação.

        Por que **kwargs e mapa de campos permitidos?
        -----------------------------------------------
        Evita SQL injection via nome de coluna. O mapa `_CAMPOS_PERMITIDOS`
        define explicitamente quais colunas podem ser alteradas.
        Qualquer campo não mapeado é simplesmente ignorado.
        """
        _CAMPOS_PERMITIDOS = {
            "descricao": lambda v: str(v).strip(),
            "valor": lambda v: round(float(v), 2),
            "tipo": lambda v: str(v),
            "categoria_id": int,
            "data": lambda v: str(v),
        }

        sets, params = [], []
        for campo, transformar in _CAMPOS_PERMITIDOS.items():
            if campo in campos and campos[campo] is not None:
                sets.append(f"{campo} = ?")
                params.append(transformar(campos[campo]))

        if not sets:
            return False

        params.extend([id_transacao, usuario_id])
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                f"UPDATE transacoes SET {', '.join(sets)} "
                "WHERE id = ? AND usuario_id = ? AND deletado = 0",
                params,
            )
        return cur.rowcount > 0

    def deletar_logico(self, id_transacao: int, usuario_id: int) -> bool:
        """Soft-delete: marca deletado=1 sem remover o registro."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE transacoes SET deletado = 1 WHERE id = ? AND usuario_id = ?",
                (id_transacao, usuario_id),
            )
        return cur.rowcount > 0

    def restaurar(self, id_transacao: int, usuario_id: int) -> bool:
        """Reverte soft-delete."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE transacoes SET deletado = 0 WHERE id = ? AND usuario_id = ?",
                (id_transacao, usuario_id),
            )
        return cur.rowcount > 0

    def existe_recorrente_no_mes(
        self, recorrente_uuid: str, ano: int, mes: int
    ) -> bool:
        """Verifica se já existe lançamento de um recorrente no mês. Evita duplicatas."""
        with self._db.get_conn() as conn:
            count = conn.execute(
                """SELECT COUNT(*) FROM transacoes
                   WHERE recorrente_uuid = ?
                     AND strftime('%Y-%m', data) = ?
                     AND deletado = 0""",
                (recorrente_uuid, f"{ano}-{mes:02d}"),
            ).fetchone()[0]
        return count > 0
    def deletar_grupo(self, grupo_parcela: str, usuario_id: int) -> int:
        """Soft-delete de todas as parcelas de um parcelamento."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """UPDATE transacoes SET deletado = 1
                   WHERE grupo_parcela = ? AND usuario_id = ? AND deletado = 0""",
                (grupo_parcela, usuario_id),
            )
        return cur.rowcount


# ── Repositório de Recorrentes ─────────────────────────────────────────────────

class RecorrenteRepository:
    """Acesso a dados da tabela `recorrentes`."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def inserir(
        self,
        uuid: str,
        descricao: str,
        valor: float,
        tipo: str,
        categoria_id: int,
        dia_vencimento: int,
        usuario_id: int,
    ) -> int:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO recorrentes
                   (uuid, descricao, valor, tipo, categoria_id, dia_vencimento, usuario_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uuid, descricao.strip(), round(valor, 2), tipo,
                 categoria_id, dia_vencimento, usuario_id),
            )
            return cur.lastrowid

    def listar_ativos(self, usuario_id: int) -> list[dict]:
        """Lista recorrentes ativos com nome da categoria."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT r.id, r.uuid, r.descricao, r.valor, r.tipo,
                          r.dia_vencimento, r.ativo,
                          COALESCE(c.nome, 'Sem categoria') AS categoria_nome,
                          COALESCE(r.categoria_id, 0) AS categoria_id
                   FROM recorrentes r
                   LEFT JOIN categorias c ON r.categoria_id = c.id
                   WHERE r.usuario_id = ? AND r.ativo = 1
                   ORDER BY r.dia_vencimento""",
                (usuario_id,),
            ).fetchall()
        return _rows_to_list(rows)

    def listar_todos_ativos_raw(self, usuario_id: int) -> list[dict]:
        """Lista mínima para processamento interno (geração de lançamentos)."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT uuid, descricao, valor, tipo, categoria_id, dia_vencimento
                   FROM recorrentes WHERE usuario_id = ? AND ativo = 1""",
                (usuario_id,),
            ).fetchall()
        return _rows_to_list(rows)

    def buscar_por_uuid(self, uuid: str, usuario_id: int) -> dict | None:
        with self._db.get_conn() as conn:
            row = conn.execute(
                """SELECT id, uuid, descricao, valor, tipo,
                          categoria_id, dia_vencimento
                   FROM recorrentes
                   WHERE uuid = ? AND usuario_id = ? AND ativo = 1""",
                (uuid, usuario_id),
            ).fetchone()
        return _row_to_dict(row)

    def atualizar(self, uuid: str, usuario_id: int, **campos: Any) -> bool:
        _CAMPOS_PERMITIDOS = {
            "descricao": lambda v: str(v).strip(),
            "valor": lambda v: round(float(v), 2),
            "tipo": lambda v: str(v),
            "categoria_id": int,
            "dia_vencimento": int,
        }
        sets, params = [], []
        for campo, transformar in _CAMPOS_PERMITIDOS.items():
            if campo in campos and campos[campo] is not None:
                sets.append(f"{campo} = ?")
                params.append(transformar(campos[campo]))

        if not sets:
            return False

        params.extend([uuid, usuario_id])
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                f"UPDATE recorrentes SET {', '.join(sets)} "
                "WHERE uuid = ? AND usuario_id = ? AND ativo = 1",
                params,
            )
        return cur.rowcount > 0

    def desativar(self, uuid: str, usuario_id: int) -> bool:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE recorrentes SET ativo = 0 WHERE uuid = ? AND usuario_id = ?",
                (uuid, usuario_id),
            )
        return cur.rowcount > 0

# ── Repositório de Metas ───────────────────────────────────────────────────────

class MetaRepository:
    """Acesso a dados da tabela `metas`."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def inserir(
        self,
        uuid: str,
        titulo: str,
        valor_alvo: float,
        data_inicio: str,
        usuario_id: int,
        descricao: str = "",
        data_fim: str | None = None,
        categoria_id: int | None = None,
    ) -> int:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO metas
                   (uuid, titulo, descricao, valor_alvo, data_inicio,
                    data_fim, categoria_id, usuario_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid, titulo.strip(), descricao, round(valor_alvo, 2),
                 data_inicio, data_fim, categoria_id, usuario_id),
            )
            return cur.lastrowid

    def listar_ativas(self, usuario_id: int) -> list[dict]:
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT m.id, m.uuid, m.titulo, m.descricao,
                          m.valor_alvo, m.valor_atual, m.data_inicio, m.data_fim,
                          COALESCE(c.nome, '') AS categoria_nome
                   FROM metas m
                   LEFT JOIN categorias c ON m.categoria_id = c.id
                   WHERE m.usuario_id = ? AND m.ativa = 1
                   ORDER BY m.data_inicio""",
                (usuario_id,),
            ).fetchall()
        return _rows_to_list(rows)

    def atualizar_valor(self, uuid: str, usuario_id: int, valor_atual: float) -> bool:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE metas SET valor_atual = ? WHERE uuid = ? AND usuario_id = ?",
                (round(valor_atual, 2), uuid, usuario_id),
            )
        return cur.rowcount > 0