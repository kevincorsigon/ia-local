#!/usr/bin/env bash
# Garante que a API do Ollama no host responde e que o modelo configurado existe.
# Ollama não é um serviço do Compose: ele roda no host (Ubuntu) ou na distribuição/Windows (WSL).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo .env não encontrado. Copie .env.example para .env." >&2
  exit 1
fi

read_env() {
  local key="$1" fallback="$2" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  printf '%s' "${value:-$fallback}"
}

OLLAMA_HOST_URL="$(read_env OLLAMA_HOST_URL http://127.0.0.1:11434)"
OLLAMA_MODEL="$(read_env OLLAMA_MODEL qwen2.5:1.5b)"
OLLAMA_SERVE_HOST="$(read_env OLLAMA_SERVE_HOST 0.0.0.0)"
OLLAMA_MODELS_DIR="$(read_env OLLAMA_MODELS_DIR "")"
OLLAMA_TIMEOUT_SECONDS="${OLLAMA_TIMEOUT_SECONDS:-60}"
OLLAMA_LOG_FILE="$ROOT_DIR/data/ollama-host.log"

if ! command -v curl >/dev/null 2>&1; then
  echo "Dependência ausente: instale 'curl' para verificar a API do Ollama." >&2
  exit 1
fi

is_wsl() {
  grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null
}

has_systemd() {
  [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1
}

api_is_ready() {
  curl --silent --fail --max-time 3 "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1
}

models_from_api() {
  curl --silent --fail --max-time 5 "$OLLAMA_HOST_URL/api/tags" \
    | grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | sed 's/.*"\([^"]*\)"$/\1/'
}

start_ollama_service() {
  has_systemd || return 1
  systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service' || return 1
  if [[ "$EUID" -eq 0 ]]; then
    systemctl start ollama
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n systemctl start ollama
    return 0
  fi
  echo "ollama.service existe, mas iniciar o serviço exige senha de sudo (sudo -n falhou)." >&2
  return 1
}

start_ollama_background() {
  command -v ollama >/dev/null 2>&1 || return 1
  mkdir -p "$(dirname "$OLLAMA_LOG_FILE")"
  echo "Iniciando 'ollama serve' em segundo plano (bind $OLLAMA_SERVE_HOST); log em $OLLAMA_LOG_FILE"
  local launcher=(env OLLAMA_HOST="$OLLAMA_SERVE_HOST")
  if [[ -n "$OLLAMA_MODELS_DIR" ]]; then
    launcher+=(OLLAMA_MODELS="$OLLAMA_MODELS_DIR")
  fi
  if command -v setsid >/dev/null 2>&1; then
    launcher+=(setsid)
  fi
  launcher+=(nohup ollama serve)
  "${launcher[@]}" >>"$OLLAMA_LOG_FILE" 2>&1 &
  return 0
}

echo "Verificando Ollama em $OLLAMA_HOST_URL ..."
if ! api_is_ready; then
  if is_wsl; then
    echo "WSL detectado: o Ollama pode rodar nesta distribuição Linux ou no Windows."
    echo "Se ele estiver no Windows, inicie-o lá e ajuste OLLAMA_HOST_URL/OLLAMA_BASE_URL no .env."
  fi
  started=0
  if start_ollama_service; then
    echo "ollama.service iniciado via systemd."
    started=1
  else
    # No WSL é comum não haver systemd utilizável nem sudo sem senha; nesse caso
    # o próprio script sobe o 'ollama serve' na distribuição, como permite a spec.
    if { is_wsl || [[ "${OLLAMA_AUTOSTART:-0}" == "1" ]]; } && command -v ollama >/dev/null 2>&1; then
      start_ollama_background && started=1
    fi
  fi
  if [[ "$started" -eq 0 ]]; then
    echo "Não consegui iniciar o Ollama automaticamente neste host." >&2
    echo "Inicie-o manualmente (Ubuntu: 'sudo systemctl start ollama'; WSL: 'OLLAMA_HOST=$OLLAMA_SERVE_HOST ollama serve')" >&2
    echo "e confira OLLAMA_HOST_URL no .env." >&2
    exit 1
  fi
fi

deadline=$((SECONDS + OLLAMA_TIMEOUT_SECONDS))
until api_is_ready; do
  if (( SECONDS >= deadline )); then
    echo "Ollama não ficou disponível em $OLLAMA_HOST_URL após ${OLLAMA_TIMEOUT_SECONDS}s." >&2
    echo "Verifique o bind (OLLAMA_HOST), o firewall e, no WSL, se o serviço está na distribuição ou no Windows." >&2
    if [[ -f "$OLLAMA_LOG_FILE" ]]; then
      tail -n 20 "$OLLAMA_LOG_FILE" >&2
    fi
    exit 1
  fi
  sleep 2
done
echo "API do Ollama respondendo no host."

if ! command -v ollama >/dev/null 2>&1; then
  echo "O Ollama responde pela API, mas o comando 'ollama' não está instalado neste host." >&2
  exit 1
fi

installed_models="$(models_from_api || true)"
model_present=0
for candidate in "$OLLAMA_MODEL" "$OLLAMA_MODEL-latest" "$OLLAMA_MODEL:latest"; do
  if printf '%s\n' "$installed_models" | grep -Fxq "$candidate"; then
    model_present=1
    break
  fi
done

if [[ "$model_present" -eq 0 ]]; then
  echo "Baixando modelo $OLLAMA_MODEL (pode levar vários minutos)..."
  OLLAMA_HOST="$OLLAMA_HOST_URL" ollama pull "$OLLAMA_MODEL"
else
  echo "Modelo $OLLAMA_MODEL já está instalado."
fi
