# Assistente de IA Local

Assistente local em pt-BR: Ollama roda no host; backend, interface e serviços de voz rodam em Docker. A interface é um console retrofuturista em CSS, desenhado para uma TV 1024×768, com a face da assistente em primeiro plano e chat em painel alternável. Inclui chat, persona configurável, ferramentas de clima e pesquisa, fala e escuta locais. A implementação ainda precisa de validação de ponta a ponta no Ubuntu/WSL e no Pentium J5040; consulte o acompanhamento na [especificação](SPEC.md).

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

O microfone do botão “Falar” é capturado pelo navegador; o áudio vai em memória ao backend, que usa FFmpeg e Vosk localmente para transcrever. A síntese roda no container Kokoro — imagem CPU do [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI), ~1,5 GB, com o modelo `v1_0` e as vozes já embutidos — com a voz feminina brasileira `pf_dora`, e devolve áudio WAV. Como o modelo vem na imagem, não há download no primeiro boot e a síntese funciona offline; a fonte da imagem pode ser trocada por `TTS_IMAGE` em `.env`. Áudio gravado não é salvo em disco pelo app.

No Ubuntu com Docker Engine, `host.docker.internal` é mapeado para o host por `host-gateway`. No WSL, escolha se o Ollama será executado na distribuição Linux ou no Windows e configure a URL correspondente. A API precisa responder tanto para o script como de dentro da rede Docker. A escuta por alcunhas envia clipes independentes de seis segundos para transcrição; ela não usa um detector acústico dedicado e pode ter latência ou falsos acionamentos.

O Ollama deve escutar numa interface alcançável pelos containers. O padrão `127.0.0.1` do host pode não ser acessível por uma rede bridge. Configure uma interface apropriada e restrinja a porta `11434` ao host/rede Docker com firewall; não publique a API na internet.

## Ollama: Windows (GPU) ou WSL (CPU)

O bootstrap procura primeiro um Ollama rodando no **Windows** e só usa o do **WSL** se não encontrar:

1. **Windows (preferido)** — rode o `ollama serve` com `$env:OLLAMA_HOST="0.0.0.0:11434"`, senão o WSL e os containers não conseguem alcançá-lo. O script `scripts/ollama-windows.ps1` já traz o comando completo (ROCm com `HSA_OVERRIDE_GFX_VERSION`, flash attention e a porta). Medido com a **Radeon RX 9070 XT**: **193 tokens/s** e respostas em ~330 ms.
2. **WSL (reserva)** — sem o Windows respondendo, o script sobe o Ollama do WSL e o usa na CPU: **34 tokens/s** e respostas em ~2.100 ms no mesmo modelo.

A escolha fica gravada em `data/ollama-mode.env` e o `OLLAMA_BASE_URL` dos containers é ajustado automaticamente (`http://<gateway-do-WSL>:11434` ou `http://host.docker.internal:11434`). `OLLAMA_PREFER_WINDOWS=0` no `.env` força o modo WSL; `OLLAMA_WINDOWS_HOST` fixa o IP, se a detecção automática não servir. Ao publicar o Ollama em `0.0.0.0`, restrinja a porta `11434` ao host/rede Docker com firewall.

## Iniciar

```bash
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

O bootstrap verifica o Ollama, tenta iniciar `ollama.service` em hosts Linux com systemd, espera a API responder, baixa o modelo se estiver ausente, prepara o Vosk, constrói e inicia os containers e confirma que backend, Ollama, modelo, STT e Kokoro respondem. No primeiro boot do Kokoro, o download do modelo de síntese pode levar alguns minutos. Em WSL sem systemd ou com Ollama no Windows, inicie o Ollama no ambiente escolhido antes de executar o script.

Abra [http://localhost:8080](http://localhost:8080), ou a porta definida em `.env`. O contexto das últimas oito trocas fica somente na memória do backend, expira após 30 minutos e não é salvo em disco. As mensagens visuais desaparecem ao recarregar a página.

## Memória persistente (storage do Docker)

As informações que você pede para guardar — “grave que eu moro em Itapecerica da Serra”, “lembre-se que eu prefiro café sem açúcar”, “anote: o portão abre com 4321” — são gravadas no volume nomeado **`assistente-local-data`**, montado em `/data` no backend. É storage do próprio Docker: sobrevive a `down`/`up` e à recriação do container. O conteúdo entra no prompt de sistema de toda conversa nova, então o que foi guardado serve de base para sessões futuras. Para listar o que já está guardado, pergunte “o que você lembra?” no chat.

```bash
# Ver o que está guardado e onde
curl http://localhost:8080/api/memories

# Apagar um item ou limpar tudo
curl -X DELETE http://localhost:8080/api/memories/<id>
curl -X DELETE http://localhost:8080/api/memories

# Inspecionar o volume do Docker
docker volume inspect assistente-local-data
```

`MAX_MEMORIES` em `.env` limita quantos itens ficam guardados (padrão 200); ao atingir o limite, os mais antigos saem. Se o volume ficar indisponível, o chat continua respondendo e avisa que não conseguiu guardar. Apagar o volume (`docker compose ... down -v`) remove toda a memória.

## Conversa só por voz (alcunhas)

Com **“Ativar alcunhas”** ligado, nada mais precisa de clique: a preferência fica salva no navegador e o assistente volta a escutar quando você recarrega a página. O rótulo embaixo do rosto mostra só o essencial — `Diga "Kunica" quando quiser falar` ou `Ouvindo…`; os detalhes técnicos ficam no terminal de debug.

1. Diga a alcunha **e** a pergunta na mesma fala — *“TVzinha, qual é a previsão do tempo?”*. O trecho depois da alcunha vai direto para o modelo e a resposta é falada; o painel de chat pode continuar fechado.
2. **Conversa contínua:** depois de responder, o assistente mantém a conversa ativa por `conversation_seconds` (60 s por padrão, em `config/assistant.yaml`). Fale normalmente, **sem repetir a alcunha**, como num chat — cada fala renova o tempo, e o relógio reinicia quando a resposta termina de ser falada. Passando esse tempo sem nenhuma fala, ele volta a esperar a alcunha.
3. Diga só a alcunha: ele responde uma saudação e abre a janela curta de continuação (`follow_up_seconds`, 8 s); a próxima fala já vai para o modelo e inicia a conversa contínua.
4. O botão **“Falar”** funciona igual: fale e pare. A captura termina sozinha no silêncio (detecção de fala no navegador) e a mensagem é enviada sem clicar em “Enviar”. Um segundo toque encerra a captura na hora.

A alcunha é reconhecida no backend (`backend/app/wake.py`, coberto por testes) porque o Vosk pt-BR não conhece esses nomes: ele transcreve “Kunica” como “única” ou “econômica” e “TVzinha” como “vizinha”. A comparação aceita essas trocas no início da fala e recusa parecidos no meio da frase — *“a única opção que eu tenho”* não aciona nada.

Medido com áudio sintetizado: *“TVzinha, …”*, *“Minha puta, …”* e *“Kunica, …”* funcionam; dizer apenas “Kunica” ou “Ei TV” costuma virar nada ou “vê” na transcrição, porque essas palavras não existem no vocabulário do modelo pequeno. Prefira frases com mais de uma palavra e fale a alcunha junto da pergunta.

Se algo não funcionar, o rótulo de estado mostra o motivo:

| O que aparece | Significado |
| --- | --- |
| `Calibrando o microfone…` | o navegador está medindo o ruído para definir o limiar de fala |
| `… mic "Microfone (USB)" · nível 42% (limiar 6%) · 28 KB · gravando` | o áudio está chegando e a fala foi detectada |
| `nível 0% … · 0 KB` mesmo falando | o navegador não está recebendo áudio: microfone errado, sem permissão ou mudo |
| `Gravei quase nada. Confira o microfone em chrome://settings/content/microphone…` | a captura terminou com menos de 3 KB de áudio |
| `Não ouvi nada. Diga "Kunica" e a pergunta na mesma fala.` | a gravação ficou abaixo de 8 KB: microfone silencioso |
| `Ouvi um som, mas não entendi as palavras.` | o áudio chegou, mas o Vosk não formou palavras: fale mais perto ou mais devagar |
| `Ouvi "…". Chame a Kunica para falar.` | transcreveu sem alcunha: fale a alcunha junto da pergunta |

A gravação começa no instante em que você clica em “Falar” (ou quando as alcunhas estão ligadas) e o
detector de fala serve apenas para encerrá-la: sem fala detectada, ela é encerrada em 8 segundos e o
áudio gravado é transcrito do mesmo jeito. Assim nenhum áudio é perdido se o medidor de nível falhar.

Se o nível ficar perto de 0% mesmo falando, o navegador está usando outro microfone ou o ganho está baixo — confira em `chrome://settings/content/microphone`.

### Escolher o microfone

No painel **Debug áudio** (botão no topo, à direita), o seletor **MICROFONE** lista as entradas de áudio e a
barrinha ao lado mostra o nível ao vivo (fica verde quando há fala e vermelha quando não chega áudio). A
escolha fica salva no navegador e passa a valer na hora, inclusive para as alcunhas; se o dispositivo
escolhido desaparecer (Bluetooth desligado, por exemplo), o app volta ao padrão sozinho e avisa no painel.

Fones Bluetooth em modo “Fones de ouvido” (A2DP) são **apenas saída de áudio**: o Chrome os oferece como
entrada, mas nada é captado — é o caso típico do nível em 0% com 0 KB. Escolha o microfone do computador no
seletor ou coloque o fone em modo **Headset/Handsfree** no Windows (aparece como um segundo dispositivo, com
microfone). A linha `microfones na interface: [...]` do painel lista todas as opções disponíveis.

### Terminal de debug

O botão **Debug áudio**, no topo à direita, abre um painel terminal na parte inferior com o microfone, o medidor
de nível e **os mesmos logs** que vão para o console (prefixo `[kunica]`) — sem precisar abrir o F12. Os botões
**Limpar** e **Copiar** servem para limpar a tela e levar o histórico para a área de transferência ao relatar um
problema. O mesmo conteúdo aparece em **F12 → Console**; clique em “Falar” e cada etapa registra o que recebeu:

```text
[kunica] botão Falar: iniciando
[kunica] microfone obtido — label="Microphone (USB Audio)" estado=live mudo=false ativo=true taxa=48000Hz canais=1
[kunica] microfones disponíveis: ["Microphone (USB Audio)", "Stereo Mix (Realtek)"]
[kunica] AudioContext: running | taxa 48000 Hz
[kunica] captura iniciada — label="Microphone (USB Audio)" … | gravador: audio/webm;codecs=opus
[kunica] calibração: ruído 0.0021 → limiar de fala 0.0200
[kunica] nível 12% (limiar 2%) · fala 0 ms · silêncio 0 ms · 8 KB · 1000 ms
[kunica] fala detectada — paro quando você ficar em silêncio
[kunica] nível 31% (limiar 2%) · fala 620 ms · silêncio 0 ms · 24 KB · 1800 ms
[kunica] captura encerrada (silêncio após a fala) — fala: sim | pico 31% | 48211 bytes | blob 48211 bytes
[kunica] transcrição (612 ms, 48211 bytes): {"text":"olá kunica que horas são","confidence":0.93}
[kunica] enviando ao backend: olá kunica que horas são
[kunica] resposta em 348 ms | ferramentas: [] | fontes: 0
[kunica] áudio de voz: 152048 bytes
```

Leitura rápida: `mudo=true` ou `estado=ended` no microfone, `AudioContext: suspended`, `nível 0%` contínuo ou
`0 bytes` na captura apontam problema antes do backend; `transcrição` vazia com áudio grande aponta o Vosk.

## Testes

```bash
docker compose --env-file .env --profile core --profile voice exec backend pytest -q
```

A suíte roda offline: Ollama, Open-Meteo, Brave Search e Kokoro são simulados e a memória persistente é gravada em um diretório temporário. Ela cobre roteamento de intenções, memória (gravar, listar, persistir, apagar), validações da API, falhas do Ollama e o guardrail de conteúdo externo.

## Validação e medições

```bash
./scripts/healthcheck.sh   # percurso completo: chat, clima, busca, voz e memória persistente
./scripts/measure.sh       # grava tokens/s, latências, recursos e testes em docs/phase9-metrics.md
```

## Operação

```bash
docker compose --env-file .env --profile core ps
docker compose --env-file .env --profile core logs -f backend
docker compose --env-file .env --profile core down
```

## O que falta validar

- Repetir build, bootstrap e medições no Ubuntu e no Pentium J5040 (as medições registradas usam a GPU do Windows).
- Testar o microfone real, com ruído: taxa de falso positivo/negativo das alcunhas e ajuste do limiar de silêncio (`VAD_SILENCE_MS` em `frontend/src/app.js`).
- Ouvir a qualidade da voz `pf_dora` no uso real e ajustar o tamanho das respostas para o J5040.
