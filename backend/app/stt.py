"""Reconhecimento de fala local, com dois motores possíveis (escolhidos por STT_ENGINE).

- ``vosk``: Kaldi pt-BR, leve e totalmente offline. Roda em máquinas fracas, mas erra
  muito em fala espontânea (o modelo pequeno chega a ~69% de erro por palavra).
- ``whisper``: faster-whisper (Whisper da OpenAI em CPU, quantizado em ``int8``). Precisa de
  alguns núcleos livres e baixa o modelo na primeira vez, mas erra bem menos e entende
  nomes próprios (inclusive as alcunhas "Kunica" e "TVzinha").

O modelo é carregado uma única vez e reaproveitado nas falas seguintes.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import io
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger("assistant")

ENGINE = os.getenv("STT_ENGINE", "vosk").strip().lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()
GROQ_STT_TIMEOUT_SECONDS = float(os.getenv("GROQ_STT_TIMEOUT_SECONDS", "20"))
VOSK_MODEL_PATH = Path(os.getenv("VOSK_MODEL_PATH", "/models/vosk-model-small-pt-0.3"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_CACHE_DIR = Path(os.getenv("WHISPER_CACHE_DIR", "/data/whisper"))
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "pt")
# ``beam_size=1`` é decodificação gulosa: rápida, porém bem menos precisa em fala espontânea.
# 5 é o padrão do Whisper e reduz bastante as trocas de palavra (custo: um pouco mais de CPU).
WHISPER_BEAM_SIZE = max(1, int(os.getenv("WHISPER_BEAM_SIZE", "5")))
# Texto de contexto opcional para enviesar o decoder (nomes, jargão). Vazio = monta o prompt
# a partir de ``set_domain_terms`` (nome e alcunhas do assistente, vindos da configuração).
WHISPER_INITIAL_PROMPT = os.getenv("WHISPER_INITIAL_PROMPT", "").strip()
# Em máquinas fracas (NUC de 4 núcleos) vale reservar núcleos para o modelo de linguagem
# e para o sintetizador, senão as três coisas competem pela mesma CPU.
WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "0"))

_model: Any | None = None
_load_lock = threading.Lock()

# Vocabulário esperado (nome do assistente, alcunhas, comandos). Vira o ``initial_prompt`` do
# Whisper: sem isso, nomes próprios saem trocados — medido neste projeto, “Kunica” vira “cônica”
# e “TVzinha” vira “vizinha”. A lista é curta de propósito: prompt longo tende a alucinar termos.
_domain_terms: list[str] = []


def set_domain_terms(terms: list[str]) -> None:
    """Define o vocabulário que o reconhecedor deve esperar (nome e alcunhas do assistente)."""
    global _domain_terms
    _domain_terms = [term.strip() for term in terms if term and term.strip()]


def _initial_prompt() -> str | None:
    """Junta o texto do `.env` (cidades, jargão) com o vocabulário do assistente (nome/alcunhas)."""
    parts: list[str] = []
    if WHISPER_INITIAL_PROMPT:
        parts.append(WHISPER_INITIAL_PROMPT)
    if _domain_terms:
        parts.append("Palavras frequentes: " + ", ".join(_domain_terms) + ".")
    if not parts:
        return None
    return "Conversa em português do Brasil. " + " ".join(parts)


class ModelUnavailable(RuntimeError):
    """O motor escolhido não está instalado/baixado nesta máquina."""


def engine() -> str:
    """Nome do motor em uso: ``vosk`` ou ``whisper``."""
    return ENGINE


def whisper_cached() -> bool:
    """O modelo do Whisper já está no cache local (o faster-whisper baixa na primeira vez)."""
    if not WHISPER_CACHE_DIR.is_dir():
        return False
    return any(WHISPER_CACHE_DIR.rglob("model.bin"))


def available() -> bool:
    if ENGINE == "groq":
        return bool(GROQ_API_KEY)
    """True quando o motor já consegue transcrever sem baixar nada novo."""
    if ENGINE == "whisper":
        if _model is not None:
            return True
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return whisper_cached()
    return VOSK_MODEL_PATH.is_dir()


def model_ready() -> bool:
    if ENGINE == "groq":
        return bool(GROQ_API_KEY)
    """O modelo está no disco (os testes usam isto para pular o que depende dele)."""
    if ENGINE == "whisper":
        return whisper_cached()
    return VOSK_MODEL_PATH.is_dir()


def describe() -> dict[str, Any]:
    if ENGINE == "groq":
        return {"engine": "groq", "model": GROQ_STT_MODEL, "compute_type": "cloud", "cpu_threads": 0, "beam_size": 0, "available": available()}
    """Resumo do motor atual para o endpoint de saúde."""
    if ENGINE == "whisper":
        return {
            "engine": "whisper",
            "model": WHISPER_MODEL,
            "compute_type": WHISPER_COMPUTE_TYPE,
            "cpu_threads": WHISPER_CPU_THREADS,
            "beam_size": WHISPER_BEAM_SIZE,
            "available": available(),
        }
    return {
        "engine": "vosk",
        "model": VOSK_MODEL_PATH.name,
        "compute_type": "",
        "cpu_threads": 0,
        "beam_size": 0,
        "available": VOSK_MODEL_PATH.is_dir(),
    }


def _load_vosk() -> Any:
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:
                if not VOSK_MODEL_PATH.is_dir():
                    raise ModelUnavailable(
                        "Modelo Vosk pt-BR ausente. Rode ./scripts/bootstrap.sh para instalar os recursos de voz."
                    )
                from vosk import Model

                logger.info("carregando Vosk de %s", VOSK_MODEL_PATH)
                _model = Model(str(VOSK_MODEL_PATH))
    return _model


def _load_whisper() -> Any:
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise ModelUnavailable(
                        "O motor Whisper não está instalado nesta imagem. Use STT_ENGINE=vosk ou reconstrua o backend."
                    ) from exc
                WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "carregando faster-whisper %s (%s/%s) em %s",
                    WHISPER_MODEL,
                    WHISPER_DEVICE,
                    WHISPER_COMPUTE_TYPE,
                    WHISPER_CACHE_DIR,
                )
                try:
                    extra: dict[str, Any] = {}
                    if WHISPER_CPU_THREADS > 0:
                        extra["cpu_threads"] = WHISPER_CPU_THREADS
                    _model = WhisperModel(
                        WHISPER_MODEL,
                        device=WHISPER_DEVICE,
                        compute_type=WHISPER_COMPUTE_TYPE,
                        download_root=str(WHISPER_CACHE_DIR),
                        **extra,
                    )
                except Exception as exc:  # download, rede ou CPU sem suporte a int8
                    raise ModelUnavailable(f"Não consegui preparar o modelo Whisper: {exc}") from exc
    return _model


def warmup() -> bool:
    if ENGINE == "groq":
        if not GROQ_API_KEY:
            raise ModelUnavailable("STT_ENGINE=groq exige GROQ_API_KEY configurada no ambiente do backend.")
        return True
    """Deixa o motor pronto (baixa o modelo do Whisper na primeira vez)."""
    if ENGINE == "whisper":
        _load_whisper()
        return True
    return _load_vosk() is not None


def _transcribe_vosk(pcm: bytes) -> tuple[str, float]:
    import json

    from vosk import KaldiRecognizer

    recognizer = KaldiRecognizer(_load_vosk(), 16000)
    recognizer.SetWords(True)
    for offset in range(0, len(pcm), 4000):
        recognizer.AcceptWaveform(pcm[offset:offset + 4000])
    result = json.loads(recognizer.FinalResult())
    words = result.get("result", [])
    confidence = sum(float(word.get("conf", 0)) for word in words) / len(words) if words else 0.0
    return str(result.get("text", "")).strip(), confidence


def _transcribe_whisper(pcm: bytes) -> tuple[str, float]:
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    segments, _info = _load_whisper().transcribe(
        samples,
        language=WHISPER_LANGUAGE,
        beam_size=WHISPER_BEAM_SIZE,
        temperature=0.0,
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=_initial_prompt(),
    )
    parts: list[str] = []
    probabilities: list[float] = []
    for segment in segments:
        parts.append(segment.text.strip())
        probabilities.append(math.exp(min(0.0, float(segment.avg_logprob))))
    text = " ".join(part for part in parts if part).strip()
    confidence = sum(probabilities) / len(probabilities) if probabilities else 0.0
    return text, confidence


def transcribe_pcm(pcm: bytes) -> tuple[str, float]:
    """Transcreve PCM 16 kHz mono s16le e devolve (texto, confiança entre 0 e 1)."""
    if not pcm:
        return "", 0.0
    if ENGINE == "whisper":
        return _transcribe_whisper(pcm)
    if ENGINE == "groq":
        raise RuntimeError("A transcrição Groq precisa do cliente HTTP assíncrono.")
    return _transcribe_vosk(pcm)


def pcm_to_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


def groq_prompt() -> str:
    return (_initial_prompt() or "Conversa em português do Brasil.")[:900]
