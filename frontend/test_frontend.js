#!/usr/bin/env node
/**
 * Frontend regression tests — run with:  node frontend/test_frontend.js
 *
 * No dependencies, no browser needed — static checks over the source files, so
 * they run anywhere node does (including a Colab cell).
 *
 * Test 1 guards a real bug that shipped: elements toggled with the `hidden`
 * attribute stayed permanently visible, because author CSS setting
 * `display: flex` silently overrides the browser's built-in
 * `[hidden] { display: none }` rule.
 */
const fs = require("fs");
const path = require("path");

const DIR = __dirname;
const html = fs.readFileSync(path.join(DIR, "index.html"), "utf8");
const css = fs.readFileSync(path.join(DIR, "styles.css"), "utf8");
const appJs = fs.readFileSync(path.join(DIR, "app.js"), "utf8");
const { I18N, t } = require(path.join(DIR, "i18n.js"));

let failures = 0;
function check(name, passed, detail) {
  if (passed) {
    console.log(`  PASS  ${name}`);
  } else {
    console.log(`  FAIL  ${name}${detail ? "\n        " + detail : ""}`);
    failures++;
  }
}

console.log("\n1. The `hidden` attribute must actually hide things");
check(
  "styles.css contains a global [hidden] { display: none !important }",
  /\[hidden\]\s*\{[^}]*display:\s*none\s*!important/.test(css),
  "Without this, .recording-panel/.file-ready/.modal-overlay stay visible forever."
);

console.log("\n2. Every id app.js reaches for exists in index.html");
const idsUsed = [...appJs.matchAll(/\$\("#([\w-]+)"\)/g)].map((m) => m[1]);
// Some elements (the transcript edit box) are built by app.js when results render,
// so ids written inside app.js's own HTML templates count as defined too.
const idsDefined = new Set([
  ...[...html.matchAll(/id="([\w-]+)"/g)].map((m) => m[1]),
  ...[...appJs.matchAll(/id="([\w-]+)"/g)].map((m) => m[1]),
]);
const missingIds = [...new Set(idsUsed)].filter((id) => !idsDefined.has(id));
check("no missing element ids", missingIds.length === 0, `Missing: ${missingIds.join(", ")}`);

console.log("\n3. English only: no language choices anywhere in the page");
check("no <select> elements for languages", !/<select[^>]*(language|lang)[^>]*>/i.test(html));
check("no interface-language picker or nav button", !/lang-modal|nav-language|lang-grid|lang-all/.test(html));
check("page text doesn't offer other languages", !/translate to|spoken language|detect automatically|any language|native script/i.test(html));
check(
  "page says English audio only",
  /English audio only/.test(html)
);
check(
  "app.js doesn't send any language fields to the server",
  !/append\("(source_language|target_language|output_language|language)"/.test(appJs)
);
check("app.js doesn't call the removed /api/languages endpoint", !/api\/languages/.test(appJs));

console.log("\n4. Non-English audio gets a clear message and a way back");
check("a dedicated 'not English' screen exists", /id="view-not-english"/.test(html) && /id="not-english-message"/.test(html));
check("it has a button back to the start", /id="btn-not-english-back"/.test(html));
check("polling handles the not_english status", /job\.status === "not_english"/.test(appJs));
check(
  "that status shows the server's message and the not-English screen",
  /not-english-message"\)\.textContent\s*=[\s\S]{0,160}job\.error[\s\S]{0,260}showView\("notEnglish"\)/.test(appJs)
);
check(
  "the back button returns to the upload page and clears the old file",
  /function goBackToStart\(\)[\s\S]{0,300}currentFile = null[\s\S]{0,200}showView\("upload"\)/.test(appJs) &&
    /btn-not-english-back"\)\.addEventListener\("click", goBackToStart\)/.test(appJs)
);
check("polling stops after a not_english result", /not_english"\)\s*\{[\s\S]{0,400}return;\s*\/\/ stop polling/.test(appJs));

console.log("\n5. Every t(\"key\") used in app.js has an English string");
const tKeys = [...new Set([...appJs.matchAll(/\bt\("([A-Za-z]+)"\)/g)].map((m) => m[1]))];
const missingKeys = tKeys.filter((k) => !(k in I18N));
check(`all ${tKeys.length} keys defined`, missingKeys.length === 0, `Missing: ${missingKeys.join(", ")}`);
check("t() falls back to the key itself rather than 'undefined'", t("noSuchKey") === "noSuchKey");

console.log("\n6. Storage failures can't break the page");
check("API key access is guarded", /getStoredKey = \(\) => \{[\s\S]{0,250}catch/.test(appJs));

console.log("\n7. Paste an audio file (Ctrl+V) — run the real code from app.js against a fake page");
{
  // Pull the paste block out of app.js and run it with stand-ins for the page, so this tests the
  // actual shipped code, not a copy of it.
  const start = appJs.indexOf("// ---------- paste an audio file");
  const end = appJs.indexOf('$("#btn-change-file")');
  check("the paste block exists in app.js", start > 0 && end > start);

  function makePage({ uploadHidden = false, recordingHidden = true } = {}) {
    const calls = { setFile: [], errors: [], prevented: 0 };
    let handler = null;
    const fakeDocument = { addEventListener: (type, fn) => { if (type === "paste") handler = fn; } };
    const $ = (sel) => (sel === "#recording-panel" ? { hidden: recordingHidden } : {});
    const views = { upload: { hidden: uploadHidden } };
    const setFile = (file, name) => calls.setFile.push({ file, name });
    const showError = (m) => calls.errors.push(m);
    new Function("document", "$", "views", "setFile", "showError", "File", appJs.slice(start, end))(
      fakeDocument, $, views, setFile, showError, File
    );
    const paste = (files) =>
      handler({ clipboardData: { files }, preventDefault: () => calls.prevented++ });
    return { calls, paste };
  }

  {
    const { calls, paste } = makePage();
    const f = new File(["x"], "meeting.mp3", { type: "audio/mpeg" });
    paste([f]);
    check("a pasted mp3 is picked up automatically and keeps its name",
      calls.setFile.length === 1 && calls.setFile[0].file === f && calls.setFile[0].name === "meeting.mp3");
  }
  {
    const { calls, paste } = makePage();
    paste([new File(["x"], "", { type: "audio/ogg" })]);
    const got = calls.setFile[0];
    check("a pasted clip with no name gets a usable one (the server picks the decoder from it)",
      got && got.name === "pasted-audio.ogg" && got.file.name === "pasted-audio.ogg");
  }
  {
    const { calls, paste } = makePage();
    paste([new File(["x"], "voice-note.opus", { type: "" })]);
    check("an audio file whose type is blank is still recognised by its extension",
      calls.setFile.length === 1 && calls.setFile[0].name === "voice-note.opus");
  }
  {
    const { calls, paste } = makePage();
    paste([new File(["x"], "photo.png", { type: "image/png" })]);
    check("a pasted non-audio file is refused with a clear message",
      calls.setFile.length === 0 && calls.errors.length === 1 && /audio file/i.test(calls.errors[0]));
  }
  {
    const { calls, paste } = makePage();
    paste([]);
    check("pasting plain text is left completely alone", calls.setFile.length === 0 && calls.errors.length === 0 && calls.prevented === 0);
  }
  {
    const { calls, paste } = makePage({ uploadHidden: true });
    paste([new File(["x"], "a.mp3", { type: "audio/mpeg" })]);
    check("ignored once you are past the first page", calls.setFile.length === 0);
  }
  {
    const { calls, paste } = makePage({ recordingHidden: false });
    paste([new File(["x"], "a.mp3", { type: "audio/mpeg" })]);
    check("ignored while a recording is in progress", calls.setFile.length === 0);
  }
  check("the page tells people they can paste", /id="paste-hint"/.test(html) && /<kbd>Ctrl<\/kbd>\+<kbd>V<\/kbd>/.test(html));
}

console.log("\n8. The page must never be blank (a real phone report)");
check(
  "Google Fonts doesn't block the page from painting",
  !/<link[^>]*rel="stylesheet"[^>]*href="https:\/\/fonts\.googleapis[^>]*>/.test(html.replace(/<noscript>[\s\S]*?<\/noscript>/g, "")) ||
    /media="print"[^>]*onload="this\.media='all'"[^>]*href="https:\/\/fonts\.googleapis/.test(html) ||
    /<link[^>]*media="print"[^>]*fonts\.googleapis/.test(html),
  "A render-blocking font stylesheet leaves a white page on slow/restricted networks."
);
check("fonts have system fallbacks", /--font-body:[^;]*system-ui/.test(css) && /--font-display:[^;]*Georgia/.test(css));
check(
  "a visible error banner is wired up BEFORE app.js, so a script failure isn't silent",
  /id="fatal-error"/.test(html) &&
    html.indexOf('addEventListener("error"') > 0 &&
    html.indexOf('addEventListener("error"') < html.indexOf('<script src="app.js">')
);
check("a no-JavaScript message exists", /<noscript>/.test(html));
check("the first page (the two-button home page) is visible without any JavaScript", /id="view-home"/.test(html) && !/id="view-home"[^>]*hidden/.test(html));

console.log("\n9. AI insights options only appear when an AI model is configured");
check("the page asks the server (/api/health) what is available", /api\/health[\s\S]{0,200}ai_insights/.test(appJs));
check(
  "when AI insights are off, their checkbox and the context field are hidden and unchecked",
  /ai_insights === false[\s\S]{0,400}opt-insights"\)\.checked = false[\s\S]{0,200}insights-row"\)\.hidden = true[\s\S]{0,200}context-label"\)\.hidden = true/.test(appJs)
);
check("AI insights are only shown when the job actually has them", /if \(job\.ai_insights\) html \+= block\(t\("aiInsightsHeading"\)/.test(appJs));


console.log("\n10. Home page: Audio to Text / Text to Audio");
check("home has exactly the two tool buttons", /id="home-audio-to-text"/.test(html) && /id="home-text-to-audio"/.test(html));
check("both buttons are wired", /home-audio-to-text"\)\.addEventListener/.test(appJs) && /home-text-to-audio"\)\.addEventListener/.test(appJs));
check("every view in the page is registered in app.js", [...html.matchAll(/id="view-([\w-]+)"/g)].every((m) => appJs.includes(`#view-${m[1]}`)));

console.log("\n11. Summary length is ONE drop-down (30/50/70/100/custom) on both pages");
check("the old 50/70/100 radio buttons are gone", !/name="summary-words"/.test(html));
for (const id of ["opt-summary-select", "txt-summary-select"]) {
  const sel = html.match(new RegExp(`<select id="${id}"[\\s\\S]*?</select>`));
  const values = sel ? [...sel[0].matchAll(/value="(\w+)"/g)].map((m) => m[1]) : [];
  check(`#${id} offers 30, 50, 70, 100 and custom`, values.join(",") === "30,50,70,100,custom", values.join(","));
}
check("custom boxes exist, hidden until 'custom' is chosen", /id="opt-summary-custom"[^>]*hidden/.test(html) && /id="txt-summary-custom"[^>]*hidden/.test(html));
check("a custom length outside 10-500 is refused", /n < 10 \|\| n > 500/.test(appJs));

console.log("\n12. Downloads sit at the bottom, in English: PDF, Word, Image only");
check("no 'downloadable as' checkboxes on the option pages", !/<legend>downloadable as/.test(html) && !/id="opt-pdf"/.test(html));
check("download card comes after the results body and before the Restart/Previous buttons",
  html.indexOf('id="results-body"') < html.indexOf('id="downloads-card"') &&
  html.indexOf('id="downloads-card"') < html.indexOf('id="btn-restart"'));
const exportFormats = [...html.matchAll(/data-export="(\w+)"/g)].map((m) => m[1]);
check("export buttons are exactly pdf, docx, jpeg", exportFormats.join(",") === "pdf,docx,jpeg", exportFormats.join(","));
check("every results page ends with Restart and Previous page buttons", /id="btn-restart"/.test(html) && /id="btn-previous"/.test(html) &&
  html.indexOf('id="btn-restart"') > html.indexOf('id="audio-downloads-card"'));
check("results order: transcript, summary, key points, AI insights, highlights",
  (() => {
    const i = (s) => appJs.indexOf(s);
    return i("renderTranscriptBlock(job, highlightTerms, isText)") < i("t(\"summaryHeading\")") &&
      i("t(\"summaryHeading\")") < i("t(\"keyPointsHeading\")") &&
      i("t(\"keyPointsHeading\")") < i("t(\"aiInsightsHeading\")") &&
      i("t(\"aiInsightsHeading\")") < i("t(\"highlightsHeading\")");
  })());

console.log("\n13. Text to Audio: input page");
check("write/paste and upload (PDF, Word, image) tabs exist", /id="tab-write"/.test(html) && /id="tab-file"/.test(html));
check("upload accepts pdf, docx and images", /accept="[^"]*\.pdf[^"]*\.docx[^"]*image\/\*/.test(html));
check("a 'Paste from clipboard' button exists", /id="btn-paste-clip"/.test(html));
check("uploaded files are read by the server and shown for checking", /api\/extract-text/.test(appJs));

console.log("\n14. Text to Audio: voices");
check("the voice drop-down has a ▶ sample button per voice", /className = "vp-play"/.test(appJs) && /api\/tts\/preview\//.test(appJs));
check("voice picker is on the options page and next to the speaker icons", /id="txt-voice-picker"/.test(html) && /data-voice-mount/.test(appJs));
check("speaker icons exist for the whole text and the summary", /speakRow\("script"\)/.test(appJs) && /speakRow\("summary"\)/.test(appJs));
check("the summary's speaker comes straight after its title", /summaryHeading"\)\} \(~\$\{job\.summary_word_target\} words\)`,\s*`\$\{isText \? speakRow\("summary"\)/.test(appJs));

console.log("\n15. Text to Audio: audio downloads");
check("audio can be downloaded for the whole text AND the summary, per accent",
  /audioBox\("script"/.test(appJs) && /audioBox\("summary"/.test(appJs) && /type="checkbox" data-voice=/.test(appJs));
check("the previously chosen accent is listed first and ticked",
  /\[voiceById\(chosenId\), \.\.\.voiceCatalog\.filter\(\(v\) => v\.id !== chosenId\)\]/.test(appJs) && /isChosen \? " checked"/.test(appJs));
check("there is a Select all box", /data-select-all/.test(appJs));

console.log("\n16. Behaviour (real code from app.js with stand-ins)");
{
  // readSummaryWords
  const start = appJs.indexOf("function readSummaryWords");
  const end = appJs.indexOf("// ---------- navigation ----------");
  function run(value, custom) {
    const errors = [];
    const els = { "#s": { value }, "#c": { value: custom, focus() {} } };
    const fn = new Function("$", "showError", appJs.slice(start, end) + "; return readSummaryWords;")(
      (sel) => els[sel], (m) => errors.push(m));
    return { result: fn("#s", "#c"), errors };
  }
  check("a listed length is returned as a number", run("30", "").result === 30);
  check("custom 150 is accepted", run("custom", "150").result === 150);
  check("custom 5 is refused with a message", (() => { const r = run("custom", "5"); return r.result === null && r.errors.length === 1; })());
  check("custom blank is refused", run("custom", "").result === null);
}
{
  // text counter source for the playback manager: only one thing plays at a time
  const start = appJs.indexOf("function stopPlayback");
  const end = appJs.indexOf("// Turns a <button> into a play / stop control");
  const states = [];
  const code = "let activePlayback = null; let playbackSpeed = 1; const showError = () => {}; const requestAnimationFrame = () => 0; const cancelAnimationFrame = () => {}; " + appJs.slice(start, end) +
    "; return { startPlayback, stopPlayback, togglePause, setSpeed: (v) => { playbackSpeed = v; }, get active() { return activePlayback; } };";
  class FakeAudio { constructor(u) { this.u = u; this.l = {}; this.paused = false; this.playbackRate = 1; this.duration = 10; this.currentTime = 0; }
    addEventListener(t, f) { this.l[t] = f; } pause() { this.paused = true; } play() { this.paused = false; return Promise.resolve(); } }
  const api = new Function("Audio", code)(FakeAudio);
  api.startPlayback("a", "k1", (s) => states.push("1:" + s));
  api.startPlayback("b", "k2", (s) => states.push("2:" + s));
  check("starting a second sound stops the first", states.join() === "1:playing,1:idle,2:playing", states.join());
  // pause / resume keeps the sound loaded; stop clears it
  api.togglePause();
  check("pause marks it paused and keeps the sound", states[states.length - 1] === "2:paused" && api.active && api.active.audio.paused);
  api.togglePause();
  check("resume plays again", states[states.length - 1] === "2:playing" && !api.active.audio.paused);
  api.setSpeed(1.5);
  api.startPlayback("c", "k3", () => {});
  check("a new sound starts at the chosen speed", api.active.audio.playbackRate === 1.5);
  api.startPlayback("b", "k2", (s) => states.push("2:" + s));
  api.stopPlayback();
  check("stop returns to idle", states[states.length - 1] === "2:idle" && api.active === null);
}

console.log("\n17. Pause/resume, speed, karaoke highlight");
check("the speaker icon is pausable and has a stop button", /pausable: true/.test(appJs) && /data-stop=/.test(appJs));
check("speed choices are 0.75x to 1.5x and are remembered", /<option value="0\.75">/.test(appJs) && /<option value="1\.5">/.test(appJs) && /savedSet\("ts_speed"/.test(appJs));
check("both the whole text and the summary can light up sentences", /data-sentences="script"/.test(appJs) && /data-sentences="summary"/.test(appJs));
{
  const start = appJs.indexOf("function splitSentences");
  const end = appJs.indexOf("function sentenceHtml");
  const split = new Function(appJs.slice(start, end) + "; return splitSentences;")();
  for (const text of ["Hello there. How are you? Fine!\nNew line here.  Trailing", "...Starts with dots.", "No punctuation at all", "Quote: \"Yes.\" Then (more.) end.", "a\n\n\nb. c"]) {
    check(`splitting never loses a character: ${JSON.stringify(text.slice(0, 24))}`, split(text).join("") === text);
  }
  check("three sentences become three pieces", split("One. Two. Three.").length === 3);
}
{
  const start = appJs.indexOf("function makeKaraoke");
  const end = appJs.indexOf("// The speaker icon with the accent drop-down");
  const classes = new Map();
  const els = ["First sentence here. ", "Second one. ", "Third sentence is the longest of them all. "].map((text, i) => ({
    textContent: text,
    classList: { add: (c) => classes.set(i, c), remove: () => classes.delete(i) },
    scrollIntoView() {},
  }));
  const makeKaraoke = new Function("document", appJs.slice(start, end) + "; return makeKaraoke;")({ querySelectorAll: () => els });
  const k = makeKaraoke("script");
  k.onTick(0.01);
  check("start of the audio lights the first sentence", classes.get(0) === "speaking" && classes.size === 1);
  k.onTick(0.99);
  check("end of the audio lights the last sentence (and only it)", classes.get(2) === "speaking" && classes.size === 1);
  k.onStop();
  check("stopping clears the highlight", classes.size === 0);
}

console.log("\n18. Remember my voice");
check("a remember box exists on the options page, ticked by default", /id="txt-remember" checked/.test(html));
check("the remembered voice is used only if it still exists", /voiceById\(saved\) \? saved : defaultVoiceId/.test(appJs));
check("unticking forgets the voice", /savedRemove\("ts_voice"\)/.test(appJs));
{
  const start = appJs.indexOf("const _memStore");
  const end = appJs.indexOf("async function apiFetch");
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  const api = new Function("localStorage", appJs.slice(start, end) + "; return { savedGet, savedSet, savedRemove };")(blocked);
  api.savedSet("ts_voice", "india-3");
  check("blocked browser storage falls back to memory without errors", api.savedGet("ts_voice") === "india-3");
  api.savedRemove("ts_voice");
  check("...and forgetting works there too", api.savedGet("ts_voice") === null);
}

console.log("\n19. Summary + whole text as one MP3");
check("a combined-audio box exists for the 'both' target", /audioBox\(\s*"both"/.test(appJs));

console.log("\n20. Speaker labels");
check("both option pages have a speaker-label box", /id="opt-speakers"/.test(html) && /id="opt-speakers-transcribe"/.test(html));
check("the box is greyed out when the server has no diarization", /data\.diarization === false/.test(appJs) && /\.disabled = true/.test(appJs));
check("the flag is sent to the server", /append\("label_speakers"/.test(appJs));
{
  const start = appJs.indexOf("function labeledHtml");
  const end = appJs.indexOf("function renderTranscriptBlock");
  const highlight = (t) => t;
  const f = new Function("highlightTranscript", "escapeHtml", appJs.slice(start, end) + "; return labeledHtml;")(highlight, (x) => x);
  const out = f("Speaker 1: Hello.\n\nSpeaker 2: Hi there.", {});
  check("each speaker turn is its own line with a bold label", (out.match(/class="spk-turn"/g) || []).length === 2 && out.includes('<strong class="spk">Speaker 2</strong> Hi there.'));
}

console.log("\n21. Sign-in, keys and the daily limit");
check("there is a Sign out button and an account line", /id="btn-sign-out"/.test(html) && /id="account-line"/.test(html));
check("the page asks the server how many jobs are used today", /\/api\/me/.test(appJs) && /jobs used today/.test(appJs));
check("a wrong key / lockout reopens the sign-in box", /Too many wrong keys/.test(appJs));

console.log(
  failures === 0
    ? "\nAll frontend checks passed.\n"
    : `\n${failures} check(s) FAILED — fix before shipping.\n`
);
process.exit(failures === 0 ? 0 : 1);
