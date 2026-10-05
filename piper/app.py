"""TTS local leve: Piper (VITS) pt-BR, voz feminina, via sherpa-onnx.

Expõe o mesmo contrato mínimo que o backend consome:
  POST /v1/audio/speech  {"model", "input", "voice", "response_format"} -> audio/wav
  GET  /health                                            -> {"status": "ok", "engine": ..., "voice": ...}

A voz vem embutida na imagem (piper/models), então a síntese funciona offline depois do build.
Troca de voz = trocar PIPER_VOICE_DIR e rebuildar.
"""
from __future__ import annotations

import logging
import os
import wave
from io import BytesIO
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("piper-tts")

VOICE_DIR = Path(os.getenv("PIPER_VOICE_DIR", "/models/pt_BR-dii-high"))
MODEL_PATH = VOICE_DIR / "pt_BR-dii-high.onnx"
TOKENS_PATH = VOICE_DIR / "tokens.txt"
ESPEAK_DATA = VOICE_DIR / "espeak-ng-data"
VOICE_NAME = os.getenv("PIPER_VOICE", "dii")
MAX_CHARS = int(os.getenv("PIPER_MAX_CHARS", "2000"))

missing = [p for p in (MODEL_PATH, TOKENS_PATH, ESPEAK_DATA) if not p.exists()]
if missing:
    raise RuntimeError(f"Voz Piper incompleta em {VOICE_DIR}: faltando {[str(p) for p in missing]}")

app = FastAPI(title="Piper TTS (pt-BR)")
_tts = None


def tts() -> "OfflineTts":
    """Carrega o modelo uma vez (lazy): medir a 1a frase cronometra o cold start."""
    global _tts
    if _tts is None:
        from sherpa_onnx import OfflineTts, OfflineTtsConfig, OfflineTtsModelConfig, OfflineTtsVitsModelConfig

        vits = OfflineTtsVitsModelConfig(
            model=str(MODEL_PATH),
            tokens=str(TOKENS_PATH),
            data_dir=str(ESPEAK_DATA),
        )
        model_config = OfflineTtsModelConfig(vits=vits, num_threads=int(os.getenv("PIPER_THREADS", "2")))
        _tts = OfflineTts(
            OfflineTtsConfig(
                model=model_config,
                max_num_sentences=int(os.getenv("PIPER_MAX_SENTENCES", "100")),
            )
        )
    return _tts


class SpeechRequest(BaseModel):
    model: str = "piper"
    input: str = Field(min_length=1, max_length=MAX_CHARS)
    voice: str = "dii"
    response_format: str = "wav"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "piper", "voice": VOICE_NAME}


@app.post("/v1/audio/speech")
def speak(request: SpeechRequest) -> Response:
    text = request.input.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Sem texto para sintetizar.")
    try:
        audio = tts().generate(text, sid=0, speed=1.0)
    except Exception as exc:  # noqa: BLE001 - o backend trata qualquer falha como 503 próprio
        logger.warning("Falha na síntese: %s", exc)
        raise HTTPException(status_code=503, detail="Síntese indisponível no momento.") from exc
    if not audio.samples:
        raise HTTPException(status_code=502, detail="A síntese voltou vazia.")
    samples = (np.asarray(audio.samples, dtype=np.float32) * 32767).astype(np.int16)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(audio.sample_rate)
        wav.writeframes(samples.tobytes())
    return Response(content=buffer.getvalue(), media_type="audio/wav")
