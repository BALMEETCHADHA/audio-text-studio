// Empty string = "call the same origin this page was loaded from". That's
// correct as soon as FastAPI serves this frontend itself (see main.py),
// which is also what makes the Colab/ngrok setup a single tunnel.
// If you ever serve the frontend from somewhere else than the backend,
// set this to that backend's full URL instead, e.g. "http://localhost:8000".
const API_BASE = "";

// ---------- small helpers ----------
const $ = (sel) => document.querySelector(sel);
const views = {
  home: $("#view-home"),
  upload: $("#view-upload"),
  mode: $("#view-mode"),
  fullOptions: $("#view-full-options"),
  transcribeOptions: $("#view-transcribe-options"),
  textInput: $("#view-text-input"),
  textOptions: $("#view-text-options"),
  loading: $("#view-loading"),
  notEnglish: $("#view-not-english"),
  results: $("#view-results"),
  history: $("#view-history"),
};

function showView(name) {
  stopPlayback(); // never keep talking after the page changes
  Object.values(views).forEach((v) => (v.hidden = true));
  views[name].hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showError(message) {
  const banner = $("#error-banner");
  banner.textContent = message;
  banner.hidden = false;
  setTimeout(() => (banner.hidden = true), 6000);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------- waveform decoration ----------
function drawBars(groupSelector, count, animate) {
  const g = document.querySelector(groupSelector);
  if (!g) return;
  g.innerHTML = "";
  const width = 520 / count;
  for (let i = 0; i < count; i++) {
    const h = 14 + Math.random() * 60;
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", i * width + width * 0.2);
    rect.setAttribute("width", width * 0.6);
    rect.setAttribute("height", h);
    rect.setAttribute("y", (90 - h) / 2);
    rect.setAttribute("rx", 2);
    if (animate) {
      rect.style.animation = `pulse ${0.6 + Math.random() * 0.8}s ease-in-out infinite`;
      rect.style.animationDelay = `${Math.random() * 0.5}s`;
      rect.style.transformOrigin = "center";
    }
    g.appendChild(rect);
  }
}
drawBars("#wave-bars", 46, false);
drawBars("#wave-bars-home", 46, false);

// ---------- access key (only matters if the backend has ACCESS_KEY set) ----------
const KEY_STORAGE = "ts_api_key";
let _apiKeyMemoryFallback = "";
const getStoredKey = () => {
  try {
    return localStorage.getItem(KEY_STORAGE) || _apiKeyMemoryFallback || "";
  } catch {
    return _apiKeyMemoryFallback || "";
  }
};
const setStoredKey = (k) => {
  _apiKeyMemoryFallback = k; // always works for the rest of this session
  try {
    localStorage.setItem(KEY_STORAGE, k);
  } catch {
    // storage blocked — the in-memory fallback above still covers this tab
  }
};

// Small "remember this" helpers (voice, speed). If the browser blocks storage they quietly fall back to memory.
const _memStore = {};
function savedGet(k) {
  try {
    const v = localStorage.getItem(k);
    return v === null ? (_memStore[k] ?? null) : v;
  } catch {
    return _memStore[k] ?? null;
  }
}
function savedSet(k, v) {
  _memStore[k] = String(v);
  try {
    localStorage.setItem(k, String(v));
  } catch {
    // blocked — memory copy above still works for this tab
  }
}
function savedRemove(k) {
  delete _memStore[k];
  try {
    localStorage.removeItem(k);
  } catch {
    // ignore
  }
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const key = getStoredKey();
  if (key) headers["X-API-Key"] = key;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    openAuthModal("That key wasn't accepted. Try again.");
    throw new Error("Locked — enter the access key to continue.");
  }
  return res;
}

// A failed request's body isn't guaranteed to be JSON — a server-level
// error (a crash before FastAPI's own error handling, a proxy's error
// page, etc.) can come back as plain text or HTML. Blindly calling
// `.json()` on that throws its own confusing parse error ("Unexpected
// token 'I', "Internal S"... is not valid JSON") that hides what actually
// went wrong. This always returns a readable string instead.
async function errorDetail(res, fallback) {
  const raw = await res.text();
  try {
    const data = JSON.parse(raw);
    return data.detail || fallback;
  } catch {
    return raw && raw.length < 200 ? raw : fallback;
  }
}

function uploadWithProgress(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    const key = getStoredKey();
    if (key) xhr.setRequestHeader("X-API-Key", key);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status === 401) {
        openAuthModal("That key wasn't accepted. Try again.");
        reject(new Error("Locked — enter the access key to continue."));
        return;
      }
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
      } else {
        reject(new Error((data && data.detail) || `Upload failed (${xhr.status}).`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload."));
    xhr.send(formData);
  });
}

function openAuthModal(errorMessage) {
  const modal = $("#auth-modal");
  const err = $("#auth-error");
  if (errorMessage) {
    err.textContent = errorMessage;
    err.hidden = false;
  } else {
    err.hidden = true;
  }
  modal.hidden = false;
  $("#auth-key-input").focus();
}

$("#btn-auth-submit").addEventListener("click", () => {
  const val = $("#auth-key-input").value.trim();
  if (!val) return;
  setStoredKey(val);
  $("#auth-modal").hidden = true;
  $("#auth-key-input").value = "";
  refreshAccount();
});
$("#auth-key-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#btn-auth-submit").click();
});

// "ravi · 3 of 20 jobs used today · Sign out" at the top of the page (only when there is something to show).
async function refreshAccount() {
  const line = $("#account-line");
  const out = $("#btn-sign-out");
  try {
    const key = getStoredKey();
    const res = await fetch(`${API_BASE}/api/me`, { headers: key ? { "X-API-Key": key } : {} });
    if (res.status === 401 && key) openAuthModal("That key wasn't accepted. Try again.");
    if (res.status === 429) openAuthModal("Too many wrong keys. Please wait 10 minutes and try again.");
    if (!res.ok) throw new Error("not signed in");
    const me = await res.json();
    const parts = [];
    if (me.name) parts.push(me.name);
    if (me.limit) parts.push(`${me.used} of ${me.limit} jobs used today`);
    line.textContent = parts.join(" · ");
    line.hidden = parts.length === 0;
    out.hidden = !me.auth_required;
  } catch {
    line.hidden = true;
    out.hidden = true;
  }
}
$("#btn-sign-out").addEventListener("click", () => {
  setStoredKey("");
  $("#account-line").hidden = true;
  $("#btn-sign-out").hidden = true;
  openAuthModal("Signed out. Enter an access key to sign in again.");
});

async function checkAuthRequirement() {
  try {
    const res = await fetch(`${API_BASE}/api/auth-required`);
    const data = await res.json();
    if (data.required && !getStoredKey()) openAuthModal();
  } catch {
    // backend not reachable yet — the rest of the app will surface that
    // error the moment the user tries to do something.
  }
}
checkAuthRequirement().then(refreshAccount);

// The server says whether a language model is configured. Without one there are no AI insights, so the
// options for them are hidden instead of leaving a checkbox that can never deliver.
async function loadCapabilities() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    const data = await res.json();
    if (data.ai_insights === false) {
      $("#opt-insights").checked = false;
      $("#insights-row").hidden = true;
      $("#context-label").hidden = true;
      $("#opt-context").hidden = true;
      $("#full-desc").textContent =
        "Full transcript, a summary at the length you choose, key points and highlighted dates/links/names — downloadable as PDF, Word, or an image.";
      // The same switches on the Text to Audio page, and the spelling fix (it needs a language model too).
      $("#txt-insights").checked = false;
      $("#txt-insights-row").hidden = true;
      $("#txt-context-label").hidden = true;
      $("#txt-context").hidden = true;
      $("#opt-spelling").checked = false;
      $("#spelling-row").hidden = true;
      $("#spelling-hint").hidden = true;
      $("#opt-spelling-transcribe").checked = false;
      $("#spelling-row-transcribe").hidden = true;
    }
    if (data.tts === false) $("#tts-unavailable").hidden = false;
    if (data.diarization === false) {
      // Speaker labels need extra setup on the server (README) — show why the boxes are greyed out.
      ["#opt-speakers", "#opt-speakers-transcribe"].forEach((id) => {
        $(id).checked = false;
        $(id).disabled = true;
      });
      $("#speakers-hint").textContent = "Not set up on this server yet — see “Speaker labels” in the README.";
      $("#speakers-hint-transcribe").textContent = "Not set up on this server yet — see “Speaker labels” in the README.";
    }
  } catch {
    // backend not reachable yet — leave the page as it is
  }
}
loadCapabilities();

// ---------- state ----------
let currentFile = null; // File or Blob (from recording)
let currentFileName = "recording.webm";
let mediaRecorder = null;
let recordedChunks = [];
let recordTimerInterval = null;
let pollTimer = null;
let viewingFromHistory = false;
let currentJob = null; // last-rendered job, used by the download panels

// ---------- file selection (browse / drag-drop) ----------
const dropzone = $("#dropzone");
const fileInput = $("#file-input");

$("#btn-browse").addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) setFile(fileInput.files[0], fileInput.files[0].name);
});

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
  })
);
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) setFile(file, file.name);
});

function setFile(fileOrBlob, name) {
  currentFile = fileOrBlob;
  currentFileName = name;
  $("#file-name").textContent = name;
  $("#audio-preview").src = URL.createObjectURL(fileOrBlob);
  $("#file-ready").hidden = false;
  $("#recording-panel").hidden = true;
  showView("mode");
}

// ---------- paste an audio file (Ctrl+V / Cmd+V) ----------
// Copy an audio file in your file manager (or from a chat app), come back to this page and paste:
// the file is picked up automatically and you go straight on to choosing what you want from it.
const AUDIO_EXT = /\.(mp3|wav|m4a|aac|ogg|oga|opus|flac|webm|weba|mp4|mpeg|mpga|3gp|amr|wma|aiff?)$/i;
const EXT_FOR_TYPE = {
  "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
  "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac", "audio/ogg": "ogg", "audio/opus": "opus",
  "audio/flac": "flac", "audio/webm": "webm", "video/webm": "webm", "video/mp4": "mp4", "audio/3gpp": "3gp",
};

function isProbablyAudio(file) {
  return (file.type || "").startsWith("audio/") || AUDIO_EXT.test(file.name || "");
}

function nameForPastedFile(file) {
  // Pasted clipboard data can arrive with no usable name; the server picks the decoder from the
  // extension, so make sure there is a sensible one.
  if (file.name && AUDIO_EXT.test(file.name)) return file.name;
  return `pasted-audio.${EXT_FOR_TYPE[file.type] || "webm"}`;
}

document.addEventListener("paste", (e) => {
  if (views.upload.hidden || !$("#recording-panel").hidden) return; // only on the first page, not while recording
  const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
  if (!files.length) return; // ordinary text paste: leave it alone
  e.preventDefault();
  const audio = files.find(isProbablyAudio);
  if (!audio) {
    showError("That doesn't look like an audio file. Copy an MP3, WAV, M4A, OGG or WEBM file and paste again.");
    return;
  }
  const name = nameForPastedFile(audio);
  setFile(name === audio.name ? audio : new File([audio], name, { type: audio.type }), name);
});

$("#btn-change-file").addEventListener("click", () => {
  currentFile = null;
  $("#file-ready").hidden = true;
  fileInput.value = "";
});

// ---------- live recording ----------
$("#btn-record").addEventListener("click", async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => recordedChunks.push(e.data);
    mediaRecorder.onstop = () => {
      const blob = new Blob(recordedChunks, { type: "audio/webm" });
      stream.getTracks().forEach((t) => t.stop());
      setFile(blob, "recording.webm");
    };
    mediaRecorder.start();

    $("#recording-panel").hidden = false;
    $("#file-ready").hidden = true;
    let seconds = 0;
    $("#record-timer").textContent = "00:00";
    recordTimerInterval = setInterval(() => {
      seconds++;
      const m = String(Math.floor(seconds / 60)).padStart(2, "0");
      const s = String(seconds % 60).padStart(2, "0");
      $("#record-timer").textContent = `${m}:${s}`;
    }, 1000);
  } catch (err) {
    showError("Couldn't access the microphone. Check your browser permissions.");
  }
});

$("#btn-stop-record").addEventListener("click", () => {
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  clearInterval(recordTimerInterval);
});

// ---------- summary length: one drop-down (30 / 50 / 70 / 100 / custom) ----------
function wireSummaryPicker(selectSel, customSel) {
  const select = $(selectSel);
  const custom = $(customSel);
  select.addEventListener("change", () => {
    custom.hidden = select.value !== "custom";
    if (!custom.hidden) custom.focus();
  });
}
wireSummaryPicker("#opt-summary-select", "#opt-summary-custom");
wireSummaryPicker("#txt-summary-select", "#txt-summary-custom");

// Returns the chosen number of words, or null (after telling the person) when a custom value is unusable.
function readSummaryWords(selectSel, customSel) {
  const value = $(selectSel).value;
  if (value !== "custom") return parseInt(value, 10);
  const n = parseInt($(customSel).value, 10);
  if (!Number.isFinite(n) || n < 10 || n > 500) {
    showError("Type a summary length between 10 and 500 words.");
    $(customSel).focus();
    return null;
  }
  return n;
}

// ---------- navigation ----------
function optionsViewFor(mode) {
  if (mode === "tts") return "textOptions";
  return mode === "full" ? "fullOptions" : "transcribeOptions";
}

function goHome() {
  clearTimeout(pollTimer);
  stopPlayback();
  currentFile = null;
  currentJob = null;
  viewingFromHistory = false;
  $("#file-ready").hidden = true;
  fileInput.value = "";
  $("#tts-text").value = "";
  $("#text-source-note").hidden = true;
  $("#extract-status").textContent = "";
  updateTextCount();
  setTextTab("write");
  showView("home");
}

function previousPage() {
  if (viewingFromHistory) {
    showView("history");
    loadHistory();
    return;
  }
  if (!currentJob) return goHome();
  showView(optionsViewFor(currentJob.mode));
}

$("#nav-home").addEventListener("click", goHome);
$("#btn-restart").addEventListener("click", goHome);
$("#btn-previous").addEventListener("click", previousPage);

$("#home-audio-to-text").addEventListener("click", () => showView("upload"));
$("#home-text-to-audio").addEventListener("click", async () => {
  showView("textInput");
  try {
    await ensureVoices();
    updateTextCount();
  } catch (err) {
    showError(err.message || "Couldn't load the voice list.");
  }
});
$("#btn-upload-back").addEventListener("click", () => showView("home"));
$("#btn-text-back").addEventListener("click", () => showView("home"));
$("#btn-text-options-back").addEventListener("click", () => showView("textInput"));

// ---------- mode selection ----------
document.querySelectorAll(".mode-card[data-mode]").forEach((card) => {
  card.addEventListener("click", () => {
    showView(card.dataset.mode === "full" ? "fullOptions" : "transcribeOptions");
  });
});

$("#btn-back-to-upload").addEventListener("click", () => showView("upload"));
$("#btn-back-full").addEventListener("click", () => showView("mode"));
$("#btn-back-transcribe").addEventListener("click", () => showView("mode"));
function goBackToStart() {
  clearTimeout(pollTimer);
  currentFile = null;
  viewingFromHistory = false;
  $("#file-ready").hidden = true;
  fileInput.value = "";
  showView("upload");
}
$("#btn-not-english-back").addEventListener("click", goBackToStart);
$("#btn-back-to-history").addEventListener("click", () => {
  showView("history");
  loadHistory();
});

// ---------- history nav ----------
$("#nav-history").addEventListener("click", () => {
  showView("history");
  loadHistory();
});
$("#btn-history-to-upload").addEventListener("click", goHome);

// ====================================================================
// Text to Audio: voices, playback, and the voice drop-down
// ====================================================================
let voiceCatalog = null;
let voiceCatalogPromise = null;
let defaultVoiceId = "india-1";
let maxTextChars = 30000;

function ensureVoices() {
  if (voiceCatalog) return Promise.resolve(voiceCatalog);
  if (!voiceCatalogPromise) {
    voiceCatalogPromise = fetch(`${API_BASE}/api/tts/voices`)
      .then((res) => {
        if (!res.ok) throw new Error("Couldn't load the list of voices.");
        return res.json();
      })
      .then((data) => {
        voiceCatalog = data.voices;
        defaultVoiceId = data.default || defaultVoiceId;
        maxTextChars = data.max_chars || maxTextChars;
        return voiceCatalog;
      })
      .catch((err) => {
        voiceCatalogPromise = null; // try again next time
        throw err;
      });
  }
  return voiceCatalogPromise;
}

const voiceById = (id) => (voiceCatalog || []).find((v) => v.id === id);
const voiceLabel = (v) => (v ? `${v.label} · ${v.gender}` : "Choose a voice");

const ICON_SPEAKER =
  '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 9v6h4l5 4V5L7 9H3z" fill="currentColor"/><path d="M16 8.5a5 5 0 0 1 0 7M18.6 6a8.6 8.6 0 0 1 0 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
const ICON_PLAY =
  '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M7 4.5v15l12-7.5z" fill="currentColor"/></svg>';
const ICON_STOP =
  '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>';
const ICON_PAUSE =
  '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1.2" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1.2" fill="currentColor"/></svg>';
const ICON_SPIN =
  '<svg class="spin" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2.6" stroke-dasharray="34 16" stroke-linecap="round"/></svg>';

// Only one thing speaks at a time. Audio is fetched as a blob through apiFetch (so the access key is
// sent when one is set, and Safari doesn't need byte-range support) and played from memory.
const blobUrlCache = new Map();
let activePlayback = null; // { audio, key, setState }

async function fetchBlobUrl(cacheKey, path) {
  if (blobUrlCache.has(cacheKey)) return blobUrlCache.get(cacheKey);
  const res = await apiFetch(path);
  if (!res.ok) throw new Error(await errorDetail(res, "Couldn't load that audio."));
  const url = URL.createObjectURL(await res.blob());
  blobUrlCache.set(cacheKey, url);
  return url;
}

// Playback speed (0.75x - 1.5x), remembered between visits.
let playbackSpeed = parseFloat(savedGet("ts_speed")) || 1;
if (![0.75, 1, 1.25, 1.5].includes(playbackSpeed)) playbackSpeed = 1;

function setSpeed(speed) {
  playbackSpeed = speed;
  savedSet("ts_speed", speed);
  document.querySelectorAll("[data-speed]").forEach((sel) => (sel.value = String(speed)));
  if (activePlayback) activePlayback.audio.playbackRate = speed;
}

function stopPlayback() {
  if (!activePlayback) return;
  const playback = activePlayback;
  activePlayback = null;
  cancelAnimationFrame(playback.raf);
  playback.audio.pause();
  if (playback.hooks && playback.hooks.onStop) playback.hooks.onStop();
  playback.setState("idle");
}

// `hooks.onTick(fraction)` is called ~60 times a second while playing (used for the karaoke highlight);
// `hooks.onStop()` when it ends or is stopped.
function startPlayback(url, key, setState, hooks) {
  stopPlayback();
  const audio = new Audio(url);
  audio.playbackRate = playbackSpeed;
  const playback = { audio, key, setState, hooks, raf: 0, tick: null };
  activePlayback = playback;
  playback.tick = () => {
    if (activePlayback !== playback) return;
    if (hooks && hooks.onTick && audio.duration) hooks.onTick(audio.currentTime / audio.duration);
    playback.raf = requestAnimationFrame(playback.tick);
  };
  const finish = () => {
    cancelAnimationFrame(playback.raf);
    if (activePlayback === playback) activePlayback = null;
    if (hooks && hooks.onStop) hooks.onStop();
    setState("idle");
  };
  audio.addEventListener("ended", finish);
  audio.addEventListener("error", () => {
    finish();
    showError("Couldn't play that audio.");
  });
  setState("playing");
  audio
    .play()
    .then(() => playback.tick())
    .catch(() => {
      finish();
      showError("Your browser blocked playback. Press the speaker again.");
    });
}

// Pause <-> resume the current sound (the speaker icon's job when it is already playing).
function togglePause() {
  const playback = activePlayback;
  if (!playback) return;
  if (playback.audio.paused) {
    playback.setState("playing");
    playback.audio.play().then(() => playback.tick());
  } else {
    playback.audio.pause();
    cancelAnimationFrame(playback.raf);
    playback.setState("paused");
  }
}

// Turns a <button> into a play / stop control (or play / pause / resume when opts.pausable).
// `keyFn` identifies what it plays; `urlFn` fetches it.
function bindAudioButton(button, idleIcon, keyFn, urlFn, opts = {}) {
  const setState = (state) => {
    button.dataset.state = state;
    button.innerHTML =
      state === "loading" ? ICON_SPIN : state === "playing" ? (opts.pausable ? ICON_PAUSE : ICON_STOP) : idleIcon;
    button.disabled = state === "loading";
    button.setAttribute("aria-pressed", state === "playing" ? "true" : "false");
    if (opts.pausable) {
      button.title = state === "playing" ? "Pause" : state === "paused" ? "Resume" : "Listen";
    }
    if (opts.onState) opts.onState(state);
  };
  setState("idle");
  button.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation(); // a ▶ inside the voice list must not also pick that voice
    const key = keyFn();
    if (activePlayback && activePlayback.key === key) {
      if (opts.pausable) togglePause();
      else stopPlayback();
      return;
    }
    stopPlayback();
    setState("loading");
    try {
      const url = await urlFn();
      startPlayback(url, key, setState, opts.hooks);
    } catch (err) {
      setState("idle");
      showError(err.message || "Couldn't play that audio.");
    }
  });
  return setState;
}

// The voice drop-down: a list of every accent, each with its own ▶ to hear a 10-second sample.
// (A plain <select> can't hold buttons, so this is built by hand.)
function closeAllPickers() {
  document.querySelectorAll(".vp-list:not([hidden])").forEach((list) => {
    list.hidden = true;
    const btn = list.parentElement.querySelector(".vp-button");
    if (btn) btn.setAttribute("aria-expanded", "false");
  });
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".vp")) closeAllPickers();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAllPickers();
});

function createVoicePicker(mount, { value, onChange }) {
  let current = value;
  mount.innerHTML = "";

  const root = document.createElement("div");
  root.className = "vp";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "vp-button";
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  const list = document.createElement("ul");
  list.className = "vp-list";
  list.setAttribute("role", "listbox");
  list.hidden = true;

  const paintButton = () => {
    button.innerHTML = `<span class="vp-label">${escapeHtml(voiceLabel(voiceById(current)))}</span><span class="vp-caret" aria-hidden="true">&#9662;</span>`;
    list.querySelectorAll(".vp-item").forEach((li) => {
      const on = li.dataset.id === current;
      li.classList.toggle("selected", on);
      li.setAttribute("aria-selected", on ? "true" : "false");
    });
  };

  let lastGroup = null;
  (voiceCatalog || []).forEach((v) => {
    if (v.group !== lastGroup) {
      const head = document.createElement("li");
      head.className = "vp-group";
      head.setAttribute("role", "presentation");
      head.textContent = v.group;
      list.appendChild(head);
      lastGroup = v.group;
    }
    const li = document.createElement("li");
    li.className = "vp-item";
    li.dataset.id = v.id;
    li.setAttribute("role", "option");
    li.innerHTML = `<span class="vp-name">${escapeHtml(v.label)}</span><span class="vp-gender">${escapeHtml(v.gender)}</span>`;
    const play = document.createElement("button");
    play.type = "button";
    play.className = "vp-play";
    play.title = `Hear a 10-second sample of ${v.label}`;
    play.setAttribute("aria-label", `Hear a 10-second sample of ${v.label}`);
    bindAudioButton(
      play,
      ICON_PLAY,
      () => `preview|${v.id}`,
      () => fetchBlobUrl(`preview|${v.id}`, `/api/tts/preview/${v.id}`)
    );
    li.appendChild(play);
    li.addEventListener("click", () => {
      current = v.id;
      paintButton();
      closeAllPickers();
      onChange(v.id);
    });
    list.appendChild(li);
  });

  button.addEventListener("click", (e) => {
    e.stopPropagation();
    const wasOpen = !list.hidden;
    closeAllPickers();
    if (!wasOpen) {
      list.hidden = false;
      button.setAttribute("aria-expanded", "true");
      const sel = list.querySelector(".vp-item.selected");
      if (sel) sel.scrollIntoView({ block: "nearest" });
    }
  });

  root.appendChild(button);
  root.appendChild(list);
  mount.appendChild(root);
  paintButton();
  return {
    get value() {
      return current;
    },
  };
}

// ====================================================================
// Text to Audio: give the text
// ====================================================================
function setTextTab(which) {
  const write = which === "write";
  $("#panel-write").hidden = !write;
  $("#panel-file").hidden = write;
  $("#tab-write").classList.toggle("active", write);
  $("#tab-file").classList.toggle("active", !write);
  $("#tab-write").setAttribute("aria-selected", write ? "true" : "false");
  $("#tab-file").setAttribute("aria-selected", write ? "false" : "true");
}
$("#tab-write").addEventListener("click", () => setTextTab("write"));
$("#tab-file").addEventListener("click", () => setTextTab("file"));

function updateTextCount() {
  const text = $("#tts-text").value.trim();
  const words = text ? text.split(/\s+/).length : 0;
  const el = $("#tts-count");
  el.textContent = `${words.toLocaleString()} words · ${text.length.toLocaleString()} / ${maxTextChars.toLocaleString()} characters`;
  el.classList.toggle("over-limit", text.length > maxTextChars);
}
$("#tts-text").addEventListener("input", () => {
  $("#text-source-note").hidden = true;
  updateTextCount();
});
$("#btn-clear-text").addEventListener("click", () => {
  $("#tts-text").value = "";
  $("#text-source-note").hidden = true;
  updateTextCount();
  $("#tts-text").focus();
});
$("#btn-paste-clip").addEventListener("click", async () => {
  try {
    const clip = await navigator.clipboard.readText();
    if (!clip.trim()) return showError("The clipboard is empty — copy some text first.");
    const box = $("#tts-text");
    box.value = box.value ? `${box.value.replace(/\s+$/, "")}\n\n${clip}` : clip;
    updateTextCount();
  } catch {
    showError("Your browser blocked clipboard access. Click in the box and press Ctrl+V instead.");
    $("#tts-text").focus();
  }
});

// Upload a PDF / Word / image: the server reads the text out of it and it lands in the box to be checked.
const textFileInput = $("#text-file-input");
$("#btn-text-browse").addEventListener("click", () => textFileInput.click());
textFileInput.addEventListener("change", () => {
  if (textFileInput.files[0]) readTextFile(textFileInput.files[0]);
});
const textDropzone = $("#text-dropzone");
["dragenter", "dragover"].forEach((evt) =>
  textDropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    textDropzone.classList.add("drag-over");
  })
);
["dragleave", "drop"].forEach((evt) =>
  textDropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    textDropzone.classList.remove("drag-over");
  })
);
textDropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) readTextFile(file);
});

async function readTextFile(file) {
  const status = $("#extract-status");
  status.textContent = `Reading ${file.name}… (pictures and scanned pages can take a few seconds)`;
  const formData = new FormData();
  formData.append("file", file, file.name);
  try {
    const res = await apiFetch("/api/extract-text", { method: "POST", body: formData });
    if (!res.ok) throw new Error(await errorDetail(res, "Couldn't read that file."));
    const data = await res.json();
    $("#tts-text").value = data.text;
    updateTextCount();
    $("#text-source-note").textContent = `Text read from ${file.name} (${data.words.toLocaleString()} words). Check it, fix anything that looks wrong, then press Next.`;
    $("#text-source-note").hidden = false;
    status.textContent = "";
    setTextTab("write");
  } catch (err) {
    status.textContent = err.message || "Couldn't read that file.";
  } finally {
    textFileInput.value = "";
  }
}

$("#btn-text-next").addEventListener("click", async () => {
  const text = $("#tts-text").value.trim();
  if (text.split(/\s+/).filter(Boolean).length < 3) return showError("Please give a little more text first.");
  if (text.length > maxTextChars) {
    return showError(`That text is too long (${text.length.toLocaleString()} characters). The limit is ${maxTextChars.toLocaleString()}.`);
  }
  try {
    await ensureVoices();
  } catch (err) {
    return showError(err.message || "Couldn't load the list of voices.");
  }
  if (!selectedVoiceId) {
    const saved = savedGet("ts_voice"); // the voice remembered from last time, if it still exists
    selectedVoiceId = voiceById(saved) ? saved : defaultVoiceId;
  }
  $("#txt-remember").checked = savedGet("ts_remember") !== "0";
  if (!textVoicePicker) {
    textVoicePicker = createVoicePicker($("#txt-voice-picker"), {
      value: selectedVoiceId || defaultVoiceId,
      onChange: (id) => (selectedVoiceId = id),
    });
  }
  showView("textOptions");
});

// ====================================================================
// Text to Audio: options -> job
// ====================================================================
let selectedVoiceId = null;
let textVoicePicker = null;

$("#btn-run-text").addEventListener("click", async () => {
  const words = readSummaryWords("#txt-summary-select", "#txt-summary-custom");
  if (words === null) return;

  const formData = new FormData();
  formData.append("text", $("#tts-text").value.trim());
  formData.append("summary_words", words);
  formData.append("include_key_points", $("#txt-keypoints").checked);
  formData.append("include_highlights", $("#txt-highlights").checked);
  formData.append("include_ai_insights", $("#txt-insights").checked);
  formData.append("voice_id", selectedVoiceId || defaultVoiceId);
  if ($("#txt-remember").checked) {
    savedSet("ts_voice", selectedVoiceId || defaultVoiceId);
    savedSet("ts_remember", "1");
  } else {
    savedRemove("ts_voice");
    savedSet("ts_remember", "0");
  }
  const context = $("#txt-context").value.trim();
  if (context) formData.append("context", context);

  startLoading("Reading and summarising your text…");
  $("#upload-progress-track").hidden = true;
  try {
    const res = await apiFetch("/api/jobs/text", { method: "POST", body: formData });
    if (!res.ok) throw new Error(await errorDetail(res, "Couldn't start that."));
    const data = await res.json();
    processingStage("tts");
    pollJob(data.job_id, "tts");
  } catch (err) {
    showError(err.message || "Something went wrong.");
    showView("textOptions");
  }
});

// ---------- running the jobs (upload -> job id -> poll) ----------
function startLoading(message) {
  $("#loading-text").textContent = message;
  $("#upload-progress-track").hidden = false;
  $("#upload-progress-fill").style.width = "0%";
  drawBars("#wave-bars-loading", 46, true);
  showView("loading");
}

function setUploadProgress(pct) {
  $("#upload-progress-fill").style.width = `${pct}%`;
  $("#loading-text").textContent = `Uploading… ${pct}%`;
}

function processingStage(mode) {
  $("#upload-progress-track").hidden = true;
  $("#loading-text").textContent =
    mode === "tts"
      ? "Reading and summarising your text…"
      : mode === "full"
        ? "Listening closely and analyzing your audio…"
        : "Listening closely and transcribing your audio…";
}

function pollJob(jobId, mode) {
  clearTimeout(pollTimer);
  const tick = async () => {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}`);
      if (!res.ok) throw new Error("Lost track of that job.");
      const job = await res.json();

      if (job.status === "queued") {
        $("#loading-text").textContent = "Waiting in queue…";
      } else if (job.status === "processing") {
        processingStage(mode);
      } else if (job.status === "done") {
        viewingFromHistory = false;
        renderResults(job);
        return; // stop polling
      } else if (job.status === "not_english") {
        // Not an error in the usual sense: the file was fine, it just isn't
        // English. Show a dedicated screen with a clear way back.
        $("#not-english-message").textContent =
          job.error || "This tool only works with English audio. Please provide English audio.";
        showView("notEnglish");
        return; // stop polling
      } else if (job.status === "error") {
        showError(job.error || "Something went wrong while processing that.");
        showView(optionsViewFor(mode));
        return; // stop polling
      }
      pollTimer = setTimeout(tick, 1500);
    } catch (err) {
      showError(err.message || "Lost connection while checking job status.");
      showView(optionsViewFor(mode));
    }
  };
  tick();
}

$("#btn-run-full").addEventListener("click", async () => {
  if (!currentFile) return showError("No audio file selected.");
  const summaryWords = readSummaryWords("#opt-summary-select", "#opt-summary-custom");
  if (summaryWords === null) return;

  const formData = new FormData();
  formData.append("file", currentFile, currentFileName);
  formData.append("summary_words", summaryWords);
  formData.append("include_key_points", $("#opt-keypoints").checked);
  formData.append("include_highlights", $("#opt-highlights").checked);
  formData.append("include_ai_insights", $("#opt-insights").checked);
  // Downloads are made on demand from the buttons at the bottom of the results page.
  formData.append("include_pdf", false);
  formData.append("include_docx", false);
  formData.append("include_image", false);
  formData.append("reduce_noise", $("#opt-denoise").checked);
  formData.append("correct_spelling", $("#opt-spelling").checked);
  formData.append("label_speakers", $("#opt-speakers").checked && !$("#opt-speakers").disabled);
  const vocabHint = $("#opt-vocab").value.trim();
  if (vocabHint) formData.append("vocabulary_hint", vocabHint);
  const context = $("#opt-context").value.trim();
  if (context) formData.append("context", context);

  startLoading("Uploading… 0%");

  try {
    const data = await uploadWithProgress("/api/jobs/full", formData, setUploadProgress);
    processingStage("full");
    pollJob(data.job_id, "full");
  } catch (err) {
    showError(err.message || "Something went wrong.");
    showView("fullOptions");
  }
});

$("#btn-run-transcribe").addEventListener("click", async () => {
  if (!currentFile) return showError("No audio file selected.");

  const formData = new FormData();
  formData.append("file", currentFile, currentFileName);
  formData.append("include_pdf", false);
  formData.append("include_docx", false);
  formData.append("reduce_noise", $("#opt-denoise-transcribe").checked);
  formData.append("correct_spelling", $("#opt-spelling-transcribe").checked);
  formData.append("label_speakers", $("#opt-speakers-transcribe").checked && !$("#opt-speakers-transcribe").disabled);
  const vocabHintTranscribe = $("#opt-vocab-transcribe").value.trim();
  if (vocabHintTranscribe) formData.append("vocabulary_hint", vocabHintTranscribe);

  startLoading("Uploading… 0%");

  try {
    const data = await uploadWithProgress("/api/jobs/transcribe", formData, setUploadProgress);
    processingStage("transcribe");
    pollJob(data.job_id, "transcribe");
  } catch (err) {
    showError(err.message || "Something went wrong.");
    showView("transcribeOptions");
  }
});

// ---------- rendering results ----------
function block(title, innerHtml) {
  return `<div class="result-block"><h3>${title}</h3>${innerHtml}</div>`;
}

// ---------- karaoke: light up the sentence being read ----------
// Cuts text into sentences without losing a single character (so the pieces always join back to the original).
function splitSentences(text) {
  const out = [];
  let cur = "";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    cur += ch;
    if (/[.!?。！？]/.test(ch)) {
      while (i + 1 < text.length && /[.!?。！？"'”’)\]]/.test(text[i + 1])) cur += text[++i];
      while (i + 1 < text.length && /\s/.test(text[i + 1])) cur += text[++i];
      out.push(cur);
      cur = "";
    } else if (ch === "\n") {
      while (i + 1 < text.length && /\s/.test(text[i + 1])) cur += text[++i];
      out.push(cur);
      cur = "";
    }
  }
  if (cur) out.push(cur);
  return out;
}

function sentenceHtml(text, terms) {
  return splitSentences(text)
    .map((sentence) => `<span class="sent">${highlightTranscript(sentence, terms)}</span>`)
    .join("");
}

// The voice service gives no word timings, so the position is estimated from sentence length (plus a short
// pause after each full stop). It follows the speed setting automatically, and is close enough to read along.
function makeKaraoke(part) {
  let els = null;
  let ends = null;
  let current = -1;
  const prepare = () => {
    els = [...document.querySelectorAll(`[data-sentences="${part}"] .sent`)];
    const weights = els.map((el) => el.textContent.trim().length + (/[.!?。！？]["'”’)\]]*\s*$/.test(el.textContent) ? 10 : 2));
    const total = weights.reduce((a, b) => a + b, 0) || 1;
    let acc = 0;
    ends = weights.map((w) => (acc += w) / total);
    current = -1;
  };
  return {
    onTick(fraction) {
      if (!els) prepare();
      if (!els.length) return;
      let index = ends.findIndex((end) => fraction <= end);
      if (index < 0) index = els.length - 1;
      if (index === current) return;
      if (current >= 0 && els[current]) els[current].classList.remove("speaking");
      els[index].classList.add("speaking");
      current = index;
      els[index].scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    onStop() {
      (els || []).forEach((el) => el.classList.remove("speaking"));
      els = null;
      current = -1;
    },
  };
}

// The speaker icon with the accent drop-down to its right (like Google Translate's), for Text to Audio.
function speakRow(part) {
  const what = part === "script" ? "the whole text" : "the summary";
  return `<div class="speak-row"><button type="button" class="speak-btn" data-speak="${part}" title="Listen to ${what}" aria-label="Listen to ${what}"></button><button type="button" class="stop-btn" data-stop="${part}" title="Stop" aria-label="Stop" hidden>&#9632;</button><span class="speak-voice" data-voice-mount="${part}"></span><label class="speed-label"><span class="visually-hidden">Speed</span><select class="select-input speed-select" data-speed aria-label="Reading speed"><option value="0.75">0.75&times;</option><option value="1">1&times;</option><option value="1.25">1.25&times;</option><option value="1.5">1.5&times;</option></select></label></div>`;
}

function labeledHtml(text, terms) {
  return text
    .split(/\n\n+/)
    .map((turn) => {
      const m = turn.match(/^(Speaker \d+): ([\s\S]*)$/);
      if (!m) return `<span class="spk-turn">${highlightTranscript(turn, terms)}</span>`;
      return `<span class="spk-turn"><strong class="spk">${escapeHtml(m[1])}</strong> ${highlightTranscript(m[2], terms)}</span>`;
    })
    .join("");
}

function renderTranscriptBlock(job, highlightTerms, isText) {
  const labeled = !isText && job.labeled_transcript;
  const bodyHtml = isText
    ? `<p data-transcript-view="main" data-sentences="script">${sentenceHtml(job.transcript || "", highlightTerms)}</p>`
    : labeled
      ? `<div class="speaker-transcript" data-transcript-view="main">${labeledHtml(job.labeled_transcript, highlightTerms)}</div>`
      : `<p data-transcript-view="main">${highlightTranscript(job.transcript || "", highlightTerms)}</p>`;
  const editBtn = `<button type="button" class="btn btn-text transcript-edit-btn" id="btn-edit-transcript">${t("editTranscript")}</button>`;
  const editArea = `
    <div id="transcript-edit-area" hidden>
      ${labeled ? '<p class="field-hint">Saving an edit replaces the speaker-labelled version with plain text.</p>' : ""}
      <textarea id="transcript-edit-textarea" class="text-input transcript-textarea" rows="6"></textarea>
      <div class="edit-actions">
        <button type="button" class="btn btn-text" id="btn-cancel-edit">${t("cancelEdit")}</button>
        <button type="button" class="btn btn-primary" id="btn-save-edit">${t("saveEdit")}</button>
      </div>
    </div>`;
  const heading = isText ? t("wholeTextHeading") : t("fullTranscriptHeading");
  const speak = isText ? speakRow("script") : "";
  return block(`${heading} ${editBtn}`, `${speak}${bodyHtml}${editArea}`);
}

function linkify(links) {
  if (!links.length) return `<p>${t("noneFound")}</p>`;
  return `<ul>${links
    .map((l) => {
      const href = l.startsWith("http") ? l : `https://${l}`;
      return `<li><a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(l)}</a></li>`;
    })
    .join("")}</ul>`;
}

function bulletList(items) {
  if (!items.length) return `<p>${t("noneFound")}</p>`;
  return `<ul>${items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`;
}

// Wraps any of the given terms where they appear in the (already
// HTML-escaped) transcript text, so dates/links/notable terms visually
// stand out inline, not just in their own list below.
function highlightTranscript(rawText, terms) {
  let html = escapeHtml(rawText);
  const all = [...(terms.dates || []), ...(terms.links || []), ...(terms.notable || [])]
    .filter(Boolean)
    .sort((a, b) => b.length - a.length); // longest first, avoids partial overlaps

  all.forEach((term) => {
    const escapedTerm = escapeHtml(term);
    if (!escapedTerm.trim()) return;
    const pattern = escapedTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(pattern, "gi");
    html = html.replace(re, (match) => `<mark>${match}</mark>`);
  });
  return html;
}

// What the smart spelling fix changed, so nothing is altered silently.
function correctionsBlock(job) {
  if (!job.corrections || !job.corrections.length) return "";
  const items = job.corrections
    .map((c) => `<li><span class="fix-from">${escapeHtml(c.from)}</span> &rarr; <strong>${escapeHtml(c.to)}</strong></li>`)
    .join("");
  return block(
    t("correctionsHeading"),
    `<p class="field-hint">These words were corrected from context. If one is wrong, use Edit on the transcript above.</p><ul>${items}</ul>`
  );
}

function downloadUrl(reportId, name) {
  return `${API_BASE}/api/download/${reportId}${name ? `?name=${encodeURIComponent(name)}` : ""}`;
}

function triggerDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

const EXPORT_LABELS = { pdf: "PDF", docx: "Word (.docx)", jpeg: "Image" };

// Links to files already made for this job (so a finished download can be fetched again).
function renderDownloads(job) {
  const row = $("#downloads-row");
  const links = [];
  const add = (id, label) => {
    if (id) links.push(`<a class="download-link" href="${downloadUrl(id)}" download>&darr; ${label}</a>`);
  };
  add(job.pdf_report_id, "PDF");
  add(job.docx_report_id, "Word (.docx)");
  add(job.image_report_id, "Image");
  (job.exports || []).forEach((exp) => add(exp.report_id, EXPORT_LABELS[exp.format] || exp.format));
  row.innerHTML = links.join("");
}

function renderResults(job) {
  currentJob = job;
  const isText = job.mode === "tts";
  const isFull = job.mode === "full";
  const hasAnalysis = isFull || isText;
  $("#results-title").textContent = isText
    ? t("resultsTitleText")
    : isFull
      ? t("resultsTitleFull")
      : t("resultsTitleTranscript");

  $("#detected-lang").textContent = isText
    ? `Language: English  ·  ${(job.word_count || 0).toLocaleString()} words`
    : "Language: English";
  if (job.noise_reduction_applied) {
    $("#detected-lang").textContent += "  ·  🔉 noise reduction applied";
  }

  // "How this was made" — model, duration, word count. Worth seeing when
  // a transcript looks off, since a small/local model on noisy or
  // non-English audio is the single most common cause.
  const madeWithParts = [];
  if (!isText) {
    if (job.transcription_model) madeWithParts.push(job.transcription_model);
    if (job.audio_duration_seconds) {
      const m = Math.floor(job.audio_duration_seconds / 60);
      const s = Math.round(job.audio_duration_seconds % 60);
      madeWithParts.push(m > 0 ? `${m}m ${s}s of audio` : `${s}s of audio`);
    }
    if (job.word_count) madeWithParts.push(`${job.word_count} words transcribed`);
  }
  if (madeWithParts.length) {
    $("#made-with-line").textContent = madeWithParts.join("  ·  ");
    $("#made-with-line").hidden = false;
  } else {
    $("#made-with-line").hidden = true;
  }

  const highlightTerms = {
    dates: job.dates_mentioned || [],
    links: job.links_mentioned || [],
    notable: job.notable_terms || [],
  };

  // The order, top to bottom: the word-for-word transcript (or whole text), summary, key points,
  // AI insights, highlights — and then, below all of it, the downloads.
  let html = renderTranscriptBlock(job, highlightTerms, isText);
  if (!isText) html += correctionsBlock(job);

  if (hasAnalysis) {
    if (job.summary) {
      html += block(
        `${t("summaryHeading")} (~${job.summary_word_target} words)`,
        `${isText ? speakRow("summary") : ""}${isText ? `<p data-sentences="summary">${sentenceHtml(job.summary, {})}</p>` : `<p>${escapeHtml(job.summary)}</p>`}`
      );
    }
    if (job.key_points?.length) html += block(t("keyPointsHeading"), bulletList(job.key_points));

    if (job.ai_insights) html += block(t("aiInsightsHeading"), `<p>${escapeHtml(job.ai_insights)}</p>`);

    const hasHighlights = (job.dates_mentioned?.length || job.links_mentioned?.length || job.notable_terms?.length);
    if (hasHighlights) {
      let inner = "";
      if (job.dates_mentioned?.length) inner += `<p><strong>${t("datesHeading")}:</strong></p>${bulletList(job.dates_mentioned)}`;
      if (job.links_mentioned?.length) inner += `<p><strong>${t("linksHeading")}:</strong></p>${linkify(job.links_mentioned)}`;
      if (job.notable_terms?.length) inner += `<p><strong>${t("notableTermsHeading")}:</strong></p>${bulletList(job.notable_terms)}`;
      html += block(t("highlightsHeading"), inner);
    }
  }

  // Surface any export that failed, so a missing download is explained
  // rather than silently absent.
  if (job.warnings && job.warnings.length) {
    html += `<div class="result-block"><h3>notes</h3><ul>${job.warnings
      .map((w) => `<li>${escapeHtml(w)}</li>`)
      .join("")}</ul></div>`;
  }

  $("#results-body").innerHTML = html;
  $("#reanalyze-prompt").hidden = true; // reset on every fresh render; a save handler re-shows it when relevant
  wireTranscriptEditing();
  if (isText) wireSpeakers(job);
  renderDownloads(job);
  renderAudioDownloads(job);
  $("#btn-back-to-history").hidden = !viewingFromHistory;
  showView("results");
  refreshAccount();
}

// ---------- Text to Audio results: the speaker icons ----------
const ttsVoice = { script: null, summary: null };

function speechUrl(job, part, voiceId) {
  const key = `speech|${job.id}|${job.updated_at}|${part}|${voiceId}`;
  if (blobUrlCache.has(key)) return Promise.resolve(blobUrlCache.get(key));
  return (async () => {
    const formData = new FormData();
    formData.append("part", part);
    formData.append("voice_id", voiceId);
    const res = await apiFetch(`/api/jobs/${job.id}/speech`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(await errorDetail(res, "Couldn't create the audio."));
    const { report_id } = await res.json();
    const url = await fetchBlobUrl(`report|${report_id}`, `/api/download/${report_id}`);
    blobUrlCache.set(key, url);
    return url;
  })();
}

function wireSpeakers(job) {
  const start = job.voice_id || defaultVoiceId;
  ttsVoice.script = start;
  ttsVoice.summary = start;

  document.querySelectorAll("[data-speed]").forEach((sel) => {
    sel.value = String(playbackSpeed);
    sel.addEventListener("change", () => setSpeed(parseFloat(sel.value)));
  });

  ["script", "summary"].forEach((part) => {
    const btn = document.querySelector(`[data-speak="${part}"]`);
    if (!btn) return;
    const stop = document.querySelector(`[data-stop="${part}"]`);
    if (stop) stop.addEventListener("click", stopPlayback);
    bindAudioButton(
      btn,
      ICON_SPEAKER,
      () => `speech|${job.id}|${part}|${ttsVoice[part]}`,
      () => speechUrl(job, part, ttsVoice[part]),
      {
        pausable: true,
        hooks: makeKaraoke(part),
        onState: (state) => {
          if (stop) stop.hidden = state === "idle" || state === "loading";
        },
      }
    );
  });

  // The drop-downs need the voice list; the speaker buttons above already work with the chosen voice.
  ensureVoices()
    .then(() => {
      if (currentJob !== job) return; // the person has moved on
      ["script", "summary"].forEach((part) => {
        const mount = document.querySelector(`[data-voice-mount="${part}"]`);
        const btn = document.querySelector(`[data-speak="${part}"]`);
        if (!mount || !btn) return;
        createVoicePicker(mount, {
          value: ttsVoice[part],
          onChange: (id) => {
            const state = btn.dataset.state;
            ttsVoice[part] = id;
            if (state === "playing" || state === "paused") {
              stopPlayback();
              if (state === "playing") btn.click(); // carry on in the new accent
            }
          },
        });
      });
    })
    .catch((err) => showError(err.message || "Couldn't load the list of voices."));
}

// ---------- Text to Audio results: download the audio in many accents ----------
function audioBox(target, title, ordered, chosenId, note) {
  const options = ordered
    .map((v) => {
      const isChosen = v.id === chosenId;
      return `<label class="accent-option"><input type="checkbox" data-voice="${escapeHtml(v.id)}"${isChosen ? " checked" : ""}> <span>${escapeHtml(voiceLabel(v))}${isChosen ? ' <em class="chosen-tag">your choice</em>' : ""}</span></label>`;
    })
    .join("");
  return `
    <div class="audio-box" data-target="${target}">
      <h4>${title}</h4>
      ${note ? `<p class="field-hint">${note}</p>` : ""}
      <label class="select-all"><input type="checkbox" data-select-all> <span>Select all accents</span></label>
      <div class="accent-grid">${options}</div>
      <div class="audio-box-actions">
        <button type="button" class="btn btn-primary" data-download-audio></button>
        <span class="field-hint" data-audio-status></span>
      </div>
    </div>`;
}

async function renderAudioDownloads(job) {
  const card = $("#audio-downloads-card");
  card.hidden = job.mode !== "tts";
  if (card.hidden) return;
  const body = $("#audio-downloads-body");
  body.innerHTML = `<p class="field-hint">Loading voices…</p>`;
  try {
    await ensureVoices();
  } catch {
    body.innerHTML = `<p class="field-hint">Couldn't load the list of voices — reload the page to try again.</p>`;
    return;
  }
  if (currentJob !== job) return; // the person has moved on

  const chosenId = voiceById(job.voice_id) ? job.voice_id : defaultVoiceId;
  // The accent chosen earlier comes first (and is ticked); every other accent follows.
  const ordered = [voiceById(chosenId), ...voiceCatalog.filter((v) => v.id !== chosenId)].filter(Boolean);
  let html = audioBox("script", "Whole text audio", ordered, chosenId);
  if (job.summary) {
    html += audioBox("summary", "Summary audio", ordered, chosenId);
    html += audioBox(
      "both",
      "Summary + whole text (one MP3)",
      ordered,
      chosenId,
      "The summary is read first, then the whole text, in a single file per accent."
    );
  }
  body.innerHTML = html;

  body.querySelectorAll(".audio-box").forEach((box) => wireAudioBox(job, box));
}

function wireAudioBox(job, box) {
  const target = box.dataset.target;
  const boxes = () => [...box.querySelectorAll("input[data-voice]")];
  const button = box.querySelector("[data-download-audio]");
  const status = box.querySelector("[data-audio-status]");
  const selectAll = box.querySelector("[data-select-all]");

  const refresh = () => {
    const n = boxes().filter((b) => b.checked).length;
    button.disabled = n === 0;
    button.textContent = n === 0 ? "Tick an accent to download" : n === 1 ? "Download audio (MP3)" : `Download ${n} accents (ZIP)`;
    selectAll.checked = n === boxes().length;
  };
  box.addEventListener("change", (e) => {
    if (e.target === selectAll) boxes().forEach((b) => (b.checked = selectAll.checked));
    refresh();
  });
  refresh();

  button.addEventListener("click", () => {
    const ids = boxes().filter((b) => b.checked).map((b) => b.dataset.voice);
    if (ids.length) downloadAudioBundle(job, target, ids, button, status);
  });
}

function waitForBundle(bundleId, onProgress) {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const res = await apiFetch(`/api/bundles/${bundleId}`);
        if (!res.ok) throw new Error(await errorDetail(res, "Lost track of that download."));
        const state = await res.json();
        if (state.status === "done") return resolve(state);
        if (state.status === "error") return reject(new Error(state.error || "Couldn't create the audio."));
        onProgress(state);
        setTimeout(tick, 1200);
      } catch (err) {
        reject(err);
      }
    };
    tick();
  });
}

async function downloadAudioBundle(job, target, ids, button, status) {
  button.disabled = true;
  status.textContent = "Starting…";
  try {
    const formData = new FormData();
    formData.append("target", target);
    formData.append("voices", ids.join(","));
    const res = await apiFetch(`/api/jobs/${job.id}/audio-bundle`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(await errorDetail(res, "Couldn't start that download."));
    const { bundle_id } = await res.json();

    const result = await waitForBundle(bundle_id, (s) => {
      status.textContent = `Making the audio… ${s.done} of ${s.total} accents done (long texts take a while)`;
    });

    const base = target === "script" ? "whole-text" : target === "both" ? "summary-and-text" : "summary";
    const name = ids.length === 1 ? `${base}-${voiceById(ids[0]).label}` : `${base}-audio-${ids.length}-accents`;
    const url = downloadUrl(result.report_id, name);
    triggerDownload(url);
    status.innerHTML = `Ready — <a href="${escapeHtml(url)}" download>download again</a>`;
  } catch (err) {
    status.textContent = "";
    showError(err.message || "Couldn't create the audio.");
  } finally {
    button.disabled = false;
  }
}

// ---------- editable transcript ----------
function wireTranscriptEditing() {
  const editBtn = $("#btn-edit-transcript");
  if (!editBtn) return; // no transcript block rendered (shouldn't happen, but don't crash if so)

  editBtn.addEventListener("click", () => {
    $("#transcript-edit-textarea").value = currentJob.transcript || "";
    document.querySelectorAll("[data-transcript-view]").forEach((p) => (p.hidden = true));
    $("#transcript-edit-area").hidden = false;
    editBtn.hidden = true;
    $("#transcript-edit-textarea").focus();
  });

  $("#btn-cancel-edit").addEventListener("click", () => {
    $("#transcript-edit-area").hidden = true;
    editBtn.hidden = false;
    document.querySelectorAll("[data-transcript-view]").forEach((p) => (p.hidden = false));
  });

  $("#btn-save-edit").addEventListener("click", async () => {
    const saveBtn = $("#btn-save-edit");
    saveBtn.disabled = true;

    const formData = new FormData();
    formData.append("transcript", $("#transcript-edit-textarea").value);

    try {
      const res = await apiFetch(`/api/jobs/${currentJob.id}/transcript`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(await errorDetail(res, "Couldn't save the edit."));
      const updatedJob = await res.json();
      const hasSummary = updatedJob.mode !== "transcribe";
      renderResults(updatedJob); // re-renders everything, including re-wiring this same editor
      if (hasSummary) $("#reanalyze-prompt").hidden = false;
    } catch (err) {
      showError(err.message || "Couldn't save the edit.");
    } finally {
      saveBtn.disabled = false;
    }
  });
}

$("#btn-reanalyze").addEventListener("click", async () => {
  if (!currentJob) return;
  const btn = $("#btn-reanalyze");
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = "…";

  const formData = new FormData();
  formData.append("summary_words", currentJob.summary_word_target || 70);
  formData.append("include_key_points", true);
  formData.append("include_highlights", true);
  formData.append("include_ai_insights", true);

  try {
    const res = await apiFetch(`/api/jobs/${currentJob.id}/reanalyze`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(await errorDetail(res, "Couldn't re-run the summary."));
    const { job_id } = await res.json();
    pollReanalysis(job_id);
  } catch (err) {
    showError(err.message || "Couldn't re-run the summary.");
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});

// Polls quietly in place on the results page — unlike pollJob(), it never
// navigates away on error, since the user is actively looking at (and may
// still want to re-edit) the transcript they just corrected.
function pollReanalysis(jobId) {
  const tick = async () => {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}`);
      if (!res.ok) throw new Error("Lost track of that job.");
      const job = await res.json();
      if (job.status === "done") {
        renderResults(job);
      } else if (job.status === "error") {
        showError(job.error || "Couldn't re-run the summary.");
        $("#btn-reanalyze").disabled = false;
        $("#btn-reanalyze").textContent = t("reanalyzeButton");
      } else {
        setTimeout(tick, 1200);
      }
    } catch (err) {
      showError(err.message || "Lost connection while re-running the summary.");
      $("#btn-reanalyze").disabled = false;
      $("#btn-reanalyze").textContent = t("reanalyzeButton");
    }
  };
  tick();
}

// ---------- downloads at the bottom: PDF / Word / Image, made on demand ----------
document.querySelectorAll("[data-export]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!currentJob) return;
    const format = btn.dataset.export;
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Preparing…";

    try {
      const formData = new FormData();
      formData.append("format", format);
      const res = await apiFetch(`/api/jobs/${currentJob.id}/export`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(await errorDetail(res, "Couldn't generate that download."));
      const data = await res.json();

      currentJob.exports = currentJob.exports || [];
      currentJob.exports.push({ format: data.format, report_id: data.report_id, created_at: "" });
      renderDownloads(currentJob);
      triggerDownload(downloadUrl(data.report_id));
    } catch (err) {
      showError(err.message || "Couldn't generate that download.");
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  });
});

// ---------- history ----------
function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

async function loadHistory() {
  const list = $("#history-list");
  list.innerHTML = `<p class="history-empty">Loading…</p>`;
  try {
    const res = await apiFetch(`/api/jobs?limit=30`);
    if (!res.ok) throw new Error("Couldn't load history.");
    const data = await res.json();

    if (!data.jobs.length) {
      list.innerHTML = `<p class="history-empty">No jobs yet — run a transcription and it'll show up here.</p>`;
      return;
    }

    list.innerHTML = data.jobs
      .map((job) => {
        const modeLabel =
          job.mode === "full" ? t("resultsTitleFull") : job.mode === "tts" ? t("resultsTitleText") : t("resultsTitleTranscript");
        const canView = job.status === "done";
        return `
          <div class="history-card" data-id="${job.id}">
            <div class="history-meta">
              <span class="history-name">${escapeHtml(job.filename || "recording")}</span>
              <span class="history-sub">${modeLabel} · ${formatDate(job.created_at)}</span>
            </div>
            <div class="history-actions">
              <span class="history-status ${job.status}">${job.status === "not_english" ? "not English" : job.status}</span>
              ${canView ? `<button type="button" class="btn btn-outline btn-view-job">View</button>` : ""}
              <button type="button" class="btn btn-text btn-delete-job">Delete</button>
            </div>
          </div>`;
      })
      .join("");

    list.querySelectorAll(".btn-view-job").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.closest(".history-card").dataset.id;
        viewJob(id);
      });
    });
    list.querySelectorAll(".btn-delete-job").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const id = e.target.closest(".history-card").dataset.id;
        if (!confirm("Delete this job from history? This can't be undone.")) return;
        try {
          await apiFetch(`/api/jobs/${id}`, { method: "DELETE" });
          loadHistory();
        } catch (err) {
          showError(err.message || "Couldn't delete that job.");
        }
      });
    });
  } catch (err) {
    list.innerHTML = `<p class="history-empty">Couldn't load history.</p>`;
  }
}

async function viewJob(id) {
  try {
    const res = await apiFetch(`/api/jobs/${id}`);
    if (!res.ok) throw new Error("Couldn't load that job.");
    const job = await res.json();
    viewingFromHistory = true;
    renderResults(job);
  } catch (err) {
    showError(err.message || "Couldn't load that job.");
  }
}
