# Medições da Fase 9 — assistente local

- Data: 2026-10-04 01:18:50 -03
- Host: Linux 6.18.33.2-microsoft-standard-WSL2 x86_64
- Ambiente: WSL (microsoft-standard-WSL2)
- Ollama no host: http://172.19.112.1:11434 (modelo `qwen2.5:1.5b`)
- Ollama em uso: windows (http://172.19.112.1:11434)
- Kokoro (TTS): `ghcr.io/remsky/kokoro-fastapi-cpu:latest`
- Interface: http://127.0.0.1:8080
- Limite de tokens por resposta: 400

## Recursos do host
```text
               total        used        free      shared  buff/cache   available
Mem:           7.7Gi       2.8Gi       766Mi        10Mi       4.4Gi       4.9Gi
Swap:          2.0Gi        24Mi       2.0Gi
```

```text
12
```

## Modelo carregado no Ollama
```text
NAME            ID              SIZE      PROCESSOR    CONTEXT    UNTIL               
qwen2.5:1.5b    65ec06548149    1.2 GB    100% GPU     4096       29 minutes from now    
```

## Velocidade de geração do Ollama (chamada direta)
- Tokens gerados: 172
- Velocidade de geração: **196.30 tokens/s**
- Velocidade de processamento do prompt: 4688.69 tokens/s (43 tokens)
- Duração total da chamada: 0.90 s
- Carregamento do modelo: 0.00 s
- Resposta do modelo: A fotossíntese é um processo natural e fundamental que ocorre na parte verde das plantas, chamada de folhas, culminando na produção de energia e nutrientes para o organismo. \n\nEssa é a forma de absorção de energia da luz do sol pelo nosso planeta e uma parte do processo de carbono fixação que sustenta a vida. O processo acontece na forma de CO2 e água para produzir água e oxigênio, além de nutrientes como proteínas, açúcares, e outros complexos. \n\nPortanto, a fotossíntese é uma vitória e um fator essencial para a existência de vida na Terra, permitindo que os seres humanos e todas as formas de vida se desenvolvam e prosperem.

## Tempo de resposta do POST /api/chat
- Rodada 1 (pergunta geral, modelo frio): **338 ms** — ferramentas: 
  - resposta: Fotossíntese é a processo por meio do qual os seres vivos, como as plantas, convertem a luz do sol, água e gás dióxido de carbono em energia que as plantas usam para se nutrir.
- Rodada 2 (mesma pergunta, modelo quente): **323 ms** — ferramentas: 
  - resposta: A fotossíntese é a capacidade de algumas plantas, árvores, algas e outras células vivas, que usam a luz do sol para converter água, carbono dióxido e água em energia e oxigênio.
- Rodada 3 (mesma pergunta, modelo quente): **405 ms** — ferramentas: 
  - resposta: A fotossíntese é um processo que ocorre nas plantas, alga e certos tipos de algas que produzem energia usada para seus próprios processos biológicos, como o crescimento, respiração e combustição de aç
- Rodada 4 (pergunta com ferramenta weather): **2261 ms** — ferramentas: "weather"
  - resposta: Segundo as previsões da ferramenta, o tempo em Itapecerica da Serra esta semana será marcado por temperaturas variando entre 16.6°C (mínima) e 30.2°C (máxima). As temperaturas estão alentadoras, mas é
- Média com o modelo quente: 364 ms
- Primeira chamada (inclui aquecimento do modelo): 338 ms

## Uso de recursos dos containers
```text
NAME                          CPU %     MEM USAGE / LIMIT     MEM %
assistente-local-backend-1    0.89%     46.75MiB / 7.727GiB   0.59%
assistente-local-frontend-1   0.05%     15.67MiB / 7.727GiB   0.20%
assistente-local-kokoro-1     0.13%     2.009GiB / 7.727GiB   26.00%
x-monsters                    0.00%     37.54MiB / 7.727GiB   0.47%
portainer                     0.05%     63.5MiB / 7.727GiB    0.80%
```

## Memória persistente (storage do Docker)
```text
[
    {
        "CreatedAt": "2026-10-04T00:22:59-03:00",
        "Driver": "local",
        "Labels": {
            "com.docker.compose.config-hash": "a505dbed7c05b187620f3d76b9eee07a4397930676a188e7be15433586460598",
            "com.docker.compose.project": "assistente-local",
            "com.docker.compose.version": "5.5.1",
            "com.docker.compose.volume": "assistant-data"
        },
        "Mountpoint": "/var/lib/docker/volumes/assistente-local-data/_data",
        "Name": "assistente-local-data",
        "Options": null,
        "Scope": "local"
    }
]
```

- Itens guardados no volume: 0

## Estado dos serviços
```text
NAME                          IMAGE                                                                     COMMAND                  SERVICE    CREATED          STATUS                    PORTS
assistente-local-backend-1    assistente-local-backend                                                  "uvicorn app.main:ap…"   backend    22 seconds ago   Up 21 seconds (healthy)   8000/tcp
assistente-local-frontend-1   sha256:60bc7c4cdc5e2ed82c5abf437e1f9a1a433076e2f9ae4b7e73a99549dea631ca   "/docker-entrypoint.…"   frontend   8 minutes ago    Up 8 minutes (healthy)    80/tcp, 127.0.0.1:8080->8080/tcp
assistente-local-kokoro-1     ghcr.io/remsky/kokoro-fastapi-cpu:latest                                  "./entrypoint.sh"        kokoro     35 minutes ago   Up 35 minutes (healthy)   8880/tcp
```

## Testes automatizados do backend
```text
........................................................................ [ 59%]
.................................................                        [100%]
=============================== warnings summary ===============================
../usr/local/lib/python3.12/site-packages/fastapi/testclient.py:1
  /usr/local/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

## Logs recentes do backend
```text
backend-1  | INFO:     Started server process [1]
backend-1  | INFO:     Waiting for application startup.
backend-1  | INFO:     Application startup complete.
backend-1  | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
backend-1  | INFO:     172.20.0.4:36946 - "GET /health HTTP/1.1" 200 OK
backend-1  | INFO:     127.0.0.1:42728 - "GET /health HTTP/1.1" 200 OK
backend-1  | INFO:     127.0.0.1:42736 - "GET /health HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:36948 - "POST /api/chat HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:36958 - "GET /health HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:36950 - "POST /api/speak HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49008 - "POST /api/chat HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49014 - "POST /api/chat HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49018 - "POST /api/chat HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49040 - "POST /api/chat HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49058 - "GET /health HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49044 - "POST /api/speak HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49028 - "POST /api/chat HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49060 - "GET /health HTTP/1.1" 200 OK
backend-1  | INFO:     172.20.0.4:49066 - "GET /api/memories HTTP/1.1" 200 OK
backend-1  | INFO:     127.0.0.1:43802 - "GET /health HTTP/1.1" 200 OK
```

## Resumo

| Métrica | Valor |
| --- | --- |
| Tokens/s (Ollama, geração) | 196.30 |
| Chat — chamada fria | 338 ms |
| Chat — chamada quente (média) | 364 ms |
| Chat — chamada com ferramenta | 2261 ms |
| Memória livre no host | 754Mi livres de 7.7Gi |
| Itens na memória persistente | 0 |
| Falhas registradas | 0 |

Medições concluídas sem falhas. Relatório gravado em `docs/phase9-metrics.md`.
