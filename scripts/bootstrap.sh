#!/usr/bin/env bash
# Ponto de entrada oficial: prepara as dependências locais, constrói as imagens
# e sobe o assistente. Idempotente. Substitui o uso direto de 'docker compose up'.
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

OLLAMA_BASE_URL="$(read_env OLLAMA_BASE_URL http://host.docker.internal:11434)"
WEB_PORT="$(read_env WEB_PORT 8080)"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.yaml")

echo "Preparando modelo do Ollama e recursos de voz..."
bash "$ROOT_DIR/scripts/pull-models.sh"

echo "Validando configuração do Compose..."
"${COMPOSE[@]}" config --quiet

echo "Construindo as imagens..."
"${COMPOSE[@]}" --profile core --profile voice build

echo "Validando a rota container -> Ollama do host ($OLLAMA_BASE_URL)..."
if ! "${COMPOSE[@]}" --profile core run --rm --no-deps -T backend \
  python -c "import os,urllib.request; urllib.request.urlopen(os.environ['OLLAMA_BASE_URL'].rstrip('/') + '/api/tags', timeout=5)" >/dev/null 2>&1; then
  echo "Os containers não alcançaram o Ollama em $OLLAMA_BASE_URL." >&2
  echo "O Ollama precisa escutar numa interface alcançável pela rede Docker (OLLAMA_SERVE_HOST)," >&2
  echo "e a porta 11434 não pode estar bloqueada por firewall." >&2
  exit 1
fi
echo "Rota container -> host confirmada."

echo "Iniciando os containers..."
"${COMPOSE[@]}" --profile core --profile voice up -d

echo "Esperando o backend responder..."
deadline=$((SECONDS + 120))
until "${COMPOSE[@]}" exec -T backend python -c "import json,pathlib,urllib.request; h=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); urllib.request.urlopen('http://piper:5000/info', timeout=5); assert h['ollama']=='ok' and h['model_available'] is True and pathlib.Path('/models/vosk-model-small-pt-0.3').is_dir()" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    "${COMPOSE[@]}" --profile core --profile voice ps
    echo "Os containers iniciaram, mas o backend não respondeu em 120 segundos." >&2
    exit 1
  fi
  sleep 3
done

echo ""
echo "Assistente iniciado: http://localhost:$WEB_PORT"
echo "Health do backend:   http://localhost:$WEB_PORT/health"
echo "Validação completa:  ./scripts/healthcheck.sh"
echo "Parar tudo:          docker compose --env-file .env --profile core --profile voice down"
