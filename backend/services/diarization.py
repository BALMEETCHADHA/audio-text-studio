"""
Speaker identification ("voice identification" in the product spec).

Important limitation: OpenAI's Whisper API transcribes speech but does not
tell you WHO is speaking. Real speaker diarization needs a separate model
that listens to the audio's voice characteristics. This module wraps
pyannote.audio for that, entirely optional:

- If ENABLE_DIARIZATION=false (the default), this is skipped and the
  frontend simply won't show speaker labels.
- If you want it: `pip install pyannote.audio torch`, get a (free)
  Hugging Face token, accept the model terms at
  https://huggingface.co/pyannote/speaker-diarization-3.1, set
  ENABLE_DIARIZATION=true and HUGGINGFACE_TOKEN in your .env.

Diarization runs locally on your machine/server (no extra per-minute API
cost), but the first run downloads model weights and needs a decent CPU
(a GPU makes it much faster).
"""
from pathlib import Path

from config import settings

_pipeline = None


def diarization_available() -> bool:
    return settings.enable_diarization and bool(settings.huggingface_token)


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pyannote.audio import Pipeline  # imported lazily: optional dependency

        name = "pyannote/speaker-diarization-3.1"
        try:  # pyannote.audio 4.x renamed the argument
            _pipeline = Pipeline.from_pretrained(name, token=settings.huggingface_token)
        except TypeError:
            _pipeline = Pipeline.from_pretrained(name, use_auth_token=settings.huggingface_token)
    return _pipeline


def label_speakers(file_path: Path, segments: list[dict]) -> list[dict]:
    """
    Given Whisper's transcript segments ([{start, end, text}]), attaches a
    "speaker" label to each one by asking pyannote who was talking during
    that time window. If diarization isn't enabled/available, returns the
    segments unchanged (no "speaker" key).
    """
    if not diarization_available():
        return segments

    pipeline = _get_pipeline()
    output = pipeline(str(file_path))
    # pyannote 4.x wraps the result; 3.x returns the annotation directly
    diarization = getattr(output, "speaker_diarization", output)

    # Build a flat list of (start, end, speaker_label) from pyannote's output
    turns = [
        (turn.start, turn.end, f"Speaker {speaker.split('_')[-1]}")
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]

    def speaker_for(start: float, end: float) -> str | None:
        mid = (start + end) / 2
        for t_start, t_end, label in turns:
            if t_start <= mid <= t_end:
                return label
        return None

    labeled = []
    for seg in segments:
        labeled.append({**seg, "speaker": speaker_for(seg["start"], seg["end"])})
    return labeled


def speaker_transcript(segments: list[dict]) -> str | None:
    """
    "Speaker 1: ...\n\nSpeaker 2: ..." — consecutive segments by the same person are merged into one
    turn, and speakers are numbered 1, 2, 3 in the order they first speak. None if nobody was labelled.
    """
    if not any(seg.get("speaker") for seg in segments):
        return None
    numbers: dict[str, int] = {}
    turns: list[list] = []  # [label, [text, ...]]
    last = None
    for seg in segments:
        raw = seg.get("speaker") or last or "unknown"
        last = raw
        numbers.setdefault(raw, len(numbers) + 1)
        label = f"Speaker {numbers[raw]}"
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if turns and turns[-1][0] == label:
            turns[-1][1].append(text)
        else:
            turns.append([label, [text]])
    return "\n\n".join(f"{label}: {' '.join(parts)}" for label, parts in turns) or None
