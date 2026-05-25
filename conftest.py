"""
tests/conftest.py — Configuração global do pytest.

Por que este arquivo?
-----------------------
pytest descobre conftest.py automaticamente.
Aqui configuramos o sys.path para que `import financeiro`
funcione sem instalar o pacote (útil em CI/CD e PythonAnywhere).
"""

import sys
import os

# Garante que o diretório raiz do projeto está no path de importação,
# permitindo `from financeiro import Banco` nos testes.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))