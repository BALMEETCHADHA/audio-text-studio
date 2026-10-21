"""
English-only support helpers.

This app only transcribes English audio. Whisper (hosted or local) detects the
spoken language by itself, and when it isn't English the job stops with a clear
"please provide English audio" message instead of producing a poor transcript
(see worker.py).

Two spellings of "English" can come back from Whisper and both are accepted:
  - the local faster-whisper model returns a code:        "en"
  - OpenAI's / Groq's hosted API returns the language name: "english"
"""

_MAX_PROMPT_CHARS = 700  # Whisper only looks at roughly the last 224 tokens of a prompt

# Used only to NAME the detected language in the "English only" message.
_NAMES = {
    "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "as": "Assamese", "az": "Azerbaijani",
    "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian", "bn": "Bengali", "bo": "Tibetan",
    "br": "Breton", "bs": "Bosnian", "ca": "Catalan", "cs": "Czech", "cy": "Welsh",
    "da": "Danish", "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "fi": "Finnish", "fo": "Faroese",
    "fr": "French", "gl": "Galician", "gu": "Gujarati", "ha": "Hausa", "haw": "Hawaiian",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "ht": "Haitian Creole", "hu": "Hungarian",
    "hy": "Armenian", "id": "Indonesian", "is": "Icelandic", "it": "Italian", "ja": "Japanese",
    "jw": "Javanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer", "kn": "Kannada",
    "ko": "Korean", "la": "Latin", "lb": "Luxembourgish", "ln": "Lingala", "lo": "Lao",
    "lt": "Lithuanian", "lv": "Latvian", "mg": "Malagasy", "mi": "Maori", "mk": "Macedonian",
    "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese",
    "my": "Burmese", "ne": "Nepali", "nl": "Dutch", "nn": "Norwegian Nynorsk", "no": "Norwegian",
    "oc": "Occitan", "pa": "Punjabi", "pl": "Polish", "ps": "Pashto", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sa": "Sanskrit", "sd": "Sindhi", "si": "Sinhala",
    "sk": "Slovak", "sl": "Slovenian", "sn": "Shona", "so": "Somali", "sq": "Albanian",
    "sr": "Serbian", "su": "Sundanese", "sv": "Swedish", "sw": "Swahili", "ta": "Tamil",
    "te": "Telugu", "tg": "Tajik", "th": "Thai", "tk": "Turkmen", "tl": "Tagalog",
    "tr": "Turkish", "tt": "Tatar", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek",
    "vi": "Vietnamese", "yi": "Yiddish", "yo": "Yoruba", "yue": "Cantonese", "zh": "Chinese",
}


class NotEnglishAudio(Exception):
    """Raised as soon as the spoken language is known to be something other than English."""

    def __init__(self, language: str):
        self.language = language
        super().__init__(not_english_message(language))


def is_english(language: str | None) -> bool:
    """True for "en" / "english" (any case). An unknown/missing value is NOT treated as English
    by this helper; callers decide what to do when detection gave nothing."""
    return (language or "").strip().lower() in {"en", "english"}


def language_name(language: str | None) -> str:
    """Readable name for a Whisper language code ("hi" -> "Hindi"); names pass through capitalised."""
    value = (language or "").strip()
    if not value:
        return "an unknown language"
    return _NAMES.get(value.lower(), value.capitalize())


def not_english_message(language: str | None) -> str:
    return (
        f"This audio sounds like {language_name(language)}, not English. "
        "This tool only works with English audio — please go back and upload or record English audio."
    )


def build_transcription_prompt(vocabulary_hint: str | None) -> str | None:
    """
    Names/terms the audio is expected to contain (e.g. "Infosys, WhatsApp") passed
    to Whisper as its prompt: it makes those spellings far more likely than a
    phonetically-similar guess. Returns None when there is nothing to add.
    """
    if vocabulary_hint and vocabulary_hint.strip():
        return vocabulary_hint.strip()[:_MAX_PROMPT_CHARS]
    return None
