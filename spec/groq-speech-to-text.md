# Spec: transcrição de áudio via Groq

**Status:** proposta; não implementada  
**Escopo:** substituir ou complementar a transcrição local da Kunica com uma API hospedada. A conversa, o LLM e o TTS continuam nos provedores atualmente configurados.

## Objetivo

Reduzir o tempo de transcrição no NUC enviando o áudio ao endpoint de Speech-to-Text da Groq. A API recebe áudio e devolve o texto; o restante do fluxo de voz continua usando `/api/chat` e `/api/speak` como hoje.

## Experiência esperada

1. A pessoa grava uma fala pelo navegador como hoje.
2. A interface envia o arquivo para `POST /api/transcribe`.
3. O backend valida tamanho e duração, normaliza o áudio e chama a Groq quando o motor selecionado for `groq`.
4. A Kunica devolve o texto transcrito no mesmo formato de resposta atual. Quando o fluxo pede detecção da wake word, o backend também executa a verificação local sobre o texto reconhecido.
5. A fala transcrita segue pelo mesmo fluxo de chat; nenhum áudio é enviado diretamente ao provedor de LLM ou TTS por causa desta mudança.

## Provedor e contrato

- Endpoint de transcrição: `POST https://api.groq.com/openai/v1/audio/transcriptions`.
- Autenticação: `Authorization: Bearer <GROQ_API_KEY>`, enviada somente pelo backend.
- Modelo inicial recomendado: `whisper-large-v3-turbo`, por priorizar velocidade e custo. Permitir trocar para `whisper-large-v3` por configuração se a avaliação em português mostrar melhor qualidade.
- Enviar `language=pt`, `response_format=json` e um prompt curto com o nome Kunica, alcunhas e termos de domínio disponíveis no backend. A documentação limita o prompt a 224 tokens.
- A API aceita arquivos WAV, WebM, MP3, FLAC, M4A e outros formatos listados na documentação. O limite publicado é 25 MB no tier gratuito e 100 MB no tier de desenvolvimento; o endpoint atual da Kunica já limita o upload recebido a 15 MB e 60 segundos. Manter esses limites locais na primeira versão.
- Esperar JSON com o campo `text`. Não assumir que a API devolve score de confiança compatível com o `confidence` do Vosk/Whisper local.

Referências do provedor: [Speech-to-Text](https://console.groq.com/docs/speech-to-text) e [referência do endpoint](https://console.groq.com/docs/api-reference).

## Configuração proposta

Adicionar opções documentadas ao `.env.example` e ao serviço backend do Compose:

```dotenv
STT_ENGINE=groq
GROQ_API_KEY=
GROQ_STT_MODEL=whisper-large-v3-turbo
GROQ_STT_TIMEOUT_SECONDS=20
STT_GROQ_FALLBACK=none
```

- Valores aceitos para `STT_ENGINE`: os atuais `vosk` e `whisper`, mais `groq`.
- Se `STT_ENGINE=groq` e a chave estiver ausente, falhar com erro de configuração claro na inicialização ou no primeiro pedido; nunca enviar a chave ao navegador nem registrá-la em logs.
- `STT_GROQ_FALLBACK` pode futuramente aceitar `vosk` ou `whisper`. O padrão deve ser `none`, para não surpreender com uma espera longa no NUC depois de falha da nuvem. Se habilitado, tentar fallback apenas em indisponibilidade/erro da API, não em áudio inválido.
- Guardar a chave em variável de ambiente local, fora do YAML versionado. Respeitar os mecanismos de segredo que o projeto já usa para `GROQ_API_KEY` do LLM.

## Tratamento de áudio

O endpoint atual já recebe o áudio, limita tamanho, usa FFmpeg para decodificar e converter para PCM mono 16 kHz e então chama `stt.transcribe_pcm`. PCM cru não é um arquivo WAV válido para multipart; a implementação deve:

1. Preferencialmente alterar a etapa FFmpeg para produzir WAV mono 16 kHz em memória, mantendo os limites e validações existentes; ou encapsular o PCM em um WAV válido sem gravar em disco.
2. Enviar o WAV como campo multipart `file`, com nome e MIME `audio.wav` / `audio/wav`.
3. Usar `httpx.AsyncClient` no endpoint assíncrono, com timeout configurável, limite de conexão e tratamento explícito de `429`, `4xx`, `5xx` e timeout.
4. Não guardar áudio temporário no volume persistente. Fechar a resposta HTTP e descartar os bytes após a transcrição.

## Compatibilidade com a API atual

Manter `POST /api/transcribe` e o campo `text`, além do campo `wake` quando `scan_wake=true`. O campo `confidence` não está disponível de forma equivalente na resposta Groq: torná-lo anulável/opcional de maneira compatível com o frontend e ajustar o log de debug para não exibir `undefined` ou inventar uma confiança. Confirmar se clientes existentes exigem sempre esse campo antes da implementação.

O reconhecimento remoto não pode ser considerado confiável para pontuar wake words sem avaliação. Medir falsos positivos/negativos com as frases e variantes já configuradas; se a transcrição cloud não mantiver a precisão necessária, conservar o motor local para o modo de wake-word contínua e usar Groq apenas após o disparo ou para gravações enviadas explicitamente.

## Falhas e limites

- `401/403`: mensagem de configuração/autorização sem expor resposta sensível do provedor.
- `429`: devolver erro temporário claro; não repetir automaticamente sem backoff.
- Timeout, DNS ou indisponibilidade: responder com erro de serviço e usar fallback local somente se habilitado.
- Áudio acima de 15 MB, acima de 60 segundos, vazio ou malformado: manter os códigos e mensagens de validação do endpoint local.
- Não registrar chave, áudio, conteúdo integral da transcrição ou prompts de áudio. Logs operacionais podem incluir provedor, modelo, latência, status HTTP e tamanho em bytes.
- Informar na documentação de configuração que áudio sai do computador/rede local e é processado pela Groq. Uso da API exige conexão e está sujeito a cotas, limites de requisição e termos/políticas do provedor.

## Fora de escopo

- Mudar o LLM ou o TTS para Groq.
- Alterar gravação, detecção de silêncio ou controles de microfone do frontend.
- Envio direto do navegador à Groq.
- Transcrição em streaming ao vivo; esta proposta mantém o fluxo de gravação e upload já existente.
- Ativar Groq por padrão ou adicionar dependências de SDK: a integração pode usar `httpx` já presente.

## Critérios de aceite para uma implementação futura

- `STT_ENGINE=vosk` e `STT_ENGINE=whisper` seguem funcionando sem regressão.
- `STT_ENGINE=groq` transcreve português via backend e devolve o contrato compatível com `/api/transcribe`.
- Ausência de chave, timeout, `429` e falha do provedor têm respostas controladas e não revelam segredos.
- `scan_wake=true` continua executando `wake.match_wake_phrase` sobre o texto obtido.
- Testes cobrem multipart enviado ao provedor usando HTTP mock, erro/timeout, configuração ausente, limites de áudio e compatibilidade do contrato.
- Medir latência ponta a ponta no NUC e comparar com Whisper local usando um conjunto curto e consentido de falas pt-BR, incluindo nome da assistente, alcunhas, perguntas comuns e ruído de fundo.
- O uso de áudio remoto e a configuração do fallback estão descritos para o usuário; nenhum provedor cloud é selecionado sem configuração explícita.
