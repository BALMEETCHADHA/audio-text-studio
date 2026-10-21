"""
Text -> speech.

Engines (settings.tts_engine):
  "auto" (default)  Microsoft neural voices through the free `edge-tts` package; if that fails
                    (blocked network, library problem) and the voice has a Google equivalent,
                    Google's voice through `gTTS` is used instead.
  "edge" / "gtts"   force one engine.

Long text is cut into pieces at sentence ends, spoken piece by piece and joined into one MP3.
Finished audio is cached on disk by (voice, text), so pressing the speaker again — or downloading
the same accent twice — costs nothing.
"""
import asyncio
import hashlib
import io
import logging
import re
import threading
import uuid
import zipfile
from pathlib import Path

from config import settings
from services import tts_voices

_log = logging.getLogger(__name__)

_CHUNK_CHARS = 2800
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")


class TTSError(RuntimeError):
    """A plain-language reason the audio couldn't be made (shown to the person as-is)."""


def is_available() -> bool:
    engine = settings.tts_engine
    try:
        import edge_tts  # noqa: F401
        if engine in ("auto", "edge"):
            return True
    except ImportError:
        pass
    try:
        import gtts  # noqa: F401
        return engine in ("auto", "gtts")
    except ImportError:
        return False


# ---------- text preparation ----------
def clean_for_speech(text: str) -> str:
    """Strip control characters and markdown marks that would be read out loud ('asterisk')."""
    text = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", " ", text or "")
    text = re.sub(r"[`*_#>|~^]+", " ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str, limit: int = _CHUNK_CHARS) -> list[str]:
    """Pack sentences into pieces of at most `limit` characters (a single huge sentence is split by words)."""
    pieces: list[str] = []
    for sentence in (s.strip() for s in _SENTENCE_RE.split(text)):
        if not sentence:
            continue
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        current = ""
        for word in sentence.split():
            if current and len(current) + 1 + len(word) > limit:
                pieces.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            pieces.append(current)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > limit:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


# ---------- engines ----------
async def _edge_chunk(chunk: str, voice_name: str) -> bytes:
    import edge_tts

    audio = bytearray()
    async for message in edge_tts.Communicate(chunk, voice_name).stream():
        if message.get("type") == "audio":
            audio += message["data"]
    if not audio:
        raise TTSError("The voice service returned no audio.")
    return bytes(audio)


async def _edge_all(chunks: list[str], voice_name: str) -> list[bytes]:
    gate = asyncio.Semaphore(3)

    async def one(chunk: str) -> bytes:
        async with gate:
            last: Exception | None = None
            for attempt in range(3):
                try:
                    return await _edge_chunk(chunk, voice_name)
                except Exception as exc:  # noqa: BLE001 — retried, then reported
                    last = exc
                    await asyncio.sleep(0.8 * (attempt + 1))
            raise last  # type: ignore[misc]

    return list(await asyncio.gather(*(one(c) for c in chunks)))


def _run_async(coro_fn, *args):
    """Run a coroutine to completion from sync code, even if this thread already has an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_fn(*args))
    box: dict = {}

    def runner():
        try:
            box["value"] = asyncio.run(coro_fn(*args))
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def _gtts_all(chunks: list[str], lang: str, tld: str) -> list[bytes]:
    from gtts import gTTS

    parts = []
    for chunk in chunks:
        buf = io.BytesIO()
        gTTS(text=chunk, lang=lang, tld=tld).write_to_fp(buf)
        parts.append(buf.getvalue())
    return parts


def synthesize(text: str, voice_id: str) -> bytes:
    """Speak `text` in the given voice and return MP3 bytes. Raises TTSError with a readable reason."""
    try:
        voice = tts_voices.get_voice(voice_id)
    except KeyError as exc:
        raise TTSError("That voice isn't available.") from exc

    text = clean_for_speech(text)
    if not text:
        raise TTSError("There is no text to read aloud.")
    chunks = split_text(text)

    problems: list[str] = []
    engine = settings.tts_engine

    if engine in ("auto", "edge"):
        try:
            return b"".join(_run_async(_edge_all, chunks, voice.edge_voice))
        except ImportError:
            problems.append("the 'edge-tts' package is not installed")
        except Exception as exc:  # noqa: BLE001
            _log.warning("edge-tts failed for %s: %s", voice.id, exc)
            problems.append(f"the Microsoft voice service failed ({exc})")

    if engine in ("auto", "gtts") and voice.gtts:
        try:
            return b"".join(_gtts_all(chunks, *voice.gtts))
        except ImportError:
            problems.append("the 'gTTS' package is not installed")
        except Exception as exc:  # noqa: BLE001
            _log.warning("gTTS failed for %s: %s", voice.id, exc)
            problems.append(f"the Google voice service failed ({exc})")
    elif engine in ("auto", "gtts") and not voice.gtts:
        problems.append("this accent has no backup voice service")

    raise TTSError(
        "Couldn't create the audio: " + "; ".join(problems or ["no voice service is configured"])
        + ". Check that the server can reach the internet and that 'edge-tts' is installed."
    )


# ---------- files ----------
def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def speech_path(text: str, voice_id: str) -> Path:
    """Where the finished MP3 for this text + voice lives (reports/, so /api/download/<stem> serves it)."""
    key = hashlib.sha256(f"{voice_id}\0{clean_for_speech(text)}".encode("utf-8")).hexdigest()[:40]
    return settings.storage_path / "reports" / f"{key}.mp3"


def synthesize_to_file(text: str, voice_id: str) -> Path:
    path = speech_path(text, voice_id)
    if path.exists() and path.stat().st_size > 0:
        return path
    _write_atomic(path, synthesize(text, voice_id))
    return path


def synthesize_combined_to_file(texts: list[str], voice_id: str) -> Path:
    """Several texts spoken one after another in one voice, as ONE MP3 (summary first, then the full text)."""
    path = speech_path("\x01COMBINED\x01" + "\x02".join(texts), voice_id)
    if path.exists() and path.stat().st_size > 0:
        return path
    parts = [synthesize_to_file(text, voice_id).read_bytes() for text in texts]
    _write_atomic(path, b"".join(parts))  # same format and settings for every part, so joining the bytes is safe
    return path


def preview_path(voice_id: str) -> Path:
    """The ~10 second sample for one voice (made once, then served from disk). KeyError if unknown."""
    tts_voices.get_voice(voice_id)
    folder = settings.storage_path / "previews"
    folder.mkdir(exist_ok=True)
    path = folder / f"{voice_id}.mp3"
    if not (path.exists() and path.stat().st_size > 0):
        _write_atomic(path, synthesize(tts_voices.PREVIEW_SENTENCE, voice_id))
    return path


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "audio"


def build_audio_bundle(text: "str | list[str]", voice_ids: list[str], label: str, progress=None) -> tuple[Path, str]:
    """
    One MP3 per chosen voice. A single voice returns that MP3; several are packed into one ZIP.
    `text` may be a list: the pieces are then spoken one after another inside each MP3.
    Returns (path, "mp3" | "zip"). `progress(done, total)` is called after each voice.
    """
    texts = [text] if isinstance(text, str) else list(text)
    files: list[tuple[str, Path]] = []
    for index, voice_id in enumerate(voice_ids, start=1):
        voice = tts_voices.get_voice(voice_id)
        made = synthesize_to_file(texts[0], voice_id) if len(texts) == 1 else synthesize_combined_to_file(texts, voice_id)
        files.append((f"{_safe_name(label)}-{_safe_name(tts_voices.display_name(voice))}.mp3", made))
        if progress:
            progress(index, len(voice_ids))

    if len(files) == 1:
        return files[0][1], "mp3"

    out = settings.storage_path / "reports" / f"{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:  # MP3 is already compressed
        for name, path in files:
            zf.write(path, arcname=name)
    return out, "zip"
