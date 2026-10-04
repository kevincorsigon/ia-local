"""Memória de longo prazo do assistente.

As informações que o usuário pede para guardar são gravadas no volume Docker
montado em ``MEMORY_DIR`` (padrão ``/data``), no arquivo ``memories.json``. Como o
volume sobrevive a ``docker compose down``, ``up`` e à recriação do container, o
conteúdo continua disponível e é injetado no prompt de sistema de toda conversa
nova — servindo de base para sessões futuras.

A gravação é atômica (arquivo temporário + ``os.replace``) para que uma
interrupção no meio da escrita não corrompa as memórias já salvas. Se o arquivo
ficar ilegível, ele é preservado com o sufixo ``.corrupt-<timestamp>.json`` e a
memória recomeça vazia em vez de derrubar a interface.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("assistant.memory")

MEMORY_DIR = Path(os.getenv("MEMORY_DIR", "/data"))
MEMORY_FILE = MEMORY_DIR / "memories.json"
MAX_MEMORIES = max(1, int(os.getenv("MAX_MEMORIES", "200")))
MAX_MEMORY_CHARS = max(20, int(os.getenv("MAX_MEMORY_CHARS", "400")))
MEMORY_PROMPT_CHARS = max(0, int(os.getenv("MEMORY_PROMPT_CHARS", "1200")))

_LOCK = asyncio.Lock()
_CACHE: list[dict[str, Any]] | None = None


class MemoryUnavailable(Exception):
    """A memória persistente não pôde ser lida ou gravada no volume de dados."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _quarantine() -> None:
    """Preserva um arquivo ilegível em vez de sobrescrevê-lo."""
    try:
        MEMORY_FILE.replace(MEMORY_FILE.with_suffix(f".corrupt-{int(datetime.now().timestamp())}.json"))
    except OSError:  # pragma: no cover - melhor esforço
        logger.warning("Não consegui preservar o arquivo de memória ilegível")


def _read_from_disk() -> list[dict[str, Any]]:
    try:
        raw = MEMORY_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise MemoryUnavailable("Não consegui ler as informações guardadas.") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Arquivo de memória ilegível; preservando cópia e recomeçando")
        _quarantine()
        return []

    items = payload.get("memories") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []

    memories: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = _normalize(str(item.get("text", "")))
        if not text:
            continue
        memories.append(
            {
                "id": str(item.get("id") or uuid.uuid4()),
                "text": text[:MAX_MEMORY_CHARS],
                "created_at": str(item.get("created_at") or _now()),
            }
        )
    return memories[-MAX_MEMORIES:]


def _write_to_disk(memories: list[dict[str, Any]]) -> None:
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        temporary = MEMORY_FILE.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "memories": memories}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, MEMORY_FILE)
    except OSError as exc:
        raise MemoryUnavailable("Não consegui gravar no volume de dados do Docker.") from exc


async def _load(force: bool = False) -> list[dict[str, Any]]:
    """Carrega do volume na primeira chamada e mantém o cache em memória."""
    global _CACHE
    if _CACHE is None or force:
        _CACHE = await asyncio.to_thread(_read_from_disk)
    return _CACHE


def reset_cache() -> None:
    """Descarta o cache; usado nos testes e após manutenção do volume."""
    global _CACHE
    _CACHE = None


def _set_cache(memories: list[dict[str, Any]]) -> None:
    """Mantém o cache alinhado com o que acabou de ser gravado no volume."""
    global _CACHE
    _CACHE = memories


async def list_memories() -> list[dict[str, Any]]:
    async with _LOCK:
        return [dict(item) for item in await _load()]


async def add_memory(text: str) -> dict[str, Any]:
    """Guarda uma informação e devolve o registro criado.

    Texto repetido não gera duplicata: devolve o registro já existente. Ao passar
    de ``MAX_MEMORIES``, as informações mais antigas são descartadas.
    """
    normalized = _normalize(text)[:MAX_MEMORY_CHARS]
    if not normalized:
        raise ValueError("A informação está vazia.")
    async with _LOCK:
        memories = await _load()
        for item in memories:
            if item["text"].casefold() == normalized.casefold():
                return dict(item)
        record = {"id": str(uuid.uuid4()), "text": normalized, "created_at": _now()}
        memories.append(record)
        del memories[:-MAX_MEMORIES]
        await asyncio.to_thread(_write_to_disk, memories)
        _set_cache(memories)
        return dict(record)


async def remove_memory(memory_id: str) -> bool:
    async with _LOCK:
        memories = await _load()
        remaining = [item for item in memories if item["id"] != memory_id]
        if len(remaining) == len(memories):
            return False
        await asyncio.to_thread(_write_to_disk, remaining)
        _set_cache(remaining)
        return True


async def clear_memories() -> int:
    async with _LOCK:
        memories = await _load()
        if memories:
            await asyncio.to_thread(_write_to_disk, [])
            _set_cache([])
        return len(memories)


def format_for_prompt(memories: list[dict[str, Any]]) -> str:
    """Monta o bloco de memória respeitando o orçamento de caracteres do prompt."""
    if not memories or MEMORY_PROMPT_CHARS <= 0:
        return ""
    lines: list[str] = []
    used = 0
    for item in reversed(memories):  # as mais recentes têm prioridade
        line = f"- {item['text']}"
        if used + len(line) > MEMORY_PROMPT_CHARS:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(reversed(lines))


async def prompt_block() -> str:
    """Bloco de memória para o prompt de sistema; nunca falha o chat."""
    try:
        memories = await list_memories()
    except MemoryUnavailable:
        logger.warning("Memória persistente indisponível ao montar o prompt")
        return ""
    return format_for_prompt(memories)


def status() -> dict[str, Any]:
    """Estado atual da memória, usado pelo endpoint de saúde."""
    return {
        "directory": str(MEMORY_DIR),
        "file": str(MEMORY_FILE),
        "count": len(_CACHE or []),
        "limit": MAX_MEMORIES,
    }
