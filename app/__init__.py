"""Pacote principal do backend do ManaPonte.

Os módulos deste pacote cuidam de persistência, autenticação, catálogo e
servidor HTTP. Manter o arquivo pequeno ajuda o Python a reconhecer a pasta
como pacote sem introduzir efeitos colaterais durante os imports.
"""

# Versão inicial do protótipo. O valor pode ser usado por ferramentas de
# diagnóstico sem precisar importar o servidor inteiro.
__version__ = "0.1.0"
