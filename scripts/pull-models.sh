#!/usr/bin/env bash
# Prepara as dependências locais sem construir imagens nem subir containers: escolhe o
# Ollama do Windows (GPU) ou o do WSL (CPU), garante o modelo e prepara o Vosk.
# O Kokoro não baixa nada: a imagem CPU já traz o modelo v1_0 e as vozes.
# Idempotente.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT_DIR/scripts/ensure-ollama.sh"
bash "$ROOT_DIR/scripts/ensure-voice-assets.sh"

echo "Dependências locais prontas. Execute ./scripts/bootstrap.sh para subir o assistente."
