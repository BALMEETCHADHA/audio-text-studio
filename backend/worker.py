"""
The long-running work that runs as a FastAPI background task after a job
is created (see main.py). This app is ENGLISH ONLY.

Two backends are supported for both steps:

- transcription: a hosted Whisper API (OpenAI, or Groq's free OpenAI-compatible
  one; TRANSCRIPTION_BACKEND=openai) or a local faster-whisper model
  (TRANSCRIPTION_BACKEND=local, no key needed).
- analysis (summary / key points / highlights / AI insights): a hosted model
  (ANALYSIS_BACKEND=openai) or a local extractive summarizer
  (ANALYSIS_BACKEND=local, see services/local_analysis.py).

If the spoken language is not English, the job ends with status "not_english"
and a plain message asking for English audio — nothing else is produced.

Swap point for scaling up: if you outgrow a single server's threadpool,
replace `background_tasks.add_task(process_full_job, ...)` in main.py with
a real task queue (Celery, RQ, arq) calling these same functions.
"""
import logging
from pathlib import Path
import re

import jobstore
from config import settings
from languages import NotEnglishAudio, language_name, not_english_message
from services import (
    analysis,
    audio_preprocessing,
    correction,
    diarization,
    export_docx,
    export_image,
    local_analysis,
    pdf_report,
)

MIN_SUMMARY_WORDS = 10
MAX_SUMMARY_WORDS = 500

_log = logging.getLogger(__name__)

def clamp_summary_words(value) -> int:
    """The summary length is whatever the person picked or typed (30 / 50 / 70 / 100 / custom), kept sensible."""
    try:
        words = int(float(value))
    except (TypeError, ValueError):
        words = 70
    return max(MIN_SUMMARY_WORDS, min(MAX_SUMMARY_WORDS, words))


def _apply_spelling_fix(
    text: str, vocabulary_hint: str | None, context: str | None, enabled: bool
) -> tuple[str, str | None, list[dict]]:
    """
    Returns (text to use, the original heard text if anything changed else None, list of changes).
    Needs an AI model; without one, or on any failure, the transcript is returned untouched.
    """
    if not enabled or not ai_insights_available():
        return text, None, []
    fixed, changes = correction.correct_transcript(text, vocabulary_hint, context)
    if not changes:
        return text, None, []
    return fixed, text, changes


def _speaker_labels(
    audio_path: Path, segments: list[dict], wanted: bool, corrections: list[dict], warnings: list[str]
) -> tuple[list[dict], str | None]:
    """Optional "who is speaking". Returns (segments, "Speaker 1: ..." text or None). Never fails the job."""
    if not wanted:
        return segments, None
    if not diarization.diarization_available():
        warnings.append("Speaker labels are not set up on this server, so the transcript has none (see the README).")
        return segments, None
    try:
        segments = diarization.label_speakers(audio_path, segments)
        labeled = diarization.speaker_transcript(segments)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Speaker labelling failed: %s", exc)
        warnings.append(f"Speaker labels couldn't be added ({exc}).")
        return segments, None
    if labeled:
        for c in corrections:  # keep the spelling fixes in the labelled version too
            labeled = re.sub(rf"\b{re.escape(c['from'])}\b", c["to"], labeled)
    return segments, labeled


def _transcribe(audio_path: Path, vocabulary_hint: str | None = None):
    if settings.transcription_backend == "local":
        from services import local_transcription

        return local_transcription.transcribe_audio(audio_path, vocabulary_hint)
    from services import transcription

    return transcription.transcribe_audio(audio_path, vocabulary_hint)


def _maybe_denoise(audio_path: Path, reduce_noise: bool) -> tuple[Path, bool]:
    """
    Returns (path_to_actually_transcribe, whether_it_was_applied). Falls
    back to the original file — rather than failing the job — if ffmpeg
    isn't available or the filter chain errors on this particular file,
    same best-effort philosophy as translation elsewhere in this module.
    """
    if not reduce_noise:
        return audio_path, False
    try:
        return audio_preprocessing.denoise_audio(audio_path), True
    except Exception:
        return audio_path, False


def flag_if_looks_unreliable(text: str, duration_seconds: float | None = None) -> str | None:
    """
    A lightweight, honest check for the most common signatures of a failed
    transcription: the model getting stuck repeating a word or short
    phrase, or producing almost no content for a long recording — instead
    of actually understanding the audio. This is a well-documented Whisper
    failure mode — worse on smaller/local models, noisy audio, or
    languages the model handles less well — and it's especially misleading
    because the output still *looks* like a transcript rather than an
    obvious error.

    This can't catch every kind of wrong transcript, only these specific
    "stuck in a loop" / "barely any real content" patterns — but they're
    common enough, and confusing enough when presented as if they were
    real, that flagging them plainly is worth doing on its own.

    duration_seconds, when available from the transcription's own segment
    timestamps, catches the most severe case directly: a two-word
    transcript for 26 seconds of continuous real speech (an actual
    reported failure) is far too short to be a real transcript, even
    though two words alone isn't enough to judge for repetition.
    """
    words = re.findall(r"\S+", text.lower())

    if duration_seconds and duration_seconds >= 8 and len(words) < duration_seconds * 0.5:
        return (
            f"This transcript has only {len(words)} word(s) for about {duration_seconds:.0f} "
            "seconds of audio — far less than continuous speech usually produces. This "
            "usually means the model failed to make sense of the audio rather than the "
            "recording genuinely having that little content. Worth trying again with less "
            "background noise, a larger local model, or the OpenAI backend."
        )

    if len(words) < 6:
        return None  # too short to judge fairly — a real short utterance shouldn't be flagged

    # Signal 1: the same word appears several times in a row — the
    # unmistakable footprint of a repetition loop ("kya hai kya hai kya
    # hai...", "dhahahaha dhahaha").
    max_run = 1
    current_run = 1
    for i in range(1, len(words)):
        if words[i] == words[i - 1]:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1
    if max_run >= 4:
        return (
            "This transcript repeats the same word several times in a row, which usually "
            "means the model got stuck rather than actually understanding the audio — a "
            "known failure mode, especially on noisy audio, background hum, or a smaller "
            "local model. Worth trying again with less background noise or the OpenAI "
            "backend before trusting this result."
        )

    # Signal 2: very low variety across the whole transcript — a handful of
    # distinct words padding out to fill the audio's length.
    unique_ratio = len(set(words)) / len(words)
    if unique_ratio < 0.3:
        return (
            "This transcript uses very few distinct words for its length, which can mean "
            "the model struggled with this audio rather than the recording genuinely being "
            "this repetitive. Worth double-checking against the original audio."
        )

    return None


def _result_duration(result) -> float | None:
    """Best-effort audio duration from the transcription's own segment timestamps."""
    if not result.segments:
        return None
    try:
        return max(seg["end"] for seg in result.segments)
    except (KeyError, ValueError, TypeError):
        return None


def _transcription_model_label() -> str:
    """'How this was made' — shown on the results page so a bad transcript
    is visibly traceable to a small/local model rather than looking like
    an unexplained fluke."""
    if settings.transcription_backend == "local":
        from services import local_transcription

        return local_transcription.active_model_label()
    host = (settings.openai_base_url or "").lower()
    provider = "OpenAI" if not host else ("Groq" if "groq" in host else "hosted API")
    return f"{settings.transcribe_model} ({provider})"


def _safe_export(label: str, build_fn, warnings: list[str]) -> str | None:
    """
    Run one export (PDF/Word/image) without letting it sink the whole job.

    A failure here used to mark the entire job as "error" — so a transcript
    that took minutes to produce was thrown away because one optional file
    format couldn't be rendered. Now each format fails on its own, the rest
    of the result is kept, and the reason is recorded as a warning the user
    actually sees.
    """
    try:
        return build_fn().stem
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{label} could not be generated: {exc}")
        return None


def ai_insights_available() -> bool:
    """True when a language model is configured to write AI insights (the page hides the option otherwise)."""
    return settings.analysis_backend != "local" and bool(settings.openai_api_key)


def _analyze(
    transcript: str,
    summary_words: int,
    include_key_points: bool,
    include_highlights: bool,
    include_ai_insights: bool,
    context: str | None,
    warnings: list[str],
    source_kind: str = "audio",
) -> dict:
    """
    Summary / key points / highlights / AI insights for an English transcript.

    AI insights come only from a real language model. When one isn't configured, or
    can't be reached, they are simply left out (no placeholder text, no error dump).

    A hosted model can fail for reasons that have nothing to do with the user's audio
    (rate limit on a free plan, a bad key, a retired model). That must not cost them a
    transcript they already waited for, so on any failure this falls back to the free
    local summarizer and adds ONE short, plain note. The technical reason goes to the
    server log, not onto the page.
    """
    def local() -> dict:
        return local_analysis.analyze_transcript_local(
            transcript=transcript,
            summary_words=summary_words,
            include_key_points=include_key_points,
            include_highlights=include_highlights,
            language_code="en",
        )

    if settings.analysis_backend == "local":
        return local()

    try:
        extras = analysis.analyze_transcript(
            transcript=transcript,
            summary_words=summary_words,
            include_key_points=include_key_points,
            include_highlights=include_highlights,
            include_ai_insights=include_ai_insights,
            context=context,
            source_kind=source_kind,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("AI analysis failed, using the basic summary instead: %s", exc)
        warnings.append(
            "The AI service couldn't be reached this time, so this is a basic summary and "
            "AI insights are left out. Press 'Re-run summary' to try again."
        )
        return local()

    if summary_words and not extras.get("summary"):
        extras["summary"] = local().get("summary", "")  # the model answered without one
    if not extras.get("ai_insights"):
        extras.pop("ai_insights", None)
    return extras


def _mark_not_english(job_id: str, exc: NotEnglishAudio):
    jobstore.update_job(
        job_id,
        status="not_english",
        detected_language=language_name(exc.language),
        error=not_english_message(exc.language),
    )


def process_full_job(
    job_id: str,
    audio_path: Path,
    summary_words: int,
    include_key_points: bool,
    include_highlights: bool,
    include_ai_insights: bool,
    include_pdf: bool,
    include_docx: bool,
    include_image: bool,
    reduce_noise: bool,
    vocabulary_hint: str | None,
    context: str | None,
    correct_spelling: bool = False,
    label_speakers: bool = False,
):
    jobstore.update_job(job_id, status="processing")
    transcribe_path = audio_path
    try:
        summary_words = clamp_summary_words(summary_words)

        transcribe_path, noise_reduced = _maybe_denoise(audio_path, reduce_noise)
        result = _transcribe(transcribe_path, vocabulary_hint=vocabulary_hint)
        result.text, raw_text, corrections = _apply_spelling_fix(
            result.text, vocabulary_hint, context, correct_spelling
        )

        warnings: list[str] = []
        unreliable = flag_if_looks_unreliable(result.text, _result_duration(result))
        if unreliable:
            warnings.append(unreliable)

        audio_duration = _result_duration(result)
        word_count = len(result.text.split())

        segments, labeled_transcript = _speaker_labels(
            transcribe_path, result.segments, label_speakers, corrections, warnings
        )

        extras = _analyze(
            result.text, summary_words, include_key_points, include_highlights,
            include_ai_insights, context, warnings,
        )
        summary = extras.get("summary")
        key_points = extras.get("key_points", [])
        ai_insights = extras.get("ai_insights")
        dates_mentioned = extras.get("dates_mentioned", [])
        links_mentioned = extras.get("links_mentioned", [])
        notable_terms = extras.get("notable_terms", [])

        pdf_id = docx_id = image_id = None
        if include_pdf:
            pdf_id = _safe_export("PDF", lambda: pdf_report.build_full_report_pdf(
                transcript=result.text,
                summary=summary,
                key_points=key_points,
                links_mentioned=links_mentioned,
                ai_insights=ai_insights,
                dates_mentioned=dates_mentioned,
                notable_terms=notable_terms,
            ), warnings)
        if include_docx:
            docx_id = _safe_export("Word document", lambda: export_docx.build_full_report_docx(
                transcript=result.text,
                summary=summary,
                key_points=key_points,
                dates_mentioned=dates_mentioned,
                links_mentioned=links_mentioned,
                notable_terms=notable_terms,
                ai_insights=ai_insights,
            ), warnings)
        if include_image:
            image_id = _safe_export("Image", lambda: export_image.build_summary_image(
                title="Audio Transcription Report",
                summary=summary,
                key_points=key_points,
                transcript=result.text,
                ai_insights=ai_insights,
                dates=dates_mentioned,
                links=links_mentioned,
                notable_terms=notable_terms,
            ), warnings)

        jobstore.update_job(
            job_id,
            status="done",
            detected_language="en",
            transcript=result.text,
            transcript_raw=raw_text,
            corrections=corrections,
            labeled_transcript=labeled_transcript,
            transcription_model=_transcription_model_label(),
            audio_duration_seconds=audio_duration,
            word_count=word_count,
            segments=segments,
            summary=summary,
            summary_word_target=summary_words,
            key_points=key_points,
            dates_mentioned=dates_mentioned,
            links_mentioned=links_mentioned,
            notable_terms=notable_terms,
            ai_insights=ai_insights,
            diarization_available=diarization.diarization_available(),
            noise_reduction_applied=noise_reduced,
            pdf_report_id=pdf_id,
            docx_report_id=docx_id,
            image_report_id=image_id,
            warnings=warnings,
        )
    except NotEnglishAudio as exc:
        _mark_not_english(job_id, exc)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the poller
        jobstore.mark_error(job_id, str(exc))
    finally:
        if transcribe_path != audio_path:
            transcribe_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)


def reanalyze_full_job(
    job_id: str,
    summary_words: int,
    include_key_points: bool,
    include_highlights: bool,
    include_ai_insights: bool,
    context: str | None,
):
    """
    Re-runs ONLY the summary/key-points/highlights step, from whatever
    transcript text is currently stored on the job — including any edits
    the user made via POST /api/jobs/{id}/transcript. No audio is involved
    (the original file is deleted right after transcription), so this is fast
    and cheap, and is exactly what "fix a name once, everything downstream
    updates" needs.
    """
    job = jobstore.get_job(job_id)
    if not job:
        return
    jobstore.update_job(job_id, status="processing")
    try:
        summary_words = clamp_summary_words(summary_words)

        warnings: list[str] = []
        extras = _analyze(
            job.get("transcript") or "", summary_words, include_key_points, include_highlights,
            include_ai_insights, context, warnings,
            source_kind="text" if job.get("mode") == "tts" else "audio",
        )
        jobstore.update_job(
            job_id,
            status="done",
            summary=extras.get("summary"),
            summary_word_target=summary_words,
            key_points=extras.get("key_points", []),
            dates_mentioned=extras.get("dates_mentioned", []),
            links_mentioned=extras.get("links_mentioned", []),
            notable_terms=extras.get("notable_terms", []),
            ai_insights=extras.get("ai_insights"),
            warnings=(job.get("warnings") or []) + warnings,
        )
    except Exception as exc:  # noqa: BLE001
        jobstore.mark_error(job_id, str(exc))


def process_transcribe_job(
    job_id: str,
    audio_path: Path,
    include_pdf: bool,
    include_docx: bool,
    reduce_noise: bool,
    vocabulary_hint: str | None,
    correct_spelling: bool = False,
    label_speakers: bool = False,
):
    jobstore.update_job(job_id, status="processing")
    transcribe_path = audio_path
    try:
        transcribe_path, noise_reduced = _maybe_denoise(audio_path, reduce_noise)
        result = _transcribe(transcribe_path, vocabulary_hint=vocabulary_hint)
        result.text, raw_text, corrections = _apply_spelling_fix(
            result.text, vocabulary_hint, None, correct_spelling
        )

        warnings: list[str] = []
        unreliable = flag_if_looks_unreliable(result.text, _result_duration(result))
        if unreliable:
            warnings.append(unreliable)
        _, labeled_transcript = _speaker_labels(
            transcribe_path, result.segments, label_speakers, corrections, warnings
        )

        audio_duration = _result_duration(result)
        word_count = len(result.text.split())

        pdf_id = docx_id = None
        if include_pdf:
            pdf_id = _safe_export("PDF", lambda: pdf_report.build_transcribe_only_pdf(result.text), warnings)
        if include_docx:
            docx_id = _safe_export("Word document", lambda: export_docx.build_transcribe_docx(result.text), warnings)

        jobstore.update_job(
            job_id,
            status="done",
            detected_language="en",
            transcript=result.text,
            transcript_raw=raw_text,
            corrections=corrections,
            labeled_transcript=labeled_transcript,
            transcription_model=_transcription_model_label(),
            audio_duration_seconds=audio_duration,
            word_count=word_count,
            pdf_report_id=pdf_id,
            docx_report_id=docx_id,
            noise_reduction_applied=noise_reduced,
            warnings=warnings,
        )
    except NotEnglishAudio as exc:
        _mark_not_english(job_id, exc)
    except Exception as exc:  # noqa: BLE001
        jobstore.mark_error(job_id, str(exc))
    finally:
        if transcribe_path != audio_path:
            transcribe_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)


def process_text_job(
    job_id: str,
    text: str,
    summary_words: int,
    include_key_points: bool,
    include_highlights: bool,
    include_ai_insights: bool,
    voice_id: str,
    context: str | None,
):
    """
    Text -> Audio: the text is analysed exactly like a transcript (summary, key points, AI insights,
    highlights). The audio itself is NOT made here — it is made on demand when the person presses a
    speaker button or downloads accents (see main.py), so this finishes as fast as the analysis.
    """
    jobstore.update_job(job_id, status="processing")
    try:
        summary_words = clamp_summary_words(summary_words)
        warnings: list[str] = []
        extras = _analyze(
            text, summary_words, include_key_points, include_highlights,
            include_ai_insights, context, warnings, source_kind="text",
        )
        jobstore.update_job(
            job_id,
            status="done",
            detected_language="en",
            transcript=text,
            word_count=len(text.split()),
            voice_id=voice_id,
            summary=extras.get("summary"),
            summary_word_target=summary_words,
            key_points=extras.get("key_points", []),
            dates_mentioned=extras.get("dates_mentioned", []),
            links_mentioned=extras.get("links_mentioned", []),
            notable_terms=extras.get("notable_terms", []),
            ai_insights=extras.get("ai_insights"),
            warnings=warnings,
        )
    except Exception as exc:  # noqa: BLE001
        jobstore.mark_error(job_id, str(exc))
