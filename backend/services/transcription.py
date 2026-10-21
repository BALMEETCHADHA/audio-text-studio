"""
Speech-to-text via an OpenAI-compatible hosted Whisper endpoint — OpenAI itself,
or any service that speaks the same API (Groq's hosted Whisper has a free tier:
set OPENAI_BASE_URL=https://api.groq.com/openai/v1 and
TRANSCRIBE_MODEL=whisper-large-v3-turbo).

English only: the language is never passed in. Whisper detects it, and if it is
not English the job stops with NotEnglishAudio (see languages.py / worker.py).
Speaker diarization is a separate, optional step: see services/diarization.py.
"""
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from config import settings
from languages import NotEnglishAudio, build_transcription_prompt, is_english


@dataclass
class TranscriptionResult:
    text: str
    detected_language: str
    segments: list[dict] = field(default_factory=list)  # [{start, end, text}]


def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError(
            "No API key is set. Add OPENAI_API_KEY (a free Groq key works — see README) "
            "or switch to TRANSCRIPTION_BACKEND=local."
        )
    kwargs = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)


def transcribe_audio(file_path: Path, vocabulary_hint: str | None = None) -> TranscriptionResult:
    """
    vocabulary_hint: optional names/terms the audio is expected to contain
    (e.g. "Infosys, WhatsApp"); biases Whisper toward those spellings.
    """
    client = _client()

    with open(file_path, "rb") as audio_file:
        kwargs = {
            "model": settings.transcribe_model,
            "file": audio_file,
            "response_format": "verbose_json",
            # 0 = the most literal, least "creative" decoding: fewer invented or swapped words.
            "temperature": 0,
        }
        prompt = build_transcription_prompt(vocabulary_hint)
        if prompt:
            kwargs["prompt"] = prompt

        response = client.audio.transcriptions.create(**kwargs)

    detected = getattr(response, "language", None)
    if detected and not is_english(detected):
        raise NotEnglishAudio(detected)

    segments = [
        {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        for seg in getattr(response, "segments", []) or []
    ]

    return TranscriptionResult(
        text=response.text.strip(),
        detected_language="en",
        segments=segments,
    )
