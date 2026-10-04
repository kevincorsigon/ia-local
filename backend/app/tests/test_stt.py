"""Testes do motor de fala escolhido por STT_ENGINE (app/stt.py) e do aquecimento na API."""
from __future__ import annotations

import pathlib

import httpx
import pytest

from app import stt

TAGS_ROUTE = "/api/tags"


def tags_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": "qualquer"}]})


def test_engine_informa_o_motor_em_uso() -> None:
    assert stt.engine() in {"vosk", "whisper"}


def test_describe_traz_motor_modelo_e_disponibilidade() -> None:
    descricao = stt.describe()

    assert set(descricao) == {"engine", "model", "compute_type", "cpu_threads", "available"}
    assert descricao["engine"] == stt.engine()
    assert descricao["model"]
    assert isinstance(descricao["available"], bool)


def test_audio_vazio_nao_carrega_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    def explodir() -> None:
        raise AssertionError("não deveria carregar o modelo para áudio vazio")

    monkeypatch.setattr(stt, "_load_vosk", explodir)
    monkeypatch.setattr(stt, "_load_whisper", explodir)

    assert stt.transcribe_pcm(b"") == ("", 0.0)


def test_modelo_do_vosk_vem_da_pasta_montada(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt, "ENGINE", "vosk")
    monkeypatch.setattr(stt, "VOSK_MODEL_PATH", tmp_path / "ausente")
    assert stt.model_ready() is False
    assert stt.available() is False

    (tmp_path / "ausente").mkdir()
    assert stt.model_ready() is True
    assert stt.available() is True


def test_modelo_do_whisper_vem_do_cache_local(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt, "ENGINE", "whisper")
    monkeypatch.setattr(stt, "WHISPER_CACHE_DIR", tmp_path / "cache")
    assert stt.whisper_cached() is False
    assert stt.model_ready() is False

    snapshot = tmp_path / "cache" / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"0")

    assert stt.whisper_cached() is True
    assert stt.model_ready() is True


def test_health_publica_o_motor_de_fala(client, external) -> None:
    external({TAGS_ROUTE: tags_ok})

    payload = client.get("/health").json()

    assert payload["speech"]["engine"] == stt.engine()
    assert payload["speech"]["available"] is stt.describe()["available"]


def test_warmup_nao_prepara_de_novo_o_que_esta_pronto(client, external, monkeypatch: pytest.MonkeyPatch) -> None:
    external({TAGS_ROUTE: tags_ok})
    chamadas: list[bool] = []
    monkeypatch.setattr(stt, "available", lambda: True)
    monkeypatch.setattr(stt, "warmup", lambda: chamadas.append(True))

    payload = client.post("/api/warmup").json()

    assert payload["started"] is False
    assert payload["engine"] == stt.engine()
    assert chamadas == []


def test_warmup_pede_preparo_quando_falta_o_modelo(client, external, monkeypatch: pytest.MonkeyPatch) -> None:
    external({TAGS_ROUTE: tags_ok})
    monkeypatch.setattr(stt, "available", lambda: False)
    monkeypatch.setattr(stt, "warmup", lambda: True)

    payload = client.post("/api/warmup").json()

    assert payload["started"] is True
    assert payload["speech"]["engine"] == stt.engine()
