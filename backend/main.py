"""
Entry point. Run with:  uvicorn main:app --reload --port 8000

The heavy lifting (transcription + analysis) happens as a background task,
not inline in the request/response cycle:

1. POST /api/jobs/full  or  POST /api/jobs/transcribe
   Uploads the audio, creates a job row (status "queued"), schedules the
   real work in the background, and returns immediately with a job id.

2. GET /api/jobs/{job_id}
   Poll this until status is "done", "error" or "not_english". The same response object
   carries the full result once done.

3. GET /api/jobs
   Recent job history, for the "History" view in the frontend.

4. POST /api/jobs/{job_id}/export
   On-demand: generate an additional download for an already-finished job
   in a different format (pdf/docx/jpeg) without re-running transcription.
   Cheap and fast — it only re-renders a file from what's already stored.

Text -> Audio (all under /api/):
   GET  /tts/voices               the narration voices (accents), India first
   GET  /tts/preview/{voice}      ~10 second sample of one voice
   POST /extract-text             text out of an uploaded PDF / Word / image file
   POST /jobs/text                summary + key points + insights + highlights for typed/pasted text
   POST /jobs/{id}/speech         make the audio for the whole text or its summary in one voice
   POST /jobs/{id}/audio-bundle   several accents at once (one MP3, or a ZIP of MP3s); poll
   GET  /bundles/{bundle_id}      ...for its progress

English only: audio in any other language ends the job with status
"not_english" and a message asking for English audio (see worker.py).

See worker.py for the actual processing functions and jobstore.py for the
SQLite-backed persistence behind all of this.
"""
import re
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.concurrency import run_in_threadpool

import jobstore
import worker
from auth import auth_enabled, client_ip, owner_of, require_api_key
from config import settings
from models import (
    BundleCreatedResponse,
    BundleStatusResponse,
    ExportCreatedResponse,
    JobCreatedResponse,
    JobListResponse,
    JobResponse,
    SpeechCreatedResponse,
)
from services import diarization, export_docx, export_image, pdf_report, text_extract, tts, tts_voices

app = FastAPI(title="Audio Transcription Studio API")
jobstore.init_db()

if not settings.access_key:
    print(
        "\n[NOTE] No ACCESS_KEY set in .env — the app is open, no login/key needed. "
        "That's the default and is fine for personal use or a temporary demo link. "
        "Set ACCESS_KEY in .env only if you want to require one. See auth.py.\n"
    )
if settings.transcription_backend == "local" or settings.analysis_backend == "local":
    print(
        f"[NOTE] Running with transcription_backend={settings.transcription_backend!r}, "
        f"analysis_backend={settings.analysis_backend!r} — no OpenAI account needed for "
        "whichever of those is 'local'. See README for what's traded off.\n"
    )

limiter = Limiter(key_func=client_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

_RATE = f"{settings.rate_limit_per_minute}/minute"
_EXPORT_FORMATS = {"pdf", "docx", "jpeg"}


def _save_upload(file: UploadFile) -> Path:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    suffix = Path(file.filename or "audio").suffix or ".webm"
    dest = settings.storage_path / "uploads" / f"{uuid.uuid4().hex}{suffix}"

    size = 0
    with open(dest, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    413, f"File too large. Max size is {settings.max_upload_mb} MB."
                )
            out.write(chunk)
    return dest


@app.get("/api/health")
def health():
    # `ai_insights` lets the page hide the "AI insights" option when no language model is configured.
    return {
        "status": "ok",
        "ai_insights": worker.ai_insights_available(),
        # `tts` lets the page warn when Text -> Audio can't work (no voice package installed).
        "tts": tts.is_available(),
        # `diarization` = "Speaker 1 / Speaker 2" labels are set up on this server.
        "diarization": diarization.diarization_available(),
    }


@app.get("/api/auth-required")
def auth_required():
    """Lets the frontend know whether to prompt for an access key at all."""
    return {"required": auth_enabled()}


def _enforce_daily_limit(request: Request) -> str:
    """Counts this job against the person's 24-hour allowance (DAILY_JOB_LIMIT). Returns the owner id."""
    owner = owner_of(request)
    limit = settings.daily_job_limit
    if limit and jobstore.count_jobs_last_day(owner) >= limit:
        raise HTTPException(
            429, f"You have reached today's limit of {limit} jobs. Please try again in a few hours."
        )
    return owner


@app.get("/api/me", dependencies=[Depends(require_api_key)])
def me(request: Request):
    """Who is signed in and how much of today's allowance is used (shown at the top of the page)."""
    owner = owner_of(request)
    return {
        "name": getattr(request.state, "user", None),
        "auth_required": auth_enabled(),
        "used": jobstore.count_jobs_last_day(owner),
        "limit": settings.daily_job_limit,
    }


@app.post("/api/jobs/full", response_model=JobCreatedResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(_RATE)
async def create_full_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    summary_words: int = Form(70),
    include_key_points: bool = Form(True),
    include_highlights: bool = Form(True),
    include_ai_insights: bool = Form(True),
    include_pdf: bool = Form(True),
    include_docx: bool = Form(True),
    include_image: bool = Form(False),
    reduce_noise: bool = Form(False),
    correct_spelling: bool = Form(False),
    label_speakers: bool = Form(False),
    vocabulary_hint: str | None = Form(None),
    context: str | None = Form(None),
):
    owner = _enforce_daily_limit(request)
    audio_path = _save_upload(file)
    job_id = jobstore.create_job(mode="full", filename=file.filename or "recording", owner=owner)

    background_tasks.add_task(
        worker.process_full_job,
        job_id=job_id,
        audio_path=audio_path,
        summary_words=summary_words,
        include_key_points=include_key_points,
        include_highlights=include_highlights,
        include_ai_insights=include_ai_insights,
        include_pdf=include_pdf,
        include_docx=include_docx,
        include_image=include_image,
        reduce_noise=reduce_noise,
        vocabulary_hint=vocabulary_hint,
        context=context,
        correct_spelling=correct_spelling,
        label_speakers=label_speakers,
    )
    return JobCreatedResponse(job_id=job_id, status="queued")


@app.post("/api/jobs/transcribe", response_model=JobCreatedResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(_RATE)
async def create_transcribe_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    include_pdf: bool = Form(False),
    include_docx: bool = Form(False),
    reduce_noise: bool = Form(False),
    correct_spelling: bool = Form(False),
    label_speakers: bool = Form(False),
    vocabulary_hint: str | None = Form(None),
):
    owner = _enforce_daily_limit(request)
    audio_path = _save_upload(file)
    job_id = jobstore.create_job(mode="transcribe", filename=file.filename or "recording", owner=owner)

    background_tasks.add_task(
        worker.process_transcribe_job,
        job_id=job_id,
        audio_path=audio_path,
        include_pdf=include_pdf,
        include_docx=include_docx,
        reduce_noise=reduce_noise,
        vocabulary_hint=vocabulary_hint,
        correct_spelling=correct_spelling,
        label_speakers=label_speakers,
    )
    return JobCreatedResponse(job_id=job_id, status="queued")


@app.get("/api/jobs", response_model=JobListResponse, dependencies=[Depends(require_api_key)])
def list_jobs(limit: int = Query(30, le=100), offset: int = Query(0, ge=0)):
    return JobListResponse(jobs=jobstore.list_jobs(limit=limit, offset=offset))


@app.get("/api/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(require_api_key)])
def get_job(job_id: str):
    job = jobstore.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return JobResponse(**job)


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def delete_job(job_id: str):
    deleted = jobstore.delete_job(job_id)
    if not deleted:
        raise HTTPException(404, "Job not found.")
    return {"deleted": True}


@app.post("/api/jobs/{job_id}/transcript", response_model=JobResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(_RATE)
async def edit_transcript(
    request: Request,
    job_id: str,
    transcript: str = Form(...),
):
    """
    Saves a user correction (e.g. a misspelled name) directly onto the
    job's stored transcript — no re-transcription, since the original
    audio no longer exists at this point. This only updates what's shown
    and downloaded; call POST .../reanalyze afterward to also refresh the
    summary/key points so they reflect the correction too.
    """
    job = jobstore.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job["status"] != "done":
        raise HTTPException(400, "Can't edit a job that hasn't finished processing yet.")

    # The "Speaker 1: ..." version no longer matches the edited text, so it is dropped.
    jobstore.update_job(job_id, transcript=transcript, word_count=len(transcript.split()), labeled_transcript=None)

    return JobResponse(**jobstore.get_job(job_id))


@app.post("/api/jobs/{job_id}/reanalyze", response_model=JobCreatedResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(_RATE)
async def reanalyze_job(
    request: Request,
    background_tasks: BackgroundTasks,
    job_id: str,
    summary_words: int = Form(70),
    include_key_points: bool = Form(True),
    include_highlights: bool = Form(True),
    include_ai_insights: bool = Form(True),
    context: str | None = Form(None),
):
    """
    Re-runs the summary/key-points/highlights from whatever transcript
    text is currently stored (including any edits saved via the endpoint
    above) — no audio or re-upload involved. Only valid for "full
    breakdown" jobs; "just transcribe" jobs have no summary to redo.
    """
    job = jobstore.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job["mode"] not in ("full", "tts"):
        raise HTTPException(400, "Only full-breakdown jobs have a summary to re-run.")
    if job["status"] != "done":
        raise HTTPException(400, "Can't re-analyze a job that hasn't finished processing yet.")

    background_tasks.add_task(
        worker.reanalyze_full_job,
        job_id=job_id,
        summary_words=summary_words,
        include_key_points=include_key_points,
        include_highlights=include_highlights,
        include_ai_insights=include_ai_insights,
        context=context,
    )
    return JobCreatedResponse(job_id=job_id, status="processing")


def _build_export(job: dict, fmt: str) -> Path:
    """One PDF / Word / image file from a finished job, in the same order as the results page."""
    transcript = job.get("labeled_transcript") or job.get("transcript") or ""
    if job["mode"] == "transcribe":
        if fmt == "pdf":
            return pdf_report.build_transcribe_only_pdf(transcript)
        if fmt == "docx":
            return export_docx.build_transcribe_docx(transcript)
        return export_image.build_summary_image(
            title="Audio Transcript", summary=None, key_points=[], transcript=transcript
        )

    is_text = job["mode"] == "tts"
    title = "Text and Audio Report" if is_text else "Audio Transcription Report"
    label = "Full Text" if is_text else "Full Transcript (word for word)"
    if fmt == "pdf":
        return pdf_report.build_full_report_pdf(
            transcript=transcript,
            summary=job.get("summary"),
            key_points=job.get("key_points") or [],
            links_mentioned=job.get("links_mentioned") or [],
            ai_insights=job.get("ai_insights"),
            dates_mentioned=job.get("dates_mentioned") or [],
            notable_terms=job.get("notable_terms") or [],
            title=title,
            transcript_label=label,
        )
    if fmt == "docx":
        return export_docx.build_full_report_docx(
            transcript=transcript,
            summary=job.get("summary"),
            key_points=job.get("key_points") or [],
            dates_mentioned=job.get("dates_mentioned") or [],
            links_mentioned=job.get("links_mentioned") or [],
            notable_terms=job.get("notable_terms") or [],
            ai_insights=job.get("ai_insights"),
            title=title,
            transcript_label=label,
        )
    return export_image.build_summary_image(
        title=title,
        summary=job.get("summary"),
        key_points=job.get("key_points") or [],
        transcript=transcript,
        transcript_label="FULL TEXT" if is_text else "FULL TRANSCRIPT",
        ai_insights=job.get("ai_insights"),
        dates=job.get("dates_mentioned") or [],
        links=job.get("links_mentioned") or [],
        notable_terms=job.get("notable_terms") or [],
    )


@app.post(
    "/api/jobs/{job_id}/export",
    response_model=ExportCreatedResponse,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(_RATE)
async def create_export(
    request: Request,
    job_id: str,
    format: str = Form(...),
):
    """
    Generates a PDF / Word / image download for a finished job, on demand, without re-running anything.
    This powers the download buttons at the bottom of the results page (English only).
    """
    if format not in _EXPORT_FORMATS:
        raise HTTPException(400, f"format must be one of: {', '.join(sorted(_EXPORT_FORMATS))}")

    job = jobstore.get_job(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(404, "Job not found, or not finished processing yet.")

    try:
        path = await run_in_threadpool(_build_export, job, format)
    except Exception as exc:
        # Whatever went wrong (a rendering library quirk, anything unforeseen), the frontend must
        # still get a JSON body it can parse — see errorDetail() in app.js.
        raise HTTPException(500, f"Couldn't generate that export: {exc}") from exc

    report_id = path.stem
    jobstore.add_export(job_id, format=format, report_id=report_id)
    return ExportCreatedResponse(report_id=report_id, format=format)


_DOWNLOAD_TYPES = [
    (".pdf", "application/pdf", "transcript-report"),
    (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "transcript-report"),
    (".jpg", "image/jpeg", "transcript-summary"),
    (".mp3", "audio/mpeg", "speech"),
    (".zip", "application/zip", "speech-audio"),
]


@app.get("/api/download/{report_id}")
def download_report(report_id: str, name: str | None = Query(None, max_length=120)):
    # Not gated by the API key on purpose: browsers can't attach a custom
    # header to a plain link click, and report_id is an unguessable random
    # UUID rather than a sequential id, so this doesn't reopen the "anyone
    # can rack up OpenAI costs" hole the key is there to close — it only
    # serves a file that already exists on disk.
    safe_id = Path(report_id).stem  # strip any path tricks
    reports_dir = settings.storage_path / "reports"
    nice = re.sub(r"[^A-Za-z0-9._ -]+", "", name or "").strip(" .-")[:80]

    for ext, media_type, default_name in _DOWNLOAD_TYPES:
        path = reports_dir / f"{safe_id}{ext}"
        if path.exists():
            return FileResponse(path, media_type=media_type, filename=f"{nice or default_name}{ext}")

    raise HTTPException(404, "Report not found (it may have expired).")


# ---------------------------------------------------------------------------
# Text -> Audio
# ---------------------------------------------------------------------------
@app.get("/api/tts/voices")
def tts_voice_list():
    """Static list (no secrets), so it needs no key. India first, then the rest."""
    return {
        "voices": [v.public() for v in tts_voices.VOICES],
        "default": tts_voices.DEFAULT_VOICE_ID,
        "max_chars": settings.max_text_chars,
    }


@app.get("/api/tts/preview/{voice_id}", dependencies=[Depends(require_api_key)])
def tts_preview(voice_id: str):
    """The ~10 second sample for one voice. Made once, then served from disk."""
    try:
        path = tts.preview_path(voice_id)
    except KeyError:
        raise HTTPException(404, "Unknown voice.")
    except tts.TTSError as exc:
        raise HTTPException(502, str(exc))
    return FileResponse(path, media_type="audio/mpeg")


@app.post("/api/extract-text", dependencies=[Depends(require_api_key)])
@limiter.limit(_RATE)
async def extract_text_endpoint(request: Request, file: UploadFile = File(...)):
    """Text out of an uploaded PDF / Word / image, so the person can check it before continuing."""
    path = _save_upload(file)
    try:
        text = await run_in_threadpool(text_extract.extract_text, path, file.filename or path.name)
    except text_extract.ExtractionError as exc:
        raise HTTPException(400, str(exc))
    finally:
        path.unlink(missing_ok=True)
    return {"text": text, "words": len(text.split()), "characters": len(text)}


def _title_from_text(text: str) -> str:
    first = " ".join(text.split())[:48]
    return first + ("…" if len(" ".join(text.split())) > 48 else "")


@app.post("/api/jobs/text", response_model=JobCreatedResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(_RATE)
async def create_text_job(
    request: Request,
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    summary_words: int = Form(70),
    include_key_points: bool = Form(True),
    include_highlights: bool = Form(True),
    include_ai_insights: bool = Form(True),
    voice_id: str = Form(tts_voices.DEFAULT_VOICE_ID),
    context: str | None = Form(None),
):
    text = text.strip()
    if len(text.split()) < 3:
        raise HTTPException(400, "Please give a little more text (at least a few words).")
    if len(text) > settings.max_text_chars:
        raise HTTPException(
            400, f"That text is too long ({len(text):,} characters). The limit is {settings.max_text_chars:,}."
        )
    if not tts_voices.has_voice(voice_id):
        raise HTTPException(400, "Unknown voice.")

    owner = _enforce_daily_limit(request)
    job_id = jobstore.create_job(mode="tts", filename=_title_from_text(text), owner=owner)
    background_tasks.add_task(
        worker.process_text_job,
        job_id=job_id,
        text=text,
        summary_words=summary_words,
        include_key_points=include_key_points,
        include_highlights=include_highlights,
        include_ai_insights=include_ai_insights,
        voice_id=voice_id,
        context=context,
    )
    return JobCreatedResponse(job_id=job_id, status="queued")


def _tts_job_text(job_id: str, part: str) -> str:
    """The text to speak for a finished Text -> Audio job: the whole text ('script') or its summary."""
    job = jobstore.get_job(job_id)
    if not job or job["status"] != "done" or job["mode"] != "tts":
        raise HTTPException(404, "Job not found, or not finished processing yet.")
    if part not in ("script", "summary"):
        raise HTTPException(400, "part must be 'script' or 'summary'.")
    text = job.get("transcript") if part == "script" else job.get("summary")
    if not (text or "").strip():
        raise HTTPException(400, "There is no summary to read aloud." if part == "summary" else "There is no text.")
    return text


def _tts_job_texts(job_id: str, target: str) -> str | list[str]:
    """For downloads: the whole text, the summary, or ('both') the summary and then the whole text."""
    if target != "both":
        return _tts_job_text(job_id, target)
    summary = _tts_job_text(job_id, "summary")
    script = _tts_job_text(job_id, "script")
    # The short spoken labels tell the listener where one part ends and the next begins.
    return [f"Summary. {summary}", f"Full text. {script}"]


@app.post("/api/jobs/{job_id}/speech", response_model=SpeechCreatedResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("30/minute")
def create_speech(
    request: Request,
    job_id: str,
    part: str = Form("script"),
    voice_id: str = Form(...),
):
    """
    Makes the audio for the whole text (part=script) or the summary (part=summary) in one voice and
    returns an id the page plays through /api/download/{id}. Sync on purpose: it runs in FastAPI's
    threadpool, so a long text doesn't freeze the server for other visitors.
    """
    if not tts_voices.has_voice(voice_id):
        raise HTTPException(400, "Unknown voice.")
    text = _tts_job_text(job_id, part)
    try:
        path = tts.synthesize_to_file(text, voice_id)
    except tts.TTSError as exc:
        raise HTTPException(502, str(exc))
    return SpeechCreatedResponse(report_id=path.stem)


# Progress of "download several accents" requests. Kept in memory: a bundle only matters for the
# minute or two it takes to make, and the finished file itself is on disk.
_bundles: dict[str, dict] = {}
_BUNDLE_KEEP = 200


def _run_bundle(bundle_id: str, text: str, voice_ids: list[str], label: str):
    state = _bundles[bundle_id]

    def progress(done: int, total: int):
        state["done"] = done

    try:
        path, fmt = tts.build_audio_bundle(text, voice_ids, label, progress)
        state.update(status="done", report_id=path.stem, format=fmt)
    except tts.TTSError as exc:
        state.update(status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        state.update(status="error", error=f"Couldn't create the audio: {exc}")


@app.post("/api/jobs/{job_id}/audio-bundle", response_model=BundleCreatedResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def create_audio_bundle(
    request: Request,
    background_tasks: BackgroundTasks,
    job_id: str,
    target: str = Form("script"),
    voices: str = Form(...),
):
    """Audio of the whole text (script), the summary, or both in one MP3 (both), in every chosen accent."""
    ids: list[str] = []
    for v in voices.split(","):
        v = v.strip()
        if v and v not in ids:
            ids.append(v)
    if not ids:
        raise HTTPException(400, "Tick at least one accent.")
    bad = [v for v in ids if not tts_voices.has_voice(v)]
    if bad:
        raise HTTPException(400, f"Unknown voice: {bad[0]}")
    if target not in ("script", "summary", "both"):
        raise HTTPException(400, "target must be 'script', 'summary' or 'both'.")
    text = _tts_job_texts(job_id, target)

    while len(_bundles) >= _BUNDLE_KEEP:  # forget the oldest finished requests
        _bundles.pop(next(iter(_bundles)))
    bundle_id = uuid.uuid4().hex
    _bundles[bundle_id] = {"status": "processing", "done": 0, "total": len(ids)}
    background_tasks.add_task(_run_bundle, bundle_id, text, ids, {"script": "whole-text", "summary": "summary", "both": "summary-and-text"}[target])
    return BundleCreatedResponse(bundle_id=bundle_id)


@app.get("/api/bundles/{bundle_id}", response_model=BundleStatusResponse, dependencies=[Depends(require_api_key)])
def get_bundle(bundle_id: str):
    state = _bundles.get(bundle_id)
    if not state:
        raise HTTPException(404, "That download request was not found (the server may have restarted). Please try again.")
    return BundleStatusResponse(**state)


# ---------------------------------------------------------------------------
# Serve the frontend from this same server + port.
#
# This is what makes single-tunnel setups (Colab + ngrok, a single Render/
# Railway service, etc.) simple: one process, one port, no CORS to worry
# about. Mounted LAST so it never shadows the /api/* routes above — Starlette
# checks routes in the order they were added, and all the explicit @app.get/
# @app.post/@app.delete routes were added first.
# ---------------------------------------------------------------------------
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
