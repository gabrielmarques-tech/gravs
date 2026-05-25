"""
utils/validators.py — Validações de entrada reutilizáveis.

Por que separar validações?
------------------------------
No código original, validações estavam espalhadas entre routes e classes
de domínio. Centralizar validações:
1. Evita duplicação (mesma regra em 3 lugares = 3 pontos de falha)
2. Facilita testes unitários das regras isoladamente
3. Services importam validators, não re-implementam lógica

Convenção: funções retornam None se válido, string de erro se inválido.
Isso permite uso simples: `erro = validar_email(email); if erro: ...`
"""

import re
from config import Config


def validar_email(email: str) -> str | None:
    """Retorna mensagem de erro ou None se válido."""
    if not email or not isinstance(email, str):
        return "Email é obrigatório"
    email = email.strip()
    # Regex simples mas suficiente — valida formato básico
    padrao = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.match(padrao, email):
        return "Email inválido"
    return None


def validar_senha(senha: str) -> str | None:
    """Retorna mensagem de erro ou None se válida."""
    if not senha:
        return "Senha é obrigatória"
    if len(senha) < Config.MIN_SENHA_LEN:
        return f"Senha deve ter pelo menos {Config.MIN_SENHA_LEN} caracteres"
    return None


def validar_nome(nome: str) -> str | None:
    """Retorna mensagem de erro ou None se válido."""
    if not nome or not nome.strip():
        return "Nome é obrigatório"
    if len(nome.strip()) < 2:
        return "Nome deve ter pelo menos 2 caracteres"
    return None


def validar_valor(valor: float | None) -> str | None:
    """Retorna mensagem de erro ou None se valor de transação válido."""
    if valor is None:
        return "Valor é obrigatório"
    if not isinstance(valor, (int, float)):
        return "Valor deve ser numérico"
    if valor <= 0:
        return "Valor deve ser maior que zero"
    if valor > 999_999_999:
        return "Valor excede o limite permitido"
    return None


def validar_tipo(tipo: str | None) -> str | None:
    """Valida tipo de transação."""
    if tipo not in ("receita", "despesa"):
        return "Tipo deve ser 'receita' ou 'despesa'"
    return None


def validar_parcelas(parcelas: int | None) -> str | None:
    """Valida número de parcelas."""
    if parcelas is None:
        return "Número de parcelas é obrigatório"
    if not isinstance(parcelas, int):
        return "Número de parcelas deve ser inteiro"
    if not (Config.MIN_PARCELAS <= parcelas <= Config.MAX_PARCELAS):
        return (
            f"Parcelas deve ser entre {Config.MIN_PARCELAS} e {Config.MAX_PARCELAS}"
        )
    return None


def validar_dia_vencimento(dia: int | None) -> str | None:
    """Valida dia de vencimento de recorrente."""
    if dia is None:
        return "Dia de vencimento é obrigatório"
    valido = (1 <= dia <= 28) or (-31 <= dia <= -1)
    if not valido:
        return "Dia deve ser entre 1-28 (fixo) ou -1 a -31 (dia útil)"
    return None


def validar_data(data_str: str | None) -> str | None:
    """Valida string de data no formato YYYY-MM-DD."""
    if not data_str:
        return "Data é obrigatória"
    from datetime import datetime
    try:
        datetime.strptime(data_str, "%Y-%m-%d")
    except ValueError:
        return "Data inválida. Use o formato AAAA-MM-DD"
    return None


def coletar_erros(**campos) -> dict[str, str]:
    """
    Valida múltiplos campos de uma vez. Retorna dict de {campo: erro}.

    Uso:
        erros = coletar_erros(email=validar_email(email), senha=validar_senha(senha))
        if erros: return jsonify({'erros': erros}), 422
    """
    return {campo: erro for campo, erro in campos.items() if erro is not None}