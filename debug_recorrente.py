# Debug para testar gerar_lancamentos_pendentes

import sys
sys.path.insert(0, '.')
import datetime as dt

from services.container import ServiceContainer

# ServiceContainer já inicializa o banco no construtor
container = ServiceContainer()

# Register user
uid, _ = container.auth.registrar('debug@test.com', 'senha123', 'Debug')

# Get a category
cats = [c for c in container.categorias_repo.listar_por_usuario(uid) if c['tipo'] == 'despesa']
print(f'Categories: {len(cats)}')
cat_id = cats[0]['id']
print(f'Using cat_id: {cat_id}')

# Create recurring
uuid_rec, erros = container.recorrentes.adicionar(
    descricao='Aluguel',
    valor=1200.0,
    tipo='despesa',
    categoria_id=cat_id,
    dia_vencimento=28,
    usuario_id=uid,
)
print(f'Recurring UUID: {uuid_rec}, errors: {erros}')

if erros:
    print(f'Error creating recurring: {erros}')
    sys.exit(1)

# Generate
hoje = dt.date.today()
print(f'Today: {hoje}')

mes = hoje.month
ano = hoje.year
if hoje.day < 28:
    if mes == 1:
        mes, ano = 12, ano - 1
    else:
        mes -= 1

print(f'Using month: {ano}-{mes}')

lancados = container.recorrentes.gerar_lancamentos_pendentes(ano, mes, uid)
print(f'Generated: {lancados}')

# List transactions
from datetime import date as d
d1 = d(ano, mes, 1)
if mes == 12:
    d2 = d(ano + 1, 1, 1)
else:
    d2 = d(ano, mes + 1, 1)

print(f'Period: {d1.isoformat()} to {d2.isoformat()}')

trans = container.transacoes.listar_por_periodo(d1.isoformat(), d2.isoformat(), uid)
print(f'Transactions: {len(trans)}')
for t in trans:
    print(f'  - {t["descricao"]}: {t["valor"]} on {t["data"]}, deletado={t.get("deletado", 0)}')

# Also query directly from database
with container.db.get_conn() as conn:
    rows = conn.execute('SELECT id, descricao, valor, data, deletado FROM transacoes WHERE usuario_id=?', (uid,)).fetchall()
    print(f'All DB rows: {len(rows)}')
    for r in rows:
        print(f'  - {r}')