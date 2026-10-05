#!/usr/bin/env bash
# Validação de ponta a ponta do assistente já em execução.
# Percorre as rotas públicas pela porta publicada (mesmo caminho do navegador),
# incluindo o ciclo completo de voz: o TTS (Kokoro ou Piper) gera o áudio e o STT o transcreve.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ASSISTANT_ENV_FILE:-$ROOT_DIR/.env}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$ROOT_DIR/$ENV_FILE"
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo de ambiente não encontrado: $ENV_FILE" >&2
  exit 1
fi

read_env() {
  local key="$1" fallback="$2" value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  printf '%s' "${value:-$fallback}"
}

WEB_PORT="$(read_env WEB_PORT 8080)"
BASE_URL="${HEALTHCHECK_BASE_URL:-http://127.0.0.1:$WEB_PORT}"

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
TTS_ENGINE="$(read_env TTS_ENGINE kokoro)"
[[ "$TTS_ENGINE" == "piper" ]] || TTS_ENGINE="kokoro"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.yaml" --profile core --profile "$TTS_PROFILE")
FAILURES=0

if ! command -v curl >/dev/null 2>&1; then
  echo "Dependência ausente: instale 'curl' para executar o healthcheck." >&2
  exit 1
fi

step() {
  echo ""
  echo "== $1"
}

ok() {
  echo "   OK: $1"
}

fail() {
  echo "   FALHA: $1" >&2
  FAILURES=$((FAILURES + 1))
}

now_ms() {
  date +%s%3N
}

json_field() {
  printf '%s' "$1" | sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p" | head -n 1
}

chat() {
  # chat <mensagem> -> imprime o JSON de resposta e define CHAT_SECONDS
  local payload start end
  payload="{\"message\":\"$1\"}"
  start="$(now_ms)"
  CHAT_JSON="$(curl --silent --show-error --max-time 300 -H 'Content-Type: application/json' \
    -d "$payload" "$BASE_URL/api/chat")"
  CHAT_STATUS=$?
  end="$(now_ms)"
  CHAT_SECONDS=$(( (end - start) / 1000 ))
}

step "Containers"
if "${COMPOSE[@]}" ps --status running | grep -q backend; then
  "${COMPOSE[@]}" ps
  ok "backend, frontend e $TTS_ENGINE estão em execução."
else
  "${COMPOSE[@]}" ps
  fail "os containers não estão em execução; rode ./scripts/bootstrap.sh."
  echo ""
  echo "Healthcheck interrompido." >&2
  exit 1
fi

step "GET /health"
HEALTH_JSON="$(curl --silent --show-error --max-time 15 "$BASE_URL/health")"
echo "   $HEALTH_JSON"
case "$HEALTH_JSON" in
  *'"status":"ok"'*) ok "Ollama acessível pelo container e modelo disponível." ;;
  *) fail "health não retornou status ok." ;;
esac

step "Motor de fala (campo 'speech' do /health)"
case "$HEALTH_JSON" in
  *'"speech"'*'"available":true'*)
    ok "motor de fala pronto: $(printf '%s' "$HEALTH_JSON" | sed -n 's/.*"speech":\({\?[^}]*}\).*/\1/p')"
    ;;
  *'"speech"'*)
    fail "o motor de fala ainda não está pronto (rode ./scripts/bootstrap.sh; o Whisper baixa o modelo na primeira vez)."
    ;;
  *) fail "o /health não informou o motor de fala." ;;
esac

step "GET /api/config/public"
CONFIG_JSON="$(curl --silent --show-error --max-time 15 "$BASE_URL/api/config/public")"
echo "   $CONFIG_JSON"
case "$CONFIG_JSON" in
  *'"assistant_name"'*) ok "configuração pública exposta sem segredos." ;;
  *) fail "configuração pública não retornou assistant_name." ;;
esac
case "$CONFIG_JSON" in
  *BRAVE*|*api_key*|*API_KEY*) fail "a configuração pública vazou informação de chave." ;;
  *) ok "nenhuma chave aparece na configuração pública." ;;
esac

step "GET / (interface)"
FRONT_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 "$BASE_URL/")"
if [[ "$FRONT_STATUS" == "200" ]]; then
  ok "interface responde HTTP 200 em $BASE_URL/."
else
  fail "interface respondeu HTTP $FRONT_STATUS."
fi


step "POST /api/chat — pergunta geral (sem ferramenta, sem internet)"
chat "Explique em uma frase o que é fotossíntese."
echo "   ${CHAT_JSON:0:400}"
if [[ "$CHAT_STATUS" -ne 0 ]]; then
  fail "a chamada de chat falhou (curl $CHAT_STATUS)."
else
  ANSWER="$(json_field "$CHAT_JSON" answer)"
  if [[ -n "$ANSWER" ]]; then
    ok "resposta em ${CHAT_SECONDS}s: ${ANSWER:0:160}"
  else
    fail "resposta vazia."
  fi
  case "$CHAT_JSON" in
    *'"used_tools":[]'*) ok "nenhuma ferramenta foi acionada para pergunta geral." ;;
    *) fail "pergunta geral acionou ferramenta." ;;
  esac
fi

step "POST /api/chat — previsão do tempo (ferramenta weather + fonte)"
chat "Como fica o tempo esta semana em Itapecerica da Serra?"
echo "   ${CHAT_JSON:0:400}"
case "$CHAT_JSON" in
  *'"used_tools":["weather"]'*) ok "roteador escolheu weather." ;;
  *) fail "roteador não escolheu weather." ;;
esac
case "$CHAT_JSON" in
  *'open-meteo.com'*) ok "fonte da previsão presente na resposta." ;;
  *) fail "fonte da previsão ausente." ;;
esac

step "POST /api/chat — dado atual (Brave Search)"
chat "Quais são as notícias de hoje sobre o Corinthians?"
echo "   ${CHAT_JSON:0:400}"
BRAVE_KEY="$(read_env BRAVE_SEARCH_API_KEY "")"
if [[ -z "$BRAVE_KEY" ]]; then
  case "$CHAT_JSON" in
    *'precisa ser configurada'*) ok "sem BRAVE_SEARCH_API_KEY o assistente avisa em vez de inventar." ;;
    *) fail "sem chave, o assistente deveria informar que a pesquisa precisa ser configurada." ;;
  esac
else
  case "$CHAT_JSON" in
    *'"url":"https://'*) ok "pesquisa retornou resultados com fonte." ;;
    *) fail "pesquisa não retornou fontes." ;;
  esac
fi

step "POST /api/speak — síntese de voz ($TTS_ENGINE)"
WAV_FILE="$(mktemp)"
curl --silent --show-error --max-time 180 -H 'Content-Type: application/json' \
  -d '{"text":"Olá, eu sou a Kunica e estou funcionando sem internet."}' \
  -o "$WAV_FILE" "$BASE_URL/api/speak"
SPEAK_STATUS=$?
WAV_BYTES="$(wc -c <"$WAV_FILE" | tr -d ' ')"
if [[ "$SPEAK_STATUS" -ne 0 ]]; then
  fail "a síntese de voz falhou (curl $SPEAK_STATUS)."
elif [[ "$WAV_BYTES" -lt 20000 ]]; then
  fail "áudio gerado tem apenas $WAV_BYTES bytes."
elif [[ "$(head -c 4 "$WAV_FILE")" != "RIFF" ]]; then
  fail "o áudio gerado não é um WAV (cabeçalho RIFF ausente)."
else
  ok "WAV pt-BR gerado com $WAV_BYTES bytes."
fi

step "POST /api/transcribe — reconhecimento de voz sobre o áudio de $TTS_ENGINE"
TRANSCRIBE_JSON="$(curl --silent --show-error --max-time 180 -H 'Content-Type: audio/wav' \
  --data-binary "@$WAV_FILE" "$BASE_URL/api/transcribe")"
TRANSCRIBE_STATUS=$?
rm -f "$WAV_FILE"
echo "   $TRANSCRIBE_JSON"
if [[ "$TRANSCRIBE_STATUS" -ne 0 ]]; then
  fail "a transcrição falhou (curl $TRANSCRIBE_STATUS)."
else
  TEXT="$(json_field "$TRANSCRIBE_JSON" text)"
  if [[ -n "$TEXT" ]]; then
    ok "motor de fala transcreveu: $TEXT"
  else
    fail "transcrição vazia."
  fi
fi

step "Memória persistente no volume Docker"
if docker volume inspect assistente-local-data >/dev/null 2>&1; then
  ok "volume assistente-local-data existe no storage do Docker."
else
  fail "volume assistente-local-data não encontrado."
fi

MEMORY_MARKER="healthcheck $(date '+%Y-%m-%d %H:%M:%S') memoria persistente ativa"
CREATE_JSON="$(curl --silent --show-error --max-time 30 -H 'Content-Type: application/json' \
  -d "{\"text\":\"$MEMORY_MARKER\"}" "$BASE_URL/api/memories")"
CREATE_STATUS=$?
MEMORY_ID="$(json_field "$CREATE_JSON" id)"
if [[ "$CREATE_STATUS" -ne 0 || -z "$MEMORY_ID" ]]; then
  fail "não consegui gravar na memória persistente (${CREATE_JSON:0:200})."
else
  ok "informação gravada no volume (id $MEMORY_ID)."
fi

LIST_JSON="$(curl --silent --show-error --max-time 15 "$BASE_URL/api/memories")"
case "$LIST_JSON" in
  *"$MEMORY_MARKER"*) ok "a informação aparece na listagem de /api/memories." ;;
  *) fail "a informação gravada não aparece na listagem." ;;
esac

# Prova de persistência: recria o container do backend e confere que o volume mantém o dado.
if "${COMPOSE[@]}" up -d --force-recreate --no-deps backend >/dev/null 2>&1; then
  for _ in $(seq 1 30); do
    curl --silent --fail --max-time 5 "$BASE_URL/health" >/dev/null 2>&1 && break
    sleep 2
  done
  AFTER_JSON="$(curl --silent --show-error --max-time 15 "$BASE_URL/api/memories")"
  case "$AFTER_JSON" in
    *"$MEMORY_MARKER"*) ok "a informação sobreviveu à recriação do container do backend." ;;
    *) fail "a informação se perdeu quando o container foi recriado." ;;
  esac
else
  fail "não consegui recriar o container do backend para testar a persistência."
fi

if [[ -n "$MEMORY_ID" ]]; then
  DELETE_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' -X DELETE "$BASE_URL/api/memories/$MEMORY_ID")"
  if [[ "$DELETE_STATUS" == "200" ]]; then
    ok "registro de teste removido da memória."
  else
    fail "não consegui remover o registro de teste (HTTP $DELETE_STATUS)."
  fi
fi

step "Limites e validações"
LONG_MESSAGE="$(printf 'a%.0s' $(seq 1 4100))"
LONG_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 30 \
  -H 'Content-Type: application/json' -d "{\"message\":\"$LONG_MESSAGE\"}" "$BASE_URL/api/chat")"
if [[ "$LONG_STATUS" == "413" ]]; then
  ok "mensagem acima do limite retorna 413."
else
  fail "mensagem acima do limite retornou HTTP $LONG_STATUS."
fi

EMPTY_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 30 \
  -H 'Content-Type: application/json' -d '{"message":"   "}' "$BASE_URL/api/chat")"
if [[ "$EMPTY_STATUS" == "422" ]]; then
  ok "mensagem vazia retorna 422."
else
  fail "mensagem vazia retornou HTTP $EMPTY_STATUS."
fi

echo ""
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Healthcheck concluído sem falhas: $BASE_URL"
  exit 0
fi
echo "Healthcheck concluído com $FAILURES falha(s)." >&2
exit 1
