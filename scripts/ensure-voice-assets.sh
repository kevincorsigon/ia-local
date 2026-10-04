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

VOSK_NAME="$(read_env VOSK_MODEL_NAME vosk-model-small-pt-0.3)"
VOSK_URL="https://alphacephei.com/vosk/models/$VOSK_NAME.zip"
VOSK_DIR="$ROOT_DIR/backend/models"
VOSK_TARGET="$VOSK_DIR/$VOSK_NAME"
TTS_VOICE="$(read_env TTS_VOICE pf_dora)"

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

mkdir -p "$VOSK_DIR"

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

# O modelo grande pt-fb traz um rescore CARPA enorme (rescore/G.carpa, 2,3 GB) que a versão atual
# do Vosk (0.3.45) não consegue ler: "ConstArpaLm <LmStates> section reading failed". Desativando
# só esse arquivo o modelo carrega normalmente e o reconhecimento continua correto — medido neste
# projeto: 0,04-0,16 s por frase, contra 1,5-2,2 s do Whisper small.
if [[ -f "$VOSK_TARGET/rescore/G.carpa" ]]; then
  mv "$VOSK_TARGET/rescore/G.carpa" "$VOSK_TARGET/rescore/G.carpa-desativado"
  echo "rescore CARPA desativado (incompatível com o Vosk 0.3.45; o modelo segue preciso)."
fi

echo "Modelo Vosk pronto. O Kokoro não precisa baixar nada: a imagem CPU já traz o modelo v1_0 e a voz feminina $TTS_VOICE."
