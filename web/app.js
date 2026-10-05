const byId = (id) => document.getElementById(id);
const state = { bookId: null, outline: null, story: null };
const debugEntries = [];

function redactSecrets(value) {
  let text = String(value ?? "");
  const enteredKey = byId("api-key")?.value?.trim();
  if (enteredKey) text = text.split(enteredKey).join("[API KEY REDACTED]");
  return text.replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, "[API KEY REDACTED]");
}

function addDebug(level, message) {
  const time = new Date().toLocaleTimeString();
  debugEntries.push({ time, level, message: redactSecrets(message) });
  if (debugEntries.length > 200) debugEntries.splice(0, debugEntries.length - 200);
  const text = debugEntries.map((entry) => `${entry.time} [${entry.level}] ${entry.message}`).join("\n");
  byId("debug-log").value = text;
  byId("debug-log").scrollTop = byId("debug-log").scrollHeight;
  byId("debug-count").textContent = `${debugEntries.length} ${debugEntries.length === 1 ? "entry" : "entries"}`;
}

async function copyDebug() {
  const value = byId("debug-log").value;
  try {
    await navigator.clipboard.writeText(value);
    setStatus("Debug log copied. Paste it into your message.");
  } catch (_error) {
    byId("debug-log").focus();
    byId("debug-log").select();
    document.execCommand("copy");
    setStatus("Debug log selected and copied. Paste it into your message.");
  }
}

byId("copy-debug").addEventListener("click", copyDebug);
byId("clear-debug").addEventListener("click", () => {
  debugEntries.length = 0;
  byId("debug-log").value = "";
  byId("debug-count").textContent = "0 entries";
  addDebug("INFO", "Log cleared by user.");
});
window.addEventListener("error", (event) => {
  addDebug("ERROR", `Browser error: ${event.message || "Unknown error"} (${event.filename || "unknown file"}:${event.lineno || 0})`);
});
window.addEventListener("unhandledrejection", (event) => {
  addDebug("ERROR", `Unhandled browser promise: ${event.reason?.message || event.reason || "Unknown error"}`);
});
addDebug("INFO", "PDF Story Studio page loaded; API keys and PDF contents are never added to this log.");
requestJson("/api/diagnostics").then((info) => {
  addDebug("INFO", `Backend version ${info.version}; local generation ${info.local_generation ? "available" : "unavailable"}.`);
}).catch((error) => {
  addDebug("ERROR", `Backend version check failed: ${error.message}. The app server may need to be fully restarted to load this update.`);
});

function setStatus(message, error = false) {
  const node = byId("status");
  node.textContent = message;
  node.style.color = error ? "#ff8db4" : "";
  if (error) byId("debug-panel").open = true;
}

function setBusy(busy, message = "Working…") {
  byId("progress-wrap").classList.toggle("hidden", !busy);
  if (busy) setStatus(message);
  ["extract-button", "outline-button", "story-button", "play-button"].forEach((id) => {
    byId(id).disabled = busy;
  });
}

async function requestJson(url, options = {}) {
  const method = options.method || "GET";
  try {
    const response = await fetch(url, options);
    const value = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = value.error || `Request failed (${response.status}).`;
      addDebug("ERROR", `${method} ${url} returned HTTP ${response.status}: ${message}`);
      throw new Error(message);
    }
    if (!url.startsWith("/api/jobs/")) addDebug("INFO", `${method} ${url} returned HTTP ${response.status}.`);
    return value;
  } catch (error) {
    if (!(error instanceof Error) || !error.message) addDebug("ERROR", `${method} ${url} failed: ${error}`);
    else if (error instanceof TypeError) addDebug("ERROR", `${method} ${url} network error: ${error.message}`);
    throw error;
  }
}

function credentials() {
  const mode = byId("generation-mode").value;
  const settings = {
    generation_mode: mode,
    scene_count: Number(byId("scene-count").value),
  };
  if (mode === "openai") {
    settings.api_key = byId("api-key").value.trim();
    settings.model = byId("model-name").value.trim();
  }
  return settings;
}

function updateGenerationMode() {
  const openai = byId("generation-mode").value === "openai";
  byId("model-field").classList.toggle("hidden", !openai);
  byId("key-field").classList.toggle("hidden", !openai);
  document.querySelectorAll(".mode-tab").forEach((tab) => {
    const selected = tab.dataset.mode === (openai ? "openai" : "local");
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  byId("generation-title").textContent = openai ? "Original OpenAI workflow" : "Local story builder";
  byId("generation-note").textContent = openai
    ? "Uses the original project workflow to analyze the PDF and write the outline and scenes with OpenAI. PDF text is sent using your API key, which is kept in memory for requests and not saved in the project. Scene illustrations are composed locally."
    : "Works offline with no API key. It finds recurring words and moments in the PDF, writes a short template-based story, and paints original illustrated scenes on this computer.";
  addDebug("INFO", `Generation tab selected: ${openai ? "Original project / OpenAI" : "Do it locally"}.`);
}

document.querySelectorAll(".mode-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    byId("generation-mode").value = tab.dataset.mode;
    updateGenerationMode();
  });
});
updateGenerationMode();

async function pollJob(jobId) {
  let lastProgress = "";
  for (;;) {
    const job = await requestJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    setStatus(job.progress || "Working…");
    if (job.status === "complete") {
      addDebug("INFO", `Background job ${jobId} completed.`);
      return job.result;
    }
    if (job.status === "error") {
      addDebug("ERROR", `Background job ${jobId} failed: ${job.error || "Unknown job error."}`);
      throw new Error(job.error || "The job failed.");
    }
    if (job.progress && job.progress !== lastProgress) {
      addDebug("INFO", `Job ${jobId}: ${job.progress}`);
      lastProgress = job.progress;
    }
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
}

byId("pdf-file").addEventListener("change", () => {
  const file = byId("pdf-file").files[0];
  byId("file-name").textContent = file ? file.name : "Select a PDF";
  byId("extract-button").disabled = !file;
  if (file) addDebug("INFO", `PDF selected: ${file.name} (${file.size.toLocaleString()} bytes). File contents are not logged.`);
});

byId("extract-button").addEventListener("click", async () => {
  const file = byId("pdf-file").files[0];
  if (!file) return;
  addDebug("INFO", `Starting local PDF extraction for ${file.name}.`);
  setBusy(true, "Extracting text locally…");
  try {
    const response = await requestJson(`/api/upload?name=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: file,
    });
    state.bookId = response.id;
    addDebug("INFO", `PDF extracted: ${response.page_count} pages, ${response.word_count.toLocaleString()} words, ${response.empty_pages.length} pages without selectable text.`);
    byId("source-title").textContent = response.filename;
    byId("source-stats").textContent = `${response.page_count} pages · ${response.word_count.toLocaleString()} words`;
    const preview = byId("page-preview");
    preview.replaceChildren();
    response.preview.forEach((page) => {
      const card = document.createElement("article");
      card.className = "page-card";
      const heading = document.createElement("h3");
      heading.textContent = `PAGE ${page.page}`;
      const text = document.createElement("p");
      text.textContent = page.text || "No selectable text on this page.";
      card.append(heading, text);
      preview.append(card);
    });
    if (response.empty_pages.length) {
      setStatus(`${response.empty_pages.length} page(s) had no selectable text; they may be scans.`);
    } else setStatus("PDF text extracted on this computer.");
    byId("source-panel").classList.remove("hidden");
    byId("outline-button").disabled = false;
    byId("outline-panel").classList.add("hidden");
    byId("story-panel").classList.add("hidden");
  } catch (error) {
    addDebug("ERROR", `PDF extraction stopped: ${error.message}`);
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

byId("outline-button").addEventListener("click", async () => {
  if (!state.bookId) return;
  addDebug("INFO", `Starting outline generation using ${byId("generation-mode").value} mode; target ${byId("scene-count").value} scenes.`);
  setBusy(true, "Preparing source notes…");
  try {
    const started = await requestJson("/api/outline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: state.bookId,
        ...credentials(),
        mode: byId("adaptation-mode").value,
      }),
    });
    const result = await pollJob(started.job_id);
    state.outline = result.outline;
    byId("outline-json").value = JSON.stringify(state.outline, null, 2);
    byId("outline-panel").classList.remove("hidden");
    byId("story-panel").classList.add("hidden");
    byId("story-button").disabled = false;
    setStatus("Outline ready. Review or edit it before writing the scenes.");
    byId("outline-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    addDebug("ERROR", `Outline generation stopped: ${error.message}`);
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

byId("story-button").addEventListener("click", async () => {
  if (!state.bookId) return;
  addDebug("INFO", `Starting screenplay generation using ${byId("generation-mode").value} mode.`);
  let outline;
  try {
    outline = JSON.parse(byId("outline-json").value);
  } catch (error) {
    setStatus(`Outline JSON is invalid: ${error.message}`, true);
    return;
  }
  setBusy(true, "Writing the screenplay…");
  try {
    const started = await requestJson("/api/story", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.bookId, outline, ...credentials() }),
    });
    const result = await pollJob(started.job_id);
    state.story = result;
    byId("story-title").textContent = result.title;
    byId("story-json").value = JSON.stringify(result, null, 2);
    const summary = byId("story-summary");
    summary.replaceChildren();
    result.scenes.forEach((scene, index) => {
      const card = document.createElement("article");
      card.className = "scene-card";
      const heading = document.createElement("h3");
      heading.textContent = `${String(index + 1).padStart(2, "0")} · ${scene.title}`;
      const body = document.createElement("p");
      body.textContent = `${scene.location || "Scene"} · ${(scene.dialogue || []).length} lines`;
      card.append(heading, body);
      summary.append(card);
    });
    byId("download-link").href = result.download_url;
    byId("download-link").classList.remove("hidden");
    byId("story-panel").classList.remove("hidden");
    setStatus("Playable draft exported with locally composed scene illustrations.");
    byId("story-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    addDebug("ERROR", `Screenplay generation stopped: ${error.message}`);
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

byId("play-button").addEventListener("click", async () => {
  if (!state.bookId) return;
  addDebug("INFO", "Starting Ren'Py preview launch.");
  setBusy(true, "Preparing the Ren'Py preview…");
  try {
    const started = await requestJson("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.bookId }),
    });
    await pollJob(started.job_id);
    setStatus("The playable preview is open in a game window.");
  } catch (error) {
    addDebug("ERROR", `Preview launch failed: ${error.message}`);
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});
