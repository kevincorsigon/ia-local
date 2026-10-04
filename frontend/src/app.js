const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const sendButton = document.querySelector("#send");
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

function setState(state, label) {
  face.className = `face state-${state}`;
  face.setAttribute("aria-label", `${assistantName.textContent} ${label.toLowerCase()}`);
  stateLabel.textContent = label;
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

fetch("/api/config/public")
  .then((response) => response.json())
  .then((config) => {
    if (config.assistant_name) {
      assistantName.textContent = config.assistant_name;
      document.title = `${config.assistant_name} — Assistente local`;
    }
  })
  .catch(() => {});

checkHealth();
window.setInterval(checkHealth, 15000);

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || sendButton.disabled) return;

  addBubble("user", message);
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
    setState("idle", "Pronto para conversar.");
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
