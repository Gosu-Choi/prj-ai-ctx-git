const state = {
  project: null,
  activeBranch: null,
  activeGlobalized: null,
  activeContextChat: false,
  branches: [],
  archived: [],
  views: [],
  globalized: [],
  graph: null,
  payload: null,
  provider: null,
  serverProjects: [],
  extensions: [],
  folders: [],
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
  messageDrafts: {},
  branchDropDepth: 0,
  branchResourceStaged: {},
  eventsVisible: false,
  mergeSelectedBranches: [],
  mergePickerOpen: false,
  sequenceRenderedReplies: {},
  sequenceOrder: [],
  sequenceEvaluator: null,
  sequenceOrderOpen: false,
  activeSummaryPath: "",
};

const CONTEXT_CHAT_KEY = "__contexts__";
// Unread-completion tab indicator state (see updateUnseenTabIndicator).
const BASE_DOCUMENT_TITLE = document.title || "ctxgit";
const notifiedDoneJobs = new Set();
const observedJobStatus = new Map();
const UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024;
const PROJECT_SESSION_KEY = "ctxgit.activeProjectPath";
const EVENT_PANEL_STORAGE_KEY = "ctxgit.eventsVisible";
const BRANCHES_COLLAPSED_STORAGE_KEY = "ctxgit.branchesCollapsed";
const BRANCH_RESOURCE_EXTENSIONS = new Set([
  ".bmp",
  ".gif",
  ".heic",
  ".heif",
  ".jpeg",
  ".jpg",
  ".docx",
  ".json",
  ".jsonl",
  ".md",
  ".pdf",
  ".png",
  ".pptx",
  ".svg",
  ".tif",
  ".tiff",
  ".txt",
  ".webp",
  ".xlsx",
]);

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
  branchesToggle: document.querySelector("#branchesToggle"),
  branchesBody: document.querySelector("#branchesBody"),
  extensionsToggle: document.querySelector("#extensionsToggle"),
  extensionsBody: document.querySelector("#extensionsBody"),
  extensionList: document.querySelector("#extensionList"),
  extensionContent: document.querySelector("#extensionContent"),
  contextChatButton: document.querySelector("#contextChatButton"),
  newFolderButton: document.querySelector("#newFolderButton"),
  folderDialog: document.querySelector("#folderDialog"),
  folderDialogTarget: document.querySelector("#folderDialogTarget"),
  folderDialogList: document.querySelector("#folderDialogList"),
  folderDialogNewForm: document.querySelector("#folderDialogNewForm"),
  folderDialogNewInput: document.querySelector("#folderDialogNewInput"),
  branchGraphButton: document.querySelector("#branchGraphButton"),
  viewList: document.querySelector("#viewList"),
  globalizedList: document.querySelector("#globalizedList"),
  gitSummary: document.querySelector("#gitSummary"),
  providerSummary: document.querySelector("#providerSummary"),
  workerSummary: document.querySelector("#workerSummary"),
  mergeForm: document.querySelector("#mergeForm"),
  mergeSourcePicker: document.querySelector("#mergeSourcePicker"),
  mergeSourceToggle: document.querySelector("#mergeSourceToggle"),
  mergeSourceToggleLabel: document.querySelector("#mergeSourceToggleLabel"),
  mergeSourceCount: document.querySelector("#mergeSourceCount"),
  mergeSourceDropdown: document.querySelector("#mergeSourceDropdown"),
  mergeSourceFilter: document.querySelector("#mergeSourceFilter"),
  mergeSelectedOrder: document.querySelector("#mergeSelectedOrder"),
  mergeSourceOptions: document.querySelector("#mergeSourceOptions"),
  mergeNameInput: document.querySelector("#mergeNameInput"),
  mergeButton: document.querySelector("#mergeButton"),
  mergeStatus: document.querySelector("#mergeStatus"),
  providerSettings: document.querySelector("#providerSettings"),
  providerInput: document.querySelector("#providerInput"),
  providerModelInput: document.querySelector("#providerModelInput"),
  webSearchInput: document.querySelector("#webSearchInput"),
  orchestrationInput: document.querySelector("#orchestrationInput"),
  orchestrationDialog: document.querySelector("#orchestrationDialog"),
  orchestrationTitle: document.querySelector("#orchestrationTitle"),
  orchestrationSubtitle: document.querySelector("#orchestrationSubtitle"),
  orchestrationBody: document.querySelector("#orchestrationBody"),
  timeoutSecondsInput: document.querySelector("#timeoutSecondsInput"),
  sandboxInput: document.querySelector("#sandboxInput"),
  saveProviderButton: document.querySelector("#saveProviderButton"),
  providerSettingsStatus: document.querySelector("#providerSettingsStatus"),
  activeTitle: document.querySelector("#activeTitle"),
  activeMeta: document.querySelector("#activeMeta"),
  openBranchDirButton: document.querySelector("#openBranchDirButton"),
  parentBranchButton: document.querySelector("#parentBranchButton"),
  chatTab: document.querySelector("#chatTab"),
  chatMain: document.querySelector(".chat-main"),
  messageList: document.querySelector("#messageList"),
  progressPanel: document.querySelector("#progressPanel"),
  progressTitle: document.querySelector("#progressTitle"),
  progressEvents: document.querySelector("#progressEvents"),
  chatError: document.querySelector("#chatError"),
  branchDropOverlay: document.querySelector("#branchDropOverlay"),
  branchResourceStage: document.querySelector("#branchResourceStage"),
  eventPanel: document.querySelector("#eventPanel"),
  eventPanelToggle: document.querySelector("#eventPanelToggle"),
  eventStatus: document.querySelector("#eventStatus"),
  copyEventLogButton: document.querySelector("#copyEventLogButton"),
  eventCopyStatus: document.querySelector("#eventCopyStatus"),
  eventMeta: document.querySelector("#eventMeta"),
  eventList: document.querySelector("#eventList"),
  reportView: document.querySelector("#reportView"),
  summaryList: document.querySelector("#summaryList"),
  summaryTitle: document.querySelector("#summaryTitle"),
  summaryMeta: document.querySelector("#summaryMeta"),
  summaryStatus: document.querySelector("#summaryStatus"),
  summaryEditor: document.querySelector("#summaryEditor"),
  summarySaveButton: document.querySelector("#summarySaveButton"),
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
  contextResetButton: document.querySelector("#contextResetButton"),
  contextBranchButton: document.querySelector("#contextBranchButton"),
  historyChatButton: document.querySelector("#historyChatButton"),
  teamButton: document.querySelector("#teamButton"),
  guestButton: document.querySelector("#guestButton"),
  guestChip: document.querySelector("#guestChip"),
  refreshButton: document.querySelector("#refreshButton"),
  telegramNotifyInput: document.querySelector("#telegramNotifyInput"),
  telegramNotifyStatus: document.querySelector("#telegramNotifyStatus"),
  outputHumanizeInput: document.querySelector("#outputHumanizeInput"),
  outputHumanizeStatus: document.querySelector("#outputHumanizeStatus"),
  sequenceRoomCreateButton: document.querySelector("#sequenceRoomCreateButton"),
  sequenceRoomUpdateButton: document.querySelector("#sequenceRoomUpdateButton"),
  sequenceNotifyToggle: document.querySelector("#sequenceNotifyToggle"),
  sequenceRoomDialog: document.querySelector("#sequenceRoomDialog"),
  sequenceRoomForm: document.querySelector("#sequenceRoomForm"),
  sequenceAgentRows: document.querySelector("#sequenceAgentRows"),
  sequenceAddAgentButton: document.querySelector("#sequenceAddAgentButton"),
  sequenceRoomName: document.querySelector("#sequenceRoomName"),
  sequenceMaxReplies: document.querySelector("#sequenceMaxReplies"),
  sequenceRoomStatus: document.querySelector("#sequenceRoomStatus"),
  sequenceUpdateDialog: document.querySelector("#sequenceUpdateDialog"),
  sequenceUpdateForm: document.querySelector("#sequenceUpdateForm"),
  sequenceUpdateOrder: document.querySelector("#sequenceUpdateOrder"),
  sequenceUpdatePrompt: document.querySelector("#sequenceUpdatePrompt"),
  sequenceUpdateAccess: document.querySelector("#sequenceUpdateAccess"),
  sequenceUpdateMaxReplies: document.querySelector("#sequenceUpdateMaxReplies"),
  sequenceUpdateMinEvaluatorRounds: document.querySelector("#sequenceUpdateMinEvaluatorRounds"),
  sequenceUpdateAcceptanceCriteria: document.querySelector("#sequenceUpdateAcceptanceCriteria"),
  sequenceSnapshotSummaryView: document.querySelector("#sequenceSnapshotSummaryView"),
  sequenceCurrentSummaryView: document.querySelector("#sequenceCurrentSummaryView"),
  sequenceSnapshotView: document.querySelector("#sequenceSnapshotView"),
  sequenceCurrentView: document.querySelector("#sequenceCurrentView"),
  sequenceUpdateSnapshot: document.querySelector("#sequenceUpdateSnapshot"),
  sequenceUpdateStatus: document.querySelector("#sequenceUpdateStatus"),
  sequenceOrderPicker: document.querySelector("#sequenceOrderPicker"),
  sequenceOrderButton: document.querySelector("#sequenceOrderButton"),
  sequenceOrderDropdown: document.querySelector("#sequenceOrderDropdown"),
  sequenceOrderSelected: document.querySelector("#sequenceOrderSelected"),
  sequenceOrderOptions: document.querySelector("#sequenceOrderOptions"),
  sequenceOrderStatus: document.querySelector("#sequenceOrderStatus"),
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

function storedProjectPath() {
  try {
    return sessionStorage.getItem(PROJECT_SESSION_KEY) || "";
  } catch {
    return "";
  }
}

function rememberProjectPath(path) {
  const value = String(path || "").trim();
  try {
    if (value) {
      sessionStorage.setItem(PROJECT_SESSION_KEY, value);
    } else {
      sessionStorage.removeItem(PROJECT_SESSION_KEY);
    }
  } catch {
    // Browsers may deny storage in private or locked-down contexts.
  }
}

function activeProjectPathForRequest() {
  // Fall back to this tab's stored project path so that on a fresh load (before
  // state.project exists) every request is still scoped to THIS tab's project
  // via the X-Ctxgit-Project header. sessionStorage is per-tab, and the folder
  // path is the unique key, so two tabs on different projects never clobber each
  // other (a refresh no longer adopts whichever project was globally opened last).
  return state.project?.path || storedProjectPath();
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const projectPath = activeProjectPathForRequest();
  if (projectPath && String(path).startsWith("/api/") && !String(path).startsWith("/api/auth/")) {
    headers["X-Ctxgit-Project"] = encodeURIComponent(projectPath);
  }
  const response = await fetch(path, {
    ...options,
    headers,
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
  if (
    !/^(?:contexts|\.ctxgit)\/[^\s<>"'`)]*\.(?:md|txt|json|jsonl|pdf|csv|tsv|html?|png|jpe?g|gif|webp|bmp|tiff?|svg|heic|heif)$/i.test(
      value,
    )
  ) {
    return false;
  }
  if (/[\\]/.test(value)) return false;
  return !value.split("/").some((part) => part === "" || part === "." || part === ".." || part === "~");
}

function renderProjectFileLink(path, labelHtml = escapeHtml(path)) {
  if (!state.project?.path || !isProjectFilePath(path)) return labelHtml;
  // Markdown opens in Obsidian; every other file opens with the OS default app.
  if (fileExtension(path) === ".md") {
    return `<a class="file-link" href="${escapeHtml(obsidianFileUrl(path))}" title="Open in Obsidian">${labelHtml}</a>`;
  }
  return `<a class="file-link" href="#" data-open-file="${escapeHtml(path)}" title="Open with default app">${labelHtml}</a>`;
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
    /(^|[\s(`])((?:contexts|\.ctxgit)\/[^\s<>"'`)]*\.(?:md|txt|json|jsonl|pdf|csv|tsv|html?|png|jpe?g|gif|webp|bmp|tiff?|svg|heic|heif))/gi,
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
  let tableRows = [];

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = "";
  };
  const flushTable = () => {
    if (tableRows.length === 0) return;
    const rows = tableRows;
    tableRows = [];
    // Needs a header row and a |---|---| separator to be a real table.
    if (rows.length < 2 || !/^\s*\|?\s*:?-{3,}/.test(rows[1])) {
      rows.forEach((row) => html.push(`<p>${renderChatInline(row)}</p>`));
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
      html.push(`<tr>${cells.map((cell) => `<${tag}>${renderChatInline(cell)}</${tag}>`).join("")}</tr>`);
    });
    html.push("</table>");
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

    if (line.includes("|") && line.trim().startsWith("|")) {
      closeList();
      tableRows.push(line);
      continue;
    }
    flushTable();

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
  flushTable();
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
  state.activeContextChat = false;
  state.branches = [];
  state.archived = [];
  state.views = [];
  state.globalized = [];
  state.graph = null;
  state.payload = null;
  state.fileBrowser = { path: "", parent: "", entries: [] };
  state.messageDrafts = {};
  state.branchResourceStaged = {};
  state.branchDropDepth = 0;
  state.mergeSelectedBranches = [];
  setMergePickerOpen(false);
  renderBranches();
  hideChatError();
  els.activeTitle.textContent = "No project selected";
  setBranchDirButton(null);
  els.sequenceRoomUpdateButton.hidden = true;
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
  renderBranchResourceStage();
  if (els.messageInput) {
    els.messageInput.value = "";
    resizeMessageInput();
  }
  hideProgress();
  hideEventPanel();
  updateComposerState();
}

function activeChatKey() {
  return state.activeContextChat ? CONTEXT_CHAT_KEY : state.activeBranch || "";
}

function saveActiveDraft() {
  const key = activeChatKey();
  if (!key || !els.messageInput) return;
  const value = els.messageInput.value;
  if (value) {
    state.messageDrafts[key] = value;
  } else {
    delete state.messageDrafts[key];
  }
}

function restoreActiveDraft() {
  if (!els.messageInput) return;
  const key = activeChatKey();
  els.messageInput.value = key ? state.messageDrafts[key] || "" : "";
  resizeMessageInput();
}

function clearDraft(key) {
  if (!key) return;
  delete state.messageDrafts[key];
  if (activeChatKey() === key && els.messageInput) {
    els.messageInput.value = "";
    resizeMessageInput();
  }
}

function renderProject(project) {
  state.project = project;
  const path = project?.path || "";
  rememberProjectPath(path);
  const initialized = project?.initialized === true;
  const gitInitialized = project?.gitInitialized === true;
  els.projectPathInput.value = path;
  const status = path
    ? `ctxgit: ${initialized ? "ready" : "not initialized"} · git: ${gitInitialized ? "ready" : "not initialized"}`
    : "No project selected";
  const displayStatus = path
    ? `ctxgit: ${initialized ? "ready" : "not initialized"} | git: ${gitInitialized ? "ready" : "not initialized"}`
    : "No project selected";
  if (!path) {
    els.projectSummary.innerHTML = `
      <div><strong>${escapeHtml(project?.name || "No project")}</strong></div>
      <div class="muted">${escapeHtml(displayStatus)}</div>
    `;
    return;
  }
  els.projectSummary.innerHTML = `
    <div><strong>${escapeHtml(project?.name || "No project")}</strong></div>
    <div class="muted">${escapeHtml(path)}</div>
    <div class="muted">ctxgit: ${initialized ? "ready" : "not initialized"} · git: ${gitInitialized ? "ready" : "not initialized"}</div>
  `;
  els.projectSummary.innerHTML = `
    <div><strong>${escapeHtml(project?.name || "No project")}</strong></div>
    <div class="muted">${escapeHtml(path)}</div>
    <div class="muted">${escapeHtml(displayStatus)}</div>
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

function hasDraggedFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

function canDropBranchResources() {
  if (!state.activeBranch || state.activeContextChat || state.activeGlobalized) return false;
  if (state.payload?.archived === true) return false;
  if (activeBranchRunningJob(state.activeBranch) || state.startingBranches[state.activeBranch]) return false;
  return true;
}

function fileExtension(name) {
  const index = String(name || "").lastIndexOf(".");
  return index >= 0 ? String(name).slice(index).toLowerCase() : "";
}

function stagedBranchResources(branch = state.activeBranch) {
  return branch ? state.branchResourceStaged[branch] || [] : [];
}

function clearStagedBranchResources(branch = state.activeBranch) {
  if (!branch) return;
  delete state.branchResourceStaged[branch];
  renderBranchResourceStage();
}

function removeStagedBranchResource(branch, index) {
  const files = stagedBranchResources(branch);
  if (!files.length || index < 0 || index >= files.length) return;
  files.splice(index, 1);
  if (files.length) {
    state.branchResourceStaged[branch] = files;
  } else {
    delete state.branchResourceStaged[branch];
  }
  renderBranchResourceStage();
}

function renderBranchResourceStage() {
  if (!els.branchResourceStage) return;
  const branch = state.activeBranch;
  const files = stagedBranchResources(branch);
  if (!branch || state.activeContextChat || state.activeGlobalized || state.payload?.archived === true || !files.length) {
    els.branchResourceStage.hidden = true;
    els.branchResourceStage.innerHTML = "";
    return;
  }
  const totalBytes = files.reduce((total, file) => total + (Number(file.size) || 0), 0);
  els.branchResourceStage.hidden = false;
  els.branchResourceStage.innerHTML = `
    <div class="resource-stage-header">
      <strong>${files.length} resource file${files.length === 1 ? "" : "s"} staged</strong>
      <span class="resource-stage-meta">${escapeHtml(branch)} · ${formatBytes(totalBytes)} · send to add</span>
      <button class="resource-stage-clear" type="button" aria-label="Clear staged resources">x</button>
    </div>
    <div class="resource-stage-list">
      ${files
        .map(
          (file, index) => `
            <span class="resource-stage-chip">
              <span title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
              <button data-staged-resource-remove="${index}" type="button" aria-label="Remove ${escapeHtml(file.name)}">x</button>
            </span>
          `,
        )
        .join("")}
    </div>
  `;
  els.branchResourceStage.querySelector(".resource-stage-clear")?.addEventListener("click", () => {
    clearStagedBranchResources(branch);
  });
  els.branchResourceStage.querySelectorAll("[data-staged-resource-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      removeStagedBranchResource(branch, Number.parseInt(button.dataset.stagedResourceRemove || "", 10));
    });
  });
}

function stageBranchResourceFiles(fileList) {
  const branch = state.activeBranch;
  const files = Array.from(fileList || []).filter((file) => file && file.name);
  if (!files.length) return;
  if (!canDropBranchResources()) {
    showChatError("Select an active writable branch before staging resource files.");
    return;
  }
  // Any file type may be attached: resources are referenced by path (name/size) in
  // the prompt, so there is no extension allowlist to filter against here.
  hideChatError();
  const existing = stagedBranchResources(branch);
  state.branchResourceStaged[branch] = [...existing, ...files];
  renderBranchResourceStage();
}

function extensionForMimeType(type) {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "image/jpeg") return ".jpg";
  if (normalized === "image/png") return ".png";
  if (normalized === "image/gif") return ".gif";
  if (normalized === "image/webp") return ".webp";
  if (normalized === "image/bmp") return ".bmp";
  if (normalized === "image/tiff") return ".tiff";
  if (normalized === "image/svg+xml") return ".svg";
  if (normalized === "image/heic") return ".heic";
  if (normalized === "image/heif") return ".heif";
  return ".png";
}

function clipboardImageFileName(file, index) {
  const existing = String(file?.name || "").trim();
  const existingExt = fileExtension(existing);
  if (existing && existing !== "image.png" && BRANCH_RESOURCE_EXTENSIONS.has(existingExt)) {
    return existing;
  }
  const stamp = new Date().toISOString().replace(/[-:.]/g, "").replace("T", "-").replace("Z", "");
  const suffix = index > 1 ? `-${index}` : "";
  return `clipboard-${stamp}${suffix}${extensionForMimeType(file?.type)}`;
}

function clipboardImageFiles(event) {
  const items = Array.from(event.clipboardData?.items || []);
  const files = [];
  for (const item of items) {
    if (!String(item.type || "").startsWith("image/")) continue;
    const file = item.getAsFile?.();
    if (!file) continue;
    files.push(new File([file], clipboardImageFileName(file, files.length + 1), {
      type: file.type || item.type || "image/png",
      lastModified: Date.now(),
    }));
  }
  return files;
}

function setBranchDropActive(active) {
  const visible = Boolean(active && canDropBranchResources());
  els.chatMain?.classList.toggle("drop-active", visible);
  if (els.branchDropOverlay) {
    els.branchDropOverlay.hidden = !visible;
  }
}

function updateBranchUploadProgress(message) {
  attachProgressPanel();
  els.progressPanel.hidden = false;
  els.progressTitle.textContent = "Branch resource upload";
  els.progressEvents.innerHTML = `<div>${escapeHtml(message)}</div>`;
}

async function uploadBranchResourceFileInChunks(file, { branch, overwrite, index, total }) {
  const path = file.name;
  const chunkCount = Math.max(1, Math.ceil(file.size / UPLOAD_CHUNK_BYTES));
  let lastPayload = null;
  if (file.size === 0) {
    updateBranchUploadProgress(`Uploading ${index}/${total}: ${path}`);
    lastPayload = await api("/api/branch/source/upload-chunk", {
      method: "POST",
      body: JSON.stringify({
        branch,
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
    updateBranchUploadProgress(`Uploading ${index}/${total}: ${path} (${chunkIndex}/${chunkCount}, ${formatBytes(offset)} of ${formatBytes(file.size)})`);
    const contentBase64 = await readBlobAsBase64(blob);
    lastPayload = await api("/api/branch/source/upload-chunk", {
      method: "POST",
      body: JSON.stringify({
        branch,
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

async function finishBranchResourceUpload(branch, uploadedPaths, options = {}) {
  const payload = await api("/api/branch/source/upload-finish", {
    method: "POST",
    body: JSON.stringify({ branch, files: uploadedPaths }),
  });
  if (options.render !== false && state.activeBranch === branch && !state.activeContextChat) {
    renderBranch(payload);
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
  }
  await refreshBranchNavigation();
  return payload;
}

async function uploadBranchResourceFiles(fileList, options = {}) {
  const branch = options.branch || state.activeBranch;
  const files = Array.from(fileList || []).filter((file) => file && file.name);
  if (!files.length) return;
  const blocked =
    !branch ||
    branch !== state.activeBranch ||
    state.activeContextChat ||
    state.activeGlobalized ||
    state.payload?.archived === true ||
    Boolean(activeBranchRunningJob(branch)) ||
    Boolean(state.startingBranches[branch] && !options.allowStarting);
  if (blocked) {
    throw new Error("Select an active writable branch before uploading resource files.");
  }
  hideChatError();
  const uploadedPaths = [];
  let overwriteAll = false;
  if (options.showProgress !== false) {
    showProgress("Branch resource upload");
  }
  try {
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      try {
        const result = await uploadBranchResourceFileInChunks(file, {
          branch,
          overwrite: overwriteAll,
          index: index + 1,
          total: files.length,
        });
        uploadedPaths.push(result?.entry?.name || file.name);
      } catch (error) {
        if (!(error instanceof ApiError) || error.payload?.error !== "file_exists") throw error;
        if (!window.confirm(`${error.message}\n\nOverwrite existing branch resource file(s) for the rest of this upload?`)) {
          if (uploadedPaths.length) {
            await finishBranchResourceUpload(branch, uploadedPaths, { render: options.render !== false });
            els.progressTitle.textContent = "완료됨";
            els.progressEvents.innerHTML = `<div>Added ${uploadedPaths.length} branch resource file(s).</div>`;
            hideProgressSoon();
          } else {
            hideProgress();
          }
          return;
        }
        overwriteAll = true;
        const result = await uploadBranchResourceFileInChunks(file, {
          branch,
          overwrite: true,
          index: index + 1,
          total: files.length,
        });
        uploadedPaths.push(result?.entry?.name || file.name);
      }
    }
    const payload = await finishBranchResourceUpload(branch, uploadedPaths, { render: options.render !== false });
    const added = payload.uploadedResources?.length || uploadedPaths.length;
    if (options.clearStage !== false) {
      clearStagedBranchResources(branch);
    }
    if (options.showProgress !== false) {
      els.progressTitle.textContent = "완료됨";
      els.progressEvents.innerHTML = `<div>Added ${added} file(s) to ${escapeHtml(branch)} resources.</div>`;
      hideProgressSoon();
    }
    return payload;
  } catch (error) {
    if (uploadedPaths.length) {
      try {
        await finishBranchResourceUpload(branch, uploadedPaths, { render: options.render !== false });
      } catch {
        // Keep the original upload error visible.
      }
    }
    showChatError(`Resource upload failed: ${error.message}`);
    hideProgress();
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

const FOLDER_COLLAPSED_STORAGE_KEY = "ctxgit.foldersCollapsed";

function getCollapsedFolders() {
  try {
    const raw = JSON.parse(localStorage.getItem(FOLDER_COLLAPSED_STORAGE_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function setCollapsedFolders(list) {
  try {
    localStorage.setItem(FOLDER_COLLAPSED_STORAGE_KEY, JSON.stringify([...new Set(list)]));
  } catch {
    // localStorage may be unavailable; state still applies for this render.
  }
}

function toggleFolderCollapsed(folder) {
  const set = new Set(getCollapsedFolders());
  if (set.has(folder)) set.delete(folder);
  else set.add(folder);
  setCollapsedFolders([...set]);
  renderBranches();
}

function applyFolderResponse(data) {
  if (data.branches) state.branches = data.branches;
  if (data.folders) state.folders = data.folders;
  renderBranches();
}

async function setBranchFolder(branch, folder) {
  try {
    applyFolderResponse(
      await api("/api/branch/folder", { method: "POST", body: JSON.stringify({ branch, folder }) }),
    );
  } catch (error) {
    window.alert(`Move to folder failed: ${error.message}`);
  }
}

async function createFolder(name) {
  const trimmed = (name || "").trim();
  if (!trimmed) return;
  try {
    applyFolderResponse(await api("/api/folders/create", { method: "POST", body: JSON.stringify({ name: trimmed }) }));
  } catch (error) {
    window.alert(`Folder create failed: ${error.message}`);
  }
}

async function deleteFolder(name) {
  if (!window.confirm(`폴더 "${name}" 삭제?\n안에 있던 브랜치는 삭제되지 않고 그룹만 해제됩니다.`)) return;
  try {
    applyFolderResponse(await api("/api/folders/delete", { method: "POST", body: JSON.stringify({ name }) }));
  } catch (error) {
    window.alert(`Folder delete failed: ${error.message}`);
  }
}

// "Move to folder" opens a picker listing existing folders (create-first UX).
function openFolderPicker(branch) {
  const dialog = els.folderDialog;
  if (!dialog) return;
  const current = (state.branches.find((item) => item.id === branch)?.folder || "").trim();
  els.folderDialogTarget.textContent = branch;
  const rows = [];
  rows.push(
    `<button class="folder-pick ${current ? "" : "active"}" data-pick-folder="" type="button">— 그룹 해제 (폴더 없음)</button>`,
  );
  (state.folders || []).forEach((folder) => {
    rows.push(
      `<button class="folder-pick ${folder === current ? "active" : ""}" data-pick-folder="${escapeHtml(folder)}" type="button">${escapeHtml(folder)}</button>`,
    );
  });
  els.folderDialogList.innerHTML = rows.join("") || '<div class="muted">폴더가 없습니다. 아래에서 새로 만드세요.</div>';
  els.folderDialogList.querySelectorAll("[data-pick-folder]").forEach((button) => {
    button.addEventListener("click", async () => {
      dialog.close();
      await setBranchFolder(branch, button.dataset.pickFolder);
    });
  });
  if (els.folderDialogNewInput) els.folderDialogNewInput.value = "";
  els.folderDialogNewForm.onsubmit = async (event) => {
    event.preventDefault();
    const name = (els.folderDialogNewInput.value || "").trim();
    if (!name) return;
    dialog.close();
    await setBranchFolder(branch, name); // assigning auto-registers the folder
  };
  dialog.showModal();
}

function renderBranches() {
  if (els.contextChatButton) {
    els.contextChatButton.classList.toggle("active", state.activeContextChat === true);
    // Contexts chat also runs jobs, so surface its running/unread-done state here;
    // otherwise a finished contexts-chat turn adds to the tab's (N) badge with no
    // visible marker to attribute it to.
    const ctxJob = branchJob(CONTEXT_CHAT_KEY);
    const ctxRunning =
      Boolean(activeBranchRunningJob(CONTEXT_CHAT_KEY)) || Boolean(state.startingBranches[CONTEXT_CHAT_KEY]);
    const ctxDoneUnseen = ctxJob?.status === "done" && !isBranchJobAcknowledged(CONTEXT_CHAT_KEY);
    els.contextChatButton.classList.toggle("job-running", ctxRunning);
    els.contextChatButton.classList.toggle("job-done", !ctxRunning && ctxDoneUnseen);
    els.contextChatButton.classList.toggle(
      "job-failed",
      !ctxRunning && !ctxDoneUnseen && ctxJob?.status === "failed",
    );
  }
  renderMergeSourcePicker();
  const buildBranchRow = (branch) => {
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
          <button data-branch-folder="${escapeHtml(branch.id)}" data-branch-current-folder="${escapeHtml(branch.folder || "")}" type="button">Move to folder…</button>
          <button data-branch-clone="${escapeHtml(branch.id)}" type="button">Clone branch</button>
          <button data-branch-archive="${escapeHtml(branch.id)}" type="button">Archive branch</button>
          <button class="danger" data-branch-remove="${escapeHtml(branch.id)}" type="button">Remove branch</button>
        </div>
      </div>
    `;
  };

  // Branches keep one global sort (orderedBranches); folders just partition that
  // same ordered list, so within-folder order matches the ungrouped order.
  const ordered = orderedBranches();
  const folderOf = (branch) => (branch.folder || "").trim();
  const collapsed = getCollapsedFolders();
  const ungrouped = ordered.filter((branch) => !folderOf(branch));
  // Folders come from the registry (so empty folders show) unioned with any
  // folder a branch still references.
  const folderNames = [
    ...new Set([...(state.folders || []), ...ordered.map(folderOf).filter(Boolean)]),
  ].sort((a, b) => a.localeCompare(b));
  // Folders render ABOVE the ungrouped branches.
  let branchHtml = "";
  folderNames.forEach((folder) => {
    const items = ordered.filter((branch) => folderOf(branch) === folder);
    const isCollapsed = collapsed.includes(folder);
    // Collapsed: keep only the active branch visible (if it lives here), hide the
    // rest. Expanded: show all. The count badge always shows the full total.
    const visibleItems = isCollapsed
      ? items.filter((branch) => branch.id === state.activeBranch)
      : items;
    let body;
    if (!items.length) {
      body = '<div class="folder-empty muted">비어 있음 — 브랜치의 ⋯ → Move to folder</div>';
    } else if (visibleItems.length) {
      body = visibleItems.map(buildBranchRow).join("");
    } else {
      body = ""; // collapsed and the active branch is elsewhere → fully hidden
    }
    const hiddenCount = items.length - visibleItems.length;
    const countLabel = isCollapsed && hiddenCount > 0 ? `${visibleItems.length}/${items.length}` : `${items.length}`;
    branchHtml += `
      <div class="branch-folder ${isCollapsed ? "collapsed" : ""}">
        <div class="folder-header-row">
          <button class="folder-header" data-folder="${escapeHtml(folder)}" type="button" title="${escapeHtml(folder)}">
            <span class="folder-caret" aria-hidden="true">▾</span><span class="folder-name">${escapeHtml(folder)}</span><span class="folder-count">${countLabel}</span>
          </button>
          <button class="folder-delete" data-folder-delete="${escapeHtml(folder)}" type="button" title="폴더 삭제 (브랜치는 유지)" aria-label="Delete folder">✕</button>
        </div>
        <div class="folder-body">${body}</div>
      </div>
    `;
  });
  branchHtml += ungrouped.map(buildBranchRow).join("");
  els.branchList.innerHTML = branchHtml || '<div class="muted">No branches yet</div>';
  els.branchList.querySelectorAll("[data-folder]").forEach((button) => {
    button.addEventListener("click", () => toggleFolderCollapsed(button.dataset.folder));
  });
  els.branchList.querySelectorAll("[data-branch-folder]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeBranchMenus();
      openFolderPicker(button.dataset.branchFolder);
    });
  });
  els.branchList.querySelectorAll("[data-folder-delete]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteFolder(button.dataset.folderDelete);
    });
  });
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
  updateUnseenTabIndicator();
}

function renderGlobalizedList() {
  const archivedBranchMarkup = (state.archived || [])
    .map(
      (branch) => `
        <div class="archived-row">
          <button class="nav-item archived-main ${branch.id === state.activeBranch ? "active" : ""}" data-archived-branch="${escapeHtml(branch.id)}" type="button" title="${escapeHtml(`${branch.title || branch.id} (${branch.id})`)}">
            <span class="nav-title" title="${escapeHtml(branch.title || branch.id)}">${escapeHtml(branch.title || branch.id)}</span>
            <span class="nav-meta" title="${escapeHtml(`${branch.id} · ${branch.historyCount || 0} messages · archived branch`)}">${escapeHtml(branch.id)} · ${branch.historyCount || 0} messages · branch</span>
          </button>
          <button class="archived-restore" data-unarchive="${escapeHtml(branch.id)}" type="button" title="브랜치로 복구 (Branches로 되돌리기)" aria-label="Restore branch">↩</button>
        </div>
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
  els.globalizedList.querySelectorAll("[data-unarchive]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      unarchiveBranch(button.dataset.unarchive);
    });
  });
  els.globalizedList.querySelectorAll("[data-globalized]").forEach((button) => {
    button.addEventListener("click", () => loadGlobalizedArchive(button.dataset.globalized));
  });
}

async function unarchiveBranch(branch) {
  if (!branch) return;
  if (!window.confirm(`아카이브된 브랜치 "${branch}" 를 Branches로 복구할까요?`)) return;
  try {
    const payload = await api("/api/branch/unarchive", {
      method: "POST",
      body: JSON.stringify({ branch }),
    });
    state.branches = payload.branches || state.branches;
    state.folders = payload.folders || state.folders;
    state.archived = payload.archived || [];
    state.globalized = payload.globalized || [];
    state.views = payload.views || state.views;
    await loadBranch(branch); // open the restored branch (also refreshes the view)
  } catch (error) {
    window.alert(`복구 실패: ${error.message}`);
  }
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
  setBranchDirButton(null);
  els.activeMeta.textContent = "Simplified ctxgit lineage";
  els.branchGraphStatus.className = "settings-status";
  els.branchGraphStatus.textContent = "Loading graph...";
  const payload = await api("/api/branch-graph");
  renderBranchGraph(payload);
}

function closeBranchMenus() {
  document.querySelectorAll(".branch-row.open").forEach((row) => row.classList.remove("open"));
}

const ORCHESTRATION_STAGE_LABEL = {
  "team-plan": "Plan",
  "team-prd": "Acceptance criteria",
  "team-exec": "Execute",
  "team-verify": "Verify",
  "team-fix": "Fix",
  "sequence-reply": "Room reply",
};

const ORCH_EVENT_ICON = { tool: "⚙", text: "💬", result: "↩", delegate: "⇢" };

function orchestrationDuration(ms) {
  const value = Number(ms || 0);
  if (!Number.isFinite(value) || value <= 0) return "";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

function orchClock(ms) {
  const value = Number(ms || 0);
  if (!Number.isFinite(value) || value < 0) return "0.0s";
  return `${(value / 1000).toFixed(1)}s`;
}

// How many subagents were active at the same instant — the "did it run in parallel"
// number, computed from the [startAt, endAt] intervals.
function orchMaxConcurrency(subs) {
  const points = [];
  subs.forEach((s) => {
    points.push([Number(s.startAt) || 0, 1]);
    points.push([Number(s.endAt) || 0, -1]);
  });
  points.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let current = 0;
  let max = 0;
  points.forEach(([, delta]) => {
    current += delta;
    max = Math.max(max, current);
  });
  return max;
}

function renderOrchSubagentLane(sub, total, index) {
  const start = Math.max(0, Number(sub.startAt) || 0);
  const end = Math.max(start, Number(sub.endAt) || start);
  const left = total > 0 ? (start / total) * 100 : 0;
  const width = total > 0 ? Math.max(1.5, ((end - start) / total) * 100) : 100;
  const dur = orchestrationDuration(sub.durationMs);
  const events = Array.isArray(sub.events) ? sub.events : [];
  const detail = events
    .map(
      (e) =>
        `<div class="orch-ev orch-ev-${escapeHtml(e.kind || "")}"><span class="orch-ev-t">${orchClock(e.at)}</span><span class="orch-ev-i">${ORCH_EVENT_ICON[e.kind] || "·"}</span><span class="orch-ev-l">${escapeHtml(e.label || "")}</span></div>`,
    )
    .join("");
  return `
    <div class="orch-lane" style="--lane: ${index};">
      <div class="orch-lane-label" title="${escapeHtml(sub.brief || "")}">
        <span class="orch-lane-name">${escapeHtml(sub.type || "subagent")}</span>
        ${dur ? `<span class="orch-lane-dur">${escapeHtml(dur)}</span>` : ""}
      </div>
      <div class="orch-lane-track">
        <div class="orch-bar" style="left:${left}%;width:${width}%;" title="${escapeHtml(sub.brief || "")} · ${escapeHtml(orchClock(start))}→${escapeHtml(orchClock(end))}"></div>
      </div>
      <details class="orch-lane-detail">
        <summary>${escapeHtml(sub.brief || sub.type || "details")} · ${events.length} step(s)</summary>
        <div class="orch-ev-list">${detail || '<div class="muted">no recorded steps</div>'}</div>
        ${sub.summary ? `<div class="orch-ev-summary"><span class="orch-task-label">returned</span><pre>${escapeHtml(sub.summary)}</pre></div>` : ""}
      </details>
    </div>
  `;
}

function renderOrchTimeline(timeline) {
  const subs = Array.isArray(timeline.subagents) ? timeline.subagents : [];
  const total = Number(timeline.totalMs) || subs.reduce((m, s) => Math.max(m, Number(s.endAt) || 0), 0);
  if (!subs.length) return "";
  const ticks = [0, 0.25, 0.5, 0.75, 1]
    .map((f) => `<span class="orch-tick" style="left:${f * 100}%;">${orchClock(f * total)}</span>`)
    .join("");
  const lanes = subs.map((sub, i) => renderOrchSubagentLane(sub, total, i)).join("");
  return `
    <div class="orch-timeline">
      <div class="orch-ruler"><div class="orch-ruler-track">${ticks}</div></div>
      ${lanes}
    </div>
  `;
}

function renderOrchestrationEntry(entry) {
  const stage = ORCHESTRATION_STAGE_LABEL[entry.stage] || entry.stage || entry.kind;
  const meta = entry.meta || {};
  const badges = [];
  if (entry.model) badges.push(entry.model);
  if (meta.isEvaluator) badges.push("evaluator");
  if (meta.writable === false) badges.push("read-only");
  if (meta.failed) badges.push("failed");
  const duration = orchestrationDuration(entry.duration_ms);
  const isDelegation = entry.kind === "delegation";
  const laneTimeline =
    meta.timeline && Array.isArray(meta.timeline.subagents) && meta.timeline.subagents.length
      ? `<div class="orch-entry-timeline"><div class="orch-entry-tl-label">delegated ${meta.timeline.subagents.length} subagent(s)${orchMaxConcurrency(meta.timeline.subagents) > 1 ? ` · up to ${orchMaxConcurrency(meta.timeline.subagents)} in parallel` : ""}</div>${renderOrchTimeline(meta.timeline)}</div>`
      : "";
  return `
    <li class="orch-entry ${isDelegation ? "orch-delegation" : ""} ${meta.failed ? "orch-failed" : ""}">
      <div class="orch-entry-head">
        <span class="orch-seq">${entry.seq}</span>
        <span class="orch-role">${escapeHtml(entry.role || "agent")}</span>
        <span class="orch-stage">${escapeHtml(isDelegation ? "delegated" : stage)}</span>
        ${badges.map((item) => `<span class="orch-badge">${escapeHtml(item)}</span>`).join("")}
        ${duration ? `<span class="orch-duration">${escapeHtml(duration)}</span>` : ""}
      </div>
      ${laneTimeline}
      ${
        entry.prompt
          ? `<details class="orch-block"><summary>asked</summary><pre>${escapeHtml(entry.prompt)}</pre></details>`
          : ""
      }
      ${
        entry.reply
          ? `<details class="orch-block" open><summary>answered</summary><pre>${escapeHtml(entry.reply)}</pre></details>`
          : ""
      }
    </li>
  `;
}

async function showOrchestrationLog(turnId) {
  const branch = activeChatKey();
  if (!branch || !turnId) return;
  els.orchestrationTitle.textContent = "Orchestration";
  els.orchestrationSubtitle.textContent = "Loading…";
  els.orchestrationBody.innerHTML = "";
  if (!els.orchestrationDialog.open) els.orchestrationDialog.showModal();
  try {
    const log = await api(
      `/api/orchestration?branch=${encodeURIComponent(branch)}&turn=${encodeURIComponent(turnId)}`,
    );
    els.orchestrationTitle.textContent = `Orchestration · ${log.mode || "turn"}`;
    const goal = log.task
      ? `<div class="orch-task"><span class="orch-task-label">Goal</span><pre>${escapeHtml(log.task)}</pre></div>`
      : "";

    if (log.timeline && Array.isArray(log.timeline.subagents) && log.timeline.subagents.length) {
      // Chat turn: one lead fanning out to subagents on a shared time axis.
      const subs = log.timeline.subagents;
      const concurrency = orchMaxConcurrency(subs);
      els.orchestrationSubtitle.textContent =
        `${subs.length} subagent(s) · ${orchClock(log.timeline.totalMs)} wall clock · ` +
        (concurrency > 1 ? `up to ${concurrency} ran in parallel` : "ran one at a time");
      els.orchestrationBody.innerHTML = `${goal}${renderOrchTimeline(log.timeline)}`;
    } else {
      // Team pipeline / sequence room: an ordered list of stages, each of which may
      // carry its own subagent timeline.
      const entries = Array.isArray(log.entries) ? log.entries : [];
      const stages = entries.filter((item) => item.kind === "stage").length;
      const delegations = entries.filter((item) => item.kind === "delegation").length;
      const total = entries.reduce((sum, item) => sum + Number(item.duration_ms || 0), 0);
      els.orchestrationSubtitle.textContent =
        `${entries.length} step(s) · ${stages} stage(s)` +
        (delegations ? ` · ${delegations} delegation(s)` : "") +
        (total ? ` · ${orchestrationDuration(total)} of agent time` : "");
      els.orchestrationBody.innerHTML = `${goal}<ol class="orch-list">${entries
        .map(renderOrchestrationEntry)
        .join("")}</ol>`;
    }
  } catch (error) {
    els.orchestrationSubtitle.textContent = "";
    els.orchestrationBody.innerHTML = `<div class="muted">기록을 불러오지 못했습니다: ${escapeHtml(error.message)}</div>`;
  }
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

function setMergePickerOpen(open) {
  state.mergePickerOpen = Boolean(open);
  els.mergeSourceDropdown.hidden = !state.mergePickerOpen;
  els.mergeSourceToggle.setAttribute("aria-expanded", String(state.mergePickerOpen));
  if (state.mergePickerOpen) {
    renderMergeSourcePicker();
    window.requestAnimationFrame(() => {
      const rect = els.mergeSourceToggle.getBoundingClientRect();
      const below = Math.max(180, window.innerHeight - rect.bottom - 12);
      const above = Math.max(180, rect.top - 12);
      const openUpward = below < 300 && above > below;
      const available = openUpward ? above : below;
      els.mergeSourcePicker.classList.toggle("open-upward", openUpward);
      els.mergeSourceDropdown.style.setProperty("--merge-dropdown-space", `${available}px`);
      els.mergeSourceFilter.focus();
    });
  } else {
    els.mergeSourcePicker.classList.remove("open-upward");
  }
}

function setSequenceOrderOpen(open) {
  state.sequenceOrderOpen = Boolean(open);
  els.sequenceOrderDropdown.hidden = !state.sequenceOrderOpen;
  els.sequenceOrderButton.setAttribute("aria-expanded", String(state.sequenceOrderOpen));
}

function sequenceParticipants() {
  return Array.isArray(state.payload?.sequenceRoom?.participants)
    ? state.payload.sequenceRoom.participants
    : [];
}

function renderSequenceOrderPicker() {
  const participants = sequenceParticipants();
  const available = new Set(participants.map((item) => Number(item.order)));
  state.sequenceOrder = state.sequenceOrder.filter((order) => available.has(Number(order)));
  if (!state.sequenceOrder.length && participants.length) {
    state.sequenceOrder = participants.map((item) => Number(item.order));
  }
  if (!state.sequenceOrder.includes(Number(state.sequenceEvaluator))) {
    state.sequenceEvaluator = null;
  }
  const evaluatorLabel = state.sequenceEvaluator ? ` · Eval ${state.sequenceEvaluator}` : " · No evaluator";
  els.sequenceOrderButton.textContent = `Order ${state.sequenceOrder.join(" → ")}${evaluatorLabel}`;
  els.sequenceOrderSelected.innerHTML = state.sequenceOrder
    .map((order, index) => {
      const participant = participants.find((item) => Number(item.order) === Number(order));
      return `
        <div class="merge-selected-item">
          <span class="merge-selected-number">${index + 1}</span>
          <span>Agent ${order} · ${escapeHtml(participant?.title || participant?.sourceBranch || "")}${state.sequenceEvaluator === order ? " · evaluator" : ""}</span>
          <button class="merge-selected-remove" data-sequence-order-toggle="${order}" type="button">×</button>
        </div>
      `;
    })
    .join("");
  els.sequenceOrderOptions.innerHTML = participants
    .map((participant) => {
      const order = Number(participant.order);
      const selectedIndex = state.sequenceOrder.indexOf(order);
      return `
        <div class="sequence-order-option ${selectedIndex >= 0 ? "selected" : ""}">
          <button class="sequence-order-speak" data-sequence-order-toggle="${order}" type="button">
            <span class="merge-option-order ${selectedIndex >= 0 ? "" : "empty"}">${selectedIndex >= 0 ? selectedIndex + 1 : "+"}</span>
            <span class="merge-option-label">
              <strong>Agent ${order} · ${escapeHtml(participant.title || participant.sourceBranch || "")}</strong>
              <small>${escapeHtml(participant.sourceBranch || "")}</small>
            </span>
          </button>
          <button
            class="sequence-evaluator-toggle ${state.sequenceEvaluator === order ? "active" : ""}"
            data-sequence-evaluator-toggle="${order}"
            type="button"
            ${selectedIndex < 0 ? "disabled" : ""}
          >${state.sequenceEvaluator === order ? "Evaluator" : "Set evaluator"}</button>
        </div>
      `;
    })
    .join("");
  els.sequenceOrderDropdown.querySelectorAll("[data-sequence-order-toggle]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const order = Number(button.dataset.sequenceOrderToggle);
      const index = state.sequenceOrder.indexOf(order);
      if (index >= 0) {
        if (state.sequenceOrder.length === 1) {
          els.sequenceOrderStatus.textContent = "At least one agent must speak.";
          els.sequenceOrderStatus.className = "settings-status error";
          return;
        }
        state.sequenceOrder.splice(index, 1);
        if (state.sequenceEvaluator === order) state.sequenceEvaluator = null;
      } else {
        state.sequenceOrder.push(order);
      }
      renderSequenceOrderPicker();
      await saveSequenceOrder();
    });
  });
  els.sequenceOrderDropdown.querySelectorAll("[data-sequence-evaluator-toggle]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const order = Number(button.dataset.sequenceEvaluatorToggle);
      state.sequenceEvaluator = state.sequenceEvaluator === order ? null : order;
      renderSequenceOrderPicker();
      await saveSequenceOrder();
    });
  });
}

async function saveSequenceOrder() {
  try {
    const payload = await api("/api/sequence-room/order", {
      method: "POST",
      body: JSON.stringify({
        branch: state.activeBranch,
        speakingOrder: state.sequenceOrder,
        evaluatorOrder: state.sequenceEvaluator,
      }),
    });
    state.payload = payload;
    els.sequenceOrderStatus.textContent = "Order saved.";
    els.sequenceOrderStatus.className = "settings-status ok";
  } catch (error) {
    els.sequenceOrderStatus.textContent = `Order failed: ${error.message}`;
    els.sequenceOrderStatus.className = "settings-status error";
  }
}

function toggleMergeBranch(branchId) {
  const index = state.mergeSelectedBranches.indexOf(branchId);
  if (index >= 0) {
    state.mergeSelectedBranches.splice(index, 1);
  } else {
    state.mergeSelectedBranches.push(branchId);
  }
  renderMergeSourcePicker();
}

function renderMergeSourcePicker() {
  const available = new Set(state.branches.map((branch) => branch.id));
  state.mergeSelectedBranches = state.mergeSelectedBranches.filter((branchId) => available.has(branchId));
  const selectedCount = state.mergeSelectedBranches.length;
  els.mergeSourceCount.textContent = String(selectedCount);
  els.mergeSourceToggleLabel.textContent =
    selectedCount > 0 ? `${selectedCount} branch${selectedCount === 1 ? "" : "es"} selected` : "Select branches";

  els.mergeSelectedOrder.innerHTML = state.mergeSelectedBranches
    .map(
      (branchId, index) => `
        <div class="merge-selected-item">
          <span class="merge-selected-number">${index + 1}</span>
          <span title="${escapeHtml(`${branchTitle(branchId)} (${branchId})`)}">${escapeHtml(branchTitle(branchId))}</span>
          <button class="merge-selected-remove" data-merge-remove="${escapeHtml(branchId)}" type="button" aria-label="Remove ${escapeHtml(branchTitle(branchId))}">×</button>
        </div>
      `,
    )
    .join("");

  const filter = els.mergeSourceFilter.value.trim().toLowerCase();
  const candidates = orderedBranches().filter((branch) => {
    if (!filter) return true;
    return branch.id.toLowerCase().includes(filter) || String(branch.title || "").toLowerCase().includes(filter);
  });
  els.mergeSourceOptions.innerHTML =
    candidates
      .map((branch) => {
        const selectedIndex = state.mergeSelectedBranches.indexOf(branch.id);
        const selected = selectedIndex >= 0;
        return `
          <button class="merge-source-option ${selected ? "selected" : ""}" data-merge-source="${escapeHtml(branch.id)}" type="button">
            <span class="merge-option-order ${selected ? "" : "empty"}">${selected ? selectedIndex + 1 : "+"}</span>
            <span class="merge-option-label">
              <span class="merge-option-title">${escapeHtml(branch.title || branch.id)}</span>
              <span class="merge-option-id">${escapeHtml(branch.id)}</span>
            </span>
          </button>
        `;
      })
      .join("") || '<div class="muted">No matching branches.</div>';

  els.mergeSelectedOrder.querySelectorAll("[data-merge-remove]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleMergeBranch(button.dataset.mergeRemove);
    });
  });
  els.mergeSourceOptions.querySelectorAll("[data-merge-source]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleMergeBranch(button.dataset.mergeSource);
    });
  });
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
  if (status.initialized === false) {
    els.gitSummary.innerHTML = `
      <div>Outer Git: <strong>not initialized</strong></div>
      <div class="muted">ctxgit Git: ${escapeHtml(String(internal.dirtyCount || 0))} pending | ${escapeHtml(internal.gitDir || "")}</div>
    `;
    if (els.internalGitLog) {
      const refs = (internal.refs || [])
        .slice(0, 20)
        .map((item) => `${item.short || ""} ${item.ref || ""} ${item.subject || ""}`.trim())
        .join("\n");
      els.internalGitLog.textContent =
        [internal.log || "No internal ctxgit commits yet.", refs ? `\nRefs:\n${refs}` : ""].filter(Boolean).join("\n");
    }
    return;
  }
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
  const orchestration = status.orchestration === "omc" ? "omc" : "legacy";
  const timeoutSeconds = status.timeoutSeconds || 900;
  const sandbox = status.sandbox || "workspace-write";
  const model = status.model || "";
  const braveStatus = status.braveApiKeyConfigured
    ? `configured via ${status.braveApiKeySource || "environment"}`
    : "not configured";
  const providers = Array.isArray(status.providers) ? status.providers : [];
  if (providers.length) {
    els.providerInput.innerHTML = providers
      .map(
        (item) =>
          `<option value="${escapeHtml(item.id)}" ${item.installed ? "" : "disabled"}>${escapeHtml(item.label)}${item.ok ? " · ready" : item.installed ? " · login required" : " · not installed"}</option>`,
      )
      .join("");
  }
  const selectedProvider = providers.find((item) => item.id === (status.provider || "codex"));
  const modelOptions = Array.isArray(selectedProvider?.models) ? selectedProvider.models : [];
  els.providerModelInput.innerHTML = modelOptions
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
    .join("");
  els.providerSummary.innerHTML = `
    <div>Provider: <strong>${escapeHtml(status.provider || "codex")}</strong></div>
    <div class="muted">Model: ${escapeHtml(model || "provider default")}</div>
    <div>${escapeHtml(status.message || status.status || "")}</div>
    <div class="muted">Web search: ${webSearch} · Orchestration: ${orchestration} · Timeout: ${escapeHtml(String(timeoutSeconds))}s</div>
    <div class="muted">Brave search: ${escapeHtml(braveStatus)}</div>
    <div class="muted">Sandbox: ${escapeHtml(sandbox)}</div>
    <div class="muted">External writes: approval required</div>
    ${providers
      .map(
        (item) =>
          `<div class="muted">${escapeHtml(item.label)}: ${item.ok ? "ready" : escapeHtml(item.status || "unavailable")}${item.id === "claude" ? " · OAuth/session auth" : ""}</div>`,
      )
      .join("")}
    ${
      status.ok
        ? ""
        : `<div class="muted">Login: <code>${escapeHtml(status.loginCommand || "codex login --device-auth")}</code></div>`
    }
  `;
  els.webSearchInput.checked = webSearch === "on";
  els.orchestrationInput.value = orchestration;
  els.providerInput.value = status.provider || "codex";
  els.providerModelInput.value = model;
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

function renderMessageResources(resources) {
  if (!Array.isArray(resources) || resources.length === 0) return "";
  const paths = resources.map((item) => String(item || "").trim()).filter(Boolean);
  if (!paths.length) return "";
  return `
    <div class="message-resources">
      <span class="message-resources-label">Attachments</span>
      ${paths
        .map((path) => renderProjectFileLink(path, `<code>${escapeHtml(path)}</code>`))
        .join("")}
    </div>
  `;
}

function renderProviderModelOptions(providerId) {
  const provider = (state.provider?.providers || []).find((item) => item.id === providerId);
  const models = Array.isArray(provider?.models) ? provider.models : [];
  els.providerModelInput.innerHTML = models
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
    .join("");
  els.providerModelInput.value = provider?.model || models[0]?.id || "";
}

function renderSequenceEvaluation(message) {
  const evaluation = message?.sequenceEvaluation;
  if (!evaluation) return "";
  const required = Array.isArray(evaluation.requiredChanges) ? evaluation.requiredChanges : [];
  const criteria = Array.isArray(evaluation.criteria) ? evaluation.criteria : [];
  const valid = message.sequenceEvaluationValid !== false;
  const decision = valid ? evaluation.decision || "continue" : "invalid · continue";
  return `
    <details class="sequence-evaluation">
      <summary>Evaluation ${escapeHtml(String(message.sequenceEvaluatorRound || ""))}: ${escapeHtml(decision)}</summary>
      ${
        required.length
          ? `<div><strong>Required changes</strong><ul>${required.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`
          : "<div>No required changes.</div>"
      }
      <ul class="sequence-criteria">
        ${criteria
          .map(
            (item) =>
              `<li class="${item.passed ? "passed" : "failed"}">${item.passed ? "Pass" : "Fail"} · ${escapeHtml(item.name || "")}${item.evidence ? ` — ${escapeHtml(item.evidence)}` : ""}</li>`,
          )
          .join("")}
      </ul>
    </details>
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

function setEventPanelVisible(visible, { persist = true } = {}) {
  state.eventsVisible = Boolean(visible);
  els.chatTab.classList.toggle("event-visible", state.eventsVisible);
  els.eventPanelToggle.setAttribute("aria-pressed", String(state.eventsVisible));
  els.eventPanelToggle.textContent = state.eventsVisible ? "Hide events" : "Events";
  if (persist) {
    try {
      localStorage.setItem(EVENT_PANEL_STORAGE_KEY, state.eventsVisible ? "1" : "0");
    } catch {
      // Storage may be unavailable in private or locked-down contexts.
    }
  }
}

function restoreEventPanelVisibility() {
  let visible = false;
  try {
    visible = localStorage.getItem(EVENT_PANEL_STORAGE_KEY) === "1";
  } catch {
    visible = false;
  }
  setEventPanelVisible(visible, { persist: false });
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
  if (activeChatKey() !== branch) return "";
  const pendingId = `pending-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const historyCount = Array.isArray(state.payload?.history) ? state.payload.history.length : 0;
  const number = historyCount + els.messageList.querySelectorAll(".message.pending-message").length + 1;
  if (els.messageList.querySelector(".muted")) {
    replaceMessageListHtml("");
  }
  appendMessageListHtml(
    `
      <article class="message message-user pending-message" data-pending-message="${escapeHtml(pendingId)}">
        <div class="message-header">
          <span class="message-role">user</span>
          <span class="message-meta-actions">
            <span class="message-number">${number}</span>
            <span>${escapeHtml(new Date().toISOString())}</span>
            <span class="pending-label">${escapeHtml(mode === "research" ? "research queued" : mode === "info-chat" ? "info queued" : mode === "context-chat" ? "context queued" : "sending")}</span>
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

function branchJob(branch = activeChatKey()) {
  const jobId = branch ? state.branchJobs[branch] : "";
  return jobId ? state.jobs[jobId] : null;
}

function activeBranchRunningJob(branch = activeChatKey()) {
  const job = branchJob(branch);
  return job?.status === "running" ? job : null;
}

async function interjectSequenceRoom(branch, job) {
  const text = els.messageInput.value.trim();
  if (!text) return;
  hideChatError();
  const runMode = String(job.mode || "").includes("info") ? "info-chat" : "send";
  try {
    const payload = await api("/api/sequence-room/interject", {
      method: "POST",
      body: JSON.stringify({ branch, id: job.id, text, runMode }),
    });
    clearDraft(branch);
    els.messageInput.value = "";
    resizeMessageInput();
    if (activeChatKey() === branch) {
      renderBranch(payload);
      updateComposerState();
      scrollChatToBottom();
    }
  } catch (error) {
    if (activeChatKey() === branch) {
      showChatError(`개입 실패: ${error.message}`);
    } else {
      window.alert(`개입 실패 on ${branch}: ${error.message}`);
    }
  }
}

async function refreshSequenceRoomProgress(job) {
  if (!job?.id || !String(job.mode || job.kind || "").startsWith("sequence-room")) return;
  const savedReplies = (job.events || []).reduce((highest, event) => {
    const match = String(event?.message || "").match(/^Sequence reply (\d+) saved$/);
    return match ? Math.max(highest, Number(match[1])) : highest;
  }, 0);
  if (!savedReplies || savedReplies <= (state.sequenceRenderedReplies[job.id] || 0)) return;
  state.sequenceRenderedReplies[job.id] = savedReplies;
  if (activeChatKey() !== job.branch) return;
  try {
    const payload = await api(`/api/branch?id=${encodeURIComponent(job.branch)}`);
    if (activeChatKey() === job.branch) {
      renderBranch(payload);
      updateComposerState();
      scrollChatToBottom();
    }
  } catch {
    // The next job poll or final payload will retry rendering.
  }
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
  const activeKey = activeChatKey();
  const running = activeBranchRunningJob(activeKey);
  const startingMode = activeKey ? state.startingBranches[activeKey] : "";
  const archived = state.payload?.archived === true;
  const contextMode = state.activeContextChat === true;
  const disabled = !activeKey || archived || Boolean(startingMode);
  els.composer.classList.toggle("context-mode", contextMode);
  els.contextResetButton.hidden = !contextMode;
  els.historyChatButton.hidden = contextMode;
  els.sendButton.disabled = disabled;
  els.contextResetButton.disabled = !contextMode || !activeKey || Boolean(running) || Boolean(startingMode);
  els.historyChatButton.disabled = disabled;
  els.sequenceRoomUpdateButton.disabled = disabled || Boolean(running);
  const busyMode = running?.mode || startingMode;
  const isSequenceRoom = state.payload?.meta?.kind === "sequence-room";
  els.sendButton.textContent = archived
    ? "Archived"
    : running
      ? isSequenceRoom
        ? "Interrupt"
        : "Stop"
      : "Send";
  els.contextResetButton.textContent = busyMode === "context-chat" ? "Busy" : "Reset";
  els.historyChatButton.textContent = archived
    ? "Archived"
    : running
      ? "Stop"
      : "Info chat";
  const claudeProvider = (state.provider?.provider || "codex") === "claude";
  const omcMode = state.provider?.orchestration === "omc";
  els.teamButton.hidden = contextMode || !omcMode;
  els.teamButton.disabled = disabled || Boolean(running) || !claudeProvider;
  els.teamButton.textContent = archived ? "Archived" : running ? "Busy" : "Team";
  els.teamButton.title = claudeProvider
    ? "Run the deterministic team pipeline: plan → prd → exec → verify → fix"
    : "Team pipeline requires the Claude provider";
  if (els.guestButton) {
    els.guestButton.hidden = contextMode || isSequenceRoom;
    els.guestButton.disabled = disabled || Boolean(running);
    els.guestButton.textContent = archived ? "Archived" : running ? "Busy" : "Guest";
  }
  // Persistent guest chip: shown until the guest is explicitly removed.
  const guest = !contextMode && !isSequenceRoom ? state.payload?.meta?.guest : null;
  if (els.guestChip) {
    if (guest && guest.active) {
      els.guestChip.hidden = false;
      els.guestChip.innerHTML = `<span class="guest-chip-label">🎙 게스트 참여 중${
        guest.provider ? ` · ${escapeHtml(guest.provider)}` : ""
      }</span><button type="button" class="guest-chip-remove" id="guestChipRemove" title="이 브랜치에서 게스트 내보내기">✕ 내보내기</button>`;
      els.guestChip.querySelector("#guestChipRemove")?.addEventListener("click", removeGuest);
    } else {
      els.guestChip.hidden = true;
      els.guestChip.innerHTML = "";
    }
  }
}

async function removeGuest() {
  const branch = state.activeBranch;
  if (!branch) return;
  try {
    const payload = await api("/api/branch/guest/remove", {
      method: "POST",
      body: JSON.stringify({ branch }),
    });
    if (state.activeBranch === branch) renderBranch(payload);
  } catch (error) {
    window.alert(`게스트 내보내기 실패: ${error.message}`);
  }
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
  state.folders = data.folders || [];
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
  if (activeChatKey() === branch) {
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

async function cancelTrackedJob(job) {
  if (!job?.id || job.status !== "running") return;
  const canceled = await api("/api/job/cancel", {
    method: "POST",
    body: JSON.stringify({ id: job.id }),
  });
  rememberJob(canceled, { branch: job.branch, mode: job.mode });
  if (activeChatKey() === job.branch) {
    renderEventPanel(canceled);
    hideProgress();
    updateComposerState();
  }
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
  if (activeChatKey() === failed.branch) {
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
        if (activeChatKey() === branch) {
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
    const isActiveChat = activeChatKey() === branch;
    if (isActiveChat) {
      updateProgress(remembered);
      renderEventPanel(remembered);
      updateComposerState();
      await refreshSequenceRoomProgress(remembered);
    }
    if (remembered.status === "done") {
      // Do not auto-clear the "done" indicator just because this branch is open;
      // it clears only when the user engages the input (focuses it). See below.
      await refreshBranchNavigation().catch(() => {});
      if (activeChatKey() === branch) {
        if (remembered.mode === "context-chat" || remembered.payload?.topLevel === true) {
          renderContextChat(remembered.payload);
        } else {
          renderBranch(remembered.payload);
        }
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
      if (activeChatKey() === branch) {
        const prefix =
          remembered.error === "timeout"
            ? "시간 초과"
            : remembered.error === "job_not_found"
              ? "중단됨"
              : remembered.mode === "research"
                ? "리서치 실패"
                : remembered.mode === "merge"
                  ? "머지 실패"
                  : remembered.mode === "context-chat"
                    ? "컨텍스트 챗 실패"
                    : "채팅 실패";
        const errorText = `${prefix}: ${remembered.message || "작업 실패"}`;
        showChatError(errorText);
        hideProgress();
        // Re-render from history so the unanswered message shows in red with
        // one-click resend/delete (the pending bubble is replaced by the real one).
        // renderBranch clears the error banner, so re-show it afterwards.
        if (remembered.mode !== "context-chat" && remembered.mode !== "merge" && state.activeBranch === branch) {
          api(`/api/branch?id=${encodeURIComponent(branch)}`)
            .then((payload) => {
              if (state.activeBranch === branch && !state.activeContextChat) {
                renderBranch(payload);
                showChatError(errorText);
              }
            })
            .catch(() => {});
        }
      }
      updateComposerState();
      loadWorkerStatus().catch(() => {});
      return;
    }
    if (remembered.status === "canceled") {
      renderBranches();
      if (activeChatKey() === branch) {
        hideProgress();
        hideChatError();
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
  const sequenceRoom = payload.meta?.kind === "sequence-room";
  els.sequenceRoomUpdateButton.hidden = !sequenceRoom;
  els.sequenceOrderPicker.hidden = !sequenceRoom;
  if (els.sequenceNotifyToggle) {
    els.sequenceNotifyToggle.hidden = !sequenceRoom;
    els.sequenceNotifyToggle.setAttribute(
      "aria-pressed",
      String(sequenceRoom && payload.sequenceRoom?.notifyEachReply === true),
    );
  }
  setSequenceOrderOpen(false);
  if (sequenceRoom) {
    const configuredOrder = Array.isArray(payload.sequenceRoom?.speakingOrder)
      ? payload.sequenceRoom.speakingOrder
      : (payload.sequenceRoom?.participants || []).map((item) => item.order);
    state.sequenceOrder = configuredOrder.map(Number);
    state.sequenceEvaluator =
      payload.sequenceRoom?.stopDecider == null ? null : Number(payload.sequenceRoom.stopDecider);
    renderSequenceOrderPicker();
  } else {
    state.sequenceOrder = [];
    state.sequenceEvaluator = null;
  }
  els.activeTitle.textContent = meta.title || meta.id;
  setBranchDirButton(meta.id);
  setBranchParentButton(meta);
  els.activeMeta.textContent = archived
    ? `${meta.id} · archived branch · read only`
    : `${meta.id} · history.jsonl is Git-tracked conversation history`;

  // A turn that got no answer leaves a trailing user message with no reply and no
  // running job. Flag it so the user can resend or delete it in one click.
  const branchBusy = Boolean(activeBranchRunningJob(meta.id)) || Boolean(state.startingBranches[meta.id]);
  const failedUserIndex =
    !archived &&
    !sequenceRoom &&
    !branchBusy &&
    payload.history.length > 0 &&
    payload.history[payload.history.length - 1].role === "user"
      ? payload.history.length - 1
      : -1;
  replaceMessageListHtml(
    payload.history
      .map(
        (message, index) => `
          <article class="message message-${escapeHtml(message.role)}${message.mode === "guest" ? " message-guest" : ""}${index === failedUserIndex ? " message-failed" : ""}" data-history-message="${index}">
            <div class="message-header">
              <span class="message-role">${
                message.mode === "guest"
                  ? `🎙 ${escapeHtml("Guest")}${message.provider ? ` · ${escapeHtml(message.provider)}` : ""}`
                  : escapeHtml(
                      message.sequenceSpeaker
                        ? `Agent ${message.sequenceSpeaker.order} · ${message.sequenceSpeaker.title || message.sequenceSpeaker.sourceBranch}`
                        : message.role,
                    )
              }</span>
                <span class="message-meta-actions">
                  <span class="message-number">${index + 1}</span>
                  <span>${escapeHtml(message.createdAt)}</span>
                  ${
                    message.orchestrationLog
                      ? `<button
                            class="orchestration-button"
                            data-orchestration-turn="${escapeHtml(message.turnId || "")}"
                            type="button"
                            title="Show how the agents produced this"
                            aria-label="Show orchestration"
                          >⛓ agents</button>`
                      : ""
                  }
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
                              data-history-fork-context="${index}"
                              data-history-created-at="${escapeHtml(message.createdAt || "")}"
                              data-history-role="${escapeHtml(message.role || "")}"
                              type="button"
                            >Fork context</button>
                            <button
                              data-history-revise="${index}"
                              data-history-created-at="${escapeHtml(message.createdAt || "")}"
                              data-history-role="${escapeHtml(message.role || "")}"
                              type="button"
                            >Revise message</button>
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
            ${
              index === failedUserIndex
                ? `<div class="message-failed-actions">
                    <span class="message-failed-note">답이 오지 않았습니다</span>
                    <button class="message-failed-resend" data-failed-resend="${index}" type="button">↻ 재전송</button>
                    <button
                      class="message-failed-delete danger"
                      data-failed-delete="${index}"
                      data-history-created-at="${escapeHtml(message.createdAt || "")}"
                      data-history-role="${escapeHtml(message.role || "")}"
                      type="button"
                    >🗑 삭제</button>
                  </div>`
                : ""
            }
            ${renderSequenceEvaluation(message)}
            ${renderMessageResources(message.resources)}
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
  els.messageList.querySelectorAll("[data-orchestration-turn]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      showOrchestrationLog(button.dataset.orchestrationTurn || "");
    });
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
  els.messageList.querySelectorAll("[data-history-fork-context]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMessageMenus();
      forkHistoryMessage(button, { contextOnly: true });
    });
  });
  els.messageList.querySelectorAll("[data-history-revise]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMessageMenus();
      beginReviseHistoryMessage(button);
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
  els.messageList.querySelectorAll("[data-failed-resend]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      resendFailedMessage(Number.parseInt(button.dataset.failedResend || "", 10));
    });
  });
  els.messageList.querySelectorAll("[data-failed-delete]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteFailedMessage(button);
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
      ...(payload.resources || []).map((resource) => ({
        title: resource.title || "resource",
        path: resource.path || "",
        status: resource.status || "resource",
      })),
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
  renderSummaries(payload.compactions || []);
  renderBranchResourceStage();
  restoreActiveDraft();
  updateComposerState();
}

function renderContextChat(payload) {
  hideChatError();
  state.payload = payload;
  const meta = payload.meta || {};
  els.activeTitle.textContent = meta.title || "Contexts";
  setBranchDirButton(null);
  if (els.contextBranchButton) els.contextBranchButton.hidden = false;
  els.activeMeta.textContent = `${meta.id || "contexts"} · top-level contexts chat`;

  replaceMessageListHtml(
    (payload.history || [])
      .map(
        (message, index) => `
          <article class="message message-${escapeHtml(message.role)}">
            <div class="message-header">
              <span class="message-role">${escapeHtml(message.role)}</span>
              <span class="message-meta-actions">
                <span class="message-number">${index + 1}</span>
                <span>${escapeHtml(message.createdAt)}</span>
              </span>
            </div>
            <div class="message-text">${renderMessageText(message.text)}</div>
          </article>
        `,
      )
      .join("") || '<div class="muted">No top-level context messages yet.</div>',
  );
  scrollChatToBottom();

  els.reportView.innerHTML = renderMarkdown(payload.context || "");
  els.trackedFiles.innerHTML = `
    <dt>contexts</dt><dd>${escapeHtml(payload.paths?.root || "contexts")}</dd>
    <dt>history</dt><dd>${escapeHtml(payload.paths?.history || "contexts/history.jsonl")}</dd>
    <dt>ctxgit ref</dt><dd>${escapeHtml(payload.git?.internal?.ref || "")}</dd>
    <dt>ctxgit head</dt><dd>${escapeHtml(payload.git?.internal?.head || "")}</dd>
  `;
  els.historyLog.textContent =
    payload.git?.internal?.log || payload.git?.historyLog || "No internal ctxgit commits for contexts chat yet.";
  els.currentDiff.textContent =
    [payload.git?.status, payload.git?.historyDiff].filter(Boolean).join("\n\n") ||
    "No uncommitted contexts chat diff.";
  if (els.internalGitLog) {
    els.internalGitLog.textContent = payload.git?.internal?.log || "No internal ctxgit commits for contexts chat yet.";
  }
  els.researchList.innerHTML = '<div class="muted">Top-level context chat has no branch documents.</div>';
  renderArchives([]);
  renderSummaries([]);
  renderBranchResourceStage();
  restoreActiveDraft();
  updateComposerState();
}

function setSummaryStatus(message, kind = "") {
  if (!els.summaryStatus) return;
  els.summaryStatus.textContent = message;
  els.summaryStatus.className = `settings-status ${kind}`.trim();
}

function renderSummaries(compactions) {
  if (!els.summaryList) return;
  const summaries = Array.isArray(compactions) ? compactions : [];
  const hasActive = summaries.some((item) => item.path === state.activeSummaryPath);
  if (!hasActive) state.activeSummaryPath = "";
  if (!summaries.length) {
    els.summaryList.innerHTML = '<div class="muted">No history summaries yet.</div>';
    els.summaryTitle.textContent = "History Summaries";
    els.summaryMeta.textContent = "No compaction summary has been created for this branch yet.";
    els.summaryEditor.value = "";
    els.summaryEditor.disabled = true;
    els.summarySaveButton.disabled = true;
    setSummaryStatus("");
    return;
  }
  els.summaryList.innerHTML = summaries
    .map((item) => {
      const injected = item.injected ? "Injected" : "Stored";
      const chars = Number(item.chars || 0).toLocaleString();
      return `
        <button class="nav-item ${item.path === state.activeSummaryPath ? "active" : ""}" data-summary-path="${escapeHtml(item.path || "")}" type="button">
          <span class="nav-title">${escapeHtml(item.title || "history summary")}</span>
          <span class="nav-meta">${escapeHtml(injected)} · ${escapeHtml(chars)} chars</span>
          <span class="nav-meta">${escapeHtml(item.path || "")}</span>
        </button>
      `;
    })
    .join("");
  els.summaryList.querySelectorAll("[data-summary-path]").forEach((button) => {
    button.addEventListener("click", () => loadSummary(button.dataset.summaryPath));
  });
  els.summaryEditor.disabled = !state.activeSummaryPath;
  els.summarySaveButton.disabled = !state.activeSummaryPath || state.payload?.archived === true;
  const summariesTabActive = document.querySelector("#summariesTab")?.classList.contains("active");
  if (!state.activeSummaryPath && summariesTabActive) {
    const firstInjected = summaries.find((item) => item.injected) || summaries[0];
    if (firstInjected?.path) {
      loadSummary(firstInjected.path).catch((error) => setSummaryStatus(`Summary load failed: ${error.message}`, "error"));
    }
  }
}

async function loadSummary(path) {
  if (!state.activeBranch || !path) return;
  state.activeSummaryPath = path;
  renderSummaries(state.payload?.compactions || []);
  setSummaryStatus("Loading summary...");
  const payload = await api(`/api/branch/compaction?branch=${encodeURIComponent(state.activeBranch)}&path=${encodeURIComponent(path)}`);
  if (state.activeSummaryPath !== path) return;
  els.summaryTitle.textContent = payload.name || "History Summary";
  els.summaryMeta.textContent = `${payload.branch || state.activeBranch} · ${payload.path || path} · ${Number(payload.size || 0).toLocaleString()} bytes`;
  els.summaryEditor.value = payload.text || "";
  els.summaryEditor.disabled = false;
  els.summarySaveButton.disabled = state.payload?.archived === true;
  setSummaryStatus("");
}

async function saveSummary() {
  if (!state.activeBranch || !state.activeSummaryPath) return;
  els.summarySaveButton.disabled = true;
  setSummaryStatus("Saving summary...");
  try {
    const payload = await api("/api/branch/compaction", {
      method: "POST",
      body: JSON.stringify({
        branch: state.activeBranch,
        path: state.activeSummaryPath,
        text: els.summaryEditor.value,
      }),
    });
    const activePath = payload.summaryEdit?.path || state.activeSummaryPath;
    renderBranch(payload);
    state.activeSummaryPath = activePath;
    await loadSummary(activePath);
    setSummaryStatus("Saved.", "ok");
  } catch (error) {
    setSummaryStatus(`Save failed: ${error.message}`, "error");
  } finally {
    if (state.activeSummaryPath && state.payload?.archived !== true) {
      els.summarySaveButton.disabled = false;
    }
  }
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
  state.folders = data.folders || [];
  state.archived = data.archived || [];
  state.views = data.views || [];
  state.globalized = data.globalized || [];
  if (!state.activeContextChat && !state.activeBranch && !state.activeGlobalized && state.branches.length) {
    state.activeBranch = state.branches[0].id;
  }
  renderBranches();
  if (state.activeContextChat) {
    await loadContextChat();
  } else if (state.activeBranch) {
    await loadBranch(state.activeBranch);
  } else {
    els.activeTitle.textContent = "No branch selected";
    setBranchDirButton(null);
    els.activeMeta.textContent = "Create a branch from the terminal with ctxgit branch <id>.";
    replaceMessageListHtml('<div class="muted">No messages yet.</div>');
    renderBranchResourceStage();
    restoreActiveDraft();
    updateComposerState();
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

// After a reload the in-memory job state is gone, but jobs keep running on the
// server. Re-attach to them so the running branch shows progress + a Stop button
// and a duplicate turn cannot be started (which used to produce two answers).
async function rehydrateRunningJobs() {
  let data;
  try {
    data = await api("/api/jobs/active");
  } catch (_error) {
    return;
  }
  let changed = false;
  for (const job of data.jobs || []) {
    if (!job.id || !job.branch) continue;
    if (state.jobs[job.id]) continue; // already tracked this session
    rememberJob({ ...job, status: job.status || "running" }, { branch: job.branch, mode: job.mode });
    monitorTrackedJob(job.id).catch((error) => handleMonitorError(state.jobs[job.id] || job, error));
    changed = true;
  }
  if (changed) {
    renderBranches();
    renderActiveBranchJob();
  }
}

async function loadProject() {
  await loadServerProjects();
  await loadWorkerStatus();
  let project;
  try {
    project = await api("/api/project");
  } catch (error) {
    // A stale stored project path (moved/deleted) would 400; drop it and fall
    // back to the server's active project so the tab still loads.
    if (error instanceof ApiError && error.payload?.error === "project_invalid") {
      rememberProjectPath("");
      project = await api("/api/project");
    } else {
      throw error;
    }
  }
  renderProject(project);
  if (project.initialized) {
    await loadBranches();
    await loadProjectFiles(state.fileBrowser.path || "");
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
    await loadWorkerStatus();
    loadNotificationSettings().catch(() => {});
    rehydrateRunningJobs().catch(() => {});
  } else if (!project.path) {
    clearWorkspace("Select or initialize a ctxgit project.");
  } else {
    clearWorkspace("This directory is not initialized for ctxgit yet.");
  }
}

async function openProject(path, { init }) {
  if (!path) return;
  saveActiveDraft();
  els.openProjectButton.disabled = true;
  els.initProjectButton.disabled = true;
  els.browseProjectButton.disabled = true;
  setProjectStatus(init ? "Initializing project..." : "Opening project...");
  try {
    const project = await api(init ? "/api/project/init" : "/api/project/open", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    renderProject(project);
    state.activeBranch = null;
    state.activeGlobalized = null;
    state.activeContextChat = false;
    state.messageDrafts = {};
    state.branchResourceStaged = {};
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
  saveActiveDraft();
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
    state.activeContextChat = false;
    state.messageDrafts = {};
    state.branchResourceStaged = {};
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
  saveActiveDraft();
  state.activeBranch = branch;
  state.activeGlobalized = null;
  state.activeContextChat = false;
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

async function loadContextChat() {
  saveActiveDraft();
  state.activeBranch = null;
  state.activeGlobalized = null;
  state.activeContextChat = true;
  selectTab("chat");
  renderBranches();
  const payload = await api("/api/context-chat");
  if (!state.activeContextChat) return;
  renderContextChat(payload);
  renderGit(await api("/api/git/status"));
  renderProvider(await api("/api/provider/status"));
  if (!state.activeContextChat) return;
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

function beginReviseHistoryMessage(button) {
  if (!state.activeBranch) return;
  const index = Number.parseInt(button.dataset.historyRevise || "", 10);
  if (!Number.isInteger(index)) return;
  const message = state.payload?.history?.[index];
  const article = els.messageList.querySelector(`[data-history-message="${index}"]`);
  const body = article?.querySelector(".message-text");
  if (!message || !body || article.classList.contains("revising")) return;
  article.classList.add("revising");
  body.innerHTML = `
    <textarea class="message-revise-input" rows="6" aria-label="Revised message">${escapeHtml(message.text || "")}</textarea>
    <div class="message-revise-actions">
      <button data-history-revise-save="${index}" type="button">Save revision</button>
      <button data-history-revise-cancel="${index}" type="button">Cancel</button>
    </div>
    <div class="message-revise-status settings-status"></div>
  `;
  const input = body.querySelector(".message-revise-input");
  const saveButton = body.querySelector("[data-history-revise-save]");
  const cancelButton = body.querySelector("[data-history-revise-cancel]");
  const resizeEditor = () => {
    input.style.height = "0";
    input.style.height = `${input.scrollHeight}px`;
  };
  resizeEditor();
  input.addEventListener("input", resizeEditor);
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  cancelButton.addEventListener("click", () => {
    article.classList.remove("revising");
    body.innerHTML = renderMessageText(message.text);
  });
  saveButton.addEventListener("click", () => {
    reviseHistoryMessage({
      article,
      body,
      input,
      saveButton,
      cancelButton,
      index,
      createdAt: button.dataset.historyCreatedAt || "",
      role: button.dataset.historyRole || "",
    });
  });
}

async function reviseHistoryMessage({ article, body, input, saveButton, cancelButton, index, createdAt, role }) {
  const branch = state.activeBranch;
  const text = input.value.trim();
  const status = body.querySelector(".message-revise-status");
  if (!branch || !text) {
    status.textContent = "Message text is required.";
    status.className = "message-revise-status settings-status error";
    return;
  }
  saveButton.disabled = true;
  cancelButton.disabled = true;
  status.textContent = "Saving revision...";
  status.className = "message-revise-status settings-status";
  try {
    const payload = await api("/api/history/revise", {
      method: "POST",
      body: JSON.stringify({ branch, index, text, createdAt, role }),
    });
    if (state.activeBranch === branch) {
      renderBranch(payload);
      renderGit(await api("/api/git/status"));
      await refreshBranchNavigation();
    }
  } catch (error) {
    status.textContent = `Revise failed: ${error.message}`;
    status.className = "message-revise-status settings-status error";
    saveButton.disabled = false;
    cancelButton.disabled = false;
    article.classList.add("revising");
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

// One-click delete of an unanswered message (no confirm; it never got a reply).
async function deleteFailedMessage(button) {
  const branch = state.activeBranch;
  if (!branch) return;
  const index = Number.parseInt(button.dataset.failedDelete || "", 10);
  if (!Number.isInteger(index)) return;
  button.disabled = true;
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
    window.alert(`삭제 실패: ${error.message}`);
    button.disabled = false;
  }
}

// One-click resend: drop the unanswered message so it is not duplicated, then
// send its text again with the same mode.
async function resendFailedMessage(index) {
  const branch = state.activeBranch;
  const message = state.payload?.history?.[index];
  if (!branch || !message || message.role !== "user") return;
  const text = String(message.text || "");
  if (!text.trim()) return;
  // Resend with the mode the message was originally sent in. Legacy "send"
  // messages predate the stored mode and have none — treat those as "chat"
  // (send), never info, so a stopped send resends as send.
  const raw = String(message.mode || "");
  const mode =
    raw === "info-chat" || raw === "research"
      ? raw
      : raw === "team" || raw === "team-pipeline"
      ? "team"
      : "chat";
  try {
    const payload = await api("/api/history/delete", {
      method: "POST",
      body: JSON.stringify({ branch, index, createdAt: message.createdAt || "", role: message.role || "" }),
    });
    if (state.activeBranch === branch) renderBranch(payload);
  } catch (error) {
    window.alert(`재전송 실패: ${error.message}`);
    return;
  }
  els.messageInput.value = text;
  resizeMessageInput();
  await sendComposerMessage({ mode, runningAction: "stop" });
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

async function forkHistoryMessage(button, { contextOnly = false } = {}) {
  if (!state.activeBranch) return;
  const index = Number.parseInt(
    contextOnly ? button.dataset.historyForkContext || "" : button.dataset.historyFork || "",
    10,
  );
  if (!Number.isInteger(index)) return;
  const branch = state.activeBranch;
  const title = window.prompt(
    contextOnly
      ? `Fork only the context from ${branch} at this message with title:`
      : `Fork ${branch} through this message with title:`,
    contextOnly ? `${branchTitle(branch)} context ${index + 1}` : `${branchTitle(branch)} fork ${index + 1}`,
  );
  if (!title) return;
  const targetTitle = title.trim();
  if (!targetTitle) return;
  const targetId = uniqueBranchIdForTitle(targetTitle);
  button.disabled = true;
  try {
    const payload = await api(contextOnly ? "/api/history/fork-context" : "/api/history/fork", {
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
    saveActiveDraft();
    state.activeBranch = targetId;
    state.activeGlobalized = null;
    state.activeContextChat = false;
    await loadBranches();
    renderBranch(payload);
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
  } catch (error) {
    window.alert(`${contextOnly ? "Fork context" : "Fork"} failed: ${error.message}`);
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
    saveActiveDraft();
    state.activeBranch = target;
    state.activeGlobalized = null;
    state.activeContextChat = false;
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
    saveActiveDraft();
    state.activeBranch = branch;
    state.activeGlobalized = null;
    state.activeContextChat = false;
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
    delete state.messageDrafts[branch];
    delete state.branchResourceStaged[branch];
    if (state.activeBranch === branch) {
      state.activeBranch = null;
      state.payload = null;
      restoreActiveDraft();
      renderBranchResourceStage();
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
    delete state.messageDrafts[branch];
    delete state.branchResourceStaged[branch];
    if (state.activeBranch === branch) {
      state.activeBranch = null;
      state.payload = null;
      restoreActiveDraft();
      renderBranchResourceStage();
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
          <article class="message message-${escapeHtml(message.role)}">
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
  saveActiveDraft();
  const payload = await api(`/api/globalized?id=${encodeURIComponent(archiveId)}`);
  state.activeBranch = null;
  state.activeGlobalized = archiveId;
  state.activeContextChat = false;
  renderBranchResourceStage();
  restoreActiveDraft();
  updateComposerState();
  renderBranches();
  const meta = payload.meta || {};
  const range = `${meta.rangeStart || "?"}-${meta.rangeEnd || "?"}`;
  els.activeTitle.textContent = meta.title || archiveId;
  setBranchDirButton(null);
  els.activeMeta.textContent = `${meta.sourceBranch || "archived"} · messages ${range}`;
  els.reportView.innerHTML = renderMarkdown(payload.markdown || "");
  const messages =
    (payload.history || [])
      .map(
        (message, index) => `
          <article class="message message-${escapeHtml(message.role)}">
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
  saveActiveDraft();
  const payload = await api(`/api/view?id=${encodeURIComponent(view)}`);
  state.activeBranch = null;
  state.activeGlobalized = null;
  state.activeContextChat = false;
  renderBranchResourceStage();
  restoreActiveDraft();
  updateComposerState();
  renderBranches();
  els.activeTitle.textContent = payload.id;
  setBranchDirButton(null);
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
  if (tab === "summaries") renderSummaries(state.payload?.compactions || []);
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

// ---------------------------------------------------------------------------
// Extensions — optional add-ons (not fundamental ctxgit features).
// Built-in registry rendered in the sidebar; opening one takes over the main
// panel via a dedicated #extensionTab.
// ---------------------------------------------------------------------------
// Client-side renderers, keyed by extension id. Metadata (name, icon,
// enabled/configured) comes from the server registry (/api/extensions).
const EXTENSION_RENDERERS = {
  instagram: renderInstagramExtension,
  google: renderGoogleExtension,
};

let openExtensionId = null;

async function loadExtensions() {
  try {
    const data = await api("/api/extensions");
    state.extensions = data.extensions || [];
  } catch (_error) {
    state.extensions = [];
  }
  renderExtensionList();
}

function renderExtensionList() {
  if (!els.extensionList) return;
  els.extensionList.innerHTML = "";
  (state.extensions || []).forEach((ext) => {
    const row = document.createElement("div");
    row.className = `extension-row${ext.enabled ? "" : " disabled"}`;

    const button = document.createElement("button");
    button.type = "button";
    button.className = `nav-item extension-item${ext.id === openExtensionId ? " active" : ""}`;
    button.textContent = `${ext.icon} ${ext.name}`;
    button.title = ext.description || "";
    button.addEventListener("click", () => openExtension(ext.id));

    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.className = "extension-toggle";
    toggle.checked = !!ext.enabled;
    toggle.title = ext.enabled ? "Deactivate" : "Activate";
    toggle.addEventListener("change", () => toggleExtension(ext.id, toggle.checked));

    row.appendChild(button);
    row.appendChild(toggle);
    els.extensionList.appendChild(row);
  });
}

async function toggleExtension(id, enabled) {
  try {
    const data = await api("/api/extensions/toggle", {
      method: "POST",
      body: JSON.stringify({ id, enabled }),
    });
    state.extensions = data.extensions || [];
  } catch (_error) {
    // Leave state as-is; re-render reflects the last known server truth.
  }
  renderExtensionList();
  if (openExtensionId === id) openExtension(id);
}

function extensionById(id) {
  return (state.extensions || []).find((item) => item.id === id) || null;
}

function showExtensionPanel() {
  document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
  document.querySelector("#extensionTab")?.classList.add("active");
}

function openExtension(id) {
  const ext = extensionById(id);
  const render = EXTENSION_RENDERERS[id];
  if (!ext || !render || !els.extensionContent) return;
  openExtensionId = id;
  showExtensionPanel();
  renderExtensionList();
  els.extensionContent.innerHTML = "";
  if (!ext.enabled) {
    els.extensionContent.innerHTML = `
      <div class="extension-header">
        <h2>${escapeHtml(ext.icon)} ${escapeHtml(ext.name)}</h2>
        <p class="extension-subtitle">This extension is deactivated.</p>
      </div>
      <button type="button" class="wide-button" id="extensionEnableButton">Activate ${escapeHtml(ext.name)}</button>
    `;
    els.extensionContent
      .querySelector("#extensionEnableButton")
      ?.addEventListener("click", () => toggleExtension(id, true));
    return;
  }
  render(els.extensionContent);
}

function renderGoogleExtension(container) {
  const ext = extensionById("google") || {};
  const connected = !!ext.configured;
  container.innerHTML = `
    <div class="extension-header">
      <h2>📧 Google (Gmail + Drive)</h2>
      <p class="extension-subtitle">내 Gmail·Drive를 <strong>읽기 전용</strong>으로 찾고 읽습니다. ctxgit이 표준 Google API를 직접 호출합니다.</p>
    </div>
    <div class="gw-status">
      <span class="gw-chip ${connected ? "ok" : "off"}">${connected ? "연결됨 (인증 완료)" : "미인증"}</span>
      <button id="gwRefresh" type="button" class="gw-refresh">상태 새로고침</button>
    </div>
    <ol class="gw-steps">
      <li><strong>Google Cloud</strong>: Gmail API + Drive API 사용 설정. OAuth 동의화면 스코프는 <strong>읽기 전용만</strong> — <code>gmail.readonly</code>, <code>drive.readonly</code>. OAuth 클라이언트를 <strong>"데스크톱 앱"</strong> 타입으로 만들어 client id/secret 발급.</li>
      <li><strong>인증</strong> — 터미널(또는 <code>!</code> 붙여) 한 번만 실행:
        <pre class="code-block">/opt/homebrew/bin/python3.12 ${escapeHtml(GOOGLE_SCRIPT_PATH)} google-auth</pre>
        브라우저가 열리면 로그인·동의 → 끝. (client id/secret 입력받고, refresh 토큰을 <code>extensions/google/.env</code>에 저장합니다.)
      </li>
    </ol>
    <p class="gw-note gw-warn">🔒 <strong>읽기 전용</strong>: 에이전트에게 찾기·읽기 툴만 노출됩니다 — <code>gmail_search</code>, <code>gmail_get_message</code>, <code>gmail_list_labels</code>, <code>drive_search</code>, <code>drive_read_file</code>. 발송·수정 툴은 아예 존재하지 않습니다. 토큰은 이 기기(<code>extensions/google/.env</code>)에만 있고, 왼쪽 토글로 언제든 차단됩니다.</p>
    <p class="gw-note">인증 후 codex/claude 채팅에서 "내 Gmail에서 thehyundai 관련 메일 찾아 요약해줘"처럼 물어보면 자동으로 읽어옵니다.</p>
  `;
  container.querySelector("#gwRefresh")?.addEventListener("click", async () => {
    await loadExtensions();
    if (openExtensionId === "google") openExtension("google");
  });
}

const GOOGLE_SCRIPT_PATH = "tools/ctxgit/ctxgit.py";

function renderInstagramExtension(container) {
  container.innerHTML = `
    <div class="extension-header">
      <h2>📸 Instagram</h2>
      <p class="extension-subtitle">Powered by Rocket API. View a public profile and recent posts.</p>
    </div>
    <form id="instagramForm" class="extension-form">
      <input id="instagramUsername" type="text" placeholder="username (without @)" autocomplete="off" />
      <button type="submit">View</button>
    </form>
    <div id="instagramStatus" class="settings-status"></div>
    <div id="instagramResult" class="instagram-result"></div>
  `;
  const form = container.querySelector("#instagramForm");
  const usernameInput = container.querySelector("#instagramUsername");
  const statusEl = container.querySelector("#instagramStatus");
  const resultEl = container.querySelector("#instagramResult");

  api("/api/extensions/instagram/status")
    .then((data) => {
      if (!data.configured) {
        statusEl.textContent = "Rocket API key is not configured. Add ROCKETAPI_KEY to extensions/instagram/.env.";
        statusEl.className = "settings-status error";
      }
    })
    .catch(() => {});

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = (usernameInput.value || "").trim().replace(/^@/, "");
    if (!username) return;
    statusEl.textContent = "Loading profile…";
    statusEl.className = "settings-status";
    resultEl.innerHTML = "";
    try {
      const profileData = await api("/api/extensions/instagram/profile", {
        method: "POST",
        body: JSON.stringify({ username }),
      });
      const profile = profileData.profile || {};
      renderInstagramProfile(resultEl, profile);
      statusEl.textContent = "";
      if (profile.id && !profile.is_private) {
        statusEl.textContent = "Loading posts…";
        try {
          const mediaData = await api("/api/extensions/instagram/media", {
            method: "POST",
            body: JSON.stringify({ id: profile.id, count: 12 }),
          });
          renderInstagramMedia(resultEl, mediaData.media || []);
          statusEl.textContent = "";
        } catch (mediaError) {
          statusEl.textContent = `Posts failed: ${mediaError.message}`;
          statusEl.className = "settings-status error";
        }
      } else if (profile.is_private) {
        const note = document.createElement("div");
        note.className = "instagram-private-note";
        note.textContent = "This account is private — posts are not available.";
        resultEl.appendChild(note);
      }
    } catch (error) {
      statusEl.textContent = `Failed: ${error.message}`;
      statusEl.className = "settings-status error";
    }
  });
}

function proxyInstagramImage(url) {
  if (!url) return "";
  return `/api/extensions/instagram/image?url=${encodeURIComponent(url)}`;
}

function renderInstagramProfile(container, profile) {
  const card = document.createElement("div");
  card.className = "instagram-profile";
  const verified = profile.is_verified ? " ✔" : "";
  const link = profile.external_url
    ? `<a href="${escapeHtml(profile.external_url)}" target="_blank" rel="noopener">${escapeHtml(profile.external_url)}</a>`
    : "";
  card.innerHTML = `
    <img class="instagram-avatar" src="${proxyInstagramImage(profile.profile_pic_url)}" alt="" />
    <div class="instagram-profile-info">
      <div class="instagram-profile-name">
        <a href="https://www.instagram.com/${escapeHtml(profile.username)}/" target="_blank" rel="noopener">@${escapeHtml(profile.username)}</a>${verified}
      </div>
      <div class="instagram-profile-fullname">${escapeHtml(profile.full_name)}</div>
      <div class="instagram-stats">
        <span><strong>${Number(profile.posts || 0).toLocaleString()}</strong> posts</span>
        <span><strong>${Number(profile.followers || 0).toLocaleString()}</strong> followers</span>
        <span><strong>${Number(profile.following || 0).toLocaleString()}</strong> following</span>
      </div>
      <div class="instagram-bio">${escapeHtml(profile.biography).replaceAll("\n", "<br />")}</div>
      <div class="instagram-external">${link}</div>
    </div>
  `;
  container.appendChild(card);
}

function renderInstagramMedia(container, media) {
  const grid = document.createElement("div");
  grid.className = "instagram-grid";
  if (!media.length) {
    grid.innerHTML = `<div class="instagram-empty">No posts found.</div>`;
    container.appendChild(grid);
    return;
  }
  media.forEach((post) => {
    const tile = document.createElement("a");
    tile.className = "instagram-tile";
    tile.href = post.permalink || "#";
    tile.target = "_blank";
    tile.rel = "noopener";
    tile.title = post.caption || "";
    const videoBadge = post.is_video ? `<span class="instagram-video-badge">▶</span>` : "";
    tile.innerHTML = `
      <img loading="lazy" src="${proxyInstagramImage(post.thumbnail_url)}" alt="" />
      ${videoBadge}
      <span class="instagram-tile-meta">♥ ${Number(post.like_count || 0).toLocaleString()} · 💬 ${Number(post.comment_count || 0).toLocaleString()}</span>
    `;
    grid.appendChild(tile);
  });
  container.appendChild(grid);
}

loadExtensions();

els.summarySaveButton.addEventListener("click", saveSummary);

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
  if (!event.target.closest("#mergeSourcePicker")) {
    setMergePickerOpen(false);
  }
  if (!event.target.closest("#sequenceOrderPicker")) {
    setSequenceOrderOpen(false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.mergePickerOpen) {
    setMergePickerOpen(false);
    els.mergeSourceToggle.focus();
  }
  if (event.key === "Escape" && state.sequenceOrderOpen) {
    setSequenceOrderOpen(false);
    els.sequenceOrderButton.focus();
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

els.contextChatButton.addEventListener("click", () => {
  loadContextChat().catch((error) => {
    showChatError(`Contexts chat failed: ${error.message}`);
  });
});

els.chatTab.addEventListener("dragenter", (event) => {
  if (!hasDraggedFiles(event)) return;
  event.preventDefault();
  state.branchDropDepth += 1;
  setBranchDropActive(true);
});

els.chatTab.addEventListener("dragover", (event) => {
  if (!hasDraggedFiles(event)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = canDropBranchResources() ? "copy" : "none";
  setBranchDropActive(true);
});

els.chatTab.addEventListener("dragleave", (event) => {
  if (!hasDraggedFiles(event)) return;
  state.branchDropDepth = Math.max(0, state.branchDropDepth - 1);
  if (state.branchDropDepth === 0) {
    setBranchDropActive(false);
  }
});

els.chatTab.addEventListener("drop", async (event) => {
  if (!hasDraggedFiles(event)) return;
  event.preventDefault();
  state.branchDropDepth = 0;
  setBranchDropActive(false);
  stageBranchResourceFiles(event.dataTransfer.files);
});

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

els.mergeSourceToggle.addEventListener("click", () => {
  setMergePickerOpen(!state.mergePickerOpen);
});

els.mergeSourceDropdown.addEventListener("click", (event) => {
  event.stopPropagation();
});

els.mergeSourceFilter.addEventListener("input", renderMergeSourcePicker);

els.mergeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const branches = [...state.mergeSelectedBranches];
  const title = els.mergeNameInput.value.trim();
  if (branches.length < 2 || !title) {
    els.mergeStatus.textContent = "Select at least two branches in merge order and enter a title.";
    els.mergeStatus.className = "settings-status error";
    return;
  }
  const name = uniqueBranchIdForTitle(title);
  els.mergeButton.disabled = true;
  els.mergeStatus.textContent = "Starting merge...";
  els.mergeStatus.className = "settings-status";
  try {
    saveActiveDraft();
    state.activeBranch = name;
    state.activeGlobalized = null;
    state.activeContextChat = false;
    markBranchActivity(name);
    renderBranches();
    await startTrackedJob(
      "/api/merge/start",
      { branches, name, title, provider: state.provider?.provider || "codex" },
      { branch: name, mode: "merge", title: "머지 요약 생성 중" },
    );
    state.mergeSelectedBranches = [];
    els.mergeSourceFilter.value = "";
    setMergePickerOpen(false);
    renderMergeSourcePicker();
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

function sequenceBranchOptions() {
  return orderedBranches()
    .filter((branch) => branch.id !== state.activeBranch || state.branches.length > 1)
    .map((branch) => `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.title || branch.id)} (${escapeHtml(branch.id)})</option>`)
    .join("");
}

function renderSequenceAgentRows(count = 2) {
  const existing = [...els.sequenceAgentRows.querySelectorAll(".sequence-agent-row")].map((row) => ({
    branch: row.querySelector("[data-sequence-agent-source]")?.value || "",
    prompt: row.querySelector("[data-sequence-agent-prompt]")?.value || "",
    access: row.querySelector("[data-sequence-agent-access]")?.value || "info-chat",
  }));
  const nextCount = Math.max(2, Math.min(12, count));
  els.sequenceAgentRows.innerHTML = Array.from({ length: nextCount }, (_, index) => {
    const previous = existing[index] || {};
    return `
      <section class="sequence-agent-row">
        <div class="sequence-agent-row-header">
          <strong>Agent ${index + 1}</strong>
          ${nextCount > 2 ? `<button data-sequence-remove-agent="${index}" type="button">Remove</button>` : ""}
        </div>
        <label>Source branch<select data-sequence-agent-source>${sequenceBranchOptions()}</select></label>
        <label>Persistent system prompt<textarea data-sequence-agent-prompt rows="4">${escapeHtml(previous.prompt || "")}</textarea></label>
        <label>Permission<select data-sequence-agent-access><option value="send">Can send and edit project</option><option value="info-chat">Info chat only</option></select></label>
      </section>
    `;
  }).join("");
  [...els.sequenceAgentRows.querySelectorAll(".sequence-agent-row")].forEach((row, index) => {
    const source = row.querySelector("[data-sequence-agent-source]");
    const access = row.querySelector("[data-sequence-agent-access]");
    if (existing[index]?.branch) source.value = existing[index].branch;
    else if (source.options.length) source.selectedIndex = Math.min(index, source.options.length - 1);
    access.value = existing[index]?.access || (index === 0 ? "send" : "info-chat");
  });
  els.sequenceAgentRows.querySelectorAll("[data-sequence-remove-agent]").forEach((button) => {
    button.addEventListener("click", () => {
      const removeIndex = Number(button.dataset.sequenceRemoveAgent);
      const rows = [...els.sequenceAgentRows.querySelectorAll(".sequence-agent-row")];
      rows[removeIndex]?.remove();
      renderSequenceAgentRows(rows.length - 1);
    });
  });
}

els.sequenceRoomCreateButton.addEventListener("click", () => {
  renderSequenceAgentRows(2);
  els.sequenceRoomStatus.textContent = "";
  els.sequenceRoomDialog.showModal();
});

els.sequenceOrderButton.addEventListener("click", (event) => {
  event.stopPropagation();
  setSequenceOrderOpen(!state.sequenceOrderOpen);
  if (state.sequenceOrderOpen) {
    els.sequenceOrderStatus.textContent = "";
    renderSequenceOrderPicker();
  }
});

els.sequenceAddAgentButton.addEventListener("click", () => {
  const count = els.sequenceAgentRows.querySelectorAll(".sequence-agent-row").length;
  if (count < 12) renderSequenceAgentRows(count + 1);
});

els.sequenceRoomForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const rows = [...els.sequenceAgentRows.querySelectorAll(".sequence-agent-row")];
  const branches = rows.map((row) => row.querySelector("[data-sequence-agent-source]").value);
  const systemPrompts = rows.map((row) => row.querySelector("[data-sequence-agent-prompt]").value);
  const accessModes = rows.map((row) => row.querySelector("[data-sequence-agent-access]").value);
  if (branches.length < 2 || branches.some((branch) => !branch) || new Set(branches).size !== branches.length) {
    els.sequenceRoomStatus.textContent = "Choose at least two distinct branches.";
    els.sequenceRoomStatus.className = "settings-status error";
    return;
  }
  try {
    const roomTitle = els.sequenceRoomName.value.trim();
    const roomId = uniqueBranchIdForTitle(roomTitle);
    const payload = await api("/api/sequence-room/create", {
      method: "POST",
      body: JSON.stringify({
        branches,
        systemPrompts,
        accessModes,
        name: roomId,
        title: roomTitle,
        maxAgentReplies: Number(els.sequenceMaxReplies.value || 6),
      }),
    });
    els.sequenceRoomDialog.close();
    state.activeBranch = payload.meta.id;
    await loadBranches();
    renderBranch(payload);
  } catch (error) {
    els.sequenceRoomStatus.textContent = `Create failed: ${error.message}`;
    els.sequenceRoomStatus.className = "settings-status error";
  }
});

async function loadSequenceParticipantComparison() {
  const order = Number(els.sequenceUpdateOrder.value || 1);
  const data = await api(`/api/sequence-room/participant?branch=${encodeURIComponent(state.activeBranch)}&order=${order}`);
  els.sequenceUpdatePrompt.value = data.participant?.systemPrompt || "";
  els.sequenceUpdateAccess.value = data.participant?.accessMode || "info-chat";
  els.sequenceUpdateMaxReplies.value = data.sequenceRoom?.defaultMaxAgentReplies || 6;
  els.sequenceUpdateMinEvaluatorRounds.value = data.sequenceRoom?.minimumEvaluatorRounds || 2;
  els.sequenceUpdateAcceptanceCriteria.value = (data.sequenceRoom?.acceptanceCriteria || []).join("\n");
  const formatSummaries = (side) =>
    (side.summaries || [])
      .map((item) =>
        [
          `# ${item.title || "summary"}`,
          item.path || "",
          "",
          item.text || "",
        ]
          .filter((line, index) => index !== 1 || line)
          .join("\n"),
      )
      .join("\n\n---\n\n");
  const formatSide = (side) =>
    `CONTEXT\n${side.context || ""}\n\nHISTORY\n${(side.history || []).map((item) => `${item.role}: ${item.text}`).join("\n\n")}`;
  els.sequenceSnapshotSummaryView.textContent = formatSummaries(data.snapshot);
  els.sequenceCurrentSummaryView.textContent = data.current?.exists ? formatSummaries(data.current) : "";
  els.sequenceSnapshotView.textContent = formatSide(data.snapshot);
  els.sequenceCurrentView.textContent = data.current?.exists ? formatSide(data.current) : "Source branch is missing.";
  els.sequenceUpdateSnapshot.checked = false;
}

els.sequenceRoomUpdateButton.addEventListener("click", async () => {
  els.sequenceUpdateStatus.textContent = "";
  els.sequenceUpdateOrder.innerHTML = sequenceParticipants()
    .map(
      (participant) =>
        `<option value="${Number(participant.order)}">Agent ${Number(participant.order)} · ${escapeHtml(participant.title || participant.sourceBranch || "")}</option>`,
    )
    .join("");
  await loadSequenceParticipantComparison();
  els.sequenceUpdateDialog.showModal();
});

els.sequenceNotifyToggle?.addEventListener("click", async () => {
  const branch = state.activeBranch;
  if (!branch || state.payload?.meta?.kind !== "sequence-room") return;
  const next = els.sequenceNotifyToggle.getAttribute("aria-pressed") !== "true";
  els.sequenceNotifyToggle.disabled = true;
  try {
    const payload = await api("/api/sequence-room/notify", {
      method: "POST",
      body: JSON.stringify({ branch, notifyEachReply: next }),
    });
    if (state.activeBranch === branch) renderBranch(payload);
  } catch (error) {
    window.alert(`알림 설정 저장 실패: ${error.message}`);
  } finally {
    els.sequenceNotifyToggle.disabled = false;
  }
});

els.sequenceUpdateOrder.addEventListener("change", () => {
  loadSequenceParticipantComparison().catch((error) => {
    els.sequenceUpdateStatus.textContent = error.message;
  });
});

els.sequenceUpdateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = await api("/api/sequence-room/update", {
      method: "POST",
      body: JSON.stringify({
        branch: state.activeBranch,
        order: Number(els.sequenceUpdateOrder.value),
        systemPrompt: els.sequenceUpdatePrompt.value,
        accessMode: els.sequenceUpdateAccess.value,
        maxAgentReplies: Number(els.sequenceUpdateMaxReplies.value || 6),
        minimumEvaluatorRounds: Number(els.sequenceUpdateMinEvaluatorRounds.value || 2),
        acceptanceCriteria: els.sequenceUpdateAcceptanceCriteria.value
          .split(/\r?\n/)
          .map((item) => item.trim())
          .filter(Boolean),
        updateSnapshot: els.sequenceUpdateSnapshot.checked,
      }),
    });
    els.sequenceUpdateDialog.close();
    renderBranch(payload);
    await refreshBranchNavigation();
  } catch (error) {
    els.sequenceUpdateStatus.textContent = `Update failed: ${error.message}`;
    els.sequenceUpdateStatus.className = "settings-status error";
  }
});

async function sendComposerMessage({ mode, runningAction = "stop" }) {
  const isContextChat = state.activeContextChat === true;
  if (!state.activeBranch && !isContextChat) return;
  if (isContextChat && mode === "research") {
    window.alert("Contexts chat은 전체 맥락을 보는 읽기 전용 챗이라 research 작업은 브랜치에서 실행해주세요.");
    return;
  }
  if (!isContextChat && state.payload?.archived === true) {
    window.alert("Archived branches are read-only. Fork or clone it before continuing work.");
    return;
  }
  const branch = isContextChat ? CONTEXT_CHAT_KEY : state.activeBranch;
  const runningJob = activeBranchRunningJob(branch);
  if (runningJob) {
    const isSequenceRoom = state.payload?.meta?.kind === "sequence-room";
    if (isSequenceRoom && runningAction === "interrupt") {
      await interjectSequenceRoom(branch, runningJob);
      return;
    }
    await cancelTrackedJob(runningJob);
    return;
  }
  const text = els.messageInput.value.trim();
  const stagedFiles = isContextChat ? [] : stagedBranchResources(branch);
  const isGuest = mode === "guest";
  // Guest may run with no typed text (it just gives feedback on the conversation).
  if (!text && !stagedFiles.length && !isGuest) return;
  hideChatError();
  const isChat = mode === "chat";
  const isResearch = mode === "research";
  const isInfoChat = mode === "info-chat";
  const isTeam = mode === "team";
  if (state.startingBranches[branch]) {
    window.alert(
      isContextChat
        ? "Contexts chat에는 이미 실행 중인 작업이 있습니다."
        : "이 브랜치에는 이미 실행 중인 작업이 있습니다. 다른 브랜치로 이동하면 별도 작업을 시작할 수 있습니다.",
    );
    return;
  }
  const requestedMode = isContextChat ? "context-chat" : isResearch ? "research" : isTeam ? "team" : isGuest ? "guest" : isInfoChat ? "info-chat" : "chat";
  // Ask for desktop-notification permission on this user gesture so a finished
  // background job can pop a native notification (best-effort; tab badge works regardless).
  ensureNotificationPermission();
  state.startingBranches[branch] = requestedMode;
  markBranchActivity(branch);
  updateComposerState();
  renderBranches();
  // A typed message is always a normal user message (even when it's the guest
  // that will answer it), so show the optimistic bubble as "chat".
  const pendingMessageId = text
    ? appendPendingUserMessage({ branch, text, mode: isGuest ? "chat" : requestedMode })
    : "";
  let turnResourcePaths = [];
  try {
    if (stagedFiles.length) {
      const uploadPayload = await uploadBranchResourceFiles(stagedFiles, {
        branch,
        allowStarting: true,
        clearStage: true,
        render: !text,
        showProgress: !text,
      });
      if (!uploadPayload) {
        throw new Error("Resource upload did not finish.");
      }
      turnResourcePaths = (uploadPayload.uploadedResources || [])
        .map((item) => item?.path || "")
        .filter(Boolean);
      if (!text) {
        els.progressTitle.textContent = "완료됨";
        els.progressEvents.innerHTML = `<div>Staged resource files added to ${escapeHtml(branch)}.</div>`;
        hideProgressSoon();
        return;
      }
    }
    if (isContextChat) {
      const configuredProvider = state.provider?.provider || "codex";
      const provider =
        configuredProvider === "codex" && state.worker?.preferWorker ? "codex-worker" : configuredProvider;
      await startTrackedJob(
        "/api/context-chat/start",
        { text, provider },
        { branch, mode: "context-chat", title: "전체 컨텍스트 챗 시작 중" },
      );
      clearDraft(branch);
      return;
    }
    if (isResearch) {
      await startTrackedJob(
        "/api/research/start",
        { branch, text, provider: "hybrid", resources: turnResourcePaths },
        { branch, mode: "research", title: "리서치 시작 중" },
      );
      clearDraft(branch);
      return;
    }
    if (isTeam) {
      await startTrackedJob(
        "/api/team/start",
        { branch, text },
        { branch, mode: "team", title: "Team pipeline running" },
      );
      clearDraft(branch);
      return;
    }
    if (isGuest) {
      await startTrackedJob(
        "/api/guest/start",
        { branch, text },
        { branch, mode: "guest", title: "게스트 응답 중" },
      );
      clearDraft(branch);
      return;
    }
    if (isChat) {
      const configuredProvider = state.provider?.provider || "codex";
      const provider =
        configuredProvider === "codex" && state.worker?.preferWorker ? "codex-worker" : configuredProvider;
      if (state.payload?.meta?.kind === "sequence-room") {
        await startTrackedJob(
          "/api/sequence-room/start",
          {
            branch,
            text,
            runMode: "send",
            maxAgentReplies: state.payload?.sequenceRoom?.defaultMaxAgentReplies || 6,
          },
          { branch, mode: "sequence-room", title: "Sequence room running" },
        );
        clearDraft(branch);
        return;
      }
      await startTrackedJob(
        "/api/chat/start",
        { branch, text, provider, resources: turnResourcePaths },
        { branch, mode: "chat", title: "채팅 턴 시작 중" },
      );
      clearDraft(branch);
      return;
    }
    if (isInfoChat) {
      const configuredProvider = state.provider?.provider || "codex";
      const provider =
        configuredProvider === "codex" && state.worker?.preferWorker ? "codex-worker" : configuredProvider;
      if (state.payload?.meta?.kind === "sequence-room") {
        await startTrackedJob(
          "/api/sequence-room/start",
          {
            branch,
            text,
            runMode: "info-chat",
            maxAgentReplies: state.payload?.sequenceRoom?.defaultMaxAgentReplies || 6,
          },
          { branch, mode: "sequence-room-info", title: "Sequence room info chat running" },
        );
        clearDraft(branch);
        return;
      }
      await startTrackedJob(
        "/api/info-chat/start",
        { branch, text, provider, resources: turnResourcePaths },
        { branch, mode: "info-chat", title: "정보 챗 시작 중" },
      );
      clearDraft(branch);
      return;
    }
  } catch (error) {
    removePendingUserMessage(pendingMessageId);
    const isTimeout = error instanceof ApiError && error.payload?.error === "timeout";
    const isMissingJob = error instanceof ApiError && error.payload?.error === "job_not_found";
    const prefix = isTimeout
      ? "시간 초과"
      : isMissingJob
        ? "중단됨"
        : isContextChat
          ? "컨텍스트 챗 실패"
          : isResearch
            ? "리서치 실패"
            : "채팅 실패";
    if (activeChatKey() === branch) {
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

async function resetContextChatHistory() {
  const key = CONTEXT_CHAT_KEY;
  if (!state.activeContextChat) return;
  if (activeBranchRunningJob(key) || state.startingBranches[key]) {
    window.alert("Contexts chat 작업이 실행 중이라 지금은 reset할 수 없습니다.");
    return;
  }
  if (!window.confirm("Reset overall chat history?\n\ncontexts/history.jsonl이 비워집니다.")) {
    return;
  }
  hideChatError();
  els.contextResetButton.disabled = true;
  try {
    const payload = await api("/api/context-chat/reset", {
      method: "POST",
      body: JSON.stringify({}),
    });
    clearDraft(key);
    if (state.activeContextChat) {
      renderContextChat(payload);
      renderGit(await api("/api/git/status"));
      renderProvider(await api("/api/provider/status"));
    }
  } catch (error) {
    showChatError(`Reset failed: ${error.message}`);
  } finally {
    updateComposerState();
  }
}

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendComposerMessage({ mode: "chat", runningAction: "interrupt" });
});

// Engaging the input (focus, click, or typing) is the explicit "I've seen this"
// signal: only then does the completion indicator (green dot + tab badge) clear.
// Just viewing the branch or letting a job finish while it is open no longer
// clears it, so a finished result stays flagged until you actually act on it.
function engageActiveChat() {
  const key = activeChatKey();
  if (key && !isBranchJobAcknowledged(key)) {
    acknowledgeBranchJob(key);
    renderBranches();
  }
}

els.messageInput.addEventListener("focus", engageActiveChat);
els.messageInput.addEventListener("pointerdown", engageActiveChat);

els.messageInput.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  await sendComposerMessage({ mode: "info-chat", runningAction: "interrupt" });
});

els.messageInput.addEventListener("input", () => {
  engageActiveChat();
  saveActiveDraft();
  resizeMessageInput();
});

els.messageInput.addEventListener("paste", (event) => {
  const files = clipboardImageFiles(event);
  if (!files.length) return;
  event.preventDefault();
  stageBranchResourceFiles(files);
});
resizeMessageInput();

els.copyEventLogButton.addEventListener("click", copyEventLog);

// Copying rendered markdown (assistant results, reports) should yield plain
// text only, without carrying rich formatting into the paste target.
function forcePlainTextCopy(event) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return;
  const text = selection.toString();
  if (!text || !event.clipboardData) return;
  event.clipboardData.setData("text/plain", text);
  event.preventDefault();
}
els.messageList.addEventListener("copy", forcePlainTextCopy);
els.reportView.addEventListener("copy", forcePlainTextCopy);

els.providerInput.addEventListener("change", () => {
  renderProviderModelOptions(els.providerInput.value);
});

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
          provider: els.providerInput.value,
          model: els.providerModelInput.value.trim(),
          timeoutSeconds,
          webSearch: els.webSearchInput.checked,
          orchestration: els.orchestrationInput.value,
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
  await sendComposerMessage({ mode: "info-chat", runningAction: "stop" });
});

els.teamButton.addEventListener("click", async () => {
  await sendComposerMessage({ mode: "team", runningAction: "stop" });
});

els.guestButton?.addEventListener("click", async () => {
  await sendComposerMessage({ mode: "guest", runningAction: "stop" });
});

function setBranchDirButton(branchId) {
  if (!els.openBranchDirButton) return;
  // The "new branch from chat" button is contexts-chat only; renderContextChat
  // re-shows it. Any branch/empty view hides it here.
  if (els.contextBranchButton) els.contextBranchButton.hidden = true;
  if (branchId) {
    els.openBranchDirButton.dataset.branch = branchId;
    els.openBranchDirButton.hidden = false;
  } else {
    delete els.openBranchDirButton.dataset.branch;
    els.openBranchDirButton.hidden = true;
    // No active branch: hide the parent button too (renderBranch re-shows it).
    if (els.parentBranchButton) {
      els.parentBranchButton.hidden = true;
      delete els.parentBranchButton.dataset.parent;
    }
  }
}

// Primary parent of a branch, mirroring the server's precedence in
// internal_git_parent_refs_for_branch: parent → forkedFrom/clonedFrom →
// parents[] → merge.sourceBranches[]. Returns "" for a root branch.
function primaryParentBranchId(meta) {
  if (!meta || typeof meta !== "object") return "";
  const clean = (value) => (typeof value === "string" ? value.trim() : "");
  const candidates = [clean(meta.parent), clean(meta.forkedFrom), clean(meta.clonedFrom)];
  if (Array.isArray(meta.parents)) {
    candidates.push(...meta.parents.map(clean));
  }
  if (meta.merge && Array.isArray(meta.merge.sourceBranches)) {
    candidates.push(...meta.merge.sourceBranches.map(clean));
  }
  return candidates.find((id) => id) || "";
}

function setBranchParentButton(meta) {
  if (!els.parentBranchButton) return;
  const parent = primaryParentBranchId(meta);
  els.parentBranchButton.hidden = false;
  if (parent) {
    els.parentBranchButton.dataset.parent = parent;
    els.parentBranchButton.title = `Go to parent branch: ${parent}`;
  } else {
    delete els.parentBranchButton.dataset.parent;
    els.parentBranchButton.title = "This branch has no parent (root branch)";
  }
}

els.openBranchDirButton?.addEventListener("click", async () => {
  const branch = els.openBranchDirButton.dataset.branch || "";
  if (!branch) return;
  const previous = els.openBranchDirButton.textContent;
  els.openBranchDirButton.disabled = true;
  try {
    await api("/api/branch/reveal", { method: "POST", body: JSON.stringify({ branch }) });
    els.openBranchDirButton.textContent = "📂 Opened";
    window.setTimeout(() => {
      els.openBranchDirButton.textContent = previous;
    }, 1500);
  } catch (error) {
    window.alert(`폴더를 열 수 없습니다: ${error.message}`);
  } finally {
    els.openBranchDirButton.disabled = false;
  }
});

// Non-markdown project file links open with the OS default app (delegated, since
// these links are injected as innerHTML across many render sites).
document.addEventListener("click", (event) => {
  const link = event.target?.closest?.("[data-open-file]");
  if (!link) return;
  event.preventDefault();
  const path = link.dataset.openFile || "";
  if (!path) return;
  api("/api/project/file/open", { method: "POST", body: JSON.stringify({ path }) }).catch((error) => {
    window.alert(`파일을 열 수 없습니다: ${error.message}`);
  });
});

els.parentBranchButton?.addEventListener("click", async () => {
  const parent = els.parentBranchButton.dataset.parent || "";
  if (!parent) {
    window.alert("이 브랜치는 부모 브랜치가 없습니다 (최상위 브랜치).");
    return;
  }
  const isActive = Array.isArray(state.branches) && state.branches.some((item) => item.id === parent);
  const isArchived = Array.isArray(state.archived) && state.archived.some((item) => item.id === parent);
  if (!isActive && !isArchived) {
    window.alert(`부모 브랜치를 찾을 수 없습니다: ${parent}`);
    return;
  }
  // Archived branches open with the same loader (read-only view), so navigate either way.
  await loadBranch(parent);
});

els.contextBranchButton?.addEventListener("click", async () => {
  if (!state.activeContextChat) return;
  const title = window.prompt("New branch title:", "");
  const targetTitle = String(title || "").trim();
  if (!targetTitle) return;
  const targetId = uniqueBranchIdForTitle(targetTitle);
  els.contextBranchButton.disabled = true;
  try {
    const payload = await api("/api/context-chat/branch", {
      method: "POST",
      body: JSON.stringify({ target: targetId, title: targetTitle }),
    });
    // Open the freshly created branch and refresh the sidebar to include it.
    state.activeContextChat = false;
    state.activeBranch = payload.meta.id;
    await loadBranches();
  } catch (error) {
    window.alert(`브랜치 생성 실패: ${error.message}`);
  } finally {
    els.contextBranchButton.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Unread-completion tab indicator
//
// When any branch's job finishes ("초록불" / done) and has not been opened yet,
// reflect it in the browser tab so it is visible even when ctxgit is in a
// background tab: an unread count in the document title and a green dot on the
// favicon (works in every browser, no permission needed). As a bonus, a native
// desktop notification fires on the running→done transition where the browser
// grants permission (Chrome, Firefox, Safari, ...).
// (BASE_DOCUMENT_TITLE / notifiedDoneJobs / observedJobStatus are declared near
// the top of this file so they are initialized before any render runs.)
// ---------------------------------------------------------------------------

function unseenDoneBranchJobs() {
  const result = [];
  for (const [branch, jobId] of Object.entries(state.branchJobs || {})) {
    const job = jobId ? state.jobs[jobId] : null;
    if (job?.status === "done" && !isBranchJobAcknowledged(branch)) {
      result.push({ branch, job });
    }
  }
  return result;
}

function faviconLinkElement() {
  let link = document.querySelector('link[rel~="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  return link;
}

function renderFaviconDataUrl(count) {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  ctx.fillStyle = "#1f2430";
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = "#e6e6e6";
  ctx.font = "bold 34px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("cg", size / 2, size / 2 + 2);
  if (count > 0) {
    const r = 19;
    ctx.beginPath();
    ctx.arc(size - r, r, r, 0, Math.PI * 2);
    ctx.fillStyle = "#2ecc71";
    ctx.fill();
    ctx.fillStyle = "#0b1220";
    ctx.font = "bold 26px sans-serif";
    ctx.fillText(count > 9 ? "9+" : String(count), size - r, r + 1);
  }
  return canvas.toDataURL("image/png");
}

function maybeShowDesktopNotification(branch, job) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  // Skip if the user is already looking at this branch in a focused tab.
  if (activeChatKey() === branch && document.hasFocus()) return;
  const label = branch === CONTEXT_CHAT_KEY ? "Contexts chat" : branchTitle(branch) || branch;
  try {
    const notification = new Notification("ctxgit — 작업 완료", {
      body: `${label} 작업이 끝났습니다.`,
      tag: `ctxgit-job-${job.id}`,
    });
    notification.onclick = () => {
      window.focus();
      if (branch === CONTEXT_CHAT_KEY) {
        loadContextChat().catch(() => {});
      } else {
        loadBranch(branch).catch(() => {});
      }
      notification.close();
    };
  } catch (_error) {
    // Notifications are best-effort; ignore construction failures.
  }
}

function updateUnseenTabIndicator() {
  const unseen = unseenDoneBranchJobs();
  const count = unseen.length;
  document.title = count > 0 ? `(${count}) ${BASE_DOCUMENT_TITLE}` : BASE_DOCUMENT_TITLE;
  try {
    faviconLinkElement().href = renderFaviconDataUrl(count);
  } catch (_error) {
    // Canvas may be unavailable; the title indicator still works.
  }
  // Fire a desktop notification only for jobs we actually watched go running→done
  // this session, so a page reload with old unread jobs does not spam popups.
  for (const { branch, job } of unseen) {
    if (observedJobStatus.get(job.id) === "running" && !notifiedDoneJobs.has(job.id)) {
      notifiedDoneJobs.add(job.id);
      maybeShowDesktopNotification(branch, job);
    }
  }
  observedJobStatus.clear();
  for (const jobId of Object.values(state.branchJobs || {})) {
    const status = jobId ? state.jobs[jobId]?.status : null;
    if (status) observedJobStatus.set(jobId, status);
  }
}

function ensureNotificationPermission() {
  if (typeof Notification === "undefined") return;
  if (Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
}

els.eventPanelToggle.addEventListener("click", () => {
  setEventPanelVisible(!state.eventsVisible);
});

els.contextResetButton.addEventListener("click", resetContextChatHistory);

els.refreshButton.addEventListener("click", async () => {
  await loadProject();
});

function setBranchesCollapsed(collapsed) {
  if (!els.branchesToggle || !els.branchesBody) return;
  els.branchesBody.hidden = collapsed;
  els.branchesToggle.setAttribute("aria-expanded", String(!collapsed));
  try {
    localStorage.setItem(BRANCHES_COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
  } catch (_error) {
    // localStorage may be unavailable; the toggle still works for this session.
  }
}

els.branchesToggle?.addEventListener("click", () => {
  const expanded = els.branchesToggle.getAttribute("aria-expanded") === "true";
  setBranchesCollapsed(expanded);
});

(function restoreBranchesCollapsed() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(BRANCHES_COLLAPSED_STORAGE_KEY) === "1";
  } catch (_error) {
    collapsed = false;
  }
  setBranchesCollapsed(collapsed);
})();

els.extensionsToggle?.addEventListener("click", () => {
  if (!els.extensionsBody) return;
  const expanded = els.extensionsToggle.getAttribute("aria-expanded") === "true";
  els.extensionsBody.hidden = expanded;
  els.extensionsToggle.setAttribute("aria-expanded", String(!expanded));
});

els.newFolderButton?.addEventListener("click", () => {
  const name = window.prompt("새 폴더 이름:");
  if (name === null) return;
  createFolder(name);
});

// Global toggle for Telegram completion messages (one switch controls all projects).
async function loadNotificationSettings() {
  if (!els.telegramNotifyInput && !els.outputHumanizeInput) return;
  const settings = await api("/api/settings/notifications");
  if (els.telegramNotifyInput) {
    els.telegramNotifyInput.checked = settings.telegramNotifyEnabled !== false;
  }
  if (els.telegramNotifyStatus) {
    els.telegramNotifyStatus.textContent = settings.telegramConfigured
      ? ""
      : "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable.";
  }
  if (els.outputHumanizeInput) {
    els.outputHumanizeInput.checked = settings.outputHumanizeEnabled === true;
  }
}

// Persist one settings toggle and reflect status; reverts the checkbox on failure.
async function saveSettingToggle(input, statusEl, key, failLabel) {
  const enabled = input.checked;
  input.disabled = true;
  try {
    await api("/api/settings/notifications", {
      method: "POST",
      body: JSON.stringify({ [key]: enabled }),
    });
    if (statusEl && !statusEl.dataset.sticky) {
      statusEl.textContent = enabled ? "On" : "Off";
      window.setTimeout(() => {
        if (statusEl.textContent === (enabled ? "On" : "Off")) statusEl.textContent = "";
      }, 1200);
    }
  } catch (error) {
    input.checked = !enabled;
    window.alert(`${failLabel}: ${error.message}`);
  } finally {
    input.disabled = false;
  }
}

els.telegramNotifyInput?.addEventListener("change", () => {
  // The status line here doubles as a "configure token" hint, so keep it sticky.
  if (els.telegramNotifyStatus) els.telegramNotifyStatus.dataset.sticky = "1";
  saveSettingToggle(
    els.telegramNotifyInput,
    els.telegramNotifyStatus,
    "telegramNotifyEnabled",
    "알림 설정 저장 실패",
  );
});

els.outputHumanizeInput?.addEventListener("change", () => {
  saveSettingToggle(
    els.outputHumanizeInput,
    els.outputHumanizeStatus,
    "outputHumanizeEnabled",
    "출력 변환 설정 저장 실패",
  );
});

restoreEventPanelVisibility();

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
