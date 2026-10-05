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

PORT=8080
if [[ -f "$ENV_FILE" ]]; then
  valor="$(sed -n 's/^WEB_PORT=//p' "$ENV_FILE" | tail -n 1)"
  [[ -n "$valor" ]] && PORT="$valor"
fi
URL="http://localhost:${PORT}"

# Espera até 3 minutos (o bootstrap aquece o modelo de fala e isso demora na primeira vez).
for _ in $(seq 1 90); do
  if curl -sSf -o /dev/null --max-time 2 "$URL"; then
    break
  fi
  sleep 2
done

echo "Abrindo $URL no navegador padrão"

# Para abrir em tela cheia de verdade (Chromium/Chrome), troque a linha abaixo por:
#   exec chromium-browser --kiosk --no-first-run "$URL"
# O console também tem o próprio botão de tela cheia: o gráfico de barras no canto superior esquerdo.
exec xdg-open "$URL"
