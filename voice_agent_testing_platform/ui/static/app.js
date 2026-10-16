// Voice Agent & IVA Testing Platform - Interactive Dual-Waveform Audio Studio & Dashboard

let liveSocket = null;
let testStartTime = null;
let timerInterval = null;
let turnCount = 0;

// Dual-Track Studio State
let recordedTurns = [];
let callerPeaks = [];
let agentPeaks = [];
let totalDurationS = 0;
let activeSpeakingTurnIdx = null;
let audioPlayer = null;
let animFrameId = null;

document.addEventListener("DOMContentLoaded", () => {
  audioPlayer = document.getElementById("audioPlayer");
  initWebSocket();
  loadPresets();
  loadHistory();
  setupEventListeners();
  setupStudioControls();
});

// ====================================================================
// 1. WebSocket Live Stream Connection
// ====================================================================
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/live`;
  const statusPill = document.getElementById("connectionStatus");

  liveSocket = new WebSocket(wsUrl);

  liveSocket.onopen = () => {
    statusPill.textContent = "● Live WebSocket Connected";
    statusPill.className = "status-pill status-ready";
  };

  liveSocket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleLiveEvent(msg.event, msg.data);
    } catch (e) {
      console.error("Error parsing WebSocket message:", e);
    }
  };

  liveSocket.onclose = () => {
    statusPill.textContent = "○ Disconnected (Reconnecting...)";
    statusPill.className = "status-pill";
    setTimeout(initWebSocket, 2000);
  };
}

// ====================================================================
// 2. Handle Live Events from Test Runner
// ====================================================================
function handleLiveEvent(eventType, data) {
  if (eventType === "test_started") {
    onTestStarted(data);
  } else if (eventType === "turn_update") {
    onTurnUpdate(data);
  } else if (eventType === "test_completed") {
    onTestCompleted(data);
  } else if (eventType === "test_error") {
    onTestError(data);
  }
}

function onTestStarted(data) {
  const statusCard = document.getElementById("statusCard");
  const dot = statusCard.querySelector(".status-dot");
  const msg = document.getElementById("statusMessage");
  const runBtn = document.getElementById("runBtn");

  dot.className = "status-dot running";
  msg.textContent = `Running: ${data.scenario_name}...`;
  runBtn.disabled = true;
  runBtn.textContent = "⏳ Running Test...";

  // Reset transcript feed & scorecards
  const feed = document.getElementById("feedContainer");
  feed.innerHTML = "";
  turnCount = 0;
  recordedTurns = [];
  document.getElementById("turnCount").textContent = "0 turns";
  document.getElementById("scorecardSection").style.display = "none";
  document.getElementById("audioCard").style.display = "none";
  document.getElementById("reasoningCard").style.display = "none";

  // Stop any active audio playback
  if (audioPlayer) {
    audioPlayer.pause();
    audioPlayer.currentTime = 0;
  }

  // Start timer
  testStartTime = Date.now();
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(updateTimer, 1000);
}

function updateTimer() {
  if (!testStartTime) return;
  const elapsed = Math.floor((Date.now() - testStartTime) / 1000);
  const m = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const s = String(elapsed % 60).padStart(2, "0");
  document.getElementById("testDuration").textContent = `${m}:${s}`;
}

function onTurnUpdate(turn) {
  turnCount++;
  recordedTurns.push(turn);
  document.getElementById("turnCount").textContent = `${turnCount} turns`;

  renderTurnBubble(turn);

  const feed = document.getElementById("feedContainer");
  feed.scrollTop = feed.scrollHeight;
}

function renderTurnBubble(turn) {
  const feed = document.getElementById("feedContainer");

  const bubble = document.createElement("div");
  bubble.className = `turn-bubble ${turn.role}`;
  bubble.dataset.turnIndex = turn.turn_index;
  if (turn.start_time_s !== undefined && turn.start_time_s !== null) {
    bubble.dataset.start = turn.start_time_s;
    bubble.dataset.end = turn.end_time_s || (turn.start_time_s + 1.0);
  }

  const header = document.createElement("div");
  header.className = "bubble-header";

  const roleLabel = turn.role === "caller" ? "👤 Caller" : "🤖 Agent Under Test";
  const timingStr = turn.start_time_s !== undefined && turn.start_time_s !== null
    ? `[${turn.start_time_s.toFixed(1)}s - ${(turn.end_time_s || 0).toFixed(1)}s]`
    : turn.timestamp;

  header.innerHTML = `<span class="bubble-role">${roleLabel}</span> <span>${timingStr}</span>`;

  if (turn.is_interruption) {
    header.innerHTML += `<span class="tag tag-interrupt">⚡ BARGE-IN</span>`;
  }
  if (turn.dtmf_digits) {
    header.innerHTML += `<span class="tag tag-dtmf">📞 DTMF: ${turn.dtmf_digits}</span>`;
  }
  if (turn.latency_ms !== null && turn.latency_ms !== undefined) {
    header.innerHTML += `<span class="tag tag-latency">⏱️ ${Math.round(turn.latency_ms)}ms</span>`;
  }

  const textDiv = document.createElement("div");
  textDiv.className = "bubble-text";
  textDiv.textContent = turn.text;

  bubble.appendChild(header);
  bubble.appendChild(textDiv);

  // Click turn bubble to seek audio to that exact moment!
  bubble.addEventListener("click", () => {
    if (bubble.dataset.start && audioPlayer && !isNaN(audioPlayer.duration)) {
      audioPlayer.currentTime = parseFloat(bubble.dataset.start);
      audioPlayer.play();
      updatePlayIcon(true);
    }
  });

  feed.appendChild(bubble);
}

function onTestCompleted(result) {
  if (timerInterval) clearInterval(timerInterval);

  const statusCard = document.getElementById("statusCard");
  const dot = statusCard.querySelector(".status-dot");
  const msg = document.getElementById("statusMessage");
  const runBtn = document.getElementById("runBtn");

  runBtn.disabled = false;
  runBtn.innerHTML = '<span class="btn-icon">▶</span> Run Test Scenario';

  dot.className = `status-dot ${result.success ? "passed" : "failed"}`;
  msg.textContent = `Completed: ${result.scenario_name} - ${result.success ? "PASSED" : "FAILED"}`;

  // Update Scorecard
  const scSection = document.getElementById("scorecardSection");
  scSection.style.display = "grid";

  const badge = document.getElementById("passFailBadge");
  badge.textContent = result.success ? "PASSED" : "FAILED";
  badge.className = `score-badge ${result.success ? "" : "failed"}`;

  // Metrics
  const scores = result.metric_scores;
  if (scores) {
    document.getElementById("overallScoreVal").textContent = Math.round(scores.overall_score || 0);

    setMeter("noiseMeter", "noiseVal", scores.comprehension_under_noise);
    setMeter("accentMeter", "accentVal", scores.accent_handling);
    setMeter("politenessMeter", "politenessVal", scores.politeness_and_tone);
    setMeter("recoveryMeter", "recoveryVal", scores.interruption_recovery);
    setMeter("goalMeter", "goalVal", scores.goal_completion);
  } else {
    document.getElementById("overallScoreVal").textContent = result.success ? "100" : "0";
  }

  // Telemetry
  const det = result.deterministic_metrics || {};
  document.getElementById("avgLatencyVal").textContent = `${Math.round(det.avg_latency_ms || 0)} ms`;
  document.getElementById("bargeInVal").textContent = det.barge_in_tested ? (det.barge_in_successful ? "✅ Handled" : "❌ Failed") : "N/A";
  document.getElementById("dtmfVal").textContent = det.dtmf_tested ? (det.dtmf_matched ? "✅ Verified" : "❌ Failed") : "N/A";
  document.getElementById("keywordsVal").textContent = det.keywords_matched ? "✅ All Matched" : `❌ Missing: ${det.unmatched_keywords.join(", ")}`;

  // Judge Reasoning
  if (result.judge_reasoning) {
    const reasonCard = document.getElementById("reasoningCard");
    reasonCard.style.display = "block";
    document.getElementById("reasoningText").textContent = result.judge_reasoning;
  }

  // Load and Setup Dual Waveform Audio Studio
  setupDualWaveformStudio(result);

  loadHistory();
}

function setMeter(meterId, valId, value) {
  const v = Math.round(value !== null && value !== undefined ? value : 0);
  document.getElementById(meterId).style.width = `${v}%`;
  document.getElementById(valId).textContent = `${v}%`;
}

function onTestError(data) {
  if (timerInterval) clearInterval(timerInterval);
  const statusCard = document.getElementById("statusCard");
  const dot = statusCard.querySelector(".status-dot");
  const msg = document.getElementById("statusMessage");
  const runBtn = document.getElementById("runBtn");

  dot.className = "status-dot failed";
  msg.textContent = `Error: ${data.error}`;
  runBtn.disabled = false;
  runBtn.innerHTML = '<span class="btn-icon">▶</span> Run Test Scenario';
}

// ====================================================================
// 3. Dual Waveform Audio Studio & Synchronized Transcript Auto-Scroll
// ====================================================================
function setupDualWaveformStudio(result) {
  const audioCard = document.getElementById("audioCard");
  audioCard.style.display = "block";

  // Cache turn data
  recordedTurns = result.turns || [];
  callerPeaks = result.caller_peaks || generateMockPeaks(250, 0.4);
  agentPeaks = result.agent_peaks || generateMockPeaks(250, 0.6);
  totalDurationS = result.total_duration_s || (result.deterministic_metrics?.total_duration_seconds) || 10.0;

  // Use stereo WAV (dual channel) or fallback to mixed WAV
  const audioFilename = result.stereo_audio_filename || result.audio_filename;
  if (audioFilename) {
    const audioUrl = `/api/audio/${audioFilename}`;
    audioPlayer.src = audioUrl;

    const downloadBtn = document.getElementById("downloadAudioBtn");
    downloadBtn.href = audioUrl;
    downloadBtn.textContent = result.stereo_audio_filename ? "Download Stereo WAV" : "Download Mixed WAV";
  }

  // Set total duration label
  document.getElementById("totalTimeDisplay").textContent = formatTime(totalDurationS);
  document.getElementById("currentTimeDisplay").textContent = "00:00.0";

  // Initial Waveform Render
  renderDualWaveforms(0.0);

  // Re-render feed with accurate start/end timestamps if turns came from completed result
  const feed = document.getElementById("feedContainer");
  feed.innerHTML = "";
  recordedTurns.forEach((turn) => renderTurnBubble(turn));
}

function generateMockPeaks(num, baseAmp) {
  const peaks = [];
  for (let i = 0; i < num; i++) {
    peaks.push(Math.round(Math.abs(Math.sin(i * 0.15)) * baseAmp * 100) / 100);
  }
  return peaks;
}

function renderDualWaveforms(progressRatio) {
  const callerCanvas = document.getElementById("callerWaveformCanvas");
  const agentCanvas = document.getElementById("agentWaveformCanvas");

  drawWaveform(callerCanvas, callerPeaks, "#3b82f6", "rgba(59, 130, 246, 0.25)", progressRatio);
  drawWaveform(agentCanvas, agentPeaks, "#10b981", "rgba(16, 185, 129, 0.25)", progressRatio);
}

function drawWaveform(canvas, peaks, activeColor, inactiveColor, progressRatio) {
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.parentElement.clientWidth;
  const height = canvas.parentElement.clientHeight || 60;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.scale(dpr, dpr);

  ctx.clearRect(0, 0, width, height);

  if (!peaks || peaks.length === 0) return;

  const barCount = peaks.length;
  const gap = 1;
  const totalBarWidth = width / barCount;
  const barWidth = Math.max(1, totalBarWidth - gap);
  const midY = height / 2;
  const progressX = width * progressRatio;

  for (let i = 0; i < barCount; i++) {
    const x = i * totalBarWidth;
    const peakVal = peaks[i] || 0.05;
    const barHeight = Math.max(3, peakVal * (height * 0.85));
    const topY = midY - barHeight / 2;

    ctx.fillStyle = (x <= progressX) ? activeColor : inactiveColor;

    // Draw rounded vertical bar
    ctx.beginPath();
    ctx.roundRect(x, topY, barWidth, barHeight, 2);
    ctx.fill();
  }
}

// Master Studio Controls Setup
function setupStudioControls() {
  const playPauseBtn = document.getElementById("playPauseBtn");
  const rewindBtn = document.getElementById("rewindBtn");
  const forwardBtn = document.getElementById("forwardBtn");
  const scrubContainer = document.getElementById("scrubContainer");
  const speedSelect = document.getElementById("playbackSpeedSelect");

  playPauseBtn.addEventListener("click", () => {
    if (!audioPlayer.src) return;
    if (audioPlayer.paused) {
      audioPlayer.play();
      updatePlayIcon(true);
    } else {
      audioPlayer.pause();
      updatePlayIcon(false);
    }
  });

  rewindBtn.addEventListener("click", () => {
    if (audioPlayer) {
      audioPlayer.currentTime = Math.max(0, audioPlayer.currentTime - 5.0);
    }
  });

  forwardBtn.addEventListener("click", () => {
    if (audioPlayer) {
      audioPlayer.currentTime = Math.min(audioPlayer.duration || totalDurationS, audioPlayer.currentTime + 5.0);
    }
  });

  speedSelect.addEventListener("change", (e) => {
    if (audioPlayer) {
      audioPlayer.playbackRate = parseFloat(e.target.value);
    }
  });

  // Scrub bar interaction
  scrubContainer.addEventListener("click", (e) => {
    if (!audioPlayer || !audioPlayer.duration) return;
    const rect = scrubContainer.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    audioPlayer.currentTime = ratio * audioPlayer.duration;
  });

  // Waveform canvas clicks to scrub directly from waveform!
  setupCanvasSeek("callerCanvasWrapper");
  setupCanvasSeek("agentCanvasWrapper");

  // Audio Player Event Listeners
  audioPlayer.addEventListener("play", () => {
    updatePlayIcon(true);
    startSyncPlaybackLoop();
  });

  audioPlayer.addEventListener("pause", () => {
    updatePlayIcon(false);
    if (animFrameId) cancelAnimationFrame(animFrameId);
  });

  audioPlayer.addEventListener("ended", () => {
    updatePlayIcon(false);
    if (animFrameId) cancelAnimationFrame(animFrameId);
    clearActiveSpeakingTurn();
  });

  audioPlayer.addEventListener("timeupdate", onAudioTimeUpdate);

  // Resize listener to redraw waveforms crisply
  window.addEventListener("resize", () => {
    if (audioPlayer && audioPlayer.duration) {
      const ratio = audioPlayer.currentTime / audioPlayer.duration;
      renderDualWaveforms(ratio);
    }
  });
}

function setupCanvasSeek(wrapperId) {
  const wrapper = document.getElementById(wrapperId);
  if (!wrapper) return;

  wrapper.addEventListener("click", (e) => {
    if (!audioPlayer || !audioPlayer.duration) return;
    const rect = wrapper.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    audioPlayer.currentTime = ratio * audioPlayer.duration;
    if (audioPlayer.paused) {
      audioPlayer.play();
      updatePlayIcon(true);
    }
  });
}

function updatePlayIcon(isPlaying) {
  const icon = document.getElementById("playIcon");
  icon.textContent = isPlaying ? "⏸" : "▶";
}

function startSyncPlaybackLoop() {
  function loop() {
    onAudioTimeUpdate();
    if (!audioPlayer.paused && !audioPlayer.ended) {
      animFrameId = requestAnimationFrame(loop);
    }
  }
  animFrameId = requestAnimationFrame(loop);
}

function onAudioTimeUpdate() {
  if (!audioPlayer) return;

  const duration = audioPlayer.duration || totalDurationS || 1.0;
  const currTime = audioPlayer.currentTime;
  const ratio = Math.max(0, Math.min(1, currTime / duration));

  // 1. Update Time Display
  document.getElementById("currentTimeDisplay").textContent = formatTime(currTime);

  // 2. Update Scrub Bar
  const pctStr = `${(ratio * 100).toFixed(2)}%`;
  document.getElementById("scrubProgress").style.width = pctStr;
  document.getElementById("scrubThumb").style.left = pctStr;

  // 3. Update Waveform Playhead Cursors
  document.getElementById("callerCursor").style.left = pctStr;
  document.getElementById("agentCursor").style.left = pctStr;

  // 4. Redraw Waveform with current progress
  renderDualWaveforms(ratio);

  // 5. SYNCHRONIZED TRANSCRIPT AUTO-SCROLL & TURN HIGHLIGHTING
  syncTranscriptWithAudio(currTime);
}

function syncTranscriptWithAudio(currTime) {
  if (!recordedTurns || recordedTurns.length === 0) return;

  // Find the turn currently being spoken
  let matchingTurn = null;
  for (const turn of recordedTurns) {
    if (turn.start_time_s !== undefined && turn.start_time_s !== null) {
      const endT = turn.end_time_s || (turn.start_time_s + 2.0);
      if (currTime >= turn.start_time_s && currTime <= endT) {
        matchingTurn = turn;
        break;
      }
    }
  }

  if (matchingTurn && matchingTurn.turn_index !== activeSpeakingTurnIdx) {
    activeSpeakingTurnIdx = matchingTurn.turn_index;

    // Remove active highlight from all bubbles
    document.querySelectorAll(".turn-bubble").forEach((b) => {
      b.classList.remove("active-speaking");
    });

    // Highlight the active speaking turn
    const activeEl = document.querySelector(`.turn-bubble[data-turn-index="${matchingTurn.turn_index}"]`);
    if (activeEl) {
      activeEl.classList.add("active-speaking");

      // AUTO-SCROLL TO ACTIVE TURN IN REAL TIME!
      activeEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  } else if (!matchingTurn && activeSpeakingTurnIdx !== null) {
    // In silence / pause between turns
    activeSpeakingTurnIdx = null;
    clearActiveSpeakingTurn();
  }
}

function clearActiveSpeakingTurn() {
  document.querySelectorAll(".turn-bubble").forEach((b) => {
    b.classList.remove("active-speaking");
  });
}

function formatTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return "00:00.0";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${ms}`;
}

// ====================================================================
// 4. UI Controls, Presets & Past Runs Loading
// ====================================================================
function setupEventListeners() {
  const callerTypeSelect = document.getElementById("callerType");
  callerTypeSelect.addEventListener("change", (e) => {
    const isDynamic = e.target.value === "dynamic";
    document.getElementById("dynamicSection").style.display = isDynamic ? "block" : "none";
    document.getElementById("scriptedSection").style.display = isDynamic ? "none" : "block";
  });

  const noiseSlider = document.getElementById("noiseVolume");
  noiseSlider.addEventListener("input", (e) => {
    document.getElementById("noiseVolumeLabel").textContent = `${Math.round(e.target.value * 100)}%`;
  });

  const presetSelect = document.getElementById("presetSelect");
  presetSelect.addEventListener("change", (e) => {
    loadPresetDetails(e.target.value);
  });

  const runBtn = document.getElementById("runBtn");
  runBtn.addEventListener("click", triggerRun);
}

// Trigger Run via POST /api/run
async function triggerRun() {
  const scenarioName = document.getElementById("scenarioName").value.trim();
  const adapterType = document.getElementById("adapterType").value;
  const targetUrl = document.getElementById("targetUrl").value.trim();
  const callerType = document.getElementById("callerType").value;
  const callerAccent = document.getElementById("callerAccent").value;
  const backgroundNoise = document.getElementById("backgroundNoise").value;
  const noiseVolume = parseFloat(document.getElementById("noiseVolume").value);
  const applyTelephony = document.getElementById("telephonyFilter").checked;

  let customScript = [];
  try {
    if (callerType === "scripted") {
      customScript = JSON.parse(document.getElementById("scriptText").value);
    }
  } catch (e) {
    alert("Invalid JSON in Scripted Steps textarea. Please check your syntax.");
    return;
  }

  const criteriaRaw = document.getElementById("criteriaText").value.trim();
  const criteria = criteriaRaw.split("\n").map((c) => c.replace(/^[-*•]\s*/, "").trim()).filter(Boolean);

  const payload = {
    scenario_id: `test_${Date.now()}`,
    scenario_name: scenarioName,
    adapter_type: adapterType,
    target_url: targetUrl,
    caller_type: callerType,
    caller_accent: callerAccent,
    background_noise: backgroundNoise,
    noise_volume: noiseVolume,
    apply_telephony_filter: applyTelephony,
    persona: document.getElementById("dynamicPersona")?.value || "",
    goal: document.getElementById("dynamicGoal")?.value || "",
    custom_script: customScript,
    criteria: criteria,
    evaluate_metrics: true,
    max_turns: 8,
  };

  try {
    const resp = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      alert(`Could not start test: ${data.error || "Unknown error"}`);
    }
  } catch (e) {
    alert(`Request error: ${e.message}`);
  }
}

// Presets Loading
let cachedPresets = [];
async function loadPresets() {
  try {
    const res = await fetch("/api/presets");
    cachedPresets = await res.json();
  } catch (e) {
    console.error("Failed to fetch presets:", e);
  }
}

function loadPresetDetails(presetId) {
  const p = cachedPresets.find((item) => item.id === presetId);
  if (!p) return;

  document.getElementById("scenarioName").value = p.name;
  document.getElementById("adapterType").value = p.adapter_type;
  document.getElementById("targetUrl").value = p.target_url;
  document.getElementById("callerType").value = p.caller_type;
  document.getElementById("callerAccent").value = p.caller_accent;
  document.getElementById("backgroundNoise").value = p.background_noise;
  document.getElementById("noiseVolume").value = p.noise_volume;
  document.getElementById("noiseVolumeLabel").textContent = `${Math.round(p.noise_volume * 100)}%`;
  document.getElementById("telephonyFilter").checked = p.apply_telephony_filter;

  const isDynamic = p.caller_type === "dynamic";
  document.getElementById("dynamicSection").style.display = isDynamic ? "block" : "none";
  document.getElementById("scriptedSection").style.display = isDynamic ? "none" : "block";

  if (p.custom_script && p.custom_script.length > 0) {
    document.getElementById("scriptText").value = JSON.stringify(p.custom_script, null, 2);
  }
  if (p.persona) document.getElementById("dynamicPersona").value = p.persona;
  if (p.goal) document.getElementById("dynamicGoal").value = p.goal;

  if (p.criteria) {
    document.getElementById("criteriaText").value = p.criteria.map((c) => `- ${c}`).join("\n");
  }
}

// Past Runs History
async function loadHistory() {
  try {
    const res = await fetch("/api/runs");
    const runs = await res.json();
    const container = document.getElementById("historyList");
    if (!runs || runs.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>No previous test runs found.</p></div>';
      return;
    }
    container.innerHTML = "";
    runs.slice(0, 8).forEach((r) => {
      const item = document.createElement("div");
      item.className = "history-item";
      item.style.cursor = "pointer";
      const timeStr = r.started_at ? r.started_at.substring(0, 19).replace("T", " ") : "Recently";
      const score = r.metric_scores ? `${Math.round(r.metric_scores.overall_score)}/100` : "";
      item.innerHTML = `
        <div>
          <strong>${r.scenario_name}</strong>
          <div style="font-size:0.75rem; color:var(--text-muted);">${timeStr} • ${r.turns ? r.turns.length : 0} turns</div>
        </div>
        <div style="display:flex; align-items:center; gap:0.75rem;">
          <span style="font-weight:600;">${score}</span>
          <span class="history-status ${r.status}">${r.status.toUpperCase()}</span>
        </div>
      `;

      // Clicking a past run in history reloads it into the studio for review and playback!
      item.addEventListener("click", () => {
        onTestCompleted(r);
      });

      container.appendChild(item);
    });
  } catch (e) {
    console.error("Failed to load history:", e);
  }
}
