const state = {
  project: null,
  browser: null,
  activeBranch: null,
  branches: [],
  views: [],
  payload: null,
  provider: null,
};

const els = {
  projectSummary: document.querySelector("#projectSummary"),
  projectForm: document.querySelector("#projectForm"),
  projectPathInput: document.querySelector("#projectPathInput"),
  openProjectButton: document.querySelector("#openProjectButton"),
  initProjectButton: document.querySelector("#initProjectButton"),
  browseProjectButton: document.querySelector("#browseProjectButton"),
  projectStatus: document.querySelector("#projectStatus"),
  recentProjects: document.querySelector("#recentProjects"),
  projectBrowser: document.querySelector("#projectBrowser"),
  branchList: document.querySelector("#branchList"),
  viewList: document.querySelector("#viewList"),
  gitSummary: document.querySelector("#gitSummary"),
  providerSummary: document.querySelector("#providerSummary"),
  providerSettings: document.querySelector("#providerSettings"),
  webSearchInput: document.querySelector("#webSearchInput"),
  timeoutSecondsInput: document.querySelector("#timeoutSecondsInput"),
  saveProviderButton: document.querySelector("#saveProviderButton"),
  providerSettingsStatus: document.querySelector("#providerSettingsStatus"),
  activeTitle: document.querySelector("#activeTitle"),
  activeMeta: document.querySelector("#activeMeta"),
  messageList: document.querySelector("#messageList"),
  reportView: document.querySelector("#reportView"),
  trackedFiles: document.querySelector("#trackedFiles"),
  historyLog: document.querySelector("#historyLog"),
  currentDiff: document.querySelector("#currentDiff"),
  researchList: document.querySelector("#researchList"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  appendOnlyButton: document.querySelector("#appendOnlyButton"),
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

function renderInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
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
  els.trackedFiles.innerHTML = "";
  els.historyLog.textContent = "";
  els.currentDiff.textContent = "";
  els.researchList.innerHTML = "";
  els.gitSummary.innerHTML = "";
  els.providerSummary.innerHTML = "";
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
  els.recentProjects.innerHTML =
    (project?.recent || [])
      .map(
        (recentPath) => `
          <button class="recent-project" data-project-path="${escapeHtml(recentPath)}" type="button">
            ${escapeHtml(recentPath)}
          </button>
        `,
      )
      .join("");
  els.recentProjects.querySelectorAll("[data-project-path]").forEach((button) => {
    button.addEventListener("click", async () => {
      els.projectPathInput.value = button.dataset.projectPath;
      await openProject(button.dataset.projectPath, { init: false });
    });
  });
}

function renderBrowser(browser) {
  state.browser = browser;
  els.projectBrowser.innerHTML = `
    <div class="browser-path">${escapeHtml(browser.path)}</div>
    <div class="browser-row">
      <button class="browser-button" data-browse-path="${escapeHtml(browser.parent || browser.path)}" type="button">..</button>
      <button class="browser-button" data-use-path="${escapeHtml(browser.path)}" type="button">Use</button>
    </div>
    ${browser.entries
      .map(
        (entry) => `
          <div class="browser-row">
            <button class="browser-button" data-browse-path="${escapeHtml(entry.path)}" type="button">
              ${escapeHtml(entry.name)}${entry.initialized ? " · ctxgit" : ""}${entry.gitInitialized ? " · git" : ""}
            </button>
            <button class="browser-button" data-use-path="${escapeHtml(entry.path)}" type="button">Use</button>
          </div>
        `,
      )
      .join("")}
  `;
  els.projectBrowser.querySelectorAll("[data-browse-path]").forEach((button) => {
    button.addEventListener("click", () => browseProject(button.dataset.browsePath));
  });
  els.projectBrowser.querySelectorAll("[data-use-path]").forEach((button) => {
    button.addEventListener("click", () => {
      els.projectPathInput.value = button.dataset.usePath;
      setProjectStatus("Path selected. Open or Init/Open.", "");
    });
  });
}

function renderBranches() {
  els.branchList.innerHTML = state.branches
    .map(
      (branch) => `
        <button class="nav-item ${branch.id === state.activeBranch ? "active" : ""}" data-branch="${escapeHtml(branch.id)}" type="button">
          <span class="nav-title">${escapeHtml(branch.title)}</span>
          <span class="nav-meta">${escapeHtml(branch.id)} · ${branch.historyCount} messages</span>
        </button>
      `,
    )
    .join("") || '<div class="muted">No branches yet</div>';
  els.branchList.querySelectorAll("[data-branch]").forEach((button) => {
    button.addEventListener("click", () => loadBranch(button.dataset.branch));
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
  els.providerSummary.innerHTML = `
    <div>Provider: <strong>${escapeHtml(status.provider || "codex")}</strong></div>
    <div>${escapeHtml(status.message || status.status || "")}</div>
    <div class="muted">Web search: ${webSearch} · Timeout: ${escapeHtml(String(timeoutSeconds))}s</div>
    ${
      status.ok
        ? ""
        : `<div class="muted">Login: <code>${escapeHtml(status.loginCommand || "codex login --device-auth")}</code></div>`
    }
  `;
  els.webSearchInput.checked = webSearch === "on";
  els.timeoutSecondsInput.value = timeoutSeconds;
  els.providerSettingsStatus.textContent = "";
  els.providerSettingsStatus.className = "settings-status";
}

function renderArtifacts(artifacts) {
  if (!Array.isArray(artifacts) || artifacts.length === 0) return "";
  return `
    <div class="artifact-links">
      ${artifacts
        .map(
          (artifact) =>
            `<div>${escapeHtml(artifact.kind || "artifact")}: <code>${escapeHtml(artifact.path || "")}</code></div>`,
        )
        .join("")}
    </div>
  `;
}

function renderBranch(payload) {
  state.payload = payload;
  const meta = payload.meta;
  els.activeTitle.textContent = meta.title || meta.id;
  els.activeMeta.textContent = `${meta.id} · history.jsonl is Git-tracked conversation history`;

  els.messageList.innerHTML =
    payload.history
      .map(
        (message) => `
          <article class="message">
            <div class="message-header">
              <span class="message-role">${escapeHtml(message.role)}</span>
              <span>${escapeHtml(message.createdAt)}</span>
            </div>
            <div class="message-text">${escapeHtml(message.text)}</div>
            ${renderArtifacts(message.artifacts)}
          </article>
        `,
      )
      .join("") || '<div class="muted">No messages yet.</div>';

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
    [...(payload.research || []), ...(payload.artifacts || [])]
      .map(
        (doc) => `
          <div class="document-item">
            <strong>${escapeHtml(doc.title)}</strong>
            <div class="nav-meta">${escapeHtml(doc.path)}</div>
          </div>
        `,
      )
      .join("") || '<div class="muted">No research notes yet.</div>';
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
  }
}

async function browseProject(path) {
  try {
    const browser = await api(`/api/project/browse?path=${encodeURIComponent(path || els.projectPathInput.value)}`);
    renderBrowser(browser);
    setProjectStatus("Choose a directory, then Open or Init/Open.", "");
  } catch (error) {
    setProjectStatus(`Browse failed: ${error.message}`, "error");
  }
}

async function loadBranch(branch) {
  state.activeBranch = branch;
  renderBranches();
  const payload = await api(`/api/branch?id=${encodeURIComponent(branch)}`);
  renderBranch(payload);
  const git = await api("/api/git/status");
  renderGit(git);
  renderProvider(await api("/api/provider/status"));
}

async function loadView(view) {
  const payload = await api(`/api/view?id=${encodeURIComponent(view)}`);
  state.activeBranch = null;
  renderBranches();
  els.activeTitle.textContent = payload.id;
  els.activeMeta.textContent = payload.path;
  els.reportView.innerHTML = renderMarkdown(payload.text);
  document.querySelector('[data-tab="report"]').click();
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}Tab`).classList.add("active");
  });
});

els.projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await openProject(els.projectPathInput.value.trim(), { init: false });
});

els.initProjectButton.addEventListener("click", async () => {
  await openProject(els.projectPathInput.value.trim(), { init: true });
});

els.browseProjectButton.addEventListener("click", async () => {
  await browseProject(els.projectPathInput.value.trim());
});

async function sendComposerMessage({ ai }) {
  if (!state.activeBranch) return;
  const text = els.messageInput.value.trim();
  if (!text) return;
  els.sendButton.disabled = true;
  els.appendOnlyButton.disabled = true;
  const previousTitle = els.sendButton.textContent;
  els.sendButton.textContent = ai ? "Thinking" : "Saving";
  try {
    const payload = await api(ai ? "/api/chat" : "/api/append", {
      method: "POST",
      body: JSON.stringify(
        ai
          ? { branch: state.activeBranch, text, provider: "codex" }
          : { branch: state.activeBranch, role: "user", text },
      ),
    });
    els.messageInput.value = "";
    renderBranch(payload);
    renderGit(await api("/api/git/status"));
    renderProvider(await api("/api/provider/status"));
  } catch (error) {
    const isTimeout = error instanceof ApiError && error.payload?.error === "timeout";
    const prefix = isTimeout ? "Timeout" : "Chat failed";
    els.messageList.insertAdjacentHTML(
      "beforebegin",
      `<div class="error-banner">${prefix}: ${escapeHtml(error.message)}</div>`,
    );
  } finally {
    els.sendButton.disabled = false;
    els.appendOnlyButton.disabled = false;
    els.sendButton.textContent = previousTitle;
  }
}

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendComposerMessage({ ai: true });
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
          timeoutSeconds,
          webSearch: els.webSearchInput.checked,
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

els.appendOnlyButton.addEventListener("click", async () => {
  await sendComposerMessage({ ai: false });
});

els.refreshButton.addEventListener("click", async () => {
  await loadProject();
});

loadProject()
  .catch((error) => {
    els.activeTitle.textContent = "Could not load ctxgit project";
    els.activeMeta.textContent = error.message;
  });
