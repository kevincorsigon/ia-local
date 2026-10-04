"""Testes da detecção de alcunhas, com as transcrições reais do Vosk deste projeto.

As frases parametrizadas abaixo foram medidas sintetizando o texto com o Kokoro e
transcrevendo com o Vosk pt-BR — inclusive os erros ("Kunica" virou "única" e
"TVzinha" virou "vizinha"), que são exatamente o que precisa continuar funcionando.
"""
from __future__ import annotations

import io
import wave

import pytest

from app import main, wake

ALIASES = ["kunica", "tvzinha", "tv", "minha puta", "ei tv", "eae tv", "e aí tv", "e ai tv"]


@pytest.mark.parametrize(
    ("transcript", "phrase", "query"),
    [
        ("única onde eu moro", "kunica", "onde eu moro"),
        ("econômica que horas são", "kunica", "que horas são"),
        ("vizinha qual é a previsão do tempo", "tvzinha", "qual é a previsão do tempo"),
        ("minha puta tudo bem", "minha puta", "tudo bem"),
        ("kunica", "kunica", ""),
        ("Ei, Kunica, tudo bem?", "kunica", "tudo bem?"),
        ("eae tv me conta uma piada", "eae tv", "me conta uma piada"),
        ("fala comigo, Kunica, que horas são?", "kunica", "que horas são?"),
    ],
)
def test_reconhece_alcunha_mesmo_com_erro_de_transcricao(transcript: str, phrase: str, query: str) -> None:
    found = wake.match_wake_phrase(transcript, ALIASES)

    assert found is not None, f"não reconheceu a alcunha em {transcript!r}"
    assert found["phrase"] == phrase
    assert found["query"] == query


@pytest.mark.parametrize(
    "transcript",
    [
        "",
        "   ",
        "qual é a previsão do tempo em São Paulo",
        "como você está hoje",
        "de que horas são",
        "te conto uma piada",
        "a única opção que eu tenho",
        "essa é a única opção que eu tenho",
        "olá eu sou a unica estão funcionando sem internet",
    ],
)
def test_nao_aciona_alcunha_em_frases_comuns(transcript: str) -> None:
    """Palavras parecidas no meio da frase não podem acordar o assistente."""
    assert wake.match_wake_phrase(transcript, ALIASES) is None


def test_alcunha_mais_longa_tem_prioridade() -> None:
    """“eae tv” deve ganhar de “tv” para a pergunta sair completa."""
    found = wake.match_wake_phrase("eae tv qual é a cotação do dólar", ALIASES)

    assert found is not None
    assert found["phrase"] == "eae tv"
    assert found["query"] == "qual é a cotação do dólar"


def test_normaliza_acentos_e_maiusculas() -> None:
    """A normalização tira acentos e maiúsculas; a pontuação é tratada na tokenização."""
    assert wake.normalize("Kúnicá, TVZinha!") == "kunica, tvzinha!"
    assert [token for token, _ in wake._tokens("Kúnicá, TVZinha!")] == ["kunica", "tvzinha"]


def test_gramatica_nao_e_usada_porque_o_modelo_nao_conhece_as_alcunhas() -> None:
    """Documenta a limitação: o Vosk pt-BR ignora palavras fora do vocabulário.

    Medido no container: restringir o reconhecimento às alcunhas devolve "[unk]"
    ou vazio, porque "kunica", "tvzinha", "tv" e "eae" não existem no vocabulário
    do modelo. Por isso a detecção é feita por comparação tolerante do texto.
    """
    assert not hasattr(wake, "grammar_for")
    assert wake.match_wake_phrase("única onde eu moro", ALIASES) is not None


def test_alcunhas_vem_da_configuracao() -> None:
    """Só as alcunhas que o Vosk consegue transcrever ficam na configuração.

    "tv", "ei tv", "eae tv" e afins foram removidas: o modelo pt-BR não tem essas
    palavras no vocabulário (ele as descarta ou escreve "vê"/"ver"), então uma
    alcunha de 2 letras nunca poderia ser igualada.
    """
    assert main.WAKE_PHRASES == ["kunica", "tvzinha", "televisão", "minha puta"]


# Transcrições medidas com o Vosk grande e com o Whisper: nenhum dos dois conhece "Kunica"
# nem "TVzinha" (não existem no dicionário), então cada um escreve uma palavra parecida.
VARIANTES = {
    "kunica": ["conica", "iconica", "nika"],
    "tvzinha": ["tevzinha", "tevizinha", "teve sozinha", "oitenta vizinha", "ate vizinha"],
}


@pytest.mark.parametrize(
    ("transcript", "phrase", "query"),
    [
        ("cônica", "kunica", ""),
        ("cônica que horas são", "kunica", "que horas são"),
        ("a icônica, que horas são?", "kunica", "que horas são?"),
        ("daí conica", "kunica", ""),
        ("com Nika", "kunica", ""),
        ("oi, tevzinha!", "tvzinha", ""),
        ("teve sozinha", "tvzinha", ""),
        ("oitenta vizinha qual é a previsão", "tvzinha", "qual é a previsão"),
        ("até vizinha", "tvzinha", ""),
    ],
)
def test_variantes_medidas_acionam_a_alcunha(transcript: str, phrase: str, query: str) -> None:
    """As formas medidas valem em qualquer posição — é o que faz o nome funcionar de fato."""
    found = wake.match_wake_phrase(transcript, ALIASES, VARIANTES)

    assert found is not None, f"não reconheceu a alcunha em {transcript!r}"
    assert found["phrase"] == phrase
    assert found["query"] == query


@pytest.mark.parametrize(
    "transcript",
    [
        "minha vizinha chegou agora",
        "a vizinha do lado reclamou do barulho",
        "a única coisa que eu quero é silêncio",
        "a situação econômica do país melhorou",
    ],
)
def test_variante_nao_aciona_com_palavra_comum(transcript: str) -> None:
    """Palavra comum do português continua fora: só as formas inventadas viram alcunha."""
    assert wake.match_wake_phrase(transcript, ALIASES, VARIANTES) is None


def test_variantes_vem_da_configuracao() -> None:
    """As formas medidas ficam no assistant.yaml, não no código."""
    assert {"conica", "iconica"} <= set(main.WAKE_VARIANTS["kunica"])
    assert {"tevzinha", "teve sozinha"} <= set(main.WAKE_VARIANTS["tvzinha"])

    found = wake.match_wake_phrase("cônica, que horas são?", main.WAKE_PHRASES, main.WAKE_VARIANTS)

    assert found is not None
    assert found["phrase"] == "kunica"
    assert found["query"] == "que horas são?"


def _silence_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)
    return buffer.getvalue()


@pytest.mark.skipif(not main.stt.model_ready(), reason="modelo de fala não está disponível neste ambiente")
def test_transcribe_com_scan_wake_nao_confunde_silencio_com_alcunha(client) -> None:
    response = client.post(
        "/api/transcribe?scan_wake=true",
        content=_silence_wav(),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == ""
    assert payload["wake"] is None


@pytest.mark.skipif(not main.stt.model_ready(), reason="modelo de fala não está disponível neste ambiente")
def test_transcribe_sem_scan_wake_mantem_o_formato_antigo(client) -> None:
    """O botão de microfone continua recebendo só texto e confiança."""
    response = client.post(
        "/api/transcribe",
        content=_silence_wav(),
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == ""
    assert 0.0 <= payload["confidence"] <= 1.0
