#!/usr/bin/env bash

# Faz o shell parar no primeiro erro, em variáveis não definidas e em falhas
# dentro de pipelines. Isso evita iniciar um servidor parcialmente configurado.
set -euo pipefail

# Descobre o projeto a partir da localização deste script, não do diretório
# atual de quem o executou.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# O seed é idempotente: garante os fixtures sem apagar um catálogo importado.
python3 -m app.seed

# Mostra ao desenvolvedor o endereço efetivo antes de entregar o processo ao
# módulo HTTP. As variáveis podem trocar host e porta sem editar o script.
echo "Abrindo ManaPonte em http://${MANAPONTE_HOST:-127.0.0.1}:${MANAPONTE_PORT:-8000}"
exec python3 -m app.server
