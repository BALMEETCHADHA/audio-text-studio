#!/usr/bin/env python3
"""
Backend tests — run from the backend/ folder with:

    python3 test_backend.py

Several of these exist because of real crashes that shipped:

- A PDF with a multi-item bullet list raised "Not enough horizontal space to
  render a single character", which marked the whole job as failed and threw
  away a transcript that took minutes to produce (section 1).
- Smart punctuation (em dashes, curly quotes) crashed the built-in PDF font
  (section 6).
- A GPU-library mismatch on Colab ("libcublas.so.12 is not found") made every
  transcription fail (section 9).

Run these anywhere the real dependencies are installed (a Colab cell works
fine) — they use the actual fpdf2 / python-docx / Pillow / openai libraries
where the bug lived in how those behave, not in our logic.
"""
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

failures = 0


def check(name, fn):
    global failures
    try:
        fn()
        print(f"  PASS  {name}")
    except Exception:
        failures += 1
        print(f"  FAIL  {name}")
        print("        " + traceback.format_exc().strip().replace("\n", "\n        "))


# Long enough to wrap lines, plus an unbreakable URL-ish token.
LONG_TEXT = (
    "This is a transcript with several sentences that will wrap across multiple "
    "lines in the rendered document. It also contains a long unbroken token like "
    "https://example.com/some/deep/path?with=query&parameters=that&are=long to make "
    "sure word-breaking is handled. " * 3
)
MANY_BULLETS = [
    "First key point, which is reasonably long so that it wraps onto a second line in the PDF.",
    "Second key point.",
    "Third key point with a URL: example.com/resources/reading-list",
    "Fourth key point.",
    "Fifth key point, also fairly long so the layout has to wrap it properly across lines.",
    "Sixth key point.",
]

print("\n1. PDF export — the regression that broke real jobs")


def pdf_full_report_with_bullets():
    from services import pdf_report

    out = pdf_report.build_full_report_pdf(
        transcript=LONG_TEXT,
        summary="A short summary of the recording.",
        key_points=MANY_BULLETS,          # <-- 6 bullets; 2+ used to crash
        links_mentioned=["example.com/a", "example.com/b", "example.com/c"],
        ai_insights="Some insight about the recording.",
    )
    assert out.exists() and out.stat().st_size > 500, "PDF is missing or suspiciously small"


def pdf_transcribe_report():
    from services import pdf_report

    out = pdf_report.build_transcribe_only_pdf(LONG_TEXT)
    assert out.exists() and out.stat().st_size > 500


def pdf_single_bullet_and_empty_fields():
    from services import pdf_report

    out = pdf_report.build_full_report_pdf(
        transcript="Short.", summary=None, key_points=["Only one bullet."],
        links_mentioned=[], ai_insights=None,
    )
    assert out.exists()


check("full report with a 6-item bullet list", pdf_full_report_with_bullets)
check("transcript-only report", pdf_transcribe_report)
check("report with empty/None optional sections", pdf_single_bullet_and_empty_fields)

print("\n2. Word export")


def docx_full_report():
    from services import export_docx

    out = export_docx.build_full_report_docx(
        transcript=LONG_TEXT, summary="A summary.", key_points=MANY_BULLETS,
        dates_mentioned=["March 15th"], links_mentioned=["example.com"],
        notable_terms=["Atomic Habits"], ai_insights="Insight.",
    )
    assert out.exists() and out.stat().st_size > 1000


def docx_transcript_only():
    from services import export_docx

    out = export_docx.build_transcribe_docx(LONG_TEXT)
    assert out.exists() and out.stat().st_size > 1000


check("full report .docx", docx_full_report)
check("transcript-only .docx", docx_transcript_only)

print("\n3. Image export")


def image_summary_card():
    from services import export_image

    out = export_image.build_summary_image(
        title="Audio Summary",
        summary="A summary of the recording that is long enough to wrap onto several lines "
        "when rendered onto the card at the configured width.",
        key_points=MANY_BULLETS,
    )
    assert out.exists() and out.stat().st_size > 1000


check("summary card .jpg", image_summary_card)

print("\n4. One failing export must not sink the whole job")


def failing_export_is_contained():
    import worker

    warnings = []

    def explode():
        raise RuntimeError("simulated rendering failure")

    result = worker._safe_export("PDF", explode, warnings)
    assert result is None, "a failed export should return None, not raise"
    assert warnings and "simulated rendering failure" in warnings[0], (
        "the failure reason should be recorded as a user-visible warning"
    )


check("a crashing export returns None and records a warning", failing_export_is_contained)

print("\n5. Local (free) analysis works on English")


def local_analysis_english():
    from services.local_analysis import analyze_transcript_local

    text = (
        "Welcome back everyone. Today we discuss productivity. The best book is Atomic Habits "
        "by James Clear. Our next meeting is March 15th. Visit example.com."
    )
    r = analyze_transcript_local(text, summary_words=20, include_key_points=True, include_highlights=True)
    assert r["summary"].strip(), "summary came back empty"
    assert "example.com" in r["links_mentioned"], r["links_mentioned"]
    assert r["dates_mentioned"], "no date found"
    assert "James Clear" in r["notable_terms"], r["notable_terms"]


check("summary, dates, links and names from an English transcript", local_analysis_english)

print("\n6. Smart punctuation must never crash the core-font PDF path")


def em_dash_in_ai_insights_used_to_crash_this():
    # The kind of string that shipped and crashed real jobs: an em dash inside AI-written text,
    # rendered with the built-in PDF font.
    from services import pdf_report

    note = "AI insights need an AI model \u2014 and this server is running without one."
    out = pdf_report.build_full_report_pdf(
        transcript="Some transcript text.", summary="A summary.", key_points=["A point."],
        links_mentioned=[], ai_insights=note,
    )
    assert out.exists()


def curly_quotes_and_ellipsis_also_used_to_crash():
    from services import pdf_report

    tricky = "She said \u201chello\u2026\u201d and it\u2019s a great \u2013 test."
    out = pdf_report.build_full_report_pdf(
        transcript=tricky, summary=tricky, key_points=[tricky], links_mentioned=[], ai_insights=tricky,
    )
    assert out.exists()


def emoji_becomes_a_placeholder_not_a_crash():
    from services import pdf_report

    out = pdf_report.build_full_report_pdf(
        transcript="Great call \U0001F600 thanks", summary=None, key_points=[],
        links_mentioned=[], ai_insights=None,
    )
    assert out.exists()


check("an em dash in AI text renders (was a real crash)", em_dash_in_ai_insights_used_to_crash_this)
check("curly quotes / ellipsis / en-dash render", curly_quotes_and_ellipsis_also_used_to_crash)
check("an emoji in the transcript doesn't crash the PDF", emoji_becomes_a_placeholder_not_a_crash)

print("\n7. The API: English only, and the export endpoint can't crash with a non-JSON error")


def export_endpoint_wraps_rendering_errors():
    """
    main.py needs FastAPI to import, which a bare sandbox may not have — so this checks the
    source for the safety net that stops a rendering failure from reaching the client as a
    raw, unhandled 500 (which broke the frontend with "Unexpected token 'I'... is not valid
    JSON", since it isn't a JSON body at all).
    """
    main_src = Path(__file__).with_name("main.py").read_text()
    assert "async def create_export" in main_src
    export_fn = main_src.split("async def create_export", 1)[1].split("\n\n\n@app.get", 1)[0]
    assert "except Exception as exc:" in export_fn, "no catch-all around the export-building calls"
    assert "raise HTTPException(500" in export_fn, "failures must still come back as a clean HTTPException"


def api_has_no_language_options():
    import re

    main_src = Path(__file__).with_name("main.py").read_text()
    assert "/api/languages" not in main_src, "the language list endpoint should be gone"
    for forbidden in ("source_language", "target_language", "output_language", "translation", "romaniz"):
        assert forbidden not in main_src, f"main.py still mentions {forbidden!r}"
    # the form fields of the job endpoints
    assert not re.search(r"language\s*:\s*str\s*=\s*Form", main_src), "an endpoint still accepts a language field"


def job_model_accepts_the_not_english_status():
    from models import JobResponse

    job = JobResponse(
        id="x", mode="full", status="not_english", created_at="t", updated_at="t",
        error="This audio sounds like Hindi, not English.", detected_language="Hindi",
    )
    assert job.status == "not_english" and "Hindi" in job.error


check("create_export catches rendering failures and returns clean JSON", export_endpoint_wraps_rendering_errors)
check("no language / translation parameters remain in the API", api_has_no_language_options)
check("the job response model carries the not_english status", job_model_accepts_the_not_english_status)

print("\n8. English only — other languages are refused, with a clear message")


def english_detection_accepts_both_spellings():
    from languages import is_english

    # local faster-whisper returns codes; OpenAI/Groq return names
    for ok in ("en", "EN", "english", "English", " english "):
        assert is_english(ok), ok
    for bad in ("hi", "hindi", "Hindi", "fr", "urdu", "", None, "unknown"):
        assert not is_english(bad), bad


def not_english_message_names_the_language_and_asks_for_english():
    from languages import language_name, not_english_message

    assert language_name("hi") == "Hindi" and language_name("hindi") == "Hindi"
    msg = not_english_message("hi")
    assert "Hindi" in msg and "English" in msg and "upload" in msg.lower(), msg


class _FakeHostedClient:
    """Stands in for the OpenAI/Groq client: returns whatever language it was told to."""

    def __init__(self, language):
        self.calls = []
        self.audio = type("A", (), {"transcriptions": self})()
        self._language = language

    def create(self, **kwargs):
        self.calls.append(kwargs)
        seg = type("S", (), {"start": 0.0, "end": 2.0, "text": " hello there "})()
        return type("R", (), {"text": " hello there ", "language": self._language, "segments": [seg]})()


def hosted_transcription_accepts_english_and_never_sends_a_language():
    from services import transcription

    fake = _FakeHostedClient("english")
    saved = transcription._client
    transcription._client = lambda: fake
    try:
        wav = Path(tempfile.mkdtemp()) / "a.wav"
        wav.write_bytes(b"RIFF")
        result = transcription.transcribe_audio(wav, "Infosys")
    finally:
        transcription._client = saved
    assert result.text == "hello there" and result.detected_language == "en"
    assert "language" not in fake.calls[0], "the language must be auto-detected, never pre-set"
    assert fake.calls[0]["prompt"] == "Infosys", "the names/terms hint should still reach Whisper"


def hosted_transcription_refuses_other_languages():
    from languages import NotEnglishAudio
    from services import transcription

    saved = transcription._client
    transcription._client = lambda: _FakeHostedClient("hindi")
    try:
        wav = Path(tempfile.mkdtemp()) / "a.wav"
        wav.write_bytes(b"RIFF")
        try:
            transcription.transcribe_audio(wav)
            raise AssertionError("Hindi audio should have been refused")
        except NotEnglishAudio as exc:
            assert "Hindi" in str(exc)
    finally:
        transcription._client = saved


def local_transcription_refuses_other_languages_before_transcribing():
    import sys as _sys
    import types
    from languages import NotEnglishAudio
    from services import local_transcription as lt

    iterated = []

    class FakeModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, path, **kwargs):
            assert kwargs["language"] is None, "language must be auto-detected"

            def gen():
                iterated.append(True)  # would mean we kept transcribing a non-English file
                yield type("S", (), {"start": 0, "end": 1, "text": "x"})()

            return gen(), type("I", (), {"language": "hi"})()

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = FakeModel
    saved_mod = _sys.modules.get("faster_whisper")
    saved = (lt._model, lt._cpu_fallback)
    _sys.modules["faster_whisper"] = fake
    try:
        lt._model, lt._cpu_fallback = None, False
        try:
            lt.transcribe_audio(Path("dummy.wav"))
            raise AssertionError("Hindi audio should have been refused")
        except NotEnglishAudio as exc:
            assert "Hindi" in str(exc)
        assert not iterated, "a non-English file must be refused BEFORE its segments are transcribed"
    finally:
        lt._model, lt._cpu_fallback = saved
        if saved_mod is None:
            _sys.modules.pop("faster_whisper", None)
        else:
            _sys.modules["faster_whisper"] = saved_mod


class _TempStorage:
    """Run a block against a throwaway job database so tests never touch real jobs."""

    def __enter__(self):
        from config import settings
        import jobstore

        self.settings, self.tmp = settings, tempfile.TemporaryDirectory()
        self.saved = settings.storage_dir
        settings.storage_dir = self.tmp.name
        jobstore.init_db()
        return jobstore

    def __exit__(self, *exc):
        self.settings.storage_dir = self.saved
        self.tmp.cleanup()


def worker_ends_the_job_with_not_english_status():
    import worker
    from languages import NotEnglishAudio

    with _TempStorage() as jobstore:
        audio = Path(tempfile.mkdtemp()) / "talk.wav"
        audio.write_bytes(b"RIFF")
        saved = worker._transcribe

        def refuse(*a, **k):
            raise NotEnglishAudio("hi")

        worker._transcribe = refuse
        try:
            for mode, run in (
                ("full", lambda jid: worker.process_full_job(
                    jid, audio, 70, True, True, True, False, False, False, False, None, None)),
                ("transcribe", lambda jid: worker.process_transcribe_job(
                    jid, audio, False, False, False, None)),
            ):
                audio.write_bytes(b"RIFF")
                job_id = jobstore.create_job(mode=mode, filename="talk.wav")
                run(job_id)
                job = jobstore.get_job(job_id)
                assert job["status"] == "not_english", (mode, job["status"])
                assert job["detected_language"] == "Hindi" and "English" in job["error"], job
                assert not job.get("transcript"), "nothing should be transcribed for non-English audio"
                assert not audio.exists(), "the uploaded audio must still be deleted"
        finally:
            worker._transcribe = saved


def worker_completes_english_jobs():
    import worker
    from config import settings
    from services.transcription import TranscriptionResult

    with _TempStorage() as jobstore:
        audio = Path(tempfile.mkdtemp()) / "talk.wav"
        audio.write_bytes(b"RIFF")
        saved = (worker._transcribe, settings.analysis_backend)
        text = "Welcome back everyone. Today we discuss productivity. Our next meeting is March 15th."
        worker._transcribe = lambda *a, **k: TranscriptionResult(
            text=text, detected_language="en", segments=[{"start": 0, "end": 5, "text": text}])
        settings.analysis_backend = "local"
        try:
            job_id = jobstore.create_job(mode="full", filename="talk.wav")
            worker.process_full_job(job_id, audio, 50, True, True, True, True, True, False, False, None, None)
            job = jobstore.get_job(job_id)
        finally:
            worker._transcribe, settings.analysis_backend = saved
        assert job["status"] == "done", job.get("error")
        assert job["detected_language"] == "en" and job["transcript"] == text
        assert job["summary"] and job["pdf_report_id"] and job["docx_report_id"], job


check("'en' and 'english' count as English; everything else doesn't", english_detection_accepts_both_spellings)
check("the message names the language and asks for English audio", not_english_message_names_the_language_and_asks_for_english)
check("hosted Whisper: English works, no language is ever pre-set", hosted_transcription_accepts_english_and_never_sends_a_language)
check("hosted Whisper: Hindi audio is refused", hosted_transcription_refuses_other_languages)
check("local Whisper: non-English is refused before transcribing", local_transcription_refuses_other_languages_before_transcribing)
check("worker: non-English audio -> job status 'not_english', file deleted", worker_ends_the_job_with_not_english_status)
check("worker: English audio -> finished job with downloads", worker_completes_english_jobs)

print("\n8b. AI insights: available through any OpenAI-compatible provider, and never cost the user their transcript")


def base_url_reaches_both_clients():
    from config import settings
    from services import analysis, transcription

    saved = (settings.openai_api_key, settings.openai_base_url)
    settings.openai_api_key = "test-key"
    try:
        settings.openai_base_url = "https://api.groq.com/openai/v1"
        for module in (transcription, analysis):
            assert str(module._client().base_url).startswith("https://api.groq.com/openai/v1"), module.__name__
        settings.openai_base_url = ""
        assert "api.openai.com" in str(analysis._client().base_url), "blank base URL must mean OpenAI itself"
    finally:
        settings.openai_api_key, settings.openai_base_url = saved


def model_label_names_the_real_provider():
    import worker
    from config import settings

    saved = (settings.transcription_backend, settings.openai_base_url, settings.transcribe_model)
    settings.transcription_backend, settings.transcribe_model = "openai", "whisper-large-v3-turbo"
    try:
        settings.openai_base_url = "https://api.groq.com/openai/v1"
        assert worker._transcription_model_label() == "whisper-large-v3-turbo (Groq)"
        settings.openai_base_url = ""
        assert worker._transcription_model_label().endswith("(OpenAI)")
    finally:
        settings.transcription_backend, settings.openai_base_url, settings.transcribe_model = saved


def ai_insights_pass_through_when_the_model_answers():
    import worker
    from config import settings
    from services import analysis

    saved = (settings.analysis_backend, analysis.analyze_transcript)
    settings.analysis_backend = "openai"
    analysis.analyze_transcript = lambda **k: {"summary": "S", "key_points": ["K"], "ai_insights": "Confident, upbeat tone."}
    try:
        warnings = []
        extras = worker._analyze("Some text.", 50, True, True, True, None, warnings)
    finally:
        settings.analysis_backend, analysis.analyze_transcript = saved
    assert extras["ai_insights"] == "Confident, upbeat tone." and not warnings


def provider_failure_falls_back_instead_of_losing_the_job():
    """A rate limit (429), bad key or outage must not throw away the transcript — and must not dump raw errors on the page."""
    import worker
    from config import settings
    from services import analysis

    def rate_limited(**k):
        raise RuntimeError("Error code: 429 - {'error': {'message': 'rate limit reached', 'code': 'rate_limit_exceeded'}}")

    saved = (settings.analysis_backend, analysis.analyze_transcript)
    settings.analysis_backend = "openai"
    analysis.analyze_transcript = rate_limited
    try:
        warnings = []
        text = "Welcome back everyone. Today we discuss productivity. Our next meeting is March 15th."
        extras = worker._analyze(text, 50, True, True, True, None, warnings)
    finally:
        settings.analysis_backend, analysis.analyze_transcript = saved
    assert extras["summary"].strip(), "a basic summary should still be produced"
    assert "ai_insights" not in extras, "no AI insights means no AI-insights section at all"
    assert len(warnings) == 1 and "couldn't be reached" in warnings[0], warnings
    assert "429" not in warnings[0] and "{" not in warnings[0], f"raw error text leaked into the note: {warnings[0]}"


def local_mode_has_no_ai_insights_and_no_noise():
    import worker
    from config import settings

    saved = settings.analysis_backend
    settings.analysis_backend = "local"
    try:
        warnings = []
        extras = worker._analyze("A short transcript. It has two sentences.", 50, True, True, True, None, warnings)
    finally:
        settings.analysis_backend = saved
    assert "ai_insights" not in extras and not warnings, (extras.keys(), warnings)


def an_empty_model_summary_is_filled_in_locally():
    import worker
    from config import settings
    from services import analysis

    saved = (settings.analysis_backend, analysis.analyze_transcript)
    settings.analysis_backend = "openai"
    analysis.analyze_transcript = lambda **k: {"summary": "", "key_points": ["K"], "ai_insights": ""}
    try:
        extras = worker._analyze("Welcome back. Today we discuss productivity. Thanks for listening.", 50, True, True, True, None, [])
    finally:
        settings.analysis_backend, analysis.analyze_transcript = saved
    assert extras["summary"].strip(), "an empty summary from the model should be replaced by the basic one"
    assert "ai_insights" not in extras, "an empty insights string must not become an empty section"


def ai_insights_availability_follows_the_configuration():
    import worker
    from config import settings

    saved = (settings.analysis_backend, settings.openai_api_key)
    try:
        settings.analysis_backend, settings.openai_api_key = "openai", "k"
        assert worker.ai_insights_available() is True
        settings.openai_api_key = ""
        assert worker.ai_insights_available() is False
        settings.analysis_backend, settings.openai_api_key = "local", "k"
        assert worker.ai_insights_available() is False
    finally:
        settings.analysis_backend, settings.openai_api_key = saved
    assert "ai_insights_available" in Path(__file__).with_name("main.py").read_text(), "/api/health must report it"


class _Err(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status_code = status


class _FakeLLM:
    """A stand-in chat client. `behaviour(kwargs)` returns JSON text or raises."""

    def __init__(self, behaviour, model_ids=()):
        self.calls = []
        self._behaviour = behaviour
        self.chat = type("C", (), {"completions": self})()
        ids = list(model_ids)
        self.models = type("M", (), {"list": lambda _s: type("L", (), {"data": [type("I", (), {"id": i})() for i in ids]})()})()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._behaviour(kwargs)
        message = type("Msg", (), {"content": text})()
        return type("R", (), {"choices": [type("Ch", (), {"message": message})()]})()


_GOOD_JSON = (
    '{"summary": "A short summary.", "key_points": ["One", "Two"], "dates_mentioned": [], '
    '"spoken_links": [], "notable_terms": [], "ai_insights": "Calm, informative tone."}'
)


def _run_analysis(fake, model="llama-3.3-70b-versatile"):
    from config import settings
    from services import analysis

    saved = (analysis._client, settings.text_model, settings.openai_base_url)
    analysis._client = lambda: fake
    settings.text_model, settings.openai_base_url = model, "https://api.example.test/v1"
    analysis._resolved_models.clear()
    try:
        return analysis.analyze_transcript("Some text to analyse.", 50, True, True, True)
    finally:
        analysis._client, settings.text_model, settings.openai_base_url = saved
        analysis._resolved_models.clear()


def retired_model_is_replaced_automatically():
    """
    The real failure: Groq retired llama-3.3-70b-versatile and every AI-insights call died with
    "model_not_found". The app must switch to a model the provider actually has.
    """
    def behaviour(kw):
        if kw["model"] == "llama-3.3-70b-versatile":
            raise _Err("Error code: 404 - {'error': {'code': 'model_not_found'}}", 404)
        return _GOOD_JSON

    fake = _FakeLLM(behaviour, model_ids=["whisper-large-v3", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "openai/gpt-oss-120b"])
    result = _run_analysis(fake)
    assert result["ai_insights"] == "Calm, informative tone.", result
    assert fake.calls[-1]["model"] == "openai/gpt-oss-120b", fake.calls[-1]["model"]
    assert all("whisper" not in c["model"] for c in fake.calls), "must never pick a speech model for chat"


def the_replacement_model_is_remembered():
    from config import settings
    from services import analysis

    def behaviour(kw):
        if kw["model"] == "gone-model":
            raise _Err("model_not_found", 404)
        return _GOOD_JSON

    fake = _FakeLLM(behaviour, model_ids=["openai/gpt-oss-20b"])
    saved = (analysis._client, settings.text_model, settings.openai_base_url)
    analysis._client = lambda: fake
    settings.text_model, settings.openai_base_url = "gone-model", "https://api.example.test/v1"
    analysis._resolved_models.clear()
    try:
        analysis.analyze_transcript("Text one.", 50, True, True, True)
        before = len(fake.calls)
        analysis.analyze_transcript("Text two.", 50, True, True, True)
        used = [c["model"] for c in fake.calls[before:]]
    finally:
        analysis._client, settings.text_model, settings.openai_base_url = saved
        analysis._resolved_models.clear()
    assert used and all(m == "openai/gpt-oss-20b" for m in used), f"should not retry the dead model each time: {used}"


def unsupported_parameters_step_down_but_rate_limits_do_not_retry():
    # a 400 on the richest request -> retried with simpler parameters and still works
    seen = []

    def picky(kw):
        seen.append(set(kw))
        if "extra_body" in kw or "response_format" in kw:
            raise _Err("400 unsupported parameter", 400)
        return _GOOD_JSON

    result = _run_analysis(_FakeLLM(picky), model="openai/gpt-oss-120b")
    assert result["summary"] == "A short summary." and len(seen) == 3, seen

    # a 429 must be raised immediately: retrying with different parameters can't fix a rate limit
    calls = []

    def limited(kw):
        calls.append(kw)
        raise _Err("429 rate limit", 429)

    try:
        _run_analysis(_FakeLLM(limited), model="openai/gpt-oss-120b")
        raise AssertionError("a 429 should have been raised")
    except _Err as exc:
        assert exc.status_code == 429 and len(calls) == 1, len(calls)


def model_replies_in_odd_shapes_are_still_understood():
    from services.analysis import _parse_json

    assert _parse_json('{"a": 1}') == {"a": 1}
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}, "fenced JSON"
    assert _parse_json('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}, "JSON with chatter around it"
    assert _parse_json("not json at all") == {} and _parse_json(None) == {} and _parse_json("[1, 2]") == {}


def notable_terms_skip_sentence_openers():
    from services.local_analysis import analyze_transcript_local

    text = (
        "And I'm going to talk about this today. But having said that, my English is plain and simple. "
        "The best book is Atomic Habits by James Clear. Visit Infosys or ask Rahul on WhatsApp."
    )
    terms = analyze_transcript_local(text, 50, True, True, language_code="en")["notable_terms"]
    assert "Atomic Habits" in terms and "James Clear" in terms and "Rahul" in terms, terms
    assert not any(t.startswith(("And", "But", "I'm")) for t in terms), f"sentence openers leaked in: {terms}"


check("OPENAI_BASE_URL reaches the transcription and analysis clients", base_url_reaches_both_clients)
check("the 'how this was made' line names the real provider", model_label_names_the_real_provider)
check("AI insights pass through unchanged when the model answers", ai_insights_pass_through_when_the_model_answers)
check("provider failure -> basic summary + ONE plain note (no raw error), job survives", provider_failure_falls_back_instead_of_losing_the_job)
check("local mode: no AI-insights section, no noise", local_mode_has_no_ai_insights_and_no_noise)
check("an empty model summary is replaced by the basic one", an_empty_model_summary_is_filled_in_locally)
check("AI insights are offered only when a model is configured (/api/health)", ai_insights_availability_follows_the_configuration)
check("a RETIRED model is replaced by one the provider has (the Groq 404)", retired_model_is_replaced_automatically)
check("the replacement is remembered, not re-tried every job", the_replacement_model_is_remembered)
check("unsupported parameters step down; a rate limit is not retried", unsupported_parameters_step_down_but_rate_limits_do_not_retry)
check("fenced / chatty model replies are still parsed", model_replies_in_odd_shapes_are_still_understood)
check("notable terms no longer include sentence openers like 'And I'm'", notable_terms_skip_sentence_openers)

print("\n9. A GPU-library mismatch must slow a job down, not fail it")


def cuda_library_error_falls_back_to_cpu():
    """
    Real failure seen on Colab: the page showed "Library libcublas.so.12 is
    not found or cannot be loaded" and nothing transcribed. faster-whisper's
    GPU path raised it (lazily, while reading segments). This fakes that
    library, raising the same message on the GPU model and working on CPU.
    """
    import sys
    import types
    from services import local_transcription as lt

    class Seg:
        start, end, text = 0.0, 1.5, " hello world "

    class Info:
        language = "en"

    class FakeModel:
        def __init__(self, name, device="auto", compute_type="auto"):
            self.name, self.device = name, device

        def transcribe(self, path, **kwargs):
            device = self.device

            def gen():
                if device != "cpu":
                    raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
                yield Seg()

            return gen(), Info()

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = FakeModel
    saved_module = sys.modules.get("faster_whisper")
    saved = (lt._model, lt._model_name, lt._cpu_fallback, lt.settings.local_whisper_model)
    sys.modules["faster_whisper"] = fake
    try:
        lt._model, lt._model_name, lt._cpu_fallback = None, None, False
        lt.settings.local_whisper_model = "large-v3"
        result = lt.transcribe_audio(Path("dummy.wav"))
        assert result.text == "hello world", result.text
        assert lt._cpu_fallback is True
        label = lt.active_model_label()
        assert "CPU fallback" in label and "large-v3" not in label, (
            f"label must name the model that really ran, not the configured one: {label}"
        )
        # an unrelated error must NOT be swallowed by the fallback
        class Boom(FakeModel):
            def transcribe(self, path, **kw):
                raise RuntimeError("something else entirely")

        fake.WhisperModel = Boom
        lt._model, lt._cpu_fallback = None, False
        try:
            lt.transcribe_audio(Path("dummy.wav"))
            raise AssertionError("an unrelated error should still propagate")
        except RuntimeError as exc:
            assert "something else" in str(exc)
    finally:
        lt._model, lt._model_name, lt._cpu_fallback, lt.settings.local_whisper_model = saved
        if saved_module is None:
            sys.modules.pop("faster_whisper", None)
        else:
            sys.modules["faster_whisper"] = saved_module


check("a libcublas/CUDA error retries on CPU instead of failing the job", cuda_library_error_falls_back_to_cpu)

print(
    "\nAll backend checks passed.\n"
    if failures == 0
    else f"\n{failures} check(s) FAILED — fix before shipping.\n"
)
sys.exit(1 if failures else 0)
