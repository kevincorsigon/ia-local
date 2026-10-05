# Inicia o Ollama no Windows usando a GPU (ROCm), acessível pelo WSL e pelos containers.
#
# Lê o tuning do .env da raiz do repo (mesma pasta deste script, dois níveis acima):
#   OLLAMA_NUM_CTX / OLLAMA_FLASH_ATTENTION / OLLAMA_KV_CACHE_TYPE /
#   OLLAMA_NUM_PARALLEL / OLLAMA_MAX_LOADED_MODELS / OLLAMA_MAX_QUEUE /
#   OLLAMA_CONTEXT_LENGTH / OLLAMA_KEEP_ALIVE / OLLAMA_HOST (via OLLAMA_PORT)
#
# Uso no Windows (PowerShell):  powershell -ExecutionPolicy Bypass -File scripts\ollama-windows.ps1
# Se o Windows Defender perguntar sobre o firewall, permita em redes privadas.
function Get-DotEnv([string]$key, [string]$fallback) {
  $envFile = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) ".env"
  if (-not (Test-Path $envFile)) { $envFile = Join-Path $PSScriptRoot ".." | Join-Path -ChildPath ".env" }
  if (Test-Path $envFile) {
    $line = Get-Content $envFile | Where-Object { $_ -match "^$key=" } | Select-Object -Last 1
    if ($line) { return ($line -replace "^$key=", "").Trim() }
  }
  return $fallback
}

$env:HSA_OVERRIDE_GFX_VERSION = "11.0.3"   # RX 9070 XT (gfx1201) via ROCm
$env:OLLAMA_FLASH_ATTENTION = Get-DotEnv "OLLAMA_FLASH_ATTENTION" "1"
$kv = Get-DotEnv "OLLAMA_KV_CACHE_TYPE" "f16"
if ($kv -ne "") { $env:OLLAMA_KV_CACHE_TYPE = $kv }
$env:OLLAMA_NUM_PARALLEL = Get-DotEnv "OLLAMA_NUM_PARALLEL" "1"
$env:OLLAMA_MAX_LOADED_MODELS = Get-DotEnv "OLLAMA_MAX_LOADED_MODELS" "1"
$env:OLLAMA_MAX_QUEUE = Get-DotEnv "OLLAMA_MAX_QUEUE" "512"
$env:OLLAMA_CONTEXT_LENGTH = Get-DotEnv "OLLAMA_CONTEXT_LENGTH" "8192"
$env:OLLAMA_KEEP_ALIVE = Get-DotEnv "OLLAMA_KEEP_ALIVE" "30m"
$port = Get-DotEnv "OLLAMA_PORT" "11434"
$env:OLLAMA_HOST = "0.0.0.0:$port"   # sem isso o WSL não alcança o Windows
$env:OLLAMA_ORIGINS = "*"

Write-Host "Ollama (GPU) escutando em $env:OLLAMA_HOST" -ForegroundColor Cyan
Write-Host "Tuning: ctx=$env:OLLAMA_CONTEXT_LENGTH flash=$env:OLLAMA_FLASH_ATTENTION kv=$kv parallel=$env:OLLAMA_NUM_PARALLEL" -ForegroundColor DarkGray
Write-Host "Dica: rode 'bash scripts/ensure-ollama.sh' no WSL para confirmar o modo ativo." -ForegroundColor DarkGray

& 'C:\Users\kevin\AppData\Local\Programs\Ollama\ollama.exe' serve
