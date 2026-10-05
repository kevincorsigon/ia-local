#!/usr/bin/env bash
# Registra o assistente para subir junto com o Ubuntu e abrir o navegador no console.
#
# O que ele faz:
#   1. habilita docker e ollama no boot;
#   2. cria o serviço de sistema "assistente-local" (roda o bootstrap.sh no boot, como o seu usuário);
#   3. cria um autostart gráfico que abre o navegador padrão na interface quando ela responder.
#
# Uso (uma vez):  ./scripts/install-autostart.sh
# Idempotente: rodar de novo só reescreve os arquivos.
set -euo pipefail

if [[ "$(id -u)" -eq 0 && -z "${SUDO_USER:-}" ]]; then
  echo "Rode como o seu usuário (o script chama sudo quando precisa), não como root." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ASSISTANT_ENV_FILE:-$ROOT_DIR/.env}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$ROOT_DIR/$ENV_FILE"
fi
USER_NAME="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
SERVICE_NAME="assistente-local"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
AUTOSTART_DIR="${USER_HOME}/.config/autostart"
DESKTOP_FILE="${AUTOSTART_DIR}/assistente-console.desktop"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo de ambiente não encontrado: $ENV_FILE" >&2
  exit 1
fi

if [[ ! -d "$USER_HOME" ]]; then
  echo "Não encontrei a home de $USER_NAME ($USER_HOME)." >&2
  exit 1
fi

chmod +x "$ROOT_DIR/scripts/bootstrap.sh" "$ROOT_DIR/scripts/open-frontend.sh" 2>/dev/null || true

echo "Instalando para o usuário $USER_NAME, a partir de $ROOT_DIR"

# 1. Docker e Ollama no boot.
sudo systemctl enable docker.service >/dev/null 2>&1 || true
sudo systemctl enable ollama.service >/dev/null 2>&1 || true

# 2. Serviço que sobe o assistente no boot (roda como o seu usuário, para não criar arquivos do root
#    dentro do repositório).
sudo tee "$UNIT_FILE" >/dev/null <<UNIT
[Unit]
Description=Assistente local (Docker Compose)
Documentation=file://${ROOT_DIR}/README.md
Wants=network-online.target
After=network-online.target docker.service ollama.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=${USER_NAME}
Environment=HOME=${USER_HOME}
Environment=ASSISTANT_ENV_FILE=${ENV_FILE}
WorkingDirectory=${ROOT_DIR}
ExecStart=/bin/bash ${ROOT_DIR}/scripts/bootstrap.sh
TimeoutStartSec=3600
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service" >/dev/null

# 3. Autostart gráfico: abre o navegador quando a interface responder.
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Assistente local (console)
Comment=Abre o navegador na interface da assistente
Exec=${ROOT_DIR}/scripts/open-frontend.sh
Terminal=false
X-GNOME-Autostart-enabled=true
DESKTOP

echo
echo "Pronto."
echo "  Serviço:    sudo systemctl status ${SERVICE_NAME}"
echo "  Log:        journalctl -u ${SERVICE_NAME} -f"
echo "  Navegador:  ${DESKTOP_FILE}"
echo "  Antes agora: sudo systemctl start ${SERVICE_NAME}   (não precisa reiniciar o NUC)"
echo

falta=0
if ! id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx docker; then
  echo "PENDENTE: $USER_NAME não está no grupo 'docker'." >&2
  echo "  sudo usermod -aG docker $USER_NAME    # depois saia e entre na sessão" >&2
  falta=1
fi
if [[ ! -f /etc/systemd/system/ollama.service.d/override.conf ]]; then
  echo "PENDENTE: o Ollama ainda não está configurado para escutar em 0.0.0.0:11434." >&2
  echo "  Veja a seção 'Problemas comuns (Linux/NUC)' no README." >&2
  falta=1
fi
if [[ "$falta" -eq 0 ]]; then
  echo "Tudo certo. Falta só, se quiser o console abrindo sozinho na TV: ativar o login automático"
  echo "do usuário (Configurações → Usuários → Login automático)."
fi
