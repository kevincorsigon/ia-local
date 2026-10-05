#!/usr/bin/env bash
# Tuning do Ollama para NUC sem GPU (CPU-only, pouca RAM).
# Aplica um override do systemd com as variáveis que mais importam em CPU:
#   OLLAMA_FLASH_ATTENTION=1  -> menos memória/tempo (recomendado em CPU)
#   OLLAMA_KV_CACHE_TYPE=q8_0 -> metade da RAM do KV-cache, perda mínima
#   OLLAMA_CONTEXT_LENGTH=2048 -> default curto; o backend ainda manda num_ctx por requisição
#   OLLAMA_NUM_PARALLEL=1 / MAX_LOADED_MODELS=1 -> 1 requisição por vez, sem dividir a CPU
#   OLLAMA_KEEP_ALIVE=30m -> mantém o qwen carregado entre mensagens
#   OLLAMA_HOST=0.0.0.0:11434 -> containers alcançam via host.docker.internal
#
# Uso (NO NUC, não no Windows):
#   sudo ./scripts/tune-ollama-nuc.sh
#   ollama show qwen2.5:1.5b   # confere o modelo
#   sudo systemctl restart ollama && ollama ps
set -euo pipefail

OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/override.conf"

if [[ $EUID -ne 0 ]]; then
  echo "Rode com sudo: sudo ./scripts/tune-ollama-nuc.sh" >&2
  exit 1
fi

mkdir -p "$OVERRIDE_DIR"
printf '%s\n' '[Service]' \
  'Environment="OLLAMA_HOST=0.0.0.0:11434"' \
  'Environment="OLLAMA_KEEP_ALIVE=30m"' \
  'Environment="OLLAMA_CONTEXT_LENGTH=2048"' \
  'Environment="OLLAMA_FLASH_ATTENTION=1"' \
  'Environment="OLLAMA_KV_CACHE_TYPE=q8_0"' \
  'Environment="OLLAMA_NUM_PARALLEL=1"' \
  'Environment="OLLAMA_MAX_LOADED_MODELS=1"' \
  'Environment="OLLAMA_MAX_QUEUE=1"' \
  > "$OVERRIDE_FILE"
systemctl daemon-reload
systemctl restart ollama
sleep 2
systemctl is-active --quiet ollama && echo "Ollama ativo com tuning NUC." || {
  echo "Ollama não subiu; veja: journalctl -u ollama -n 50" >&2
  exit 1
}
echo "Verifique com: ollama ps && curl -s http://127.0.0.1:11434/api/tags | head -c 300"

