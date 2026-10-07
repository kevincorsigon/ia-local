"""Fluxo de música simulado, sem depender do Jellyfin real."""
from __future__ import annotations

import httpx

from app import jellyfin_music
from app.tests.conftest import raises


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
        "/Audio/12345678/stream": lambda request: httpx.Response(206, content=b"audio", headers={
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
