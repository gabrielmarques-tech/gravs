"""
utils/calendario.py — Utilitários de cálculo de datas para o Brasil.

Por que separar em utils/?
-----------------------------
CalendarioUtil não é regra de negócio (não decide QUANDO lançar),
nem é infraestrutura (não acessa banco). É um utilitário puro:
entra data, sai data calculada. Perfeitamente testável sem banco.

O código original já tinha essa classe isolada em financeiro.py,
mas misturada com acesso ao banco. Aqui ela fica pura.
"""

import calendar
from datetime import date, timedelta

import holidays


class CalendarioUtil:
    """
    Cálculos de dias úteis com feriados brasileiros.

    Convencão dos dias de vencimento:
    - Positivo (1–28): dia fixo do mês (ex: 5 = dia 5)
    - Negativo (-1 a -31): N-ésimo dia útil (ex: -1 = 1º dia útil)

    Por que limitar dias fixos a 28?
    -----------------------------------
    Fevereiro tem no mínimo 28 dias. Dias 29, 30, 31 não existem em
    todos os meses. Usando 28 como limite, o sistema garante que
    todo vencimento fixo tem uma data válida em qualquer mês.
    """

    def __init__(self) -> None:
        self._feriados_br = holidays.Brazil()

    def eh_dia_util(self, data: date) -> bool:
        """Retorna True se a data é dia útil (seg–sex, sem feriado nacional BR)."""
        if data.weekday() >= 5:  # 5=sábado, 6=domingo
            return False
        return data not in self._feriados_br

    def proximo_dia_util(self, data: date) -> date:
        """Avança para o próximo dia útil se a data não for útil."""
        while not self.eh_dia_util(data):
            data += timedelta(days=1)
        return data

    def dia_util_do_mes(self, ano: int, mes: int, n: int) -> date:
        """
        Retorna o N-ésimo dia útil do mês (n ≥ 1).
        Se N > total de dias úteis no mês, retorna o último dia útil.
        """
        if n < 1:
            raise ValueError(f"n deve ser >= 1, recebido: {n}")

        data = date(ano, mes, 1)
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        contagem = 0

        while data.day <= ultimo_dia:
            if self.eh_dia_util(data):
                contagem += 1
                if contagem == n:
                    return data
            data += timedelta(days=1)

        # N é maior que o total de dias úteis: retorna o último dia útil
        data = date(ano, mes, ultimo_dia)
        while not self.eh_dia_util(data):
            data -= timedelta(days=1)
        return data

    def calcular_data_vencimento(self, ano: int, mes: int, dia: int) -> date:
        """
        Converte o campo `dia_vencimento` em uma data concreta.

        dia > 0: dia fixo, ajustado para próximo dia útil se necessário
        dia < 0: N-ésimo dia útil do mês (abs(dia))
        """
        if dia < 0:
            return self.dia_util_do_mes(ano, mes, abs(dia))

        ultimo_dia = calendar.monthrange(ano, mes)[1]
        data = date(ano, mes, min(dia, ultimo_dia))
        return self.proximo_dia_util(data)