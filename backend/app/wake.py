"""Detecção das alcunhas (wake words) tolerante aos erros do Vosk em pt-BR.

O modelo pequeno do pt-BR transcreve nomes próprios de forma imprevisível — medido
neste projeto: "Kunica, onde eu moro?" virou "única onde eu moro" e "TVzinha" virou
"vizinha". Por isso a comparação aceita pequenas diferenças:

* tokens longos (>= 4 letras) usam similaridade, o que cobre "única"→"kunica" e
  "vizinha"→"tvzinha";
* tokens curtos (<= 3 letras, como "tv" e "ei") exigem igualdade, porque qualquer
  folga neles casaria com palavras comuns do português ("de", "que", "te");
* todos os tokens da alcunha precisam aparecer em sequência;
* a resposta traz o que o usuário falou depois da alcunha, já pronto para o chat.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z\u00c0-\u024f]+")

# Limiares calibrados com as saídas reais do Vosk deste projeto:
#   "unica" (de "Kunica, onde eu moro?")        -> 0.91
#   "vizinha" (de "TVzinha, qual é a previsão") -> 0.86
#   "economica" (de "Ei, Kunica, que horas")    -> 0.40
# O limiar baixo vale só para a PRIMEIRA palavra de uma alcunha de palavra única,
# porque palavras comuns no início ("minha" x "kunica" = 0.36) ficariam perigosas
# se qualquer posição aceitasse tão pouco.
_RATIO_STRICT = 0.72
_RATIO_RELAXED = 0.4
_SHORT_TOKEN_MAX = 3
_MAX_LENGTH_GAP = 3


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, para comparar o que o Vosk escreveu."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _tokens(text: str) -> list[tuple[str, int]]:
    """Tokens normalizados e o índice onde cada um termina no texto original."""
    return [(normalize(match.group()), match.end()) for match in _TOKEN_PATTERN.finditer(text)]


def _token_matches(token: str, alias_token: str, relaxed: bool = False) -> bool:
    if token == alias_token:
        return True
    if len(alias_token) <= _SHORT_TOKEN_MAX:
        # Curto demais para arriscar: "tv" não pode casar com "de" nem com "que".
        return False
    if abs(len(token) - len(alias_token)) > _MAX_LENGTH_GAP:
        return False
    ratio = SequenceMatcher(None, token, alias_token).ratio()
    if ratio >= _RATIO_STRICT:
        return True
    # Para um nome que não existe no vocabulário, o Vosk escreve uma palavra real
    # mais longa ("Kunica" vira "econômica", 0.40) — mas nunca uma mais curta
    # ("qual" também dá 0.40 e não pode virar alcunha).
    return relaxed and len(token) > len(alias_token) and ratio >= _RATIO_RELAXED


def matches_alias(
    text: str, alias: str, label: str | None = None, fuzzy: bool = True
) -> dict[str, Any] | None:
    """Verifica uma alcunha no texto e devolve a pergunta que veio depois dela.

    Igualdade exata vale em qualquer posição ("fala comigo, Kunica, ..."). A comparação
    aproximada vale só na primeira palavra, para que "a única opção" ou "a situação
    econômica" no meio de uma frase não acionem o assistente. ``fuzzy=False`` exige
    igualdade exata: é o que as variantes medidas usam, senão um "nika" curto casaria com
    "minha" (0.44) e o assistente acordaria em "minha vizinha chegou agora".
    """
    alias_tokens = normalize(alias).split()
    if not alias_tokens:
        return None
    tokens = _tokens(text)
    if len(tokens) < len(alias_tokens):
        return None
    single_token = len(alias_tokens) == 1
    for start in range(len(tokens) - len(alias_tokens) + 1):
        window = tokens[start:start + len(alias_tokens)]
        exact = all(token == wanted for (token, _), wanted in zip(window, alias_tokens))
        if not exact:
            if start > 0 or not fuzzy:
                continue
            relaxed = single_token
            if not all(_token_matches(token, wanted, relaxed) for (token, _), wanted in zip(window, alias_tokens)):
                continue
        end_index = window[-1][1]
        query = text[end_index:].lstrip(" ,;:!?—-\t")
        pergunta = query.strip()
        if not any(char.isalnum() for char in pergunta):
            # Sobrou só pontuação ("Oi, TVzinha!"): é uma saudação, não uma pergunta.
            pergunta = ""
        return {"phrase": label or alias, "query": pergunta}
    return None


def alias_forms(alias: str, variants: dict[str, list[str]] | None = None) -> list[str]:
    """A alcunha e as formas que o reconhecimento costuma escrever no lugar dela."""
    mapa = variants or {}
    extras = mapa.get(normalize(alias)) or mapa.get(alias) or []
    formas = [alias]
    conhecidas = {normalize(forma) for forma in formas}
    for extra in extras:
        texto = str(extra).strip()
        if texto and normalize(texto) not in conhecidas:
            formas.append(texto)
            conhecidas.add(normalize(texto))
    return formas


def match_wake_phrase(
    text: str, aliases: list[str], variants: dict[str, list[str]] | None = None
) -> dict[str, Any] | None:
    """Procura as alcunhas da configuração; devolve a primeira (mais longa) que casar.

    Alcunhas mais longas têm prioridade para que "eae tv" ganhe de "tv" e o texto
    depois da alcunha fique correto. As ``variants`` são formas medidas nos motores de
    fala ("Kunica" não existe no dicionário de nenhum deles) e valem em qualquer posição
    da frase — é isso que faz "a icônica, que horas são?" acionar o assistente.
    """
    if not text.strip():
        return None
    ordered = sorted((alias for alias in aliases if normalize(alias).strip()), key=len, reverse=True)
    for alias in ordered:
        for position, forma in enumerate(alias_forms(alias, variants)):
            # A própria alcunha aceita semelhança; as variantes medidas são texto exato.
            found = matches_alias(text, forma, label=alias, fuzzy=position == 0)
            if found:
                return found
    return None
