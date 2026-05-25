"""
services/recorrente_service.py — Regras de negócio para recorrentes.

A lógica mais delicada aqui é `gerar_lancamentos_pendentes`:
ela verifica quais recorrentes ainda não foram lançados no mês
e os lança automaticamente. Deve ser idempotente (pode ser chamada
múltiplas vezes sem criar duplicatas).
"""

import logging
import uuid as uuid_lib
from datetime import date

from database.repositories import RecorrenteRepository, TransacaoRepository
from services.transacao_service import TransacaoService
from utils.calendario import CalendarioUtil
from utils.validators import (
    coletar_erros,
    validar_dia_vencimento,
    validar_tipo,
    validar_valor,
)

logger = logging.getLogger(__name__)


class RecorrenteService:
    """Orquestra operações sobre lançamentos recorrentes."""

    def __init__(
        self,
        recorrente_repo: RecorrenteRepository,
        transacao_service: TransacaoService,
        calendario: CalendarioUtil,
    ) -> None:
        self._repo = recorrente_repo
        self._transacoes = transacao_service
        self._calendario = calendario

    def adicionar(
        self,
        descricao: str,
        valor: float,
        tipo: str,
        categoria_id: int,
        dia_vencimento: int,
        usuario_id: int,
    ) -> tuple[int | None, dict[str, str]]:
        """Cadastra novo recorrente com validação completa."""
        erros = coletar_erros(
            valor=validar_valor(valor),
            tipo=validar_tipo(tipo),
            dia_vencimento=validar_dia_vencimento(dia_vencimento),
        )
        if not descricao or not str(descricao).strip():
            erros["descricao"] = "Descrição não pode ser vazia"
        if erros:
            return None, erros

        novo_uuid = str(uuid_lib.uuid4())
        id_rec = self._repo.inserir(
            uuid=novo_uuid,
            descricao=str(descricao).strip(),
            valor=valor,
            tipo=tipo,
            categoria_id=categoria_id,
            dia_vencimento=dia_vencimento,
            usuario_id=usuario_id,
        )
        return id_rec, {}

    def listar(self, usuario_id: int) -> list[dict]:
        """Lista todos os recorrentes ativos do usuário."""
        return self._repo.listar_ativos(usuario_id)

    def editar(self, uuid: str, usuario_id: int, **campos) -> tuple[bool, dict]:
        """Edita recorrente com validação de campos."""
        erros = {}
        if "valor" in campos and campos["valor"] is not None:
            erro = validar_valor(campos["valor"])
            if erro:
                erros["valor"] = erro
        if "dia_vencimento" in campos and campos["dia_vencimento"] is not None:
            erro = validar_dia_vencimento(campos["dia_vencimento"])
            if erro:
                erros["dia_vencimento"] = erro
        if erros:
            return False, erros

        atualizado = self._repo.atualizar(uuid, usuario_id, **campos)
        return atualizado, {}

    def desativar(self, uuid: str, usuario_id: int) -> bool:
        """Desativa recorrente (soft-delete)."""
        return self._repo.desativar(uuid, usuario_id)

    def gerar_lancamentos_pendentes(
        self, ano: int, mes: int, usuario_id: int
    ) -> int:
        """
        Lança automaticamente recorrentes que ainda não foram gerados no mês.

        Idempotência garantida por:
        - `existe_recorrente_no_mes()` antes de qualquer inserção
        - Só lança se a data de vencimento já passou (não lança futuro)

        Retorna o número de lançamentos gerados.
        """
        hoje = date.today()
        recorrentes = self._repo.listar_todos_ativos_raw(usuario_id)
        lancados = 0

        for rec in recorrentes:
            data_venc = self._calendario.calcular_data_vencimento(
                ano, mes, rec["dia_vencimento"]
            )

            # Não lança lançamentos futuros
            if data_venc > hoje:
                continue

            # Verifica se já foi lançado este mês (idempotência)
            ja_existe = self._transacoes._repo.existe_recorrente_no_mes(
                rec["uuid"], ano, mes
            )
            if ja_existe:
                continue

            id_t, erros = self._transacoes.adicionar(
                descricao=rec["descricao"],
                valor=rec["valor"],
                tipo=rec["tipo"],
                categoria_id=rec["categoria_id"],
                usuario_id=usuario_id,
                data=data_venc.strftime("%Y-%m-%d"),
                recorrente_uuid=rec["uuid"],
            )

            if id_t:
                lancados += 1
                logger.info(
                    "Recorrente lançado: '%s' em %s (user_id=%d)",
                    rec["descricao"], data_venc, usuario_id,
                )
            else:
                logger.error(
                    "Falha ao lançar recorrente '%s': %s",
                    rec["descricao"], erros,
                )

        return lancados

    def listar_proximos_do_mes(
        self, ano: int, mes: int, usuario_id: int
    ) -> list[dict]:
        """
        Lista recorrentes com status calculado:
        - 'lancado': já existe transação no mês
        - 'agendado': data futura
        - 'passado': data passada mas não lançado (pendente)
        """
        hoje = date.today()
        recorrentes = self._repo.listar_todos_ativos_raw(usuario_id)
        resultado = []

        for rec in recorrentes:
            data_venc = self._calendario.calcular_data_vencimento(
                ano, mes, rec["dia_vencimento"]
            )
            ja_lancado = self._transacoes._repo.existe_recorrente_no_mes(
                rec["uuid"], ano, mes
            )

            if ja_lancado:
                status = "lancado"
            elif data_venc >= hoje:
                status = "agendado"
            else:
                status = "passado"

            resultado.append({
                **rec,
                "data": data_venc.strftime("%d/%m/%Y"),
                "data_iso": data_venc.strftime("%Y-%m-%d"),
                "status": status,
            })

        return sorted(resultado, key=lambda x: x["data_iso"])