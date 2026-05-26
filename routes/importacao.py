"""
routes/importacao.py — Importação de extrato bancário via CSV.

Suporta o formato padrão de exportação CSV do Bradesco.
O usuário faz upload do arquivo, o sistema lê, classifica
automaticamente receitas e despesas, e exibe uma tela de
revisão antes de confirmar a importação no banco.

Segurança:
- Arquivo processado em memória, nunca salvo em disco
- Limite de 2MB via MAX_CONTENT_LENGTH no app.py
- Usuário só confirma após revisar — nenhuma inserção cega
- usuario_id sempre vinculado às transações geradas
"""

import csv
import io
import logging
import uuid
from datetime import date, datetime

from flask import (
    Blueprint, flash, jsonify,
    redirect, render_template, request, session, url_for
)
from flask_login import current_user, login_required

from routes.helpers import get_services

logger = logging.getLogger(__name__)

importacao_bp = Blueprint("importacao", __name__, url_prefix="/importacao")

# ── Mapeamento de palavras-chave → categoria padrão ───────────────────────────
# Usado para classificação automática da descrição do extrato.
# Chave: fragmento (lowercase) da descrição. Valor: nome da categoria.
_KEYWORDS_CATEGORIA: list[tuple[str, str]] = [
    # Receitas — PIX recebido vira categoria Receita PIX
    ("salario",     "Salário"),
    ("salário",     "Salário"),
    ("freelance",   "Freelance"),
    ("transferencia recebida", "Outros"),
    ("pix recebido",           "Receita PIX"),
    ("pix rec",                "Receita PIX"),
    ("credito pix",            "Receita PIX"),
    # Despesas PIX — separadas por nome para facilitar rastreio
    ("pix enviado",            "Transferências PIX"),
    ("pix env",                "Transferências PIX"),
    ("pix efetuado",           "Transferências PIX"),
    ("debito pix",             "Transferências PIX"),
    ("transferencia pix",      "Transferências PIX"),
    ("pagamento pix",          "Transferências PIX"),
    # Alimentação
    ("ifood",       "Alimentação"),
    ("rappi",       "Alimentação"),
    ("mcdonalds",   "Alimentação"),
    ("burger",      "Alimentação"),
    ("restaurante", "Alimentação"),
    ("padaria",     "Alimentação"),
    ("mercado",     "Alimentação"),
    ("supermercado","Alimentação"),
    ("carrefour",   "Alimentação"),
    ("extra",       "Alimentação"),
    ("pao de acucar","Alimentação"),
    # Transporte
    ("uber",        "Transporte"),
    ("99app",       "Transporte"),
    ("99pop",       "Transporte"),
    ("posto",       "Transporte"),
    ("combustivel", "Transporte"),
    ("gasolina",    "Transporte"),
    ("metro",       "Transporte"),
    ("bilhete",     "Transporte"),
    # Moradia
    ("aluguel",     "Moradia"),
    ("condominio",  "Moradia"),
    ("luz",         "Moradia"),
    ("energia",     "Moradia"),
    ("agua",        "Moradia"),
    ("gas",         "Moradia"),
    # Saúde
    ("farmacia",    "Saúde"),
    ("drogasil",    "Saúde"),
    ("ultrafarma",  "Saúde"),
    ("medico",      "Saúde"),
    ("clinica",     "Saúde"),
    ("hospital",    "Saúde"),
    ("laboratorio", "Saúde"),
    # Lazer
    ("netflix",     "Assinaturas"),
    ("spotify",     "Assinaturas"),
    ("amazon prime","Assinaturas"),
    ("disney",      "Assinaturas"),
    ("hbo",         "Assinaturas"),
    ("cinema",      "Lazer"),
    ("teatro",      "Lazer"),
    # Educação
    ("escola",      "Educação"),
    ("faculdade",   "Educação"),
    ("curso",       "Educação"),
    ("livro",       "Educação"),
    ("udemy",       "Educação"),
]


def _classificar_categoria(descricao: str) -> str:
    """
    Tenta adivinhar a categoria a partir da descrição do lançamento.
    Retorna o nome da categoria sugerida ou 'Outros'.
    """
    desc_lower = descricao.lower()
    for keyword, categoria in _KEYWORDS_CATEGORIA:
        if keyword in desc_lower:
            return categoria
    return "Outros"


def _parsear_csv_bradesco(conteudo: str) -> list[dict]:
    """
    Lê o CSV no formato Bradesco e retorna lista de transações brutas.

    O Bradesco exporta com:
    - Separador: ponto e vírgula (;)
    - Encoding: latin-1
    - Colunas: Data;Histórico;Docto;Crédito;Débito;Saldo
    - Linhas de cabeçalho e rodapé que devem ser ignoradas
    - Valores com vírgula decimal e possível ponto como milhar

    Retorna lista de dicts com:
        data, descricao, valor, tipo, categoria_sugerida
    """
    transacoes = []
    reader = csv.reader(io.StringIO(conteudo), delimiter=";")

    cabecalho_encontrado = False

    for linha in reader:
        # Ignora linhas vazias ou muito curtas
        if len(linha) < 5:
            continue

        # Detecta a linha de cabeçalho real
        primeira = linha[0].strip().lower()
        if "data" in primeira and not cabecalho_encontrado:
            cabecalho_encontrado = True
            continue

        if not cabecalho_encontrado:
            continue

        # A partir daqui, processa linhas de dados
        try:
            data_str   = linha[0].strip()
            historico  = linha[1].strip() if len(linha) > 1 else ""
            credito    = linha[3].strip() if len(linha) > 3 else ""
            debito     = linha[4].strip() if len(linha) > 4 else ""

            # Ignora linhas de totais ou rodapé
            if not data_str or not historico:
                continue
            # Valida formato de data DD/MM/AAAA
            try:
                dt = datetime.strptime(data_str, "%d/%m/%Y")
                data_iso = dt.strftime("%Y-%m-%d")
            except ValueError:
                continue  # Linha não é dado — pula

            def parse_valor(v: str) -> float | None:
                v = v.strip().replace(".", "").replace(",", ".")
                if not v:
                    return None
                try:
                    f = float(v)
                    return round(abs(f), 2) if f != 0 else None
                except ValueError:
                    return None

            val_credito = parse_valor(credito)
            val_debito  = parse_valor(debito)

            if val_credito and val_credito > 0:
                tipo  = "receita"
                valor = val_credito
            elif val_debito and val_debito > 0:
                tipo  = "despesa"
                valor = val_debito
            else:
                continue  # Linha sem valor útil (ex: saldo anterior)

            categoria = _classificar_categoria(historico)

            transacoes.append({
                "data":               data_iso,
                "descricao":          historico[:200],
                "valor":              valor,
                "tipo":               tipo,
                "categoria_sugerida": categoria,
            })

        except Exception as exc:
            logger.debug("Linha ignorada no CSV: %s — %s", linha, exc)
            continue

    return transacoes


# ── Rotas ──────────────────────────────────────────────────────────────────────

@importacao_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    """Página inicial de importação — instruções e upload.
    
    Aceita POST para redirecionar corretamente quando o browser
    repete a requisição após erro de upload.
    """
    if request.method == "POST":
        return redirect(url_for("importacao.upload"))
    return render_template("importacao/index.html")


@importacao_bp.route("/upload", methods=["POST"])
@login_required
def upload():
    """
    Recebe o arquivo CSV, processa e exibe tela de revisão.

    O arquivo é lido em memória e os dados ficam temporariamente
    na sessão Flask para a etapa de confirmação.
    Nenhum dado é gravado no banco ainda.
    """
    arquivo = request.files.get("arquivo")

    if not arquivo or arquivo.filename == "":
        flash("Selecione um arquivo CSV.", "erro")
        return redirect(url_for("importacao.index"))

    if not arquivo.filename.lower().endswith(".csv"):
        flash("O arquivo deve ser .csv exportado do Bradesco.", "erro")
        return redirect(url_for("importacao.index"))

    try:
        # Tenta latin-1 primeiro (padrão Bradesco), depois utf-8
        conteudo_bytes = arquivo.read()
        try:
            conteudo = conteudo_bytes.decode("latin-1")
        except UnicodeDecodeError:
            conteudo = conteudo_bytes.decode("utf-8", errors="replace")

        transacoes = _parsear_csv_bradesco(conteudo)

        if not transacoes:
            flash(
                "Nenhuma transação encontrada. Verifique se é o formato correto do Bradesco.",
                "erro"
            )
            return redirect(url_for("importacao.index"))

        # Busca categorias do usuário para mostrar no select de revisão
        svc = get_services()
        categorias = svc.categorias_repo.listar_por_usuario(current_user.id)

        # Monta mapa nome→id para facilitar o template
        cat_map = {c["nome"]: c["id"] for c in categorias}

        # Enriquece com id da categoria sugerida
        for t in transacoes:
            t["categoria_id"] = cat_map.get(t["categoria_sugerida"]) or _id_fallback(categorias, t["tipo"])

        logger.info(
            "CSV Bradesco processado: user_id=%d, %d transações encontradas",
            current_user.id, len(transacoes)
        )

        return render_template(
            "importacao/revisao.html",
            transacoes=transacoes,
            categorias=categorias,
            total=len(transacoes),
            total_receitas=sum(t["valor"] for t in transacoes if t["tipo"] == "receita"),
            total_despesas=sum(t["valor"] for t in transacoes if t["tipo"] == "despesa"),
        )

    except Exception as exc:
        logger.error("Erro ao processar CSV de importação: %s", exc, exc_info=True)
        flash("Erro ao processar o arquivo. Verifique se é o formato correto.", "erro")
        return redirect(url_for("importacao.index"))


@importacao_bp.route("/confirmar", methods=["POST"])
@login_required
def confirmar():
    """
    Recebe os dados revisados e os persiste no banco.

    Cada transação vem do form com:
        transacoes[i][incluir], [data], [descricao], [valor], [tipo], [categoria_id]

    Só importa as que o usuário marcou como incluir=1.
    """
    svc = get_services()
    uid = current_user.id

    importadas = 0
    ignoradas  = 0
    erros      = 0

    # O form envia listas paralelas
    indices     = request.form.getlist("idx")
    incluirs    = request.form.getlist("incluir")
    datas       = request.form.getlist("data")
    descricoes  = request.form.getlist("descricao")
    valores_raw = request.form.getlist("valor")
    tipos       = request.form.getlist("tipo")
    cat_ids     = request.form.getlist("categoria_id")

    # Conjunto dos índices marcados como "incluir"
    incluir_set = set(incluirs)

    for i, idx in enumerate(indices):
        if idx not in incluir_set:
            ignoradas += 1
            continue

        try:
            valor = round(float(valores_raw[i].replace(",", ".")), 2)
            tipo  = tipos[i] if tipos[i] in ("receita", "despesa") else "despesa"
            cat_id = int(cat_ids[i]) if cat_ids[i] else None

            if valor <= 0:
                ignoradas += 1
                continue

            svc.transacoes.adicionar(
                descricao=descricoes[i][:200],
                valor=valor,
                tipo=tipo,
                categoria_id=cat_id,
                usuario_id=uid,
                data=datas[i],
            )
            importadas += 1

        except Exception as exc:
            logger.error("Erro ao importar transação idx=%s: %s", idx, exc)
            erros += 1

    if importadas > 0:
        flash(
            f"✓ {importadas} transação(ões) importada(s) com sucesso!"
            + (f" {ignoradas} ignorada(s)." if ignoradas else "")
            + (f" {erros} com erro." if erros else ""),
            "sucesso"
        )
    else:
        flash("Nenhuma transação foi importada.", "erro")

    logger.info(
        "Importação concluída: user_id=%d, importadas=%d, ignoradas=%d, erros=%d",
        uid, importadas, ignoradas, erros
    )

    return redirect(url_for("transacoes.todas"))


def _id_fallback(categorias: list[dict], tipo: str) -> int | None:
    """Retorna ID da primeira categoria do tipo como fallback."""
    for c in categorias:
        if c["tipo"] == tipo:
            return c["id"]
    return None
