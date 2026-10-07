const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const recordButton = document.querySelector("#record");
const recordLabel = document.querySelector("#record-label");
const stopSpeakingButton = document.querySelector("#stop-speaking");
const wakeModeButton = document.querySelector("#wake-mode");
const micSelect = document.querySelector("#mic-select");
const micLevel = document.querySelector("#mic-level");
const micHint = document.querySelector("#mic-hint");
const debugControls = document.querySelector("#debug-controls");
const debugPanel = document.querySelector("#debug-panel");
const debugLog = document.querySelector("#debug-log");
const debugToggle = document.querySelector("#debug-toggle");
const debugClose = document.querySelector("#debug-close");
const debugClear = document.querySelector("#debug-clear");
const debugCopy = document.querySelector("#debug-copy");
const fullscreenToggle = document.querySelector("#fullscreen-toggle");
const chatToggle = document.querySelector("#chat-toggle");
const chatClose = document.querySelector("#chat-close");
const chatPanel = document.querySelector("#chat-panel");
const musicToggle = document.querySelector("#music-toggle");
const musicClose = document.querySelector("#music-close");
const musicPanel = document.querySelector("#music-panel");
const musicStatus = document.querySelector("#music-status");
const musicLibrary = document.querySelector("#music-library");
const musicSearchForm = document.querySelector("#music-search-form");
const musicSearch = document.querySelector("#music-search");
const musicResults = document.querySelector("#music-results");
const musicPrevious = document.querySelector("#music-previous");
const musicNext = document.querySelector("#music-next");
const musicRandom = document.querySelector("#music-random");
const musicNowPlaying = document.querySelector("#music-now-playing");
const musicPlayPause = document.querySelector("#music-play-pause");
const musicNextTrack = document.querySelector("#music-next-track");
const musicStop = document.querySelector("#music-stop");
const terminal = document.querySelector(".terminal");
const conversation = document.querySelector("#conversation");
const emptyState = document.querySelector("#empty-state");
const face = document.querySelector("#face");
const stateLabel = document.querySelector("#state-label");
const connection = document.querySelector("#connection");
const providerReadout = document.querySelector("#provider-readout");
const assistantName = document.querySelector("#assistant-name");
// O identificador da sessão fica no localStorage (não no sessionStorage): assim a conversa
// sobrevive a recarregar a página e a fechar/reabrir a aba, dentro do TTL do backend.
const sessionKey = "assistant-session-id";
const chatOpenKey = "assistant-chat-open";
let sessionId = localStorage.getItem(sessionKey);
if (!sessionId) sessionId = crypto.randomUUID();
localStorage.setItem(sessionKey, sessionId);
let recorder = null;
let recordingStream = null;
let recordingChunks = [];
let recordingTimeout = null;
let currentAudio = null;
let currentAudioUrl = null;
const musicAudio = new Audio();
let musicQueue = [];
let musicIndex = -1;
let musicRandomMode = false;
let musicView = "tracks";
let musicStart = 0;
let musicFilterArtist = "";
let musicFilterGenre = "";
let wakeWasEnabledForMusic = false;
let musicPausedForMic = false;
let musicPausedForSpeech = false;
// Verdadeiro do envio da mensagem até o fim da fala da resposta. Enquanto isso o rosto fica em
// “pensando/falando” e a escuta por alcunhas espera: era o loop de escuta que reescrevia o estado
// para “listening” a cada 80 ms e fazia a boca parar de mexer no meio do áudio.
let assistantBusy = false;
let pendingTimerSpeech = [];
let drainingTimerSpeech = false;
// Trechos de fala em andamento (null = nada tocando): permite "Parar áudio" encerrar tudo.
let speechQueue = null;
let wakeRecorder = null;
let wakeStream = null;
let wakeEnabled = false;
let wakeFollowupUntil = 0;
let followUpSeconds = 8;
// Depois de uma resposta por voz, a conversa fica ativa por este tempo: falar já envia a
// mensagem, sem repetir a alcunha. Passado o tempo sem fala, volta a exigir a alcunha.
let conversationUntil = 0;
let conversationSeconds = 60;
let wakeLabel = "Kunica";

// Detecção de fala (VAD) no navegador: a captura termina quando o usuário para de
// falar, então nada depende de clicar em "Parar" nem em "Enviar". O limiar de fala é
// calibrado a cada captura pelo ruído do ambiente (ver captureSpeech).
const VAD_SILENCE_MS = 500;
const VAD_MIN_MS = 500;
const VAD_POLL_MS = 80;
// Piso e teto do limiar de fala: abaixo do piso o ruído passaria por fala; acima do teto
// um ambiente barulhento nunca seria considerado fala.
const VAD_MIN_THRESHOLD = 0.02;
const VAD_MAX_THRESHOLD = 0.2;
let captureRunning = false;
let captureStopRequest = false;

// Logs de diagnóstico no console do navegador (F12 → Console) e no painel "Debug áudio".
// Ajudam a ver o nível de áudio, o tamanho da gravação e o que cada etapa devolveu.
const logLines = [];
const LOG_LINE_LIMIT = 400;

function stringifyArg(value) {
  if (typeof value === "string") return value;
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function writeLogLine(text) {
  logLines.push(text);
  if (logLines.length > LOG_LINE_LIMIT) logLines.splice(0, logLines.length - LOG_LINE_LIMIT);
  if (debugLog) {
    debugLog.textContent = logLines.join("\n");
    debugLog.scrollTop = debugLog.scrollHeight;
  }
}

function log(...args) {
  console.log("[kunica]", ...args);
  writeLogLine(`${new Date().toLocaleTimeString("pt-BR")} ${args.map(stringifyArg).join(" ")}`);
}

function logWarn(...args) {
  console.warn("[kunica]", ...args);
  writeLogLine(`${new Date().toLocaleTimeString("pt-BR")} ! ${args.map(stringifyArg).join(" ")}`);
}

// --- Seleção de microfone --------------------------------------------------------
const micStorageKey = "assistant-mic-id";
let chosenMicId = window.localStorage.getItem(micStorageKey) || "";

function looksLikeOutput(label) {
  return /fone|headphone|headset|alto-?falante|speaker|saída|output|hdmi/i.test(label);
}

function updateMicHint(text) {
  if (!micHint) return;
  if (text) {
    micHint.textContent = text;
    micHint.hidden = false;
  } else {
    micHint.hidden = true;
  }
}

function micConstraints() {
  // O processamento de “chamada de voz” atrapalha o reconhecedor: a supressão de ruído corta
  // pedaços das palavras (o Whisper foi treinado com áudio cru). Mantemos o cancelamento de eco
  // para o microfone não captar a própria voz do assistente e o ganho automático para o nível.
  const audio = { echoCancellation: true, noiseSuppression: false, autoGainControl: true };
  if (chosenMicId) audio.deviceId = { exact: chosenMicId };
  return { audio };
}

async function openMicrophone() {
  try {
    return await navigator.mediaDevices.getUserMedia(micConstraints());
  } catch (error) {
    if (chosenMicId) {
      logWarn("o microfone escolhido não abriu; voltando ao padrão:", error);
      chosenMicId = "";
      window.localStorage.removeItem(micStorageKey);
      return navigator.mediaDevices.getUserMedia(micConstraints());
    }
    throw error;
  }
}

function checkMicChoice() {
  const label = micSelect?.selectedOptions?.[0]?.textContent || "";
  updateMicHint(
    looksLikeOutput(label)
      ? `"${label}" parece ser de saída de áudio. Escolha o microfone do computador (ou ligue o modo "Headset" do Bluetooth).`
      : ""
  );
}

async function refreshMicDevices() {
  if (!micSelect || !navigator.mediaDevices?.enumerateDevices) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((device) => device.kind === "audioinput");
    micSelect.innerHTML = "";
    if (!inputs.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "nenhum microfone encontrado";
      micSelect.append(option);
      updateMicHint("Nenhuma entrada de áudio disponível neste computador.");
      return;
    }
    for (const [index, device] of inputs.entries()) {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `Microfone ${index + 1}`;
      option.selected = device.deviceId === chosenMicId;
      micSelect.append(option);
    }
    if (!chosenMicId && micSelect.value) {
      // Fixa o dispositivo que a interface está mostrando, para o que você vê ser o que é usado.
      chosenMicId = micSelect.value;
      window.localStorage.setItem(micStorageKey, chosenMicId);
    }
    log("microfones na interface:", inputs.map((device) => device.label || "(sem nome)"));
    checkMicChoice();
  } catch (error) {
    logWarn("não consegui listar os microfones:", error);
  }
}

function setMicLevel(level, { hot = false, silent = false } = {}) {
  if (micLevel) {
    micLevel.style.width = `${Math.min(100, Math.round(level * 400))}%`;
    micLevel.classList.toggle("hot", hot);
  }
  debugControls?.classList.toggle("silent", silent);
}

function resetMicLevel() {
  setMicLevel(0);
}

function setChatOpen(open, { focus = true, remember = true } = {}) {
  if (open) setMusicOpen(false);
  terminal.classList.toggle("chat-open", open);
  chatToggle.setAttribute("aria-expanded", String(open));
  chatPanel.setAttribute("aria-hidden", String(!open));
  chatPanel.inert = !open;
  if (remember) localStorage.setItem(chatOpenKey, String(open));
  if (open && focus) {
    window.setTimeout(() => input.focus(), 240);
  }
}

function setDebugOpen(open) {
  terminal.classList.toggle("debug-open", open);
  debugToggle.setAttribute("aria-expanded", String(open));
  debugPanel.setAttribute("aria-hidden", String(!open));
  debugPanel.inert = !open;
}

setChatOpen(false, { focus: false, remember: false });
setDebugOpen(false);

function setMusicOpen(open) {
  terminal.classList.toggle("music-open", open);
  musicToggle.setAttribute("aria-expanded", String(open));
  musicPanel.setAttribute("aria-hidden", String(!open));
  musicPanel.inert = !open;
  if (open) {
    setChatOpen(false, { focus: false });
    void loadMusicCatalog();
  }
}

async function musicRequest(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== undefined) url.searchParams.set(key, String(value));
  }
  const response = await fetch(url);
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || `Jellyfin: HTTP ${response.status}`);
  return result;
}

async function loadMusicCatalog() {
  try {
    const status = await musicRequest("/api/music/status");
    musicStatus.textContent = status.reason;
    if (!status.available) {
      musicLibrary.replaceChildren();
      musicResults.textContent = "Servidor de música indisponível.";
      return;
    }
    const result = await musicRequest("/api/music/libraries");
    const previous = musicLibrary.value;
    musicLibrary.replaceChildren();
    for (const library of result.items) {
      const option = new Option(library.name, library.id);
      musicLibrary.add(option);
    }
    if (result.items.some((item) => item.id === previous)) musicLibrary.value = previous;
    if (!result.items.length) {
      musicStatus.textContent = "Nenhuma biblioteca de música encontrada.";
      return;
    }
    await loadMusicView();
  } catch (error) {
    musicStatus.textContent = error.message || "Não consegui acessar o Jellyfin.";
  }
}

function musicItemButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

async function loadMusicView() {
  if (!musicLibrary.value) return;
  musicResults.textContent = "Carregando…";
  try {
    const common = { library_id: musicLibrary.value, start: musicStart };
    let items;
    if (musicView === "artists") {
      items = (await musicRequest("/api/music/artists", { ...common, search: musicSearch.value.trim() })).items;
    } else if (musicView === "genres") {
      items = (await musicRequest("/api/music/genres", { library_id: musicLibrary.value })).items;
      if (musicSearch.value.trim()) items = items.filter((name) => name.toLocaleLowerCase("pt-BR").includes(musicSearch.value.trim().toLocaleLowerCase("pt-BR")));
    } else {
      items = (await musicRequest("/api/music/tracks", {
        ...common, search: musicSearch.value.trim(), artist: musicFilterArtist, genre: musicFilterGenre,
      })).items;
    }
    musicResults.replaceChildren();
    if (!items.length) musicResults.textContent = "Nenhum resultado nesta biblioteca.";
    for (const item of items) {
      if (musicView === "artists") {
        musicResults.append(musicItemButton(item.name, () => {
          musicFilterArtist = item.name;
          musicFilterGenre = "";
          musicView = "tracks";
          musicStart = 0;
          musicSearch.value = "";
          void loadMusicView();
        }));
      } else if (musicView === "genres") {
        musicResults.append(musicItemButton(item, () => {
          musicFilterGenre = item;
          musicFilterArtist = "";
          musicView = "tracks";
          musicStart = 0;
          musicSearch.value = "";
          void loadMusicView();
        }));
      } else {
        const label = `${item.name} — ${item.artists.join(", ") || "Artista desconhecido"}`;
        musicResults.append(musicItemButton(label, () => void playMusicTrack(item, items)));
      }
    }
    musicPrevious.disabled = musicStart === 0;
    musicNext.disabled = musicView === "genres" || items.length < (musicView === "artists" ? 50 : 30);
    musicStatus.textContent = musicView === "tracks" && (musicFilterArtist || musicFilterGenre)
      ? `Filtrando: ${musicFilterArtist || musicFilterGenre}` : "Servidor de música disponível.";
  } catch (error) {
    musicResults.textContent = error.message || "Falha ao consultar músicas.";
  }
}

async function playMusicTrack(track, queue = null, randomMode = false) {
  if (!track?.id) return;
  musicPausedForSpeech = false;
  if (wakeEnabled) {
    wakeWasEnabledForMusic = true;
    await setWakeMode(false);
  }
  if (queue) {
    musicQueue = queue;
    musicIndex = queue.findIndex((item) => item.id === track.id);
  } else {
    musicQueue = [track];
    musicIndex = 0;
  }
  musicRandomMode = randomMode;
  musicAudio.pause();
  musicAudio.src = `/api/music/stream/${encodeURIComponent(track.id)}`;
  musicNowPlaying.textContent = `${track.name} — ${track.artists.join(", ") || "Artista desconhecido"}`;
  musicPlayPause.textContent = "Pausar";
  try {
    await musicAudio.play();
  } catch (error) {
    musicStatus.textContent = "Não consegui iniciar o áudio. Clique em Tocar ou confira o Jellyfin.";
    musicPlayPause.textContent = "Tocar";
    logWarn("falha na reprodução de música:", error);
  }
}

async function playRandomMusic() {
  try {
    const result = await musicRequest("/api/music/random", {
      library_id: musicLibrary.value, artist: musicFilterArtist, genre: musicFilterGenre,
    });
    if (!result.track) {
      musicStatus.textContent = "Não encontrei música para esta seleção.";
      return;
    }
    await playMusicTrack(result.track, null, true);
  } catch (error) {
    musicStatus.textContent = error.message || "Servidor de música indisponível.";
  }
}

async function nextMusicTrack() {
  if (musicQueue[musicIndex + 1]) {
    await playMusicTrack(musicQueue[musicIndex + 1], musicQueue, musicRandomMode);
  } else {
    await playRandomMusic();
  }
}

function stopMusic() {
  musicAudio.pause();
  musicAudio.removeAttribute("src");
  musicAudio.load();
  musicQueue = [];
  musicIndex = -1;
  musicRandomMode = false;
  musicNowPlaying.textContent = "Nenhuma música tocando";
  musicPlayPause.textContent = "Tocar";
  musicPausedForMic = false;
  musicPausedForSpeech = false;
  if (wakeWasEnabledForMusic) {
    wakeWasEnabledForMusic = false;
    void setWakeMode(true);
  }
}

function resumeMusicAfterMic() {
  if (!musicPausedForMic) return;
  musicPausedForMic = false;
  if (musicAudio.getAttribute("src")) void musicAudio.play().catch(() => {});
}

async function applyMusicAction(action) {
  if (!action) return;
  if (action.action === "play") await playMusicTrack(action.track);
  else if (action.action === "pause") { musicAudio.pause(); musicPlayPause.textContent = "Tocar"; }
  else if (action.action === "resume") { await musicAudio.play().catch(() => {}); musicPlayPause.textContent = "Pausar"; }
  else if (action.action === "stop") stopMusic();
  else if (action.action === "next") await nextMusicTrack();
  else if (action.action === "browse") { musicView = action.view || "tracks"; setMusicOpen(true); }
}

musicAudio.addEventListener("ended", () => void nextMusicTrack());
musicAudio.addEventListener("error", () => {
  if (musicAudio.getAttribute("src")) musicStatus.textContent = "Falha ao reproduzir. Confira a conexão com o Jellyfin.";
});
musicToggle.addEventListener("click", () => setMusicOpen(!terminal.classList.contains("music-open")));
musicClose.addEventListener("click", () => setMusicOpen(false));
musicLibrary.addEventListener("change", () => { musicStart = 0; musicFilterArtist = ""; musicFilterGenre = ""; void loadMusicView(); });
musicSearchForm.addEventListener("submit", (event) => { event.preventDefault(); musicStart = 0; void loadMusicView(); });
musicPanel.querySelectorAll("[data-music-view]").forEach((button) => button.addEventListener("click", () => {
  musicView = button.dataset.musicView;
  musicStart = 0;
  musicFilterArtist = "";
  musicFilterGenre = "";
  musicSearch.value = "";
  void loadMusicView();
}));
musicPrevious.addEventListener("click", () => { musicStart = Math.max(0, musicStart - (musicView === "artists" ? 50 : 30)); void loadMusicView(); });
musicNext.addEventListener("click", () => { musicStart += musicView === "artists" ? 50 : 30; void loadMusicView(); });
musicRandom.addEventListener("click", () => void playRandomMusic());
musicNextTrack.addEventListener("click", () => void nextMusicTrack());
musicStop.addEventListener("click", stopMusic);
musicPlayPause.addEventListener("click", () => {
  if (!musicAudio.getAttribute("src")) return;
  if (musicAudio.paused) void musicAudio.play().then(() => { musicPlayPause.textContent = "Pausar"; }).catch(() => {});
  else { musicAudio.pause(); musicPlayPause.textContent = "Tocar"; }
});
setMusicOpen(false);

function setState(state, label) {
  face.className = `face state-${state}`;
  face.setAttribute("aria-label", `${assistantName.textContent} ${label.toLowerCase()}`);
  stateLabel.textContent = label;
}

function conversationActive() {
  return conversationUntil > performance.now();
}

function idleVoiceLabel() {
  return conversationActive() ? "Ouvindo — conversa ativa, pode falar" : `Diga "${wakeLabel}" quando quiser falar`;
}

function showReadyState() {
  if (assistantBusy) return; // não sobrescreve “pensando”/“falando”
  if (wakeEnabled) {
    setState("listening", idleVoiceLabel());
  } else {
    setState("idle", "Pronto para conversar.");
  }
}

function addBubble(role, text) {
  emptyState.hidden = true;
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  conversation.append(bubble);
  conversation.scrollTop = conversation.scrollHeight;
  return bubble;
}

// Recupera a conversa da sessão atual no backend: são as mesmas falas que o modelo usa como
// contexto, então recarregar a página não “apaga” o que já foi conversado.
async function restoreConversation() {
  try {
    const response = await fetch(`/api/session/${encodeURIComponent(sessionId)}`);
    if (!response.ok) return;
    const data = await response.json();
    const messages = Array.isArray(data.messages) ? data.messages : [];
    for (const item of messages) {
      if (item?.content) addBubble(item.role, item.content);
    }
    if (messages.length) log(`conversa restaurada (${messages.length} mensagens da sessão)`);
  } catch (error) {
    logWarn("não consegui restaurar a conversa:", error);
  }
}

function mediaRecorderOptions() {
  return MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? { mimeType: "audio/webm;codecs=opus" } : undefined;
}

function audioLevel(analyser, buffer) {
  analyser.getFloatTimeDomainData(buffer);
  let sum = 0;
  for (const value of buffer) sum += value * value;
  return Math.sqrt(sum / buffer.length);
}

function describeTrack(stream) {
  const track = stream.getAudioTracks()[0];
  if (!track) return "sem faixa de áudio";
  const settings = track.getSettings ? track.getSettings() : {};
  return [
    `label="${track.label || "(sem nome)"}"`,
    `estado=${track.readyState}`,
    `mudo=${track.muted}`,
    `ativo=${track.enabled}`,
    settings.sampleRate ? `taxa=${settings.sampleRate}Hz` : null,
    settings.channelCount ? `canais=${settings.channelCount}` : null,
    settings.deviceId ? `deviceId=${String(settings.deviceId).slice(0, 8)}…` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

// Grava desde o primeiro instante e resolve quando o usuário para de falar.
// O VAD decide apenas QUANDO PARAR — antes ele decidia quando começar, e se o navegador
// não entregasse nível de áudio (contexto suspenso, microfone sem ganho) nada era gravado.
// Há um envio de segurança: sem detectar fala, a gravação é encerrada em `fallbackMs` e
// ainda assim é transcrita, então nenhum áudio é descartado.
async function captureSpeech(
  stream,
  { maxMs = 15000, fallbackMs = 8000, idleLabel = "Ouvindo…", activeLabel = "Ouvindo…" } = {}
) {
  const context = new AudioContext();
  try {
    await context.resume();
  } catch {
    // Alguns navegadores liberam o áudio só depois de um clique; o botão já é um clique.
  }
  log("AudioContext:", context.state, "| taxa", context.sampleRate, "Hz");
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 2048;
  // Liga o grafo a um ganho mudo: sem isso o navegador pode não alimentar o analisador.
  const silent = context.createGain();
  silent.gain.value = 0;
  source.connect(analyser);
  analyser.connect(silent);
  silent.connect(context.destination);
  const buffer = new Float32Array(analyser.fftSize);
  const recorder = new MediaRecorder(stream, mediaRecorderOptions());
  const chunks = [];
  let bytes = 0;
  log("captura iniciada —", describeTrack(stream), "| gravador:", recorder.mimeType || "(padrão)");

  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) {
      chunks.push(event.data);
      bytes += event.data.size;
      log("bloco de áudio:", event.data.size, "bytes (total", bytes, "bytes)");
    }
  });

  // Calibração curta: mede o ruído de fundo e define o limiar a partir dele.
  const noiseSamples = [];
  const calibrateUntil = performance.now() + 300;
  while (performance.now() < calibrateUntil) {
    noiseSamples.push(audioLevel(analyser, buffer));
    await new Promise((resolve) => window.setTimeout(resolve, 40));
  }
  // Mediana em vez de média: se você falar durante a calibração, os picos não elevam o limiar.
  const noise = noiseSamples.length
    ? [...noiseSamples].sort((a, b) => a - b)[Math.floor(noiseSamples.length / 2)]
    : 0;
  const threshold = Math.min(VAD_MAX_THRESHOLD, Math.max(VAD_MIN_THRESHOLD, noise * 3));
  const startedAt = performance.now();
  log("calibração: ruído", noise.toFixed(4), "→ limiar de fala", threshold.toFixed(4));

  return new Promise((resolve) => {
    let speechDetected = false;
    let speechMs = 0;
    let silenceMs = 0;
    let finished = false;
    let lastLevelLog = 0;
    let peak = 0;
    let reason = "fim";
    let lastTick = startedAt;
    recorder.start();
    resetMicLevel();

    const finalize = async () => {
      // O último "dataavailable" chega antes do evento "stop": só aqui o áudio está completo.
      try {
        await context.close();
      } catch {
        // contexto já fechado
      }
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      log(
        `captura encerrada (${reason}) — fala: ${speechDetected ? "sim" : "não"}`,
        `| pico ${(peak * 100).toFixed(0)}% | ${bytes} bytes | blob ${blob.size} bytes`
      );
      resetMicLevel();
      resolve({ blob, speechDetected, bytes });
    };

    const finish = (why) => {
      if (finished) return;
      finished = true;
      reason = why;
      window.clearInterval(timer);
      captureRunning = false;
      // Não monta o áudio aqui: quem monta é o evento "stop", depois do último bloco.
      if (recorder.state === "inactive") void finalize();
      else recorder.stop();
    };

    recorder.addEventListener("stop", () => void finalize(), { once: true });

    const timer = window.setInterval(() => {
      if (finished) return;
      if (captureStopRequest) {
        finish("parada manual");
        return;
      }
      const level = audioLevel(analyser, buffer);
      if (level > peak) peak = level;
      const now = performance.now();
      const delta = now - lastTick;
      lastTick = now;
      const elapsed = now - startedAt;
      const speaking = level >= threshold;
      if (speaking) {
        if (!speechDetected) log("fala detectada — paro quando você ficar em silêncio");
        speechDetected = true;
        speechMs += delta;
        silenceMs = 0;
      } else if (speechDetected) {
        silenceMs += delta;
      }
      setMicLevel(level, {
        hot: speaking,
        silent: !speechDetected && elapsed > 2500 && peak < threshold,
      });
      if (now - lastLevelLog >= 1000) {
        lastLevelLog = now;
        log(
          `nível ${(level * 100).toFixed(0)}% (limiar ${(threshold * 100).toFixed(0)}%)`,
          `· fala ${speechMs.toFixed(0)} ms · silêncio ${silenceMs.toFixed(0)} ms`,
          `· ${Math.round(bytes / 1024)} KB · ${elapsed.toFixed(0)} ms`
        );
      }
      // O rótulo fica simples: os detalhes técnicos vivem no terminal de debug.
      setState("listening", speechDetected ? activeLabel : idleLabel);

      // A fala conta por tempo acumulado acima do limiar: um estalo de ruído não encerra nada.
      if (speechDetected && speechMs >= VAD_MIN_MS && silenceMs >= VAD_SILENCE_MS) {
        finish("silêncio após a fala");
        return;
      }
      if (elapsed >= maxMs) {
        finish("tempo máximo");
        return;
      }
      if (!speechDetected && elapsed >= fallbackMs) finish("envio de segurança sem detectar fala");
    }, VAD_POLL_MS);
  });
}

// Espera o áudio da resposta terminar para o microfone não escutar a própria voz. Inclui o
// intervalo de síntese: sem isso a escuta recomeça antes de o som sair e apaga o “falando”.
async function waitWhileSpeaking() {
  while (assistantBusy || (currentAudio && !currentAudio.paused)) {
    await new Promise((resolve) => window.setTimeout(resolve, 150));
  }
}

async function listenForWake() {
  while (wakeEnabled && wakeStream) {
    const capture = await captureSpeech(wakeStream, {
      maxMs: 20000,
      fallbackMs: 8000,
      idleLabel: idleVoiceLabel(),
      activeLabel: "Ouvindo…",
    });
    if (!wakeEnabled) break;
    // Sem fala detectada e com áudio desprezível, apenas continua escutando em silêncio.
    if (!capture.speechDetected && capture.bytes < 8000) continue;
    await handleWakeClip(capture.blob);
  }
}

// Cada fala renova a janela de conversa: o assistente só volta a exigir a alcunha
// depois de ficar um tempo sem ouvir nada.
function startConversation(message) {
  conversationUntil = performance.now() + conversationSeconds * 1000;
  log(`conversa ativa por ${conversationSeconds}s — próxima fala não precisa de alcunha`);
  void sendMessage(message);
}

function isStopSpeakingCommand(text) {
  const normalized = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("pt-BR").replace(/[^a-z0-9]+/g, " ").trim();
  return /^(?:kunica )?(?:pode )?(?:parar(?: de falar)?|pare|para(?: de falar)?|cala a boca|fica quieta)$/.test(normalized);
}

function stopSpeechByVoice() {
  if (!speechQueue && !currentAudio) return;
  log("voz interrompida por comando falado");
  speechQueue = null;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
  }
  finishPlayback();
}

async function handleWakeClip(blob) {
  if (!wakeEnabled) return;
  if (!blob.size) {
    log("alcunha: nenhum áudio gravado neste ciclo");
    return;
  }
  const startedAt = performance.now();
  setState("thinking", "Transcrevendo sua fala…");
  try {
    const response = await fetch("/api/transcribe?scan_wake=true", {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob,
    });
    if (!response.ok) {
      logWarn("alcunha: /api/transcribe respondeu HTTP", response.status);
      return;
    }
    const result = await response.json();
    const transcript = (result.text || "").trim();
    log(
      `alcunha: transcrevi "${transcript}"${Number.isFinite(result.confidence) ? ` (confiança ${result.confidence})` : ""}`,
      "| wake:", JSON.stringify(result.wake),
      `| ${Math.round(performance.now() - startedAt)} ms`
    );
    if (!transcript) {
      setState("listening", "Ouvi um som, mas não entendi as palavras. Fale mais perto do microfone.");
      return;
    }

    const stopCommandText = result.wake?.query || transcript;
    if (assistantBusy && isStopSpeakingCommand(stopCommandText)) {
      stopSpeechByVoice();
      return;
    }
    // Durante a reprodução, a captura serve apenas para comandos de interrupção.
    if (assistantBusy) return;

    const now = performance.now();
    if (result.wake) {
      const query = (result.wake.query || "").trim();
      log("alcunha detectada:", result.wake.phrase, "| pergunta:", query || "(só a saudação)");
      if (query) {
        startConversation(query);
      } else {
        wakeFollowupUntil = now + followUpSeconds * 1000;
        void sendMessage("Oi, pode falar comigo.");
      }
      return;
    }
    if (now <= wakeFollowupUntil) {
      log("janela de continuação aberta — enviando sem alcunha");
      wakeFollowupUntil = 0;
      startConversation(transcript);
      return;
    }
    if (now <= conversationUntil) {
      log(`conversa ativa (mais ${Math.round((conversationUntil - now) / 1000)}s) — enviando sem alcunha`);
      startConversation(transcript);
      return;
    }
    if (conversationUntil) {
      conversationUntil = 0;
      log("conversa encerrada por falta de fala — volte a usar a alcunha");
    }
    setState("listening", `Diga "${wakeLabel}" para falar comigo.`);
  } catch {
    setState("error", "Falha no reconhecimento local. Tente desligar e ligar as alcunhas.");
  }
}

// A captura é contínua com VAD (captureSpeech): não há mais clipes fixos de 6s,
// que cortavam a fala no meio e atrasavam a resposta.

const wakeModeStorageKey = "assistant-wake-mode";

async function setWakeMode(enabled) {
  window.localStorage.setItem(wakeModeStorageKey, enabled ? "1" : "0");
  log("alcunhas:", enabled ? "ligando…" : "desligando");
  if (!enabled) {
    wakeEnabled = false;
    captureStopRequest = true;
    wakeRecorder?.stop();
    wakeStream?.getTracks().forEach((track) => track.stop());
    wakeRecorder = null;
    wakeStream = null;
    wakeFollowupUntil = 0;
    conversationUntil = 0;
    wakeModeButton.classList.remove("active");
    wakeModeButton.setAttribute("aria-pressed", "false");
    wakeModeButton.textContent = "Ativar alcunhas";
    recordButton.disabled = false;
    setState("idle", "Alcunhas desligadas. Pode usar o microfone ou digitar.");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setState("error", "Este navegador não oferece gravação de áudio.");
    wakeModeButton.setAttribute("aria-pressed", "false");
    return;
  }
  try {
    wakeStream = await openMicrophone();
    wakeEnabled = true;
    captureStopRequest = false;
    log("alcunhas ligadas —", describeTrack(wakeStream));
    void refreshMicDevices();
    wakeModeButton.classList.add("active");
    wakeModeButton.setAttribute("aria-pressed", "true");
    wakeModeButton.textContent = "Alcunhas ligadas · desligar";
    recordButton.disabled = true;
    setState("listening", idleVoiceLabel());
    void listenForWake();
  } catch (error) {
    logWarn("falha ao acessar o microfone para as alcunhas:", error);
    wakeStream?.getTracks().forEach((track) => track.stop());
    wakeStream = null;
    wakeEnabled = false;
    wakeModeButton.setAttribute("aria-pressed", "false");
    setState("error", "Não consegui acessar o microfone. Confira a permissão do navegador.");
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const health = await response.json();
    const cloudMode = health.llm_mode === "cloud";
    const autoMode = health.llm_mode === "auto";
    const ollamaReady = health.ollama === "ok" && health.model_available;
    const ready = cloudMode || ollamaReady;
    providerReadout.textContent = cloudMode
      ? "CLOUD // GROQ"
      : autoMode ? "AUTO // OLLAMA + CLOUD" : "OLLAMA // LOCAL";
    connection.textContent = cloudMode
      ? "Cloud conectado"
      : autoMode
        ? ollamaReady ? "Ollama preferido · cloud reserva" : "Ollama indisponível · cloud reserva"
        : ready ? "Ollama conectado" : health.ollama === "ok" ? "Modelo indisponível" : "Ollama indisponível";
    connection.className = `connection ${ready ? "ready" : "offline"}`;
  } catch {
    connection.textContent = "Backend indisponível";
    connection.className = "connection offline";
  }
}

function finishPlayback() {
  assistantBusy = false;
  speechQueue = null;
  currentAudio = null;
  if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
  currentAudioUrl = null;
  stopSpeakingButton.hidden = true;
  // A resposta terminou: libera o tempo cheio de conversa antes de exigir a alcunha de novo.
  if (conversationActive()) conversationUntil = performance.now() + conversationSeconds * 1000;
  showReadyState();
  resumeMusicAfterMic();
  if (musicPausedForSpeech) {
    musicPausedForSpeech = false;
    if (musicAudio.getAttribute("src")) void musicAudio.play().catch(() => {});
  }
}

// Kokoro sintetiza em CPU: um trecho de até 220 caracteres leva ~1,3 s para virar áudio. Para a
// fala começar quase junto com o texto, o PRIMEIRO trecho é bem curto (uma oração, ~70 caracteres)
// e os seguintes usam o teto maior — eles são sintetizados enquanto o anterior toca, então o tempo
// total não muda, mas a primeira palavra sai bem antes. Frases gigantes (sem pontuação) são
// cortadas perto do limite, preferindo vírgula/ponto e vírgula para o corte soar natural.
const FIRST_SPEECH_CHARS = 70;
const SPEECH_CHUNK_CHARS = 220;

function cutLongSentence(sentence, limit) {
  if (sentence.length <= limit) return [sentence];
  const pieces = [];
  let rest = sentence;
  while (rest.length > limit) {
    const janela = rest.slice(0, limit);
    const pausa = Math.max(janela.lastIndexOf(","), janela.lastIndexOf(";"));
    const espaco = janela.lastIndexOf(" ");
    const minimo = limit * 0.4;
    let corte = limit;
    if (pausa >= minimo) corte = pausa + 1;
    else if (espaco >= minimo) corte = espaco;
    pieces.push(rest.slice(0, corte).trim());
    rest = rest.slice(corte).trim();
  }
  if (rest) pieces.push(rest);
  return pieces;
}

function splitForSpeech(text, maxChars = SPEECH_CHUNK_CHARS) {
  const primeiroLimite = Math.min(FIRST_SPEECH_CHARS, maxChars);
  const partes = text
    .split(/(?<=[.!?…])\s+|\n+/)
    .map((parte) => parte.trim())
    .filter(Boolean)
    .flatMap((frase) => cutLongSentence(frase, primeiroLimite));
  const chunks = [];
  let atual = "";
  let limite = primeiroLimite;
  for (const parte of partes) {
    if (atual && atual.length + parte.length + 1 > limite) {
      chunks.push(atual);
      atual = parte;
      limite = maxChars;
    } else {
      atual = atual ? `${atual} ${parte}` : parte;
    }
  }
  if (atual) chunks.push(atual);
  return chunks.length ? chunks : [text];
}

async function synthesize(text) {
  const response = await fetch("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) throw new Error(`síntese indisponível (HTTP ${response.status})`);
  return response.blob();
}

// Aquece o sintetizador: a primeira síntese depois de o container subir é bem mais lenta (o modelo
// é carregado nessa hora). Um pedido curto logo na abertura deixa o Kokoro pronto, então a primeira
// resposta já sai no ritmo normal em vez de somar o carregamento à espera do som.
async function warmUpSpeech() {
  const startedAt = performance.now();
  try {
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "Olá." }),
    });
    log(`síntese aquecida em ${Math.round(performance.now() - startedAt)} ms (HTTP ${response.status})`);
  } catch (error) {
    logWarn("não consegui aquecer a síntese de voz:", error);
  }
}

async function speakAnswer(text) {
  const startedAt = performance.now();
  try {
    if (musicAudio.getAttribute("src") && !musicAudio.paused) {
      musicAudio.pause();
      musicPausedForSpeech = true;
    }
    if (currentAudio) {
      currentAudio.pause();
      finishPlayback();
    }
    // Depois do finishPlayback acima (que zera a flag): daqui até o fim da fala a escuta espera.
    assistantBusy = true;
    const chunks = splitForSpeech(text);
    speechQueue = chunks;
    stopSpeakingButton.textContent = "Parar áudio";
    stopSpeakingButton.hidden = false;
    setState("speaking", "Estou falando…");
    log(`voz: ${chunks.length} trecho(s) para sintetizar`);

    // Já começa a sintetizar o primeiro trecho, e adianta o próximo enquanto fala.
    let proximo = synthesize(chunks[0]);
    for (let indice = 0; indice < chunks.length; indice += 1) {
      const audioBlob = await proximo;
      if (!speechQueue) return; // o usuário parou
      if (indice + 1 < chunks.length) proximo = synthesize(chunks[indice + 1]);
      if (!audioBlob.size) continue;
      if (indice === 0) {
        log(`voz: primeiro áudio pronto em ${Math.round(performance.now() - startedAt)} ms`);
      }
      currentAudioUrl = URL.createObjectURL(audioBlob);
      currentAudio = new Audio(currentAudioUrl);
      setState("speaking", "Estou falando…");
      await new Promise((resolve, reject) => {
        currentAudio.addEventListener("ended", resolve, { once: true });
        currentAudio.addEventListener("error", reject, { once: true });
        currentAudio.play().catch(reject);
      });
      if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
      currentAudioUrl = null;
      currentAudio = null;
      if (!speechQueue) return;
    }
    finishPlayback();
  } catch (error) {
    assistantBusy = false;
    logWarn("falha na síntese de voz:", error);
    if (currentAudio) {
      // Mantém o trecho que já existe para tocar no botão (ex.: o navegador bloqueou o autoplay).
      speechQueue = null;
      stopSpeakingButton.textContent = "Tocar resposta";
      stopSpeakingButton.hidden = false;
      setState("idle", "A resposta está pronta para tocar.");
    } else {
      finishPlayback();
    }
  }
}

stopSpeakingButton.addEventListener("click", async () => {
  // Enquanto a resposta está sendo falada, o botão encerra a fila inteira.
  if (speechQueue) {
    log("voz interrompida pelo usuário");
    speechQueue = null;
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.currentTime = 0;
    }
    finishPlayback();
    return;
  }
  if (!currentAudio) return;
  try {
    await currentAudio.play();
    stopSpeakingButton.textContent = "Parar áudio";
    setState("speaking", "Estou falando…");
  } catch {
    finishPlayback();
  }
});

async function transcribeAndSend(blob) {
  if (blob.size < 3000) {
    logWarn("transcrição abortada: apenas", blob.size, "bytes de áudio");
    setState("idle", "Gravei quase nada. Confira o microfone em chrome://settings/content/microphone e permita o acesso.");
    resumeMusicAfterMic();
    return;
  }
  setState("transcribing", "Estou entendendo sua fala…");
  const startedAt = performance.now();
  try {
    const response = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob,
    });
    const result = await response.json();
    log(`transcrição (${Math.round(performance.now() - startedAt)} ms, ${blob.size} bytes):`, JSON.stringify(result));
    if (!response.ok) throw new Error(result.detail || "Não consegui transcrever o áudio.");
    const text = (result.text || "").trim();
    if (!text) {
      setState("idle", "Não reconheci palavras. Tente falar um pouco mais perto do microfone.");
      resumeMusicAfterMic();
      return;
    }
    // Envio automático: basta parar de falar, sem clicar em "Enviar".
    await sendMessage(text);
    if (!assistantBusy) resumeMusicAfterMic();
  } catch (error) {
    setState("error", error.message || "Falha ao transcrever o áudio.");
    resumeMusicAfterMic();
  }
}

recordButton.addEventListener("click", async () => {
  if (captureRunning) {
    // Um segundo toque encerra a captura na hora.
    log("botão Falar: encerrando a captura a pedido");
    captureStopRequest = true;
    recordLabel.textContent = "Transcrevendo…";
    return;
  }
  log("botão Falar: iniciando");
  if (musicAudio.getAttribute("src") && !musicAudio.paused) {
    musicAudio.pause();
    musicPausedForMic = true;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setState("error", "Este navegador não oferece gravação de áudio.");
    resumeMusicAfterMic();
    return;
  }
  try {
    const stream = await openMicrophone();
    log("microfone obtido —", describeTrack(stream));
    void refreshMicDevices();
    captureRunning = true;
    captureStopRequest = false;
    recordButton.classList.add("recording");
    recordButton.setAttribute("aria-pressed", "true");
    recordLabel.textContent = "Estou ouvindo…";
    setState("listening", "Calibrando o microfone…");
    const capture = await captureSpeech(stream, {
      maxMs: 30000,
      fallbackMs: 8000,
      idleLabel: "Fale a sua pergunta",
      activeLabel: "Ouvindo…",
    });
    stream.getTracks().forEach((track) => track.stop());
    recordButton.classList.remove("recording");
    recordButton.setAttribute("aria-pressed", "false");
    recordLabel.textContent = "Falar";
    await transcribeAndSend(capture.blob);
  } catch (error) {
    logWarn("falha ao obter o microfone:", error);
    captureRunning = false;
    recordButton.classList.remove("recording");
    recordButton.setAttribute("aria-pressed", "false");
    recordLabel.textContent = "Falar";
    setState("error", "Não consegui acessar o microfone. Confira a permissão do navegador.");
    resumeMusicAfterMic();
  }
});

fetch("/api/config/public")
  .then((response) => response.json())
  .then((config) => {
    if (config.assistant_name) {
      assistantName.textContent = config.assistant_name;
      document.title = `${config.assistant_name} — Assistente local`;
    }
    wakeLabel = Array.isArray(config.wake_phrases) && config.wake_phrases.length
      ? String(config.wake_phrases[0]) : wakeLabel;
    followUpSeconds = Number(config.follow_up_seconds) || 8;
    conversationSeconds = Number(config.conversation_seconds) || 60;
    log(
      "configuração recebida — alcunhas:", config.wake_phrases,
      "| continuação:", followUpSeconds, "s",
      "| conversa:", conversationSeconds, "s"
    );
    if (window.localStorage.getItem(wakeModeStorageKey) !== "0") {
      // A escuta por alcunhas nasce habilitada: só continua desligada se o
      // usuário optou por desativá-la antes ("0" salvo no navegador).
      void setWakeMode(true);
    }
  })
  .catch(() => {});

checkHealth();
window.setInterval(checkHealth, 15000);

let skipNextSpeech = false;
wakeModeButton.addEventListener("click", () => void setWakeMode(!wakeEnabled));

// Trocar o microfone na interface passa a valer imediatamente e fica salvo no navegador.
micSelect?.addEventListener("change", async () => {
  chosenMicId = micSelect.value;
  window.localStorage.setItem(micStorageKey, chosenMicId);
  log("microfone escolhido:", micSelect.selectedOptions[0]?.textContent);
  checkMicChoice();
  if (wakeEnabled) {
    wakeEnabled = false;
    captureStopRequest = true;
    wakeStream?.getTracks().forEach((track) => track.stop());
    wakeStream = null;
    await setWakeMode(true);
  }
});

navigator.mediaDevices?.addEventListener?.("devicechange", () => void refreshMicDevices());
void refreshMicDevices();
// Reabre o painel como o usuário deixou e devolve o histórico da sessão (mesmo contexto do modelo).
setChatOpen(localStorage.getItem(chatOpenKey) === "true", { focus: false });
void restoreConversation();
void warmUpSpeech();
log("interface iniciada — chat, voz e painel de debug prontos");
chatToggle.addEventListener("click", () => setChatOpen(!terminal.classList.contains("chat-open")));
chatClose.addEventListener("click", () => setChatOpen(false));
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (terminal.classList.contains("chat-open")) setChatOpen(false);
  if (terminal.classList.contains("debug-open")) setDebugOpen(false);
});

// Painel de debug: terminal com o microfone, o nível e os logs desta sessão.
debugToggle.addEventListener("click", () => setDebugOpen(!terminal.classList.contains("debug-open")));
debugClose.addEventListener("click", () => setDebugOpen(false));
debugClear.addEventListener("click", () => {
  logLines.length = 0;
  if (debugLog) debugLog.textContent = "";
});
debugCopy.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(logLines.join("\n"));
    log("logs copiados para a área de transferência");
  } catch (error) {
    logWarn("não consegui copiar os logs:", error);
  }
});

// --- Tela cheia ---------------------------------------------------------------------
// O "gráfico" (barras) do canto superior esquerdo é o botão que alterna a tela cheia do console.
function fullscreenElement() {
  return document.fullscreenElement || document.webkitFullscreenElement || null;
}

function updateFullscreenButton() {
  if (!fullscreenToggle) return;
  const active = Boolean(fullscreenElement());
  fullscreenToggle.setAttribute("aria-pressed", String(active));
  const label = active ? "Sair da tela cheia" : "Abrir em tela cheia";
  fullscreenToggle.title = label;
  fullscreenToggle.setAttribute("aria-label", label);
}

function toggleFullscreen() {
  try {
    if (fullscreenElement()) {
      // O Escape também sai; aqui tratamos o toque no botão.
      const exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (exit) void Promise.resolve(exit.call(document)).catch(() => {});
      return;
    }
    const request = terminal.requestFullscreen || terminal.webkitRequestFullscreen;
    if (!request) return;
    void Promise.resolve(request.call(terminal))
      .then(() => log("tela cheia ativada"))
      .catch((error) => logWarn("não consegui abrir em tela cheia:", error));
  } catch (error) {
    logWarn("tela cheia indisponível:", error);
  }
}

if (fullscreenToggle) {
  const request = terminal.requestFullscreen || terminal.webkitRequestFullscreen;
  const enabled = Boolean((document.fullscreenEnabled ?? document.webkitFullscreenEnabled) && request);
  if (enabled) {
    fullscreenToggle.addEventListener("click", toggleFullscreen);
    // O estado pode mudar também pelo Escape ou pela tecla F11 do navegador.
    document.addEventListener("fullscreenchange", updateFullscreenButton);
    document.addEventListener("webkitfullscreenchange", updateFullscreenButton);
    updateFullscreenButton();
  } else {
    // Navegador sem a API (ou dentro de um iframe restrito): mantém o visual, sem ação.
    fullscreenToggle.disabled = true;
    fullscreenToggle.title = "Tela cheia não disponível neste navegador";
    fullscreenToggle.setAttribute("aria-label", fullscreenToggle.title);
  }
}

input.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
  event.preventDefault();
  if (form.requestSubmit) form.requestSubmit();
  else void sendMessage(input.value);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

// Envio da mensagem: usado pelo chat digitado, pelo botão de microfone e pelas alcunhas.
async function sendMessage(rawMessage) {
  const message = (rawMessage || "").trim();
  if (!message || sendButton.disabled) return;
  log("enviando ao backend:", message.slice(0, 120));
  const startedAt = performance.now();

  addBubble("user", message);
  if (currentAudio) {
    currentAudio.pause();
    finishPlayback();
  }
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  assistantBusy = true;
  setState("thinking", "Estou pensando…");
  const pending = addBubble("assistant", "…");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Não consegui responder agora.");
    log(
      `resposta em ${Math.round(performance.now() - startedAt)} ms`,
      "| ferramentas:", JSON.stringify(result.used_tools),
      "| fontes:", result.sources?.length || 0
    );
    if (result.session_id && result.session_id !== sessionId) {
      sessionId = result.session_id;
      localStorage.setItem(sessionKey, sessionId);
    }
    pending.textContent = result.answer;
    if (result.music) await applyMusicAction(result.music);
    if (result.music && ["play", "pause", "stop", "next"].includes(result.music.action)) musicPausedForMic = false;
    if (result.sources?.length) {
      const sources = document.createElement("div");
      sources.className = "sources";
      const label = document.createElement("span");
      label.textContent = "Fontes: ";
      sources.append(label);
      for (const source of result.sources) {
        try {
          const url = new URL(source.url);
          if (url.protocol !== "https:") continue;
          const link = document.createElement("a");
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = source.title || url.hostname;
          sources.append(link);
        } catch {
          // Ignora qualquer endereço inválido retornado pela ferramenta.
        }
      }
      if (sources.querySelector("a")) pending.after(sources);
    }
    if (skipNextSpeech) {
      skipNextSpeech = false;
      assistantBusy = false;
      showReadyState();
    } else if (result.should_speak !== false) {
      // speakAnswer assume o estado e só libera no fim da fala (finishPlayback).
      void speakAnswer(result.answer);
    } else {
      assistantBusy = false;
      showReadyState();
    }
    checkHealth();
  } catch (error) {
    assistantBusy = false;
    logWarn("falha no /api/chat:", error);
    pending.textContent = error.message || "Não consegui acessar o assistente.";
    pending.classList.add("error");
    setState("error", "Tive um problema. Confira a conexão e tente novamente.");
    checkHealth();
  } finally {
    sendButton.disabled = false;
    input.focus();
    conversation.scrollTop = conversation.scrollHeight;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  void sendMessage(input.value);
});

async function drainTimerSpeech() {
  if (assistantBusy || drainingTimerSpeech || pendingTimerSpeech.length === 0) return;
  drainingTimerSpeech = true;
  try {
    while (pendingTimerSpeech.length > 0 && !assistantBusy) {
      await speakAnswer(pendingTimerSpeech.shift());
    }
  } finally {
    drainingTimerSpeech = false;
  }
}

// Busca temporizadores concluídos; o backend associa cada aviso à sessão atual.
window.setInterval(async () => {
  try {
    const response = await fetch(`/api/timers/${encodeURIComponent(sessionId)}`);
    if (!response.ok) return;
    const { notifications = [] } = await response.json();
    for (const item of notifications) {
      const message = `O temporizador terminou${item.text ? `: ${item.text}` : "."}`;
      addBubble("assistant", message);
      pendingTimerSpeech.push(message);
    }
    void drainTimerSpeech();
  } catch {
    // O chat continua funcionando quando a consulta de avisos falha.
  }
}, 3000);
