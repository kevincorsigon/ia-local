#!/usr/bin/env bash
# Abre o navegador padrão na interface da assistente, esperando ela responder.
#
# Usado pelo autostart do desktop (ver scripts/install-autostart.sh). Como o assistente sobe em
# paralelo no boot, aqui a gente espera a porta responder antes de abrir — assim o navegador não
# cai numa página de erro.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ASSISTANT_ENV_FILE:-$ROOT_DIR/.env}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$ROOT_DIR/$ENV_FILE"
fi
# No NUC o arquivo chega renomeado para .env padrão; se o .env pedido não
# existir (ex.: o atalho antigo apontava para .env.nuc), cai para o .env.
if [[ ! -f "$ENV_FILE" && -f "$ROOT_DIR/.env" ]]; then
  ENV_FILE="$ROOT_DIR/.env"
fi

PORT=8080
limpa_cr() { tr -d '\r'; }
if [[ -f "$ENV_FILE" ]]; then
  valor="$(sed -n 's/^WEB_PORT=//p' "$ENV_FILE" | tail -n 1 | limpa_cr)"
  [[ -n "$valor" ]] && PORT="$valor"
  kiosk_env="$(sed -n 's/^ASSISTANT_KIOSK=//p' "$ENV_FILE" | tail -n 1 | limpa_cr | tr -d '[:space:]')"
  [[ -n "$kiosk_env" ]] && ASSISTANT_KIOSK="$kiosk_env"
fi
URL="http://localhost:${PORT}"
ASSISTANT_KIOSK="$(printf '%s' "${ASSISTANT_KIOSK:-0}" | limpa_cr | tr -d '[:space:]')"
[[ -z "$ASSISTANT_KIOSK" ]] && ASSISTANT_KIOSK=0

# Espera até 3 minutos (o bootstrap aquece o modelo de fala e isso demora na primeira vez).
for _ in $(seq 1 90); do
  if curl -sSf -o /dev/null --max-time 2 "$URL"; then
    break
  fi
  sleep 2
done

abrir_kiosk() {
  # Tenta os lançadores conhecidos do Chromium/Chrome em modo quiosque
  # (tela cheia de verdade, sem bordas nem barra de endereço).
  # O snap do Ubuntu atende por "chromium" mas instala o binário em
  # /snap/bin, que pode não estar no PATH do autostart — cobre esse caso.
  for bin in chromium-browser chromium google-chrome google-chrome-stable /snap/bin/chromium /usr/bin/chromium-browser /usr/bin/chromium /usr/bin/google-chrome /usr/bin/google-chrome-stable; do
    caminho="$bin"
    if [[ "$bin" != /* ]]; then
      caminho="$(command -v "$bin" 2>/dev/null || true)"
      [[ -z "$caminho" ]] && continue
    fi
    if [[ -x "$caminho" ]]; then
      echo "Abrindo $URL em tela cheia ($caminho --kiosk)"
      exec "$caminho" --kiosk --no-first-run --disable-pinch --overscroll-history-navigation=0 "$URL"
    fi
  done
  # Firefox como reserva: quiosque de verdade (sem bordas nem barra).
  for bin in firefox firefox-esr /snap/bin/firefox /usr/bin/firefox; do
    caminho="$bin"
    if [[ "$bin" != /* ]]; then
      caminho="$(command -v "$bin" 2>/dev/null || true)"
      [[ -z "$caminho" ]] && continue
    fi
    if [[ -x "$caminho" ]]; then
      echo "Abrindo $URL em tela cheia ($caminho --kiosk)"
      exec "$caminho" --kiosk "$URL"
    fi
  done
  return 1
}

if [[ "$ASSISTANT_KIOSK" == "1" ]]; then
  echo "Modo quiosque pedido (ASSISTANT_KIOSK=1, env: $ENV_FILE)"
  abrir_kiosk || {
    echo "Nenhum navegador com modo quiosque encontrado (Chromium/Chrome/Firefox)." >&2
    echo "Instale um, ex.:  sudo apt install -y chromium-browser" >&2
    echo "Abrindo no navegador padrão mesmo assim." >&2
  }
fi

echo "Abrindo $URL no navegador padrão"

# O console também tem o próprio botão de tela cheia: o gráfico de barras no canto superior esquerdo.
# Sem navegador instalado o xdg-open falha com mensagens confusas; deixa uma clara.
if ! xdg-open "$URL"; then
  echo "Nenhum navegador encontrado para abrir $URL." >&2
  echo "Instale um, ex.:  sudo apt install -y chromium-browser" >&2
  exit 1
fi
exit 0
