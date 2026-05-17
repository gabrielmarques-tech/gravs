"""
services/transacao_service.py — Regras de negócio de transações.

Este service centraliza TODA a lógica de negócio relacionada a transações:
- Adicionar transação simples
- Adicionar transação parcelada (com cálculo de juros)
- Preview de parcelas
- Deleção e restauração com validação de acesso

Por que calcular parcelas no service e não no model?
------------------------------------------------------
Cálculo de parcelas envolve múltiplas operações (PMT, Price, simples),
usa configurações do sistema (MIN/MAX_PARCELAS), e cria múltiplos registros
no banco. Isso excede a responsabilidade de um model puro.
"""

import logging
import uuid as uuid_lib
from datetime import date, datetime, timedelta

from database.repositories import TransacaoRepository
from utils.formatters import parse_valor_monetario
from utils.validators import (
    coletar_erros,
    validar_data,
    validar_parcelas,
    validar_tipo,
    validar_valor,
)

logger = logging.getLogger(__name__)


class TransacaoService:
    """Orquestra operações sobre transações financeiras."""

    def __init__(self, transacao_repo: TransacaoRepository) -> None:
        self._repo = transacao_repo

    def adicionar(
        self,
        descricao: str,
        valor: float,
        tipo: str,
        categoria_id: int,
        usuario_id: int,
        data: str | None = None,
        recorrente_uuid: str | None = None,
        grupo_parcela: str | None = None,
        conta_id: int | None = None,
    ) -> tuple[int | None, dict[str, str]]:
        """
        Adiciona uma transação simples.

        Retorna (id, erros). Em sucesso, erros é dict vazio.
        """
        data_final = data or date.today().strftime("%Y-%m-%d")

        erros = coletar_erros(
            valor=validar_valor(valor),
            tipo=validar_tipo(tipo),
            data=validar_data(data_final),
        )
        if not descricao or not str(descricao).strip():
            erros["descricao"] = "Descrição não pode ser vazia"
        if erros:
            return None, erros

        novo_uuid = str(uuid_lib.uuid4())
        try:
            id_transacao = self._repo.inserir(
                uuid=novo_uuid,
                descricao=str(descricao).strip(),
                valor=valor,
                tipo=tipo,
                categoria_id=categoria_id,
                data=data_final,
                usuario_id=usuario_id,
                recorrente_uuid=recorrente_uuid,
                grupo_parcela=grupo_parcela,
                conta_id=conta_id,
            )
            return id_transacao, {}
        except Exception as exc:
            logger.error("Erro ao inserir transação: %s", exc, exc_info=True)
            return None, {"sistema": "Erro interno ao salvar transação"}

    def adicionar_parcelado(
        self,
        descricao: str,
        valor_total: float,
        tipo: str,
        categoria_id: int,
        usuario_id: int,
        parcelas: int,
        data_inicial: str | None = None,
        tipo_juros: str = "sem",
        taxa_juros_mensal: float = 0.0,
        conta_id: int | None = None,
    ) -> tuple[list[int], dict[str, str]]:
        """
        Cria múltiplas transações para compra parcelada.

        Retorna ([ids], erros).

        Por que timedelta(days=30) para parcelas mensais?
        ---------------------------------------------------
        timedelta(days=30) é uma aproximação. O correto seria avançar
        mês a mês usando relativedelta (dateutil). Usamos 30 dias aqui
        por simplicidade — para um sistema pessoal é aceitável.
        Em um sistema financeiro real, use dateutil.relativedelta.

        Por que grupo_parcela?
        ------------------------
        UUID compartilhado por todas as parcelas de uma compra.
        Permite futuro agrupamento/cancelamento de todas de uma vez.
        """
        erros = coletar_erros(
            valor=validar_valor(valor_total),
            tipo=validar_tipo(tipo),
            parcelas=validar_parcelas(parcelas),
        )
        if erros:
            return [], erros

        valores_parcelas = self.calcular_preview_parcelas(
            valor_total, parcelas, tipo_juros, taxa_juros_mensal
        )

        data_base = (
            datetime.strptime(data_inicial, "%Y-%m-%d")
            if data_inicial
            else datetime.now()
        )

        grupo = str(uuid_lib.uuid4())
        ids_gerados: list[int] = []

        for i, valor_parcela in enumerate(valores_parcelas):
            data_parcela = data_base + timedelta(days=30 * i)
            desc_parcela = f"{descricao} ({i + 1}/{parcelas})"
            id_t, erros_t = self.adicionar(
                descricao=desc_parcela,
                valor=valor_parcela,
                tipo=tipo,
                categoria_id=categoria_id,
                usuario_id=usuario_id,
                data=data_parcela.strftime("%Y-%m-%d"),
                grupo_parcela=grupo,
                conta_id=conta_id,  # mesma conta para todas as parcelas
            )
            if id_t:
                ids_gerados.append(id_t)
            else:
                logger.error("Falha ao criar parcela %d/%d: %s", i + 1, parcelas, erros_t)

        logger.info(
            "Parcelamento criado: %d/%d parcelas, grupo=%s",
            len(ids_gerados), parcelas, grupo
        )
        return ids_gerados, {}

    def calcular_preview_parcelas(
        self,
        valor_total: float,
        parcelas: int,
        tipo_juros: str,
        taxa_mensal: float,
    ) -> list[float]:
        """
        Calcula valor de cada parcela. Três modalidades:

        'sem': divisão simples, diferença de centavos na 1ª parcela
        'simples': juros simples — total × (1 + taxa × n)
        'price': sistema Price (tabela de amortização francês)
                 PMT = PV × [i(1+i)^n] / [(1+i)^n - 1]

        Por que ajustar diferença de centavos na 1ª parcela?
        -------------------------------------------------------
        round() introduz erro de arredondamento acumulado.
        Ex: R$ 10,00 / 3 = R$ 3,333... → R$ 3,33 × 3 = R$ 9,99 (não R$ 10,00)
        A diferença (R$ 0,01) vai para a 1ª parcela, garantindo que
        a soma das parcelas seja exatamente o valor total.
        """
        if tipo_juros == "sem" or taxa_mensal == 0:
            base = round(valor_total / parcelas, 2)
            valores = [base] * parcelas
            diferenca = round(valor_total - base * parcelas, 2)
            valores[0] = round(valores[0] + diferenca, 2)

        elif tipo_juros == "simples":
            total_com_juros = valor_total * (1 + (taxa_mensal / 100) * parcelas)
            base = round(total_com_juros / parcelas, 2)
            valores = [base] * parcelas

        else:  # price
            taxa = taxa_mensal / 100
            if taxa == 0:
                base = round(valor_total / parcelas, 2)
                valores = [base] * parcelas
            else:
                # Fórmula PMT (Price)
                pmt = valor_total * (taxa * (1 + taxa) ** parcelas) / (
                    (1 + taxa) ** parcelas - 1
                )
                valores = [round(pmt, 2)] * parcelas

        return valores

    def buscar_por_uuid(self, uuid: str, usuario_id: int) -> dict | None:
        """Busca transação por UUID garantindo pertença ao usuário."""
        return self._repo.buscar_por_uuid(uuid, usuario_id)

    def deletar(self, id_transacao: int, usuario_id: int) -> bool:
        """Soft-delete de transação."""
        return self._repo.deletar_logico(id_transacao, usuario_id)

    def restaurar(self, id_transacao: int, usuario_id: int) -> bool:
        """Restaura transação deletada."""
        return self._repo.restaurar(id_transacao, usuario_id)

    def editar(self, id_transacao: int, usuario_id: int, **campos) -> bool:
        """Edita campos de uma transação existente."""
        return self._repo.atualizar(id_transacao, usuario_id, **campos)

    def listar_por_periodo(
        self, data_inicio: str, data_fim: str, usuario_id: int
    ) -> list[dict]:
        return self._repo.listar_por_periodo(data_inicio, data_fim, usuario_id)