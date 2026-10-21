from typing import Optional
from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None  # e.g. "Speaker 1" — only set when diarization ran


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str


class ExportRecord(BaseModel):
    format: str
    report_id: str
    created_at: str


class JobResponse(BaseModel):
    id: str
    mode: str
    # queued | processing | done | error | not_english
    # "not_english" = the audio was detected as another language; `error` holds the
    # plain-language message to show, `detected_language` the name of that language.
    status: str
    created_at: str
    updated_at: str
    filename: Optional[str] = None
    error: Optional[str] = None

    detected_language: Optional[str] = None
    transcript: Optional[str] = None
    segments: list[TranscriptSegment] = []
    summary: Optional[str] = None
    summary_word_target: Optional[int] = None
    key_points: list[str] = []
    dates_mentioned: list[str] = []
    links_mentioned: list[str] = []
    notable_terms: list[str] = []
    ai_insights: Optional[str] = None
    diarization_available: bool = False
    noise_reduction_applied: bool = False

    pdf_report_id: Optional[str] = None
    docx_report_id: Optional[str] = None
    image_report_id: Optional[str] = None
    exports: list[ExportRecord] = []
    warnings: list[str] = []

    # "How this was made" transparency, so a bad result is visibly traceable
    # to its cause instead of looking like an unexplained fluke.
    transcription_model: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    word_count: Optional[int] = None

    # Text -> Audio: the voice picked on the options page ("india-1"); for audio jobs, the
    # spelling fix: the transcript as first heard + the list of words it changed.
    voice_id: Optional[str] = None
    transcript_raw: Optional[str] = None
    corrections: list[dict] = []
    labeled_transcript: Optional[str] = None  # "Speaker 1: ..." version, only when speaker labels ran


class SpeechCreatedResponse(BaseModel):
    report_id: str


class BundleCreatedResponse(BaseModel):
    bundle_id: str


class BundleStatusResponse(BaseModel):
    status: str  # processing | done | error
    done: int = 0
    total: int = 0
    report_id: Optional[str] = None
    format: Optional[str] = None  # mp3 | zip
    error: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


class ExportCreatedResponse(BaseModel):
    report_id: str
    format: str
