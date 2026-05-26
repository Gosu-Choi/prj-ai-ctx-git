const state = {
  project: null,
  activeBranch: null,
  branches: [],
  views: [],
  payload: null,
  provider: null,
  currentJob: null,
  jobs: {},
  branchJobs: {},
  branchActivityAt: {},
  acknowledgedBranchJobs: {},
  startingBranches: {},
};

const els = {
  projectSummary: document.querySelector("#projectSummary"),
  projectForm: document.querySelector("#projectForm"),
  projectPathInput: document.querySelector("#projectPathInput"),
  openProjectButton: document.querySelector("#openProjectButton"),
  initProjectButton: document.querySelector("#initProjectButton"),
  browseProjectButton: document.querySelector("#browseProjectButton"),
  projectStatus: document.querySelector("#projectStatus"),
  branchList: document.querySelector("#branchList"),
  viewList: document.querySelector("#viewList"),
  gitSummary: document.querySelector("#gitSummary"),
  providerSummary: document.querySelector("#providerSummary"),
  mergeForm: document.querySelector("#mergeForm"),
  mergeSourcesInput: document.querySelector("#mergeSourcesInput"),
  mergeNameInput: document.querySelector("#mergeNameInput"),
  mergeButton: document.querySelector("#mergeButton"),
  mergeStatus: document.querySelector("#mergeStatus"),
  providerSettings: document.querySelector("#providerSettings"),
  webSearchInput: document.querySelector("#webSearchInput"),
  timeoutSecondsInput: document.querySelector("#timeoutSecondsInput"),
  sandboxInput: document.querySelector("#sandboxInput"),
  saveProviderButton: document.querySelector("#saveProviderButton"),
  providerSettingsStatus: document.querySelector("#providerSettingsStatus"),
  activeTitle: document.querySelector("#activeTitle"),
  activeMeta: document.querySelector("#activeMeta"),
  chatTab: document.querySelector("#chatTab"),
  messageList: document.querySelector("#messageList"),
  progressPanel: document.querySelector("#progressPanel"),
  progressTitle: document.querySelector("#progressTitle"),
  progressEvents: document.querySelector("#progressEvents"),
  eventPanel: document.querySelector("#eventPanel"),
  eventStatus: document.querySelector("#eventStatus"),
  copyEventLogButton: document.querySelector("#copyEventLogButton"),
  eventCopyStatus: document.querySelector("#eventCopyStatus"),
  eventMeta: document.querySelector("#eventMeta"),
  eventList: document.querySelector("#eventList"),
  reportView: document.querySelector("#reportView"),
  archiveList: document.querySelector("#archiveList"),
  archiveViewer: document.querySelector("#archiveViewer"),
  trackedFiles: document.querySelector("#trackedFiles"),
  historyLog: document.querySelector("#historyLog"),
  currentDiff: document.querySelector("#currentDiff"),
  researchList: document.querySelector("#researchList"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  researchButton: document.querySelector("#researchButton"),
  historyChatButton: document.querySelector("#historyChatButton"),
  refreshButton: document.querySelector("#refreshButton"),
};

class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { message: text };
    }
  }
  if (!response.ok) {
    throw new ApiError(payload.message || payload.error || `Request failed: ${response.status}`, response.status, payload);
  }
  return payload;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function formatEventTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDuration(seconds) {
  const total = Number.parseInt(seconds, 10);
  if (!Number.isFinite(total) || total < 0) return "0s";
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function renderInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}

function projectAbsolutePath(path) {
  const root = state.project?.path || "";
  if (!root) return path;
  const separator = root.includes("\\") || /^[A-Za-z]:/.test(root) ? "\\" : "/";
  const cleanRoot = root.replace(/[\\/]+$/, "");
  const cleanPath = String(path || "").replace(/^[\\/]+/, "");
  return `${cleanRoot}${separator}${cleanPath.replace(/[\\/]+/g, separator)}`;
}

function obsidianFileUrl(path) {
  const absolutePath = projectAbsolutePath(path);
  return `obsidian://open?path=${encodeURIComponent(absolutePath)}&paneType=tab`;
}

function renderProjectFileLinks(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(
    /(^|[\s(`])((?:contexts|\.ctxgit)\/[^\s<>"'`)]*\.(?:md|txt|json|jsonl|pdf|csv|tsv|html?))/g,
    (_match, prefix, path) =>
      `${prefix}<a class="file-link" href="${escapeHtml(obsidianFileUrl(path))}" title="Open in Obsidian">${path}</a>`,
  );
}

function renderMessageText(text) {
  return renderProjectFileLinks(text);
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").split("\n");
  const html = [];
  let listOpen = false;
  let tableRows = [];

  const closeList = () => {
    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
  };
  const flushTable = () => {
    if (tableRows.length === 0) return;
    const rows = tableRows;
    tableRows = [];
    if (rows.length < 2 || !/^\s*\|?\s*:?-{3,}/.test(rows[1])) {
      rows.forEach((row) => html.push(`<p>${renderInline(row)}</p>`));
      return;
    }
    html.push("<table>");
    rows.forEach((row, index) => {
      if (index === 1) return;
      const cells = row
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
      const tag = index === 0 ? "th" : "td";
      html.push(`<tr>${cells.map((cell) => `<${tag}>${renderInline(cell)}</${tag}>`).join("")}</tr>`);
    });
    html.push("</table>");
  };

  for (const line of lines) {
    if (line.includes("|") && line.trim().startsWith("|")) {
      closeList();
      tableRows.push(line);
      continue;
    }
    flushTable();
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^\s*-\s+(.*)$/);
    if (bullet) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${renderInline(bullet[1])}</li>`);
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    closeList();
    html.push(`<p>${renderInline(line)}</p>`);
  }
  flushTable();
  closeList();
  return html.join("\n");
}

function setProjectStatus(message, kind = "") {
  els.projectStatus.textContent = message;
  els.projectStatus.className = `settings-status ${kind}`.trim();
}

function clearWorkspace(message = "Select or initialize a ctxgit project.") {
  state.activeBranch = null;
  state.branches = [];
  state.views = [];
  state.payload = null;
  renderBranches();
  els.activeTitle.textContent = "No project selected";
  els.activeMeta.textContent = message;
  els.messageList.innerHTML = `<div class="muted">${escapeHtml(message)}</div>`;
  els.reportView.innerHTML = "";
  els.archiveList.innerHTML = "";
  els.archiveViewer.innerHTML = '<div class="muted">No archived source branch selected.</div>';
  els.trackedFiles.innerHTML = "";
  els.historyLog.textContent = "";
  els.currentDiff.textContent = "";
  els.researchList.innerHTML = "";
  els.gitSummary.innerHTML = "";
  els.providerSummary.innerHTML = "";
  els.mergeStatus.textContent = "";
  hideProgress();
  hideEventPanel();
}

function renderProject(project) {
  state.project = project;
  const path = project?.path || "";
  const initialized = project?.initialized === true;
  const gitInitialized = project?.gitInitialized === true;
  els.projectPathInput.value = path;
  els.projectSummary.innerHTML = `
    <div><strong>${escapeHtml(project?.name || "No project")}</strong></div>
    <div class="muted">${escapeHtml(path)}</div>
    <div class="muted">ctxgit: ${initialized ? "ready" : "not initialized"} · git: ${gitInitialized ? "ready" : "not initialized"}</div>
  `;
}

function renderBranches() {
  els.branchList.innerHTML = orderedBranches()
    .map((branch) => {
      const job = branchJob(branch.id);
      const startingMode = state.startingBranches[branch.id] || "";
      const isRunning = Boolean(startingMode) || job?.status === "running";
      const isDoneUnseen = job?.status === "done" && !isBranchJobAcknowledged(branch.id);
      const statusClass = isRunning ? "job-running" : isDoneUnseen ? "job-done" : job?.status === "failed" ? "job-failed" : "";
      const jobLabel =
        isRunning
          ? ` · 실행 중 ${startingMode || job?.mode || job?.kind || "job"}`
          : isDoneUnseen
          ? " · 완료됨"
          : job?.status === "failed"
          ? " · 최근 작업 실패"
          : "";
      return `
        <div class="branch-row ${branch.id === state.activeBranch ? "active" : ""} ${statusClass}">
          <button class="nav-item branch-main ${branch.id === state.activeBranch ? "active" : ""}" data-branch="${escapeHtml(branch.id)}" type="button">
            <span class="nav-title">${escapeHtml(branch.title)}</span>
            <span class="nav-meta">${escapeHtml(branch.id)} · ${branch.historyCount} messages${escapeHtml(jobLabel)}</span>
          </button>
          <button class="branch-options-button" data-branch-options="${escapeHtml(branch.id)}" type="button" aria-label="Branch options">...</button>
          <div class="branch-options-menu">
            <button data-branch-rename="${escapeHtml(branch.id)}" data-branch-title="${escapeHtml(branch.title)}" type="button">Rename branch</button>
            <button data-branch-clone="${escapeHtml(branch.id)}" type="button">Clone branch</button>
            <button class="danger" data-branch-remove="${escapeHtml(branch.id)}" type="button">Remove branch</button>
          </div>
        </div>
      `;
    })
    .join("") || '<div class="muted">No branches yet</div>';
  els.branchList.querySelectorAll("[data-branch]").forEach((button) => {
    button.addEventListener("click", () => loadBranch(button.dataset.branch));
  });
  els.branchList.querySelectorAll("[data-branch-options]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const row = button.closest(".branch-row");
      const wasOpen = row.classList.contains("open");
      closeBranchMenus();
      row.classList.toggle("open", !wasOpen);
    });
  });
  els.branchList.querySelectorAll("[data-branch-clone]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      closeBranchMenus();
      const source = button.dataset.branchClone;
      const title = window.prompt(`Clone ${source} with title:`, `${branchTitle(source)} copy`);
      if (!title) return;
      await cloneBranch(source, title.trim());
    });
  });
  els.branchList.querySelectorAll("[data-branch-rename]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      closeBranchMenus();
      const branch = button.dataset.branchRename;
      const currentTitle = button.dataset.branchTitle || branch;
      const title = window.prompt(`Rename ${branch} to:`, currentTitle);
      if (!title) return;
      await renameBranch(branch, title.trim());
    });
  });
  els.branchList.querySelectorAll("[data-branch-remove]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      closeBranchMenus();
      const branch = button.dataset.branchRemove;
      if (!window.confirm(`Remove branch "${branch}"? This deletes its ctxgit files from the project.`)) return;
      await removeBranch(branch);
    });
  });

  els.viewList.innerHTML =
    state.views
      .map(
        (view) => `
          <button class="nav-item" data-view="${escapeHtml(view.id)}" type="button">
            <span class="nav-title">${escapeHtml(view.id)}</span>
            <span class="nav-meta">${escapeHtml(view.path)}</span>
          </button>
        `,
      )
      .join("") || '<div class="muted">No views yet</div>';
  els.viewList.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => loadView(button.dataset.view));
  });
}

function closeBranchMenus() {
  document.querySelectorAll(".branch-row.open").forEach((row) => row.classList.remove("open"));
}

function closeMessageMenus() {
  document.querySelectorAll(".message-options.open").forEach((item) => item.classList.remove("open"));
}

function jobStartedAt(job) {
  return Date.parse(job?.createdAt || job?.updatedAt || "") || 0;
}

function markBranchActivity(branchId, timestamp = Date.now()) {
  if (!branchId) return;
  state.branchActivityAt[branchId] = timestamp || Date.now();
}

function isBranchJobAcknowledged(branchId) {
  const job = branchJob(branchId);
  return Boolean(job?.id && state.acknowledgedBranchJobs[branchId] === job.id);
}

function acknowledgeBranchJob(branchId) {
  const job = branchJob(branchId);
  if (job?.id && job.status !== "running") {
    state.acknowledgedBranchJobs[branchId] = job.id;
  }
}

function branchActivityTime(branchId) {
  const job = branchJob(branchId);
  return state.branchActivityAt[branchId] || jobStartedAt(job);
}

function orderedBranches() {
  return state.branches
    .map((branch, index) => ({ branch, index }))
    .sort((left, right) => {
      const leftActivity = branchActivityTime(left.branch.id);
      const rightActivity = branchActivityTime(right.branch.id);
      if (leftActivity || rightActivity) {
        if (!leftActivity) return 1;
        if (!rightActivity) return -1;
        const timeDiff = rightActivity - leftActivity;
        if (timeDiff) return timeDiff;
      }
      return left.index - right.index;
    })
    .map((item) => item.branch);
}

function branchTitle(branchId) {
  const branch = state.branches.find((item) => item.id === branchId);
  return branch?.title || branchId;
}

function branchIdFromTitle(title) {
  const normalized = title
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9._-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[^a-z0-9]+/, "")
    .replace(/[^a-z0-9]+$/, "");
  return (normalized || "branch").slice(0, 80).replace(/[^a-z0-9]+$/, "") || "branch";
}

function uniqueBranchIdForTitle(title) {
  const existing = new Set(state.branches.map((branch) => branch.id));
  const base = branchIdFromTitle(title);
  if (!existing.has(base)) return base;
  for (let index = 1; index < 1000; index += 1) {
    const suffix = `_${index}`;
    const candidate = `${base.slice(0, 80 - suffix.length).replace(/[^a-z0-9]+$/, "") || "branch"}${suffix}`;
    if (!existing.has(candidate)) return candidate;
  }
  return `${base.slice(0, 66).replace(/[^a-z0-9]+$/, "") || "branch"}_${Date.now().toString(36)}`;
}

function renderGit(status) {
  els.gitSummary.innerHTML = `
    <div>Branch: <strong>${escapeHtml(status.branch || "(none)")}</strong></div>
    <div>Staged: ${status.stagedCount} · Unstaged: ${status.unstagedCount} · Untracked: ${status.untrackedCount}</div>
  `;
}

function renderProvider(status) {
  state.provider = status;
  const webSearch = status.webSearch === false ? "off" : "on";
  const timeoutSeconds = status.timeoutSeconds || 900;
  const sandbox = status.sandbox || "workspace-write";
  const braveStatus = status.braveApiKeyConfigured
    ? `configured via ${status.braveApiKeySource || "environment"}`
    : "not configured";
  els.providerSummary.innerHTML = `
    <div>Provider: <strong>${escapeHtml(status.provider || "codex")}</strong></div>
    <div>${escapeHtml(status.message || status.status || "")}</div>
    <div class="muted">Web search: ${webSearch} · Timeout: ${escapeHtml(String(timeoutSeconds))}s</div>
    <div class="muted">Brave search: ${escapeHtml(braveStatus)}</div>
    <div class="muted">Sandbox: ${escapeHtml(sandbox)}</div>
    <div class="muted">External writes: approval required</div>
    ${
      status.ok
        ? ""
        : `<div class="muted">Login: <code>${escapeHtml(status.loginCommand || "codex login --device-auth")}</code></div>`
    }
  `;
  els.webSearchInput.checked = webSearch === "on";
  els.timeoutSecondsInput.value = timeoutSeconds;
  els.sandboxInput.value = sandbox;
  els.providerSettingsStatus.textContent = "";
  els.providerSettingsStatus.className = "settings-status";
}

function renderArtifacts(artifacts) {
  if (!Array.isArray(artifacts) || artifacts.length === 0) return "";
  return `
    <div class="artifact-links">
      ${artifacts
        .map(
          (artifact) => {
            const path = artifact.path || "";
            const label = path ? `<a class="file-link" href="${escapeHtml(obsidianFileUrl(path))}" title="Open in Obsidian"><code>${escapeHtml(path)}</code></a>` : "<code></code>";
            return `<div>${escapeHtml(artifact.kind || "artifact")}: ${label}</div>`;
          },
        )
        .join("")}
    </div>
  `;
}

function renderApprovalRequests(requests, statuses = {}) {
  if (!Array.isArray(requests) || requests.length === 0) return "";
  return `
    <div class="approval-requests">
      ${requests
        .map((request) => {
          const id = request.id || "";
          const status = statuses[id] || request.status || "pending";
          const path = request.path || "";
          const operation = request.operation || "write-outside-workspace";
          const reason = request.reason || "";
          const actions =
            status === "pending"
              ? `
                <div class="approval-actions">
                  <button data-approval="${escapeHtml(id)}" data-decision="approved" data-path="${escapeHtml(path)}" type="button">Approve</button>
                  <button data-approval="${escapeHtml(id)}" data-decision="denied" data-path="${escapeHtml(path)}" type="button">Deny</button>
                </div>
              `
              : `<div class="approval-status">${escapeHtml(status)}</div>`;
          return `
            <div class="approval-request">
              <div><strong>External file access</strong>: ${escapeHtml(operation)}</div>
              <div><code>${escapeHtml(path)}</code></div>
              <div class="nav-meta">${escapeHtml(reason)}</div>
              ${actions}
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function scrollChatToBottom() {
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      els.chatTab.scrollTo({ top: els.chatTab.scrollHeight, behavior: "auto" });
    });
  });
}

function showProgress(title) {
  els.progressPanel.hidden = false;
  els.progressTitle.textContent = title;
  els.progressEvents.innerHTML = "";
  scrollChatToBottom();
}

function updateProgress(job) {
  const events = Array.isArray(job.events) ? job.events.slice(-5) : [];
  const latest = events.length ? events[events.length - 1].message : job.status || "Working";
  els.progressTitle.textContent =
    job.status === "done" ? "완료됨" : job.status === "failed" ? "실패" : latest || "작업 중";
  els.progressEvents.innerHTML = events
    .map((event) => `<div>${escapeHtml(event.message || "")}</div>`)
    .join("");
}

function hideProgress() {
  els.progressPanel.hidden = true;
  els.progressTitle.textContent = "";
  els.progressEvents.innerHTML = "";
}

function renderEventPanel(job) {
  if (!job || !job.id) return;
  state.currentJob = job;
  els.chatTab.classList.add("event-visible");
  els.copyEventLogButton.disabled = false;
  const diagnostics = job.diagnostics || {};
  els.eventStatus.textContent = diagnostics.state || job.status || "";
  const eventCount = Array.isArray(job.events) ? job.events.length : 0;
  const started = formatEventTime(job.createdAt);
  const updated = formatEventTime(job.updatedAt);
  els.eventMeta.innerHTML = `
    <div>작업: <code>${escapeHtml(job.id)}</code></div>
    <div>종류: ${escapeHtml(job.kind || "")}</div>
    <div>경과: ${escapeHtml(formatDuration(diagnostics.elapsedSeconds))} · 유휴: ${escapeHtml(formatDuration(diagnostics.idleSeconds))}</div>
    ${diagnostics.detail ? `<div>${escapeHtml(diagnostics.detail)}</div>` : ""}
    <div>시작: ${escapeHtml(started)} · 갱신: ${escapeHtml(updated)} · 이벤트: ${eventCount}</div>
    ${job.message ? `<div>오류: ${escapeHtml(job.message)}</div>` : ""}
  `;
  els.eventList.innerHTML =
    (job.events || [])
      .map(
        (event) => `
          <div class="event-item">
            <div class="event-time">${escapeHtml(formatEventTime(event.createdAt))}</div>
            <div class="event-message">${escapeHtml(event.message || "")}</div>
          </div>
        `,
      )
      .join("") || '<div class="muted">아직 이벤트가 없습니다.</div>';
  els.eventList.scrollTop = els.eventList.scrollHeight;
}

function hideEventPanel() {
  state.currentJob = null;
  els.eventStatus.textContent = "";
  els.eventCopyStatus.textContent = "";
  els.copyEventLogButton.disabled = true;
  els.eventMeta.innerHTML = '<div>작업 이벤트가 여기에 표시됩니다.</div>';
  els.eventList.innerHTML = '<div class="muted">아직 이벤트가 없습니다.</div>';
}

function buildEventLogText(job) {
  const diagnostics = job.diagnostics || {};
  const lines = [
    "ctxgit event log",
    `작업: ${job.id || ""}`,
    `종류: ${job.kind || ""}`,
    `상태: ${diagnostics.state || job.status || ""}`,
    `생성: ${job.createdAt || ""}`,
    `갱신: ${job.updatedAt || ""}`,
    `경과: ${formatDuration(diagnostics.elapsedSeconds)}`,
    `유휴: ${formatDuration(diagnostics.idleSeconds)}`,
  ];
  if (diagnostics.detail) lines.push(`상세: ${diagnostics.detail}`);
  if (job.message) lines.push(`오류: ${job.message}`);
  lines.push("", "이벤트:");
  (job.events || []).forEach((event, index) => {
    lines.push(`${index + 1}. [${event.createdAt || ""}] ${event.message || ""}`);
  });
  return lines.join("\n");
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

async function copyEventLog() {
  if (!state.currentJob) return;
  try {
    await copyTextToClipboard(buildEventLogText(state.currentJob));
    els.eventCopyStatus.textContent = "복사됨.";
  } catch (error) {
    els.eventCopyStatus.textContent = `복사 실패: ${error.message}`;
  }
  window.setTimeout(() => {
    els.eventCopyStatus.textContent = "";
  }, 1800);
}

function hideProgressSoon() {
  window.setTimeout(() => {
    if (els.progressTitle.textContent === "완료됨") hideProgress();
  }, 900);
}

function rememberJob(job, meta = {}) {
  if (!job || !job.id) return job;
  const previous = state.jobs[job.id] || {};
  const remembered = {
    ...previous,
    ...job,
    branch: meta.branch || previous.branch || job.branch || "",
    mode: meta.mode || previous.mode || job.mode || "",
  };
  state.jobs[job.id] = remembered;
  if (remembered.branch) {
    const previousBranchJobId = state.branchJobs[remembered.branch];
    state.branchJobs[remembered.branch] = remembered.id;
    if (previousBranchJobId !== remembered.id) {
      markBranchActivity(remembered.branch, jobStartedAt(remembered));
      delete state.acknowledgedBranchJobs[remembered.branch];
    }
  }
  return remembered;
}

function branchJob(branch = state.activeBranch) {
  const jobId = branch ? state.branchJobs[branch] : "";
  return jobId ? state.jobs[jobId] : null;
}

function activeBranchRunningJob(branch = state.activeBranch) {
  const job = branchJob(branch);
  return job?.status === "running" ? job : null;
}

function updateComposerState() {
  const running = activeBranchRunningJob();
  const startingMode = state.activeBranch ? state.startingBranches[state.activeBranch] : "";
  const disabled = !state.activeBranch || Boolean(running) || Boolean(startingMode);
  els.sendButton.disabled = disabled;
  els.researchButton.disabled = disabled;
  els.historyChatButton.disabled = disabled;
  const busyMode = running?.mode || startingMode;
  els.sendButton.textContent = busyMode === "chat" ? "생각 중" : "Send";
  els.researchButton.textContent = busyMode === "research" ? "리서치 중" : "Research";
  els.historyChatButton.textContent = busyMode === "info-chat" ? "Info..." : "Info chat";
}

function renderActiveBranchJob() {
  const job = branchJob();
  if (!job) {
    hideProgress();
    hideEventPanel();
    updateComposerState();
    return;
  }
  renderEventPanel(job);
  if (job.status === "running") {
    updateProgress(job);
  } else {
    hideProgress();
  }
  updateComposerState();
}

async function refreshBranchNavigation() {
  const data = await api("/api/branches");
  state.branches = data.branches || [];
  state.views = data.views || [];
  renderBranches();
}

async function startTrackedJob(endpoint, body, { branch, mode, title }) {
  const started = await api(endpoint, {
    method: "POST",
    body: JSON.stringify(body),
  });
  const remembered = rememberJob(started, { branch, mode });
  if (state.activeBranch === branch) {
    showProgress(title);
    updateProgress(remembered);
    renderEventPanel(remembered);
  }
  updateComposerState();
  refreshBranchNavigation().catch(() => {});
  monitorTrackedJob(remembered.id).catch((error) => handleMonitorError(remembered, error));
  return remembered;
}

function handleMonitorError(job, error) {
  const now = new Date().toISOString();
  const failed = rememberJob(
    {
      ...job,
      status: "failed",
      error: "monitor_failed",
      message: error.message || "작업 모니터링 실패",
      updatedAt: now,
      events: [...(job.events || []), { message: `실패: ${error.message || "작업 모니터링 실패"}`, createdAt: now }],
      diagnostics: {
        elapsedSeconds: 0,
        idleSeconds: 0,
        state: "monitor_failed",
        detail: error.message || "작업 모니터링 실패",
        lastEvent: "모니터링 실패",
      },
    },
    { branch: job.branch, mode: job.mode },
  );
  if (state.activeBranch === failed.branch) {
    renderEventPanel(failed);
    els.messageList.insertAdjacentHTML(
      "beforebegin",
      `<div class="error-banner">작업 모니터링 실패: ${escapeHtml(failed.message)}</div>`,
    );
    hideProgress();
  }
  updateComposerState();
}

async function monitorTrackedJob(jobId) {
  const tracked = state.jobs[jobId];
  if (!tracked) return;
  const branch = tracked.branch;
  let waitMs = 500;
  while (true) {
    await sleep(waitMs);
    let job;
    try {
      job = await api(`/api/job?id=${encodeURIComponent(jobId)}`);
    } catch (error) {
      if (error instanceof ApiError && error.payload?.error === "job_not_found") {
        const message =
          "ctxgit 서버가 이 작업을 더 이상 갖고 있지 않습니다. 서버가 재시작되었거나 브라우저가 다른 ctxgit 서버를 조회 중일 수 있습니다.";
        const now = new Date().toISOString();
        job = {
          ...tracked,
          status: "failed",
          error: "job_not_found",
          message,
          updatedAt: now,
        events: [...(tracked.events || []), { message: `실패: ${message}`, createdAt: now }],
          diagnostics: {
            elapsedSeconds: 0,
            idleSeconds: 0,
            state: "job_not_found",
            detail: message,
            lastEvent: "job not found",
          },
        };
      } else {
        throw error;
      }
    }
    const remembered = rememberJob(job, { branch, mode: tracked.mode });
    const isActiveBranch = state.activeBranch === branch;
    if (state.activeBranch === branch) {
      updateProgress(remembered);
      renderEventPanel(remembered);
      updateComposerState();
    }
    if (remembered.status === "done") {
      if (isActiveBranch) {
        acknowledgeBranchJob(branch);
      }
      await refreshBranchNavigation().catch(() => {});
      if (state.activeBranch === branch) {
        renderBranch(remembered.payload);
        renderGit(await api("/api/git/status"));
        renderProvider(await api("/api/provider/status"));
        hideProgressSoon();
      }
      updateComposerState();
      return;
    }
    if (remembered.status === "failed") {
      renderBranches();
      if (state.activeBranch === branch) {
        const prefix = remembered.error === "timeout" ? "시간 초과" : remembered.error === "job_not_found" ? "중단됨" : remembered.mode === "research" ? "리서치 실패" : "채팅 실패";
        els.messageList.insertAdjacentHTML(
          "beforebegin",
          `<div class="error-banner">${prefix}: ${escapeHtml(remembered.message || "작업 실패")}</div>`,
        );
        hideProgress();
      }
      updateComposerState();
      return;
    }
    waitMs = Math.min(1200, waitMs + 100);
  }
}

function renderBranch(payload) {
  state.payload = payload;
  const meta = payload.meta;
  els.activeTitle.textContent = meta.title || meta.id;
  els.activeMeta.textContent = `${meta.id} · history.jsonl is Git-tracked conversation history`;

  els.messageList.innerHTML =
    payload.history
      .map(
        (message, index) => `
          <article class="message">
            <div class="message-header">
              <span class="message-role">${escapeHtml(message.role)}</span>
              <span class="message-meta-actions">
                <span>${escapeHtml(message.createdAt)}</span>
                <span class="message-options">
                  <button
                    class="message-options-button"
                    data-message-options="${index}"
                    type="button"
                    title="Message options"
                    aria-label="Message options"
                  >...</button>
                  <span class="message-options-menu">
                    <button
                      data-history-fork="${index}"
                      data-history-created-at="${escapeHtml(message.createdAt || "")}"
                      data-history-role="${escapeHtml(message.role || "")}"
                      type="button"
                    >Fork here</button>
                    <button
                      class="danger"
                      data-history-delete="${index}"
                      data-history-created-at="${escapeHtml(message.createdAt || "")}"
                      data-history-role="${escapeHtml(message.role || "")}"
                      type="button"
                    >Delete message</button>
                  </span>
                </span>
              </span>
            </div>
            <div class="message-text">${renderMessageText(message.text)}</div>
            ${renderArtifacts(message.artifacts)}
            ${renderApprovalRequests(message.approvalRequests, payload.approvalStatuses || {})}
          </article>
        `,
      )
      .join("") || '<div class="muted">No messages yet.</div>';
  els.messageList.querySelectorAll("[data-approval]").forEach((button) => {
    button.addEventListener("click", () => decideApproval(button));
  });
  els.messageList.querySelectorAll("[data-message-options]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = button.closest(".message-options");
      const wasOpen = menu?.classList.contains("open");
      closeMessageMenus();
      if (menu && !wasOpen) menu.classList.add("open");
    });
  });
  els.messageList.querySelectorAll("[data-history-fork]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMessageMenus();
      forkHistoryMessage(button);
    });
  });
  els.messageList.querySelectorAll("[data-history-delete]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMessageMenus();
      deleteHistoryMessage(button);
    });
  });
  scrollChatToBottom();

  els.reportView.innerHTML = renderMarkdown(payload.context);
  els.trackedFiles.innerHTML = `
    <dt>context</dt><dd>${escapeHtml(payload.paths.context)}</dd>
    <dt>history</dt><dd>${escapeHtml(payload.paths.history)}</dd>
    <dt>meta</dt><dd>${escapeHtml(payload.paths.meta)}</dd>
  `;
  els.historyLog.textContent = payload.git.historyLog || "No commits for this history file yet.";
  els.currentDiff.textContent =
    [payload.git.status, payload.git.historyDiff, payload.git.contextDiff].filter(Boolean).join("\n\n") ||
    "No uncommitted branch file diff.";
  els.researchList.innerHTML =
    [
      ...(payload.sources || []).map((source) => ({
        title: source.sourcePath || "source",
        path: source.textPath || source.sourcePath || "",
        status: source.status || "",
      })),
      ...(payload.compactions || []).map((compaction) => ({
        title: compaction.title || "history compaction",
        path: compaction.path || "",
        status: "history compaction",
      })),
      ...(payload.research || []),
      ...(payload.artifacts || []),
    ]
      .map(
        (doc) => `
          <div class="document-item">
            <strong>${escapeHtml(doc.title)}</strong>
            <div class="nav-meta">${escapeHtml(doc.path)}</div>
            ${doc.status ? `<div class="nav-meta">${escapeHtml(doc.status)}</div>` : ""}
          </div>
        `,
      )
      .join("") || '<div class="muted">No research notes yet.</div>';
  renderArchives(payload.archives || []);
  updateComposerState();
}

function renderArchives(archives) {
  if (!archives.length) {
    els.archiveList.innerHTML = '<div class="muted">No merged source archives.</div>';
    els.archiveViewer.innerHTML = '<div class="muted">This branch has no archived parent histories.</div>';
    return;
  }
  els.archiveList.innerHTML = archives
    .map(
      (archive) => `
        <button class="nav-item" data-archive="${escapeHtml(archive.id)}" type="button">
          <span class="nav-title">${escapeHtml(archive.title || archive.id)}</span>
          <span class="nav-meta">${escapeHtml(archive.id)} · ${archive.historyCount || 0} messages</span>
        </button>
      `,
    )
    .join("");
  els.archiveList.querySelectorAll("[data-archive]").forEach((button) => {
    button.addEventListener("click", () => loadArchive(button.dataset.archive));
  });
  els.archiveViewer.innerHTML = '<div class="muted">Select an archived source branch.</div>';
}

async function loadBranches() {
  const data = await api("/api/branches");
  state.branches = data.branches || [];
  state.views = data.views || [];
  if (!state.activeBranch && state.branches.length) {
    state.activeBranch = state.branches[0].id;
  }
  renderBranches();
  if (state.activeBranch) {
    await loadBranch(state.activeBranch);
  } else {
    els.activeTitle.textContent = "No branch selected";
    els.activeMeta.textContent = "Create a branch from the terminal with ctxgit branch <id>.";
    els.messageList.innerHTML = '<div class="muted">No messages yet.</div>';
  }
}

async function loadProject() {
  const project = await api("/api/project");
  renderProject(project);
  if (project.initialized) {
    await loadBranches();
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
  } else {
    clearWorkspace("This directory is not initialized for ctxgit yet.");
  }
}

async function openProject(path, { init }) {
  if (!path) return;
  els.openProjectButton.disabled = true;
  els.initProjectButton.disabled = true;
  els.browseProjectButton.disabled = true;
  setProjectStatus(init ? "Initializing project..." : "Opening project...");
  try {
    const project = await api(init ? "/api/project/init" : "/api/project/open", {
      method: "POST",
      body: JSON.stringify({ path, gitInit: true }),
    });
    renderProject(project);
    state.activeBranch = null;
    await loadBranches();
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
    setProjectStatus(init ? "Initialized and opened." : "Opened.", "ok");
  } catch (error) {
    if (error instanceof ApiError && error.payload?.project) {
      renderProject(error.payload.project);
    }
    clearWorkspace(error.message);
    setProjectStatus(`${init ? "Init" : "Open"} failed: ${error.message}`, "error");
  } finally {
    els.openProjectButton.disabled = false;
    els.initProjectButton.disabled = false;
    els.browseProjectButton.disabled = false;
  }
}

async function chooseProjectDirectory() {
  els.browseProjectButton.disabled = true;
  setProjectStatus("Opening directory picker...");
  try {
    const selected = await api("/api/project/choose-directory", {
      method: "POST",
      body: JSON.stringify({ path: els.projectPathInput.value.trim() || state.project?.path || "" }),
    });
    els.projectPathInput.value = selected.path;
    setProjectStatus("Directory selected.", "ok");
    return selected;
  } catch (error) {
    const canceled = error.message.toLowerCase().includes("canceled");
    setProjectStatus(canceled ? "Directory selection canceled." : `Browse failed: ${error.message}`, canceled ? "" : "error");
    return null;
  } finally {
    els.browseProjectButton.disabled = false;
  }
}

async function projectPathForAction() {
  const path = els.projectPathInput.value.trim();
  if (path) return path;
  const selected = await chooseProjectDirectory();
  return selected?.path || "";
}

async function loadBranch(branch) {
  state.activeBranch = branch;
  acknowledgeBranchJob(branch);
  selectTab("chat");
  renderBranches();
  const payload = await api(`/api/branch?id=${encodeURIComponent(branch)}`);
  if (state.activeBranch !== branch) return;
  renderBranch(payload);
  const git = await api("/api/git/status");
  if (state.activeBranch !== branch) return;
  renderGit(git);
  renderProvider(await api("/api/provider/status"));
  if (state.activeBranch !== branch) return;
  renderActiveBranchJob();
}

async function decideApproval(button) {
  if (!state.activeBranch) return;
  const approvalId = button.dataset.approval || "";
  const decision = button.dataset.decision || "";
  const path = button.dataset.path || "";
  if (!approvalId || !decision) return;
  if (
    decision === "approved" &&
    !window.confirm(`Allow this turn to write outside the project?\n\n${path}`)
  ) {
    return;
  }
  button.disabled = true;
  try {
    const payload = await api("/api/approval", {
      method: "POST",
      body: JSON.stringify({
        branch: state.activeBranch,
        approvalId,
        decision,
      }),
    });
    renderBranch(payload);
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
  } catch (error) {
    window.alert(`Approval failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function deleteHistoryMessage(button) {
  if (!state.activeBranch) return;
  const index = Number.parseInt(button.dataset.historyDelete || "", 10);
  if (!Number.isInteger(index)) return;
  if (!window.confirm("이 메시지를 history.jsonl에서 삭제할까?")) return;
  button.disabled = true;
  const branch = state.activeBranch;
  try {
    const payload = await api("/api/history/delete", {
      method: "POST",
      body: JSON.stringify({
        branch,
        index,
        createdAt: button.dataset.historyCreatedAt || "",
        role: button.dataset.historyRole || "",
      }),
    });
    if (state.activeBranch === branch) {
      renderBranch(payload);
      renderGit(await api("/api/git/status"));
      await refreshBranchNavigation();
    }
  } catch (error) {
    window.alert(`Delete failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function forkHistoryMessage(button) {
  if (!state.activeBranch) return;
  const index = Number.parseInt(button.dataset.historyFork || "", 10);
  if (!Number.isInteger(index)) return;
  const branch = state.activeBranch;
  const title = window.prompt(`Fork ${branch} through this message with title:`, `${branchTitle(branch)} fork ${index + 1}`);
  if (!title) return;
  const targetTitle = title.trim();
  if (!targetTitle) return;
  const targetId = uniqueBranchIdForTitle(targetTitle);
  button.disabled = true;
  try {
    const payload = await api("/api/history/fork", {
      method: "POST",
      body: JSON.stringify({
        branch,
        target: targetId,
        title: targetTitle,
        index,
        createdAt: button.dataset.historyCreatedAt || "",
        role: button.dataset.historyRole || "",
      }),
    });
    state.activeBranch = targetId;
    await loadBranches();
    renderBranch(payload);
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
  } catch (error) {
    window.alert(`Fork failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function cloneBranch(source, title) {
  const targetTitle = title.trim();
  if (!targetTitle) return;
  const target = uniqueBranchIdForTitle(targetTitle);
  try {
    const payload = await api("/api/branch/clone", {
      method: "POST",
      body: JSON.stringify({ source, target, title: targetTitle }),
    });
    state.activeBranch = target;
    await loadBranches();
    renderBranch(payload);
  } catch (error) {
    window.alert(`Clone failed: ${error.message}`);
  }
}

async function renameBranch(branch, title) {
  if (!title) return;
  try {
    const payload = await api("/api/branch/rename", {
      method: "POST",
      body: JSON.stringify({ branch, title }),
    });
    state.activeBranch = branch;
    await loadBranches();
    renderBranch(payload);
  } catch (error) {
    window.alert(`Rename failed: ${error.message}`);
  }
}

async function removeBranch(branch) {
  try {
    await api("/api/branch/remove", {
      method: "POST",
      body: JSON.stringify({ branch }),
    });
    if (state.activeBranch === branch) {
      state.activeBranch = null;
      state.payload = null;
    }
    await loadBranches();
  } catch (error) {
    window.alert(`Remove failed: ${error.message}`);
  }
}

async function loadArchive(archiveId) {
  if (!state.activeBranch) return;
  const payload = await api(
    `/api/archive?branch=${encodeURIComponent(state.activeBranch)}&id=${encodeURIComponent(archiveId)}`,
  );
  els.archiveList.querySelectorAll("[data-archive]").forEach((button) => {
    button.classList.toggle("active", button.dataset.archive === archiveId);
  });
  const title = payload.meta?.title || archiveId;
  const messages =
    payload.history
      .map(
        (message) => `
          <article class="message">
            <div class="message-header">
              <span class="message-role">${escapeHtml(message.role)}</span>
              <span>${escapeHtml(message.createdAt)}</span>
            </div>
            <div class="message-text">${renderMessageText(message.text)}</div>
          </article>
        `,
      )
      .join("") || '<div class="muted">No archived messages.</div>';
  els.archiveViewer.innerHTML = `
    <div class="archive-heading">
      <h2>${escapeHtml(title)}</h2>
      <div class="active-meta">${escapeHtml(payload.paths?.history || "")}</div>
    </div>
    <div class="message-list">${messages}</div>
  `;
}

async function loadView(view) {
  const payload = await api(`/api/view?id=${encodeURIComponent(view)}`);
  state.activeBranch = null;
  renderBranches();
  els.activeTitle.textContent = payload.id;
  els.activeMeta.textContent = payload.path;
  els.reportView.innerHTML = renderMarkdown(payload.text);
  selectTab("report");
}

function selectTab(tab) {
  const button = document.querySelector(`[data-tab="${tab}"]`);
  const panel = document.querySelector(`#${tab}Tab`);
  if (!button || !panel) return;
  document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  panel.classList.add("active");
  if (tab === "chat") scrollChatToBottom();
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => selectTab(button.dataset.tab));
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".branch-row")) {
    closeBranchMenus();
  }
  if (!event.target.closest(".message-options")) {
    closeMessageMenus();
  }
});

els.projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const path = await projectPathForAction();
  await openProject(path, { init: false });
});

els.initProjectButton.addEventListener("click", async () => {
  const path = await projectPathForAction();
  await openProject(path, { init: true });
});

els.browseProjectButton.addEventListener("click", async () => {
  const selected = await chooseProjectDirectory();
  if (!selected) return;
  if (selected.project?.initialized) {
    await openProject(selected.path, { init: false });
  } else {
    setProjectStatus("Directory selected. Use Init/Open to initialize it.", "");
  }
});

els.mergeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const branches = els.mergeSourcesInput.value
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  const name = els.mergeNameInput.value.trim();
  if (branches.length < 2 || !name) {
    els.mergeStatus.textContent = "Use two sources and a new branch id.";
    els.mergeStatus.className = "settings-status error";
    return;
  }
  els.mergeButton.disabled = true;
  els.mergeStatus.textContent = "Merging...";
  els.mergeStatus.className = "settings-status";
  try {
    const payload = await api("/api/merge", {
      method: "POST",
      body: JSON.stringify({ branches, name }),
    });
    state.activeBranch = name;
    await loadBranches();
    renderBranch(payload);
    els.mergeSourcesInput.value = "";
    els.mergeNameInput.value = "";
    els.mergeStatus.textContent = "Merged.";
    els.mergeStatus.classList.add("ok");
    selectTab("archives");
  } catch (error) {
    els.mergeStatus.textContent = `Merge failed: ${error.message}`;
    els.mergeStatus.classList.add("error");
  } finally {
    els.mergeButton.disabled = false;
  }
});

async function sendComposerMessage({ mode }) {
  if (!state.activeBranch) return;
  const branch = state.activeBranch;
  const text = els.messageInput.value.trim();
  if (!text) return;
  const isChat = mode === "chat";
  const isResearch = mode === "research";
  const isInfoChat = mode === "info-chat";
  if (activeBranchRunningJob(branch) || state.startingBranches[branch]) {
    window.alert("이 브랜치에는 이미 실행 중인 작업이 있습니다. 다른 브랜치로 이동하면 별도 작업을 시작할 수 있습니다.");
    return;
  }
  const requestedMode = isResearch ? "research" : isInfoChat ? "info-chat" : "chat";
  state.startingBranches[branch] = requestedMode;
  markBranchActivity(branch);
  updateComposerState();
  renderBranches();
  try {
    if (isResearch) {
      await startTrackedJob(
        "/api/research/start",
        { branch, text, provider: "hybrid" },
        { branch, mode: "research", title: "리서치 시작 중" },
      );
      els.messageInput.value = "";
      return;
    }
    if (isChat) {
      await startTrackedJob(
        "/api/chat/start",
        { branch, text, provider: "codex" },
        { branch, mode: "chat", title: "채팅 턴 시작 중" },
      );
      els.messageInput.value = "";
      return;
    }
    if (isInfoChat) {
      await startTrackedJob(
        "/api/info-chat/start",
        { branch, text, provider: "codex" },
        { branch, mode: "info-chat", title: "정보 챗 시작 중" },
      );
      els.messageInput.value = "";
      return;
    }
  } catch (error) {
    const isTimeout = error instanceof ApiError && error.payload?.error === "timeout";
    const isMissingJob = error instanceof ApiError && error.payload?.error === "job_not_found";
    const prefix = isTimeout ? "시간 초과" : isMissingJob ? "중단됨" : isResearch ? "리서치 실패" : "채팅 실패";
    if (state.activeBranch === branch) {
      els.messageList.insertAdjacentHTML(
        "beforebegin",
        `<div class="error-banner">${prefix}: ${escapeHtml(error.message)}</div>`,
      );
      hideProgress();
    } else {
      window.alert(`${prefix} on ${branch}: ${error.message}`);
    }
  } finally {
    delete state.startingBranches[branch];
    updateComposerState();
  }
}

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendComposerMessage({ mode: "chat" });
});

els.messageInput.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  await sendComposerMessage({ mode: "info-chat" });
});

els.copyEventLogButton.addEventListener("click", copyEventLog);

els.providerSettings.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.providerSettingsStatus.textContent = "";
  els.providerSettingsStatus.className = "settings-status";
  els.saveProviderButton.disabled = true;
  const previousTitle = els.saveProviderButton.textContent;
  els.saveProviderButton.textContent = "Saving";
  try {
    const timeoutSeconds = Number.parseInt(els.timeoutSecondsInput.value, 10);
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds <= 0) {
      throw new Error("Timeout must be a positive integer.");
    }
    renderProvider(
      await api("/api/provider/config", {
        method: "POST",
        body: JSON.stringify({
          timeoutSeconds,
          webSearch: els.webSearchInput.checked,
          sandbox: els.sandboxInput.value,
        }),
      }),
    );
    els.providerSettingsStatus.textContent = "Saved";
    els.providerSettingsStatus.classList.add("ok");
  } catch (error) {
    els.providerSettingsStatus.textContent = `Settings failed: ${error.message}`;
    els.providerSettingsStatus.classList.add("error");
  } finally {
    els.saveProviderButton.disabled = false;
    els.saveProviderButton.textContent = previousTitle;
  }
});

els.historyChatButton.addEventListener("click", async () => {
  await sendComposerMessage({ mode: "info-chat" });
});

els.researchButton.addEventListener("click", async () => {
  await sendComposerMessage({ mode: "research" });
});

els.refreshButton.addEventListener("click", async () => {
  await loadProject();
});

loadProject()
  .catch((error) => {
    els.activeTitle.textContent = "Could not load ctxgit project";
    els.activeMeta.textContent = error.message;
  });
