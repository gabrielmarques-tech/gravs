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
        """
        Insere novo usuário. Retorna ID ou None se email duplicado.

        Trata o caso de conta excluída com mesmo email:
        ao fazer soft-delete, o email é anonimizado (deleted_<id>@excluido),
        liberando o UNIQUE para novo cadastro com o mesmo endereço.
        """
        try:
            with self._db.get_write_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                    (email.lower().strip(), senha_hash, nome.strip()),
                )
                return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def anonimizar_email(self, usuario_id: int) -> None:
        """
        Substitui o email por um valor anonimizado ao excluir conta.

        Isso libera o UNIQUE constraint, permitindo que o mesmo email
        seja usado para criar uma nova conta no futuro — comportamento
        esperado pelo usuário e exigido pela LGPD (direito ao esquecimento).

        Formato: deleted_<id>_<timestamp>@excluido.gravs
        """
        import time
        email_anonimo = f"deleted_{usuario_id}_{int(time.time())}@excluido.gravs"
        with self._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET email=?, ativo=0 WHERE id=?",
                (email_anonimo, usuario_id)
            )

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

    def get_modo_contabil(self, usuario_id: int) -> bool:
        """Retorna se o modo contábil está ativo para o usuário."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT modo_contabil FROM usuarios WHERE id=?",
                (usuario_id,),
            ).fetchone()
        return bool(row and row["modo_contabil"])

    def set_modo_contabil(self, usuario_id: int, ativo: bool) -> None:
        """Define o modo contábil do usuário."""
        with self._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET modo_contabil = ? WHERE id = ?",
                (1 if ativo else 0, usuario_id),
            )

    def atualizar_nome(self, usuario_id: int, novo_nome: str) -> None:
        """Atualiza o nome do usuário."""
        with self._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET nome = ? WHERE id = ?",
                (novo_nome, usuario_id),
            )

    def atualizar_senha_hash(self, usuario_id: int, novo_hash: str) -> None:
        """Atualiza o hash da senha do usuário."""
        with self._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                (novo_hash, usuario_id),
            )

    def marcar_excluido(self, usuario_id: int) -> None:
        """Marca o momento da exclusão da conta."""
        from datetime import datetime
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._db.get_write_conn() as conn:
            conn.execute(
                "UPDATE usuarios SET excluido_em=? WHERE id=?",
                (agora, usuario_id),
            )


# ── Repositório de Categorias ──────────────────────────────────────────────────

class CategoriaRepository:
    """
    Acesso a dados da tabela `categorias`.

    Categorias são por usuário — cada conta tem seu próprio conjunto.
    Nunca listar categorias de outros usuários.
    """

    CATEGORIAS_PADRAO: list[tuple[str, str, str, str]] = [
        ("Salário",           "receita",  "💼", "#22c55e"),
        ("Freelance",         "receita",  "💻", "#06b6d4"),
        ("Receita PIX",       "receita",  "💸", "#10b981"),
        ("Outros",            "receita",  "💰", "#a855f7"),
        ("Moradia",           "despesa",  "🏠", "#ef4444"),
        ("Alimentação",       "despesa",  "🍕", "#f97316"),
        ("Transporte",        "despesa",  "🚗", "#eab308"),
        ("Saúde",             "despesa",  "❤️", "#ec4899"),
        ("Lazer",             "despesa",  "🎮", "#8b5cf6"),
        ("Educação",          "despesa",  "📚", "#06b6d4"),
        ("Vestuário",         "despesa",  "👕", "#14b8a6"),
        ("Assinaturas",       "despesa",  "📱", "#6366f1"),
        ("Transferências PIX","despesa",  "🔄", "#6b7280"),
        ("Outros",            "despesa",  "💸", "#6b7280"),
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

    def criar_categoria(self, nome: str, tipo: str, usuario_id: int, icone: str = "💸", cor: str = "#7c3aed") -> bool:
        """Cria uma categoria personalizada. Retorna True se criou, False se duplicada."""
        try:
            with self._db.get_write_conn() as conn:
                conn.execute(
                    "INSERT INTO categorias (nome, tipo, usuario_id, icone, cor) VALUES (?, ?, ?, ?, ?)",
                    (nome, tipo, usuario_id, icone, cor)
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def atualizar(self, cat_id: int, usuario_id: int, nome: str, icone: str, cor: str) -> bool:
        """Atualiza nome, ícone e cor de uma categoria."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """UPDATE categorias SET nome=?, icone=?, cor=?
                   WHERE id=? AND usuario_id=?""",
                (nome, icone, cor, cat_id, usuario_id),
            )
        return cur.rowcount > 0

    def deletar(self, cat_id: int, usuario_id: int) -> bool:
        """Remove uma categoria fisicamente."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "DELETE FROM categorias WHERE id=? AND usuario_id=?",
                (cat_id, usuario_id),
            )
            return cur.rowcount > 0

    def contar_transacoes_vinculadas(self, cat_id: int, usuario_id: int) -> int:
        """Retorna quantas transações ativas estão vinculadas a esta categoria."""
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM transacoes WHERE categoria_id=? AND usuario_id=? AND deletado=0",
                (cat_id, usuario_id),
            ).fetchone()
        return row[0] if row else 0

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
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """
        Insere transação e retorna ID gerado.

        Opcionalmente aceita uma conexão externa (conn) para participar
        de transações gerenciadas por outra camada (ex: ContabilService).
        Quando conn é fornecido, NÃO fecha a conexão nem faz commit —
        quem chamou é responsável pelo gerenciamento da transação.
        """
        if conn is not None:
            cur = conn.execute(
                """INSERT INTO transacoes
                   (uuid, descricao, valor, tipo, categoria_id, data,
                    usuario_id, recorrente_uuid, grupo_parcela, conta_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid, descricao, round(valor, 2), tipo, categoria_id,
                 data, usuario_id, recorrente_uuid, grupo_parcela, conta_id),
            )
            return cur.lastrowid
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

        Usa BETWEEN em vez de strftime() para aproveitar o índice
        composto (usuario_id, data DESC), reduzindo scan de tabela.
        """
        import calendar as cal
        ultimo_dia = cal.monthrange(ano, mes)[1]
        d_ini = f"{ano:04d}-{mes:02d}-01"
        d_fim = f"{ano:04d}-{mes:02d}-{ultimo_dia:02d}"
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT tipo, COALESCE(SUM(valor), 0) AS total
                   FROM transacoes
                   WHERE usuario_id = ?
                     AND data BETWEEN ? AND ?
                     AND deletado = 0
                   GROUP BY tipo""",
                (usuario_id, d_ini, d_fim),
            ).fetchall()
        totais = {row["tipo"]: row["total"] for row in rows}
        receitas = totais.get("receita", 0.0)
        despesas = totais.get("despesa", 0.0)
        return receitas, despesas, receitas - despesas

    def gastos_por_categoria(
        self, ano: int, mes: int, usuario_id: int
    ) -> list[dict]:
        """
        Agrupa despesas por categoria para o gráfico de pizza.

        Usa BETWEEN em vez de strftime() para aproveitar o índice
        idx_trans_user_data, reduzindo scan de tabela para lookup por índice.
        """
        import calendar as cal
        ultimo_dia = cal.monthrange(ano, mes)[1]
        d_ini = f"{ano:04d}-{mes:02d}-01"
        d_fim = f"{ano:04d}-{mes:02d}-{ultimo_dia:02d}"
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
                     AND t.data BETWEEN ? AND ?
                     AND t.tipo = 'despesa'
                     AND t.deletado = 0
                   GROUP BY c.id, c.nome, c.icone, c.cor
                   ORDER BY total DESC""",
                (usuario_id, d_ini, d_fim),
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
        """
        Retorna saldo por conta considerando transações E transferências.

        Transferências redistribuem saldo entre contas sem afetar
        receitas/despesas totais. Ex: pagar fatura do cartão debita
        a conta corrente e credita o cartão, sem criar nova despesa.
        """
        with self._db.get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    cb.id, cb.nome, cb.tipo, cb.icone,
                    COALESCE(
                        (SELECT SUM(CASE WHEN t.tipo='receita' THEN t.valor ELSE -t.valor END)
                         FROM transacoes t
                         WHERE t.conta_id = cb.id AND t.deletado = 0 AND t.usuario_id = ?)
                    , 0)
                    +
                    COALESCE(
                        (SELECT SUM(tr.valor) FROM transferencias tr
                         WHERE tr.conta_destino_id = cb.id AND tr.deletado = 0 AND tr.usuario_id = ?)
                    , 0)
                    -
                    COALESCE(
                        (SELECT SUM(tr.valor) FROM transferencias tr
                         WHERE tr.conta_origem_id = cb.id AND tr.deletado = 0 AND tr.usuario_id = ?)
                    , 0) AS saldo
                FROM contas_bancarias cb
                WHERE cb.usuario_id = ? AND cb.ativo = 1
                ORDER BY cb.nome
            """, (usuario_id, usuario_id, usuario_id, usuario_id)).fetchall()
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

class TransferenciaRepository:
    """
    Repositório de transferências entre contas do usuário.

    Uma transferência é uma movimentação interna — debita a conta de origem
    e credita a conta de destino pelo mesmo valor. NÃO afeta receitas/despesas.

    Casos de uso:
    - Pagar fatura do cartão (conta corrente → cartão de crédito)
    - Transferir para poupança (conta corrente → poupança)
    - PIX entre contas próprias

    O saldo calculado por SaldoContaRepository já considera transferências
    ao somar créditos e debita        # Delega cálculo para o repositório (uma única query SQL com SUM + CASE WHEN)
        totais = self._lancamentos.calcular_saldo(
            conta_id=conta_id,
            usuario_id=usuario_id,
            data_ate=data_ate,
        )r débitos por conta.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def inserir(
        self,
        uuid: str,
        descricao: str,
        valor: float,
        conta_origem_id: int,
        conta_destino_id: int,
        data: str,
        usuario_id: int,
    ) -> int:
        """Registra uma transferência. Retorna o ID gerado."""
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO transferencias
                   (uuid, descricao, valor, conta_origem_id, conta_destino_id,
                    data, usuario_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uuid, descricao.strip(), round(valor, 2),
                 conta_origem_id, conta_destino_id, data, usuario_id)
            )
            return cur.lastrowid

    def listar_por_periodo(
        self, data_inicio: str, data_fim: str, usuario_id: int
    ) -> list[dict]:
        """Lista transferências no período com nomes das contas."""
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT t.id, t.uuid, t.descricao, t.valor, t.data,
                          t.conta_origem_id, t.conta_destino_id,
                          co.nome AS conta_origem_nome, co.icone AS conta_origem_icone,
                          cd.nome AS conta_destino_nome, cd.icone AS conta_destino_icone
                   FROM transferencias t
                   JOIN contas_bancarias co ON co.id = t.conta_origem_id
                   JOIN contas_bancarias cd ON cd.id = t.conta_destino_id
                   WHERE t.usuario_id = ?
                     AND t.data BETWEEN ? AND ?
                     AND t.deletado = 0
                   ORDER BY t.data DESC, t.criado_em DESC""",
                (usuario_id, data_inicio, data_fim)
            ).fetchall()
        return _rows_to_list(rows)

    def buscar_por_uuid(self, uuid: str, usuario_id: int) -> dict | None:
        with self._db.get_conn() as conn:
            row = conn.execute(
                """SELECT t.*, co.nome AS conta_origem_nome,
                          cd.nome AS conta_destino_nome
                   FROM transferencias t
                   JOIN contas_bancarias co ON co.id = t.conta_origem_id
                   JOIN contas_bancarias cd ON cd.id = t.conta_destino_id
                   WHERE t.uuid = ? AND t.usuario_id = ? AND t.deletado = 0""",
                (uuid, usuario_id)
            ).fetchone()
        return _row_to_dict(row)

    def deletar_logico(self, uuid: str, usuario_id: int) -> bool:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE transferencias SET deletado=1 WHERE uuid=? AND usuario_id=?",
                (uuid, usuario_id)
            )
        return cur.rowcount > 0


class MetaRepository:
    """
    Repositório de metas financeiras do usuário.

    Uma meta tem um valor alvo e um prazo. O progresso pode ser
    atualizado manualmente ou calculado a partir de uma categoria
    de transações no período.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def listar(self, usuario_id: int) -> list[dict]:
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT m.*, c.nome AS categoria_nome, c.icone AS categoria_icone
                   FROM metas m
                   LEFT JOIN categorias c ON c.id = m.categoria_id
                   WHERE m.usuario_id = ? AND m.ativa = 1
                   ORDER BY m.data_fim ASC NULLS LAST, m.criado_em DESC""",
                (usuario_id,)
            ).fetchall()
        return _rows_to_list(rows)

    def buscar_por_uuid(self, uuid: str, usuario_id: int) -> dict | None:
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM metas WHERE uuid=? AND usuario_id=? AND ativa=1",
                (uuid, usuario_id)
            ).fetchone()
        return _row_to_dict(row)

    def criar(
        self,
        uuid: str,
        titulo: str,
        valor_alvo: float,
        data_fim: str | None,
        usuario_id: int,
        descricao: str = "",
        categoria_id: int | None = None,
        data_inicio: str | None = None,
    ) -> int:
        from datetime import date
        inicio = data_inicio or date.today().strftime("%Y-%m-%d")
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO metas
                   (uuid, titulo, descricao, valor_alvo, valor_atual,
                    data_inicio, data_fim, categoria_id, usuario_id)
                   VALUES (?,?,?,?,0,?,?,?,?)""",
                (uuid, titulo.strip(), descricao.strip(),
                 round(valor_alvo, 2), inicio, data_fim, categoria_id, usuario_id)
            )
            return cur.lastrowid

    def atualizar_progresso(self, uuid: str, valor_atual: float, usuario_id: int) -> bool:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE metas SET valor_atual=? WHERE uuid=? AND usuario_id=?",
                (round(valor_atual, 2), uuid, usuario_id)
            )
        return cur.rowcount > 0

    def deletar(self, uuid: str, usuario_id: int) -> bool:
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "UPDATE metas SET ativa=0 WHERE uuid=? AND usuario_id=?",
                (uuid, usuario_id)
            )
        return cur.rowcount > 0


# ── Plano de Contas Contábil ───────────────────────────────────────────────────

from dataclasses import dataclass
from typing import Optional


@dataclass
class PlanoConta:
    """
    Entidade do Plano de Contas Contábil.

    Representa uma conta na estrutura hierárquica de partidas dobradas.
    Mutável — suporta edição de nome, ativo, aceita_lancamentos e conta_pai_id.
    Código contábil é imutável por regra de negócio (não existe update de código).

    Mapeamento 1:1 com a tabela `plano_contas`.
    """
    id: int
    usuario_id: int
    codigo: str
    nome: str
    tipo: str           # ativo | passivo | patrimonio_liquido | receita | despesa | redutora
    natureza: str       # devedora | credora
    nivel: int          # 1 a 5
    aceita_lancamentos: bool
    ativo: bool
    conta_pai_id: Optional[int] = None
    criado_em: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'PlanoConta':
        """Constrói PlanoConta a partir de um sqlite3.Row."""
        return cls(
            id=row['id'],
            usuario_id=row['usuario_id'],
            codigo=row['codigo'],
            nome=row['nome'],
            tipo=row['tipo'],
            natureza=row['natureza'],
            nivel=row['nivel'],
            aceita_lancamentos=bool(row['aceita_lancamentos']),
            ativo=bool(row['ativo']),
            conta_pai_id=row['conta_pai_id'],
            criado_em=row['criado_em'],
        )


class PlanoContasRepository:
    """
    Acesso a dados da tabela `plano_contas`.

    Responsabilidades:
    - CRUD básico de contas contábeis
    - Validação de unicidade do código por usuário (via UNIQUE do banco)
    - Isolamento por usuário em todas as queries
    - Retorno tipado como PlanoConta (nunca dict)

    Hierarquia:
    - Nível 1: Grupos (Ativo, Passivo, PL, Receitas, Despesas)
    - Nível 2: Subgrupos
    - Nível 3-5: Contas Analíticas

    Regras aplicadas no banco (triggers/constraints):
    - UNIQUE(usuario_id, codigo): código único por usuário
    - CHECK(nivel BETWEEN 1 AND 5): profundidade limitada
    - Trigger trg_plano_contas_no_self_ref: impede auto-referência no conta_pai_id
    """

    _CAMPOS_PERMITIDOS: dict[str, callable] = {
        "nome": lambda v: str(v).strip(),
        "aceita_lancamentos": bool,
        "ativo": bool,
        "conta_pai_id": lambda v: int(v) if v is not None else None,
    }

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def criar(
        self,
        usuario_id: int,
        codigo: str,
        nome: str,
        tipo: str,
        natureza: str,
        nivel: int,
        aceita_lancamentos: bool = True,
        conta_pai_id: int | None = None,
    ) -> PlanoConta:
        """
        Cria uma nova conta no plano de contas.

        Args:
            usuario_id: ID do usuário proprietário
            codigo: Código contábil (ex: '1.01.001'). Único por usuário.
            nome: Nome da conta (ex: 'Caixa')
            tipo: ativo | passivo | patrimonio_liquido | receita | despesa | redutora
            natureza: devedora | credora
            nivel: Profundidade hierárquica (1 a 5)
            aceita_lancamentos: Se recebe lançamentos contábeis diretamente
            conta_pai_id: ID da conta pai (None se for raiz)

        Returns:
            PlanoConta recém-criada

        Raises:
            sqlite3.IntegrityError: Se código já existe para o usuário ou
                                    conta_pai_id não existe
        """
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO plano_contas
                   (usuario_id, codigo, nome, tipo, natureza, nivel,
                    aceita_lancamentos, conta_pai_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (usuario_id, codigo.strip(), nome.strip(), tipo,
                 natureza, nivel, int(aceita_lancamentos), conta_pai_id),
            )
            # Re-lê para obter criado_em e id gerado
            row = conn.execute(
                "SELECT * FROM plano_contas WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()

        return PlanoConta.from_row(row)

    def buscar_por_id(self, conta_id: int, usuario_id: int) -> PlanoConta | None:
        """
        Busca conta pelo ID, garantindo isolamento de usuário.

        Args:
            conta_id: ID da conta
            usuario_id: ID do usuário (filtro de segurança)

        Returns:
            PlanoConta ou None se não encontrada
        """
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM plano_contas "
                "WHERE id = ? AND usuario_id = ?",
                (conta_id, usuario_id),
            ).fetchone()
        return PlanoConta.from_row(row) if row else None

    def buscar_por_codigo(self, codigo: str, usuario_id: int) -> PlanoConta | None:
        """
        Busca conta pelo código contábil.

        Args:
            codigo: Código contábil (ex: '1.01.001')
            usuario_id: ID do usuário

        Returns:
            PlanoConta ou None se não encontrada
        """
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM plano_contas "
                "WHERE codigo = ? AND usuario_id = ?",
                (codigo.strip(), usuario_id),
            ).fetchone()
        return PlanoConta.from_row(row) if row else None

    def listar_por_usuario(
        self,
        usuario_id: int,
        apenas_ativas: bool = True,
    ) -> list[PlanoConta]:
        """
        Lista contas do usuário, ordenadas por nível e código.

        Args:
            usuario_id: ID do usuário
            apenas_ativas: Se True, filtra apenas contas com ativo=1

        Returns:
            Lista de PlanoConta
        """
        with self._db.get_conn() as conn:
            if apenas_ativas:
                rows = conn.execute(
                    "SELECT * FROM plano_contas "
                    "WHERE usuario_id = ? AND ativo = 1 "
                    "ORDER BY nivel, codigo",
                    (usuario_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM plano_contas "
                    "WHERE usuario_id = ? "
                    "ORDER BY nivel, codigo",
                    (usuario_id,),
                ).fetchall()
        return [PlanoConta.from_row(r) for r in rows]


class ArvorePlanoContas:
    """
    Helper de navegação hierárquica para o Plano de Contas.

    Responsabilidades:
    - Montar caminhos completos (ex: "1 - Ativo > 1.1 - Disponível > 1.1.1 - Caixa")
    - Construir estrutura de árvore a partir de lista plana

    Princípios:
    - NÃO acessa banco de dados
    - Recebe list[PlanoConta] já carregada
    - Constrói dict[int, PlanoConta] em memória para lookups O(1)
    - Zero queries durante iteração

    Uso típico:
        contas = repo.listar_por_usuario(usuario_id)
        arvore = ArvorePlanoContas.arvore_completa(contas)
    """

    @staticmethod
    def caminho_completo(
        conta: PlanoConta,
        mapa_contas: dict[int, PlanoConta],
    ) -> str:
        """
        Monta o caminho hierárquico completo de uma conta.

        Sobe na árvore via conta_pai_id até a raiz, usando
        o hash map para lookup O(1) em cada nível.

        Args:
            conta: Conta alvo
            mapa_contas: Dict {id: PlanoConta} com TODAS as contas
                         do mesmo usuário (deve estar completo)

        Returns:
            String no formato "1 - Ativo > 1.1 - Disponível > 1.1.1 - Caixa"
        """
        segmentos: list[str] = []
        atual: PlanoConta | None = conta
        while atual is not None:
            segmentos.append(f"{atual.codigo} - {atual.nome}")
            if atual.conta_pai_id is None:
                break
            atual = mapa_contas.get(atual.conta_pai_id)
        return " > ".join(reversed(segmentos))

    @staticmethod
    def arvore_completa(
        contas: list[PlanoConta],
    ) -> list[dict]:
        """
        Constrói lista de dicionários com caminho completo
        para cada conta, pronta para consumo pelo frontend.

        Args:
            contas: Lista plana de PlanoConta (retorno de listar_por_usuario)

        Returns:
            Lista de dicts no formato:
            [
                {
                    "id": 1,
                    "codigo": "1",
                    "nome": "Ativo",
                    "caminho": "1 - Ativo",
                    "nivel": 1,
                    "aceita_lancamentos": True,
                    "tipo": "ativo",
                    "natureza": "devedora",
                },
                ...
            ]
        """
        if not contas:
            return []

        mapa = {c.id: c for c in contas}
        return [
            {
                "id": c.id,
                "codigo": c.codigo,
                "nome": c.nome,
                "caminho": ArvorePlanoContas.caminho_completo(c, mapa),
                "nivel": c.nivel,
                "aceita_lancamentos": c.aceita_lancamentos,
                "tipo": c.tipo,
                "natureza": c.natureza,
            }
            for c in contas
        ]


# ── Lançamentos Contábeis (Partida Dobrada) ────────────────────────────────────


@dataclass
class LancamentoContabil:
    """
    Lançamento em Partida Dobrada.

    Representa um lançamento contábil que debita uma conta e credita
    outra pelo mesmo valor. Mapeamento 1:1 com a tabela `lancamentos_contabeis`.

    O repository NÃO valida regras de negócio como:
    - Partida dobrada (débito = crédito)
    - Natureza das contas (devedora/credora)
    - Se a conta aceita lançamentos

    Essas validações são responsabilidade do service.
    O banco já aplica CHECK(debito_id != credito_id) e as FKs.
    """
    id: int
    uuid: str
    usuario_id: int
    data: str
    historico: str
    valor: float
    debito_id: int
    credito_id: int
    transacao_id: Optional[int] = None
    criado_em: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'LancamentoContabil':
        """Constrói LancamentoContabil a partir de um sqlite3.Row."""
        return cls(
            id=row['id'],
            uuid=row['uuid'],
            usuario_id=row['usuario_id'],
            data=row['data'],
            historico=row['historico'],
            valor=row['valor'],
            debito_id=row['debito_id'],
            credito_id=row['credito_id'],
            transacao_id=row['transacao_id'],
            criado_em=row['criado_em'],
        )


class LancamentoContabilRepository:
    """
    Acesso a dados da tabela `lancamentos_contabeis`.

    Responsabilidades:
    - CRUD de lançamentos contábeis
    - Isolamento por usuário em todas as queries
    - Retorno tipado como LancamentoContabil (nunca dict)

    NÃO faz validações contábeis (service faz).
    O banco já possui:
    - CHECK(valor > 0)
    - CHECK(debito_id != credito_id)
    - FKs para plano_contas e transacoes
    - UNIQUE(uuid)
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def criar(
        self,
        uuid: str,
        usuario_id: int,
        data: str,
        historico: str,
        valor: float,
        debito_id: int,
        credito_id: int,
        transacao_id: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> LancamentoContabil:
        """
        Insere um lançamento contábil.

        Args:
            uuid: Identificador único do lançamento
            usuario_id: ID do usuário
            data: Data do lançamento (formato YYYY-MM-DD)
            historico: Descrição do lançamento
            valor: Valor positivo (CHECK do banco garante > 0)
            debito_id: ID da conta debitada (FK para plano_contas)
            credito_id: ID da conta creditada (FK para plano_contas)
            transacao_id: ID da transação associada (opcional)
            conn: Conexão externa para participar de transações gerenciadas
                  por outra camada. Quando fornecido, NÃO abre/fecha conexão
                  própria nem faz commit.

        Returns:
            LancamentoContabil recém-criado

        Raises:
            sqlite3.IntegrityError: Se uuid duplicado, FK inválida,
                                    ou CHECK(valor > 0) violado
        """
        if conn is not None:
            cur = conn.execute(
                """INSERT INTO lancamentos_contabeis
                   (uuid, usuario_id, data, historico, valor,
                    debito_id, credito_id, transacao_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid, usuario_id, data, historico.strip(),
                 round(valor, 2), debito_id, credito_id, transacao_id),
            )
            row = conn.execute(
                "SELECT * FROM lancamentos_contabeis WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            return LancamentoContabil.from_row(row)

        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                """INSERT INTO lancamentos_contabeis
                   (uuid, usuario_id, data, historico, valor,
                    debito_id, credito_id, transacao_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid, usuario_id, data, historico.strip(),
                 round(valor, 2), debito_id, credito_id, transacao_id),
            )
            row = conn.execute(
                "SELECT * FROM lancamentos_contabeis WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        return LancamentoContabil.from_row(row)

    def buscar_por_id(self, lancamento_id: int, usuario_id: int) -> LancamentoContabil | None:
        """
        Busca lançamento pelo ID com isolamento de usuário.

        Args:
            lancamento_id: ID do lançamento
            usuario_id: ID do usuário (filtro de segurança)

        Returns:
            LancamentoContabil ou None se não encontrado
        """
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM lancamentos_contabeis "
                "WHERE id = ? AND usuario_id = ?",
                (lancamento_id, usuario_id),
            ).fetchone()
        return LancamentoContabil.from_row(row) if row else None

    def buscar_por_uuid(self, uuid: str, usuario_id: int) -> LancamentoContabil | None:
        """
        Busca lançamento pelo UUID com isolamento de usuário.

        Args:
            uuid: UUID do lançamento
            usuario_id: ID do usuário (filtro de segurança)

        Returns:
            LancamentoContabil ou None se não encontrado
        """
        with self._db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM lancamentos_contabeis "
                "WHERE uuid = ? AND usuario_id = ?",
                (uuid, usuario_id),
            ).fetchone()
        return LancamentoContabil.from_row(row) if row else None

    def listar_por_usuario(
        self,
        usuario_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LancamentoContabil]:
        """
        Lista lançamentos do usuário, do mais recente para o mais antigo.

        Args:
            usuario_id: ID do usuário
            limit: Número máximo de registros
            offset: Deslocamento para paginação

        Returns:
            Lista de LancamentoContabil
        """
        with self._db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM lancamentos_contabeis "
                "WHERE usuario_id = ? "
                "ORDER BY data DESC, id DESC "
                "LIMIT ? OFFSET ?",
                (usuario_id, limit, offset),
            ).fetchall()
        return [LancamentoContabil.from_row(r) for r in rows]

    def listar_por_conta(
        self,
        conta_id: int,
        usuario_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LancamentoContabil]:
        """
        Lista lançamentos que envolvem uma conta específica
        (como débito OU crédito).

        Args:
            conta_id: ID da conta contábil
            usuario_id: ID do usuário (filtro de segurança)
            limit: Número máximo de registros
            offset: Deslocamento para paginação

        Returns:
            Lista de LancamentoContabil
        """
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM lancamentos_contabeis
                   WHERE usuario_id = ?
                     AND (debito_id = ? OR credito_id = ?)
                   ORDER BY data DESC, id DESC
                   LIMIT ? OFFSET ?""",
                (usuario_id, conta_id, conta_id, limit, offset),
            ).fetchall()
        return [LancamentoContabil.from_row(r) for r in rows]

    def listar_por_periodo(
        self,
        usuario_id: int,
        data_inicio: str,
        data_fim: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[LancamentoContabil]:
        """
        Lista lançamentos em um intervalo de datas.

        Args:
            usuario_id: ID do usuário
            data_inicio: Data inicial (inclusiva, formato YYYY-MM-DD)
            data_fim: Data final (inclusiva, formato YYYY-MM-DD)
            limit: Número máximo de registros
            offset: Deslocamento para paginação

        Returns:
            Lista de LancamentoContabil
        """
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM lancamentos_contabeis
                   WHERE usuario_id = ?
                     AND data BETWEEN ? AND ?
                   ORDER BY data DESC, id DESC
                   LIMIT ? OFFSET ?""",
                (usuario_id, data_inicio, data_fim, limit, offset),
            ).fetchall()
        return [LancamentoContabil.from_row(r) for r in rows]

    def listar_por_periodo_com_nomes(
        self,
        usuario_id: int,
        data_inicio: str,
        data_fim: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict]:
        """
        Lista lançamentos em um intervalo de datas com nomes das contas resolvidos via JOIN.

        UMA ÚNICA QUERY com JOINs — elimina N+1 lookups do PlanoContasRepository
        que ocorriam no service ao resolver nomes de conta para cada lançamento.
        Args:
            usuario_id: ID do usuário
            data_inicio: Data inicial (inclusiva, formato YYYY-MM-DD)
            data_fim: Data final (inclusiva, formato YYYY-MM-DD)
            limit: Número máximo de registros
            offset: Deslocamento para paginação
        Returns:
            Lista de dicts com campos: id, uuid, data, historico, valor,
            debito_id, credito_id, transacao_id,
            conta_debito_nome, conta_credito_nome (já formatados)
        """
        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT l.id, l.uuid, l.data, l.historico, l.valor,
                          l.debito_id, l.credito_id, l.transacao_id,
                          COALESCE(d.codigo || ' - ' || d.nome, '[Conta ' || l.debito_id || ']') AS conta_debito_nome,
                          COALESCE(c.codigo || ' - ' || c.nome, '[Conta ' || l.credito_id || ']') AS conta_credito_nome
                    FROM lancamentos_contabeis l
                   LEFT JOIN plano_contas d ON l.debito_id = d.id AND d.usuario_id = ?
                   LEFT JOIN plano_contas c ON l.credito_id = c.id AND c.usuario_id = ?
                    WHERE l.usuario_id = ?
                     AND l.data BETWEEN ? AND ?
                   ORDER BY l.data DESC, l.id DESC
                   LIMIT ? OFFSET ?""",
                (usuario_id, usuario_id, usuario_id, data_inicio, data_fim, limit, offset),
            ).fetchall()
        return _rows_to_list(rows)

    def deletar(self, lancamento_id: int, usuario_id: int) -> bool:
        """
        Remove fisicamente um lançamento contábil.

        Diferente de transações (que usam soft-delete), lançamentos
        contábeis podem ser deletados permanentemente porque:
        1. São registros atômicos (não têm filhos)
        2. O UUID garante rastreabilidade externa
        3. O service pode optar por estornar em vez de deletar

        Args:
            lancamento_id: ID do lançamento
            usuario_id: ID do usuário (filtro de segurança)

        Returns:
            True se deletou, False se não encontrou
        """
        with self._db.get_write_conn() as conn:
            cur = conn.execute(
                "DELETE FROM lancamentos_contabeis "
                "WHERE id = ? AND usuario_id = ?",
                (lancamento_id, usuario_id),
            )
        return cur.rowcount > 0

    def calcular_saldo(
        self,
        conta_id: int,
        usuario_id: int,
        data_ate: str | None = None,
    ) -> dict | None:
        """
        Calcula totais de débito e crédito de uma conta com UMA ÚNICA QUERY.

        Usa SUM + CASE WHEN diretamente no SQLite, eliminando:
        - Duas idas ao banco (antes: duas queries separadas)
        - Carga de linhas em memória (antes: carregava todos os lançamentos)
        - Processamento Python para somar (agora é feito no banco)

        A query única permite que o SQLite otimize o plano de execução
        com um único scan na tabela, aplicando os dois CASE WHEN
        em cada linha lida.

        Impacto:
        - Menos RAM: não carrega linhas
        - Menos CPU: agregação no banco
        - Menos tempo de resposta: uma query vs duas

        Args:
            conta_id: ID da conta contábil
            usuario_id: ID do usuário (filtro de segurança)
            data_ate: Data limite (inclusiva, YYYY-MM-DD).
                      Se None, considera todos os lançamentos.

        Returns:
            Dict com 'total_debito_sum' e 'total_credito_sum'
            ou None se não houver lançamentos.
        """
        with self._db.get_conn() as conn:
            if data_ate:
                row = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(CASE WHEN l.debito_id = ? THEN l.valor ELSE 0 END), 0) AS total_debito_sum,
                        COALESCE(SUM(CASE WHEN l.credito_id = ? THEN l.valor ELSE 0 END), 0) AS total_credito_sum
                    FROM lancamentos_contabeis l
                    WHERE l.usuario_id = ?
                      AND (l.debito_id = ? OR l.credito_id = ?)
                      AND l.data <= ?
                    """,
                    (conta_id, conta_id, usuario_id, conta_id, conta_id, data_ate),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(CASE WHEN l.debito_id = ? THEN l.valor ELSE 0 END), 0) AS total_debito_sum,
                        COALESCE(SUM(CASE WHEN l.credito_id = ? THEN l.valor ELSE 0 END), 0) AS total_credito_sum
                    FROM lancamentos_contabeis l
                    WHERE l.usuario_id = ?
                      AND (l.debito_id = ? OR l.credito_id = ?)
                    """,
                    (conta_id, conta_id, usuario_id, conta_id, conta_id),
                ).fetchone()

        if row is None:
            return None

        total_debito = row['total_debito_sum']
        total_credito = row['total_credito_sum']

        # Se ambos forem zero, retorna None para indicar que não há lançamentos
        if total_debito == 0 and total_credito == 0:
            return None

        return {
            'total_debito_sum': total_debito,
            'total_credito_sum': total_credito,
        }

