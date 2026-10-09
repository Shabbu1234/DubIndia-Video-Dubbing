/* DubIndia — Frontend JavaScript */
"use strict";

// ── State ──────────────────────────────────────────────────────────────────
let currentJobId = null;
let sseSource = null;
let statusInterval = null;
let selectedFile = null;

// ── DOM refs ───────────────────────────────────────────────────────────────
const dropZone = document.getElementById("drop-zone");
const dropInner = document.getElementById("drop-inner");
const dropPreview = document.getElementById("drop-preview");
const fileInput = document.getElementById("file-input");
const previewName = document.getElementById("preview-name");
const previewSize = document.getElementById("preview-size");
const previewRm = document.getElementById("preview-remove");
const btnDub = document.getElementById("btn-dub");
const modelSelect = document.getElementById("model-select");
const speakersIn = document.getElementById("speakers-input");
const voiceVol = document.getElementById("voice-vol");
const voiceVolVal = document.getElementById("voice-vol-val");
const bgVol = document.getElementById("bg-vol");
const bgVolVal = document.getElementById("bg-vol-val");
const skipBgmToggle = document.getElementById("skip-bgm-toggle");

const uploadSection = document.getElementById("upload-section");
const progressCard = document.getElementById("progress-card");
const resultCard = document.getElementById("result-card");
const errorCard = document.getElementById("error-card");

const progressBar = document.getElementById("progress-bar");
const progressPct = document.getElementById("progress-pct");
const progressStage = document.getElementById("progress-stage");
const logBody = document.getElementById("log-body");
const logClear = document.getElementById("log-clear");
const btnDownload = document.getElementById("btn-download");
const btnAgain = document.getElementById("btn-again");
const btnAgainErr = document.getElementById("btn-again-err");
const resultStats = document.getElementById("result-stats");
const errorMsg = document.getElementById("error-msg");

// ── Pipeline step thresholds ───────────────────────────────────────────────
const STEP_THRESHOLDS = [5, 12, 30, 45, 58, 70, 85];

// ── File size formatter ────────────────────────────────────────────────────
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 ** 3) return (bytes / 1024 ** 2).toFixed(1) + " MB";
  return (bytes / 1024 ** 3).toFixed(2) + " GB";
}

// ── File handling ──────────────────────────────────────────────────────────
function setFile(file) {
  selectedFile = file;
  previewName.textContent = file.name;
  previewSize.textContent = fmtSize(file.size);
  dropInner.hidden = true;
  dropPreview.hidden = false;
  dropPreview.style.display = "flex";
  btnDub.disabled = false;
}

function clearFile() {
  selectedFile = null;
  fileInput.value = "";
  dropInner.hidden = false;
  dropPreview.hidden = true;
  dropPreview.style.display = "";
  btnDub.disabled = true;
}

// Drag & Drop
dropZone.addEventListener("click", e => {
  if (e.target === previewRm) return;
  fileInput.click();
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});
previewRm.addEventListener("click", e => {
  e.stopPropagation();
  clearFile();
});

dropZone.addEventListener("dragover", e => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", e => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  const f = e.dataTransfer.files[0];
  if (f) setFile(f);
});

// ── Volume sliders ─────────────────────────────────────────────────────────
function updateSliderGradient(el) {
  const min = parseFloat(el.min), max = parseFloat(el.max), val = parseFloat(el.value);
  const pct = ((val - min) / (max - min)) * 100;
  el.style.background = `linear-gradient(to right, var(--accent) ${pct}%, var(--surface2) ${pct}%)`;
}

voiceVol.addEventListener("input", () => {
  voiceVolVal.textContent = Math.round(parseFloat(voiceVol.value) * 100) + "%";
  updateSliderGradient(voiceVol);
});
bgVol.addEventListener("input", () => {
  bgVolVal.textContent = Math.round(parseFloat(bgVol.value) * 100) + "%";
  updateSliderGradient(bgVol);
});
updateSliderGradient(voiceVol);
updateSliderGradient(bgVol);

// ── Log panel ──────────────────────────────────────────────────────────────
function addLog(msg, level = "info", ts = null) {
  const el = document.createElement("div");
  el.className = `log-entry ${level}`;
  const d = ts ? new Date(ts * 1000) : new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  el.innerHTML = `<span class="log-time">${hh}:${mm}:${ss}</span><span class="log-msg">${escHtml(msg)}</span>`;
  logBody.appendChild(el);
  logBody.scrollTop = logBody.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

logClear.addEventListener("click", () => { logBody.innerHTML = ""; });

// ── Pipeline step visual ───────────────────────────────────────────────────
function updateSteps(pct) {
  const stepEls = document.querySelectorAll(".pipeline-steps .step");
  let activeSet = false;
  stepEls.forEach((el, i) => {
    const thresh = STEP_THRESHOLDS[i];
    const nextThresh = STEP_THRESHOLDS[i + 1] || 101;
    el.classList.remove("active", "done");
    if (pct >= nextThresh) {
      el.classList.add("done");
    } else if (pct >= thresh && !activeSet) {
      el.classList.add("active");
      activeSet = true;
    }
  });
}

// ── UI state machine ───────────────────────────────────────────────────────
function showSection(name) {
  uploadSection.hidden = name !== "upload";
  progressCard.hidden = name !== "progress";
  resultCard.hidden = name !== "result";
  errorCard.hidden = name !== "error";
}

function showProgress(pct, stage) {
  showSection("progress");
  progressBar.style.width = pct + "%";
  progressPct.textContent = pct + "%";
  progressStage.textContent = stage || "Chal rahi hai...";
  updateSteps(pct);
}

function fmtTime(sec) {
  const m = Math.floor(sec / 60);
  const s = (sec % 60).toFixed(1);
  return `${String(m).padStart(2, "0")}:${s < 10 ? "0" : ""}${s}`;
}

function showResult(summary, jobId, cuts = []) {
  showSection("result");
  resultStats.innerHTML = "";
  const stats = [
    { val: summary.language || "?", label: "Language" },
    { val: summary.speakers || 1, label: "Speakers" },
    { val: summary.cuts || (cuts ? cuts.length : 0), label: "Timeline Cuts" },
    { val: summary.warnings || 0, label: "Warnings" },
  ];
  stats.forEach(s => {
    const d = document.createElement("div");
    d.className = "stat-box";
    d.innerHTML = `<div class="stat-val">${s.val}</div><div class="stat-label">${s.label}</div>`;
    resultStats.appendChild(d);
  });

  // Setup Video Player preview
  const resultVideo = document.getElementById("result-video");
  if (resultVideo) {
    resultVideo.src = `/api/video/${jobId}`;
    resultVideo.load();
  }

  // Setup Timeline Cuts visualizer
  const cutsList = document.getElementById("timeline-cuts-list");
  const cutsCounter = document.getElementById("cuts-counter");
  if (cutsList) {
    cutsList.innerHTML = "";
    if (cuts && cuts.length > 0) {
      if (cutsCounter) cutsCounter.textContent = `${cuts.length} Cuts Synced`;
      cuts.forEach(cut => {
        const item = document.createElement("div");
        item.className = "cut-item";
        item.innerHTML = `
          <div class="cut-header-row">
            <span class="cut-badge-id">Cut #${cut.id}</span>
            <button class="cut-time-btn" title="Click karke video is cut pe seek karo">
              ⏱️ ${fmtTime(cut.start)} ➔ ${fmtTime(cut.end)} <small>(${cut.duration}s)</small> ▶
            </button>
            <span class="cut-speaker-badge ${cut.gender === 'F' ? 'female' : 'male'}">
              ${cut.gender === 'F' ? '👩' : '👨'} Speaker ${cut.speaker} (${cut.gender === 'F' ? 'Female' : 'Male'})
            </span>
            <span class="cut-sync-tag">100% Synced</span>
          </div>
          <div class="cut-dialogue-row">
            <div class="cut-dialogue orig">
              <span class="tag">ORIGINAL:</span>
              <span class="txt">${escHtml(cut.orig || "-")}</span>
            </div>
            <div class="cut-dialogue dub">
              <span class="tag dub">HINDUSTANI:</span>
              <span class="txt">${escHtml(cut.hi || "-")}</span>
            </div>
          </div>
        `;

        // Click timestamp to seek video
        item.querySelector(".cut-time-btn").addEventListener("click", () => {
          if (resultVideo) {
            resultVideo.currentTime = Math.max(0, cut.start);
            resultVideo.play();
            resultVideo.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        });

        cutsList.appendChild(item);
      });
    } else {
      if (cutsCounter) cutsCounter.textContent = `0 Cuts`;
      cutsList.innerHTML = `<div class="cuts-empty">Koi speech cut detect nahi hua.</div>`;
    }
  }

  btnDownload.onclick = () => {
    window.location.href = `/api/download/${jobId}`;
  };

  const btnSrt = document.getElementById("btn-download-srt");
  if (btnSrt) {
    btnSrt.onclick = () => {
      window.location.href = `/api/subtitles/${jobId}`;
    };
  }
}

function showError(msg) {
  showSection("error");
  errorMsg.textContent = msg || "Kuch gadbad ho gayi!";
}

// ── SSE log stream ─────────────────────────────────────────────────────────
function startLogStream(jobId) {
  if (sseSource) sseSource.close();
  sseSource = new EventSource(`/api/logs/${jobId}`);
  sseSource.onmessage = e => {
    try {
      const d = JSON.parse(e.data);
      if (d._done) { sseSource.close(); return; }
      addLog(d.msg, d.level || "info", d.t);
    } catch { }
  };
  sseSource.onerror = () => sseSource.close();
}

// ── Status polling ─────────────────────────────────────────────────────────
function startPolling(jobId) {
  if (statusInterval) clearInterval(statusInterval);
  statusInterval = setInterval(async () => {
    try {
      const r = await fetch(`/api/status/${jobId}`);
      const d = await r.json();
      showProgress(d.progress || 0, d.stage);
      if (d.status === "done") {
        clearInterval(statusInterval);
        statusInterval = null;
        showResult(d.summary || {}, jobId, d.cuts || []);
      } else if (d.status === "error") {
        clearInterval(statusInterval);
        statusInterval = null;
        showError(d.error);
      }
    } catch (err) {
      console.error("Polling error:", err);
    }
  }, 800);
}

// ── Submit ─────────────────────────────────────────────────────────────────
btnDub.addEventListener("click", async () => {
  if (!selectedFile) return;

  const fd = new FormData();
  fd.append("video", selectedFile);
  fd.append("model", modelSelect.value);
  fd.append("voice_vol", voiceVol.value);
  fd.append("bg_vol", bgVol.value);
  fd.append("skip_bgm", skipBgmToggle && skipBgmToggle.checked ? "true" : "false");
  if (speakersIn.value) fd.append("speakers", speakersIn.value);

  showProgress(0, "Upload ho raha hai...");
  addLog("Video upload ho rahi hai...", "info");

  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    if (!r.ok) {
      const err = await r.json();
      showError(err.error || "Upload failed");
      return;
    }
    const { job_id } = await r.json();
    currentJobId = job_id;
    addLog(`Job shuru hua: ${job_id}`, "success");
    startLogStream(job_id);
    startPolling(job_id);
  } catch (e) {
    showError("Server se connection nahi hua: " + e.message);
  }
});

// ── Reset ──────────────────────────────────────────────────────────────────
function resetApp() {
  if (sseSource) { sseSource.close(); sseSource = null; }
  if (statusInterval) { clearInterval(statusInterval); statusInterval = null; }
  currentJobId = null;
  clearFile();
  const resultVideo = document.getElementById("result-video");
  if (resultVideo) {
    resultVideo.pause();
    resultVideo.removeAttribute("src");
    resultVideo.load();
  }
  const cutsList = document.getElementById("timeline-cuts-list");
  if (cutsList) cutsList.innerHTML = "";
  logBody.innerHTML = "";
  progressBar.style.width = "0%";
  progressPct.textContent = "0%";
  updateSteps(0);
  showSection("upload");
}

btnAgain.addEventListener("click", resetApp);
btnAgainErr.addEventListener("click", resetApp);
