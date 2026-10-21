# Transcript Studio (English)

Upload or record **English** audio and get back a word-for-word transcript, plus (optionally)
a summary, key points, highlighted dates/links/names and **AI insights** — downloadable as PDF,
Word, or an image card.

* **English only.** If the audio is in another language, nothing is transcribed. The page says
  *"This audio sounds like Hindi, not English… please upload or record English audio"* and shows a
  **Back to the start** button.
* **Two tools, one start page.** *Audio to Text* (above) and *Text to Audio*: write, paste or upload text
  (PDF, Word, image), get a summary at the length you choose (30 / 50 / 70 / 100 / custom words), AI insights and
  highlights, and hear the whole text or its summary in **24 voices / accents** (8 Indian first, then US, UK,
  Australian, Canadian, Irish, South African, Japanese, Chinese). Every voice has a ▶ 10-second sample. Download the
  audio in any accents you tick (one MP3, or a ZIP), and the report as PDF, Word or an image.
* One server does everything: a FastAPI backend that also serves the web page (`frontend/`).
* **Add audio three ways:** browse, drag-and-drop, or **copy an audio file and press Ctrl+V (⌘V on Mac)** on the
  page — it is picked up automatically. You can also record straight from the microphone.

```
backend/    FastAPI app (main.py), job worker (worker.py), services/ (transcription, analysis, exports)
frontend/   index.html + app.js + styles.css   (plain HTML/JS, no build step)
Dockerfile, render.yaml     for deploying (Render)
run_on_colab.ipynb          run it in Google Colab
```

---

## 1. Choose how it transcribes (one-time setup)

| | **A. Groq (free, hosted)** ← best for a live site | **B. OpenAI (paid)** | **C. Local (no account)** |
|---|---|---|---|
| Transcript | Whisper on Groq | Whisper on OpenAI | Whisper on your own machine |
| AI insights | **Yes** (gpt-oss on Groq) | **Yes** (GPT) | **No** — nothing to write them |
| Cost | $0, with free-tier limits | per use | $0 |
| Works on Render free | **Yes** | Yes | **No** (not enough RAM) |
| Needs GPU / big RAM | No | No | Better with a GPU |

All three are just settings in `backend/.env` (copy `backend/.env.example` to `.env` — it has all
three ready to paste). **A** and **B** use the same code: a key plus, for Groq, `OPENAI_BASE_URL`.

**AI insights** are *written by a language model*, so they need Setup A or B. In local mode (or if the
AI service can't be reached) they are simply left out: the page hides the "AI insights" option when no
model is configured, and never shows error text in the results.

**Groq free-tier limits to know about** (checked October 2026; Groq can change them): audio files up to
25 MB, rate limits, and no uptime guarantee. Get a key at https://console.groq.com (no card needed).
Groq retires models from time to time (it retired `llama-3.3-70b-versatile` on 16 August 2026, which
made AI insights fail with a "model does not exist" error). The default is now `openai/gpt-oss-120b`,
and if the configured model ever disappears the app looks up one the provider still has and uses that.

---

## 2. Run it on your computer (VS Code)

1. Install **Python 3.10–3.12** and VS Code (with the Python extension).
2. Unzip, then **File → Open Folder →** `audio-text-studio`. Open a terminal (`Ctrl+` `` ` ``) and:
   ```
   cd backend
   python -m venv venv
   venv\Scripts\activate            # Mac/Linux: source venv/bin/activate
   pip install -r requirements.txt
   copy .env.example .env           # Mac/Linux: cp .env.example .env
   ```
3. Edit `.env`: keep Setup A and paste your Groq key into `OPENAI_API_KEY=`.
4. Start it:  `uvicorn main:app --reload --port 8000`
5. Open http://localhost:8000. Check http://localhost:8000/api/health shows `{"status":"ok"}`.
6. Try a 30-second English clip, then a non-English clip to see the "English audio only" screen.
   (If a phone shows a blank page on a temporary ngrok link, see "Troubleshooting" below.)

*Optional:* install **ffmpeg** to enable "Reduce background noise" (the option is skipped without it).
*For Setup C only:* `pip install faster-whisper "av<19"` and install ffmpeg.

## 3. Run it in Google Colab

Open `run_on_colab.ipynb` in Colab and run the sections top to bottom. In section 4 you can paste a
free Groq key (recommended: fast, no GPU needed, AI insights on) or leave it blank for fully-local mode.

---

## 4. Going live on Render

**What you'll have:** a public link like `https://transcript-studio.onrender.com` that anyone can open.

**Before you start:** a free **GitHub** account, a free **Render** account (render.com), and a free
**Groq API key** (console.groq.com).

1. **Put the project on GitHub.** Create a new *private* repository, then from the project folder:
   ```
   git init
   git add .
   git commit -m "Transcript Studio"
   git branch -M main
   git remote add origin https://github.com/YOUR-NAME/transcript-studio.git
   git push -u origin main
   ```
   (Or use GitHub's "Upload files" button.) The included `.gitignore` keeps `.env` out — **never
   upload a real key.** Check on github.com that `backend/.env` is *not* there.
2. **Render → New + → Blueprint →** connect GitHub → pick the repo. Render reads `render.yaml`.
3. **Paste your Groq key** into `OPENAI_API_KEY` when asked (also fill in `ACCESS_KEY` and keep `DAILY_JOB_LIMIT` before sharing the link — see 4f; a blank
   `ACCESS_KEY` means anyone with the link can use your quota). Click **Apply**.
4. **Wait for the first build** (about 5–10 minutes). When it says *Live*, open the URL Render shows.
5. **Check it:** `/api/health` shows ok; upload a short English clip; upload a non-English clip and
   confirm you get the "English audio only" screen with the back button.

**To update the site later:** `git push` again — Render redeploys automatically.
**To change settings** (a different model, a new key): Render dashboard → your service → *Environment*.

### What the free tier means (checked October 2026)
* **Sleeps after 15 minutes without visitors.** The next visit takes about a minute to wake up.
* **Small machine** (512 MB RAM, 0.1 CPU) — fine, because Groq does the heavy work; it could never run Whisper itself.
* **Files don't persist.** History and generated downloads disappear when the service sleeps or
  redeploys, so **download results right away.** To keep them, move the service to a paid instance
  with a persistent disk (Render's cheapest paid web service is $7/month and doesn't sleep).
* The 750 free instance-hours a month cover one always-awake service; don't set up "keep-alive" pingers.

### Why not Vercel?
Vercel is excellent for websites but a poor fit for *this* app: its serverless functions cap request
bodies at **4.5 MB** (audio files are far bigger, so uploads fail), run for limited time, and keep
no state between requests — while this app uploads audio, then works on it in the background and
keeps the job in a database. Render (or Railway / Fly.io) runs it as one always-on container, which
is what it needs. (A split setup — page on Vercel, backend on Render — works but only adds moving parts.)

---

## 4b. Text to Audio setup

`pip install -r backend/requirements.txt` installs everything (`edge-tts` = the free Microsoft voices, `gTTS` =
Google backup, `pypdf`, `pypdfium2`, `pytesseract`). No key is needed for voices. Two extras:

* **Reading text from images / scanned PDFs** needs the Tesseract program: Windows — installer from
  <https://github.com/UB-Mannheim/tesseract/wiki> (tick "add to PATH"); Mac — `brew install tesseract`;
  Linux/Colab — `apt install tesseract-ocr` (the Dockerfile and the Colab notebook already do this).
  Typed/pasted text, Word files and normal PDFs work without it.
* **Voices need internet** (they are generated online). Voice samples and finished audio are cached in
  `storage/`, so each is made only once.
* **About the accents:** India 1-2, US, UK, Australia, Canada, Ireland and South Africa are real English voices.
  India 3-8 (Hindi/Tamil/Telugu voices), Japan and China are native-language voices reading English, so the
  accent is authentic but some English words sound heavier. Edit `backend/services/tts_voices.py` to swap, add or
  rename voices. If Microsoft's service is blocked on your host, `TTS_ENGINE=auto` falls back to Google voices for
  the English accents (Japan/China have no backup).

## 4c. Getting more accurate transcripts

1. Keep `TRANSCRIBE_MODEL=whisper-large-v3` (now the default; the `-turbo` one is faster but misses more words).
2. Fill **Names & terms to expect** with the tricky words (`Edunet Foundation, AICTE, BiLSTM, GARCH`). The model
   is told to spell them that way.
3. Leave **Reduce background noise** and **Smart spelling fix** ticked (now the default). The fix lists every
   word it changed under the transcript and refuses to apply anything that looks like a rewrite.
4. Record close to the mic, one speaker at a time, no music; use **Edit** to correct anything left, then
   **Re-run summary**.
5. Running locally instead of Groq? Use `LOCAL_WHISPER_MODEL=medium` or `large-v3`, not `small`.

## 4d. Reading along, speed, remembered voice

* The speaker icon on the Text to Audio results **pauses and resumes** (the small ■ stops it); the **0.75× – 1.5×**
  box changes the speed, even mid-sentence. Your speed is remembered.
* The sentence being read is **highlighted** as it plays. The voice service gives no exact word timings, so the
  position is estimated from sentence length: it stays close, but may drift by a moment on unusual text.
* **Remember my voice for next time** (ticked by default, on the options page) pre-selects your accent on your next visit.
  It is stored in that browser only.
* **Summary + whole text (one MP3)** in the audio downloads reads "Summary…" then "Full text…" in one file per accent.

## 4e. Speaker labels (Speaker 1 / Speaker 2)

Tick **Label who is speaking** on the Audio to Text options page to get the transcript as turns
(`Speaker 1: …`, `Speaker 2: …`); the same text goes into the PDF / Word / image. Whisper itself can't tell voices
apart, so this uses a second model (pyannote). It is off until you set it up:

1. `pip install pyannote.audio torch` (large download; needs a few GB of RAM, much faster on a GPU).
2. Make a free Hugging Face account, create a *read* token, and accept the terms on
   <https://huggingface.co/pyannote/speaker-diarization-3.1> (and `pyannote/segmentation-3.0`).
3. In `.env`: `ENABLE_DIARIZATION=true` and `HUGGINGFACE_TOKEN=hf_...`, then restart.

Until then the checkbox is greyed out with a note. **Not for Render's free plan** (too little memory); it works on
your own computer or on Colab (use the GPU runtime). Speakers are numbered in the order they first speak, and
editing the transcript afterwards replaces the labelled version with plain text.

## 4f. Sharing publicly: sign-in and limits

Before you post the link anywhere, set these (in `.env`, or Render's Environment tab):

* `ACCESS_KEY` — turns on sign-in. Best is **a key per person**: `ravi=k7Hq2xPz,priya=Vb83nLmQ`. Each person types their
  key once; the page then shows their name and "3 of 20 jobs used today" with a **Sign out** button. To cut someone
  off, delete just their entry and restart.
* `DAILY_JOB_LIMIT` — the most jobs one person can start per 24 hours (`20` is a sensible start). With sign-in on it is
  counted per key; with it off, per IP address. This is what actually protects your Groq/OpenAI quota.
* Ten wrong keys in a row from one address pause that address for 10 minutes.
* `RATE_LIMIT_PER_MINUTE` (already there) slows anyone hammering the buttons. `TRUST_PROXY=true` (default) makes
  these limits use each visitor's real address when you are behind Render / ngrok / Colab.
* This is a shared-secret scheme: fine for friends, a class or a small team. For anything sensitive or paid, put real
  accounts in front (Google/GitHub sign-in).
* Text to Audio voices are free, but every job still costs a little server time; the daily limit covers those too.

## 5. Troubleshooting

* **"Couldn't create the audio…"** The server can't reach the voice service. Check internet, that `edge-tts` is
  installed (`pip install -U edge-tts` — Microsoft changes things now and then), or set `TTS_ENGINE=gtts`.

* **Blank white page on a phone, using a Colab/ngrok link.** The page no longer waits for web fonts and shows
  an error banner if its script fails, so a *completely* blank page means the phone never got the page
  at all. Likely causes: the Colab session ended; the phone is on a network that blocks `ngrok` addresses
  (some mobile carriers and Wi-Fi networks do); or ngrok's free "Visit Site" warning page didn't load in
  the app you opened the link from (open it in Chrome/Safari instead). Quick test: open `<your link>/api/health`
  on the phone. If that is blank too, it's the network or the session, not the app. A Render deployment (below)
  gives a normal, stable `onrender.com` address and avoids all of this.
* **"AI insights" missing.** Check the key and `ANALYSIS_BACKEND=openai` in your settings; the server log shows
  the real reason when the AI service fails.

## 6. Tests

```
cd backend && python test_backend.py      # exports, English-only gate, AI insights fallback, GPU fallback
cd backend && python test_text_to_audio.py  # voice list, audio cache/ZIP, file reading, spelling-fix safety, summary length
node frontend/test_frontend.js            # page wiring, English-only UI, paste, blank-page guards
```

## 7. Known limits

* **Language detection is automatic and occasionally wrong** on very short, noisy or heavily
  accented English; if a real English clip is refused, try again with a longer or clearer sample.
* Speaker labels (diarization) are off by default and need extra setup (`ENABLE_DIARIZATION`).
* PDF/Word/image downloads are English text only (emoji and unusual symbols become `?` in the PDF).
* `backend/services/local_analysis.py` still contains word lists for a few other languages from an
  earlier version; they are never used because everything is English.
