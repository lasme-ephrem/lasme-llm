let chatProjects = [];
let editingProjectId = null;
let activeCanvasArtifact = null;
let canvasArtifacts = [];
const WORKSPACE_PRIMARY_PROJECT_ID = "default";

const chatProjectSelect = document.getElementById("chatProjectSelect");
const workspaceSwitcher = document.querySelector(".workspace-switcher");
const newProjectBtn = document.getElementById("newProjectBtn");
const projectSettingsBtn = document.getElementById("projectSettingsBtn");
const projectSwitcherTrigger = document.getElementById("projectSwitcherTrigger");
const activeProjectIcon = projectSwitcherTrigger?.querySelector(".workspace-project-icon");
const projectSwitcherMenu = document.getElementById("projectSwitcherMenu");
const projectMenuList = document.getElementById("projectMenuList");
const activeProjectName = document.getElementById("activeProjectName");
const activeProjectMeta = document.getElementById("activeProjectMeta");
const projectModal = document.getElementById("projectModal");
const projectModalOverlay = document.getElementById("projectModalOverlay");
const projectModalCloseBtn = document.getElementById("projectModalCloseBtn");
const projectModalTitle = document.getElementById("projectModalTitle");
const projectModalSubtitle = document.getElementById("projectModalSubtitle");
const projectModalIcon = document.getElementById("projectModalIcon");
const projectPrimaryNotice = document.getElementById("projectPrimaryNotice");
const projectEditableFields = document.getElementById("projectEditableFields");
const projectNameInput = document.getElementById("projectNameInput");
const projectDescriptionInput = document.getElementById("projectDescriptionInput");
const projectInstructionsInput = document.getElementById("projectInstructionsInput");
const projectMemoryModeSelect = document.getElementById("projectMemoryModeSelect");
const projectSaveBtn = document.getElementById("projectSaveBtn");
const projectDeleteBtn = document.getElementById("projectDeleteBtn");
const projectStatus = document.getElementById("projectStatus");
const projectDocumentsSummary = document.getElementById("projectDocumentsSummary");

function projectIconMarkup(isPrimary, size = 18) {
    if (isPrimary) {
        return `
            <svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <path d="m3 10.5 9-7 9 7"></path>
                <path d="M5.5 9v10.5h13V9"></path>
                <path d="M9.5 19.5v-6h5v6"></path>
            </svg>
        `;
    }
    return `
        <svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"></path>
        </svg>
    `;
}

const canvasPanel = document.getElementById("canvasPanel");
const canvasToggleBtn = document.getElementById("canvasToggleBtn");
const canvasCloseBtn = document.getElementById("canvasCloseBtn");
const canvasTitleInput = document.getElementById("canvasTitleInput");
const canvasArtifactSelect = document.getElementById("canvasArtifactSelect");
const canvasKindSelect = document.getElementById("canvasKindSelect");
const canvasKindHint = document.getElementById("canvasKindHint");
const canvasVersionLabel = document.getElementById("canvasVersionLabel");
const canvasVersionSelect = document.getElementById("canvasVersionSelect");
const canvasNewBtn = document.getElementById("canvasNewBtn");
const canvasSaveBtn = document.getElementById("canvasSaveBtn");
const canvasExportBtn = document.getElementById("canvasExportBtn");
const canvasEditor = document.getElementById("canvasEditor");
const canvasPreview = document.getElementById("canvasPreview");
const canvasChangeSummary = document.getElementById("canvasChangeSummary");
const canvasStatus = document.getElementById("canvasStatus");

async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/projects`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        chatProjects = Array.isArray(payload.projects) ? payload.projects : [];
        if (!chatProjects.some(project => project.id === currentProjectId)) {
            currentProjectId = chatProjects[0]?.id || "default";
        }
        currentDocumentScopeId = currentProjectId;
        localStorage.setItem("active_project_id", currentProjectId);
        syncProjectSelector();
        await loadCanvasArtifacts();
        await loadProjectDocuments();
    } catch (error) {
        console.error("Impossible de charger les projets :", error);
    }
}

async function loadProjectDocuments() {
    if (!projectDocumentsSummary) return;
    try {
        const response = await fetch(
            `${API_BASE}/documents?scope_id=${encodeURIComponent(currentProjectId)}`
        );
        if (!response.ok) return;
        const payload = await response.json();
        const documents = payload.documents || [];
        projectDocumentsSummary.textContent = documents.length
            ? `${documents.length} document${documents.length > 1 ? "s" : ""} · ${documents.map(item => item.filename).join(", ")}`
            : "Aucun document";
        projectDocumentsSummary.title = documents
            .map(item => `${item.filename} · ${item.page_count} page(s)`)
            .join("\n");
    } catch (_) {
        projectDocumentsSummary.textContent = "Documents indisponibles";
    }
}

function syncProjectSelector() {
    if (!chatProjectSelect) return;
    chatProjectSelect.innerHTML = "";
    chatProjects.forEach(project => {
        const option = document.createElement("option");
        option.value = project.id;
        option.textContent = project.name;
        option.selected = project.id === currentProjectId;
        chatProjectSelect.appendChild(option);
    });
    const project = chatProjects.find(item => item.id === currentProjectId);
    const isPrimary = project?.id === WORKSPACE_PRIMARY_PROJECT_ID;
    workspaceSwitcher?.classList.toggle("primary-workspace", isPrimary);
    projectSwitcherTrigger?.classList.toggle("is-primary", isPrimary);
    if (activeProjectIcon) {
        activeProjectIcon.innerHTML = projectIconMarkup(isPrimary, 20);
    }
    if (activeProjectName) {
        activeProjectName.textContent = project?.name || "Espace principal";
    }
    if (activeProjectMeta) {
        const sessionCount = Number(project?.session_count) || 0;
        const memoryLabel = project?.memory_mode === "global"
            ? "mémoire personnelle"
            : (project?.memory_mode === "off" ? "sans mémoire" : "mémoire isolée");
        activeProjectMeta.textContent = `${sessionCount} conversation${sessionCount > 1 ? "s" : ""} · ${memoryLabel}`;
    }
    renderProjectMenu();
    if (project?.default_model && inputModelSelect) {
        inputModelSelect.value = project.default_model;
        const option = document.querySelector(
            `#modelPickerDropdown [data-model="${CSS.escape(project.default_model)}"]`
        );
        option?.click();
    }
}

function closeProjectSwitcher() {
    projectSwitcherMenu?.classList.remove("open");
    projectSwitcherMenu?.setAttribute("aria-hidden", "true");
    projectSwitcherTrigger?.setAttribute("aria-expanded", "false");
}

async function activateChatProject(projectId) {
    const resolvedProjectId = projectId || "default";
    if (!chatProjects.some(project => project.id === resolvedProjectId)) return;
    if (resolvedProjectId === currentProjectId) {
        closeProjectSwitcher();
        return;
    }
    currentProjectId = resolvedProjectId;
    currentDocumentScopeId = currentProjectId;
    localStorage.setItem("active_project_id", currentProjectId);
    if (chatProjectSelect) chatProjectSelect.value = currentProjectId;
    syncProjectSelector();
    closeProjectSwitcher();
    await startNewChat();
    await loadSessions();
    await loadCanvasArtifacts();
    await loadProjectDocuments();
    closeSidebar();
}

function renderProjectMenu() {
    if (!projectMenuList) return;
    projectMenuList.innerHTML = "";
    chatProjects.forEach(project => {
        const isPrimary = project.id === WORKSPACE_PRIMARY_PROJECT_ID;
        const button = document.createElement("button");
        button.type = "button";
        button.className = [
            "workspace-menu-project",
            project.id === currentProjectId ? "active" : "",
            isPrimary ? "is-primary" : ""
        ].filter(Boolean).join(" ");
        button.dataset.projectId = project.id;
        button.setAttribute("role", "option");
        button.setAttribute(
            "aria-selected",
            project.id === currentProjectId ? "true" : "false"
        );

        const icon = document.createElement("span");
        icon.className = "workspace-menu-project-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.innerHTML = projectIconMarkup(isPrimary, 17);

        const copy = document.createElement("span");
        copy.className = "workspace-menu-project-copy";
        const name = document.createElement("strong");
        name.textContent = project.name;
        const detail = document.createElement("small");
        const count = Number(project.session_count) || 0;
        detail.textContent = isPrimary
            ? `Principal · ${count} conversation${count > 1 ? "s" : ""}`
            : `${count} conversation${count > 1 ? "s" : ""}`;
        copy.append(name, detail);

        const check = document.createElement("span");
        check.className = "workspace-menu-check";
        check.setAttribute("aria-hidden", "true");
        check.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
        `;

        button.append(icon, copy, check);
        button.addEventListener("click", () => activateChatProject(project.id));
        projectMenuList.appendChild(button);
    });
}

projectSwitcherTrigger?.addEventListener("click", event => {
    event.stopPropagation();
    const open = !projectSwitcherMenu?.classList.contains("open");
    projectSwitcherMenu?.classList.toggle("open", open);
    projectSwitcherMenu?.setAttribute("aria-hidden", open ? "false" : "true");
    projectSwitcherTrigger.setAttribute("aria-expanded", open ? "true" : "false");
});

projectSwitcherMenu?.addEventListener("click", event => event.stopPropagation());
document.addEventListener("click", closeProjectSwitcher);

chatProjectSelect?.addEventListener("change", () => {
    void activateChatProject(chatProjectSelect.value);
});

function openProjectModal(createNew = false) {
    editingProjectId = createNew ? null : currentProjectId;
    const project = chatProjects.find(item => item.id === editingProjectId);
    const isPrimary = editingProjectId === WORKSPACE_PRIMARY_PROJECT_ID;

    projectNameInput.value = project?.name || "";
    projectDescriptionInput.value = project?.description || "";
    projectInstructionsInput.value = project?.instructions || "";
    projectMemoryModeSelect.value = project?.memory_mode || "project";

    projectModal.classList.toggle("primary-project-mode", isPrimary);
    projectPrimaryNotice.hidden = !isPrimary;
    projectEditableFields.hidden = isPrimary;
    projectNameInput.disabled = isPrimary;
    projectDescriptionInput.disabled = isPrimary;
    projectInstructionsInput.disabled = isPrimary;
    projectModalTitle.textContent = isPrimary
        ? "Espace principal"
        : (createNew ? "Nouveau projet" : "Paramètres du projet");
    projectModalSubtitle.textContent = isPrimary
        ? "Cet espace permanent accueille vos conversations par défaut."
        : "Conversations, fichiers, instructions et mémoire restent isolés.";
    projectModalIcon.innerHTML = projectIconMarkup(isPrimary, 21);
    projectSaveBtn.textContent = isPrimary
        ? "Enregistrer la mémoire"
        : "Enregistrer";
    projectDeleteBtn.style.display = (
        !editingProjectId || isPrimary
    ) ? "none" : "inline-flex";
    projectStatus.textContent = "";
    projectModal.style.display = "flex";
    projectModal.setAttribute("aria-hidden", "false");
    setTimeout(
        () => (isPrimary ? projectMemoryModeSelect : projectNameInput).focus(),
        0
    );
}

function closeProjectModal() {
    projectModal.style.display = "none";
    projectModal.setAttribute("aria-hidden", "true");
}

newProjectBtn?.addEventListener("click", () => {
    closeProjectSwitcher();
    openProjectModal(true);
});
projectSettingsBtn?.addEventListener("click", () => {
    closeProjectSwitcher();
    openProjectModal(false);
});
projectModalCloseBtn?.addEventListener("click", closeProjectModal);
projectModalOverlay?.addEventListener("click", closeProjectModal);

projectSaveBtn?.addEventListener("click", async () => {
    const isPrimary = editingProjectId === WORKSPACE_PRIMARY_PROJECT_ID;
    const name = projectNameInput.value.trim();
    if (!isPrimary && !name) {
        projectStatus.textContent = "Le nom est requis.";
        return;
    }
    const payload = isPrimary
        ? { memory_mode: projectMemoryModeSelect.value }
        : {
            name,
            description: projectDescriptionInput.value.trim(),
            instructions: projectInstructionsInput.value.trim(),
            memory_mode: projectMemoryModeSelect.value,
            default_model: inputModelSelect?.value || "gemma-4-chat"
        };
    const endpoint = editingProjectId
        ? `${API_BASE}/projects/${encodeURIComponent(editingProjectId)}`
        : `${API_BASE}/projects`;
    const response = await fetch(endpoint, {
        method: editingProjectId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
        projectStatus.textContent = data.detail || "Enregistrement impossible.";
        return;
    }
    currentProjectId = data.project.id;
    currentDocumentScopeId = currentProjectId;
    localStorage.setItem("active_project_id", currentProjectId);
    await loadProjects();
    await startNewChat();
    closeProjectModal();
});

projectDeleteBtn?.addEventListener("click", async () => {
    if (!editingProjectId || editingProjectId === WORKSPACE_PRIMARY_PROJECT_ID) return;
    if (!window.confirm("Supprimer ce projet ? Ses conversations seront déplacées dans Espace principal.")) {
        return;
    }
    const response = await fetch(
        `${API_BASE}/projects/${encodeURIComponent(editingProjectId)}`,
        { method: "DELETE" }
    );
    if (!response.ok) {
        projectStatus.textContent = "Suppression impossible.";
        return;
    }
    currentProjectId = WORKSPACE_PRIMARY_PROJECT_ID;
    currentDocumentScopeId = currentProjectId;
    localStorage.setItem("active_project_id", currentProjectId);
    await loadProjects();
    await startNewChat();
    closeProjectModal();
});

function setCanvasOpen(open) {
    canvasPanel?.classList.toggle("open", open);
    canvasPanel?.setAttribute("aria-hidden", open ? "false" : "true");
    canvasToggleBtn?.classList.toggle("active", open);
    canvasToggleBtn?.setAttribute("aria-pressed", open ? "true" : "false");
    if (canvasToggleBtn) {
        canvasToggleBtn.title = open
            ? "Fermer l’espace Canvas"
            : "Ouvrir l’espace Canvas";
    }
    document.body.classList.toggle("canvas-open", open);
}

canvasCloseBtn?.addEventListener("click", () => setCanvasOpen(false));

const CANVAS_KIND_HINTS = {
    document: "Texte, formules, tableaux et blocs de code",
    markdown: "Note structurée écrite en Markdown",
    code: "Un fichier de code source principal",
    table: "Données tabulaires et comparaisons",
    research: "Rapport documenté avec résultats et sources"
};

function detectCanvasKind(content) {
    const source = String(content || "").trim();
    if (!source) return "document";

    const fencedBlocks = Array.from(
        source.matchAll(/```([A-Za-z0-9_+#.-]*)\s*\n([\s\S]*?)```/g)
    );
    if (fencedBlocks.length === 1) {
        const prose = source.replace(fencedBlocks[0][0], "").trim();
        if (!prose) return "code";
    }

    const lines = source.split(/\r?\n/).filter(line => line.trim());
    const tableRows = lines.filter(line => /^\s*\|.+\|\s*$/.test(line));
    if (tableRows.length >= 3 && tableRows.length / Math.max(lines.length, 1) >= 0.7) {
        return "table";
    }
    return "document";
}

function updateCanvasKindHint() {
    if (!canvasKindHint || !canvasKindSelect) return;
    canvasKindHint.textContent = CANVAS_KIND_HINTS[canvasKindSelect.value]
        || CANVAS_KIND_HINTS.document;
}

function renderCanvasCodePreview(source) {
    canvasPreview.innerHTML = "";
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    const fenced = String(source || "").trim().match(
        /^```([A-Za-z0-9_+#.-]*)\s*\n([\s\S]*?)```\s*$/
    );
    const language = fenced?.[1] || "";
    code.textContent = fenced ? fenced[2].replace(/\s+$/, "") : source;
    if (language) code.classList.add(`language-${language.toLowerCase()}`);
    pre.appendChild(code);
    canvasPreview.appendChild(pre);
    if (window.hljs) window.hljs.highlightElement(code);
}

function renderCanvasDocumentPreview(source) {
    const preparedMath = window.LasmeMath
        ? window.LasmeMath.prepareForMarkdown(source)
        : { text: source, math: [] };
    let html = typeof marked !== "undefined"
        ? marked.parse(preparedMath.text)
        : escapeHtml(preparedMath.text);
    if (window.LasmeMath) {
        html = window.LasmeMath.restoreAfterMarkdown(
            html,
            preparedMath.math,
            escapeHtml
        );
    }
    canvasPreview.innerHTML = sanitizeHtml(html);
    canvasPreview.querySelectorAll("a").forEach(link => {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
    });
    if (typeof renderMathInElement !== "undefined") {
        try {
            renderMathInElement(canvasPreview, {
                delimiters: [
                    { left: "\\[", right: "\\]", display: true },
                    { left: "$$", right: "$$", display: true },
                    { left: "\\(", right: "\\)", display: false },
                    { left: "$", right: "$", display: false }
                ],
                throwOnError: false,
                errorColor: "#6B7280",
                strict: false,
                trust: false,
                macros: window.LasmeMath ? window.LasmeMath.KATEX_MACROS : {},
                ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"]
            });
        } catch (error) {
            console.warn("Impossible d’afficher une formule du Canvas :", error);
        }
    }
    canvasPreview.querySelectorAll("pre code").forEach(block => {
        if (window.hljs) window.hljs.highlightElement(block);
    });
}

function renderCanvasPreview() {
    if (!canvasPreview || !canvasEditor) return;
    const source = canvasEditor.value;
    updateCanvasKindHint();
    if (!source.trim()) {
        canvasPreview.innerHTML = `
            <div class="canvas-empty-state">
                <span class="canvas-empty-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M6.5 3.5h8l3 3v14h-11z"></path>
                        <path d="M14.5 3.5v3h3"></path>
                        <path d="M9 11h6M9 14h4"></path>
                        <path d="m17.5 14.8.45 1.12 1.12.45-1.12.45-.45 1.12-.45-1.12-1.12-.45 1.12-.45z"></path>
                    </svg>
                </span>
                <strong>Votre aperçu apparaîtra ici</strong>
                <span>Écrivez à gauche ou ouvrez une réponse de Lasme dans Canvas.</span>
            </div>
        `;
        return;
    }
    if (canvasKindSelect?.value === "code") {
        renderCanvasCodePreview(source);
        return;
    }
    renderCanvasDocumentPreview(source);
}

canvasEditor?.addEventListener("input", renderCanvasPreview);
canvasKindSelect?.addEventListener("change", renderCanvasPreview);

function resetCanvas(
    content = "",
    title = "Sans titre",
    kind = "document",
    status = ""
) {
    activeCanvasArtifact = null;
    canvasArtifactSelect.value = "";
    canvasTitleInput.value = title;
    canvasKindSelect.value = kind;
    canvasEditor.value = content;
    delete canvasEditor.dataset.sourceMessageId;
    canvasVersionSelect.innerHTML = "";
    canvasVersionLabel.textContent = "Non enregistré";
    canvasChangeSummary.value = "";
    canvasStatus.textContent = status;
    renderCanvasPreview();
}

canvasNewBtn?.addEventListener("click", () => {
    resetCanvas(
        "",
        "Sans titre",
        "document",
        "Nouveau brouillon · il sera conservé après enregistrement."
    );
    canvasEditor?.focus();
});

async function loadCanvasArtifacts() {
    if (!canvasArtifactSelect) return [];
    try {
        const response = await fetch(
            `${API_BASE}/artifacts?project_id=${encodeURIComponent(currentProjectId)}`
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        canvasArtifacts = Array.isArray(payload.artifacts)
            ? payload.artifacts
            : [];
        const selected = activeCanvasArtifact?.id || "";
        if (
            activeCanvasArtifact
            && !canvasArtifacts.some(artifact => artifact.id === selected)
        ) {
            activeCanvasArtifact = null;
        }
        canvasArtifactSelect.innerHTML = '<option value="">Nouvel artefact</option>';
        canvasArtifacts.forEach(artifact => {
            const option = document.createElement("option");
            option.value = artifact.id;
            option.textContent = `${artifact.title} · v${artifact.version_count}`;
            canvasArtifactSelect.appendChild(option);
        });
        canvasArtifactSelect.value = activeCanvasArtifact?.id || "";
        return canvasArtifacts;
    } catch (error) {
        console.error("Impossible de charger les Canvas :", error);
        canvasArtifacts = [];
        canvasStatus.textContent = "Les Canvas enregistrés sont momentanément indisponibles.";
        return [];
    }
}

async function openCanvasArtifact(artifactId) {
    if (!artifactId) return false;
    canvasStatus.textContent = "Ouverture du Canvas…";
    try {
        const response = await fetch(
            `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}`
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        activeCanvasArtifact = payload.artifact;
        canvasTitleInput.value = activeCanvasArtifact.title;
        canvasKindSelect.value = activeCanvasArtifact.kind;
        canvasEditor.value = activeCanvasArtifact.content || "";
        delete canvasEditor.dataset.sourceMessageId;
        canvasVersionLabel.textContent = `Version ${activeCanvasArtifact.current_version}`;
        canvasVersionSelect.innerHTML = "";
        (activeCanvasArtifact.versions || []).forEach(version => {
            const option = document.createElement("option");
            option.value = version.version_number;
            option.textContent = `v${version.version_number} · ${new Date(version.created_at).toLocaleString("fr-FR")}`;
            canvasVersionSelect.appendChild(option);
        });
        canvasArtifactSelect.value = artifactId;
        canvasStatus.textContent = "Canvas chargé.";
        renderCanvasPreview();
        setCanvasOpen(true);
        return true;
    } catch (error) {
        console.error("Impossible d’ouvrir le Canvas :", error);
        canvasStatus.textContent = "Impossible d’ouvrir ce Canvas.";
        return false;
    }
}

canvasArtifactSelect?.addEventListener("change", () => {
    if (canvasArtifactSelect.value) {
        openCanvasArtifact(canvasArtifactSelect.value);
    } else {
        resetCanvas();
    }
});

canvasVersionSelect?.addEventListener("change", () => {
    const version = activeCanvasArtifact?.versions?.find(
        item => String(item.version_number) === canvasVersionSelect.value
    );
    if (!version) return;
    canvasEditor.value = version.content;
    canvasVersionLabel.textContent = `Aperçu v${version.version_number}`;
    renderCanvasPreview();
});

canvasSaveBtn?.addEventListener("click", async () => {
    if (!canvasEditor.value.trim()) {
        canvasStatus.textContent = "Ajoutez du contenu avant d’enregistrer.";
        canvasEditor.focus();
        return;
    }
    canvasStatus.textContent = "Enregistrement…";
    const payload = activeCanvasArtifact
        ? {
            title: canvasTitleInput.value.trim() || "Sans titre",
            content: canvasEditor.value,
            change_summary: canvasChangeSummary.value.trim(),
            kind: canvasKindSelect.value
        }
        : {
            project_id: currentProjectId,
            session_id: currentSessionId,
            source_message_id: canvasEditor.dataset.sourceMessageId || null,
            title: canvasTitleInput.value.trim() || "Sans titre",
            content: canvasEditor.value,
            kind: canvasKindSelect.value
        };
    const endpoint = activeCanvasArtifact
        ? `${API_BASE}/artifacts/${encodeURIComponent(activeCanvasArtifact.id)}`
        : `${API_BASE}/artifacts`;
    try {
        const response = await fetch(endpoint, {
            method: activeCanvasArtifact ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) {
            canvasStatus.textContent = data.detail || "Erreur d’enregistrement.";
            return;
        }
        activeCanvasArtifact = data.artifact;
        canvasStatus.textContent = `Version ${activeCanvasArtifact.current_version} enregistrée`;
        canvasChangeSummary.value = "";
        await loadCanvasArtifacts();
        await openCanvasArtifact(activeCanvasArtifact.id);
    } catch (error) {
        console.error("Impossible d’enregistrer le Canvas :", error);
        canvasStatus.textContent = "Connexion impossible pendant l’enregistrement.";
    }
});

canvasExportBtn?.addEventListener("click", async () => {
    if (!activeCanvasArtifact) {
        canvasStatus.textContent = "Enregistrez d’abord l’artefact.";
        return;
    }
    const response = await fetch(
        `${API_BASE}/artifacts/${encodeURIComponent(activeCanvasArtifact.id)}/export`
    );
    if (!response.ok) return;
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "artifact.md";
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
});

function openCanvasWithContent(content, title = "Réponse", sourceMessageId = null) {
    resetCanvas(
        content,
        title,
        detectCanvasKind(content),
        "Brouillon importé depuis la conversation · enregistrez-le pour le conserver."
    );
    if (sourceMessageId) canvasEditor.dataset.sourceMessageId = sourceMessageId;
    setCanvasOpen(true);
}

function canvasTitleFromContent(content) {
    const firstUsefulLine = String(content || "")
        .split(/\r?\n/)
        .map(line => line.trim())
        .find(line => line && !line.startsWith("```"));
    const cleanTitle = String(firstUsefulLine || "Réponse de Lasme")
        .replace(/^#{1,6}\s+/, "")
        .replace(/[*_`[\]]/g, "")
        .replace(/\s+/g, " ")
        .trim();
    return cleanTitle.length > 62
        ? `${cleanTitle.slice(0, 59).trim()}…`
        : cleanTitle;
}

function latestAssistantCanvasSource() {
    const messages = Array.from(
        document.querySelectorAll("#chatMessages .message.assistant")
    ).reverse();
    for (const message of messages) {
        const bubble = message.querySelector(".bubble");
        if (!bubble) continue;
        const rawContent = String(
            bubble._lasmeRawContent
            || bubble.querySelector(".answer-content")?.innerText
            || ""
        ).trim();
        if (!rawContent || rawContent === "...") continue;
        return {
            content: rawContent,
            title: canvasTitleFromContent(rawContent),
            sourceMessageId: message.dataset.messageId || null
        };
    }
    return null;
}

async function openDefaultCanvas() {
    if (canvasPanel?.classList.contains("open")) {
        setCanvasOpen(false);
        return;
    }

    if (activeCanvasArtifact || canvasEditor?.value.trim()) {
        setCanvasOpen(true);
        return;
    }

    const artifacts = canvasArtifacts.length
        ? canvasArtifacts
        : await loadCanvasArtifacts();
    if (artifacts.length && await openCanvasArtifact(artifacts[0].id)) {
        return;
    }

    const latestResponse = latestAssistantCanvasSource();
    if (latestResponse) {
        openCanvasWithContent(
            latestResponse.content,
            latestResponse.title,
            latestResponse.sourceMessageId
        );
        return;
    }

    resetCanvas(
        "",
        "Sans titre",
        "document",
        "Commencez ici ou ouvrez une réponse depuis son action Canvas."
    );
    setCanvasOpen(true);
    canvasEditor?.focus();
}

canvasToggleBtn?.addEventListener("click", openDefaultCanvas);

async function createConversationBranch(messageId, content = null) {
    if (!currentSessionId || !messageId) return null;
    const payload = {
        message_id: messageId,
        model: inputModelSelect?.value || "gemma-4-chat"
    };
    if (content !== null) payload.content = content;
    const response = await fetch(
        `${API_BASE}/sessions/${encodeURIComponent(currentSessionId)}/branch`,
        {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Branche impossible.");
    await selectSession(data.session.id);
    return data.session;
}

function beginInlineMessageEdit(messageElement, messageId, currentText) {
    const bubble = messageElement.querySelector(".bubble");
    const textContent = bubble.querySelector(".user-text-content");
    if (!textContent || bubble.querySelector(".message-inline-editor")) return;
    textContent.style.display = "none";
    const editor = document.createElement("div");
    editor.className = "message-inline-editor";
    editor.innerHTML = `
        <div class="message-inline-editor-header">
            <span class="message-inline-editor-icon" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 20h9"></path>
                    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4z"></path>
                </svg>
            </span>
            <span>
                <strong>Modifier votre message</strong>
                <small>Une nouvelle branche sera créée automatiquement.</small>
            </span>
        </div>
        <textarea aria-label="Message modifié"></textarea>
        <div class="message-inline-editor-footer">
            <span class="message-inline-editor-status" aria-live="polite"></span>
            <button type="button" class="inline-editor-cancel" data-action="cancel">Annuler</button>
            <button type="button" class="inline-editor-submit" data-action="save">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M5 12h14M13 6l6 6-6 6"></path>
                </svg>
                <span>Enregistrer et relancer</span>
            </button>
        </div>
    `;
    const textarea = editor.querySelector("textarea");
    textarea.value = currentText;
    editor.querySelector('[data-action="cancel"]').addEventListener("click", () => {
        editor.remove();
        textContent.style.display = "";
    });
    const submitButton = editor.querySelector('[data-action="save"]');
    const status = editor.querySelector(".message-inline-editor-status");
    const submitEdit = async () => {
        const replacement = textarea.value.trim();
        if (!replacement) return;
        submitButton.disabled = true;
        textarea.disabled = true;
        status.textContent = "Relance en cours…";
        try {
            await createConversationBranch(messageId, replacement);
            await sendChatMessage({ replayExistingLastUser: true });
        } catch (error) {
            submitButton.disabled = false;
            textarea.disabled = false;
            status.textContent = error.message || "Impossible de relancer.";
        }
    };
    submitButton.addEventListener("click", submitEdit);
    textarea.addEventListener("keydown", event => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            void submitEdit();
        }
    });
    bubble.appendChild(editor);
    textarea.focus();
}

const MESSAGE_ACTION_ICONS = {
    copy: `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="8" y="8" width="11" height="11" rx="2"></rect>
            <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path>
        </svg>
    `,
    branch: `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="6" cy="5" r="2"></circle>
            <circle cx="18" cy="7" r="2"></circle>
            <circle cx="18" cy="18" r="2"></circle>
            <path d="M6 7v5a6 6 0 0 0 6 6h10M8 8c2 0 3-1 4-2s2-1 4-1"></path>
        </svg>
    `,
    edit: `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 20h9"></path>
            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4z"></path>
        </svg>
    `,
    canvas: `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="3" width="18" height="18" rx="4"></rect>
            <path d="M9 3v18"></path>
            <path d="m15.5 8 .55 1.45L17.5 10l-1.45.55L15.5 12l-.55-1.45L13.5 10l1.45-.55z"></path>
        </svg>
    `,
    regenerate: `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 7v5h-5"></path>
            <path d="M4 17v-5h5"></path>
            <path d="M6.1 9A7 7 0 0 1 18.7 6.3L20 8M4 16l1.3 1.7A7 7 0 0 0 17.9 15"></path>
        </svg>
    `
};

function decorateMessageActions(messageElement, role, messageId, text) {
    if (!messageElement) return;
    if (messageId) messageElement.dataset.messageId = messageId;
    messageElement.querySelector(".message-actions")?.remove();
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const addAction = (label, action, handler) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "message-action-btn";
        button.dataset.action = action;
        button.dataset.tooltip = label;
        button.title = label;
        button.setAttribute("aria-label", label);
        button.innerHTML = `
            ${MESSAGE_ACTION_ICONS[action] || ""}
            <span class="sr-only">${label}</span>
        `;
        button.addEventListener("click", handler);
        actions.appendChild(button);
    };
    addAction("Copier", "copy", () => navigator.clipboard.writeText(text || ""));
    if (!messageId) {
        messageElement.appendChild(actions);
        return;
    }
    addAction("Branche", "branch", () => createConversationBranch(messageId));
    if (role === "user") {
        addAction("Modifier", "edit", () => {
            beginInlineMessageEdit(messageElement, messageId, text);
        });
    } else {
        addAction("Ouvrir dans Canvas", "canvas", () => {
            openCanvasWithContent(text, "Réponse de Lasme", messageId);
        });
        addAction("Régénérer", "regenerate", async () => {
            let previous = messageElement.previousElementSibling;
            while (previous && !previous.classList.contains("user")) {
                previous = previous.previousElementSibling;
            }
            const userMessageId = previous?.dataset.messageId;
            if (!userMessageId) return;
            await createConversationBranch(userMessageId);
            const previousMode = webSearchBtn?.dataset.mode;
            if (previousMode === "deep") webSearchBtn.dataset.mode = "auto";
            await sendChatMessage({ replayExistingLastUser: true });
            if (previousMode === "deep") webSearchBtn.dataset.mode = previousMode;
        });
    }
    messageElement.appendChild(actions);
}

function renderResearchPlan(container, steps) {
    container.querySelector(".typing-indicator")?.remove();
    let plan = container.querySelector(".research-plan");
    if (!plan) {
        plan = document.createElement("section");
        plan.className = "research-plan";
        container.prepend(plan);
    }
    plan.innerHTML = '<div class="research-plan-title">Plan de recherche</div>';
    steps.forEach(step => {
        const row = document.createElement("div");
        row.className = "research-step";
        row.dataset.stepId = step.id;
        row.innerHTML = `<span><strong>${escapeHtml(step.label)}</strong><br><small>${escapeHtml(step.query)}</small></span>`;
        plan.appendChild(row);
    });
}

function updateResearchStep(container, event) {
    const row = container.querySelector(
        `.research-step[data-step-id="${CSS.escape(event.step_id || "")}"]`
    );
    if (!row) return;
    row.classList.remove("running", "done");
    row.classList.add(event.status === "done" ? "done" : "running");
    if (event.status === "done" && event.result_count !== undefined) {
        const small = row.querySelector("small");
        if (small) {
            small.textContent = `${event.result_count} résultat(s) · ${event.engine || "recherche"}`;
        }
    }
}
