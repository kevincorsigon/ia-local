# Análise do Projeto & Sugestões de Novas Funções — Kunica

## O que a Kunica faz hoje

| Função | Como funciona |
|---|---|
| **Conversa por texto** | Chat via FastAPI + Ollama (local) ou Groq (cloud), com sessão e histórico |
| **Conversa por voz** | Captura por microfone → Vosk/Whisper STT → resposta → Kokoro TTS |
| **Previsão do tempo** | Open-Meteo, 7 dias, cidades do Brasil |
| **Esportes** | Brave Search para jogos e placares |
| **Pesquisa na internet** | Brave Search API |
| **Memória persistente** | Guardar/listar/apagar fatos no volume Docker |
| **Ativação por voz** | Wake words com tolerância a erros do Vosk |
| **Rosto animado** | Face CSS com estados idle/listening/thinking/speaking/error |

---

## Sugestões de Novas Funções

Organizadas por **complexidade de implementação** e **impacto para o usuário**.

---

### 🟢 Fáceis (1-2 dias cada, só backend + regras no roteador)

#### 1. Hora e Data
> "Que horas são?" · "Que dia é hoje?" · "Que dia da semana é amanhã?"

Hoje a Kunica passa a pergunta pro modelo, que pode inventar a hora. Com uma ferramenta `datetime`, a resposta é exata — e não precisa de internet.

```yaml
- title: Hora e data
  detail: "hora atual, dia da semana e datas — ex.: 'que horas são agora?'"
```

#### 2. Temporizador / Alarme por Voz
> "Me avisa daqui a 5 minutos" · "Coloca um timer de 10 minutos"

Um `asyncio.sleep` no backend que manda uma notificação via WebSocket ou polling. Simples e muito útil na cozinha ou enquanto trabalha.

```yaml
- title: Timer e alarmes
  detail: "temporizador por voz — ex.: 'me avisa em 15 minutos'"
```

#### 3. Cálculos e Conversões
> "Quanto é 15% de 230?" · "Converte 100 dólares pra reais" · "Quantos km são 10 milhas?"

Usar uma ferramenta com `eval()` seguro (ou a lib `simpleeval`) para cálculos exatos. Conversão de câmbio pode usar a mesma API do Brave ou uma API de câmbio gratuita.

```yaml
- title: Cálculos e conversões
  detail: "contas, porcentagens e conversões — ex.: 'quanto é 18% de 350?'"
```

#### 4. Resumo de Notícias do Dia
> "Quais são as notícias de hoje?" · "Resume as notícias do dia"

Já existe a busca na web, mas uma ferramenta dedicada poderia buscar as top 5-10 manchetes e montar um resumo automático, em vez de jogar os snippets brutos pro modelo.

```yaml
- title: Resumo de notícias
  detail: "manchetes do dia resumidas — ex.: 'me conta as notícias de hoje'"
```

---

### 🟡 Médias (3-5 dias cada)

#### 5. Agenda / Lembretes com Data
> "Me lembra de pagar o boleto dia 15" · "O que tenho agendado pra essa semana?"

Evolução natural da memória: em vez de guardar fatos soltos, permite guardar **eventos com data**. Um arquivo `schedule.json` no volume Docker, com verificação periódica.

```yaml
- title: Agenda e lembretes
  detail: "lembrete com data e hora — ex.: 'me lembra dia 10 de pagar a internet'"
```

#### 6. Controle de Tarefas / To-Do List
> "Adiciona 'comprar leite' na minha lista" · "O que falta na minha lista de tarefas?"

Uma lista persistente com status (pendente/feito), separada da memória. Comandos: adicionar, listar, marcar como feito, remover.

```yaml
- title: Lista de tarefas
  detail: "to-do list por voz — ex.: 'adiciona comprar café na minha lista'"
```

#### 7. Dicionário / Significado de Palavras
> "O que significa 'resiliência'?" · "Como se diz 'obrigado' em inglês?"

Usar a API gratuita do DicionarioAberto ou Wiktionary para definições, e uma ferramenta simples de tradução (LibreTranslate self-hosted ou MyMemory API gratuita).

```yaml
- title: Dicionário e tradução
  detail: "significado de palavras e tradução simples — ex.: 'o que significa pragmático?'"
```

#### 8. Cotação de Moedas e Criptomoedas
> "Qual o preço do dólar hoje?" · "Quanto está o Bitcoin?"

APIs gratuitas: AwesomeAPI (câmbio BR), CoinGecko (cripto). Respostas exatas em vez de depender da busca web genérica.

```yaml
- title: Cotações
  detail: "câmbio e cripto em tempo real — ex.: 'quanto está o dólar?'"
```

#### 9. Piadas, Curiosidades e Entretenimento
> "Me conta uma piada" · "Me diz uma curiosidade" · "Verdade ou mito: ..."

O modelo já faz isso parcialmente, mas uma ferramenta dedicada garantiria piadas novas (de uma base local em JSON) e curiosidades verificadas.

```yaml
- title: Entretenimento
  detail: "piadas e curiosidades — ex.: 'conta uma piada pra mim'"
```

---

### 🟠 Avançadas (1-2 semanas cada)

#### 10. Resumir Páginas da Web
> "Resume esse link pra mim: https://..." · "O que diz essa matéria?"

Buscar o conteúdo da URL, extrair o texto principal (com `readability` ou `trafilatura`), e pedir ao modelo para resumir. Muito útil para notícias.

```yaml
- title: Resumo de páginas
  detail: "resumir uma URL — ex.: 'resume esse link: https://g1.globo.com/...'"
```

#### 11. Rotina / Automações por Horário
> "Todo dia às 7h, me diga a previsão do tempo e as notícias"

Um agendador (`apscheduler` ou cron interno) que executa ferramentas em horários definidos e sintetiza a resposta quando o usuário estiver presente (detectando atividade do microfone).

```yaml
- title: Rotinas automáticas
  detail: "briefing diário programado — ex.: 'todo dia às 7h me fala o tempo e as notícias'"
```

#### 12. Notas de Voz / Diário
> "Anota no meu diário: hoje fui ao médico e ele disse que..." · "O que eu anotei ontem?"

Diferente da memória (fatos curtos), aqui seriam **anotações longas com data**, como um diário. Gravadas em arquivos separados no volume.

```yaml
- title: Diário / notas de voz
  detail: "anotar pensamentos longos com data — ex.: 'anota no diário: hoje eu...'"
```

#### 13. Integração com Calendário Local (ICS)
> "Quais são meus compromissos de amanhã?"

Ler um arquivo `.ics` exportado (Google Calendar / Outlook) de uma pasta do volume Docker. Sem autenticação externa — o usuário copia o arquivo.

```yaml
- title: Calendário local
  detail: "ler compromissos de um arquivo ICS — ex.: 'o que tenho agendado amanhã?'"
```

#### 14. Modo "Estudo" / Flashcards
> "Me ajuda a estudar sobre a Segunda Guerra" · "Me faça 5 perguntas sobre fotossíntese"

O modelo gera perguntas, espera a resposta do usuário (por voz!), corrige e dá uma nota. Ótimo para quem quer estudar hands-free.

```yaml
- title: Modo estudo
  detail: "quiz interativo por voz — ex.: 'me faça perguntas sobre história do Brasil'"
```

#### 15. Controle de Gastos Simples
> "Gastei 45 reais no mercado" · "Quanto gastei esse mês?"

Registrar despesas por categoria em `expenses.json` no volume, com totais por período. Entrada 100% por voz.

```yaml
- title: Controle de gastos
  detail: "registrar e consultar despesas — ex.: 'gastei 80 reais de gasolina'"
```

---

### 🔴 Ambiciosas (futuro)

#### 16. Integração com Home Assistant (MQTT)
Controlar luzes, tomadas e sensores via MQTT ou API REST do Home Assistant. Está fora do escopo V1, mas a arquitetura de ferramentas já suporta.

#### 17. Reprodução de Música / Rádio
Tocar rádios online ou playlists locais via streaming de áudio. Exigiria mudanças no frontend (player de música separado do TTS).

#### 18. Reconhecimento de Voz Multi-Usuário
Identificar quem está falando (speaker diarization) para dar respostas personalizadas com memórias separadas por pessoa.

#### 19. Modo Offline Completo
Substituir o Brave Search por um índice local (Wikipedia offline, base de dados local), para funcionar 100% sem internet.

---

## Prioridade Sugerida para Implementação

| Prioridade | Funções | Justificativa |
|---|---|---|
| **1ª** | Hora/Data, Timer, Cálculos | Zero dependência externa, útil no dia a dia, rápido de implementar |
| **2ª** | Agenda/Lembretes, To-Do List | Evolução natural da memória, alto valor percebido |
| **3ª** | Cotações, Resumo de Notícias | Melhora as ferramentas que já existem |
| **4ª** | Resumir URLs, Diário, Gastos | Funcionalidades mais completas que diferenciam o assistente |
| **5ª** | Rotinas, Estudo, Home Assistant | Transformam a Kunica de assistente reativo em proativo |

> [!TIP]
> Cada nova ferramenta segue o mesmo padrão: (1) adicionar regex no `route_question` em [tools.py](file:///c:/dev/ia-local/backend/app/tools.py), (2) implementar a função assíncrona, (3) conectar no `chat()` em [main.py](file:///c:/dev/ia-local/backend/app/main.py), (4) atualizar o catálogo em [assistant.yaml](file:///c:/dev/ia-local/config/assistant.yaml).
