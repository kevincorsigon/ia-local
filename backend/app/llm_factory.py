"""
Fábrica para alternar entre diferentes provedores de LLM (Ollama, Groq, etc.)
mantendo uma interface unificada compatível com OpenAI.
"""
import os
import httpx
import logging
from typing import Any, List, Dict, Optional

# Usamos os valores diretamente do os.getenv para evitar importação circular do main.py
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", "0"))
OLLAMA_NUM_BATCH = int(os.getenv("OLLAMA_NUM_BATCH", "512"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
OLLAMA_REPEAT_PENALTY = float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.0"))
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}
CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "180"))

logger = logging.getLogger(__name__)

class LLMProvider:
    """Interface base para provedores de LLM."""
    async def generate(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses devem implementar o método generate.")

class OllamaProvider(LLMProvider):
    def __init__(self):
        self.base_url = OLLAMA_BASE_URL
        self.model = OLLAMA_MODEL
        self.keep_alive = OLLAMA_KEEP_ALIVE
        self.num_ctx = OLLAMA_NUM_CTX
        self.num_thread = OLLAMA_NUM_THREAD
        self.num_batch = OLLAMA_NUM_BATCH
        self.temperature = OLLAMA_TEMPERATURE
        self.repeat_penalty = OLLAMA_REPEAT_PENALTY
        self.think = OLLAMA_THINK

    async def generate(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "keep_alive": self.keep_alive,
            "think": self.think,
            "stream": False,
            "messages": messages,
            "options": {
                "num_ctx": self.num_ctx,
                "num_thread": self.num_thread,
                "num_batch": self.num_batch,
                "temperature": self.temperature,
                "repeat_penalty": self.repeat_penalty,
                "num_predict": kwargs.get("max_tokens", 400),
            },
        }
        candidates = kwargs.get("ollama_candidates") or [self.base_url]
        remember_ollama = kwargs.get("remember_ollama")
        last_connection_error = None
        for base_url in candidates:
            try:
                async with httpx.AsyncClient(timeout=CHAT_TIMEOUT_SECONDS) as client:
                    response = await client.post(f"{base_url}/api/chat", json=payload)
                    response.raise_for_status()
                    data = response.json()
                if remember_ollama:
                    remember_ollama(base_url)
                return {"message": data.get("message", {}), "sources": []}
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_connection_error = exc
        if last_connection_error:
            raise last_connection_error
        raise httpx.ConnectError("nenhum Ollama respondeu")

class GroqProvider(LLMProvider):
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", "llama3-8b-8192")
        if not self.api_key:
            logger.warning("GROQ_API_KEY não está definida no ambiente.")

    async def generate(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        # Groq usa parâmetros no nível raiz, não dentro de 'options'
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 400),
        }
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            # Groq retorna a estrutura de resposta com 'choices'
            message = data.get("choices", [{}])[0].get("message", {})
            return {"message": message, "sources": []}

def get_llm_provider() -> LLMProvider:
    mode = os.getenv("LLM_MODE", "ollama").lower()
    if mode == "groq" or mode == "cloud":
        return GroqProvider()
    return OllamaProvider()
