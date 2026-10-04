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
    API -->|texto da resposta| TTS[Piper pt-BR\nTexto para fala]
    TTS -->|áudio WAV| UI

    Wake[Detector local de alcunhas\nOpenWakeWord ou Vosk] -. frase reconhecida .-> UI
    UI -->|trecho de voz em memória| API

    API --> Data[(Volume local\nSessões e logs)]
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
    class UI,API,State,Guard,Router,STT,TTS,Wake,Data,LLM local;
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
    participant P as Piper

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

## Fronteiras de rede

| Origem | Destino | Permitido quando |
| --- | --- | --- |
| Navegador | Backend | Sempre, pela rede local. |
| Backend | Vosk e Piper | Sempre, dentro do Compose. |
| Backend | Ollama no host, porta `11434` | Sempre que gerar resposta, pela rota configurada de host gateway. |
| Backend | APIs externas | Somente quando o roteador aciona uma ferramenta. |
| Internet | Serviços internos | Nunca diretamente. |
