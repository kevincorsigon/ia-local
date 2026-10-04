# Assistente de IA Local

Assistente local em pt-BR: Ollama roda no host; backend, interface e serviços de voz rodam em Docker. Inclui chat, persona configurável, ferramentas de clima e pesquisa, fala e escuta locais e um rosto animado. A implementação ainda precisa de validação de ponta a ponta no Ubuntu/WSL e no Pentium J5040; consulte o acompanhamento na [especificação](SPEC.md).

## Pré-requisitos

- Docker Engine e Docker Compose v2.
- Ollama instalado e iniciado diretamente no host.
- CLI `ollama` e `curl` disponíveis no host que executa o bootstrap.
- Docker capaz de alcançar o Ollama na URL configurada em `OLLAMA_BASE_URL`.
- 8 GB de RAM como referência inicial; medir uso e velocidade no Pentium J5040.

## Configurar

```bash
cp .env.example .env
```

`OLLAMA_HOST_URL` é usado pelo script no host. `OLLAMA_BASE_URL` é usado pelo backend dentro do container. Revise essas URLs conforme sua instalação no Ubuntu/WSL, além do modelo e da porta web.

Edite `config/assistant.yaml` para mudar o nome, a personalidade, as alcunhas e o tempo de continuação. A escuta contínua é opcional e começa somente quando o usuário ativa “Ativar alcunhas” na interface.

O clima consulta Open-Meteo somente quando a pergunta pede previsão e inclui uma cidade brasileira. Pesquisa geral e jogos usam Brave Search: configure `BRAVE_SEARCH_API_KEY` em `.env` para ativá-los. O Docker Compose injeta essa variável no container do backend em tempo de execução; a chave não é copiada para a imagem nem para o frontend. Sem ela, o assistente informa que a pesquisa precisa ser configurada. O código não consulta a web para perguntas gerais.

O microfone do botão “Falar” é capturado pelo navegador; o áudio vai em memória ao backend, que usa FFmpeg e Vosk localmente para transcrever. O Piper usa a voz local `pt_BR-faber-medium` para gerar áudio WAV depois das respostas. O bootstrap baixa os arquivos Vosk/Piper para `backend/models/` e `piper/voices/` (ignorados pelo Git). Esses downloads são feitos de [Vosk Models](https://alphacephei.com/vosk/models) e [Piper Voices](https://huggingface.co/rhasspy/piper-voices); áudio gravado não é salvo em disco pelo app.

No Ubuntu com Docker Engine, `host.docker.internal` é mapeado para o host por `host-gateway`. No WSL, escolha se o Ollama será executado na distribuição Linux ou no Windows e configure a URL correspondente. A API precisa responder tanto para o script como de dentro da rede Docker. A escuta por alcunhas envia clipes independentes de seis segundos para transcrição; ela não usa um detector acústico dedicado e pode ter latência ou falsos acionamentos.

O Ollama deve escutar numa interface alcançável pelos containers. O padrão `127.0.0.1` do host pode não ser acessível por uma rede bridge. Configure uma interface apropriada e restrinja a porta `11434` ao host/rede Docker com firewall; não publique a API na internet.

## Iniciar

```bash
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

O bootstrap verifica o Ollama, tenta iniciar `ollama.service` em hosts Linux com systemd, espera a API responder, baixa o modelo se estiver ausente, prepara os modelos Vosk/Piper, constrói e inicia os containers e confirma que backend, Ollama, modelo, STT e Piper respondem. Em WSL sem systemd ou com Ollama no Windows, inicie o Ollama no ambiente escolhido antes de executar o script.

Abra [http://localhost:8080](http://localhost:8080), ou a porta definida em `.env`. O contexto das últimas oito trocas fica somente na memória do backend, expira após 30 minutos e não é salvo em disco. As mensagens visuais desaparecem ao recarregar a página.

## Operação

```bash
docker compose --env-file .env --profile core ps
docker compose --env-file .env --profile core logs -f backend
docker compose --env-file .env --profile core down
```

## O que falta validar

- Fazer o build e iniciar os serviços com Docker no WSL e no Ubuntu.
- Validar Ollama no host, downloads Vosk/Piper, gravação pelo navegador e reprodução de áudio.
- Medir latência, memória, uso de CPU e taxa de falso acionamento no Pentium J5040; ajustar modelo e duração dos clipes conforme os resultados.
