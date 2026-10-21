"""
Optional audio clean-up pass, run before transcription when the user turns
on "Reduce background noise" in either mode's options. Uses ffmpeg (a
system binary, not a Python ML dependency) with a filter chain aimed
specifically at making speech more intelligible to a transcription model:

- highpass=f=100        — cuts low-frequency rumble/handling noise/hum
                           that carries no speech information.
- afftdn=nf=-25          — FFT-based noise reduction: estimates a steady
                           background noise floor (fans, hiss, hum) and
                           subtracts it.
- dynaudnorm=f=150:g=15  — dynamic normalization: evens out volume over
                           time so quiet words aren't lost next to loud
                           ones, without the pumping artifacts a simple
                           compressor can cause.
- loudnorm               — final loudness normalization to a consistent,
                           standard level.
- resampled to 16kHz mono — Whisper's native input rate; also shrinks the
                           file, which speeds up upload and transcription.

This is a real signal-processing step (not a placeholder) but it's not
magic: it helps most with steady background noise (fans, hiss, traffic
hum, room tone) and quiet/uneven speech. It won't rescue audio with heavy
overlapping speech, extreme clipping, or very short/sharp noises (a door
slam, a cough) — those need more specialized tools than a filter chain.
"""
import subprocess
import uuid
from pathlib import Path

_FILTER_CHAIN = "highpass=f=100,afftdn=nf=-25,dynaudnorm=f=150:g=15,loudnorm"


def is_ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def denoise_audio(input_path: Path) -> Path:
    """
    Runs the filter chain over `input_path` and returns the path to a new,
    cleaned-up WAV file alongside it. Raises RuntimeError if ffmpeg isn't
    installed or the process fails — callers should catch this and fall
    back to transcribing the original file rather than failing the job,
    exactly like the rest of this codebase treats translation as
    best-effort rather than mandatory.
    """
    output_path = input_path.parent / f"{input_path.stem}_denoised_{uuid.uuid4().hex[:8]}.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", _FILTER_CHAIN,
        "-ar", "16000",
        "-ac", "1",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg is not installed — noise reduction needs it on the system PATH "
            "(apt install ffmpeg / brew install ffmpeg)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed while cleaning up the audio: {exc.stderr.decode(errors='ignore')[-500:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Noise reduction timed out on this file.") from exc

    return output_path
