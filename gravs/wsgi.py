"""
wsgi.py — Entry point para PythonAnywhere.

Configure no painel do PythonAnywhere:
  Web > WSGI configuration file > cole este conteúdo

Substitua SEU_USUARIO pelo seu nome de usuário do PythonAnywhere.
"""

import sys
import os

# Caminho do projeto no PythonAnywhere
path = '/home/SEU_USUARIO/gravs'
if path not in sys.path:
    sys.path.insert(0, path)

# Variáveis de ambiente de produção
os.environ['FLASK_ENV'] = 'production'
os.environ['SECRET_KEY'] = 'troque-por-uma-chave-longa-e-aleatoria-aqui'
os.environ['DATABASE_URL'] = 'sqlite:////home/SEU_USUARIO/gravs/financas.db'

from app import create_app
application = create_app()
