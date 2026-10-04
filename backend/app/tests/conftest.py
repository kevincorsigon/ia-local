"""Fixtures dos testes: nenhuma dependência externa real é acessada.

Ollama, Open-Meteo, Brave Search e Kokoro são simulados com ``httpx.MockTransport``,
mantendo o mesmo caminho de código usado em produção (``httpx.AsyncClient``).
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, memory

Responder = Callable[[httpx.Request], httpx.Response]


class ExternalCalls:
    """Programa respostas por marcador de URL e registra o que o backend chamou."""

    def __init__(self, routes: dict[str, Responder]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []
        self.unmatched: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        for marker, responder in self.routes.items():
            if marker in url:
                return responder(request)
        self.unmatched.append(url)
        return httpx.Response(500, json={"error": f"rota não simulada: {url}"})

    def payloads(self, marker: str) -> list[dict[str, Any]]:
        """Corpos JSON enviados pelo backend para as URLs que contêm o marcador."""
        found: list[dict[str, Any]] = []
        for request in self.requests:
            if marker in str(request.url) and request.content:
                found.append(json.loads(request.content))
        return found

    def urls(self, marker: str) -> list[str]:
        return [str(request.url) for request in self.requests if marker in str(request.url)]


@pytest.fixture
def external(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, Responder]], ExternalCalls]:
    """Instala o transporte simulado no ``httpx.AsyncClient`` usado por app e tools."""

    def install(routes: dict[str, Responder]) -> ExternalCalls:
        calls = ExternalCalls(routes)
        real_client = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(calls.handler)
            return real_client(*args, **kwargs)

        # ``app.main`` e ``app.tools`` compartilham o mesmo módulo httpx importado.
        monkeypatch.setattr(main.httpx, "AsyncClient", factory)
        return calls

    return install


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isola a memória persistente: cada teste grava em um volume temporário."""
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "memories.json")
    memory.reset_cache()
    yield tmp_path
    memory.reset_cache()


def ollama_reply(content: str) -> Responder:
    """Resposta do Ollama no formato ``/api/chat`` (não streaming)."""

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    return responder


def raises(exc: Exception) -> Responder:
    """Simula falha de transporte: conexão recusada, timeout, DNS etc."""

    def responder(request: httpx.Request) -> httpx.Response:
        raise exc

    return responder
