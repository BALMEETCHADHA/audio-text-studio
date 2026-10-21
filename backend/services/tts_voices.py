"""
The list of narration voices ("accents") offered on the Text -> Audio pages.

Edit this file to add, remove or rename voices — nothing else needs to change. Each voice has:

  id          short slug used by the web page and the API ("india-1")
  label       what the person sees ("India 1")
  gender      "Female" / "Male"
  edge_voice  the Microsoft neural voice used by the edge-tts engine
  gtts        (language, tld) for the Google fallback engine, or None if it has no matching accent

Honest note about accents: Microsoft has real English voices for the US, UK, Australia, Canada,
Ireland, South Africa and India (en-IN, 2 voices). For the other six Indian voices, and for Japan
and China, there is no English-language voice with that accent, so the voice is a native Hindi /
Tamil / Telugu / Japanese / Mandarin neural voice reading the English text. That gives a genuine
local accent, but pronunciation of some English words can sound heavier than a native English voice.

Indian voices come first and are numbered "India 1" ... "India 8" (4 female, 4 male), as requested.
"""
from dataclasses import dataclass

# The sentence played by the little ▶ button next to each voice (about 10 seconds when spoken).
PREVIEW_SENTENCE = (
    "Hello! This is a sample of my voice. I can read your full text, or its summary, "
    "in this accent. Choose me if you like how I sound."
)


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    group: str
    gender: str
    edge_voice: str
    gtts: tuple[str, str] | None = None  # (lang, tld)

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "group": self.group, "gender": self.gender}


_IN = ("en", "co.in")
_US = ("en", "com")
_UK = ("en", "co.uk")
_AU = ("en", "com.au")
_CA = ("en", "ca")
_IE = ("en", "ie")
_ZA = ("en", "co.za")

VOICES: list[Voice] = [
    # --- India: 8 voices, 4 female + 4 male, always at the top ---
    Voice("india-1", "India 1", "India", "Female", "en-IN-NeerjaNeural", _IN),
    Voice("india-2", "India 2", "India", "Male", "en-IN-PrabhatNeural", _IN),
    Voice("india-3", "India 3", "India", "Female", "hi-IN-SwaraNeural", _IN),
    Voice("india-4", "India 4", "India", "Male", "hi-IN-MadhurNeural", _IN),
    Voice("india-5", "India 5", "India", "Female", "ta-IN-PallaviNeural", _IN),
    Voice("india-6", "India 6", "India", "Male", "ta-IN-ValluvarNeural", _IN),
    Voice("india-7", "India 7", "India", "Female", "te-IN-ShrutiNeural", _IN),
    Voice("india-8", "India 8", "India", "Male", "te-IN-MohanNeural", _IN),
    # --- English-speaking countries ---
    Voice("us-1", "US English 1", "United States", "Female", "en-US-JennyNeural", _US),
    Voice("us-2", "US English 2", "United States", "Male", "en-US-GuyNeural", _US),
    Voice("uk-1", "UK English 1", "United Kingdom", "Female", "en-GB-SoniaNeural", _UK),
    Voice("uk-2", "UK English 2", "United Kingdom", "Male", "en-GB-RyanNeural", _UK),
    Voice("australia-1", "Australian English 1", "Australia", "Female", "en-AU-NatashaNeural", _AU),
    Voice("australia-2", "Australian English 2", "Australia", "Male", "en-AU-WilliamNeural", _AU),
    Voice("canada-1", "Canadian English 1", "Canada", "Female", "en-CA-ClaraNeural", _CA),
    Voice("canada-2", "Canadian English 2", "Canada", "Male", "en-CA-LiamNeural", _CA),
    Voice("ireland-1", "Irish English 1", "Ireland", "Female", "en-IE-EmilyNeural", _IE),
    Voice("ireland-2", "Irish English 2", "Ireland", "Male", "en-IE-ConnorNeural", _IE),
    Voice("south-africa-1", "South African English 1", "South Africa", "Female", "en-ZA-LeahNeural", _ZA),
    Voice("south-africa-2", "South African English 2", "South Africa", "Male", "en-ZA-LukeNeural", _ZA),
    # --- Japanese and Chinese accents (native voices reading English) ---
    Voice("japan-1", "Japanese accent 1", "Japan", "Female", "ja-JP-NanamiNeural", None),
    Voice("japan-2", "Japanese accent 2", "Japan", "Male", "ja-JP-KeitaNeural", None),
    Voice("china-1", "Chinese accent 1", "China", "Female", "zh-CN-XiaoxiaoNeural", None),
    Voice("china-2", "Chinese accent 2", "China", "Male", "zh-CN-YunxiNeural", None),
]

DEFAULT_VOICE_ID = "india-1"

_BY_ID = {v.id: v for v in VOICES}


def has_voice(voice_id: str | None) -> bool:
    return voice_id in _BY_ID


def get_voice(voice_id: str) -> Voice:
    """Raises KeyError for an unknown id (callers turn that into a 400/404)."""
    return _BY_ID[voice_id]


def display_name(voice: Voice) -> str:
    """'India 1 (Female)' — used for file names inside the audio zip and for headings."""
    return f"{voice.label} ({voice.gender})"
