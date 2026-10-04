const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const recordButton = document.querySelector("#record");
const recordLabel = document.querySelector("#record-label");
const stopSpeakingButton = document.querySelector("#stop-speaking");
const wakeModeButton = document.querySelector("#wake-mode");
const conversation = document.querySelector("#conversation");
const emptyState = document.querySelector("#empty-state");
const face = document.querySelector("#face");
const stateLabel = document.querySelector("#state-label");
const connection = document.querySelector("#connection");
const assistantName = document.querySelector("#assistant-name");
const sessionStorageKey = "assistant-session-id";
let sessionId = sessionStorage.getItem(sessionStorageKey);
if (!sessionId) {
  sessionId = crypto.randomUUID();
  sessionStorage.setItem(sessionStorageKey, sessionId);
}
let recorder = null;
let recordingStream = null;
let recordingChunks = [];
let recordingTimeout = null;
let currentAudio = null;
let currentAudioUrl = null;
let wakeRecorder = null;
let wakeStream = null;
let wakeBusy = false;
let wakeEnabled = false;
let wakeFollowupUntil = 0;
let wakeClipTimer = null;
let followUpSeconds = 8;
let wakePhrases = [];

function setState(state, label) {
  face.className = `face state-${state}`;
  face.setAttribute("aria-label", `${assistantName.textContent} ${label.toLowerCase()}`);
  stateLabel.textContent = label;
}

function showReadyState() {
  if (wakeEnabled) {
    setState("listening", "Estou monitorando as alcunhas localmente. Toque para desligar.");
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

function normalizeForWake(text) {
  return text.toLocaleLowerCase("pt-BR").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function matchWakePhrase(text) {
  const tokens = [...text.matchAll(/[\p{L}\p{N}]+/gu)];
  const normalizedTokens = tokens.map((token) => normalizeForWake(token[0]));
  const aliases = wakePhrases
    .map((alias) => ({ alias, tokens: normalizeForWake(alias).split(" ") }))
    .sort((a, b) => b.tokens.length - a.tokens.length);
  for (const candidate of aliases) {
    for (let start = 0; start <= normalizedTokens.length - candidate.tokens.length; start += 1) {
      const matched = candidate.tokens.every((token, offset) => normalizedTokens[start + offset] === token);
      if (!matched) continue;
      const finalToken = tokens[start + candidate.tokens.length - 1];
      const query = text.slice(finalToken.index + finalToken[0].length)
        .replace(/^[\s,;:!?—-]+/, "").trim();
      return { alias: candidate.alias, query };
    }
  }
  return null;
}

async function scanWakeChunk(blob) {
  if (!wakeEnabled || wakeBusy || !blob.size) return;
  if (currentAudio && !currentAudio.paused) {
    window.setTimeout(scheduleWakeClip, 1000);
    return;
  }
  wakeBusy = true;
  try {
    const response = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob,
    });
    if (!response.ok) return;
    const result = await response.json();
    const transcript = result.text?.trim();
    if (!transcript) return;

    const now = performance.now();
    const invocation = matchWakePhrase(transcript);
    if (invocation) {
      wakeFollowupUntil = invocation.query ? 0 : now + followUpSeconds * 1000;
      input.value = invocation.query || "Oi, pode falar comigo.";
      if (!invocation.query) skipNextSpeech = true;
      form.requestSubmit();
      return;
    }
    if (wakeFollowupUntil && now <= wakeFollowupUntil) {
      wakeFollowupUntil = 0;
      input.value = transcript;
      form.requestSubmit();
      return;
    }
    if (wakeFollowupUntil && now > wakeFollowupUntil) wakeFollowupUntil = 0;
  } catch {
    setState("error", "Falha no reconhecimento local. Tente desligar e ligar as alcunhas.");
  } finally {
    wakeBusy = false;
    if (wakeEnabled) scheduleWakeClip();
  }
}

function scheduleWakeClip() {
  if (!wakeEnabled || !wakeStream || wakeBusy) return;
  wakeRecorder = new MediaRecorder(wakeStream);
  const clipRecorder = wakeRecorder;
  const clipChunks = [];
  clipRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) clipChunks.push(event.data);
  });
  clipRecorder.addEventListener("stop", () => {
    if (wakeRecorder === clipRecorder) wakeRecorder = null;
    void scanWakeChunk(new Blob(clipChunks, { type: clipRecorder.mimeType || "audio/webm" }));
  }, { once: true });
  clipRecorder.start();
  wakeClipTimer = window.setTimeout(() => {
    if (clipRecorder.state === "recording") clipRecorder.stop();
  }, 6000);
}

async function setWakeMode(enabled) {
  if (!enabled) {
    wakeEnabled = false;
    window.clearTimeout(wakeClipTimer);
    wakeRecorder?.stop();
    wakeStream?.getTracks().forEach((track) => track.stop());
    wakeRecorder = null;
    wakeStream = null;
    wakeFollowupUntil = 0;
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
    wakeStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    wakeEnabled = true;
    scheduleWakeClip();
    wakeModeButton.classList.add("active");
    wakeModeButton.setAttribute("aria-pressed", "true");
    wakeModeButton.textContent = "Alcunhas ligadas · desligar";
    recordButton.disabled = true;
    setState("listening", "Estou monitorando as alcunhas localmente. Toque para desligar.");
  } catch {
    window.clearTimeout(wakeClipTimer);
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
    const ready = health.ollama === "ok" && health.model_available;
    connection.textContent = ready
      ? "Ollama conectado"
      : health.ollama === "ok" ? "Modelo indisponível" : "Ollama indisponível";
    connection.className = `connection ${ready ? "ready" : "offline"}`;
  } catch {
    connection.textContent = "Backend indisponível";
    connection.className = "connection offline";
  }
}

function finishPlayback() {
  currentAudio = null;
  if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
  currentAudioUrl = null;
  stopSpeakingButton.hidden = true;
  showReadyState();
}

async function speakAnswer(text) {
  try {
    if (currentAudio) {
      currentAudio.pause();
      finishPlayback();
    }
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) return;
    const audioBlob = await response.blob();
    if (!audioBlob.size) return;
    currentAudioUrl = URL.createObjectURL(audioBlob);
    currentAudio = new Audio(currentAudioUrl);
    currentAudio.addEventListener("ended", finishPlayback, { once: true });
    currentAudio.addEventListener("error", finishPlayback, { once: true });
    stopSpeakingButton.textContent = "Parar áudio";
    stopSpeakingButton.hidden = false;
    setState("speaking", "Estou falando…");
    await currentAudio.play();
  } catch {
    if (currentAudio) {
      stopSpeakingButton.textContent = "Tocar resposta";
      stopSpeakingButton.hidden = false;
      setState("idle", "A resposta está pronta para tocar.");
    }
  }
}

stopSpeakingButton.addEventListener("click", async () => {
  if (!currentAudio) return;
  if (currentAudio.paused) {
    try {
      await currentAudio.play();
      stopSpeakingButton.textContent = "Parar áudio";
      setState("speaking", "Estou falando…");
    } catch {
      finishPlayback();
    }
  } else {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    finishPlayback();
  }
});

async function transcribeRecording(blob) {
  if (!blob.size) {
    setState("idle", "Não captei áudio. Tente novamente.");
    return;
  }
  recordButton.disabled = true;
  recordLabel.textContent = "Transcrevendo…";
  setState("transcribing", "Estou entendendo sua fala…");
  try {
    const response = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Não consegui transcrever o áudio.");
    input.value = result.text || "";
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
    input.focus();
    setState("idle", result.text
      ? `Transcrição pronta (confiança ${(result.confidence * 100).toFixed(0)}%). Revise e envie.`
      : "Não reconheci palavras. Tente falar um pouco mais perto do microfone.");
  } catch (error) {
    setState("error", error.message || "Falha ao transcrever o áudio.");
  } finally {
    recordButton.disabled = false;
    recordLabel.textContent = "Falar";
  }
}

recordButton.addEventListener("click", async () => {
  if (recorder?.state === "recording") {
    window.clearTimeout(recordingTimeout);
    recorder.stop();
    recordButton.classList.remove("recording");
    recordButton.setAttribute("aria-pressed", "false");
    recordLabel.textContent = "Transcrevendo…";
    setState("transcribing", "Estou entendendo sua fala…");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setState("error", "Este navegador não oferece gravação de áudio.");
    return;
  }
  try {
    recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordingChunks = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus" : "";
    recorder = new MediaRecorder(recordingStream, mimeType ? { mimeType } : undefined);
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) recordingChunks.push(event.data);
    });
    recorder.addEventListener("stop", () => {
      recordingStream?.getTracks().forEach((track) => track.stop());
      recordingStream = null;
      void transcribeRecording(new Blob(recordingChunks, { type: recorder.mimeType || "audio/webm" }));
    }, { once: true });
    recorder.start();
    recordButton.classList.add("recording");
    recordButton.setAttribute("aria-pressed", "true");
    recordLabel.textContent = "Parar";
    setState("listening", "Estou ouvindo… toque em Parar quando terminar.");
    recordingTimeout = window.setTimeout(() => {
      if (recorder?.state === "recording") recordButton.click();
    }, 30000);
  } catch {
    recordingStream?.getTracks().forEach((track) => track.stop());
    recordingStream = null;
    setState("error", "Não consegui acessar o microfone. Confira a permissão do navegador.");
  }
});

fetch("/api/config/public")
  .then((response) => response.json())
  .then((config) => {
    if (config.assistant_name) {
      assistantName.textContent = config.assistant_name;
      document.title = `${config.assistant_name} — Assistente local`;
    }
    wakePhrases = Array.isArray(config.wake_phrases) ? config.wake_phrases : [];
    followUpSeconds = Number(config.follow_up_seconds) || 8;
  })
  .catch(() => {});

checkHealth();
window.setInterval(checkHealth, 15000);

let skipNextSpeech = false;
wakeModeButton.addEventListener("click", () => void setWakeMode(!wakeEnabled));

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || sendButton.disabled) return;

  addBubble("user", message);
  if (currentAudio) {
    currentAudio.pause();
    finishPlayback();
  }
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
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
    if (result.session_id && result.session_id !== sessionId) {
      sessionId = result.session_id;
      sessionStorage.setItem(sessionStorageKey, sessionId);
    }
    pending.textContent = result.answer;
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
    if (skipNextSpeech) skipNextSpeech = false;
    else if (result.should_speak !== false) void speakAnswer(result.answer);
    showReadyState();
    checkHealth();
  } catch (error) {
    pending.textContent = error.message || "Não consegui acessar o assistente.";
    pending.classList.add("error");
    setState("error", "Tive um problema. Confira a conexão e tente novamente.");
    checkHealth();
  } finally {
    sendButton.disabled = false;
    input.focus();
    conversation.scrollTop = conversation.scrollHeight;
  }
});
