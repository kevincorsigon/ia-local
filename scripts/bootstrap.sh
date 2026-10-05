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

# Um .env editado no Windows chega com CRLF (fim de linha \r\n). No Linux o "\r" fica dentro do
# valor — nome do modelo, porta, caminho do store de modelos — e quebra o script silenciosamente.
# Normaliza antes de qualquer leitura.
if grep -q $'\r' "$ENV_FILE" 2>/dev/null; then
  echo "Normalizando o .env (CRLF -> LF)..."
  sed -i 's/\r$//' "$ENV_FILE"
fi

read_env() {
  local key="$1" fallback="$2" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  printf '%s' "${value:-$fallback}"
}

OLLAMA_BASE_URL="$(read_env OLLAMA_BASE_URL http://host.docker.internal:11434)"
WEB_PORT="$(read_env WEB_PORT 8080)"
STATE_FILE="$ROOT_DIR/data/ollama-mode.env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.yaml")

echo "Preparando Ollama (Windows/GPU primeiro, WSL como reserva) e recursos de voz..."
bash "$ROOT_DIR/scripts/pull-models.sh"

# O ensure-ollama.sh grava qual instância foi escolhida; a URL dos containers vem daí.
if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
  export OLLAMA_BASE_URL
  export OLLAMA_FALLBACK_URL
  OLLAMA_MODE="${OLLAMA_MODE:-wsl}"
  echo "Ollama em uso: $OLLAMA_MODE ($OLLAMA_BASE_URL)"
fi

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
deadline=$((SECONDS + 300))
until "${COMPOSE[@]}" exec -T backend python -c "import json,urllib.request; h=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); urllib.request.urlopen('http://kokoro:8880/health', timeout=5); assert h['ollama']=='ok' and h['model_available'] is True and h['speech']['engine']" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    "${COMPOSE[@]}" --profile core --profile voice ps
    echo "Os containers iniciaram, mas o backend e o Kokoro não responderam em 300 segundos." >&2
    exit 1
  fi
  sleep 3
done

# O Vosk já tem o modelo montado; o Whisper baixa o modelo (centenas de MB) na primeira vez
# e guarda no volume de dados, então essa espera só é longa na primeira execução.
"${COMPOSE[@]}" exec -T backend python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/api/warmup', method='POST'), timeout=15)" >/dev/null 2>&1 || true
printf 'Preparando o reconhecimento de fala'
deadline=$((SECONDS + 900))
until "${COMPOSE[@]}" exec -T backend python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3))['speech']['available'] is True" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo ""
    echo "O reconhecimento de fala ainda não está pronto; o restante do assistente funciona." >&2
    break
  fi
  printf '.'
  sleep 5
done
printf '\n'
MOTOR="$("${COMPOSE[@]}" exec -T backend python -c "import json,urllib.request; s=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3))['speech']; print(s['engine'] + ' / ' + s['model'])" 2>/dev/null | tr -d '\r' | tail -n 1)"
echo "Reconhecimento de fala: ${MOTOR:-indefinido}"

echo ""
echo "Assistente iniciado: http://localhost:$WEB_PORT"
echo "Health do backend:   http://localhost:$WEB_PORT/health"
echo "Validação completa:  ./scripts/healthcheck.sh"
echo "Parar tudo:          docker compose --env-file .env --profile core --profile voice down"
