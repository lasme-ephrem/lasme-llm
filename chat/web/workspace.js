let chatProjects = [];
let editingProjectId = null;
let activeCanvasArtifact = null;
let canvasArtifacts = [];
let projectFiles = [];
let activeProjectFileId = null;
let selectedProjectFileIds = new Set();
let projectFileRefreshTimer = null;
let projectSummaryRefreshSequence = 0;
const WORKSPACE_PRIMARY_PROJECT_ID = "default";
const PROJECT_TYPE_LABELS = {
    general: "Général",
    research: "Recherche",
    learning: "Apprentissage",
    data: "Données et analyse",
    coding: "Développement",
    writing: "Rédaction",
    media: "Visuel et média"
};

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
const projectTypeSelect = document.getElementById("projectTypeSelect");
const projectColorInput = document.getElementById("projectColorInput");
const projectTagsInput = document.getElementById("projectTagsInput");
const projectFavoriteInput = document.getElementById("projectFavoriteInput");
const projectMemoryModeSelect = document.getElementById("projectMemoryModeSelect");
const projectSaveBtn = document.getElementById("projectSaveBtn");
const projectDeleteBtn = document.getElementById("projectDeleteBtn");
const projectStatus = document.getElementById("projectStatus");
const projectDocumentsSummary = document.getElementById("projectDocumentsSummary");
const projectFilesBtn = document.getElementById("projectFilesBtn");
const fileLibraryModal = document.getElementById("fileLibraryModal");
const fileLibraryOverlay = document.getElementById("fileLibraryOverlay");
const fileLibraryCloseBtn = document.getElementById("fileLibraryCloseBtn");
const fileLibrarySubtitle = document.getElementById("fileLibrarySubtitle");
const fileLibrarySearchInput = document.getElementById("fileLibrarySearchInput");
const fileLibraryKindFilter = document.getElementById("fileLibraryKindFilter");
const fileLibraryUploadBtn = document.getElementById("fileLibraryUploadBtn");
const projectFileUploadInput = document.getElementById("projectFileUploadInput");
const fileLibraryDropzone = document.getElementById("fileLibraryDropzone");
const fileLibraryStatus = document.getElementById("fileLibraryStatus");
const fileLibraryList = document.getElementById("fileLibraryList");
const filePreviewPane = document.getElementById("filePreviewPane");

function projectIconMarkup(isPrimary, size = 18, projectType = "general") {
    if (isPrimary) {
        return `
            <svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <path d="m3 10.5 9-7 9 7"></path>
                <path d="M5.5 9v10.5h13V9"></path>
                <path d="M9.5 19.5v-6h5v6"></path>
            </svg>
        `;
    }
    const typeIcons = {
        research: `
            <path d="M4 19.5h16"></path>
            <path d="M7 17V9l5-5 5 5v8"></path>
            <path d="M10 17v-4h4v4"></path>
            <circle cx="12" cy="8.5" r="1.5"></circle>
        `,
        learning: `
            <path d="m3 9 9-5 9 5-9 5z"></path>
            <path d="M7 12v4.5c2.8 2 7.2 2 10 0V12"></path>
            <path d="M21 9v6"></path>
        `,
        data: `
            <path d="M4 19V9"></path>
            <path d="M10 19V5"></path>
            <path d="M16 19v-7"></path>
            <path d="M22 19H2"></path>
        `,
        coding: `
            <path d="m8 9-4 3 4 3"></path>
            <path d="m16 9 4 3-4 3"></path>
            <path d="m14 5-4 14"></path>
        `,
        writing: `
            <path d="M4 20h16"></path>
            <path d="m14.7 4.3 5 5L9 20H4v-5z"></path>
            <path d="m12.5 6.5 5 5"></path>
        `,
        media: `
            <rect x="3" y="5" width="18" height="14" rx="3"></rect>
            <path d="m8 15 3-3 2 2 3-4 3 5"></path>
            <circle cx="8.5" cy="9" r="1.2"></circle>
        `,
        general: `
            <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"></path>
        `
    };
    return `
        <svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
            ${typeIcons[projectType] || typeIcons.general}
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
const canvasRunBtn = document.getElementById("canvasRunBtn");
const canvasRunResult = document.getElementById("canvasRunResult");
const canvasExportBtn = document.getElementById("canvasExportBtn");
const canvasExportFormatSelect = document.getElementById("canvasExportFormatSelect");
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
        projectFiles = Array.isArray(payload.files)
            ? payload.files
            : (payload.documents || []);
        const availableIds = new Set(projectFiles.map(item => item.id));
        selectedProjectFileIds = new Set(
            Array.from(selectedProjectFileIds).filter(id => availableIds.has(id))
        );
        const indexedCount = projectFiles.filter(item => item.status === "ready").length;
        projectDocumentsSummary.textContent = projectFiles.length
            ? `${projectFiles.length} fichier${projectFiles.length > 1 ? "s" : ""} · ${indexedCount} prêt${indexedCount > 1 ? "s" : ""}`
            : "Aucun document";
        projectDocumentsSummary.title = projectFiles
            .map(item => `${item.display_name || item.filename} · ${item.page_count || 0} page(s)`)
            .join("\n");
        if (fileLibraryStatus && !fileLibraryStatus.classList.contains("error")) {
            fileLibraryStatus.textContent = selectedProjectFileIds.size
                ? `${selectedProjectFileIds.size} fichier${selectedProjectFileIds.size > 1 ? "s" : ""} ciblé${selectedProjectFileIds.size > 1 ? "s" : ""}.`
                : "Sans sélection, tous les fichiers prêts enrichissent la réponse.";
        }
        renderFileLibrary();
    } catch (_) {
        projectFiles = [];
        projectDocumentsSummary.textContent = "Documents indisponibles";
        renderFileLibrary();
    }
}

async function refreshProjectSessionCounts() {
    const refreshSequence = ++projectSummaryRefreshSequence;
    try {
        const response = await fetch(`${API_BASE}/projects`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (refreshSequence !== projectSummaryRefreshSequence) return;
        const projects = Array.isArray(payload.projects)
            ? payload.projects
            : [];
        if (!projects.length) return;
        chatProjects = projects;
        if (!chatProjects.some(project => project.id === currentProjectId)) {
            currentProjectId = WORKSPACE_PRIMARY_PROJECT_ID;
            currentDocumentScopeId = currentProjectId;
            localStorage.setItem("active_project_id", currentProjectId);
        }
        syncProjectSelector();
    } catch (error) {
        console.error(
            "Impossible d’actualiser les compteurs des projets :",
            error
        );
    }
}

function stopProjectFilePolling() {
    if (projectFileRefreshTimer) {
        clearTimeout(projectFileRefreshTimer);
        projectFileRefreshTimer = null;
    }
}

function startProjectFilePolling(attempt = 0) {
    stopProjectFilePolling();
    if (attempt >= 75) return;
    projectFileRefreshTimer = setTimeout(async () => {
        projectFileRefreshTimer = null;
        await loadProjectDocuments();
        if (projectFiles.some(item => item.status === "indexing")) {
            startProjectFilePolling(attempt + 1);
        } else if (fileLibraryStatus && !fileLibraryStatus.classList.contains("error")) {
            const failed = projectFiles.filter(item => item.status === "error").length;
            fileLibraryStatus.textContent = failed
                ? `${failed} fichier${failed > 1 ? "s nécessitent" : " nécessite"} une nouvelle analyse.`
                : "Tous les fichiers sont prêts pour le chat.";
        }
    }, 1_200);
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
        activeProjectIcon.innerHTML = projectIconMarkup(
            isPrimary,
            20,
            project?.project_type || "general"
        );
        activeProjectIcon.style.setProperty(
            "--project-color",
            project?.color || (isPrimary ? "#5B6EE1" : "#0BAE83")
        );
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
    stopProjectFilePolling();
    selectedProjectFileIds.clear();
    closeFilePreview();
    window.LasmeComposer?.resetDocumentAttachment?.();
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
    let lastGroup = "";
    chatProjects.forEach(project => {
        const isPrimary = project.id === WORKSPACE_PRIMARY_PROJECT_ID;
        const projectType = project.project_type || "general";
        const group = isPrimary ? "principal" : projectType;
        if (group !== lastGroup) {
            const heading = document.createElement("div");
            heading.className = "workspace-menu-group";
            heading.textContent = isPrimary
                ? "Espace permanent"
                : (PROJECT_TYPE_LABELS[projectType] || PROJECT_TYPE_LABELS.general);
            projectMenuList.appendChild(heading);
            lastGroup = group;
        }
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
        icon.innerHTML = projectIconMarkup(isPrimary, 17, projectType);
        icon.style.setProperty(
            "--project-color",
            project.color || (isPrimary ? "#5B6EE1" : "#0BAE83")
        );

        const copy = document.createElement("span");
        copy.className = "workspace-menu-project-copy";
        const name = document.createElement("strong");
        name.textContent = `${project.favorite ? "★ " : ""}${project.name}`;
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
    if (projectTypeSelect) projectTypeSelect.value = project?.project_type || "general";
    if (projectColorInput) {
        projectColorInput.value = project?.color || (isPrimary ? "#5B6EE1" : "#0BAE83");
    }
    if (projectTagsInput) {
        projectTagsInput.value = Array.isArray(project?.tags)
            ? project.tags.join(", ")
            : "";
    }
    if (projectFavoriteInput) projectFavoriteInput.checked = Boolean(project?.favorite);

    projectModal.classList.toggle("primary-project-mode", isPrimary);
    projectPrimaryNotice.hidden = !isPrimary;
    projectEditableFields.hidden = isPrimary;
    projectNameInput.disabled = isPrimary;
    projectDescriptionInput.disabled = isPrimary;
    projectInstructionsInput.disabled = isPrimary;
    if (projectTypeSelect) projectTypeSelect.disabled = isPrimary;
    if (projectColorInput) projectColorInput.disabled = isPrimary;
    if (projectTagsInput) projectTagsInput.disabled = isPrimary;
    if (projectFavoriteInput) projectFavoriteInput.disabled = isPrimary;
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
            default_model: inputModelSelect?.value || "muse-glimmer:30b-q4_K_M-dflash",
            project_type: projectTypeSelect?.value || "general",
            color: projectColorInput?.value || "#0BAE83",
            tags: (projectTagsInput?.value || "")
                .split(",")
                .map(item => item.trim())
                .filter(Boolean),
            favorite: Boolean(projectFavoriteInput?.checked)
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

const FILE_KIND_META = {
    pdf: { label: "PDF", color: "#E25555" },
    word: { label: "Word", color: "#3B73D1" },
    spreadsheet: { label: "Excel", color: "#1F9D68" },
    presentation: { label: "PowerPoint", color: "#E56B3F" },
    image: { label: "Image", color: "#9B59D0" },
    text: { label: "Texte", color: "#60758A" }
};

function fileKindIcon(kind) {
    const icons = {
        image: `<rect x="3" y="4" width="18" height="16" rx="3"></rect><circle cx="8.5" cy="9" r="1.5"></circle><path d="m5 17 4.5-4.5 3 3 2.5-3 4 4.5"></path>`,
        spreadsheet: `<rect x="3" y="3" width="18" height="18" rx="3"></rect><path d="M3 9h18M9 3v18M9 15h12"></path>`,
        presentation: `<rect x="4" y="3" width="16" height="13" rx="2"></rect><path d="M8 21l4-5 4 5M9 8h6M9 11h4"></path>`,
        word: `<path d="M6 2h9l4 4v16H6z"></path><path d="M15 2v5h4M9 12h7M9 16h7"></path>`,
        pdf: `<path d="M6 2h9l4 4v16H6z"></path><path d="M15 2v5h4M9 12h6M9 16h4"></path>`,
        text: `<path d="M6 2h9l4 4v16H6z"></path><path d="M15 2v5h4M9 12h7M9 16h7"></path>`
    };
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${icons[kind] || icons.text}</svg>`;
}

function formatProjectFileSize(bytes) {
    const value = Number(bytes) || 0;
    if (value < 1024) return `${value} o`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} Ko`;
    return `${(value / (1024 * 1024)).toFixed(1)} Mo`;
}

function projectFileStatusLabel(file) {
    const labels = {
        ready: "Prêt pour le chat",
        indexing: "Préparation en arrière-plan",
        stored: "Ajouté",
        error: "Analyse à relancer"
    };
    return labels[file?.status] || "En attente";
}

function closeFilePreview() {
    activeProjectFileId = null;
    filePreviewPane?.classList.remove("open");
    renderFileLibrary();
}

function closeFileLibrary() {
    fileLibraryModal.style.display = "none";
    fileLibraryModal.setAttribute("aria-hidden", "true");
    closeFilePreview();
}

function openFileLibrary() {
    const project = chatProjects.find(item => item.id === currentProjectId);
    if (fileLibrarySubtitle) {
        fileLibrarySubtitle.textContent = `${project?.name || "Projet"} · cliquez sur un fichier pour le télécharger`;
    }
    fileLibraryModal.style.display = "flex";
    fileLibraryModal.setAttribute("aria-hidden", "false");
    void loadProjectDocuments().then(() => {
        if (projectFiles.some(item => item.status === "indexing")) {
            startProjectFilePolling();
        }
    });
    setTimeout(() => fileLibrarySearchInput?.focus(), 0);
}

function toggleProjectFileSelection(fileId, selected) {
    if (selected) selectedProjectFileIds.add(fileId);
    else selectedProjectFileIds.delete(fileId);
    if (fileLibraryStatus) {
        fileLibraryStatus.classList.remove("error");
        fileLibraryStatus.textContent = selectedProjectFileIds.size
            ? `${selectedProjectFileIds.size} fichier${selectedProjectFileIds.size > 1 ? "s" : ""} ciblé${selectedProjectFileIds.size > 1 ? "s" : ""}.`
            : "Sans sélection, tous les fichiers prêts enrichissent la réponse.";
    }
    renderFileLibrary();
}

function renderFileLibrary() {
    if (!fileLibraryList) return;
    const query = (fileLibrarySearchInput?.value || "").trim().toLocaleLowerCase();
    const kind = fileLibraryKindFilter?.value || "all";
    const filtered = projectFiles.filter(file => {
        const name = String(file.display_name || file.filename || "").toLocaleLowerCase();
        return (!query || name.includes(query)) && (kind === "all" || file.kind === kind);
    });
    fileLibraryList.replaceChildren();
    if (!filtered.length) {
        const empty = document.createElement("div");
        empty.className = "file-library-empty-list";
        const strong = document.createElement("strong");
        strong.textContent = projectFiles.length ? "Aucun résultat" : "Aucun fichier";
        const small = document.createElement("span");
        small.textContent = projectFiles.length
            ? "Modifiez votre recherche ou le filtre."
            : "Ajoutez un document pour enrichir ce projet.";
        empty.append(strong, small);
        fileLibraryList.appendChild(empty);
        return;
    }

    filtered.forEach(file => {
        const card = document.createElement("div");
        card.className = `project-file-card${file.id === activeProjectFileId ? " active" : ""}`;
        card.setAttribute("role", "button");
        card.tabIndex = 0;

        const icon = document.createElement("span");
        icon.className = "project-file-icon";
        icon.style.setProperty(
            "--file-color",
            (FILE_KIND_META[file.kind] || FILE_KIND_META.text).color
        );
        icon.innerHTML = fileKindIcon(file.kind);

        const copy = document.createElement("span");
        copy.className = "project-file-copy";
        const title = document.createElement("strong");
        title.textContent = file.display_name || file.filename;
        const meta = document.createElement("small");
        const details = [
            (FILE_KIND_META[file.kind] || FILE_KIND_META.text).label,
            file.metadata?.legacy_index
                ? "Index historique"
                : formatProjectFileSize(file.size_bytes),
            file.page_count ? `${file.page_count} page${file.page_count > 1 ? "s" : ""}` : "",
            projectFileStatusLabel(file)
        ].filter(Boolean);
        meta.textContent = details.join(" · ");
        copy.append(title, meta);

        const controls = document.createElement("span");
        controls.className = "project-file-controls";
        const contextToggle = document.createElement("button");
        contextToggle.type = "button";
        contextToggle.className = `project-file-context${selectedProjectFileIds.has(file.id) ? " selected" : ""}`;
        contextToggle.disabled = file.status !== "ready";
        contextToggle.title = selectedProjectFileIds.has(file.id)
            ? "Retirer du contexte ciblé"
            : "Utiliser uniquement les fichiers sélectionnés dans la prochaine réponse";
        contextToggle.setAttribute(
            "aria-label",
            selectedProjectFileIds.has(file.id) ? "Retirer du contexte" : "Ajouter au contexte"
        );
        contextToggle.innerHTML = selectedProjectFileIds.has(file.id)
            ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m5 12 4 4 10-10"></path></svg>`
            : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M12 5v14M5 12h14"></path></svg>`;
        contextToggle.addEventListener("click", event => {
            event.stopPropagation();
            toggleProjectFileSelection(file.id, !selectedProjectFileIds.has(file.id));
        });
        const status = document.createElement("span");
        status.className = `project-file-status ${file.status || ""}`;
        status.title = file.error || projectFileStatusLabel(file);

        if (file.status === "error") {
            const retry = document.createElement("button");
            retry.type = "button";
            retry.className = "project-file-inline-action";
            retry.title = "Relancer l’analyse";
            retry.setAttribute("aria-label", "Relancer l’analyse");
            retry.innerHTML = fileActionIcon("refresh");
            retry.addEventListener("click", async event => {
                event.stopPropagation();
                retry.disabled = true;
                await fetch(
                    `${API_BASE}/files/${encodeURIComponent(file.id)}/reindex`,
                    { method: "POST" }
                );
                await loadProjectDocuments();
            });
            controls.appendChild(retry);
        }

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "project-file-inline-action danger";
        remove.title = "Supprimer du projet";
        remove.setAttribute("aria-label", "Supprimer le fichier");
        remove.innerHTML = fileActionIcon("delete");
        remove.addEventListener("click", async event => {
            event.stopPropagation();
            if (!window.confirm(`Supprimer « ${file.display_name || file.filename} » du projet ?`)) return;
            const response = await fetch(
                `${API_BASE}/files/${encodeURIComponent(file.id)}`,
                { method: "DELETE" }
            );
            if (!response.ok) {
                if (fileLibraryStatus) {
                    fileLibraryStatus.classList.add("error");
                    fileLibraryStatus.textContent = "Suppression impossible.";
                }
                return;
            }
            selectedProjectFileIds.delete(file.id);
            await loadProjectDocuments();
        });

        const downloadCue = document.createElement("span");
        downloadCue.className = "project-file-download-cue";
        downloadCue.title = "Télécharger";
        downloadCue.innerHTML = fileActionIcon("download");
        controls.append(contextToggle, status, downloadCue, remove);
        card.append(icon, copy, controls);

        const open = () => void openProjectFile(file.id);
        card.addEventListener("click", open);
        card.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                open();
            }
        });
        fileLibraryList.appendChild(card);
    });
}

function fileActionIcon(kind) {
    const icons = {
        back: `<path d="m15 18-6-6 6-6"></path>`,
        download: `<path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path>`,
        refresh: `<path d="M20 7v5h-5"></path><path d="M4 17v-5h5"></path><path d="M6.1 9A7 7 0 0 1 18 6l2 2"></path><path d="M17.9 15A7 7 0 0 1 6 18l-2-2"></path>`,
        delete: `<path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m6 7 1 14h10l1-14"></path><path d="M10 11v6M14 11v6"></path>`
    };
    return `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${icons[kind]}</svg>`;
}

async function openProjectFile(fileId, page = null) {
    const file = projectFiles.find(item => item.id === fileId);
    if (!file?.download_url) return false;

    const link = document.createElement("a");
    link.href = file.download_url;
    link.download = file.display_name || file.filename || "document";
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
    return true;

    /* Legacy preview implementation retained below for migration safety.
       The file library now deliberately downloads originals on click. */
    if (!filePreviewPane) return false;
    activeProjectFileId = fileId;
    renderFileLibrary();
    filePreviewPane.classList.add("open");
    filePreviewPane.replaceChildren();

    const topbar = document.createElement("div");
    topbar.className = "file-preview-topbar";
    const back = document.createElement("button");
    back.type = "button";
    back.className = "file-preview-back";
    back.title = "Revenir aux fichiers";
    back.innerHTML = fileActionIcon("back");
    back.addEventListener("click", closeFilePreview);
    const title = document.createElement("span");
    title.className = "file-preview-title";
    const name = document.createElement("strong");
    name.textContent = file.display_name || file.filename;
    const detail = document.createElement("small");
    detail.textContent = file.metadata?.legacy_index
        ? `${(FILE_KIND_META[file.kind] || FILE_KIND_META.text).label} · index historique sans original`
        : `${(FILE_KIND_META[file.kind] || FILE_KIND_META.text).label} · ${formatProjectFileSize(file.size_bytes)}`;
    title.append(name, detail);
    const actions = document.createElement("span");
    actions.className = "file-preview-actions";
    const download = document.createElement("a");
    download.href = file.download_url;
    download.title = "Télécharger l’original";
    download.setAttribute("download", "");
    download.innerHTML = fileActionIcon("download");
    const reindex = document.createElement("button");
    reindex.type = "button";
    reindex.title = "Reconstruire l’index documentaire";
    reindex.innerHTML = fileActionIcon("refresh");
    reindex.addEventListener("click", async () => {
        reindex.disabled = true;
        if (fileLibraryStatus) {
            fileLibraryStatus.classList.remove("error");
            fileLibraryStatus.textContent = `Réindexation de ${file.display_name || file.filename}…`;
        }
        const response = await fetch(
            `${API_BASE}/files/${encodeURIComponent(file.id)}/reindex`,
            { method: "POST" }
        );
        const payload = await response.json();
        if (!response.ok && fileLibraryStatus) {
            fileLibraryStatus.classList.add("error");
            fileLibraryStatus.textContent = payload.detail || "Réindexation impossible.";
        }
        await loadProjectDocuments();
        reindex.disabled = false;
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.title = "Supprimer le fichier";
    remove.innerHTML = fileActionIcon("delete");
    remove.addEventListener("click", async () => {
        if (!window.confirm(`Supprimer « ${file.display_name || file.filename} » du projet ?`)) return;
        const response = await fetch(`${API_BASE}/files/${encodeURIComponent(file.id)}`, {
            method: "DELETE"
        });
        if (!response.ok) {
            if (fileLibraryStatus) {
                fileLibraryStatus.textContent = "Suppression impossible.";
                fileLibraryStatus.classList.add("error");
            }
            return;
        }
        selectedProjectFileIds.delete(file.id);
        closeFilePreview();
        await loadProjectDocuments();
    });
    if (!file.metadata?.legacy_index) actions.append(reindex);
    if (file.download_url) actions.append(download);
    actions.append(remove);
    topbar.append(back, title, actions);

    const content = document.createElement("div");
    content.className = "file-preview-content";
    const loading = document.createElement("div");
    loading.className = "file-preview-empty";
    loading.textContent = "Préparation de l’aperçu…";
    content.appendChild(loading);
    filePreviewPane.append(topbar, content);

    try {
        const response = await fetch(`${API_BASE}/files/${encodeURIComponent(file.id)}/preview`);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Aperçu indisponible");
        content.replaceChildren();
        if (payload.mode === "pdf") {
            const frame = document.createElement("iframe");
            frame.title = `Aperçu de ${file.display_name || file.filename}`;
            frame.setAttribute("sandbox", "");
            frame.referrerPolicy = "no-referrer";
            frame.src = `${payload.url}${page ? `#page=${Math.max(1, Number(page) || 1)}` : ""}`;
            content.appendChild(frame);
        } else if (payload.mode === "image") {
            const stack = document.createElement("div");
            stack.className = "file-image-preview-stack";
            const image = document.createElement("img");
            image.src = payload.url;
            image.alt = file.display_name || file.filename;
            stack.appendChild(image);
            const visualAnalysis = String(
                payload.file?.metadata?.visual_analysis
                || file.metadata?.visual_analysis
                || ""
            ).trim();
            if (visualAnalysis) {
                const analysis = document.createElement("section");
                analysis.className = "file-vision-analysis";
                const heading = document.createElement("h3");
                heading.textContent = "Lecture par Lasme Vision";
                const body = document.createElement("pre");
                body.textContent = visualAnalysis;
                analysis.append(heading, body);
                stack.appendChild(analysis);
            }
            content.appendChild(stack);
        } else {
            const sections = document.createElement("div");
            sections.className = "file-preview-sections";
            (payload.sections || []).forEach((section, index) => {
                const block = document.createElement("section");
                block.className = "file-preview-section";
                const heading = document.createElement("h3");
                heading.textContent = section.title || `Section ${index + 1}`;
                const body = document.createElement("pre");
                body.textContent = section.text || section.content || "";
                block.append(heading, body);
                sections.appendChild(block);
            });
            if (!sections.children.length) {
                sections.textContent = "Ce fichier ne contient aucun texte prévisualisable.";
            }
            content.appendChild(sections);
        }
    } catch (error) {
        content.replaceChildren();
        const unavailable = document.createElement("div");
        unavailable.className = "file-preview-empty";
        unavailable.textContent = error.message || "Aperçu indisponible.";
        content.appendChild(unavailable);
    }
}

async function uploadProjectFiles(files) {
    const queue = Array.from(files || []).filter(Boolean);
    if (!queue.length) return;
    if (fileLibraryStatus) {
        fileLibraryStatus.classList.remove("error");
        fileLibraryStatus.textContent = `Ajout de ${queue.length} fichier${queue.length > 1 ? "s" : ""}…`;
    }

    let completed = 0;
    const uploadOne = async file => {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("scope_id", currentProjectId);
        const response = await fetch(`${API_BASE}/documents/upload`, {
            method: "POST",
            body: formData
        });
        const payload = await response.json();
        if (!response.ok) {
            const detail = typeof payload.detail === "object"
                ? payload.detail.message
                : payload.detail;
            throw new Error(detail || `Échec de ${file.name}`);
        }
        completed += 1;
        if (fileLibraryStatus) {
            fileLibraryStatus.textContent = `${completed}/${queue.length} ajouté${completed > 1 ? "s" : ""} · préparation en arrière-plan`;
        }
        return payload.file;
    };

    const outcomes = await Promise.allSettled(queue.map(uploadOne));
    const failures = outcomes
        .map((result, index) => ({ result, file: queue[index] }))
        .filter(item => item.result.status === "rejected");

    if (fileLibraryStatus) {
        fileLibraryStatus.classList.toggle("error", failures.length > 0);
        fileLibraryStatus.textContent = failures.length
            ? `${queue.length - failures.length} ajouté${queue.length - failures.length > 1 ? "s" : ""} · ${failures.length} échec${failures.length > 1 ? "s" : ""} (${failures.map(item => item.file.name).join(", ")})`
            : `${queue.length} fichier${queue.length > 1 ? "s ajoutés" : " ajouté"} · préparation en arrière-plan`;
    }
    if (projectFileUploadInput) projectFileUploadInput.value = "";
    await loadProjectDocuments();
    if (projectFiles.some(item => item.status === "indexing")) {
        startProjectFilePolling();
    }
}

projectFilesBtn?.addEventListener("click", openFileLibrary);
fileLibraryCloseBtn?.addEventListener("click", closeFileLibrary);
fileLibraryOverlay?.addEventListener("click", closeFileLibrary);
fileLibraryUploadBtn?.addEventListener("click", () => projectFileUploadInput?.click());
projectFileUploadInput?.addEventListener("change", () => {
    void uploadProjectFiles(projectFileUploadInput.files);
});
fileLibrarySearchInput?.addEventListener("input", renderFileLibrary);
fileLibraryKindFilter?.addEventListener("change", renderFileLibrary);
fileLibraryDropzone?.addEventListener("click", () => projectFileUploadInput?.click());
["dragenter", "dragover"].forEach(eventName => {
    fileLibraryDropzone?.addEventListener(eventName, event => {
        event.preventDefault();
        fileLibraryDropzone.classList.add("dragging");
    });
});
["dragleave", "drop"].forEach(eventName => {
    fileLibraryDropzone?.addEventListener(eventName, event => {
        event.preventDefault();
        fileLibraryDropzone.classList.remove("dragging");
    });
});
fileLibraryDropzone?.addEventListener("drop", event => {
    void uploadProjectFiles(event.dataTransfer?.files);
});

window.LasmeWorkspace = {
    ...(window.LasmeWorkspace || {}),
    getSelectedFileIds: () => Array.from(selectedProjectFileIds),
    refreshProjectSessionCounts,
    resetDocumentSelection: async () => {
        stopProjectFilePolling();
        selectedProjectFileIds.clear();
        activeProjectFileId = null;
        await loadProjectDocuments();
    },
    openFile: (fileId, page = null) => {
        if (!projectFiles.some(item => item.id === fileId)) return false;
        void openProjectFile(fileId, page);
        return true;
    },
    openFileByName: (filename, page = null) => {
        const normalized = String(filename || "").trim().toLocaleLowerCase();
        const file = projectFiles.find(item => {
            const displayName = String(item.display_name || "")
                .trim()
                .toLocaleLowerCase();
            const originalName = String(item.filename || "")
                .trim()
                .toLocaleLowerCase();
            return displayName === normalized || originalName === normalized;
        });
        if (!file) return false;
        void openProjectFile(file.id, page);
        return true;
    }
};

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
    research: "Rapport documenté avec résultats et sources",
    html: "Page HTML autonome, prévisualisée dans un espace isolé",
    interactive: "Mini-application HTML/CSS/JavaScript interactive et isolée",
    diagram: "Diagramme Mermaid : flux, séquence, architecture ou chronologie",
    mindmap: "Carte mentale Mermaid structurée par niveaux",
    chart: "Graphique Mermaid xychart ou diagramme de données",
    presentation: "Trame de présentation exportable vers PowerPoint"
};

function detectCanvasKind(content) {
    const source = String(content || "").trim();
    if (!source) return "document";
    if (/^```(?:html)\s*\n/i.test(source) || /<!doctype html|<html[\s>]/i.test(source)) {
        return "html";
    }
    const mermaidBlock = source.match(/```mermaid\s*\n([\s\S]*?)```/i);
    if (mermaidBlock) {
        const body = mermaidBlock[1].trim();
        if (/^mindmap\b/i.test(body)) return "mindmap";
        if (/^xychart-beta\b/i.test(body)) return "chart";
        return "diagram";
    }

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
            const mathDelimiters = [
                { left: "\\[", right: "\\]", display: true },
                { left: "$$", right: "$$", display: true },
                { left: "\\(", right: "\\)", display: false }
            ];
            // Boucle jusqu'à stabilité : le premier pass peut laisser des
            // fragments de formules (même raison que dans app.js).
            for (let mathPass = 0; mathPass < 3; mathPass++) {
                const before = canvasPreview.querySelectorAll(".katex").length;
                renderMathInElement(canvasPreview, {
                    delimiters: mathDelimiters,
                    throwOnError: false,
                    errorColor: "#6B7280",
                    strict: false,
                    trust: false,
                    // Copie mutable OBLIGATOIRE : KaTeX ajoute des macros internes (\cr pour
        // les \ des matrices) ; l'objet gelé de math-renderer ferait throw
        // « Cannot add property » et avorterait tout le pass de rendu.
                macros: { ...(window.LasmeMath ? window.LasmeMath.KATEX_MACROS : {}) },
                    ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"]
                });
                if (canvasPreview.querySelectorAll(".katex").length === before) break;
            }
        } catch (error) {
            console.warn("Impossible d’afficher une formule du Canvas :", error);
        }
    }
    canvasPreview.querySelectorAll("pre code").forEach(block => {
        if (window.hljs) window.hljs.highlightElement(block);
    });
}

function canvasHtmlDocument(source) {
    const value = String(source || "");
    const policy = [
        "default-src 'none'",
        "img-src data: blob:",
        "font-src data:",
        "style-src 'unsafe-inline'",
        "script-src 'unsafe-inline'",
        "connect-src 'none'",
        "media-src data: blob:",
        "frame-src 'none'",
        "form-action 'none'",
        "base-uri 'none'"
    ].join("; ");
    const meta = `<meta http-equiv="Content-Security-Policy" content="${policy}">`;
    if (/<head[\s>]/i.test(value)) {
        return value.replace(/<head([^>]*)>/i, `<head$1>${meta}`);
    }
    if (/<html[\s>]/i.test(value)) {
        return value.replace(/<html([^>]*)>/i, `<html$1><head>${meta}</head>`);
    }
    return `<!doctype html><html lang="fr"><head>${meta}<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{min-height:100%;margin:0;font-family:system-ui,sans-serif}</style></head><body>${value}</body></html>`;
}

let canvasPreviewTimer = null;
let canvasPreviewRequestId = 0;

function renderCanvasHtmlPreview(source) {
    canvasPreview.replaceChildren();
    const frame = document.createElement("iframe");
    frame.className = "canvas-html-preview";
    frame.title = "Aperçu isolé de l’artefact HTML";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("referrerpolicy", "no-referrer");
    const fenced = String(source || "").trim().match(
        /^```html\s*\n([\s\S]*?)```\s*$/i
    );
    const documentSource = canvasHtmlDocument(fenced ? fenced[1] : source);
    canvasPreview.appendChild(frame);
    const loading = document.createElement("div");
    loading.className = "canvas-preview-loading";
    loading.textContent = "Préparation de l’aperçu sécurisé…";
    canvasPreview.appendChild(loading);

    const requestId = ++canvasPreviewRequestId;
    clearTimeout(canvasPreviewTimer);
    canvasPreviewTimer = setTimeout(async () => {
        try {
            const response = await fetch(`${API_BASE}/artifact-previews`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: documentSource })
            });
            if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try {
                    const errorPayload = await response.json();
                    detail = errorPayload.detail || detail;
                } catch (_) {
                    // Keep the HTTP status when the response is not JSON.
                }
                throw new Error(detail);
            }
            const payload = await response.json();
            if (requestId !== canvasPreviewRequestId || !frame.isConnected) return;
            frame.addEventListener("load", () => loading.remove(), { once: true });
            frame.src = payload.url;
        } catch (error) {
            if (requestId !== canvasPreviewRequestId || !frame.isConnected) return;
            frame.remove();
            loading.classList.add("is-error");
            loading.textContent = error?.message || "Aperçu HTML indisponible.";
        }
    }, 180);
}

function renderCanvasDiagramPreview(source) {
    canvasPreview.replaceChildren();
    const diagram = document.createElement("div");
    diagram.className = "canvas-mermaid-preview mermaid";
    const fenced = String(source || "").trim().match(
        /```(?:mermaid)?\s*\n([\s\S]*?)```/i
    );
    diagram.textContent = fenced ? fenced[1] : source;
    canvasPreview.appendChild(diagram);
    if (typeof mermaid !== "undefined") {
        try {
            Promise.resolve(mermaid.run({ nodes: [diagram] })).catch(() => {
                diagram.classList.add("render-error");
            });
        } catch (_) {
            diagram.classList.add("render-error");
        }
    }
}

function renderCanvasPreview() {
    if (!canvasPreview || !canvasEditor) return;
    const source = canvasEditor.value;
    updateCanvasKindHint();
    const fencedLanguage = source.trim().match(/^```([A-Za-z0-9_+#.-]+)/)?.[1]?.toLowerCase() || "";
    if (canvasRunBtn) {
        canvasRunBtn.hidden = !(
            canvasKindSelect?.value === "code"
            && (!fencedLanguage || ["py", "python"].includes(fencedLanguage))
        );
    }
    if (!source.trim()) {
        canvasPreviewRequestId += 1;
        clearTimeout(canvasPreviewTimer);
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
    if (["html", "interactive"].includes(canvasKindSelect?.value)) {
        renderCanvasHtmlPreview(source);
        return;
    }
    if (["diagram", "mindmap", "chart"].includes(canvasKindSelect?.value)) {
        renderCanvasDiagramPreview(source);
        return;
    }
    renderCanvasDocumentPreview(source);
}

function clearCanvasRunResult() {
    if (!canvasRunResult) return;
    canvasRunResult.hidden = true;
    canvasRunResult.replaceChildren();
}

canvasEditor?.addEventListener("input", () => {
    clearCanvasRunResult();
    renderCanvasPreview();
});
canvasKindSelect?.addEventListener("change", () => {
    clearCanvasRunResult();
    renderCanvasPreview();
});

function extractCanvasPythonCode(source) {
    const fenced = String(source || "").trim().match(
        /^```(?:py|python)?\s*\n([\s\S]*?)```\s*$/i
    );
    return fenced ? fenced[1] : String(source || "");
}

function renderCanvasRunResult(result) {
    if (!canvasRunResult) return;
    canvasRunResult.hidden = false;
    canvasRunResult.replaceChildren();
    const header = document.createElement("header");
    const label = document.createElement("strong");
    label.textContent = result.status === "success"
        ? "Exécution réussie"
        : (result.status === "timeout" ? "Temps limite atteint" : "Erreur d’exécution");
    const timing = document.createElement("span");
    timing.textContent = `${Math.round(Number(result.duration_ms) || 0)} ms · Docker isolé`;
    header.append(label, timing);
    canvasRunResult.appendChild(header);
    if (result.stdout) {
        const output = document.createElement("pre");
        output.className = "canvas-run-stdout";
        output.textContent = result.stdout;
        canvasRunResult.appendChild(output);
    }
    if (result.stderr) {
        const error = document.createElement("pre");
        error.className = "canvas-run-stderr";
        error.textContent = result.stderr;
        canvasRunResult.appendChild(error);
    }
    if (Array.isArray(result.files) && result.files.length) {
        const files = document.createElement("div");
        files.className = "canvas-run-files";
        result.files.forEach(file => {
            const link = document.createElement("a");
            link.href = file.url;
            link.target = "_blank";
            link.rel = "noopener";
            link.textContent = `${file.name} · ${formatProjectFileSize(file.size_bytes)}`;
            if (/\.(png|jpe?g|webp|svg)$/i.test(file.name)) {
                const image = document.createElement("img");
                image.src = file.url;
                image.alt = file.name;
                link.prepend(image);
            }
            files.appendChild(link);
        });
        canvasRunResult.appendChild(files);
    }
}

canvasRunBtn?.addEventListener("click", async () => {
    const code = extractCanvasPythonCode(canvasEditor?.value || "");
    if (!code.trim()) return;
    canvasRunBtn.disabled = true;
    canvasRunBtn.classList.add("running");
    canvasRunResult.hidden = false;
    canvasRunResult.textContent = "Exécution isolée en cours…";
    try {
        const response = await fetch(`${API_BASE}/runner/python`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code, timeout_seconds: 15 })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Runner indisponible");
        renderCanvasRunResult(payload.result);
    } catch (error) {
        canvasRunResult.replaceChildren();
        const message = document.createElement("div");
        message.className = "canvas-run-error";
        message.textContent = error.message || "Exécution impossible.";
        canvasRunResult.appendChild(message);
    } finally {
        canvasRunBtn.disabled = false;
        canvasRunBtn.classList.remove("running");
    }
});

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
    clearCanvasRunResult();
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
    const requestedFormat = canvasExportFormatSelect?.value || "";
    if (
        ["diagram", "mindmap", "chart"].includes(activeCanvasArtifact.kind)
        && (!requestedFormat || requestedFormat === "svg")
    ) {
        const svg = canvasPreview?.querySelector("svg");
        if (!svg) {
            canvasStatus.textContent = "Le diagramme doit être affiché avant l’export SVG.";
            return;
        }
        const source = new XMLSerializer().serializeToString(svg);
        const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${(activeCanvasArtifact.title || "diagramme")
            .replace(/[^\p{L}\p{N}_-]+/gu, "-")
            .replace(/^-+|-+$/g, "") || "diagramme"}.svg`;
        anchor.click();
        URL.revokeObjectURL(url);
        return;
    }
    const query = requestedFormat
        ? `?format=${encodeURIComponent(requestedFormat)}`
        : "";
    const response = await fetch(
        `${API_BASE}/artifacts/${encodeURIComponent(activeCanvasArtifact.id)}/export${query}`
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
        model: inputModelSelect?.value || "muse-glimmer:30b-q4_K_M-dflash"
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
                <small>La réponse sera régénérée dans cette conversation.</small>
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
        status.textContent = "Mise à jour en cours…";
        try {
            if (!currentSessionId || !messageId) {
                throw new Error("Impossible de modifier ce message.");
            }
            const response = await fetch(
                `${API_BASE}/sessions/${encodeURIComponent(currentSessionId)}/messages/${encodeURIComponent(messageId)}/edit`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ content: replacement })
                }
            );
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "Édition impossible.");

            // The turn is now the last one: update the bubble in place...
            textContent.textContent = replacement;
            editor.remove();
            textContent.style.display = "";
            decorateMessageActions(messageElement, "user", messageId, replacement);

            // ...drop every rendered message that followed it...
            let following = messageElement.nextElementSibling;
            while (following) {
                const next = following.nextElementSibling;
                if (following.classList.contains("message")) following.remove();
                following = next;
            }

            // ...and align the in-memory history with the truncated session.
            if (Array.isArray(conversationHistory)) {
                let lastUserIndex = -1;
                for (let i = conversationHistory.length - 1; i >= 0; i -= 1) {
                    if (conversationHistory[i]?.role === "user") {
                        lastUserIndex = i;
                        break;
                    }
                }
                if (lastUserIndex >= 0) {
                    conversationHistory.length = lastUserIndex + 1;
                    conversationHistory[lastUserIndex] = { role: "user", content: replacement };
                }
            }

            await sendChatMessage({ replayExistingLastUser: true });
        } catch (error) {
            submitButton.disabled = false;
            textarea.disabled = false;
            status.textContent = error.message || "Impossible de modifier.";
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
