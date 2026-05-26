"""
wsgi.py — Entry point para PythonAnywhere.
"""

import sys
import os

path = '/home/Gravs/gravs'
if path not in sys.path:
    sys.path.insert(0, path)

env_path = os.path.join(path, '.env.secret')
if os.path.exists(env_path):
    with open(env_path) as f:
        for linha in f:
            linha = linha.strip()
            if linha and not linha.startswith('#') and '=' in linha:
                chave, valor = linha.split('=', 1)
                os.environ[chave.strip()] = valor.strip()

os.environ['FLASK_ENV'] = 'production'

from app import create_app
application = create_app()