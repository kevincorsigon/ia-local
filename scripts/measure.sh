#!/usr/bin/env bash
# Mede o desempenho real do assistente e grava a evidência da Fase 9 em docs/phase9-metrics.md.
# Registra: tokens/s do Ollama, tempos de resposta do chat, uso dos containers,
# memória do host, testes automatizados e os logs recentes do backend.
set -uo pipefail

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

WEB_PORT="$(read_env WEB_PORT 8080)"
OLLAMA_HOST_URL="$(read_env OLLAMA_HOST_URL http://127.0.0.1:11434)"
OLLAMA_MODEL="$(read_env OLLAMA_MODEL qwen2.5:1.5b)"
MAX_RESPONSE_TOKENS="$(read_env MAX_RESPONSE_TOKENS 400)"
TTS_IMAGE="$(read_env TTS_IMAGE ghcr.io/remsky/kokoro-fastapi-cpu:latest)"
BASE_URL="${MEASURE_BASE_URL:-http://127.0.0.1:$WEB_PORT}"
OUTPUT_FILE="${MEASURE_OUTPUT:-$ROOT_DIR/docs/phase9-metrics.md}"

# O ensure-ollama.sh grava qual instância está em uso (Windows/GPU ou WSL/CPU).
STATE_FILE="$ROOT_DIR/data/ollama-mode.env"
if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
fi
OLLAMA_MODE="${OLLAMA_MODE:-desconhecido}"

# Regra única de mapeamento engine -> profile (mesma lógica de bootstrap.sh:tts_profile).
tts_profile() {
  local engine
  engine="$(read_env TTS_ENGINE kokoro)"
  if [[ "$engine" == "piper" ]]; then
    printf '%s' "tts-piper"
  else
    printf '%s' "tts-kokoro"
  fi
}
TTS_PROFILE="$(tts_profile)"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.yaml" --profile core --profile "$TTS_PROFILE")
FAILURES=0

if ! command -v curl >/dev/null 2>&1; then
  echo "Dependência ausente: instale 'curl' para executar as medições." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"
: >"$OUTPUT_FILE"

say() {
  printf '%s\n' "$1" | tee -a "$OUTPUT_FILE"
}

section() {
  say ""
  say "## $1"
}

# run_block <comando...>: executa o comando e grava a saída como bloco de código.
run_block() {
  say '```text'
  "$@" 2>&1 | tee -a "$OUTPUT_FILE"
  say '```'
}

now_ms() {
  date +%s%3N
}

json_number() {
  printf '%s' "$1" | grep -o "\"$2\":[0-9]*" | head -n 1 | sed 's/.*://'
}

json_list() {
  printf '%s' "$1" | sed -n "s/.*\"$2\":\[\([^]]*\)\].*/\1/p" | head -n 1
}

json_field() {
  printf '%s' "$1" | sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p" | head -n 1
}

fail() {
  say "- **FALHA:** $1"
  FAILURES=$((FAILURES + 1))
}

say "# Medições da Fase 9 — assistente local"
say ""
say "- Data: $(date '+%Y-%m-%d %H:%M:%S %Z')"
say "- Host: $(uname -srm)"
if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
  say "- Ambiente: WSL ($(grep -oE 'microsoft[^ ]*' /proc/version | head -n 1))"
fi
say "- Ollama no host: $OLLAMA_HOST_URL (modelo \`$OLLAMA_MODEL\`)"
say "- Ollama em uso: $OLLAMA_MODE ($OLLAMA_HOST_URL)"
say "- Kokoro (TTS): \`$TTS_IMAGE\`"
say "- Interface: $BASE_URL"
say "- Limite de tokens por resposta: $MAX_RESPONSE_TOKENS"

section "Recursos do host"
run_block free -h
say ""
run_block nproc

section "Modelo carregado no Ollama"
if command -v ollama >/dev/null 2>&1; then
  run_block env OLLAMA_HOST="$OLLAMA_HOST_URL" ollama ps
else
  say "O comando \`ollama\` não está instalado neste host (a API responde em $OLLAMA_HOST_URL)."
fi

section "Velocidade de geração do Ollama (chamada direta)"
PROMPT="Explique em uma frase o que é fotossíntese."
# think=false: sem isso o Gemma 4 gasta o num_predict no raciocínio e devolve vazio.
GENERATE_JSON="$(curl --silent --max-time 600 -H 'Content-Type: application/json' \
  -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"$PROMPT\",\"stream\":false,\"think\":false,\"options\":{\"num_predict\":$MAX_RESPONSE_TOKENS}}" \
  "$OLLAMA_HOST_URL/api/generate")"
EVAL_COUNT="$(json_number "$GENERATE_JSON" eval_count)"
EVAL_DURATION="$(json_number "$GENERATE_JSON" eval_duration)"
PROMPT_COUNT="$(json_number "$GENERATE_JSON" prompt_eval_count)"
PROMPT_DURATION="$(json_number "$GENERATE_JSON" prompt_eval_duration)"
TOTAL_DURATION="$(json_number "$GENERATE_JSON" total_duration)"
LOAD_DURATION="$(json_number "$GENERATE_JSON" load_duration)"

if [[ -z "$EVAL_COUNT" || -z "$EVAL_DURATION" || "$EVAL_DURATION" == "0" ]]; then
  fail "não foi possível medir tokens/s no Ollama (resposta: ${GENERATE_JSON:0:200})."
else
  TOKENS_PER_SECOND="$(awk -v c="$EVAL_COUNT" -v d="$EVAL_DURATION" 'BEGIN{printf "%.2f", (c*1000000000)/d}')"
  PROMPT_TOKENS_PER_SECOND="$(awk -v c="${PROMPT_COUNT:-0}" -v d="${PROMPT_DURATION:-0}" 'BEGIN{ if (d>0) printf "%.2f", (c*1000000000)/d; else print "n/d" }')"
  say "- Tokens gerados: $EVAL_COUNT"
  say "- Velocidade de geração: **${TOKENS_PER_SECOND} tokens/s**"
  say "- Velocidade de processamento do prompt: ${PROMPT_TOKENS_PER_SECOND} tokens/s (${PROMPT_COUNT:-0} tokens)"
  say "- Duração total da chamada: $(awk -v d="${TOTAL_DURATION:-0}" 'BEGIN{printf "%.2f", d/1000000000}') s"
  say "- Carregamento do modelo: $(awk -v d="${LOAD_DURATION:-0}" 'BEGIN{printf "%.2f", d/1000000000}') s"
  say "- Resposta do modelo: $(json_field "$GENERATE_JSON" response)"
fi

section "Tempo de resposta do POST /api/chat"

measure_chat() {
  # measure_chat <mensagem> -> preenche CHAT_JSON, CHAT_STATUS e CHAT_MS
  local payload start end
  payload="{\"message\":\"$1\"}"
  start="$(now_ms)"
  CHAT_JSON="$(curl --silent --show-error --max-time 600 -H 'Content-Type: application/json' \
    -d "$payload" "$BASE_URL/api/chat")"
  CHAT_STATUS=$?
  end="$(now_ms)"
  CHAT_MS=$((end - start))
}

report_chat() {
  # report_chat <rótulo> <mensagem>
  local label="$1" message="$2" answer
  measure_chat "$message"
  if [[ "$CHAT_STATUS" -ne 0 ]]; then
    fail "$label: chamada falhou (curl $CHAT_STATUS)."
    return
  fi
  answer="$(json_field "$CHAT_JSON" answer)"
  if [[ -z "$answer" ]]; then
    fail "$label: resposta vazia (${CHAT_JSON:0:200})."
    return
  fi
  say "- $label: **${CHAT_MS} ms** — ferramentas: $(json_list "$CHAT_JSON" used_tools)"
  say "  - resposta: ${answer:0:200}"
  LAST_CHAT_MS="$CHAT_MS"
}

GENERAL_QUESTION="Explique em uma frase o que é fotossíntese."
report_chat "Rodada 1 (pergunta geral, modelo frio)" "$GENERAL_QUESTION"
COLD_MS="${LAST_CHAT_MS:-0}"
report_chat "Rodada 2 (mesma pergunta, modelo quente)" "$GENERAL_QUESTION"
WARM_1_MS="${LAST_CHAT_MS:-0}"
report_chat "Rodada 3 (mesma pergunta, modelo quente)" "$GENERAL_QUESTION"
WARM_2_MS="${LAST_CHAT_MS:-0}"
report_chat "Rodada 4 (pergunta com ferramenta weather)" "Como fica o tempo esta semana em Itapecerica da Serra?"

if [[ "${WARM_1_MS:-0}" -gt 0 && "${WARM_2_MS:-0}" -gt 0 ]]; then
  say "- Média com o modelo quente: $(awk -v a="$WARM_1_MS" -v b="$WARM_2_MS" 'BEGIN{printf "%.0f", (a+b)/2}') ms"
fi
if [[ "${COLD_MS:-0}" -gt 0 ]]; then
  say "- Primeira chamada (inclui aquecimento do modelo): ${COLD_MS} ms"
fi

section "Uso de recursos dos containers"
run_block docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"

section "Memória persistente (storage do Docker)"
if docker volume inspect assistente-local-data >/dev/null 2>&1; then
  run_block docker volume inspect assistente-local-data
else
  say "O volume assistente-local-data ainda não existe; rode ./scripts/bootstrap.sh."
fi
MEMORY_JSON="$(curl --silent --show-error --max-time 15 "$BASE_URL/api/memories")"
say ""
say "- Itens guardados no volume: $(json_number "$MEMORY_JSON" count)"

section "Estado dos serviços"
run_block "${COMPOSE[@]}" ps

section "Testes automatizados do backend"
if "${COMPOSE[@]}" ps --status running 2>/dev/null | grep -q backend; then
  run_block "${COMPOSE[@]}" exec -T backend pytest -q
else
  run_block "${COMPOSE[@]}" run --rm --no-deps backend pytest -q
fi

section "Logs recentes do backend"
run_block "${COMPOSE[@]}" logs --tail=40 backend

section "Resumo"
say ""
say "| Métrica | Valor |"
say "| --- | --- |"
say "| Tokens/s (Ollama, geração) | ${TOKENS_PER_SECOND:-n/d} |"
say "| Chat — chamada fria | ${COLD_MS:-n/d} ms |"
say "| Chat — chamada quente (média) | $(awk -v a="${WARM_1_MS:-0}" -v b="${WARM_2_MS:-0}" 'BEGIN{ if (a>0 && b>0) printf "%.0f", (a+b)/2; else print "n/d" }') ms |"
say "| Chat — chamada com ferramenta | ${LAST_CHAT_MS:-n/d} ms |"
say "| Memória livre no host | $(free -h | awk '/^Mem:/{print $4" livres de "$2}') |"
say "| Itens na memória persistente | $(json_number "$MEMORY_JSON" count) |"
say "| Falhas registradas | $FAILURES |"

say ""
if [[ "$FAILURES" -eq 0 ]]; then
  say "Medições concluídas sem falhas. Relatório gravado em \`docs/phase9-metrics.md\`."
  exit 0
fi
say "Medições concluídas com $FAILURES falha(s). Relatório gravado em \`docs/phase9-metrics.md\`."
exit 1
