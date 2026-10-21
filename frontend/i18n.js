// English-only: the few strings app.js builds in JavaScript. The page's own
// static text is plain English in index.html.
//
// `t(key)` stays a function (rather than inlining the strings) so every piece
// of generated text lives in one place and the unit tests can check it.
const I18N = {
  editTranscript: "Edit",
  cancelEdit: "Cancel",
  saveEdit: "Save",
  fullTranscriptHeading: "full transcript (word for word)",
  noneFound: "None found.",
  resultsTitleFull: "Full breakdown",
  resultsTitleTranscript: "Transcript",
  resultsTitleText: "Text to Audio",
  wholeTextHeading: "whole text",
  correctionsHeading: "spelling fixes",
  summaryHeading: "summary",
  keyPointsHeading: "key points",
  datesHeading: "dates mentioned",
  linksHeading: "links mentioned",
  notableTermsHeading: "notable terms",
  highlightsHeading: "highlights",
  aiInsightsHeading: "ai insights",
  reanalyzeButton: "Re-run summary",
};

function t(key) {
  return I18N[key] !== undefined ? I18N[key] : key;
}

if (typeof module !== "undefined") module.exports = { I18N, t };
