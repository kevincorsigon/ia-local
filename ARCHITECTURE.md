# Arquitetura do Assistente Local

```mermaid
flowchart TB
    User[Usuário] --> UI[Interface web local\nRosto animado + chat + microfone]
    UI <-->|HTTP / WebSocket| API[Backend FastAPI\nOrquestrador]

    API --> State[Gestor de sessão\nContexto curto]
    API --> Guard[Guardrails\npt-BR, validações e limites]
    API --> Router{Roteador\nDados atuais?}
    Router -->|Pergunta geral| LLM[Ollama no host\nQwen 2.5 1.5B :11434]
    Router -->|Clima| Weather[Adaptador de clima]
    Router -->|Esportes| Sports[Adaptador esportivo]
    Router -->|Busca atual| Search[Adaptador de busca web]
    Router -->|Guardar ou listar| Mem[Memória do usuário]
    Weather --> Internet[APIs públicas externas]
    Sports --> Internet
    Search --> Internet
    Weather --> LLM
    Sports --> LLM
    Search --> LLM
    State --> LLM
    Guard --> LLM
    LLM --> Guard
    Guard --> API

    UI -->|áudio WebM/WAV| API
    API -->|encaminha áudio| STT[Vosk pt-BR\nFala para texto]
    STT -->|transcrição| API
    API -->|texto da resposta| TTS{Motor TTS configurável}
    TTS -->|TTS_ENGINE=kokoro| Kokoro[Kokoro pt-BR · pf_dora]
    TTS -->|TTS_ENGINE=piper| Piper[Piper pt-BR · dii]
    Kokoro -->|áudio WAV| UI
    Piper -->|áudio WAV| UI

    Wake[Detector local de alcunhas\nOpenWakeWord ou Vosk] -. frase reconhecida .-> UI
    UI -->|trecho de voz em memória| API

    Mem --> Data[(Volume Docker\nMemória persistente)]
    API --> Data
    subgraph Docker Compose
      UI
      API
      STT
      TTS
      Wake
      Data
    end

    subgraph Host WSL ou Ubuntu
      LLM
    end

    API <-->|HTTP API :11434\nhost.docker.internal| LLM

    classDef local fill:#dbeafe,stroke:#2563eb,color:#111827;
    classDef external fill:#fef3c7,stroke:#d97706,color:#111827;
    class UI,API,State,Guard,Router,Mem,STT,TTS,Wake,Data,LLM local;
    class Weather,Sports,Search,Internet external;
```

## Fluxo de uma pergunta

```mermaid
sequenceDiagram
    participant U as Usuário
    participant W as Interface web
    participant A as Backend
    participant R as Roteador
    participant T as Ferramenta atual
    participant O as Ollama
    participant P as Kokoro

    U->>W: Digita ou fala uma pergunta
    alt Pergunta falada
        W->>A: Envia áudio
        A-->>W: Texto transcrito
    end
    W->>A: Envia mensagem
    A->>R: Classifica intenção
    alt Dado atual necessário
        R->>T: Consulta fonte permitida
        T-->>A: Dados e URL da fonte
    end
    A->>O: Prompt pt-BR + contexto + dados
    O-->>A: Resposta
    A-->>W: Resposta e fontes
    A->>P: Texto limpo para voz
    P-->>W: Áudio WAV
    W-->>U: Rosto fala e reproduz áudio
```

## Memória persistente

```mermaid
sequenceDiagram
    participant U as Usuário
    participant W as Interface web
    participant A as Backend
    participant R as Roteador
    participant V as Volume Docker\nassistente-local-data
    participant O as Ollama

    U->>W: “Grave que eu moro em Itapecerica da Serra”
    W->>A: POST /api/chat
    A->>R: Classifica intenção
    R-->>A: memory
    A->>V: Grava memories.json (escrita atômica)
    A-->>W: Confirmação, sem chamar o modelo
    U->>W: Pergunta nova, em outra sessão
    A->>V: Lê o que está guardado
    A->>O: Prompt de sistema com persona e memória
    O-->>A: Resposta personalizada
```

O volume nomeado `assistente-local-data`, montado em `/data`, é storage do Docker: sobrevive a
`down`/`up` e à recriação do container. A gravação usa arquivo temporário + `os.replace`, e um
`memories.json` ilegível é preservado com o sufixo `.corrupt-<timestamp>.json` em vez de ser
sobrescrito. O bloco injetado no prompt respeita `MEMORY_PROMPT_CHARS` e é marcado como dado,
nunca como instrução. Se o volume falhar, o backend responde com aviso e mantém o chat de pé.

## Hospedagem do Ollama

| Cenário | Onde roda | Como o container alcança | Medido com qwen2.5:1.5b |
| --- | --- | --- | --- |
| Preferido: Windows com GPU | `ollama serve` no Windows, com `OLLAMA_HOST=0.0.0.0:11434` | `http://<gateway-do-WSL>:11434` | ~193 tokens/s (Radeon RX 9070 XT) |
| Reserva: WSL | `ollama serve` na distribuição Linux | `http://host.docker.internal:11434` | ~34 tokens/s (CPU) |

`scripts/ensure-ollama.sh` decide qual usar, grava a escolha em `data/ollama-mode.env` e o
bootstrap exporta `OLLAMA_BASE_URL` para o Compose. Rotas, prompts e ferramentas são idênticos
nos dois casos: muda apenas o host que gera o texto.

## Fronteiras de rede

| Origem | Destino | Permitido quando |
| --- | --- | --- |
| Navegador | Backend | Sempre, pela rede local. |
| Backend | Vosk e Kokoro | Sempre, dentro do Compose. |
| Backend | Ollama no host, porta `11434` | Sempre que gerar resposta, pela rota configurada de host gateway. |
| Backend | APIs externas | Somente quando o roteador aciona uma ferramenta. |
| Internet | Serviços internos | Nunca diretamente. |
