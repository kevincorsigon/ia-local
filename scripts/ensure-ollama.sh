#!/usr/bin/env bash
# Garante um Ollama utilizável para o assistente, nesta ordem de preferência:
#   1) Ollama rodando no host Windows — é o caminho com GPU (ROCm) e muito mais rápido;
#   2) se o Windows não estiver acessível, sobe/usa o Ollama dentro do WSL (100% CPU).
# A decisão fica gravada em data/ollama-mode.env, que o bootstrap, o healthcheck e o
# measure reutilizam para saber qual instância está em uso.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
STATE_FILE="$ROOT_DIR/data/ollama-mode.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo .env não encontrado. Copie .env.example para .env." >&2
  exit 1
fi

read_env() {
  local key="$1" fallback="$2" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  printf '%s' "${value:-$fallback}"
}

OLLAMA_PREFER_WINDOWS="$(read_env OLLAMA_PREFER_WINDOWS 1)"
OLLAMA_WINDOWS_HOST="$(read_env OLLAMA_WINDOWS_HOST "")"
OLLAMA_PREFER_PORT="$(read_env OLLAMA_PORT 11434)"
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

api_ready() {
  # api_ready <url>
  curl --silent --fail --max-time 4 "$1/api/tags" >/dev/null 2>&1
}

models_from_url() {
  # models_from_url <url>
  curl --silent --fail --max-time 6 "$1/api/tags" \
    | grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | sed 's/.*"\([^"]*\)"$/\1/'
}

has_model() {
  # has_model <url> ; devolve 0 se o modelo configurado existe naquela instância
  local url="$1" candidate
  local installed
  installed="$(models_from_url "$url" || true)"
  for candidate in "$OLLAMA_MODEL" "$OLLAMA_MODEL-latest" "$OLLAMA_MODEL:latest"; do
    printf '%s\n' "$installed" | grep -Fxq "$candidate" && return 0
  done
  return 1
}

windows_host_ip() {
  # IP do host Windows visto pelo WSL: variável do .env ou o gateway padrão.
  if [[ -n "$OLLAMA_WINDOWS_HOST" ]]; then
    printf '%s' "$OLLAMA_WINDOWS_HOST"
    return 0
  fi
  ip route show default 2>/dev/null | awk '{print $3}' | head -n 1
}

pull_model_via_api() {
  # pull_model_via_api <url> — baixa o modelo usando a API, sem depender do CLI
  local url="$1"
  echo "Baixando o modelo $OLLAMA_MODEL em $url (pode levar vários minutos)..."
  curl --silent --show-error --max-time 3600 -X POST "$url/api/pull" \
    -d "{\"model\":\"$OLLAMA_MODEL\",\"stream\":false}" >/dev/null || return 1
  return 0
}

# O host responder em 127.0.0.1 não implica que os containers alcancem: uma escuta em loopback
# devolve "Connection refused" para a rede Docker e o bootstrap falha linhas depois, sem apontar a
# causa. host.docker.internal aponta para o gateway da bridge, então só um bind wildcard
# (0.0.0.0 / ::) resolve — escutar num IP específico da LAN também não é alcançável por lá.
assert_bind_reachable_from_docker() {
  command -v ss >/dev/null 2>&1 || return 0
  local addrs addr
  addrs="$(ss -tln 2>/dev/null \
    | awk -v p=":${OLLAMA_PREFER_PORT}" \
        '$1 == "LISTEN" && index($4, p) == length($4) - length(p) + 1 {
           a = $4; sub(/:[0-9]+$/, "", a); gsub(/[\[\]]/, "", a); print a
         }' \
    | sort -u)"
  # Sem listener identificado não há o que avaliar: quem acusa é o teste do bootstrap.
  [[ -n "$addrs" ]] || return 0
  while read -r addr; do
    case "$addr" in
      0.0.0.0|::|\*) return 0 ;;
    esac
  done <<<"$addrs"
  {
    echo "O Ollama responde no host, mas não escuta em nenhuma interface alcançável pela rede Docker"
    echo "(encontrado: $(tr '\n' ' ' <<<"$addrs") no ${OLLAMA_PREFER_PORT}/tcp). Os containers levam"
    echo "'Connection refused' em host.docker.internal. Para o serviço systemd escutar em 0.0.0.0:"
    echo
    echo "  sudo mkdir -p /etc/systemd/system/ollama.service.d"
    echo "  sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'"
    echo "  [Service]"
    echo "  Environment=\"OLLAMA_HOST=0.0.0.0:${OLLAMA_PREFER_PORT}\""
    echo "  EOF"
    echo "  sudo systemctl daemon-reload && sudo systemctl restart ollama"
    echo "  ss -tlnp | grep ${OLLAMA_PREFER_PORT}   # precisa mostrar 0.0.0.0:${OLLAMA_PREFER_PORT}"
    echo
    echo "Depois rode ./scripts/bootstrap.sh de novo."
  } >&2
  return 1
}

write_state() {
  local mode="$1" host_url="$2" base_url="$3" fallback_url="${4:-}"
  mkdir -p "$(dirname "$STATE_FILE")"
  cat >"$STATE_FILE" <<STATE
# Gerado por scripts/ensure-ollama.sh — não editar à mão.
OLLAMA_MODE=$mode
OLLAMA_HOST_URL=$host_url
OLLAMA_BASE_URL=$base_url
OLLAMA_FALLBACK_URL=$fallback_url
OLLAMA_MODEL=$OLLAMA_MODEL
STATE
}

start_ollama_service() {
  has_systemd || return 1
  systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service' || return 1
  # Já está ativo: nada a subir.
  if systemctl is-active --quiet ollama 2>/dev/null; then
    return 0
  fi
  if [[ "$EUID" -eq 0 ]]; then
    systemctl start ollama
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n systemctl start ollama
    return 0
  fi
  # A unidade existe, mas subir exige senha (sudo -n não passa). Devolve 2 para o chamador
  # orientar o usuário — subir um 'ollama serve' paralelo colidiria com o serviço na porta.
  return 2
}

start_wsl_background() {
  command -v ollama >/dev/null 2>&1 || return 1
  # Porta já ocupada significa que existe um Ollama rodando (ou o próprio serviço systemd).
  # Subir outro resultaria em "bind: address already in use" e atrapalharia o que já responde.
  if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${OLLAMA_PREFER_PORT}[[:space:]]"; then
    echo "A porta ${OLLAMA_PREFER_PORT} já está em uso — não vou iniciar um segundo 'ollama serve'."
    return 0
  fi
  mkdir -p "$(dirname "$OLLAMA_LOG_FILE")"
  echo "Iniciando 'ollama serve' no host (bind $OLLAMA_SERVE_HOST); log em $OLLAMA_LOG_FILE"
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

stop_wsl_ollama() {
  # Quando o Windows assume, o WSL não precisa manter o modelo carregado.
  local stopped=1
  if has_systemd && systemctl is-active --quiet ollama 2>/dev/null; then
    if [[ "$EUID" -eq 0 ]]; then
      systemctl stop ollama || stopped=0
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
      sudo -n systemctl stop ollama || stopped=0
    else
      stopped=0
    fi
  fi
  if pkill -f 'ollama serve' 2>/dev/null; then
    :
  fi
  [[ "$stopped" -eq 1 ]]
}

wait_ready() {
  # wait_ready <url> <segundos>
  local url="$1" limit="${2:-60}"
  local deadline=$((SECONDS + limit))
  until api_ready "$url"; do
    if (( SECONDS >= deadline )); then
      return 1
    fi
    sleep 2
  done
  return 0
}

WINDOWS_IP="$(windows_host_ip)"
WINDOWS_URL="http://${WINDOWS_IP:-127.0.0.1}:${OLLAMA_PREFER_PORT}"
MODE=""
HOST_URL=""
BASE_URL=""
FALLBACK_URL=""

echo "Procurando o Ollama do host Windows em $WINDOWS_URL ..."
if [[ "$OLLAMA_PREFER_WINDOWS" == "1" && -n "$WINDOWS_IP" ]] && api_ready "$WINDOWS_URL"; then
  MODE="windows"
  HOST_URL="$WINDOWS_URL"
  BASE_URL="$WINDOWS_URL"
  FALLBACK_URL="http://host.docker.internal:${OLLAMA_PREFER_PORT}"
  echo "Ollama do Windows encontrado — usando a GPU dele."
  if ! has_model "$WINDOWS_URL"; then
    if ! pull_model_via_api "$WINDOWS_URL"; then
      echo "Não consegui baixar $OLLAMA_MODEL no Ollama do Windows; vou usar o do WSL." >&2
      MODE=""
    fi
  fi
fi

if [[ -z "$MODE" ]]; then
  if [[ "$OLLAMA_PREFER_WINDOWS" == "1" ]]; then
    if [[ -z "$WINDOWS_IP" ]]; then
      echo "Não identifiquei o host Windows; seguindo com o Ollama do WSL."
    else
      echo "Ollama do Windows não respondeu em $WINDOWS_URL; seguindo com o Ollama do WSL."
      if is_wsl && command -v tasklist.exe >/dev/null 2>&1 && ! tasklist.exe 2>/dev/null | tr -d '\r' | grep -qi 'ollama'; then
        echo "  Causa provável: nenhum 'ollama.exe' está rodando no Windows."
        echo "  Para usar a GPU, rode no Windows: powershell -ExecutionPolicy Bypass -File scripts\\ollama-windows.ps1"
      else
        echo "  Se ele já está rodando, falta liberar a rede na inicialização:"
        echo "  \$env:OLLAMA_HOST=\"0.0.0.0:$OLLAMA_PREFER_PORT\" antes de 'ollama serve'."
      fi
    fi
  fi

  echo "Verificando o Ollama do WSL em $OLLAMA_HOST_URL ..."
  if ! api_ready "$OLLAMA_HOST_URL"; then
    started=0
    if start_ollama_service; then
      echo "ollama.service pronto via systemd."
      started=1
    else
      code=$?
      if [[ "$code" -eq 2 ]]; then
        echo "O serviço ollama existe, mas iniciá-lo exige senha (o script usa 'sudo -n', sem prompt)." >&2
        echo "Rode:  sudo systemctl restart ollama" >&2
        echo "Depois rode ./scripts/bootstrap.sh de novo." >&2
        exit 1
      fi
      start_wsl_background && started=1
    fi
    if [[ "$started" -eq 0 ]]; then
      echo "Não consegui iniciar o Ollama no host." >&2
      echo "Inicie manualmente (Ubuntu: 'sudo systemctl restart ollama'; WSL: 'OLLAMA_HOST=$OLLAMA_SERVE_HOST ollama serve')" >&2
      echo "e confira OLLAMA_HOST_URL no .env." >&2
      exit 1
    fi
    if ! wait_ready "$OLLAMA_HOST_URL" "$OLLAMA_TIMEOUT_SECONDS"; then
      echo "O Ollama não ficou disponível em $OLLAMA_HOST_URL após ${OLLAMA_TIMEOUT_SECONDS}s." >&2
      if [[ -f "$OLLAMA_LOG_FILE" ]]; then
        tail -n 20 "$OLLAMA_LOG_FILE" >&2
      fi
      exit 1
    fi
  fi

  # O host respondendo não basta: se a escuta for só em loopback, os containers levam
  # "Connection refused" e o bootstrap falha depois apontando para o sintoma, não para a causa.
  assert_bind_reachable_from_docker || exit 1

  MODE="wsl"
  HOST_URL="$OLLAMA_HOST_URL"
  BASE_URL="http://host.docker.internal:${OLLAMA_PREFER_PORT}"
  # O fallback só vale quando existe um segundo Ollama de verdade. Com OLLAMA_PREFER_WINDOWS=0 o
  # usuário pediu para ignorar o Windows, mas windows_host_ip() devolve o gateway padrão numa
  # máquina sem Windows — a reserva acabaria apontando para o roteador em toda tentativa de chat.
  if [[ "$OLLAMA_PREFER_WINDOWS" == "1" ]]; then
    FALLBACK_URL="${WINDOWS_IP:+$WINDOWS_URL}"
  fi
  if ! has_model "$OLLAMA_HOST_URL"; then
    if command -v ollama >/dev/null 2>&1; then
      echo "Baixando modelo $OLLAMA_MODEL (pode levar vários minutos)..."
      OLLAMA_HOST="$OLLAMA_HOST_URL" ollama pull "$OLLAMA_MODEL" || exit 1
    elif ! pull_model_via_api "$OLLAMA_HOST_URL"; then
      echo "Falha ao baixar o modelo $OLLAMA_MODEL." >&2
      exit 1
    fi
  fi
else
  echo "Dispensando o Ollama do WSL para liberar CPU e memória."
  stop_wsl_ollama || true
fi

write_state "$MODE" "$HOST_URL" "$BASE_URL" "$FALLBACK_URL"
echo ""
echo "Ollama em uso: $MODE"
echo "  Host/scripts (OLLAMA_HOST_URL): $HOST_URL"
echo "  Containers   (OLLAMA_BASE_URL): $BASE_URL"
echo "  Reserva      (OLLAMA_FALLBACK_URL): ${FALLBACK_URL:-nenhuma}"
echo "  Estado gravado em $STATE_FILE"
