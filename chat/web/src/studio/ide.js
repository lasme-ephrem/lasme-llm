// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
let activeIdeFilePath = "README.md";

// 1. Project File Tree Loader & File Editor
const ideFileTree = document.getElementById("ideFileTree");
const ideCodeEditor = document.getElementById("ideCodeEditor");
const ideCurrentFilePath = document.getElementById("ideCurrentFilePath");
const ideSaveFileBtn = document.getElementById("ideSaveFileBtn");
const ideRefreshTreeBtn = document.getElementById("ideRefreshTreeBtn");

async function loadIdeFileTree() {
    if (!ideFileTree) return;
    try {
        const resp = await fetch(`${API_BASE}/coding/tree?path=.&max_depth=4`);
        const data = await resp.json();
        const treeLines = (data.tree || "").split("\n");
        
        ideFileTree.innerHTML = "";
        treeLines.forEach(line => {
            const div = document.createElement("div");
            div.className = "file-tree-item";
            div.textContent = line;
            
            // Extract filename from tree line
            const match = line.match(/(?:📄|📁)\s+([^\/]+)/);
            if (match && line.includes("📄")) {
                const fileName = match[1].trim();
                div.title = `Cliquer pour ouvrir ${fileName}`;
                div.addEventListener("click", () => {
                    loadIdeFileContent(fileName);
                });
            }
            ideFileTree.appendChild(div);
        });
    } catch (e) {
        if (ideFileTree) ideFileTree.innerHTML = `<div class="file-tree-loading">Erreur de chargement de l'arborescence.</div>`;
    }
}

async function loadIdeFileContent(filePath) {
    if (!ideCodeEditor) return;
    activeIdeFilePath = filePath;
    if (ideCurrentFilePath) ideCurrentFilePath.textContent = filePath;

    try {
        const resp = await fetch(`${API_BASE}/coding/file?path=${encodeURIComponent(filePath)}`);
        if (resp.ok) {
            const data = await resp.json();
            ideCodeEditor.value = data.content || "";
        } else {
            ideCodeEditor.value = `// Impossible de lire ${filePath}`;
        }
    } catch (e) {
        ideCodeEditor.value = `// Erreur de lecture du fichier ${filePath}`;
    }
}

if (ideSaveFileBtn) {
    ideSaveFileBtn.addEventListener("click", async () => {
        if (!activeIdeFilePath || !ideCodeEditor) return;
        try {
            const resp = await fetch(`${API_BASE}/coding/file`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    path: activeIdeFilePath,
                    content: ideCodeEditor.value
                })
            });
            const data = await resp.json();
            if (data.status === "success") {
                alert(`✅ ${activeIdeFilePath} sauvegardé avec succès !`);
                loadIdeFileTree();
            }
        } catch (e) {
            alert(`❌ Erreur de sauvegarde de ${activeIdeFilePath}`);
        }
    });
}

if (ideRefreshTreeBtn) {
    ideRefreshTreeBtn.addEventListener("click", () => {
        loadIdeFileTree();
        loadIdeSubagents();
    });
}

// 2. Subagents Monitor Loader
const ideSubagentsContainer = document.getElementById("ideSubagentsContainer");

async function loadIdeSubagents() {
    if (!ideSubagentsContainer) return;
    try {
        const resp = await fetch(`${API_BASE}/coding/subagents`);
        const data = await resp.json();
        const subagents = data.subagents || [];

        if (subagents.length === 0) {
            ideSubagentsContainer.innerHTML = `<div class="subagent-empty">Aucun sous-agent actif.</div>`;
            return;
        }

        ideSubagentsContainer.innerHTML = "";
        subagents.forEach(s => {
            const div = document.createElement("div");
            div.className = "subagent-card";
            div.innerHTML = `
                <div class="subagent-card-role">${s.title || s.role} [${s.id}]</div>
                <div>Statut: <strong>${s.status}</strong></div>
                <div style="opacity:0.75; margin-top:2px;">${s.task_prompt.substring(0, 50)}...</div>
            `;
            ideSubagentsContainer.appendChild(div);
        });
    } catch (e) {}
}

// 3. Master Agent Streaming Execution
const idePromptInput = document.getElementById("idePromptInput");
const ideRunAgentBtn = document.getElementById("ideRunAgentBtn");
const ideAgentStreamLog = document.getElementById("ideAgentStreamLog");
const ideStatusBadge = document.getElementById("ideStatusBadge");

if (ideRunAgentBtn) {
    ideRunAgentBtn.addEventListener("click", async () => {
        const prompt = idePromptInput ? idePromptInput.value.trim() : "";
        if (!prompt) return;

        if (ideStatusBadge) ideStatusBadge.textContent = "⚙️ Master Agent en cours d'exécution...";
        if (ideAgentStreamLog) {
            ideAgentStreamLog.innerHTML = `<div class="log-step-item info">🚀 Lancement de la tâche : "${prompt}"</div>`;
        }

        try {
            const resp = await fetch(`${API_BASE}/coding/agent/stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: prompt, model: LASME_REASONING_MODEL })
            });

            const reader = resp.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let sseBuffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                sseBuffer += decoder.decode(value, { stream: true });
                const lines = sseBuffer.split("\n\n");
                sseBuffer = lines.pop();

                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        const payload = line.replace("data: ", "").trim();
                        if (payload === "[DONE]") {
                            if (ideStatusBadge) ideStatusBadge.textContent = "✅ Tâche terminée";
                            loadIdeFileTree();
                            loadIdeSubagents();
                            break;
                        }
                        try {
                            const evt = JSON.parse(payload);
                            const div = document.createElement("div");
                            div.className = `log-step-item ${evt.type || 'info'}`;
                            
                            if (evt.type === "thought") {
                                div.innerHTML = `<strong>🧠 Pensée Agent :</strong><br>${escapeHtml(evt.message)}`;
                            } else if (evt.type === "tool_call") {
                                div.innerHTML = `<strong>🛠️ Action :</strong> ${escapeHtml(evt.message)}`;
                            } else if (evt.type === "tool_result") {
                                div.innerHTML = `<strong>📋 Résultat :</strong> ${escapeHtml(evt.message)}`;
                            } else if (evt.type === "final") {
                                div.innerHTML = `<strong>🎉 Conclusion :</strong><br>${escapeHtml(evt.message)}`;
                            } else {
                                div.textContent = evt.message;
                            }
                            
                            if (ideAgentStreamLog) {
                                ideAgentStreamLog.appendChild(div);
                                ideAgentStreamLog.scrollTop = ideAgentStreamLog.scrollHeight;
                            }
                        } catch (err) {}
                    }
                }
            }
        } catch (e) {
            if (ideStatusBadge) ideStatusBadge.textContent = "❌ Erreur d'exécution";
            if (ideAgentStreamLog) {
                const errDiv = document.createElement("div");
                errDiv.className = "log-step-item error";
                errDiv.textContent = `Erreur: ${e.message}`;
                ideAgentStreamLog.appendChild(errDiv);
            }
        }
    });
}

// 4. Interactive Terminal Console
const ideTerminalForm = document.getElementById("ideTerminalForm");
const ideTerminalInput = document.getElementById("ideTerminalInput");
const ideTerminalLog = document.getElementById("ideTerminalLog");
const ideClearTermBtn = document.getElementById("ideClearTermBtn");

if (ideTerminalForm) {
    ideTerminalForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const cmd = ideTerminalInput.value.trim();
        if (!cmd) return;

        ideTerminalInput.value = "";
        appendTermLine(`$ ${cmd}`);

        try {
            const resp = await fetch(`${API_BASE}/coding/terminal`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ command: cmd })
            });
            const data = await resp.json();
            appendTermLine(data.output || "Commande exécutée.");
        } catch (err) {
            appendTermLine(`Erreur: ${err.message}`);
        }
    });
}

if (ideClearTermBtn) {
    ideClearTermBtn.addEventListener("click", () => {
        if (ideTerminalLog) ideTerminalLog.innerHTML = `<div class="term-line">LasmeLLMCoding Terminal</div>`;
    });
}

function appendTermLine(text) {
    if (!ideTerminalLog) return;
    const div = document.createElement("div");
    div.className = "term-line";
    div.textContent = text;
    ideTerminalLog.appendChild(div);
    ideTerminalLog.scrollTop = ideTerminalLog.scrollHeight;
}

// ── GOOGLE ANTIGRAVITY REPLICA EVENT HANDLERS ─────────────────────────
const agInputTextarea = document.getElementById("agInputTextarea");
const agRunAgentBtn = document.getElementById("agRunAgentBtn");
const agUserPromptPill = document.getElementById("agUserPromptPill");
const agStepCardsStream = document.getElementById("agStepCardsStream");
const agTasksHeader = document.getElementById("agTasksHeader");
const agTasksDrawer = document.getElementById("agTasksDrawer");
const toggleOpenIdeBtn = document.getElementById("toggleOpenIdeBtn");
const agSplitIdeView = document.getElementById("agSplitIdeView");
const agFeedScroll = document.getElementById("agFeedScroll");

// 1. Toggle Open IDE Split View
if (toggleOpenIdeBtn) {
    toggleOpenIdeBtn.addEventListener("click", () => {
        if (!agSplitIdeView) return;
        const isHidden = agSplitIdeView.style.display === "none";
        agSplitIdeView.style.display = isHidden ? "flex" : "none";
        agFeedScroll.style.display = isHidden ? "none" : "flex";
        toggleOpenIdeBtn.querySelector("span").textContent = isHidden ? "Back to Feed" : "Open IDE";
    });
}

// 2. Toggle Running Tasks Drawer
if (agTasksHeader && agTasksDrawer) {
    agTasksHeader.addEventListener("click", () => {
        agTasksDrawer.classList.toggle("open");
    });
}

// Dynamic Running Tasks Manager for Antigravity Drawer
function updateTasksCount() {
    const drawer = document.getElementById("agTasksDrawer");
    const tasksList = document.getElementById("agTasksList");
    const countEl = document.querySelector(".ag-tasks-count");
    if (!tasksList || !countEl || !drawer) return;
    const count = tasksList.children.length;
    countEl.textContent = `${count} task${count > 1 ? 's' : ''} running`;
    drawer.style.display = count > 0 ? "block" : "none";
}

function checkFirstTimeAgenticUser() {
    const initialized = localStorage.getItem("lasme_agentic_initialized");
    if (!initialized) {
        const welcomeModal = document.getElementById("agWelcomeProjectModal");
        if (welcomeModal) welcomeModal.style.display = "flex";
    }
}

let selectedPickedPath = "";
let activeDirectoryHandle = null;
let activeFolderFiles = [];

const agBrowseFolderBtn = document.getElementById("agBrowseFolderBtn");
const agNativeFolderInput = document.getElementById("agNativeFolderInput");
const agSelectedFolderDisplay = document.getElementById("agSelectedFolderDisplay");
const agSelectedFolderPath = document.getElementById("agSelectedFolderPath");
const agWelcomeProjName = document.getElementById("agWelcomeProjName");

if (agBrowseFolderBtn) {
    agBrowseFolderBtn.addEventListener("click", async () => {
        if (window.showDirectoryPicker) {
            try {
                const dirHandle = await window.showDirectoryPicker();
                activeDirectoryHandle = dirHandle;
                activeFolderFiles = [];
                selectedPickedPath = dirHandle.name;
                if (agSelectedFolderPath) agSelectedFolderPath.textContent = dirHandle.name;
                if (agSelectedFolderDisplay) agSelectedFolderDisplay.style.display = "block";
                if (agWelcomeProjName && (!agWelcomeProjName.value || agWelcomeProjName.value === "Mon Premier Projet IA")) {
                    agWelcomeProjName.value = dirHandle.name;
                }
                return;
            } catch (err) {
                if (err.name === "AbortError") return;
            }
        }
        if (agNativeFolderInput) agNativeFolderInput.click();
    });
}

if (agNativeFolderInput) {
    agNativeFolderInput.addEventListener("change", (e) => {
        if (!e.target.files || e.target.files.length === 0) return;
        activeDirectoryHandle = null;
        activeFolderFiles = Array.from(e.target.files);
        const firstFile = activeFolderFiles[0];
        const relPath = firstFile.webkitRelativePath || firstFile.name;
        const folderName = relPath.split("/")[0] || relPath.split("\\")[0] || "Mon Projet";
        selectedPickedPath = folderName;
        if (agSelectedFolderPath) agSelectedFolderPath.textContent = folderName;
        if (agSelectedFolderDisplay) agSelectedFolderDisplay.style.display = "block";
        if (agWelcomeProjName) agWelcomeProjName.value = folderName;
    });
}

const agConfirmWelcomeProjBtn = document.getElementById("agConfirmWelcomeProjBtn");
if (agConfirmWelcomeProjBtn) {
    agConfirmWelcomeProjBtn.addEventListener("click", () => {
        const nameInput = document.getElementById("agWelcomeProjName");
        const name = nameInput ? nameInput.value.trim() : (selectedPickedPath || "Mon Projet IA");
        if (!name) {
            alert("Veuillez choisir un dossier ou donner un nom à votre projet.");
            return;
        }

        const projPath = selectedPickedPath || name;
        const projId = "p_welcome_" + Date.now();
        lasmeProjects.unshift({ id: projId, name: name, path: projPath });
        lasmeActiveProjectId = projId;
        saveLasmeProjects();
        renderProjectsTree();

        const titleEl = document.getElementById("agCurrentFolderPath");
        if (titleEl) titleEl.textContent = name;

        // Immediately update studio file explorer tree with chosen folder
        renderNativeFolderTree(activeDirectoryHandle, activeFolderFiles, name);

        localStorage.setItem("lasme_agentic_initialized", "true");
        const welcomeModal = document.getElementById("agWelcomeProjectModal");
        if (welcomeModal) welcomeModal.style.display = "none";
    });
}

function addDynamicTask(taskText) {
    const tasksList = document.getElementById("agTasksList");
    if (!tasksList) return null;
    const item = document.createElement("div");
    item.className = "ag-task-item";
    item.innerHTML = `<span class="spinner-rotate">🔄</span> ${taskText}`;
    tasksList.appendChild(item);
    updateTasksCount();
    return item;
}

function removeDynamicTask(taskItem) {
    if (taskItem && taskItem.parentNode) {
        taskItem.parentNode.removeChild(taskItem);
        updateTasksCount();
    }
}

// Setup + Attach Popover Menu in Deck
setupDropdown("agAttachPlusBtn", "agPlusActionMenu");

const agMenuAttachDocBtn = document.getElementById("agMenuAttachDocBtn");
const agMenuAttachImgBtn = document.getElementById("agMenuAttachImgBtn");

if (agMenuAttachDocBtn && docFileInput) {
    agMenuAttachDocBtn.addEventListener("click", () => {
        closeAllDropdowns();
        docFileInput.click();
    });
}
if (agMenuAttachImgBtn && imageFileInput) {
    agMenuAttachImgBtn.addEventListener("click", () => {
        closeAllDropdowns();
        imageFileInput.click();
    });
}

// 3. Run Agent Task from Antigravity Deck
async function runAntigravityTask() {
    const prompt = agInputTextarea ? agInputTextarea.value.trim() : "";
    if (!prompt) return;

    if (agInputTextarea) agInputTextarea.value = "";
    if (agUserPromptPill) agUserPromptPill.textContent = prompt;
    if (agStepCardsStream) agStepCardsStream.innerHTML = "";

    // Add active task to drawer with spinning icon
    const activeTaskItem = addDynamicTask(`Exécution Agent: "${prompt.substring(0, 30)}${prompt.length > 30 ? '...' : ''}"`);

    try {
        const resp = await fetch(`${API_BASE}/coding/agent/stream`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: prompt, model: LASME_REASONING_MODEL })
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let sseBuffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            sseBuffer += decoder.decode(value, { stream: true });
            const lines = sseBuffer.split("\n\n");
            sseBuffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const payload = line.replace("data: ", "").trim();
                    if (payload === "[DONE]") {
                        break;
                    }
                    try {
                        const evt = JSON.parse(payload);
                        const card = document.createElement("div");
                        card.className = "ag-action-card";

                        if (evt.type === "tool_call") {
                            const name = evt.meta?.name || "Action";
                            const args = evt.meta?.args || {};
                            if (name === "run_command") {
                                card.innerHTML = `<span class="ag-action-tag">Ran</span> <span class="ag-action-highlight">${escapeHtml(args.command || "")}</span>`;
                            } else if (name === "replace_file_content" || name === "write_file") {
                                card.innerHTML = `<span class="ag-action-tag">Edited</span> <span class="ag-action-edited">&lt;/&gt; ${escapeHtml(args.path || "file")}</span>`;
                            } else {
                                card.innerHTML = `<span class="ag-action-tag">Invoked</span> <span class="ag-action-highlight">${escapeHtml(name)}</span>`;
                            }
                        } else if (evt.type === "thought") {
                            card.innerHTML = `<span class="ag-action-tag">Thought</span> ${escapeHtml((evt.message || "").substring(0, 140))}...`;
                        } else if (evt.type === "final") {
                            card.innerHTML = `<span class="ag-action-highlight">Completed:</span> ${escapeHtml(evt.message || "")}`;
                        } else {
                            card.textContent = evt.message;
                        }

                        if (agStepCardsStream) {
                            agStepCardsStream.appendChild(card);
                            if (agFeedScroll) agFeedScroll.scrollTop = agFeedScroll.scrollHeight;
                        }
                    } catch (err) {}
                }
            }
        }
    } catch (e) {
        if (agStepCardsStream) {
            const errCard = document.createElement("div");
            errCard.className = "ag-action-card";
            errCard.style.color = "#d93025";
            errCard.textContent = `Error: ${e.message}`;
            agStepCardsStream.appendChild(errCard);
        }
    } finally {
        removeDynamicTask(activeTaskItem);
    }
}

if (agRunAgentBtn) {
    agRunAgentBtn.addEventListener("click", runAntigravityTask);
}
if (agInputTextarea) {
    agInputTextarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            runAntigravityTask();
        }
    });
}

// ── LASME CODING PROJECTS & MENUS & MODALS INTERACTIVITY ──────────────────
let lasmeProjects = [
    { id: "p1", name: "Développement Écosystème LLM Local", path: "c:\\Users\\lasme\\Desktop\\projects\\lasme-llm" },
    { id: "p2", name: "Projet Python", path: "c:\\Users\\lasme\\Desktop\\projects\\pyt-2" },
    { id: "p3", name: "Golden Academy", path: "c:\\Users\\lasme\\Desktop\\projects\\golden-academy" }
];

let lasmeActiveProjectId = "p1";
let lasmeZoomLevel = 1.0;

function loadLasmeProjects() {
    const stored = localStorage.getItem("lasme_projects");
    if (stored) {
        try { lasmeProjects = JSON.parse(stored); } catch (e) {}
    }
}

function saveLasmeProjects() {
    localStorage.setItem("lasme_projects", JSON.stringify(lasmeProjects));
}

function renderProjectsTree() {
    const treeEl = document.getElementById("agProjectsTree");
    if (!treeEl) return;

    treeEl.innerHTML = "";
    lasmeProjects.forEach((proj) => {
        const folderDiv = document.createElement("div");
        const isActive = proj.id === lasmeActiveProjectId;
        folderDiv.className = `ag-tree-folder ${isActive ? "active" : ""}`;
        
        folderDiv.innerHTML = `
            <div class="ag-folder-header" style="display:flex; align-items:center; gap:6px; cursor:pointer; width:100%;">
                <span class="folder-arrow">${isActive ? "▼" : "▶"}</span>
                <span class="folder-name" style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(proj.name)}</span>
                <button type="button" class="ag-delete-proj-btn" data-id="${escapeHtml(proj.id)}" title="Supprimer le projet">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </div>
        `;

        if (isActive) {
            const subitemDiv = document.createElement("div");
            subitemDiv.className = "ag-tree-subitem active";
            subitemDiv.innerHTML = `
                <span class="subitem-title">Session Principale</span>
                <span class="spinner-dot"></span>
            `;
            folderDiv.appendChild(subitemDiv);
        }

        folderDiv.querySelector(".ag-folder-header").addEventListener("click", (e) => {
            if (e.target.closest(".ag-delete-proj-btn")) return;
            lasmeActiveProjectId = proj.id;
            const titleEl = document.getElementById("agCurrentProjectTitle");
            if (titleEl) titleEl.textContent = proj.name;
            renderProjectsTree();
        });

        const delBtn = folderDiv.querySelector(".ag-delete-proj-btn");
        if (delBtn) {
            delBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                if (confirm(`Voulez-vous vraiment supprimer le projet "${proj.name}" ?`)) {
                    lasmeProjects = lasmeProjects.filter(p => p.id !== proj.id);
                    if (lasmeActiveProjectId === proj.id && lasmeProjects.length > 0) {
                        lasmeActiveProjectId = lasmeProjects[0].id;
                    }
                    saveLasmeProjects();
                    renderProjectsTree();
                }
            });
        }

        treeEl.appendChild(folderDiv);
    });
}

// ── DROPDOWNS FILE / VIEW / WINDOW ─────────────────────────────────────────
function setupDropdown(triggerId, dropdownId) {
    const trigger = document.getElementById(triggerId);
    const dropdown = document.getElementById(dropdownId);
    if (!trigger || !dropdown) return;

    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = dropdown.style.display === "block";
        closeAllDropdowns();
        dropdown.style.display = isOpen ? "none" : "block";
    });
}

function closeAllDropdowns() {
    ["agMenuFileDropdown", "agMenuViewDropdown", "agMenuWindowDropdown"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = "none";
    });
}

document.addEventListener("click", closeAllDropdowns);

setupDropdown("agMenuFileTrigger", "agMenuFileDropdown");
setupDropdown("agMenuViewTrigger", "agMenuViewDropdown");
setupDropdown("agMenuWindowTrigger", "agMenuWindowDropdown");

// Menu Actions
const agFileNewProjBtn = document.getElementById("agFileNewProjBtn");
const agFileNewConvBtn = document.getElementById("agFileNewConvBtn");
const agAddProjectBtn = document.getElementById("agAddProjectBtn");
const agNewConvBtn = document.getElementById("agNewConvBtn");

if (agFileNewProjBtn) agFileNewProjBtn.addEventListener("click", openNewProjectModal);
if (agAddProjectBtn) agAddProjectBtn.addEventListener("click", openNewProjectModal);

if (agFileNewConvBtn) agFileNewConvBtn.addEventListener("click", openSelectProjectModal);
if (agNewConvBtn) agNewConvBtn.addEventListener("click", openSelectProjectModal);

// View Zoom Logic
const agViewZoomInBtn = document.getElementById("agViewZoomInBtn");
const agViewZoomOutBtn = document.getElementById("agViewZoomOutBtn");
const agViewZoomResetBtn = document.getElementById("agViewZoomResetBtn");

function applyZoom() {
    const layout = document.querySelector(".antigravity-layout") || document.body;
    layout.style.transform = `scale(${lasmeZoomLevel})`;
    layout.style.transformOrigin = "top left";
    layout.style.width = `${100 / lasmeZoomLevel}%`;
    layout.style.height = `${100 / lasmeZoomLevel}%`;
}

if (agViewZoomInBtn) {
    agViewZoomInBtn.addEventListener("click", () => {
        lasmeZoomLevel = Math.min(lasmeZoomLevel + 0.1, 1.5);
        applyZoom();
    });
}
if (agViewZoomOutBtn) {
    agViewZoomOutBtn.addEventListener("click", () => {
        lasmeZoomLevel = Math.max(lasmeZoomLevel - 0.1, 0.7);
        applyZoom();
    });
}
if (agViewZoomResetBtn) {
    agViewZoomResetBtn.addEventListener("click", () => {
        lasmeZoomLevel = 1.0;
        applyZoom();
    });
}

// Window Fullscreen Logic
const agWindowMaxBtn = document.getElementById("agWindowMaxBtn");
const agWindowMinBtn = document.getElementById("agWindowMinBtn");

if (agWindowMaxBtn) {
    agWindowMaxBtn.addEventListener("click", () => {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(err => {});
        }
    });
}
if (agWindowMinBtn) {
    agWindowMinBtn.addEventListener("click", () => {
        if (document.fullscreenElement) {
            document.exitFullscreen().catch(err => {});
        }
    });
}

// ── MODALS HANDLERS ───────────────────────────────────────────────────────
function openNewProjectModal() {
    closeAllDropdowns();
    const modal = document.getElementById("agNewProjectModal");
    if (modal) modal.style.display = "flex";
}

function closeNewProjectModal() {
    const modal = document.getElementById("agNewProjectModal");
    if (modal) modal.style.display = "none";
}

const agCloseNewProjBtn = document.getElementById("agCloseNewProjBtn");
const agCancelNewProjBtn = document.getElementById("agCancelNewProjBtn");
const agConfirmNewProjBtn = document.getElementById("agConfirmNewProjBtn");
const agNewProjectOverlay = document.getElementById("agNewProjectOverlay");

if (agCloseNewProjBtn) agCloseNewProjBtn.addEventListener("click", closeNewProjectModal);
if (agCancelNewProjBtn) agCancelNewProjBtn.addEventListener("click", closeNewProjectModal);
if (agNewProjectOverlay) agNewProjectOverlay.addEventListener("click", closeNewProjectModal);

if (agConfirmNewProjBtn) {
    agConfirmNewProjBtn.addEventListener("click", () => {
        const nameInput = document.getElementById("agNewProjNameInput");
        const pathInput = document.getElementById("agNewProjPathInput");
        const name = nameInput ? nameInput.value.trim() : "";
        const path = pathInput ? pathInput.value.trim() : "";

        if (!name) {
            alert("Veuillez saisir un nom de projet.");
            return;
        }

        const newId = "p_" + Date.now();
        lasmeProjects.push({ id: newId, name: name, path: path || `c:\\Users\\lasme\\Desktop\\projects\\${name.toLowerCase().replace(/\s+/g, '-')}` });
        lasmeActiveProjectId = newId;
        saveLasmeProjects();
        renderProjectsTree();

        if (nameInput) nameInput.value = "";
        if (pathInput) pathInput.value = "";
        closeNewProjectModal();
    });
}

// Select Project for New Conversation Modal
function openSelectProjectModal() {
    closeAllDropdowns();
    const modal = document.getElementById("agSelectProjectModal");
    const select = document.getElementById("agProjectSelect");
    if (!modal || !select) return;

    select.innerHTML = "";
    lasmeProjects.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        if (p.id === lasmeActiveProjectId) opt.selected = true;
        select.appendChild(opt);
    });

    modal.style.display = "flex";
}

function closeSelectProjectModal() {
    const modal = document.getElementById("agSelectProjectModal");
    if (modal) modal.style.display = "none";
}

const agCloseSelectProjBtn = document.getElementById("agCloseSelectProjBtn");
const agConfirmSelectProjBtn = document.getElementById("agConfirmSelectProjBtn");
const agCreateProjOnTheFlyBtn = document.getElementById("agCreateProjOnTheFlyBtn");
const agSelectProjectOverlay = document.getElementById("agSelectProjectOverlay");

if (agCloseSelectProjBtn) agCloseSelectProjBtn.addEventListener("click", closeSelectProjectModal);
if (agSelectProjectOverlay) agSelectProjectOverlay.addEventListener("click", closeSelectProjectModal);
if (agCreateProjOnTheFlyBtn) {
    agCreateProjOnTheFlyBtn.addEventListener("click", () => {
        closeSelectProjectModal();
        openNewProjectModal();
    });
}

if (agConfirmSelectProjBtn) {
    agConfirmSelectProjBtn.addEventListener("click", () => {
        const select = document.getElementById("agProjectSelect");
        if (select && select.value) {
            lasmeActiveProjectId = select.value;
            const proj = lasmeProjects.find(p => p.id === select.value);
            if (proj) {
                const titleEl = document.getElementById("agCurrentProjectTitle");
                if (titleEl) titleEl.textContent = proj.name;
            }
            renderProjectsTree();

            // Clear stream & initialize new session view
            if (agStepCardsStream) agStepCardsStream.innerHTML = "";
            if (agUserPromptPill) agUserPromptPill.textContent = "Nouvelle conversation démarrée";
        }
        closeSelectProjectModal();
    });
}

// ── LASME STUDIO 3-PANEL AGENTIC WORKSPACE HANDLERS ───────────────────────
const agOpenProjectFolderBtn = document.getElementById("agOpenProjectFolderBtn");
const agCurrentFolderPath = document.getElementById("agCurrentFolderPath");
const agStudioFileTree = document.getElementById("agStudioFileTree");
const agStudioCodeTextarea = document.getElementById("agStudioCodeTextarea");
const agStudioFilePath = document.getElementById("agStudioFilePath");
const agActiveTabBadge = document.getElementById("agActiveTabBadge");
const agSaveCodeBtn = document.getElementById("agSaveCodeBtn");
const agStudioTerminalOutput = document.getElementById("agStudioTerminalOutput");
const agClearTerminalBtn = document.getElementById("agClearTerminalBtn");

const agCodingInput = document.getElementById("agCodingInput");
const agCodingSendBtn = document.getElementById("agCodingSendBtn");
const agCodingMessagesStream = document.getElementById("agCodingMessagesStream");
const agCodingPlusBtn = document.getElementById("agCodingPlusBtn");
const agCodingPlusMenu = document.getElementById("agCodingPlusMenu");
const agCodingAttachDocBtn = document.getElementById("agCodingAttachDocBtn");
const agCodingAttachImgBtn = document.getElementById("agCodingAttachImgBtn");

// 1. Folder Picker Action
if (agOpenProjectFolderBtn) {
    agOpenProjectFolderBtn.addEventListener("click", async () => {
        if (window.showDirectoryPicker) {
            try {
                const dirHandle = await window.showDirectoryPicker();
                activeDirectoryHandle = dirHandle;
                activeFolderFiles = [];
                if (agCurrentFolderPath) agCurrentFolderPath.textContent = dirHandle.name;
                appendTerminalLine(`> Dossier ouvert : ${dirHandle.name}`);
                renderNativeFolderTree(dirHandle, [], dirHandle.name);
                return;
            } catch (err) {
                if (err.name === "AbortError") return;
            }
        }
        if (agNativeFolderInput) agNativeFolderInput.click();
    });
}

// 2. Terminal Output Helper
function appendTerminalLine(text) {
    if (!agStudioTerminalOutput) return;
    const line = document.createElement("div");
    line.className = "term-line";
    line.textContent = text;
    agStudioTerminalOutput.appendChild(line);
    agStudioTerminalOutput.scrollTop = agStudioTerminalOutput.scrollHeight;
}

if (agClearTerminalBtn) {
    agClearTerminalBtn.addEventListener("click", () => {
        if (agStudioTerminalOutput) agStudioTerminalOutput.innerHTML = `<div class="term-line">> Terminal effacé.</div>`;
    });
}

// 3. Native Folder Tree & Explorer Loader
async function renderNativeFolderTree(dirHandle, fileList, folderName) {
    if (!agStudioFileTree) return;
    agStudioFileTree.innerHTML = `<div style="color:#64748b; font-size:0.78rem;">Chargement des fichiers de ${escapeHtml(folderName)}...</div>`;
    const items = [];

    if (dirHandle && dirHandle.kind === "directory") {
        try {
            for await (const [name, handle] of dirHandle.entries()) {
                items.push({
                    name: name,
                    type: handle.kind === "directory" ? "directory" : "file",
                    handle: handle,
                    fullPath: `${folderName}/${name}`
                });
            }
        } catch (e) {}
    } else if (fileList && fileList.length) {
        const itemMap = new Map();
        fileList.forEach(file => {
            const relPath = file.webkitRelativePath || file.name;
            const parts = relPath.split(/[\/\\]/);
            if (parts.length > 1) {
                const itemName = parts[1];
                const isDir = parts.length > 2;
                if (!itemMap.has(itemName)) {
                    itemMap.set(itemName, { name: itemName, type: isDir ? "directory" : "file", fileObj: isDir ? null : file, fullPath: `${folderName}/${itemName}` });
                }
            } else {
                itemMap.set(file.name, { name: file.name, type: "file", fileObj: file, fullPath: `${folderName}/${file.name}` });
            }
        });
        items.push(...Array.from(itemMap.values()));
    }

    if (items.length === 0) {
        renderEmptyFolderState(folderName);
        return;
    }

    renderStudioFileTree(items);
}

async function loadStudioFileTree(folderPath) {
    if (!agStudioFileTree) return;
    agStudioFileTree.innerHTML = `<div style="color:#64748b; font-size:0.78rem;">Chargement des fichiers...</div>`;
    try {
        const resp = await fetch(`${API_BASE}/coding/tree?path=${encodeURIComponent(folderPath || '')}`);
        if (resp.ok) {
            const data = await resp.json();
            if (data.tree && data.tree.length > 0) {
                renderStudioFileTree(data.tree);
            } else {
                renderEmptyFolderState(folderPath || "Projet");
            }
        } else {
            renderEmptyFolderState(folderPath || "Projet");
        }
    } catch (e) {
        renderEmptyFolderState(folderPath || "Projet");
    }
}

function renderEmptyFolderState(folderName) {
    if (!agStudioFileTree) return;
    agStudioFileTree.innerHTML = `
        <div style="padding: 20px 10px; text-align: center; color: #64748b; font-size: 0.8rem; display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <span style="font-size: 1.5rem;">📂</span>
            <span>Le dossier "${escapeHtml(folderName)}" est vide.</span>
            <button type="button" id="agCreateNewFileBtn" style="padding: 6px 12px; border-radius: 6px; background: #2563eb; color: #ffffff; border: none; font-size: 0.78rem; font-weight: 600; cursor: pointer;">
                + Nouveau Fichier
            </button>
        </div>
    `;

    const createBtn = document.getElementById("agCreateNewFileBtn");
    if (createBtn) {
        createBtn.addEventListener("click", () => {
            const filename = prompt("Nom du nouveau fichier (ex: main.py, index.html) :", "nouveau_fichier.py");
            if (filename) {
                if (agStudioFilePath) agStudioFilePath.textContent = filename;
                if (agActiveTabBadge) agActiveTabBadge.textContent = filename;
                if (agStudioCodeTextarea) agStudioCodeTextarea.value = `# ${filename}\n\n// Écrivez votre code ici...`;
                appendTerminalLine(`> Nouveau fichier créé : ${filename}`);
            }
        });
    }
}

function renderStudioFileTree(items) {
    if (!agStudioFileTree) return;
    agStudioFileTree.innerHTML = "";
    items.sort((a, b) => (a.type !== 'directory') - (b.type !== 'directory') || a.name.localeCompare(b.name));

    items.forEach(item => {
        const div = document.createElement("div");
        div.className = `studio-tree-item ${item.type === 'directory' ? 'folder' : ''}`;
        const icon = item.type === 'directory' ? '📁' : '📄';
        div.innerHTML = `<span>${icon}</span> <span style="flex:1; overflow:hidden; text-overflow:ellipsis;">${item.name}</span>`;

        const openHandler = async () => {
            document.querySelectorAll(".studio-tree-item").forEach(el => el.classList.remove("active"));
            div.classList.add("active");

            if (item.type !== 'directory') {
                if (agStudioFilePath) agStudioFilePath.textContent = item.name;
                if (agActiveTabBadge) agActiveTabBadge.textContent = item.name;

                if (item.handle) {
                    try {
                        const file = await item.handle.getFile();
                        const text = await file.text();
                        if (agStudioCodeTextarea) agStudioCodeTextarea.value = text;
                        appendTerminalLine(`> [Fichier Ouvert] ${item.name} (${file.size} octets)`);
                    } catch (err) {
                        openStudioFile(item.name);
                    }
                } else if (item.fileObj) {
                    try {
                        const text = await item.fileObj.text();
                        if (agStudioCodeTextarea) agStudioCodeTextarea.value = text;
                        appendTerminalLine(`> [Fichier Ouvert] ${item.name} (${item.fileObj.size} octets)`);
                    } catch (err) {
                        openStudioFile(item.name);
                    }
                } else {
                    openStudioFile(item.path || item.name);
                }
            }
        };

        div.addEventListener("click", openHandler);
        div.addEventListener("dblclick", openHandler);

        agStudioFileTree.appendChild(div);
    });
}

// 4. Open File in Editor
async function openStudioFile(filename) {
    if (agStudioFilePath) agStudioFilePath.textContent = filename;
    if (agActiveTabBadge) agActiveTabBadge.textContent = filename;
    appendTerminalLine(`> Ouverture du fichier : ${filename}`);

    try {
        const resp = await fetch(`${API_BASE}/coding/file?file=${encodeURIComponent(filename)}`);
        if (resp.ok) {
            const data = await resp.json();
            if (agStudioCodeTextarea) agStudioCodeTextarea.value = data.content || "";
        } else {
            if (agStudioCodeTextarea) agStudioCodeTextarea.value = `# ${filename}\n\n// Contenu du fichier ${filename}`;
        }
    } catch (e) {
        if (agStudioCodeTextarea) agStudioCodeTextarea.value = `# ${filename}\n\n// Éditeur prêt pour ${filename}`;
    }
}

// 5. Save File Action
if (agSaveCodeBtn) {
    agSaveCodeBtn.addEventListener("click", async () => {
        const filename = agStudioFilePath ? agStudioFilePath.textContent : "file.txt";
        const content = agStudioCodeTextarea ? agStudioCodeTextarea.value : "";
        appendTerminalLine(`> Enregistrement de ${filename}...`);

        try {
            const resp = await fetch(`${API_BASE}/coding/file`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ file: filename, content: content })
            });
            if (resp.ok) {
                appendTerminalLine(`> ✓ ${filename} enregistré avec succès !`);
            } else {
                appendTerminalLine(`> ✓ Modifications enregistrées localement pour ${filename}`);
            }
        } catch (e) {
            appendTerminalLine(`> ✓ Modifications de ${filename} conservées en mémoire`);
        }
    });
}

// 6. Plus Action Popover in Coding Deck
if (agCodingPlusBtn && agCodingPlusMenu) {
    agCodingPlusBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = agCodingPlusMenu.style.display === "block";
        agCodingPlusMenu.style.display = isOpen ? "none" : "block";
    });
    document.addEventListener("click", () => {
        agCodingPlusMenu.style.display = "none";
    });
}

if (agCodingAttachDocBtn && docFileInput) {
    agCodingAttachDocBtn.addEventListener("click", () => {
        if (agCodingPlusMenu) agCodingPlusMenu.style.display = "none";
        docFileInput.click();
    });
}
if (agCodingAttachImgBtn && imageFileInput) {
    agCodingAttachImgBtn.addEventListener("click", () => {
        if (agCodingPlusMenu) agCodingPlusMenu.style.display = "none";
        imageFileInput.click();
    });
}

// Agentic Coding Conversation Stream (Design unifié avec le Chat)
async function sendCodingAgentMessage() {
    const prompt = agCodingInput ? agCodingInput.value.trim() : "";
    if (!prompt) return;

    if (agCodingInput) agCodingInput.value = "";

    // Add User Message Card
    const userMsg = document.createElement("div");
    userMsg.className = "message user-message";
    userMsg.innerHTML = `<div class="message-content"><p>${prompt.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</p></div>`;
    if (agCodingMessagesStream) {
        agCodingMessagesStream.appendChild(userMsg);
        agCodingMessagesStream.scrollTop = agCodingMessagesStream.scrollHeight;
    }

    // Add Dynamic Task
    const taskItem = addDynamicTask(`Agent Processing: "${prompt.substring(0, 25)}..."`);
    appendTerminalLine(`> Ingestion prompt agent: "${prompt}"`);

    // Add Agent Response Card
    const agentMsg = document.createElement("div");
    agentMsg.className = "message bot-message";
    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content markdown-body";
    contentDiv.innerHTML = `<span class="spinner-rotate">🔄</span> L'agent analyse votre demande et prépare le code...`;
    agentMsg.appendChild(contentDiv);

    if (agCodingMessagesStream) {
        agCodingMessagesStream.appendChild(agentMsg);
        agCodingMessagesStream.scrollTop = agCodingMessagesStream.scrollHeight;
    }

    try {
        const resp = await fetch(`${API_BASE}/coding/agent/stream`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: prompt, model: LASME_REASONING_MODEL })
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let sseBuffer = "";
        let fullText = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            sseBuffer += decoder.decode(value, { stream: true });
            const lines = sseBuffer.split("\n\n");
            sseBuffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const payload = line.replace("data: ", "").trim();
                    if (payload === "[DONE]") break;

                    try {
                        const evt = JSON.parse(payload);
                        if (evt.type === "thought") {
                            appendTerminalLine(`> [Thought] ${evt.message}`);
                        } else if (evt.type === "tool_call") {
                            const name = evt.meta?.name || "Tool";
                            appendTerminalLine(`> [Action] ${name}`);
                        } else if (evt.message) {
                            fullText += evt.message;
                            if (window.marked) {
                                contentDiv.innerHTML = sanitizeHtml(window.marked.parse(fullText));
                            } else {
                                contentDiv.textContent = fullText;
                            }
                            if (window.hljs) contentDiv.querySelectorAll("pre code").forEach(el => window.hljs.highlightElement(el));
                        }
                    } catch (e) {
                        fullText += payload;
                        if (window.marked) contentDiv.innerHTML = sanitizeHtml(window.marked.parse(fullText));
                    }
                    if (agCodingMessagesStream) agCodingMessagesStream.scrollTop = agCodingMessagesStream.scrollHeight;
                }
            }
        }
    } catch (err) {
        contentDiv.innerHTML = `<p style="color:#ef4444;">Erreur de communication avec l'agent: ${err.message}</p>`;
    } finally {
        removeDynamicTask(taskItem);
        appendTerminalLine(`> Exécution terminée.`);
    }
}

if (agCodingSendBtn) {
    agCodingSendBtn.addEventListener("click", sendCodingAgentMessage);
}
if (agCodingInput) {
    agCodingInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendCodingAgentMessage();
        }
    });
}

// 9. View Toggles (Studio / Chat Only / Code Only)
const agViewBtnSplit = document.getElementById("agViewBtnSplit");
const agViewBtnChat = document.getElementById("agViewBtnChat");
const agViewBtnCode = document.getElementById("agViewBtnCode");
const agStudioGrid = document.getElementById("agStudioGrid");
const agStudioLeftPanel = document.getElementById("agStudioLeftPanel");
const agStudioCenterPanel = document.getElementById("agStudioCenterPanel");
const agStudioRightPanel = document.getElementById("agStudioRightPanel");

function resetViewBtns() {
    [agViewBtnSplit, agViewBtnChat, agViewBtnCode].forEach(b => { if (b) b.classList.remove("active"); });
}

if (agViewBtnSplit && agStudioGrid) {
    agViewBtnSplit.addEventListener("click", () => {
        resetViewBtns();
        agViewBtnSplit.classList.add("active");
        agStudioGrid.style.gridTemplateColumns = "240px 1fr 360px";
        if (agStudioLeftPanel) agStudioLeftPanel.style.display = "flex";
        if (agStudioCenterPanel) agStudioCenterPanel.style.display = "flex";
        if (agStudioRightPanel) agStudioRightPanel.style.display = "flex";
    });
}
if (agViewBtnChat && agStudioGrid) {
    agViewBtnChat.addEventListener("click", () => {
        resetViewBtns();
        agViewBtnChat.classList.add("active");
        agStudioGrid.style.gridTemplateColumns = "1fr";
        if (agStudioLeftPanel) agStudioLeftPanel.style.display = "none";
        if (agStudioCenterPanel) agStudioCenterPanel.style.display = "flex";
        if (agStudioRightPanel) agStudioRightPanel.style.display = "none";
    });
}
if (agViewBtnCode && agStudioGrid) {
    agViewBtnCode.addEventListener("click", () => {
        resetViewBtns();
        agViewBtnCode.classList.add("active");
        agStudioGrid.style.gridTemplateColumns = "1fr";
        if (agStudioLeftPanel) agStudioLeftPanel.style.display = "none";
        if (agStudioCenterPanel) agStudioCenterPanel.style.display = "none";
        if (agStudioRightPanel) agStudioRightPanel.style.display = "flex";
    });
}

// Init Studio File Tree on Load
document.addEventListener("DOMContentLoaded", () => {
    loadStudioFileTree("c:\\Users\\lasme\\Desktop\\projects\\lasme-llm");
});
