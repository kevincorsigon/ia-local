#!/usr/bin/env bash
# Tuning do Ollama para NUC sem GPU (CPU-only, pouca RAM).
# Lê tudo do arquivo informado ou de ASSISTANT_ENV_FILE (padrão: .env).
# Uso (NO NUC, não no Windows):
#   sudo ./scripts/tune-ollama-nuc.sh .env.nuc
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-${ASSISTANT_ENV_FILE:-$ROOT_DIR/.env}}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$ROOT_DIR/$ENV_FILE"
fi
OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/override.conf"

read_env() {
  local key="$1" fallback="$2" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" 2>/dev/null | tail -n 1)"
  printf '%s' "${value:-$fallback}"
}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo de ambiente não encontrado: $ENV_FILE" >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "Rode com sudo: sudo ./scripts/tune-ollama-nuc.sh" >&2
  exit 1
fi

PORT="$(read_env OLLAMA_PORT 11434)"
KEEP_ALIVE="$(read_env OLLAMA_KEEP_ALIVE 30m)"
CTX="$(read_env OLLAMA_CONTEXT_LENGTH 2048)"
FLASH="$(read_env OLLAMA_FLASH_ATTENTION 1)"
KV="$(read_env OLLAMA_KV_CACHE_TYPE q8_0)"
PARALLEL="$(read_env OLLAMA_NUM_PARALLEL 1)"
MODELS="$(read_env OLLAMA_MAX_LOADED_MODELS 1)"
QUEUE="$(read_env OLLAMA_MAX_QUEUE 1)"

mkdir -p "$OVERRIDE_DIR"
{
  printf '%s\n' '[Service]'
  printf '%s\n' "Environment=\"OLLAMA_HOST=0.0.0.0:${PORT}\""
  printf '%s\n' "Environment=\"OLLAMA_KEEP_ALIVE=${KEEP_ALIVE}\""
  printf '%s\n' "Environment=\"OLLAMA_CONTEXT_LENGTH=${CTX}\""
  printf '%s\n' "Environment=\"OLLAMA_FLASH_ATTENTION=${FLASH}\""
  if [[ -n "$KV" ]]; then
    printf '%s\n' "Environment=\"OLLAMA_KV_CACHE_TYPE=${KV}\""
  fi
  printf '%s\n' "Environment=\"OLLAMA_NUM_PARALLEL=${PARALLEL}\""
  printf '%s\n' "Environment=\"OLLAMA_MAX_LOADED_MODELS=${MODELS}\""
  printf '%s\n' "Environment=\"OLLAMA_MAX_QUEUE=${QUEUE}\""
} > "$OVERRIDE_FILE"
echo "Override gravado em $OVERRIDE_FILE (de $(basename "$ENV_FILE"): ctx=$CTX flash=$FLASH kv=${KV:-default} parallel=$PARALLEL)."
systemctl daemon-reload
systemctl restart ollama
sleep 2
systemctl is-active --quiet ollama && echo "Ollama ativo com tuning NUC." || {
  echo "Ollama não subiu; veja: journalctl -u ollama -n 50" >&2
  exit 1
}
echo "Verifique com: ollama ps && curl -s http://127.0.0.1:11434/api/tags | head -c 300"

