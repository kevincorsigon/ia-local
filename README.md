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

O microfone do botão “Falar” é capturado pelo navegador; o áudio vai em memória ao backend, que usa FFmpeg e o motor local de fala para transcrever — Whisper por padrão (`STT_ENGINE=whisper`), com Vosk como alternativa rápida e menos precisa. A síntese usa Kokoro por padrão (`TTS_ENGINE=kokoro`), com a voz brasileira `pf_dora`, ou Piper como alternativa leve (`TTS_ENGINE=piper`), com a voz `dii`. O Kokoro usa uma imagem CPU do [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI), ~1,5 GB, com modelo e vozes embutidos; o Piper constrói uma imagem local menor, com o modelo pt-BR baixado durante o build. Ambos devolvem WAV e funcionam offline depois de preparados. Para trocar, ajuste `TTS_ENGINE` no `.env` e rode `./scripts/bootstrap.sh`; o bootstrap constrói e inicia o profile correto. Deixe `TTS_VOICE` vazio para usar a voz padrão do motor, ou preencha para escolher uma voz compatível. `TTS_IMAGE` só altera a imagem do Kokoro. Áudio gravado não é salvo em disco pelo app.

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

### Memória como regra das ferramentas

Além de personalizar as respostas, a memória alimenta **as ferramentas**. Uma memória que manda usar
uma fonte funciona como guideline da busca:

> “Grave que, quando eu perguntar sobre o Corinthians, você deve usar o site meutimao.com.br.”

A partir daí, perguntas sobre o Corinthians vão para a ferramenta de esportes com `meutimao.com.br` na
consulta e as fontes desse site vêm primeiro na lista. A regra vale só para o assunto citado — a mesma
memória não desvia perguntas sobre outro time. Se a regra não citar assunto (“sempre olhe primeiro no
meu Timão.com”), ela vale apenas como preferência de ordem, sem mudar a consulta, para não desviar
perguntas de outros temas.

Também passou a valer “salve na memória” (antes só “grave/lembre-se/anote” eram reconhecidos). Para
conferir o que está guardado: `curl http://localhost:8080/api/memories`.

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

### Qualidade do reconhecimento (modelo de fala)

O motor é escolhido no `.env` por `STT_ENGINE`. Medições deste projeto em fala espontânea:

| Motor | Modelo | Erro por palavra | Tempo por frase | Quando usar |
| --- | --- | --- | --- | --- |
| `whisper` | `small` (int8) | baixo — acerta nomes próprios | ~2–3 s | **padrão recomendado** |
| `vosk` | `vosk-model-pt-fb-v0.1.1-20220516_2113` (1,6 GB) | ~54 % | 0,04–0,16 s | só se a velocidade importar mais que a precisão |
| `vosk` | `vosk-model-small-pt-0.3` (31 MB) | ~69 % | ~0,05 s | máquinas muito fracas (Raspberry/J5040) |

O Vosk é dezenas de vezes mais rápido, mas em conversa livre troca **muitas** palavras — é ele que
“confunde” o que você fala. O Whisper entende bem mais, inclusive nomes próprios, e é o padrão
(`STT_ENGINE=whisper`).

Três ajustes entram junto com o Whisper e fazem diferença na precisão:

- **`WHISPER_BEAM_SIZE=5`** (o código usava `1`, decodificação gulosa): menos trocas de palavra ao
  custo de um pouco mais de CPU.
- **Vocabulário do assistente** como `initial_prompt`: o nome e as alcunhas do `config/assistant.yaml`
  enviesam o decoder (é o que evita `Kunica` virar `cônica`). Para reforçar, defina
  `WHISPER_INITIAL_PROMPT` no `.env` com nomes de cidades e jargão do seu dia a dia.
- **Microfone sem supressão de ruído** (`frontend/src/app.js`): o processamento de “chamada de voz”
  corta pedaços das palavras. Cancelamento de eco e ganho automático continuam ligados.

Para trocar o tamanho do modelo do Whisper: `WHISPER_MODEL=medium` erra ainda menos (bem mais lento em
CPU) e `base`/`tiny` são mais rápidos e mais imprecisos.

O modelo do Whisper é baixado na primeira vez (~460 MB para o `small`) e fica no volume Docker
(`/data/whisper`). Se ficar no Vosk, o modelo fica em `backend/models/` (fora do Git), com licença
**GPLv3** para o grande (projeto FalaBrasil), e o primeiro carregamento consome alguns GB de RAM.

### Resposta falada em trechos

O Kokoro sintetiza em CPU: uma resposta inteira leva ~4 s para virar áudio. Para a fala começar
quase junto com o texto na tela, o `app.js` fatia a resposta em frases e mantém o **primeiro trecho
bem curto** (uma oração, ~70 caracteres, cortando na vírgula quando dá); ele toca assim que chega —
em geral bem antes de 1 s — enquanto já sintetiza o trecho seguinte (até ~220 caracteres). O tempo
total não muda, mas a primeira palavra sai bem antes. O botão **Parar áudio** interrompe a fila
inteira.

A página também **aquece o sintetizador** ao abrir (um `/api/speak` com texto curto, descartado):
sem isso a primeira resposta pagaria o carregamento do modelo do Kokoro junto com a espera do som.
No painel **Debug áudio** dá para ver a conta de cada etapa: `resposta em N ms` (chat) e
`voz: primeiro áudio pronto em N ms` (síntese).

Enquanto a resposta é falada, o rosto fica em `speaking` e a boca abre e fecha durante **todo** o
áudio: a escuta por alcunhas espera o fim da fala. Antes ela recomeçava no meio da síntese e
reescrevia o estado para `listening` a cada 80 ms, o que congelava a boca.

### Tela cheia

O “gráfico” de barras no canto superior esquerdo da barra de título é um botão: um clique coloca o
console em tela cheia e outro clique (ou `Esc`) volta ao normal. Enquanto a tela cheia está ativa, o
botão fica realçado. Em navegadores que não oferecem a Fullscreen API (ou dentro de um iframe
restrito), o botão fica desabilitado e o restante da interface segue igual.

### Comando de pesquisa na internet

Digite ou fale **“pesquisa na internet”**, **“pesquisa no google”**, **“pesquise”**, **“busque”** ou
**“google”** seguido do assunto: o comando sai e só o restante vira a consulta. Ex.:
“pesquisa na internet qual a capital da Austrália” procura por *qual a capital da Austrália* — e não
pelo comando inteiro.

Se você falar só o comando (“pesquisa na internet”), o assistente pergunta o que pesquisar e trata a
**próxima fala** como o termo da busca, na mesma sessão.

### O que o assistente consegue fazer

O catálogo das ferramentas fica em `config/assistant.yaml`, em `capabilities` (cada item tem `title`
e `detail` com um exemplo de pergunta). Ele vai no **prompt do sistema**, então perguntas como
“quais ferramentas você tem?” ou “o que você consegue fazer?” são respondidas pelo próprio modelo com
a lista real — e o prompt deixa explícito que essa é a lista completa, para ele não inventar
capacidades que não existem.

O mesmo catálogo sai em `GET /api/capabilities` (útil para conferir) e, se você remover a chave do
YAML, o backend usa um padrão embutido. Para anunciar outra coisa, basta editar o YAML e recriar o
backend.

As respostas saem em **texto simples**: o backend remove a formatação de markdown que o modelo
insiste em usar (`**negrito**`, listas com `*`, `#` de título, crases) e os **emojis** antes de
devolver — `*   **Clima:** 🙂 item` vira `- Clima: item`. Isso é necessário porque o balão do chat
mostra o texto literal (não renderiza markdown) e o sintetizador de voz leria os asteriscos. O prompt
também pede texto simples e sem emoji; a limpeza no código é a garantia, já que modelo pequeno nem
sempre obedece.

A limpeza é conservadora de propósito: valores técnicos (`14.4°C`, `94%`, datas, `;`), sublinhados de
URLs (`meutimao.com.br/jogos_do_dia`) e setas comuns (`→`) ficam intactos.

### Quando o clima pede a cidade

Se a cidade sair errada na fala (o reconhecedor troca nomes próprios — “Itapecerica da Serra” vira
“Tápicirica da Serra”), o assistente responde que não encontrou e **espera a correção**: a próxima
fala é tratada como a cidade, não como conversa livre. Isso evita o pior caso, que era o modelo
inventar uma previsão com números que não vieram de ferramenta nenhuma.

O estado é aceito junto e descartado na consulta: “Itapecerica da Serra, SP”, “Itapecerica da Serra,
São Paulo” e “... estado de São Paulo” consultam a mesma cidade. Para reduzir os erros na origem,
liste suas cidades em `WHISPER_INITIAL_PROMPT` no `.env` (ver “Qualidade do reconhecimento”).

### Contexto da conversa

O backend guarda as últimas `max_history_turns` falas de cada sessão (padrão 8, em
`config/assistant.yaml`) e envia esse histórico ao modelo em toda mensagem — é assim que ele sabe
que você está falando de algo já comentado. A sessão expira após `session_ttl_minutes` sem uso
(padrão 30).

Todas as respostas entram no histórico, inclusive as prontas das ferramentas (pedir a cidade, pedir
o termo da busca), para o modelo nunca ficar com “buracos” do que ele mesmo disse. O identificador
da sessão fica no `localStorage` do navegador e a interface repõe as bolhas via
`GET /api/session/<id>` ao abrir a página, então recarregar ou fechar/reabrir a aba mantém a conversa
— o que você vê é o mesmo contexto que o modelo recebe.

Para começar do zero, limpe os dados do site no navegador (DevTools → Application → Local Storage)
ou espere o TTL da sessão.

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

## Problemas comuns (Linux/NUC)

**`./scripts/bootstrap.sh: linha 38: docker: comando não encontrado`** (ou qualquer `docker: comando não encontrado`).
O Docker Engine não está instalado — ou o usuário ainda não está no grupo `docker`. No Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker          # ou saia e entre na sessão
docker compose version # precisa imprimir a versão do plugin v2
./scripts/bootstrap.sh
```

O pacote `docker.io` do Ubuntu já traz o Engine; `docker-compose-v2` é o plugin que o bootstrap chama
(`docker compose`, com espaço). Sem o grupo `docker`, o comando existe mas o daemon recusa a conexão.

**`Error: listen tcp 0.0.0.0:11434: bind: address already in use` ou o bootstrap não acha o Ollama.**
Há mais de um Ollama disputando a porta. Deixe o serviço do `systemd` como dono dela:

```bash
sudo pkill -f 'ollama serve'          # derruba instâncias soltas
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
ss -tlnp | grep 11434                 # precisa mostrar 0.0.0.0:11434
curl -s http://127.0.0.1:11434/api/tags | head -c 80
```

O `OLLAMA_HOST=0.0.0.0` é obrigatório: com o padrão `127.0.0.1` o **container não alcança** o Ollama
do host, e o bootstrap para em "Os containers não alcançaram o Ollama". Restrinja a porta `11434` ao
host/rede Docker com firewall — não a exponha à internet.

**O bootstrap para pedindo senha.** Os scripts usam `sudo -n`, que nunca pede senha. Se o seu `sudo`
exige senha, deixe o Ollama já rodando antes de executar; se ele avisar no meio do caminho, rode
`sudo systemctl restart ollama` e execute `./scripts/bootstrap.sh` de novo (é idempotente).

**`.env` editado no Windows.** Chega em CRLF e o `\r` entra dentro do valor (modelo, porta, store),
quebrando o script. O `bootstrap.sh` normaliza sozinho; confira com `grep -c $'\r' .env` — o esperado
é `0`.

**Acessar de outra máquina da casa.** O Compose publica a interface só em `127.0.0.1`. Para abrir na
LAN, troque no `compose.yaml` a porta por `"${WEB_PORT:-8080}:8080"` — sem autenticação, mantenha na
rede local — ou use um túnel SSH (`ssh -L 8080:localhost:8080 usuario@nuc`).

## Espaço em disco no NUC

O build das imagens, o Kokoro (~1,5 GB) e os modelos de fala pedem alguns GB. O `bootstrap.sh` avisa
antes de começar quando falta espaço; se o build já falhou com `No space left on device`, comece pelo
diagnóstico:

```bash
df -h
sudo docker info | grep -i "root dir"    # onde o Docker guarda de verdade
sudo du -xh --max-depth=1 /var 2>/dev/null | sort -h | tail
sudo du -xh --max-depth=1 /home 2>/dev/null | sort -h | tail
sudo du -sh /usr/share/ollama/.ollama
du -sh ~/.ollama ~/ia-local/data ~/.cache 2>/dev/null
docker system df
journalctl --disk-usage
```

Duas armadilhas de leitura: o `SIZE` do `docker system df` soma as camadas e conta as compartilhadas
mais de uma vez, então é maior que o `du` do diretório — use o `root dir` acima para achar o caminho
real antes de concluir qualquer coisa. E se existir `~/.ollama` junto com
`/usr/share/ollama/.ollama`, você tem **dois stores**: o do serviço (`ollama.service`) e uma cópia
órfã de um `ollama serve`/`ollama pull` rodado como usuário comum. Confira com `ollama list` (que fala
com a API, portanto mostra o store do serviço) antes de apagar o da sua home.

Em seguida, do mais seguro ao mais pesado:

```bash
# 1. cache de build e imagens penduradas (não toca em volume)
docker builder prune -af
docker image prune -f

# 2. pacotes e logs do sistema
sudo apt-get clean
sudo apt-get autoremove --purge -y
sudo journalctl --vacuum-size=50M

# 3. lixeira, cache do usuário e revisões antigas de snap
rm -rf ~/.local/share/Trash/* ~/.cache/thumbnails
sudo snap list --all | awk '/disabled/{print $1, $3}'
```

**Modelos do Ollama.** Eles ficam em `/usr/share/ollama/.ollama/models` — o serviço roda como usuário
`ollama`, então o peso deles **não aparece na sua home** nem no `du` de `~`. Veja o que existe e
remova tudo menos o `OLLAMA_MODEL` do `.env`:

```bash
grep '^OLLAMA_MODEL=' .env          # qual modelo o assistente usa (ex.: qwen2.5:1.5b)
ollama list                         # nome e tamanho de cada modelo baixado
sudo du -sh /usr/share/ollama/.ollama/models
ollama rm <nome-do-modelo-que-nao-usa>
```

Remova um por vez e confira com `ollama list` antes de seguir. Rebaixar `WHISPER_MODEL` de `small`
para `base` também economiza ~300 MB no volume — mas só depois de tudo funcionar.

**Blobs.** Os dados ficam em `.../models/blobs` e o `ollama rm` já descarta os que deixam de ser
referenciados por um manifesto. O que nenhum comando do CLI limpa são os blobs de `pull`
interrompido — compare o que existe com o que é referenciado:

```bash
sudo bash -c '
S=/usr/share/ollama/.ollama/models
find "$S/manifests" -type f -print0 | xargs -0 cat | grep -o "sha256:[0-9a-f]*" | sort -u > /tmp/u
find "$S/blobs" -type f -printf "%f\n" | sed "s/^sha256-/sha256:/" | sort -u > /tmp/e
du -sh "$S/blobs"
echo "--- órfãos (seguros de apagar) ---"
comm -13 /tmp/u /tmp/e
'
```

Só apague o que o `comm -13` listar: remover um blob ainda referenciado corrompe o modelo e a única
recuperação é um `ollama pull` novo. Para apagar de fato:

```bash
sudo bash -c 'S=/usr/share/ollama/.ollama/models; comm -13 /tmp/u /tmp/e | while read -r d; do rm -f "$S/blobs/${d/:/-}"; done'
```

Se a lista de órfãos vier vazia — o caso mais comum — todo o peso é de modelos registrados e não há o
que apagar em `blobs`: a limpeza é o `ollama rm` dos modelos que você não usa.

Se ainda faltar espaço, pare os containers e remova tudo **menos volumes**:

```bash
docker compose --env-file .env --profile core --profile voice down
docker system prune -af          # NUNCA --volumes
```

Nada disso mexe no volume `assistente-local-data`, onde fica a memória do assistente. Um
`docker system prune --volumes` apagaria essa memória junto — por isso o aviso acima.

## Iniciar junto com o Ubuntu (console de TV)

Para o NUC ligar e já mostrar o assistente na TV:

```bash
bash scripts/install-autostart.sh        # (ou ./scripts/install-autostart.sh, com chmod +x)
```

Ele faz três coisas (idempotente):

1. habilita `docker.service` e `ollama.service` no boot;
2. cria o serviço de sistema **`assistente-local`**, que roda o `scripts/bootstrap.sh` no boot — como
   o **seu usuário**, para não criar arquivos do root dentro do repositório;
3. cria um autostart gráfico (`~/.config/autostart/assistente-console.desktop`) que abre o
   **navegador padrão** em `http://localhost:<WEB_PORT>` **quando a interface responde**
   (`scripts/open-frontend.sh` espera até 3 minutos — o primeiro boot é lento por causa dos
   downloads).

Controle:

```bash
sudo systemctl start assistente-local      # subir agora, sem reiniciar
systemctl status assistente-local
journalctl -u assistente-local -f          # acompanhar a subida
```

Dois ajustes que só se fazem uma vez:

- **Login automático** do usuário (Configurações → Usuários), senão o autostart gráfico não roda —
  ele depende da sessão gráfica.
- O usuário precisa estar no grupo **`docker`**: `sudo usermod -aG docker $USER` e saia/entre na
  sessão. O instalador avisa se faltar.

Para abrir em tela cheia de verdade, troque a linha final do `scripts/open-frontend.sh` por
`exec chromium-browser --kiosk "$URL"` (ou use o botão de tela cheia do próprio console — o gráfico
de barras no canto superior esquerdo).

Para desfazer:

```bash
sudo systemctl disable --now assistente-local
sudo rm /etc/systemd/system/assistente-local.service
rm ~/.config/autostart/assistente-console.desktop
sudo systemctl daemon-reload
```

## O que falta validar

- Repetir build, bootstrap e medições no Ubuntu e no Pentium J5040 (as medições registradas usam a GPU do Windows).
- Testar o microfone real, com ruído: taxa de falso positivo/negativo das alcunhas e ajuste do limiar de silêncio (`VAD_SILENCE_MS` em `frontend/src/app.js`).
- Ouvir a qualidade da voz `pf_dora` no uso real e ajustar o tamanho das respostas para o J5040.
