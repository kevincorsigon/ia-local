"""Testes de API do backend com Ollama, ferramentas e Kokoro simulados (Fase 9 da SPEC)."""
from __future__ import annotations

import io
import wave
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import main, tools
from app.tests.conftest import ollama_reply, raises

OLLAMA_TAGS = {"models": [{"name": main.OLLAMA_MODEL}]}
TAGS_ROUTE = "/api/tags"
CHAT_ROUTE = "/api/chat"

GEO_ROUTE = "geocoding-api.open-meteo.com"
FORECAST_ROUTE = "api.open-meteo.com/v1/forecast"
BRAVE_ROUTE = "api.search.brave.com"
TTS_ROUTE = "/v1/audio/speech"

GEO_REPLY = {
    "results": [
        {
            "name": "Itapecerica da Serra",
            "admin1": "São Paulo",
            "country_code": "BR",
            "latitude": -23.7167,
            "longitude": -46.85,
        }
    ]
}
FORECAST_REPLY = {
    "daily": {
        "time": ["2026-10-03", "2026-10-04"],
        "weather_code": [61, 3],
        "temperature_2m_max": [24.1, 22.0],
        "temperature_2m_min": [14.4, 13.0],
        "precipitation_probability_max": [94, 40],
    }
}


def tags_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=OLLAMA_TAGS)


def test_health_reporta_ollama_e_modelo(client, external) -> None:
    external({TAGS_ROUTE: tags_ok})

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["ollama"] == "ok"
    assert payload["model"] == main.OLLAMA_MODEL
    assert payload["model_available"] is True


def test_health_degradado_nao_derruba_a_interface(client, external) -> None:
    """Critério global de aceite: falha de dependência não derruba a interface."""
    external({TAGS_ROUTE: lambda request: httpx.Response(503, json={})})

    health = client.get("/health")
    config = client.get("/api/config/public")

    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["model_available"] is False
    assert config.status_code == 200
    assert config.json()["assistant_name"] == main.ASSISTANT_NAME


def test_config_publica_nao_expoe_segredos(client, external, monkeypatch) -> None:
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "chave-super-secreta")
    external({TAGS_ROUTE: tags_ok})

    response = client.get("/api/config/public")

    assert response.status_code == 200
    assert "chave-super-secreta" not in response.text
    assert "BRAVE" not in response.text


def test_config_publica_expoe_as_janelas_de_voz(client, external) -> None:
    """A interface precisa saber por quanto tempo a conversa fica ativa sem alcunha."""
    external({TAGS_ROUTE: tags_ok})

    payload = client.get("/api/config/public").json()

    assert payload["follow_up_seconds"] == 8
    assert payload["conversation_seconds"] == 60
    assert payload["wake_phrases"]


def test_chat_geral_usa_so_o_modelo_local(client, external) -> None:
    calls = external({CHAT_ROUTE: ollama_reply("Fotossíntese converte luz em energia.")})

    response = client.post("/api/chat", json={"message": "Explique em uma frase o que é fotossíntese."})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Fotossíntese converte luz em energia."
    assert payload["used_tools"] == []
    assert payload["sources"] == []
    assert payload["should_speak"] is True
    assert payload["session_id"]
    assert calls.unmatched == []

    enviado = calls.payloads(CHAT_ROUTE)[0]
    assert enviado["model"] == main.OLLAMA_MODEL
    assert enviado["messages"][0]["role"] == "system"
    assert main.ASSISTANT_NAME in enviado["messages"][0]["content"]
    assert enviado["options"]["num_predict"] == main.MAX_RESPONSE_TOKENS
    # Tuning de velocidade via .env: o backend manda tudo em options.*.
    assert enviado["options"]["num_ctx"] == main.OLLAMA_NUM_CTX
    assert enviado["options"]["num_thread"] == main.OLLAMA_NUM_THREAD
    assert enviado["options"]["num_batch"] == main.OLLAMA_NUM_BATCH
    assert enviado["options"]["temperature"] == main.OLLAMA_TEMPERATURE
    assert enviado["options"]["repeat_penalty"] == main.OLLAMA_REPEAT_PENALTY
    # Thinking desligado por padrão: sem think=false o Gemma 4 gasta o orçamento
    # no raciocínio e devolve content vazio (foi o HC reprovado com 400 e 1200).
    assert enviado["think"] is False


@pytest.mark.parametrize("llm_mode", ["groq", "cloud"])
def test_chat_usa_groq_quando_configurado(client, external, monkeypatch, llm_mode) -> None:
    monkeypatch.setenv("LLM_MODE", llm_mode)
    monkeypatch.setenv("GROQ_API_KEY", "teste-chave")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    def groq_reply(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer teste-chave"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Resposta Groq."}}]},
        )

    calls = external({"api.groq.com": groq_reply})

    response = client.post("/api/chat", json={"message": "Responda apenas: teste."})

    assert response.status_code == 200
    assert response.json()["answer"] == "Resposta Groq."
    assert calls.unmatched == []
    enviado = calls.payloads("api.groq.com")[0]
    assert enviado["model"] == "llama-3.3-70b-versatile"
    assert enviado["max_tokens"] == main.MAX_RESPONSE_TOKENS
    assert "options" not in enviado


def test_chat_desliga_thinking_e_reaproveita_thinking_vazio(client, external) -> None:
    """Gemma 4 com thinking ligado: content vazio + thinking usa o thinking."""

    def thinking_reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "", "thinking": "Canberra."}}
        )

    calls = external({CHAT_ROUTE: thinking_reply})

    response = client.post("/api/chat", json={"message": "Qual é a capital da Austrália?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Canberra."
    assert calls.payloads(CHAT_ROUTE)[0]["think"] is False


def test_chat_mantem_contexto_e_isola_sessoes(client, external) -> None:
    """Duas sessões não misturam contexto (aceite da Fase 2)."""
    calls = external({CHAT_ROUTE: ollama_reply("Combinado.")})

    primeira = client.post(
        "/api/chat", json={"message": "Meu nome é Kevin.", "session_id": "teste-sessao-a"}
    ).json()
    client.post("/api/chat", json={"message": "Qual é o meu nome?", "session_id": "teste-sessao-a"})
    client.post("/api/chat", json={"message": "Qual é o meu nome?", "session_id": "teste-sessao-b"})

    assert primeira["session_id"] == "teste-sessao-a"
    enviados = calls.payloads(CHAT_ROUTE)
    assert [item["role"] for item in enviados[0]["messages"]] == ["system", "user"]
    assert [item["role"] for item in enviados[1]["messages"]] == ["system", "user", "assistant", "user"]
    assert enviados[1]["messages"][1]["content"] == "Meu nome é Kevin."
    assert [item["role"] for item in enviados[2]["messages"]] == ["system", "user"]


def test_chat_registra_resposta_direta_no_contexto(client, external) -> None:
    """A resposta direta da ferramenta (pedir a cidade) entra no contexto que o modelo recebe."""
    calls = external({CHAT_ROUTE: ollama_reply("Certo, anotei.")})

    sessao = {"session_id": "teste-contexto-direto"}
    pedido = client.post("/api/chat", json={"message": "Como fica o tempo hoje?", **sessao}).json()
    assert "preciso saber a cidade" in pedido["answer"]

    client.post("/api/chat", json={"message": "obrigado", **sessao})

    enviados = calls.payloads(CHAT_ROUTE)[0]
    assert [item["role"] for item in enviados["messages"]] == ["system", "user", "assistant", "user"]
    assert "preciso saber a cidade" in enviados["messages"][2]["content"]


def test_session_endpoint_devolve_o_historico(client, external) -> None:
    """A interface usa isto para redesenhar a conversa e manter o mesmo contexto do modelo."""
    external({CHAT_ROUTE: ollama_reply("Olá!")})

    sessao = {"session_id": "teste-historico"}
    client.post("/api/chat", json={"message": "oi", **sessao})

    payload = client.get("/api/session/teste-historico").json()

    assert payload["session_id"] == "teste-historico"
    assert payload["messages"] == [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "Olá!"},
    ]


def test_session_endpoint_de_sessao_desconhecida_e_vazio(client, external) -> None:
    external({})

    payload = client.get("/api/session/nao-existe").json()

    assert payload["messages"] == []


def test_chat_gera_session_id_quando_vem_sem_um(client, external) -> None:
    external({CHAT_ROUTE: ollama_reply("Olá!")})

    payload = client.post("/api/chat", json={"message": "oi"}).json()

    assert payload["session_id"]
    assert payload["session_id"] != "oi"


def test_chat_de_clima_devolve_previsao_com_fonte(client, external) -> None:
    calls = external(
        {
            GEO_ROUTE: lambda request: httpx.Response(200, json=GEO_REPLY),
            FORECAST_ROUTE: lambda request: httpx.Response(200, json=FORECAST_REPLY),
            CHAT_ROUTE: ollama_reply("Vai chover nesta semana."),
        }
    )

    response = client.post(
        "/api/chat", json={"message": "Como fica o tempo esta semana em Itapecerica da Serra?"}
    )

    payload = response.json()
    assert payload["used_tools"] == ["weather"]
    assert payload["sources"] == [{"title": "Open-Meteo — previsão do tempo", "url": "https://open-meteo.com/"}]
    assert calls.unmatched == []

    prompt = calls.payloads(CHAT_ROUTE)[0]["messages"][-1]["content"]
    assert "chuva leve" in prompt
    assert "mínima 14.4°C, máxima 24.1°C" in prompt
    assert "chance de chuva 94%" in prompt


def test_chat_de_clima_com_cidade_ambigua_pede_escolha(client, external) -> None:
    """Resposta direta da ferramenta, sem gastar tokens do modelo."""
    calls = external(
        {
            GEO_ROUTE: lambda request: httpx.Response(
                200,
                json={
                    "results": [
                        {"name": "Santos", "admin1": "São Paulo", "country_code": "BR", "latitude": -23.9, "longitude": -46.3},
                        {"name": "Santos", "admin1": "Outro estado", "country_code": "BR", "latitude": -20.1, "longitude": -44.2},
                    ]
                },
            )
        }
    )

    payload = client.post("/api/chat", json={"message": "Como fica o tempo em Santos?"}).json()

    assert payload["used_tools"] == ["weather"]
    assert payload["sources"] == []
    assert "mais de uma cidade" in payload["answer"]
    assert calls.payloads(CHAT_ROUTE) == []


def test_chat_de_clima_de_cidade_conhecida_nao_pede_escolha(client, external) -> None:
    """A API devolve “São Paulo” com parecidos (Frei Paulo) e homônimos menores: não vale perguntar."""
    calls = external(
        {
            GEO_ROUTE: lambda request: httpx.Response(
                200,
                json={
                    "results": [
                        {"name": "São Paulo", "admin1": "São Paulo", "country_code": "BR", "latitude": -23.55, "longitude": -46.63, "population": 10021295},
                        {"name": "Frei Paulo", "admin1": "Sergipe", "country_code": "BR", "latitude": -10.55, "longitude": -37.53},
                        {"name": "São Paulo", "admin1": "Alagoas", "country_code": "BR", "latitude": -9.75, "longitude": -36.34, "population": 1500},
                    ]
                },
            ),
            FORECAST_ROUTE: lambda request: httpx.Response(200, json=FORECAST_REPLY),
            CHAT_ROUTE: ollama_reply("Vai chover nesta semana."),
        }
    )

    payload = client.post(
        "/api/chat", json={"message": "Qual é a previsão do tempo para hoje em São Paulo?"}
    ).json()

    assert payload["used_tools"] == ["weather"]
    assert payload["sources"] == [{"title": "Open-Meteo — previsão do tempo", "url": "https://open-meteo.com/"}]
    assert calls.unmatched == []


def test_chat_de_clima_reaproveita_a_cidade_da_sessao(client, external) -> None:
    """“a previsão do tempo lá?” usa a cidade já falada na sessão, sem pedir de novo."""
    calls = external(
        {
            GEO_ROUTE: lambda request: httpx.Response(200, json=GEO_REPLY),
            FORECAST_ROUTE: lambda request: httpx.Response(200, json=FORECAST_REPLY),
            CHAT_ROUTE: ollama_reply("Vai chover nesta semana."),
        }
    )

    sessao = {"session_id": "teste-clima-contexto"}
    client.post(
        "/api/chat",
        json={"message": "Como fica o tempo esta semana em Itapecerica da Serra?", **sessao},
    )
    payload = client.post("/api/chat", json={"message": "a previsão do tempo lá", **sessao}).json()

    assert payload["used_tools"] == ["weather"]
    assert payload["sources"] == [{"title": "Open-Meteo — previsão do tempo", "url": "https://open-meteo.com/"}]
    assert "preciso saber a cidade" not in payload["answer"]
    # As duas perguntas geocodificaram a mesma cidade (a segunda reaproveitou a lembrança).
    geocodificadas = [url for url in calls.urls(GEO_ROUTE) if "itapecerica" in url.casefold()]
    assert len(geocodificadas) == 2
    assert calls.unmatched == []


def test_capabilities_lista_as_ferramentas(client, external) -> None:
    """O catálogo fica registrado na API — o mesmo que o modelo recebe no prompt."""
    external({})

    payload = client.get("/api/capabilities").json()

    titulos = [item["title"] for item in payload["capabilities"]]
    assert payload["assistant_name"] == main.ASSISTANT_NAME
    assert len(titulos) >= 4
    assert any("Clima" in titulo for titulo in titulos)
    assert any("Pesquisa na internet" in titulo for titulo in titulos)
    assert any("Memória" in titulo for titulo in titulos)


def test_prompt_do_modelo_traz_o_catalogo(client, external) -> None:
    """O modelo precisa saber quais ferramentas existem para poder listá-las sob demanda."""
    calls = external({CHAT_ROUTE: ollama_reply("Consigo ver o clima e pesquisar na internet.")})

    client.post("/api/chat", json={"message": "Quais ferramentas você tem?"})

    sistema = calls.payloads(CHAT_ROUTE)[0]["messages"][0]["content"]
    assert "Ferramentas que você tem" in sistema
    assert "Clima" in sistema
    assert "Pesquisa na internet" in sistema
    assert "Memória" in sistema
    assert "Não invente outras capacidades" in sistema


def test_chat_remove_o_markdown_da_resposta(client, external) -> None:
    """O balão mostra o texto literal e a voz leria os asteriscos: a resposta sai em texto simples."""
    external(
        {
            CHAT_ROUTE: ollama_reply(
                "Eu tenho disponível: 🚀\n\n*   **Clima:** 🙂 previsão de 7 dias\n*   **Esportes:** ⚽ próximos jogos"
            )
        }
    )

    payload = client.post("/api/chat", json={"message": "Quais ferramentas você tem?"}).json()

    assert "*" not in payload["answer"]
    assert payload["answer"] == (
        "Eu tenho disponível:\n\n- Clima: previsão de 7 dias\n- Esportes: próximos jogos"
    )


def test_catalogo_usa_o_padrao_sem_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "ASSISTANT_SETTINGS", {})

    assert main.load_capabilities() == main.DEFAULT_CAPABILITIES


def test_catalogo_le_do_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        "ASSISTANT_SETTINGS",
        {"capabilities": [{"title": "Rádio", "detail": "tocar música"}]},
    )

    assert main.load_capabilities() == [{"title": "Rádio", "detail": "tocar música"}]


def test_catalogo_ignora_entradas_incompletas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        "ASSISTANT_SETTINGS",
        {"capabilities": [{"title": "Sem detalhe"}, {"detail": "sem título"}, "texto solto"]},
    )

    assert main.load_capabilities() == main.DEFAULT_CAPABILITIES


def test_chat_de_clima_aproveita_a_cidade_corrigida(client, external) -> None:
    """Falha de geocodificação → a próxima fala com o nome corrigido volta para o clima.

    Antes, “Itapcerica da Serra, São Paulo” caía na conversa livre e o modelo inventava uma
    previsão com números que nunca vieram de ferramenta nenhuma.
    """
    tentativas = {"n": 0}

    def geocodifica(request: httpx.Request) -> httpx.Response:
        tentativas["n"] += 1
        # A primeira grafia (com erro) não existe; a corrigida sim.
        if tentativas["n"] == 1:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=GEO_REPLY)

    calls = external(
        {
            GEO_ROUTE: geocodifica,
            FORECAST_ROUTE: lambda request: httpx.Response(200, json=FORECAST_REPLY),
            CHAT_ROUTE: ollama_reply("Vai chover nesta semana."),
        }
    )

    sessao = {"session_id": "teste-clima-correcao"}
    errado = client.post(
        "/api/chat",
        json={"message": "qual a previsão do tempo em Itapcerica da Serra", **sessao},
    ).json()

    assert errado["used_tools"] == ["weather"]
    assert "Não encontrei uma cidade brasileira" in errado["answer"]
    assert errado["sources"] == []
    # Nada foi ao modelo: nenhuma previsão inventada.
    assert calls.urls(CHAT_ROUTE) == []

    certo = client.post(
        "/api/chat", json={"message": "Itapcerica da Serra, São Paulo", **sessao}
    ).json()

    assert certo["used_tools"] == ["weather"]
    assert certo["sources"], "a fala com a cidade corrigida deveria consultar o clima"
    assert len(calls.urls(CHAT_ROUTE)) == 1
    assert calls.unmatched == []


def test_chat_de_clima_fora_do_brasil_nao_inventa(client, external) -> None:
    external({GEO_ROUTE: lambda request: httpx.Response(200, json={"results": [{"name": "Lisboa", "country_code": "PT"}]})})

    payload = client.post("/api/chat", json={"message": "Como fica o tempo em Lisboa?"}).json()

    assert payload["used_tools"] == ["weather"]
    assert "cidade brasileira" in payload["answer"]


def test_chat_informa_falha_quando_a_ferramenta_de_clima_cai(client, external) -> None:
    external({GEO_ROUTE: lambda request: httpx.Response(503, json={})})

    payload = client.post("/api/chat", json={"message": "Como fica o tempo em Curitiba?"}).json()

    assert payload["used_tools"] == ["weather"]
    assert payload["answer"] == "Não consegui consultar a previsão do tempo agora. Tente novamente daqui a pouco."


def test_chat_sem_chave_brave_avisa_em_vez_de_inventar(client, external, monkeypatch) -> None:
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "")
    calls = external({CHAT_ROUTE: ollama_reply("Não deveria ser usado.")})

    payload = client.post("/api/chat", json={"message": "Pesquise notícias de hoje sobre o mercado."}).json()

    assert payload["used_tools"] == ["web_search"]
    assert "precisa ser configurada" in payload["answer"]
    assert calls.unmatched == []
    assert calls.payloads(CHAT_ROUTE) == []


def test_chat_de_pesquisa_devolve_fontes_e_nao_vaza_chave(client, external, monkeypatch) -> None:
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "chave-super-secreta")
    calls = external(
        {
            BRAVE_ROUTE: lambda request: httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"title": "Manchete A", "url": "https://exemplo.com/a", "description": "Resumo A."},
                            {"title": "Ignorado", "url": "http://exemplo.com/b", "description": "Sem https."},
                        ]
                    }
                },
            ),
            CHAT_ROUTE: ollama_reply("Encontrei duas informações."),
        }
    )

    response = client.post("/api/chat", json={"message": "Pesquise notícias de hoje sobre o mercado."})

    payload = response.json()
    assert payload["used_tools"] == ["web_search"]
    assert payload["sources"] == [{"title": "Manchete A", "url": "https://exemplo.com/a"}]
    assert "chave-super-secreta" not in response.text
    assert calls.unmatched == []


def test_chat_de_pesquisa_remove_o_comando_da_consulta(client, external, monkeypatch) -> None:
    """“pesquisa na internet X” procura por “X”, não pelo comando inteiro."""
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "chave-de-teste")
    calls = external(
        {
            BRAVE_ROUTE: lambda request: httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"title": "Capital", "url": "https://exemplo.com/a", "description": "Camberra."}
                        ]
                    }
                },
            ),
            CHAT_ROUTE: ollama_reply("A capital é Camberra."),
        }
    )

    client.post("/api/chat", json={"message": "pesquisa na internet qual a capital da Austrália"})

    consulta = parse_qs(urlparse(calls.urls(BRAVE_ROUTE)[0]).query)["q"][0]
    assert consulta == "qual a capital da Austrália"


def test_chat_de_pesquisa_usa_a_proxima_fala_como_consulta(client, external, monkeypatch) -> None:
    """Comando sozinho pergunta o termo e usa a próxima fala como busca (mesma sessão)."""
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "chave-de-teste")
    calls = external(
        {
            BRAVE_ROUTE: lambda request: httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"title": "Capital", "url": "https://exemplo.com/a", "description": "Camberra."}
                        ]
                    }
                },
            ),
            CHAT_ROUTE: ollama_reply("A capital é Camberra."),
        }
    )

    sessao = {"session_id": "teste-busca-contexto"}
    pedido = client.post("/api/chat", json={"message": "pesquisa na internet", **sessao}).json()
    assert pedido["used_tools"] == ["web_search"]
    assert "que eu pesquise na internet" in pedido["answer"]
    assert calls.urls(BRAVE_ROUTE) == []

    resposta = client.post("/api/chat", json={"message": "qual a capital da Austrália", **sessao}).json()

    assert resposta["used_tools"] == ["web_search"]
    assert calls.unmatched == []
    assert parse_qs(urlparse(calls.urls(BRAVE_ROUTE)[0]).query)["q"][0] == "qual a capital da Austrália"


def test_memoria_orienta_a_ferramenta_de_busca(client, external, monkeypatch) -> None:
    """“Guideline” salva na memória entra na consulta e na ordem das fontes."""
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "chave-de-teste")
    client.post(
        "/api/memories",
        json={"text": "Sempre use o site meutimao.com.br quando eu perguntar sobre o Corinthians"},
    )
    calls = external(
        {
            BRAVE_ROUTE: lambda request: httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "Outro site",
                                "url": "https://exemplo.com/a",
                                "description": "Nada a ver.",
                            },
                            {
                                "title": "Meu Timão",
                                "url": "https://meutimao.com.br/jogos",
                                "description": "Próximo jogo.",
                            },
                        ]
                    }
                },
            ),
            CHAT_ROUTE: ollama_reply("O próximo jogo é sábado."),
        }
    )

    payload = client.post(
        "/api/chat", json={"message": "Qual é o próximo jogo do Corinthians?"}
    ).json()

    assert payload["used_tools"] == ["sports"]
    assert "meutimao.com.br" in calls.urls(BRAVE_ROUTE)[0]
    assert payload["sources"][0]["url"] == "https://meutimao.com.br/jogos"
    assert calls.unmatched == []


def test_memoria_sem_fonte_nao_desvia_a_busca(client, external, monkeypatch) -> None:
    """Memória que não manda usar fonte não entra na consulta."""
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "chave-de-teste")
    client.post("/api/memories", json={"text": "eu moro em Itapecerica da Serra"})
    calls = external(
        {
            BRAVE_ROUTE: lambda request: httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"title": "Dólar", "url": "https://exemplo.com/d", "description": "Hoje."}
                        ]
                    }
                },
            ),
            CHAT_ROUTE: ollama_reply("O dólar está em alta."),
        }
    )

    client.post("/api/chat", json={"message": "Pesquise notícias de hoje sobre o mercado."})

    assert "itapecerica" not in calls.urls(BRAVE_ROUTE)[0].casefold()
    assert calls.unmatched == []


def test_chat_de_esporte_usa_pesquisa_esportiva(client, external, monkeypatch) -> None:
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "chave-de-teste")
    calls = external(
        {
            BRAVE_ROUTE: lambda request: httpx.Response(
                200,
                json={"web": {"results": [{"title": "Próximo jogo", "url": "https://exemplo.com/jogo", "description": "Sábado."}]}},
            ),
            CHAT_ROUTE: ollama_reply("O próximo jogo é sábado."),
        }
    )

    payload = client.post("/api/chat", json={"message": "Quando é o próximo jogo do Corinthians?"}).json()

    assert payload["used_tools"] == ["sports"]
    assert payload["sources"][0]["url"] == "https://exemplo.com/jogo"
    assert "Corinthians" in calls.urls(BRAVE_ROUTE)[0]


def test_chat_reporta_erro_do_ollama(client, external) -> None:
    """Erro 5xx do Ollama vira 502 com explicação em pt-BR, sem stack trace."""
    external({CHAT_ROUTE: lambda request: httpx.Response(500, json={})})

    response = client.post("/api/chat", json={"message": "oi"})

    assert response.status_code == 502
    assert response.json()["detail"] == "O Ollama retornou um erro ao gerar a resposta."


def test_chat_avisa_quando_o_modelo_nao_existe(client, external) -> None:
    """404 do Ollama orienta a rodar o bootstrap (modelo não baixado)."""
    external({CHAT_ROUTE: lambda request: httpx.Response(404, json={})})

    response = client.post("/api/chat", json={"message": "oi"})

    assert response.status_code == 503
    assert main.OLLAMA_MODEL in response.json()["detail"]
    assert "./scripts/bootstrap.sh" in response.json()["detail"]


def test_chat_avisa_quando_o_ollama_esta_fora_do_ar(client, external) -> None:
    external({CHAT_ROUTE: raises(httpx.ConnectError("sem rota"))})

    response = client.post("/api/chat", json={"message": "oi"})

    assert response.status_code == 503
    assert "Não consegui acessar o Ollama no host" in response.json()["detail"]


def test_chat_avisa_quando_o_modelo_demora(client, external) -> None:
    external({CHAT_ROUTE: raises(httpx.ReadTimeout("lento"))})

    response = client.post("/api/chat", json={"message": "oi"})

    assert response.status_code == 504
    assert "demorou demais" in response.json()["detail"]


def test_chat_rejeita_resposta_vazia_do_modelo(client, external) -> None:
    external({CHAT_ROUTE: ollama_reply("   ")})

    response = client.post("/api/chat", json={"message": "oi"})

    assert response.status_code == 502
    assert response.json()["detail"] == "O modelo retornou uma resposta vazia."


def test_mensagem_vazia_e_rejeitada(client, external) -> None:
    external({})

    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.post("/api/chat", json={}).status_code == 422


def test_mensagem_longa_e_rejeitada(client, external) -> None:
    external({})

    longa = "a" * (main.MAX_MESSAGE_CHARS + 1)

    assert client.post("/api/chat", json={"message": longa}).status_code == 413


def test_mensagem_no_limite_e_aceita(client, external) -> None:
    external({CHAT_ROUTE: ollama_reply("Ok.")})

    no_limite = "a" * main.MAX_MESSAGE_CHARS

    assert client.post("/api/chat", json={"message": no_limite}).status_code == 200


def test_speak_devolve_wav_do_kokoro(client, external) -> None:
    audio = b"RIFF" + b"\x00" * 4096
    calls = external(
        {TTS_ROUTE: lambda request: httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})}
    )

    response = client.post("/api/speak", json={"text": "Olá, eu sou a Kunica."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == audio
    assert calls.payloads(TTS_ROUTE)[0] == {
        "model": "kokoro",
        "input": "Olá, eu sou a Kunica.",
        "voice": main.TTS_VOICE,
        "response_format": "wav",
    }


def test_speak_devolve_wav_do_piper(client, external, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = b"RIFF" + b"\x00" * 4096
    monkeypatch.setattr(main, "TTS_ENGINE", "piper")
    monkeypatch.setattr(main, "TTS_URL", "http://piper:8890")
    monkeypatch.setattr(main, "TTS_VOICE", "dii")
    monkeypatch.setattr(main, "TTS_MODEL", "piper")
    calls = external(
        {TTS_ROUTE: lambda request: httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})}
    )

    response = client.post("/api/speak", json={"text": "Olá, eu sou a Kunica."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == audio
    assert calls.payloads(TTS_ROUTE)[0] == {
        "model": "piper",
        "input": "Olá, eu sou a Kunica.",
        "voice": "dii",
        "response_format": "wav",
    }


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        ("kokoro", ("kokoro", "http://kokoro:8880", "pf_dora", "kokoro")),
        ("piper", ("piper", "http://piper:8890", "dii", "piper")),
        ("unknown", ("kokoro", "http://kokoro:8880", "pf_dora", "kokoro")),
    ],
)
def test_resolve_tts_usa_padrao_por_motor(engine: str, expected: tuple[str, str, str, str]) -> None:
    assert main.resolve_tts(engine, "", "") == expected


def test_resolve_tts_preserva_overrides_nao_vazios() -> None:
    assert main.resolve_tts("piper", "http://tts.local:9000/", "custom") == (
        "piper",
        "http://tts.local:9000",
        "custom",
        "piper",
    )


def test_speak_indisponivel_preserva_a_resposta_escrita(client, external) -> None:
    external({TTS_ROUTE: lambda request: httpx.Response(503, json={})})

    response = client.post("/api/speak", json={"text": "Olá."})

    assert response.status_code == 503
    assert "Síntese de voz indisponível" in response.json()["detail"]


def test_speak_valida_texto(client, external) -> None:
    external({})

    assert client.post("/api/speak", json={"text": "   "}).status_code == 422
    assert client.post("/api/speak", json={"text": "a" * 2001}).status_code == 413


def test_transcribe_rejeita_audio_vazio(client, external) -> None:
    external({})

    assert client.post("/api/transcribe", content=b"").status_code == 400


def test_transcribe_rejeita_audio_grande_demais(client, external) -> None:
    external({})

    assert client.post("/api/transcribe", content=b"\x00" * (main.MAX_AUDIO_BYTES + 1)).status_code == 413


@pytest.mark.skipif(not main.stt.model_ready(), reason="modelo de fala não está disponível neste ambiente")
def test_transcribe_silencio_devolve_texto_vazio(client) -> None:
    """Exercita FFmpeg + Vosk de verdade: silêncio não pode gerar texto."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)

    response = client.post(
        "/api/transcribe", content=buffer.getvalue(), headers={"content-type": "audio/wav"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == ""
    assert 0.0 <= payload["confidence"] <= 1.0


def test_chat_usa_a_instancia_alternativa_de_ollama(client, external, monkeypatch) -> None:
    """Cobre 'docker compose up' sem bootstrap: a URL principal é a outra instância."""
    monkeypatch.setattr(main, "OLLAMA_BASE_URL", "http://ollama-principal:11434")
    monkeypatch.setattr(main, "OLLAMA_FALLBACK_URL", "http://ollama-alternativo:11434")
    monkeypatch.setattr(main, "_ACTIVE_OLLAMA_URL", None)
    calls = external(
        {
            "ollama-principal": raises(httpx.ConnectError("fora do ar")),
            "ollama-alternativo": ollama_reply("Respondi pela reserva."),
        }
    )

    payload = client.post("/api/chat", json={"message": "oi"}).json()

    assert payload["answer"] == "Respondi pela reserva."
    assert calls.urls("ollama-principal") and calls.urls("ollama-alternativo")
    assert main._ACTIVE_OLLAMA_URL == "http://ollama-alternativo:11434"


def test_health_usa_a_instancia_alternativa_de_ollama(client, external, monkeypatch) -> None:
    monkeypatch.setattr(main, "OLLAMA_BASE_URL", "http://ollama-principal:11434")
    monkeypatch.setattr(main, "OLLAMA_FALLBACK_URL", "http://ollama-alternativo:11434")
    monkeypatch.setattr(main, "_ACTIVE_OLLAMA_URL", None)
    external(
        {
            "ollama-principal": raises(httpx.ConnectError("fora do ar")),
            "ollama-alternativo": lambda request: httpx.Response(
                200, json={"models": [{"name": main.OLLAMA_MODEL}]}
            ),
        }
    )

    payload = client.get("/health").json()

    assert payload["ollama"] == "ok"
    assert payload["model_available"] is True


def test_chat_avisa_quando_nenhuma_instancia_de_ollama_responde(client, external, monkeypatch) -> None:
    monkeypatch.setattr(main, "OLLAMA_BASE_URL", "http://ollama-principal:11434")
    monkeypatch.setattr(main, "OLLAMA_FALLBACK_URL", "http://ollama-alternativo:11434")
    monkeypatch.setattr(main, "_ACTIVE_OLLAMA_URL", None)
    external(
        {
            "ollama-principal": raises(httpx.ConnectError("fora do ar")),
            "ollama-alternativo": raises(httpx.ConnectError("fora do ar")),
        }
    )

    response = client.post("/api/chat", json={"message": "oi"})

    assert response.status_code == 503
    assert "Não consegui acessar o Ollama" in response.json()["detail"]
