#!/usr/bin/env bash
# Prepara todas as dependências locais (modelo do Ollama no host, Vosk e Piper)
# sem construir imagens nem subir containers. Idempotente.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT_DIR/scripts/ensure-ollama.sh"
bash "$ROOT_DIR/scripts/ensure-voice-assets.sh"

echo "Dependências locais prontas. Execute ./scripts/bootstrap.sh para subir o assistente."
