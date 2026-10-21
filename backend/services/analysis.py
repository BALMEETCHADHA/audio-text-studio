"""
Everything that turns a raw transcript into the "Full Analysis" the user
asked for: a summary at a target word count, key points, and "highlights"
— dates, links, and notable terms (book/course names, products, proper
nouns worth calling out) mentioned in the audio — plus a short set of
AI-generated insights.

One JSON-mode call to the language model does summary + key points + highlights + insights
(cheaper, and keeps them consistent with each other). Link detection is
double-checked with a plain regex pass over the transcript for anything
already URL-shaped, on top of GPT's own reconstruction of links that were
spoken aloud ("visit example dot com slash pricing").

See services/local_analysis.py for the zero-API-cost equivalent used when
ANALYSIS_BACKEND=local.
"""
import json
import logging
import re

from openai import OpenAI

from config import settings

_URL_RE = re.compile(
    r"\b((?:https?://|www\.)[^\s,]+|[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|dev|ai)(?:/[^\s,]*)?)",
    re.IGNORECASE,
)


def _client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError(
            "No API key is set. Add OPENAI_API_KEY (a free Groq key works — see README) "
            "or set ANALYSIS_BACKEND=local to run without an API key."
        )
    kwargs = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)


_log = logging.getLogger(__name__)

# When the configured model is retired (Groq retired llama-3.3-70b-versatile on
# 16 Aug 2026, which silently broke every AI-insights call with a 404), pick a
# working chat model from the provider's own live model list instead of failing.
_PREFERRED_FALLBACKS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "gpt-4o-mini"]
_NOT_CHAT_MODELS = ("whisper", "tts", "guard", "embed", "orpheus", "playai", "moderation", "safeguard", "dall", "image", "transcribe")
_resolved_models: dict[tuple[str, str], str] = {}


def _status(exc: Exception):
    return getattr(exc, "status_code", None)


def _is_model_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return _status(exc) == 404 or "model_not_found" in msg or "does not exist" in msg or "decommissioned" in msg


def _pick_available_model(client: OpenAI, avoid: str) -> str:
    ids = [m.id for m in client.models.list().data]
    chat = [i for i in ids if i != avoid and not any(k in i.lower() for k in _NOT_CHAT_MODELS)]
    for preferred in _PREFERRED_FALLBACKS:
        if preferred in chat:
            return preferred
    if chat:
        return sorted(chat)[0]
    raise RuntimeError(f"The model {avoid!r} is unavailable and the provider lists no other chat model.")


def _complete(client: OpenAI, model: str, prompt: str):
    """
    One chat call, trying the richest request first and stepping down on a 400 (a parameter this
    provider/model doesn't accept). Rate limits, bad keys and missing models are raised right
    away — retrying them with different parameters can't help.
    """
    base = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    json_mode = {"response_format": {"type": "json_object"}}
    ladder = []
    if model.startswith("openai/gpt-oss"):
        # reasoning models: a low effort keeps this fast and cheap for a summarising task
        ladder.append({**json_mode, "extra_body": {"reasoning_effort": "low"}})
    ladder.append(json_mode)
    ladder.append({})  # last resort: plain text, parsed leniently below

    last_exc = None
    for extra in ladder:
        try:
            return client.chat.completions.create(**base, **extra)
        except Exception as exc:  # noqa: BLE001
            if _is_model_missing(exc) or _status(exc) in (401, 403, 429):
                raise
            last_exc = exc
    raise last_exc


def _parse_json(text) -> dict:
    """Models sometimes wrap JSON in ```fences``` or add a sentence around it."""
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    for candidate in (text, (re.search(r"\{.*\}", text, re.DOTALL) or [None])[0]):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            continue
    return {}


def _regex_links(transcript: str) -> list[str]:
    found = {m.group(0).rstrip(".,)") for m in _URL_RE.finditer(transcript)}
    return sorted(found)


def _run_json(client: OpenAI, prompt: str) -> dict:
    """Send one prompt, switching to a working model if the configured one was retired; parsed JSON back."""
    key = (settings.openai_base_url, settings.text_model)
    model = _resolved_models.get(key, settings.text_model)
    try:
        response = _complete(client, model, prompt)
    except Exception as exc:  # noqa: BLE001
        if not _is_model_missing(exc):
            raise
        replacement = _pick_available_model(client, avoid=model)
        _log.warning("Model %r is unavailable (%s); using %r instead.", model, exc, replacement)
        _resolved_models[key] = replacement
        response = _complete(client, replacement, prompt)
    return _parse_json(response.choices[0].message.content)


def run_json_prompt(prompt: str) -> dict:
    """Used by other services (the spelling fix): one JSON-answering call to the configured model."""
    return _run_json(_client(), prompt)


def analyze_transcript(
    transcript: str,
    summary_words: int,
    include_key_points: bool,
    include_highlights: bool,
    include_ai_insights: bool,
    context: str | None = None,
    source_kind: str = "audio",
) -> dict:
    """
    Returns a dict with whichever of these keys were requested:
    summary, key_points (list[str]), dates_mentioned (list[str]),
    links_mentioned (list[str]), notable_terms (list[str]), ai_insights

    source_kind: "audio" (a transcript of speech) or "text" (text the person typed/uploaded).
    """
    result: dict = {}
    client = _client()

    wanted = []
    if summary_words:
        wanted.append(
            f'"summary": a summary in close to {summary_words} words (do not go over {summary_words})'
        )
    if include_key_points:
        wanted.append('"key_points": a list of 5-8 short, concrete key points (strings)')
    if include_highlights:
        wanted.append(
            '"dates_mentioned": a list of any specific dates, days, deadlines or time '
            'references mentioned (strings, as spoken — e.g. "March 15th", "next Friday"). '
            "Empty list if none."
        )
        wanted.append(
            '"spoken_links": a list of any website addresses, links or URLs mentioned '
            "in speech, reconstructed into normal URL form (e.g. \"visit example dot "
            'com slash pricing" becomes "example.com/pricing"). Empty list if none.'
        )
        wanted.append(
            '"notable_terms": a list of specific named things worth calling out — book '
            "titles, course names, product names, tools, organizations, or people's names "
            "mentioned. Not generic nouns. Empty list if none."
        )
    if include_ai_insights:
        context_line = f"\nAdditional context from the user: {context}" if context else ""
        wanted.append(
            '"ai_insights": 2-4 sentences of AI-generated insight on the transcript '
            "- e.g. tone, notable claims worth double-checking, what kind of "
            "document/project this could feed into, or suggested next steps."
            + context_line
        )

    if not wanted:
        return result

    if source_kind == "text":
        intro = (
            "You are analyzing a piece of written English text (an article, report, notes, a "
            "document or a message). Write everything in English."
        )
        label = "Text"
    else:
        intro = (
            "You are analyzing a transcript of spoken English audio (a podcast, meeting, lecture, or "
            "recording). Write everything in English."
        )
        label = "Transcript"
    prompt = (
        intro
        + " Respond with a single JSON object with exactly these keys:\n"
        + "\n".join(f"- {w}" for w in wanted)
        + f"\n\n{label}:\n"
        + transcript
    )

    parsed = _run_json(client, prompt)

    if summary_words:
        result["summary"] = str(parsed.get("summary", "")).strip()
    if include_key_points:
        result["key_points"] = [str(p).strip() for p in parsed.get("key_points", []) if str(p).strip()]
    if include_highlights:
        result["dates_mentioned"] = [str(d).strip() for d in parsed.get("dates_mentioned", []) if str(d).strip()]
        spoken = [str(l).strip() for l in parsed.get("spoken_links", []) if str(l).strip()]
        result["links_mentioned"] = sorted(set(spoken) | set(_regex_links(transcript)))
        result["notable_terms"] = [str(t).strip() for t in parsed.get("notable_terms", []) if str(t).strip()]
    if include_ai_insights:
        result["ai_insights"] = str(parsed.get("ai_insights", "")).strip()

    return result
