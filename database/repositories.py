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
        """
        Retorna usuário ativo pelo email (case-insensitive).
        Usado tanto no login quanto na recuperação de senha.
        """
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT id, email, senha_hash, nome, modo_contabil FROM usuarios "
                "WHERE email = ? AND ativo = 1",
                (email.lower().strip(),),
            ).fetchone()
        return _row_to_dict(row)

    def buscar_por_id(self, user_id: int) -> dict | None:
        """Retorna usuário ativo pelo ID."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT id, email, senha_hash, nome, modo_contabil, "
                "COALESCE(onboarding_completo, 0) as onboarding_completo FROM usuarios "
                "WHERE id = ? AND ativo = 1",
                (int(user_id),),
            ).fetchone()
        return _row_to_dict(row)

    def marcar_onboarding_completo(self, usuario_id: int) -> None:
        """Marca que o usuário completou ou pulou o onboarding."""
        with self._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET onboarding_completo = 1 WHERE id = ?",
                (usuario_id,)
            )


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
        conta_id: int | None = None,
    ) -> int:
        """Insere transação e retorna ID gerado."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO transacoes
                   (uuid, descricao, valor, tipo, categoria_id, data,
                    usuario_id, recorrente_uuid, grupo_parcela, conta_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid, descricao, round(valor, 2), tipo, categoria_id,
                 data, usuario_id, recorrente_uuid, grupo_parcela, conta_id),
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
                          COALESCE(t.categoria_id, 0) AS categoria_id,
                          t.conta_debito, t.conta_credito,
                          t.conta_id,
                          COALESCE(cb.nome, '') AS conta_nome,
                          COALESCE(cb.icone, '') AS conta_icone
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   LEFT JOIN contas_bancarias cb ON t.conta_id = cb.id AND cb.ativo = 1
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
                """SELECT COALESCE(c.id, 0) AS id,
                          COALESCE(c.nome, 'Sem categoria') AS nome,
                          COALESCE(c.icone, '💸') AS icone,
                          COALESCE(SUM(t.valor), 0) AS total,
                          COALESCE(c.cor, '#6b7280') AS cor
                   FROM transacoes t
                   LEFT JOIN categorias c ON t.categoria_id = c.id
                   WHERE t.usuario_id = ?
                     AND strftime('%Y-%m', t.data) = ?
                     AND t.tipo = 'despesa'
                     AND t.deletado = 0
                   GROUP BY c.id, c.nome, c.icone, c.cor
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
        # Campos permitidos para atualização — lista explícita evita SQL injection
        _CAMPOS_PERMITIDOS = {
            "descricao":   lambda v: str(v).strip(),
            "valor":       lambda v: round(float(v), 2),
            "tipo":        lambda v: str(v),
            "categoria_id": int,
            "data":        lambda v: str(v),
            "conta_id":    lambda v: int(v) if v else None,
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
        """
        Verifica se já foi gerado lançamento de um recorrente no mês.

        IMPORTANTE: NÃO filtra por deletado=0.
        Se o usuário deletar o lançamento gerado automaticamente,
        o sistema NÃO deve recriar na próxima vez que abrir o dashboard.
        A deleção é uma decisão consciente do usuário — respeitamos ela.
        """
        with self._db.get_conn() as conn:
            count = conn.execute(
                """SELECT COUNT(*) FROM transacoes
                   WHERE recorrente_uuid = ?
                     AND strftime('%Y-%m', data) = ?""",
                (recorrente_uuid, f"{ano}-{mes:02d}"),
            ).fetchone()[0]
        return count > 0
    def deletar_por_recorrente(self, recorrente_uuid: str, usuario_id: int) -> int:
        """
        Soft-delete de TODOS os lançamentos gerados por uma conta fixa.

        Chamado quando o usuário exclui uma conta fixa — remove também
        todos os lançamentos automáticos que ela gerou.

        Retorna quantos lançamentos foram deletados.
        """
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """UPDATE transacoes SET deletado = 1
                   WHERE recorrente_uuid = ? AND usuario_id = ? """,
                (recorrente_uuid, usuario_id),
            )
        return cur.rowcount

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

class LimiteCategoriaRepository:
    """Gerencia limites de gasto mensais por categoria."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def salvar(self, usuario_id: int, categoria_id: int, limite: float) -> None:
        """Insere ou atualiza o limite de uma categoria (upsert)."""
        with self._db.get_write_conn() as conn:
            conn.execute(
                """INSERT INTO limites_categoria (usuario_id, categoria_id, limite)
                   VALUES (?, ?, ?)
                   ON CONFLICT(usuario_id, categoria_id)
                   DO UPDATE SET limite = excluded.limite""",
                (usuario_id, categoria_id, round(limite, 2))
            )

    def remover(self, usuario_id: int, categoria_id: int) -> None:
        """Remove o limite de uma categoria."""
        with self._db.get_write_conn() as conn:
            conn.execute(
                "DELETE FROM limites_categoria WHERE usuario_id = ? AND categoria_id = ?",
                (usuario_id, categoria_id)
            )

    def listar(self, usuario_id: int) -> list[dict]:
        """Retorna todos os limites do usuário com nome e cor da categoria."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT lc.categoria_id, lc.limite,
                          c.nome, c.icone, c.cor
                   FROM limites_categoria lc
                   JOIN categorias c ON c.id = lc.categoria_id
                   WHERE lc.usuario_id = ?
                   ORDER BY c.nome""",
                (usuario_id,)
            ).fetchall()
        return _rows_to_list(rows)

    def buscar(self, usuario_id: int, categoria_id: int) -> float | None:
        """Retorna o limite de uma categoria específica ou None."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT limite FROM limites_categoria WHERE usuario_id = ? AND categoria_id = ?",
                (usuario_id, categoria_id)
            ).fetchone()
        return row["limite"] if row else None


class BuscaRepository:
    """
    Repositório dedicado para busca full-text nas transações.

    Separado do TransacaoRepository para manter SRP —
    busca tem lógica diferente de CRUD simples.
    """

    def __init__(self, db) -> None:
        self._db = db

    def buscar(
        self,
        usuario_id: int,
        termo: str = "",
        conta_id: int | None = None,
        tipo: str | None = None,
        data_inicio: str | None = None,
        data_fim: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Busca transações com filtros combinados.

        Args:
            termo: texto livre para buscar na descrição
            conta_id: filtra por conta bancária específica
            tipo: 'receita' ou 'despesa'
            data_inicio / data_fim: intervalo de datas
        """
        conditions = ["t.usuario_id = ?", "t.deletado = 0"]
        params: list = [usuario_id]

        if termo:
            conditions.append("t.descricao LIKE ?")
            params.append(f"%{termo}%")

        if conta_id:
            conditions.append("t.conta_id = ?")
            params.append(conta_id)

        if tipo in ("receita", "despesa"):
            conditions.append("t.tipo = ?")
            params.append(tipo)

        if data_inicio:
            conditions.append("t.data >= ?")
            params.append(data_inicio)

        if data_fim:
            conditions.append("t.data <= ?")
            params.append(data_fim)

        where = " AND ".join(conditions)
        params.append(limit)

        with self._db.get_conn() as conn:
            rows = conn.execute(f"""
                SELECT t.id, t.uuid, t.descricao, t.valor, t.tipo,
                       t.data, t.recorrente_uuid, t.grupo_parcela,
                       COALESCE(c.nome, 'Sem categoria') AS categoria_nome,
                       COALESCE(c.icone, '💰') AS categoria_icone,
                       COALESCE(t.categoria_id, 0) AS categoria_id,
                       t.conta_debito, t.conta_credito, t.conta_id,
                       COALESCE(cb.nome, '') AS conta_nome,
                       COALESCE(cb.icone, '') AS conta_icone
                FROM transacoes t
                LEFT JOIN categorias c ON t.categoria_id = c.id
                LEFT JOIN contas_bancarias cb ON t.conta_id = cb.id AND cb.ativo = 1
                WHERE {where}
                ORDER BY t.data DESC, t.criado_em DESC
                LIMIT ?
            """, params).fetchall()

        return _rows_to_list(rows)


class SaldoContaRepository:
    """
    Calcula saldo atual por conta bancária.

    Saldo = soma de receitas - soma de despesas lançadas nessa conta.
    """

    def __init__(self, db) -> None:
        self._db = db

    def saldos_por_conta(self, usuario_id: int) -> list[dict]:
        """Retorna lista de contas com saldo calculado."""
        with self._db.get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    cb.id,
                    cb.nome,
                    cb.tipo,
                    cb.icone,
                    COALESCE(SUM(
                        CASE WHEN t.tipo = 'receita' THEN t.valor
                             WHEN t.tipo = 'despesa' THEN -t.valor
                             ELSE 0 END
                    ), 0) AS saldo
                FROM contas_bancarias cb
                LEFT JOIN transacoes t
                    ON t.conta_id = cb.id AND t.deletado = 0 AND t.usuario_id = ?
                WHERE cb.usuario_id = ? AND cb.ativo = 1
                GROUP BY cb.id, cb.nome, cb.tipo, cb.icone
                ORDER BY cb.nome
            """, (usuario_id, usuario_id)).fetchall()

        return _rows_to_list(rows)




class ContaBancariaRepository:
    """Repositório de contas bancárias e cartões do usuário."""

    ICONES = {
        "conta":   "🏦",
        "cartao":  "💳",
        "carteira": "👛",
        "poupanca": "🐷",
        "investimento": "📈",
    }

    SUGESTOES_PADRAO = [
        ("Conta Corrente", "conta"),
        ("Poupança",       "poupanca"),
        ("Carteira",       "carteira"),
    ]

    def __init__(self, db) -> None:
        self._db = db

    def listar(self, usuario_id: int) -> list:
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT id, nome, tipo, icone FROM contas_bancarias
                   WHERE usuario_id = ? AND ativo = 1
                   ORDER BY nome""",
                (usuario_id,)
            ).fetchall()
        return _rows_to_list(rows)

    def adicionar(self, nome: str, tipo: str, usuario_id: int) -> tuple:
        """Adiciona conta. Retorna (id, erro). Impede duplicidade de nome."""
        nome = nome.strip()
        if not nome:
            return None, "Nome é obrigatório"

        icone = self.ICONES.get(tipo, "🏦")

        try:
            with self._db.get_write_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO contas_bancarias (usuario_id, nome, tipo, icone)
                       VALUES (?, ?, ?, ?)""",
                    (usuario_id, nome, tipo, icone)
                )
            return cur.lastrowid, None
        except Exception as e:
            if "UNIQUE" in str(e):
                return None, f'Você já tem uma conta chamada "{nome}"'
            return None, "Erro ao salvar conta"

    def deletar(self, conta_id: int, usuario_id: int) -> bool:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE contas_bancarias SET ativo=0 WHERE id=? AND usuario_id=?",
                (conta_id, usuario_id)
            )
        return cur.rowcount > 0

    def criar_sugestoes_padrao(self, usuario_id: int) -> None:
        """Cria contas padrão para novos usuários."""
        for nome, tipo in self.SUGESTOES_PADRAO:
            try:
                self.adicionar(nome, tipo, usuario_id)
            except Exception:
                pass