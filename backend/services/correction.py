"""
"Smart spelling fix" for transcripts.

Speech-to-text models hear sounds, not spellings, so names, brands, acronyms and technical terms
come out phonetically ("Edinet Foundation" for "Edunet Foundation", "ECTE" for "AICTE"). This pass
gives the transcript, the person's list of expected terms and the optional "what is this for"
context to a language model and asks it to repair ONLY those misheard words.

It is deliberately conservative, because the transcript must stay word for word:
  * the model is told not to rephrase, add, remove or reorder anything;
  * every piece it returns is checked against the original — if the word count moves by more than
    a few words or the text differs too much, that piece is thrown away and the original is kept;
  * every change that was accepted is returned, so the page can show exactly what was fixed.
"""
import difflib
import logging
import re

from services import analysis

_log = logging.getLogger(__name__)

_CHUNK_WORDS = 800
_MAX_CHANGE_WORDS = 4  # a single replacement longer than this isn't a "spelling fix"


def _chunks(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current, count = [], [], 0
    for sentence in sentences:
        n = len(sentence.split())
        if current and count + n > _CHUNK_WORDS:
            chunks.append(" ".join(current))
            current, count = [], 0
        current.append(sentence)
        count += n
    if current:
        chunks.append(" ".join(current))
    return chunks


def accept_correction(original: str, corrected: str) -> bool:
    """True only if `corrected` is the same text with a few words repaired (never a rewrite)."""
    ow, cw = original.split(), corrected.split()
    if not ow or not cw:
        return False
    if abs(len(ow) - len(cw)) > max(3, int(len(ow) * 0.03)):
        return False
    touched = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ow, cw, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if (i2 - i1) > _MAX_CHANGE_WORDS or (j2 - j1) > _MAX_CHANGE_WORDS:
            return False  # a long stretch changed: that's rephrasing, not a spelling fix
        touched += max(i2 - i1, j2 - j1)
    return touched <= max(4, int(len(ow) * 0.12))


def list_changes(original: str, corrected: str) -> list[dict]:
    """[{'from': 'Edinet', 'to': 'Edunet'}, ...] for the small word swaps between the two texts."""
    ow, cw = original.split(), corrected.split()
    changes = []
    matcher = difflib.SequenceMatcher(None, ow, cw, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or (i2 - i1) > _MAX_CHANGE_WORDS or (j2 - j1) > _MAX_CHANGE_WORDS:
            continue
        before = " ".join(ow[i1:i2]).strip(".,;:!?\"'()")
        after = " ".join(cw[j1:j2]).strip(".,;:!?\"'()")
        if before and after and before != after:
            changes.append({"from": before, "to": after})
    return changes


def _prompt(chunk: str, vocabulary_hint: str | None, context: str | None) -> str:
    extra = ""
    if vocabulary_hint and vocabulary_hint.strip():
        extra += f"\nTerms the speaker is known to use (spell them exactly like this): {vocabulary_hint.strip()}"
    if context and context.strip():
        extra += f"\nWhat the recording is about: {context.strip()}"
    return (
        "You are a careful proofreader for an automatic speech-to-text transcript. The recognizer "
        "sometimes writes a name, brand, acronym or technical term the way it SOUNDS instead of how "
        "it is spelled (for example 'pie torch' for 'PyTorch').\n"
        "Fix ONLY words that are clearly misheard, using the surrounding context.\n"
        "Rules:\n"
        "- Keep every other word exactly as written. Do not rephrase, add, remove or reorder words.\n"
        "- Do not fix grammar, do not remove filler words, do not change punctuation or numbers.\n"
        "- If you are not sure a word is wrong, leave it.\n"
        "- If nothing is wrong, return the text unchanged."
        + extra
        + '\nRespond with one JSON object: {"corrected": "<the full text>"}.\n\nTranscript:\n'
        + chunk
    )


def correct_transcript(
    transcript: str, vocabulary_hint: str | None = None, context: str | None = None
) -> tuple[str, list[dict]]:
    """Returns (possibly repaired transcript, list of accepted changes). Never raises for model trouble."""
    if len(transcript.split()) < 8:
        return transcript, []

    fixed_parts: list[str] = []
    changes: list[dict] = []
    for chunk in _chunks(transcript):
        try:
            parsed = analysis.run_json_prompt(_prompt(chunk, vocabulary_hint, context))
            candidate = str(parsed.get("corrected", "")).strip()
        except Exception as exc:  # noqa: BLE001 — a failed fix must never cost the transcript
            _log.warning("Spelling fix skipped: %s", exc)
            return transcript, []
        if candidate and candidate != chunk and accept_correction(chunk, candidate):
            changes += list_changes(chunk, candidate)
            fixed_parts.append(candidate)
        else:
            fixed_parts.append(chunk)

    if not changes:
        return transcript, []

    seen, unique = set(), []
    for c in changes:
        key = (c["from"].lower(), c["to"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return " ".join(fixed_parts), unique[:40]
