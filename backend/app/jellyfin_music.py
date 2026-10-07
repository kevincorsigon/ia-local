"""Consulta apenas bibliotecas de música do Jellyfin configurado pelo usuário."""
from __future__ import annotations

import os
import asyncio
from difflib import SequenceMatcher
import random
import re
import unicodedata
from typing import Any

import httpx

URL = os.getenv("JELLYFIN_URL", "").strip().rstrip("/")
API_KEY = os.getenv("JELLYFIN_API_KEY", "").strip()
USER_ID = os.getenv("JELLYFIN_USER_ID", "").strip()
USERNAME = os.getenv("JELLYFIN_USERNAME", "").strip()
PASSWORD = os.getenv("JELLYFIN_PASSWORD", "")
_access_token = ""
_access_user_id = ""
_login_lock = asyncio.Lock()


class MusicUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(URL and (API_KEY or (USERNAME and PASSWORD)))


async def _headers(force_login: bool = False) -> dict[str, str]:
    token = API_KEY or await _login(force=force_login)
    return {"Authorization": f'MediaBrowser Token="{token}", Client="Kunica", Device="NUC", DeviceId="kunica-nuc", Version="0.1"'}


async def _login(force: bool = False) -> str:
    global _access_token, _access_user_id
    if _access_token and not force:
        return _access_token
    if not URL:
        raise MusicUnavailable("Configure JELLYFIN_URL no ambiente do backend.")
    if not USERNAME or not PASSWORD:
        raise MusicUnavailable("Configure JELLYFIN_API_KEY ou JELLYFIN_USERNAME e JELLYFIN_PASSWORD.")
    async with _login_lock:
        if _access_token and not force:
            return _access_token
        if force:
            _access_token = ""
            _access_user_id = ""
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post(
                    f"{URL}/Users/AuthenticateByName",
                    headers={"Authorization": 'MediaBrowser Client="Kunica", Device="NUC", DeviceId="kunica-nuc", Version="0.1"'},
                    json={"Username": USERNAME, "Pw": PASSWORD},
                )
                response.raise_for_status()
                data = response.json()
            _access_token = str(data.get("AccessToken") or "")
            _access_user_id = str((data.get("User") or {}).get("Id") or "")
            if not _access_token or not _access_user_id:
                raise MusicUnavailable("O Jellyfin não forneceu uma sessão válida para música.")
            return _access_token
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise MusicUnavailable("O Jellyfin recusou o usuário ou a senha da música.") from exc
            raise MusicUnavailable("Não consegui autenticar no Jellyfin.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MusicUnavailable("Não consegui acessar o Jellyfin pela rede.") from exc


async def _user_id() -> str:
    if API_KEY:
        return USER_ID
    await _login()
    return _access_user_id


async def status() -> dict[str, Any]:
    if not URL:
        return {"available": False, "reason": "O endereço JELLYFIN_URL não está configurado."}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{URL}/health")
        if response.status_code == 200:
            return {"available": True, "reason": "O servidor de música está disponível."}
        return {"available": False, "reason": f"O servidor de música respondeu HTTP {response.status_code}."}
    except httpx.HTTPError:
        return {"available": False, "reason": "O servidor de música está desligado ou inacessível pela rede."}


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not configured():
        raise MusicUnavailable("Configure JELLYFIN_URL e uma chave ou conta Jellyfin no ambiente do backend.")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{URL}{path}", headers=await _headers(), params=params)
            if response.status_code == 401 and not API_KEY:
                # Jellyfin pode invalidar uma sessÃ£o antiga (reinÃ­cio, troca de senha ou
                # encerramento de sessÃµes). Renova uma vez antes de declarar falha.
                response = await client.get(f"{URL}{path}", headers=await _headers(force_login=True), params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401 and API_KEY:
            raise MusicUnavailable("O Jellyfin recusou a chave de API. Confira JELLYFIN_API_KEY.") from exc
        if exc.response.status_code == 401:
            raise MusicUnavailable("O Jellyfin recusou a sessÃ£o da conta. Confira usuÃ¡rio, senha e permissÃµes.") from exc
        if exc.response.status_code == 403:
            raise MusicUnavailable("A conta da Kunica nÃ£o tem permissÃ£o para consultar esta biblioteca no Jellyfin.") from exc
        raise MusicUnavailable("Não consegui consultar o catálogo de música do Jellyfin.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise MusicUnavailable("Não consegui acessar o Jellyfin pela rede.") from exc


def _item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("Id") or ""),
        "name": str(raw.get("Name") or ""),
        "album": str(raw.get("Album") or ""),
        "artists": [str(x) for x in raw.get("Artists") or []],
        "genres": [str(x) for x in raw.get("Genres") or []],
    }


async def libraries() -> list[dict[str, str]]:
    user_id = await _user_id()
    data = await _get(f"/Users/{user_id}/Views" if user_id else "/Library/MediaFolders")
    return [
        {"id": str(item["Id"]), "name": str(item.get("Name") or "Música")}
        for item in data.get("Items", [])
        if str(item.get("CollectionType") or "").lower() == "music" and item.get("Id")
    ]


async def _library_id(library_id: str = "") -> str:
    found = await libraries()
    if not found:
        raise MusicUnavailable("Não encontrei bibliotecas de música no Jellyfin.")
    if library_id:
        if not any(item["id"] == library_id for item in found):
            raise MusicUnavailable("Esta biblioteca de música não existe no Jellyfin.")
        return library_id
    return found[0]["id"]


async def artists(library_id: str = "", search: str = "", limit: int = 50, start: int = 0) -> list[dict[str, str]]:
    parent = await _library_id(library_id)
    params: dict[str, Any] = {"ParentId": parent, "Limit": min(limit, 100),
                              "StartIndex": max(start, 0), "SortBy": "SortName"}
    user_id = await _user_id()
    if user_id:
        params["UserId"] = user_id
    if search:
        params["SearchTerm"] = search
    data = await _get("/Artists", params)
    return [{"id": str(x["Id"]), "name": str(x.get("Name") or "")} for x in data.get("Items", []) if x.get("Id")]


async def genres(library_id: str = "") -> list[str]:
    parent = await _library_id(library_id)
    params: dict[str, Any] = {"ParentId": parent, "IncludeItemTypes": "MusicAlbum", "Limit": 200}
    user_id = await _user_id()
    if user_id:
        params["UserId"] = user_id
    data = await _get("/Genres", params)
    return [str(x.get("Name")) for x in data.get("Items", []) if x.get("Name")]


async def tracks(
    library_id: str = "", search: str = "", artist: str = "", genre: str = "",
    limit: int = 30, start: int = 0,
) -> dict[str, Any]:
    parent = await _library_id(library_id)
    params: dict[str, Any] = {
        "ParentId": parent, "IncludeItemTypes": "Audio", "Recursive": "true",
        "Limit": min(max(limit, 1), 100), "StartIndex": max(start, 0),
        "EnableTotalRecordCount": "true", "SortBy": "SortName",
    }
    user_id = await _user_id()
    if user_id:
        params["UserId"] = user_id
    if search:
        params["SearchTerm"] = search
    if genre:
        params["Genres"] = genre
    if artist:
        matches = await artists(parent, artist, 20)
        exact = next((x for x in matches if _fold(x["name"]) == _fold(artist)), None)
        selected = exact or (matches[0] if matches else None)
        if not selected:
            return {"items": [], "total": 0}
        params["ArtistIds"] = selected["id"]
    data = await _get("/Items", params)
    return {"items": [_item(x) for x in data.get("Items", []) if x.get("Type") == "Audio"],
            "total": int(data.get("TotalRecordCount") or 0)}


async def random_track(library_id: str = "", artist: str = "", genre: str = "") -> dict[str, Any] | None:
    choices = [library_id] if library_id else [x["id"] for x in await libraries()]
    random.shuffle(choices)
    for parent in choices:
        first = await tracks(parent, artist=artist, genre=genre, limit=1)
        total = first["total"]
        if total:
            chosen = await tracks(parent, artist=artist, genre=genre, limit=1, start=random.randrange(total))
            if chosen["items"]:
                return chosen["items"][0]
    return None


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def _spoken(value: str) -> str:
    """Corrige erros frequentes do STT apenas nas palavras dos comandos."""
    folded = _fold(value)
    folded = re.sub(r"\b(?:msuca|msuica|msucia|muscia|muisca)\b", "musica", folded)
    return re.sub(r"\bdisponiblw\b", "disponivel", folded)


def parse_command(message: str) -> dict[str, str] | None:
    """Reconhece pedidos explícitos de música antes do roteador geral/LLM."""
    text = message.strip()
    folded = _spoken(text)
    list_request = re.search(r"\b(?:lista|liste|listar|mostra|mostre|mostrar|quais|ver)\b", folded)
    if re.search(r"\b(?:servidor\s+de\s+musica|jellyfin)\b.*\b(?:disponivel|online|funcionando|ligado|acessivel)\b", folded):
        return {"kind": "status"}
    if list_request and re.search(r"\b(?:bibliotecas|colecoes)\b", folded):
        return {"kind": "libraries"}
    if list_request and re.search(r"\bartistas\b", folded):
        return {"kind": "artists"}
    if list_request and re.search(r"\bgeneros\b", folded):
        return {"kind": "genres"}
    if list_request and re.search(r"\b(?:musicas|faixas|cancoes)\b", folded):
        return {"kind": "tracks"}
    if re.fullmatch(r"(?:pare|parar|pause|pausar|continua|continue|retome|proxima|proximo)(?:\s+(?:a\s+)?(?:musica|faixa|cancao))?[.!?]*", folded):
        if folded.startswith(("pare", "parar")):
            return {"kind": "control", "action": "stop"}
        if folded.startswith(("pause", "pausar")):
            return {"kind": "control", "action": "pause"}
        if folded.startswith(("proxima", "proximo")):
            return {"kind": "control", "action": "next"}
        return {"kind": "control", "action": "resume"}
    play = re.match(r"^(?:toque|toca|tocar|coloque|bota|reproduza|reproduzir)\s+(.+?)[.!?]*$", text, re.I)
    if not play:
        return None
    target = play.group(1).strip().rstrip(".!?")
    plain = _spoken(target)
    genre = re.search(r"(?:musicas?\s+)?(?:d[eo]\s+)?genero\s+(.+)$", plain)
    if genre:
        return {"kind": "random", "genre": target[genre.start(1):].strip()}
    genre = re.match(r"(?:uma\s+)?musicas?\s+d[eo]\s+(rock|samba|jazz|pop|sertanejo|mpb|forro|funk|eletronica|classica|metal|blues|reggae)\b", plain)
    if genre:
        return {"kind": "random", "genre": target[genre.start(1):genre.end(1)].strip()}
    if re.fullmatch(r"(?:heavy|thrash|power|nu|hard)\s+metal|metal|rock|hard\s+rock|jazz|pop|mpb|blues|reggae|sertanejo|samba|funk|eletronica", plain):
        return {"kind": "random", "genre": target}
    if re.fullmatch(r"(?:(?:uma|alguma)\s+)?(?:musica|cancao|faixa)(?:\s+ai|\s+aleatoria)?", plain) or plain in {"algo", "qualquer musica"}:
        return {"kind": "random"}
    original = _fold(target)
    music_word = r"(?:musica|msuca|msuica|msucia|muscia|muisca|cancao|faixa)"
    by_artist = re.match(rf"(?:uma\s+)?{music_word}s?\s+(?:do|da|de)\s+(.+)$", original)
    if by_artist:
        return {"kind": "random", "artist": target[by_artist.start(1):by_artist.end(1)].strip()}
    named = re.match(rf"(?:a\s+)?{music_word}\s+(.+?)\s+(?:do|da|de)\s+(.+)$", original)
    if named:
        return {"kind": "named", "search": target[named.start(1):named.end(1)].strip(),
                "artist": target[named.start(2):named.end(2)].strip()}
    prefix = re.match(rf"^(?:a\s+)?{music_word}\s+", original)
    return {"kind": "named", "search": target[prefix.end():] if prefix else target}


async def _named_track(search: str, artist: str = "") -> dict[str, Any] | None:
    library_list = await libraries()
    for library in library_list:
        found = await tracks(library["id"], search=search, artist=artist, limit=30)
        if found["items"]:
            wanted = _fold(search)
            return next((x for x in found["items"] if _fold(x["name"]) == wanted), found["items"][0])

    # O SearchTerm do Jellyfin exige grafia próxima; uma palavra correta pode
    # recuperar candidatos quando o STT erra outra palavra do título.
    words = sorted(set(re.findall(r"[\w]+", _fold(search))), key=len, reverse=True)
    candidates: dict[str, dict[str, Any]] = {}
    for word in (word for word in words if len(word) >= 4):
        for library in library_list:
            found = await tracks(library["id"], search=word, artist=artist, limit=50)
            for item in found["items"]:
                candidates[item["id"]] = item
        if candidates:
            break
    if not candidates:
        return None
    best = max(candidates.values(), key=lambda item: SequenceMatcher(None, _fold(search), _fold(item["name"])).ratio())
    return best if SequenceMatcher(None, _fold(search), _fold(best["name"])).ratio() >= 0.72 else None


async def handle_command(command: dict[str, str]) -> tuple[str, dict[str, Any] | None]:
    kind = command["kind"]
    if kind == "status":
        check = await status()
        return check["reason"], None
    if kind == "control":
        action = command["action"]
        return {"pause": "Música pausada.", "resume": "Continuando a música.", "stop": "Música parada.", "next": "Próxima música."}[action], {"action": action}
    check = await status()
    if not check["available"]:
        raise MusicUnavailable(check["reason"])
    if kind == "libraries":
        names = [x["name"] for x in await libraries()]
        return ("Bibliotecas de música: " + ", ".join(names)) if names else "Não encontrei bibliotecas de música.", None
    if kind == "artists":
        found = await artists()
        return ("Artistas: " + ", ".join(x["name"] for x in found[:10])) if found else "Não encontrei artistas.", {"action": "browse", "view": "artists"}
    if kind == "genres":
        found = await genres()
        return ("Gêneros: " + ", ".join(found[:15])) if found else "Não encontrei gêneros.", {"action": "browse", "view": "genres"}
    if kind == "tracks":
        found = []
        for library in await libraries():
            result = await tracks(library["id"], limit=5 - len(found))
            found.extend(result["items"])
            if len(found) >= 5:
                break
        if not found:
            return "Não encontrei músicas nas bibliotecas do Jellyfin.", None
        names = [f"{item['name']}, de {', '.join(item['artists']) or 'artista desconhecido'}" for item in found]
        return "Algumas músicas da sua biblioteca: " + "; ".join(names) + ".", {"action": "browse", "view": "tracks"}
    if kind == "random":
        genre = command.get("genre", "")
        if genre:
            available_genres = []
            for library in await libraries():
                available_genres.extend(await genres(library["id"]))
            genre = next((name for name in available_genres if _fold(name) == _fold(genre)), genre)
        item = await random_track(artist=command.get("artist", ""), genre=genre)
    else:
        item = await _named_track(command.get("search", ""), command.get("artist", ""))
    if not item:
        return "Não encontrei uma música correspondente no Jellyfin.", None
    artist_text = ", ".join(item["artists"]) or "artista desconhecido"
    return f"Tocando {item['name']}, de {artist_text}.", {"action": "play", "track": item}
