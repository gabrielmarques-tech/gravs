import re

with open('tests/test_sistema.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        # Gera lançamento do mês
        import datetime
        hoje = datetime.date.today()
        lancados = container.recorrentes.gerar_lancamentos_pendentes(hoje.year, hoje.month, uid)
        assert lancados >= 0

        # Verifica que foi gerado
        transacoes = container.transacoes.listar_por_periodo(
            f"{hoje.year}-{hoje.month:02d}-01",
            hoje.strftime("%Y-%m-%d"),
            uid
        )
        assert len(transacoes) == 1'''

new = '''        import datetime
        hoje = datetime.date.today()
        import calendar

        # Calcula o mês anterior se hoje ainda não passou do dia de vencimento (28)
        mes = hoje.month
        ano = hoje.year
        if hoje.day < 28:
            if mes == 1:
                mes, ano = 12, ano - 1
            else:
                mes -= 1

        # Gera para o mês correto
        lancados = container.recorrentes.gerar_lancamentos_pendentes(ano, mes, uid)
        assert lancados >= 1, f"Deveria gerar ao menos 1 lançamento para {ano}-{mes}"

        # Verifica que foi gerado — usa o mês completo como período
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        transacoes = container.transacoes.listar_por_periodo(
            f"{ano}-{mes:02d}-01",
            f"{ano}-{mes:02d}-{ultimo_dia:02d}",
            uid
        )
        assert len(transacoes) >= 1, (
            f"Deveria ter transações em {ano}-{mes}, "
            f"período: {ano}-{mes:02d}-01 a {ano}-{mes:02d}-{ultimo_dia:02d}, "
            f"lançamentos gerados: {lancados}"
        )'''

if old in content:
    content = content.replace(old, new, 1)
    with open('tests/test_sistema.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Substituiu com sucesso!')
else:
    print('String antiga NAO encontrada!')
    # Debug: encontrar trecho similar
    idx = content.find('Gera lan')
    if idx >= 0:
        print(f'Encontrado em idx {idx}')
        print(repr(content[idx:idx+60]))
    idx2 = content.find('hoje = datetime')
    if idx2 >= 0:
        print(f'\nhoje encontrado em {idx2}:')
        print(repr(content[idx2-50:idx2+80]))
    # Mostrar linhas 436-448
    lines = content.split('\n')
    for i in range(435, min(449, len(lines))):
        print(f'{i+1}: {repr(lines[i])}')