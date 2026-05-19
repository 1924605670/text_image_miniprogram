const state = {
  activeJobId: null,
  pollTimer: null,
  selectedStyle: "cinematic",
  workflow: null,
  selectedWorkflowVersion: "",
};

const form = document.querySelector("#generationForm");
const requirementForm = document.querySelector("#requirementForm");
const resultPanel = document.querySelector("#resultPanel");
const historyList = document.querySelector("#historyList");
const healthBadge = document.querySelector("#healthBadge");
const providerTitle = document.querySelector("#providerTitle");
const refreshHistory = document.querySelector("#refreshHistory");
const workflowBoard = document.querySelector("#workflowBoard");
const versionFilter = document.querySelector("#versionFilter");
const releaseDialog = document.querySelector("#releaseDialog");
const releaseRecordForm = document.querySelector("#releaseRecordForm");

document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadHealth(), loadOptions(), loadHistory(), loadWorkflow()]);
  restoreDraft();
  wireEvents();
  window.lucide?.createIcons();
});

function wireEvents() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    saveDraft();
    await createGeneration();
  });

  requirementForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await createRequirement();
  });

  form.addEventListener("input", saveDraft);
  refreshHistory.addEventListener("click", loadHistory);
  workflowBoard.addEventListener("click", handleWorkflowAction);
  versionFilter.addEventListener("change", async (event) => {
    state.selectedWorkflowVersion = event.target.value;
    await loadWorkflow();
  });
  document.querySelector("#closeReleaseDialog").addEventListener("click", closeReleaseDialog);
  document.querySelector("#cancelReleaseRecord").addEventListener("click", closeReleaseDialog);
  document.querySelector("#markChecklistDone").addEventListener("click", () => {
    releaseRecordForm.elements.release_checklist.value = checkedChecklist(
      releaseRecordForm.elements.release_checklist.value,
    );
  });
  releaseRecordForm.addEventListener("submit", saveReleaseRecord);

  document.querySelector("#formatSelect").addEventListener("change", (event) => {
    const compression = form.elements.output_compression;
    const enabled = ["jpeg", "webp"].includes(event.target.value);
    compression.disabled = !enabled;
    if (!enabled) compression.value = "";
  });
}

function switchView(viewId) {
  document.querySelectorAll(".view-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === viewId);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId);
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

async function loadWorkflow() {
  try {
    const query = state.selectedWorkflowVersion
      ? `?version=${encodeURIComponent(state.selectedWorkflowVersion)}`
      : "";
    state.workflow = await api(`/api/workflow/board${query}`);
    renderWorkflow();
  } catch (error) {
    renderWorkflowError(error.message);
  }
}

async function createRequirement() {
  const data = new FormData(requirementForm);
  const payload = {
    title: String(data.get("title") || "").trim(),
    background: "",
    business_goal: String(data.get("business_goal") || "").trim(),
    priority: String(data.get("priority") || "high"),
    scope: String(data.get("scope") || "").trim(),
    acceptance_criteria: String(data.get("acceptance_criteria") || "").trim(),
    expected_version: String(data.get("expected_version") || "").trim(),
  };
  setRequirementBusy(true);
  try {
    await api("/api/workflow/requirements", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    requirementForm.reset();
    requirementForm.elements.priority.value = "high";
    await loadWorkflow();
  } catch (error) {
    renderWorkflowToast(error.message);
  } finally {
    setRequirementBusy(false);
  }
}

async function handleWorkflowAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, id } = button.dataset;
  button.disabled = true;
  try {
    await runWorkflowAction(action, id);
    await loadWorkflow();
  } catch (error) {
    renderWorkflowToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function runWorkflowAction(action, id) {
  if (action === "confirm-requirement") {
    return api(`/api/workflow/requirements/${id}/confirm`, { method: "POST" });
  }
  if (action === "pause-requirement") {
    return api(`/api/workflow/requirements/${id}/pause`, { method: "POST" });
  }
  if (action === "create-dev") {
    const requirement = findRequirement(id);
    return api("/api/workflow/development-tasks", {
      method: "POST",
      body: JSON.stringify({
        requirement_id: id,
        title: `${requirement.title}开发实现`,
        description: requirement.scope,
        developer: workflowDefault("defaultDeveloper", "dev"),
      }),
    });
  }
  if (action === "start-dev") {
    return api(`/api/workflow/development-tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "in_progress" }),
    });
  }
  if (action === "submit-dev") {
    return api(`/api/workflow/development-tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "submitted_to_test",
        self_test_notes: "开发自测通过：主流程、异常输入、接口错误提示均已覆盖。",
        commit_notes: "本地工作区改动已完成，待测试回归。",
      }),
    });
  }
  if (action === "create-test") {
    const development = findDevelopment(id);
    const requirement = findRequirement(development.requirement_id);
    return api("/api/workflow/test-tasks", {
      method: "POST",
      body: JSON.stringify({
        development_task_id: id,
        tester: workflowDefault("defaultTester", "qa"),
        test_cases: requirement.acceptance_criteria || "覆盖需求验收标准和关键回归路径",
      }),
    });
  }
  if (action === "start-test") {
    return api(`/api/workflow/test-tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "in_progress" }),
    });
  }
  if (action === "pass-test") {
    return api(`/api/workflow/test-tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "passed",
        result_notes: "测试通过：验收标准、核心回归、小程序兼容性检查通过。",
      }),
    });
  }
  if (action === "fail-test") {
    return api(`/api/workflow/test-tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "failed",
        defect_notes: "测试未通过：需开发修复后重新提交测试。",
      }),
    });
  }
  if (action === "create-release") {
    const testTask = findTest(id);
    const requirement = findRequirement(testTask.requirement_id);
    return api("/api/workflow/release-tasks", {
      method: "POST",
      body: JSON.stringify({
        test_task_id: id,
        operator: workflowDefault("defaultOperator", "ops"),
        version: workflowDefault("defaultVersion", requirement.expected_version || "0.2.0-test"),
        release_notes: "服务器部署并提交微信小程序测试版本。",
        rollback_notes: "如测试版异常，回退到上一稳定测试版本。",
      }),
    });
  }
  if (action === "start-release") {
    return api(`/api/workflow/release-tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "in_progress" }),
    });
  }
  if (action === "submit-release") {
    return api(`/api/workflow/release-tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "submitted_test_version",
        server_deploy_result: "服务器部署完成，健康检查通过。",
        mini_program_test_result: "小程序测试版本提交成功，等待产品验收。",
        release_checklist: checkedChecklist(findRelease(id).release_checklist),
      }),
    });
  }
  if (action === "edit-release-record") {
    openReleaseDialog(id);
    return null;
  }
  if (action === "accept-release") {
    return api(`/api/workflow/release-tasks/${id}/acceptance`, {
      method: "PATCH",
      body: JSON.stringify({ status: "accepted", notes: "产品验收通过。" }),
    });
  }
  if (action === "reject-release") {
    const value = prompt("验收阻塞原因", "发现影响验收的问题，需要修复后重新提交。");
    if (value === null) return null;
    return api(`/api/workflow/release-tasks/${id}/acceptance`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "rejected",
        notes: "产品验收未通过，需补齐遗留问题。",
        blocker_notes: value,
      }),
    });
  }
}

function renderWorkflow() {
  const board = state.workflow || emptyWorkflow();
  syncVersionFilter(board);
  document.querySelector("#metricRequirements").textContent = board.requirements.length;
  document.querySelector("#metricDevelopment").textContent = board.development_tasks.length;
  document.querySelector("#metricTesting").textContent = board.test_tasks.length;
  document.querySelector("#metricRelease").textContent = board.release_tasks.filter(
    (item) => item.status === "submitted_test_version",
  ).length;
  document.querySelector("#metricAcceptance").textContent = board.acceptances.filter(
    (item) => item.status === "accepted",
  ).length;
  renderAcceptanceOverview(board);

  renderWorkflowList("#requirementList", board.requirements, requirementCard);
  renderWorkflowList("#developmentList", board.development_tasks, developmentCard);
  renderWorkflowList("#testList", board.test_tasks, testCard);
  renderWorkflowList("#releaseList", board.release_tasks, releaseCard);
  window.lucide?.createIcons();
}

function openReleaseDialog(id) {
  const release = findRelease(id);
  releaseRecordForm.elements.release_id.value = id;
  releaseRecordForm.elements.release_checklist.value = release.release_checklist || defaultReleaseChecklist();
  releaseRecordForm.elements.risk_notes.value = release.risk_notes || "";
  releaseRecordForm.elements.known_issues.value = release.known_issues || "";
  releaseRecordForm.elements.test_version_url.value = release.test_version_url || "";
  document.querySelector("#releaseDialogTitle").textContent = `${release.version || "测试版本"}发布记录`;
  if (typeof releaseDialog.showModal === "function") {
    releaseDialog.showModal();
  } else {
    releaseDialog.setAttribute("open", "");
  }
  window.lucide?.createIcons();
}

function closeReleaseDialog() {
  if (typeof releaseDialog.close === "function") {
    releaseDialog.close();
  } else {
    releaseDialog.removeAttribute("open");
  }
}

async function saveReleaseRecord(event) {
  event.preventDefault();
  const releaseId = releaseRecordForm.elements.release_id.value;
  const submit = releaseRecordForm.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    await api(`/api/workflow/release-tasks/${releaseId}`, {
      method: "PATCH",
      body: JSON.stringify({
        release_checklist: releaseRecordForm.elements.release_checklist.value,
        risk_notes: releaseRecordForm.elements.risk_notes.value,
        known_issues: releaseRecordForm.elements.known_issues.value,
        test_version_url: releaseRecordForm.elements.test_version_url.value,
      }),
    });
    closeReleaseDialog();
    await loadWorkflow();
  } catch (error) {
    renderWorkflowToast(error.message);
  } finally {
    submit.disabled = false;
  }
}

function syncVersionFilter(board) {
  const selected = board.selected_version || state.selectedWorkflowVersion || "";
  const options = [`<option value="">全部版本</option>`]
    .concat(
      (board.versions || []).map((version) => {
        const active = version === selected ? " selected" : "";
        return `<option value="${escapeHtml(version)}"${active}>${escapeHtml(version)}</option>`;
      }),
    )
    .join("");
  if (versionFilter.innerHTML !== options) {
    versionFilter.innerHTML = options;
  }
  versionFilter.value = selected;
}

function renderAcceptanceOverview(board) {
  const releaseCount = board.release_tasks.length;
  const submittedCount = board.release_tasks.filter((item) => item.status === "submitted_test_version").length;
  const acceptedCount = board.acceptances.filter((item) => item.status === "accepted").length;
  const readiness = releaseCount ? Math.round(((submittedCount + acceptedCount) / (releaseCount * 2)) * 100) : 0;
  const riskCount = board.release_tasks.filter((item) => item.risk_notes?.trim()).length;
  const openIssueCount = board.release_tasks.filter((item) => item.known_issues?.trim()).length;
  const blockerCount = board.acceptances.filter(
    (item) => item.status === "rejected" || item.blocker_notes?.trim(),
  ).length;

  document.querySelector("#readinessPercent").textContent = `${readiness}%`;
  document.querySelector("#readinessBar").style.width = `${readiness}%`;
  document.querySelector("#insightReleaseCount").textContent = releaseCount;
  document.querySelector("#insightRiskCount").textContent = riskCount;
  document.querySelector("#insightOpenIssueCount").textContent = openIssueCount;
  document.querySelector("#insightBlockerCount").textContent = blockerCount;
}

function renderWorkflowList(selector, items, renderer) {
  const list = document.querySelector(selector);
  list.innerHTML = items.length ? items.map(renderer).join("") : `<div class="workflow-empty">暂无记录</div>`;
}

function requirementCard(item) {
  const hasDevelopment = state.workflow.development_tasks.some((task) => task.requirement_id === item.id);
  return `
    <article class="workflow-card priority-${item.priority}">
      <div class="workflow-card-head">
        <strong>${escapeHtml(item.title)}</strong>
        <span class="pill ${item.status}">${requirementStatusText(item.status)}</span>
      </div>
      <p>${escapeHtml(item.business_goal)}</p>
      <dl>
        <div><dt>范围</dt><dd>${escapeHtml(item.scope)}</dd></div>
        <div><dt>验收</dt><dd>${escapeHtml(item.acceptance_criteria)}</dd></div>
      </dl>
      <div class="card-actions">
        ${item.status !== "confirmed" ? actionButton("confirm-requirement", item.id, "check", "确认") : ""}
        ${item.status === "confirmed" && !hasDevelopment ? actionButton("create-dev", item.id, "code-2", "拆开发") : ""}
        ${item.status !== "paused" ? actionButton("pause-requirement", item.id, "pause", "暂缓") : ""}
      </div>
    </article>
  `;
}

function developmentCard(item) {
  const requirement = findRequirement(item.requirement_id);
  const hasTest = state.workflow.test_tasks.some((task) => task.development_task_id === item.id);
  return `
    <article class="workflow-card">
      <div class="workflow-card-head">
        <strong>${escapeHtml(item.title)}</strong>
        <span class="pill ${item.status}">${developmentStatusText(item.status)}</span>
      </div>
      <p>${escapeHtml(requirement.title)} · ${escapeHtml(item.developer)}</p>
      <dl>
        <div><dt>任务</dt><dd>${escapeHtml(item.description)}</dd></div>
        ${item.self_test_notes ? `<div><dt>自测</dt><dd>${escapeHtml(item.self_test_notes)}</dd></div>` : ""}
      </dl>
      <div class="card-actions">
        ${item.status === "pending" ? actionButton("start-dev", item.id, "play", "开始") : ""}
        ${item.status !== "submitted_to_test" ? actionButton("submit-dev", item.id, "send", "提测") : ""}
        ${item.status === "submitted_to_test" && !hasTest ? actionButton("create-test", item.id, "test-tube-2", "建测试") : ""}
      </div>
    </article>
  `;
}

function testCard(item) {
  const development = findDevelopment(item.development_task_id);
  const hasRelease = state.workflow.release_tasks.some((task) => task.test_task_id === item.id);
  return `
    <article class="workflow-card">
      <div class="workflow-card-head">
        <strong>${escapeHtml(development.title)}</strong>
        <span class="pill ${item.status}">${testStatusText(item.status)}</span>
      </div>
      <p>${escapeHtml(item.tester)} · ${escapeHtml(findRequirement(item.requirement_id).title)}</p>
      <dl>
        <div><dt>用例</dt><dd>${escapeHtml(item.test_cases)}</dd></div>
        ${item.result_notes ? `<div><dt>结果</dt><dd>${escapeHtml(item.result_notes)}</dd></div>` : ""}
        ${item.defect_notes ? `<div><dt>缺陷</dt><dd>${escapeHtml(item.defect_notes)}</dd></div>` : ""}
      </dl>
      <div class="card-actions">
        ${item.status === "pending" ? actionButton("start-test", item.id, "play", "开始") : ""}
        ${item.status !== "passed" ? actionButton("pass-test", item.id, "check", "通过") : ""}
        ${item.status !== "passed" ? actionButton("fail-test", item.id, "x", "失败") : ""}
        ${item.status === "passed" && !hasRelease ? actionButton("create-release", item.id, "rocket", "建发布") : ""}
      </div>
    </article>
  `;
}

function releaseCard(item) {
  const testTask = findTest(item.test_task_id);
  const acceptance = state.workflow.acceptances.find((entry) => entry.release_task_id === item.id);
  const checklist = checklistState(item.release_checklist);
  return `
    <article class="workflow-card">
      <div class="workflow-card-head">
        <strong>${escapeHtml(item.version || "测试版本")}</strong>
        <span class="pill ${item.status}">${releaseStatusText(item.status)}</span>
      </div>
      <p>${escapeHtml(item.operator)} · ${escapeHtml(findRequirement(testTask.requirement_id).title)}</p>
      <div class="release-readiness">
        <span>${checklist.done}/${checklist.total || 1}</span>
        <div><i style="width: ${checklist.percent}%"></i></div>
      </div>
      <dl>
        <div><dt>发布说明</dt><dd>${escapeHtml(item.release_notes || "待记录")}</dd></div>
        <div><dt>检查清单</dt><dd>${releaseChecklistHtml(item.release_checklist)}</dd></div>
        ${item.server_deploy_result ? `<div><dt>服务</dt><dd>${escapeHtml(item.server_deploy_result)}</dd></div>` : ""}
        ${item.mini_program_test_result ? `<div><dt>测试版</dt><dd>${escapeHtml(item.mini_program_test_result)}</dd></div>` : ""}
        ${item.test_version_url ? `<div><dt>测试入口</dt><dd>${linkOrText(item.test_version_url)}</dd></div>` : ""}
        ${item.risk_notes ? `<div><dt>风险</dt><dd class="risk-text">${escapeHtml(item.risk_notes)}</dd></div>` : ""}
        ${item.known_issues ? `<div><dt>遗留</dt><dd class="issue-text">${escapeHtml(item.known_issues)}</dd></div>` : ""}
        ${
          acceptance
            ? `<div><dt>验收</dt><dd>${acceptanceStatusText(acceptance.status)} ${escapeHtml(acceptance.notes)} ${
                acceptance.blocker_notes ? `阻塞：${escapeHtml(acceptance.blocker_notes)}` : ""
              }</dd></div>`
            : ""
        }
      </dl>
      <div class="card-actions">
        ${item.status === "pending" ? actionButton("start-release", item.id, "play", "发布") : ""}
        ${actionButton("edit-release-record", item.id, "file-pen-line", "记录")}
        ${item.status !== "submitted_test_version" ? actionButton("submit-release", item.id, "upload-cloud", "提交测试版") : ""}
        ${item.status === "submitted_test_version" ? actionButton("accept-release", item.id, "check", "验收通过") : ""}
        ${item.status === "submitted_test_version" ? actionButton("reject-release", item.id, "x", "验收驳回") : ""}
      </div>
    </article>
  `;
}

function actionButton(action, id, icon, label) {
  return `
    <button class="secondary-action compact-action" type="button" data-action="${action}" data-id="${id}">
      <i data-lucide="${icon}"></i><span>${label}</span>
    </button>
  `;
}

function renderWorkflowError(message) {
  ["#requirementList", "#developmentList", "#testList", "#releaseList"].forEach((selector) => {
    document.querySelector(selector).innerHTML = `<div class="error-box">${escapeHtml(message)}</div>`;
  });
}

function renderWorkflowToast(message) {
  const list = document.querySelector("#requirementList");
  list.insertAdjacentHTML("afterbegin", `<div class="error-box">${escapeHtml(message)}</div>`);
}

function findRequirement(id) {
  return state.workflow.requirements.find((item) => item.id === id) || { title: "未知需求", scope: "" };
}

function findDevelopment(id) {
  return (
    state.workflow.development_tasks.find((item) => item.id === id) || {
      title: "未知开发任务",
      requirement_id: "",
    }
  );
}

function findTest(id) {
  return state.workflow.test_tasks.find((item) => item.id === id) || { requirement_id: "" };
}

function findRelease(id) {
  return state.workflow.release_tasks.find((item) => item.id === id) || {};
}

function checklistState(value) {
  const source = String(value || defaultReleaseChecklist());
  const lines = source
    .split("\n")
    .map((line) => line.trim().toLowerCase())
    .filter(Boolean);
  const items = lines.filter((line) => line.startsWith("- ["));
  const total = items.length || (source.trim() ? 1 : 0);
  const done = items.length ? items.filter((line) => line.startsWith("- [x]")).length : total;
  return {
    done,
    total,
    percent: total ? Math.round((done / total) * 100) : 0,
  };
}

function checkedChecklist(value) {
  const source = String(value || defaultReleaseChecklist());
  return source
    .split("\n")
    .map((line) => {
      if (line.trim().startsWith("- [ ]")) return line.replace("- [ ]", "- [x]");
      return line;
    })
    .join("\n");
}

function releaseChecklistHtml(value) {
  const lines = String(value || defaultReleaseChecklist())
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  return `
    <ul class="checklist-view">
      ${lines
        .map((line) => {
          const checked = line.toLowerCase().startsWith("- [x]");
          const text = line.replace(/^- \[[ xX]\]\s*/, "");
          return `<li class="${checked ? "done" : ""}"><span>${checked ? "OK" : "--"}</span>${escapeHtml(text)}</li>`;
        })
        .join("")}
    </ul>
  `;
}

function defaultReleaseChecklist() {
  return [
    "- [ ] 服务器部署健康检查通过",
    "- [ ] 小程序测试版提交记录完整",
    "- [ ] 回滚方案和负责人已确认",
  ].join("\n");
}

function linkOrText(value) {
  const safe = escapeHtml(value);
  if (/^https?:\/\//i.test(value)) {
    return `<a href="${safe}" target="_blank" rel="noreferrer">${safe}</a>`;
  }
  return safe;
}

function workflowDefault(id, fallback) {
  return document.querySelector(`#${id}`)?.value.trim() || fallback;
}

function setRequirementBusy(busy) {
  requirementForm.querySelector("button[type='submit']").disabled = busy;
}

function emptyWorkflow() {
  return {
    requirements: [],
    development_tasks: [],
    test_tasks: [],
    release_tasks: [],
    acceptances: [],
    versions: [],
    selected_version: "",
  };
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

function requirementStatusText(status) {
  return {
    draft: "草稿",
    pending_confirmation: "待确认",
    confirmed: "已确认",
    paused: "暂缓",
  }[status] || status;
}

function developmentStatusText(status) {
  return {
    pending: "待开发",
    in_progress: "开发中",
    pending_self_test: "待自测",
    self_test_passed: "自测通过",
    submitted_to_test: "已提测",
  }[status] || status;
}

function testStatusText(status) {
  return {
    pending: "待测试",
    in_progress: "测试中",
    failed: "测试失败",
    retesting: "复测中",
    passed: "测试通过",
  }[status] || status;
}

function releaseStatusText(status) {
  return {
    pending: "待发布",
    in_progress: "发布中",
    submitted_test_version: "已提交测试版",
    failed: "发布失败",
  }[status] || status;
}

function acceptanceStatusText(status) {
  return {
    pending: "待验收",
    accepted: "验收通过",
    rejected: "验收驳回",
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
