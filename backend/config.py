"""
Central place for all configuration. Everything is read from environment
variables (via a .env file in development) so no secrets ever live in code.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # One key + (optional) base URL powers BOTH transcription and AI insights
    # when the backends below are "openai". Leave OPENAI_BASE_URL blank for
    # OpenAI itself. Any OpenAI-compatible service works by setting its URL —
    # for example Groq (free tier): OPENAI_BASE_URL=https://api.groq.com/openai/v1
    # with its key in OPENAI_API_KEY (see README "Going live").
    openai_api_key: str = ""
    openai_base_url: str = ""
    transcribe_model: str = "whisper-1"
    text_model: str = "gpt-4o-mini"
    max_upload_mb: int = 100
    storage_dir: str = "./storage"
    enable_diarization: bool = False
    huggingface_token: str = ""
    allowed_origins: str = "http://localhost:5500"

    # Auth: if access_key is left blank, the API is open to anyone who can
    # reach it (fine for local-only testing, not fine once it's public).
    # One key, or several: "ravi=key1,priya=key2" (see auth.py).
    access_key: str = ""
    # Most transcription / text jobs one person (one key, or one IP when the lock is off) may start per 24 hours.
    # 0 = unlimited. Set this (e.g. 20) before sharing a public link.
    daily_job_limit: int = 0
    # Read the visitor's real address from X-Forwarded-For (right on Render / ngrok / Colab).
    trust_proxy: bool = True

    # Rate limiting: max transcribe requests per minute, per IP address.
    rate_limit_per_minute: int = 10

    # "openai" (default, needs OPENAI_API_KEY, best quality) or "local"
    # (runs faster-whisper on this machine, no key/billing needed, slower
    # and no GPT-powered summary/insights — see worker.py + README).
    transcription_backend: str = "openai"
    analysis_backend: str = "openai"
    local_whisper_model: str = "small"  # tiny/base/small/medium/large-v3 — see local_transcription.py

    # Text -> Audio. "auto" tries Microsoft's free neural voices (edge-tts) first and falls back to
    # Google's (gTTS) for the accents it can do; "edge" / "gtts" force one of them.
    tts_engine: str = "auto"
    # Longest text the Text -> Audio page accepts (characters). ~30,000 is roughly 5,000 words.
    max_text_chars: int = 30000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "uploads").mkdir(exist_ok=True)
        (p / "reports").mkdir(exist_ok=True)
        return p


settings = Settings()
