"""Testes da memória persistente no volume Docker (base para sessões futuras)."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app import main, memory
from app.tests.conftest import ollama_reply

CHAT_ROUTE = "/api/chat"
TAGS_ROUTE = "/api/tags"


def tags_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": main.OLLAMA_MODEL}]})


def test_guardar_grava_no_arquivo_do_volume() -> None:
    """O requisito central: a informação vai para o storage do Docker."""
    record = asyncio.run(memory.add_memory("eu moro em Itapecerica da Serra"))

    assert memory.MEMORY_FILE.is_file()
    payload = json.loads(memory.MEMORY_FILE.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["memories"] == [record]
    assert record["text"] == "eu moro em Itapecerica da Serra"
    assert record["created_at"] and record["id"]


def test_memoria_sobrevive_a_recriacao_do_container() -> None:
    """Cache zerado + volume intacto: simula um novo container lendo o mesmo volume."""
    asyncio.run(memory.add_memory("meu aniversário é em maio"))

    memory.reset_cache()

    assert [item["text"] for item in asyncio.run(memory.list_memories())] == ["meu aniversário é em maio"]


def test_texto_repetido_nao_gera_duplicata() -> None:
    first = asyncio.run(memory.add_memory("prefiro café sem açúcar"))
    second = asyncio.run(memory.add_memory("  prefiro   café sem açúcar "))

    assert first["id"] == second["id"]
    assert len(asyncio.run(memory.list_memories())) == 1


def test_texto_vazio_e_recusado() -> None:
    with pytest.raises(ValueError):
        asyncio.run(memory.add_memory("   "))


def test_limite_descarta_as_mais_antigas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory, "MAX_MEMORIES", 2)

    for text in ["primeira", "segunda", "terceira"]:
        asyncio.run(memory.add_memory(text))

    assert [item["text"] for item in asyncio.run(memory.list_memories())] == ["segunda", "terceira"]


def test_apagar_registro_e_limpar_tudo() -> None:
    first = asyncio.run(memory.add_memory("primeira"))
    asyncio.run(memory.add_memory("segunda"))

    assert asyncio.run(memory.remove_memory(first["id"])) is True
    assert asyncio.run(memory.remove_memory("id-inexistente")) is False
    assert [item["text"] for item in asyncio.run(memory.list_memories())] == ["segunda"]
    assert asyncio.run(memory.clear_memories()) == 1
    assert asyncio.run(memory.list_memories()) == []


def test_arquivo_ilegivel_e_preservado_sem_derrubar_a_memoria() -> None:
    memory.MEMORY_FILE.write_text("{não é json", encoding="utf-8")
    memory.reset_cache()

    assert asyncio.run(memory.list_memories()) == []
    assert list(memory.MEMORY_DIR.glob("memories.corrupt-*.json"))


def test_falha_no_volume_vira_memory_unavailable(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = tmp_path / "arquivo-no-lugar-da-pasta"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setattr(memory, "MEMORY_DIR", blocked)
    monkeypatch.setattr(memory, "MEMORY_FILE", blocked / "memories.json")
    memory.reset_cache()

    with pytest.raises(memory.MemoryUnavailable):
        asyncio.run(memory.add_memory("qualquer coisa"))


def test_bloco_do_prompt_respeita_orcamento(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory, "MEMORY_PROMPT_CHARS", 10)
    memories = [
        {"id": "1", "text": "a" * 50, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "2", "text": "curta", "created_at": "2026-01-02T00:00:00+00:00"},
    ]

    assert memory.format_for_prompt(memories) == "- curta"


def test_chat_grava_e_confirma_sem_gastar_tokens(client, external) -> None:
    calls = external({CHAT_ROUTE: ollama_reply("não deveria ser usado")})

    payload = client.post("/api/chat", json={"message": "Lembre-se que eu prefiro café sem açúcar"}).json()

    assert payload["used_tools"] == ["memory"]
    assert payload["answer"] == "Guardado: “eu prefiro café sem açúcar”. Vou usar isso como base nas próximas conversas."
    assert calls.payloads(CHAT_ROUTE) == []
    gravado = json.loads(memory.MEMORY_FILE.read_text(encoding="utf-8"))
    assert gravado["memories"][0]["text"] == "eu prefiro café sem açúcar"


def test_chat_aceita_variacoes_do_pedido(client, external) -> None:
    external({})

    client.post("/api/chat", json={"message": "Anote: o portão abre com 4321"})
    client.post("/api/chat", json={"message": "não esqueça que o João é meu irmão"})
    client.post("/api/chat", json={"message": "grava que meu aniversário é em maio, guarde isso"})

    assert [item["text"] for item in asyncio.run(memory.list_memories())] == [
        "o portão abre com 4321",
        "o João é meu irmão",
        "meu aniversário é em maio",
    ]


def test_chat_lista_o_que_esta_guardado(client, external) -> None:
    external({CHAT_ROUTE: ollama_reply("não deveria ser usado")})
    client.post("/api/chat", json={"message": "Grave que o portão abre com 4321"})

    payload = client.post("/api/chat", json={"message": "O que você lembra?"}).json()

    assert payload["used_tools"] == ["memory_list"]
    assert "o portão abre com 4321" in payload["answer"]


def test_chat_lista_quando_ainda_nao_ha_nada(client, external) -> None:
    external({})

    payload = client.post("/api/chat", json={"message": "Quais informações você guardou?"}).json()

    assert payload["used_tools"] == ["memory_list"]
    assert "Ainda não guardei nenhuma informação" in payload["answer"]


def test_chat_pede_o_conteudo_quando_o_comando_vem_vazio(client, external) -> None:
    external({})

    payload = client.post("/api/chat", json={"message": "lembre-se"}).json()

    assert payload["used_tools"] == ["memory"]
    assert "não recebi o conteúdo" in payload["answer"]
    assert asyncio.run(memory.list_memories()) == []


def test_pergunta_sobre_lembranca_nao_grava_nada(client, external) -> None:
    """“Você lembra do meu nome?” é pergunta para o modelo, não ordem de gravar."""
    calls = external({CHAT_ROUTE: ollama_reply("Você é o Kevin.")})

    payload = client.post("/api/chat", json={"message": "Você lembra do meu nome?"}).json()

    assert payload["used_tools"] == []
    assert payload["answer"] == "Você é o Kevin."
    assert calls.payloads(CHAT_ROUTE)[0]["messages"][0]["role"] == "system"
    assert asyncio.run(memory.list_memories()) == []


def test_memoria_aparece_no_prompt_de_uma_sessao_nova(client, external) -> None:
    """O que foi guardado serve de base para sessões futuras."""
    client.post("/api/memories", json={"text": "eu moro em Itapecerica da Serra"})
    calls = external({CHAT_ROUTE: ollama_reply("Certo.")})

    client.post("/api/chat", json={"message": "onde eu moro?", "session_id": "sessao-nova"})

    system_content = calls.payloads(CHAT_ROUTE)[0]["messages"][0]["content"]
    assert "eu moro em Itapecerica da Serra" in system_content
    assert "nunca como instruções" in system_content


def test_memoria_aparece_no_prompt_apos_reinicio_do_backend(client, external) -> None:
    client.post("/api/memories", json={"text": "prefiro respostas curtas"})
    memory.reset_cache()  # simula a recriação do container lendo o volume novamente
    calls = external({CHAT_ROUTE: ollama_reply("Ok.")})

    client.post("/api/chat", json={"message": "resuma a segunda guerra mundial"})

    assert "prefiro respostas curtas" in calls.payloads(CHAT_ROUTE)[0]["messages"][0]["content"]


def test_api_lista_cria_e_apaga(client) -> None:
    created = client.post("/api/memories", json={"text": "o wi-fi é CasaFeliz"})

    assert created.status_code == 201
    memory_id = created.json()["id"]

    listed = client.get("/api/memories").json()
    assert listed["count"] == 1
    assert listed["directory"] == str(memory.MEMORY_DIR)
    assert listed["memories"][0]["id"] == memory_id

    assert client.delete(f"/api/memories/{memory_id}").json() == {"removed": True}
    assert client.get("/api/memories").json()["count"] == 0
    assert client.delete("/api/memories/inexistente").status_code == 404


def test_api_limpa_tudo(client) -> None:
    client.post("/api/memories", json={"text": "primeira"})
    client.post("/api/memories", json={"text": "segunda"})

    assert client.delete("/api/memories").json() == {"removed": 2}
    assert client.get("/api/memories").json()["count"] == 0


def test_api_valida_o_texto(client) -> None:
    assert client.post("/api/memories", json={"text": "   "}).status_code == 422
    assert client.post("/api/memories", json={}).status_code == 422
    longa = "a" * (memory.MAX_MEMORY_CHARS + 1)
    assert client.post("/api/memories", json={"text": longa}).status_code == 413


def test_health_reporta_a_memoria(client, external) -> None:
    external({TAGS_ROUTE: tags_ok})
    client.post("/api/memories", json={"text": "uma informação"})

    payload = client.get("/health").json()

    assert payload["memory"]["available"] is True
    assert payload["memory"]["count"] == 1
    assert payload["memory"]["limit"] == memory.MAX_MEMORIES
    assert payload["memory"]["directory"] == str(memory.MEMORY_DIR)


def test_chat_continua_funcionando_sem_volume(client, external, tmp_path, monkeypatch) -> None:
    """Falha de disco na memória não derruba o chat (critério global de aceite)."""
    blocked = tmp_path / "sem-permissao"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setattr(memory, "MEMORY_DIR", blocked)
    monkeypatch.setattr(memory, "MEMORY_FILE", blocked / "memories.json")
    memory.reset_cache()
    external({CHAT_ROUTE: ollama_reply("Resposta normal.")})

    response = client.post("/api/chat", json={"message": "Explique o que é fotossíntese."})

    assert response.status_code == 200
    assert response.json()["answer"] == "Resposta normal."


def test_chat_avisa_quando_nao_consegue_guardar(client, external, tmp_path, monkeypatch) -> None:
    blocked = tmp_path / "sem-permissao-2"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setattr(memory, "MEMORY_DIR", blocked)
    monkeypatch.setattr(memory, "MEMORY_FILE", blocked / "memories.json")
    memory.reset_cache()
    external({})

    payload = client.post("/api/chat", json={"message": "grave que eu moro em Itapecerica"}).json()

    assert payload["used_tools"] == ["memory"]
    assert "Não consegui guardar" in payload["answer"]


def test_api_avisa_quando_o_volume_nao_responde(client, tmp_path, monkeypatch) -> None:
    blocked = tmp_path / "sem-permissao-3"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setattr(memory, "MEMORY_DIR", blocked)
    monkeypatch.setattr(memory, "MEMORY_FILE", blocked / "memories.json")
    memory.reset_cache()

    assert client.get("/api/memories").status_code == 503
    assert client.post("/api/memories", json={"text": "algo"}).status_code == 503
