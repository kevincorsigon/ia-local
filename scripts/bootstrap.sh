#!/usr/bin/env bash
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
OLLAMA_TIMEOUT_SECONDS="${OLLAMA_TIMEOUT_SECONDS:-45}"

api_is_ready() {
  curl --silent --fail --max-time 2 "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1
}

echo "Verificando Ollama em $OLLAMA_HOST_URL ..."
if ! api_is_ready; then
  if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    echo "Ollama não respondeu; tentando iniciar ollama.service..."
    if [[ "$EUID" -eq 0 ]]; then
      systemctl start ollama
    elif command -v sudo >/dev/null 2>&1; then
      sudo systemctl start ollama
    else
      echo "Não consigo iniciar ollama.service sem systemctl ou sudo." >&2
      exit 1
    fi
  else
    echo "Ollama indisponível e este host não possui systemd. Inicie-o manualmente e confira OLLAMA_HOST_URL." >&2
    exit 1
  fi
fi

deadline=$((SECONDS + OLLAMA_TIMEOUT_SECONDS))
until api_is_ready; do
  if (( SECONDS >= deadline )); then
    echo "Ollama não ficou disponível em $OLLAMA_HOST_URL após ${OLLAMA_TIMEOUT_SECONDS}s." >&2
    exit 1
  fi
  sleep 2
done

if ! command -v ollama >/dev/null 2>&1; then
  echo "O Ollama responde pela API, mas o comando 'ollama' não está instalado neste host." >&2
  exit 1
fi

installed_models="$(OLLAMA_HOST="$OLLAMA_HOST_URL" ollama list)"
if ! printf '%s\n' "$installed_models" | awk 'NR > 1 { print $1 }' | grep -Fxq "$OLLAMA_MODEL"; then
  echo "Baixando modelo $OLLAMA_MODEL..."
  OLLAMA_HOST="$OLLAMA_HOST_URL" ollama pull "$OLLAMA_MODEL"
else
  echo "Modelo $OLLAMA_MODEL já está instalado."
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.yaml")
echo "Validando configuração do Compose..."
"${COMPOSE[@]}" config --quiet
echo "Construindo e iniciando os containers..."
"${COMPOSE[@]}" --profile core up -d --build

WEB_PORT="$(read_env WEB_PORT 8080)"
echo "Esperando o backend responder..."
deadline=$((SECONDS + 60))
until "${COMPOSE[@]}" exec -T backend python -c "import json,urllib.request; h=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); assert h['ollama']=='ok' and h['model_available'] is True" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    "${COMPOSE[@]}" ps
    echo "Os containers iniciaram, mas o backend não respondeu em 60 segundos." >&2
    exit 1
  fi
  sleep 2
done
echo "Assistente iniciado: http://localhost:$WEB_PORT"
