"""Fluxo de música simulado, sem depender do Jellyfin real."""
from __future__ import annotations

import httpx
import json
import pytest

from app import jellyfin_music, main
from app.tests.conftest import ollama_reply, raises


def test_comandos_de_musica() -> None:
    assert jellyfin_music.parse_command("servidor de música está disponível?") == {"kind": "status"}
    assert jellyfin_music.parse_command("toca uma música aí") == {"kind": "random"}
    assert jellyfin_music.parse_command("toca música do gênero rock") == {"kind": "random", "genre": "rock"}
    assert jellyfin_music.parse_command("toca a música Imagine do John Lennon") == {
        "kind": "named", "search": "Imagine", "artist": "John Lennon",
    }


def test_servidor_desligado_e_avisado_em_voz(client, external, monkeypatch) -> None:
    monkeypatch.setattr(jellyfin_music, "URL", "http://jellyfin.local:8096")
    monkeypatch.setattr(jellyfin_music, "API_KEY", "testkey")
    external({"jellyfin.local": raises(httpx.ConnectError("offline"))})

    response = client.post("/api/chat", json={"message": "toca uma música aí"})

    assert response.status_code == 200
    payload = response.json()
    assert "inacessível" in payload["answer"]
    assert payload["should_speak"] is True
    assert payload["music"] is None


def test_navega_apenas_bibliotecas_de_musica(client, external, monkeypatch) -> None:
    monkeypatch.setattr(jellyfin_music, "URL", "http://jellyfin.local:8096")
    monkeypatch.setattr(jellyfin_music, "API_KEY", "testkey")
    calls = external({
        "/Library/MediaFolders": lambda request: httpx.Response(200, json={"Items": [
            {"Id": "music123", "Name": "Minhas músicas", "CollectionType": "music"},
            {"Id": "movies123", "Name": "Filmes", "CollectionType": "movies"},
            {"Id": "series123", "Name": "Séries", "CollectionType": "tvshows"},
        ]}),
    })

    response = client.get("/api/music/libraries")

    assert response.json() == {"items": [{"id": "music123", "name": "Minhas músicas"}]}
    assert calls.requests[0].headers["authorization"].startswith("MediaBrowser Token=")


def test_audio_passa_pelo_backend_sem_expor_chave(client, external, monkeypatch) -> None:
    monkeypatch.setattr(jellyfin_music, "URL", "http://jellyfin.local:8096")
    monkeypatch.setattr(jellyfin_music, "API_KEY", "testkey")
    calls = external({
        "/Items/12345678": lambda request: httpx.Response(200, json={"Id": "12345678", "Type": "Audio"}),
        "/Audio/12345678/stream": lambda request: httpx.Response(206, stream=httpx.ByteStream(b"audio"), headers={
            "Content-Type": "audio/mpeg", "Content-Range": "bytes 0-4/5",
        }),
    })

    response = client.get("/api/music/stream/12345678", headers={"Range": "bytes=0-4"})

    assert response.status_code == 206
    assert response.content == b"audio"
    assert response.headers["content-range"] == "bytes 0-4/5"
    assert calls.requests[-1].headers["range"] == "bytes=0-4"
    assert "testkey" not in str(calls.requests[-1].url)


def test_conta_jellyfin_lista_so_bibliotecas_visiveis(client, external, monkeypatch) -> None:
    monkeypatch.setattr(jellyfin_music, "URL", "http://jellyfin.local:8096")
    monkeypatch.setattr(jellyfin_music, "API_KEY", "")
    monkeypatch.setattr(jellyfin_music, "USERNAME", "kunica")
    monkeypatch.setattr(jellyfin_music, "PASSWORD", "senha-de-teste")
    monkeypatch.setattr(jellyfin_music, "_access_token", "")
    monkeypatch.setattr(jellyfin_music, "_access_user_id", "")
    calls = external({
        "/Users/AuthenticateByName": lambda request: httpx.Response(200, json={
            "AccessToken": "token-de-teste", "User": {"Id": "user12345"},
        }),
        "/Users/user12345/Views": lambda request: httpx.Response(200, json={"Items": [
            {"Id": "music123", "Name": "Músicas", "CollectionType": "music"},
            {"Id": "movies123", "Name": "Filmes", "CollectionType": "movies"},
        ]}),
    })

    response = client.get("/api/music/libraries")

    assert response.json() == {"items": [{"id": "music123", "name": "Músicas"}]}
    assert calls.requests[0].url.path == "/Users/AuthenticateByName"
    assert calls.requests[1].headers["authorization"].startswith("MediaBrowser Token=")
    assert "token-de-teste" not in response.text


@pytest.fixture
def music_catalog(external, monkeypatch):
    """Catálogo cujo artista não aparece no título: reproduz a falha de 'toca Nirvana'."""
    monkeypatch.setenv("LLM_MODE", "ollama")
    monkeypatch.setattr(jellyfin_music, "URL", "http://jellyfin.local:8096")
    monkeypatch.setattr(jellyfin_music, "API_KEY", "testkey")
    monkeypatch.setattr(jellyfin_music, "USER_ID", "")

    def install(classification, extra_artists=()):
        catalog_artists = [
            {"Id": "nirvana123", "Name": "Nirvana"},
            {"Id": "avenged123", "Name": "Avenged Sevenfold"},
            *extra_artists,
        ]

        def artist_results(request):
            query = request.url.params.get("SearchTerm", "").casefold()
            found = [item for item in catalog_artists if query in item["Name"].casefold()]
            start = int(request.url.params.get("StartIndex", 0))
            return httpx.Response(200, json={"Items": found[start:start + 100]})

        def items(request):
            params = request.url.params
            if params.get("IncludeItemTypes") == "MusicAlbum":
                assert params["ParentId"] == "music123"
                assert params["ArtistIds"] == "nirvana123"
                return httpx.Response(200, json={"Items": [
                    {"Id": "album123", "Name": "Nevermind", "Type": "MusicAlbum"},
                ]})
            assert params.get("IncludeItemTypes") == "Audio"
            assert params.get("ParentId") in {"music123", "album123"}
            found = (params.get("ArtistIds") == "nirvana123"
                     or params.get("SearchTerm") == "Smells Like Teen Spirit"
                     or params.get("ParentId") == "album123")
            tracks = [{"Id": "track123", "Name": "Smells Like Teen Spirit", "Type": "Audio",
                       "Artists": ["Nirvana"], "Album": "Nevermind"}] if found else []
            if params.get("ArtistIds") == "avenged123":
                tracks = [{"Id": "track_a7x", "Name": "Nightmare", "Type": "Audio",
                           "Artists": ["Avenged Sevenfold"], "Album": "Nightmare"}]
            return httpx.Response(200, json={"Items": tracks, "TotalRecordCount": len(tracks)})

        return external({
            "/api/chat": ollama_reply(classification),
            "/health": lambda request: httpx.Response(200),
            "/Library/MediaFolders": lambda request: httpx.Response(200, json={"Items": [
                {"Id": "music123", "Name": "Músicas", "CollectionType": "music"},
                {"Id": "movies123", "Name": "Filmes", "CollectionType": "movies"},
            ]}),
            "/Artists": artist_results,
            "/Items": items,
        })
    return install


@pytest.mark.parametrize("message", ["toca nirvana", "quero ouvir Nirvana", "bota um nirvna pra mim"])
def test_ia_interpreta_artista_antes_de_consultar_jellyfin(client, music_catalog, message):
    calls = music_catalog('{"music":true,"intent":"artist","artist":"Nirvana"}')
    payload = client.post("/api/chat", json={"message": message}).json()
    assert payload["music"]["track"]["id"] == "track123"
    assert calls.requests[0].url.path == "/api/chat"
    assert len(calls.payloads("/api/chat")) == 1
    item_calls = [request for request in calls.requests if request.url.path == "/Items"]
    assert item_calls and all(request.url.params["ArtistIds"] == "nirvana123" for request in item_calls)
    assert all("SearchTerm" not in request.url.params for request in item_calls)
    prompt = calls.payloads("/api/chat")[0]["messages"][0]["content"]
    assert "toca nirvana" in prompt and "VocÃ" not in prompt


def test_titulo_explicito_continua_busca_por_faixa(client, music_catalog):
    calls = music_catalog(json.dumps({"music": True, "intent": "track",
                                    "search": "Smells Like Teen Spirit", "artist": "Nirvana"}))
    payload = client.post("/api/chat", json={"message": "toca Smells Like Teen Spirit do Nirvana"}).json()
    assert payload["music"]["action"] == "play"
    request = next(request for request in calls.requests if request.url.path == "/Items")
    assert request.url.params["SearchTerm"] == "Smells Like Teen Spirit"
    assert request.url.params["ArtistIds"] == "nirvana123"


@pytest.mark.parametrize("reply", ["JSON inválido", "[]", '{"music":true,"intent":"artist","artist":{}}'])
def test_fallback_consulta_artista_exato_quando_ia_falha(client, music_catalog, reply):
    calls = music_catalog(reply)
    payload = client.post("/api/chat", json={"message": "toca nirvana"}).json()
    assert payload["music"]["track"]["artists"] == ["Nirvana"]
    assert len(calls.payloads("/api/chat")) == 1


def test_timeout_do_modelo_preserva_fallback(client, music_catalog, monkeypatch):
    music_catalog("")
    class UnavailableProvider:
        async def generate(self, *args, **kwargs):
            raise httpx.ReadTimeout("offline")
    monkeypatch.setattr(main, "get_llm_provider", UnavailableProvider)
    payload = client.post("/api/chat", json={"message": "toca nirvana"}).json()
    assert payload["music"]["track"]["id"] == "track123"


def test_album_gera_fila_de_faixas_reais(client, music_catalog):
    calls = music_catalog('{"music":true,"intent":"album","album":"Nevermind","artist":"Nirvana"}')
    payload = client.post("/api/chat", json={"message": "toca o álbum Nevermind do Nirvana"}).json()
    assert payload["music"]["queue"][0] == payload["music"]["track"]
    request = calls.requests[-1]
    assert request.url.params["ParentId"] == "album123"
    assert request.url.params["SortBy"] == "ParentIndexNumber,IndexNumber,SortName"


def test_esclarecimento_usa_resposta_e_historico(client, music_catalog):
    calls = music_catalog('{"music":true,"intent":"clarify","question":"Qual artista?"}')
    first = client.post("/api/chat", json={"message": "toca aquela banda"}).json()
    assert first["should_speak"] is True and first["music"] is None
    calls.routes["/api/chat"] = ollama_reply('{"music":true,"intent":"artist","artist":"Nirvana"}')
    second = client.post("/api/chat", json={"message": "Nirvana", "session_id": first["session_id"]}).json()
    assert second["music"]["track"]["id"] == "track123"
    assert "Qual artista?" in calls.payloads("/api/chat")[-1]["messages"][-1]["content"]


def test_recusa_do_classificador_nao_dispara_jellyfin(client, music_catalog):
    calls = music_catalog('{"music":false,"intent":"none"}')
    payload = client.post("/api/chat", json={"message": "coloque música como tema de uma redação"}).json()
    assert payload["music"] is None
    assert not any(request.url.host == "jellyfin.local" for request in calls.requests)


def test_controle_imediato_nao_chama_modelo(client, music_catalog):
    calls = music_catalog("")
    payload = client.post("/api/chat", json={"message": "pause a música"}).json()
    assert payload["music"] == {"action": "pause"}
    assert not calls.requests


def test_artista_ausente_nao_inventa_faixa(client, music_catalog):
    music_catalog('{"music":true,"intent":"artist","artist":"Banda ausente"}')
    payload = client.post("/api/chat", json={"message": "toca Banda ausente"}).json()
    assert payload["music"] is None
    assert "Banda ausente" in payload["answer"]
    assert payload["should_speak"] is True


def test_aspas_nao_transformam_titulo_em_artista():
    assert jellyfin_music.parse_command('toca a música "Imagine"') == {"kind": "named", "search": "Imagine"}
    assert jellyfin_music.parse_command('toca "Nirvana"') == {"kind": "search", "search": "Nirvana"}


@pytest.mark.parametrize("message", ["toca a7x", "toca avenged", "toca sevenfold", "quero ouvir a7x"])
@pytest.mark.parametrize("reply", [
    '{"music":true,"intent":"artist","artist":"Avenged76"}',
    "JSON inválido",
])
def test_nome_original_resolve_artista_mesmo_se_ia_inventar(client, music_catalog, message, reply):
    calls = music_catalog(reply)
    payload = client.post("/api/chat", json={"message": message}).json()
    assert payload["music"]["track"]["artists"] == ["Avenged Sevenfold"]
    requests = [request for request in calls.requests if request.url.path == "/Items"]
    assert requests and all(request.url.params["ArtistIds"] == "avenged123" for request in requests)
    assert not any(request.url.params.get("SearchTerm") == "Avenged76" for request in calls.requests)


def test_historico_errado_nao_contamina_proximo_nome(client, music_catalog):
    music_catalog('{"music":true,"intent":"artist","artist":"Avenged76"}')
    main.SESSIONS["a7x-regressao"] = {
        "messages": [
            {"role": "user", "content": "toca a7x"},
            {"role": "assistant", "content": "Não encontrei músicas de Avenged76 no Jellyfin."},
        ],
        "updated_at": main.time.monotonic(),
    }
    for message in ("toca avenged", "toca sevenfold"):
        payload = client.post("/api/chat", json={"message": message, "session_id": "a7x-regressao"}).json()
        assert payload["music"]["track"]["id"] == "track_a7x"


def test_nome_parcial_ambiguo_pergunta_e_aceita_esclarecimento(client, music_catalog):
    calls = music_catalog('{"music":true,"intent":"artist","artist":"Avenged Sevenfold"}',
                          extra_artists=[{"Id": "tribute123", "Name": "Avenged Tribute"}])
    payload = client.post("/api/chat", json={"message": "toca avenged"}).json()
    assert payload["music"] is None and payload["should_speak"] is True
    assert "Avenged Sevenfold" in payload["answer"] and "Avenged Tribute" in payload["answer"]
    assert not any(request.url.path == "/Items" for request in calls.requests)
    second = client.post("/api/chat", json={"message": "Avenged Sevenfold", "session_id": payload["session_id"]}).json()
    assert second["music"]["track"]["id"] == "track_a7x"


def test_alias_exato_tem_prioridade_sobre_banda_cover(client, music_catalog):
    music_catalog('{"music":true,"intent":"artist","artist":"Avenged76"}',
                  extra_artists=[{"Id": "cover123", "Name": "Avenged Sevenfold Cover"}])
    payload = client.post("/api/chat", json={"message": "toca a7x"}).json()
    assert payload["music"]["track"]["id"] == "track_a7x"


def test_artista_inventado_nao_aceita_primeiro_resultado_da_api(client, music_catalog):
    calls = music_catalog('{"music":true,"intent":"artist","artist":"Artista inexistente"}')
    calls.routes["/Artists"] = lambda request: httpx.Response(200, json={"Items": [
        {"Id": "nirvana123", "Name": "Nirvana"},
    ]})
    payload = client.post("/api/chat", json={"message": "toca Artista inexistente"}).json()
    assert payload["music"] is None
    assert not any(request.url.path == "/Items" for request in calls.requests)


def test_artista_ausente_informa_nome_original(client, music_catalog):
    music_catalog('{"music":true,"intent":"artist","artist":"Avenged76"}')
    payload = client.post("/api/chat", json={"message": "toca banda desconhecida"}).json()
    assert payload["music"] is None
    assert "banda desconhecida" in payload["answer"] and "Avenged76" not in payload["answer"]


@pytest.mark.parametrize("artist,first_title,second_title", [
    ("Raimundos", "Mulher de fases", "A mais pedida"),
    ("Linkin Park", "Lying From You", "Numb"),
])
@pytest.mark.parametrize("followup", ["outra", "outra música", "mais uma", "próxima música"])
def test_outra_reproduz_faixa_diferente_do_mesmo_artista(
    client, music_catalog, monkeypatch, artist, first_title, second_title, followup,
):
    calls = music_catalog(json.dumps({"music": True, "intent": "artist", "artist": artist}))
    artist_id = f"artist-{artist.replace(' ', '-').lower()}"
    tracks = [
        {"Id": "track-first", "Name": first_title, "Type": "Audio", "Artists": [artist]},
        {"Id": "track-second", "Name": second_title, "Type": "Audio", "Artists": [artist]},
    ]
    calls.routes["/Artists"] = lambda request: httpx.Response(200, json={"Items": [
        {"Id": artist_id, "Name": artist},
    ] if request.url.params.get("SearchTerm", "").casefold() == artist.casefold() else []})
    def items(request):
        assert request.url.params.get("ArtistIds") == artist_id
        index = int(request.url.params.get("StartIndex", "0"))
        return httpx.Response(200, json={
            "Items": tracks[index:index + int(request.url.params.get("Limit", "1"))],
            "TotalRecordCount": len(tracks),
        })
    calls.routes["/Items"] = items
    monkeypatch.setattr(jellyfin_music.random, "randrange", lambda count: 0)

    first = client.post("/api/chat", json={"message": f"toca {artist}"}).json()
    assert first["music"]["track"]["id"] == "track-first"
    second = client.post("/api/chat", json={
        "message": followup, "session_id": first["session_id"], "music_track_id": "track-first",
    }).json()
    assert second["music"]["action"] == "play"
    assert second["music"]["track"]["id"] == "track-second"
    assert second_title in second["answer"] and artist in second["answer"]
    assert len(calls.payloads("/api/chat")) == 1  # Não inventa resposta via LLM.
    assert any(request.url.params.get("StartIndex") == "1" for request in calls.requests
               if request.url.path == "/Items")


def test_outra_sem_faixa_alternativa_nao_finge_reproducao(client, music_catalog, monkeypatch):
    calls = music_catalog('{"music":true,"intent":"artist","artist":"Nirvana"}')
    monkeypatch.setattr(jellyfin_music.random, "randrange", lambda count: 0)
    first = client.post("/api/chat", json={"message": "toca Nirvana"}).json()
    second = client.post("/api/chat", json={
        "message": "outra", "session_id": first["session_id"],
        "music_track_id": first["music"]["track"]["id"],
    }).json()
    assert second["music"] is None
    assert "Não encontrei outra música" in second["answer"]
    assert second["should_speak"] is True
    assert len(calls.payloads("/api/chat")) == 1


def test_api_random_respeita_faixa_atual(client, music_catalog, monkeypatch):
    calls = music_catalog("")
    calls.routes["/Artists"] = lambda request: httpx.Response(200, json={"Items": [
        {"Id": "raimundos123", "Name": "Raimundos"},
    ]})
    tracks = [
        {"Id": "track-first", "Name": "Mulher de fases", "Type": "Audio", "Artists": ["Raimundos"]},
        {"Id": "track-second", "Name": "A mais pedida", "Type": "Audio", "Artists": ["Raimundos"]},
    ]
    calls.routes["/Items"] = lambda request: httpx.Response(200, json={
        "Items": tracks[int(request.url.params.get("StartIndex", "0")):][:1],
        "TotalRecordCount": 2,
    })
    monkeypatch.setattr(jellyfin_music.random, "randrange", lambda count: 0)
    response = client.get("/api/music/random", params={
        "artist": "Raimundos", "exclude_track_id": "track-first",
    })
    assert response.status_code == 200
    assert response.json()["track"]["id"] == "track-second"


def test_outra_de_album_avanca_fila_do_player(client, music_catalog):
    calls = music_catalog('{"music":true,"intent":"album","album":"Nevermind","artist":"Nirvana"}')
    first = client.post("/api/chat", json={"message": "toca o álbum Nevermind do Nirvana"}).json()
    second = client.post("/api/chat", json={
        "message": "outra", "session_id": first["session_id"],
        "music_track_id": first["music"]["track"]["id"],
    }).json()
    assert second["music"] == {"action": "next"}
    assert len(calls.payloads("/api/chat")) == 1


def test_parar_limpa_contexto_de_outra(client, music_catalog):
    calls = music_catalog('{"music":true,"intent":"artist","artist":"Nirvana"}')
    first = client.post("/api/chat", json={"message": "toca Nirvana"}).json()
    client.post("/api/chat", json={"message": "pare", "session_id": first["session_id"]})
    calls.routes["/api/chat"] = ollama_reply("Outra o quê?")
    last = client.post("/api/chat", json={"message": "outra", "session_id": first["session_id"]}).json()
    assert last["music"] is None
    assert last["answer"] == "Outra o quê?"
