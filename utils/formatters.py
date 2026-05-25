"""
utils/formatters.py — Funções de formatação puras.

Por que separar formatação?
------------------------------
No código original, `formatar_real()` estava definida em app.py junto
com as rotas. Funções de formatação são utilitários reutilizáveis:
podem ser usadas em routes, services e templates sem criar dependências
circulares. Funções puras (sem side-effects) são triviais de testar.
"""

import html
import re


def formatar_real(valor: float) -> str:
    """
    Formata valor float para moeda brasileira.

    Exemplo: 1234.5 → "R$ 1.234,50"

    Por que não usar locale?
    --------------------------
    locale.setlocale() tem comportamento global e não é thread-safe.
    A formatação manual é mais segura em ambientes web concorrentes.
    """
    try:
        # Formata com separador de milhar e 2 casas decimais
        # f"{1234.5:,.2f}" → "1,234.50" (padrão EN-US)
        # Depois troca separadores para PT-BR
        formatado = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatado}"
    except (TypeError, ValueError):
        return "R$ 0,00"


def parse_valor_monetario(valor_str: str) -> float:
    """
    Converte string de valor monetário brasileiro para float.

    Aceita: "1.234,50", "1234,50", "1234.50", "1234"
    Retorna: float ou levanta ValueError

    Por que isso existe?
    ---------------------
    O frontend formata valores como "1.234,50" (PT-BR).
    O Python espera "1234.50" (EN-US). Sem conversão explícita,
    float("1.234,50") levanta ValueError silencioso e o valor vira 0.
    Essa conversão deve ser testada exaustivamente.
    """
    if not valor_str:
        raise ValueError("Valor não pode ser vazio")

    # Remove R$, espaços e outros caracteres não numéricos exceto . e ,
    limpo = re.sub(r"[^\d.,]", "", str(valor_str).strip())

    if not limpo:
        raise ValueError(f"Valor inválido: '{valor_str}'")

    # Detecta formato PT-BR (vírgula como decimal): "1.234,50"
    if "," in limpo and "." in limpo:
        # Tem ambos: ponto é separador de milhar, vírgula é decimal
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        # Só vírgula: é o separador decimal
        limpo = limpo.replace(",", ".")
    # Se só ponto: já está em formato EN-US — mantém

    try:
        valor = float(limpo)
    except ValueError:
        raise ValueError(f"Não foi possível converter '{valor_str}' para número")

    if valor < 0:
        raise ValueError("Valor monetário não pode ser negativo")

    return round(valor, 2)


def escape_html(valor: str) -> str:
    """Escapa HTML para uso seguro em templates f-string."""
    return html.escape(str(valor))


def formatar_percentual(valor: float, total: float) -> str:
    """Retorna percentual formatado: '25,4%'. Retorna '0%' se total=0."""
    if total == 0:
        return "0%"
    pct = (valor / total) * 100
    return f"{pct:.1f}%".replace(".", ",")