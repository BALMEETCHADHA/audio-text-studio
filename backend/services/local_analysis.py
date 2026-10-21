"""
Summary/key-points/highlights with no OpenAI account needed. Set
ANALYSIS_BACKEND=local in .env to use this instead of GPT.

This is intentionally simple — word-frequency extractive summarization and
regex/heuristic entity spotting, no machine learning model, no external
calls. It is noticeably less capable than the GPT-based version in
services/analysis.py:
- The "summary" is built from sentences pulled verbatim out of the
  transcript (picked by importance), not freshly written prose.
- "Notable terms" (book/course names, etc.) relies on capitalization for
  scripts that have it (Latin, Cyrillic, Greek...); Devanagari, Gurmukhi,
  and Arabic/Urdu script have no concept of capital letters, so for those
  a different, weaker heuristic is used instead — see _notable_terms().
- There is no AI-insights output in local mode — that specifically
  requires a language model's judgment, which is the one thing this
  module deliberately doesn't try to fake.

Language coverage: tokenization, stopwords and date-word matching are
tuned for English, Hindi, Punjabi, Urdu, French, and Spanish — the
languages this project's own testing has actually covered. Anything else
falls back to English stopwords/dates, which will under-filter (foreign
function words won't be recognized as "noise") but won't crash or produce
nothing, since word-splitting itself (see _WORD_RE) works for any script.

Good enough to make the app fully usable with zero API cost; switch back
to ANALYSIS_BACKEND=openai whenever you want the sharper, language-general
version.
"""
import re
import unicodedata
from collections import Counter

# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------
# Python's \w (Unicode-aware by default in Python 3) works correctly for
# most scripts — verified for Arabic/Urdu, French and Spanish — but
# actually BREAKS Devanagari and Gurmukhi: it splits a word apart at every
# vowel sign/matra (combining mark), e.g. "कैसे" becomes "क", "स" with the
# vowel signs silently dropped. Those two scripts get explicit Unicode
# block ranges instead (Devanagari/Gurmukhi/Arabic ranges), with the
# Devanagari danda/double-danda (। ॥ — sentence-ending punctuation, not
# letters) carved back out so it doesn't glue onto the preceding word.
# Latin gets accented letters (À-ÿ) added so French/Spanish don't fracture
# at é/ñ/ó/etc. the same way.
_WORD_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ']+"       # Latin, incl. accented (en, fr, es, ...)
    r"|[\u0900-\u0963\u0966-\u097F]+"  # Devanagari (hi, mr, ne) minus danda
    r"|[\u0A00-\u0A7F]+"         # Gurmukhi (pa)
    r"|\w+",                      # everything else \w handles correctly (ur, ar, bn, ta, ...)
    re.UNICODE,
)

# Scripts with no case distinction — the capitalized-run heuristic for
# "notable terms" fundamentally cannot work here (see _notable_terms()).
_NO_CASE_LANGS = {"hi", "mr", "ne", "pa", "ur", "ar", "fa", "bn", "ta", "te", "kn", "ml", "th", "he"}

_SENTENCE_RE = re.compile(r"(?<=[.!?\u0964\u0965])\s+")

# ---------------------------------------------------------------------------
# Stopwords — common function words (pronouns, articles/postpositions,
# conjunctions, auxiliary verbs) filtered out of word-frequency scoring so
# they don't drown out actual content words. Each list is representative,
# not exhaustive — enough to meaningfully change which sentences score
# highest, same ambition level as the original English-only list.
# ---------------------------------------------------------------------------
_STOPWORDS_BY_LANG: dict[str, set[str]] = {
    "en": set(
        "a an the this that these those is are was were be been being have has had "
        "do does did will would shall should may might must can could i you he she it "
        "we they me him her us them my your his its our their and or but if so because "
        "as of in on at by for with about against between into through during before "
        "after above below to from up down out over under again further then once here "
        "there when where why how all any both each few more most other some such no "
        "nor not only own same than too very s t just don now".split()
    ),
    "hi": set(
        "है हैं था थे थी हो होना और या पर लेकिन तो भी ही से में को का की के कि जो यह "
        "वह ये वो इस उस इन उन हम तुम आप मैं मुझे हमें तुम्हें आपको उसे इसे अपना अपनी "
        "अपने क्या कौन कहाँ कब क्यों कैसे नहीं न मत जी ना एक दो सब कुछ कोई यहाँ वहाँ "
        "अभी फिर बहुत बस सकता सकती सकते रहा रही रहे गया गई गए दिया दी दिए वाला वाली वाले".split()
    ),
    "pa": set(
        "ਹੈ ਹਨ ਸੀ ਸਨ ਹੋ ਹੋਣਾ ਅਤੇ ਜਾਂ ਪਰ ਤੇ ਵੀ ਹੀ ਤੋਂ ਵਿੱਚ ਨੂੰ ਦਾ ਦੀ ਦੇ ਕਿ ਜੋ ਇਹ ਉਹ "
        "ਇਹਨਾਂ ਉਹਨਾਂ ਅਸੀਂ ਤੁਸੀਂ ਤੁਹਾਨੂੰ ਮੈਂ ਮੈਨੂੰ ਸਾਨੂੰ ਆਪਣਾ ਆਪਣੀ ਆਪਣੇ ਕੀ ਕੌਣ ਕਿੱਥੇ "
        "ਕਦੋਂ ਕਿਉਂ ਕਿਵੇਂ ਨਹੀਂ ਨਾ ਜੀ ਇੱਕ ਦੋ ਸਭ ਕੁਝ ਕੋਈ ਇੱਥੇ ਉੱਥੇ ਹੁਣ ਫਿਰ ਬਹੁਤ ਬੱਸ".split()
    ),
    "ur": set(
        "ہے ہیں تھا تھے تھی ہو اور یا پر لیکن تو بھی ہی سے میں کو کا کی کے کہ جو یہ "
        "وہ اس ان ہم تم آپ مجھے ہمیں تمہیں اسے اپنا اپنی اپنے کیا کون کہاں کب کیوں "
        "کیسے نہیں نہ ایک دو سب کچھ کوئی یہاں وہاں ابھی پھر بہت".split()
    ),
    "fr": set(
        "le la les un une des de du et ou mais donc car ni que qui quoi dont où ce cet "
        "cette ces il elle ils elles on nous vous je tu me te se lui leur mon ma mes "
        "ton ta tes son sa ses notre votre leurs à au aux dans sur sous avec sans pour "
        "par entre vers chez est sont était étaient être avoir ai as a avons avez ont "
        "pas ne plus très bien comme si alors aussi tout tous toute toutes".split()
    ),
    "es": set(
        "el la los las un una unos unas de del y o pero porque que quien cual donde "
        "este esta estos estas ese esa esos esas él ella ellos ellas nosotros vosotros "
        "yo tú usted me te se le les mi mis tu tus su sus nuestro nuestra a al en con "
        "sin para por entre hacia es son era eran ser estar soy eres somos sois no más "
        "muy bien como si también todo todos toda todas".split()
    ),
}

_URL_RE = re.compile(
    r"\b((?:https?://|www\.)[^\s,]+|[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|dev|ai)(?:/[^\s,]*)?)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Dates — numeric formats (DD/MM/YYYY, YYYY-MM-DD) are language-agnostic
# and always checked; month/day NAMES are language-specific and looked up
# per detected language, falling back to English if unlisted.
# ---------------------------------------------------------------------------
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")

_MONTHS_BY_LANG = {
    "en": "January February March April May June July August September October November December".split(),
    "hi": "जनवरी फरवरी फ़रवरी मार्च अप्रैल मई जून जुलाई अगस्त सितंबर सितम्बर अक्टूबर नवंबर नवम्बर दिसंबर दिसम्बर".split(),
    "pa": "ਜਨਵਰੀ ਫ਼ਰਵਰੀ ਮਾਰਚ ਅਪ੍ਰੈਲ ਮਈ ਜੂਨ ਜੁਲਾਈ ਅਗਸਤ ਸਤੰਬਰ ਅਕਤੂਬਰ ਨਵੰਬਰ ਦਸੰਬਰ".split(),
    "ur": "جنوری فروری مارچ اپریل مئی جون جولائی اگست ستمبر اکتوبر نومبر دسمبر".split(),
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
}
_DAYS_BY_LANG = {
    "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(),
    "hi": "सोमवार मंगलवार बुधवार गुरुवार वीरवार शुक्रवार शनिवार रविवार".split(),
    "pa": "ਸੋਮਵਾਰ ਮੰਗਲਵਾਰ ਬੁੱਧਵਾਰ ਵੀਰਵਾਰ ਸ਼ੁੱਕਰਵਾਰ ਸ਼ਨੀਵਾਰ ਐਤਵਾਰ".split(),
    "ur": "پیر منگل بدھ جمعرات جمعہ ہفتہ اتوار".split(),
    "fr": "lundi mardi mercredi jeudi vendredi samedi dimanche".split(),
    "es": "lunes martes miércoles jueves viernes sábado domingo".split(),
}

_NUM_RE = r"\d{1,2}(?:st|nd|rd|th)?"

# A connector word some languages place between a day number and the
# month name ("15 DE marzo", not just "15 marzo") — optional per language;
# omitted entirely for languages that don't use one.
_DATE_CONNECTOR_BY_LANG = {"es": "de"}


def _date_word_re(language_code: str) -> re.Pattern:
    months = _MONTHS_BY_LANG.get(language_code, _MONTHS_BY_LANG["en"])
    days = _DAYS_BY_LANG.get(language_code, _DAYS_BY_LANG["en"])
    month_alt = "|".join(re.escape(m) for m in months)
    day_alt = "|".join(re.escape(d) for d in days)
    connector = _DATE_CONNECTOR_BY_LANG.get(language_code)
    connector_part = rf"(?:{re.escape(connector)}\s+)?" if connector else ""
    pattern = (
        rf"\b((?:{_NUM_RE}\s+{connector_part})?(?:{month_alt})(?:\s+{connector_part}{_NUM_RE})?(?:,?\s+\d{{4}})?"
        rf"|\b(?:{day_alt})\b)"
    )
    return re.compile(pattern, re.IGNORECASE)


# A run of 2+ capitalized words (skips a lone capitalized word right after
# a period, which is almost always just sentence-start capitalization).
# Only meaningful for scripts that actually have capitalization.
_PROPER_NOUN_RUN_RE = re.compile(r"\b(?:[A-Z][a-zA-Z']*\s+){1,3}[A-Z][a-zA-Z']*\b")


def _has_case(language_code: str) -> bool:
    return language_code not in _NO_CASE_LANGS


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _word_frequencies(sentences: list[str], stopwords: set[str]) -> Counter:
    freqs = Counter()
    for s in sentences:
        for w in _tokenize(s.lower()):
            if w not in stopwords and len(w) > 1:
                freqs[w] += 1
    return freqs


def _score_sentences(sentences: list[str], freqs: Counter, stopwords: set[str]) -> list[tuple[int, float, str]]:
    scored = []
    for i, s in enumerate(sentences):
        words = [w for w in _tokenize(s.lower()) if w not in stopwords]
        if not words:
            continue
        score = sum(freqs[w] for w in words) / len(words)
        scored.append((i, score, s))
    return scored


# Words that are capitalised only because they start a sentence (or are the pronoun "I"), never
# names. Without this, "And I'm going to..." was reported as a notable term.
_NOT_NAME_WORDS = set(
    "and but so well yes no okay ok hello hi hey thanks thank today now then also however because "
    "if when what this that these those there here it we you they he she my our your the a an as at "
    "in on of for to with by from let please welcome good great right sure maybe yeah like just "
    "actually basically anyway finally first second next one two three i i'm i've i'll i'd it's "
    "we're you're they're he's she's that's there's what's let's monday tuesday wednesday thursday "
    "friday saturday sunday january february march april may june july august september october "
    "november december english visit call email check see read watch join follow subscribe open go "
    "click use try ask tell send contact download get take make".split()
)


def _capitalized_terms(transcript: str, stopwords: set[str]) -> list[str]:
    """
    Names and titles in cased scripts, without an NLP model:
      - runs of 2+ capitalised words ("James Clear", "Atomic Habits"), after trimming sentence-opening
        and function words off the ends, and
      - single capitalised words that appear MID-sentence ("visit Infosys"), where capitalisation can't
        just be sentence-start.
    """
    def is_not_name(word: str) -> bool:
        w = word.lower()
        return w in _NOT_NAME_WORDS or w in stopwords

    counts: Counter = Counter()
    for m in _PROPER_NOUN_RUN_RE.finditer(transcript):
        words = m.group(0).split()
        while words and is_not_name(words[0]):
            words = words[1:]
        while words and is_not_name(words[-1]):
            words = words[:-1]
        if len(words) >= 2:
            counts[" ".join(words)] += 1

    multiword = " | ".join(counts)
    for m in re.finditer(r"(?<=[a-z,;:] )([A-Z][a-zA-Z]{2,})\b", transcript):
        word = m.group(1)
        if not is_not_name(word) and word not in multiword:
            counts[word] += 1

    return [term for term, _ in counts.most_common(10)]


def _notable_terms(transcript: str, language_code: str, stopwords: set[str]) -> list[str]:
    """
    Stand-in for "proper nouns" without a real NLP model.

    Cased scripts (Latin, Cyrillic, Greek, ...): a run of capitalized
    words — catches names, titles, places reasonably well.

    Uncased scripts (Devanagari, Gurmukhi, Urdu/Arabic script, and others
    in _NO_CASE_LANGS): capitalization doesn't exist, so that heuristic is
    skipped entirely rather than silently returning nothing useful. Instead:
    content words (not a stopword) that occur rarely (1-2 times) in the
    transcript — the intuition being that common function words and
    frequently-repeated topic words are rarely the specific name/term
    someone would want highlighted, while a word said once or twice and
    carrying real content more often is one. Weaker and noisier than the
    capitalization heuristic, but genuinely better than nothing — and
    honest about being a different (not equivalent) technique.
    """
    if _has_case(language_code):
        return _capitalized_terms(transcript, stopwords)

    counts = Counter(_tokenize(transcript))
    rare_content_words = [
        w for w, c in counts.items()
        if w.lower() not in stopwords and len(w) > 2 and 1 <= c <= 2
    ]
    # Keep transcript order (not frequency order — they're all rare) and
    # preserve the original casing/form as first seen.
    seen_lower = set()
    ordered = []
    for w in _tokenize(transcript):
        wl = w.lower()
        if w in rare_content_words and wl not in seen_lower:
            seen_lower.add(wl)
            ordered.append(w)
    return ordered[:10]


def analyze_transcript_local(
    transcript: str,
    summary_words: int,
    include_key_points: bool,
    include_highlights: bool,
    language_code: str = "en",
) -> dict:
    result: dict = {}
    sentences = _sentences(transcript)
    if not sentences:
        return {"summary": "", "key_points": [], "dates_mentioned": [], "notable_terms": [], "links_mentioned": []}

    stopwords = _STOPWORDS_BY_LANG.get(language_code, _STOPWORDS_BY_LANG["en"])
    freqs = _word_frequencies(sentences, stopwords)
    scored = _score_sentences(sentences, freqs, stopwords)
    ranked = sorted(scored, key=lambda t: t[1], reverse=True)

    if summary_words:
        picked = []
        word_count = 0
        for idx, _, s in sorted(ranked[: max(3, len(ranked) // 3)], key=lambda t: t[0]):
            picked.append(s)
            word_count += len(s.split())
            if word_count >= summary_words:
                break
        summary_text = " ".join(picked)
        words = summary_text.split()
        if len(words) > summary_words * 1.15:  # a long sentence can overshoot a short target
            summary_text = " ".join(words[:summary_words]).rstrip(",;:") + "…"
        result["summary"] = summary_text

    if include_key_points:
        top = ranked[:6]
        result["key_points"] = [s for _, _, s in sorted(top, key=lambda t: t[0])]

    if include_highlights:
        date_word_re = _date_word_re(language_code)
        dates = {m.group(0) for m in _NUMERIC_DATE_RE.finditer(transcript)}
        dates |= {m.group(0) for m in date_word_re.finditer(transcript)}
        result["dates_mentioned"] = sorted(dates)
        result["links_mentioned"] = sorted(set(m.group(0).rstrip(".,)") for m in _URL_RE.finditer(transcript)))
        result["notable_terms"] = _notable_terms(transcript, language_code, stopwords)

    return result
