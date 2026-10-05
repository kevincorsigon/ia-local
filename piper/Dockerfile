# TTS leve: Piper (VITS) pt-BR, voz feminina, via sherpa-onnx (CPU).
# A voz vem embutida na imagem (~64 MB), então a síntese funciona offline depois do build
# e o bootstrap não precisa baixar nada na primeira execução.
FROM python:3.12-slim-bookworm AS downloader

ARG PIPER_MODEL_URL=https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-pt_BR-dii-high.tar.bz2

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl bzip2 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /models \
    && curl --fail --location --retry 3 --silent --show-error \
        -o /tmp/voice.tar.bz2 "$PIPER_MODEL_URL" \
    && tar -xjf /tmp/voice.tar.bz2 -C /models \
    && rm -f /tmp/voice.tar.bz2 \
    && ls /models

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIPER_VOICE_DIR=/models/vits-piper-pt_BR-dii-high \
    PIPER_VOICE=dii \
    PIPER_THREADS=2

WORKDIR /srv
COPY --from=downloader /models /models
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./

EXPOSE 8890
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8890"]
