const state = {
  project: null,
  activeBranch: null,
  activeGlobalized: null,
  branches: [],
  archived: [],
  views: [],
  globalized: [],
  graph: null,
  payload: null,
  provider: null,
  serverProjects: [],
  worker: null,
  auth: null,
  authMode: "login",
  fileBrowser: { path: "", parent: "", entries: [] },
  currentJob: null,
  jobs: {},
  branchJobs: {},
  branchActivityAt: {},
  acknowledgedBranchJobs: {},
  startingBranches: {},
};

const UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024;

const els = {
  authGate: document.querySelector("#authGate"),
  authModeLabel: document.querySelector("#authModeLabel"),
  loginForm: document.querySelector("#loginForm"),
  loginUsername: document.querySelector("#loginUsername"),
  loginPassword: document.querySelector("#loginPassword"),
  loginButton: document.querySelector("#loginButton"),
  registerForm: document.querySelector("#registerForm"),
  registerUsername: document.querySelector("#registerUsername"),
  registerPassword: document.querySelector("#registerPassword"),
  registerButton: document.querySelector("#registerButton"),
  authSwitchButton: document.querySelector("#authSwitchButton"),
  authStatus: document.querySelector("#authStatus"),
  authSummary: document.querySelector("#authSummary"),
  logoutButton: document.querySelector("#logoutButton"),
  projectSummary: document.querySelector("#projectSummary"),
  projectForm: document.querySelector("#projectForm"),
  projectPathInput: document.querySelector("#projectPathInput"),
  openProjectButton: document.querySelector("#openProjectButton"),
  initProjectButton: document.querySelector("#initProjectButton"),
  browseProjectButton: document.querySelector("#browseProjectButton"),
  projectStatus: document.querySelector("#projectStatus"),
  serverProjectPanel: document.querySelector("#serverProjectPanel"),
  serverProjectSelect: document.querySelector("#serverProjectSelect"),
  openServerProjectButton: document.querySelector("#openServerProjectButton"),
  serverProjectStatus: document.querySelector("#serverProjectStatus"),
  branchList: document.querySelector("#branchList"),
  branchGraphButton: document.querySelector("#branchGraphButton"),
  viewList: document.querySelector("#viewList"),
  globalizedList: document.querySelector("#globalizedList"),
  gitSummary: document.querySelector("#gitSummary"),
  providerSummary: document.querySelector("#providerSummary"),
  workerSummary: document.querySelector("#workerSummary"),
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
  chatError: document.querySelector("#chatError"),
  eventPanel: document.querySelector("#eventPanel"),
  eventStatus: document.querySelector("#eventStatus"),
  copyEventLogButton: document.querySelector("#copyEventLogButton"),
  eventCopyStatus: document.querySelector("#eventCopyStatus"),
  eventMeta: document.querySelector("#eventMeta"),
  eventList: document.querySelector("#eventList"),
  reportView: document.querySelector("#reportView"),
  filePathForm: document.querySelector("#filePathForm"),
  fileUpButton: document.querySelector("#fileUpButton"),
  fileRefreshButton: document.querySelector("#fileRefreshButton"),
  filePathInput: document.querySelector("#filePathInput"),
  fileGoButton: document.querySelector("#fileGoButton"),
  newFolderButton: document.querySelector("#newFolderButton"),
  fileUploadInput: document.querySelector("#fileUploadInput"),
  folderUploadInput: document.querySelector("#folderUploadInput"),
  fileStatus: document.querySelector("#fileStatus"),
  fileList: document.querySelector("#fileList"),
  filePreview: document.querySelector("#filePreview"),
  archiveList: document.querySelector("#archiveList"),
  archiveViewer: document.querySelector("#archiveViewer"),
  graphRefreshButton: document.querySelector("#graphRefreshButton"),
  branchGraphStatus: document.querySelector("#branchGraphStatus"),
  branchGraph: document.querySelector("#branchGraph"),
  trackedFiles: document.querySelector("#trackedFiles"),
  historyLog: document.querySelector("#historyLog"),
  currentDiff: document.querySelector("#currentDiff"),
  internalGitLog: document.querySelector("#internalGitLog"),
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
    if (response.status === 401 && payload?.error === "auth_required") {
      renderAuth(payload.auth || { authenticated: false, registrationOpen: false });
    }
    throw new ApiError(payload.message || payload.error || `Request failed: ${response.status}`, response.status, payload);
  }
  return payload;
}

function setAuthStatus(message, kind = "") {
  els.authStatus.textContent = message;
  els.authStatus.className = `settings-status ${kind}`.trim();
}

function showAuthMode(mode) {
  state.authMode = mode === "register" ? "register" : "login";
  const registrationOpen = state.auth?.registrationOpen === true;
  const userCount = Number(state.auth?.userCount || 0);
  const showRegister = state.authMode === "register" && registrationOpen;
  els.loginForm.hidden = showRegister;
  els.registerForm.hidden = !showRegister;
  els.authModeLabel.textContent = showRegister
    ? userCount ? "Create another account" : "Create the first admin account"
    : "Login required";
  if (registrationOpen) {
    els.authSwitchButton.hidden = false;
    els.authSwitchButton.textContent = showRegister ? "Use existing account" : "Create account";
  } else {
    els.authSwitchButton.hidden = true;
    els.authSwitchButton.textContent = "";
  }
}

function renderAuth(auth) {
  state.auth = auth || { authenticated: false, registrationOpen: false };
  if (state.auth.enabled === false) {
    els.authGate.hidden = true;
    els.logoutButton.hidden = true;
    els.authSummary.innerHTML = '<div class="muted">Auth disabled for local access.</div>';
    setAuthStatus("");
    return;
  }
  const authenticated = state.auth.authenticated === true;
  els.authGate.hidden = authenticated;
  els.logoutButton.hidden = !authenticated;
  if (authenticated) {
    const user = state.auth.user || {};
    els.authSummary.innerHTML = `
      <div>Signed in: <strong>${escapeHtml(user.username || "")}</strong></div>
      <div class="muted">${escapeHtml(user.role || "user")} - ${escapeHtml(user.provider || "local")}</div>
    `;
    setAuthStatus("");
    return;
  }
  els.authSummary.innerHTML = '<div class="muted">Not signed in.</div>';
  const userCount = Number(state.auth.userCount || 0);
  showAuthMode(state.auth.registrationOpen && userCount === 0 ? "register" : state.authMode);
}

async function loadAuthStatus() {
  const auth = await api("/api/auth/status");
  renderAuth(auth);
  return auth;
}

async function submitLogin(event) {
  event.preventDefault();
  const username = els.loginUsername.value.trim();
  const password = els.loginPassword.value;
  if (!username || !password) {
    setAuthStatus("Username and password are required.", "error");
    return;
  }
  els.loginButton.disabled = true;
  setAuthStatus("Logging in...");
  try {
    const auth = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    els.loginPassword.value = "";
    renderAuth(auth);
    await loadProject();
  } catch (error) {
    setAuthStatus(`Login failed: ${error.message}`, "error");
  } finally {
    els.loginButton.disabled = false;
  }
}

async function submitRegister(event) {
  event.preventDefault();
  const username = els.registerUsername.value.trim();
  const password = els.registerPassword.value;
  if (!username || !password) {
    setAuthStatus("Username and password are required.", "error");
    return;
  }
  els.registerButton.disabled = true;
  setAuthStatus("Creating account...");
  try {
    const auth = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    els.registerPassword.value = "";
    renderAuth(auth);
    await loadProject();
  } catch (error) {
    setAuthStatus(`Signup failed: ${error.message}`, "error");
  } finally {
    els.registerButton.disabled = false;
  }
}

async function logout() {
  els.logoutButton.disabled = true;
  try {
    const auth = await api("/api/auth/logout", { method: "POST", body: JSON.stringify({}) });
    renderAuth(auth);
    clearWorkspace("Login required.");
  } catch (error) {
    window.alert(`Logout failed: ${error.message}`);
  } finally {
    els.logoutButton.disabled = false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isNetworkFetchError(error) {
  const message = String(error?.message || "");
  return error instanceof TypeError || /Failed to fetch|NetworkError|Load failed/i.test(message);
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
  return String(text || "")
    .split(/(`[^`\n]+`)/g)
    .map((part) => {
      if (part.startsWith("`") && part.endsWith("`")) {
        return renderCodeSpan(part.slice(1, -1));
      }
      return renderMarkdownInlineNoCode(part);
    })
    .join("");
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

function isProjectFilePath(path) {
  const value = String(path || "");
  if (!/^(?:contexts|\.ctxgit)\/[^\s<>"'`)]*\.(?:md|txt|json|jsonl|pdf|csv|tsv|html?)$/.test(value)) {
    return false;
  }
  if (/[\\]/.test(value)) return false;
  return !value.split("/").some((part) => part === "" || part === "." || part === ".." || part === "~");
}

function renderProjectFileLink(path, labelHtml = escapeHtml(path)) {
  if (!state.project?.path || !isProjectFilePath(path)) return labelHtml;
  return `<a class="file-link" href="${escapeHtml(obsidianFileUrl(path))}" title="Open in Obsidian">${labelHtml}</a>`;
}

function renderCodeSpan(text) {
  const value = String(text || "");
  if (isProjectFilePath(value)) {
    return renderProjectFileLink(value, `<code>${escapeHtml(value)}</code>`);
  }
  return `<code>${escapeHtml(value)}</code>`;
}

function renderProjectFileLinks(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(
    /(^|[\s(`])((?:contexts|\.ctxgit)\/[^\s<>"'`)]*\.(?:md|txt|json|jsonl|pdf|csv|tsv|html?))/g,
    (_match, prefix, path) =>
      `${prefix}${renderProjectFileLink(path, path)}`,
  );
}

function safeMarkdownHref(href) {
  const value = String(href || "").trim();
  if (/^(https?:|mailto:)/i.test(value)) return escapeHtml(value);
  return "";
}

function linkTargetAttrs() {
  return 'target="_blank" rel="noopener noreferrer"';
}

function renderMarkdownInlineNoCode(text) {
  const pattern = /\[([^\]\n]+)\]\(([^)\s]+)\)|(^|[\s(])((?:https?:\/\/|mailto:)[^\s<>"'`]+[^\s<>"'`.,;:!?)]?)/g;
  let html = "";
  let lastIndex = 0;
  for (const match of text.matchAll(pattern)) {
    html += escapeHtml(text.slice(lastIndex, match.index));
    if (match[1] !== undefined) {
      const href = safeMarkdownHref(match[2]);
      html += href
        ? `<a href="${href}" ${linkTargetAttrs()}>${escapeHtml(match[1])}</a>`
        : escapeHtml(match[0]);
    } else {
      const prefix = match[3] || "";
      const url = match[4] || "";
      const href = safeMarkdownHref(url);
      html += `${escapeHtml(prefix)}${href ? `<a href="${href}" ${linkTargetAttrs()}>${escapeHtml(url)}</a>` : escapeHtml(url)}`;
    }
    lastIndex = (match.index || 0) + match[0].length;
  }
  html += escapeHtml(text.slice(lastIndex));
  return html;
}

function renderChatEmphasis(text) {
  return escapeHtml(text)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
}

function renderChatInlineNoCode(text) {
  const pattern =
    /\[([^\]\n]+)\]\(([^)\s]+)\)|(^|[\s(`])((?:contexts|\.ctxgit)\/[^\s<>"'`)]*\.(?:md|txt|json|jsonl|pdf|csv|tsv|html?))|(^|[\s(])((?:https?:\/\/|mailto:)[^\s<>"'`]+[^\s<>"'`.,;:!?)]?)/g;
  let html = "";
  let lastIndex = 0;
  for (const match of text.matchAll(pattern)) {
    html += renderChatEmphasis(text.slice(lastIndex, match.index));
    if (match[1] !== undefined) {
      const href = safeMarkdownHref(match[2]);
      html += href
        ? `<a href="${href}" ${linkTargetAttrs()}>${renderChatEmphasis(match[1])}</a>`
        : renderChatEmphasis(match[0]);
    } else if (match[4] !== undefined) {
      const prefix = match[3] || "";
      const path = match[4] || "";
      html += `${renderChatEmphasis(prefix)}${renderProjectFileLink(path)}`;
    } else {
      const prefix = match[5] || "";
      const url = match[6] || "";
      const href = safeMarkdownHref(url);
      html += `${renderChatEmphasis(prefix)}${href ? `<a href="${href}" ${linkTargetAttrs()}>${escapeHtml(url)}</a>` : renderChatEmphasis(url)}`;
    }
    lastIndex = (match.index || 0) + match[0].length;
  }
  html += renderChatEmphasis(text.slice(lastIndex));
  return html;
}

function renderChatInline(text) {
  return String(text || "")
    .split(/(`[^`\n]+`)/g)
    .map((part) => {
      if (part.startsWith("`") && part.endsWith("`")) {
        return renderCodeSpan(part.slice(1, -1));
      }
      return renderChatInlineNoCode(part);
    })
    .join("");
}

function renderMessageText(text) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let listType = "";
  let inFence = false;
  let fenceLines = [];

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = "";
  };
  const openList = (type, start = null) => {
    if (listType === type) return;
    closeList();
    if (type === "ol") {
      const startValue = Number.parseInt(start, 10);
      const startAttr = Number.isFinite(startValue) && startValue > 1 ? ` start="${startValue}"` : "";
      html.push(`<ol${startAttr}>`);
    } else {
      html.push(`<${type}>`);
    }
    listType = type;
  };
  const closeFence = () => {
    html.push(`<pre><code>${escapeHtml(fenceLines.join("\n"))}</code></pre>`);
    fenceLines = [];
    inFence = false;
  };
  const appendListContinuation = (value) => {
    if (!listType || !html.length) return false;
    const last = html[html.length - 1];
    if (!last.endsWith("</li>")) return false;
    html[html.length - 1] = `${last.slice(0, -5)}<br>${renderChatInline(value)}</li>`;
    return true;
  };

  for (const line of lines) {
    if (/^```/.test(line.trim())) {
      if (inFence) {
        closeFence();
      } else {
        closeList();
        inFence = true;
        fenceLines = [];
      }
      continue;
    }
    if (inFence) {
      fenceLines.push(line);
      continue;
    }

    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${renderChatInline(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.*)$/);
    if (unordered) {
      openList("ul");
      html.push(`<li>${renderChatInline(unordered[1])}</li>`);
      continue;
    }

    const ordered = line.match(/^\s*(\d+)\.\s+(.*)$/);
    if (ordered) {
      openList("ol", ordered[1]);
      html.push(`<li>${renderChatInline(ordered[2])}</li>`);
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      html.push(`<blockquote>${renderChatInline(quote[1])}</blockquote>`);
      continue;
    }

    if (appendListContinuation(line)) continue;
    closeList();
    html.push(`<p>${renderChatInline(line)}</p>`);
  }
  if (inFence) closeFence();
  closeList();
  return html.join("\n");
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").split("\n");
  const html = [];
  let listType = "";
  let tableRows = [];

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = "";
  };
  const openList = (type, start = null) => {
    if (listType === type) return;
    closeList();
    if (type === "ol") {
      const startValue = Number.parseInt(start, 10);
      const startAttr = Number.isFinite(startValue) && startValue > 1 ? ` start="${startValue}"` : "";
      html.push(`<ol${startAttr}>`);
    } else {
      html.push(`<${type}>`);
    }
    listType = type;
  };
  const appendListContinuation = (value) => {
    if (!listType || !html.length) return false;
    const last = html[html.length - 1];
    if (!last.endsWith("</li>")) return false;
    html[html.length - 1] = `${last.slice(0, -5)}<br>${renderInline(value)}</li>`;
    return true;
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
      openList("ul");
      html.push(`<li>${renderInline(bullet[1])}</li>`);
      continue;
    }
    const ordered = line.match(/^\s*(\d+)\.\s+(.*)$/);
    if (ordered) {
      openList("ol", ordered[1]);
      html.push(`<li>${renderInline(ordered[2])}</li>`);
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    if (appendListContinuation(line)) continue;
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
  state.activeGlobalized = null;
  state.branches = [];
  state.archived = [];
  state.views = [];
  state.globalized = [];
  state.graph = null;
  state.payload = null;
  state.fileBrowser = { path: "", parent: "", entries: [] };
  renderBranches();
  hideChatError();
  els.activeTitle.textContent = "No project selected";
  els.activeMeta.textContent = message;
  replaceMessageListHtml(`<div class="muted">${escapeHtml(message)}</div>`);
  els.reportView.innerHTML = "";
  els.filePathInput.value = "";
  els.fileList.innerHTML = "";
  els.filePreview.textContent = "";
  els.fileStatus.textContent = "";
  els.archiveList.innerHTML = "";
  els.archiveViewer.innerHTML = '<div class="muted">No archived source branch selected.</div>';
  els.branchGraphStatus.textContent = "";
  els.branchGraph.innerHTML = "";
  els.trackedFiles.innerHTML = "";
  els.historyLog.textContent = "";
  els.currentDiff.textContent = "";
  els.internalGitLog.textContent = "";
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

function setServerProjectStatus(message, kind = "") {
  els.serverProjectStatus.textContent = message;
  els.serverProjectStatus.className = `settings-status ${kind}`.trim();
}

function renderServerProjects(payload) {
  const projects = payload?.projects || [];
  state.serverProjects = projects;
  const enabled = payload?.enabled === true || projects.length > 1;
  els.serverProjectPanel.hidden = !enabled;
  if (!enabled) return;
  els.serverProjectSelect.innerHTML = projects
    .map((project) => {
      const label = `${project.name || project.id}${project.initialized ? "" : " (not initialized)"}`;
      return `<option value="${escapeHtml(project.id)}" ${project.active ? "selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("");
  setServerProjectStatus(
    payload.projectsRoot ? `Server root: ${payload.projectsRoot}` : "Current project only",
    "",
  );
}

function renderWorker(status) {
  state.worker = status;
  if (!status || status.enabled === false) {
    els.workerSummary.innerHTML = '<div class="muted">Worker API unavailable.</div>';
    return;
  }
  const mode = status.preferWorker ? "local worker" : "server process";
  els.workerSummary.innerHTML = `
    <div>Codex runs on: <strong>${escapeHtml(mode)}</strong></div>
    <div class="muted">Active: ${status.activeWorkers || 0} · Queued: ${status.queued || 0} · Claimed: ${status.claimed || 0}</div>
  `;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let amount = bytes;
  let unitIndex = 0;
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024;
    unitIndex += 1;
  }
  return `${amount >= 10 || unitIndex === 0 ? Math.round(amount) : amount.toFixed(1)} ${units[unitIndex]}`;
}

function setFileStatus(message, kind = "") {
  els.fileStatus.textContent = message;
  els.fileStatus.className = `settings-status ${kind}`.trim();
}

function renderProjectFiles(payload) {
  state.fileBrowser = {
    path: payload?.path || "",
    parent: payload?.parent || "",
    entries: payload?.entries || [],
  };
  els.filePathInput.value = state.fileBrowser.path;
  els.fileUpButton.disabled = !state.fileBrowser.path;
  els.fileList.innerHTML =
    state.fileBrowser.entries
      .map((entry) => {
        const kind = entry.isDirectory ? "folder" : "file";
        const meta = entry.isDirectory ? "folder" : `${formatBytes(entry.size)} · ${entry.modifiedAt || ""}`;
        return `
          <button class="file-row" data-file-path="${escapeHtml(entry.path)}" data-file-kind="${kind}" type="button" title="${escapeHtml(entry.path)}">
            <span class="file-icon">${entry.isDirectory ? "▸" : "·"}</span>
            <span class="file-name">${escapeHtml(entry.name)}</span>
            <span class="file-meta">${escapeHtml(meta)}</span>
          </button>
        `;
      })
      .join("") || '<div class="muted">No files</div>';
  els.fileList.querySelectorAll("[data-file-path]").forEach((button) => {
    button.addEventListener("click", () => {
      const path = button.dataset.filePath || "";
      if (button.dataset.fileKind === "folder") {
        loadProjectFiles(path);
      } else {
        previewProjectFile(path);
      }
    });
  });
}

async function loadProjectFiles(path = state.fileBrowser.path || "") {
  if (!state.project?.initialized) return;
  setFileStatus("Loading...");
  try {
    const payload = await api(`/api/project/files?path=${encodeURIComponent(path)}`);
    renderProjectFiles(payload);
    setFileStatus(payload.path || "Project root", "ok");
  } catch (error) {
    setFileStatus(`Load failed: ${error.message}`, "error");
  }
}

async function previewProjectFile(path) {
  setFileStatus("Opening...");
  try {
    const payload = await api(`/api/project/file/text?path=${encodeURIComponent(path)}`);
    if (payload.binary) {
      els.filePreview.textContent = `${payload.path}\n\n${formatBytes(payload.size)} binary file`;
    } else {
      els.filePreview.textContent = `${payload.path}${payload.truncated ? " (truncated)" : ""}\n\n${payload.text || ""}`;
    }
    setFileStatus(payload.path, "ok");
  } catch (error) {
    setFileStatus(`Open failed: ${error.message}`, "error");
  }
}

function readBlobAsBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const result = String(reader.result || "");
      const encoded = result.includes(",") ? result.split(",", 2)[1] : "";
      resolve(encoded);
    });
    reader.addEventListener("error", () => reject(reader.error || new Error("file read failed")));
    reader.readAsDataURL(blob);
  });
}

async function uploadFileInChunks(file, { directory, overwrite, index, total }) {
  const path = file.webkitRelativePath || file.name;
  const chunkCount = Math.max(1, Math.ceil(file.size / UPLOAD_CHUNK_BYTES));
  let lastPayload = null;
  if (file.size === 0) {
    setFileStatus(`Uploading ${index}/${total}: ${path}`);
    lastPayload = await api("/api/project/file/upload-chunk", {
      method: "POST",
      body: JSON.stringify({
        directory,
        path,
        contentBase64: "",
        offset: 0,
        totalSize: 0,
        overwrite,
        lastChunk: true,
      }),
    });
    return lastPayload;
  }
  for (let offset = 0, chunkIndex = 1; offset < file.size; offset += UPLOAD_CHUNK_BYTES, chunkIndex += 1) {
    const blob = file.slice(offset, Math.min(file.size, offset + UPLOAD_CHUNK_BYTES));
    setFileStatus(`Uploading ${index}/${total}: ${path} (${chunkIndex}/${chunkCount}, ${formatBytes(offset)} of ${formatBytes(file.size)})`);
    const contentBase64 = await readBlobAsBase64(blob);
    lastPayload = await api("/api/project/file/upload-chunk", {
      method: "POST",
      body: JSON.stringify({
        directory,
        path,
        contentBase64,
        offset,
        totalSize: file.size,
        overwrite: overwrite && offset === 0,
        lastChunk: offset + blob.size >= file.size,
      }),
    });
  }
  return lastPayload;
}

async function finishChunkedUpload(directory, uploadedPaths) {
  const payload = await api("/api/project/file/upload-finish", {
    method: "POST",
    body: JSON.stringify({ directory, files: uploadedPaths }),
  });
  renderProjectFiles(payload.files);
  renderGit(await api("/api/git/status"));
  return payload;
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const directory = state.fileBrowser.path || "";
  const uploadedPaths = [];
  let overwriteAll = false;
  try {
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      try {
        const result = await uploadFileInChunks(file, {
          directory,
          overwrite: overwriteAll,
          index: index + 1,
          total: files.length,
        });
        const uploadedPath = result?.entry?.path || file.webkitRelativePath || file.name;
        uploadedPaths.push(uploadedPath);
      } catch (error) {
        if (!(error instanceof ApiError) || error.payload?.error !== "file_exists") throw error;
        if (!window.confirm(`${error.message}\n\nOverwrite existing file(s) for the rest of this upload?`)) {
          if (uploadedPaths.length) {
            await finishChunkedUpload(directory, uploadedPaths);
            setFileStatus(`Upload canceled after ${uploadedPaths.length} file(s).`, "ok");
          } else {
            setFileStatus("Upload canceled.");
          }
          return;
        }
        overwriteAll = true;
        const result = await uploadFileInChunks(file, {
          directory,
          overwrite: true,
          index: index + 1,
          total: files.length,
        });
        const uploadedPath = result?.entry?.path || file.webkitRelativePath || file.name;
        uploadedPaths.push(uploadedPath);
      }
    }
    const payload = await finishChunkedUpload(directory, uploadedPaths);
    setFileStatus(`Uploaded ${payload.uploaded?.length || uploadedPaths.length} file(s).`, "ok");
  } catch (error) {
    if (uploadedPaths.length) {
      try {
        await finishChunkedUpload(directory, uploadedPaths);
      } catch {
        // Keep the original upload error visible.
      }
    }
    setFileStatus(`Upload failed: ${error.message}`, "error");
  } finally {
    els.fileUploadInput.value = "";
    els.folderUploadInput.value = "";
  }
}

async function createFolderFromPrompt() {
  const base = state.fileBrowser.path ? `${state.fileBrowser.path}/` : "";
  const name = window.prompt("New folder path:", base);
  if (!name) return;
  setFileStatus("Creating folder...");
  try {
    const payload = await api("/api/project/directory/create", {
      method: "POST",
      body: JSON.stringify({ path: name.trim() }),
    });
    renderProjectFiles(payload.files);
    setFileStatus(`Created ${payload.entry?.path || name}.`, "ok");
    renderGit(await api("/api/git/status"));
  } catch (error) {
    setFileStatus(`Create failed: ${error.message}`, "error");
  }
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
          <button class="nav-item branch-main ${branch.id === state.activeBranch ? "active" : ""}" data-branch="${escapeHtml(branch.id)}" type="button" title="${escapeHtml(`${branch.title} (${branch.id})`)}">
            <span class="nav-title" title="${escapeHtml(branch.title)}">${escapeHtml(branch.title)}</span>
            <span class="nav-meta" title="${escapeHtml(`${branch.id} · ${branch.historyCount} messages${jobLabel}`)}">${escapeHtml(branch.id)} · ${branch.historyCount} messages${escapeHtml(jobLabel)}</span>
          </button>
          <button class="branch-options-button" data-branch-options="${escapeHtml(branch.id)}" type="button" aria-label="Branch options">...</button>
          <div class="branch-options-menu">
            <button data-branch-rename="${escapeHtml(branch.id)}" data-branch-title="${escapeHtml(branch.title)}" type="button">Rename branch</button>
            <button data-branch-clone="${escapeHtml(branch.id)}" type="button">Clone branch</button>
            <button data-branch-archive="${escapeHtml(branch.id)}" type="button">Archive branch</button>
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
  els.branchList.querySelectorAll("[data-branch-archive]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      closeBranchMenus();
      await archiveBranch(button.dataset.branchArchive);
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
          <button class="nav-item" data-view="${escapeHtml(view.id)}" type="button" title="${escapeHtml(`${view.id} (${view.path})`)}">
            <span class="nav-title" title="${escapeHtml(view.id)}">${escapeHtml(view.id)}</span>
            <span class="nav-meta" title="${escapeHtml(view.path)}">${escapeHtml(view.path)}</span>
          </button>
        `,
      )
      .join("") || '<div class="muted">No views yet</div>';
  els.viewList.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => loadView(button.dataset.view));
  });
  renderGlobalizedList();
}

function renderGlobalizedList() {
  const archivedBranchMarkup = (state.archived || [])
    .map(
      (branch) => `
        <button class="nav-item ${branch.id === state.activeBranch ? "active" : ""}" data-archived-branch="${escapeHtml(branch.id)}" type="button" title="${escapeHtml(`${branch.title || branch.id} (${branch.id})`)}">
          <span class="nav-title" title="${escapeHtml(branch.title || branch.id)}">${escapeHtml(branch.title || branch.id)}</span>
          <span class="nav-meta" title="${escapeHtml(`${branch.id} · ${branch.historyCount || 0} messages · archived branch`)}">${escapeHtml(branch.id)} · ${branch.historyCount || 0} messages · branch</span>
        </button>
      `,
    )
    .join("");
  const rangeArchiveMarkup = (state.globalized || [])
    .map(
      (archive) => `
        <button class="nav-item ${archive.id === state.activeGlobalized ? "active" : ""}" data-globalized="${escapeHtml(archive.id)}" type="button" title="${escapeHtml(`${archive.title || archive.id} (${archive.sourceBranch || "archived"})`)}">
          <span class="nav-title" title="${escapeHtml(archive.title || archive.id)}">${escapeHtml(archive.title || archive.id)}</span>
          <span class="nav-meta" title="${escapeHtml(`${archive.sourceBranch || ""} · ${archive.rangeStart || "?"}-${archive.rangeEnd || "?"} · ${archive.messageCount || 0} messages`)}">${escapeHtml(archive.sourceBranch || "")} · ${archive.rangeStart || "?"}-${archive.rangeEnd || "?"} · ${archive.messageCount || 0} messages</span>
        </button>
      `,
    )
    .join("");
  els.globalizedList.innerHTML =
    (archivedBranchMarkup || rangeArchiveMarkup)
      ? `${archivedBranchMarkup}${rangeArchiveMarkup}`
      : '<div class="muted">No archived chats yet</div>';
  els.globalizedList.querySelectorAll("[data-archived-branch]").forEach((button) => {
    button.addEventListener("click", () => loadBranch(button.dataset.archivedBranch));
  });
  els.globalizedList.querySelectorAll("[data-globalized]").forEach((button) => {
    button.addEventListener("click", () => loadGlobalizedArchive(button.dataset.globalized));
  });
}

function graphLabel(value, max = 24) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, Math.max(0, max - 1))}…` : text;
}

function buildGraphLayout(payload) {
  const nodeWidth = 190;
  const nodeHeight = 64;
  const columnGap = 112;
  const rowGap = 92;
  const margin = 40;
  const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
  const edges = Array.isArray(payload?.edges) ? payload.edges : [];
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map();
  edges.forEach((edge) => {
    if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) return;
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    incoming.get(edge.target).push(edge.source);
  });
  const levels = new Map();
  function levelFor(nodeId, stack = new Set()) {
    if (levels.has(nodeId)) return levels.get(nodeId);
    const node = nodeById.get(nodeId);
    if (!node || node.kind === "root" || stack.has(nodeId)) {
      levels.set(nodeId, 0);
      return 0;
    }
    stack.add(nodeId);
    const parents = incoming.get(nodeId) || [];
    const level = parents.length ? Math.max(...parents.map((parent) => levelFor(parent, stack) + 1)) : 1;
    stack.delete(nodeId);
    levels.set(nodeId, level);
    return level;
  }
  nodes.forEach((node) => levelFor(node.id));
  const groups = new Map();
  nodes.forEach((node) => {
    const level = levels.get(node.id) || 0;
    if (!groups.has(level)) groups.set(level, []);
    groups.get(level).push(node);
  });
  groups.forEach((group) => {
    group.sort((left, right) => {
      if (left.kind === "root") return -1;
      if (right.kind === "root") return 1;
      const leftTime = Date.parse(left.createdAt || left.updatedAt || "") || 0;
      const rightTime = Date.parse(right.createdAt || right.updatedAt || "") || 0;
      if (leftTime !== rightTime) return leftTime - rightTime;
      return String(left.label || left.id).localeCompare(String(right.label || right.id));
    });
  });
  const positioned = new Map();
  let maxLevel = 0;
  let maxRows = 1;
  groups.forEach((group, level) => {
    maxLevel = Math.max(maxLevel, level);
    maxRows = Math.max(maxRows, group.length);
    group.forEach((node, index) => {
      positioned.set(node.id, {
        ...node,
        x: margin + level * (nodeWidth + columnGap),
        y: margin + index * rowGap,
        width: nodeWidth,
        height: nodeHeight,
      });
    });
  });
  return {
    nodes: Array.from(positioned.values()),
    edges: edges
      .map((edge) => ({ ...edge, sourceNode: positioned.get(edge.source), targetNode: positioned.get(edge.target) }))
      .filter((edge) => edge.sourceNode && edge.targetNode),
    width: Math.max(900, margin * 2 + (maxLevel + 1) * nodeWidth + maxLevel * columnGap),
    height: Math.max(520, margin * 2 + maxRows * nodeHeight + Math.max(0, maxRows - 1) * (rowGap - nodeHeight)),
  };
}

function edgePath(edge) {
  const source = edge.sourceNode;
  const target = edge.targetNode;
  const startX = source.x + source.width;
  const startY = source.y + source.height / 2;
  const endX = target.x;
  const endY = target.y + target.height / 2;
  const bend = Math.max(48, (endX - startX) / 2);
  return `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`;
}

function renderBranchGraph(payload) {
  state.graph = payload;
  const summary = payload?.summary || {};
  els.branchGraphStatus.className = "settings-status";
  els.branchGraphStatus.textContent = `${summary.activeBranches || 0} active · ${summary.archivedBranches || 0} archived · ${summary.mergeBranches || 0} merge · ${summary.globalizedArchives || 0} globalized`;
  const layout = buildGraphLayout(payload);
  if (!layout.nodes.length) {
    els.branchGraph.innerHTML = '<div class="muted">No branch graph yet.</div>';
    return;
  }
  const edgeMarkup = layout.edges
    .map((edge) => {
      const source = edge.sourceNode;
      const target = edge.targetNode;
      const labelX = (source.x + source.width + target.x) / 2;
      const labelY = (source.y + target.y) / 2 + source.height / 2 - 6;
      const label = edge.kind === "root" || edge.kind === "parent" ? "" : graphLabel(edge.label || edge.kind, 12);
      return `
        <g class="graph-edge graph-edge-${escapeHtml(edge.kind || "edge")}">
          <path d="${edgePath(edge)}"></path>
          ${label ? `<text x="${labelX}" y="${labelY}">${escapeHtml(label)}</text>` : ""}
        </g>
      `;
    })
    .join("");
  const nodeMarkup = layout.nodes
    .map((node) => {
      const active = node.branchId === state.activeBranch || node.archiveId === state.activeGlobalized;
      const canOpen = node.status !== "missing" && (node.branchId || node.archiveId);
      const clickable = canOpen ? "clickable" : "";
      const meta =
        node.kind === "branch"
          ? `${node.meta || ""}${node.shortHead ? ` · ${node.shortHead}` : ""}${Number.isFinite(node.historyCount) ? ` · ${node.historyCount} msg` : ""}`
          : node.meta || "";
      const data =
        !canOpen
          ? ""
          : node.archiveId
          ? `data-graph-archive="${escapeHtml(node.archiveId)}"`
          : node.branchId
          ? `data-graph-branch="${escapeHtml(node.branchId)}"`
          : "";
      return `
        <g class="graph-node graph-node-${escapeHtml(node.kind || "node")} graph-status-${escapeHtml(node.status || "")} ${active ? "active" : ""} ${clickable}" transform="translate(${node.x}, ${node.y})" ${data}>
          <title>${escapeHtml(`${node.title || node.label || node.id}\n${meta}`)}</title>
          <rect width="${node.width}" height="${node.height}" rx="7"></rect>
          <circle cx="16" cy="18" r="5"></circle>
          <text class="graph-node-label" x="28" y="23">${escapeHtml(graphLabel(node.label || node.id, 23))}</text>
          <text class="graph-node-meta" x="12" y="45">${escapeHtml(graphLabel(meta, 28))}</text>
        </g>
      `;
    })
    .join("");
  els.branchGraph.innerHTML = `
    <svg class="branch-graph-svg" viewBox="0 0 ${layout.width} ${layout.height}" role="img">
      <defs>
        <marker id="graphArrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
          <path d="M 0 0 L 10 4 L 0 8 z"></path>
        </marker>
      </defs>
      ${edgeMarkup}
      ${nodeMarkup}
    </svg>
  `;
  els.branchGraph.querySelectorAll("[data-graph-branch]").forEach((node) => {
    node.addEventListener("click", () => loadBranch(node.dataset.graphBranch));
  });
  els.branchGraph.querySelectorAll("[data-graph-archive]").forEach((node) => {
    node.addEventListener("click", () => loadGlobalizedArchive(node.dataset.graphArchive));
  });
}

async function loadBranchGraph() {
  selectTab("graph");
  els.activeTitle.textContent = "Branch graph";
  els.activeMeta.textContent = "Simplified ctxgit lineage";
  els.branchGraphStatus.className = "settings-status";
  els.branchGraphStatus.textContent = "Loading graph...";
  const payload = await api("/api/branch-graph");
  renderBranchGraph(payload);
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
  const branch = state.branches.find((item) => item.id === branchId);
  return (
    state.branchActivityAt[branchId] ||
    jobStartedAt(job) ||
    Date.parse(branch?.lastUserMessageAt || "") ||
    0
  );
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
  const internal = status.internal || {};
  els.gitSummary.innerHTML = `
    <div>Branch: <strong>${escapeHtml(status.branch || "(none)")}</strong></div>
    <div>Staged: ${status.stagedCount} · Unstaged: ${status.unstagedCount} · Untracked: ${status.untrackedCount}</div>
    <div class="muted">ctxgit Git: ${escapeHtml(String(internal.dirtyCount || 0))} pending · ${escapeHtml(internal.gitDir || "")}</div>
  `;
  if (els.internalGitLog) {
    const refs = (internal.refs || [])
      .slice(0, 20)
      .map((item) => `${item.short || ""} ${item.ref || ""} ${item.subject || ""}`.trim())
      .join("\n");
    els.internalGitLog.textContent =
      [internal.log || "No internal ctxgit commits yet.", refs ? `\nRefs:\n${refs}` : ""].filter(Boolean).join("\n");
  }
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
            const label = path ? renderProjectFileLink(path, `<code>${escapeHtml(path)}</code>`) : "<code></code>";
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
      els.messageList.scrollTo({ top: els.messageList.scrollHeight, behavior: "auto" });
    });
  });
}

function attachProgressPanel() {
  if (!els.progressPanel || !els.messageList) return;
  if (els.progressPanel.parentElement !== els.messageList) {
    els.messageList.appendChild(els.progressPanel);
  }
}

function replaceMessageListHtml(html) {
  els.messageList.innerHTML = html;
  attachProgressPanel();
}

function appendMessageListHtml(html) {
  attachProgressPanel();
  if (els.progressPanel.parentElement === els.messageList) {
    els.progressPanel.insertAdjacentHTML("beforebegin", html);
  } else {
    els.messageList.insertAdjacentHTML("beforeend", html);
  }
}

function showProgress(title) {
  attachProgressPanel();
  els.progressPanel.hidden = false;
  els.progressTitle.textContent = title;
  els.progressEvents.innerHTML = "";
  scrollChatToBottom();
}

function updateProgress(job) {
  attachProgressPanel();
  els.progressPanel.hidden = false;
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

function showChatError(message) {
  if (!els.chatError) return;
  document.querySelectorAll(".chat-main > .error-banner:not(#chatError)").forEach((item) => item.remove());
  els.chatError.textContent = message || "작업 실패";
  els.chatError.hidden = false;
}

function hideChatError() {
  if (!els.chatError) return;
  els.chatError.hidden = true;
  els.chatError.textContent = "";
  document.querySelectorAll(".chat-main > .error-banner:not(#chatError)").forEach((item) => item.remove());
}

function isEventListNearBottom() {
  const remaining = els.eventList.scrollHeight - els.eventList.scrollTop - els.eventList.clientHeight;
  return remaining <= 32;
}

function setEventListScrollTop(value) {
  els.eventList.scrollTop = value;
  window.requestAnimationFrame(() => {
    els.eventList.scrollTop = value;
    window.requestAnimationFrame(() => {
      els.eventList.scrollTop = value;
    });
  });
}

function renderEventPanel(job) {
  if (!job || !job.id) return;
  const isNewJob = state.currentJob?.id !== job.id;
  const previousScrollTop = els.eventList.scrollTop;
  const shouldFollowEvents = isNewJob || isEventListNearBottom();
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
  setEventListScrollTop(shouldFollowEvents ? els.eventList.scrollHeight : previousScrollTop);
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

function appendPendingUserMessage({ branch, text, mode }) {
  if (state.activeBranch !== branch) return "";
  const pendingId = `pending-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const historyCount = Array.isArray(state.payload?.history) ? state.payload.history.length : 0;
  const number = historyCount + els.messageList.querySelectorAll(".message.pending-message").length + 1;
  if (els.messageList.querySelector(".muted")) {
    replaceMessageListHtml("");
  }
  appendMessageListHtml(
    `
      <article class="message pending-message" data-pending-message="${escapeHtml(pendingId)}">
        <div class="message-header">
          <span class="message-role">user</span>
          <span class="message-meta-actions">
            <span class="message-number">${number}</span>
            <span>${escapeHtml(new Date().toISOString())}</span>
            <span class="pending-label">${escapeHtml(mode === "research" ? "research queued" : mode === "info-chat" ? "info queued" : "sending")}</span>
          </span>
        </div>
        <div class="message-text">${renderMessageText(text)}</div>
      </article>
    `,
  );
  scrollChatToBottom();
  return pendingId;
}

function removePendingUserMessage(pendingId) {
  if (!pendingId) return;
  els.messageList.querySelector(`[data-pending-message="${pendingId}"]`)?.remove();
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

function resizeMessageInput() {
  const input = els.messageInput;
  if (!input) return;
  const maxHeight = Number.parseFloat(window.getComputedStyle(input).maxHeight);
  input.style.height = "auto";
  const nextHeight = Number.isFinite(maxHeight)
    ? Math.min(input.scrollHeight, maxHeight)
    : input.scrollHeight;
  input.style.height = `${nextHeight}px`;
}

function updateComposerState() {
  const running = activeBranchRunningJob();
  const startingMode = state.activeBranch ? state.startingBranches[state.activeBranch] : "";
  const archived = state.payload?.archived === true;
  const disabled = !state.activeBranch || archived || Boolean(running) || Boolean(startingMode);
  els.sendButton.disabled = disabled;
  els.researchButton.disabled = disabled;
  els.historyChatButton.disabled = disabled;
  const busyMode = running?.mode || startingMode;
  els.sendButton.textContent = archived ? "Archived" : busyMode === "chat" ? "생각 중" : "Send";
  els.researchButton.textContent = archived ? "Archived" : busyMode === "research" ? "리서치 중" : "Research";
  els.historyChatButton.textContent = archived ? "Archived" : busyMode === "info-chat" ? "Info..." : "Info chat";
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
    scrollChatToBottom();
  } else {
    hideProgress();
  }
  updateComposerState();
}

async function refreshBranchNavigation() {
  const data = await api("/api/branches");
  state.branches = data.branches || [];
  state.archived = data.archived || [];
  state.views = data.views || [];
  state.globalized = data.globalized || [];
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
  loadWorkerStatus().catch(() => {});
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
    showChatError(`작업 모니터링 실패: ${failed.message}`);
    hideProgress();
  }
  updateComposerState();
}

async function monitorTrackedJob(jobId) {
  const tracked = state.jobs[jobId];
  if (!tracked) return;
  const branch = tracked.branch;
  let waitMs = 500;
  let fetchFailures = 0;
  while (true) {
    await sleep(waitMs);
    let job;
    try {
      job = await api(`/api/job?id=${encodeURIComponent(jobId)}`);
      fetchFailures = 0;
    } catch (error) {
      if (isNetworkFetchError(error)) {
        fetchFailures += 1;
        const now = new Date().toISOString();
        const previous = state.jobs[jobId] || tracked;
        const message =
          fetchFailures === 1
            ? "서버 연결이 잠시 끊겨 작업 상태를 다시 확인 중입니다."
            : `서버 연결 재시도 중 (${fetchFailures})`;
        const events =
          fetchFailures === 1 || fetchFailures % 5 === 0
            ? [...(previous.events || []), { message, createdAt: now }]
            : previous.events || [];
        const reconnecting = rememberJob(
          {
            ...previous,
            status: "running",
            error: "monitor_reconnecting",
            message,
            updatedAt: now,
            events,
            diagnostics: {
              ...(previous.diagnostics || {}),
              state: "monitor_reconnecting",
              detail: message,
              lastEvent: message,
            },
          },
          { branch, mode: tracked.mode },
        );
        if (state.activeBranch === branch) {
          updateProgress(reconnecting);
          renderEventPanel(reconnecting);
          updateComposerState();
        }
        waitMs = Math.min(2500, waitMs + 300);
        continue;
      } else if (error instanceof ApiError && error.payload?.error === "job_not_found") {
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
        if (remembered.mode === "merge") {
          selectTab("archives");
        }
        renderGit(await api("/api/git/status"));
        renderProvider(await api("/api/provider/status"));
        hideProgressSoon();
      }
      updateComposerState();
      loadWorkerStatus().catch(() => {});
      return;
    }
    if (remembered.status === "failed") {
      renderBranches();
      if (state.activeBranch === branch) {
        const prefix = remembered.error === "timeout" ? "시간 초과" : remembered.error === "job_not_found" ? "중단됨" : remembered.mode === "research" ? "리서치 실패" : remembered.mode === "merge" ? "머지 실패" : "채팅 실패";
        showChatError(`${prefix}: ${remembered.message || "작업 실패"}`);
        hideProgress();
      }
      updateComposerState();
      loadWorkerStatus().catch(() => {});
      return;
    }
    waitMs = Math.min(1200, waitMs + 100);
  }
}

function renderBranch(payload) {
  hideChatError();
  state.payload = payload;
  const meta = payload.meta;
  const archived = payload.archived === true;
  els.activeTitle.textContent = meta.title || meta.id;
  els.activeMeta.textContent = archived
    ? `${meta.id} · archived branch · read only`
    : `${meta.id} · history.jsonl is Git-tracked conversation history`;

  replaceMessageListHtml(
    payload.history
      .map(
        (message, index) => `
          <article class="message">
            <div class="message-header">
              <span class="message-role">${escapeHtml(message.role)}</span>
                <span class="message-meta-actions">
                  <span class="message-number">${index + 1}</span>
                  <span>${escapeHtml(message.createdAt)}</span>
                  ${
                    archived
                      ? ""
                      : `<span class="message-options">
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
                              data-history-cut="${index}"
                              data-history-created-at="${escapeHtml(message.createdAt || "")}"
                              data-history-role="${escapeHtml(message.role || "")}"
                              type="button"
                            >Cut here</button>
                            <button
                              class="danger"
                              data-history-delete="${index}"
                              data-history-created-at="${escapeHtml(message.createdAt || "")}"
                              data-history-role="${escapeHtml(message.role || "")}"
                              type="button"
                            >Delete message</button>
                          </span>
                        </span>`
                  }
              </span>
            </div>
            <div class="message-text">${renderMessageText(message.text)}</div>
            ${renderArtifacts(message.artifacts)}
            ${archived ? "" : renderApprovalRequests(message.approvalRequests, payload.approvalStatuses || {})}
          </article>
        `,
      )
      .join("") || '<div class="muted">No messages yet.</div>',
  );
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
  els.messageList.querySelectorAll("[data-history-cut]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMessageMenus();
      cutHistoryMessage(button);
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
    <dt>ctxgit ref</dt><dd>${escapeHtml(payload.git?.internal?.ref || "")}</dd>
    <dt>ctxgit head</dt><dd>${escapeHtml(payload.git?.internal?.head || "")}</dd>
  `;
  els.historyLog.textContent =
    payload.git?.internal?.log || payload.git.historyLog || "No internal ctxgit commits for this branch yet.";
  els.currentDiff.textContent =
    [payload.git.status, payload.git.historyDiff, payload.git.contextDiff].filter(Boolean).join("\n\n") ||
    "No uncommitted branch file diff.";
  if (els.internalGitLog) {
    els.internalGitLog.textContent = payload.git?.internal?.log || "No internal ctxgit commits for this branch yet.";
  }
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
  state.archived = data.archived || [];
  state.views = data.views || [];
  state.globalized = data.globalized || [];
  if (!state.activeBranch && !state.activeGlobalized && state.branches.length) {
    state.activeBranch = state.branches[0].id;
  }
  renderBranches();
  if (state.activeBranch) {
    await loadBranch(state.activeBranch);
  } else {
    els.activeTitle.textContent = "No branch selected";
    els.activeMeta.textContent = "Create a branch from the terminal with ctxgit branch <id>.";
    replaceMessageListHtml('<div class="muted">No messages yet.</div>');
  }
}

async function loadServerProjects() {
  try {
    renderServerProjects(await api("/api/server/projects"));
  } catch (error) {
    els.serverProjectPanel.hidden = true;
  }
}

async function loadWorkerStatus() {
  try {
    renderWorker(await api("/api/worker/status"));
  } catch (error) {
    renderWorker(null);
  }
}

async function loadProject() {
  await loadServerProjects();
  await loadWorkerStatus();
  const project = await api("/api/project");
  renderProject(project);
  if (project.initialized) {
    await loadBranches();
    await loadProjectFiles(state.fileBrowser.path || "");
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
    await loadWorkerStatus();
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
    state.fileBrowser = { path: "", parent: "", entries: [] };
    await loadBranches();
    await loadProjectFiles("");
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

async function openServerProject() {
  const id = els.serverProjectSelect.value;
  if (!id) return;
  els.openServerProjectButton.disabled = true;
  setServerProjectStatus("Opening server project...");
  try {
    const project = await api("/api/server/project/open", {
      method: "POST",
      body: JSON.stringify({ id }),
    });
    renderProject(project);
    state.activeBranch = null;
    state.activeGlobalized = null;
    state.fileBrowser = { path: "", parent: "", entries: [] };
    await loadServerProjects();
    await loadBranches();
    await loadProjectFiles("");
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
    await loadWorkerStatus();
    setServerProjectStatus("Opened.", "ok");
  } catch (error) {
    clearWorkspace(error.message);
    setServerProjectStatus(`Open failed: ${error.message}`, "error");
  } finally {
    els.openServerProjectButton.disabled = false;
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
  state.activeGlobalized = null;
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

async function cutHistoryMessage(button) {
  if (!state.activeBranch) return;
  const index = Number.parseInt(button.dataset.historyCut || "", 10);
  if (!Number.isInteger(index)) return;
  const branch = state.activeBranch;
  if (
    !window.confirm(
      `Cut ${branch} after message ${index + 1}?\n\nThis rewinds branch history and context to that internal ctxgit snapshot. Messages and context after it will disappear from this branch.`,
    )
  ) {
    return;
  }
  button.disabled = true;
  try {
    const payload = await api("/api/history/cut", {
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
    window.alert(`Cut failed: ${error.message}`);
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

async function archiveBranch(branch) {
  if (!branch) return;
  const range = window.prompt(`Archive ${branch}. Leave blank for archive only, or enter start,end to globalize a range:`, "");
  if (range === null) return;
  const body = { branch };
  const trimmed = range.trim();
  if (trimmed) {
    const parts = trimmed
      .split(/[,\s]+/)
      .map((item) => Number.parseInt(item.trim(), 10))
      .filter((item) => Number.isInteger(item));
    if (parts.length !== 2) {
      window.alert("Archive range must be blank, or two message numbers like 2,5.");
      return;
    }
    body.start = parts[0];
    body.end = parts[1];
  }
  try {
    const payload = await api("/api/branch/archive", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.branches = payload.branches || state.branches;
    state.archived = payload.archived || state.archived;
    state.views = payload.views || state.views;
    state.globalized = payload.globalized || state.globalized;
    if (state.activeBranch === branch) {
      state.activeBranch = null;
      state.payload = null;
    }
    await refreshBranchNavigation();
    if (payload.archive?.id) {
      await loadGlobalizedArchive(payload.archive.id);
    } else {
      await loadBranches();
    }
  } catch (error) {
    window.alert(`Archive failed: ${error.message}`);
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

async function loadGlobalizedArchive(archiveId) {
  if (!archiveId) return;
  const payload = await api(`/api/globalized?id=${encodeURIComponent(archiveId)}`);
  state.activeBranch = null;
  state.activeGlobalized = archiveId;
  renderBranches();
  const meta = payload.meta || {};
  const range = `${meta.rangeStart || "?"}-${meta.rangeEnd || "?"}`;
  els.activeTitle.textContent = meta.title || archiveId;
  els.activeMeta.textContent = `${meta.sourceBranch || "archived"} · messages ${range}`;
  els.reportView.innerHTML = renderMarkdown(payload.markdown || "");
  const messages =
    (payload.history || [])
      .map(
        (message, index) => `
          <article class="message">
            <div class="message-header">
              <span class="message-role">${escapeHtml(message.role)}</span>
              <span class="message-meta-actions">
                <span class="message-number">${(meta.rangeStart || 1) + index}</span>
                <span>${escapeHtml(message.createdAt)}</span>
              </span>
            </div>
            <div class="message-text">${renderMessageText(message.text)}</div>
          </article>
        `,
      )
      .join("") || '<div class="muted">No archived messages.</div>';
  els.archiveList.innerHTML = `
    <button class="nav-item active" type="button">
      <span class="nav-title">${escapeHtml(meta.title || archiveId)}</span>
      <span class="nav-meta">${escapeHtml(payload.paths?.history || "")}</span>
    </button>
  `;
  els.archiveViewer.innerHTML = `
    <div class="archive-heading">
      <h2>${escapeHtml(meta.title || archiveId)}</h2>
      <div class="active-meta">${escapeHtml(payload.paths?.markdown || "")}</div>
    </div>
    <div class="message-list">${messages}</div>
  `;
  selectTab("archives");
}

async function loadView(view) {
  const payload = await api(`/api/view?id=${encodeURIComponent(view)}`);
  state.activeBranch = null;
  state.activeGlobalized = null;
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
  if (tab === "files") loadProjectFiles().catch(() => {});
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.tab === "graph") {
      loadBranchGraph().catch((error) => {
        els.branchGraphStatus.textContent = `Graph failed: ${error.message}`;
        els.branchGraphStatus.className = "settings-status error";
      });
      return;
    }
    selectTab(button.dataset.tab);
  });
});

els.branchGraphButton.addEventListener("click", () => {
  loadBranchGraph().catch((error) => {
    els.branchGraphStatus.textContent = `Graph failed: ${error.message}`;
    els.branchGraphStatus.className = "settings-status error";
  });
});

els.graphRefreshButton.addEventListener("click", () => {
  loadBranchGraph().catch((error) => {
    els.branchGraphStatus.textContent = `Graph failed: ${error.message}`;
    els.branchGraphStatus.className = "settings-status error";
  });
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".branch-row")) {
    closeBranchMenus();
  }
  if (!event.target.closest(".message-options")) {
    closeMessageMenus();
  }
});

els.loginForm.addEventListener("submit", submitLogin);
els.registerForm.addEventListener("submit", submitRegister);
els.logoutButton.addEventListener("click", logout);
els.authSwitchButton.addEventListener("click", () => {
  showAuthMode(state.authMode === "register" ? "login" : "register");
  setAuthStatus("");
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

els.openServerProjectButton.addEventListener("click", openServerProject);

els.filePathForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadProjectFiles(els.filePathInput.value.trim());
});

els.fileUpButton.addEventListener("click", async () => {
  await loadProjectFiles(state.fileBrowser.parent || "");
});

els.fileRefreshButton.addEventListener("click", async () => {
  await loadProjectFiles();
});

els.newFolderButton.addEventListener("click", createFolderFromPrompt);

els.fileUploadInput.addEventListener("change", async () => {
  await uploadFiles(els.fileUploadInput.files);
});

els.folderUploadInput.addEventListener("change", async () => {
  await uploadFiles(els.folderUploadInput.files);
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
  els.mergeStatus.textContent = "Starting merge...";
  els.mergeStatus.className = "settings-status";
  try {
    state.activeBranch = name;
    markBranchActivity(name);
    renderBranches();
    await startTrackedJob(
      "/api/merge/start",
      { branches, name },
      { branch: name, mode: "merge", title: "머지 요약 생성 중" },
    );
    els.mergeSourcesInput.value = "";
    els.mergeNameInput.value = "";
    els.mergeStatus.textContent = "Merge started.";
    els.mergeStatus.classList.add("ok");
  } catch (error) {
    els.mergeStatus.textContent = `Merge failed: ${error.message}`;
    els.mergeStatus.classList.add("error");
  } finally {
    els.mergeButton.disabled = false;
  }
});

async function sendComposerMessage({ mode }) {
  if (!state.activeBranch) return;
  if (state.payload?.archived === true) {
    window.alert("Archived branches are read-only. Fork or clone it before continuing work.");
    return;
  }
  const branch = state.activeBranch;
  const text = els.messageInput.value.trim();
  if (!text) return;
  hideChatError();
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
  const pendingMessageId = appendPendingUserMessage({ branch, text, mode: requestedMode });
  try {
    if (isResearch) {
      await startTrackedJob(
        "/api/research/start",
        { branch, text, provider: "hybrid" },
        { branch, mode: "research", title: "리서치 시작 중" },
      );
      els.messageInput.value = "";
      resizeMessageInput();
      return;
    }
    if (isChat) {
      const provider = state.worker?.preferWorker ? "codex-worker" : "codex";
      await startTrackedJob(
        "/api/chat/start",
        { branch, text, provider },
        { branch, mode: "chat", title: "채팅 턴 시작 중" },
      );
      els.messageInput.value = "";
      resizeMessageInput();
      return;
    }
    if (isInfoChat) {
      const provider = state.worker?.preferWorker ? "codex-worker" : "codex";
      await startTrackedJob(
        "/api/info-chat/start",
        { branch, text, provider },
        { branch, mode: "info-chat", title: "정보 챗 시작 중" },
      );
      els.messageInput.value = "";
      resizeMessageInput();
      return;
    }
  } catch (error) {
    removePendingUserMessage(pendingMessageId);
    const isTimeout = error instanceof ApiError && error.payload?.error === "timeout";
    const isMissingJob = error instanceof ApiError && error.payload?.error === "job_not_found";
    const prefix = isTimeout ? "시간 초과" : isMissingJob ? "중단됨" : isResearch ? "리서치 실패" : "채팅 실패";
    if (state.activeBranch === branch) {
      showChatError(`${prefix}: ${error.message}`);
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

els.messageInput.addEventListener("input", resizeMessageInput);
resizeMessageInput();

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

loadAuthStatus()
  .then((auth) => {
    if (auth.authenticated) {
      return loadProject();
    }
    clearWorkspace("Login required.");
    return null;
  })
  .catch((error) => {
    els.activeTitle.textContent = "Could not load ctxgit project";
    els.activeMeta.textContent = error.message;
  });
