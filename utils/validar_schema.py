import tempfile, os, sys

fd, path = tempfile.mkstemp(suffix=".db")
os.close(fd)

try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from services.container import ServiceContainer
    sc = ServiceContainer(db_path=path)

    import sqlite3
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row

    # Cria o schema
    sc.db.init_schema()

    def show_table_info(conn, table_name, label):
        """Mostra info das colunas de uma tabela."""
        print("\n" + "=" * 70)
        print(f"{label}: PRAGMA table_info({table_name})")
        print("=" * 70)
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if not rows:
            print("  [Tabela vazia ou inexistente]")
            return
        # PRAGMA table_info retorna: cid, name, type, notnull, dflt_value, pk
        for r in rows:
            print(f"  col: {r[0]:<3} nome: {r[1]:<25} type: {r[2]:<15} notnull: {r[3]:<3} default: {str(r[4]):<15} pk: {r[5]}")

    def show_foreign_keys(conn, table_name, label):
        """Mostra FKs de uma tabela."""
        print("\n" + "=" * 70)
        print(f"{label}: PRAGMA foreign_key_list({table_name})")
        print("=" * 70)
        rows = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        if not rows:
            print("  NENHUMA FK encontrada!")
            return
        for r in rows:
            print(f"  coluna local: {r[3]:<20} -> {r[2]}({r[4]})  [on_delete: {r[5]:<10} on_update: {r[6]:<10}]")

    # ── 1 e 2: plano_contas ──
    show_table_info(c, "plano_contas", "1")
    # ── 3 e 4: lancamentos_contabeis ──
    show_table_info(c, "lancamentos_contabeis", "2")
    # ── 5: FK plano_contas ──
    show_foreign_keys(c, "plano_contas", "3")
    # ── 6: FK lancamentos_contabeis ──
    show_foreign_keys(c, "lancamentos_contabeis", "4")

    # ── 7. Triggers ──
    print("\n" + "=" * 70)
    print("5. TRIGGERS")
    print("=" * 70)
    rows = c.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'").fetchall()
    if not rows:
        print("  NENHUM trigger encontrado!")
    for r in rows:
        print(f"  Trigger: {r[0]}")
        for line in (r[1] or "").split("\n"):
            print(f"    {line.strip()}")
        print()

    # ── 8. Todos os índices ──
    print("=" * 70)
    print("6. TODOS OS ÍNDICES")
    print("=" * 70)
    rows = c.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_auto%' ORDER BY tbl_name, name").fetchall()
    if not rows:
        print("  NENHUM índice encontrado!")
    print(f"{'Índice':<45} {'Tabela':<20}")
    print("-" * 65)
    for r in rows:
        print(f"{r[0]:<45} {r[1]:<20}")

    # ── 9. CHECK constraints ──
    print("\n" + "=" * 70)
    print("7. CHECK CONSTRAINTS")
    print("=" * 70)
    tables = ['plano_contas', 'lancamentos_contabeis', 'transferencias', 'usuarios', 'recorrentes', 'transacoes']
    for tbl in tables:
        row = c.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{tbl}'").fetchone()
        if row:
            checks = [line.strip() for line in row[0].split('\n') if 'CHECK' in line.upper()]
            if checks:
                print(f"\n  {tbl}:")
                for chk in checks:
                    print(f"    {chk}")

    # ── 10. Teste do trigger ──
    print("\n" + "=" * 70)
    print("8. TESTE DO TRIGGER (auto-referencia)")
    print("=" * 70)
    try:
        cur = c.execute("INSERT INTO usuarios (email, senha_hash, nome) VALUES ('t@t.com', 'hash', 'T')")
        uid = cur.lastrowid
        cur = c.execute("INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, '1', 'Ativo', 'ativo', 'devedora', 1, 1)", (uid,))
        pc_id = cur.lastrowid
        try:
            c.execute("UPDATE plano_contas SET conta_pai_id=? WHERE id=?", (pc_id, pc_id))
            print("  ERRO: Trigger NAO bloqueou auto-referencia!")
        except Exception as e:
            if "Auto-referencia" in str(e) or "auto-referencia" in str(e).lower():
                print(f"  OK: Trigger funcionou: {str(e)[:80]}")
            else:
                print(f"  Outro erro: {str(e)[:120]}")
        c.rollback()
    except Exception as e:
        print(f"  Erro no setup: {str(e)[:120]}")
        c.rollback()

    # ── 11. Teste CHECK ──
    print("\n" + "=" * 70)
    print("9. TESTE CHECK (debito_id != credito_id)")
    print("=" * 70)
    try:
        cur = c.execute("INSERT INTO usuarios (email, senha_hash, nome) VALUES ('t2@t.com', 'hash', 'T2')")
        uid = cur.lastrowid
        cur = c.execute("INSERT INTO plano_contas (usuario_id, codigo, nome, tipo, natureza, nivel, aceita_lancamentos) VALUES (?, '1.1', 'Caixa', 'ativo', 'devedora', 2, 1)", (uid,))
        cc_id = cur.lastrowid
        try:
            c.execute("INSERT INTO lancamentos_contabeis (uuid, usuario_id, data, historico, valor, debito_id, credito_id) VALUES ('test-uuid', ?, '2026-01-01', 'Teste', 100.0, ?, ?)", (uid, cc_id, cc_id))
            c.rollback()
            print("  ERRO: CHECK nao bloqueou debito == credito!")
        except Exception as e:
            print(f"  OK: CHECK funcionou: {str(e)[:120]}")
        c.rollback()
    except Exception as e:
        print(f"  Erro no setup: {str(e)[:120]}")
        c.rollback()

    c.close()

finally:
    try:
        os.unlink(path)
    except OSError:
        pass

