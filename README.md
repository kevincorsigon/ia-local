# Assistente de IA Local

Assistente em pt-BR com Ollama executando no host e interface local em Docker. A primeira implementação cobre chat textual, persona configurável e contexto curto mantido apenas em memória. Voz e ferramentas web estão descritas na [especificação](SPEC.md) para as próximas etapas.

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

Edite `config/assistant.yaml` para mudar o nome e a personalidade. As alcunhas já ficam configuradas ali para a etapa futura de ativação por voz.

O clima consulta Open-Meteo somente quando a pergunta pede previsão e inclui uma cidade brasileira. Pesquisa geral e jogos usam Brave Search: configure `BRAVE_SEARCH_API_KEY` em `.env` para ativá-los. A chave fica somente no backend; sem ela, o assistente informa que a pesquisa precisa ser configurada. O código não consulta a web para perguntas gerais.

No Ubuntu com Docker Engine, `host.docker.internal` é mapeado para o host por `host-gateway`. No WSL, escolha se o Ollama será executado na distribuição Linux ou no Windows e configure a URL correspondente. A API precisa responder tanto para o script como de dentro da rede Docker.

O Ollama deve escutar numa interface alcançável pelos containers. O padrão `127.0.0.1` do host pode não ser acessível por uma rede bridge. Configure uma interface apropriada e restrinja a porta `11434` ao host/rede Docker com firewall; não publique a API na internet.

## Iniciar

```bash
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

O bootstrap verifica o Ollama, tenta iniciar `ollama.service` em hosts Linux com systemd, espera a API responder, baixa o modelo se estiver ausente, valida o Compose, constrói e inicia os containers. Em WSL sem systemd ou com Ollama no Windows, inicie o Ollama no ambiente escolhido antes de executar o script.

Abra [http://localhost:8080](http://localhost:8080), ou a porta definida em `.env`. O contexto das últimas oito trocas fica somente na memória do backend, expira após 30 minutos e não é salvo em disco. As mensagens visuais desaparecem ao recarregar a página.

## Operação

```bash
docker compose --env-file .env --profile core ps
docker compose --env-file .env --profile core logs -f backend
docker compose --env-file .env --profile core down
```

## Próximas etapas

- Persona, contexto curto de sessão em memória e configuração das alcunhas de ativação.
- Ferramentas de clima (Open-Meteo) e pesquisa/esportes (Brave Search, requer chave).
- Piper para síntese e Vosk para reconhecimento de fala.
- Integração visual dos estados do rosto, palavra de ativação local e medições no J5040.
