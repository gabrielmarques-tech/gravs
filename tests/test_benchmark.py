"""
test_benchmark.py - Benchmark de desempenho das funções contábeis.

Mede:
  - saldo_conta()          (ContabilService.saldo_conta)
  - listar_partidas_dobradas()  (ContabilService.listar_partidas_dobradas_por_periodo)
  - exportar_excel()       (geração de planilha .xlsx com openpyxl)

Cenários:
  10.000 lançamentos
  50.000 lançamentos
  100.000 lançamentos

Mede ANTES (primeira chamada, sem cache) e DEPOIS (segunda chamada,
com possibilidade de cache de página/buffer do SQLite).

Filosofia:
  "Se não medirmos, estamos apenas supondo."
  - Medir para decidir, não para decorar.
"""

import os
import time
import io
import sqlite3
import uuid as uuid_lib
import tempfile
from datetime import datetime, timedelta
from dataclasses import dataclass

# ── Importações do projeto ──────────────────────────────────────────────────
from database.manager import DatabaseManager
from database.repositories import (
    PlanoContasRepository,
    LancamentoContabilRepository,
    TransacaoRepository,
)
from services.contabil_service import ContabilService


# ── Configurações ───────────────────────────────────────────────────────────

QTD_LANCAMENTOS = [10_000, 50_000, 100_000]
USUARIO_ID = 1
DEBITO_ID = 3   # Caixa (id=3)
CREDITO_ID = 9  # Vendas (id=9)

# Contas contábeis padrão que serão criadas
CONTAS_PADRAO = [
    ("1", "Ativo",          "ativo",  "devedora", 1, "1 - Ativo"),
    ("1.1", "Disponível",   "ativo",  "devedora", 2, "1 - Ativo"),
    ("1.1.1", "Caixa",      "ativo",  "devedora", 3, "1.1 - Disponível"),
    ("2", "Passivo",        "passivo", "credora",  1, "2 - Passivo"),
    ("2.1", "Circulante",   "passivo", "credora",  2, "2 - Passivo"),
    ("2.1.1", "Fornecedores", "passivo", "credora", 3, "2.1 - Circulante"),
    ("3", "Receitas",       "receita", "credora",  1, "3 - Receitas"),
    ("3.1", "Operacionais", "receita", "credora",  2, "3 - Receitas"),
    ("3.1.1", "Vendas",     "receita", "credora",  3, "3.1 - Operacionais"),
    ("4", "Despesas",       "despesa", "devedora", 1, "4 - Despesas"),
    ("4.1", "Operacionais", "despesa", "devedora", 2, "4 - Despesas"),
    ("4.1.1", "Salários",   "despesa", "devedora", 3, "4.1 - Operacionais"),
]


@dataclass
class ResultadoBenchmark:
    """Resultado de uma medição individual."""
    nome_teste: str
    qtd_lancamentos: int
    tempo_antes: float    # segundos
    tempo_depois: float   # segundos


def criar_banco_com_lancamentos(qtd: int) -> DatabaseManager:
    """Cria banco em arquivo temporário e insere N lançamentos contábeis."""
    # Usa arquivo temporário (mais rápido que :memory: compartilhado)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    db = DatabaseManager(db_path)
    db.init_schema()

    # Cria usuário
    with db.get_write_conn() as conn:
        conn.execute(
            "INSERT INTO usuarios (id, email, senha_hash, nome) VALUES (?, ?, ?, ?)",
            (USUARIO_ID, "benchmark@teste.com", "hash_benchmark", "Usuário Benchmark")
        )

    # Cria repositórios
    plano_repo = PlanoContasRepository(db)
    lancamento_repo = LancamentoContabilRepository(db)

    # Cria contas contábeis
    for codigo, nome, tipo, natureza, nivel, _ in CONTAS_PADRAO:
        conta_pai_id = None
        if "." in codigo:
            pai_codigo = codigo.rsplit(".", 1)[0]
            conta_pai = plano_repo.buscar_por_codigo(pai_codigo, USUARIO_ID)
            if conta_pai:
                conta_pai_id = conta_pai.id

        plano_repo.criar(
            usuario_id=USUARIO_ID,
            codigo=codigo,
            nome=nome,
            tipo=tipo,
            natureza=natureza,
            nivel=nivel,
            aceita_lancamentos=True,
            conta_pai_id=conta_pai_id,
        )

    # Insere lançamentos em lote usando conexão direta (mais rápido)
    data_base = datetime(2025, 1, 1)
    batch_size = 5_000
    historicos = [
        "Venda de produtos", "Prestação de serviços", "Recebimento de duplicatas",
        "Pagamento de fornecedores", "Salários do mês", "Aluguel",
        "Comissões", "Material de escritório", "Consultoria",
        "Manutenção", "Impostos", "Transporte"
    ]

    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("PRAGMA journal_mode = WAL")
    raw_conn.execute("PRAGMA synchronous = OFF")
    raw_conn.execute("PRAGMA foreign_keys = ON")
    raw_conn.execute("BEGIN")

    for i in range(qtd):
        dia = (data_base + timedelta(days=i % 365)).strftime("%Y-%m-%d")
        valor = round((i % 1000) + 100.50, 2)
        historico = historicos[i % len(historicos)]
        uuid_str = str(uuid_lib.uuid4())
        debito = DEBITO_ID if i % 2 == 0 else 6  # 6 = Fornecedores
        credito = 9 if i % 2 == 0 else DEBITO_ID  # 9 = Vendas

        raw_conn.execute(
            """INSERT INTO lancamentos_contabeis
               (uuid, usuario_id, data, historico, valor, debito_id, credito_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uuid_str, USUARIO_ID, dia, historico, valor, debito, credito),
        )

        if (i + 1) % batch_size == 0:
            raw_conn.commit()
            raw_conn.execute("BEGIN")

    raw_conn.commit()
    raw_conn.close()

    # Verifica quantidade
    with db.get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM lancamentos_contabeis WHERE usuario_id = ?",
            (USUARIO_ID,)
        ).fetchone()[0]
    print(f"    Registros confirmados: {count:,}")

    return db


def medir_tempo(funcao, *args, rotulo: str = "", **kwargs) -> tuple[float, any]:
    """Executa função e retorna (tempo_segundos, resultado)."""
    inicio = time.perf_counter()
    resultado = funcao(*args, **kwargs)
    fim = time.perf_counter()
    duracao = fim - inicio
    print(f"  {rotulo}: {duracao:.4f}s")
    return duracao, resultado


def executar_benchmark(qtd: int) -> list[ResultadoBenchmark]:
    """Executa todas as medições para uma quantidade de lançamentos."""
    resultados = []
    print(f"\n{'='*65}")
    print(f"  BENCHMARK - {qtd:,} lançamentos")
    print(f"{'='*65}")

    print(f"\nCriando banco com {qtd:,} lançamentos...")
    t0 = time.perf_counter()
    db = criar_banco_com_lancamentos(qtd)
    t_criacao = time.perf_counter() - t0
    print(f"  Banco criado em {t_criacao:.4f}s")

    plano_repo = PlanoContasRepository(db)
    lancamento_repo = LancamentoContabilRepository(db)
    transacao_repo = TransacaoRepository(db)
    service = ContabilService(db, plano_repo, lancamento_repo, transacao_repo)

    # ── 1. saldo_conta() ──────────────────────────────────────────────────────
    print(f"\n>> saldo_conta()")

    print(f"  ANTES (frio):")
    tempo_frio, resultado = medir_tempo(
        service.saldo_conta, DEBITO_ID, USUARIO_ID, data_ate="2025-12-31",
        rotulo="   saldo_conta (Caixa até 2025-12-31)"
    )
    assert resultado[0], f"saldo_conta falhou: {resultado[1]}"
    print(f"    Saldo calculado: R$ {resultado[1]:,.2f}")

    print(f"  DEPOIS (quente):")
    tempo_quente, resultado = medir_tempo(
        service.saldo_conta, DEBITO_ID, USUARIO_ID, data_ate="2025-12-31",
        rotulo="   saldo_conta (Caixa até 2025-12-31)"
    )
    assert resultado[0], f"saldo_conta quente falhou: {resultado[1]}"
    print(f"    Saldo calculado: R$ {resultado[1]:,.2f}")

    resultados.append(ResultadoBenchmark(
        nome_teste="saldo_conta()", qtd_lancamentos=qtd,
        tempo_antes=tempo_frio, tempo_depois=tempo_quente,
    ))

    # ── 2. listar_partidas_dobradas() ──────────────────────────────────────────
    print(f"\n>> listar_partidas_dobradas() [COM JOIN ÚNICO — N+1 ELIMINADO]")

    print(f"  ANTES (frio):")
    tempo_frio, lancamentos = medir_tempo(
        service.listar_partidas_dobradas_por_periodo,
        USUARIO_ID, "2025-01-01", "2025-12-31", limit=qtd,
        rotulo="   listar_partidas (2025 inteiro, JOIN)"
    )
    print(f"    Retornou {len(lancamentos)} registros")

    print(f"  DEPOIS (quente):")
    tempo_quente, lancamentos = medir_tempo(
        service.listar_partidas_dobradas_por_periodo,
        USUARIO_ID, "2025-01-01", "2025-12-31", limit=qtd,
        rotulo="   listar_partidas (2025 inteiro, JOIN)"
    )
    print(f"    Retornou {len(lancamentos)} registros")

    resultados.append(ResultadoBenchmark(
        nome_teste="listar_partidas_dobradas() [JOIN]", qtd_lancamentos=qtd,
        tempo_antes=tempo_frio, tempo_depois=tempo_quente,
    ))

    # ── 3. exportar_excel() ──────────────────────────────────────────────────
    print(f"\n>> exportar_excel() - geração manual de planilha openpyxl")
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter

        cabecalhos = ["Data", "Descrição", "Tipo", "Valor (R$)", "Conta Débito", "Conta Crédito", "Categoria"]
        larguras = [12, 35, 12, 16, 25, 25, 20]

        def gerar_planilha(lancs) -> io.BytesIO:
            """Gera planilha Excel similar à rota exportar_partida_dobrada()."""
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Partida Dobrada"

            ws.merge_cells("A1:G1")
            ws["A1"].value = f"Gravs - Lançamentos em Partida Dobrada | 2025-01-01 a 2025-12-31"
            ws["A1"].font = Font(bold=True, size=13, color="2D1B69")
            ws["A1"].alignment = Alignment(horizontal="center")
            ws["A1"].fill = PatternFill("solid", fgColor="F0EBFF")

            for col, cab in enumerate(cabecalhos, 1):
                cell = ws.cell(row=3, column=col, value=cab)
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="2D1B69")
                cell.alignment = Alignment(horizontal="center")

            for linha, l in enumerate(lancs, 4):
                ws.cell(row=linha, column=1, value=l.data)
                ws.cell(row=linha, column=2, value=l.historico)
                ws.cell(row=linha, column=3, value="Receita" if l.valor > 500 else "Despesa")
                val_cell = ws.cell(row=linha, column=4, value=l.valor)
                val_cell.number_format = 'R$ #,##0.00'
                ws.cell(row=linha, column=5, value=l.conta_debito_nome)
                ws.cell(row=linha, column=6, value=l.conta_credito_nome)
                ws.cell(row=linha, column=7, value="Benchmark")

            for col, larg in enumerate(larguras, 1):
                ws.column_dimensions[get_column_letter(col)].width = larg

            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            return buffer

        print(f"  ANTES (frio, gerando Excel):")
        t_frio = time.perf_counter()
        buffer = gerar_planilha(lancamentos)
        tempo_excel_frio = time.perf_counter() - t_frio
        print(f"  Excel gerado - {len(lancamentos)} linhas em {tempo_excel_frio:.4f}s")
        print(f"  Tamanho do arquivo: {len(buffer.getvalue()) / 1024:.1f} KB")

        print(f"\n  DEPOIS (quente, gerando Excel novamente):")
        t_inicio = time.perf_counter()
        buffer2 = gerar_planilha(lancamentos)
        tempo_excel_quente = time.perf_counter() - t_inicio
        print(f"  Excel gerado - {len(lancamentos)} linhas em {tempo_excel_quente:.4f}s")
        print(f"  Tamanho do arquivo: {len(buffer2.getvalue()) / 1024:.1f} KB")

        resultados.append(ResultadoBenchmark(
            nome_teste="exportar_excel()", qtd_lancamentos=qtd,
            tempo_antes=tempo_excel_frio, tempo_depois=tempo_excel_quente,
        ))

    except ImportError:
        print("  openpyxl não instalado - pulando exportar_excel()")
        resultados.append(ResultadoBenchmark(
            nome_teste="exportar_excel()", qtd_lancamentos=qtd,
            tempo_antes=0.0, tempo_depois=0.0,
        ))
    except Exception as exc:
        print(f"  Erro ao gerar Excel: {exc}")
        import traceback
        traceback.print_exc()
        resultados.append(ResultadoBenchmark(
            nome_teste="exportar_excel()", qtd_lancamentos=qtd,
            tempo_antes=0.0, tempo_depois=0.0,
        ))

    # Limpa arquivo temporário
    if hasattr(db, 'db_path') and os.path.exists(db.db_path):
        try:
            os.remove(db.db_path)
        except (OSError, PermissionError):
            pass

    return resultados


def exibir_tabela_resultados(todos_resultados: list[list[ResultadoBenchmark]]):
    """Exibe tabela comparativa com todos os resultados."""
    print(f"\n{'='*80}")
    print(f"  RESUMO - COMPARATIVO DE DESEMPENHO")
    print(f"{'='*80}")

    cabecalho = f"{'Função':<35} {'Lançamentos':<14} {'Antes (s)':<12} {'Depois (s)':<12}"
    print(f"\n{cabecalho}")
    print(f"{'-'*73}")

    for resultados_qtd in todos_resultados:
        for r in resultados_qtd:
            linha = f"{r.nome_teste:<35} {r.qtd_lancamentos:>10,}     {r.tempo_antes:<10.4f}  {r.tempo_depois:<10.4f}"
            print(linha)

    print(f"\nLegenda:")
    print(f"  Antes (s)  = Primeira execução (frio: sem cache, sem buffer)")
    print(f"  Depois (s) = Segunda execução (quente: com cache de página SQLite)")


def main():
    """Ponto de entrada do benchmark."""
    print(f"{'='*65}")
    print(f"  BENCHMARK - Sistema Contábil (Partida Dobrada)")
    print(f"  Medindo: saldo_conta | listar_partidas_dobradas | exportar_excel")
    print(f"  Volumes: 10.000 | 50.000 | 100.000 lançamentos")
    print(f"  'Se não medirmos, estamos apenas supondo.'")
    print(f"{'='*65}")

    todos_resultados = []
    for qtd in QTD_LANCAMENTOS:
        resultados = executar_benchmark(qtd)
        todos_resultados.append(resultados)

    exibir_tabela_resultados(todos_resultados)


if __name__ == "__main__":
    main()