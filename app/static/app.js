const state = {
  activeJobId: null,
  pollTimer: null,
  selectedStyle: "cinematic",
};

const form = document.querySelector("#generationForm");
const resultPanel = document.querySelector("#resultPanel");
const historyList = document.querySelector("#historyList");
const healthBadge = document.querySelector("#healthBadge");
const providerTitle = document.querySelector("#providerTitle");
const refreshHistory = document.querySelector("#refreshHistory");

document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadHealth(), loadOptions(), loadHistory()]);
  restoreDraft();
  wireEvents();
  window.lucide?.createIcons();
});

function wireEvents() {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    saveDraft();
    await createGeneration();
  });

  form.addEventListener("input", saveDraft);
  refreshHistory.addEventListener("click", loadHistory);

  document.querySelector("#formatSelect").addEventListener("change", (event) => {
    const compression = form.elements.output_compression;
    const enabled = ["jpeg", "webp"].includes(event.target.value);
    compression.disabled = !enabled;
    if (!enabled) compression.value = "";
  });
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    const mode = health.retry.streaming ? "stream" : "json";
    providerTitle.textContent = `${health.provider.model} · ${mode} · ${health.retry.attempts} retries`;
    healthBadge.textContent = health.provider.has_api_key ? "已配置" : "缺少 key";
    healthBadge.className = `status-dot ${health.provider.has_api_key ? "ready" : "error"}`;
  } catch {
    healthBadge.textContent = "异常";
    healthBadge.className = "status-dot error";
  }
}

async function loadOptions() {
  const options = await api("/api/options");
  renderStyles(options.styles);
  fillSelect("#sizeSelect", options.sizes, "value", "label", "1024x1024");
  fillSelect("#qualitySelect", options.qualities, null, null, "auto");
  fillSelect("#formatSelect", options.formats, null, null, "png");
  fillSelect("#backgroundSelect", options.backgrounds, null, null, "auto");
}

function renderStyles(styles) {
  const container = document.querySelector("#styleButtons");
  container.innerHTML = "";
  for (const style of styles) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = style.label;
    button.dataset.style = style.id;
    button.className = style.id === state.selectedStyle ? "active" : "";
    button.addEventListener("click", () => {
      state.selectedStyle = style.id;
      for (const item of container.querySelectorAll("button")) item.classList.remove("active");
      button.classList.add("active");
      saveDraft();
    });
    container.appendChild(button);
  }
}

function fillSelect(selector, items, valueKey, labelKey, selected) {
  const select = document.querySelector(selector);
  select.innerHTML = "";
  for (const item of items) {
    const value = valueKey ? item[valueKey] : item;
    const label = labelKey ? item[labelKey] : item;
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === selected;
    select.appendChild(option);
  }
}

async function createGeneration() {
  const payload = formPayload();
  setFormBusy(true);
  renderLoading("pending", payload.prompt);
  try {
    const response = await api("/api/generations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.activeJobId = response.job.id;
    renderJob(response.job);
    await loadHistory();
    startPolling(response.job.id);
  } catch (error) {
    renderError(error.message);
  } finally {
    setFormBusy(false);
  }
}

function formPayload() {
  const data = new FormData(form);
  const outputFormat = String(data.get("output_format"));
  const compressionRaw = String(data.get("output_compression") || "").trim();
  return {
    prompt: String(data.get("prompt") || "").trim(),
    negative_prompt: String(data.get("negative_prompt") || "").trim(),
    style_preset: state.selectedStyle,
    size: String(data.get("size")),
    quality: String(data.get("quality")),
    output_format: outputFormat,
    output_compression:
      ["jpeg", "webp"].includes(outputFormat) && compressionRaw ? Number(compressionRaw) : null,
    background: String(data.get("background")),
    n: Number(data.get("n") || 1),
  };
}

function startPolling(jobId) {
  stopPolling();
  state.pollTimer = window.setInterval(async () => {
    const job = await api(`/api/generations/${jobId}`);
    renderJob(job);
    await loadHistory();
    if (["succeeded", "failed"].includes(job.status)) {
      stopPolling();
    }
  }, 1400);
}

function stopPolling() {
  if (state.pollTimer) window.clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function loadHistory() {
  const jobs = await api("/api/generations?limit=40");
  historyList.innerHTML = jobs.length ? "" : `<div class="history-card"><p>暂无任务</p></div>`;
  for (const job of jobs) {
    historyList.appendChild(historyCard(job));
  }
  window.lucide?.createIcons();
}

function historyCard(job) {
  const card = document.createElement("article");
  card.className = `history-card ${job.id === state.activeJobId ? "active" : ""}`;
  const title = escapeHtml(job.prompt || "Untitled");
  card.innerHTML = `
    <div class="history-title">
      <strong>${title.slice(0, 70)}</strong>
      <span class="pill ${job.status}">${statusText(job.status)}</span>
    </div>
    <p>${new Date(job.created_at).toLocaleString()} · ${job.request.size} · ${job.request.quality}</p>
    <div class="row">
      <button class="text-button open-job" type="button">打开</button>
      <button class="text-button retry-job" type="button">重试</button>
    </div>
  `;
  card.querySelector(".open-job").addEventListener("click", async () => {
    state.activeJobId = job.id;
    renderJob(await api(`/api/generations/${job.id}`));
    await loadHistory();
    if (["pending", "running"].includes(job.status)) startPolling(job.id);
  });
  card.querySelector(".retry-job").addEventListener("click", async () => {
    const response = await api(`/api/generations/${job.id}/retry`, { method: "POST" });
    state.activeJobId = response.job.id;
    renderJob(response.job);
    await loadHistory();
    startPolling(response.job.id);
  });
  return card;
}

function renderLoading(status, prompt) {
  resultPanel.className = "result-panel";
  resultPanel.innerHTML = `
    <div class="job-meta">
      <div>
        <h2>${escapeHtml(prompt)}</h2>
        <p>任务已提交</p>
      </div>
      <span class="pill ${status}">${statusText(status)}</span>
    </div>
    <div class="empty-state">
      <div class="spinner"></div>
      <h2>生成中</h2>
    </div>
  `;
}

function renderJob(job) {
  resultPanel.className = "result-panel";
  const controls = `
    <button class="secondary-action" id="retryActive" type="button">
      <i data-lucide="rotate-ccw"></i><span>重试</span>
    </button>
  `;
  const meta = `
    <div class="job-meta">
      <div>
        <h2>${escapeHtml(job.prompt)}</h2>
        <p>${job.request.size} · ${job.request.quality} · ${job.request.output_format} · attempts ${job.attempts}</p>
      </div>
      <div class="toolbar-actions">
        <span class="pill ${job.status}">${statusText(job.status)}</span>
        ${controls}
      </div>
    </div>
  `;

  if (["pending", "running"].includes(job.status)) {
    resultPanel.innerHTML = `${meta}<div class="empty-state"><div class="spinner"></div><h2>生成中</h2></div>${details(job)}`;
  } else if (job.status === "failed") {
    resultPanel.innerHTML = `${meta}<div class="error-box">${escapeHtml(job.error || "生成失败")}</div>${details(job)}`;
  } else {
    resultPanel.innerHTML = `${meta}${imageGrid(job.images)}${details(job)}`;
  }

  document.querySelector("#retryActive")?.addEventListener("click", async () => {
    const response = await api(`/api/generations/${job.id}/retry`, { method: "POST" });
    state.activeJobId = response.job.id;
    renderJob(response.job);
    await loadHistory();
    startPolling(response.job.id);
  });
  window.lucide?.createIcons();
}

function imageGrid(images) {
  if (!images.length) return `<div class="empty-state"><i data-lucide="image-off"></i><h2>无图片</h2></div>`;
  return `
    <div class="image-grid">
      ${images
        .map(
          (image) => `
            <figure class="image-tile">
              <img src="${image.url}" alt="${escapeHtml(image.filename)}" />
              <figcaption class="image-actions">
                <a href="${image.url}" target="_blank" rel="noreferrer">打开</a>
                <a href="${image.url}" download="${escapeHtml(image.filename)}">下载</a>
              </figcaption>
            </figure>
          `,
        )
        .join("")}
    </div>
  `;
}

function details(job) {
  return `
    <details class="detail-block">
      <summary>最终提示词</summary>
      <pre>${escapeHtml(job.final_prompt)}</pre>
    </details>
    <details class="detail-block">
      <summary>重试日志</summary>
      <pre>${escapeHtml(JSON.stringify(job.attempt_log, null, 2))}</pre>
    </details>
  `;
}

function renderError(message) {
  resultPanel.className = "result-panel";
  resultPanel.innerHTML = `<div class="error-box">${escapeHtml(message)}</div>`;
}

function setFormBusy(busy) {
  form.querySelector("button[type='submit']").disabled = busy;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || body.message || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }
  return response.json();
}

function statusText(status) {
  return {
    pending: "排队",
    running: "生成中",
    succeeded: "成功",
    failed: "失败",
  }[status] || status;
}

function saveDraft() {
  const payload = formPayload();
  localStorage.setItem("text-image-demo:draft", JSON.stringify(payload));
}

function restoreDraft() {
  const raw = localStorage.getItem("text-image-demo:draft");
  if (!raw) return;
  try {
    const draft = JSON.parse(raw);
    for (const [key, value] of Object.entries(draft)) {
      if (key === "style_preset") {
        state.selectedStyle = value;
        document.querySelectorAll("#styleButtons button").forEach((button) => {
          button.classList.toggle("active", button.dataset.style === value);
        });
      } else if (form.elements[key] && value !== null) {
        form.elements[key].value = value;
      }
    }
  } catch {
    localStorage.removeItem("text-image-demo:draft");
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
