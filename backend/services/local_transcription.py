"""
Speech-to-text with no OpenAI account needed. Uses faster-whisper, an
open-source, locally-run implementation of Whisper. Set
TRANSCRIPTION_BACKEND=local in .env to use this instead of the OpenAI API.

English only: non-English audio is detected up front and rejected (NotEnglishAudio).

Trade-offs vs. the OpenAI backend (services/transcription.py), and please
read this before trusting local mode for anything that matters:
- No per-minute cost, no API key.
- Slower on CPU (a GPU helps a lot; still usable on CPU for short clips).
- First run downloads model weights (a few hundred MB to several GB
  depending on size, one-time, needs internet for that download even
  though there's no ongoing API cost).
- Accuracy scales heavily with model size, and this is the one that
  actually matters: the default "small" model is noticeably behind
  OpenAI's hosted API on anything other than short, clear, low-noise
  audio, and that gap widens for languages other than English and for
  background noise. On real-world recordings a small local model can
  produce confidently-wrong garbage (repeated syllables, hallucinated
  words) rather than failing loudly. worker.py's
  `flag_if_looks_unreliable()` catches the most obvious cases of this and
  surfaces a warning, but it can't catch everything a weak model gets
  wrong. If reliable multi-language transcription is the actual goal,
  TRANSCRIPTION_BACKEND=openai is the one that delivers it — local mode is
  for quick, low-stakes testing or when a GPU is available (see the Colab
  notebook, which picks "large-v3" automatically when a GPU is present).

KNOWN UPSTREAM ISSUE (as of Oct 2026): PyAV 19.0 removed the
`metadata_errors` argument from `av.open()`, which faster-whisper 1.2.1
still passes — every local transcription fails with "open() got an
unexpected keyword argument 'metadata_errors'" if a plain `pip install
faster-whisper` pulls in PyAV 19+. requirements.txt and the Colab notebook
both pin `av<19` to avoid this; if you see that exact error, your
environment installed an unpinned `av` — run `pip install "av<19"
--force-reinstall` (or re-run the Colab setup cell, which already pins
it). This is a bug in faster-whisper/PyAV's compatibility, not in this
project; drop the pin once faster-whisper ships a fix.

KNOWN COLAB ISSUE: on a GPU session faster-whisper can start fine and then
fail while transcribing with "Library libcublas.so.12 is not found or cannot
be loaded" (or a similar libcudnn / CUDA message) when the session's CUDA
libraries don't match what CTranslate2 expects. The Colab notebook installs
the matching libraries; as a safety net this module also catches that error,
reloads the model on the CPU, and retries once, so a GPU/library mismatch
slows a job down instead of failing it.

Same return type as the OpenAI backend (TranscriptionResult) so worker.py
can use either one interchangeably based on settings.transcription_backend.
"""
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from languages import NotEnglishAudio, build_transcription_prompt, is_english

# Re-use the same result shape as the OpenAI backend.
from services.transcription import TranscriptionResult  # noqa: F401

import logging

_log = logging.getLogger(__name__)

_model = None
_model_name: str | None = None
_cpu_fallback = False


def _get_model():
    global _model, _model_name
    if _model is None:
        from faster_whisper import WhisperModel  # imported lazily: optional, heavy dependency

        if _cpu_fallback:
            # large-v3/medium on a Colab CPU would take far too long, so the
            # fallback uses a model that finishes in reasonable time.
            _model_name = (
                settings.local_whisper_model
                if settings.local_whisper_model in ("tiny", "base", "small")
                else "small"
            )
            _model = WhisperModel(_model_name, device="cpu", compute_type="int8")
        else:
            _model_name = settings.local_whisper_model
            _model = WhisperModel(_model_name, device="auto", compute_type="auto")
    return _model


def active_model_label() -> str:
    """What was really used — shown on the results page ('how this was made')."""
    name = _model_name or settings.local_whisper_model
    return f"{name} (local, free, CPU fallback)" if _cpu_fallback else f"{name} (local, free)"


def _is_cuda_library_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("libcublas", "libcudnn", "libcudart", "cuda", "cudnn", "cublas"))


def _switch_to_cpu(exc: Exception) -> None:
    global _model, _cpu_fallback
    _log.warning("GPU transcription failed (%s); retrying on CPU.", exc)
    _cpu_fallback = True
    _model = None  # forces _get_model() to build a CPU model


def _run(model, file_path: Path, prompt: str | None) -> TranscriptionResult:
    # language=None -> Whisper detects the language itself, which is what lets us
    # refuse non-English audio instead of transcribing it badly.
    segments_iter, info = model.transcribe(
        str(file_path),
        language=None,
        vad_filter=True,
        initial_prompt=prompt,
        # condition_on_previous_text=False is the specific, well-documented
        # fix for the "word word word word..." repetition-loop failure
        # mode: by default Whisper feeds its own last output back in as
        # context for the next chunk, so once it starts repeating, that
        # repetition itself becomes the context and the loop reinforces
        # itself. Turning this off means a bad chunk can't drag the rest
        # of the transcript down with it.
        condition_on_previous_text=False,
    )

    # Language detection has already happened by this point, so a non-English
    # file is rejected right away instead of after minutes of transcribing.
    if info.language and not is_english(info.language):
        raise NotEnglishAudio(info.language)

    # The segments are produced lazily, so a GPU-library error can surface
    # here (while iterating) rather than in model.transcribe() itself.
    segments = []
    full_text_parts = []
    for seg in segments_iter:
        text = seg.text.strip()
        full_text_parts.append(text)
        segments.append({"start": seg.start, "end": seg.end, "text": text})

    return TranscriptionResult(
        text=" ".join(full_text_parts).strip(),
        detected_language="en",
        segments=segments,
    )


def transcribe_audio(file_path: Path, vocabulary_hint: str | None = None) -> TranscriptionResult:
    """
    vocabulary_hint: optional free text naming names/terms the audio is
    expected to contain (e.g. "Infosys, WhatsApp"); see
    languages.build_transcription_prompt.
    """
    prompt = build_transcription_prompt(vocabulary_hint)

    try:
        return _run(_get_model(), file_path, prompt)
    except NotEnglishAudio:
        raise
    except Exception as exc:  # noqa: BLE001
        if _cpu_fallback or not _is_cuda_library_error(exc):
            raise
        _switch_to_cpu(exc)
        return _run(_get_model(), file_path, prompt)
