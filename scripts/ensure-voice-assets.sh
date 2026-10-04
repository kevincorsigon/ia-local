#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

read_env() {
  local key="$1" fallback="$2" value=""
  if [[ -f "$ENV_FILE" ]]; then
    value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  fi
  printf '%s' "${value:-$fallback}"
}

VOSK_NAME="vosk-model-small-pt-0.3"
VOSK_URL="https://alphacephei.com/vosk/models/$VOSK_NAME.zip"
VOSK_DIR="$ROOT_DIR/backend/models"
VOSK_TARGET="$VOSK_DIR/$VOSK_NAME"

PIPER_VOICE_NAME="$(read_env PIPER_VOICE pt_BR-faber-medium)"
PIPER_DIR="$ROOT_DIR/piper/voices"
PIPER_TARGET="$PIPER_DIR/$PIPER_VOICE_NAME.onnx"
PIPER_JSON="$PIPER_TARGET.json"

# pt_BR-faber-medium -> pt/pt_BR/faber/medium no repositório de vozes do Piper.
IFS='-' read -r PIPER_LOCALE PIPER_SPEAKER PIPER_QUALITY <<<"$PIPER_VOICE_NAME"
PIPER_LANGUAGE="${PIPER_LOCALE%%_*}"
PIPER_BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/$PIPER_LANGUAGE/$PIPER_LOCALE/$PIPER_SPEAKER/$PIPER_QUALITY"

if ! command -v curl >/dev/null 2>&1; then
  echo "Dependência ausente: instale 'curl' para baixar os modelos de voz." >&2
  exit 1
fi

download() {
  local url="$1" target="$2" label="$3"
  echo "Baixando $label..."
  curl --fail --location --retry 3 --silent --show-error --output "$target" "$url"
  if [[ ! -s "$target" ]]; then
    rm -f "$target"
    echo "Falha ao baixar $label de $url." >&2
    exit 1
  fi
}

extract_zip() {
  local archive="$1" destination="$2"
  if command -v unzip >/dev/null 2>&1; then
    unzip -q -o "$archive" -d "$destination"
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$archive" "$destination" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PY
  elif command -v busybox >/dev/null 2>&1; then
    (cd "$destination" && busybox unzip -o -q "$archive")
  else
    echo "Nenhuma ferramenta para extrair ZIP disponível: instale 'unzip' ou 'python3'." >&2
    exit 1
  fi
}

vosk_model_ready() {
  # Modelos "small" trazem final.mdl na raiz; modelos grandes trazem am/final.mdl.
  [[ -s "$VOSK_TARGET/final.mdl" || -s "$VOSK_TARGET/am/final.mdl" ]]
}

mkdir -p "$VOSK_DIR" "$PIPER_DIR"

if ! vosk_model_ready; then
  archive="$(mktemp)"
  trap 'rm -f "$archive"' EXIT
  download "$VOSK_URL" "$archive" "modelo Vosk pt-BR (compactado, cerca de 31 MB)"
  extract_zip "$archive" "$VOSK_DIR"
  rm -f "$archive"
  trap - EXIT
  if ! vosk_model_ready; then
    echo "O modelo Vosk foi extraído, mas final.mdl não foi encontrado em $VOSK_TARGET." >&2
    exit 1
  fi
else
  echo "Modelo Vosk pt-BR já está instalado."
fi

if [[ ! -s "$PIPER_TARGET" || ! -s "$PIPER_JSON" ]]; then
  download "$PIPER_BASE_URL/$PIPER_VOICE_NAME.onnx" "$PIPER_TARGET" "voz Piper $PIPER_VOICE_NAME (cerca de 63 MB)"
  download "$PIPER_BASE_URL/$PIPER_VOICE_NAME.onnx.json" "$PIPER_JSON" "configuração da voz Piper $PIPER_VOICE_NAME"
else
  echo "Voz Piper $PIPER_VOICE_NAME já está instalada."
fi

echo "Modelos de fala prontos. Os arquivos permanecem nas pastas ignoradas pelo Git."
