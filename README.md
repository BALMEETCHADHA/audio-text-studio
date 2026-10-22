# AUDIO_TEXT_STUDIO — Transcript Studio

An end-to-end AI-assisted **speech and text studio** — turn English audio into an accurate word-for-word transcript with a summary, key points, AI insights and highlights, or turn any text (typed, pasted, PDF, Word or image) into natural speech in **24 voices and accents**. Built as a working FastAPI web app with sign-in, usage limits and one-click cloud deployment.

## Live Demo

**[Transcript Studio — Live App](https://transcript-studio-n534.onrender.com)**

> Hosted on Render's free plan: if nobody has used it for 15 minutes, the first visit takes about a minute to wake up. If sign-in is switched on, you will be asked for an access key once.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Key Features](#key-features)
3. [Technologies Used](#technologies-used)
4. [Models & Data Sources](#models--data-sources)
5. [System Architecture](#system-architecture)
6. [Repository Structure](#repository-structure)
7. [How to Run the Project](#how-to-run-the-project)
8. [Run & Test on Google Colab](#run--test-on-google-colab)
9. [Supported Inputs & Outputs](#supported-inputs--outputs)
10. [Sharing Publicly: Sign-in & Limits](#sharing-publicly-sign-in--limits)
11. [Limitations & Honest Notes](#limitations--honest-notes)
12. [Results](#results)
13. [Tests](#tests)
14. [Disclaimer](#disclaimer)
15. [License](#license)

---

## Project Overview

Transcript Studio was built as part of my internship at **Infosys**. It began as an audio transcriber and grew into a two-tool web application with one start page:

- **Audio to Text** — upload, drag-and-drop, paste or record English audio, and get back the word-for-word transcript, a summary at the length you choose, key points, AI insights and highlighted dates, links and names.
- **Text to Audio** — write, paste or upload text (PDF, Word, image), get the same summary, AI insights and highlights, and hear the whole text or just its summary read aloud in the accent you pick.

Everything can be downloaded as **PDF, Word, or an image** (and as **MP3 / ZIP** for audio). One FastAPI server does all the work and also serves the web page, so there is nothing else to run.

---

## Key Features

### Audio to Text
- **Word-for-Word Transcription** — Whisper (`whisper-large-v3`) with temperature 0 for the most literal, least "creative" output.
- **English-Only Gate** — audio in any other language is refused with a clear message and a "Back to the start" button, rather than producing a wrong transcript.
- **Smart Spelling Fix** — an AI proofreader repairs only clearly misheard names, brands, acronyms and technical terms (for example *Edinet* → *Edunet*). It never rewrites sentences, rejects anything that looks like a rewrite, and **lists every word it changed** under the transcript.
- **Names & Terms to Expect** — optional list of tricky words that the model is told to spell exactly.
- **Background Noise Reduction** — optional ffmpeg filter for hiss, hum and quiet recordings.
- **Speaker Labels (optional)** — "Speaker 1 / Speaker 2" turns for meetings and interviews using pyannote diarization (needs extra setup, see below).
- **Editable Transcript** — fix any word, then re-run the summary so it reflects the correction.
- **Four Ways to Add Audio** — browse, drag-and-drop, copy a file and press **Ctrl+V** anywhere on the page, or record straight from the microphone.

### Text to Audio
- **Flexible Text Input** — write or paste text (with a *Paste from clipboard* button), or upload a **PDF, Word (.docx) or image** (read with OCR); the extracted text is shown for checking and editing before you continue.
- **24 Voices / Accents** — **8 Indian voices first (4 female, 4 male)**, then US, UK, Australian, Canadian, Irish, South African, Japanese and Chinese accents.
- **10-Second Voice Samples** — every voice in the drop-down has its own ▶ button so you can hear it before choosing.
- **Speaker Icon with Accent Drop-down** — like Google Translate: press the speaker to hear the whole text, and again right under the **Summary** title to hear the summary, in any accent.
- **Pause / Resume and Speed Control** — 0.75×–1.5×, remembered between visits.
- **Karaoke-Style Highlighting** — the sentence being read lights up as it plays.
- **Remember My Voice** — your favourite accent is pre-selected next time.
- **Audio Downloads in Many Accents** — tick any accents (the one you chose is listed first and pre-ticked) for the whole text, the summary, or **summary + whole text in one MP3**. One accent downloads as MP3; several as a ZIP.

### Shared by Both Tools
- **One Summary-Length Drop-down** — 30 / 50 / 70 / 100 words, or **Custom** (10–500).
- **Results in a Fixed Order** — transcript (or whole text), summary, key points, AI insights, highlights, then downloads at the bottom.
- **Highlights** — dates, links and notable terms (books, courses, names, tools) are marked inside the text itself.
- **Downloads in English** — PDF, Word (.docx) and Image, created on demand.
- **History** — reopen earlier jobs and download them again.
- **Restart / Previous Page** buttons at the bottom of every results page.
- **Sign-in and Daily Limit** — a key per person, a per-person daily job cap, wrong-key lockout and real-IP rate limiting to protect the AI quota.
- **Mobile-Friendly** — responsive layout; a guard prevents a blank page if a script fails.

---

## Technologies Used

- **Python, FastAPI, Uvicorn** (backend and production server), **SQLite** (job history)
- **Whisper** via **Groq** (hosted, free tier) or OpenAI, or **faster-whisper** locally
- **Groq `openai/gpt-oss-120b`** for summaries, key points, highlights, insights and the spelling fix
- **edge-tts** (Microsoft neural voices, no API key) with **gTTS** (Google) as automatic backup
- **pyannote.audio** (optional speaker labels)
- **ffmpeg** (noise reduction), **Tesseract OCR** + **pytesseract**, **pypdf**, **pypdfium2**, **python-docx** (reading uploaded files)
- **fpdf2**, **python-docx**, **Pillow** (PDF, Word and image exports)
- **slowapi** (rate limiting), custom access-key auth
- **HTML, CSS, JavaScript** (plain, no build step)
- **Docker** and **Render** (deployment), **pyngrok** (Colab live link)

---

## Models & Data Sources

No dataset is needed to run the app. It uses pre-trained models:

| Job | Default | Alternatives |
|---|---|---|
| Speech-to-text | Whisper `whisper-large-v3` on **Groq** (free tier) | OpenAI Whisper, or local `faster-whisper` |
| Summary, insights, spelling fix | `openai/gpt-oss-120b` on **Groq** | OpenAI GPT models; none in fully-local mode |
| Text-to-speech | **edge-tts** Microsoft neural voices (free, no key) | **gTTS** Google voices (English accents) |
| Speaker labels | `pyannote/speaker-diarization-3.1` | off by default |

Three setups, all just settings in `backend/.env`:

| | A. Groq (free, hosted) | B. OpenAI (paid) | C. Local (no account) |
|---|---|---|---|
| Transcript | Whisper on Groq | Whisper on OpenAI | Whisper on your machine |
| AI insights | Yes | Yes | No |
| Cost | $0, free-tier limits | per use | $0 |
| Works on Render free | Yes | Yes | No (not enough RAM) |

---

## System Architecture

```
                         ┌─────────────── Audio to Text ───────────────┐
 audio (upload / paste / │  noise filter → Whisper → English check →   │
 microphone)  ──────────▶│  smart spelling fix → (speaker labels) →    │──┐
                         │  summary · key points · insights · highlights│  │
                         └──────────────────────────────────────────────┘  │   ┌──────────────┐
                                                                            ├──▶│ Results page │──▶ PDF · Word · Image
                         ┌─────────────── Text to Audio ───────────────┐  │   └──────┬───────┘
 text / PDF / Word /     │  OCR / file reading → summary · key points · │  │          │
 image  ────────────────▶│  insights · highlights                       │──┘          ▼
                         └──────────────────────────────────────────────┘      speaker icon ▶ 24 voices
                                                                               → MP3 / ZIP downloads
```

Jobs run as background tasks: the page uploads, receives a job id, and polls for progress. The finished job is stored in SQLite, so results can be reopened from **History**. Audio for Text to Audio is created **on demand** (when you press the speaker or download) and cached by voice + text, so each file is generated only once.

---

## Repository Structure

```
audio-text-studio/
├── backend/                         # FastAPI application
│   ├── main.py                      # Entry point & all web routes (also serves the frontend)
│   ├── worker.py                    # Background jobs: audio, transcribe-only, text-to-audio
│   ├── auth.py                      # Access keys, wrong-key lockout, real-IP detection
│   ├── config.py                    # All settings (read from .env)
│   ├── jobstore.py                  # SQLite job history + daily-limit counting
│   ├── models.py                    # API response models
│   ├── languages.py                 # English-only gate + transcription hint prompt
│   ├── requirements.txt             # Dependency list
│   ├── .env.example                 # Every setting, ready to copy
│   ├── test_backend.py              # Exports, English gate, fallbacks tests
│   ├── test_text_to_audio.py        # Voices, audio cache/ZIP, file reading, spelling-fix tests
│   └── services/
│       ├── transcription.py         # Whisper via Groq / OpenAI
│       ├── local_transcription.py   # Offline faster-whisper (optional)
│       ├── audio_preprocessing.py   # ffmpeg noise reduction
│       ├── correction.py            # Smart spelling fix with safety checks
│       ├── diarization.py           # Speaker labels (pyannote)
│       ├── analysis.py              # Summary, key points, highlights, AI insights
│       ├── local_analysis.py        # Offline fallback analysis
│       ├── text_extract.py          # Text from PDF / Word / image (OCR)
│       ├── tts_voices.py            # The 24-voice catalogue (edit to add/swap voices)
│       ├── tts.py                   # Text-to-speech, caching, MP3/ZIP bundles
│       ├── pdf_report.py            # PDF export
│       ├── export_docx.py           # Word export
│       └── export_image.py          # Image export
├── frontend/
│   ├── index.html                   # All pages (home, both tools, results, history)
│   ├── app.js                       # Page logic, voice picker, playback, downloads
│   ├── styles.css                   # Styling
│   ├── i18n.js                      # Page text
│   └── test_frontend.js             # Page wiring & behaviour tests
├── Dockerfile                       # Container (includes ffmpeg + Tesseract)
├── render.yaml                      # Render Blueprint (one-click deploy)
├── run_on_colab.ipynb               # One-click Colab runner
└── README.md
```

---

## How to Run the Project

### Prerequisites

- Python 3.10–3.12 and VS Code
- A free **Groq API key** from <https://console.groq.com> (no card needed)
- Optional: **ffmpeg** (noise reduction) and **Tesseract** (reading text from images / scanned PDFs)

### Steps to Run Locally

```bash
git clone https://github.com/BALMEETCHADHA/audio-text-studio.git
cd audio-text-studio/backend
python -m venv venv
venv\Scripts\activate            # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # Mac/Linux: cp .env.example .env
```

Edit `.env`: keep **Setup A** and paste your Groq key into `OPENAI_API_KEY=`. Then:

```bash
uvicorn main:app --reload --port 8000
```

Open <http://localhost:8000> and check <http://localhost:8000/api/health> shows `{"status":"ok"}`.

**Install Tesseract (for image / scanned-PDF input):** Windows — installer from <https://github.com/UB-Mannheim/tesseract/wiki> (tick "add to PATH"); Mac — `brew install tesseract`; Linux — `apt install tesseract-ocr`. Typed text, Word files and normal PDFs work without it.

### Deploy Your Own Live Link (Render)

1. Push this project to GitHub as real files (the `Dockerfile` and `render.yaml` must be at the top level of the repo).
2. Go to [render.com](https://render.com) → **New +** → **Blueprint** → connect the repo. Render reads `render.yaml`.
3. Fill in `OPENAI_API_KEY` (your Groq key) and `ACCESS_KEY` (see *Sharing Publicly* below).
4. Click **Deploy Blueprint**. After the first build (5–10 minutes) Render gives you a permanent `https://….onrender.com` link.
5. To update later: push to GitHub and Render redeploys automatically. Settings and keys live in Render → **Environment**, not in the code.

---

## Run & Test on Google Colab

This repo includes `run_on_colab.ipynb` for quick, no-setup testing:

1. Open it in Colab.
2. Run the install cell (it also installs ffmpeg and Tesseract).
3. Paste your free Groq key when asked (recommended), or leave it blank for fully-local mode.
4. Run the ngrok cell and paste your free authtoken.
5. Run the last cell — it prints a clickable public URL running the real app.

This link is temporary (only while the cell is running) — use the Render deployment for a permanent link.

---

## Supported Inputs & Outputs

| | Formats |
|---|---|
| **Audio input** | MP3, WAV, M4A, WEBM, OGG — upload, drag-and-drop, Ctrl+V paste, or microphone (English only, up to 25 MB on the hosted setup) |
| **Text input** | Typed / pasted text, PDF, Word (.docx), image (PNG / JPG), TXT — up to 30,000 characters |
| **Document output** | PDF, Word (.docx), Image — English |
| **Audio output** | MP3 (one accent) or ZIP of MP3s (several accents): whole text, summary, or summary + whole text |

---

## Sharing Publicly: Sign-in & Limits

Set these in `.env` (or Render's **Environment** tab) before posting the link anywhere:

- `ACCESS_KEY` — turns on sign-in. Best is **a key per person**: `ravi=k7Hq2xPz,priya=Vb83nLmQ`. The page then shows the person's name and a **Sign out** button.
- `DAILY_JOB_LIMIT` — most jobs one person can start in 24 hours (`0` = unlimited). Counted per key, or per IP address when sign-in is off.
- Ten wrong keys in a row pause that visitor for 10 minutes.
- `RATE_LIMIT_PER_MINUTE` slows anyone hammering the buttons; `TRUST_PROXY=true` makes the limits use each visitor's real address behind Render / ngrok / Colab.
- A blank `ACCESS_KEY` means **anyone with the link can use your AI quota**.

This is a shared-secret scheme — fine for friends, a class or a small team. For sensitive or paid use, put real accounts (Google / GitHub sign-in) in front.

---

## Limitations & Honest Notes

- **English only** — non-English audio is refused by design. Language detection is automatic and occasionally wrong on very short, noisy or heavily accented clips; try again with a longer or clearer sample.
- **Accents** — India 1–2, US, UK, Australia, Canada, Ireland and South Africa are real English voices. India 3–8 (Hindi/Tamil/Telugu voices), Japan and China are native-language voices reading English: the accent is authentic, but some English words sound heavier. Voices need internet; if Microsoft's service is blocked on a host, `TTS_ENGINE=gtts` switches to Google voices for the English accents.
- **Karaoke highlight is an estimate** — the voice service gives no word timings, so the position is estimated from sentence length and may drift slightly.
- **OCR is best-effort** — clear screenshots and photos work well; blurry or handwritten text does not.
- **Smart spelling fix is conservative** — it repairs misheard terms but may leave an unusual name unchanged; use **Edit** to correct anything left. Adding the name under *Names & terms to expect* is the most reliable fix.
- **Speaker labels** need `pyannote.audio` + `torch`, a Hugging Face token, and a few GB of RAM — not available on Render's free plan. The checkbox is greyed out until set up.
- **Free-plan hosting** — the service sleeps after 15 minutes idle, and job history and generated files are lost on restart or redeploy. Download results right away, or use a paid instance with a persistent disk.
- **Free-tier AI limits** — Groq's free tier has rate limits and no uptime guarantee; models are retired from time to time, so the app looks up a working replacement if the configured model disappears.
- **AI summaries and insights are generated by a language model** and can contain mistakes; check important details against the transcript.
- PDF/Word/image downloads are English text (emoji and unusual symbols may become `?` in the PDF).

---

## Results

For a typical English recording, the app returns:

- the **full transcript**, word for word, with dates, links and notable terms highlighted
- a **summary** at your chosen length, **key points** and **AI insights**
- a list of any **words the spelling fix corrected**
- a **PDF, Word or image** report, ready to download

For text, the app returns the same analysis plus **spoken audio** of the whole text or the summary in your chosen accent, downloadable in any combination of the 24 voices.

*(Add screenshots of the home page, the transcript results and the voice picker here.)*

---

## Tests

```bash
cd backend && python test_backend.py          # exports, English-only gate, AI-insights fallback, GPU fallback
cd backend && python test_text_to_audio.py    # voices, audio cache/ZIP, file reading, spelling-fix safety, summary length, keys & limits
node frontend/test_frontend.js                # page wiring, English-only UI, paste, playback, voice picker, blank-page guards
```

---

## Disclaimer

This project is for educational and research purposes. Transcripts, summaries, insights, spelling corrections and voice output are AI-generated and may contain errors — always check important content against the original. Do not upload confidential recordings or documents to a public deployment: audio and text are processed by third-party services (Groq / OpenAI for transcription and analysis, Microsoft / Google for voices).

---

## License

Educational project built during an internship at Infosys. Add a `LICENSE` file if you want to set reuse terms for others.
