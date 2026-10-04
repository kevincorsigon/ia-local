# Inicia o Ollama no Windows usando a GPU (ROCm), acessível pelo WSL e pelos containers.
#
# Equivale ao comando manual, com a linha extra do OLLAMA_HOST:
#   $env:HSA_OVERRIDE_GFX_VERSION="11.0.3"   # RX 9070 XT (gfx1201) via ROCm
#   $env:OLLAMA_FLASH_ATTENTION="1"
#   $env:OLLAMA_HOST="0.0.0.0:11434"         # sem isso o WSL não alcança o Windows
#   & 'C:\Users\kevin\AppData\Local\Programs\Ollama\ollama.exe' serve
#
# Uso no Windows (PowerShell):  powershell -ExecutionPolicy Bypass -File scripts\ollama-windows.ps1
# Se o Windows Defender perguntar sobre o firewall, permita em redes privadas.
$env:HSA_OVERRIDE_GFX_VERSION = "11.0.3"
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_HOST = "0.0.0.0:11434"
$env:OLLAMA_ORIGINS = "*"
$env:OLLAMA_NUM_PARALLEL = "1"

Write-Host "Ollama (GPU) escutando em $env:OLLAMA_HOST" -ForegroundColor Cyan
Write-Host "Dica: rode 'bash scripts/ensure-ollama.sh' no WSL para confirmar o modo ativo." -ForegroundColor DarkGray

& 'C:\Users\kevin\AppData\Local\Programs\Ollama\ollama.exe' serve
