"""
services/contabil_service.py — Centraliza todas as regras contábeis.

Responsabilidades:
------------------
- Orquestrar PlanoContasRepository e LancamentoContabilRepository
- Validar TODAS as regras de domínio antes de persistir
- NENHUMA regra de negócio deve ficar em routes
- Repository continua sem validações de domínio

Regras validadas:
-----------------
1. Contas de débito e crédito existem e pertencem ao usuário
2. Contas estão ativas
3. Contas aceitam lançamentos (aceita_lancamentos = True)
4. Débito != Crédito
5. Valor > 0
6. Data válida (formato YYYY-MM-DD)
7. Histórico não vazio
"""

import logging
import uuid as uuid_lib
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from database.repositories import (
    LancamentoContabil,
    PlanoConta,
    PlanoContasRepository,
    LancamentoContabilRepository,
    TransacaoRepository,
)
from utils.metrics import metricas, medir, tempo_consulta
from database.manager import DatabaseManager


@dataclass
class PartidaDobradaDTO:
    """
    DTO para exibição de partida dobrada no template.

    Contém dados do lançamento contábil + nomes das contas
    de débito e crédito (resolvidos via JOIN ou lookup).
    """
    id: int
    uuid: str
    data: str
    historico: str
    valor: float
    conta_debito_nome: str
    conta_credito_nome: str
    transacao_id: int | None = None

logger = logging.getLogger(__name__)


def _validar_data(data: str) -> str | None:
    """
    Valida formato e existência da data.

    Retorna mensagem de erro ou None se válida.
    """
    if not data or not data.strip():
        return "Data é obrigatória"

    try:
        datetime.strptime(data.strip(), "%Y-%m-%d")
        return None
    except ValueError:
        return f"Data inválida: '{data}'. Use o formato YYYY-MM-DD"


class ContabilService:
    """
    Serviço contábil — orquestra operações de partida dobrada.

    Centraliza TODAS as validações contábeis.
    Recebe repositórios via injeção de dependência.
    """

    def __init__(
        self,
        db: DatabaseManager,
        plano_contas_repo: PlanoContasRepository,
        lancamento_repo: LancamentoContabilRepository,
        transacao_repo: TransacaoRepository,
    ) -> None:
        self._db = db
        self._plano_contas = plano_contas_repo
        self._lancamentos = lancamento_repo
        self._transacoes = transacao_repo

    # ── Validações ────────────────────────────────────────────────────────────

    def validar_conta_lancavel(self, conta_id: int, usuario_id: int) -> tuple[bool, str]:
        """
        Valida se uma conta contábil pode receber lançamentos.

        Regras:
        - Conta existe
        - Conta pertence ao usuário
        - Conta está ativa
        - Conta aceita lançamentos (aceita_lancamentos = True)

        Returns:
            (True, "") se válida
            (False, "mensagem de erro") se inválida
        """
        conta = self._plano_contas.buscar_por_id(conta_id, usuario_id)
        if conta is None:
            return False, f"Conta contábil id={conta_id} não encontrada"

        if not conta.ativo:
            return False, f"Conta '{conta.nome}' ({conta.codigo}) está inativa"

        if not conta.aceita_lancamentos:
            return False, f"Conta '{conta.nome}' ({conta.codigo}) não aceita lançamentos diretos"

        return True, ""

    def _validar_lancamento(
        self,
        debito_id: int,
        credito_id: int,
        valor: float,
        data: str,
        historico: str,
        usuario_id: int,
    ) -> tuple[bool, str]:
        """
        Valida todas as regras de um lançamento contábil.

        Returns:
            (True, "") se válido
            (False, "mensagem de erro") se inválido
        """
        # 1. Débito != Crédito
        if debito_id == credito_id:
            return False, "Conta de débito e crédito devem ser diferentes"

        # 2. Valor > 0
        if not valor or valor <= 0:
            return False, "Valor do lançamento deve ser maior que zero"

        # 3. Data válida
        erro_data = _validar_data(data)
        if erro_data:
            return False, erro_data

        # 4. Histórico não vazio
        if not historico or not historico.strip():
            return False, "Histórico do lançamento não pode ser vazio"

        # 5. Valida conta de débito
        valido, erro = self.validar_conta_lancavel(debito_id, usuario_id)
        if not valido:
            return False, f"Débito: {erro}"

        # 6. Valida conta de crédito
        valido, erro = self.validar_conta_lancavel(credito_id, usuario_id)
        if not valido:
            return False, f"Crédito: {erro}"

        return True, ""

    # ── Operação principal: partida dobrada com transação atômica ─────────────

    @medir('criar_lancamento_completo')
    def criar_lancamento_completo(
        self,
        usuario_id: int,
        data: str,
        historico: str,
        valor: float,
        debito_id: int,
        credito_id: int,
        descricao_transacao: str,
        tipo_transacao: str,
        categoria_id: int,
    ) -> tuple[bool, str | dict]:
        """
        Cria transação financeira E lançamento contábil em UMA transação atômica.

        Este método orquestra a criação completa de uma partida dobrada:
        1. Valida todas as regras contábeis PRIMEIRO (evita abrir transação à toa)
        2. Abre transação SQL via DatabaseManager.get_write_conn() com lock thread-safe
        3. Insere a transação financeira (tabela transacoes)
        4. Insere o lançamento contábil (tabela lancamentos_contabeis)
        5. COMMIT se tudo ok, ROLLBACK em qualquer erro

        A transação atômica garante que NENHUMA gravação parcial ocorra
        em caso de erro — o DatabaseManager.get_write_conn() garante
        rollback automático se qualquer exceção for lançada dentro do
        context manager.

        O lock global de escrita (_write_lock) serializa escritas concorrentes,
        prevenindo "database is locked" em condições de corrida.

        Args:
            usuario_id: ID do usuário
            data: Data do lançamento (YYYY-MM-DD)
            historico: Descrição do lançamento contábil
            valor: Valor positivo
            debito_id: ID da conta debitada
            credito_id: ID da conta creditada
            descricao_transacao: Descrição amigável (para a transação financeira)
            tipo_transacao: 'receita' ou 'despesa'
            categoria_id: ID da categoria da transação

        Returns:
            (True, dict{"transacao_id": int, "lancamento": LancamentoContabil})
            (False, "mensagem de erro")
        """
        # Valida regras de negócio contábeis PRIMEIRO (evita abrir transação à toa)
        valido, erro_validacao = self._validar_lancamento(
            debito_id=debito_id,
            credito_id=credito_id,
            valor=valor,
            data=data,
            historico=historico,
            usuario_id=usuario_id,
        )
        if not valido:
            return False, erro_validacao

        # Gera UUIDs para os novos registros
        transacao_uuid = str(uuid_lib.uuid4())
        lancamento_uuid = str(uuid_lib.uuid4())

        try:
            # Usa o get_write_conn() do DatabaseManager que:
            # 1. Adquire o write_lock (serializa escritas concorrentes)
            # 2. Abre conexão configurada (WAL, FK, etc.)
            # 3. Faz ROLLBACK automático em caso de exceção
            # 4. Faz COMMIT se tudo der certo (fim do context manager)
                        # 5. Fecha a conexão no finally
            with self._db.get_write_conn(operacao="criar_lancamento_completo") as conn:
                # Passo 1: Insere transação financeira (via repository, conn externa)
                transacao_id = self._transacoes.inserir(
                    uuid=transacao_uuid,
                    descricao=descricao_transacao.strip(),
                    valor=round(valor, 2),
                    tipo=tipo_transacao,
                    categoria_id=categoria_id,
                    data=data.strip(),
                    usuario_id=usuario_id,
                    conn=conn,
                )

                # Passo 2: Insere lançamento contábil (via repository, conn externa)
                lancamento = self._lancamentos.criar(
                    uuid=lancamento_uuid,
                    usuario_id=usuario_id,
                    data=data.strip(),
                    historico=historico.strip(),
                    valor=round(valor, 2),
                    debito_id=debito_id,
                    credito_id=credito_id,
                    transacao_id=transacao_id,
                    conn=conn,
                )

                # O COMMIT acontece automaticamente ao sair do context manager
                # (o yield conn do get_write_conn termina, chamando conn.commit())
                # O ROLLBACK acontece automaticamente se qualquer exceção ocorrer
                # (o except do get_conn/get_write_conn chama conn.rollback())

                logger.info(
                    "Lançamento contábil completo criado: transacao_id=%d lancamento_id=%d uuid=%s valor=%.2f",
                    transacao_id, lancamento.id, lancamento.uuid, lancamento.valor,
                )
                return True, {
                    "transacao_id": transacao_id,
                    "lancamento": lancamento,
                }

        except sqlite3.IntegrityError as exc:
            logger.error(
                "IntegrityError ao criar lançamento completo: %s", exc, exc_info=True,
            )
            return False, f"Erro de integridade: {exc}"

        except Exception as exc:
            logger.error(
                "Erro ao criar lançamento completo: %s", exc, exc_info=True,
            )
            return False, f"Erro interno ao salvar lançamento: {exc}"

    # ── Operações CRUD (já existentes) ────────────────────────────────────────

    def criar_lancamento(
        self,
        usuario_id: int,
        data: str,
        historico: str,
        valor: float,
        debito_id: int,
        credito_id: int,
        transacao_id: int | None = None,
    ) -> tuple[bool, str | LancamentoContabil]:
        """
        Cria um lançamento contábil com todas as validações.
        (Método original, mantido para compatibilidade)
        """
        # Valida regras de negócio
        valido, erro = self._validar_lancamento(
            debito_id=debito_id,
            credito_id=credito_id,
            valor=valor,
            data=data,
            historico=historico,
            usuario_id=usuario_id,
        )
        if not valido:
            return False, erro

        # Persiste
        try:
            lc_uuid = str(uuid_lib.uuid4())
            lancamento = self._lancamentos.criar(
                uuid=lc_uuid,
                usuario_id=usuario_id,
                data=data.strip(),
                historico=historico.strip(),
                valor=valor,
                debito_id=debito_id,
                credito_id=credito_id,
                transacao_id=transacao_id,
            )
            logger.info(
                "Lançamento contábil criado: id=%d uuid=%s valor=%.2f",
                lancamento.id, lancamento.uuid, lancamento.valor,
            )
            return True, lancamento

        except Exception as exc:
            logger.error(
                "Erro ao criar lançamento contábil: %s", exc, exc_info=True,
            )
            return False, f"Erro interno ao salvar lançamento: {exc}"

    def buscar_lancamento(
        self,
        lancamento_id: int,
        usuario_id: int,
    ) -> LancamentoContabil | None:
        """
        Busca lançamento pelo ID com isolamento de usuário.

        Args:
            lancamento_id: ID do lançamento
            usuario_id: ID do usuário (filtro de segurança)

        Returns:
            LancamentoContabil ou None se não encontrado
        """
        return self._lancamentos.buscar_por_id(lancamento_id, usuario_id)

    def listar_lancamentos(
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
        return self._lancamentos.listar_por_usuario(usuario_id, limit, offset)

    def listar_lancamentos_por_conta(
        self,
        conta_id: int,
        usuario_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[bool, str | list[LancamentoContabil]]:
        """
        Lista lançamentos que envolvem uma conta específica.

        Primeiro valida se a conta existe e pertence ao usuário.

        Args:
            conta_id: ID da conta contábil
            usuario_id: ID do usuário
            limit: Número máximo de registros
            offset: Deslocamento para paginação

        Returns:
            (True, list[LancamentoContabil]) em caso de sucesso
            (False, "mensagem de erro") se conta não encontrada
        """
        # Verifica se a conta existe (apenas para validar pertencimento)
        conta = self._plano_contas.buscar_por_id(conta_id, usuario_id)
        if conta is None:
            return False, f"Conta contábil id={conta_id} não encontrada"

        lancamentos = self._lancamentos.listar_por_conta(
            conta_id, usuario_id, limit, offset,
        )
        return True, lancamentos

    def listar_lancamentos_por_periodo(
        self,
        usuario_id: int,
        data_inicio: str,
        data_fim: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[bool, str | list[LancamentoContabil]]:
        """
        Lista lançamentos em um intervalo de datas com validação.

        Args:
            usuario_id: ID do usuário
            data_inicio: Data inicial (inclusiva, YYYY-MM-DD)
            data_fim: Data final (inclusiva, YYYY-MM-DD)
            limit: Número máximo de registros
            offset: Deslocamento para paginação

        Returns:
            (True, list[LancamentoContabil]) em caso de sucesso
            (False, "mensagem de erro") se datas inválidas
        """
        erro_ini = _validar_data(data_inicio)
        if erro_ini:
            return False, f"Data início: {erro_ini}"

        erro_fim = _validar_data(data_fim)
        if erro_fim:
            return False, f"Data fim: {erro_fim}"

        if data_inicio > data_fim:
            return False, "Data início não pode ser maior que data fim"

        lancamentos = self._lancamentos.listar_por_periodo(
            usuario_id, data_inicio, data_fim, limit, offset,
        )
        return True, lancamentos

    # ── Partida Dobrada para listagem (com nomes das contas) ────────────────

    @medir('listar_partidas_dobradas')
    def listar_partidas_dobradas_por_periodo(
        self,
        usuario_id: int,
        data_inicio: str,
        data_fim: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[PartidaDobradaDTO]:
        """
        Lista lançamentos de partida dobrada enriquecidos com nomes das contas.

        Fonte oficial: tabela lancamentos_contabeis.
        Agora usa uma ÚNICA QUERY com JOIN para resolver nomes das contas
        de débito e crédito — eliminou N+1 lookups do PlanoContasRepository.
        Args:
            usuario_id: ID do usuário
            data_inicio: Data inicial (YYYY-MM-DD, inclusiva)
            data_fim: Data final (YYYY-MM-DD, inclusiva)
            limit: Máximo de registros
            offset: Deslocamento para paginação

        Returns:
            Lista de PartidaDobradaDTO pronta para o template
        """
        # Usa o novo método otimizado que faz JOIN SQL em vez de N lookups
        rows = self._lancamentos.listar_por_periodo_com_nomes(
            usuario_id, data_inicio, data_fim, limit, offset,
        )

        return [
            PartidaDobradaDTO(
                id=r['id'],
                uuid=r['uuid'],
                data=r['data'],
                historico=r['historico'],
                valor=r['valor'],
                conta_debito_nome=r['conta_debito_nome'],
                conta_credito_nome=r['conta_credito_nome'],
                transacao_id=r.get('transacao_id'),
            )
            for r in rows
        ]

    # ── Funções contábeis ─────────────────────────────────────────────────────

    @medir('saldo_conta')
    def saldo_conta(
        self,
        conta_id: int,
        usuario_id: int,
        data_ate: str | None = None,
    ) -> tuple[bool, str | float]:
        """
        Calcula o saldo de uma conta contábil até uma data.

        Saldo = SUM(valor dos débitos) - SUM(valor dos créditos)
        para contas de natureza DEVEDORA.

        Para contas de natureza CREDORA, inverte o sinal:
        Saldo = SUM(valor dos créditos) - SUM(valor dos débitos)

        Agora usa uma única query SQL agregada (SUM + CASE WHEN)
        em vez de carregar linhas em memória.

        Args:
            conta_id: ID da conta contábil
            usuario_id: ID do usuário
            data_ate: Data limite (inclusiva, YYYY-MM-DD).
                      Se None, considera todos os lançamentos.

        Returns:
            (True, saldo_float) em caso de sucesso
            (False, "mensagem de erro") se conta não encontrada
        """
        # Valida conta
        conta = self._plano_contas.buscar_por_id(conta_id, usuario_id)
        if conta is None:
            return False, f"Conta contábil id={conta_id} não encontrada"

        # Valida data_ate antes de qualquer processamento
        if data_ate:
            erro_data = _validar_data(data_ate)
            if erro_data:
                return False, erro_data

        # Delega cálculo para o repositório (uma única query SQL com SUM + CASE WHEN)
        totais = self._lancamentos.calcular_saldo(
            conta_id=conta_id,
            usuario_id=usuario_id,
            data_ate=data_ate,
        )

        if totais is None:
            return True, 0.0

        if conta.natureza == "devedora":
            saldo = totais['total_debito_sum'] - totais['total_credito_sum']
        else:
            saldo = totais['total_credito_sum'] - totais['total_debito_sum']

        return True, round(saldo, 2)

    def deletar_lancamento(
        self,
        lancamento_id: int,
        usuario_id: int,
    ) -> tuple[bool, str]:
        """
        Deleta fisicamente um lançamento contábil.

        Verifica se o lançamento existe e pertence ao usuário
        antes de deletar.

        Args:
            lancamento_id: ID do lançamento
            usuario_id: ID do usuário

        Returns:
            (True, "") em caso de sucesso
            (False, "mensagem de erro") se não encontrado
        """
        lancamento = self._lancamentos.buscar_por_id(lancamento_id, usuario_id)
        if lancamento is None:
            return False, f"Lançamento id={lancamento_id} não encontrado"

        deletado = self._lancamentos.deletar(lancamento_id, usuario_id)
        if deletado:
            logger.info(
                "Lançamento deletado: id=%d uuid=%s", lancamento_id, lancamento.uuid,
            )
            return True, ""

        return False, f"Erro ao deletar lançamento id={lancamento_id}"


